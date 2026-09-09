"""Batch limit and layout tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uns_datalake.batch import BatchManager, FlushLimits, LakeRecord, lake_object_path, new_flush_id
from conftest import source_envelope


def _record(partition: int, offset: int, *, topic: str | None = None, payload_size: int = 100) -> LakeRecord:
    envelope = source_envelope(topic=topic or f"Enterprise/PlantA/Metric/{offset}")
    payload = b"x" * payload_size
    return LakeRecord(
        kafka_topic="uns.historic-events",
        partition=partition,
        offset=offset,
        envelope=envelope,
        envelope_bytes=payload,
    )


def test_lake_object_path_uses_ingestion_partition_layout():
    path = lake_object_path(
        ingest_date=datetime(2026, 9, 9, tzinfo=UTC).date(),
        ingest_hour=10,
        partition=3,
        flush_id="abc123",
    )
    assert path == "v1/ingest_date=2026-09-09/hour=10/partition=3/abc123.parquet"


def test_batch_flushes_on_record_limit():
    limits = FlushLimits(max_records=2, max_bytes=1_000_000, interval_seconds=60, worker_max_buffered_bytes=1_000_000)
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    assert manager.try_add(_record(0, 0))
    assert manager.try_add(_record(0, 1))
    assert manager.choose_flush_partition() == 0


def test_worker_pressure_flushes_oldest_partition():
    limits = FlushLimits(max_records=10_000, max_bytes=10_000, interval_seconds=60, worker_max_buffered_bytes=150)
    clock = {"now": 0.0}
    manager = BatchManager(limits=limits, monotonic=lambda: clock["now"])
    assert manager.try_add(_record(1, 0, payload_size=80))
    clock["now"] = 5.0
    assert manager.try_add(_record(2, 0, payload_size=80))
    assert manager.partition_needing_pressure_flush() == 1


def test_ten_thousand_topics_still_bound_object_count():
    limits = FlushLimits(max_records=10_000, max_bytes=100_000_000, interval_seconds=60, worker_max_buffered_bytes=100_000_000)
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    for index in range(10_000):
        assert manager.try_add(_record(0, index, topic=f"Enterprise/PlantA/Device/{index}"))
    assert manager.choose_flush_partition() == 0
    buffer = manager.pop_partition(0)
    assert len(buffer.records) == 10_000
    assert manager.choose_flush_partition() is None


def test_oversize_record_is_rejected():
    limits = FlushLimits(max_record_bytes=10)
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    with pytest.raises(ValueError):
        manager.try_add(_record(0, 0, payload_size=20))


def test_flush_id_is_unique():
    assert new_flush_id(now=datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)) != new_flush_id(
        now=datetime(2026, 9, 9, 10, 0, 1, tzinfo=UTC)
    )
