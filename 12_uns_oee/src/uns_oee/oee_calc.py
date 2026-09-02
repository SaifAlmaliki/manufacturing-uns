"""The OEE arithmetic, and nothing else.

Spec section 8:

    Planned Down   = | (planned exception windows u planned-reason stops) n shift |
    Loading Time   = (shift_end - shift_start) - Planned Down
    Unplanned Down = | (unplanned-reason stops) n Loading Time |
    Run Time       = Loading Time - Unplanned Down

    Availability = Run Time / Loading Time
    Performance  = sum_p (ideal_cycle_time_s(p) x total_count(p)) / Run Time
    Quality      = Good Count / Total Count
    OEE          = Availability x Performance x Quality

Planned time has two sources: a calendar exception, and a stop whose reason is planned. Both
leave Loading Time, and they are unioned - an exception window overlapping a changeover is
one period of planned time, and summing it twice inflates Availability. In the flattering
direction, which is the kind of error nobody reports.

Unplanned stops are intersected with Loading Time before they reduce Run Time, so a breakdown
during a planned shutdown is not subtracted twice.

No factor is ever invented. Where a denominator is zero the factor is `None` and `status`
says which case it was, because a shift that nobody staffed is not a 0% shift.

Pure, and no clock: `compute` reads only what it is given.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from uns_oee.classifier import ClassifiedStop, planned_intervals, unplanned_intervals
from uns_oee.states import Interval, intersect, subtract, union_duration_s

STATUS_OK = "OK"
STATUS_NO_LOADING_TIME = "NO_LOADING_TIME"
STATUS_NO_PRODUCTION = "NO_PRODUCTION"
STATUS_MISSING_IDEAL_CYCLE_TIME = "MISSING_IDEAL_CYCLE_TIME"
STATUS_NO_INPUT_DATA = "NO_INPUT_DATA"

#: Performance above this means the authored ideal cycle time is wrong. Clamped, never hidden.
_PERFORMANCE_CEILING = 1.0


@dataclass(frozen=True, slots=True)
class ProductSegment:
    """What one product ran during, and what it produced.

    Counts are counter deltas taken over `intervals`, not pro-rated from a shift total: a
    counter is cumulative, so its delta across a segment already is that segment's output and
    needs no assumption about rate. `product_code` is `None` when the unit declares no product
    binding, in which case the pipeline passes a single segment spanning the whole shift.
    """

    product_code: str | None = None
    intervals: tuple[Interval, ...] = ()
    ideal_cycle_time_s: float | None = None
    good_count: float = 0.0
    reject_count: float = 0.0

    @property
    def total_count(self) -> float:
        return self.good_count + self.reject_count


@dataclass(frozen=True, slots=True)
class ShiftInputs:
    """Everything one shift's numbers are computed from.

    `has_input_data` is separate from `products` being empty: a unit that published nothing
    all shift is a different fact from a unit that was scheduled, ran, and made nothing.
    """

    window: Interval
    exception_intervals: tuple[Interval, ...] = ()
    classified_stops: tuple[ClassifiedStop, ...] = ()
    products: tuple[ProductSegment, ...] = ()
    has_input_data: bool = True


@dataclass(frozen=True, slots=True)
class ProductMetrics:
    """One product's share of the shift, as stored in `oee.shift_result_product`."""

    product_code: str | None
    run_time_s: float
    good_count: float
    reject_count: float
    total_count: float
    ideal_cycle_time_s: float | None


@dataclass(frozen=True, slots=True)
class ShiftMetrics:
    """One shift's result. A `None` factor is a fact, not a missing value - see `status`."""

    loading_time_s: float = 0.0
    run_time_s: float = 0.0
    planned_down_s: float = 0.0
    unplanned_down_s: float = 0.0
    good_count: float = 0.0
    reject_count: float = 0.0
    total_count: float = 0.0
    availability: float | None = None
    performance: float | None = None
    performance_raw: float | None = None
    quality: float | None = None
    oee: float | None = None
    status: str = STATUS_NO_INPUT_DATA
    products: tuple[ProductMetrics, ...] = field(default_factory=tuple)
    missing_ideal_cycle_time: bool = False
    performance_over_unity: bool = False


