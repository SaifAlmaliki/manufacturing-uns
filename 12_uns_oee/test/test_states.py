"""Tests for state segmentation and interval arithmetic.

Two rules are being pinned here. First: the state a machine is in when a shift begins is
whatever it was last reported to be, even if that report predates the shift - a machine
stopped at 05:40 is still stopped at 06:00, and a segmenter that starts at the first
in-shift sample would credit the stop to nobody. Second: durations come from a union, never
from a sum. Overlapping stops double-count under addition, and a double-counted stop can
push Run Time negative.
"""

from datetime import datetime, timedelta, timezone

from uns_oee.states import (
    Interval,
    StateSample,
    StateSegment,
    intersect,
    merge,
    state_segments,
    stop_intervals,
    subtract,
    union_duration_s,
)

PRODUCING = ("EXECUTE",)


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


SHIFT = Interval(t(6), t(14))


def test_the_state_before_the_shift_carries_into_it():
    segments = state_segments(
        [StateSample(t(5, 50), "HELD"), StateSample(t(7), "EXECUTE")], SHIFT
    )
    assert [(segment.state, segment.interval) for segment in segments] == [
        ("HELD", Interval(t(6), t(7))),
        ("EXECUTE", Interval(t(7), t(14))),
    ]


def test_a_sample_on_the_shift_start_is_the_opening_state_and_is_not_duplicated():
    segments = state_segments(
        [StateSample(t(6), "IDLE"), StateSample(t(10), "EXECUTE")], SHIFT
    )
    assert [segment.state for segment in segments] == ["IDLE", "EXECUTE"]
    assert segments[0].interval == Interval(t(6), t(10))


def test_a_sample_on_the_shift_end_belongs_to_the_next_shift():
    segments = state_segments(
        [StateSample(t(6), "EXECUTE"), StateSample(t(14), "HELD")], SHIFT
    )
    assert segments == [StateSegment(state="EXECUTE", interval=Interval(t(6), t(14)))]


def test_repeated_identical_states_become_one_segment():
    segments = state_segments(
        [
            StateSample(t(5, 50), "EXECUTE"),
            StateSample(t(8), "EXECUTE"),
            StateSample(t(11), "EXECUTE"),
        ],
        SHIFT,
    )
    assert len(segments) == 1
    assert segments[0].interval == SHIFT


def test_with_no_prior_sample_the_first_segment_starts_where_the_data_does():
    segments = state_segments([StateSample(t(7), "HELD")], SHIFT)
    assert segments[0].interval == Interval(t(7), t(14))


def test_no_samples_in_or_before_the_window_yields_nothing():
    assert state_segments([StateSample(t(15), "EXECUTE")], SHIFT) == []
    assert state_segments([], SHIFT) == []


def test_stops_are_every_segment_not_in_a_producing_state():
    segments = state_segments(
        [
            StateSample(t(6), "EXECUTE"),
            StateSample(t(9), "HELD"),
            StateSample(t(9, 30), "EXECUTE"),
            StateSample(t(12), "SUSPENDED"),
        ],
        SHIFT,
    )
    stops = stop_intervals(segments, PRODUCING)
    assert [(stop.state, stop.interval.duration_s) for stop in stops] == [
        ("HELD", 1800.0),
        ("SUSPENDED", 7200.0),
    ]
    assert union_duration_s([stop.interval for stop in stops]) == 9000.0


def test_two_producing_states_can_be_declared():
    segments = state_segments(
        [StateSample(t(6), "EXECUTE"), StateSample(t(10), "COMPLETING")], SHIFT
    )
    assert stop_intervals(segments, ("EXECUTE", "COMPLETING")) == []


def test_merge_coalesces_overlapping_and_touching_intervals():
    assert merge(
        [Interval(t(6), t(8)), Interval(t(7), t(9)), Interval(t(9), t(10)), Interval(t(12), t(13))]
    ) == [Interval(t(6), t(10)), Interval(t(12), t(13))]


def test_union_never_double_counts():
    overlapping = [Interval(t(6), t(9)), Interval(t(7), t(10))]
    assert sum(interval.duration_s for interval in overlapping) == 6 * 3600
    assert union_duration_s(overlapping) == 4 * 3600


def test_intersect_keeps_only_common_time():
    assert intersect([Interval(t(6), t(10))], [Interval(t(8), t(12))]) == [Interval(t(8), t(10))]
    assert intersect([Interval(t(6), t(7))], [Interval(t(8), t(9))]) == []


def test_subtract_can_split_an_interval_in_two():
    assert subtract([Interval(t(6), t(14))], [Interval(t(9), t(10))]) == [
        Interval(t(6), t(9)),
        Interval(t(10), t(14)),
    ]


def test_subtract_removes_a_fully_covered_interval():
    assert subtract([Interval(t(9), t(10))], [Interval(t(6), t(14))]) == []


def test_subtract_with_nothing_to_remove_returns_the_merged_input():
    assert subtract([Interval(t(6), t(8)), Interval(t(7), t(9))], []) == [Interval(t(6), t(9))]


def test_a_zero_length_interval_has_no_duration_and_survives_no_operation():
    assert Interval(t(6), t(6)).duration_s == 0.0
    assert merge([Interval(t(6), t(6))]) == []


def test_an_inverted_interval_reads_as_empty_rather_than_negative():
    # Defensive: a caller that mixed up its bounds must not create negative Run Time.
    assert Interval(t(10), t(6)).duration_s == 0.0


def test_clipped_to_is_none_when_there_is_no_overlap():
    assert Interval(t(6), t(7)).clipped_to(Interval(t(8), t(9))) is None
    assert Interval(t(6), t(9)).clipped_to(SHIFT) == Interval(t(6), t(9))


def test_intervals_sort_by_start_then_end():
    unsorted = [Interval(t(8), t(9)), Interval(t(6), t(12)), Interval(t(6), t(7))]
    assert sorted(unsorted) == [Interval(t(6), t(7)), Interval(t(6), t(12)), Interval(t(8), t(9))]


def test_a_stop_that_spans_the_whole_shift_is_the_whole_shift():
    segments = state_segments([StateSample(t(4), "ABORTED")], SHIFT)
    stops = stop_intervals(segments, PRODUCING)
    assert union_duration_s([stop.interval for stop in stops]) == timedelta(hours=8).total_seconds()
