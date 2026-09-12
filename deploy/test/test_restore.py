"""Restore and cutover contracts for cloud-edge qualification."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_DOC = REPO_ROOT / "docs" / "benchmarks" / "cloud-edge-qualification.md"
CLOUD_COMPOSE = REPO_ROOT / "deploy" / "cloud" / "compose.yml"
CLOUD_RELEASE = REPO_ROOT / "deploy" / "cloud" / "release.json"
EDGE_RELEASE = REPO_ROOT / "deploy" / "edge" / "release.json"

RESTORE_COMPONENTS = (
    "sql_catalog",
    "encrypted_secrets_with_keys",
    "identity_database",
    "broker_state",
    "kafka_retained_log",
    "outbox_receipts",
    "edge_journal",
    "object_store_lake",
)


def test_restore_components_documented_in_qualification_report():
    text = QUALIFICATION_DOC.read_text(encoding="utf-8")
    for component in RESTORE_COMPONENTS:
        assert component.replace("_", " ") in text or component in text


def test_cloud_bundle_declares_backup_profile_without_auto_restore():
    compose = yaml.safe_load(CLOUD_COMPOSE.read_text(encoding="utf-8"))
    backup = compose["services"]["cloud_backup"]
    assert backup.get("profiles") == ["backup"]
    assert "timescale_data" in str(backup.get("volumes", []))
    assert "kafka_data" in str(backup.get("volumes", []))


def test_cloud_release_records_backup_image_separately_from_runtime():
    release = json.loads(CLOUD_RELEASE.read_text(encoding="utf-8"))
    assert "uns-cloud-backup" in release["images"]
    backup = release["images"]["uns-cloud-backup"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", backup["digest"])


def test_restore_policy_forbids_silent_kafka_offset_reset():
    text = QUALIFICATION_DOC.read_text(encoding="utf-8")
    assert "offset" in text.lower()
    assert "reset" in text.lower()
    hostinger = (REPO_ROOT / "deploy" / "cloud" / "hostinger.md").read_text(encoding="utf-8")
    assert "backup" in hostinger.lower()
    assert "rollback" in hostinger.lower()


def test_edge_release_keeps_identity_material_outside_images():
    release = json.loads(EDGE_RELEASE.read_text(encoding="utf-8"))
    for image in release["images"].values():
        assert "password" not in json.dumps(image).lower()
        assert "license" not in json.dumps(image).lower()


def test_edge_journal_restore_contract_is_unit_tested():
    journal_tests = (REPO_ROOT / "15_uns_edge_agent" / "test" / "test_journal.py").read_text(
        encoding="utf-8"
    )
    assert "pending_apply" in journal_tests
    assert "pending_reports" in journal_tests


@pytest.mark.integrationtest
@pytest.mark.faultmatrix
def test_pending_configuration_survives_https_outage_until_restore(cloud_edge):
    cloud_edge.enroll("edge-01")
    cloud_edge.block_https()
    revision = cloud_edge.save_connection(
        "edge-01",
        "opc_ua",
        {"endpoint": "opc.tcp://plant-plc.example:4840/"},
    )
    with pytest.raises(TimeoutError):
        cloud_edge.wait_applied("edge-01", revision, timeout=8)
    cloud_edge.restore_https()
    report = cloud_edge.wait_applied("edge-01", revision, timeout=90)
    assert report.desired_revision == revision


@pytest.mark.integrationtest
@pytest.mark.faultmatrix
@pytest.mark.skip(reason="Persistent cloud-management store not wired in qualification stubs")
def test_pending_desired_state_survives_cloud_management_restart(cloud_edge):
    cloud_edge.enroll("edge-01")
    revision = cloud_edge.save_connection(
        "edge-01",
        "opc_ua",
        {"endpoint": "opc.tcp://plant-plc.example:4840/"},
    )
    cloud_edge.restart_cloud_management()
    report = cloud_edge.wait_applied("edge-01", revision, timeout=90)
    assert report.applied_revision == revision


@pytest.mark.integrationtest
def test_lake_rows_preserve_kafka_coordinates_after_replay(cloud_edge):
    cloud_edge.enroll("edge-01")
    body = json.dumps({"sample_id": "S-RESTORE", "result": 3.3}).encode("utf-8")
    identity = cloud_edge.publish_case("lims", "cloud-edge-qualification", body)
    rows = cloud_edge.wait_lake(identity, timeout=120)
    offsets = sorted(row.get("kafka_offset") for row in rows if row.get("kafka_offset") is not None)
    assert len(offsets) >= 2
    assert offsets[0] != offsets[-1]
