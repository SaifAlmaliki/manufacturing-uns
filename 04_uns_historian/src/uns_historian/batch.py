"""Batch assembly and projection helpers for Kafka historian ingestion."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from uns_config.events import HistoricEventEnvelope, immutable_content_hash

from uns_historian.metric_flattener import MetricExpansionLimitError, iter_payload_metrics

HISTORIC_KAFKA_TOPIC = "uns.historic-events"
PIPELINE_SCHEMA = "historian"

DEFAULT_MAX_EVENTS = 500
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_AGE_SECONDS = 0.1
DEFAULT_MAX_METRIC_ROWS = 20_000


class ContentConflictError(ValueError):
    """The same (time, event_id) already exists with different immutable content."""

    def __init__(
        self,
        event_id: str,
        *,
        existing_hash: str,
        incoming_hash: str,
    ) -> None:
        self.event_id = event_id
        self.existing_hash = existing_hash
        self.incoming_hash = incoming_hash
        super().__init__(
            f"content conflict for {event_id}: existing={existing_hash} incoming={incoming_hash}"
        )


@dataclass(frozen=True, slots=True)
class BatchLimits:
    max_events: int = DEFAULT_MAX_EVENTS
    max_bytes: int = DEFAULT_MAX_BYTES
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
    max_metric_rows: int = DEFAULT_MAX_METRIC_ROWS


@dataclass(frozen=True, slots=True)
class ConsumedEvent:
    kafka_topic: str
    partition: int
    offset: int
    envelope: HistoricEventEnvelope
    envelope_bytes: bytes

    @property
    def partition_key(self) -> tuple[str, int]:
        return (self.kafka_topic, self.partition)


@dataclass(frozen=True, slots=True)
class IgnoredConsumedRecord:
    """Kafka record consumed but not projected into historian SQL."""

    kafka_topic: str
    partition: int
    offset: int

    @property
    def partition_key(self) -> tuple[str, int]:
        return (self.kafka_topic, self.partition)


@dataclass(frozen=True, slots=True)
class RawInsertRow:
    time: datetime
    topic: str
    client_id: str | None
    mqtt_msg: dict[str, Any]
    event_id: str
    identity_quality: str
    received_at: datetime
    event_kind: str
    is_historical: bool
    site_id: str
    source_id: str
    source_boot_id: str | None
    source_sequence: int | None
    timestamp_quality: str
    immutable_content_hash: str
    kafka_topic: str
    partition: int
    offset: int


@dataclass(frozen=True, slots=True)
class MetricInsertRow:
    time: datetime
    topic: str
    metric_name: str
    value_double: float | None
    value_text: str | None
    event_id: str


@dataclass(frozen=True, slots=True)
class BatchPersistResult:
    inserted_count: int
    duplicate_count: int
    filtered_stale_count: int
    quarantined_conflicts: tuple[ContentConflictError, ...]
    next_offsets: dict[tuple[str, int], int]


@dataclass(slots=True)
class BatchCollector:
    limits: BatchLimits
    events: list[ConsumedEvent] = field(default_factory=list)
    _byte_total: int = 0
    _started_at: float | None = None

    def try_add(self, event: ConsumedEvent, *, monotonic: float | None = None) -> bool:
        now = time.monotonic() if monotonic is None else monotonic
        if self._started_at is None:
            self._started_at = now
        if self.events and self.is_full(now):
            return False
        projected = len(self.events) + 1
        projected_bytes = self._byte_total + len(event.envelope_bytes)
        if projected > self.limits.max_events or projected_bytes > self.limits.max_bytes:
            return False
        self.events.append(event)
        self._byte_total = projected_bytes
        return True

    def is_full(self, monotonic: float | None = None) -> bool:
        if not self.events:
            return False
        now = time.monotonic() if monotonic is None else monotonic
        assert self._started_at is not None
        if len(self.events) >= self.limits.max_events:
            return True
        if self._byte_total >= self.limits.max_bytes:
            return True
        return (now - self._started_at) >= self.limits.max_age_seconds

    def spans_partitions(self) -> bool:
        if len(self.events) < 2:
            return False
        first = self.events[0].partition_key
        return any(event.partition_key != first for event in self.events[1:])


def envelope_content_hash(envelope: HistoricEventEnvelope) -> str:
    return immutable_content_hash(envelope)


def raw_row_from_event(event: ConsumedEvent) -> RawInsertRow:
    envelope = event.envelope
    return RawInsertRow(
        time=envelope.time,
        topic=envelope.topic,
        client_id=None,
        mqtt_msg=envelope.payload,
        event_id=envelope.event_id,
        identity_quality=envelope.identity_quality,
        received_at=envelope.received_at,
        event_kind=envelope.event_kind,
        is_historical=envelope.is_historical,
        site_id=envelope.site_id,
        source_id=envelope.source_id,
        source_boot_id=envelope.source_boot_id,
        source_sequence=envelope.source_sequence,
        timestamp_quality=envelope.timestamp_quality,
        immutable_content_hash=envelope_content_hash(envelope),
        kafka_topic=event.kafka_topic,
        partition=event.partition,
        offset=event.offset,
    )


def compute_next_offset(checkpoint_next: int, handled_offsets: Sequence[int]) -> int:
    """Advance only across a contiguous prefix starting at the checkpoint."""
    next_offset = checkpoint_next
    for offset in sorted(handled_offsets):
        if offset < next_offset:
            continue
        if offset == next_offset:
            next_offset = offset + 1
            continue
        break
    return next_offset


def utc_day(value: datetime) -> datetime.date:
    return value.astimezone(UTC).date()


def sorted_partition_keys(events: Iterable[ConsumedEvent]) -> list[tuple[str, int]]:
    return sorted({event.partition_key for event in events})


def build_metric_rows(raw_row: RawInsertRow, *, limits: BatchLimits) -> list[MetricInsertRow]:
    if raw_row.event_kind != "telemetry":
        return []
    rows: list[MetricInsertRow] = []
    for metric_name, value_double, value_text in iter_payload_metrics(
        raw_row.mqtt_msg,
        limit=limits.max_metric_rows + 1,
    ):
        if len(rows) >= limits.max_metric_rows:
            raise MetricExpansionLimitError(
                f"metric expansion exceeds limit of {limits.max_metric_rows} for {raw_row.event_id}"
            )
        rows.append(
            MetricInsertRow(
                time=raw_row.time,
                topic=raw_row.topic,
                metric_name=metric_name,
                value_double=value_double,
                value_text=value_text,
                event_id=raw_row.event_id,
            )
        )
    return rows
