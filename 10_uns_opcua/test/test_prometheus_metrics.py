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
    # Counters are process-global, so collector tests that already incremented
    # server="plc01" would make an absolute "== 1" assertion fail. Use a label
    # no other test uses, and a before/after delta like the unlabelled test.
    prometheus_metrics.SERVER_UP.labels(server="metrics-plc").set(1)
    prometheus_metrics.MONITORED_ITEMS.labels(server="metrics-plc").set(3)
    before_datachanges = (
        REGISTRY.get_sample_value("uns_opcua_datachanges_total", {"server": "metrics-plc"}) or 0
    )
    prometheus_metrics.DATACHANGES.labels(server="metrics-plc").inc()
    prometheus_metrics.DEADBAND_REJECTED.labels(server="metrics-plc").inc()
    prometheus_metrics.UNRESOLVED_NODES.labels(server="metrics-plc").inc()
    before_fallback = (
        REGISTRY.get_sample_value("uns_opcua_timestamp_fallback_total", {"reason": "server_timestamp"}) or 0
    )
    prometheus_metrics.TIMESTAMP_FALLBACK.labels(reason="server_timestamp").inc()

    assert REGISTRY.get_sample_value("uns_opcua_server_up", {"server": "metrics-plc"}) == 1
    assert (
        REGISTRY.get_sample_value("uns_opcua_datachanges_total", {"server": "metrics-plc"})
        == before_datachanges + 1
    )
    assert (
        REGISTRY.get_sample_value("uns_opcua_timestamp_fallback_total", {"reason": "server_timestamp"})
        == before_fallback + 1
    )


def test_unlabelled_metrics_increment():
    before = REGISTRY.get_sample_value("uns_opcua_publish_total") or 0
    prometheus_metrics.PUBLISH_TOTAL.inc()
    assert REGISTRY.get_sample_value("uns_opcua_publish_total") == before + 1
