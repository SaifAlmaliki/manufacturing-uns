"""The caller's view of the Asset tree.

One scope per request. Admin is unrestricted; everyone else is the union of
Access Group root paths they belong to. `covers_path` is the model `covers`
rule so GraphQL and the repository cannot drift.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from uns_model.access import covers
from uns_model.access_repository import AccessGroupRepository
from uns_model.engine import Database

from uns_graphql.auth.context import identity_in
from uns_graphql.auth.token import Identity

_RootsFor = Callable[[str], Awaitable[frozenset[str]]]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class AccessScope:
    unrestricted: bool
    root_paths: frozenset[str]

    def covers_path(self, path: str) -> bool:
        if self.unrestricted:
            return True
        return any(covers(path, root) for root in self.root_paths)


async def scope_for(identity: Identity | None, *, roots_for: _RootsFor | None = None) -> AccessScope:
    if identity is None:
        return AccessScope(unrestricted=False, root_paths=frozenset())
    if identity.has_any({"admin"}):
        return AccessScope(unrestricted=True, root_paths=frozenset())
    if roots_for is None:
        roots_for = AccessGroupRepository(Database.shared("graphql")).root_paths_for_subject
    return AccessScope(unrestricted=False, root_paths=await roots_for(identity.subject))


def visible_topic(scope: AccessScope, bound_asset_path: str | None) -> bool:
    if scope.unrestricted:
        return True
    if bound_asset_path is None:
        return False
    return scope.covers_path(bound_asset_path)


async def scope_from_info(info: Any) -> AccessScope:
    return await scope_for(identity_in(getattr(info, "context", None)))


def filter_by_path(scope: AccessScope, items: list[T], path_of: Callable[[T], str]) -> list[T]:
    return [item for item in items if scope.covers_path(path_of(item))]


async def allowed_topic(scope: AccessScope, topic: str, resolver: Any) -> bool:
    """True when the caller may see this topic.

    Unrestricted callers skip binding. Everyone else resolves the topic to an Asset
    path; unmodelled topics are hidden.
    """
    if scope.unrestricted:
        return True
    context = await resolver.resolve(topic)
    bound = None if context is None else context.asset_path
    return visible_topic(scope, bound)
