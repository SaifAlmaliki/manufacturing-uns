"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and is distributed "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Reading and writing the console's Connectivity catalog.

The seam for schema `console`, kept apart from `AssetModelRepository` because a
Connectivity server is not part of the Asset Model: the model says what exists,
a server says where to read it from. They share a database and nothing else.

The catalog is shared with the OPC-UA bridge (`10_uns_opcua`), which reads it to
know which servers to dial and which nodes to subscribe to, and which writes
`record_test` results back. The console writes everything else.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from uns_model.engine import Database
import re

from uns_model.tables import (
    CONNECTIVITY_AUTH_MODES,
    CONNECTIVITY_PROTOCOLS,
    CONNECTIVITY_SECURITY_MODES,
    CONNECTIVITY_SECURITY_POLICIES,
    ConnectivityServer,
    ConnectivityTag,
)

_ENDPOINT = re.compile(r"^opc\.tcp://[^\s/:]+:\d{1,5}(/.*)?$")

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectivityServerSpec:
    """
    One OPC-UA server as the console authors it.

    A value object rather than a bag of keyword arguments: the console edits a
    whole server at a time, and a partial update of an endpoint is not a thing
    anybody should be able to express by accident.
    """

    id: str
    name: str
    protocol: str
    endpoint: str
    auth_mode: str = "anonymous"
    security_policy: str = "None"
    security_mode: str = "None"
    username: str = ""
    password: str = ""
    certificate: str = ""
    private_key: str = ""
    server_certificate: str = ""

    def validate(self) -> None:
        """Reject what the vocabularies do not allow, before Postgres does."""
        if not self.id:
            raise ValueError("A Connectivity server needs an id")
        if not self.name:
            raise ValueError(f"Connectivity server {self.id!r} needs a name")
        if not self.endpoint:
            raise ValueError(f"Connectivity server {self.id!r} needs an endpoint")
        if not _ENDPOINT.match(self.endpoint):
            raise ValueError("Endpoint must be opc.tcp://host:port")
        _require_one_of("protocol", self.protocol, CONNECTIVITY_PROTOCOLS)
        _require_one_of("auth_mode", self.auth_mode, CONNECTIVITY_AUTH_MODES)
        _require_one_of("security_policy", self.security_policy, CONNECTIVITY_SECURITY_POLICIES)
        _require_one_of("security_mode", self.security_mode, CONNECTIVITY_SECURITY_MODES)
        if self.security_policy == "None" and self.security_mode != "None":
            raise ValueError("Security mode must be None when the policy is None")
        if self.security_policy != "None" and self.security_mode == "None":
            raise ValueError("Choose Sign or SignAndEncrypt when a security policy is set")
        if self.security_policy != "None" and (not self.certificate or not self.private_key):
            raise ValueError("Certificate and private key paths are required for a secured channel")
        if self.auth_mode == "username" and (not self.username or not self.password):
            raise ValueError("Username and password are required")
        if self.auth_mode == "x509":
            if not self.certificate or not self.private_key:
                raise ValueError("Certificate and private key paths are required for X509 authentication")
            if self.security_policy == "None":
                raise ValueError("X509 authentication needs a security policy other than None")

    def column_values(self) -> dict[str, Any]:
        """The spec as column values."""
        return {column.name: getattr(self, column.name) for column in fields(self)}


@dataclass(slots=True)
class ConnectivityTagSpec:
    """
    One OPC-UA node the console subscribes to.

    `mqtt_topic` is engineer-edited: a re-discovery must not overwrite it. The
    repository keeps it via `merge_discovered`, which is the one decision with
    its own unit test.
    """

    node_id: str
    browse_path: str
    display_name: str
    mqtt_topic: str
    subscribed: bool = True

    def validate(self) -> None:
        if not self.node_id:
            raise ValueError("A Connectivity tag needs a node_id")


