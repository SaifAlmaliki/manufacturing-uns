"""Computing one shift for one unit, in the order spec section 5 fixes.

    shift_calendar -> sources -> counters + states -> classifier -> oee_calc -> store -> publisher

`classifier` runs before `oee_calc` because a reason's `is_planned` flag decides whether its
stop leaves Loading Time, so classification is an arithmetic input and not a presentation
detail.

Everything up to `store` is a pure function in this module: `product_segments` and
`shift_inputs` take sample lists and return dataclasses. Only `ShiftPipeline.run_shift`
performs IO, and it reads no clock - `computed_at` is passed in by the scheduler, which is
what lets a whole shift be recomputed deterministically from the same rows.
"""

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from uns_model.oee_tables import UNCLASSIFIED_REASON_CODE
from uns_oee.classifier import ClassifiedStop, ManualReason, classify
from uns_oee.counters import Sample, counter_delta, counter_delta_in
from uns_oee.master_data import ExceptionWindow, MasterDataLoader, UnitMasterData, exception_intervals
from uns_oee.oee_calc import ProductSegment, ShiftInputs, ShiftMetrics, compute
from uns_oee.publisher import ResultPublisher
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import Fingerprint, MetricSource
from uns_oee.states import Interval, StateSample, merge, state_segments, stop_intervals, union_duration_s
from uns_oee.store import ResultStore

LOGGER = logging.getLogger(__name__)

#: A shift computed for the first time. `revision` is 1.
ACTION_COMPUTED = "COMPUTED"

#: A shift recomputed because its input fingerprint moved. `revision` was bumped.
ACTION_REVISED = "REVISED"

#: The stored numbers were already right; only the MQTT message was missing.
ACTION_REPUBLISHED = "REPUBLISHED"

#: Same inputs, already published. Nothing was read past the fingerprint.
ACTION_UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class ShiftSamples:
    """Every series one shift needs, already fetched.

    Separated from the fetching so the arithmetic can be tested against a hand-written series.
    An empty tuple is a legitimate value: a unit with no reject binding has no reject samples,
    and a counter delta over nothing is zero rather than an error.
    """

    state: tuple[StateSample, ...] = ()
    good: tuple[Sample, ...] = ()
    reject: tuple[Sample, ...] = ()
    product: tuple[StateSample, ...] = ()

    @property
    def counter_resets(self) -> int:
        """Resets seen across both counters. Reported, never silently absorbed."""
        return counter_delta(self.good).resets + counter_delta(self.reject).resets


@dataclass(frozen=True, slots=True)
class ShiftOutcome:
    """What `run_shift` did, in the terms the scheduler and the metrics need."""

    unit_id: int
    asset_path: str
    window: ShiftWindow
    action: str
    metrics: ShiftMetrics | None
    revision: int
    published: bool
    input_rows: int = 0
    counter_resets: int = 0
    unclassified_seconds: float = 0.0

    #: Whether the historian's half of the fingerprint moved, as opposed to an operator having
    #: reassigned a reason. Both cause a revision; only this one is late-arriving data.
    late_data: bool = False

    #: Wall time this shift took, stamped by the scheduler from `time.monotonic()`. Left at
    #: zero here: the pipeline reads no clock, and this number is never stored - it exists
    #: only to fill `uns_oee_shift_compute_seconds`.
    compute_seconds: float = 0.0


def as_interval(window: ShiftWindow) -> Interval:
    """The shift window as the half-open interval the arithmetic works in."""
    return Interval(window.start, window.end)


def product_segments(
    unit: UnitMasterData, window: ShiftWindow, samples: ShiftSamples
) -> tuple[ProductSegment, ...]:
    """The shift split by what was running, with each part's counts.

    A product code series is a state series - contiguous runs of one string - so this reuses
    `state_segments` rather than reimplementing coalescing. With no product binding, or no
    product samples to segment by, the whole shift is one unnamed segment; the calculator
    handles that identically, and the counts then equal the whole-window delta.
    """
    whole = as_interval(window)
    if unit.product_ref is None or not samples.product:
        return (_segment(unit, None, (whole,), samples),)

    grouped: dict[str, list[Interval]] = {}
    for segment in state_segments(samples.product, whole):
        grouped.setdefault(segment.state, []).append(segment.interval)
    return tuple(
        _segment(unit, code, tuple(merge(intervals)), samples)
        for code, intervals in grouped.items()
    )


