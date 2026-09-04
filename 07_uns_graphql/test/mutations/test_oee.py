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

Correcting a downtime reason through the schema, with the repository replaced.

This is the second write this service has ever exposed, and the only one that touches
plant data. The tests pin down what it is allowed to be: it corrects an attribution and
queues a recomputation. It must never become a way to edit an OEE number directly.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uns_model.oee_results import DowntimeEventRow
from uns_model.oee_tables import DowntimeEvent

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.scope import AccessScope
from uns_graphql.auth.token import Identity
from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.mutations.oee._repository"


@pytest.fixture(autouse=True)
def _any_plant_path():
    """These tests are about the mutation, not Access Groups; Task 6 covers refusal."""
    with patch(
        "uns_graphql.auth.require.scope_for",
        AsyncMock(return_value=AccessScope(unrestricted=True, root_paths=frozenset())),
    ):
        yield


# These tests are about what the mutation does, not about who may call it - that is
# test/auth/test_require.py, one case per cell. Operator, because that is the role that
# reassigns a stop reason in a plant, so the test exercises the row's lower bound.
OPERATOR = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000002",
        username="olga.operator",
        roles=frozenset({"operator"}),
    )
}

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)

ASSIGN = """
    mutation Assign($eventId: ID!, $reasonCode: String!, $note: String) {
        assignDowntimeReason(eventId: $eventId, reasonCode: $reasonCode, note: $note) {
            id reasonCode reasonSource isPlanned assignedBy note
        }
    }
"""


def _assigned(**overrides) -> DowntimeEventRow:
    values = {
        "id": 11,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "CHANGEOVER",
        "reason_source": "manual",
        "assigned_by": "a.operator",
        "assigned_at": datetime(2026, 8, 31, 15, 0, tzinfo=UTC),
        "note": "Product change to MDI-02",
    }
    values.update(overrides)
    return DowntimeEventRow(
        event=DowntimeEvent(**values),
        asset_path=LINE,
        display_name="Changeover",
        category="PLANNED",
        is_planned=True,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_assign_downtime_reason_records_the_signed_in_user():
    """
    Spec success criterion 4: "a downtime reason reassignment records an identity the caller
    did not choose". The caller cannot supply a name, so the name in the row is the name in
    the token.
    """
    repository = AsyncMock()
    repository.get_downtime_event.return_value = _assigned(assigned_by="olga.operator")
    repository.assign_reason.return_value = _assigned(assigned_by="olga.operator")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={
                "eventId": "11",
                "reasonCode": "CHANGEOVER",
                "note": "Product change to MDI-02",
            },
            context_value=OPERATOR,
        )

    assert result.errors is None
    assert result.data["assignDowntimeReason"] == {
        "id": "11",
        "reasonCode": "CHANGEOVER",
        "reasonSource": "MANUAL",
        "isPlanned": True,
        "assignedBy": "olga.operator",
        "note": "Product change to MDI-02",
    }
    repository.assign_reason.assert_awaited_once_with(
        11, "CHANGEOVER", note="Product change to MDI-02", assigned_by="olga.operator"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_the_event_id_reaches_the_repository_as_a_number():
    """The schema publishes ID, which is a string. The primary key is a BIGINT."""
    repository = AsyncMock()
    repository.get_downtime_event.return_value = _assigned()
    repository.assign_reason.return_value = _assigned()

    with patch(REPOSITORY, return_value=repository):
        await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={"eventId": "11", "reasonCode": "CHANGEOVER"},
            context_value=OPERATOR,
        )

    assert repository.assign_reason.await_args.args == (11, "CHANGEOVER")


@pytest.mark.asyncio(loop_scope="function")
async def test_omitting_the_note_leaves_the_stored_note_alone():
    """
    None rather than '': the repository omits the column entirely when the note is
    None, so an operator correcting only the code cannot erase somebody else's note.
    """
    repository = AsyncMock()
    repository.get_downtime_event.return_value = _assigned(note="Called maintenance at 09:05")
    repository.assign_reason.return_value = _assigned(note="Called maintenance at 09:05")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={"eventId": "11", "reasonCode": "CHANGEOVER"},
            context_value=OPERATOR,
        )

    assert result.errors is None
    assert repository.assign_reason.await_args.kwargs == {
        "note": None,
        "assigned_by": "olga.operator",
    }
    assert result.data["assignDowntimeReason"]["note"] == "Called maintenance at 09:05"


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unknown_event_is_an_error_and_not_a_null():
    """The return type is non-null, and an operator whose click did nothing must be told."""
    repository = AsyncMock()
    repository.get_downtime_event.return_value = None

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={"eventId": "999", "reasonCode": "CHANGEOVER"},
            context_value=OPERATOR,
        )

    assert result.errors
    assert "999" in result.errors[0].message
    repository.assign_reason.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unauthored_reason_code_reaches_the_caller_as_a_message():
    """The repository's ValueError, not a driver-level foreign key violation."""
    repository = AsyncMock()
    repository.get_downtime_event.return_value = _assigned()
    repository.assign_reason.side_effect = ValueError("'NOT_A_REASON' is not an authored downtime reason code")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={"eventId": "11", "reasonCode": "NOT_A_REASON"},
            context_value=OPERATOR,
        )

    assert result.errors
    assert "NOT_A_REASON" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_an_event_id_that_is_not_a_number_is_rejected_before_the_database():
    repository = AsyncMock()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={"eventId": "eleven", "reasonCode": "CHANGEOVER"},
            context_value=OPERATOR,
        )

    assert result.errors
    assert "eleven" in result.errors[0].message
    repository.get_downtime_event.assert_not_awaited()
    repository.assign_reason.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_the_schema_exposes_no_other_way_to_write_to_the_oee_schema():
    """
    A shift result is computed, never edited. If a second OEE mutation ever appears,
    this test is the place that argues about it.
    """
    result = await UNSGraphql.schema.execute("""{ __type(name: "Mutation") { fields { name } } }""")

    assert result.errors is None
    names = [field["name"] for field in result.data["__type"]["fields"]]
    assert [name for name in names if "owntime" in name or "Oee" in name or "oee" in name] == [
        "assignDowntimeReason"
    ]


@pytest.mark.asyncio(loop_scope="function")
async def test_supplying_an_identity_is_a_schema_error():
    """
    Spec test 5: "a request that tries to supply assignedBy fails schema validation because
    the argument no longer exists". A caller who could name themselves could name anybody, and
    the argument's own description used to admit as much.
    """
    result = await UNSGraphql.schema.execute(
        """
        mutation {
            assignDowntimeReason(eventId: "11", reasonCode: "CHANGEOVER",
                                 assignedBy: "somebody.else") { id }
        }
        """,
        context_value=OPERATOR,
    )

    assert result.errors
    assert "assignedBy" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_the_schema_publishes_no_way_to_name_the_assigner():
    result = await UNSGraphql.schema.execute(
        """{ __type(name: "Mutation") { fields { name args { name } } } }"""
    )

    assert result.errors is None
    field = next(
        f for f in result.data["__type"]["fields"] if f["name"] == "assignDowntimeReason"
    )
    assert [arg["name"] for arg in field["args"]] == ["eventId", "reasonCode", "note"]
