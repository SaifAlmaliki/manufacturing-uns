"""Writing one shift's numbers, so that writing them twice changes nothing.

Recomputation is normal here: a late sample, a corrected shift exception or an operator
assigning a downtime reason all make yesterday's shift worth computing again. Every write is
therefore keyed on something the engine did not derive - a result on (unit, shift_start), a
stop on (unit, started_at) - and the numbers a revision replaces move to
`oee.shift_result_revision` rather than disappearing.

The one thing a recomputation must never do is overwrite a person. `classifier.classify`
already honours a stored manual reason; the `ON CONFLICT` clause here refuses the overwrite a
second time, because the match by `started_at` fails whenever recomputation moves a stop's
first sample, and an operator's work must not depend on that.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, delete, insert, select, update
from sqlalchemy.dialects.postgresql import Insert as PostgresInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from uns_model.engine import Database
from uns_model.oee_tables import (
    DowntimeEvent,
    ShiftResult,
    ShiftResultProduct,
    ShiftResultRevision,
)
from uns_oee.classifier import MANUAL, ClassifiedStop, ManualReason
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import Fingerprint

LOGGER = logging.getLogger(__name__)

#: Derived from the samples on every run, so always refreshed. None of these is ever authored.
GEOMETRY_COLUMNS = ("shift_start", "ended_at", "duration_s", "state_value")

#: Kept as they are once `reason_source` is 'manual'. This tuple is the enforcement of Rule 3.
REASON_COLUMNS = ("reason_code", "reason_source", "assigned_by", "assigned_at", "note")


@dataclass(frozen=True, slots=True)
class StoredResult:
    """What is already on record for one shift.

    `input_fingerprint` is the reason this type exists: comparing it against a fresh
    fingerprint is how the pipeline decides a shift needs no work, which is what makes a
    30-day backfill cheap on its second run.
    """

    result_id: int
    revision: int
    input_fingerprint: str
    published_at: datetime | None


def result_values(
    unit_id: int,
    window: ShiftWindow,
    metrics: ShiftMetrics,
    fingerprint: Fingerprint,
    computed_at: datetime,
) -> dict[str, object]:
    """The `oee.shift_result` column values for one computed shift.

    `published_at` is always None, including on a revision. A corrected number has not been
    published even though the number it replaces was, and keeping the old timestamp would make
    the publisher skip the correction and leave MQTT disagreeing with the database for good.
    """
    return {
        "oee_unit_id": unit_id,
        "shift_start": window.start,
        "shift_end": window.end,
        "shift_label": window.label,
        "loading_time_s": metrics.loading_time_s,
        "run_time_s": metrics.run_time_s,
        "planned_down_s": metrics.planned_down_s,
        "unplanned_down_s": metrics.unplanned_down_s,
        "good_count": metrics.good_count,
        "reject_count": metrics.reject_count,
        "total_count": metrics.total_count,
        "availability": metrics.availability,
        "performance": metrics.performance,
        "performance_raw": metrics.performance_raw,
        "quality": metrics.quality,
        "oee": metrics.oee,
        "status": metrics.status,
        "input_fingerprint": fingerprint.as_text(),
        "computed_at": computed_at,
        "published_at": None,
    }


def revision_values(stored: ShiftResult) -> dict[str, object]:
    """The row about to be replaced, as an `oee.shift_result_revision` insert.

    The old `revision` and the old `computed_at` are copied, not restamped: this row's whole
    purpose is to say what the number was and when it was worked out. `superseded_at` is left
    to the column default so the database, not the engine, records when it stopped being true.
    """
    return {
        "oee_unit_id": stored.oee_unit_id,
        "shift_start": stored.shift_start,
        "revision": stored.revision,
        "loading_time_s": stored.loading_time_s,
        "run_time_s": stored.run_time_s,
        "good_count": stored.good_count,
        "reject_count": stored.reject_count,
        "total_count": stored.total_count,
        "availability": stored.availability,
        "performance": stored.performance,
        "quality": stored.quality,
        "oee": stored.oee,
        "status": stored.status,
        "input_fingerprint": stored.input_fingerprint,
        "computed_at": stored.computed_at,
    }


def product_values(result_id: int, metrics: ShiftMetrics) -> list[dict[str, object]]:
    """One `oee.shift_result_product` row per product segment.

    A segment with no product code stores the empty string rather than NULL, because
    `product_code` is part of a unique constraint and NULLs there would let the same unbound
    segment be inserted twice.
    """
    return [
        {
            "shift_result_id": result_id,
            "product_code": item.product_code or "",
            "good_count": item.good_count,
            "reject_count": item.reject_count,
            "total_count": item.total_count,
            "ideal_cycle_time_s": item.ideal_cycle_time_s,
        }
        for item in metrics.products
    ]


def event_values(
    unit_id: int, shift_start: datetime, stops: Sequence[ClassifiedStop]
) -> list[dict[str, object]]:
    """One `oee.downtime_event` row per classified stop.

    `assigned_at` is always None. A stop can only be manual because a stored row already was,
    and the conflict clause keeps that row's timestamp - so a value here would either be
    ignored or, worse, restamp a human decision with the time the engine last ran.
    """
    return [
        {
            "oee_unit_id": unit_id,
            "shift_start": shift_start,
            "started_at": stop.interval.start,
            "ended_at": stop.interval.end,
            "duration_s": stop.interval.duration_s,
            "state_value": stop.state_value,
            "reason_code": stop.reason_code,
            "reason_source": stop.source,
            "assigned_by": stop.assigned_by,
            "assigned_at": None,
            "note": stop.note,
        }
        for stop in stops
    ]


def downtime_upsert(rows: Sequence[Mapping[str, object]]) -> PostgresInsert:
    """Insert these stops, refreshing what is derived and preserving what a person set.

    In `ON CONFLICT DO UPDATE`, an unqualified reference to the target table is the row already
    stored and `excluded` is the row being inserted. So each reason column becomes: keep the
    stored value where the stored `reason_source` is 'manual', otherwise take the new one. The
    geometry columns take the new value unconditionally, because a stop that recomputed to a
    different length is a better fact than the one on record.
    """
    statement = pg_insert(DowntimeEvent)
    stored = DowntimeEvent.__table__.c
    is_manual = stored.reason_source == MANUAL
    refreshed: dict[str, object] = {
        column: statement.excluded[column] for column in GEOMETRY_COLUMNS
    }
    preserved: dict[str, object] = {
        column: case((is_manual, stored[column]), else_=statement.excluded[column])
        for column in REASON_COLUMNS
    }
    return statement.values(list(rows)).on_conflict_do_update(
        index_elements=["oee_unit_id", "started_at"],
        set_=refreshed | preserved,
    )


class ResultStore:
    """Every write the engine makes to the `oee` schema."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def existing(self, unit_id: int, shift_start: datetime) -> StoredResult | None:
        """What is on record for this shift, or None if it has never been computed."""
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(
                        ShiftResult.id,
                        ShiftResult.revision,
                        ShiftResult.input_fingerprint,
                        ShiftResult.published_at,
                    ).where(
                        ShiftResult.oee_unit_id == unit_id,
                        ShiftResult.shift_start == shift_start,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        return StoredResult(
            result_id=row.id,
            revision=row.revision,
            input_fingerprint=row.input_fingerprint,
            published_at=row.published_at,
        )

    async def manual_reasons(
        self, unit_id: int, window: ShiftWindow
    ) -> dict[datetime, ManualReason]:
        """The human-assigned reasons inside this shift, keyed by the stop's start instant.

        Keyed by `started_at` because that is what `classifier.classify` matches on, and what
        the unique constraint keys on. A stop whose start moved between runs will not match,
        which is why `downtime_upsert` refuses the overwrite as well.
        """
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(
                        DowntimeEvent.started_at,
                        DowntimeEvent.reason_code,
                        DowntimeEvent.note,
                        DowntimeEvent.assigned_by,
                    ).where(
                        DowntimeEvent.oee_unit_id == unit_id,
                        DowntimeEvent.reason_source == MANUAL,
                        DowntimeEvent.started_at >= window.start,
                        DowntimeEvent.started_at < window.end,
                    )
                )
            ).all()
        return {
            row.started_at: ManualReason(
                reason_code=row.reason_code, note=row.note, assigned_by=row.assigned_by
            )
            for row in rows
        }

    async def save(
        self,
        unit_id: int,
        window: ShiftWindow,
        metrics: ShiftMetrics,
        stops: Sequence[ClassifiedStop],
        fingerprint: Fingerprint,
        computed_at: datetime,
    ) -> StoredResult:
        """Write this shift's numbers, superseding whatever was there. One transaction.

        The existing row is selected `FOR UPDATE` so two engine processes cannot both decide
        they are writing revision 3. On the insert path there is no row to lock, and the unique
        constraint on (oee_unit_id, shift_start) is what stops the duplicate instead.
        """
        values = result_values(unit_id, window, metrics, fingerprint, computed_at)
        async with self._database.session() as session:
            stored = (
                await session.scalars(
                    select(ShiftResult)
                    .where(
                        ShiftResult.oee_unit_id == unit_id,
                        ShiftResult.shift_start == window.start,
                    )
                    .with_for_update()
                )
            ).one_or_none()

            if stored is None:
                revision = 1
                result_id = (
                    await session.execute(
                        insert(ShiftResult)
                        .values(**values, revision=revision)
                        .returning(ShiftResult.id)
                    )
                ).scalar_one()
            else:
                revision = stored.revision + 1
                result_id = stored.id
                session.add(ShiftResultRevision(**revision_values(stored)))
                await session.execute(
                    update(ShiftResult)
                    .where(ShiftResult.id == result_id)
                    .values(**values, revision=revision)
                )
                await session.execute(
                    delete(ShiftResultProduct).where(
                        ShiftResultProduct.shift_result_id == result_id
                    )
                )
                LOGGER.info(
                    "OEE unit %d shift %s recomputed as revision %d",
                    unit_id,
                    window.start.isoformat(),
                    revision,
                )

            products = product_values(result_id, metrics)
            if products:
                await session.execute(insert(ShiftResultProduct), products)

            events = event_values(unit_id, window.start, stops)
            if events:
                await session.execute(downtime_upsert(events))

        return StoredResult(
            result_id=result_id,
            revision=revision,
            input_fingerprint=str(values["input_fingerprint"]),
            published_at=None,
        )

    async def mark_published(self, result_id: int, published_at: datetime) -> None:
        """Record that this result reached MQTT.

        Separate from `save` and written after the publish returns, so a broker outage leaves
        `published_at` NULL and the next scan retries rather than silently losing the message.
        """
        async with self._database.session() as session:
            await session.execute(
                update(ShiftResult)
                .where(ShiftResult.id == result_id)
                .values(published_at=published_at)
            )


__all__ = [
    "GEOMETRY_COLUMNS",
    "REASON_COLUMNS",
    "ResultStore",
    "StoredResult",
    "downtime_upsert",
    "event_values",
    "product_values",
    "result_values",
    "revision_values",
]
