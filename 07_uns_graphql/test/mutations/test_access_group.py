"""Access Group mutations through the schema, with the repository replaced."""

from unittest.mock import AsyncMock, patch

import pytest
from uns_model.access_repository import AccessGroupRecord

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.require import NotPermittedError
from uns_graphql.auth.token import Identity
from uns_graphql.mutations.access_group import Mutation as AccessGroupMutation
from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.mutations.access_group._repository"

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

SAVE_MUTATION = """
    mutation Save($name: String!, $rootAssetIds: [Int64!]!, $id: Int64) {
        saveAccessGroup(name: $name, rootAssetIds: $rootAssetIds, id: $id) {
            id name roots { assetId path segment level } subjects
        }
    }
"""


def _group(
    group_id: int = 1,
    name: str = "Filtration",
    *,
    asset_id: int = 9,
    path: str = "AcmeWater/Site1/Filtration",
    segment: str = "Filtration",
    level: str = "AREA",
    subjects: tuple[str, ...] = (),
) -> AccessGroupRecord:
    return AccessGroupRecord(
        id=group_id,
        name=name,
        root_asset_ids=(asset_id,),
        root_paths=(path,),
        root_segments=(segment,),
        root_levels=(level,),
        subjects=subjects,
    )


@pytest.mark.asyncio
async def test_save_access_group_exists():
    result = await UNSGraphql.schema.execute(
        'mutation { saveAccessGroup(name: "X", rootAssetIds: [1]) { id name } }'
    )
    messages = [e.message for e in (result.errors or [])]
    assert not any("Cannot query field" in m for m in messages)


@pytest.mark.asyncio
async def test_admin_can_save_access_group():
    repository = AsyncMock()
    repository.save_group.return_value = _group()
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION,
            variable_values={"name": "Filtration", "rootAssetIds": [9]},
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveAccessGroup"] == {
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
        "subjects": [],
    }
    repository.save_group.assert_awaited_once_with(None, "Filtration", [9])


@pytest.mark.asyncio
async def test_engineer_cannot_save_access_group():
    repository = AsyncMock()
    with (
        patch(REPOSITORY, return_value=repository),
        pytest.raises(NotPermittedError, match="saveAccessGroup"),
    ):
        await AccessGroupMutation().save_access_group(
            type("Info", (), {"context": ENGINEER})(),
            name="Filtration",
            root_asset_ids=[9],
        )
    repository.save_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_engineer_save_access_group_is_refused_on_the_schema():
    repository = AsyncMock()
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION,
            variable_values={"name": "Filtration", "rootAssetIds": [9]},
            context_value=ENGINEER,
        )

    assert result.errors
    assert any("saveAccessGroup" in (error.message or "") for error in result.errors)
    repository.save_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_roots_valueerror_reaches_the_result_errors():
    repository = AsyncMock()
    repository.save_group.side_effect = ValueError("An Access Group needs at least one root Asset.")
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION,
            variable_values={"name": "Filtration", "rootAssetIds": []},
            context_value=ADMIN,
        )

    messages = [error.message for error in (result.errors or [])]
    assert any("at least one root" in message for message in messages)


@pytest.mark.asyncio
async def test_admin_can_delete_access_group():
    repository = AsyncMock()
    repository.delete_group.return_value = True
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "mutation { deleteAccessGroup(id: 1) }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["deleteAccessGroup"] is True
    repository.delete_group.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_engineer_cannot_delete_access_group():
    repository = AsyncMock()
    with (
        patch(REPOSITORY, return_value=repository),
        pytest.raises(NotPermittedError, match="deleteAccessGroup"),
    ):
        await AccessGroupMutation().delete_access_group(
            type("Info", (), {"context": ENGINEER})(),
            id=1,
        )
    repository.delete_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_can_set_access_group_members():
    repository = AsyncMock()
    repository.set_members.return_value = _group(subjects=("kc-1",))
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "mutation { setAccessGroupMembers(id: 1, subjects: [\"kc-1\"]) { id subjects } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["setAccessGroupMembers"] == {"id": 1, "subjects": ["kc-1"]}
    repository.set_members.assert_awaited_once_with(1, ["kc-1"])


@pytest.mark.asyncio
async def test_engineer_cannot_set_access_group_members():
    repository = AsyncMock()
    with (
        patch(REPOSITORY, return_value=repository),
        pytest.raises(NotPermittedError, match="setAccessGroupMembers"),
    ):
        await AccessGroupMutation().set_access_group_members(
            type("Info", (), {"context": ENGINEER})(),
            id=1,
            subjects=["kc-1"],
        )
    repository.set_members.assert_not_awaited()
