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
from uns_config.hivemq_edge_api import EdgeApplyError, apply_catalog_adapters_live
from uns_config.hivemq_edge_xml import EdgeAdapterInput, adapter_id_for, apply_catalog_adapters_file
from uns_config.loader import resolve_conf_dir
from uns_model.connectivity import (
    EDGE_APPLY_ERROR,
    EDGE_PROTOCOLS,
    ConnectivityRepository,
    ConnectivityServerSpec,
    ConnectivityTagSpec,
    edge_adapters_from_rows,
    is_cloud_edge_mode,
    parse_host_port,
)
from uns_model.edge_desired import CloudDesiredContext, commit_connectivity_desired
from uns_model.edge_repository import EdgeRepository, EdgeRevisionConflict
from uns_model.edge_secrets import EdgeKeyRing, EdgeSecretStore
from uns_model.engine import Database
from uns_model.tables import ConnectivityServer
from uns_opcua import browse as opcua_browse
from uns_opcua.session import open_client

from uns_graphql.auth.context import identity_in
from uns_graphql.auth.require import require, require_edge_access
from uns_graphql.backend.historian import HistorianRepository
from uns_graphql.input.connectivity import (
    ConnectivityServerInput,
    ConnectivityTagInput,
    ConnectivityTagUpdateInput,
)
from uns_config.edge_jobs import JOB_KIND_BROWSE_TAGS, JOB_KIND_TEST_CONNECTION
from uns_graphql.edge_api.jobs import EdgeJobService
from uns_graphql.edge_api.service import EdgeServiceError
from uns_graphql.tcp_probe import probe_tcp
from uns_graphql.type.connectivity import (
    ConnectivityJobType,
    ConnectivityServerType,
    ConnectivityTagType,
    UnitOfMeasureType,
    connectivity_job_from_record,
)
from uns_model.edge_repository import EdgeStatusSnapshot

LOGGER = logging.getLogger(__name__)


def _repository() -> ConnectivityRepository:
    return ConnectivityRepository(Database.shared("graphql"))


def _edge_repository() -> EdgeRepository:
    return EdgeRepository(Database.shared("graphql"))


async def _require_connected_edge(edge_id: str) -> EdgeStatusSnapshot:
    status = await _edge_repository().device_status(edge_id)
    if status is None or status.last_seen is None:
        raise ValueError(f"Edge {edge_id!r} is not connected")
    return status


async def _start_connectivity_job(
    info: strawberry.Info,
    server: ConnectivityServer,
    *,
    kind: str,
    node_id: str | None = None,
    cursor: str | None = None,
) -> ConnectivityJobType:
    if not server.edge_id:
        raise ValueError("edge_id is required in cloud edge mode")
    await require_edge_access(info, server.edge_id)
    status = await _require_connected_edge(server.edge_id)
    try:
        record = await _job_service().create_job(
            edge_id=server.edge_id,
            connection_id=server.id,
            kind=kind,
            config_revision=status.desired_revision,
            node_id=node_id,
            cursor=cursor,
        )
    except EdgeServiceError as exc:
        raise ValueError(exc.reason) from exc
    return connectivity_job_from_record(record)


def _job_service() -> EdgeJobService:
    from uns_graphql.mutations.edge import _edge_service

    management = _edge_service()
    return EdgeJobService(
        Database.shared("graphql"),
        _edge_repository(),
        management,
    )


def _sync_edge(adapters: list[EdgeAdapterInput]) -> None:
    """Splice the catalog's Edge rows into HiveMQ Edge's `config.xml`. Sync, per `after_flush`'s contract."""
    apply_catalog_adapters_file(resolve_conf_dir() / "hivemq" / "config.xml", adapters)


def _edge_secret_store() -> EdgeSecretStore | None:
    try:
        return EdgeSecretStore(EdgeKeyRing.from_settings())
    except Exception:
        LOGGER.warning("Edge secret store unavailable; cloud writes skip secret versions", exc_info=True)
        return None


