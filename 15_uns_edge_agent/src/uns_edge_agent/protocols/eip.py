"""EtherNet/IP adapter compilation."""

from __future__ import annotations

from typing import Any

from uns_config.edge_contracts import AdapterConfig
from uns_config.hivemq_edge_xml import edge_data_type

from uns_edge_agent.protocols._common import (
    check_endpoint_allowlist,
    edge_protocol_type,
    mapping_by_tag_id,
    require_int,
    require_str,
    unique_tag_names,
    validate_resolved_secret_scope,
)
from uns_edge_agent.protocols._common import CompiledAdapter


def compile(
    adapter: AdapterConfig,
    resolved_secrets: dict[str, bytes],
    *,
    endpoint_allowlist: frozenset[str],
) -> CompiledAdapter:
    validate_resolved_secret_scope(adapter, resolved_secrets)
    check_endpoint_allowlist(adapter, endpoint_allowlist)
    connection = adapter.connection
    host = require_str(connection.get("host"), "connection.host")
    port = require_int(connection.get("port"), "connection.port", minimum=1, maximum=65535)
    config: dict[str, Any] = {"host": host, "port": port}
    mappings = mapping_by_tag_id(adapter)
    names = unique_tag_names(adapter.tags, address_key="address")
    tag_items: list[dict[str, Any]] = []
    mapping_items: list[dict[str, Any]] = []
    for tag, name in zip(adapter.tags, names, strict=True):
        tag_id = require_str(tag.get("tag_id"), "tags.tag_id")
        address = require_str(tag.get("address"), "tags.address")
        mapping = mappings.get(tag_id)
        if mapping is None:
            raise ValueError(f"missing northbound mapping for tag_id={tag_id}")
        topic = require_str(mapping.get("topic"), "northbound_mappings.topic")
        tag_items.append(
            {
                "name": name,
                "description": str(tag.get("display_name") or address),
                "definition": {
                    "address": address,
                    "dataType": edge_data_type(tag.get("data_type")),
                },
            }
        )
        mapping_items.append(
            {
                "topic": topic,
                "tagName": name,
                "maxQoS": "AT_LEAST_ONCE",
                "includeTimestamp": True,
            }
        )
    return CompiledAdapter(
        adapter_id=adapter.adapter_id,
        protocol_type=edge_protocol_type(adapter.protocol),
        adapter_body={"id": adapter.adapter_id, "type": "eip", "config": config},
        tags=tag_items,
        mappings=mapping_items,
    )
