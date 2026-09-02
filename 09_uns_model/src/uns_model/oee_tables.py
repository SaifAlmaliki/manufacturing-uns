"""Declarative models for shift OEE: master data in schema `model`, results in `oee`.

Two schemas because the two halves have different lifecycles. Master data is authored
by a person from `conf/oee/*.yaml` and changes rarely; results are derived, disposable
and recomputable from the historian at any time. Putting the derived half in its own
schema means it can be truncated and rebuilt without touching anything a human wrote.

Nothing here is a hypertable. Result volume is one row per unit per shift - a few
thousand rows a year - so a plain table with a b-tree index is the right shape, and
`uns_metrics` remains the only time-series table in the platform (ADR-0002).
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from uns_model.model_config import MODEL_SCHEMA, OEE_SCHEMA
from uns_model.tables import Base

#: What a calendar exception does to a shift window. PLANNED_DOWN subtracts from Loading
#: Time; NON_PRODUCING and HOLIDAY do too, and are kept distinct only so a report can say
#: which it was.
SHIFT_EXCEPTION_KINDS: tuple[str, ...] = ("PLANNED_DOWN", "NON_PRODUCING", "HOLIDAY")

#: Who put the reason code on a downtime event. `manual` is never overwritten.
REASON_SOURCES: tuple[str, ...] = ("auto", "manual")

#: Why a shift result reads the way it does. Precedence when several could apply is
#: NO_INPUT_DATA, NO_LOADING_TIME, NO_PRODUCTION, MISSING_IDEAL_CYCLE_TIME, OK.
OEE_STATUSES: tuple[str, ...] = (
    "OK",
    "NO_LOADING_TIME",
    "NO_PRODUCTION",
    "MISSING_IDEAL_CYCLE_TIME",
    "NO_INPUT_DATA",
)

#: PackML/OMAC states that count as producing. EXECUTE is the only one that makes parts.
DEFAULT_PRODUCING_STATES: tuple[str, ...] = ("EXECUTE",)

#: The reason assigned when no rule matches. Never null, so a Pareto always adds up.
UNCLASSIFIED_REASON_CODE = "UNCLASSIFIED"

#: (code, display_name, category, is_planned) seeded by migration 0003. A deployment adds
#: to these from conf/oee/reasons.yaml; they exist so a fresh install can classify at all.
DEFAULT_DOWNTIME_REASONS: tuple[tuple[str, str, str, bool], ...] = (
    ("UNCLASSIFIED", "Unclassified", "Unknown", False),
    ("PLANNED_MAINTENANCE", "Planned maintenance", "Maintenance", True),
    ("CHANGEOVER", "Product changeover", "Setup", True),
    ("PLANNED_BREAK", "Planned break", "Organisational", True),
    ("BREAKDOWN", "Equipment breakdown", "Technical", False),
    ("MINOR_STOP", "Minor stop", "Technical", False),
    ("MATERIAL_SHORTAGE", "Material shortage", "Supply", False),
    ("OPERATOR_ABSENT", "No operator", "Organisational", False),
    ("QUALITY_HOLD", "Quality hold", "Quality", False),
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """A CHECK body constraining `column` to `values`."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


# --------------------------------------------------------------------------------------
# Master data - schema `model`
# --------------------------------------------------------------------------------------


