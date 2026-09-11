"""Cloud-edge pipeline contracts for enrollment, configuration, and lake delivery."""

from __future__ import annotations

import json

import pytest


@pytest.mark.integrationtest
def test_enroll_save_and_apply_round_trip(cloud_edge):
    identity = cloud_edge.enroll("edge-01")
    print(
        "enrolled_identity="
        f"edge_id={identity.edge_id} "
        f"management_subject={identity.management_subject} "
        f"bridge_subject={identity.bridge_subject}"
    )
    revision = cloud_edge.save_connection(
        "edge-01",
        "opc_ua",
        {"endpoint": "opc.tcp://opcua-simulator:4840/cloud-edge-qualification/"},
    )
    print(f"pending_revision={revision}")
    report = cloud_edge.wait_applied("edge-01", revision, timeout=30)
    print(
        "applied_report="
        f"desired_revision={report.desired_revision} "
        f"applied_revision={report.applied_revision} "
        f"phase={report.phase} "
        f"certificate_subject={report.certificate_subject}"
    )
    assert report.applied_revision >= revision
    assert report.phase in {"applied", "applying", "pending"}


@pytest.mark.integrationtest
def test_publish_case_reaches_lake_fixture(cloud_edge):
    body = json.dumps({"sample_id": "S-9001", "result": 4.2, "unit": "mg/L"}).encode("utf-8")
    identity = cloud_edge.publish_case("lims", "cloud-edge-qualification", body)
    print(f"expected_event_identity={identity.event_id} topic={identity.topic}")
    rows = cloud_edge.wait_lake(identity, timeout=120)
    print(
        "lake_rows="
        f"count={len(rows)} "
        f"offsets={[row.get('kafka_offset') for row in rows[:5]]}"
    )
    assert rows
    assert any(row.get("event_id") == identity.event_id for row in rows)


@pytest.mark.integrationtest
def test_block_and_restore_cloud_paths(cloud_edge):
    cloud_edge.block_cloud()
    blocked = cloud_edge.outbound_connectivity_report()
    print(f"blocked_outbound={blocked}")
    cloud_edge.restore_cloud()
    restored = cloud_edge.outbound_connectivity_report()
    print(f"restored_outbound={restored}")
    assert blocked["management"] is False or blocked["mqtt"] is False
    assert restored["management"] is True
    assert restored["mqtt"] is True
