"""Tests for uns_oee.scheduler - which shifts a pass computes, and why.

The window arithmetic is pure and gets real schedules: the bugs that matter are a shift
computed before the historian caught up, a shift re-checked forever, and a backfill that
invents thirty days of NO_INPUT_DATA out of dropped chunks. The pass itself gets fakes,
because what matters there is that one broken unit does not stop the plant's other lines.
"""

from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from uns_oee.oee_config import OeeConfig
from uns_oee.pipeline import ACTION_COMPUTED, ShiftOutcome
from uns_oee.scheduler import (
    ClaimedRange,
    ShiftScheduler,
    backfill_windows,
    claim_requests,
    clamp_backfill_days,
    ordered_unique,
    ranges_for,
    recheck_windows,
    request_windows,
    retention_days,
)
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot, ShiftWindow

NOW = datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc)
SETTLE = 15
LATE = 48

#: One eight-hour morning shift every day, in UTC so the arithmetic in this file is readable.
#: Task 4's tests are where the timezone and DST behaviour is pinned.
DAILY = ShiftSchedule(
    name="daily mornings",
    timezone="UTC",
    slots=tuple(ShiftSlot(day, time(6, 0), 480, "A") for day in range(7)),
)


class FakeUnit:
    """Only the three attributes the scheduler reads off a UnitMasterData."""

    def __init__(self, unit_id: int = 1, schedule: ShiftSchedule = DAILY) -> None:
        self.unit_id = unit_id
        self.asset_path = f"CovestroAG/Dormagen/Production/Line{unit_id}"
        self.schedule = schedule
        self.refs = ()


def days(windows) -> list[int]:
    return [window.start.day for window in windows]


# --- the window arithmetic -----------------------------------------------------------


def test_a_settled_shift_inside_the_late_window_is_rechecked():
    windows = recheck_windows(FakeUnit(), NOW, settle_minutes=SETTLE, late_window_hours=LATE)
    # Sept 9 ended an hour ago, Sept 8 twenty-five hours ago. Sept 7 ended 49h ago.
    assert days(windows) == [8, 9]


def test_a_shift_that_has_not_settled_is_not_rechecked():
    just_ended = datetime(2026, 9, 9, 14, 10, tzinfo=timezone.utc)
    windows = recheck_windows(FakeUnit(), just_ended, settle_minutes=SETTLE, late_window_hours=LATE)
    assert 9 not in days(windows)


def test_a_shift_older_than_the_late_window_is_not_rechecked():
    windows = recheck_windows(FakeUnit(), NOW, settle_minutes=SETTLE, late_window_hours=LATE)
    assert 7 not in days(windows)
    assert 6 not in days(windows)


def test_the_lookback_covers_a_shift_longer_than_a_day():
    marathon = ShiftSchedule(
        name="weekly",
        timezone="UTC",
        slots=(ShiftSlot(0, time(6, 0), 60 * 30, "LONG"),),
    )
    # Started Mon Sept 7 06:00, ended Tue Sept 8 12:00 - 27h before NOW, so inside the late
    # window. A fixed one-day lookback would have missed its start.
    windows = recheck_windows(
        FakeUnit(schedule=marathon), NOW, settle_minutes=SETTLE, late_window_hours=LATE
    )
    assert days(windows) == [7]


