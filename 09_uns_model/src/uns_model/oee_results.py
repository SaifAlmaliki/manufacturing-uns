"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Reading OEE results, and the one write a human is allowed to make to them.

The seam for schema `oee`, kept apart from `OeeMasterDataRepository` because a shift
result is not master data: the model says how the line is rostered and rated, a result
says what actually happened. They share a database and nothing else.

It lives here rather than in `12_uns_oee` so the GraphQL service can read results
without depending on the engine's package. `07_uns_graphql` already depends on
`09_uns_model`; importing `uns_oee` would put an aiomqtt publisher and a scheduler into
the API container for the sake of three SELECTs.

Every join is spelled out and every grouping happens in Python. There is no
`relationship()` anywhere in `uns_model`, because under asyncio a lazy load on an
unloaded attribute raises `MissingGreenlet` in the resolver rather than in the query.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select, update

from uns_model.engine import Database
from uns_model.oee_tables import (
    DowntimeEvent,
    DowntimeReason,
    OeeUnit,
    RecomputeRequest,
    ShiftResult,
    ShiftResultProduct,
)
from uns_model.tables import Asset

LOGGER = logging.getLogger(__name__)

MANUAL_REASON_SOURCE = "manual"
"""One of `REASON_SOURCES`. `test_oee_results.py` fails if it stops being."""

SINGLE_SHIFT_MARGIN = timedelta(seconds=1)
"""How wide a recompute range has to be to name exactly one shift.

`shift_windows` selects windows whose *start* lies in `[range_start, range_end)`, so a
range of one second beginning at a shift's start picks out that shift and no other -
including the one that begins the moment it ends.
"""


@dataclass(frozen=True, slots=True)
class ParetoBucket:
    """One reason code's share of the downtime in a window."""

    reason_code: str
    display_name: str
    category: str
    is_planned: bool
    event_count: int
    total_seconds: float
    share: float


@dataclass(frozen=True, slots=True)
class ShiftResultRow:
    """One `oee.shift_result` with its Asset path and its per-product terms."""

    result: ShiftResult
    asset_path: str
    products: tuple[ShiftResultProduct, ...] = ()


@dataclass(frozen=True, slots=True)
class DowntimeEventRow:
    """One `oee.downtime_event` with the reason it is attributed to already resolved.

    `is_planned` travels with the event because it is what explains a changed OEE: it is
    the flag that moves an interval between Unplanned Down and excluded time.
    """

    event: DowntimeEvent
    asset_path: str
    display_name: str
    category: str
    is_planned: bool


def pareto_from_rows(rows: Sequence[tuple[str, str, str, bool, int, float]]) -> list[ParetoBucket]:
    """Grouped rows, ordered as a Pareto and given their share of the total.

    A pure function, so the one piece of this file that decides a number can be tested
    without a database. `share` is 0.0 rather than None when nothing was lost: a Pareto of
    zero downtime has no bars, and a null would make the console's percentage formatter the
    place that decides what to draw.

    Ties break on the reason code, so two reasons with the same lost time do not swap
    places between two refreshes of the same dashboard.
    """
    total = sum(float(seconds) for *_, seconds in rows)
    buckets = [
        ParetoBucket(
            reason_code=code,
            # The column defaults to '', and a nameless bar is unreadable.
            display_name=display_name or code,
            category=category,
            is_planned=bool(is_planned),
            event_count=int(event_count),
            total_seconds=float(seconds),
            share=float(seconds) / total if total > 0 else 0.0,
        )
        for code, display_name, category, is_planned, event_count, seconds in rows
    ]
    buckets.sort(key=lambda bucket: (-bucket.total_seconds, bucket.reason_code))
    return buckets


