"""Platform Observability for the OEE engine: spec section 14's series on port 9095.

Twenty-two series, twenty-one of them named in the spec and one - `_compute_failures_total` -
added because section 13 asks for a counted skip and `PassSummary.failures` is that count.

Everything here is fed from a `PassSummary` and a `Readings`, never read from the database by
the collector itself. A scrape must not be able to start a query: Prometheus scrapes on its
own HTTP thread, and a gauge that lazily queried Timescale would put an unbounded, unpooled
database call on a path whose only failure mode should be a stale number.
"""

import logging
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
from sqlalchemy import func, select

from uns_model.engine import Database
from uns_model.oee_tables import RecomputeRequest, ShiftResult
from uns_oee.pipeline import ACTION_REVISED, ShiftOutcome
from uns_oee.scheduler import SKIP_NO_HISTORY, SKIP_PREDATES_DATA, PassSummary

LOGGER = logging.getLogger(__name__)

#: prometheus_client appends `_total` to every Counter, so the names declared below are one
#: suffix short of the names spec section 14 promises. The test asserts the exposed text.
METRIC_PREFIX = "uns_oee"

#: A shift is a handful of indexed queries plus arithmetic over one shift's samples. Anything
#: past ten seconds means the historian is struggling, which is worth its own bucket.
COMPUTE_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

_UNIT = "unit"
_STATUS = "status"
_REASON = "reason"


@dataclass(frozen=True, slots=True)
class Readings:
    """The three numbers that come from the database rather than from a pass.

    `database_up` defaults to False so a failed read cannot be mistaken for a healthy one by
    omission - the caller has to have succeeded to set it.
    """

    recompute_queue_depth: int = 0
    unpublished_results: int = 0
    database_up: bool = False


async def read_gauges(database: Database) -> Readings:
    """The queue depth and the publication backlog, in one transaction.

    Both are `count(*)` over an indexed partial predicate, so they are cheap enough to read
    once per pass. Any failure returns `database_up=False` with the counts left at zero: a
    stale non-zero backlog would be worse than an obvious outage.
    """
    queued = (
        select(func.count())
        .select_from(RecomputeRequest)
        .where(RecomputeRequest.claimed_at.is_(None))
    )
    unpublished = (
        select(func.count()).select_from(ShiftResult).where(ShiftResult.published_at.is_(None))
    )
    try:
        async with database.begin() as connection:
            depth = (await connection.execute(queued)).scalar_one()
            backlog = (await connection.execute(unpublished)).scalar_one()
    except Exception:
        LOGGER.exception("OEE could not read its observability counts")
        return Readings(database_up=False)
    return Readings(
        recompute_queue_depth=int(depth or 0),
        unpublished_results=int(backlog or 0),
        database_up=True,
    )


