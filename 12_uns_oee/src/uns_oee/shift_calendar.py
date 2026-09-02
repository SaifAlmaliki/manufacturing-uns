"""Which UTC windows a shift pattern produces.

Pure: a schedule and a UTC range in, a list of windows out. No clock read, no database, no
configuration - which is what makes every DST case reachable from a unit test.

A shift is authored as (weekday, local wall-clock start, duration in minutes) because that
is how a plant describes it. The duration is wall-clock, not elapsed: an eight-hour night
shift is eight hours on the operator's clock, so on the spring-forward night it occupies
seven real hours and on the fall-back night nine. Loading Time has to agree with the clock
on the wall, because that is the clock the shift was staffed against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: Widened by a day at each end when walking local dates, so a shift that starts the day
#: before `from_utc` in local time - or the day after `to_utc` - is still considered.
_EDGE_DAYS = 1


@dataclass(frozen=True, slots=True)
class ShiftSlot:
    """One shift on one weekday. `day_of_week` is 0 = Monday, as `date.weekday()`."""

    day_of_week: int
    start_time: time
    duration_minutes: int
    label: str = ""


@dataclass(frozen=True, slots=True)
class ShiftSchedule:
    """A named weekly pattern in one IANA timezone.

    Distinct from `uns_model.oee_master_data.ShiftPatternSpec`, which is the authoring
    shape. This is the calculation shape: it carries a resolved zone and nothing else.
    """

    name: str
    timezone: str
    slots: tuple[ShiftSlot, ...] = ()

    @property
    def zone(self) -> ZoneInfo:
        """The pattern's zone.

        Raises `ValueError` naming the zone, because `ZoneInfoNotFoundError` alone does not
        say which pattern is misconfigured - and on a host with no IANA database (Windows
        without `tzdata`) every zone fails, which is worth stating plainly.
        """
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                f"shift pattern {self.name!r} names timezone {self.timezone!r}, which this host "
                f"cannot resolve. Install the `tzdata` package or correct the zone name."
            ) from error


@dataclass(frozen=True, slots=True, order=True)
class ShiftWindow:
    """One closed-ended UTC interval a shift occupies. `end` is exclusive."""

    start: datetime
    end: datetime
    label: str = ""

    @property
    def duration_s(self) -> float:
        """Real elapsed seconds, which is not the nominal length across a DST change."""
        return (self.end - self.start).total_seconds()

    def is_closed_at(self, at: datetime, settle_minutes: int) -> bool:
        """True once enough time has passed after `end` for in-flight data to have landed.

        Computing at `end` exactly would read a window the historian has not finished
        receiving, and produce a first revision that is wrong for a knowable reason.
        """
        return at >= self.end + timedelta(minutes=settle_minutes)


def resolve_local(zone: ZoneInfo, day: date, at: time) -> datetime:
    """The instant a local wall-clock time names, as an aware datetime.

    `fold=0` throughout, which is one rule covering both awkward cases: for a local time
    that happens twice it takes the earlier instant, and for one that never happens it
    applies the offset in force before the transition, landing on a real instant. Either
    way it never raises, and two runs over the same shift agree - which Rule 1 requires.

    The result is converted to UTC. PEP 495 makes inter-zone equality False whenever
    `utcoffset` depends on `fold`, which is exactly the DST-boundary cases this function
    exists to settle; callers (and the tests) compare instants, not wall times.
    """
    return datetime.combine(day, at).replace(tzinfo=zone, fold=0).astimezone(timezone.utc)


def shift_windows(schedule: ShiftSchedule, from_utc: datetime, to_utc: datetime) -> list[ShiftWindow]:
    """Every window of `schedule` whose start lies in `[from_utc, to_utc)`, earliest first.

    Bounded by start, not by overlap: a shift belongs to the instant it began, so a caller
    asking for a day gets that day's shifts and not the tail of the previous night's.
    """
    if to_utc <= from_utc:
        return []
    zone = schedule.zone
    windows: list[ShiftWindow] = []
    first_day = (from_utc.astimezone(zone) - timedelta(days=_EDGE_DAYS)).date()
    last_day = (to_utc.astimezone(zone) + timedelta(days=_EDGE_DAYS)).date()

    for slot in schedule.slots:
        day = first_day
        while day <= last_day:
            if day.weekday() == slot.day_of_week:
                windows.append(_window(zone, day, slot))
            day += timedelta(days=1)

    return sorted(
        window for window in windows if from_utc <= window.start < to_utc
    )


def _window(zone: ZoneInfo, day: date, slot: ShiftSlot) -> ShiftWindow:
    """One window, with both ends resolved as local wall-clock times.

    The end is the local start plus the duration, re-resolved through the zone - not the
    start instant plus the duration. Adding to the instant would keep the shift eight real
    hours long and slide its wall-clock end by an hour across a DST change, which is the
    opposite of what the roster says.
    """
    naive_start = datetime.combine(day, slot.start_time)
    naive_end = naive_start + timedelta(minutes=slot.duration_minutes)
    start = resolve_local(zone, naive_start.date(), naive_start.time())
    end = resolve_local(zone, naive_end.date(), naive_end.time())
    return ShiftWindow(
        start=start.astimezone(timezone.utc),
        end=end.astimezone(timezone.utc),
        label=slot.label,
    )


__all__ = ["ShiftSchedule", "ShiftSlot", "ShiftWindow", "resolve_local", "shift_windows"]