class OeeResultRepository:
    """Everything the GraphQL service does with schema `oee`.

    Callers get whole rows and never a `Session`. The engine remains the only writer of
    results: the one write here corrects a reason code and *queues* a recomputation, which
    is why `assign_reason` touches `oee.recompute_request` and never `oee.shift_result`.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ------------------------------------------------------------------- reads

    async def shift_results(
        self, asset_path: str, range_start: datetime, range_end: datetime
    ) -> list[ShiftResultRow]:
        """The results for one Asset whose shift began in `[range_start, range_end)`.

        Two statements rather than one outer join: a shift with four products would repeat
        the result's twenty-odd columns four times, and the products would still have to be
        grouped in Python afterwards either way.
        """
        statement = (
            select(ShiftResult, Asset.path)
            .join(OeeUnit, ShiftResult.oee_unit_id == OeeUnit.id)
            .join(Asset, OeeUnit.asset_id == Asset.id)
            .where(
                Asset.path == asset_path,
                ShiftResult.shift_start >= range_start,
                ShiftResult.shift_start < range_end,
            )
            .order_by(ShiftResult.shift_start)
        )
        async with self._database.session() as session:
            found = (await session.execute(statement)).all()
            if not found:
                return []
            products = (
                await session.scalars(
                    select(ShiftResultProduct)
                    .where(ShiftResultProduct.shift_result_id.in_([result.id for result, _ in found]))
                    .order_by(ShiftResultProduct.shift_result_id, ShiftResultProduct.product_code)
                )
            ).all()

        by_result: dict[int, list[ShiftResultProduct]] = {}
        for product in products:
            by_result.setdefault(product.shift_result_id, []).append(product)
        return [
            ShiftResultRow(result=result, asset_path=path, products=tuple(by_result.get(result.id, ())))
            for result, path in found
        ]

    async def downtime_events(
        self, asset_path: str, range_start: datetime, range_end: datetime
    ) -> list[DowntimeEventRow]:
        """The stops for one Asset that began in `[range_start, range_end)`, oldest first.

        Filtered on `started_at` and not on `shift_start` - the same column and the same
        predicate `downtime_pareto` uses - so an events table and a Pareto chart on one
        dashboard can never disagree about which stops are in the window.

        An inner join to `downtime_reason` is safe: `reason_code` is NOT NULL behind a
        RESTRICT foreign key, so an event with no reason cannot exist.
        """
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    _event_projection().where(
                        Asset.path == asset_path,
                        DowntimeEvent.started_at >= range_start,
                        DowntimeEvent.started_at < range_end,
                    )
                    .order_by(DowntimeEvent.started_at)
                )
            ).all()
        return _event_rows(rows)

    async def downtime_pareto(
        self, asset_path: str, range_start: datetime, range_end: datetime
    ) -> list[ParetoBucket]:
        """Lost time per reason code over a window, largest first.

        Aggregated in the database rather than by summing `downtime_events` in Python: a
        year of stops on a busy line is tens of thousands of rows, and the console wants the
        nine reason codes.
        """
        statement = (
            select(
                DowntimeEvent.reason_code,
                DowntimeReason.display_name,
                DowntimeReason.category,
                DowntimeReason.is_planned,
                func.count().label("event_count"),
                func.coalesce(func.sum(DowntimeEvent.duration_s), 0.0).label("total_seconds"),
            )
            .join(OeeUnit, DowntimeEvent.oee_unit_id == OeeUnit.id)
            .join(Asset, OeeUnit.asset_id == Asset.id)
            .join(DowntimeReason, DowntimeEvent.reason_code == DowntimeReason.code)
            .where(
                Asset.path == asset_path,
                DowntimeEvent.started_at >= range_start,
                DowntimeEvent.started_at < range_end,
            )
            .group_by(
                DowntimeEvent.reason_code,
                DowntimeReason.display_name,
                DowntimeReason.category,
                DowntimeReason.is_planned,
            )
        )
        async with self._database.session() as session:
            rows = (await session.execute(statement)).all()
        return pareto_from_rows([tuple(row) for row in rows])

    async def get_downtime_event(self, event_id: int) -> DowntimeEventRow | None:
        """One stop by id, or None. Read-only, so a caller can refuse before assigning."""
        async with self._database.session() as session:
            rows = (
                await session.execute(_event_projection().where(DowntimeEvent.id == event_id))
            ).all()
        found = _event_rows(rows)
        return found[0] if found else None

    # ------------------------------------------------------------------- write

    async def assign_reason(
        self,
        event_id: int,
        reason_code: str,
        *,
        note: str | None = None,
        assigned_by: str,
    ) -> DowntimeEventRow | None:
        """Attribute a stop to a reason by hand, and queue that shift for recomputation.

        One transaction for both, because a corrected reason that never reached the queue
        would leave a downtime breakdown disagreeing with the OEE above it until somebody
        noticed and ran the CLI.

        `assigned_at` is `func.now()` and not a caller's timestamp: the console runs in a
        browser, and a wrong laptop clock must not be able to reorder who corrected what.

        `assigned_by` is required. The caller is the only party that knows who is asking, and
        a stored `None` would be an unattributable edit to plant data.

        Returns None when there is no such event. A console acting on a list of stops that a
        recomputation has since replaced is normal, not an error.
        """
        values: dict = {
            "reason_code": reason_code,
            "reason_source": MANUAL_REASON_SOURCE,
            "assigned_by": assigned_by,
            "assigned_at": func.now(),
        }
        if note is not None:
            # Omitted rather than defaulted to '': an operator correcting only the code must
            # not erase a note somebody else typed.
            values["note"] = note

        async with self._database.session() as session:
            known = (
                await session.scalars(select(DowntimeReason.code).where(DowntimeReason.code == reason_code))
            ).first()
            if known is None:
                # Checked here so the caller gets a sentence rather than a foreign key
                # violation naming a generated constraint.
                raise ValueError(f"{reason_code!r} is not an authored downtime reason code")

            changed = (
                await session.execute(
                    update(DowntimeEvent)
                    .where(DowntimeEvent.id == event_id)
                    .values(**values)
                    .returning(DowntimeEvent.oee_unit_id, DowntimeEvent.shift_start)
                )
            ).one_or_none()
            if changed is None:
                LOGGER.warning("No downtime event %s to assign reason %s to", event_id, reason_code)
                return None

            await session.execute(
                insert(RecomputeRequest).values(
                    oee_unit_id=changed.oee_unit_id,
                    range_start=changed.shift_start,
                    range_end=changed.shift_start + SINGLE_SHIFT_MARGIN,
                    reason=f"reason {reason_code} assigned to downtime event {event_id}",
                    requested_by=assigned_by,
                )
            )
            LOGGER.info(
                "Downtime event %s reassigned to %s by %s; shift %s queued for recompute",
                event_id,
                reason_code,
                assigned_by,
                changed.shift_start.isoformat(),
            )
            rows = _event_rows(
                (await session.execute(_event_projection().where(DowntimeEvent.id == event_id))).all()
            )
        return rows[0] if rows else None


def _event_projection():
    """The five-column event select, shared by the read and the write-then-read.

    One definition, so the row the mutation returns has exactly the shape the query
    returns - a console must not get a different object depending on how it got there.
    """
    return (
        select(
            DowntimeEvent,
            Asset.path,
            DowntimeReason.display_name,
            DowntimeReason.category,
            DowntimeReason.is_planned,
        )
        .join(OeeUnit, DowntimeEvent.oee_unit_id == OeeUnit.id)
        .join(Asset, OeeUnit.asset_id == Asset.id)
        .join(DowntimeReason, DowntimeEvent.reason_code == DowntimeReason.code)
    )


def _event_rows(rows: Sequence) -> list[DowntimeEventRow]:
    """The five-column event projection as dataclasses. One shape, one mapping."""
    return [
        DowntimeEventRow(
            event=event,
            asset_path=asset_path,
            display_name=display_name or event.reason_code,
            category=category,
            is_planned=bool(is_planned),
        )
        for event, asset_path, display_name, category, is_planned in rows
    ]


__all__ = [
    "MANUAL_REASON_SOURCE",
    "SINGLE_SHIFT_MARGIN",
    "DowntimeEventRow",
    "OeeResultRepository",
    "ParetoBucket",
    "ShiftResultRow",
    "pareto_from_rows",
]