def _cloud_context(
    info: strawberry.Info,
    edge_id: str,
    expected_revision: int,
    *,
    deleted_adapter_ids: tuple[str, ...] = (),
) -> CloudDesiredContext:
    identity = identity_in(getattr(info, "context", None))
    return CloudDesiredContext(
        edge_id=edge_id,
        expected_revision=expected_revision,
        actor=getattr(identity, "username", None),
        deleted_adapter_ids=deleted_adapter_ids,
        edge_repository=_edge_repository(),
        secret_store=_edge_secret_store(),
    )


def _desired_flush(ctx: CloudDesiredContext):
    async def _flush(session):
        await commit_connectivity_desired(session, ctx)

    return _flush


async def _edge_status(edge_id: str | None):
    if not edge_id:
        return None
    return await _edge_repository().device_status(edge_id)


def _require_cloud_revision(server: ConnectivityServerInput) -> tuple[str, int]:
    if not server.edge_id:
        raise ValueError("edge_id is required in cloud edge mode")
    if server.expected_revision is None:
        raise ValueError("expected_revision is required in cloud edge mode")
    return server.edge_id, int(server.expected_revision)


async def _finish_live_apply(mutated_ids: list[str]) -> None:
    """Push catalog adapters to the running broker. Never raises into the mutation."""
    repo = _repository()
    adapters = edge_adapters_from_rows(await repo.list_servers())
    try:
        apply_catalog_adapters_live(adapters)
    except EdgeApplyError:
        LOGGER.warning("HiveMQ Edge live apply failed", exc_info=True)
        await repo.record_live_apply(mutated_ids, ok=False)
        return
    edge_ids = [adapter.server_id for adapter in adapters] or mutated_ids
    await repo.record_live_apply(edge_ids, ok=True)


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


