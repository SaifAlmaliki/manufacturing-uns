"""Compile cloud desired-state adapters into Edge API operations."""

from __future__ import annotations

from typing import Any, Callable

from uns_config.edge_contracts import AdapterConfig, SUPPORTED_PROTOCOLS

from uns_edge_agent.protocols._common import CompileError, CompiledAdapter


def _compilers() -> dict[str, Callable[..., CompiledAdapter]]:
    from uns_edge_agent.protocols import eip, modbus, opcua, s7

    return {
        "opc_ua": opcua.compile,
        "modbus": modbus.compile,
        "s7": s7.compile,
        "ethernet_ip": eip.compile,
    }


def compile_adapter(
    adapter: AdapterConfig,
    capabilities: dict[str, Any],
    resolved_secrets: dict[str, bytes],
    *,
    endpoint_allowlist: frozenset[str] = frozenset(),
) -> CompiledAdapter:
    if adapter.protocol not in SUPPORTED_PROTOCOLS:
        raise CompileError("unsupported_protocol", adapter.protocol)
    supported = capabilities.get("protocols", ())
    if supported and adapter.protocol not in supported:
        raise CompileError("capability_missing", adapter.protocol)
    if adapter.southbound_mappings:
        raise CompileError("southbound_forbidden")
    if adapter.connection.get("read_only") is not True:
        raise CompileError("writes_forbidden")
    compiler = _compilers().get(adapter.protocol)
    if compiler is None:
        raise CompileError("unsupported_protocol", adapter.protocol)
    return compiler(adapter, resolved_secrets, endpoint_allowlist=endpoint_allowlist)
