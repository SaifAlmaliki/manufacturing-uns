"""Tests for uns_oee.pipeline - the shift's assembly line.

Two halves. The pure functions get real sample series, because the bugs that matter here are
arithmetic: a product changeover counted twice, a stop truncated at the shift boundary, a
manual reason lost. The five-branch action decision gets fakes, because what matters there is
which writes happen - and a revision bump for a broker outage is a bug no arithmetic test
would catch.
"""

from datetime import datetime, time, timezone

import pytest

from uns_model.oee_tables import UNCLASSIFIED_REASON_CODE
from uns_oee.classifier import AUTO, MANUAL, ManualReason, ReasonResolver, ReasonSpec
from uns_oee.counters import Sample
from uns_oee.master_data import ExceptionWindow, UnitMasterData
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.pipeline import (
    ACTION_COMPUTED,
    ACTION_REPUBLISHED,
    ACTION_REVISED,
    ACTION_UNCHANGED,
    UNOBSERVED_STATE,
    ShiftPipeline,
    ShiftSamples,
    manual_digest,
    product_segments,
    shift_inputs,
    unclassified_seconds,
)
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot, ShiftWindow
from uns_oee.sources import Fingerprint, MetricRef
from uns_oee.states import Interval, StateSample
from uns_oee.store import StoredResult

LINE = "CovestroAG/Dormagen/Production/Line1"
MES = f"{LINE}/Cell1/MES-01"


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


WINDOW = ShiftWindow(start=t(6), end=t(14), label="A")
COMPUTED_AT = datetime(2026, 9, 7, 14, 15, tzinfo=timezone.utc)

REASONS = {
    UNCLASSIFIED_REASON_CODE: ReasonSpec(UNCLASSIFIED_REASON_CODE, "Unclassified", "UNKNOWN", False),
    "MECH_FAILURE": ReasonSpec("MECH_FAILURE", "Mechanical failure", "EQUIPMENT", False),
    "TOOL_CHANGE": ReasonSpec("TOOL_CHANGE", "Tool change", "PLANNED", True),
}


def unit(*, product_bound: bool = True) -> UnitMasterData:
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
        state_ref=MetricRef(f"{MES}/Status/PackMlState", "value"),
        good_ref=MetricRef(f"{MES}/ProcessValue/GoodCount", "value"),
        reject_ref=MetricRef(f"{MES}/ProcessValue/RejectCount", "value"),
        product_ref=MetricRef(f"{MES}/Status/RecipeId", "value") if product_bound else None,
        ideal_cycle_times={None: 3.0, "R-100-STD": 2.0},
        resolver=ReasonResolver(
            reasons=REASONS,
            unit_rules={},
            default_rules={"ABORTED": "MECH_FAILURE", "SUSPENDED": "TOOL_CHANGE"},
        ),
    )


def samples(
    *,
    state: tuple[StateSample, ...] = (),
    good: tuple[Sample, ...] = (),
    reject: tuple[Sample, ...] = (),
    product: tuple[StateSample, ...] = (),
) -> ShiftSamples:
    return ShiftSamples(state=state, good=good, reject=reject, product=product)


#: EXECUTE from before the boundary, ABORTED 09:00-10:00, EXECUTE to the end.
RUN_WITH_ONE_STOP = (
    StateSample(t(5, 58), "EXECUTE"),
    StateSample(t(9), "ABORTED"),
    StateSample(t(10), "EXECUTE"),
)
GOOD_CLIMB = (Sample(t(6), 0.0), Sample(t(10), 2500.0), Sample(t(14), 6000.0))
REJECT_CLIMB = (Sample(t(6), 0.0), Sample(t(14), 100.0))
TWO_PRODUCTS = (StateSample(t(6), "R-100-STD"), StateSample(t(10), "R-200-FAST"))


# --- the pure half --------------------------------------------------------------------------------


def test_a_unit_with_no_product_binding_gets_one_segment_spanning_the_shift():
    segments = product_segments(
        unit(product_bound=False), WINDOW, samples(good=GOOD_CLIMB, reject=REJECT_CLIMB)
    )
    assert len(segments) == 1
    assert segments[0].product_code is None
    assert segments[0].intervals == (Interval(t(6), t(14)),)
    assert segments[0].good_count == 6000.0
    assert segments[0].reject_count == 100.0
    assert segments[0].ideal_cycle_time_s == 3.0


