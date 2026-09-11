"""Pure edge desired-state contracts and validation.

No database, MQTT, HTTP, or environment imports.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from uns_config.edge_config_digest import configuration_digest

MAX_EDGE_CONFIG_BYTES = 4 * 1024 * 1024
MAX_ADAPTERS = 500
MAX_TAGS = 20_000
SUPPORTED_CONTRACT_VERSION = 1
SUPPORTED_PROTOCOLS = frozenset({"opc_ua", "modbus", "s7", "ethernet_ip"})
CATALOG_ADAPTER_PREFIX = "catalog-"

_SECRET_VALUE_KEYS = frozenset(
    {
        "password",
        "secret",
        "private_key",
        "certificate",
        "token",
        "credential",
        "client_secret",
    }
)
_WRITE_ENABLE_KEYS = frozenset({"writes_enabled", "write_enabled", "allow_writes"})


class EdgeConfigError(ValueError):
    """Bounded contract failure with a stable reason code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    adapter_id: str
    protocol: str
    connection: dict[str, Any]
    tags: tuple[dict[str, Any], ...]
    northbound_mappings: tuple[dict[str, Any], ...]
    southbound_mappings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class EdgeConfig:
    contract_version: int
    edge_id: str
    revision: int
    digest: str
    adapters: tuple[AdapterConfig, ...]
    required_route_revision: int
    secret_refs: tuple[dict[str, Any], ...]
    deleted_adapter_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EdgeReport:
    edge_id: str
    boot_id: str
    report_sequence: int
    desired_revision: int
    applied_revision: int
    applied_digest: str
    phase: str
    adapter_results: tuple[dict[str, Any], ...]
    last_error_code: str | None
    versions: dict[str, Any]
    capabilities: dict[str, Any]


def decode_edge_config(raw: bytes) -> EdgeConfig:
    if len(raw) > MAX_EDGE_CONFIG_BYTES:
        raise EdgeConfigError("oversize")
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_pairs_hook)
    except EdgeConfigError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EdgeConfigError("invalid_json") from exc
    if not isinstance(parsed, dict):
        raise EdgeConfigError("invalid_json")
    _reject_non_finite(parsed)
    return _dict_to_edge_config(parsed)


def validate_collection_only(config: EdgeConfig) -> None:
    adapter_ids = {adapter.adapter_id for adapter in config.adapters}
    for deleted_id in config.deleted_adapter_ids:
        if not deleted_id.startswith(CATALOG_ADAPTER_PREFIX):
            raise EdgeConfigError("undeclared_deletion", deleted_id)
        if deleted_id in adapter_ids:
            raise EdgeConfigError("undeclared_deletion", deleted_id)

    for adapter in config.adapters:
        _validate_collection_adapter(adapter)


def _object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise EdgeConfigError("duplicate_key")
    return dict(pairs)


def _dict_to_edge_config(parsed: dict[str, Any]) -> EdgeConfig:
    contract_version = parsed.get("contract_version")
    if contract_version != SUPPORTED_CONTRACT_VERSION:
        raise EdgeConfigError("unsupported_contract")

    edge_id = parsed.get("edge_id")
    if not isinstance(edge_id, str) or not edge_id.strip():
        raise EdgeConfigError("missing_field", "edge_id")

    revision = _require_int(parsed.get("revision"), "revision")
    required_route_revision = _require_int(
        parsed.get("required_route_revision"),
        "required_route_revision",
    )

    adapters_raw = parsed.get("adapters")
    if not isinstance(adapters_raw, list):
        raise EdgeConfigError("invalid_field", "adapters")
    if len(adapters_raw) > MAX_ADAPTERS:
        raise EdgeConfigError("too_many_adapters")

    total_tags = 0
    for adapter in adapters_raw:
        if not isinstance(adapter, dict):
            raise EdgeConfigError("invalid_field", "adapters")
        tags = adapter.get("tags")
        if tags is None:
            continue
        if not isinstance(tags, list):
            raise EdgeConfigError("invalid_field", "tags")
        total_tags += len(tags)
        if total_tags > MAX_TAGS:
            raise EdgeConfigError("too_many_tags")

    secret_refs_raw = parsed.get("secret_refs", [])
    if secret_refs_raw is None:
        secret_refs_raw = []
    if not isinstance(secret_refs_raw, list):
        raise EdgeConfigError("invalid_field", "secret_refs")

    deleted_raw = parsed.get("deleted_adapter_ids", [])
    if deleted_raw is None:
        deleted_raw = []
    if not isinstance(deleted_raw, list):
        raise EdgeConfigError("invalid_field", "deleted_adapter_ids")

    digest = parsed.get("digest")
    if not isinstance(digest, str) or not digest:
        raise EdgeConfigError("missing_field", "digest")
    expected_digest = configuration_digest(parsed)
    if digest != expected_digest:
        raise EdgeConfigError("digest_mismatch")

    adapters = tuple(_dict_to_adapter(item) for item in adapters_raw)
    secret_refs = tuple(_dict_to_secret_ref(item) for item in secret_refs_raw)
    deleted_adapter_ids = tuple(_require_str(item, "deleted_adapter_ids") for item in deleted_raw)

    config = EdgeConfig(
        contract_version=contract_version,
        edge_id=edge_id,
        revision=revision,
        digest=digest,
        adapters=adapters,
        required_route_revision=required_route_revision,
        secret_refs=secret_refs,
        deleted_adapter_ids=deleted_adapter_ids,
    )
    _reject_inline_secret_values(config)
    return config


