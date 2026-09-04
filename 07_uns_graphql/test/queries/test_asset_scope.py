"""Plant reads hide Assets outside the caller's Access Groups."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from uns_model.hierarchy import HierarchyArea, HierarchyLine, HierarchySite, HierarchyTree

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.scope import AccessScope, filter_by_path
from uns_graphql.auth.token import Identity
from uns_graphql.mutations.hierarchy import Query as HierarchyQuery
from uns_graphql.queries.asset import Query

FILT = "AcmeWater/Site1/Filtration"
RAW = "AcmeWater/Site1/RawWater"


def _info(scope: AccessScope, roles=frozenset({"operator"})):
    identity = Identity(subject="op", username="omar", roles=roles)
    return SimpleNamespace(context={CONTEXT_KEY: identity, "_scope": scope})


def _asset(*, path: str, segment: str, level: str) -> SimpleNamespace:
    # AssetNode.from_asset reads every field below; keep this in lockstep with type/asset.py.
    return SimpleNamespace(
        id=1,
        path=path,
        segment=segment,
        level=level,
        name=segment,
        description=None,
        manufacturer=None,
        model_number=None,
        serial_number=None,
        criticality=None,
        is_active=True,
        attributes={},
    )


def test_filter_by_path_keeps_covered_items_only():
    scope = AccessScope(False, frozenset({FILT}))
    items = [
        SimpleNamespace(path=RAW),
        SimpleNamespace(path=FILT),
        SimpleNamespace(path=f"{FILT}/Train1"),
    ]
    kept = filter_by_path(scope, items, lambda item: item.path)
    assert [item.path for item in kept] == [FILT, f"{FILT}/Train1"]


def test_filter_by_path_unrestricted_keeps_all():
    scope = AccessScope(True, frozenset())
    items = [SimpleNamespace(path=RAW), SimpleNamespace(path=FILT)]
    assert filter_by_path(scope, items, lambda item: item.path) == items


@pytest.mark.asyncio
async def test_get_assets_hides_other_areas():
    assets = [
        _asset(path=RAW, segment="RawWater", level="AREA"),
        _asset(path=FILT, segment="Filtration", level="AREA"),
        _asset(path=f"{FILT}/Train1", segment="Train1", level="LINE"),
    ]
    query = Query()
    filt_scope = AccessScope(False, frozenset({FILT}))
    with (
        patch("uns_graphql.queries.asset._repository") as repo,
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=filt_scope)),
    ):
        repo.return_value.list_assets = AsyncMock(return_value=assets)
        result = await query.get_assets(info=_info(filt_scope))
    paths = [node.path for node in result]
    assert paths == [FILT, f"{FILT}/Train1"]
    assert RAW not in paths


@pytest.mark.asyncio
async def test_get_unmodelled_topics_hidden_from_operator():
    query = Query()
    filt_scope = AccessScope(False, frozenset({FILT}))
    with (
        patch("uns_graphql.queries.asset._repository") as repo,
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=filt_scope)),
    ):
        repo.return_value.unmodelled_topics = AsyncMock(return_value=["orphan/topic"])
        result = await query.get_unmodelled_topics(info=_info(filt_scope))
    assert result == []


@pytest.mark.asyncio
async def test_get_unmodelled_topics_admin_sees_orphans():
    query = Query()
    admin_scope = AccessScope(True, frozenset())
    orphans = ["orphan/topic"]
    with (
        patch("uns_graphql.queries.asset._repository") as repo,
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=admin_scope)),
    ):
        repo.return_value.unmodelled_topics = AsyncMock(return_value=orphans)
        result = await query.get_unmodelled_topics(
            info=_info(admin_scope, roles=frozenset({"admin"}))
        )
    assert result == orphans


@pytest.mark.asyncio
async def test_get_hierarchy_hides_rawwater_from_filtration_operator():
    tree = HierarchyTree(
        enterprise="AcmeWater",
        sites=(
            HierarchySite(
                name="Site1",
                areas=(
                    HierarchyArea(
                        name="RawWater",
                        kind="production",
                        lines=(HierarchyLine(name="Train1", cells=("V101",)),),
                    ),
                    HierarchyArea(
                        name="Filtration",
                        kind="production",
                        lines=(HierarchyLine(name="Train1", cells=("F101",)),),
                    ),
                ),
            ),
        ),
    )
    filt_scope = AccessScope(False, frozenset({FILT}))
    with (
        patch("uns_graphql.mutations.hierarchy.load_plant_tree", return_value=tree),
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=filt_scope)),
    ):
        result = await HierarchyQuery().get_hierarchy(info=_info(filt_scope))
    area_names = [area.name for site in result.sites for area in site.areas]
    assert area_names == ["Filtration"]
    assert RAW.split("/")[-1] not in area_names
