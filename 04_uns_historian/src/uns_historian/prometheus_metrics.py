"""Prometheus instrumentation for the historian."""

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
EVENTS_CONSUMED = Counter(
    "uns_historian_kafka_events_consumed_total",
    "Canonical historic events accepted into a Kafka batch",
)
DECODE_FAILURE = Counter(
    "uns_historian_kafka_decode_failure_total",
    "Invalid canonical envelopes rejected by the historian consumer",
    ["reason"],
)
KAFKA_COMMITS = Counter(
    "uns_historian_kafka_commits_total",
    "Explicit Kafka offset commits after SQL batch success",
)
BATCH_FLUSH_DURATION = Histogram(
    "uns_historian_batch_flush_duration_seconds",
    "Time spent persisting one Kafka batch to TimescaleDB",
)
CONSUMER_LAG = Histogram(
    "uns_historian_consumer_lag_messages",
    "Observed Kafka consumer lag per assigned partition",
    ["partition"],
)
AGGREGATE_REFRESH_SUCCESS = Counter(
    "uns_historian_aggregate_refresh_success_total",
    "Successful late-data continuous aggregate refreshes",
)
AGGREGATE_REFRESH_FAILURE = Counter(
    "uns_historian_aggregate_refresh_failure_total",
    "Failed late-data continuous aggregate refreshes",
)


def start_metrics_server(port: int) -> None:
    """Expose /metrics for Prometheus scraping."""
    start_http_server(port)
