"""Tests for monotonic counter differencing.

A PLC production counter is not a measurement, it is an odometer. It only ever climbs, and
then one day the operator power-cycles the panel or the tag wraps at 32767 and it starts
again from zero. Differencing naively gives a large negative number, which silently drags a
shift's Good Count below zero and makes Quality nonsense. Every case below is one of those
days.
"""

from datetime import datetime, timedelta, timezone

from uns_oee.counters import Sample, counter_delta, counter_delta_in

T0 = datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def samples(*pairs: tuple[float, float]) -> list[Sample]:
    return [Sample(at=at(minutes), value=value) for minutes, value in pairs]


def test_a_rising_counter_is_last_minus_first():
    delta = counter_delta(samples((0, 100.0), (5, 140.0), (10, 175.0)))
    assert delta.total == 75.0
    assert delta.resets == 0
    assert delta.samples == 3


def test_a_reset_contributes_the_value_after_the_reset():
    # 100 -> 140, then a restart that has already climbed back to 12 by the time we see it.
    delta = counter_delta(samples((0, 100.0), (5, 140.0), (10, 12.0), (15, 30.0)))
    assert delta.total == 40.0 + 12.0 + 18.0
    assert delta.resets == 1


def test_two_resets_are_both_counted():
    delta = counter_delta(samples((0, 50.0), (5, 5.0), (10, 3.0)))
    assert delta.resets == 2
    assert delta.total == 5.0 + 3.0


def test_a_flat_counter_produces_zero_not_none():
    delta = counter_delta(samples((0, 88.0), (5, 88.0)))
    assert delta.total == 0.0
    assert delta.resets == 0


def test_one_sample_cannot_produce_a_delta():
    delta = counter_delta(samples((0, 88.0)))
    assert delta.total == 0.0
    assert delta.samples == 1


def test_no_samples_is_zero_and_not_an_error():
    delta = counter_delta([])
    assert delta.total == 0.0
    assert delta.samples == 0


def test_samples_are_sorted_before_differencing():
    delta = counter_delta(samples((10, 175.0), (0, 100.0), (5, 140.0)))
    assert delta.total == 75.0
    assert delta.resets == 0


def test_a_window_anchors_on_the_sample_at_or_before_the_start():
    # The shift starts at minute 5. The counter read 140 at minute 5 exactly and 200 at the
    # end, so the shift made 60 - the pre-shift climb from 100 must not be included.
    window = counter_delta_in(samples((0, 100.0), (5, 140.0), (30, 200.0)), at(5), at(30))
    assert window.total == 60.0


def test_a_window_uses_the_last_prior_sample_when_none_lands_on_the_boundary():
    # Nothing arrived exactly at minute 10, so minute 8's reading is the baseline. This
    # attributes the two minutes before the shift to the shift, bounded by one sample
    # interval - the alternative loses everything made before the first in-shift sample,
    # which is a larger and less predictable error.
    window = counter_delta_in(samples((8, 140.0), (12, 150.0), (30, 200.0)), at(10), at(30))
    assert window.total == 60.0


def test_a_window_with_no_prior_sample_starts_at_the_first_sample_inside_it():
    window = counter_delta_in(samples((12, 150.0), (30, 200.0)), at(10), at(30))
    assert window.total == 50.0


def test_a_window_excludes_samples_after_its_end():
    window = counter_delta_in(samples((0, 100.0), (30, 200.0), (40, 260.0)), at(0), at(30))
    assert window.total == 100.0


def test_a_window_end_is_inclusive_so_the_closing_sample_counts():
    window = counter_delta_in(samples((0, 100.0), (30, 200.0)), at(0), at(30))
    assert window.total == 100.0


def test_an_empty_window_is_zero():
    window = counter_delta_in(samples((0, 100.0), (30, 200.0)), at(50), at(60))
    assert window.total == 0.0
    assert window.samples == 0
