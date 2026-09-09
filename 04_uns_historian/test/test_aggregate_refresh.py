"""Unit tests for late aggregate refresh worker."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest

from uns_historian.aggregate_refresh import (
    AggregateRefreshError,
    AggregateRefreshWorker,
    RefreshClaim,
    utc_day_bounds,
)


def test_utc_day_bounds_cover_full_utc_day():
    start, end = utc_day_bounds(date(2026, 9, 9))
    assert start == datetime(2026, 9, 9, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio(loop_scope="function")
async def test_run_once_returns_false_when_no_pending_work():
    worker = AggregateRefreshWorker(database=AsyncMock())
    worker.claim_pending = AsyncMock(return_value=None)
    assert await worker.run_once() is False


@pytest.mark.asyncio(loop_scope="function")
async def test_refresh_claim_marks_only_requested_generation(monkeypatch):
    worker = AggregateRefreshWorker(database=AsyncMock())
    connection = AsyncMock()
    connection.execute = AsyncMock()
    connection.execute.return_value.rowcount = 1
    transaction = AsyncMock()
    transaction.__aenter__.return_value = connection
    transaction.__aexit__.return_value = None
    worker._database.begin = lambda: transaction  # type: ignore[method-assign]

    claim = RefreshClaim(utc_day=date(2026, 9, 1), generation=3)
    await worker.refresh_claim(claim)

    assert connection.execute.await_count == 3


@pytest.mark.asyncio(loop_scope="function")
async def test_refresh_claim_raises_when_generation_superseded():
    worker = AggregateRefreshWorker(database=AsyncMock())
    connection = AsyncMock()
    connection.execute = AsyncMock()
    connection.execute.return_value.rowcount = 0
    transaction = AsyncMock()
    transaction.__aenter__.return_value = connection
    transaction.__aexit__.return_value = None
    worker._database.begin = lambda: transaction  # type: ignore[method-assign]

    with pytest.raises(AggregateRefreshError):
        await worker.refresh_claim(RefreshClaim(utc_day=date(2026, 9, 1), generation=2))
