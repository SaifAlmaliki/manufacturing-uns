"""Connectivity catalog writes.

Role each field needs is in `auth/require.py`, not in these resolvers. Repository
`ValueError` is raised as-is so Strawberry surfaces the message, same contract as
`mutations/access_group.py`.

`subscribeOpcUaVariables` is the discovery path: it discovers every Variable on the
server's endpoint and folds the result into the catalog via
`ConnectivityRepository.replace_subscribed_tags`, which keeps an engineer's edited
`mqtt_topic` and never unsubscribes by omission. It only makes sense for OPC UA:
S7 and EtherNet/IP have no discovery protocol, so the console authors their tags
one at a time via `saveConnectivityTag`.

Every write that can change what HiveMQ Edge should be running (`saveConnectivityServer`,
`deleteConnectivityServer`, `saveConnectivityTag`, `updateConnectivityTag`,
`updateConnectivityTagTopic`, `unsubscribeConnectivityTag`) passes `_sync_edge` as the
repository's `after_flush`, so a failed XML write rolls the catalog write back with it
instead of leaving Postgres and HiveMQ Edge's `config.xml` disagreeing.
"""

from __future__ import annotations

import logging
from typing import Any

import strawberry
from uns_config.hivemq_edge_xml import EdgeAdapterInput, apply_catalog_adapters_file
from uns_config.loader import resolve_conf_dir
from uns_model.connectivity import (
    EDGE_APPLY_ERROR,
    ConnectivityRepository,
    ConnectivityServerSpec,
    ConnectivityTagSpec,
    parse_host_port,
)
from uns_model.engine import Database
from uns_model.tables import ConnectivityServer
from uns_opcua import browse as opcua_browse
from uns_opcua.session import open_client

from uns_graphql.auth.require import require
from uns_graphql.input.connectivity import (
    ConnectivityServerInput,
    ConnectivityTagInput,
    ConnectivityTagUpdateInput,
)
from uns_graphql.tcp_probe import probe_tcp
from uns_graphql.type.connectivity import ConnectivityServerType, ConnectivityTagType, UnitOfMeasureType

LOGGER = logging.getLogger(__name__)


def _repository() -> ConnectivityRepository:
    return ConnectivityRepository(Database.shared("graphql"))


def _sync_edge(adapters: list[EdgeAdapterInput]) -> None:
    """Splice the catalog's PLC rows into HiveMQ Edge's `config.xml`. Sync, per `after_flush`'s contract."""
    apply_catalog_adapters_file(resolve_conf_dir() / "hivemq" / "config.xml", adapters)


def _as_int(value: int | str | None) -> int | None:
    """Int64 parses to str; the repository wants an int. Same conversion as AlertRuleInput."""
    return None if value is None else int(value)


def _tag_update_fields(patch: ConnectivityTagUpdateInput) -> dict[str, Any]:
    """Only keys the caller set, so omitted patch fields are not written as null.

    `labels: null` becomes `[]` (column is NOT NULL). Null `display_name` /
    `mqtt_topic` are ignored rather than written into NOT NULL columns.
    """
    fields: dict[str, Any] = {}
    for name in (
        "display_name",
        "mqtt_topic",
        "asset_id",
        "unit_of_measure",
        "semantic_class",
        "data_type",
        "labels",
    ):
        value = getattr(patch, name)
        if value is strawberry.UNSET:
            continue
        if name == "asset_id":
            fields[name] = _as_int(value)
        elif name in {"semantic_class", "data_type"}:
            fields[name] = value.value if value is not None else None
        elif name == "labels":
            fields[name] = [] if value is None else value
        elif name in {"display_name", "mqtt_topic"} and value is None:
            continue
        else:
            fields[name] = value
    return fields


async def _find_server(repo: ConnectivityRepository, server_id: str) -> ConnectivityServer | None:
    """The saved server with this id, or None. `list_servers` has no by-id read; this is it."""
    for server in await repo.list_servers():
        if server.id == server_id:
            return server
    return None


