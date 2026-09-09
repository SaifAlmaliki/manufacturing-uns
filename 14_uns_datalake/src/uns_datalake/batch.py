"""In-memory batch buffer for Historic Event records."""

from __future__ import annotations

import json
from collections.abc import Callable

from uns_config.datalake import HistoricEventRecord


class HistoricEventBatch:
    """Accumulates records until flush thresholds are met."""

    def __init__(
        self,
        interval_seconds: float,
        max_bytes: int,
        clock: Callable[[], float],
        max_records: int = 10000,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._max_bytes = max_bytes
        self._max_records = max_records
        self._clock = clock
        self._records: list[HistoricEventRecord] = []
        self._estimated_bytes = 0
        self._started_at: float | None = None

    def add(self, record: HistoricEventRecord) -> None:
        if self._started_at is None:
            self._started_at = self._clock()
        self._records.append(record)
        self._estimated_bytes += (
            len(json.dumps(record.payload).encode("utf-8"))
            + len(record.topic.encode("utf-8"))
            + 64
        )

    def should_flush(self) -> bool:
        if not self._records and self._started_at is None:
            return False
        if self._records and self._estimated_bytes >= self._max_bytes:
            return True
        if self._records and len(self._records) >= self._max_records:
            return True
        if self._started_at is not None and self._clock() - self._started_at >= self._interval_seconds:
            return True
        return False

    def snapshot(self) -> tuple[HistoricEventRecord, ...]:
        return tuple(self._records)

    def take(self) -> list[HistoricEventRecord]:
        records = list(self._records)
        self._records.clear()
        self._estimated_bytes = 0
        self._started_at = None
        return records
