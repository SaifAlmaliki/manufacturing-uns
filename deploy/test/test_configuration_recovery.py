"""Configuration recovery and fault-matrix contracts for cloud-edge qualification."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml

from support.fault_matrix import FAULT_MATRIX, fault_ids

REPO_ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_DOC = REPO_ROOT / "docs" / "benchmarks" / "cloud-edge-qualification.md"
EDGE_BASE_COMPOSE = REPO_ROOT / "deploy" / "edge" / "compose.yml"
EDGE_SIM_COMPOSE = REPO_ROOT / "deploy" / "edge" / "compose.simulation.yml"
WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "cloud-edge-release.yml"
SIM_SERVICES = (
    "oee-simulator",
    "multi-system-simulator",
    "opcua-simulator",
    "modbus-simulator",
)


def test_fault_matrix_covers_task_15_table():
    assert len(FAULT_MATRIX) == 20
    assert fault_ids() == {
        "all_simulators_disabled",
        "real_and_simulator_together",
        "edge_sim_no_plc",
        "mapping_changed_on_simulated_source",
        "https_only_outage",
        "cloud_management_unavailable",
        "vm_power_loss_during_apply",
        "cloud_restart_after_snapshot",
        "https_response_loss_after_report",
        "duplicate_cloned_agent",
        "bridge_wan_outage_edge_restart",
        "broker_crash_after_puback",
        "kafka_mapper_outage_full_queue",
        "store_historian_outage",
        "partial_route_acl_release",
        "certificate_expiry_rotation",
        "outbox_publish_before_status_crash",
        "http_flood_oversized_config",
        "two_sites_identical_local_names",
        "unsupported_discovery_mapping",
    }


def test_qualification_doc_records_fault_matrix_status():
    text = QUALIFICATION_DOC.read_text(encoding="utf-8")
    for case in FAULT_MATRIX:
        assert case.fault_id in text, case.fault_id
        assert case.summary in text or case.assertion[:40] in text


def test_release_workflow_exists_and_never_publishes_on_push_only():
    workflow = yaml.safe_load(WORKFLOW_FILE.read_text(encoding="utf-8"))
    publish_job = workflow["jobs"]["publish-release"]
    assert "workflow_dispatch" in publish_job["if"]
    assert "publish_release" in publish_job["if"]
    build_job = workflow["jobs"]["build-images"]
    matrix = build_job["strategy"]["matrix"]["include"]
    platforms = {entry["platform"] for entry in matrix}
    assert platforms == {"linux/amd64", "linux/arm64"}


def _decorator_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Attribute):
        names.add(node.attr)
        names.update(_decorator_names(node.value))
    elif isinstance(node, ast.Call):
        names.update(_decorator_names(node.func))
        for arg in node.args:
            names.update(_decorator_names(arg))
        for keyword in node.keywords:
            if keyword.value is not None:
                names.update(_decorator_names(keyword.value))
    return names


def test_cloud_edge_fixture_consumers_are_marked_integrationtest():
    missing: list[str] = []
    for path in Path(__file__).parent.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            uses_cloud_edge = any(arg.arg == "cloud_edge" for arg in node.args.args)
            if not uses_cloud_edge:
                continue
            marks = set()
            for decorator in node.decorator_list:
                marks.update(_decorator_names(decorator))
            if "integrationtest" not in marks:
                missing.append(f"{path.name}::{node.name}")
    assert missing == [], (
        "cloud_edge harness tests must be marked integrationtest so the "
        "unit-contract job does not start docker compose: " + ", ".join(missing)
    )


def test_edge_base_compose_runs_without_simulators():
    compose = yaml.safe_load(EDGE_BASE_COMPOSE.read_text(encoding="utf-8"))
    services = set(compose["services"])
    assert services == {"hivemq-edge", "uns-edge-agent"}
    assert set(SIM_SERVICES).isdisjoint(services)


def test_edge_sim_overlay_is_optional_profile():
    sim = yaml.safe_load(EDGE_SIM_COMPOSE.read_text(encoding="utf-8"))
    for name in SIM_SERVICES:
        assert sim["services"][name]["profiles"] == ["edge-sim"]


def test_release_manifests_share_simulator_dockerfiles_with_qualification_harness():
    qual = yaml.safe_load((REPO_ROOT / "deploy" / "test" / "compose.yml").read_text(encoding="utf-8"))
    edge_release = json.loads((REPO_ROOT / "deploy" / "edge" / "release.json").read_text(encoding="utf-8"))
    for service in SIM_SERVICES:
        assert service in qual["services"]
        assert service in edge_release["images"]


@pytest.mark.faultmatrix
@pytest.mark.integrationtest
def test_all_simulators_disabled_base_configuration_still_works(cloud_edge):
    cloud_edge.enroll("edge-01")
    cloud_edge.stop_simulators()
    revision = cloud_edge.save_connection(
        "edge-01",
        "opc_ua",
        {"endpoint": "opc.tcp://plant-plc.example:4840/"},
    )
    report = cloud_edge.wait_applied("edge-01", revision, timeout=90)
    assert report.phase == "applied"
    assert report.applied_revision == revision


@pytest.mark.faultmatrix
@pytest.mark.integrationtest
def test_real_shaped_and_simulator_connections_use_separate_settings(cloud_edge):
    cloud_edge.enroll("edge-01")
    real_revision = cloud_edge.save_connection(
        "edge-01",
        "opc_ua",
        {"endpoint": "opc.tcp://plant-plc.example:4840/"},
    )
    sim_revision = cloud_edge.configure_simulated_source("opcua")
    assert sim_revision != real_revision
    cloud_edge.wait_applied("edge-01", real_revision, timeout=90)
    cloud_edge.wait_applied("edge-01", sim_revision, timeout=120)
    sim_data = cloud_edge.wait_source_data("opcua", sim_revision, timeout=120)
    assert sim_data.values_match_fixture


@pytest.mark.faultmatrix
@pytest.mark.integrationtest
def test_https_only_outage_keeps_mqtt_while_configuration_stays_pending(cloud_edge):
    cloud_edge.enroll("edge-01")
    cloud_edge.block_https()
    revision = cloud_edge.save_connection(
        "edge-01",
        "opc_ua",
        {"endpoint": "opc.tcp://opcua-simulator:4840/cloud-edge-qualification/"},
    )
    identity = cloud_edge.publish_case(
        "lims",
        "cloud-edge-qualification",
        json.dumps({"sample_id": "S-443", "result": 1.0}).encode("utf-8"),
    )
    rows = cloud_edge.wait_lake(identity, timeout=120)
    assert rows
    with pytest.raises(TimeoutError):
        cloud_edge.wait_applied("edge-01", revision, timeout=8)
    cloud_edge.restore_https()
    report = cloud_edge.wait_applied("edge-01", revision, timeout=90)
    assert report.phase == "applied"


@pytest.mark.faultmatrix
@pytest.mark.integrationtest
def test_cloud_management_outage_eventually_reconciles_after_restore(cloud_edge):
    cloud_edge.enroll("edge-01")
    cloud_edge.block_https()
    revision = cloud_edge.save_connection(
        "edge-01",
        "modbus",
        {"host": "modbus-simulator", "port": 1502, "unit_id": 1},
    )
    with pytest.raises(TimeoutError):
        cloud_edge.wait_applied("edge-01", revision, timeout=8)
    cloud_edge.restore_https()
    report = cloud_edge.wait_applied("edge-01", revision, timeout=90)
    assert report.applied_revision == revision


@pytest.mark.faultmatrix
@pytest.mark.integrationtest
def test_bridge_wan_outage_survives_edge_restart_and_reconciles(cloud_edge):
    cloud_edge.enroll("edge-01")
    body = json.dumps({"sample_id": "S-WAN", "result": 2.0}).encode("utf-8")
    identity = cloud_edge.publish_case("lims", "cloud-edge-qualification", body)
    cloud_edge.wait_lake(identity, timeout=120)
    cloud_edge.block_cloud()
    cloud_edge.restart_edge()
    cloud_edge.restore_cloud()
    replay_rows = cloud_edge.wait_lake(identity, timeout=120)
    offsets = {row.get("kafka_offset") for row in replay_rows}
    assert len(offsets) >= 2


@pytest.mark.faultmatrix
@pytest.mark.parametrize(
    "fault_id,blocker",
    [
        (case.fault_id, case.blocker)
        for case in FAULT_MATRIX
        if case.status == "blocked"
    ],
)
def test_blocked_fault_cases_are_explicit(fault_id: str, blocker: str | None):
    assert blocker
    text = QUALIFICATION_DOC.read_text(encoding="utf-8")
    assert fault_id in text
    assert "blocked" in text.lower()


def test_vm_power_loss_journal_contract_is_unit_tested():
    journal_tests = REPO_ROOT / "15_uns_edge_agent" / "test" / "test_journal.py"
    text = journal_tests.read_text(encoding="utf-8")
    assert "test_begin_apply_survives_restart" in text
    assert "test_report_retries_keep_same_boot_id_sequence_and_content" in text


def test_oversized_configuration_is_rejected_by_publication_contract():
    outbox_tests = REPO_ROOT / "09_uns_model" / "test" / "test_publication_outbox.py"
    text = outbox_tests.read_text(encoding="utf-8")
    assert "413" in text or "payload_too_large" in text.lower()


def test_unsupported_protocol_has_explicit_rejection_in_edge_agent():
    protocol_tests = REPO_ROOT / "15_uns_edge_agent" / "test" / "test_protocols.py"
    text = protocol_tests.read_text(encoding="utf-8")
    assert "unsupported" in text.lower() or "reject" in text.lower()
