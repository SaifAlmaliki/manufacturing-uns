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

The OEE vocabularies are written down twice: once as CHECK constraints in
`uns_model.oee_tables` and once as GraphQL enums. That is deliberate - a published
schema should not change shape because somebody edited a database constraint - and
these tests are what keeps the two copies honest.
"""

from datetime import UTC, datetime
from enum import Enum

import pytest
from uns_model.oee_results import DowntimeEventRow, ParetoBucket, ShiftResultRow
from uns_model.oee_tables import (
    OEE_STATUSES,
    REASON_SOURCES,
    DowntimeEvent,
    ShiftResult,
    ShiftResultProduct,
)

from uns_graphql.type.oee import (
    DowntimeEventType,
    DowntimeParetoBucket,
    OeeShiftResult,
    OeeStatus,
    ReasonSource,
)

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "graphql_enum, vocabulary",
    [
        (OeeStatus, OEE_STATUSES),
        (ReasonSource, REASON_SOURCES),
    ],
)
def test_enums_match_the_database_vocabulary(graphql_enum: type[Enum], vocabulary: tuple[str, ...]):
    """
    A value the database accepts must be expressible in the schema, and vice versa.

    Fails both ways round on purpose: an enum member the CHECK constraint rejects is a
    query that can never match, and a stored status with no enum member is a shift
    result the console cannot read back at all.
    """
    assert {member.value for member in graphql_enum} == set(vocabulary)


@pytest.mark.parametrize("vocabulary", [OEE_STATUSES, REASON_SOURCES])
def test_vocabularies_have_no_duplicates(vocabulary: tuple[str, ...]):
    """A duplicate would make the set comparison above pass while the CHECK body repeats itself."""
    assert len(vocabulary) == len(set(vocabulary))


def _result(**overrides) -> ShiftResult:
    values = {
        "id": 1,
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
        "performance_raw": 1.04,
        "quality": 0.96,
        "oee": 0.7344,
        "status": "OK",
        "revision": 2,
        "input_fingerprint": "1200:2026-08-31T14:00:00+00:00",
        "computed_at": datetime(2026, 8, 31, 14, 20, tzinfo=UTC),
        "published_at": datetime(2026, 8, 31, 14, 20, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return ShiftResult(**values)


def _event(**overrides) -> DowntimeEvent:
    values = {
        "id": 11,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "MECH_FAULT",
        "reason_source": "manual",
        "assigned_by": "a.operator",
        "assigned_at": datetime(2026, 8, 31, 15, 0, tzinfo=UTC),
        "note": "Gearbox seized",
    }
    values.update(overrides)
    return DowntimeEvent(**values)


def test_from_row_maps_every_shift_result_field():
    row = ShiftResultRow(result=_result(), asset_path=LINE, products=())

    result = OeeShiftResult.from_row(row)

    assert result.asset_path == LINE
    assert result.shift_start == SHIFT_START
    assert result.shift_end == SHIFT_END
    assert result.shift_label == "Morning"
    assert result.loading_time_s == pytest.approx(27000.0)
    assert result.run_time_s == pytest.approx(24300.0)
    assert result.planned_down_s == pytest.approx(1800.0)
    assert result.unplanned_down_s == pytest.approx(2700.0)
    assert result.good_count == pytest.approx(4800.0)
    assert result.reject_count == pytest.approx(200.0)
    assert result.total_count == pytest.approx(5000.0)
    assert result.availability == pytest.approx(0.9)
    assert result.performance == pytest.approx(0.85)
    assert result.performance_raw == pytest.approx(1.04)
    assert result.quality == pytest.approx(0.96)
    assert result.oee == pytest.approx(0.7344)
    assert result.status is OeeStatus.OK
    assert result.revision == 2
    assert result.computed_at == row.result.computed_at
    assert result.published_at == row.result.published_at


def test_a_null_factor_stays_null():
    """
    Spec section 8.1: a shift with no Loading Time has no Availability. Rendering it as
    0.0 would put a catastrophic shift on the trend that never happened.
    """
    row = ShiftResultRow(
        result=_result(status="NO_LOADING_TIME", availability=None, performance=None, quality=None, oee=None),
        asset_path=LINE,
    )

    result = OeeShiftResult.from_row(row)

    assert (result.availability, result.performance, result.quality, result.oee) == (None, None, None, None)
    assert result.status is OeeStatus.NO_LOADING_TIME


def test_the_per_product_terms_are_carried_through():
    """Performance is a sum over products, so a mixed shift's terms have to be readable."""
    row = ShiftResultRow(
        result=_result(),
        asset_path=LINE,
        products=(
            ShiftResultProduct(
                id=1,
                shift_result_id=1,
                product_code="MDI-01",
                good_count=2900.0,
                reject_count=100.0,
                total_count=3000.0,
                ideal_cycle_time_s=4.0,
            ),
            ShiftResultProduct(
                id=2,
                shift_result_id=1,
                product_code="MDI-02",
                good_count=1900.0,
                reject_count=100.0,
                total_count=2000.0,
                ideal_cycle_time_s=None,
            ),
        ),
    )

    products = OeeShiftResult.from_row(row).products

    assert [product.product_code for product in products] == ["MDI-01", "MDI-02"]
    assert products[0].ideal_cycle_time_s == pytest.approx(4.0)
    assert products[1].ideal_cycle_time_s is None


def test_a_single_product_line_has_an_empty_product_list():
    """Not null: the console iterates it, and a null list is an extra branch for no reason."""
    assert OeeShiftResult.from_row(ShiftResultRow(result=_result(), asset_path=LINE)).products == []


def test_downtime_event_from_row_carries_the_resolved_reason():
    row = DowntimeEventRow(
        event=_event(),
        asset_path=LINE,
        display_name="Mechanical fault",
        category="FAILURE",
        is_planned=False,
    )

    event = DowntimeEventType.from_row(row)

    assert event.id == "11"
    assert event.asset_path == LINE
    assert event.shift_start == SHIFT_START
    assert event.started_at == row.event.started_at
    assert event.ended_at == row.event.ended_at
    assert event.duration_s == pytest.approx(2700.0)
    assert event.state_value == "ABORTED"
    assert event.reason_code == "MECH_FAULT"
    assert event.reason_display_name == "Mechanical fault"
    assert event.reason_category == "FAILURE"
    assert event.is_planned is False
    assert event.reason_source is ReasonSource.MANUAL
    assert event.assigned_by == "a.operator"
    assert event.assigned_at == row.event.assigned_at
    assert event.note == "Gearbox seized"


def test_an_auto_classified_event_has_no_assignee():
    row = DowntimeEventRow(
        event=_event(reason_code="UNCLASSIFIED", reason_source="auto", assigned_by=None, assigned_at=None, note=""),
        asset_path=LINE,
        display_name="Unclassified",
        category="",
        is_planned=False,
    )

    event = DowntimeEventType.from_row(row)

    assert event.reason_source is ReasonSource.AUTO
    assert event.assigned_by is None
    assert event.assigned_at is None


def test_pareto_bucket_from_bucket():
    bucket = ParetoBucket("MECH_FAULT", "Mechanical fault", "FAILURE", False, 5, 5400.0, 0.6)

    published = DowntimeParetoBucket.from_bucket(bucket)

    assert published.reason_code == "MECH_FAULT"
    assert published.display_name == "Mechanical fault"
    assert published.category == "FAILURE"
    assert published.is_planned is False
    assert published.event_count == 5
    assert published.total_seconds == pytest.approx(5400.0)
    assert published.share == pytest.approx(0.6)
