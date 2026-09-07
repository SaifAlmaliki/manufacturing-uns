"""Splice catalog-owned HiveMQ Edge adapters into config.xml without restyling the rest."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

_DATA_TYPES = {"Integer": "DINT", "Double": "REAL", "Boolean": "BOOL", "String": "STRING"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")
_ADAPTER_BLOCK = re.compile(
    r"[ \t]*<protocol-adapter>.*?</protocol-adapter>",
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
    controller_type: str = "S7_1500"
    tags: tuple[EdgeTagInput, ...] = ()


def adapter_id_for(server_id: str) -> str:
    return f"catalog-{server_id}"


def edge_data_type(catalog_type: str | None) -> str:
    return _DATA_TYPES.get(catalog_type or "", "DINT")


def tag_xml_name(node_id: str) -> str:
    cleaned = _SAFE_NAME.sub("_", node_id).strip("_")
    return cleaned or "tag"


def render_catalog_adapter(adapter: EdgeAdapterInput) -> str:
    protocol_id = "eip" if adapter.protocol == "ethernet_ip" else "s7"
    aid = adapter_id_for(adapter.server_id)
    lines = [
        "        <protocol-adapter>",
        f"            <adapterId>{_esc(aid)}</adapterId>",
        f"            <protocolId>{protocol_id}</protocolId>",
        "            <config>",
        f"                <host>{_esc(adapter.host)}</host>",
        f"                <port>{adapter.port}</port>",
    ]
    if protocol_id == "s7":
        lines.append(
            f"                <controllerType>{_esc(adapter.controller_type)}</controllerType>"
        )
    lines.append("            </config>")
    if not adapter.tags:
        lines.extend(["            <northboundMappings/>", "            <tags/>"])
    else:
        lines.append("            <northboundMappings>")
        for tag in adapter.tags:
            name = tag_xml_name(tag.node_id)
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
        addr_el = "tagAddress" if protocol_id == "s7" else "address"
        for tag in adapter.tags:
            name = tag_xml_name(tag.node_id)
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


def apply_catalog_adapters(document: str, adapters: list[EdgeAdapterInput]) -> str:
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
    kept = [
        block
        for block in _ADAPTER_BLOCK.findall(inner)
        if "<adapterId>catalog-" not in block
    ]
    rendered = [render_catalog_adapter(item) for item in sorted(adapters, key=lambda a: a.server_id)]
    body = "\n".join([*kept, *rendered])
    return f"{prefix}\n{body}\n    {suffix}" if body else f"{prefix}\n    {suffix}"


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
