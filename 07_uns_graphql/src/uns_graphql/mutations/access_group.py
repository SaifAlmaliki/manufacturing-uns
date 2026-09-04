"""Admin writes for Access Groups.

Role each field needs is in auth/require.py, not in these resolvers. Repository
`ValueError` is raised as-is so Strawberry surfaces the message.
"""

from __future__ import annotations

import logging

import strawberry
from uns_model.access_repository import AccessGroupRepository
from uns_model.engine import Database

from uns_graphql.auth.require import require
from uns_graphql.type.access_group import AccessGroupType

LOGGER = logging.getLogger(__name__)


def _repository() -> AccessGroupRepository:
    return AccessGroupRepository(Database.shared("graphql"))


def _as_int(value: int | str | None) -> int | None:
    """Int64 parses to str; the repository wants an int. Same conversion as AlertRuleInput."""
    return None if value is None else int(value)


@strawberry.type(description="Author Access Groups: who may see which Asset subtree")
class Mutation:
    @strawberry.mutation(
        description="Create or replace one Access Group and return it as stored. "
        "Create when id is omitted. Fails with a readable message when the name is blank, "
        "already used, the root list is empty, or an Asset id does not exist."
    )
    async def save_access_group(
        self,
        info: strawberry.Info,
        name: str,
        root_asset_ids: list[int],
        id: int | None = None,  # noqa: A002
    ) -> AccessGroupType:
        require(info, "saveAccessGroup")
        saved = await _repository().save_group(
            _as_int(id),
            name,
            [int(asset_id) for asset_id in root_asset_ids],
        )
        LOGGER.info("Access Group %s saved as %s", saved.id, saved.name)
        return AccessGroupType.from_record(saved)

    @strawberry.mutation(description="Delete an Access Group. False when there was no such group.")
    async def delete_access_group(self, info: strawberry.Info, id: int) -> bool:  # noqa: A002
        require(info, "deleteAccessGroup")
        deleted = await _repository().delete_group(int(id))
        if deleted:
            LOGGER.info("Access Group %s deleted", id)
        return deleted

    @strawberry.mutation(
        description="Replace the members of an Access Group. An empty list is allowed: "
        "those people then see no plant data. Unknown id fails with a readable message."
    )
    async def set_access_group_members(
        self, info: strawberry.Info, id: int, subjects: list[str]  # noqa: A002
    ) -> AccessGroupType:
        require(info, "setAccessGroupMembers")
        saved = await _repository().set_members(int(id), subjects)
        LOGGER.info("Access Group %s members set (%s)", saved.id, len(saved.subjects))
        return AccessGroupType.from_record(saved)
