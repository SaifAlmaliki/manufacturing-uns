"""Bounded per-partition batch assembly for the datalake mapper."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from uns_config.events import HistoricEventEnvelope

from uns_datalake.config import FlushLimits


@dataclass(frozen=True, slots=True)
class LakeRecord:
    kafka_topic: str
    partition: int
    offset: int
    envelope: HistoricEventEnvelope
    envelope_bytes: bytes

    @property
    def partition_key(self) -> tuple[str, int]:
        return (self.kafka_topic, self.partition)


@dataclass(slots=True)
class PartitionBuffer:
    partition: int
    records: list[LakeRecord] = field(default_factory=list)
    byte_total: int = 0
    started_at: float | None = None

    def is_empty(self) -> bool:
        return not self.records

    def age_seconds(self, *, monotonic: float) -> float:
        if self.started_at is None:
            return 0.0
        return monotonic - self.started_at


@dataclass(frozen=True, slots=True)
class FrozenPartitionFlush:
    partition: int
    ingest_date: date
    ingest_hour: int
    flush_id: str
    records: tuple[LakeRecord, ...]
    parquet_bytes: bytes
    object_path: str


def lake_object_path(*, ingest_date: date, ingest_hour: int, partition: int, flush_id: str) -> str:
    return f"v1/ingest_date={ingest_date.isoformat()}/hour={ingest_hour:02d}/partition={partition}/{flush_id}.parquet"


def new_flush_id(*, now: datetime | None = None) -> str:
    instant = datetime.now(tz=UTC) if now is None else now.astimezone(UTC)
    return f"{instant.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


@dataclass(slots=True)
class BatchManager:
    limits: FlushLimits
    buffers: dict[int, PartitionBuffer] = field(default_factory=dict)
    monotonic: Callable[[], float] = field(default_factory=time.monotonic)

    def total_buffered_bytes(self) -> int:
        return sum(buffer.byte_total for buffer in self.buffers.values())

    def try_add(self, record: LakeRecord) -> bool:
        if len(record.envelope_bytes) > self.limits.max_record_bytes:
            raise ValueError("record exceeds configured max_record_bytes")
        buffer = self._buffer(record.partition)
        projected_records = len(buffer.records) + 1
        projected_bytes = buffer.byte_total + len(record.envelope_bytes)
        if projected_records > self.limits.max_records or projected_bytes > self.limits.max_bytes:
            return False
        if buffer.started_at is None:
            buffer.started_at = self.monotonic()
        buffer.records.append(record)
        buffer.byte_total = projected_bytes
        return True

    def should_flush_partition(self, partition: int) -> bool:
        buffer = self.buffers.get(partition)
        if buffer is None or buffer.is_empty():
            return False
        now = self.monotonic()
        if len(buffer.records) >= self.limits.max_records:
            return True
        if buffer.byte_total >= self.limits.max_bytes:
            return True
        if buffer.age_seconds(monotonic=now) >= self.limits.interval_seconds:
            return True
        return False

    def partition_needing_pressure_flush(self) -> int | None:
        if self.total_buffered_bytes() <= self.limits.worker_max_buffered_bytes:
            return None
        candidates = [buffer for buffer in self.buffers.values() if not buffer.is_empty()]
        if not candidates:
            return None
        oldest = min(candidates, key=lambda item: item.started_at or 0.0)
        return oldest.partition

    def choose_flush_partition(self) -> int | None:
        ready = [partition for partition in self.buffers if self.should_flush_partition(partition)]
        if ready:
            return min(ready)
        return self.partition_needing_pressure_flush()

    def pop_partition(self, partition: int) -> PartitionBuffer:
        buffer = self.buffers.pop(partition, PartitionBuffer(partition=partition))
        return buffer

    def _buffer(self, partition: int) -> PartitionBuffer:
        if partition not in self.buffers:
            self.buffers[partition] = PartitionBuffer(partition=partition)
        return self.buffers[partition]
