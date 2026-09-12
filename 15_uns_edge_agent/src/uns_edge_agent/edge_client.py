"""Local HiveMQ Edge Management API client."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from uns_config.edge_contracts import CATALOG_ADAPTER_PREFIX
from uns_edge_agent.protocols._common import CompiledAdapter

_AUTH = "/api/v1/auth/authenticate"
_ADAPTERS = "/api/v1/management/protocol-adapters/adapters"
_CAPABILITIES = "/api/v1/management/protocol-adapters/capabilities"


class EdgeClientError(Exception):
    """Local Edge API failure."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class NormalizedAdapter:
    adapter_id: str
    protocol_type: str
    connection: dict[str, Any]
    tags: tuple[dict[str, Any], ...]
    northbound_mappings: tuple[dict[str, Any], ...]


class EdgeClient(Protocol):
    def capabilities(self) -> dict[str, Any]: ...

    def read_owned(self, edge_id: str) -> dict[str, NormalizedAdapter]: ...

    def apply_adapter(self, compiled: CompiledAdapter) -> None: ...

    def delete_owned(self, adapter_id: str) -> None: ...


def normalize_adapter_record(item: dict[str, Any]) -> NormalizedAdapter:
    adapter_id = str(item.get("id", ""))
    protocol_type = str(item.get("type", ""))
    config = item.get("config")
    if not isinstance(config, dict):
        config = {}
    tags_raw = item.get("tags")
    mappings_raw = item.get("northboundMappings")
    tags = tuple(tags_raw.get("items", [])) if isinstance(tags_raw, dict) else ()
    mappings = tuple(mappings_raw.get("items", [])) if isinstance(mappings_raw, dict) else ()
    return NormalizedAdapter(
        adapter_id=adapter_id,
        protocol_type=protocol_type,
        connection=dict(config),
        tags=tags,
        northbound_mappings=mappings,
    )


def snapshot_owned(adapters: dict[str, NormalizedAdapter]) -> dict[str, Any]:
    return {
        adapter_id: {
            "adapter_id": adapter.adapter_id,
            "protocol_type": adapter.protocol_type,
            "connection": copy.deepcopy(adapter.connection),
            "tags": [copy.deepcopy(tag) for tag in adapter.tags],
            "northbound_mappings": [copy.deepcopy(mapping) for mapping in adapter.northbound_mappings],
        }
        for adapter_id, adapter in adapters.items()
    }


