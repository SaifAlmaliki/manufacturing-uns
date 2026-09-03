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


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))


def test_broker_image_is_hivemq_edge():
    assert _compose()["services"]["uns_mqtt_broker"]["image"] == "hivemq/hivemq-edge:latest"


def test_broker_publishes_mqtt_1883_and_console_18080():
    ports = _compose()["services"]["uns_mqtt_broker"]["ports"]
    assert "1883:1883" in ports
    assert "18080:8080" in ports
    assert "8080:8080" not in ports
    assert "1884:1884" not in ports
    assert "8090:8090" not in ports


def test_broker_mounts_repo_config_read_only():
    volumes = _compose()["services"]["uns_mqtt_broker"]["volumes"]
    assert "./conf/hivemq/config.xml:/opt/hivemq/conf/config.xml:ro" in volumes


def test_broker_healthcheck_does_not_call_emqx():
    check = _compose()["services"]["uns_mqtt_broker"]["healthcheck"]["test"]
    joined = " ".join(check)
    assert "emqx" not in joined
    assert "1883" in joined


def _dev_compose() -> dict:
    # Compose merge tags (!reset) are not understood by PyYAML; strip for file contracts.
    text = _DEV_COMPOSE_FILE.read_text(encoding="utf-8").replace(": !reset\n", ":\n")
    return yaml.safe_load(text)


def _prometheus() -> dict:
    return yaml.safe_load(_PROMETHEUS_FILE.read_text(encoding="utf-8"))


def test_opcua_client_is_not_a_compose_service():
    assert "opcua_client" not in _compose()["services"]
    assert "opcua_spool" not in (_compose().get("volumes") or {})


def test_prometheus_does_not_scrape_opcua_client():
    jobs = {job["job_name"]: job for job in _prometheus()["scrape_configs"]}
    assert "uns_opcua" not in jobs
    targets = [
        t
        for job in _prometheus()["scrape_configs"]
        for t in job["static_configs"][0]["targets"]
    ]
    assert "opcua_client:9093" not in targets


def test_prometheus_compose_does_not_depend_on_opcua_client():
    assert "opcua_client" not in _compose()["services"]["uns_prometheus"]["depends_on"]
    assert "opcua_client" not in _dev_compose()["services"]["uns_prometheus"]["depends_on"]
