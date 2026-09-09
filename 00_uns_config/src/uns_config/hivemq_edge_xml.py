"""Splice catalog-owned HiveMQ Edge adapters into config.xml without restyling the rest.

Limitation: only whole `<!-- ... -->` comments and `<protocol-adapter>` blocks between
`<protocol-adapters>` and `</protocol-adapters>` are preserved verbatim (see `_TOKEN`).
Any other inner text at that level (e.g. stray non-comment text) is dropped, same as
before this was documented. A comment inside a catalog-owned adapter's own block is
lost on the next re-render, since that block is fully regenerated from the catalog row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

_DATA_TYPES = {"Integer": "DINT", "Double": "REAL", "Boolean": "BOOL", "String": "STRING"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")
_TOKEN = re.compile(
    r"[ \t]*(?:<!--.*?-->|<protocol-adapter>.*?</protocol-adapter>)",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class EdgeTagInput:
    node_id: str
    display_name: str
    mqtt_topic: str
    data_type: str | None


@dataclass(frozen=True, slots=True)
class EdgeAdapterInput:
    server_id: str
    protocol: str
    host: str
    port: int
    uri: str = ""
    controller_type: str = "S7_1500"
    tags: tuple[EdgeTagInput, ...] = ()


def adapter_id_for(server_id: str) -> str:
    return f"catalog-{server_id}"


def edge_data_type(catalog_type: str | None) -> str:
    return _DATA_TYPES.get(catalog_type or "", "DINT")


def tag_xml_name(node_id: str) -> str:
    cleaned = _SAFE_NAME.sub("_", node_id).strip("_")
    return cleaned or "tag"


def _unique_tag_names(tags: tuple[EdgeTagInput, ...]) -> list[str]:
    """
    `tag_xml_name` sanitizes each `node_id` independently, so two distinct
    node_ids (e.g. `%ID103` and `%ID.103`) can collide on the same `<name>`.
    HiveMQ Edge needs every tag name in an adapter to be unique, so a
    collision is suffixed `_2`, `_3`, ... in tag order rather than silently
    letting the second tag shadow the first.
    """
    seen: dict[str, int] = {}
    names: list[str] = []
    for tag in tags:
        base = tag_xml_name(tag.node_id)
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return names


def render_catalog_adapter(adapter: EdgeAdapterInput) -> str:
    if adapter.protocol == "ethernet_ip":
        protocol_id = "eip"
    elif adapter.protocol == "opc_ua":
        protocol_id = "opcua"
    else:
        protocol_id = "s7"
    aid = adapter_id_for(adapter.server_id)
    lines = [
        "        <protocol-adapter>",
        f"            <adapterId>{_esc(aid)}</adapterId>",
        f"            <protocolId>{protocol_id}</protocolId>",
        "            <config>",
    ]
    if protocol_id == "opcua":
        lines.append(f"                <uri>{_esc(adapter.uri)}</uri>")
    else:
        lines.extend(
            [
                f"                <host>{_esc(adapter.host)}</host>",
                f"                <port>{adapter.port}</port>",
            ]
        )
        if protocol_id == "s7":
            lines.append(
                f"                <controllerType>{_esc(adapter.controller_type)}</controllerType>"
            )
    lines.append("            </config>")
    if not adapter.tags:
        lines.extend(["            <northboundMappings/>", "            <tags/>"])
    else:
        names = _unique_tag_names(adapter.tags)
        lines.append("            <northboundMappings>")
        for tag, name in zip(adapter.tags, names, strict=True):
            lines.extend(
                [
                    "                <northboundMapping>",
                    f"                    <topic>{_esc(tag.mqtt_topic)}</topic>",
                    f"                    <tagName>{_esc(name)}</tagName>",
                    "                    <maxQos>1</maxQos>",
                    "                    <includeTimestamp>true</includeTimestamp>",
                    "                </northboundMapping>",
                ]
            )
        lines.append("            </northboundMappings>")
        lines.append("            <tags>")
        if protocol_id == "s7":
            addr_el = "tagAddress"
        elif protocol_id == "eip":
            addr_el = "address"
        else:
            addr_el = "node"
        for tag, name in zip(adapter.tags, names, strict=True):
            desc = tag.display_name or tag.node_id
            lines.extend(
                [
                    "                <tag>",
                    f"                    <name>{_esc(name)}</name>",
                    f"                    <description>{_esc(desc)}</description>",
                    "                    <definition>",
                    f"                        <{addr_el}>{_esc(tag.node_id)}</{addr_el}>",
                    f"                        <dataType>{edge_data_type(tag.data_type)}</dataType>",
                    "                    </definition>",
                    "                </tag>",
                ]
            )
        lines.append("            </tags>")
    lines.append("        </protocol-adapter>")
    return "\n".join(lines)


def _is_catalog_adapter_block(token: str) -> bool:
    stripped = token.lstrip()
    return stripped.startswith("<protocol-adapter>") and "<adapterId>catalog-" in token


def apply_catalog_adapters(document: str, adapters: list[EdgeAdapterInput]) -> str:
    """
    Return `document` with every `catalog-*` protocol-adapter replaced by `adapters`.

    Re-parses the *result* as XML before returning: a bug in this splice (or an
    engineer-typed value that breaks well-formedness despite `_esc`) must fail loudly
    here rather than let `apply_catalog_adapters_file` write a config.xml HiveMQ Edge
    cannot parse.
    """
    if "<hivemq" not in document:
        raise ValueError("config.xml is not a HiveMQ document")
    try:
        ET.fromstring(document)
    except ET.ParseError as exc:
        raise ValueError("config.xml is not well-formed XML") from exc
    start = document.find("<protocol-adapters>")
    end = document.find("</protocol-adapters>")
    if start < 0 or end < 0:
        raise ValueError("config.xml has no protocol-adapters element")
    open_len = len("<protocol-adapters>")
    prefix = document[: start + open_len]
    inner = document[start + open_len : end]
    suffix = document[end:]
    kept = [token for token in _TOKEN.findall(inner) if not _is_catalog_adapter_block(token)]
    rendered = [render_catalog_adapter(item) for item in sorted(adapters, key=lambda a: a.server_id)]
    body = "\n".join([*kept, *rendered])
    result = f"{prefix}\n{body}\n    {suffix}" if body else f"{prefix}\n    {suffix}"
    try:
        ET.fromstring(result)
    except ET.ParseError as exc:
        raise ValueError("apply_catalog_adapters produced invalid XML; not writing it") from exc
    return result


def apply_catalog_adapters_file(path: Path, adapters: list[EdgeAdapterInput]) -> None:
    original = path.read_text(encoding="utf-8")
    updated = apply_catalog_adapters(original, adapters)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(path)


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
