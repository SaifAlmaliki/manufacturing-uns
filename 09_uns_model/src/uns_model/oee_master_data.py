"""Authoring access to the OEE master data in schema `model`.

Follows `alert_rules.py`: a frozen dataclass spec per table with a `validate()` that
produces a readable error before Postgres gets a chance to produce an unreadable one, and
one repository that owns every write. Reads used by the engine live in the second half of
this file, added in Task 8.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from uns_model.engine import Database
from uns_model.oee_tables import (
    DEFAULT_PRODUCING_STATES,
    SHIFT_EXCEPTION_KINDS,
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


def _require_one_of(what: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {', '.join(allowed)}, got {value!r}")


def _require_non_empty(what: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{what} must not be empty")


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """Something the plant makes."""

    code: str
    name: str = ""

    def validate(self) -> None:
        _require_non_empty("product code", self.code)


@dataclass(frozen=True, slots=True)
class ShiftSlotSpec:
    """One shift on one weekday, as local wall-clock start plus duration."""

    day_of_week: int
    start_time: time
    duration_minutes: int
    label: str = ""

    def validate(self) -> None:
        if not 0 <= self.day_of_week <= 6:
            raise ValueError(f"day_of_week must be 0 (Monday) to 6 (Sunday), got {self.day_of_week}")
        if not 0 < self.duration_minutes <= 1440:
            raise ValueError(f"duration_minutes must be 1 to 1440, got {self.duration_minutes}")


@dataclass(frozen=True, slots=True)
class ShiftPatternSpec:
    """A named weekly schedule in one timezone."""

    name: str
    timezone: str
    asset_path: str | None = None
    slots: tuple[ShiftSlotSpec, ...] = ()

    def validate(self) -> None:
        _require_non_empty("shift pattern name", self.name)
        _require_non_empty("shift pattern timezone", self.timezone)
        if not self.slots:
            raise ValueError(f"shift pattern {self.name!r} declares no slots, so no shift ever closes")
        for slot in self.slots:
            slot.validate()


@dataclass(frozen=True, slots=True)
class ShiftExceptionSpec:
    """A window that is not available for production."""

    starts_at: datetime
    ends_at: datetime
    kind: str = "PLANNED_DOWN"
    asset_path: str | None = None
    note: str = ""

    def validate(self) -> None:
        _require_one_of("shift exception kind", self.kind, SHIFT_EXCEPTION_KINDS)
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("shift exception timestamps must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError(f"shift exception ends_at {self.ends_at} is not after starts_at {self.starts_at}")


@dataclass(frozen=True, slots=True)
class DowntimeReasonSpec:
    """A reason code and whether it counts as planned."""

    code: str
    display_name: str
    category: str = ""
    is_planned: bool = False

    def validate(self) -> None:
        _require_non_empty("downtime reason code", self.code)
        _require_non_empty("downtime reason display_name", self.display_name)


@dataclass(frozen=True, slots=True)
class OeeUnitSpec:
    """An Asset OEE is reported for, and where its inputs come from."""

    asset_path: str
    shift_pattern_name: str
    state_metric_key: str
    good_count_metric_key: str
    reject_count_metric_key: str | None = None
    product_metric_key: str | None = None
    producing_states: tuple[str, ...] = DEFAULT_PRODUCING_STATES

    def validate(self) -> None:
        _require_non_empty("unit asset path", self.asset_path)
        _require_non_empty("unit shift_pattern", self.shift_pattern_name)
        _require_non_empty("unit state_metric_key", self.state_metric_key)
        _require_non_empty("unit good_count_metric_key", self.good_count_metric_key)
        if not self.producing_states:
            raise ValueError(f"unit {self.asset_path!r} declares no producing states, so Run Time would always be zero")


@dataclass(frozen=True, slots=True)
class IdealCycleTimeSpec:
    """Seconds per unit at the designed rate. `product_code` None is the fallback."""

    asset_path: str
    seconds_per_unit: float
    product_code: str | None = None

    def validate(self) -> None:
        _require_non_empty("ideal cycle time asset path", self.asset_path)
        if self.seconds_per_unit <= 0:
            raise ValueError(
                f"ideal cycle time for {self.asset_path!r} must be greater than zero, got {self.seconds_per_unit}"
            )


@dataclass(frozen=True, slots=True)
class StateReasonRuleSpec:
    """Attributes a published state value to a reason code. None asset is the default."""

    state_value: str
    reason_code: str
    asset_path: str | None = None

    def validate(self) -> None:
        _require_non_empty("state rule state", self.state_value)
        _require_non_empty("state rule reason", self.reason_code)


def product_upsert(spec: ProductSpec):
    """Insert or update a product, reviving it if a previous import had deactivated it."""
    return (
        insert(Product)
        .values(code=spec.code, name=spec.name, is_active=True)
        .on_conflict_do_update(
            index_elements=[Product.code],
            set_={"name": spec.name, "is_active": True},
        )
        .returning(Product.id)
    )


def shift_pattern_upsert(spec: ShiftPatternSpec, asset_id: int | None):
    """Insert or update a pattern, reviving it if a previous import had deactivated it."""
    return (
        insert(ShiftPattern)
        .values(name=spec.name, timezone=spec.timezone, asset_id=asset_id, is_active=True)
        .on_conflict_do_update(
            index_elements=[ShiftPattern.name],
            set_={"timezone": spec.timezone, "asset_id": asset_id, "is_active": True},
        )
        .returning(ShiftPattern.id)
    )


def oee_unit_upsert(values: dict[str, Any]):
    """Insert or update a unit, reviving it if a previous import had deactivated it."""
    revived = {**values, "is_active": True}
    return (
        insert(OeeUnit)
        .values(**revived)
        .on_conflict_do_update(
            index_elements=[OeeUnit.asset_id],
            set_={**revived, "updated_at": func.now()},
        )
        .returning(OeeUnit.id)
    )


def deactivate_products_absent_from(keep_codes: Sequence[str]):
    statement = update(Product).values(is_active=False)
    if keep_codes:
        statement = statement.where(Product.code.notin_(list(keep_codes)))
    return statement


def deactivate_patterns_absent_from(keep_names: Sequence[str]):
    statement = update(ShiftPattern).values(is_active=False)
    if keep_names:
        statement = statement.where(ShiftPattern.name.notin_(list(keep_names)))
    return statement


def deactivate_units_absent_from(keep_asset_ids: Sequence[int]):
    statement = update(OeeUnit).values(is_active=False)
    if keep_asset_ids:
        statement = statement.where(OeeUnit.asset_id.notin_(list(keep_asset_ids)))
    return statement


def _delete_rows_absent_from(model: Any, keep_matchers: Sequence[Any]):
    statement = delete(model)
    if not keep_matchers:
        return statement
    return statement.where(~or_(*keep_matchers))


def delete_exceptions_absent_from(
    keep: Sequence[tuple[int | None, datetime, datetime, str]],
):
    matchers = [
        and_(
            ShiftException.asset_id.is_not_distinct_from(asset_id),
            ShiftException.starts_at == starts_at,
            ShiftException.ends_at == ends_at,
            ShiftException.kind == kind,
        )
        for asset_id, starts_at, ends_at, kind in keep
    ]
    return _delete_rows_absent_from(ShiftException, matchers)


def delete_cycle_times_absent_from(keep: Sequence[tuple[int, int | None]]):
    matchers = [
        and_(
            IdealCycleTime.asset_id == asset_id,
            IdealCycleTime.product_id.is_not_distinct_from(product_id),
        )
        for asset_id, product_id in keep
    ]
    return _delete_rows_absent_from(IdealCycleTime, matchers)


def delete_state_rules_absent_from(keep: Sequence[tuple[int | None, str]]):
    matchers = [
        and_(
            StateReasonMap.oee_unit_id.is_not_distinct_from(unit_id),
            StateReasonMap.state_value == state_value,
        )
        for unit_id, state_value in keep
    ]
    return _delete_rows_absent_from(StateReasonMap, matchers)


class OeeMasterDataRepository:
    """Every write to the OEE master data.

    Idempotent by natural key throughout - product code, pattern name, (asset, product),
    (unit, state) - so re-importing an edited `conf/oee/` updates rather than duplicates.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ---- writes -------------------------------------------------------------------

    async def save_product(self, spec: ProductSpec) -> int:
        spec.validate()
        async with self._database.session() as session:
            return (await session.execute(product_upsert(spec))).scalar_one()

    async def save_downtime_reason(self, spec: DowntimeReasonSpec) -> str:
        spec.validate()
        statement = (
            insert(DowntimeReason)
            .values(
                code=spec.code,
                display_name=spec.display_name,
                category=spec.category,
                is_planned=spec.is_planned,
            )
            .on_conflict_do_update(
                index_elements=[DowntimeReason.code],
                set_={
                    "display_name": spec.display_name,
                    "category": spec.category,
                    "is_planned": spec.is_planned,
                },
            )
            .returning(DowntimeReason.code)
        )
        async with self._database.session() as session:
            return (await session.execute(statement)).scalar_one()

    async def save_shift_pattern(self, spec: ShiftPatternSpec) -> int:
        """Upsert the pattern, then replace its slots wholesale.

        Replace rather than merge: the pattern is authored as one document, so a slot
        deleted from the YAML has to disappear from the database too.
        """
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._asset_id(session, spec.asset_path)
            pattern_id = (await session.execute(shift_pattern_upsert(spec, asset_id))).scalar_one()
            await session.execute(delete(ShiftPatternSlot).where(ShiftPatternSlot.shift_pattern_id == pattern_id))
            if spec.slots:
                await session.execute(
                    insert(ShiftPatternSlot),
                    [
                        {
                            "shift_pattern_id": pattern_id,
                            "day_of_week": slot.day_of_week,
                            "start_time": slot.start_time,
                            "duration_minutes": slot.duration_minutes,
                            "label": slot.label,
                        }
                        for slot in spec.slots
                    ],
                )
            return pattern_id

    async def save_shift_exception(self, spec: ShiftExceptionSpec) -> int:
        """Insert an exception, skipping an identical one.

        Keyed on the whole window rather than a surrogate id, so re-importing the same
        holiday does not add a second row - and two genuinely different overlapping
        exceptions are still both kept, because union arithmetic makes that harmless.
        """
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._asset_id(session, spec.asset_path)
            existing = (
                await session.execute(
                    select(ShiftException.id).where(
                        ShiftException.asset_id.is_not_distinct_from(asset_id),
                        ShiftException.starts_at == spec.starts_at,
                        ShiftException.ends_at == spec.ends_at,
                        ShiftException.kind == spec.kind,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
            return (
                await session.execute(
                    insert(ShiftException)
                    .values(
                        asset_id=asset_id,
                        starts_at=spec.starts_at,
                        ends_at=spec.ends_at,
                        kind=spec.kind,
                        note=spec.note,
                    )
                    .returning(ShiftException.id)
                )
            ).scalar_one()

    async def save_oee_unit(self, spec: OeeUnitSpec) -> int:
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._require_asset_id(session, spec.asset_path)
            pattern_id = (
                await session.execute(select(ShiftPattern.id).where(ShiftPattern.name == spec.shift_pattern_name))
            ).scalar_one_or_none()
            if pattern_id is None:
                raise ValueError(
                    f"unit {spec.asset_path!r} names shift pattern {spec.shift_pattern_name!r}, which does not exist"
                )
            values = {
                "asset_id": asset_id,
                "shift_pattern_id": pattern_id,
                "state_metric_key": spec.state_metric_key,
                "good_count_metric_key": spec.good_count_metric_key,
                "reject_count_metric_key": spec.reject_count_metric_key,
                "product_metric_key": spec.product_metric_key,
                "producing_states": list(spec.producing_states),
            }
            statement = oee_unit_upsert(values)
            return (await session.execute(statement)).scalar_one()

    async def save_ideal_cycle_time(self, spec: IdealCycleTimeSpec) -> int:
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._require_asset_id(session, spec.asset_path)
            product_id = None
            if spec.product_code is not None:
                product_id = (
                    await session.execute(select(Product.id).where(Product.code == spec.product_code))
                ).scalar_one_or_none()
                if product_id is None:
                    raise ValueError(
                        f"ideal cycle time on {spec.asset_path!r} names product {spec.product_code!r}, which does not exist"
                    )
            statement = (
                insert(IdealCycleTime)
                .values(asset_id=asset_id, product_id=product_id, seconds_per_unit=spec.seconds_per_unit)
                .on_conflict_do_update(
                    constraint="uq_ideal_cycle_time_asset_product",
                    set_={"seconds_per_unit": spec.seconds_per_unit, "updated_at": func.now()},
                )
                .returning(IdealCycleTime.id)
            )
            return (await session.execute(statement)).scalar_one()

    async def save_state_reason_rule(self, spec: StateReasonRuleSpec) -> int:
        spec.validate()
        async with self._database.session() as session:
            unit_id = None
            if spec.asset_path is not None:
                asset_id = await self._require_asset_id(session, spec.asset_path)
                unit_id = (await session.execute(select(OeeUnit.id).where(OeeUnit.asset_id == asset_id))).scalar_one_or_none()
                if unit_id is None:
                    raise ValueError(f"state rule names asset {spec.asset_path!r}, which is not an OEE unit")
            statement = (
                insert(StateReasonMap)
                .values(oee_unit_id=unit_id, state_value=spec.state_value, reason_code=spec.reason_code)
                .on_conflict_do_update(
                    constraint="uq_state_reason_map_unit_state",
                    set_={"reason_code": spec.reason_code},
                )
                .returning(StateReasonMap.id)
            )
            return (await session.execute(statement)).scalar_one()

    async def reconcile_products(self, specs: Sequence[ProductSpec]) -> None:
        async with self._database.session() as session:
            await session.execute(deactivate_products_absent_from([spec.code for spec in specs]))

    async def reconcile_shift_patterns(self, specs: Sequence[ShiftPatternSpec]) -> None:
        async with self._database.session() as session:
            await session.execute(deactivate_patterns_absent_from([spec.name for spec in specs]))

    async def reconcile_oee_units(self, specs: Sequence[OeeUnitSpec]) -> None:
        async with self._database.session() as session:
            asset_ids = [await self._require_asset_id(session, spec.asset_path) for spec in specs]
            await session.execute(deactivate_units_absent_from(asset_ids))

    async def reconcile_shift_exceptions(self, specs: Sequence[ShiftExceptionSpec]) -> None:
        async with self._database.session() as session:
            keep = [
                (await self._asset_id(session, spec.asset_path), spec.starts_at, spec.ends_at, spec.kind)
                for spec in specs
            ]
            await session.execute(delete_exceptions_absent_from(keep))

    async def reconcile_ideal_cycle_times(self, specs: Sequence[IdealCycleTimeSpec]) -> None:
        async with self._database.session() as session:
            keep: list[tuple[int, int | None]] = []
            for spec in specs:
                asset_id = await self._require_asset_id(session, spec.asset_path)
                product_id = None
                if spec.product_code is not None:
                    product_id = (
                        await session.execute(select(Product.id).where(Product.code == spec.product_code))
                    ).scalar_one_or_none()
                keep.append((asset_id, product_id))
            await session.execute(delete_cycle_times_absent_from(keep))

    async def reconcile_state_reason_rules(self, specs: Sequence[StateReasonRuleSpec]) -> None:
        async with self._database.session() as session:
            keep: list[tuple[int | None, str]] = []
            for spec in specs:
                unit_id = None
                if spec.asset_path is not None:
                    asset_id = await self._require_asset_id(session, spec.asset_path)
                    unit_id = (
                        await session.execute(select(OeeUnit.id).where(OeeUnit.asset_id == asset_id))
                    ).scalar_one_or_none()
                keep.append((unit_id, spec.state_value))
            await session.execute(delete_state_rules_absent_from(keep))

    # ---- reads --------------------------------------------------------------------

    async def counts(self) -> dict[str, int]:
        """Row counts, for the importer's closing log line."""
        tables = {
            "products": Product,
            "shift_patterns": ShiftPattern,
            "shift_pattern_slots": ShiftPatternSlot,
            "shift_exceptions": ShiftException,
            "downtime_reasons": DowntimeReason,
            "oee_units": OeeUnit,
            "ideal_cycle_times": IdealCycleTime,
            "state_reason_rules": StateReasonMap,
        }
        async with self._database.session() as session:
            return {
                name: (await session.execute(select(func.count()).select_from(model))).scalar_one()
                for name, model in tables.items()
            }

    # ---- helpers ------------------------------------------------------------------

    async def _asset_id(self, session: Any, asset_path: str | None) -> int | None:
        """None path means every Asset, which is stored as a NULL asset_id."""
        if asset_path is None:
            return None
        return await self._require_asset_id(session, asset_path)

    async def _require_asset_id(self, session: Any, asset_path: str) -> int:
        asset_id = (await session.execute(select(Asset.id).where(Asset.path == asset_path))).scalar_one_or_none()
        if asset_id is None:
            raise ValueError(f"Asset {asset_path!r} is not in the Asset Model. Run `uns_model_seed` first.")
        return asset_id


__all__ = [
    "DowntimeReasonSpec",
    "IdealCycleTimeSpec",
    "OeeMasterDataRepository",
    "OeeUnitSpec",
    "ProductSpec",
    "ShiftExceptionSpec",
    "ShiftPatternSpec",
    "ShiftSlotSpec",
    "StateReasonRuleSpec",
    "deactivate_patterns_absent_from",
    "deactivate_products_absent_from",
    "deactivate_units_absent_from",
    "delete_cycle_times_absent_from",
    "delete_exceptions_absent_from",
    "delete_state_rules_absent_from",
    "oee_unit_upsert",
    "product_upsert",
    "shift_pattern_upsert",
]
