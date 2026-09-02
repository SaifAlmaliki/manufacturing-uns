"""Turning odometer readings into production counts.

A PLC production counter climbs and then, on a power cycle or a tag wrap, restarts. So the
count a shift produced is the sum of the positive steps between consecutive readings, not
last minus first - and a step that goes backwards is read as a restart whose new value is
itself production since the restart.

Pure and stateless: same samples in, same numbers out, on any run. That is Rule 1, and it
is what makes a recomputation of last Tuesday agree with what was stored last Tuesday.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, order=True)
class Sample:
    """One counter reading. `at` is UTC-aware; `value` is the raw tag value."""

    at: datetime
    value: float


@dataclass(frozen=True, slots=True)
class CounterDelta:
    """How much a counter advanced, and how much of that was inferred across a restart.

    `resets` is carried so a suspicious shift is identifiable: one reset in a shift is a
    power cycle, twelve is a misconfigured binding pointed at a value that is not a counter.
    """

    total: float = 0.0
    resets: int = 0
    samples: int = 0


def counter_delta(samples: Sequence[Sample]) -> CounterDelta:
    """The production represented by `samples`, restart-safe.

    Sorted first, because the historian is queried by time but a caller may have merged two
    result sets, and one out-of-order pair would read as a reset and inflate the total.
    """
    ordered = sorted(samples)
    total = 0.0
    resets = 0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        step = current.value - previous.value
        if step >= 0:
            total += step
        else:
            # The counter restarted somewhere in between. Everything it has climbed to
            # since is production; what it lost between `previous` and the restart is not
            # recoverable from the samples and is not invented here.
            resets += 1
            total += max(current.value, 0.0)
    return CounterDelta(total=total, resets=resets, samples=len(ordered))


def counter_delta_in(samples: Sequence[Sample], start: datetime, end: datetime) -> CounterDelta:
    """The production between `start` and `end`, both bounds inclusive.

    When no sample lands on `start` exactly, the last sample before it is pulled in as the
    baseline so the climb up to the first in-shift reading is not lost. That attributes up
    to one sample interval of pre-shift production to the shift; the alternative - starting
    at the first sample inside the window - loses an unbounded amount, because a counter on
    the fifteen-minute meter tier may have no in-shift sample until minute fourteen. A
    sample sitting exactly on the boundary already is the baseline, so nothing is pulled in.
    """
    ordered = sorted(samples)
    inside = [sample for sample in ordered if start <= sample.at <= end]
    prior = [sample for sample in ordered if sample.at < start]
    if inside and prior and inside[0].at > start:
        inside.insert(0, prior[-1])
    return counter_delta(inside)


__all__ = ["CounterDelta", "Sample", "counter_delta", "counter_delta_in"]
