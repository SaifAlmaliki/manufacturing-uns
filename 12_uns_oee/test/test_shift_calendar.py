"""Tests for shift-window generation.

The DST cases are the point of this module. A shift is authored as a local wall-clock start
plus a duration in minutes, and the operator's 22:00-to-06:00 shift really is seven hours
long on the spring-forward night and nine on the autumn one. Getting this wrong moves
Loading Time by an hour twice a year, in opposite directions, which is exactly the kind of
error that shows up as an unexplained OEE step and never as a bug report.
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot, resolve_local, shift_windows

BERLIN = ZoneInfo("Europe/Berlin")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


NIGHTS = ShiftSchedule(
    name="every night",
    timezone="Europe/Berlin",
    slots=tuple(ShiftSlot(day, time(22, 0), 480, "C") for day in range(7)),
)

WEEKDAY_MORNINGS = ShiftSchedule(
    name="weekday mornings",
    timezone="Europe/Berlin",
    slots=tuple(ShiftSlot(day, time(6, 0), 480, "A") for day in range(5)),
)


def test_a_plain_shift_is_its_nominal_length():
    windows = shift_windows(WEEKDAY_MORNINGS, utc(2026, 9, 7), utc(2026, 9, 8))
    assert len(windows) == 1
    assert windows[0].start == utc(2026, 9, 7, 4, 0)
    assert windows[0].end == utc(2026, 9, 7, 12, 0)
    assert windows[0].duration_s == 8 * 3600
    assert windows[0].label == "A"


def test_the_spring_forward_night_shift_is_seven_hours():
    windows = shift_windows(NIGHTS, utc(2026, 3, 28, 12), utc(2026, 3, 29, 12))
    starts = [window.start for window in windows]
    assert utc(2026, 3, 28, 21, 0) in starts
    window = next(w for w in windows if w.start == utc(2026, 3, 28, 21, 0))
    assert window.end == utc(2026, 3, 29, 4, 0)
    assert window.duration_s == 7 * 3600


def test_the_fall_back_night_shift_is_nine_hours():
    windows = shift_windows(NIGHTS, utc(2026, 10, 24, 12), utc(2026, 10, 25, 12))
    window = next(w for w in windows if w.start == utc(2026, 10, 24, 20, 0))
    assert window.end == utc(2026, 10, 25, 5, 0)
    assert window.duration_s == 9 * 3600


@pytest.mark.parametrize(
    ("day", "at", "expected"),
    [
        # Ambiguous: 02:30 happens twice on the fall-back night. fold=0 takes the first.
        (date(2026, 10, 25), time(2, 30), utc(2026, 10, 25, 0, 30)),
        # Non-existent: 02:30 is skipped on the spring-forward night. fold=0 interprets it
        # with the offset in force before the transition, landing on a real later instant.
        (date(2026, 3, 29), time(2, 30), utc(2026, 3, 29, 1, 30)),
    ],
)
def test_resolve_local_never_raises_on_a_dst_boundary(day, at, expected):
    assert resolve_local(BERLIN, day, at) == expected


def test_windows_are_sorted_and_bounded_by_start():
    windows = shift_windows(WEEKDAY_MORNINGS, utc(2026, 9, 7), utc(2026, 9, 12))
    assert windows == sorted(windows, key=lambda window: window.start)
    assert len(windows) == 5
    assert all(utc(2026, 9, 7) <= window.start < utc(2026, 9, 12) for window in windows)


def test_a_shift_is_closed_only_after_the_settle_window():
    window = shift_windows(WEEKDAY_MORNINGS, utc(2026, 9, 7), utc(2026, 9, 8))[0]
    assert not window.is_closed_at(utc(2026, 9, 7, 12, 10), settle_minutes=15)
    assert window.is_closed_at(utc(2026, 9, 7, 12, 15), settle_minutes=15)


def test_an_unknown_timezone_is_named_in_the_error():
    schedule = ShiftSchedule(name="broken", timezone="Mars/Olympus", slots=NIGHTS.slots)
    with pytest.raises(ValueError, match="Mars/Olympus"):
        shift_windows(schedule, utc(2026, 9, 7), utc(2026, 9, 8))
