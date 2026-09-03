"""File contracts for HiveMQ Edge as uns_mqtt_broker.

Spec: docs/superpowers/specs/2026-09-03-hivemq-edge-uns-broker-design.md
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HIVEMQ_CONFIG = _REPO_ROOT / "conf" / "hivemq" / "config.xml"
_HIVEMQ_FIXTURE = _REPO_ROOT / "conf" / "hivemq" / "fixtures" / "adapters-unroutable.xml"
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"
_DEV_COMPOSE_FILE = _REPO_ROOT / "docker-compose.dev.yml"
_PROMETHEUS_FILE = (
    _REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"
)


def _xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def test_default_config_exists_and_is_valid_xml():
    root = _xml(_HIVEMQ_CONFIG)
    assert root.tag.endswith("hivemq")


def test_default_config_listens_on_1883():
    ports = [el.text for el in _xml(_HIVEMQ_CONFIG).iter() if el.tag.endswith("port")]
    assert "1883" in ports


def test_default_config_has_no_protocol_adapters():
    root = _xml(_HIVEMQ_CONFIG)
    adapters = [el for el in root.iter() if el.tag.endswith("protocol-adapter")]
    assert adapters == []


def test_default_config_has_no_southbound_mappings():
    root = _xml(_HIVEMQ_CONFIG)
    south = [el for el in root.iter() if el.tag.endswith("southboundMapping")]
    assert south == []


def test_fixture_declares_s7_eip_and_opcua_at_documentation_hosts():
    root = _xml(_HIVEMQ_FIXTURE)
    adapters = [el for el in root.iter() if el.tag.endswith("protocol-adapter")]
    ids = {el.find("protocolId").text for el in adapters}
    assert ids == {"s7", "eip", "opcua"}
    for adapter in adapters:
        config = adapter.find("config")
        host = config.find("host")
        uri = config.find("uri")
        target = (host.text if host is not None else "") + (
            uri.text if uri is not None else ""
        )
        assert "192.0.2.1" in target
        for mapping in adapter.iter():
            if not mapping.tag.endswith("northboundMapping"):
                continue
            assert mapping.find("includeTimestamp").text == "true"
            assert mapping.find("maxQos").text == "1"
    assert [el for el in root.iter() if el.tag.endswith("southboundMapping")] == []
