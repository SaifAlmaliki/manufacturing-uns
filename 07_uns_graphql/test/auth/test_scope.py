from unittest.mock import AsyncMock

import pytest
from uns_model.access import covers  # only to document the same rule

from uns_graphql.auth.scope import AccessScope, scope_for, visible_topic
from uns_graphql.auth.token import Identity

ADMIN = AccessScope(unrestricted=True, root_paths=frozenset())
EMPTY = AccessScope(unrestricted=False, root_paths=frozenset())
FILT = AccessScope(unrestricted=False, root_paths=frozenset({"AcmeWater/Site1/Filtration"}))
UNION = AccessScope(
    unrestricted=False,
    root_paths=frozenset({"AcmeWater/Site1/Filtration", "AcmeWater/Site1/Storage"}),
)


def test_admin_covers_everything():
    assert ADMIN.covers_path("AcmeWater/Site1/RawWater/Train1")


def test_empty_covers_nothing():
    assert not EMPTY.covers_path("AcmeWater/Site1/Filtration")


def test_union_covers_both_roots():
    assert UNION.covers_path("AcmeWater/Site1/Filtration/Train1")
    assert UNION.covers_path("AcmeWater/Site1/Storage/Train1")
    assert not UNION.covers_path("AcmeWater/Site1/RawWater")


def test_unmodelled_topic_is_admin_only():
    assert visible_topic(ADMIN, None)
    assert not visible_topic(FILT, None)
    assert visible_topic(FILT, "AcmeWater/Site1/Filtration")


def test_covers_path_uses_the_model_rule():
    path = "AcmeWater/Site1/Filtration/Train1"
    root = "AcmeWater/Site1/Filtration"
    assert FILT.covers_path(path) is covers(path, root)


def _identity(*roles: str) -> Identity:
    return Identity(subject="s", username="u", roles=frozenset(roles))


@pytest.mark.asyncio
async def test_scope_for_none_is_empty():
    boom = AsyncMock(side_effect=AssertionError("unsigned-in must not load membership"))
    scope = await scope_for(None, roots_for=boom)
    assert scope == EMPTY
    boom.assert_not_called()


@pytest.mark.asyncio
async def test_scope_for_admin_is_unrestricted_without_loading_roots():
    boom = AsyncMock(side_effect=AssertionError("admin must not load membership"))
    scope = await scope_for(_identity("admin"), roots_for=boom)
    assert scope == ADMIN
    boom.assert_not_called()


@pytest.mark.asyncio
async def test_scope_for_without_membership_is_empty():
    none = AsyncMock(return_value=frozenset())
    scope = await scope_for(_identity("operator"), roots_for=none)
    assert scope == EMPTY
    none.assert_awaited_once_with("s")


@pytest.mark.asyncio
async def test_scope_for_loads_roots_for_a_member():
    filt = AsyncMock(return_value=frozenset({"AcmeWater/Site1/Filtration"}))
    scope = await scope_for(_identity("operator"), roots_for=filt)
    assert scope == FILT
    filt.assert_awaited_once_with("s")