async def _rewrite_topics(session, old_topic: str, new_topic: str) -> None:
    connection = await session.connection()
    await HistorianRepository(Database.shared("graphql")).rewrite_topic_prefix(
        old_topic, new_topic, connection=connection
    )


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
        repo = _repository()
        spec = ConnectivityServerSpec(
            id=server.id,
            name=server.name,
            protocol=server.protocol.value,
            endpoint=server.endpoint,
            edge_id=server.edge_id,
            auth_mode=server.auth_mode.value,
            security_policy=server.security_policy.value,
            security_mode=server.security_mode.value,
            username=server.username,
            password=server.password,
            certificate=server.certificate,
            private_key=server.private_key,
            server_certificate=server.server_certificate,
            protocol_config=server.protocol_config,
        )
        if is_cloud_edge_mode():
            edge_id, expected_revision = _require_cloud_revision(server)
            await require_edge_access(info, edge_id)
            ctx = _cloud_context(info, edge_id, expected_revision)
            try:
                saved = await repo.save_server(spec, after_flush_async=_desired_flush(ctx))
            except EdgeRevisionConflict as exc:
                raise ValueError(str(exc)) from exc
            status = await _edge_status(saved.edge_id)
            LOGGER.info("Connectivity server %s saved for edge %s", saved.id, edge_id)
            return ConnectivityServerType.from_server(saved, edge_status=status)

        saved = await repo.save_server(
            spec,
            after_flush=_sync_edge,
        )
        if saved.protocol in EDGE_PROTOCOLS:
            await _finish_live_apply([saved.id])
            refetched = await _find_server(repo, saved.id)
            if refetched is not None:
                saved = refetched
        LOGGER.info("Connectivity server %s saved as %s", saved.id, saved.name)
        return ConnectivityServerType.from_server(saved)

    @strawberry.mutation(
        description="Delete a Connectivity server and its tags (cascade). False when there was no such server."
    )
    async def delete_connectivity_server(
        self,
        info: strawberry.Info,
        id: str,  # noqa: A002
        edge_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        require(info, "deleteConnectivityServer")
        repo = _repository()
        existing = await _find_server(repo, id)
        if is_cloud_edge_mode():
            if not edge_id or expected_revision is None:
                raise ValueError("edge_id and expected_revision are required in cloud edge mode")
            await require_edge_access(info, edge_id)
            deleted_id = adapter_id_for(id) if existing is not None else None
            ctx = _cloud_context(
                info,
                edge_id,
                int(expected_revision),
                deleted_adapter_ids=(deleted_id,) if deleted_id else (),
            )
            try:
                deleted = await repo.delete_server(id, after_flush_async=_desired_flush(ctx))
            except EdgeRevisionConflict as exc:
                raise ValueError(str(exc)) from exc
            if deleted:
                LOGGER.info("Connectivity server %s deleted from edge %s", id, edge_id)
            return deleted

        deleted = await repo.delete_server(id, after_flush=_sync_edge)
        if deleted and existing is not None and existing.protocol in EDGE_PROTOCOLS:
            await _finish_live_apply([])
        if deleted:
            LOGGER.info("Connectivity server %s deleted", id)
        return deleted

    @strawberry.mutation(
        description="Request a paged OPC UA browse on an edge-owned server. Returns a job "
        "the console polls until tags are available. Cloud edge mode only."
    )
    async def browse_opc_ua_tags(
        self,
        info: strawberry.Info,
        server_id: str,
        node_id: str | None = strawberry.UNSET,
        cursor: str | None = strawberry.UNSET,
    ) -> ConnectivityJobType:
        require(info, "browseOpcUaTags")
        if not is_cloud_edge_mode():
            raise ValueError("browseOpcUaTags is only available in cloud edge mode")
        server = await _find_server(_repository(), server_id)
        if server is None:
            raise ValueError(f"No Connectivity server with id {server_id!r}")
        if server.protocol != "opc_ua":
            raise ValueError("OPC UA browse is only available for OPC UA servers")
        return await _start_connectivity_job(
            info,
            server,
            kind=JOB_KIND_BROWSE_TAGS,
            node_id=node_id if node_id is not strawberry.UNSET else None,
            cursor=cursor if cursor is not strawberry.UNSET else None,
        )

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
        if is_cloud_edge_mode():
            raise ValueError(
                "OPC UA discovery is unavailable in cloud edge mode; add tags manually."
            )
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
        stored = await _repository().replace_subscribed_tags(server_id, tags, after_flush=_sync_edge)
        await _finish_live_apply([server_id])
        LOGGER.info("Subscribed %s tag(s) on %s", len(stored), server_id)
        return [ConnectivityTagType.from_tag(tag) for tag in stored]

    @strawberry.mutation(
        description="Create or replace one tag on a server, authored directly rather than "
        "discovered. The one way to add a tag on an S7/EtherNet-IP server."
    )
    async def save_connectivity_tag(
        self,
        info: strawberry.Info,
        server_id: str,
        tag: ConnectivityTagInput,
        expected_revision: int | None = None,
    ) -> ConnectivityTagType:
        require(info, "saveConnectivityTag")
        repo = _repository()
        server = await _find_server(repo, server_id)
        if is_cloud_edge_mode():
            if server is None or not server.edge_id:
                raise ValueError(f"No edge-scoped Connectivity server with id {server_id!r}")
            if expected_revision is None:
                raise ValueError("expected_revision is required in cloud edge mode")
            await require_edge_access(info, server.edge_id)
            ctx = _cloud_context(info, server.edge_id, int(expected_revision))
            try:
                stored = await repo.save_tag(
                    server_id,
                    ConnectivityTagSpec(
                        node_id=tag.node_id,
                        browse_path=tag.browse_path,
                        display_name=tag.display_name,
                        mqtt_topic=tag.mqtt_topic,
                        subscribed=tag.subscribed,
                        data_type=tag.data_type.value if tag.data_type is not None else None,
                    ),
                    after_flush_async=_desired_flush(ctx),
                )
            except EdgeRevisionConflict as exc:
                raise ValueError(str(exc)) from exc
            LOGGER.info("Connectivity tag %s saved on %s", tag.node_id, server_id)
            return ConnectivityTagType.from_tag(stored)

        stored = await repo.save_tag(
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
        if server is not None and server.protocol in EDGE_PROTOCOLS:
            await _finish_live_apply([server_id])
        LOGGER.info("Connectivity tag %s saved on %s", tag.node_id, server_id)
        return ConnectivityTagType.from_tag(stored)

    @strawberry.mutation(
        description="Set the MQTT topic an engineer wants this node republished under."
    )
    async def update_connectivity_tag_topic(
        self,
        info: strawberry.Info,
        server_id: str,
        node_id: str,
        mqtt_topic: str,
        expected_revision: int | None = None,
    ) -> ConnectivityTagType:
        require(info, "updateConnectivityTagTopic")
        repo = _repository()
        server = await _find_server(repo, server_id)
        if is_cloud_edge_mode():
            if server is None or not server.edge_id:
                raise ValueError(f"No edge-scoped Connectivity server with id {server_id!r}")
            if expected_revision is None:
                raise ValueError("expected_revision is required in cloud edge mode")
            await require_edge_access(info, server.edge_id)
            ctx = _cloud_context(info, server.edge_id, int(expected_revision))
            try:
                tag = await repo.update_tag_topic(
                    server_id,
                    node_id,
                    mqtt_topic,
                    after_flush_async=_desired_flush(ctx),
                    on_topic_rewrite=_rewrite_topics,
                )
            except EdgeRevisionConflict as exc:
                raise ValueError(str(exc)) from exc
        else:
            tag = await repo.update_tag_topic(
                server_id,
                node_id,
                mqtt_topic,
                after_flush=_sync_edge,
                on_topic_rewrite=_rewrite_topics,
            )
            if server is not None and server.protocol in EDGE_PROTOCOLS:
                await _finish_live_apply([server_id])
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
        self,
        info: strawberry.Info,
        server_id: str,
        node_id: str,
        expected_revision: int | None = None,
    ) -> bool:
        require(info, "unsubscribeConnectivityTag")
        repo = _repository()
        server = await _find_server(repo, server_id)
        if is_cloud_edge_mode():
            if server is None or not server.edge_id:
                raise ValueError(f"No edge-scoped Connectivity server with id {server_id!r}")
            if expected_revision is None:
                raise ValueError("expected_revision is required in cloud edge mode")
            await require_edge_access(info, server.edge_id)
            ctx = _cloud_context(info, server.edge_id, int(expected_revision))
            try:
                tag = await repo.unsubscribe_tag(
                    server_id, node_id, after_flush_async=_desired_flush(ctx)
                )
            except EdgeRevisionConflict as exc:
                raise ValueError(str(exc)) from exc
        else:
            tag = await repo.unsubscribe_tag(server_id, node_id, after_flush=_sync_edge)
            if server is not None and server.protocol in EDGE_PROTOCOLS:
                await _finish_live_apply([server_id])
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
        expected_revision: int | None = None,
    ) -> ConnectivityTagType:
        require(info, "updateConnectivityTag")
        repo = _repository()
        server = await _find_server(repo, server_id)
        if is_cloud_edge_mode():
            if server is None or not server.edge_id:
                raise ValueError(f"No edge-scoped Connectivity server with id {server_id!r}")
            if expected_revision is None:
                raise ValueError("expected_revision is required in cloud edge mode")
            await require_edge_access(info, server.edge_id)
            ctx = _cloud_context(info, server.edge_id, int(expected_revision))
            try:
                tag = await repo.update_tag(
                    server_id,
                    node_id,
                    after_flush_async=_desired_flush(ctx),
                    **_tag_update_fields(patch),
                )
            except EdgeRevisionConflict as exc:
                raise ValueError(str(exc)) from exc
        else:
            tag = await repo.update_tag(
                server_id, node_id, after_flush=_sync_edge, **_tag_update_fields(patch)
            )
            if server is not None and server.protocol in EDGE_PROTOCOLS:
                await _finish_live_apply([server_id])
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
        if is_cloud_edge_mode():
            job = await _start_connectivity_job(info, server, kind=JOB_KIND_TEST_CONNECTION)
            status = await _edge_status(server.edge_id)
            return ConnectivityServerType.from_server(
                server,
                edge_status=status,
                active_job_id=job.job_id,
                active_job_status=job.status.value,
            )
        was_pending = server.last_status == "pending"
        if server.protocol == "opc_ua":
            ok, error, _elapsed_ms = await opcua_browse.test_connection(server.endpoint)
        else:
            host, port = parse_host_port(server.endpoint)
            ok, error = probe_tcp(host, port)
        if ok and was_pending:
            error = EDGE_APPLY_ERROR
        updated = await repo.record_test(id, ok=ok, error=error)
        LOGGER.info("Connectivity server %s tested: ok=%s", id, ok)
        return ConnectivityServerType.from_server(updated)

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the Asset Model queries, which dispose it."""