def _segment(
    unit: UnitMasterData,
    product_code: str | None,
    intervals: tuple[Interval, ...],
    samples: ShiftSamples,
) -> ProductSegment:
    """One product's counts, taken per interval rather than pro-rated.

    `counter_delta_in` includes the sample sitting exactly on the interval's end, so the
    increment across a changeover is credited to the outgoing product and the incoming one
    starts from the changeover value. The per-product totals therefore sum to the shift's.
    """
    return ProductSegment(
        product_code=product_code,
        intervals=intervals,
        ideal_cycle_time_s=unit.ideal_cycle_time_for(product_code),
        good_count=sum(counter_delta_in(samples.good, i.start, i.end).total for i in intervals),
        reject_count=sum(counter_delta_in(samples.reject, i.start, i.end).total for i in intervals),
    )


def shift_inputs(
    unit: UnitMasterData,
    window: ShiftWindow,
    samples: ShiftSamples,
    exceptions: Sequence[ExceptionWindow],
    manual: Mapping[datetime, ManualReason],
    *,
    has_input_data: bool = True,
) -> ShiftInputs:
    """Everything the calculator needs, assembled from one shift's rows.

    All three shift-exception kinds subtract from Loading Time (`SHIFT_EXCEPTION_KINDS` is
    PLANNED_DOWN, NON_PRODUCING, HOLIDAY, kept distinct only so a report can name which), so
    no filtering by kind happens here.
    """
    whole = as_interval(window)
    segments = state_segments(samples.state, whole)
    stops = stop_intervals(segments, unit.producing_states)
    return ShiftInputs(
        window=whole,
        exception_intervals=tuple(exception_intervals(exceptions)),
        classified_stops=tuple(classify(stops, unit.resolver, manual=manual)),
        products=product_segments(unit, window, samples),
        has_input_data=has_input_data,
    )


def unclassified_seconds(stops: Sequence[ClassifiedStop]) -> float:
    """Downtime with no reason rule behind it - the master data quality signal.

    Totalled by union, like every other duration in this module, so two stops that somehow
    overlap cannot inflate the number an engineer is being asked to act on.
    """
    return union_duration_s(
        [stop.interval for stop in stops if stop.reason_code == UNCLASSIFIED_REASON_CODE]
    )


