"""Reading Access Groups through the schema, with the repository replaced.

Non-admins are hidden from, not refused: empty list / null, no 403.
"""

from unittest.mock import AsyncMock, patch

import pytest
from uns_model.access_repository import AccessGroupRecord

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity
from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.queries.access_group._repository"

ADMIN = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000099",
        username="ada.admin",
        roles=frozenset({"admin"}),
    )
}
ENGINEER = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000002",
        username="erin.engineer",
        roles=frozenset({"engineer"}),
    )
}

LIST_QUERY = """
    { getAccessGroups { id name roots { assetId path segment level } subjects } }
"""
GET_QUERY = """
    query Get($id: Int64!) { getAccessGroup(id: $id) { id name } }
"""


def _group() -> AccessGroupRecord:
    return AccessGroupRecord(
        id=1,
        name="Filtration",
        root_asset_ids=(9,),
        root_paths=("AcmeWater/Site1/Filtration",),
        root_segments=("Filtration",),
        root_levels=("AREA",),
        subjects=("kc-1",),
    )


@pytest.mark.asyncio
async def test_admin_lists_access_groups():
    repository = AsyncMock()
    repository.list_groups.return_value = [_group()]
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(LIST_QUERY, context_value=ADMIN)

    assert result.errors is None
    assert result.data["getAccessGroups"] == [
        {
            "id": 1,
            "name": "Filtration",
            "roots": [
                {
                    "assetId": 9,
                    "path": "AcmeWater/Site1/Filtration",
                    "segment": "Filtration",
                    "level": "AREA",
                }
            ],
            "subjects": ["kc-1"],
        }
    ]


@pytest.mark.asyncio
async def test_engineer_lists_no_access_groups():
    repository = AsyncMock()
    repository.list_groups.return_value = [_group()]
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(LIST_QUERY, context_value=ENGINEER)

    assert result.errors is None
    assert result.data["getAccessGroups"] == []
    repository.list_groups.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_gets_one_access_group():
    repository = AsyncMock()
    repository.get_group.return_value = _group()
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            GET_QUERY, variable_values={"id": 1}, context_value=ADMIN
        )

    assert result.errors is None
    assert result.data["getAccessGroup"] == {"id": 1, "name": "Filtration"}
    repository.get_group.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_engineer_gets_null_access_group():
    repository = AsyncMock()
    repository.get_group.return_value = _group()
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            GET_QUERY, variable_values={"id": 1}, context_value=ENGINEER
        )

    assert result.errors is None
    assert result.data["getAccessGroup"] is None
    repository.get_group.assert_not_awaited()
