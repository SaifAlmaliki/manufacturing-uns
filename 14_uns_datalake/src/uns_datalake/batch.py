"""Bounded per-partition batch assembly for the datalake mapper."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from uns_datalake.config import FlushLimits
from uns_datalake.routing import LakeRecord, LakeRoute, lake_object_path

PartitionKey = tuple[str, int]


@dataclass(slots=True)
class PartitionBuffer:
    partition_key: PartitionKey
    records: list[LakeRecord] = field(default_factory=list)
    byte_total: int = 0
    started_at: float | None = None
    route_groups: set[LakeRoute] = field(default_factory=set)

    @property
    def partition(self) -> int:
        return self.partition_key[1]

    def is_empty(self) -> bool:
        return not self.records

    def age_seconds(self, *, monotonic: float) -> float:
        if self.started_at is None:
            return 0.0
        return monotonic - self.started_at


@dataclass(frozen=True, slots=True)
class FrozenRouteGroup:
    route: LakeRoute
    object_id: str
    records: tuple[LakeRecord, ...]
    object_path: str
    parquet_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class FrozenPartitionFlush:
    partition_key: PartitionKey
    flush_id: str
    route_groups: tuple[FrozenRouteGroup, ...]

    @property
    def partition(self) -> int:
        return self.partition_key[1]


def lake_object_path_v1(*, ingest_date: date, ingest_hour: int, partition: int, flush_id: str) -> str:
    return f"v1/ingest_date={ingest_date.isoformat()}/hour={ingest_hour:02d}/partition={partition}/{flush_id}.parquet"


def new_flush_id(*, now: datetime | None = None) -> str:
    instant = datetime.now(tz=UTC) if now is None else now.astimezone(UTC)
    return f"{instant.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def new_object_id() -> str:
    return str(uuid.uuid4())


def group_records_by_route(records: Sequence[LakeRecord]) -> dict[LakeRoute, tuple[LakeRecord, ...]]:
    grouped: dict[LakeRoute, list[LakeRecord]] = {}
    for record in records:
        route = record.resolved.route
        grouped.setdefault(route, []).append(record)
    return {route: tuple(items) for route, items in grouped.items()}


def freeze_partition_records(
    partition_key: PartitionKey,
    records: Sequence[LakeRecord],
    *,
    now: datetime | None = None,
) -> FrozenPartitionFlush:
    grouped = group_records_by_route(records)
    flush_id = new_flush_id(now=now)
    route_groups: list[FrozenRouteGroup] = []
    for route in sorted(grouped, key=_route_sort_key):
        object_id = new_object_id()
        route_groups.append(
            FrozenRouteGroup(
                route=route,
                object_id=object_id,
                records=grouped[route],
                object_path=lake_object_path(route, object_id),
            )
        )
    return FrozenPartitionFlush(
        partition_key=partition_key,
        flush_id=flush_id,
        route_groups=tuple(route_groups),
    )


def _route_sort_key(route: LakeRoute) -> tuple[str, str, str, str, str]:
    return (
        route.application,
        route.site,
        route.schema,
        route.version,
        route.ingestion_date.isoformat(),
    )


@dataclass(slots=True)
class BatchManager:
    limits: FlushLimits
    buffers: dict[PartitionKey, PartitionBuffer] = field(default_factory=dict)
    monotonic: Callable[[], float] = field(default=time.monotonic)
    pending_record_bytes: int = 0

    def total_buffered_bytes(self) -> int:
        return sum(buffer.byte_total for buffer in self.buffers.values()) + self.pending_record_bytes

    def reserve_admission(self, wire_bytes: int) -> None:
        if wire_bytes > self.limits.max_record_bytes:
            raise ValueError("record exceeds configured max_record_bytes")
        self.pending_record_bytes = wire_bytes

    def clear_admission_reservation(self) -> None:
        self.pending_record_bytes = 0

    def admission_would_exceed_limits(self, record: LakeRecord) -> bool:
        wire_bytes = len(record.envelope_bytes)
        if wire_bytes > self.limits.max_record_bytes:
            raise ValueError("record exceeds configured max_record_bytes")
        partition_key = record.partition_key
        buffer = self.buffers.get(partition_key)
        projected_records = (len(buffer.records) if buffer else 0) + 1
        projected_bytes = (buffer.byte_total if buffer else 0) + wire_bytes + self.pending_record_bytes
        projected_groups = self._projected_route_groups(partition_key, record)
        if projected_groups > self.limits.max_active_route_groups:
            return True
        if projected_records > self.limits.max_records:
            return True
        if projected_bytes > self.limits.max_bytes:
            return True
        return False

    def try_add(self, record: LakeRecord) -> bool:
        if self.admission_would_exceed_limits(record):
            return False
        buffer = self._buffer(record.partition_key)
        if buffer.started_at is None:
            buffer.started_at = self.monotonic()
        buffer.records.append(record)
        buffer.byte_total += len(record.envelope_bytes)
        buffer.route_groups.add(record.resolved.route)
        self.clear_admission_reservation()
        return True

    def should_flush_partition(self, partition_key: PartitionKey) -> bool:
        buffer = self.buffers.get(partition_key)
        if buffer is None or buffer.is_empty():
            return False
        now = self.monotonic()
        if len(buffer.records) >= self.limits.max_records:
            return True
        if buffer.byte_total >= self.limits.max_bytes:
            return True
        if len(buffer.route_groups) >= self.limits.max_active_route_groups:
            return True
        if buffer.age_seconds(monotonic=now) >= self.limits.interval_seconds:
            return True
        return False

    def partition_needing_pressure_flush(self) -> PartitionKey | None:
        if self.total_buffered_bytes() <= self.limits.worker_max_buffered_bytes:
            return None
        candidates = [buffer for buffer in self.buffers.values() if not buffer.is_empty()]
        if not candidates:
            return None
        oldest = min(candidates, key=lambda item: item.started_at or 0.0)
        return oldest.partition_key

    def choose_flush_partition(self) -> PartitionKey | None:
        ready = [key for key in self.buffers if self.should_flush_partition(key)]
        if ready:
            return min(ready)
        return self.partition_needing_pressure_flush()

    def pop_partition(self, partition_key: PartitionKey) -> PartitionBuffer:
        buffer = self.buffers.pop(partition_key, PartitionBuffer(partition_key=partition_key))
        return buffer

    def active_route_group_count(self, partition_key: PartitionKey) -> int:
        buffer = self.buffers.get(partition_key)
        if buffer is None:
            return 0
        return len(buffer.route_groups)

    def _projected_route_groups(self, partition_key: PartitionKey, record: LakeRecord) -> int:
        buffer = self.buffers.get(partition_key)
        if buffer is None:
            return 1
        route = record.resolved.route
        if route in buffer.route_groups:
            return len(buffer.route_groups)
        return len(buffer.route_groups) + 1

    def _buffer(self, partition_key: PartitionKey) -> PartitionBuffer:
        if partition_key not in self.buffers:
            self.buffers[partition_key] = PartitionBuffer(partition_key=partition_key)
        return self.buffers[partition_key]
