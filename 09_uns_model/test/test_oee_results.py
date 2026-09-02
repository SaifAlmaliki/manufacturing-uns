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

What the OEE result reads return, and what a reason assignment writes.

The Pareto arithmetic is tested as a pure function, because that is the one piece of
this file that decides a number rather than a row. The repository methods are tested
against a scripted session: what matters here is that the right statements are built in
the right order and that their rows land on the right dataclass fields. Whether the SQL
is valid against a real TimescaleDB is `test_integration.py`'s job.
"""

from __future__ import annotations

from collections import namedtuple
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from uns_model.oee_results import (
    MANUAL_REASON_SOURCE,
    SINGLE_SHIFT_MARGIN,
    DowntimeEventRow,
    OeeResultRepository,
    ParetoBucket,
    pareto_from_rows,
)
from uns_model.oee_tables import REASON_SOURCES, DowntimeEvent, ShiftResult, ShiftResultProduct

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def row(**fields):
    """A stand-in for a SQLAlchemy `Row`: attribute access and tuple unpacking both work."""
    return namedtuple("Row", fields)(**fields)


class FakeResult:
    """One scripted result. `all`, `first` and `one_or_none` read the same rows."""

    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        if len(self._rows) > 1:
            raise AssertionError("one_or_none over more than one row")
        return self._rows[0] if self._rows else None


class FakeSession:
    """Hands back scripted results in order and keeps every statement it was given."""

    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    async def scalars(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


class FakeDatabase:
    def __init__(self, results=()):
        self.session_obj = FakeSession(results)

    @asynccontextmanager
    async def session(self):
        yield self.session_obj


def sql(statement) -> str:
    return str(statement)


def bound(statement) -> dict:
    """The literal values a statement carries, so an INSERT can be asserted on."""
    return statement.compile().params


def _result(result_id: int = 1, **overrides) -> ShiftResult:
    values = {
        "id": result_id,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "shift_end": SHIFT_END,
        "shift_label": "Morning",
        "loading_time_s": 27000.0,
        "run_time_s": 24300.0,
        "planned_down_s": 1800.0,
        "unplanned_down_s": 2700.0,
        "good_count": 4800.0,
        "reject_count": 200.0,
        "total_count": 5000.0,
        "availability": 0.9,
        "performance": 0.85,
        "performance_raw": 0.85,
        "quality": 0.96,
        "oee": 0.7344,
        "status": "OK",
        "revision": 1,
        "input_fingerprint": "1200:2026-08-31T14:00:00+00:00",
        "computed_at": datetime(2026, 8, 31, 14, 20, tzinfo=UTC),
        "published_at": datetime(2026, 8, 31, 14, 20, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return ShiftResult(**values)


def _event(event_id: int = 11, **overrides) -> DowntimeEvent:
    values = {
        "id": event_id,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "UNCLASSIFIED",
        "reason_source": "auto",
        "assigned_by": None,
        "assigned_at": None,
        "note": "",
    }
    values.update(overrides)
    return DowntimeEvent(**values)


# --------------------------------------------------------------------- the Pareto


def test_manual_reason_source_is_in_the_database_vocabulary():
    """A constant the CHECK constraint rejects would fail on every assignment, at runtime."""
    assert MANUAL_REASON_SOURCE in REASON_SOURCES


def test_pareto_orders_by_lost_time_descending():
    """A Pareto chart *is* the ordering. Unsorted buckets are just a table."""
    buckets = pareto_from_rows(
        [
            ("CHANGEOVER", "Changeover", "PLANNED", True, 2, 1800.0),
            ("MECH_FAULT", "Mechanical fault", "FAILURE", False, 5, 5400.0),
            ("NO_FEED", "No feedstock", "SUPPLY", False, 1, 3600.0),
        ]
    )

    assert [bucket.reason_code for bucket in buckets] == ["MECH_FAULT", "NO_FEED", "CHANGEOVER"]
    assert buckets[0].event_count == 5
    assert buckets[0].total_seconds == pytest.approx(5400.0)


def test_pareto_breaks_ties_on_the_reason_code():
    """Two reasons with the same lost time must not swap places between refreshes."""
    buckets = pareto_from_rows(
        [
            ("NO_FEED", "No feedstock", "SUPPLY", False, 1, 600.0),
            ("CHANGEOVER", "Changeover", "PLANNED", True, 1, 600.0),
        ]
    )

    assert [bucket.reason_code for bucket in buckets] == ["CHANGEOVER", "NO_FEED"]


def test_pareto_shares_sum_to_one():
    """Spec section 10: a Pareto must always account for all of the downtime."""
    buckets = pareto_from_rows(
        [
            ("MECH_FAULT", "Mechanical fault", "FAILURE", False, 3, 3000.0),
            ("NO_FEED", "No feedstock", "SUPPLY", False, 2, 1000.0),
        ]
    )

    assert buckets[0].share == pytest.approx(0.75)
    assert buckets[1].share == pytest.approx(0.25)
    assert sum(bucket.share for bucket in buckets) == pytest.approx(1.0)


def test_pareto_of_zero_total_downtime_reports_zero_shares():
    """Stops of no measurable length are not a division by zero."""
    buckets = pareto_from_rows([("CHANGEOVER", "Changeover", "PLANNED", True, 1, 0.0)])

    assert buckets[0].share == 0.0


def test_pareto_of_an_empty_window_is_empty():
    assert pareto_from_rows([]) == []


def test_pareto_falls_back_to_the_code_when_a_reason_has_no_display_name():
    """`display_name` defaults to '' in the table, and a nameless bar is unreadable."""
    buckets = pareto_from_rows([("MECH_FAULT", "", "FAILURE", False, 1, 60.0)])

    assert buckets[0].display_name == "MECH_FAULT"


def test_pareto_buckets_compare_by_value():
    """A frozen dataclass, so a test can assert on a whole bucket."""
    bucket = ParetoBucket(
        reason_code="NO_FEED",
        display_name="No feedstock",
        category="SUPPLY",
        is_planned=False,
        event_count=1,
        total_seconds=60.0,
        share=1.0,
    )

    assert bucket == ParetoBucket("NO_FEED", "No feedstock", "SUPPLY", False, 1, 60.0, 1.0)


# ---------------------------------------------------------------------- the reads


@pytest.mark.asyncio
async def test_shift_results_maps_rows_and_groups_products():
    database = FakeDatabase(
        [
            FakeResult(
                [
                    row(ShiftResult=_result(1), path=LINE),
                    row(ShiftResult=_result(2, shift_start=SHIFT_END), path=LINE),
                ]
            ),
            FakeResult(
                [
                    ShiftResultProduct(id=1, shift_result_id=1, product_code="MDI-01", total_count=3000.0),
                    ShiftResultProduct(id=2, shift_result_id=1, product_code="MDI-02", total_count=2000.0),
                    ShiftResultProduct(id=3, shift_result_id=2, product_code="MDI-01", total_count=1000.0),
                ]
            ),
        ]
    )

    rows = await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END + timedelta(hours=8))

    assert [item.result.id for item in rows] == [1, 2]
    assert [item.asset_path for item in rows] == [LINE, LINE]
    assert [product.product_code for product in rows[0].products] == ["MDI-01", "MDI-02"]
    assert [product.product_code for product in rows[1].products] == ["MDI-01"]


@pytest.mark.asyncio
async def test_a_shift_result_with_no_products_gets_an_empty_tuple():
    """A single-product line publishes no recipe, so `shift_result_product` stays empty."""
    database = FakeDatabase([FakeResult([row(ShiftResult=_result(1), path=LINE)]), FakeResult([])])

    rows = await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END)

    assert rows[0].products == ()


@pytest.mark.asyncio
async def test_shift_results_filters_on_a_half_open_range():
    database = FakeDatabase([FakeResult([]), FakeResult([])])

    await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END)

    statement = sql(database.session_obj.statements[0])
    assert "shift_result.shift_start >= " in statement
    assert "shift_result.shift_start < " in statement
    assert "asset.path = " in statement


@pytest.mark.asyncio
async def test_shift_results_does_not_query_products_when_there_are_no_results():
    """One round trip, not two, for the common case of a line with no shifts in range."""
    database = FakeDatabase([FakeResult([])])

    rows = await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END)

    assert rows == []
    assert len(database.session_obj.statements) == 1


@pytest.mark.asyncio
async def test_downtime_events_carry_the_joined_reason():
    """The console needs `isPlanned` to explain why a reassignment moved the OEE."""
    database = FakeDatabase(
        [
            FakeResult(
                [
                    row(
                        DowntimeEvent=_event(11),
                        path=LINE,
                        display_name="Mechanical fault",
                        category="FAILURE",
                        is_planned=False,
                    )
                ]
            )
        ]
    )

    rows = await OeeResultRepository(database).downtime_events(LINE, SHIFT_START, SHIFT_END)

    assert len(rows) == 1
    assert rows[0] == DowntimeEventRow(
        event=rows[0].event,
        asset_path=LINE,
        display_name="Mechanical fault",
        category="FAILURE",
        is_planned=False,
    )
    assert rows[0].event.id == 11
    assert "downtime_event.started_at >= " in sql(database.session_obj.statements[0])


@pytest.mark.asyncio
async def test_downtime_pareto_aggregates_in_the_database():
    """Grouped in SQL: a year of stops is thousands of rows and the console wants nine."""
    database = FakeDatabase(
        [
            FakeResult(
                [
                    row(
                        reason_code="NO_FEED",
                        display_name="No feedstock",
                        category="SUPPLY",
                        is_planned=False,
                        event_count=2,
                        total_seconds=1200.0,
                    )
                ]
            )
        ]
    )

    buckets = await OeeResultRepository(database).downtime_pareto(LINE, SHIFT_START, SHIFT_END)

    assert buckets == [ParetoBucket("NO_FEED", "No feedstock", "SUPPLY", False, 2, 1200.0, 1.0)]
    statement = sql(database.session_obj.statements[0]).upper()
    assert "GROUP BY" in statement
    assert "COUNT(" in statement
    assert "SUM(" in statement


# ---------------------------------------------------------------------- the write


def _assignment_database(existing_note: str = "") -> FakeDatabase:
    """The four results `assign_reason` consumes: reason check, update, insert, re-read."""
    return FakeDatabase(
        [
            FakeResult(["MECH_FAULT"]),
            FakeResult([row(oee_unit_id=7, shift_start=SHIFT_START)]),
            FakeResult([]),
            FakeResult(
                [
                    row(
                        DowntimeEvent=_event(
                            11,
                            reason_code="MECH_FAULT",
                            reason_source="manual",
                            assigned_by="a.operator",
                            assigned_at=datetime(2026, 8, 31, 15, 0, tzinfo=UTC),
                            note=existing_note,
                        ),
                        path=LINE,
                        display_name="Mechanical fault",
                        category="FAILURE",
                        is_planned=False,
                    )
                ]
            ),
        ]
    )


@pytest.mark.asyncio
async def test_assign_reason_marks_the_row_manual():
    database = _assignment_database()

    assigned = await OeeResultRepository(database).assign_reason(
        11, "MECH_FAULT", note="Gearbox seized", assigned_by="a.operator"
    )

    assert assigned is not None
    assert assigned.event.reason_source == MANUAL_REASON_SOURCE
    assert assigned.display_name == "Mechanical fault"
    changed = bound(database.session_obj.statements[1])
    assert changed["reason_code"] == "MECH_FAULT"
    assert changed["reason_source"] == MANUAL_REASON_SOURCE
    assert changed["assigned_by"] == "a.operator"
    assert changed["note"] == "Gearbox seized"


@pytest.mark.asyncio
async def test_assign_reason_enqueues_a_recompute_for_that_one_shift():
    """
    Spec section 10: a reason's `is_planned` flag moves the interval between Unplanned Down
    and excluded time, so the number changes. The range is one second wide because
    `shift_windows` selects on `[from, to)` over the shift's *start*.
    """
    database = _assignment_database()

    await OeeResultRepository(database).assign_reason(11, "MECH_FAULT", assigned_by="a.operator")

    enqueued = bound(database.session_obj.statements[2])
    assert enqueued["oee_unit_id"] == 7
    assert enqueued["range_start"] == SHIFT_START
    assert enqueued["range_end"] == SHIFT_START + SINGLE_SHIFT_MARGIN
    assert enqueued["requested_by"] == "a.operator"
    assert "11" in enqueued["reason"]


@pytest.mark.asyncio
async def test_assign_reason_without_a_note_leaves_the_stored_note_alone():
    """An operator correcting only the code must not erase what somebody else typed."""
    database = _assignment_database(existing_note="Called maintenance at 09:05")

    assigned = await OeeResultRepository(database).assign_reason(11, "MECH_FAULT", assigned_by="a.operator")

    assert "note" not in bound(database.session_obj.statements[1])
    assert assigned.event.note == "Called maintenance at 09:05"


@pytest.mark.asyncio
async def test_assign_reason_is_null_for_an_unknown_event():
    """Null, not an error: acting on a list a recomputation has since replaced is normal."""
    database = FakeDatabase([FakeResult(["MECH_FAULT"]), FakeResult([])])

    assert await OeeResultRepository(database).assign_reason(999, "MECH_FAULT") is None
    assert len(database.session_obj.statements) == 2


@pytest.mark.asyncio
async def test_assign_reason_rejects_a_reason_code_nobody_authored():
    """
    A readable sentence instead of a driver-level foreign key violation naming a generated
    constraint - the same reason `AlertRuleSpec.validate` duplicates its CHECK constraints.
    """
    database = FakeDatabase([FakeResult([])])

    with pytest.raises(ValueError, match="NOT_A_REASON"):
        await OeeResultRepository(database).assign_reason(11, "NOT_A_REASON")

    assert len(database.session_obj.statements) == 1