class Product(Base):
    """Something the plant makes. Ideal cycle time is per Asset and per Product."""

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("code", name="uq_product_code"),
        CheckConstraint("code <> ''", name="ck_product_code_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    """The value that appears on the product/recipe topic, e.g. 'RECIPE-A'."""

    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"Product(code={self.code!r})"


class ShiftPattern(Base):
    """A named weekly shift schedule, in one timezone."""

    __tablename__ = "shift_pattern"
    __table_args__ = (
        UniqueConstraint("name", name="uq_shift_pattern_name"),
        CheckConstraint("timezone <> ''", name="ck_shift_pattern_timezone_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    """IANA zone name, e.g. 'Europe/Berlin'. Shift slots are local wall-clock times, so
    the zone is what makes a 06:00 start mean 06:00 to the operator across a DST change."""

    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=True,
    )
    """The Asset this pattern was authored for, for display and scoping only. NULL means
    site-wide. Which pattern a unit uses is decided by `oee_unit.shift_pattern_id`."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"ShiftPattern(name={self.name!r}, timezone={self.timezone!r})"


class ShiftPatternSlot(Base):
    """One shift within a weekly pattern.

    Stored as (day, local start time, duration) rather than (start, end) so a shift that
    crosses midnight needs no second row and no end-before-start special case.
    """

    __tablename__ = "shift_pattern_slot"
    __table_args__ = (
        UniqueConstraint(
            "shift_pattern_id", "day_of_week", "start_time", name="uq_shift_slot_pattern_day_start"
        ),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_shift_slot_day_of_week"),
        CheckConstraint(
            "duration_minutes > 0 AND duration_minutes <= 1440", name="ck_shift_slot_duration"
        ),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shift_pattern_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.shift_pattern.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    """0 = Monday, matching `datetime.date.weekday()`."""

    start_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    """Local wall-clock start, resolved through the pattern's timezone at read time."""

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """What the operators call it, e.g. 'A'. Published on the KPI payload."""

    def __repr__(self) -> str:
        return f"ShiftPatternSlot(day={self.day_of_week}, start={self.start_time}, label={self.label!r})"


class ShiftException(Base):
    """A window that is not available for production, overriding the weekly pattern."""

    __tablename__ = "shift_exception"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_shift_exception_range"),
        CheckConstraint(_in_list("kind", SHIFT_EXCEPTION_KINDS), name="ck_shift_exception_kind"),
        Index("idx_shift_exception_window", "starts_at", "ends_at"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=True,
    )
    """NULL means every Asset - a plant holiday is one row, not one per line."""

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="PLANNED_DOWN")
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"ShiftException(kind={self.kind!r}, starts_at={self.starts_at})"


class OeeUnit(Base):
    """An Asset that OEE is reported for, and where its inputs come from.

    The subject is the Line, because that is the number a plant manages. The metric
    bindings are paths relative to the Line's topic prefix, so they can name a descendant
    machine - `Cell1/MES-01/Status/PackMlState/value` - without a second Asset row and
    without a column that duplicates the tree.
    """

    __tablename__ = "oee_unit"
    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_oee_unit_asset"),
        CheckConstraint("state_metric_key <> ''", name="ck_oee_unit_state_metric_key"),
        CheckConstraint(
            "array_length(producing_states, 1) >= 1", name="ck_oee_unit_producing_states"
        ),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_pattern_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.shift_pattern.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state_metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    good_count_metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    reject_count_metric_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    """NULL when the line publishes no reject counter. Quality is then 1.0."""

    product_metric_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    """NULL when the line makes one product. Ideal cycle time then falls back to the
    Asset-wide row, which is what the NULL `product_id` in `ideal_cycle_time` is for."""

    producing_states: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{EXECUTE}'::text[]")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"OeeUnit(asset_id={self.asset_id}, state_metric_key={self.state_metric_key!r})"


class IdealCycleTime(Base):
    """Seconds per unit at the designed rate, per Asset and optionally per Product."""

    __tablename__ = "ideal_cycle_time"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "product_id",
            name="uq_ideal_cycle_time_asset_product",
            # A NULL product_id means 'any product on this Asset'. Without this, two such
            # rows would both be accepted and the lookup would be ambiguous.
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("seconds_per_unit > 0", name="ck_ideal_cycle_time_positive"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.product.id", ondelete="CASCADE"),
        nullable=True,
    )
    seconds_per_unit: Mapped[float] = mapped_column(Double, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"IdealCycleTime(asset_id={self.asset_id}, product_id={self.product_id})"


class DowntimeReason(Base):
    """A downtime reason code and whether it counts as planned.

    `is_planned` is an input to the calculation, not a label: a planned stop leaves
    Loading Time, an unplanned one leaves Run Time. That is why classification runs
    before the calculator.
    """

    __tablename__ = "downtime_reason"
    __table_args__ = (
        CheckConstraint("code <> ''", name="ck_downtime_reason_code_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_planned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    def __repr__(self) -> str:
        return f"DowntimeReason(code={self.code!r}, is_planned={self.is_planned})"


class StateReasonMap(Base):
    """Maps a published state value to a reason code, for auto-classification."""

    __tablename__ = "state_reason_map"
    __table_args__ = (
        UniqueConstraint(
            "oee_unit_id",
            "state_value",
            name="uq_state_reason_map_unit_state",
            # NULL oee_unit_id is the default rule for every unit; two defaults for one
            # state value would make classification depend on row order.
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("state_value <> ''", name="ck_state_reason_map_state_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=True,
    )
    """NULL is the platform default rule. A unit-specific row wins over it."""

    state_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{MODEL_SCHEMA}.downtime_reason.code", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"StateReasonMap(unit={self.oee_unit_id}, state={self.state_value!r})"


# --------------------------------------------------------------------------------------
# Results - schema `oee`
# --------------------------------------------------------------------------------------


class ShiftResult(Base):
    """The current OEE result for one unit and one shift.

    One row per (unit, shift_start), overwritten in place when a revision supersedes it.
    The superseded numbers move to `shift_result_revision`, so a dashboard reads one row
    and an audit can still see what the number was yesterday.
    """

    __tablename__ = "shift_result"
    __table_args__ = (
        UniqueConstraint("oee_unit_id", "shift_start", name="uq_shift_result_unit_start"),
        CheckConstraint("shift_end > shift_start", name="ck_shift_result_range"),
        CheckConstraint(_in_list("status", OEE_STATUSES), name="ck_shift_result_status"),
        CheckConstraint("revision >= 1", name="ck_shift_result_revision"),
        CheckConstraint(
            "good_count >= 0 AND reject_count >= 0 AND total_count >= 0",
            name="ck_shift_result_counts_non_negative",
        ),
        Index("idx_shift_result_shift_start", "shift_start"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    loading_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    run_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    planned_down_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    unplanned_down_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")

    good_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    reject_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    total_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")

    availability: Mapped[float | None] = mapped_column(Double, nullable=True)
    performance: Mapped[float | None] = mapped_column(Double, nullable=True)
    performance_raw: Mapped[float | None] = mapped_column(Double, nullable=True)
    """Performance before the clamp at 1.0. A value above 1 means the ideal cycle time is
    wrong or a stop was missed, and the unclamped number is the only evidence of that."""

    quality: Mapped[float | None] = mapped_column(Double, nullable=True)
    oee: Mapped[float | None] = mapped_column(Double, nullable=True)
    """Ratios are NULL, never zero, when they are undefined. A shift with no Loading Time
    did not achieve 0% Availability - it has no Availability, and averaging a fabricated
    zero drags every rollup down."""

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="OK")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """Row count and max(time) over the input window. Equal fingerprint means equal input,
    so a re-check can skip the whole computation."""

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """NULL means the result exists but has not reached MQTT. The engine retries these."""

    def __repr__(self) -> str:
        return f"ShiftResult(unit={self.oee_unit_id}, shift_start={self.shift_start}, oee={self.oee})"


class ShiftResultProduct(Base):
    """Per-product counts and ideal time within one shift result.

    Performance is a sum over products, so the terms have to be stored: a mixed shift's
    number cannot be re-derived from the totals once the product mix is gone.
    """

    __tablename__ = "shift_result_product"
    __table_args__ = (
        UniqueConstraint("shift_result_id", "product_code", name="uq_shift_result_product"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shift_result_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{OEE_SCHEMA}.shift_result.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """The raw published value, not a FK: an unknown recipe must still be recorded."""

    good_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    reject_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    total_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    ideal_cycle_time_s: Mapped[float | None] = mapped_column(Double, nullable=True)
    """NULL when no ideal cycle time was configured, which sets status
    MISSING_IDEAL_CYCLE_TIME on the parent row."""

    def __repr__(self) -> str:
        return f"ShiftResultProduct(product={self.product_code!r}, total={self.total_count})"


class ShiftResultRevision(Base):
    """A superseded result, kept verbatim so a changed number can be explained."""

    __tablename__ = "shift_result_revision"
    __table_args__ = (
        UniqueConstraint("oee_unit_id", "shift_start", "revision", name="uq_shift_result_revision"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    loading_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    run_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    good_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    reject_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    total_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    availability: Mapped[float | None] = mapped_column(Double, nullable=True)
    performance: Mapped[float | None] = mapped_column(Double, nullable=True)
    quality: Mapped[float | None] = mapped_column(Double, nullable=True)
    oee: Mapped[float | None] = mapped_column(Double, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="OK")
    input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"ShiftResultRevision(unit={self.oee_unit_id}, revision={self.revision})"


class DowntimeEvent(Base):
    """One stop, with the reason it is attributed to.

    Keyed on (unit, started_at) rather than on the shift result, because a manual reason
    assignment must survive recomputation - and recomputation replaces the result row.
    """

    __tablename__ = "downtime_event"
    __table_args__ = (
        UniqueConstraint("oee_unit_id", "started_at", name="uq_downtime_event_unit_start"),
        CheckConstraint("ended_at > started_at", name="ck_downtime_event_range"),
        CheckConstraint(
            _in_list("reason_source", REASON_SOURCES), name="ck_downtime_event_reason_source"
        ),
        Index("idx_downtime_event_shift", "oee_unit_id", "shift_start"),
        Index("idx_downtime_event_reason", "reason_code"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    state_value: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """The published state that held for the whole stop, e.g. 'ABORTED'."""

    reason_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{MODEL_SCHEMA}.downtime_reason.code", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
        server_default=UNCLASSIFIED_REASON_CODE,
    )
    reason_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="auto")
    assigned_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"DowntimeEvent(unit={self.oee_unit_id}, started_at={self.started_at})"


class RecomputeRequest(Base):
    """A queued request to recompute a range, from the CLI or a reason reassignment.

    A queue rather than a direct call: a reason change arrives on the GraphQL process, and
    the engine is the only writer of results. `claimed_at` is how a single worker takes a
    request without a lock table.
    """

    __tablename__ = "recompute_request"
    __table_args__ = (
        CheckConstraint("range_end > range_start", name="ck_recompute_request_range"),
        Index("idx_recompute_request_pending", "claimed_at", "requested_at"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=True,
    )
    """NULL means every active unit."""

    range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"RecomputeRequest(unit={self.oee_unit_id}, range_start={self.range_start})"


__all__ = [
    "DEFAULT_DOWNTIME_REASONS",
    "DEFAULT_PRODUCING_STATES",
    "OEE_STATUSES",
    "REASON_SOURCES",
    "SHIFT_EXCEPTION_KINDS",
    "UNCLASSIFIED_REASON_CODE",
    "DowntimeEvent",
    "DowntimeReason",
    "IdealCycleTime",
    "OeeUnit",
    "Product",
    "RecomputeRequest",
    "ShiftException",
    "ShiftPattern",
    "ShiftPatternSlot",
    "ShiftResult",
    "ShiftResultProduct",
    "ShiftResultRevision",
    "StateReasonMap",
]