def test_backfill_enumerates_from_now_minus_backfill_days_oldest_first():
    plan = backfill_windows(
        FakeUnit(),
        NOW,
        settle_minutes=SETTLE,
        backfill_days=3,
        earliest_input_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert days(plan.windows) == [7, 8, 9]
    assert plan.skipped_predates_data == 0


def test_a_backfill_shift_ending_before_the_first_input_row_is_skipped():
    plan = backfill_windows(
        FakeUnit(),
        NOW,
        settle_minutes=SETTLE,
        backfill_days=30,
        earliest_input_at=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
    )
    # Sept 7's shift ends at 14:00, after the first row, so it is computed. Everything before
    # it predates the data entirely and is skipped rather than written as NO_INPUT_DATA.
    assert days(plan.windows) == [7, 8, 9]
    # Aug 11 through Sept 6 inclusive: counted, so the choice is visible in Prometheus.
    assert plan.skipped_predates_data == 27


def test_a_unit_that_never_published_anything_gets_no_backfill():
    plan = backfill_windows(
        FakeUnit(), NOW, settle_minutes=SETTLE, backfill_days=30, earliest_input_at=None
    )
    assert plan.windows == ()
    assert plan.skipped_no_history == 30
    assert plan.skipped_predates_data == 0


def test_a_recompute_range_becomes_the_shift_windows_inside_it():
    ranges = ((datetime(2026, 9, 7, tzinfo=timezone.utc), datetime(2026, 9, 9, tzinfo=timezone.utc)),)
    windows = request_windows(FakeUnit(), ranges, NOW, settle_minutes=SETTLE)
    # Requested ranges ignore the late window entirely: a human asked.
    assert days(windows) == [7, 8]


def test_an_unsettled_shift_inside_a_requested_range_is_not_returned():
    ranges = ((datetime(2026, 9, 9, tzinfo=timezone.utc), datetime(2026, 9, 10, tzinfo=timezone.utc)),)
    just_ended = datetime(2026, 9, 9, 14, 10, tzinfo=timezone.utc)
    assert request_windows(FakeUnit(), ranges, just_ended, settle_minutes=SETTLE) == []


def test_a_range_with_no_unit_applies_to_every_unit():
    claimed = [ClaimedRange(request_id=1, unit_id=None, start=NOW, end=NOW + timedelta(hours=1))]
    assert len(ranges_for(1, claimed)) == 1
    assert len(ranges_for(99, claimed)) == 1


def test_a_range_with_a_unit_applies_only_to_that_unit():
    claimed = [ClaimedRange(request_id=1, unit_id=1, start=NOW, end=NOW + timedelta(hours=1))]
    assert len(ranges_for(1, claimed)) == 1
    assert ranges_for(2, claimed) == ()


def test_windows_from_two_sources_collapse_to_one_ordered_list():
    first = ShiftWindow(start=NOW - timedelta(days=1), end=NOW - timedelta(hours=16), label="A")
    second = ShiftWindow(start=NOW - timedelta(hours=9), end=NOW - timedelta(hours=1), label="A")
    assert ordered_unique([second, first, second]) == [first, second]


def test_backfill_days_is_clamped_to_the_retention_policy():
    assert clamp_backfill_days(400, 365.25) == 365


def test_a_backfill_inside_retention_is_left_alone():
    assert clamp_backfill_days(30, 365.25) == 30


def test_no_retention_policy_leaves_the_backfill_alone():
    assert clamp_backfill_days(400, None) == 400


# --- the three statements ------------------------------------------------------------


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, results):
        self._results = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, parameters=None):
        # Compiled against PostgreSQL because SKIP LOCKED does not exist in the default
        # dialect, and it is the whole point of the claim query.
        compiled = statement.compile(dialect=postgresql.dialect())
        self.calls.append((str(compiled).lower(), dict(parameters or {})))
        return self._results.pop(0) if self._results else FakeResult([])


class FakeDatabase:
    """Stands in for `uns_model.engine.Database`; only `begin()` is used here."""

    def __init__(self, *results):
        self.connection = FakeConnection(results)

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_the_retention_query_asks_timescale_for_the_metrics_table():
    database = FakeDatabase(FakeResult([(365.25,)]))
    assert await retention_days(database, "uns_metrics") == 365.25
    sql, params = database.connection.calls[0]
    assert "timescaledb_information.jobs" in sql
    assert "policy_retention" in sql
    assert params == {"table": "uns_metrics"}


@pytest.mark.asyncio
async def test_no_retention_row_reads_as_no_policy():
    assert await retention_days(FakeDatabase(FakeResult([])), "uns_metrics") is None
    assert await retention_days(FakeDatabase(FakeResult([(None,)])), "uns_metrics") is None


@pytest.mark.asyncio
async def test_claiming_skips_rows_another_worker_holds():
    rows = [(7, 1, NOW - timedelta(days=1), NOW)]
    database = FakeDatabase(FakeResult(rows))
    claimed = await claim_requests(database, NOW)

    assert claimed == [ClaimedRange(request_id=7, unit_id=1, start=NOW - timedelta(days=1), end=NOW)]
    sql, _ = database.connection.calls[0]
    # SKIP LOCKED is what makes a second engine instance a no-op instead of a duplicate.
    assert "skip locked" in sql
    assert "claimed_at is null" in sql


# --- one pass ------------------------------------------------------------------------


class FakeSource:
    def __init__(self, earliest=None):
        self.earliest = earliest
        self.asked = 0

    async def earliest_sample_at(self, refs):
        self.asked += 1
        return self.earliest


class FakeMaster:
    def __init__(self, units):
        self.units = list(units)

    async def active_units(self):
        return list(self.units)


class FakePipeline:
    def __init__(self, *, failing_units=()):
        self.failing_units = set(failing_units)
        self.calls: list[tuple[int, datetime, datetime]] = []

    async def run_shift(self, unit, window, computed_at):
        if unit.unit_id in self.failing_units:
            raise RuntimeError("historian went away")
        self.calls.append((unit.unit_id, window.start, computed_at))
        return ShiftOutcome(
            unit_id=unit.unit_id,
            asset_path=unit.asset_path,
            window=window,
            action=ACTION_COMPUTED,
            metrics=None,
            revision=1,
            published=True,
        )


