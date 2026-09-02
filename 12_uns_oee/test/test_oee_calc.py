"""Tests for the OEE arithmetic.

Spec section 8.1 is a table of six cases in which the obvious implementation either raises
ZeroDivisionError or - much worse - returns a believable number. Each has a test here. The
believable-number cases are the reason `status` exists: a shift nobody staffed is not a 0%
shift, and recording it as one poisons every average it enters for the rest of the year.
"""

from datetime import datetime, timezone

from uns_model.oee_tables import OEE_STATUSES

from uns_oee.classifier import ClassifiedStop
from uns_oee.oee_calc import (
    STATUS_MISSING_IDEAL_CYCLE_TIME,
    STATUS_NO_INPUT_DATA,
    STATUS_NO_LOADING_TIME,
    STATUS_NO_PRODUCTION,
    STATUS_OK,
    ProductSegment,
    ShiftInputs,
    compute,
)
from uns_oee.states import Interval


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


SHIFT = Interval(t(6), t(14))  # eight hours = 28800 s


def stop(from_h: int, to_h: int, *, planned: bool, state: str = "HELD") -> ClassifiedStop:
    return ClassifiedStop(
        interval=Interval(t(from_h), t(to_h)),
        state_value=state,
        reason_code="CHANGEOVER" if planned else "BREAKDOWN",
        is_planned=planned,
        source="auto",
        note=None,
        assigned_by=None,
    )


def segment(
    *,
    code: str | None = "R-100-STD",
    intervals: tuple[Interval, ...] = (SHIFT,),
    ideal: float | None = 2.0,
    good: float = 0.0,
    reject: float = 0.0,
) -> ProductSegment:
    return ProductSegment(
        product_code=code,
        intervals=intervals,
        ideal_cycle_time_s=ideal,
        good_count=good,
        reject_count=reject,
    )


def test_a_clean_shift_multiplies_out():
    # Loading 28800 s, one hour unplanned stop -> Run Time 25200 s.
    # 12000 units at an ideal 2.0 s/unit = 24000 s of work in 25200 s of run time.
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            classified_stops=(stop(9, 10, planned=False),),
            products=(segment(good=11760, reject=240),),
        )
    )
    assert metrics.loading_time_s == 28800.0
    assert metrics.planned_down_s == 0.0
    assert metrics.unplanned_down_s == 3600.0
    assert metrics.run_time_s == 25200.0
    assert metrics.total_count == 12000.0
    assert metrics.availability == 25200.0 / 28800.0
    assert metrics.performance == (2.0 * 12000.0) / 25200.0
    assert metrics.quality == 11760.0 / 12000.0
    assert metrics.oee == metrics.availability * metrics.performance * metrics.quality
    assert metrics.status == STATUS_OK


def test_a_planned_reason_stop_leaves_loading_time():
    # Availability is not punished for a changeover: the hour comes out of the denominator.
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(9, 10, planned=True),), products=(segment(good=100),))
    )
    assert metrics.planned_down_s == 3600.0
    assert metrics.loading_time_s == 25200.0
    assert metrics.unplanned_down_s == 0.0
    assert metrics.run_time_s == 25200.0
    assert metrics.availability == 1.0


def test_a_calendar_exception_also_leaves_loading_time():
    metrics = compute(
        ShiftInputs(window=SHIFT, exception_intervals=(Interval(t(6), t(8)),), products=(segment(good=100),))
    )
    assert metrics.planned_down_s == 7200.0
    assert metrics.loading_time_s == 21600.0


def test_an_exception_overlapping_a_planned_stop_is_counted_once():
    # Summing would give 7200 + 3600 = 10800 and inflate Availability. The union is 7200.
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            exception_intervals=(Interval(t(6), t(8)),),
            classified_stops=(stop(7, 8, planned=True),),
            products=(segment(good=100),),
        )
    )
    assert metrics.planned_down_s == 7200.0
    assert metrics.loading_time_s == 21600.0


def test_an_unplanned_stop_inside_planned_time_does_not_reduce_run_time_twice():
    # The breakdown happened during a window nobody was scheduled to run. It is already out
    # of Loading Time, so it must not also come out of Run Time.
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            exception_intervals=(Interval(t(6), t(8)),),
            classified_stops=(stop(6, 7, planned=False),),
            products=(segment(good=100),),
        )
    )
    assert metrics.loading_time_s == 21600.0
    assert metrics.unplanned_down_s == 0.0
    assert metrics.run_time_s == 21600.0


def test_an_unplanned_stop_straddling_the_planned_boundary_counts_only_its_loaded_part():
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            exception_intervals=(Interval(t(6), t(8)),),
            classified_stops=(stop(7, 9, planned=False),),
            products=(segment(good=100),),
        )
    )
    assert metrics.unplanned_down_s == 3600.0
    assert metrics.run_time_s == 18000.0


def test_overlapping_unplanned_stops_are_unioned():
    stops = (stop(9, 11, planned=False), stop(10, 12, planned=False))
    metrics = compute(ShiftInputs(window=SHIFT, classified_stops=stops, products=(segment(good=100),)))
    assert metrics.unplanned_down_s == 3 * 3600.0


