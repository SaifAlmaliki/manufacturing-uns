"""Network boundary contracts for the isolated cloud-edge qualification harness."""

from __future__ import annotations

import pytest


def test_cloud_cannot_dial_dmz_management(cloud_edge):
    assert cloud_edge.local_management_is_healthy()
    assert not cloud_edge.cloud_can_open_dmz_management()
    cloud_edge.assert_cloud_management_denied_by_firewall()


@pytest.mark.integrationtest
def test_dmz_outbound_cloud_paths_work(cloud_edge):
    report = cloud_edge.outbound_connectivity_report()
    assert report["management"] is True
    assert report["mqtt"] is True
    cloud_edge.assert_outbound_established_replies(report)


@pytest.mark.integrationtest
def test_ot_simulators_cannot_reach_cloud(cloud_edge):
    assert not cloud_edge.ot_can_reach_cloud_mqtt()


@pytest.mark.integrationtest
def test_ot_protocol_requires_explicit_rule(cloud_edge):
    report = cloud_edge.ot_protocol_connectivity_report()
    print(
        "ot_protocol_connectivity="
        f"opcua={report['opcua']} "
        f"modbus={report['modbus']} "
        f"firewall_counters={report['firewall_counters']}"
    )
    assert report["opcua"] is True
    assert report["modbus"] is True
