"""Prometheus instrumentation for the graphdb mapper."""

from prometheus_client import Counter, Histogram, start_http_server

MESSAGES_RECEIVED = Counter(
    "uns_graphdb_messages_received_total",
    "MQTT messages received by the graphdb mapper",
)
PERSIST_SUCCESS = Counter(
    "uns_graphdb_persist_success_total",
    "UNS Nodes persisted successfully",
)
PERSIST_FAILURE = Counter(
    "uns_graphdb_persist_failure_total",
    "GraphDB persist failures",
    ["reason"],
)
PERSIST_DURATION = Histogram(
    "uns_graphdb_persist_duration_seconds",
    "Time spent persisting a message to Neo4j",
)


def start_metrics_server(port: int) -> None:
    """Expose /metrics for Prometheus scraping."""
    start_http_server(port)
