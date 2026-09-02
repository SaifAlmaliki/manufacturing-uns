"""Tests for uns_oee.prometheus_metrics.

The exposed text is what is asserted, not the Python attributes. Spec section 14 is a promise
about metric names, and prometheus_client renames things - a Counter declared as `x` is
exposed as `x_total`. Only `generate_latest` can tell whether the promise was kept.
"""

from datetime import datetime, timedelta, timezone

import pytest
from prometheus_client import generate_latest

from uns_oee.oee_calc import ShiftMetrics
from uns_oee.pipeline import (
    ACTION_COMPUTED,
    ACTION_REVISED,
    ACTION_UNCHANGED,
    ShiftOutcome,
)
from uns_oee.prometheus_metrics import OeeMetrics, Readings, read_gauges
from uns_oee.scheduler import BackfillTally, PassSummary
from uns_oee.shift_calendar import ShiftWindow

LINE = "CovestroAG/Dormagen/Production/Line1"
WINDOW = ShiftWindow(
    start=datetime(2026, 9, 7, 6, tzinfo=timezone.utc),
    end=datetime(2026, 9, 7, 14, tzinfo=timezone.utc),
    label="A",
)

#: Every series spec section 14 promises, as the names Prometheus actually scrapes.
EXPECTED_SERIES = (
    "uns_oee_shifts_computed_total",
    "uns_oee_shift_compute_seconds_bucket",
    "uns_oee_revisions_total",
    "uns_oee_late_data_detected_total",
    "uns_oee_input_rows",
    "uns_oee_shift_oee",
    "uns_oee_availability",
    "uns_oee_performance",
    "uns_oee_quality",
    "uns_oee_performance_over_unity_total",
    "uns_oee_counter_resets_total",
    "uns_oee_missing_ideal_cycle_time_total",
    "uns_oee_unclassified_downtime_seconds_total",
    "uns_oee_recompute_queue_depth",
    "uns_oee_unpublished_results",
    "uns_oee_publish_total",
    "uns_oee_publish_errors_total",
    "uns_oee_last_shift_close_timestamp",
    "uns_oee_db_up",
    "uns_oee_backfill_shifts_total",
    "uns_oee_backfill_shifts_skipped_total",
    "uns_oee_compute_failures_total",
)


def good_metrics(**overrides) -> ShiftMetrics:
    values = {
        "loading_time_s": 27000.0,
        "run_time_s": 24084.0,
        "good_count": 12840.0,
        "reject_count": 182.0,
        "total_count": 13022.0,
        "availability": 0.892,
        "performance": 0.841,
        "quality": 0.952,
        "oee": 0.714,
        "status": "OK",
    }
    values.update(overrides)
    return ShiftMetrics(**values)


def outcome(**overrides) -> ShiftOutcome:
    values = {
        "unit_id": 1,
        "asset_path": LINE,
        "window": WINDOW,
        "action": ACTION_COMPUTED,
        "metrics": good_metrics(),
        "revision": 1,
        "published": True,
        "input_rows": 2880,
        "counter_resets": 0,
        "unclassified_seconds": 0.0,
        "compute_seconds": 0.4,
    }
    values.update(overrides)
    return ShiftOutcome(**values)


def exposed(metrics: OeeMetrics) -> str:
    return generate_latest(metrics.registry).decode("utf-8")


def series(text: str, name: str, labels: str = "") -> float | None:
    """The value of one sample line, or None if the series is absent."""
    needle = f"{name}{labels} "
    for line in text.splitlines():
        if line.startswith(needle):
            return float(line.rsplit(" ", 1)[1])
    return None


# --- the promise ---------------------------------------------------------------------


def test_every_series_the_spec_names_is_exposed():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(
            outcomes=(outcome(),),
            units=1,
            windows=1,
            failures=1,
            backfilled=True,
            backfill=(
                BackfillTally(
                    unit_id=1,
                    asset_path=LINE,
                    computed=2,
                    skipped_no_history=0,
                    skipped_predates_data=28,
                ),
            ),
        )
    )
    metrics.apply(Readings(recompute_queue_depth=3, unpublished_results=1, database_up=True))
    text = exposed(metrics)
    missing = [name for name in EXPECTED_SERIES if name not in text]
    assert missing == []


def test_the_registry_carries_nothing_but_this_engines_series():
    text = exposed(OeeMetrics())
    # Not the default registry: no process or GC collectors on this port.
    assert "python_gc_objects_collected_total" not in text
    assert "process_virtual_memory_bytes" not in text


def test_two_instances_do_not_collide_on_one_registry():
    # Module-level Counters would raise "Duplicated timeseries" here.
    first, second = OeeMetrics(), OeeMetrics()
    assert first.registry is not second.registry


# --- what one shift records ----------------------------------------------------------


def test_a_computed_shift_records_its_factors_and_its_close_time():
    metrics = OeeMetrics()
    metrics.observe_pass(PassSummary(outcomes=(outcome(),)))
    text = exposed(metrics)

    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_shift_oee", label) == 0.714
    assert series(text, "uns_oee_availability", label) == 0.892
    assert series(text, "uns_oee_performance", label) == 0.841
    assert series(text, "uns_oee_quality", label) == 0.952
    assert series(text, "uns_oee_input_rows", label) == 2880.0
    assert series(text, "uns_oee_last_shift_close_timestamp", label) == WINDOW.end.timestamp()
    assert series(text, "uns_oee_shifts_computed_total", f'{{status="OK",unit="{LINE}"}}') == 1.0