def _require_one_of(what: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {list(allowed)}, got {value!r}")


def merge_discovered(
    existing: Sequence[ConnectivityTagSpec],
    discovered: Sequence[ConnectivityTagSpec],
) -> list[ConnectivityTagSpec]:
    """
    Fold a freshly discovered set of tags into the existing ones.

    Rules (per the task brief):
    - Existing nodes keep their `mqtt_topic`: an engineer's edit survives a
      re-discovery.
    - Existing nodes are updated with the discovered `browse_path` and
      `display_name`, because the server is the source of truth for those.
    - Existing nodes keep `subscribed=True` even when absent from this
      discovery: unsubscribe is a deliberate act (`unsubscribe_tag`), not an
      omission.
    - New nodes are added with `subscribed=True` and the discovered topic.
    """
    by_node: dict[str, ConnectivityTagSpec] = {tag.node_id: tag for tag in existing}
    for tag in discovered:
        if tag.node_id in by_node:
            kept = by_node[tag.node_id]
            by_node[tag.node_id] = ConnectivityTagSpec(
                node_id=tag.node_id,
                browse_path=tag.browse_path,
                display_name=tag.display_name,
                mqtt_topic=kept.mqtt_topic,
                subscribed=True,
            )
        else:
            by_node[tag.node_id] = ConnectivityTagSpec(
                node_id=tag.node_id,
                browse_path=tag.browse_path,
                display_name=tag.display_name,
                mqtt_topic=tag.mqtt_topic,
                subscribed=True,
            )
    return list(by_node.values())


class ConnectivityRepository:
    """
    The console's Connectivity catalog.

    Callers get whole servers and tags and never a `Session`. Every server
    write is an upsert by id, so the console can save a server it has just
    edited without knowing whether the server has seen it before.

    `replace_subscribed_tags` is the discovery path: it folds a freshly
    discovered set of tags into the existing ones via `merge_discovered`, so
    an engineer's edited `mqtt_topic` survives. It does **not** unsubscribe
    nodes that are missing from the discovery: that is a deliberate act via
    `unsubscribe_tag`.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ------------------------------------------------------------------ writes

    async def save_server(self, spec: ConnectivityServerSpec) -> ConnectivityServer:
        """Create or replace one OPC-UA server."""
        spec.validate()
        if not spec.password:
            existing = await self._server_by_id(spec.id)
            if existing is not None and existing.password:
                spec.password = existing.password
        values = spec.column_values()
        async with self._database.session() as session:
            statement = (
                insert(ConnectivityServer)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[ConnectivityServer.id],
                    set_={key: value for key, value in values.items() if key != "id"}
                    | {"updated_at": func.now()},
                )
            )
            await session.execute(statement)
            return (
                await session.execute(select(ConnectivityServer).where(ConnectivityServer.id == spec.id))
            ).scalar_one()

    async def _server_by_id(self, server_id: str) -> ConnectivityServer | None:
        async with self._database.session() as session:
            return (
                await session.execute(select(ConnectivityServer).where(ConnectivityServer.id == server_id))
            ).scalar_one_or_none()

    async def delete_server(self, server_id: str) -> bool:
        """Delete a server and its tags (cascade). False when there was nothing to delete."""
        async with self._database.session() as session:
            result = await session.execute(
                delete(ConnectivityServer).where(ConnectivityServer.id == server_id)
            )
            return bool(result.rowcount)

    async def replace_subscribed_tags(
        self, server_id: str, tags: Sequence[ConnectivityTagSpec]
    ) -> list[ConnectivityTag]:
        """
        Fold a freshly discovered set of tags into the catalog for one server.

        Existing tags keep their `mqtt_topic` and their `subscribed` flag (the
        latter only ever goes True here; missing nodes stay subscribed until
        `unsubscribe_tag`). New tags are inserted with `subscribed=True`.
        """
        existing_specs = [
            ConnectivityTagSpec(
                node_id=row.node_id,
                browse_path=row.browse_path,
                display_name=row.display_name,
                mqtt_topic=row.mqtt_topic,
                subscribed=row.subscribed,
            )
            for row in await self.list_subscribed_tags(server_id)
        ]
        merged = merge_discovered(existing_specs, tags)
        async with self._database.session() as session:
            for tag in merged:
                values: dict[str, Any] = {
                    "server_id": server_id,
                    "node_id": tag.node_id,
                    "browse_path": tag.browse_path,
                    "display_name": tag.display_name,
                    "mqtt_topic": tag.mqtt_topic,
                    "subscribed": tag.subscribed,
                }
                # Only set mqtt_topic on INSERT, never on UPDATE: an engineer's
                # edit must survive a re-discovery. The CHECK-free column is the
                # one place a discovery must not clobber.
                on_conflict_set = {
                    "browse_path": tag.browse_path,
                    "display_name": tag.display_name,
                    "subscribed": tag.subscribed,
                    "updated_at": func.now(),
                }
                await session.execute(
                    insert(ConnectivityTag)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[ConnectivityTag.server_id, ConnectivityTag.node_id],
                        set_=on_conflict_set,
                    )
                )
            return await self.list_subscribed_tags(server_id)

    async def update_tag_topic(self, server_id: str, node_id: str, mqtt_topic: str) -> ConnectivityTag | None:
        """Set the MQTT topic an engineer wants this node republished under."""
        async with self._database.session() as session:
            await session.execute(
                update(ConnectivityTag)
                .where(ConnectivityTag.server_id == server_id, ConnectivityTag.node_id == node_id)
                .values(mqtt_topic=mqtt_topic, updated_at=func.now())
            )
            return (
                await session.execute(
                    select(ConnectivityTag).where(
                        ConnectivityTag.server_id == server_id,
                        ConnectivityTag.node_id == node_id,
                    )
                )
            ).scalar_one_or_none()

    async def unsubscribe_tag(self, server_id: str, node_id: str) -> ConnectivityTag | None:
        """Stop subscribing to a node. A deliberate act, never done by omission."""
        async with self._database.session() as session:
            await session.execute(
                update(ConnectivityTag)
                .where(ConnectivityTag.server_id == server_id, ConnectivityTag.node_id == node_id)
                .values(subscribed=False, updated_at=func.now())
            )
            return (
                await session.execute(
                    select(ConnectivityTag).where(
                        ConnectivityTag.server_id == server_id,
                        ConnectivityTag.node_id == node_id,
                    )
                )
            ).scalar_one_or_none()

    async def record_test(
        self, server_id: str, *, ok: bool, error: str | None = None
    ) -> ConnectivityServer | None:
        """
        Remember the outcome of a connection test, timestamped by the server.

        The OPC-UA bridge calls this after dialing a server. Timestamps come
        from the database rather than the caller: a wrong laptop clock must
        not be able to reorder the connection history.
        """
        status = "connected" if ok else "failed"
        values: dict[str, Any] = {
            "last_status": status,
            "last_error": error or "",
            "last_tested_at": func.now(),
            "updated_at": func.now(),
        }
        async with self._database.session() as session:
            await session.execute(
                update(ConnectivityServer).where(ConnectivityServer.id == server_id).values(**values)
            )
            return (
                await session.execute(
                    select(ConnectivityServer).where(ConnectivityServer.id == server_id)
                )
            ).scalar_one_or_none()

    # ------------------------------------------------------------------- reads

    async def list_servers(self, *, protocol: str | None = None) -> list[ConnectivityServer]:
        """Every server, newest edit last, so the console renders a stable order."""
        statement = select(ConnectivityServer).order_by(
            ConnectivityServer.created_at, ConnectivityServer.id
        )
        if protocol is not None:
            statement = statement.where(ConnectivityServer.protocol == protocol)
        async with self._database.session() as session:
            return list((await session.execute(statement)).scalars())

    async def list_subscribed_tags(self, server_id: str) -> list[ConnectivityTag]:
        """Every tag for one server, in node_id order. Used by the bridge and by discovery."""
        statement = (
            select(ConnectivityTag)
            .where(ConnectivityTag.server_id == server_id)
            .order_by(ConnectivityTag.node_id)
        )
        async with self._database.session() as session:
            return list((await session.execute(statement)).scalars())

    async def catalog_updated_at(self) -> datetime | None:
        """The latest `updated_at` across servers and tags, for a console deciding whether to refetch."""
        async with self._database.session() as session:
            server_at = (
                await session.execute(select(func.max(ConnectivityServer.updated_at)))
            ).scalar_one_or_none()
            tag_at = (
                await session.execute(select(func.max(ConnectivityTag.updated_at)))
            ).scalar_one_or_none()
        candidates = [v for v in (server_at, tag_at) if v is not None]
        return max(candidates) if candidates else None


__all__ = [
    "ConnectivityRepository",
    "ConnectivityServerSpec",
    "ConnectivityTagSpec",
    "merge_discovered",
]