def manual_digest(manual: Mapping[datetime, ManualReason]) -> str:
    """A short, stable summary of the operator's attributions for one shift.

    Hashed rather than stored verbatim so `input_fingerprint` stays a short key on a shift
    with fifty reassigned stops. Both the stop instants and the codes go in, sorted, because
    a reason moved from one stop to another is as much a change as a code edited in place.
    """
    if not manual:
        return "-"
    joined = "|".join(
        f"{at.isoformat()}={reason.reason_code}" for at, reason in sorted(manual.items())
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


class ShiftPipeline:
    """One shift for one unit: fetch, compute, store, publish."""

    def __init__(
        self,
        source: MetricSource,
        master: MasterDataLoader,
        store: ResultStore,
        publisher: ResultPublisher,
    ) -> None:
        self._source = source
        self._master = master
        self._store = store
        self._publisher = publisher

    async def run_shift(
        self, unit: UnitMasterData, window: ShiftWindow, computed_at: datetime
    ) -> ShiftOutcome:
        """Compute and publish one closed shift, doing as little as the inputs allow.

        The fingerprint is checked first because it is three indexed reads, which is what makes
        re-checking every open shift on every pass affordable while a full recompute is not.
        Four outcomes follow from it and from whether the stored row reached MQTT.

        The manual reasons are read before the decision, not after it. A reassignment changes
        no sample, so a fingerprint made only of historian rows would call the shift unchanged
        and never write the corrected Availability - which is exactly the case spec section 13
        says must bump the revision.
        """
        counted = await self._source.fingerprint(unit.refs, window.start, window.end)
        manual = await self._store.manual_reasons(unit.unit_id, window)
        fingerprint = counted.with_manual(manual_digest(manual))
        stored = await self._store.existing(unit.unit_id, window.start)
        unchanged = stored is not None and stored.input_fingerprint == fingerprint.as_text()

        if unchanged and stored.published_at is not None:
            return ShiftOutcome(
                unit_id=unit.unit_id,
                asset_path=unit.asset_path,
                window=window,
                action=ACTION_UNCHANGED,
                metrics=None,
                revision=stored.revision,
                published=True,
                input_rows=fingerprint.row_count,
            )

        samples = await self._fetch(unit, window)
        exceptions = await self._master.exception_windows(unit, as_interval(window))
        inputs = shift_inputs(
            unit,
            window,
            samples,
            exceptions,
            manual,
            has_input_data=not fingerprint.is_empty,
        )
        metrics = compute(inputs)

        if unchanged:
            # Rule 1: same inputs, same output. So the numbers on record are these numbers,
            # and publishing them under the stored revision is exact. Writing a new revision
            # here would make `revision` count broker outages instead of corrections.
            action = ACTION_REPUBLISHED
            result_id, revision = stored.result_id, stored.revision
        else:
            saved = await self._store.save(
                unit.unit_id,
                window,
                metrics,
                inputs.classified_stops,
                fingerprint,
                computed_at,
            )
            result_id, revision = saved.result_id, saved.revision
            action = ACTION_COMPUTED if revision == 1 else ACTION_REVISED

        # A revision has two causes and the operator needs to tell them apart. Comparing only
        # the historian half isolates late-arriving data from a reason reassignment.
        late_data = stored is not None and Fingerprint.source_part(
            stored.input_fingerprint
        ) != Fingerprint.source_part(fingerprint.as_text())

        published = await self._publisher.publish(unit.asset_path, window, metrics, revision)
        if published:
            await self._store.mark_published(result_id, computed_at)

        LOGGER.info(
            "OEE %s %s shift %s: %s revision %d, status %s",
            unit.asset_path,
            window.label,
            window.start.isoformat(),
            action,
            revision,
            metrics.status,
        )
        return ShiftOutcome(
            unit_id=unit.unit_id,
            asset_path=unit.asset_path,
            window=window,
            action=action,
            metrics=metrics,
            revision=revision,
            published=published,
            input_rows=fingerprint.row_count,
            counter_resets=samples.counter_resets,
            unclassified_seconds=unclassified_seconds(inputs.classified_stops),
            late_data=late_data,
        )

    async def _fetch(self, unit: UnitMasterData, window: ShiftWindow) -> ShiftSamples:
        """Every series this unit binds, for this window.

        `include_prior` is left at its default for all four: the state at the boundary decides
        whether the shift opens in a stop, and a counter's pre-boundary value is what makes the
        first in-shift delta correct rather than a jump from zero.
        """
        state = await self._source.text_samples(unit.state_ref, window.start, window.end)
        good = await self._source.numeric_samples(unit.good_ref, window.start, window.end)
        reject = (
            await self._source.numeric_samples(unit.reject_ref, window.start, window.end)
            if unit.reject_ref is not None
            else []
        )
        product = (
            await self._source.text_samples(unit.product_ref, window.start, window.end)
            if unit.product_ref is not None
            else []
        )
        return ShiftSamples(
            state=tuple(state), good=tuple(good), reject=tuple(reject), product=tuple(product)
        )


__all__ = [
    "ACTION_COMPUTED",
    "ACTION_REPUBLISHED",
    "ACTION_REVISED",
    "ACTION_UNCHANGED",
    "ShiftOutcome",
    "ShiftPipeline",
    "ShiftSamples",
    "as_interval",
    "manual_digest",
    "product_segments",
    "shift_inputs",
    "unclassified_seconds",
]