def test_a_product_series_splits_the_shift_into_one_segment_per_code():
    segments = product_segments(
        unit(), WINDOW, samples(good=GOOD_CLIMB, reject=REJECT_CLIMB, product=TWO_PRODUCTS)
    )
    assert {segment.product_code for segment in segments} == {"R-100-STD", "R-200-FAST"}


def test_per_product_counts_sum_to_the_whole_window_delta():
    segments = product_segments(
        unit(), WINDOW, samples(good=GOOD_CLIMB, reject=REJECT_CLIMB, product=TWO_PRODUCTS)
    )
    by_code = {segment.product_code: segment for segment in segments}
    assert by_code["R-100-STD"].good_count == 2500.0
    assert by_code["R-200-FAST"].good_count == 3500.0
    assert sum(segment.good_count for segment in segments) == 6000.0


def test_each_segment_carries_the_ideal_cycle_time_for_its_own_code():
    segments = product_segments(unit(), WINDOW, samples(good=GOOD_CLIMB, product=TWO_PRODUCTS))
    by_code = {segment.product_code: segment for segment in segments}
    assert by_code["R-100-STD"].ideal_cycle_time_s == 2.0
    assert by_code["R-200-FAST"].ideal_cycle_time_s == 3.0


def test_a_product_that_ran_twice_keeps_both_of_its_intervals():
    interrupted = (
        StateSample(t(6), "R-100-STD"),
        StateSample(t(8), "R-200-FAST"),
        StateSample(t(10), "R-100-STD"),
    )
    segments = product_segments(unit(), WINDOW, samples(good=GOOD_CLIMB, product=interrupted))
    by_code = {segment.product_code: segment for segment in segments}
    assert by_code["R-100-STD"].intervals == (Interval(t(6), t(8)), Interval(t(10), t(14)))


def test_a_counter_reset_inside_the_shift_is_counted():
    restarted = (Sample(t(6), 0.0), Sample(t(10), 2500.0), Sample(t(11), 0.0), Sample(t(14), 900.0))
    assert samples(good=restarted).counter_resets == 1
    assert samples(good=GOOD_CLIMB, reject=REJECT_CLIMB).counter_resets == 0


def test_the_state_held_at_the_shift_start_is_carried_in():
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), {})
    # One stop only. If the 05:58 EXECUTE sample were dropped, the shift would open with an
    # unknown state and 06:00-09:00 would become a second, fabricated stop.
    assert len(inputs.classified_stops) == 1
    assert inputs.classified_stops[0].interval == Interval(t(9), t(10))


def test_an_unobserved_opening_prefix_is_unclassified_not_run_time():
    """
    No sample at or before shift_start. The first in-window report is EXECUTE at 07:00.
    [06:00, 07:00) is unknown, not producing, so Availability must not count it as Run Time.
    """
    late_execute = (StateSample(t(7), "EXECUTE"),)
    inputs = shift_inputs(unit(), WINDOW, samples(state=late_execute), (), {})
    opening = [stop for stop in inputs.classified_stops if stop.interval.start == t(6)]
    assert len(opening) == 1
    assert opening[0].interval == Interval(t(6), t(7))
    assert opening[0].state_value == UNOBSERVED_STATE
    assert opening[0].reason_code == UNCLASSIFIED_REASON_CODE


def test_a_shift_with_counters_but_no_state_is_unobserved_throughout():
    inputs = shift_inputs(unit(), WINDOW, samples(good=GOOD_CLIMB), (), {}, has_input_data=True)
    assert len(inputs.classified_stops) == 1
    assert inputs.classified_stops[0].interval == Interval(t(6), t(14))
    assert inputs.classified_stops[0].reason_code == UNCLASSIFIED_REASON_CODE
    assert inputs.has_input_data is True


def test_a_stop_is_classified_before_the_inputs_are_built():
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), {})
    stop = inputs.classified_stops[0]
    assert stop.reason_code == "MECH_FAILURE"
    assert stop.source == AUTO
    assert stop.is_planned is False


def test_a_planned_reason_marks_the_stop_planned():
    suspended = (StateSample(t(5, 58), "EXECUTE"), StateSample(t(9), "SUSPENDED"), StateSample(t(10), "EXECUTE"))
    inputs = shift_inputs(unit(), WINDOW, samples(state=suspended), (), {})
    assert inputs.classified_stops[0].reason_code == "TOOL_CHANGE"
    assert inputs.classified_stops[0].is_planned is True


