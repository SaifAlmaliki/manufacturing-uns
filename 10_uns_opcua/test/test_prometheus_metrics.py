"""The metric surface is part of this module's contract, so it is asserted."""

from prometheus_client import REGISTRY
from uns_opcua import prometheus_metrics

EXPECTED_SAMPLES = {
    "uns_opcua_server_up",
    "uns_opcua_monitored_items",
    "uns_opcua_datachanges_total",
    "uns_opcua_deadband_rejected_total",
    "uns_opcua_unresolved_nodes_total",
    "uns_opcua_queue_dropped_total",
    "uns_opcua_publish_total",
    "uns_opcua_publish_errors_total",
    "uns_opcua_spool_rows",
    "uns_opcua_spool_bytes",
    "uns_opcua_spool_dropped_total",
    "uns_opcua_spool_write_errors_total",
    "uns_opcua_spool_lag_seconds",
    "uns_opcua_unmodelled_tags",
    "uns_opcua_timestamp_fallback_total",
}


def test_every_documented_metric_is_registered():
    registered = {metric.name for metric in REGISTRY.collect()}
    # Counters register under their name without the _total suffix.
    expected = {name.removesuffix("_total") for name in EXPECTED_SAMPLES}
    assert expected <= registered


def test_labelled_metrics_accept_their_labels():
    prometheus_metrics.SERVER_UP.labels(server="plc01").set(1)
    prometheus_metrics.MONITORED_ITEMS.labels(server="plc01").set(3)
    prometheus_metrics.DATACHANGES.labels(server="plc01").inc()
    prometheus_metrics.DEADBAND_REJECTED.labels(server="plc01").inc()
    prometheus_metrics.UNRESOLVED_NODES.labels(server="plc01").inc()
    prometheus_metrics.TIMESTAMP_FALLBACK.labels(reason="server_timestamp").inc()

    assert REGISTRY.get_sample_value("uns_opcua_server_up", {"server": "plc01"}) == 1
    assert REGISTRY.get_sample_value("uns_opcua_datachanges_total", {"server": "plc01"}) == 1
    assert (
        REGISTRY.get_sample_value("uns_opcua_timestamp_fallback_total", {"reason": "server_timestamp"}) == 1
    )


def test_unlabelled_metrics_increment():
    before = REGISTRY.get_sample_value("uns_opcua_publish_total") or 0
    prometheus_metrics.PUBLISH_TOTAL.inc()
    assert REGISTRY.get_sample_value("uns_opcua_publish_total") == before + 1
