"""Loading the authored master data one OEE run needs.

Read once per scan and handed to the pure modules as frozen dataclasses, so a thirty-day
backfill re-queries nothing. Everything that resolves - an ideal cycle time falling back to
the Asset default, an exception applying to a descendant Asset - resolves here, in one place,
where it is testable without a database.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from uns_model.engine import Database
from uns_model.oee_tables import (
    DEFAULT_PRODUCING_STATES,
    DowntimeReason,
    IdealCycleTime,
    OeeUnit,
    Product,
    ShiftException,
    ShiftPattern,
    ShiftPatternSlot,
    StateReasonMap,
)
from uns_model.tables import Asset

from uns_oee.classifier import ReasonResolver, ReasonSpec
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot
from uns_oee.sources import MetricRef, split_metric_key
from uns_oee.states import Interval, merge

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UnitMasterData:
    """One `model.oee_unit` row with everything it points at already resolved."""

    unit_id: int
    asset_id: int
    asset_path: str
    schedule: ShiftSchedule
    producing_states: tuple[str, ...]
    state_ref: MetricRef
    good_ref: MetricRef
    reject_ref: MetricRef | None
    product_ref: MetricRef | None
    ideal_cycle_times: Mapping[str | None, float]
    resolver: ReasonResolver

    @property
    def refs(self) -> tuple[MetricRef, ...]:
        """Every series this unit reads. The fingerprint is taken over exactly these.

        Exactly these, so a unit with no reject counter is not fingerprinted over a series
        that will never have rows - which would leave `max(time)` permanently behind and make
        every shift look like it was still waiting for data.
        """
        optional = (self.reject_ref, self.product_ref)
        return (self.state_ref, self.good_ref, *(ref for ref in optional if ref is not None))

    def ideal_cycle_time_for(self, product_code: str | None) -> float | None:
        """This product's authored cycle time, else the Asset default, else nothing.

        A value row winning over a null row is the same precedence `MetricDefinition` and
        `state_reason_map` already use. Returning `None` rather than a guess is what makes the
        calculator report MISSING_IDEAL_CYCLE_TIME instead of averaging over a master data gap.
        """
        if product_code is not None and product_code in self.ideal_cycle_times:
            return self.ideal_cycle_times[product_code]
        return self.ideal_cycle_times.get(None)


@dataclass(frozen=True, slots=True)
class ExceptionWindow:
    """A `model.shift_exception` row that applies to a unit, clipped to the shift."""

    interval: Interval
    kind: str
    asset_path: str | None


def applies_to(exception_asset_path: str | None, unit_asset_path: str) -> bool:
    """Whether an exception authored on one Asset covers a unit.

    Null covers every unit; the unit's own Asset covers it; an ancestor covers it, so a
    site-wide shutdown does not have to be repeated on every line. A descendant does not: one
    cell stopping is not the line stopping, which is the whole point of reporting at the line.
    """
    if exception_asset_path is None:
        return True
    if exception_asset_path == unit_asset_path:
        return True
    return unit_asset_path.startswith(f"{exception_asset_path}/")


def exception_intervals(windows: Sequence[ExceptionWindow]) -> list[Interval]:
    """The windows as a minimal set of non-overlapping intervals.

    Coalesced here rather than at the call site so two overlapping exceptions cannot be
    subtracted from Loading Time twice.
    """
    return merge(window.interval for window in windows)


class MasterDataLoader:
    """Every read of the authored tables the engine performs."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def active_units(self) -> list[UnitMasterData]:
        """Every active OEE unit, fully resolved. One call per scan.

        Five small selects rather than one join with five left outer joins: the authored tables
        hold tens of rows, and the shared lookups - reasons, rules, slots - are the same for
        every unit, so fetching them once each is both fewer rows and easier to read.
        """
        async with self._database.session() as session:
            reasons = {
                row.code: ReasonSpec(
                    code=row.code,
                    display_name=row.display_name,
                    category=row.category,
                    is_planned=row.is_planned,
                )
                for row in (await session.scalars(select(DowntimeReason))).all()
            }
            rules = (await session.scalars(select(StateReasonMap))).all()
            slots = (await session.scalars(select(ShiftPatternSlot))).all()
            cycle_times = (
                await session.execute(
                    select(
                        IdealCycleTime.asset_id,
                        Product.code,
                        IdealCycleTime.seconds_per_unit,
                    ).outerjoin(Product, IdealCycleTime.product_id == Product.id)
                )
            ).all()
            units = (
                await session.execute(
                    select(OeeUnit, Asset.path, ShiftPattern.name, ShiftPattern.timezone)
                    .join(Asset, OeeUnit.asset_id == Asset.id)
                    .join(ShiftPattern, OeeUnit.shift_pattern_id == ShiftPattern.id)
                    .where(OeeUnit.is_active.is_(True))
                    .order_by(Asset.path)
                )
            ).all()

        return [
            self._resolve(
                unit=unit,
                asset_path=asset_path,
                schedule=_schedule(pattern_name, pattern_timezone, unit.shift_pattern_id, slots),
                reasons=reasons,
                rules=rules,
                cycle_times=cycle_times,
            )
            for unit, asset_path, pattern_name, pattern_timezone in units
        ]

    async def exception_windows(
        self, unit: UnitMasterData, window: Interval
    ) -> list[ExceptionWindow]:
        """The exceptions overlapping `window` that apply to `unit`, clipped to it.

        Fetched by time range only; whether an exception's Asset covers the unit is decided in
        Python by `applies_to`, because the rows in one window are few and a prefix check is
        easier to be sure of than the SQL equivalent.
        """
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(ShiftException, Asset.path)
                    .outerjoin(Asset, ShiftException.asset_id == Asset.id)
                    .where(
                        ShiftException.starts_at < window.end,
                        ShiftException.ends_at > window.start,
                    )
                )
            ).all()

        found: list[ExceptionWindow] = []
        for exception, asset_path in rows:
            if not applies_to(asset_path, unit.asset_path):
                continue
            clipped = Interval(exception.starts_at, exception.ends_at).clipped_to(window)
            if clipped is not None:
                found.append(
                    ExceptionWindow(interval=clipped, kind=exception.kind, asset_path=asset_path)
                )
        return found

    def _resolve(
        self,
        unit: OeeUnit,
        asset_path: str,
        schedule: ShiftSchedule,
        reasons: Mapping[str, ReasonSpec],
        rules: Sequence[StateReasonMap],
        cycle_times: Sequence[tuple[int, str | None, float]],
    ) -> UnitMasterData:
        """One ORM unit and the shared lookups, as a frozen record the pure modules accept."""
        producing = tuple(unit.producing_states or ())
        if not producing:
            LOGGER.warning(
                "OEE unit %s declares no producing states; falling back to %s. Every state "
                "would otherwise be a stop and Availability would read zero.",
                asset_path,
                DEFAULT_PRODUCING_STATES,
            )
            producing = tuple(DEFAULT_PRODUCING_STATES)

        return UnitMasterData(
            unit_id=unit.id,
            asset_id=unit.asset_id,
            asset_path=asset_path,
            schedule=schedule,
            producing_states=producing,
            state_ref=split_metric_key(asset_path, unit.state_metric_key),
            good_ref=split_metric_key(asset_path, unit.good_count_metric_key),
            reject_ref=_optional_ref(asset_path, unit.reject_count_metric_key),
            product_ref=_optional_ref(asset_path, unit.product_metric_key),
            ideal_cycle_times={
                product_code: float(seconds)
                for asset_id, product_code, seconds in cycle_times
                if asset_id == unit.asset_id
            },
            resolver=ReasonResolver(
                reasons=reasons,
                unit_rules={
                    rule.state_value: rule.reason_code
                    for rule in rules
                    if rule.oee_unit_id == unit.id
                },
                default_rules={
                    rule.state_value: rule.reason_code
                    for rule in rules
                    if rule.oee_unit_id is None
                },
            ),
        )


def _optional_ref(asset_path: str, metric_key: str | None) -> MetricRef | None:
    """A binding that the unit may legitimately not have. Blank counts as absent."""
    return split_metric_key(asset_path, metric_key) if metric_key else None


def _schedule(
    name: str, timezone_name: str, pattern_id: int, slots: Sequence[ShiftPatternSlot]
) -> ShiftSchedule:
    """The ORM shift pattern as the calendar's calculation shape.

    Sorted, so two runs build the same schedule and the windows come out in the same order -
    `shift_windows` sorts its output anyway, but a stable schedule is easier to compare in a log.
    """
    return ShiftSchedule(
        name=name,
        timezone=timezone_name,
        slots=tuple(
            ShiftSlot(
                day_of_week=slot.day_of_week,
                start_time=slot.start_time,
                duration_minutes=slot.duration_minutes,
                label=slot.label or "",
            )
            for slot in sorted(
                (slot for slot in slots if slot.shift_pattern_id == pattern_id),
                key=lambda slot: (slot.day_of_week, slot.start_time),
            )
        ),
    )


__all__ = [
    "ExceptionWindow",
    "MasterDataLoader",
    "UnitMasterData",
    "applies_to",
    "exception_intervals",
]
