"""Shared protocol compilation helpers."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from uns_config.edge_contracts import AdapterConfig
from uns_config.hivemq_edge_xml import tag_xml_name


class CompileError(ValueError):
    """Adapter compilation failure with a stable reason code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CompiledAdapter:
    adapter_id: str
    protocol_type: str
    adapter_body: dict[str, Any]
    tags: list[dict[str, Any]]
    mappings: list[dict[str, Any]]


_OPC_TCP_RE = re.compile(r"^opc\.tcp://([^/]+)", re.IGNORECASE)


def edge_protocol_type(protocol: str) -> str:
    if protocol == "ethernet_ip":
        return "eip"
    if protocol == "opc_ua":
        return "opcua"
    if protocol in {"modbus", "s7"}:
        return protocol
    raise CompileError("unsupported_protocol", protocol)


def connection_host(adapter: AdapterConfig) -> str:
    connection = adapter.connection
    if adapter.protocol == "opc_ua":
        uri = connection.get("uri")
        if not isinstance(uri, str) or not uri:
            raise CompileError("missing_field", "connection.uri")
        match = _OPC_TCP_RE.match(uri.strip())
        if match is None:
            raise CompileError("invalid_field", "connection.uri")
        host_port = match.group(1)
        return host_port.split(":")[0]
    host = connection.get("host")
    if not isinstance(host, str) or not host.strip():
        raise CompileError("missing_field", "connection.host")
    return host.strip()


def check_endpoint_allowlist(adapter: AdapterConfig, allowlist: frozenset[str]) -> None:
    if not allowlist:
        return
    host = connection_host(adapter)
    if host not in allowlist:
        raise CompileError("endpoint_not_allowed", host)


def unique_tag_names(tags: tuple[dict[str, Any], ...], *, address_key: str) -> list[str]:
    seen: dict[str, int] = {}
    names: list[str] = []
    for tag in tags:
        base = tag_xml_name(str(tag.get(address_key, tag.get("tag_id", "tag"))))
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return names


def mapping_by_tag_id(adapter: AdapterConfig) -> dict[str, dict[str, Any]]:
    return {str(item["tag_id"]): item for item in adapter.northbound_mappings if "tag_id" in item}


def require_int(value: Any, field: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompileError("invalid_field", field)
    if minimum is not None and value < minimum:
        raise CompileError("invalid_field", field)
    if maximum is not None and value > maximum:
        raise CompileError("invalid_field", field)
    return value


def require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompileError("missing_field", field)
    return value


def resolve_secret_ref(
    connection: dict[str, Any],
    key: str,
    resolved_secrets: dict[str, bytes],
) -> str | None:
    ref_key = f"{key}_secret_ref"
    secret_id = connection.get(ref_key)
    if secret_id is None:
        return None
    if not isinstance(secret_id, str) or not secret_id:
        raise CompileError("invalid_field", ref_key)
    if secret_id not in resolved_secrets:
        raise CompileError("secret_not_resolved", secret_id)
    return resolved_secrets[secret_id].decode("utf-8")


def validate_resolved_secret_scope(
    adapter: AdapterConfig,
    resolved_secrets: dict[str, bytes],
) -> None:
    prefix = f"{adapter.adapter_id}/"
    for secret_id in resolved_secrets:
        if not secret_id.startswith(prefix):
            raise CompileError("secret_scope_invalid", secret_id)


def is_private_or_loopback(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def parse_host_port(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri if "://" in uri else f"tcp://{uri}")
    host = parsed.hostname
    if not host:
        raise CompileError("invalid_field", "connection.uri")
    port = parsed.port
    if port is None:
        raise CompileError("invalid_field", "connection.uri")
    return host, port
