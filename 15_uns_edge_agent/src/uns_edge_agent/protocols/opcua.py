"""OPC UA adapter compilation."""

from __future__ import annotations

from typing import Any

from uns_config.edge_contracts import AdapterConfig
from uns_config.hivemq_edge_xml import edge_data_type

from uns_edge_agent.protocols._common import (
    check_endpoint_allowlist,
    edge_protocol_type,
    mapping_by_tag_id,
    require_str,
    resolve_secret_ref,
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
    uri = require_str(connection.get("uri"), "connection.uri")
    config: dict[str, Any] = {"uri": uri}
    security_mode = connection.get("security_mode")
    security_policy = connection.get("security_policy")
    if security_mode is not None:
        config["securityMode"] = str(security_mode)
    if security_policy is not None:
        config["securityPolicy"] = str(security_policy)
    username = resolve_secret_ref(connection, "username", resolved_secrets)
    password = resolve_secret_ref(connection, "password", resolved_secrets)
    if username is not None:
        config["username"] = username
    if password is not None:
        config["password"] = password
    mappings = mapping_by_tag_id(adapter)
    names = unique_tag_names(adapter.tags, address_key="node_id")
    tag_items: list[dict[str, Any]] = []
    mapping_items: list[dict[str, Any]] = []
    for tag, name in zip(adapter.tags, names, strict=True):
        tag_id = require_str(tag.get("tag_id"), "tags.tag_id")
        node_id = require_str(tag.get("node_id"), "tags.node_id")
        mapping = mappings.get(tag_id)
        if mapping is None:
            raise ValueError(f"missing northbound mapping for tag_id={tag_id}")
        topic = require_str(mapping.get("topic"), "northbound_mappings.topic")
        tag_items.append(
            {
                "name": name,
                "description": str(tag.get("display_name") or node_id),
                "definition": {
                    "node": node_id,
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
        adapter_body={"id": adapter.adapter_id, "type": "opcua", "config": config},
        tags=tag_items,
        mappings=mapping_items,
    )