def test_a_manual_reason_wins_over_the_rule():
    manual = {t(9): ManualReason(reason_code="TOOL_CHANGE", note="die swap", assigned_by="operator1")}
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), manual)
    stop = inputs.classified_stops[0]
    assert stop.reason_code == "TOOL_CHANGE"
    assert stop.source == MANUAL
    assert stop.assigned_by == "operator1"


def test_exception_windows_become_exception_intervals():
    windows = (
        ExceptionWindow(interval=Interval(t(6), t(7)), kind="PLANNED_DOWN", asset_path=LINE),
        ExceptionWindow(interval=Interval(t(7), t(8)), kind="NON_PRODUCING", asset_path=None),
    )
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), windows, {})
    # Merged, so two adjacent exceptions cannot subtract from Loading Time twice.
    assert inputs.exception_intervals == (Interval(t(6), t(8)),)


def test_no_input_rows_makes_the_shift_report_no_input_data():
    inputs = shift_inputs(unit(), WINDOW, samples(), (), {}, has_input_data=False)
    assert inputs.has_input_data is False


def test_unclassified_seconds_totals_only_the_unclassified_stops():
    unknown = (StateSample(t(5, 58), "EXECUTE"), StateSample(t(9), "HELD"), StateSample(t(10), "EXECUTE"))
    inputs = shift_inputs(unit(), WINDOW, samples(state=unknown), (), {})
    assert inputs.classified_stops[0].reason_code == UNCLASSIFIED_REASON_CODE
    assert unclassified_seconds(inputs.classified_stops) == 3600.0


def test_unclassified_seconds_is_zero_when_every_stop_has_a_reason():
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), {})
    assert unclassified_seconds(inputs.classified_stops) == 0.0


def test_no_manual_reasons_digests_to_a_stable_placeholder():
    assert manual_digest({}) == "-"


def test_a_reassigned_code_changes_the_digest():
    before = {t(9): ManualReason(reason_code="TOOL_CHANGE", assigned_by="operator1")}
    after = {t(9): ManualReason(reason_code="MECH_FAILURE", assigned_by="operator1")}
    assert manual_digest(before) != manual_digest(after)
    # The note and the author are not inputs to the arithmetic, so they are not in the digest.
    assert manual_digest(before) == manual_digest(
        {t(9): ManualReason(reason_code="TOOL_CHANGE", note="die swap", assigned_by="operator2")}
    )


def test_a_reason_moved_to_another_stop_changes_the_digest():
    here = {t(9): ManualReason(reason_code="TOOL_CHANGE")}
    there = {t(11): ManualReason(reason_code="TOOL_CHANGE")}
    assert manual_digest(here) != manual_digest(there)


# --- the IO half ---------------------------------------------------------------------------------


class FakeSource:
    def __init__(self, series: ShiftSamples, fingerprint: Fingerprint) -> None:
        self.series = series
        self._fingerprint = fingerprint

    async def fingerprint(self, refs, start, end) -> Fingerprint:
        return self._fingerprint

    async def text_samples(self, ref, start, end, *, include_prior=True):
        return list(self.series.product if ref.topic.endswith("RecipeId") else self.series.state)

    async def numeric_samples(self, ref, start, end, *, include_prior=True):
        return list(self.series.reject if ref.topic.endswith("RejectCount") else self.series.good)


class FakeMaster:
    def __init__(self, windows=()) -> None:
        self.windows = list(windows)

    async def exception_windows(self, unit, window):
        return list(self.windows)


class FakeStore:
    def __init__(self, stored: StoredResult | None = None) -> None:
        self.stored = stored
        self.manual: dict[datetime, ManualReason] = {}
        self.saves: list[int] = []
        self.marked: list[tuple[int, datetime]] = []

    async def existing(self, unit_id, shift_start):
        return self.stored

    async def manual_reasons(self, unit_id, window):
        return dict(self.manual)

    async def save(self, unit_id, window, metrics, stops, fingerprint, computed_at):
        revision = 1 if self.stored is None else self.stored.revision + 1
        self.saves.append(revision)
        return StoredResult(
            result_id=11,
            revision=revision,
            input_fingerprint=fingerprint.as_text(),
            published_at=None,
        )

    async def mark_published(self, result_id, published_at):
        self.marked.append((result_id, published_at))


