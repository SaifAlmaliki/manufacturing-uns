"""Cloud-authored OPC UA / Modbus configuration round-trip against real protocol servers."""

from __future__ import annotations

import pytest


@pytest.mark.integrationtest
@pytest.mark.parametrize("protocol", ["opcua", "modbus"])
def test_cloud_configuration_changes_simulated_collection(cloud_edge, protocol):
    cloud_edge.enroll("edge-01")
    revision = cloud_edge.configure_simulated_source(protocol)
    report = cloud_edge.wait_applied("edge-01", revision, timeout=120)
    assert report.applied_revision == revision
    first = cloud_edge.wait_source_data(protocol, revision, timeout=120)
    assert first.values_match_fixture
    assert first.lake_payloads_match_local_mqtt
    changed = cloud_edge.change_simulated_mapping(protocol)
    assert changed > revision
    cloud_edge.wait_applied("edge-01", changed, timeout=120)
    next_data = cloud_edge.wait_source_data(
        protocol,
        changed,
        timeout=120,
        expect_remapped=True,
    )
    assert next_data.uses_updated_mapping
    assert next_data.values_match_fixture
    assert next_data.lake_payloads_match_local_mqtt
