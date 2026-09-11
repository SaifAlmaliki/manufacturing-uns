"""Batch limit and layout tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uns_datalake.batch import BatchManager, lake_object_path_v1, new_flush_id
from uns_datalake.config import FlushLimits
from conftest import lake_record_from_envelope, legacy_route_map, source_envelope, v2_envelope


def _record(
    partition: int,
    offset: int,
    *,
    topic: str | None = None,
    payload_size: int = 100,
    application: str = "machine",
    schema: str = "temperature",
) -> object:
    envelope = v2_envelope(
        topic=topic or f"Enterprise/PlantA/Metric/{offset}",
        source_application=application,
        payload_schema_id=schema,
        original_payload=b"x" * payload_size,
    )
    return lake_record_from_envelope(
        envelope,
        partition=partition,
        offset=offset,
        envelope_bytes=b"x" * payload_size,
    )


def test_lake_object_path_uses_ingestion_partition_layout():
    path = lake_object_path_v1(
        ingest_date=datetime(2026, 9, 9, tzinfo=UTC).date(),
        ingest_hour=10,
        partition=3,
        flush_id="abc123",
    )
    assert path == "v1/ingest_date=2026-09-09/hour=10/partition=3/abc123.parquet"


def test_batch_flushes_on_record_limit():
    limits = FlushLimits(
        max_records=2,
        max_bytes=1_000_000,
        max_record_bytes=1_000_000,
        interval_seconds=60,
        worker_max_buffered_bytes=1_000_000,
    )
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    assert manager.try_add(_record(0, 0))
    assert manager.try_add(_record(0, 1))
    assert manager.choose_flush_partition() == ("uns.historic-events", 0)


def test_worker_pressure_flushes_oldest_partition():
    limits = FlushLimits(
        max_records=10_000,
        max_bytes=150,
        max_record_bytes=150,
        interval_seconds=60,
        worker_max_buffered_bytes=150,
    )
    clock = {"now": 0.0}
    manager = BatchManager(limits=limits, monotonic=lambda: clock["now"])
    assert manager.try_add(_record(1, 0, payload_size=80))
    clock["now"] = 5.0
    assert manager.try_add(_record(2, 0, payload_size=80))
    assert manager.partition_needing_pressure_flush() == ("uns.historic-events", 1)


def test_ten_thousand_topics_still_bound_object_count():
    limits = FlushLimits(max_records=10_000, max_bytes=100_000_000, interval_seconds=60, worker_max_buffered_bytes=100_000_000)
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    for index in range(10_000):
        assert manager.try_add(_record(0, index, topic=f"Enterprise/PlantA/Device/{index}"))
    assert manager.choose_flush_partition() == ("uns.historic-events", 0)
    buffer = manager.pop_partition(("uns.historic-events", 0))
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


def test_mixed_topics_with_equal_partition_ids_use_distinct_buffers():
    limits = FlushLimits(
        max_records=10,
        max_bytes=1_000_000,
        max_record_bytes=1_000_000,
        interval_seconds=60,
        worker_max_buffered_bytes=1_000_000,
    )
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    legacy_map = legacy_route_map()
    envelope = source_envelope()
    record_a = lake_record_from_envelope(envelope, legacy_map=legacy_map, kafka_topic="topic-a", partition=0, offset=0)
    record_b = lake_record_from_envelope(envelope, legacy_map=legacy_map, kafka_topic="topic-b", partition=0, offset=0)
    assert manager.try_add(record_a)
    assert manager.try_add(record_b)
    assert ("topic-a", 0) in manager.buffers
    assert ("topic-b", 0) in manager.buffers
