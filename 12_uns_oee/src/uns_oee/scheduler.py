"""Which shifts a pass computes (spec sections 9 and 9.1).

Four sources of work, in one ordered list per unit:

  recheck   every settled shift still inside `late_window_hours`
  request   every settled shift inside a claimed `oee.recompute_request` range
  backfill  on the first pass only, back to `backfill_days` clamped to retention
  (nothing)  a shift older than the late window with no request against it

`run_pass(now)` takes the pass's timestamp as an argument and passes it down as `computed_at`.
Nothing in this module or below it reads a clock, which is what makes a pass replayable and
`recompute_cli` able to reproduce a historical result exactly.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import select, text, update

from uns_model.engine import Database
from uns_model.oee_tables import RecomputeRequest
from uns_oee.master_data import MasterDataLoader, UnitMasterData
from uns_oee.oee_config import OeeConfig
from uns_oee.pipeline import ShiftOutcome, ShiftPipeline
from uns_oee.shift_calendar import ShiftWindow, shift_windows
from uns_oee.sources import MetricSource

LOGGER = logging.getLogger(__name__)

#: Requests claimed per pass. A ceiling rather than a page size: a reason reassignment queues
#: one row, so reaching 200 means something is generating requests in a loop, and draining
#: them all in one pass would starve the shifts that are actually due.
REQUEST_CLAIM_LIMIT = 200

#: Label values for `uns_oee_backfill_shifts_skipped_total{unit,reason}`. Two distinct facts:
#: a unit that has never published anything, and a shift older than the data it would need.
SKIP_NO_HISTORY = "NO_HISTORY"
SKIP_PREDATES_DATA = "PREDATES_DATA"

#: Postgres parses the policy's interval and converts it to days; see `retention_days`.
_RETENTION_SQL = """
SELECT EXTRACT(EPOCH FROM (config->>'drop_after')::interval) / 86400.0
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_retention' AND hypertable_name = :table
"""


@dataclass(frozen=True, slots=True)
class ClaimedRange:
    """One recompute request this instance has taken. `unit_id` None means every unit."""

    request_id: int
    unit_id: int | None
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    """The backfill's windows plus what it declined, so the skips can be counted.

    A skip is reported rather than silently dropped: spec section 13 requires
    `_backfill_shifts_skipped_total`, because "no result for last March" and "we chose not to
    compute last March" are different answers to the same operator question.
    """

    windows: tuple[ShiftWindow, ...] = ()
    skipped_no_history: int = 0
    skipped_predates_data: int = 0


@dataclass(frozen=True, slots=True)
class BackfillTally:
    """One unit's backfill, as the metrics module needs it labelled."""

    unit_id: int
    asset_path: str
    computed: int
    skipped_no_history: int
    skipped_predates_data: int


@dataclass(frozen=True, slots=True)
class PassSummary:
    """What one pass did. Consumed by prometheus_metrics, which owns no state of its own."""

    outcomes: tuple[ShiftOutcome, ...] = ()
    units: int = 0
    windows: int = 0
    failures: int = 0
    backfilled: bool = False
    backfill: tuple[BackfillTally, ...] = ()


def clamp_backfill_days(configured: int, retention: float | None) -> int:
    """`backfill_days`, reduced to what the retention policy can still answer.

    Without the clamp, a 400-day request against a one-year hypertable would write months of
    NO_INPUT_DATA results for chunks that were dropped on schedule - an outage in the data
    that never happened in the plant.
    """
    if retention is None:
        return configured
    return min(configured, int(retention))


def _lookback(unit: UnitMasterData, late_window_hours: int) -> timedelta:
    """How far back to enumerate so no shift inside the late window is missed.

    `shift_windows` bounds by start, so the range has to open one full shift earlier than the
    late window itself. Derived from the schedule's longest slot rather than a fixed margin,
    because a 30-hour campaign shift is a legitimate roster.
    """
    longest = max(
        (timedelta(minutes=slot.duration_minutes) for slot in unit.schedule.slots),
        default=timedelta(),
    )
    return timedelta(hours=late_window_hours) + longest


def recheck_windows(
    unit: UnitMasterData, now: datetime, *, settle_minutes: int, late_window_hours: int
) -> list[ShiftWindow]:
    """Settled shifts still inside their late window - the steady-state work of a pass.

    No earliest-input guard here, deliberately. A unit that has gone silent must still get one
    row per shift with `status = 'NO_INPUT_DATA'` (spec section 13), because that row is the
    only evidence in the system that a line stopped reporting.
    """
    limit = timedelta(hours=late_window_hours)
    return [
        window
        for window in shift_windows(unit.schedule, now - _lookback(unit, late_window_hours), now)
        if window.is_closed_at(now, settle_minutes) and now - window.end <= limit
    ]