class OeeMetrics:
    """The engine's series, on their own registry.

    Instance attributes rather than module-level objects: several of these are built in one
    test session, and module-level Counters sharing a registry raise on the second import.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        registry_ = self.registry

        self.shifts_computed = Counter(
            f"{METRIC_PREFIX}_shifts_computed",
            "Shifts whose result was computed, by unit and result status.",
            [_UNIT, _STATUS],
            registry=registry_,
        )
        self.compute_seconds = Histogram(
            f"{METRIC_PREFIX}_shift_compute_seconds",
            "Wall time to compute, store and publish one shift.",
            buckets=COMPUTE_BUCKETS,
            registry=registry_,
        )
        self.revisions = Counter(
            f"{METRIC_PREFIX}_revisions",
            "Stored results superseded by a recomputation, from any cause.",
            [_UNIT],
            registry=registry_,
        )
        self.late_data = Counter(
            f"{METRIC_PREFIX}_late_data_detected",
            "Revisions caused by historian rows arriving after the shift settled.",
            [_UNIT],
            registry=registry_,
        )
        self.input_rows = Gauge(
            f"{METRIC_PREFIX}_input_rows",
            "Historian rows behind the most recently computed shift.",
            [_UNIT],
            registry=registry_,
        )
        self.shift_oee = Gauge(
            f"{METRIC_PREFIX}_shift_oee",
            "OEE of the most recently computed shift, 0 to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.availability = Gauge(
            f"{METRIC_PREFIX}_availability",
            "Availability of the most recently computed shift, 0 to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.performance = Gauge(
            f"{METRIC_PREFIX}_performance",
            "Performance of the most recently computed shift, clamped to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.quality = Gauge(
            f"{METRIC_PREFIX}_quality",
            "Quality of the most recently computed shift, 0 to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.performance_over_unity = Counter(
            f"{METRIC_PREFIX}_performance_over_unity",
            "Shifts whose raw Performance exceeded 1.0 and was clamped.",
            [_UNIT],
            registry=registry_,
        )
        self.counter_resets = Counter(
            f"{METRIC_PREFIX}_counter_resets",
            "Production counter resets or rollovers detected inside a shift.",
            [_UNIT],
            registry=registry_,
        )
        self.missing_ideal_cycle_time = Counter(
            f"{METRIC_PREFIX}_missing_ideal_cycle_time",
            "Shifts with a product segment that had no ideal cycle time authored.",
            [_UNIT],
            registry=registry_,
        )
        self.unclassified_downtime_seconds = Counter(
            f"{METRIC_PREFIX}_unclassified_downtime_seconds",
            "Downtime with no state_reason_map rule behind it. A master-data hole.",
            [_UNIT],
            registry=registry_,
        )
        self.compute_failures = Counter(
            f"{METRIC_PREFIX}_compute_failures",
            "Shift computations that raised and were skipped so the pass could continue.",
            registry=registry_,
        )
        self.backfill_shifts = Counter(
            f"{METRIC_PREFIX}_backfill_shifts",
            "Shifts the first pass enumerated for the bounded backfill.",
            [_UNIT],
            registry=registry_,
        )
        self.backfill_shifts_skipped = Counter(
            f"{METRIC_PREFIX}_backfill_shifts_skipped",
            "Backfill shifts declined, by reason.",
            [_UNIT, _REASON],
            registry=registry_,
        )
        self.publishes = Counter(
            f"{METRIC_PREFIX}_publish",
            "Shift results published to the namespace.",
            registry=registry_,
        )
        self.publish_errors = Counter(
            f"{METRIC_PREFIX}_publish_errors",
            "Publish attempts that failed, leaving published_at NULL for the next pass.",
            registry=registry_,
        )
        self.last_shift_close = Gauge(
            f"{METRIC_PREFIX}_last_shift_close_timestamp",
            "Unix time of the end of the last shift closed for this unit.",
            [_UNIT],
            registry=registry_,
        )
        self.recompute_queue_depth = Gauge(
            f"{METRIC_PREFIX}_recompute_queue_depth",
            "Unclaimed rows in oee.recompute_request.",
            registry=registry_,
        )
        self.unpublished_results = Gauge(
            f"{METRIC_PREFIX}_unpublished_results",
            "Stored results whose published_at is still NULL. The broker backlog.",
            registry=registry_,
        )
        self.db_up = Gauge(
            f"{METRIC_PREFIX}_db_up",
            "1 when the engine's last database read succeeded, 0 otherwise.",
            registry=registry_,
        )

    def observe_pass(self, summary: PassSummary) -> None:
        """Record everything one pass produced."""
        self.compute_failures.inc(summary.failures)
        for tally in summary.backfill:
            # `.inc(0)` on purpose: the series exists at zero, so a Grafana panel shows a
            # backfill that skipped nothing rather than a gap that could mean anything.
            self.backfill_shifts.labels(tally.asset_path).inc(tally.computed)
            self.backfill_shifts_skipped.labels(tally.asset_path, SKIP_NO_HISTORY).inc(
                tally.skipped_no_history
            )
            self.backfill_shifts_skipped.labels(tally.asset_path, SKIP_PREDATES_DATA).inc(
                tally.skipped_predates_data
            )
        for outcome in summary.outcomes:
            self._observe_shift(outcome)

    def apply(self, readings: Readings) -> None:
        """Set the three gauges that come from the database."""
        self.recompute_queue_depth.set(readings.recompute_queue_depth)
        self.unpublished_results.set(readings.unpublished_results)
        self.db_up.set(1.0 if readings.database_up else 0.0)

    def serve(self, port: int) -> None:
        """Expose the registry on `port` in a background thread."""
        start_http_server(port, registry=self.registry)
        LOGGER.info("OEE metrics available on port %d", port)

    def _observe_shift(self, outcome: ShiftOutcome) -> None:
        """One shift's contribution. An UNCHANGED shift contributes nothing.

        `metrics is None` is the test rather than the action name, because it is the honest
        one: without a `ShiftMetrics` there is no status to label and no factor to set.
        """
        if outcome.metrics is None:
            return
        metrics = outcome.metrics
        unit = outcome.asset_path

        self.compute_seconds.observe(outcome.compute_seconds)
        self.shifts_computed.labels(unit, metrics.status).inc()
        self.input_rows.labels(unit).set(outcome.input_rows)
        self.last_shift_close.labels(unit).set(outcome.window.end.timestamp())
        self.counter_resets.labels(unit).inc(outcome.counter_resets)
        self.unclassified_downtime_seconds.labels(unit).inc(outcome.unclassified_seconds)

        if outcome.action == ACTION_REVISED:
            self.revisions.labels(unit).inc()
            # Zeroed rather than skipped, so the series exists for every unit that has ever
            # been revised and a rate() over it is not a gap.
            self.late_data.labels(unit).inc(1 if outcome.late_data else 0)
        if metrics.performance_over_unity:
            self.performance_over_unity.labels(unit).inc()
        if metrics.missing_ideal_cycle_time:
            self.missing_ideal_cycle_time.labels(unit).inc()
        if outcome.published:
            self.publishes.inc()
        else:
            self.publish_errors.inc()

        # A null factor is left unset. `_scalar_to_metric` makes the same choice on the MQTT
        # side (04_uns_historian/src/uns_historian/metric_flattener.py): an undefined
        # Availability rendered as 0.0 would read as a catastrophic shift instead of no shift.
        self._set_if_known(self.shift_oee, unit, metrics.oee)
        self._set_if_known(self.availability, unit, metrics.availability)
        self._set_if_known(self.performance, unit, metrics.performance)
        self._set_if_known(self.quality, unit, metrics.quality)

    @staticmethod
    def _set_if_known(gauge: Gauge, unit: str, value: float | None) -> None:
        if value is not None:
            gauge.labels(unit).set(value)


__all__ = ["COMPUTE_BUCKETS", "METRIC_PREFIX", "OeeMetrics", "Readings", "read_gauges"]