def test_a_null_factor_is_not_exposed_as_zero():
    metrics = OeeMetrics()
    silent = good_metrics(
        availability=None, performance=None, quality=None, oee=None, status="NO_INPUT_DATA"
    )
    metrics.observe_pass(PassSummary(outcomes=(outcome(metrics=silent),)))
    text = exposed(metrics)

    label = f'{{unit="{LINE}"}}'
    # A zero OEE and an undefined OEE are different facts, and a trend that plots the second
    # as the first invents a catastrophic shift. Absent is the only honest rendering.
    assert series(text, "uns_oee_shift_oee", label) is None
    assert series(text, "uns_oee_availability", label) is None
    # The shift is still counted, with the status that says why there are no factors.
    assert series(text, "uns_oee_shifts_computed_total", f'{{status="NO_INPUT_DATA",unit="{LINE}"}}') == 1.0


def test_an_unchanged_shift_records_nothing():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(outcomes=(outcome(action=ACTION_UNCHANGED, metrics=None),))
    )
    text = exposed(metrics)
    assert series(text, "uns_oee_shifts_computed_total", f'{{status="OK",unit="{LINE}"}}') is None
    assert series(text, "uns_oee_shift_compute_seconds_count") == 0.0


def test_a_revision_counts_as_a_revision_and_as_late_data():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(outcomes=(outcome(action=ACTION_REVISED, revision=2, late_data=True),))
    )
    text = exposed(metrics)
    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_revisions_total", label) == 1.0
    assert series(text, "uns_oee_late_data_detected_total", label) == 1.0


def test_a_reassignment_is_a_revision_but_not_late_data():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(outcomes=(outcome(action=ACTION_REVISED, revision=2, late_data=False),))
    )
    text = exposed(metrics)
    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_revisions_total", label) == 1.0
    assert series(text, "uns_oee_late_data_detected_total", label) == 0.0


def test_the_data_quality_signals_are_counted():
    metrics = OeeMetrics()
    flawed = good_metrics(missing_ideal_cycle_time=True, performance_over_unity=True)
    metrics.observe_pass(
        PassSummary(
            outcomes=(outcome(metrics=flawed, counter_resets=2, unclassified_seconds=3600.0),)
        )
    )
    text = exposed(metrics)
    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_missing_ideal_cycle_time_total", label) == 1.0
    assert series(text, "uns_oee_performance_over_unity_total", label) == 1.0
    assert series(text, "uns_oee_counter_resets_total", label) == 2.0
    assert series(text, "uns_oee_unclassified_downtime_seconds_total", label) == 3600.0


def test_a_failed_publish_is_an_error_not_a_publish():
    metrics = OeeMetrics()
    metrics.observe_pass(PassSummary(outcomes=(outcome(published=False),)))
    text = exposed(metrics)
    assert series(text, "uns_oee_publish_total") == 0.0
    assert series(text, "uns_oee_publish_errors_total") == 1.0


def test_the_two_kinds_of_skipped_backfill_are_labelled_apart():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(
            backfill=(
                BackfillTally(1, LINE, computed=2, skipped_no_history=0, skipped_predates_data=28),
                BackfillTally(2, "Line2", computed=0, skipped_no_history=30, skipped_predates_data=0),
            )
        )
    )
    text = exposed(metrics)
    assert series(text, "uns_oee_backfill_shifts_total", f'{{unit="{LINE}"}}') == 2.0
    assert (
        series(
            text,
            "uns_oee_backfill_shifts_skipped_total",
            f'{{reason="PREDATES_DATA",unit="{LINE}"}}',
        )
        == 28.0
    )
    assert (
        series(
            text, "uns_oee_backfill_shifts_skipped_total", '{reason="NO_HISTORY",unit="Line2"}'
        )
        == 30.0
    )


def test_a_pass_failure_is_counted():
    metrics = OeeMetrics()
    metrics.observe_pass(PassSummary(failures=3))
    assert series(exposed(metrics), "uns_oee_compute_failures_total") == 3.0


def test_the_readings_land_on_their_gauges():
    metrics = OeeMetrics()
    metrics.apply(Readings(recompute_queue_depth=4, unpublished_results=7, database_up=True))
    text = exposed(metrics)
    assert series(text, "uns_oee_recompute_queue_depth") == 4.0
    assert series(text, "uns_oee_unpublished_results") == 7.0
    assert series(text, "uns_oee_db_up") == 1.0


def test_a_database_that_is_down_reads_as_zero():
    metrics = OeeMetrics()
    metrics.apply(Readings(database_up=False))
    assert series(exposed(metrics), "uns_oee_db_up") == 0.0


# --- the two counts that come from the database --------------------------------------


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeConnection:
    def __init__(self, results, raises=False):
        self._results = list(results)
        self._raises = raises
        self.calls: list[str] = []

    async def execute(self, statement, parameters=None):
        if self._raises:
            raise RuntimeError("could not connect to server")
        self.calls.append(str(statement).lower())
        return self._results.pop(0)


class FakeDatabase:
    def __init__(self, *results, raises=False):
        self.connection = FakeConnection(results, raises=raises)

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_the_queue_depth_and_the_backlog_are_read_together():
    database = FakeDatabase(FakeResult(3), FakeResult(11))
    readings = await read_gauges(database)

    assert readings == Readings(recompute_queue_depth=3, unpublished_results=11, database_up=True)
    queue_sql, backlog_sql = database.connection.calls
    assert "recompute_request" in queue_sql and "claimed_at is null" in queue_sql
    assert "shift_result" in backlog_sql and "published_at is null" in backlog_sql


@pytest.mark.asyncio
async def test_a_database_that_refuses_the_query_reads_as_down():
    readings = await read_gauges(FakeDatabase(raises=True))
    # Nothing invented: the counts stay at zero and `database_up` is what the alert fires on.
    assert readings == Readings(recompute_queue_depth=0, unpublished_results=0, database_up=False)
