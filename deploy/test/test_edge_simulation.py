"""Compose contracts for the optional edge-sim hardware-free commissioning overlay."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EDGE_DIR = REPO_ROOT / "deploy" / "edge"
BASE_COMPOSE = EDGE_DIR / "compose.yml"
SIM_COMPOSE = EDGE_DIR / "compose.simulation.yml"
RELEASE_FILE = EDGE_DIR / "release.json"
SIM_CONNECTIONS = EDGE_DIR / "simulation" / "connections.json"
SIM_ROUTES = EDGE_DIR / "simulation" / "publication-routes.yaml"

SIM_SERVICES = (
    "oee-simulator",
    "multi-system-simulator",
    "opcua-simulator",
    "modbus-simulator",
)
CLOUD_ENV_MARKERS = (
    "CLOUD_MQTT",
    "cloud-mqtt",
    "CLOUD_MANAGEMENT",
    "cloud.example",
    "UNS_EDGE_CLOUD_URL",
)
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


@pytest.fixture
def base_compose() -> dict:
    return yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture
def sim_compose() -> dict:
    return yaml.safe_load(SIM_COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture
def merged_compose(tmp_path: Path) -> dict:
    project_dir = tmp_path / "uns-edge"
    secrets_dir = project_dir / "simulation" / "secrets"
    secrets_dir.mkdir(parents=True)
    for name in ("compose.yml", "compose.simulation.yml"):
        (project_dir / name).write_text(
            (EDGE_DIR / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (project_dir / "agent.env").write_text(
        "UNS_EDGE_CLOUD_URL=https://cloud.example.test\n",
        encoding="utf-8",
    )
    (secrets_dir / "mqtt-sim.env").write_text(
        "MQTT_USERNAME=edge-sim\nMQTT_PASSWORD=fixture-secret\n",
        encoding="utf-8",
    )
    (secrets_dir / "mqtt-tls.env").write_text(
        "MQTT_CA_FILE=/run/secrets/edge-mqtt-ca.pem\n",
        encoding="utf-8",
    )
    (project_dir / "secrets").mkdir(exist_ok=True)
    (project_dir / "secrets" / "edge-api.env").write_text(
        "UNS_EDGE_API_USERNAME=fixture\nUNS_EDGE_API_PASSWORD=fixture\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(project_dir),
            "-f",
            str(project_dir / "compose.yml"),
            "-f",
            str(project_dir / "compose.simulation.yml"),
            "--profile",
            "edge-sim",
            "config",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)


def test_simulation_overlay_files_exist():
    required = [
        SIM_COMPOSE,
        SIM_CONNECTIONS,
        SIM_ROUTES,
        EDGE_DIR / "simulation" / "README.md",
        EDGE_DIR / "simulation" / "secrets" / "mqtt-sim.env.example",
        EDGE_DIR / "simulation" / "secrets" / "mqtt-tls.env.example",
    ]
    for path in required:
        assert path.is_file(), path


def test_base_compose_has_only_edge_and_agent(base_compose):
    assert set(base_compose["services"]) == {"hivemq-edge", "uns-edge-agent"}


def test_overlay_adds_four_profiled_simulators(sim_compose):
    services = sim_compose["services"]
    for name in SIM_SERVICES:
        service = services[name]
        assert service["profiles"] == ["edge-sim"]


def test_overlay_defines_internal_sim_ot_network(sim_compose, merged_compose):
    assert sim_compose["networks"]["sim-ot"]["internal"] is True
    assert "sim-ot" in merged_compose["networks"]
    assert merged_compose["networks"]["sim-ot"]["internal"] is True


def test_hivemq_edge_joins_sim_ot_but_agent_does_not(merged_compose):
    edge_networks = merged_compose["services"]["hivemq-edge"]["networks"]
    agent_networks = merged_compose["services"]["uns-edge-agent"]["networks"]
    assert "sim-ot" in edge_networks
    assert "sim-ot" not in agent_networks


def test_simulators_have_no_host_ports(merged_compose):
    for name in SIM_SERVICES:
        assert not merged_compose["services"][name].get("ports")


def test_simulators_have_no_cloud_credentials_or_broker(merged_compose):
    for name in SIM_SERVICES:
        rendered = yaml.safe_dump(merged_compose["services"][name])
        for marker in CLOUD_ENV_MARKERS:
            assert marker not in rendered
    for name in ("oee-simulator", "multi-system-simulator"):
        env = merged_compose["services"][name].get("environment", {})
        assert env.get("MQTT_HOST") == "hivemq-edge"
        assert env.get("MQTT_PORT") == "8883"
        assert env.get("H", env.get("MQTT_HOST")) == "hivemq-edge"
        assert str(env.get("P", env.get("MQTT_PORT"))) == "8883"


def test_simulators_use_secret_files_not_inline_passwords(merged_compose):
    for name in ("oee-simulator", "multi-system-simulator"):
        service = merged_compose["services"][name]
        secrets = {secret if isinstance(secret, str) else secret["source"] for secret in service["secrets"]}
        assert "mqtt_sim_credentials" in secrets
        assert "mqtt_sim_tls" in secrets
        rendered = yaml.safe_dump(service)
        assert "password=" not in rendered.lower()


def test_simulators_have_no_docker_socket(merged_compose):
    for name in SIM_SERVICES:
        mounts = merged_compose["services"][name].get("volumes") or []
        assert "/var/run/docker.sock" not in " ".join(str(mount) for mount in mounts)


def test_release_json_includes_simulator_images():
    release = json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    for name in SIM_SERVICES:
        image = release["images"][name]
        assert DIGEST_PATTERN.fullmatch(image["digest"])
        service_image = yaml.safe_load(SIM_COMPOSE.read_text(encoding="utf-8"))["services"][name]["image"]
        assert service_image.endswith(image["digest"])


def test_sample_connections_target_fixture_endpoints():
    connections = json.loads(SIM_CONNECTIONS.read_text(encoding="utf-8"))
    assert "opc.tcp://opcua-simulator:4840/uns-sim/" in connections["opcua"]["initial"]["endpoint"]
    assert connections["modbus"]["initial"]["host"] == "modbus-simulator"
    assert connections["modbus"]["initial"]["address_convention"] == "zero_based_holding_register"


def test_publication_routes_scope_edge_simulation_namespace():
    routes = yaml.safe_load(SIM_ROUTES.read_text(encoding="utf-8"))
    assert routes["site_id"] == "edge-simulation"
    filters = [route["topic_filter"] for route in routes["routes"]]
    assert all("EdgeSimulation" in filter_ for filter_ in filters)
