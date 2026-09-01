"""Prometheus instrumentation for the OPC UA edge connector."""

from prometheus_client import Counter, Gauge, start_http_server

SERVER_UP = Gauge(
    "uns_opcua_server_up",
    "1 while an OPC UA session is established, 0 otherwise",
    ["server"],
)
MONITORED_ITEMS = Gauge(
    "uns_opcua_monitored_items",
    "Monitored items the server accepted",
    ["server"],
)
DATACHANGES = Counter(
    "uns_opcua_datachanges_total",
    "Data change notifications received",
    ["server"],
)
DEADBAND_REJECTED = Counter(
    "uns_opcua_deadband_rejected_total",
    "Monitored items the server would not accept a deadband filter for",
    ["server"],
)
UNRESOLVED_NODES = Counter(
    "uns_opcua_unresolved_nodes_total",
    "Configured node_ids that could not be resolved on the server",
    ["server"],
)
QUEUE_DROPPED = Counter(
    "uns_opcua_queue_dropped_total",
    "Notifications dropped because the in-memory hand-off to the spool writer was full",
)
PUBLISH_TOTAL = Counter(
    "uns_opcua_publish_total",
    "Messages published to the MQTT broker",
)
PUBLISH_ERRORS = Counter(
    "uns_opcua_publish_errors_total",
    "Failed publish attempts",
)
SPOOL_ROWS = Gauge(
    "uns_opcua_spool_rows",
    "Rows currently waiting in the spool",
)
SPOOL_BYTES = Gauge(
    "uns_opcua_spool_bytes",
    "On-disk size of the spool database",
)
SPOOL_DROPPED = Counter(
    "uns_opcua_spool_dropped_total",
    "Oldest spool rows deleted to stay inside the configured bounds",
)
SPOOL_WRITE_ERRORS = Counter(
    "uns_opcua_spool_write_errors_total",
    "Spool write failures, e.g. a full disk",
)
SPOOL_LAG_SECONDS = Gauge(
    "uns_opcua_spool_lag_seconds",
    "Age of the oldest unpublished spool row - how far behind this edge node is",
)
UNMODELLED_TAGS = Gauge(
    "uns_opcua_unmodelled_tags",
    "Configured tags with no matching Asset or MetricDefinition",
)
TIMESTAMP_FALLBACK = Counter(
    "uns_opcua_timestamp_fallback_total",
    "Notifications whose timestamp did not come from SourceTimestamp",
    ["reason"],
)


def start_metrics_server(port: int) -> None:
    """Expose /metrics for Prometheus scraping."""
    start_http_server(port)
