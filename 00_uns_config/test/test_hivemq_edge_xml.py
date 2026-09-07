from pathlib import Path

import pytest

from uns_config.hivemq_edge_xml import (
    EdgeAdapterInput,
    EdgeTagInput,
    adapter_id_for,
    apply_catalog_adapters,
    apply_catalog_adapters_file,
    edge_data_type,
    render_catalog_adapter,
    tag_xml_name,
)

_REPO = Path(__file__).resolve().parents[2]
_CONFIG = (_REPO / "conf" / "hivemq" / "config.xml").read_text(encoding="utf-8")


def _s7(**overrides) -> EdgeAdapterInput:
    tags = overrides.pop("tags", (
        EdgeTagInput("%ID103", "Speed", "Acme/Test/Area/Line/Cell/S7/ProcessValue/Speed", "Integer"),
    ))
    return EdgeAdapterInput(
        server_id=overrides.pop("server_id", "fixture-s7"),
        protocol="s7",
        host=overrides.pop("host", "192.0.2.1"),
        port=overrides.pop("port", 102),
        controller_type=overrides.pop("controller_type", "S7_1500"),
        tags=tags,
    )


def test_adapter_id_prefix():
    assert adapter_id_for("srv_ab") == "catalog-srv_ab"


def test_edge_data_type_map():
    assert edge_data_type("Integer") == "DINT"
    assert edge_data_type("Double") == "REAL"
    assert edge_data_type("Boolean") == "BOOL"
    assert edge_data_type("String") == "STRING"
    assert edge_data_type(None) == "DINT"


def test_render_s7_structural_indent():
    rendered = render_catalog_adapter(_s7())
    assert "\t" not in rendered
    lines = rendered.splitlines()
    assert lines[0] == "        <protocol-adapter>"
    assert lines[-1] == "        </protocol-adapter>"
    for line in lines:
        if line.strip().startswith("<"):
            leading = len(line) - len(line.lstrip(" "))
            assert leading % 4 == 0

    def _section(tag: str) -> list[str]:
        open_tag = f"<{tag}>"
        close_tag = f"</{tag}>"
        start = rendered.index(open_tag) + len(open_tag)
        end = rendered.index(close_tag, start)
        block = rendered[start:end]
        return [line.strip() for line in block.splitlines() if line.strip()]

    adapter_children = [
        line.split(">")[0].split("<")[-1].rstrip("/")
        for line in lines
        if line.startswith("            <") and not line.startswith("                ")
    ]
    assert adapter_children == [
        "adapterId",
        "protocolId",
        "config",
        "/config",
        "northboundMappings",
        "/northboundMappings",
        "tags",
        "/tags",
    ]
    config_children = [
        line.split(">")[0].split("<")[-1]
        for line in _section("config")
        if line.startswith("<")
    ]
    assert config_children == ["host", "port", "controllerType"]
    mapping_children = [
        line.split(">")[0].split("<")[-1]
        for line in _section("northboundMapping")
        if line.startswith("<")
    ]
    assert mapping_children == ["topic", "tagName", "maxQos", "includeTimestamp"]
    assert "<adapterId>catalog-fixture-s7</adapterId>" in rendered
    assert f"<tagName>{tag_xml_name('%ID103')}</tagName>" in rendered


def test_declaration_and_simulation_survive_apply(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text(_CONFIG, encoding="utf-8")
    apply_catalog_adapters_file(path, [_s7(server_id="srv1")])
    text = path.read_text(encoding="utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8" ?>')
    assert "HiveMQ Edge simulators" in text
    assert "<adapterId>sim</adapterId>" in text
    assert "<protocolId>s7</protocolId>" in text
    assert "<adapterId>catalog-srv1</adapterId>" in text
    assert "southbound" not in text.lower()
    # 4-space indent on catalog adapter
    assert "\n        <protocol-adapter>\n            <adapterId>catalog-srv1</adapterId>" in text


def test_replace_same_adapter_id_does_not_duplicate(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text(_CONFIG, encoding="utf-8")
    apply_catalog_adapters_file(path, [_s7(server_id="srv1", host="10.0.0.1")])
    apply_catalog_adapters_file(path, [_s7(server_id="srv1", host="10.0.0.2")])
    text = path.read_text(encoding="utf-8")
    assert text.count("<adapterId>catalog-srv1</adapterId>") == 1
    assert "<host>10.0.0.2</host>" in text


def test_delete_catalog_adapter_keeps_simulation(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text(_CONFIG, encoding="utf-8")
    apply_catalog_adapters_file(path, [_s7(server_id="srv1")])
    apply_catalog_adapters_file(path, [])
    text = path.read_text(encoding="utf-8")
    assert "catalog-srv1" not in text
    assert "<adapterId>sim</adapterId>" in text


def test_empty_tags_self_close():
    xml = render_catalog_adapter(_s7(tags=()))
    assert "<northboundMappings/>" in xml
    assert "<tags/>" in xml


def test_eip_protocol_id_is_eip():
    adapter = EdgeAdapterInput(
        server_id="e1",
        protocol="ethernet_ip",
        host="192.0.2.1",
        port=44818,
        tags=(EdgeTagInput("Program:MainProgram.Count", "Count", "Acme/Test/Count", "Integer"),),
    )
    xml = render_catalog_adapter(adapter)
    assert "<protocolId>eip</protocolId>" in xml
    assert "<address>Program:MainProgram.Count</address>" in xml
    assert "<tagAddress>" not in xml


def test_broken_xml_is_not_written(tmp_path: Path):
    path = tmp_path / "config.xml"
    path.write_text("<not-hivemq>", encoding="utf-8")
    with pytest.raises(ValueError):
        apply_catalog_adapters_file(path, [_s7()])
    assert path.read_text(encoding="utf-8") == "<not-hivemq>"