class HiveMQEdgeClient:
    """HTTP client for the local HiveMQ Edge Management API."""

    def __init__(
        self,
        base_url: str,
        *,
        username: str,
        password: str,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self._username = username
        self._password = password
        self._token: str | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _authenticate(self) -> None:
        if self._token is not None:
            return
        response = self._request(
            "POST",
            _AUTH,
            json={"userName": self._username, "password": self._password},
        )
        self._token = response.json()["token"]
        self._client.headers["Authorization"] = f"Bearer {self._token}"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise EdgeClientError("edge_unreachable", str(exc)) from exc
        if response.status_code >= 400:
            raise EdgeClientError("edge_http_error", f"{method} {path} -> {response.status_code}")
        return response

    def capabilities(self) -> dict[str, Any]:
        self._authenticate()
        response = self._request("GET", _CAPABILITIES)
        payload = response.json()
        protocols = tuple(
            item.get("protocolId")
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("protocolId")
        )
        return {"version": payload.get("version", 1), "protocols": protocols}

    def read_owned(self, edge_id: str) -> dict[str, NormalizedAdapter]:
        self._authenticate()
        response = self._request("GET", _ADAPTERS)
        items = response.json().get("items") or []
        owned: dict[str, NormalizedAdapter] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            adapter_id = item.get("id")
            if not isinstance(adapter_id, str) or not adapter_id.startswith(CATALOG_ADAPTER_PREFIX):
                continue
            detail = self._request("GET", f"{_ADAPTERS}/{adapter_id}").json()
            tags = self._request("GET", f"{_ADAPTERS}/{adapter_id}/tags").json()
            mappings = self._request("GET", f"{_ADAPTERS}/{adapter_id}/northboundMappings").json()
            detail["tags"] = tags
            detail["northboundMappings"] = mappings
            owned[adapter_id] = normalize_adapter_record(detail)
        return owned

    def apply_adapter(self, compiled: CompiledAdapter) -> None:
        self._authenticate()
        adapter_id = compiled.adapter_id
        listed = self._request("GET", _ADAPTERS).json().get("items") or []
        existing_ids = {item.get("id") for item in listed if isinstance(item, dict)}
        body = compiled.adapter_body
        if adapter_id in existing_ids:
            self._request("PUT", f"{_ADAPTERS}/{adapter_id}", json=body)
        else:
            self._request("POST", f"{_ADAPTERS}/{compiled.protocol_type}", json=body)
        self._request("PUT", f"{_ADAPTERS}/{adapter_id}/tags", json={"items": compiled.tags})
        self._request(
            "PUT",
            f"{_ADAPTERS}/{adapter_id}/northboundMappings",
            json={"items": compiled.mappings},
        )

    def delete_owned(self, adapter_id: str) -> None:
        if not adapter_id.startswith(CATALOG_ADAPTER_PREFIX):
            raise EdgeClientError("undeclared_deletion", adapter_id)
        self._authenticate()
        self._request("DELETE", f"{_ADAPTERS}/{adapter_id}")


class FakeEdgeClient:
    """In-memory Edge API for unit tests with stage-specific failures."""

    def __init__(self) -> None:
        self._adapters: dict[str, dict[str, Any]] = {}
        self._capabilities = {
            "version": 1,
            "protocols": ("opc_ua", "modbus", "s7", "ethernet_ip"),
        }
        self.failures: dict[str, str] = {}
        self.fail_after_write: set[str] = set()
        self.corrupt_readback = False
        self.calls: list[tuple[str, str]] = []

    def set_capabilities(self, capabilities: dict[str, Any]) -> None:
        self._capabilities = capabilities

    def capabilities(self) -> dict[str, Any]:
        return dict(self._capabilities)

    def read_owned(self, edge_id: str) -> dict[str, NormalizedAdapter]:
        if self.corrupt_readback:
            return {}
        return self.read_owned_for_snapshot(edge_id)

    def read_owned_for_snapshot(self, edge_id: str) -> dict[str, NormalizedAdapter]:
        return {
            adapter_id: normalize_adapter_record(copy.deepcopy(record))
            for adapter_id, record in self._adapters.items()
            if adapter_id.startswith("catalog-")
        }

    def seed_adapter(self, record: dict[str, Any]) -> None:
        adapter_id = str(record["id"])
        self._adapters[adapter_id] = copy.deepcopy(record)

    def apply_adapter(self, compiled: CompiledAdapter) -> None:
        adapter_id = compiled.adapter_id
        self.calls.append(("apply", adapter_id))
        stage = self.failures.get(adapter_id)
        if stage == "adapter":
            raise EdgeClientError("adapter_failed", adapter_id)
        record = copy.deepcopy(compiled.adapter_body)
        self._adapters[adapter_id] = record
        if adapter_id in self.fail_after_write:
            raise EdgeClientError("response_lost", adapter_id)
        if stage == "tags":
            raise EdgeClientError("tags_failed", adapter_id)
        record["tags"] = {"items": copy.deepcopy(compiled.tags)}
        if stage == "mappings":
            raise EdgeClientError("mappings_failed", adapter_id)
        record["northboundMappings"] = {"items": copy.deepcopy(compiled.mappings)}

    def delete_owned(self, adapter_id: str) -> None:
        self.calls.append(("delete", adapter_id))
        if self.failures.get(adapter_id) == "delete":
            raise EdgeClientError("delete_failed", adapter_id)
        self._adapters.pop(adapter_id, None)

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._adapters = {}
        for adapter_id, record in snapshot.items():
            self._adapters[adapter_id] = {
                "id": adapter_id,
                "type": record["protocol_type"],
                "config": copy.deepcopy(record["connection"]),
                "tags": {"items": copy.deepcopy(record.get("tags", []))},
                "northboundMappings": {
                    "items": copy.deepcopy(record.get("northbound_mappings", [])),
                },
            }
