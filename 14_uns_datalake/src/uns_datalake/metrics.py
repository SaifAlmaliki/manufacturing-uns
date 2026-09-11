"""Prometheus instrumentation for the datalake mapper."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

MAPPER_UP = Gauge("uns_datalake_up", "Datalake mapper process is running")
MAPPER_READY = Gauge("uns_datalake_ready", "Datalake mapper consumer assignment is active")
LAST_LOOP_TIMESTAMP = Gauge("uns_datalake_last_loop_timestamp_seconds", "Unix timestamp of the last poll loop heartbeat")
LAST_PUT_TIMESTAMP = Gauge("uns_datalake_last_put_timestamp_seconds", "Unix timestamp of the last successful object upload")
EVENTS_BUFFERED = Counter("uns_datalake_events_buffered_total", "Valid canonical events accepted into partition buffers")
ARCHIVE_ROWS = Counter("uns_datalake_archive_rows_total", "Verified physical rows uploaded to object storage")
DECODE_FAILURE = Counter(
    "uns_datalake_decode_failure_total",
    "Invalid envelopes routed to the DLQ",
    ["reason"],
)
REJECTIONS = Counter(
    "uns_datalake_rejections_total",
    "Durable rejections delivered to the DLQ",
    ["reason"],
)
DLQ_FAILURE = Counter("uns_datalake_dlq_failure_total", "Failed DLQ deliveries for rejected envelopes")
FLUSH_COUNT = Counter("uns_datalake_flush_total", "Completed partition flushes uploaded to object storage")
PUT_FAILURE = Counter("uns_datalake_put_failure_total", "Object upload failures before a successful flush")
COMMIT_FAILURE = Counter("uns_datalake_commit_failure_total", "Explicit Kafka offset commit failures")
INTEGRITY_FAILURE = Counter("uns_datalake_integrity_failure_total", "Object store integrity failures")
REPLAY_FAILURE = Counter(
    "uns_datalake_replay_failure_total",
    "Replay start and retention-gap failures",
    ["reason"],
)
CONSUMER_LAG = Gauge("uns_datalake_consumer_lag", "Kafka consumer lag across owned partitions")
OLDEST_UNRESOLVED_AGE = Gauge(
    "uns_datalake_oldest_unresolved_age_seconds",
    "Age of the oldest unresolved receipt including frozen, retry, and DLQ state",
)
BUFFERED_BYTES = Gauge("uns_datalake_buffered_bytes", "Application buffered envelope bytes")
ENCODED_BYTES = Gauge("uns_datalake_encoded_bytes", "Encoded artifact bytes retained during flush")
ACTIVE_ROUTE_GROUPS = Gauge("uns_datalake_active_route_groups", "Active route groups in partition buffers")
FLUSH_DURATION = Histogram("uns_datalake_flush_duration_seconds", "Time spent uploading one frozen partition flush")


def start_metrics_server(port: int) -> None:
    start_http_server(port)
