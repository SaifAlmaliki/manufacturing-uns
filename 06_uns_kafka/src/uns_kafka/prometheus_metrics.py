"""Prometheus instrumentation for the Kafka ingestion mapper."""

from prometheus_client import Counter, Gauge, start_http_server

INGEST_RECEIVED = Counter(
    "uns_kafka_ingest_received_total",
    "MQTT historic events received by the ingestion mapper",
    ["shard", "qos"],
)
INGEST_ADMITTED = Counter(
    "uns_kafka_ingest_admitted_total",
    "Historic events queued for durable Kafka publication",
    ["shard"],
)
INGEST_ACCEPTED = Counter(
    "uns_kafka_ingest_accepted_total",
    "Historic events successfully delivered to the canonical log",
    ["shard"],
)
INGEST_QOS0 = Counter(
    "uns_kafka_ingest_qos0_total",
    "Best-effort QoS 0 historic events published without manual acknowledgment",
    ["shard"],
)
INGEST_REJECTED = Counter(
    "uns_kafka_ingest_rejected_total",
    "Historic events durably rejected to the DLQ",
    ["shard", "reason"],
)
INGEST_BACKPRESSURE = Counter(
    "uns_kafka_ingest_backpressure_total",
    "Ingestion backpressure or delivery failure events",
    ["shard", "reason"],
)
INGEST_READY = Gauge(
    "uns_kafka_ingest_ready",
    "Whether the ingestion shard is accepting new MQTT deliveries",
    ["shard"],
)


def start_metrics_server(port: int) -> None:
    start_http_server(port)
