"""Machine-state segments and the interval algebra the OEE numbers are built from.

Loading Time is a shift window with planned-down periods subtracted. Run Time is Loading
Time with stops subtracted. A product's share of Run Time is Run Time intersected with the
periods that product was running. All three are the same three operations - merge, subtract,
intersect - so they live here once, and every duration comes out of `union_duration_s`.

Never sum durations. Two stops that overlap sum to more than the time that elapsed, and a
Run Time computed by subtracting a sum can go negative, which surfaces as an OEE above one
or below zero and is not traceable back to the arithmetic that caused it.

Intervals are half-open: `[start, end)`. A sample landing exactly on a shift end therefore
opens the next shift rather than closing this one, and no instant is counted twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, order=True)
class Interval:
    """A half-open UTC interval. Inverted or empty bounds read as zero, never negative."""

    start: datetime
    end: datetime

    @property
    def duration_s(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)

    @property
    def is_empty(self) -> bool:
        return self.end <= self.start

    def clipped_to(self, other: Interval) -> Interval | None:
        """The overlap with `other`, or `None` when they do not overlap."""
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return None if end <= start else Interval(start, end)


@dataclass(frozen=True, slots=True, order=True)
class StateSample:
    """One machine-state report. `state` is the raw published value, e.g. `"EXECUTE"`."""

    at: datetime
    state: str


@dataclass(frozen=True, slots=True)
class StateSegment:
    """A period the machine spent continuously in one state, clipped to the shift."""

    state: str
    interval: Interval


@dataclass(frozen=True, slots=True)
class StopInterval:
    """A segment in a non-producing state - a candidate for a downtime reason code."""

    state: str
    interval: Interval


def state_segments(samples: Sequence[StateSample], window: Interval) -> list[StateSegment]:
    """Segment `window` by machine state.

    The last sample at or before `window.start` sets the opening state, because state is a
    level and not an event: a machine that went down at 05:40 and published nothing since is
    still down at 06:00. With no such sample the first segment starts where the data starts -
    the state before the first report is unknown and is not guessed.

    Consecutive samples reporting the same state are coalesced, so a status tier republishing
    `EXECUTE` every thirty seconds produces one segment and not nine hundred and sixty.
    """
    ordered = sorted(samples)
    prior = [sample for sample in ordered if sample.at <= window.start]
    points = [StateSample(at=window.start, state=prior[-1].state)] if prior else []
    points.extend(sample for sample in ordered if window.start < sample.at < window.end)

    segments: list[StateSegment] = []
    for index, point in enumerate(points):
        end = points[index + 1].at if index + 1 < len(points) else window.end
        if end <= point.at:
            continue
        if segments and segments[-1].state == point.state:
            merged = Interval(segments[-1].interval.start, end)
            segments[-1] = StateSegment(state=point.state, interval=merged)
            continue
        segments.append(StateSegment(state=point.state, interval=Interval(point.at, end)))
    return segments


def stop_intervals(
    segments: Sequence[StateSegment], producing_states: Sequence[str]
) -> list[StopInterval]:
    """Every segment whose state is not one the unit declares as producing.

    Kept as separate stops rather than a merged blanket, because each one gets its own reason
    code: a thirty-minute changeover and a two-hour breakdown are one number in Availability
    and two very different lines in the Pareto.
    """
    producing = set(producing_states)
    return [
        StopInterval(state=segment.state, interval=segment.interval)
        for segment in segments
        if segment.state not in producing
    ]


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    """The input as a minimal set of non-overlapping intervals, earliest first.

    Touching intervals are joined: `[06:00, 08:00)` and `[08:00, 09:00)` describe two hours
    of continuous time and splitting them would only invite a later off-by-one.
    """
    ordered = sorted(interval for interval in intervals if not interval.is_empty)
    merged: list[Interval] = []
    for interval in ordered:
        if merged and interval.start <= merged[-1].end:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return merged


def union_duration_s(intervals: Iterable[Interval]) -> float:
    """Seconds covered by at least one interval. The only sanctioned way to total time."""
    return sum(interval.duration_s for interval in merge(intervals))


def intersect(left: Iterable[Interval], right: Iterable[Interval]) -> list[Interval]:
    """Time covered by both sides."""
    overlaps = [
        clipped
        for one in merge(left)
        for other in merge(right)
        if (clipped := one.clipped_to(other)) is not None
    ]
    return merge(overlaps)


def subtract(left: Iterable[Interval], right: Iterable[Interval]) -> list[Interval]:
    """Time covered by `left` and not by `right`."""
    remaining = merge(left)
    for cut in merge(right):
        next_remaining: list[Interval] = []
        for interval in remaining:
            if cut.end <= interval.start or cut.start >= interval.end:
                next_remaining.append(interval)
                continue
            if interval.start < cut.start:
                next_remaining.append(Interval(interval.start, cut.start))
            if cut.end < interval.end:
                next_remaining.append(Interval(cut.end, interval.end))
        remaining = next_remaining
    return remaining


__all__ = [
    "Interval",
    "StateSample",
    "StateSegment",
    "StopInterval",
    "intersect",
    "merge",
    "state_segments",
    "stop_intervals",
    "subtract",
    "union_duration_s",
]