def _dict_to_adapter(parsed: dict[str, Any]) -> AdapterConfig:
    adapter_id = parsed.get("adapter_id")
    if not isinstance(adapter_id, str) or not adapter_id:
        raise EdgeConfigError("invalid_field", "adapter_id")
    protocol = parsed.get("protocol")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise EdgeConfigError("invalid_field", "protocol")
    connection = parsed.get("connection")
    if not isinstance(connection, dict):
        raise EdgeConfigError("invalid_field", "connection")
    tags_raw = parsed.get("tags", [])
    if tags_raw is None:
        tags_raw = []
    if not isinstance(tags_raw, list):
        raise EdgeConfigError("invalid_field", "tags")
    mappings_raw = parsed.get("northbound_mappings", [])
    if mappings_raw is None:
        mappings_raw = []
    if not isinstance(mappings_raw, list):
        raise EdgeConfigError("invalid_field", "northbound_mappings")
    southbound_raw = parsed.get("southbound_mappings", [])
    if southbound_raw is None:
        southbound_raw = []
    if not isinstance(southbound_raw, list):
        raise EdgeConfigError("invalid_field", "southbound_mappings")

    tags = tuple(_dict_to_mapping(item, "tags") for item in tags_raw)
    northbound_mappings = tuple(
        _dict_to_mapping(item, "northbound_mappings") for item in mappings_raw
    )
    southbound_mappings = tuple(
        _dict_to_mapping(item, "southbound_mappings") for item in southbound_raw
    )
    return AdapterConfig(
        adapter_id=adapter_id,
        protocol=protocol,
        connection=dict(connection),
        tags=tags,
        northbound_mappings=northbound_mappings,
        southbound_mappings=southbound_mappings,
    )


def _dict_to_mapping(parsed: Any, field: str) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise EdgeConfigError("invalid_field", field)
    return dict(parsed)


def _dict_to_secret_ref(parsed: Any) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise EdgeConfigError("invalid_field", "secret_refs")
    secret_id = parsed.get("secret_id")
    version = parsed.get("version")
    if not isinstance(secret_id, str) or not secret_id:
        raise EdgeConfigError("invalid_field", "secret_refs.secret_id")
    version_int = _require_int(version, "secret_refs.version")
    return {"secret_id": secret_id, "version": version_int}


def _validate_collection_adapter(adapter: AdapterConfig) -> None:
    if adapter.southbound_mappings:
        raise EdgeConfigError("southbound_forbidden")
    connection = adapter.connection
    if connection.get("read_only") is not True:
        raise EdgeConfigError("writes_forbidden")
    for key, value in connection.items():
        if key in _WRITE_ENABLE_KEYS and value is True:
            raise EdgeConfigError("writes_forbidden", key)
        if key == "mode" and isinstance(value, str) and value.lower() == "write":
            raise EdgeConfigError("writes_forbidden", key)


def _reject_inline_secret_values(config: EdgeConfig) -> None:
    for adapter in config.adapters:
        for key in adapter.connection:
            normalized = key.lower()
            if normalized.endswith("_secret_ref"):
                continue
            if normalized in _SECRET_VALUE_KEYS:
                raise EdgeConfigError("secret_value_forbidden", key)


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EdgeConfigError("invalid_field", field)
    return value


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EdgeConfigError("invalid_field", field)
    return value


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EdgeConfigError("invalid_nan")
        return
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
