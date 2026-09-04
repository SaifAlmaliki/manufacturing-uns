"""GraphQL queries for Access Groups.

Admin-only reads: a non-admin caller gets an empty list or null, not a 403.
`require` is not used — these names are not in MUTATION_ROLES.
"""

from __future__ import annotations

import strawberry
from uns_model.access_repository import AccessGroupRepository
from uns_model.engine import Database

from uns_graphql.auth.context import identity_in
from uns_graphql.type.access_group import AccessGroupType


def _repository() -> AccessGroupRepository:
    return AccessGroupRepository(Database.shared("graphql"))


def _caller_is_admin(info: strawberry.Info) -> bool:
    identity = identity_in(getattr(info, "context", None))
    return identity is not None and identity.has_any({"admin"})


@strawberry.type(description="Query Access Groups: who may see which Asset subtree")
class Query:
    @strawberry.field(description="Every Access Group, name then id. Empty when the caller is not an admin.")
    async def get_access_groups(self, info: strawberry.Info) -> list[AccessGroupType]:
        if not _caller_is_admin(info):
            return []
        groups = await _repository().list_groups()
        return [AccessGroupType.from_record(group) for group in groups]

    @strawberry.field(description="One Access Group by id, or null when it is missing or the caller is not an admin.")
    async def get_access_group(self, info: strawberry.Info, id: int) -> AccessGroupType | None:  # noqa: A002
        if not _caller_is_admin(info):
            return None
        group = await _repository().get_group(int(id))
        return AccessGroupType.from_record(group) if group is not None else None
