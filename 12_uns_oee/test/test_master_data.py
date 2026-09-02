"""Tests for the pure half of master-data loading.

The queries themselves are exercised against a real database in the end-to-end integration
test. What is worth pinning here is the resolution logic, because each rule has a quiet
failure mode: an ideal cycle time that falls back to the wrong default reads as a Performance
change nobody made, and an exception that resolves to the wrong Asset silently rewrites
Loading Time for a line that was running.
"""

from dataclasses import replace
from datetime import datetime, time, timezone

from uns_oee.classifier import ReasonResolver, ReasonSpec
from uns_oee.master_data import (
    ExceptionWindow,
    UnitMasterData,
    applies_to,
    exception_intervals,
)
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot
from uns_oee.sources import MetricRef
from uns_oee.states import Interval

LINE = "CovestroAG/Dormagen/Production/Line1"


def t(hour: int) -> datetime:
    return datetime(2026, 9, 7, hour, tzinfo=timezone.utc)


def unit(ideal: dict[str | None, float] | None = None) -> UnitMasterData:
    return UnitMasterData(
        unit_id=1,
        asset_id=42,
        asset_path=LINE,
        schedule=ShiftSchedule(
            name="Dormagen 3-shift",
            timezone="Europe/Berlin",
            slots=(ShiftSlot(0, time(6, 0), 480, "A"),),
        ),
        producing_states=("EXECUTE",),
        state_ref=MetricRef(f"{LINE}/Cell1/MES-01/Status/PackMlState", "value"),
        good_ref=MetricRef(f"{LINE}/Cell1/MES-01/ProcessValue/GoodCount", "value"),
        reject_ref=MetricRef(f"{LINE}/Cell1/MES-01/ProcessValue/RejectCount", "value"),
        product_ref=MetricRef(f"{LINE}/Cell1/MES-01/Status/RecipeId", "value"),
        ideal_cycle_times=ideal if ideal is not None else {None: 3.0, "R-100-STD": 2.0},
        resolver=ReasonResolver(
            reasons={"UNCLASSIFIED": ReasonSpec("UNCLASSIFIED", "Unclassified", "UNKNOWN", False)},
            unit_rules={},
            default_rules={},
        ),
    )


def test_an_exact_product_wins_over_the_asset_default():
    assert unit().ideal_cycle_time_for("R-100-STD") == 2.0


def test_an_unknown_product_falls_back_to_the_asset_default():
    assert unit().ideal_cycle_time_for("R-999-NEW") == 3.0


def test_no_product_uses_the_asset_default():
    assert unit().ideal_cycle_time_for(None) == 3.0


def test_with_no_default_an_unknown_product_has_no_ideal_cycle_time():
    assert unit({"R-100-STD": 2.0}).ideal_cycle_time_for("R-999-NEW") is None


def test_refs_lists_every_series_the_unit_reads():
    assert len(unit().refs) == 4
    assert unit().refs[0] == unit().state_ref


def test_a_unit_with_no_product_binding_reads_three_series():
    assert len(replace(unit(), product_ref=None).refs) == 3


def test_a_unit_with_no_reject_binding_reads_three_series():
    # A machine with no reject counter is a real configuration. It reports quality 1.0, and
    # the missing binding is visible in the unit row rather than assumed away.
    assert len(replace(unit(), reject_ref=None).refs) == 3


def test_a_unit_with_neither_optional_binding_reads_two_series():
    assert len(replace(unit(), reject_ref=None, product_ref=None).refs) == 2


def test_an_exception_with_no_asset_applies_everywhere():
    assert applies_to(None, LINE) is True


def test_an_exception_on_the_unit_itself_applies():
    assert applies_to(LINE, LINE) is True


def test_an_exception_on_an_ancestor_applies():
    assert applies_to("CovestroAG/Dormagen", LINE) is True
    assert applies_to("CovestroAG", LINE) is True


def test_an_exception_on_a_descendant_does_not_apply():
    assert applies_to(f"{LINE}/Cell1", LINE) is False


def test_an_exception_on_a_sibling_does_not_apply():
    assert applies_to("CovestroAG/Dormagen/Production/Line2", LINE) is False


def test_a_prefix_that_is_not_a_path_boundary_does_not_apply():
    # "Line1" must not match "Line10". The separator is part of the comparison.
    assert applies_to("CovestroAG/Dormagen/Production/Line10", LINE) is False
    assert applies_to("CovestroAG/Dormagen/Production/Line1", f"{LINE}0") is False


def test_exception_intervals_are_extracted_in_order():
    windows = [
        ExceptionWindow(interval=Interval(t(10), t(11)), kind="PLANNED_DOWN", asset_path=LINE),
        ExceptionWindow(interval=Interval(t(6), t(7)), kind="HOLIDAY", asset_path=None),
    ]
    assert exception_intervals(windows) == [Interval(t(6), t(7)), Interval(t(10), t(11))]


def test_overlapping_exceptions_are_coalesced_so_they_cannot_be_double_counted():
    windows = [
        ExceptionWindow(interval=Interval(t(6), t(9)), kind="PLANNED_DOWN", asset_path=LINE),
        ExceptionWindow(interval=Interval(t(8), t(11)), kind="HOLIDAY", asset_path=None),
    ]
    assert exception_intervals(windows) == [Interval(t(6), t(11))]
