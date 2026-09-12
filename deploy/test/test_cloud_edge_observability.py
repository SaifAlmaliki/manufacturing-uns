"""Prometheus alert contracts for cloud-edge qualification observability."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ALERTS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "alerts.yml"
DASHBOARD_FILE = REPO_ROOT / "08_uns_observability" / "grafana" / "dashboards" / "platform-observability.json"

REQUIRED_CLOUD_EDGE_ALERTS = {
    "UnsEdgeDesiredAppliedLag",
    "UnsEdgeBridgeBufferPressure",
    "UnsPublicationOutboxBacklog",
    "UnsEdgeCertificateExpiryWarning",
    "UnsKafkaIngestionNotReady",
    "UnsKafkaIngestionBackpressure",
    "UnsDatalakeNotReady",
}


def _alert_names() -> set[str]:
    alerts = yaml.safe_load(ALERTS_FILE.read_text(encoding="utf-8"))
    return {rule["alert"] for group in alerts["groups"] for rule in group["rules"]}


def test_prometheus_alerts_cover_cloud_edge_qualification_signals():
    names = _alert_names()
    missing = REQUIRED_CLOUD_EDGE_ALERTS - names
    assert not missing, f"missing alerts: {sorted(missing)}"


def test_platform_dashboard_references_cloud_edge_metrics():
    dashboard = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    panel_text = json.dumps(dashboard["panels"])
    for expr_fragment in (
        "uns_edge_desired_applied_lag_seconds",
        "uns_edge_bridge_buffer_bytes",
        "uns_publication_outbox_queued_bytes",
        "uns_edge_certificate_expiry_seconds",
    ):
        assert expr_fragment in panel_text
