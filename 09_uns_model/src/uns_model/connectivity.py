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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from uns_config.hivemq_edge_xml import EdgeAdapterInput, EdgeTagInput
from uns_model.engine import Database
import re

from uns_model.repositories import AssetModelRepository
from uns_model.tables import (
    CONNECTIVITY_AUTH_MODES,
    CONNECTIVITY_PROTOCOLS,
    CONNECTIVITY_SECURITY_MODES,
    CONNECTIVITY_SECURITY_POLICIES,
    PLC_PROTOCOLS,
    S7_CONTROLLER_TYPES,
    Asset,
    ConnectivityServer,
    ConnectivityTag,
    SignalLabel,
    UnitOfMeasure,
)

_ENDPOINT = re.compile(r"^opc\.tcp://[^\s/:]+:\d{1,5}(/.*)?$")
_HOST_PORT = re.compile(r"^([A-Za-z0-9.-]+):(\d{1,5})$")

EDGE_APPLY_ERROR = "Recreate uns_mqtt_broker to apply Edge config"

LOGGER = logging.getLogger(__name__)


def parse_host_port(endpoint: str) -> tuple[str, int]:
    match = _HOST_PORT.fullmatch((endpoint or "").strip())
    if not match:
        raise ValueError("Endpoint must be host:port")
    port = int(match.group(2))
    if port < 1 or port > 65535:
        raise ValueError("port must be 1–65535")
    return match.group(1), port


def edge_adapters_from_rows(servers: Sequence[ConnectivityServer]) -> list[EdgeAdapterInput]:
    """
    Map catalog rows to what `uns_config.hivemq_edge_xml` needs to splice HiveMQ Edge.

    Only PLC rows (S7, EtherNet/IP) become adapters: OPC UA is not a HiveMQ Edge
    protocol adapter, the OPC-UA bridge (`10_uns_opcua`) still owns those. Only
    subscribed tags are republished, same rule as everywhere else in this module.
    """
    adapters: list[EdgeAdapterInput] = []
    for server in servers:
        if getattr(server, "protocol", None) not in PLC_PROTOCOLS:
            continue
        host, port = parse_host_port(server.endpoint)
        controller = (getattr(server, "protocol_config", None) or {}).get("controllerType", "S7_1500")
        tags = tuple(
            EdgeTagInput(tag.node_id, tag.display_name, tag.mqtt_topic, getattr(tag, "data_type", None))
            for tag in getattr(server, "tags", [])
            if tag.subscribed
        )
        adapters.append(
            EdgeAdapterInput(
                server_id=server.id,
                protocol=server.protocol,
                host=host,
                port=port,
                controller_type=controller,
                tags=tags,
            )
        )
    return adapters


def assert_unique_mqtt_topic(existing: set[str], topic: str, *, node_id: str) -> None:
    """
    Reject a tag write that would republish another node under the same topic.

    Two subscribed nodes sharing an `mqtt_topic` would make one of them
    unrecoverable at the consumer end, so this must run before any write
    reaches Postgres. A blank topic is not yet assigned and cannot collide.
    """
    if topic and topic in existing:
        raise ValueError(
            f"mqtt_topic {topic!r} is already subscribed by another tag; node {node_id!r} needs a distinct one"
        )


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
    protocol_config: dict[str, Any] | None = None

    def validate(self) -> None:
        """Reject what the vocabularies do not allow, before Postgres does."""
        if not self.id:
            raise ValueError("A Connectivity server needs an id")
        if not self.name:
            raise ValueError(f"Connectivity server {self.id!r} needs a name")
        if not self.endpoint:
            raise ValueError(f"Connectivity server {self.id!r} needs an endpoint")
        if self.protocol in PLC_PROTOCOLS:
            parse_host_port(self.endpoint)
            if self.protocol == "s7":
                controller = (self.protocol_config or {}).get("controllerType", "S7_1500")
                _require_one_of("controllerType", controller, S7_CONTROLLER_TYPES)
        else:
            if not _ENDPOINT.match(self.endpoint):
                raise ValueError("Endpoint must be opc.tcp://host:port")
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
        _require_one_of("protocol", self.protocol, CONNECTIVITY_PROTOCOLS)
        _require_one_of("auth_mode", self.auth_mode, CONNECTIVITY_AUTH_MODES)
        _require_one_of("security_policy", self.security_policy, CONNECTIVITY_SECURITY_POLICIES)
        _require_one_of("security_mode", self.security_mode, CONNECTIVITY_SECURITY_MODES)

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