def test_a_fully_planned_down_shift_has_no_factors():
    metrics = compute(
        ShiftInputs(window=SHIFT, exception_intervals=(SHIFT,), products=(segment(good=0),))
    )
    assert metrics.loading_time_s == 0.0
    assert metrics.status == STATUS_NO_LOADING_TIME
    assert metrics.availability is None
    assert metrics.performance is None
    assert metrics.quality is None
    assert metrics.oee is None


def test_a_scheduled_shift_that_produced_nothing_keeps_availability():
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(6, 10, planned=False),), products=(segment(),))
    )
    assert metrics.availability == (28800.0 - 14400.0) / 28800.0
    assert metrics.performance is None
    assert metrics.quality is None
    assert metrics.oee is None
    assert metrics.status == STATUS_NO_PRODUCTION


def test_counts_with_no_run_time_null_performance_but_keep_quality():
    # The inputs disagree: the unit was stopped all shift yet the counter moved. Inventing a
    # Performance would hide that; Quality is still a fact about the units that exist.
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(6, 14, planned=False),), products=(segment(good=90, reject=10),))
    )
    assert metrics.run_time_s == 0.0
    assert metrics.availability == 0.0
    assert metrics.performance is None
    assert metrics.quality == 0.9
    assert metrics.oee is None
    assert metrics.status == STATUS_NO_PRODUCTION


def test_a_silent_unit_is_distinguished_from_an_idle_one():
    metrics = compute(ShiftInputs(window=SHIFT, has_input_data=False))
    assert metrics.status == STATUS_NO_INPUT_DATA
    assert metrics.availability is None
    assert metrics.loading_time_s == 0.0
    assert metrics.run_time_s == 0.0
    assert metrics.total_count == 0.0


def test_a_missing_ideal_cycle_time_nulls_performance_and_says_so():
    metrics = compute(ShiftInputs(window=SHIFT, products=(segment(ideal=None, good=100),)))
    assert metrics.performance is None
    assert metrics.performance_raw is None
    assert metrics.quality == 1.0
    assert metrics.oee is None
    assert metrics.status == STATUS_MISSING_IDEAL_CYCLE_TIME
    assert metrics.missing_ideal_cycle_time is True


def test_a_segment_that_produced_nothing_needs_no_ideal_cycle_time():
    products = (
        segment(code="R-100-STD", intervals=(Interval(t(6), t(10)),), ideal=2.0, good=1000),
        segment(code="R-330-LOW", intervals=(Interval(t(10), t(14)),), ideal=None),
    )
    metrics = compute(ShiftInputs(window=SHIFT, products=products))
    assert metrics.status == STATUS_OK
    assert metrics.missing_ideal_cycle_time is False


def test_performance_above_one_is_clamped_and_flagged():
    # 20000 units at 2.0 s each is 40000 s of work claimed inside 28800 s of run time. The
    # authored ideal cycle time is wrong; the true value is kept so it can be seen.
    metrics = compute(ShiftInputs(window=SHIFT, products=(segment(good=20000),)))
    assert metrics.performance_raw == 40000.0 / 28800.0
    assert metrics.performance == 1.0
    assert metrics.performance_over_unity is True
    assert metrics.oee == metrics.availability * 1.0 * metrics.quality
    assert metrics.status == STATUS_OK


def test_performance_is_time_weighted_across_products():
    products = (
        segment(code="R-100-STD", intervals=(Interval(t(6), t(10)),), ideal=2.0, good=6000),
        segment(code="R-220-STD", intervals=(Interval(t(10), t(14)),), ideal=4.0, good=3000),
    )
    metrics = compute(ShiftInputs(window=SHIFT, products=products))
    assert metrics.total_count == 9000.0
    assert metrics.performance == (2.0 * 6000.0 + 4.0 * 3000.0) / 28800.0
    assert [item.run_time_s for item in metrics.products] == [14400.0, 14400.0]


def test_a_products_run_time_excludes_downtime_inside_its_own_segment():
    products = (
        segment(code="R-100-STD", intervals=(Interval(t(6), t(10)),), ideal=2.0, good=6000),
        segment(code="R-220-STD", intervals=(Interval(t(10), t(14)),), ideal=4.0, good=3000),
    )
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(8, 9, planned=False),), products=products)
    )
    assert [item.run_time_s for item in metrics.products] == [10800.0, 14400.0]
    assert sum(item.run_time_s for item in metrics.products) == metrics.run_time_s


def test_quality_uses_good_over_total_and_reject_is_reported():
    metrics = compute(ShiftInputs(window=SHIFT, products=(segment(good=900, reject=100),)))
    assert metrics.good_count == 900.0
    assert metrics.reject_count == 100.0
    assert metrics.total_count == 1000.0
    assert metrics.quality == 0.9


def test_every_status_the_calculator_returns_is_a_declared_status():
    assert {
        STATUS_OK,
        STATUS_NO_LOADING_TIME,
        STATUS_NO_PRODUCTION,
        STATUS_MISSING_IDEAL_CYCLE_TIME,
        STATUS_NO_INPUT_DATA,
    } <= set(OEE_STATUSES)


def test_no_products_at_all_is_no_production_not_a_crash():
    metrics = compute(ShiftInputs(window=SHIFT))
    assert metrics.status == STATUS_NO_PRODUCTION
    assert metrics.availability == 1.0
    assert metrics.products == ()