def backfill_windows(
    unit: UnitMasterData,
    now: datetime,
    *,
    settle_minutes: int,
    backfill_days: int,
    earliest_input_at: datetime | None,
) -> BackfillPlan:
    """Settled shifts back to `now - backfill_days` that the unit has data for.

    A shift ending at or before the unit's first sample is skipped entirely rather than stored
    as NO_INPUT_DATA: the line was not silent then, it did not exist in this system yet, and a
    Grafana panel cannot tell those two apart. A unit with no samples at all gets nothing, and
    both kinds of skip are counted so the decision is visible.
    """
    settled = [
        window
        for window in shift_windows(unit.schedule, now - timedelta(days=backfill_days), now)
        if window.is_closed_at(now, settle_minutes)
    ]
    if earliest_input_at is None:
        return BackfillPlan(skipped_no_history=len(settled))
    kept = tuple(window for window in settled if window.end > earliest_input_at)
    return BackfillPlan(windows=kept, skipped_predates_data=len(settled) - len(kept))


def request_windows(
    unit: UnitMasterData,
    ranges: Sequence[tuple[datetime, datetime]],
    now: datetime,
    *,
    settle_minutes: int,
) -> list[ShiftWindow]:
    """Settled shifts inside the requested ranges, with no late window applied.

    The late window exists because a machine does not amend last month's data by itself. A
    human reassigning a reason code is exactly the case it was never meant to block.
    """
    windows: list[ShiftWindow] = []
    for start, end in ranges:
        windows.extend(
            window
            for window in shift_windows(unit.schedule, start, end)
            if window.is_closed_at(now, settle_minutes)
        )
    return windows


def ranges_for(
    unit_id: int, claimed: Sequence[ClaimedRange]
) -> tuple[tuple[datetime, datetime], ...]:
    """The claimed ranges that apply to one unit, including the unit-less ones."""
    return tuple(
        (item.start, item.end) for item in claimed if item.unit_id in (None, unit_id)
    )


def ordered_unique(windows: Sequence[ShiftWindow]) -> list[ShiftWindow]:
    """One window per shift start, earliest first.

    Keyed on `start` because that is what `uq_shift_result_unit_start` is keyed on: two
    sources offering the same shift are the same row, and computing it twice in one pass would
    write a revision whose only change is the revision number.
    """
    seen: set[datetime] = set()
    unique: list[ShiftWindow] = []
    for window in sorted(windows, key=lambda item: item.start):
        if window.start in seen:
            continue
        seen.add(window.start)
        unique.append(window)
    return unique


async def retention_days(database: Database, table: str) -> float | None:
    """The hypertable's retention policy in days, or None if it has none.

    The interval is parsed by Postgres rather than by this module: `1 year` and `365 days` are
    both legitimate policy values and only the server knows what the first one means.
    """
    async with database.begin() as connection:
        row = (await connection.execute(text(_RETENTION_SQL), {"table": table})).first()
    if row is None or row[0] is None:
        return None
    return float(row[0])