def compute(inputs: ShiftInputs) -> ShiftMetrics:
    """The four factors for one shift, or the reason there are none."""
    if not inputs.has_input_data:
        return ShiftMetrics(status=STATUS_NO_INPUT_DATA)

    planned = list(inputs.exception_intervals) + planned_intervals(inputs.classified_stops)
    planned_in_shift = intersect(planned, [inputs.window])
    planned_down_s = union_duration_s(planned_in_shift)
    loading = subtract([inputs.window], planned_in_shift)
    loading_time_s = union_duration_s(loading)

    unplanned_in_loading = intersect(unplanned_intervals(inputs.classified_stops), loading)
    unplanned_down_s = union_duration_s(unplanned_in_loading)
    run = subtract(loading, unplanned_in_loading)
    run_time_s = union_duration_s(run)

    products = _product_metrics(inputs.products, run)
    good_count = sum(item.good_count for item in products)
    reject_count = sum(item.reject_count for item in products)
    total_count = good_count + reject_count

    if loading_time_s <= 0.0:
        return ShiftMetrics(
            planned_down_s=planned_down_s,
            good_count=good_count,
            reject_count=reject_count,
            total_count=total_count,
            status=STATUS_NO_LOADING_TIME,
            products=products,
        )

    availability = run_time_s / loading_time_s
    quality = good_count / total_count if total_count > 0.0 else None
    performance_raw, missing_ideal = _performance_raw(products, run_time_s, total_count)
    performance = None if performance_raw is None else min(performance_raw, _PERFORMANCE_CEILING)
    oee = None if performance is None or quality is None else availability * performance * quality

    return ShiftMetrics(
        loading_time_s=loading_time_s,
        run_time_s=run_time_s,
        planned_down_s=planned_down_s,
        unplanned_down_s=unplanned_down_s,
        good_count=good_count,
        reject_count=reject_count,
        total_count=total_count,
        availability=availability,
        performance=performance,
        performance_raw=performance_raw,
        quality=quality,
        oee=oee,
        status=_status(performance, quality, missing_ideal),
        products=products,
        missing_ideal_cycle_time=missing_ideal,
        performance_over_unity=performance_raw is not None and performance_raw > _PERFORMANCE_CEILING,
    )


def _product_metrics(
    segments: Sequence[ProductSegment], run: Sequence[Interval]
) -> tuple[ProductMetrics, ...]:
    """Each segment's counts, with its run time clipped to the shift's actual Run Time.

    Clipping means the per-product run times sum to the shift's Run Time rather than to the
    segments' wall-clock length, so a per-product panel reconciles with the headline row.
    """
    return tuple(
        ProductMetrics(
            product_code=segment.product_code,
            run_time_s=union_duration_s(intersect(segment.intervals, run)),
            good_count=segment.good_count,
            reject_count=segment.reject_count,
            total_count=segment.total_count,
            ideal_cycle_time_s=segment.ideal_cycle_time_s,
        )
        for segment in segments
    )


def _performance_raw(
    products: Sequence[ProductMetrics], run_time_s: float, total_count: float
) -> tuple[float | None, bool]:
    """The unclamped Performance, and whether an ideal cycle time was missing.

    All-or-nothing on the master data: if any product that actually produced has no authored
    ideal cycle time, Performance is null rather than computed from the products that do. A
    partial numerator over the full Run Time understates Performance by an amount that looks
    like a real loss.
    """
    if run_time_s <= 0.0 or total_count <= 0.0:
        return None, False
    producing = [item for item in products if item.total_count > 0.0]
    if any(item.ideal_cycle_time_s is None for item in producing):
        return None, True
    ideal_seconds = sum(
        (item.ideal_cycle_time_s or 0.0) * item.total_count for item in producing
    )
    return ideal_seconds / run_time_s, False


def _status(performance: float | None, quality: float | None, missing_ideal: bool) -> str:
    """Which of the section 8.1 cases this shift landed in.

    Order matters: a shift with no ideal cycle time and no production is reported as
    NO_PRODUCTION, because fixing the master data would not give it a Performance.
    """
    if quality is None or (performance is None and not missing_ideal):
        return STATUS_NO_PRODUCTION
    if missing_ideal:
        return STATUS_MISSING_IDEAL_CYCLE_TIME
    return STATUS_OK


__all__ = [
    "STATUS_MISSING_IDEAL_CYCLE_TIME",
    "STATUS_NO_INPUT_DATA",
    "STATUS_NO_LOADING_TIME",
    "STATUS_NO_PRODUCTION",
    "STATUS_OK",
    "ProductMetrics",
    "ProductSegment",
    "ShiftInputs",
    "ShiftMetrics",
    "compute",
]
