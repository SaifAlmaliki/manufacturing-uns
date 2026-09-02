"""Tests for uns_oee.main.

The service is constructed with its scheduler, its metrics and its clock passed in, so every
test here runs without a database, a broker or a wall clock. Only the two waits use real time,
and both are milliseconds.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from uns_oee.main import OeeService, build_scheduler, utc_now
from uns_oee.oee_config import OeeConfig
from uns_oee.prometheus_metrics import OeeMetrics, Readings
from uns_oee.scheduler import PassSummary

NOW = datetime(2026, 9, 9, 15, tzinfo=timezone.utc)


def config(**overrides) -> OeeConfig:
    values = {"mqtt_host": "localhost", "scan_interval_seconds": 0.01}
    values.update(overrides)
    return OeeConfig(**values)


class FakeScheduler:
    """Records the timestamps it was passed and can be told to fail."""

    def __init__(self, *, failures: int = 0, on_pass=None) -> None:
        self.calls: list[datetime] = []
        self._failures = failures
        self._on_pass = on_pass

    async def run_pass(self, now: datetime) -> PassSummary:
        self.calls.append(now)
        if self._on_pass is not None:
            self._on_pass()
        if self._failures > 0:
            self._failures -= 1
            raise RuntimeError("connection refused")
        return PassSummary(units=2, windows=3)


async def fake_gauges(_database) -> Readings:
    return Readings(recompute_queue_depth=5, unpublished_results=0, database_up=True)


def service(scheduler, *, metrics=None, gauges=fake_gauges, **config_overrides) -> OeeService:
    return OeeService(
        config(**config_overrides),
        database=object(),
        scheduler=scheduler,
        metrics=metrics if metrics is not None else OeeMetrics(),
        clock=lambda: NOW,
        gauges=gauges,
    )


# --- one pass ------------------------------------------------------------------------


def test_utc_now_is_timezone_aware():
    # A naive timestamp would silently become "UTC" three layers down, where the shift
    # calendar is doing DST arithmetic with it.
    assert utc_now().tzinfo is not None


@pytest.mark.asyncio
async def test_a_pass_stamps_the_clock_the_service_was_given():
    scheduler = FakeScheduler()
    summary = await service(scheduler).run_once()
    assert scheduler.calls == [NOW]
    assert summary == PassSummary(units=2, windows=3)


@pytest.mark.asyncio
async def test_a_pass_reads_the_database_gauges_afterwards():
    metrics = OeeMetrics()
    await service(FakeScheduler(), metrics=metrics).run_once()
    from prometheus_client import generate_latest

    text = generate_latest(metrics.registry).decode("utf-8")
    assert "uns_oee_recompute_queue_depth 5.0" in text
    assert "uns_oee_db_up 1.0" in text


@pytest.mark.asyncio
async def test_a_pass_that_raises_still_reads_the_gauges():
    metrics = OeeMetrics()
    # The pass failed, so there is no summary - but the queue depth is exactly the number an
    # operator wants during an outage, so it is read either way.
    assert await service(FakeScheduler(failures=1), metrics=metrics).run_once() is None
    from prometheus_client import generate_latest

    assert "uns_oee_recompute_queue_depth 5.0" in generate_latest(metrics.registry).decode("utf-8")


# --- the loop ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stop_before_the_first_pass_runs_nothing():
    scheduler = FakeScheduler()
    engine = service(scheduler, scan_interval_seconds=30.0)
    engine.request_stop()
    await asyncio.wait_for(engine.run_forever(), timeout=1.0)
    assert scheduler.calls == []


@pytest.mark.asyncio
async def test_a_stop_during_a_pass_ends_the_loop_without_serving_out_the_interval():
    holder: dict[str, OeeService] = {}
    scheduler = FakeScheduler(on_pass=lambda: holder["engine"].request_stop())
    holder["engine"] = service(scheduler, scan_interval_seconds=30.0)
    # A 30 second interval and a one second timeout: if the stop only took effect after the
    # sleep, `docker stop` would kill the container instead of it exiting.
    await asyncio.wait_for(holder["engine"].run_forever(), timeout=1.0)
    assert scheduler.calls == [NOW]


@pytest.mark.asyncio
async def test_the_loop_keeps_going_after_a_failed_pass():
    calls = 0

    def stop_after_two():
        nonlocal calls
        calls += 1
        if calls == 2:
            holder["engine"].request_stop()

    holder: dict[str, OeeService] = {}
    scheduler = FakeScheduler(failures=1, on_pass=stop_after_two)
    holder["engine"] = service(scheduler)
    await asyncio.wait_for(holder["engine"].run_forever(), timeout=2.0)
    # Two passes: the first raised, and the loop did not treat that as a reason to stop.
    assert len(scheduler.calls) == 2


# --- wiring --------------------------------------------------------------------------


def test_build_scheduler_rejects_a_metrics_table_that_is_not_an_identifier():
    # The table name reaches SQL by interpolation, so the guard in MetricSource must fire at
    # startup rather than on the first query of the first shift.
    with pytest.raises(ValueError, match="not a plain SQL identifier"):
        build_scheduler(config(metrics_table="uns_metrics; DROP TABLE oee.shift_result"), object(), None)


def test_build_scheduler_returns_a_scheduler_for_a_sane_configuration():
    from uns_oee.scheduler import ShiftScheduler

    assert isinstance(build_scheduler(config(), object(), None), ShiftScheduler)
