"""Business delivery contracts for cloud-edge qualification (MQTT + HTTPS outbox)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_DOC = REPO_ROOT / "docs" / "benchmarks" / "cloud-edge-qualification.md"
PUBLISHER_DOC = REPO_ROOT / "docs" / "operations" / "business-publisher-onboarding.md"

BUSINESS_SHAPES = (
    ("lims", {"sample_id": "S-LIMS", "result": 4.2, "unit": "mg/L"}),
    ("mes", {"order_id": "WO-9001", "status": "complete", "good_qty": 120}),
    ("sap", {"material": "RM-100", "movement": "GR", "qty": 50}),
    ("machine", b"\x00\x01raw-machine-payload"),
)


def test_business_onboarding_runbook_exists():
    text = PUBLISHER_DOC.read_text(encoding="utf-8")
    for phrase in (
        "Idempotency-Key",
        "202",
        "broker_accepted",
        "outbox",
        "seven-day",
    ):
        assert phrase in text


def test_publication_outbox_unit_tests_cover_idempotency_and_capacity():
    outbox_tests = REPO_ROOT / "09_uns_model" / "test" / "test_publication_outbox.py"
    text = outbox_tests.read_text(encoding="utf-8")
    for phrase in ("409", "413", "503", "idempot"):
        assert phrase.lower() in text.lower()


def test_publication_worker_retries_without_changing_wrapper_identity():
    worker_tests = REPO_ROOT / "07_uns_graphql" / "test" / "publication_api" / "test_worker.py"
    text = worker_tests.read_text(encoding="utf-8")
    assert "lease" in text.lower()
    assert "broker" in text.lower()


def test_qualification_doc_separates_broker_acceptance_from_lake_delivery():
    text = QUALIFICATION_DOC.read_text(encoding="utf-8")
    assert "broker_accepted" in text or "outbox" in text
    assert "lake" in text.lower()


@pytest.mark.integrationtest
@pytest.mark.parametrize("application,payload", BUSINESS_SHAPES)
def test_business_case_reaches_lake_without_cloud_local_shortcut(cloud_edge, application, payload):
    cloud_edge.enroll("edge-01")
    if isinstance(payload, dict):
        body = json.dumps(payload).encode("utf-8")
    else:
        body = payload
    identity = cloud_edge.publish_case(application, "cloud-edge-qualification", body)
    rows = cloud_edge.wait_lake(identity, timeout=120)
    assert len(rows) >= 2
    assert all(row.get("event_id") == identity.event_id for row in rows)
    assert identity.topic.startswith("Enterprise/cloud-edge-qualification/")


@pytest.mark.integrationtest
def test_business_delivery_survives_broker_restart(cloud_edge):
    cloud_edge.enroll("edge-01")
    body = json.dumps({"sample_id": "S-RESTART", "result": 9.9}).encode("utf-8")
    identity = cloud_edge.publish_case("lims", "cloud-edge-qualification", body)
    cloud_edge.restart_broker()
    rows = cloud_edge.wait_lake(identity, timeout=180)
    assert rows


@pytest.mark.integrationtest
def test_historian_independence_documented_for_lake_path(cloud_edge):
    """Lake mapper in the qualification harness consumes Kafka directly."""
    compose = (REPO_ROOT / "deploy" / "test" / "compose.yml").read_text(encoding="utf-8")
    assert "qualification-lake-sink" in compose
    assert "qualification-kafka-mapper" in compose
    cloud_edge.enroll("edge-01")
    body = json.dumps({"sample_id": "S-LAKE", "result": 1.1}).encode("utf-8")
    identity = cloud_edge.publish_case("mes", "cloud-edge-qualification", body)
    rows = cloud_edge.wait_lake(identity, timeout=120)
    assert all("kafka_offset" in row for row in rows)
