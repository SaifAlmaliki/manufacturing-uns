from datetime import UTC, datetime

from uns_config.datalake import HistoricEventRecord
from uns_datalake.batch import HistoricEventBatch


def test_flush_on_max_bytes():
    batch = HistoricEventBatch(interval_seconds=3600, max_bytes=50, clock=lambda: 0.0)
    record = HistoricEventRecord(datetime.now(UTC), "t", {"x": "y" * 40})
    batch.add(record)
    assert batch.should_flush() is True


def test_flush_on_interval():
    start = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    now = 0.0
    batch = HistoricEventBatch(interval_seconds=60, max_bytes=10_000_000, clock=lambda: now)
    batch.add(HistoricEventRecord(start, "t", {"v": 1}))
    assert batch.should_flush() is False
    now = 61.0
    assert batch.should_flush() is True


def test_take_clears():
    batch = HistoricEventBatch(interval_seconds=1, max_bytes=10, clock=lambda: 0.0)
    batch.add(HistoricEventRecord(datetime.now(UTC), "t", {"v": 1}))
    taken = batch.take()
    assert len(taken) == 1
    assert batch.take() == []
