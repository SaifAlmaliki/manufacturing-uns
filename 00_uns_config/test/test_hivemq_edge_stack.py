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
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_MQTT_SERVICE_WORKFLOWS = (
    "uns_graphdb-app.yml",
    "uns_historian-app.yml",
    "uns_kafka-app.yml",
    "uns_graphql-app.yml",
    "uns_sparkplugb-app.yml",
    "uns_mqtt-app.yml",
)


def _xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def test_default_config_exists_and_is_valid_xml():
    root = _xml(_HIVEMQ_CONFIG)
    assert root.tag.endswith("hivemq")


def test_default_config_listens_on_1883():
    ports = [el.text for el in _xml(_HIVEMQ_CONFIG).iter() if el.tag.endswith("port")]
    assert "1883" in ports


def test_default_config_binds_admin_http_on_8080_all_interfaces():
    root = _xml(_HIVEMQ_CONFIG)
    listeners = [el for el in root.iter() if el.tag.endswith("http-listener")]
    assert listeners, "admin-api http-listener missing"
    listener = listeners[0]
    ports = [el.text for el in listener.iter() if el.tag.endswith("port")]
    binds = [el.text for el in listener.iter() if el.tag.endswith("bind-address")]
    assert "8080" in ports
    assert "0.0.0.0" in binds


def test_default_config_has_no_protocol_adapters():
    """The shipped simulation adapter may stay; no catalog or plant PLC/OPC UA adapter may."""
    root = _xml(_HIVEMQ_CONFIG)
    adapters = [el for el in root.iter() if el.tag.endswith("protocol-adapter")]
    adapter_ids = {el.find("adapterId").text for el in adapters}
    protocol_ids = {el.find("protocolId").text for el in adapters}
    assert not any(adapter_id.startswith("catalog-") for adapter_id in adapter_ids)
    assert protocol_ids <= {"simulation"}


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


def _workflow_mqtt_services(name: str) -> list[dict]:
    data = yaml.safe_load((_WORKFLOWS_DIR / name).read_text(encoding="utf-8"))
    found: list[dict] = []
    for job in data["jobs"].values():
        mqtt = (job.get("services") or {}).get("uns_mqtt")
        if mqtt is not None:
            found.append(mqtt)
    return found


def test_github_actions_mqtt_service_is_hivemq_edge():
    """GHA cannot mount conf/hivemq; the stock Edge image still listens on 1883 and allows '#'."""
    for name in _MQTT_SERVICE_WORKFLOWS:
        services = _workflow_mqtt_services(name)
        assert services, f"{name} has no uns_mqtt service"
        for mqtt in services:
            assert mqtt["image"] == "hivemq/hivemq-edge:latest", name
            ports = mqtt["ports"]
            assert "1883:1883" in ports
            assert "8080:8080" not in ports
            assert "1884:1884" not in ports
            env = mqtt.get("env") or {}
            assert "EMQX_AUTHORIZATION__NO_MATCH" not in env
            options = mqtt.get("options") or ""
            assert "emqx" not in options.lower()
            assert "1883" in options


def test_github_actions_workflows_do_not_use_emqx_image():
    for path in _WORKFLOWS_DIR.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "emqx/emqx" not in text, path.name
        assert "emqx_docker-compose.yaml" not in text, path.name
        assert "eclipse-mosquitto" not in text, path.name
        assert "mosquitto_docker-compose.yaml" not in text, path.name


def test_mqtt_client_module_has_no_sideline_broker_fixture():
    """Client library CI uses the same Edge service as mappers, not Mosquitto/EMQX extras."""
    fixture = _REPO_ROOT / "02_mqtt-cluster" / "test" / "local_mqtt"
    assert not fixture.exists()


def test_devcontainer_starts_hivemq_edge_not_emqx():
    text = (_REPO_ROOT / ".devcontainer" / "devcontainersetup.sh").read_text(encoding="utf-8")
    assert "hivemq/hivemq-edge" in text
    assert "emqx/emqx" not in text
    assert "local_mqtt" not in text
    assert "uns_mqtt_broker" in text


def _dev_compose() -> dict:
    # Compose merge tags (!reset) are not understood by PyYAML; strip for file contracts.
    text = _DEV_COMPOSE_FILE.read_text(encoding="utf-8").replace(": !reset\n", ":\n")
    return yaml.safe_load(text)


def _prometheus() -> dict:
    return yaml.safe_load(_PROMETHEUS_FILE.read_text(encoding="utf-8"))


def test_opcua_client_is_a_compose_service():
    assert "opcua_client" in _compose()["services"]
    assert "opcua_spool" in (_compose().get("volumes") or {})
    build = _compose()["services"]["opcua_client"]["build"]
    assert build["dockerfile"] == "./10_uns_opcua/Dockerfile"


def test_opcua_client_is_legacy_opcua_profile_only():
    service = _compose()["services"]["opcua_client"]
    assert service.get("profiles") == ["legacy-opcua"]


def test_prometheus_does_not_depend_on_opcua_client():
    assert "opcua_client" not in _compose()["services"]["uns_prometheus"]["depends_on"]
    dev_deps = _dev_compose()["services"]["uns_prometheus"]["depends_on"]
    if isinstance(dev_deps, dict):
        assert "opcua_client" not in dev_deps
    else:
        assert "opcua_client" not in dev_deps


def test_prometheus_scrapes_opcua_client():
    jobs = {job["job_name"]: job for job in _prometheus()["scrape_configs"]}
    assert "uns_opcua" in jobs
    targets = jobs["uns_opcua"]["static_configs"][0]["targets"]
    assert "opcua_client:9093" in targets


def test_dev_overlay_maps_host_opc_servers_for_edge_adapters():
    """Edge OPC UA adapters poll PLCs on the host; the broker container needs the same DNS
    aliases as graphql_server for desktop NetBIOS names and host.docker.internal."""
    hosts = _dev_compose()["services"]["uns_mqtt_broker"]["extra_hosts"]
    assert "desktop-h4hdql2:host-gateway" in hosts
    assert "host.docker.internal:host-gateway" in hosts
