"""Modbus TCP adapter compilation."""

from __future__ import annotations

from typing import Any

from uns_config.edge_contracts import AdapterConfig

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

_MODBUS_FUNCTIONS = {
    "holding_register": "HOLDING_REGISTER",
    "input_register": "INPUT_REGISTER",
    "coil": "COIL",
    "discrete_input": "DISCRETE_INPUT",
}
_MODBUS_DATA_TYPES = {
    "UInt16": "UINT16",
    "Int16": "INT16",
    "UInt32": "UINT32",
    "Int32": "INT32",
    "Float32": "FLOAT32",
    "Boolean": "BOOL",
}


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
    unit_id = require_int(connection.get("unit_id"), "connection.unit_id", minimum=0, maximum=255)
    byte_order = connection.get("byte_order")
    word_order = connection.get("word_order")
    polling_interval_ms = connection.get("polling_interval_ms")
    config: dict[str, Any] = {"host": host, "port": port, "unitId": unit_id}
    if byte_order is not None:
        config["byteOrder"] = str(byte_order)
    if word_order is not None:
        config["wordOrder"] = str(word_order)
    if polling_interval_ms is not None:
        config["pollingIntervalMs"] = require_int(
            polling_interval_ms,
            "connection.polling_interval_ms",
            minimum=100,
            maximum=3_600_000,
        )
    mappings = mapping_by_tag_id(adapter)
    names = unique_tag_names(adapter.tags, address_key="address")
    tag_items: list[dict[str, Any]] = []
    mapping_items: list[dict[str, Any]] = []
    for tag, name in zip(adapter.tags, names, strict=True):
        tag_id = require_str(tag.get("tag_id"), "tags.tag_id")
        address = require_int(tag.get("address"), "tags.address", minimum=0, maximum=65535)
        function = _MODBUS_FUNCTIONS.get(str(tag.get("function", "")).lower())
        if function is None:
            raise ValueError(f"unsupported modbus function for tag_id={tag_id}")
        data_type = _MODBUS_DATA_TYPES.get(str(tag.get("data_type", "")))
        if data_type is None:
            raise ValueError(f"unsupported modbus data_type for tag_id={tag_id}")
        mapping = mappings.get(tag_id)
        if mapping is None:
            raise ValueError(f"missing northbound mapping for tag_id={tag_id}")
        topic = require_str(mapping.get("topic"), "northbound_mappings.topic")
        definition: dict[str, Any] = {
            "address": address,
            "function": function,
            "dataType": data_type,
        }
        scale = tag.get("scale")
        if scale is not None:
            definition["scale"] = float(scale)
        tag_items.append(
            {
                "name": name,
                "description": str(tag.get("display_name") or tag_id),
                "definition": definition,
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
        adapter_body={"id": adapter.adapter_id, "type": "modbus", "config": config},
        tags=tag_items,
        mappings=mapping_items,
    )
