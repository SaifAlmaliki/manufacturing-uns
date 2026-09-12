"""Build cloud edge desired-state snapshots from connectivity catalog rows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uns_config.edge_contracts import SUPPORTED_PROTOCOLS
from uns_config.hivemq_edge_xml import adapter_id_for, tag_xml_name
from uns_model.connectivity import parse_host_port
from uns_model.edge_repository import EdgeRepository
from uns_model.edge_secrets import EdgeSecretStore
from uns_model.edge_tables import EdgeReport, EdgeSecretVersion
from uns_model.tables import ConnectivityServer, EDGE_PROTOCOLS

_MODBUS_DATA_TYPES = {
    "Integer": "Int16",
    "Double": "Float32",
    "Boolean": "Boolean",
    "String": "UInt16",
}


@dataclass(frozen=True, slots=True)
class CloudDesiredContext:
    """Transactional desired-state write scoped to one edge revision."""

    edge_id: str
    expected_revision: int
    actor: str | None = None
    deleted_adapter_ids: tuple[str, ...] = ()
    required_route_revision: int = 0
    edge_repository: EdgeRepository | None = None
    secret_store: EdgeSecretStore | None = None


def connection_health_from_server(server: ConnectivityServer) -> str:
    """Probe outcome separate from desired/applied reconciliation."""
    return server.last_status


def _tag_key(node_id: str) -> str:
    return tag_xml_name(node_id) or "tag"


def _modbus_tag(tag) -> dict[str, Any]:
    address = int(str(tag.node_id).strip())
    data_type = _MODBUS_DATA_TYPES.get(getattr(tag, "data_type", None) or "", "UInt16")
    config = getattr(tag, "protocol_config", None) or {}
    function = str(config.get("function", "holding_register")).lower()
    payload: dict[str, Any] = {
        "tag_id": _tag_key(tag.node_id),
        "address": address,
        "function": function,
        "data_type": data_type,
    }
    scale = config.get("scale")
    if scale is not None:
        payload["scale"] = scale
    return payload


def _adapter_tags(server: ConnectivityServer) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tags: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for tag in getattr(server, "tags", []):
        if not tag.subscribed:
            continue
        tag_id = _tag_key(tag.node_id)
        if server.protocol == "opc_ua":
            tags.append(
                {
                    "tag_id": tag_id,
                    "node_id": tag.node_id,
                    "display_name": tag.display_name,
                    "data_type": tag.data_type or "Double",
                }
            )
        elif server.protocol == "modbus":
            tags.append(_modbus_tag(tag))
        else:
            tags.append(
                {
                    "tag_id": tag_id,
                    "address": tag.node_id,
                    "display_name": tag.display_name,
                    "data_type": tag.data_type or "Integer",
                }
            )
        mappings.append({"tag_id": tag_id, "topic": tag.mqtt_topic})
    return tags, mappings


def _connection_document(
    server: ConnectivityServer,
    *,
    secret_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    connection: dict[str, Any] = {"read_only": True}
    if server.protocol == "opc_ua":
        connection["uri"] = server.endpoint
        connection["security_mode"] = server.security_mode
        connection["security_policy"] = server.security_policy
        if server.username:
            secret_id = f"{adapter_id_for(server.id)}/username"
            connection["username_secret_ref"] = secret_id
            secret_refs.append({"secret_id": secret_id, "version": 1})
        if server.password:
            secret_id = f"{adapter_id_for(server.id)}/password"
            connection["password_secret_ref"] = secret_id
            secret_refs.append({"secret_id": secret_id, "version": 1})
        return connection
    host, port = parse_host_port(server.endpoint)
    connection["host"] = host
    connection["port"] = port
    if server.protocol == "s7":
        controller = (server.protocol_config or {}).get("controllerType", "S7_1500")
        connection["controller_type"] = controller
    if server.protocol == "modbus":
        config = server.protocol_config or {}
        connection["unit_id"] = int(config.get("unit_id", 1))
        if "byte_order" in config:
            connection["byte_order"] = config["byte_order"]
        if "word_order" in config:
            connection["word_order"] = config["word_order"]
        if "polling_interval_ms" in config:
            connection["polling_interval_ms"] = int(config["polling_interval_ms"])
    return connection


def build_adapter_document(server: ConnectivityServer) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One adapter block plus any secret references it introduces."""
    secret_refs: list[dict[str, Any]] = []
    tags, mappings = _adapter_tags(server)
    adapter = {
        "adapter_id": adapter_id_for(server.id),
        "protocol": server.protocol,
        "connection": _connection_document(server, secret_refs=secret_refs),
        "tags": tags,
        "northbound_mappings": mappings,
    }
    return adapter, secret_refs


