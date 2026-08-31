"""Prometheus instrumentation for the historian mapper."""

from prometheus_client import Counter, Histogram, start_http_server

MESSAGES_RECEIVED = Counter(
    "uns_historian_messages_received_total",
    "MQTT messages received by the historian",
)
PERSIST_SUCCESS = Counter(
    "uns_historian_persist_success_total",
    "Historic Events and Metrics persisted successfully",
)
PERSIST_FAILURE = Counter(
    "uns_historian_persist_failure_total",
    "Historian persist failures",
    ["reason"],
)
PERSIST_DURATION = Histogram(
    "uns_historian_persist_duration_seconds",
    "Time spent persisting a message to TimescaleDB",
)


def start_metrics_server(port: int) -> None:
    """Expose /metrics for Prometheus scraping."""
    start_http_server(port)
