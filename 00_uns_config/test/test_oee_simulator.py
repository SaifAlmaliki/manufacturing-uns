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
    assert service["environment"]["H"] == "uns_mqtt_broker"
    assert service["depends_on"]["uns_mqtt_broker"]["condition"] == "service_healthy"


def test_oee_simulator_script_runs_in_container_or_via_docker():
    text = SIMULATOR_SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "/opt/hivemq/tools/mqtt-cli/bin/mqtt" in text
    assert "MQTT_BROKER_CONTAINER" in text