class FakePublisher:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, int]] = []

    async def publish(self, asset_path, window, metrics, revision) -> bool:
        self.sent.append((asset_path, revision))
        return self.ok


FULL_SHIFT = ShiftSamples(
    state=RUN_WITH_ONE_STOP, good=GOOD_CLIMB, reject=REJECT_CLIMB, product=TWO_PRODUCTS
)
FINGERPRINT = Fingerprint(row_count=2880, max_time=t(14))


def pipeline(store: FakeStore, publisher: FakePublisher, fingerprint=FINGERPRINT) -> ShiftPipeline:
    return ShiftPipeline(
        source=FakeSource(FULL_SHIFT, fingerprint),
        master=FakeMaster(),
        store=store,
        publisher=publisher,
    )


@pytest.mark.asyncio
async def test_a_shift_with_no_stored_result_is_computed_at_revision_one():
    store, publisher = FakeStore(), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.revision == 1
    assert outcome.published is True
    assert outcome.input_rows == 2880
    assert outcome.metrics is not None
    assert outcome.metrics.status == "OK"
    assert store.saves == [1]
    assert store.marked == [(11, COMPUTED_AT)]
    assert publisher.sent == [(LINE, 1)]


@pytest.mark.asyncio
async def test_a_changed_fingerprint_is_a_revision():
    stored = StoredResult(result_id=11, revision=1, input_fingerprint="1440:-", published_at=t(14))
    store, publisher = FakeStore(stored), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_REVISED
    assert outcome.revision == 2
    assert outcome.late_data is True
    assert store.saves == [2]
    assert publisher.sent == [(LINE, 2)]


@pytest.mark.asyncio
async def test_an_unchanged_published_shift_does_no_work_at_all():
    stored = StoredResult(
        result_id=11, revision=1, input_fingerprint=FINGERPRINT.as_text(), published_at=t(14)
    )
    store, publisher = FakeStore(stored), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_UNCHANGED
    assert outcome.metrics is None
    assert store.saves == []
    assert publisher.sent == []


@pytest.mark.asyncio
async def test_an_unchanged_unpublished_shift_is_republished_at_the_same_revision():
    stored = StoredResult(
        result_id=11, revision=2, input_fingerprint=FINGERPRINT.as_text(), published_at=None
    )
    store, publisher = FakeStore(stored), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_REPUBLISHED
    assert outcome.revision == 2
    # Nothing written but the publication timestamp: a broker outage is not a correction.
    assert store.saves == []
    assert store.marked == [(11, COMPUTED_AT)]
    assert publisher.sent == [(LINE, 2)]


@pytest.mark.asyncio
async def test_a_reassigned_reason_is_a_revision_even_though_no_sample_moved():
    stored = StoredResult(
        result_id=11, revision=1, input_fingerprint=FINGERPRINT.as_text(), published_at=t(14)
    )
    store, publisher = FakeStore(stored), FakePublisher()
    store.manual = {t(9): ManualReason(reason_code="TOOL_CHANGE", assigned_by="operator1")}
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    # Spec section 13: Loading Time shrinks, Availability changes, revision bumps.
    assert outcome.action == ACTION_REVISED
    assert outcome.revision == 2
    # Not late data: no sample moved, so `uns_oee_late_data_detected_total` must not move.
    assert outcome.late_data is False
    assert store.saves == [2]


@pytest.mark.asyncio
async def test_a_failed_publish_leaves_the_result_unmarked_for_the_next_pass():
    store, publisher = FakeStore(), FakePublisher(ok=False)
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.published is False
    assert store.saves == [1]
    assert store.marked == []


@pytest.mark.asyncio
async def test_a_silent_unit_still_gets_a_row_with_no_input_data():
    store, publisher = FakeStore(), FakePublisher()
    empty = Fingerprint(row_count=0, max_time=None)
    outcome = await pipeline(store, publisher, empty).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.metrics is not None
    assert outcome.metrics.status == "NO_INPUT_DATA"
    assert store.saves == [1]


@pytest.mark.asyncio
async def test_the_outcome_reports_the_shifts_unclassified_downtime():
    store, publisher = FakeStore(), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)
    assert outcome.unclassified_seconds == 0.0
    assert outcome.counter_resets == 0
