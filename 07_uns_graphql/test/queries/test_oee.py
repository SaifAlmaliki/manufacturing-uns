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

Reading OEE results through the schema, with the repository replaced.

Executed against the real schema rather than by calling the resolvers, because the
schema is what a dashboard talks to: an argument renamed here is a broken dashboard
even though every resolver still passes its own test. What the repository does with a
live Postgres is `09_uns_model`'s integration test's job.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uns_model.oee_results import DowntimeEventRow, ParetoBucket, ShiftResultRow
from uns_model.oee_tables import DowntimeEvent, ShiftResult

from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.queries.oee._repository"

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def _result_row(**overrides) -> ShiftResultRow:
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
        "performance_raw": 0.85,
        "quality": 0.96,
        "oee": 0.7344,
        "status": "OK",
        "revision": 1,
        "input_fingerprint": "",
        "computed_at": datetime(2026, 8, 31, 14, 20, tzinfo=UTC),
        "published_at": None,
    }
    values.update(overrides)
    return ShiftResultRow(result=ShiftResult(**values), asset_path=LINE)


def _event_row(**overrides) -> DowntimeEventRow:
    values = {
        "id": 11,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "MECH_FAULT",
        "reason_source": "auto",
        "assigned_by": None,
        "assigned_at": None,
        "note": "",
    }
    values.update(overrides)
    return DowntimeEventRow(
        event=DowntimeEvent(**values),
        asset_path=LINE,
        display_name="Mechanical fault",
        category="FAILURE",
        is_planned=False,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_the_range_arguments_are_named_from_and_to():
    """
    Spec section 10 writes the signature down. Asserted by introspection rather than
    against printed SDL, so a Strawberry upgrade that reformats the schema cannot
    break a test that is about the contract.
    """
    result = await UNSGraphql.schema.execute("""{ __type(name: "Query") { fields { name args { name } } } }""")

    assert result.errors is None
    arguments = {field["name"]: [arg["name"] for arg in field["args"]] for field in result.data["__type"]["fields"]}
    assert arguments["oeeShiftResults"] == ["assetPath", "from", "to"]
    assert arguments["downtimeEvents"] == ["assetPath", "from", "to"]
    assert arguments["downtimePareto"] == ["assetPath", "from", "to"]


@pytest.mark.asyncio(loop_scope="function")
async def test_oee_shift_results_returns_what_the_repository_holds():
    repository = AsyncMock()
    repository.shift_results.return_value = [_result_row()]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                assetPath shiftLabel availability performance quality oee status revision publishedAt
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert result.data["oeeShiftResults"] == [
        {
            "assetPath": LINE,
            "shiftLabel": "Morning",
            "availability": pytest.approx(0.9),
            "performance": pytest.approx(0.85),
            "quality": pytest.approx(0.96),
            "oee": pytest.approx(0.7344),
            "status": "OK",
            "revision": 1,
            "publishedAt": None,
        }
    ]


@pytest.mark.asyncio(loop_scope="function")
async def test_oee_shift_results_passes_the_parsed_range_through():
    repository = AsyncMock()
    repository.shift_results.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                shiftLabel
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    repository.shift_results.assert_awaited_once_with(
        LINE, SHIFT_START, datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_a_null_factor_is_null_in_the_response():
    """A shift with no Loading Time must not arrive at the dashboard as 0%."""
    repository = AsyncMock()
    repository.shift_results.return_value = [
        _result_row(status="NO_LOADING_TIME", availability=None, performance=None, quality=None, oee=None)
    ]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                status availability oee
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert result.data["oeeShiftResults"][0] == {
        "status": "NO_LOADING_TIME",
        "availability": None,
        "oee": None,
    }


@pytest.mark.asyncio(loop_scope="function")
async def test_an_asset_with_no_results_is_an_empty_list():
    """Not an error: a line whose first shift has not closed yet is normal."""
    repository = AsyncMock()
    repository.shift_results.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "nope", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                oee
              }
            }
            """
        )

    assert result.errors is None
    assert result.data["oeeShiftResults"] == []


@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_events_expose_the_resolved_reason():
    repository = AsyncMock()
    repository.downtime_events.return_value = [_event_row()]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              downtimeEvents(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-08-31T14:00:00+00:00") {
                id durationS stateValue reasonCode reasonDisplayName reasonCategory isPlanned reasonSource note
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert result.data["downtimeEvents"] == [
        {
            "id": "11",
            "durationS": pytest.approx(2700.0),
            "stateValue": "ABORTED",
            "reasonCode": "MECH_FAULT",
            "reasonDisplayName": "Mechanical fault",
            "reasonCategory": "FAILURE",
            "isPlanned": False,
            "reasonSource": "AUTO",
            "note": "",
        }
    ]
    repository.downtime_events.assert_awaited_once_with(LINE, SHIFT_START, SHIFT_END)


@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_pareto_returns_the_buckets_in_order():
    repository = AsyncMock()
    repository.downtime_pareto.return_value = [
        ParetoBucket("MECH_FAULT", "Mechanical fault", "FAILURE", False, 5, 5400.0, 0.6),
        ParetoBucket("CHANGEOVER", "Changeover", "PLANNED", True, 2, 3600.0, 0.4),
    ]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              downtimePareto(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-08-31T14:00:00+00:00") {
                reasonCode displayName isPlanned eventCount totalSeconds share
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert [bucket["reasonCode"] for bucket in result.data["downtimePareto"]] == ["MECH_FAULT", "CHANGEOVER"]
    assert result.data["downtimePareto"][0]["eventCount"] == 5
    assert result.data["downtimePareto"][0]["share"] == pytest.approx(0.6)
    assert result.data["downtimePareto"][1]["isPlanned"] is True