@strawberry.type(description="Author the console's Connectivity catalog")
class Mutation:
    @strawberry.mutation(
        description="Create or replace one Connectivity server and return it as stored. "
        "Fails with a readable message when a value is outside the allowed vocabulary."
    )
    async def save_connectivity_server(
        self, info: strawberry.Info, server: ConnectivityServerInput
    ) -> ConnectivityServerType:
        require(info, "saveConnectivityServer")
        saved = await _repository().save_server(
            ConnectivityServerSpec(
                id=server.id,
                name=server.name,
                protocol=server.protocol.value,
                endpoint=server.endpoint,
                auth_mode=server.auth_mode.value,
                security_policy=server.security_policy.value,
                security_mode=server.security_mode.value,
                username=server.username,
                password=server.password,
                certificate=server.certificate,
                private_key=server.private_key,
                server_certificate=server.server_certificate,
                protocol_config=server.protocol_config,
            ),
            after_flush=_sync_edge,
        )
        LOGGER.info("Connectivity server %s saved as %s", saved.id, saved.name)
        return ConnectivityServerType.from_server(saved)

    @strawberry.mutation(
        description="Delete a Connectivity server and its tags (cascade). False when there was no such server."
    )
    async def delete_connectivity_server(self, info: strawberry.Info, id: str) -> bool:  # noqa: A002
        require(info, "deleteConnectivityServer")
        deleted = await _repository().delete_server(id, after_flush=_sync_edge)
        if deleted:
            LOGGER.info("Connectivity server %s deleted", id)
        return deleted

    @strawberry.mutation(
        description="Discover Variables under nodeId (or the whole Objects tree) and fold "
        "them into the catalog. An engineer's edited mqttTopic survives; nodes missing "
        "from this discovery stay subscribed until unsubscribeConnectivityTag removes them. "
        "OPC UA only — S7/EtherNet-IP tags have no discovery protocol."
    )
    async def subscribe_opc_ua_variables(
        self,
        info: strawberry.Info,
        server_id: str,
        node_id: str | None = strawberry.UNSET,
    ) -> list[ConnectivityTagType]:
        require(info, "subscribeOpcUaVariables")
        server = await _find_server(_repository(), server_id)
        if server is None:
            raise ValueError(f"No Connectivity server with id {server_id!r}")
        if server.protocol != "opc_ua":
            raise ValueError("OPC UA browse is only available for OPC UA servers")
        start = node_id if node_id is not strawberry.UNSET else None
        async with await open_client(server.endpoint) as client:
            discovered = await opcua_browse.discover_variables(client, start)
        tags = [
            ConnectivityTagSpec(
                node_id=row.node_id,
                browse_path=row.browse_path,
                display_name=row.display_name,
                mqtt_topic=row.browse_path,
            )
            for row in discovered
        ]
        stored = await _repository().replace_subscribed_tags(server_id, tags)
        LOGGER.info("Subscribed %s tag(s) on %s", len(stored), server_id)
        return [ConnectivityTagType.from_tag(tag) for tag in stored]

    @strawberry.mutation(
        description="Create or replace one tag on a server, authored directly rather than "
        "discovered. The one way to add a tag on an S7/EtherNet-IP server."
    )
    async def save_connectivity_tag(
        self, info: strawberry.Info, server_id: str, tag: ConnectivityTagInput
    ) -> ConnectivityTagType:
        require(info, "saveConnectivityTag")
        stored = await _repository().save_tag(
            server_id,
            ConnectivityTagSpec(
                node_id=tag.node_id,
                browse_path=tag.browse_path,
                display_name=tag.display_name,
                mqtt_topic=tag.mqtt_topic,
                subscribed=tag.subscribed,
                data_type=tag.data_type.value if tag.data_type is not None else None,
            ),
            after_flush=_sync_edge,
        )
        LOGGER.info("Connectivity tag %s saved on %s", tag.node_id, server_id)
        return ConnectivityTagType.from_tag(stored)

    @strawberry.mutation(
        description="Set the MQTT topic an engineer wants this node republished under."
    )
    async def update_connectivity_tag_topic(
        self, info: strawberry.Info, server_id: str, node_id: str, mqtt_topic: str
    ) -> ConnectivityTagType:
        require(info, "updateConnectivityTagTopic")
        tag = await _repository().update_tag_topic(
            server_id, node_id, mqtt_topic, after_flush=_sync_edge
        )
        if tag is None:
            raise ValueError(
                f"No Connectivity tag for server {server_id!r} node {node_id!r}"
            )
        return ConnectivityTagType.from_tag(tag)

    @strawberry.mutation(
        description="Stop subscribing to a node. A deliberate act, never done by omission. "
        "False when there was no such tag."
    )
    async def unsubscribe_connectivity_tag(
        self, info: strawberry.Info, server_id: str, node_id: str
    ) -> bool:
        require(info, "unsubscribeConnectivityTag")
        tag = await _repository().unsubscribe_tag(server_id, node_id, after_flush=_sync_edge)
        if tag is None:
            return False
        LOGGER.info("Unsubscribed %s on %s", node_id, server_id)
        return True

    @strawberry.mutation(
        description="Insert a Unit of Measure. Duplicate symbols return the existing row."
    )
    async def save_unit_of_measure(
        self, info: strawberry.Info, symbol: str, name: str | None = None
    ) -> UnitOfMeasureType:
        require(info, "saveUnitOfMeasure")
        saved = await _repository().save_unit_of_measure(symbol, name)
        return UnitOfMeasureType(symbol=saved.symbol, name=saved.name)

    @strawberry.mutation(
        description="Insert a signal label. Duplicate names return the existing row."
    )
    async def save_signal_label(self, info: strawberry.Info, name: str) -> str:
        require(info, "saveSignalLabel")
        saved = await _repository().save_signal_label(name)
        return saved.name

    @strawberry.mutation(
        description="Partial-update one Connectivity tag's engineer-authored context and return it as stored."
    )
    async def update_connectivity_tag(
        self,
        info: strawberry.Info,
        server_id: str,
        node_id: str,
        patch: ConnectivityTagUpdateInput,
    ) -> ConnectivityTagType:
        require(info, "updateConnectivityTag")
        tag = await _repository().update_tag(
            server_id, node_id, after_flush=_sync_edge, **_tag_update_fields(patch)
        )
        if tag is None:
            raise ValueError(
                f"No Connectivity tag for server {server_id!r} node {node_id!r}"
            )
        return ConnectivityTagType.from_tag(tag)

    @strawberry.mutation(
        description="Test a saved server's connection: OPC UA opens a session and reads the "
        "server node; S7/EtherNet-IP is a bare TCP connect. Records the outcome against "
        "the server, same as testOpcUaConnection does for an ad hoc endpoint."
    )
    async def test_connectivity_server(self, info: strawberry.Info, id: str) -> ConnectivityServerType:  # noqa: A002
        require(info, "testConnectivityServer")
        repo = _repository()
        server = await _find_server(repo, id)
        if server is None:
            raise ValueError(f"No Connectivity server with id {id!r}")
        was_pending = server.last_status == "pending"
        if server.protocol == "opc_ua":
            ok, error, _elapsed_ms = await opcua_browse.test_connection(server.endpoint)
        else:
            host, port = parse_host_port(server.endpoint)
            ok, error = probe_tcp(host, port)
        if ok and was_pending:
            # The row was pending its first HiveMQ Edge apply, not actually broken.
            # A successful TCP probe does not prove Edge itself is happy — keep the
            # reminder to recreate uns_mqtt_broker rather than clearing it to "connected".
            error = EDGE_APPLY_ERROR
        updated = await repo.record_test(id, ok=ok, error=error)
        LOGGER.info("Connectivity server %s tested: ok=%s", id, ok)
        return ConnectivityServerType.from_server(updated)

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the Asset Model queries, which dispose it."""