async def claim_requests(
    database: Database, at: datetime, *, limit: int = REQUEST_CLAIM_LIMIT
) -> list[ClaimedRange]:
    """Take up to `limit` unclaimed requests, stamping `claimed_at`.

    `FOR UPDATE SKIP LOCKED` inside the subquery is what makes a second engine instance a
    no-op rather than a duplicate writer: it takes the rows the first instance did not, and
    `claimed_at` keeps them taken across restarts.
    """
    pending = (
        select(RecomputeRequest.id)
        .where(RecomputeRequest.claimed_at.is_(None))
        .order_by(RecomputeRequest.requested_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    statement = (
        update(RecomputeRequest)
        .where(RecomputeRequest.id.in_(pending))
        .values(claimed_at=at)
        .returning(
            RecomputeRequest.id,
            RecomputeRequest.oee_unit_id,
            RecomputeRequest.range_start,
            RecomputeRequest.range_end,
        )
    )
    async with database.begin() as connection:
        rows = (await connection.execute(statement)).fetchall()
    return [
        ClaimedRange(request_id=row[0], unit_id=row[1], start=row[2], end=row[3]) for row in rows
    ]


async def complete_requests(
    database: Database,
    request_ids: Sequence[int],
    at: datetime,
    *,
    error: str | None = None,
) -> None:
    """Close the claimed requests. Coarse by design: one verdict for the whole pass.

    A request names a range, and a range spans shifts across units, so attributing one
    window's failure to one request would be a guess. `error` records that the pass which
    drained these requests was not clean, and the operator re-runs it from `recompute_cli`.
    """
    if not request_ids:
        return
    statement = (
        update(RecomputeRequest)
        .where(RecomputeRequest.id.in_(list(request_ids)))
        .values(completed_at=at, error=error)
    )
    async with database.begin() as connection:
        await connection.execute(statement)


class ShiftScheduler:
    """One pass over every active unit, computing what is due.

    `claim`, `retention` and `complete` are injected with real defaults. They are this
    module's only SQL, against tables `ResultStore` does not own, and keeping them behind
    parameters is what lets the scheduling decisions be tested without a database.
    """

    def __init__(
        self,
        config: OeeConfig,
        database: Database,
        source: MetricSource,
        master: MasterDataLoader,
        pipeline: ShiftPipeline,
        *,
        claim: Callable = claim_requests,
        retention: Callable = retention_days,
        complete: Callable = complete_requests,
    ) -> None:
        self._config = config
        self._database = database
        self._source = source
        self._master = master
        self._pipeline = pipeline
        self._claim = claim
        self._retention = retention
        self._complete = complete
        self._backfill_days: int | None = None
        self._backfilled = False

    async def run_pass(self, now: datetime) -> PassSummary:
        """Compute every due shift for every active unit. Never raises for one unit's sake.

        A failure is counted and logged, and the pass continues: one line's historian gap must
        not cost the other lines their shift reports. The failure count is what makes the
        outage visible on `uns_oee_compute_failures_total`.
        """
        await self._bound_backfill()
        units = await self._master.active_units()
        claimed = await self._claim(self._database, now, limit=REQUEST_CLAIM_LIMIT)
        backfilling = not self._backfilled

        outcomes: list[ShiftOutcome] = []
        tallies: list[BackfillTally] = []
        windows_seen = 0
        failures = 0
        for unit in units:
            windows, tally = await self._windows_for(unit, now, claimed, backfilling)
            if tally is not None:
                tallies.append(tally)
            windows_seen += len(windows)
            for window in windows:
                try:
                    # Monotonic, so an NTP step during a pass cannot produce a negative
                    # histogram sample. Never stored - `computed_at` is the recorded time.
                    started = time.monotonic()
                    outcome = await self._pipeline.run_shift(unit, window, now)
                    outcomes.append(
                        replace(outcome, compute_seconds=time.monotonic() - started)
                    )
                except Exception:
                    failures += 1
                    LOGGER.exception(
                        "OEE compute failed for %s shift starting %s",
                        unit.asset_path,
                        window.start.isoformat(),
                    )

        if claimed:
            summary = None if failures == 0 else f"{failures} window(s) failed in this pass"
            await self._complete(
                self._database, [item.request_id for item in claimed], now, error=summary
            )

        # A backfill that half failed is not a backfill, so the next pass enumerates it again.
        # The re-enumeration is cheap - an unchanged shift costs two indexed queries - and the
        # alternative is losing history silently to a transient outage.
        if backfilling and failures == 0:
            self._backfilled = True

        return PassSummary(
            outcomes=tuple(outcomes),
            units=len(units),
            windows=windows_seen,
            failures=failures,
            backfilled=backfilling,
            backfill=tuple(tallies),
        )

    async def _bound_backfill(self) -> None:
        """Resolve `backfill_days` against the retention policy, once, and say so."""
        if self._backfill_days is not None:
            return
        retention = await self._retention(self._database, self._config.metrics_table)
        self._backfill_days = clamp_backfill_days(self._config.backfill_days, retention)
        if self._backfill_days != self._config.backfill_days:
            LOGGER.warning(
                "OEE backfill of %d days reduced to %d days: %s retains %s days",
                self._config.backfill_days,
                self._backfill_days,
                self._config.metrics_table,
                f"{retention:.0f}" if retention is not None else "unknown",
            )
        else:
            LOGGER.info(
                "OEE backfill bounded to %d days; %s retains %s days",
                self._backfill_days,
                self._config.metrics_table,
                f"{retention:.0f}" if retention is not None else "no policy",
            )

    async def _windows_for(
        self,
        unit: UnitMasterData,
        now: datetime,
        claimed: Sequence[ClaimedRange],
        backfilling: bool,
    ) -> tuple[list[ShiftWindow], BackfillTally | None]:
        """This unit's due shifts from all sources, deduped and ordered oldest first.

        Oldest first because a revision supersedes the row before it: computing September 9
        before September 1 would still be correct, but the revision history would read
        backwards to anyone auditing it.

        The tally is None on every pass but the first: there is no backfill to report.
        """
        windows = recheck_windows(
            unit,
            now,
            settle_minutes=self._config.settle_minutes,
            late_window_hours=self._config.late_window_hours,
        )
        windows.extend(
            request_windows(
                unit,
                ranges_for(unit.unit_id, claimed),
                now,
                settle_minutes=self._config.settle_minutes,
            )
        )
        if not backfilling:
            return ordered_unique(windows), None

        earliest = await self._source.earliest_sample_at(unit.refs)
        plan = backfill_windows(
            unit,
            now,
            settle_minutes=self._config.settle_minutes,
            backfill_days=self._backfill_days or 0,
            earliest_input_at=earliest,
        )
        windows.extend(plan.windows)
        tally = BackfillTally(
            unit_id=unit.unit_id,
            asset_path=unit.asset_path,
            computed=len(plan.windows),
            skipped_no_history=plan.skipped_no_history,
            skipped_predates_data=plan.skipped_predates_data,
        )
        return ordered_unique(windows), tally


__all__ = [
    "REQUEST_CLAIM_LIMIT",
    "SKIP_NO_HISTORY",
    "SKIP_PREDATES_DATA",
    "BackfillPlan",
    "BackfillTally",
    "ClaimedRange",
    "PassSummary",
    "ShiftScheduler",
    "backfill_windows",
    "claim_requests",
    "clamp_backfill_days",
    "complete_requests",
    "ordered_unique",
    "ranges_for",
    "recheck_windows",
    "request_windows",
    "retention_days",
]
