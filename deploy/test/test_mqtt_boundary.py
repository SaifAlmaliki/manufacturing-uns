"""MQTT boundary contracts for the central broker isolated-qualification profile."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FILE = REPO_ROOT / "deploy" / "release-contract.json"
BROKER_CONFIG = REPO_ROOT / "deploy" / "cloud" / "broker" / "config.xml"
AUTH_CONFIG = REPO_ROOT / "deploy" / "cloud" / "broker" / "authorization" / "config.xml"
PERMISSIONS = REPO_ROOT / "deploy" / "cloud" / "broker" / "authorization" / "permissions.xml"


def _release_contract() -> dict:
    return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))


def _broker_qualified() -> bool:
    contract = _release_contract()
    return (
        contract.get("qualification_status") == "qualified"
        and contract.get("broker_profile") != "isolated-qualification"
        and contract.get("authentication_extension", {}).get("status") == "verified"
    )


@pytest.fixture
def broker_qualified() -> bool:
    return _broker_qualified()


def test_broker_config_requires_tls_and_client_certificates():
    config = BROKER_CONFIG.read_text(encoding="utf-8")
    assert "tls-tcp-listener" in config
    assert "<port>8883</port>" in config
    assert "client-authentication-mode>REQUIRED" in config
    assert "TLSv1.3" in config
    assert "TLSv1.2" in config


def test_broker_config_refuses_startup_without_authorization_extension():
    config = BROKER_CONFIG.read_text(encoding="utf-8")
    assert "hivemq-enterprise-security-extension" in config
    assert "authorization/config.xml" in config
    assert AUTH_CONFIG.is_file()
    assert PERMISSIONS.is_file()


def test_bridge_principals_are_publish_only():
    permissions = PERMISSIONS.read_text(encoding="utf-8")
    assert 'id="edge-01-bridge"' in permissions
    assert "<subscribe deny=\"true\"/>" in permissions
    assert "Enterprise/PlantA/LIMS/results" in permissions


def test_release_contract_documents_blocked_live_broker_qualification():
    contract = _release_contract()
    assert contract["qualification_status"] == "unqualified"
    assert contract["broker_profile"] == "isolated-qualification"
    blockers = contract["qualification_blockers"]
    assert any("broker" in item.lower() or "hivemq" in item.lower() for item in blockers)
    assert contract["authentication_extension"]["status"] == "blocked"


@pytest.mark.integrationtest
@pytest.mark.skipif(
    not _broker_qualified(),
    reason="Live central broker qualification blocked — see deploy/release-contract.json",
)
def test_edge_a_can_publish_only_its_registered_filters():
    pytest.fail("Qualified broker harness not wired in Task 10")


@pytest.mark.integrationtest
@pytest.mark.skipif(
    not _broker_qualified(),
    reason="Live central broker qualification blocked — see deploy/release-contract.json",
)
def test_anonymous_or_revoked_certificate_is_refused():
    pytest.fail("Qualified broker harness not wired in Task 10")


@pytest.mark.integrationtest
@pytest.mark.skipif(
    not _broker_qualified(),
    reason="Live central broker qualification blocked — see deploy/release-contract.json",
)
def test_active_revoked_client_stops_publishing_within_revocation_bound():
    pytest.fail("Qualified broker harness not wired in Task 10")