def build_desired_document(
    servers: Sequence[ConnectivityServer],
    *,
    edge_id: str,
    deleted_adapter_ids: Sequence[str] = (),
    required_route_revision: int = 0,
) -> dict[str, Any]:
    adapters: list[dict[str, Any]] = []
    secret_refs: list[dict[str, Any]] = []
    seen_secrets: set[tuple[str, int]] = set()
    for server in servers:
        if server.edge_id != edge_id or server.protocol not in EDGE_PROTOCOLS:
            continue
        adapter, refs = build_adapter_document(server)
        adapters.append(adapter)
        for ref in refs:
            key = (ref["secret_id"], ref["version"])
            if key not in seen_secrets:
                seen_secrets.add(key)
                secret_refs.append(ref)
    return {
        "contract_version": 1,
        "edge_id": edge_id,
        "adapters": adapters,
        "required_route_revision": required_route_revision,
        "secret_refs": secret_refs,
        "deleted_adapter_ids": list(deleted_adapter_ids),
    }


async def _servers_for_edge(session: AsyncSession, edge_id: str) -> list[ConnectivityServer]:
    from sqlalchemy.orm import selectinload

    from uns_model.tables import ConnectivityTag

    statement = (
        select(ConnectivityServer)
        .options(selectinload(ConnectivityServer.tags).selectinload(ConnectivityTag.asset))
        .where(ConnectivityServer.edge_id == edge_id)
        .order_by(ConnectivityServer.id)
    )
    return list((await session.execute(statement)).scalars())


async def _edge_capabilities(session: AsyncSession, edge_id: str) -> frozenset[str] | None:
    report = (
        await session.execute(
            select(EdgeReport)
            .where(EdgeReport.edge_id == edge_id)
            .order_by(EdgeReport.received_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if report is None:
        return None
    payload = report.payload or {}
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        return None
    protocols = capabilities.get("protocols")
    if not protocols:
        return None
    advertised = frozenset(str(item) for item in protocols)
    return advertised


async def validate_edge_protocols(
    session: AsyncSession,
    edge_id: str,
    servers: Sequence[ConnectivityServer],
) -> None:
    advertised = await _edge_capabilities(session, edge_id)
    if advertised is None:
        return
    for server in servers:
        if server.edge_id != edge_id:
            continue
        if server.protocol not in EDGE_PROTOCOLS:
            continue
        if server.protocol not in advertised:
            raise ValueError(
                f"Edge {edge_id!r} has not advertised {server.protocol!r} capability"
            )


async def _next_secret_version(session: AsyncSession, secret_id: str) -> int:
    current = (
        await session.execute(
            select(func.max(EdgeSecretVersion.version)).where(
                EdgeSecretVersion.secret_id == secret_id
            )
        )
    ).scalar_one_or_none()
    return 1 if current is None else int(current) + 1


async def _persist_server_secrets(
    session: AsyncSession,
    server: ConnectivityServer,
    *,
    edge_id: str,
    secret_store: EdgeSecretStore,
) -> None:
    adapter_id = adapter_id_for(server.id)
    candidates: list[tuple[str, str]] = []
    if server.protocol == "opc_ua":
        if server.username:
            candidates.append((f"{adapter_id}/username", server.username))
        if server.password:
            candidates.append((f"{adapter_id}/password", server.password))
    for secret_id, plaintext in candidates:
        version = await _next_secret_version(session, secret_id)
        encrypted = secret_store.encrypt(
            edge_id=edge_id,
            secret_id=secret_id,
            version=version,
            plaintext=plaintext.encode("utf-8"),
        )
        session.add(
            EdgeSecretVersion(
                secret_id=secret_id,
                version=version,
                edge_id=edge_id,
                key_id=encrypted.key_id,
                nonce=encrypted.nonce,
                ciphertext=encrypted.ciphertext,
            )
        )


async def commit_connectivity_desired(
    session: AsyncSession,
    ctx: CloudDesiredContext,
) -> int:
    """Write the next immutable desired snapshot in the same transaction as catalog edits."""
    if ctx.edge_repository is None:
        from uns_model.engine import Database

        edge_repo = EdgeRepository(Database.shared())
    else:
        edge_repo = ctx.edge_repository

    servers = await _servers_for_edge(session, ctx.edge_id)
    await validate_edge_protocols(session, ctx.edge_id, servers)
    if ctx.secret_store is not None:
        for server in servers:
            await _persist_server_secrets(
                session,
                server,
                edge_id=ctx.edge_id,
                secret_store=ctx.secret_store,
            )
    document = build_desired_document(
        servers,
        edge_id=ctx.edge_id,
        deleted_adapter_ids=ctx.deleted_adapter_ids,
        required_route_revision=ctx.required_route_revision,
    )
    saved = await edge_repo.save_desired(
        ctx.edge_id,
        ctx.expected_revision,
        document,
        actor=ctx.actor,
        session=session,
    )
    return saved.revision


def supported_protocols() -> frozenset[str]:
    return frozenset(SUPPORTED_PROTOCOLS)
