"""Validate deploy/release-contract.json for the cloud-edge qualification programme."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FILE = REPO_ROOT / "deploy" / "release-contract.json"


@pytest.fixture
def release_contract() -> dict:
    return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))


def test_release_contract_file_exists():
    assert CONTRACT_FILE.is_file()


def test_release_contract_has_required_top_level_fields(release_contract):
    required = {
        "contract_version",
        "release_id",
        "qualification_status",
        "broker_profile",
        "edge_api_version",
        "supported_protocols",
        "buffering_license_required",
        "images",
        "allowed_deployment_profiles",
    }
    assert required.issubset(release_contract)


def test_release_contract_is_unqualified_for_isolated_profile(release_contract):
    assert release_contract["qualification_status"] == "unqualified"
    assert release_contract["broker_profile"] == "isolated-qualification"
    assert "isolated-qualification" in release_contract["allowed_deployment_profiles"]


def test_release_contract_records_blocked_broker_and_license_gates(release_contract):
    blockers = release_contract["qualification_blockers"]
    assert any("license" in item.lower() for item in blockers)
    assert any("digest" in item.lower() or "pinned" in item.lower() for item in blockers)
    assert release_contract["buffering_license_status"] == "blocked"
    assert all(image["status"] == "blocked" for image in release_contract["images"])


def test_release_contract_edge_api_paths_match_v1_surface(release_contract):
    assert release_contract["edge_api_version"] == "v1"
    assert "/api/v1/auth/authenticate" in release_contract["edge_api_paths"]
    assert "/api/v1/management/protocol-adapters/adapters" in release_contract["edge_api_paths"]


def test_qualification_compose_uses_shared_simulator_images():
    import yaml

    compose = yaml.safe_load((REPO_ROOT / "deploy" / "test" / "compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["oee-simulator"]["build"]["dockerfile"] == "conf/simulator/Dockerfile"
    assert services["multi-system-simulator"]["build"]["dockerfile"] == "conf/simulator/Dockerfile.multi-system"
    assert services["opcua-simulator"]["build"]["dockerfile"] == "conf/simulator/protocols/Dockerfile.opcua"
    assert services["modbus-simulator"]["build"]["dockerfile"] == "conf/simulator/protocols/Dockerfile.modbus"
    assert "cloud" in compose["networks"]
    assert "dmz" in compose["networks"]
    assert "ot" in compose["networks"]


def test_release_contract_includes_modbus_and_implemented_outbox(release_contract):
    assert "modbus_tcp" in release_contract["supported_protocols"]
    assert "supported_protocols_planned" not in release_contract
    assert release_contract["adapter_api_schemas"]["modbus"]["status"] == "code-mapped"
    assert release_contract["rpo"]["sql_outbox_persistence"]["status"] == "implemented"
    blockers = " ".join(release_contract["qualification_blockers"]).lower()
    assert "outbox not implemented" not in blockers


def test_qualification_compose_mqtt_simulators_target_hivemq_edge_8883():
    import yaml

    compose = yaml.safe_load((REPO_ROOT / "deploy" / "test" / "compose.yml").read_text(encoding="utf-8"))
    oee = compose["services"]["oee-simulator"]["environment"]
    multi = compose["services"]["multi-system-simulator"]["environment"]
    assert oee["H"] == "hivemq-edge"
    assert str(oee["P"]) == "8883"
    assert multi["MQTT_HOST"] == "hivemq-edge"
    assert str(multi["MQTT_PORT"]) == "8883"
    health = " ".join(compose["services"]["hivemq-edge"]["healthcheck"]["test"])
    assert "8883" in health
    assert "1883" not in health