def metric_key_for_tag(
    *, asset_path: str, mqtt_topic: str, browse_path: str, display_name: str
) -> str:
    prefix = asset_path.rstrip("/") + "/"
    if mqtt_topic.startswith(prefix):
        return mqtt_topic[len(prefix):]
    if mqtt_topic == asset_path:
        return display_name or browse_path or mqtt_topic
    return browse_path or display_name or mqtt_topic


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

    async def save_server(
        self,
        spec: ConnectivityServerSpec,
        *,
        after_flush: Callable[[list[EdgeAdapterInput]], None] | None = None,
    ) -> ConnectivityServer:
        """
        Create or replace one Connectivity server.

        `after_flush`, when given, is called with every PLC row's `EdgeAdapterInput`
        before this transaction commits, so a HiveMQ Edge XML write failure rolls
        back the catalog write instead of leaving them out of sync. The console
        always passes it for S7/EtherNet/IP, which is also when this sets
        `last_status="pending"` / `last_error=EDGE_APPLY_ERROR`: the row is not
        actually live until `testConnectivityServer` confirms the Edge apply.
        """
        spec.validate()
        if not spec.password:
            existing = await self._server_by_id(spec.id)
            if existing is not None and existing.password:
                spec.password = existing.password
        values = spec.column_values()
        if after_flush is not None and spec.protocol in PLC_PROTOCOLS:
            values = values | {"last_status": "pending", "last_error": EDGE_APPLY_ERROR}
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
            server = (
                await session.execute(select(ConnectivityServer).where(ConnectivityServer.id == spec.id))
            ).scalar_one()
            if after_flush is not None:
                await self._sync_edge(session, after_flush)
            return server

    async def _server_by_id(self, server_id: str) -> ConnectivityServer | None:
        async with self._database.session() as session:
            return (
                await session.execute(select(ConnectivityServer).where(ConnectivityServer.id == server_id))
            ).scalar_one_or_none()

    async def delete_server(
        self,
        server_id: str,
        *,
        after_flush: Callable[[list[EdgeAdapterInput]], None] | None = None,
    ) -> bool:
        """Delete a server and its tags (cascade). False when there was nothing to delete."""
        async with self._database.session() as session:
            result = await session.execute(
                delete(ConnectivityServer).where(ConnectivityServer.id == server_id)
            )
            deleted = bool(result.rowcount)
            if after_flush is not None and deleted:
                await self._sync_edge(session, after_flush)
            return deleted

    async def save_tag(
        self,
        server_id: str,
        spec: ConnectivityTagSpec,
        *,
        after_flush: Callable[[list[EdgeAdapterInput]], None] | None = None,
    ) -> ConnectivityTag:
        """
        Create or replace one tag, engineer-authored rather than discovered.

        Unlike `replace_subscribed_tags` (the discovery path), this is one node
        at a time and rejects an `mqtt_topic` already used by another subscribed
        node in the same transaction: two nodes publishing to the same topic
        would make one of them unrecoverable at the consumer end.
        """
        spec.validate()
        async with self._database.session() as session:
            existing_topics = await self.subscribed_topics(session, exclude=(server_id, spec.node_id))
            assert_unique_mqtt_topic(existing_topics, spec.mqtt_topic, node_id=spec.node_id)
            values: dict[str, Any] = {
                "server_id": server_id,
                "node_id": spec.node_id,
                "browse_path": spec.browse_path,
                "display_name": spec.display_name,
                "mqtt_topic": spec.mqtt_topic,
                "subscribed": spec.subscribed,
            }
            await session.execute(
                insert(ConnectivityTag)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[ConnectivityTag.server_id, ConnectivityTag.node_id],
                    set_={key: value for key, value in values.items() if key not in ("server_id", "node_id")}
                    | {"updated_at": func.now()},
                )
            )
            if after_flush is not None:
                await self._mark_pending_if_plc(session, server_id)
            row = (
                await session.execute(
                    select(ConnectivityTag)
                    .options(selectinload(ConnectivityTag.asset))
                    .where(ConnectivityTag.server_id == server_id, ConnectivityTag.node_id == spec.node_id)
                )
            ).scalar_one()
            if after_flush is not None:
                await self._sync_edge(session, after_flush)
            return row

    async def subscribed_topics(
        self, session: AsyncSession, *, exclude: tuple[str, str] | None = None
    ) -> set[str]:
        """
        Every `mqtt_topic` currently subscribed, in this session's transaction.

        Takes a `session` rather than opening its own, so a caller like `save_tag`
        can check for a duplicate topic and write the new one in the same
        transaction, instead of racing a second writer between the check and
        the write.
        """
        statement = select(
            ConnectivityTag.server_id, ConnectivityTag.node_id, ConnectivityTag.mqtt_topic
        ).where(ConnectivityTag.subscribed.is_(True))
        rows = (await session.execute(statement)).all()
        return {
            topic
            for row_server_id, row_node_id, topic in rows
            if topic and (exclude is None or (row_server_id, row_node_id) != exclude)
        }

    async def _mark_pending_if_plc(self, session: AsyncSession, server_id: str) -> None:
        """Flag the server a tag write touched as needing a HiveMQ Edge re-apply."""
        protocol = (
            await session.execute(select(ConnectivityServer.protocol).where(ConnectivityServer.id == server_id))
        ).scalar_one_or_none()
        if protocol in PLC_PROTOCOLS:
            await session.execute(
                update(ConnectivityServer)
                .where(ConnectivityServer.id == server_id)
                .values(last_status="pending", last_error=EDGE_APPLY_ERROR, updated_at=func.now())
            )

    async def _sync_edge(
        self, session: AsyncSession, after_flush: Callable[[list[EdgeAdapterInput]], None]
    ) -> None:
        """
        Flush this transaction's writes and hand every PLC row to `after_flush`.

        Called before the session commits: an `after_flush` that raises (a bad
        XML write) rolls the whole catalog write back with it, rather than
        leaving Postgres and HiveMQ Edge's `config.xml` disagreeing.
        """
        await session.flush()
        statement = select(ConnectivityServer).options(selectinload(ConnectivityServer.tags))
        servers = list((await session.execute(statement)).scalars())
        after_flush(edge_adapters_from_rows(servers))

    async def replace_subscribed_tags(
        self, server_id: str, tags: Sequence[ConnectivityTagSpec]
    ) -> list[ConnectivityTag]:
        """
        Fold a freshly discovered set of tags into the catalog for one server.

        Existing tags keep their `mqtt_topic`, `display_name`, and context
        columns; UPDATE only refreshes `browse_path`, `subscribed`, and
        `updated_at`. New tags are inserted with `subscribed=True`.
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
                # INSERT may set mqtt_topic and display_name; UPDATE must not,
                # and must not touch context columns. Engineer edits survive
                # a re-discovery.
                on_conflict_set = {
                    "browse_path": tag.browse_path,
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
        return await self.update_tag(server_id, node_id, mqtt_topic=mqtt_topic)

    _TAG_UPDATE_FIELDS = frozenset(
        {
            "display_name",
            "mqtt_topic",
            "asset_id",
            "unit_of_measure",
            "semantic_class",
            "data_type",
            "labels",
        }
    )

    async def update_tag(
        self,
        server_id: str,
        node_id: str,
        *,
        after_flush: Callable[[list[EdgeAdapterInput]], None] | None = None,
        **fields: Any,
    ) -> ConnectivityTag | None:
        """
        Partial-update one catalog tag. Only keys the caller passed are written.

        `None` for unit_of_measure, asset_id, semantic_class, or data_type clears
        that column. After save, a tag with both an Asset and a Unit of Measure
        upserts a Metric Definition so Enrichment stays aligned.
        """
        unknown = set(fields) - self._TAG_UPDATE_FIELDS
        if unknown:
            raise ValueError(f"update_tag does not accept {sorted(unknown)}")

        values: dict[str, Any] = dict(fields)
        values["updated_at"] = func.now()

        define: dict[str, Any] | None = None
        async with self._database.session() as session:
            await session.execute(
                update(ConnectivityTag)
                .where(ConnectivityTag.server_id == server_id, ConnectivityTag.node_id == node_id)
                .values(**values)
            )
            row = (
                await session.execute(
                    select(ConnectivityTag)
                    .options(selectinload(ConnectivityTag.asset))
                    .where(
                        ConnectivityTag.server_id == server_id,
                        ConnectivityTag.node_id == node_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if after_flush is not None:
                await self._mark_pending_if_plc(session, server_id)
                await self._sync_edge(session, after_flush)
            if row.asset_id is not None and row.unit_of_measure is not None:
                asset_path = (
                    await session.execute(select(Asset.path).where(Asset.id == row.asset_id))
                ).scalar_one()
                define = {
                    "metric_key": metric_key_for_tag(
                        asset_path=asset_path,
                        mqtt_topic=row.mqtt_topic,
                        browse_path=row.browse_path,
                        display_name=row.display_name,
                    ),
                    "asset_path": asset_path,
                    "unit_of_measure": row.unit_of_measure,
                    "display_name": row.display_name,
                }

        if define is not None:
            await AssetModelRepository(self._database).define_metric(
                define["metric_key"],
                asset_path=define["asset_path"],
                unit_of_measure=define["unit_of_measure"],
                display_name=define["display_name"],
            )
        return row

    async def save_unit_of_measure(self, symbol: str, name: str | None = None) -> UnitOfMeasure:
        """Insert a Unit of Measure. Duplicate symbols return the existing row."""
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("A Unit of Measure needs a symbol")
        if name is not None:
            name = name.strip() or None
        async with self._database.session() as session:
            await session.execute(
                insert(UnitOfMeasure)
                .values(symbol=symbol, name=name)
                .on_conflict_do_nothing(index_elements=[UnitOfMeasure.symbol])
            )
            return (
                await session.execute(select(UnitOfMeasure).where(UnitOfMeasure.symbol == symbol))
            ).scalar_one()

    async def save_signal_label(self, name: str) -> SignalLabel:
        """Insert a signal label. Duplicate names return the existing row."""
        name = name.strip()
        if not name:
            raise ValueError("A signal label needs a name")
        async with self._database.session() as session:
            await session.execute(
                insert(SignalLabel).values(name=name).on_conflict_do_nothing(index_elements=[SignalLabel.name])
            )
            return (await session.execute(select(SignalLabel).where(SignalLabel.name == name))).scalar_one()

    async def unsubscribe_tag(
        self,
        server_id: str,
        node_id: str,
        *,
        after_flush: Callable[[list[EdgeAdapterInput]], None] | None = None,
    ) -> ConnectivityTag | None:
        """Stop subscribing to a node. A deliberate act, never done by omission."""
        async with self._database.session() as session:
            await session.execute(
                update(ConnectivityTag)
                .where(ConnectivityTag.server_id == server_id, ConnectivityTag.node_id == node_id)
                .values(subscribed=False, updated_at=func.now())
            )
            row = (
                await session.execute(
                    select(ConnectivityTag).where(
                        ConnectivityTag.server_id == server_id,
                        ConnectivityTag.node_id == node_id,
                    )
                )
            ).scalar_one_or_none()
            if after_flush is not None:
                await self._mark_pending_if_plc(session, server_id)
                await self._sync_edge(session, after_flush)
            return row

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
        statement = (
            select(ConnectivityServer)
            .options(selectinload(ConnectivityServer.tags).selectinload(ConnectivityTag.asset))
            .order_by(ConnectivityServer.created_at, ConnectivityServer.id)
        )
        if protocol is not None:
            statement = statement.where(ConnectivityServer.protocol == protocol)
        async with self._database.session() as session:
            return list((await session.execute(statement)).scalars())

    async def list_units_of_measure(self) -> list[UnitOfMeasure]:
        """Unit of Measure catalog, ordered by symbol."""
        async with self._database.session() as session:
            return list((await session.execute(select(UnitOfMeasure).order_by(UnitOfMeasure.symbol))).scalars())

    async def list_signal_labels(self) -> list[SignalLabel]:
        """Signal label catalog, ordered by name."""
        async with self._database.session() as session:
            return list((await session.execute(select(SignalLabel).order_by(SignalLabel.name))).scalars())

    async def list_subscribed_tags(self, server_id: str) -> list[ConnectivityTag]:
        """Every tag for one server, in node_id order. Used by the bridge and by discovery."""
        statement = (
            select(ConnectivityTag)
            .options(selectinload(ConnectivityTag.asset))
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
    "EDGE_APPLY_ERROR",
    "assert_unique_mqtt_topic",
    "edge_adapters_from_rows",
    "merge_discovered",
    "metric_key_for_tag",
    "parse_host_port",
]
