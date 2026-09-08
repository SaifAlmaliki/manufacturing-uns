"""Push catalog-owned adapters to a running HiveMQ Edge via the Management API."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from uns_config.hivemq_edge_xml import (
    EdgeAdapterInput,
    _unique_tag_names,
    adapter_id_for,
    edge_data_type,
)
from uns_config.loader import get_settings

LOGGER = logging.getLogger(__name__)

_TIMEOUT = 10.0
_AUTH = "/api/v1/auth/authenticate"
_ADAPTERS = "/api/v1/management/protocol-adapters/adapters"


class EdgeApplyError(Exception):
    """HiveMQ Edge did not accept the catalog adapters."""


def _protocol_id(protocol: str) -> str:
    if protocol == "ethernet_ip":
        return "eip"
    if protocol == "s7":
        return "s7"
    raise ValueError(f"unsupported Edge protocol: {protocol}")


def _adapter_body(adapter: EdgeAdapterInput) -> dict[str, Any]:
    protocol_id = _protocol_id(adapter.protocol)
    config: dict[str, Any] = {"host": adapter.host, "port": adapter.port}
    if protocol_id == "s7":
        config["controllerType"] = adapter.controller_type
    return {"id": adapter_id_for(adapter.server_id), "type": protocol_id, "config": config}


def _tag_items(adapter: EdgeAdapterInput) -> list[dict[str, Any]]:
    protocol_id = _protocol_id(adapter.protocol)
    addr_key = "tagAddress" if protocol_id == "s7" else "address"
    names = _unique_tag_names(adapter.tags)
    items = []
    for tag, name in zip(adapter.tags, names, strict=True):
        items.append(
            {
                "name": name,
                "description": tag.display_name or tag.node_id,
                "definition": {
                    addr_key: tag.node_id,
                    "dataType": edge_data_type(tag.data_type),
                },
            }
        )
    return items


def _mapping_items(adapter: EdgeAdapterInput) -> list[dict[str, Any]]:
    names = _unique_tag_names(adapter.tags)
    return [
        {
            "topic": tag.mqtt_topic,
            "tagName": name,
            "maxQoS": "AT_LEAST_ONCE",
            "includeTimestamp": True,
        }
        for tag, name in zip(adapter.tags, names, strict=True)
    ]


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise EdgeApplyError(str(exc)) from exc
    if response.status_code >= 400:
        raise EdgeApplyError(f"{method} {path} -> {response.status_code}")
    return response


def apply_catalog_adapters_live(
    adapters: list[EdgeAdapterInput],
    *,
    client: httpx.Client | None = None,
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout: float = _TIMEOUT,
) -> None:
    owns_client = client is None
    if owns_client:
        settings = get_settings()
        client = httpx.Client(
            base_url=base_url or str(settings.get("hivemq_edge.base_url", "http://127.0.0.1:18080")),
            timeout=timeout,
        )
        user = username or str(settings.get("hivemq_edge.username", "admin"))
        secret = password or str(settings.get("hivemq_edge.password", "hivemq"))
    else:
        user = username or "admin"
        secret = password or "hivemq"
    try:
        token = _request(
            client, "POST", _AUTH, json={"userName": user, "password": secret}
        ).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        listed = _request(client, "GET", _ADAPTERS).json().get("items") or []
        wanted = {adapter_id_for(adapter.server_id): adapter for adapter in adapters}
        existing_ids = {item.get("id") for item in listed if isinstance(item, dict)}
        for item in listed:
            adapter_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(adapter_id, str) and adapter_id.startswith("catalog-") and adapter_id not in wanted:
                _request(client, "DELETE", f"{_ADAPTERS}/{adapter_id}")
        for adapter_id, adapter in wanted.items():
            body = _adapter_body(adapter)
            if adapter_id in existing_ids:
                _request(client, "PUT", f"{_ADAPTERS}/{adapter_id}", json=body)
            else:
                _request(client, "POST", f"{_ADAPTERS}/{body['type']}", json=body)
            _request(client, "PUT", f"{_ADAPTERS}/{adapter_id}/tags", json={"items": _tag_items(adapter)})
            _request(
                client,
                "PUT",
                f"{_ADAPTERS}/{adapter_id}/northboundMappings",
                json={"items": _mapping_items(adapter)},
            )
    finally:
        if owns_client:
            client.close()
