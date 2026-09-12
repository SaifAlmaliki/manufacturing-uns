"""Execute bounded management jobs against edge-owned connections."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any, Protocol

from uns_config.hivemq_edge_xml import adapter_id_for
from uns_model.connectivity import parse_host_port

from uns_config.edge_jobs import MAX_TAGS_PER_PAGE, parse_cursor_offset

try:
    from uns_opcua import browse as opcua_browse
except ImportError:  # pragma: no cover - optional in minimal installs
    opcua_browse = None


class JobExecutionError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PolledJob:
    job_id: str
    edge_id: str
    connection_id: str
    config_revision: int
    kind: str
    cursor: str | None
    node_id: str | None
    expires_at: str


class ConnectionResolver(Protocol):
    def resolve(self, edge_id: str, connection_id: str, config_revision: int) -> dict[str, Any]: ...


def connection_from_config(document: dict[str, Any], connection_id: str) -> dict[str, Any]:
    adapter_id = adapter_id_for(connection_id)
    for adapter in document.get("adapters", []):
        if not isinstance(adapter, dict):
            continue
        if adapter.get("adapter_id") == adapter_id:
            connection = adapter.get("connection")
            if not isinstance(connection, dict):
                break
            protocol = str(adapter.get("protocol", ""))
            endpoint = str(connection.get("uri") or connection.get("endpoint") or "")
            if not endpoint and connection.get("host"):
                host = str(connection["host"])
                port = int(connection.get("port", 0))
                endpoint = f"{host}:{port}" if port else host
            return {
                "protocol": protocol,
                "endpoint": endpoint,
                "connection": dict(connection),
            }
    raise JobExecutionError("connection_not_in_config", connection_id)


class JobExecutor:
    """Run one bounded management job using edge-local protocol access."""

    def __init__(self, *, endpoint_allowlist: frozenset[str] = frozenset()) -> None:
        self._endpoint_allowlist = endpoint_allowlist

    def execute_sync(self, job: PolledJob, connection: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        return asyncio.run(self.execute(job, connection))

    async def execute(self, job: PolledJob, connection: dict[str, Any]) -> dict[str, Any]:
        if job.kind == "test_connection":
            return await self._test_connection(connection)
        if job.kind == "browse_tags":
            return await self._browse_tags(connection, job.cursor, job.node_id)
        raise JobExecutionError("unsupported_kind", job.kind)

    async def _test_connection(self, connection: dict[str, Any]) -> dict[str, Any]:
        protocol = str(connection.get("protocol", ""))
        endpoint = str(connection.get("endpoint", ""))
        self._check_allowlist(endpoint)
        if protocol == "opc_ua":
            if opcua_browse is None:
                raise JobExecutionError("opcua_unavailable")
            ok, error, elapsed_ms = await opcua_browse.test_connection(endpoint)
            if not ok:
                return {
                    "status": "failed",
                    "result": {"ok": False, "elapsed_ms": elapsed_ms},
                    "error_code": "connection_failed",
                    "error_detail": error,
                }
            return {"status": "completed", "result": {"ok": True, "elapsed_ms": elapsed_ms}}
        host, port = parse_host_port(endpoint)
        ok, error = _probe_tcp(host, port)
        if not ok:
            return {
                "status": "failed",
                "result": {"ok": False},
                "error_code": "connection_failed",
                "error_detail": error,
            }
        return {"status": "completed", "result": {"ok": True}}

    async def _browse_tags(
        self,
        connection: dict[str, Any],
        cursor: str | None,
        node_id: str | None,
    ) -> dict[str, Any]:
        protocol = str(connection.get("protocol", ""))
        if protocol != "opc_ua":
            return {
                "status": "failed",
                "error_code": "discovery_unsupported",
                "error_detail": protocol,
            }
        if opcua_browse is None:
            raise JobExecutionError("opcua_unavailable")
        endpoint = str(connection.get("endpoint", ""))
        self._check_allowlist(endpoint)
        offset = parse_cursor_offset(cursor)
        from uns_opcua.session import open_client

        async with await open_client(endpoint) as client:
            rows = await opcua_browse.browse_children(client, node_id)
        page = rows[offset : offset + MAX_TAGS_PER_PAGE]
        next_offset = offset + len(page)
        has_more = next_offset < len(rows)
        tags = [
            {
                "node_id": row.node_id,
                "browse_name": row.browse_name,
                "display_name": row.display_name,
                "browse_path": row.browse_path,
                "node_class": row.node_class,
                "has_children": row.has_children,
            }
            for row in page
        ]
        result = {"tags": tags, "has_more": has_more}
        if has_more:
            result["next_cursor"] = f"{job_cursor_token(cursor)}.{next_offset}"
        return {"status": "completed", "result": result}

    def _check_allowlist(self, endpoint: str) -> None:
        if not self._endpoint_allowlist:
            return
        host, _port = parse_host_port(endpoint.replace("opc.tcp://", "").split("/", 1)[0])
        if host not in self._endpoint_allowlist:
            raise JobExecutionError("endpoint_not_allowed", host)


def job_cursor_token(cursor: str | None) -> str:
    if cursor and "." in cursor:
        return cursor.rsplit(".", 1)[0]
    return "page"


def _probe_tcp(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as exc:
        return False, str(exc)


def polled_job_from_payload(payload: dict[str, Any]) -> PolledJob:
    return PolledJob(
        job_id=str(payload["job_id"]),
        edge_id=str(payload["edge_id"]),
        connection_id=str(payload["connection_id"]),
        config_revision=int(payload["config_revision"]),
        kind=str(payload["kind"]),
        cursor=payload.get("cursor"),
        node_id=payload.get("node_id"),
        expires_at=str(payload["expires_at"]),
    )