def scheduler(master, pipeline, source=None, *, claimed=(), backfill_days=30):
    config = OeeConfig(
        mqtt_host=None,
        settle_minutes=SETTLE,
        late_window_hours=LATE,
        backfill_days=backfill_days,
    )
    completed: list[tuple[tuple[int, ...], datetime]] = []

    async def fake_claim(database, at, *, limit=200):
        return list(claimed)

    async def fake_retention(database, table):
        return None

    async def fake_complete(database, request_ids, at, *, error=None):
        completed.append((tuple(request_ids), at))

    instance = ShiftScheduler(
        config=config,
        database=FakeDatabase(),
        source=source or FakeSource(),
        master=master,
        pipeline=pipeline,
        claim=fake_claim,
        retention=fake_retention,
        complete=fake_complete,
    )
    instance.completed = completed
    return instance


@pytest.mark.asyncio
async def test_a_pass_computes_every_settled_window_for_every_active_unit():
    pipeline = FakePipeline()
    master = FakeMaster([FakeUnit(1), FakeUnit(2)])
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    summary = await scheduler(master, pipeline, source).run_pass(NOW)

    assert summary.units == 2
    assert summary.failures == 0
    assert summary.backfilled is True
    # Sept 8 and Sept 9 for each unit: the backfill's windows are the same two, deduped.
    assert [(unit_id, start.day) for unit_id, start, _ in pipeline.calls] == [
        (1, 8), (1, 9), (2, 8), (2, 9),
    ]
    assert len(summary.outcomes) == 4


@pytest.mark.asyncio
async def test_the_backfill_only_runs_on_the_first_pass():
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    instance = scheduler(FakeMaster([FakeUnit(1)]), FakePipeline(), source)

    await instance.run_pass(NOW)
    assert source.asked == 1
    second = await instance.run_pass(NOW + timedelta(minutes=5))
    assert source.asked == 1
    assert second.backfilled is False


@pytest.mark.asyncio
async def test_a_failing_unit_does_not_stop_the_pass():
    pipeline = FakePipeline(failing_units={1})
    master = FakeMaster([FakeUnit(1), FakeUnit(2)])
    summary = await scheduler(master, pipeline).run_pass(NOW)

    assert summary.failures == 2  # unit 1's two windows
    assert {unit_id for unit_id, _, _ in pipeline.calls} == {2}


@pytest.mark.asyncio
async def test_a_pass_with_a_failure_retries_the_backfill():
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    instance = scheduler(FakeMaster([FakeUnit(1)]), FakePipeline(failing_units={1}), source)

    await instance.run_pass(NOW)
    await instance.run_pass(NOW + timedelta(minutes=5))
    # A backfill that half failed is not a backfill. Two enumerations, not one.
    assert source.asked == 2


@pytest.mark.asyncio
async def test_a_claimed_request_is_computed_and_completed():
    pipeline = FakePipeline()
    request = ClaimedRange(
        request_id=7,
        unit_id=1,
        start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    instance = scheduler(FakeMaster([FakeUnit(1)]), pipeline, claimed=[request])
    await instance.run_pass(NOW)

    computed = sorted({start.day for _, start, _ in pipeline.calls})
    # Sept 1 and 2 from the request, plus the two the late window already covered.
    assert computed == [1, 2, 8, 9]
    assert instance.completed == [((7,), NOW)]


@pytest.mark.asyncio
async def test_the_pipeline_is_given_the_passs_timestamp():
    pipeline = FakePipeline()
    await scheduler(FakeMaster([FakeUnit(1)]), pipeline).run_pass(NOW)
    assert {computed_at for _, _, computed_at in pipeline.calls} == {NOW}


@pytest.mark.asyncio
async def test_every_outcome_is_stamped_with_how_long_it_took():
    summary = await scheduler(FakeMaster([FakeUnit(1)]), FakePipeline()).run_pass(NOW)
    # Monotonic, so never negative even if the host clock steps mid-pass.
    assert all(outcome.compute_seconds >= 0.0 for outcome in summary.outcomes)


@pytest.mark.asyncio
async def test_the_pass_reports_what_the_backfill_declined():
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    summary = await scheduler(FakeMaster([FakeUnit(1)]), FakePipeline(), source).run_pass(NOW)
    tally = summary.backfill[0]
    assert tally.asset_path.endswith("Line1")
    assert (tally.computed, tally.skipped_predates_data, tally.skipped_no_history) == (2, 28, 0)


@pytest.mark.asyncio
async def test_a_later_pass_reports_no_backfill_at_all():
    instance = scheduler(FakeMaster([FakeUnit(1)]), FakePipeline())
    await instance.run_pass(NOW)
    assert (await instance.run_pass(NOW + timedelta(minutes=5))).backfill == ()


@pytest.mark.asyncio
async def test_a_silent_unit_still_gets_its_steady_state_windows():
    pipeline = FakePipeline()
    # earliest_sample_at is None, so the unit has never published. The backfill skips it, but
    # the late window does not: spec section 13 wants one NO_INPUT_DATA row per silent shift.
    await scheduler(FakeMaster([FakeUnit(1)]), pipeline, FakeSource(earliest=None)).run_pass(NOW)
    assert sorted(start.day for _, start, _ in pipeline.calls) == [8, 9]
