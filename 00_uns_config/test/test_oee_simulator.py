"""Compose contract for the optional OEE demo MQTT publisher."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
SIMULATOR_SCRIPT = REPO_ROOT / "HiveMQ-Simulator.sh"


def test_oee_simulator_is_opt_in_compose_service():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    service = compose["services"]["oee_mqtt_simulator"]

    assert service["profiles"] == ["oee-demo"]
    assert service["build"]["dockerfile"] == "./conf/simulator/Dockerfile"
    assert service["depends_on"]["uns_mqtt_broker"]["condition"] == "service_healthy"
    dockerfile = (REPO_ROOT / "conf" / "simulator" / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV H=uns_mqtt_broker" in dockerfile


def test_oee_simulator_script_runs_in_container_or_via_docker():
    text = SIMULATOR_SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "hivemq/mqtt-cli" in text
    assert "MQTT_BROKER_CONTAINER" in text


def test_oee_simulator_compose_image_bundles_mqtt_cli():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    service = compose["services"]["oee_mqtt_simulator"]
    assert service["build"]["dockerfile"] == "./conf/simulator/Dockerfile"
