"""
Unit tests for Enrichment. No database: the resolver is handed a fake repository,
which is the point of accepting one rather than creating it.
"""

from __future__ import annotations

import pytest

from uns_model.asset_context import TopicContextResolver
from uns_model.tables import Asset, MetricDefinition

TOPIC = "CovestroAG/Dormagen/Production/Line1/Cell1/G1/ProcessValue/Temperature"
MACHINE_PATH = "CovestroAG/Dormagen/Production/Line1/Cell1/G1"


def _asset(path: str, level: str, **kwargs) -> Asset:
    return Asset(id=abs(hash(path)) % 10_000, path=path, segment=path.rsplit("/", 1)[-1], level=level, **kwargs)


SIMULATOR_BRANCH = [
    _asset("CovestroAG", "ENTERPRISE"),
    _asset("CovestroAG/Dormagen", "SITE", display_name="Dormagen Plant"),
    _asset("CovestroAG/Dormagen/Production", "AREA"),
    _asset("CovestroAG/Dormagen/Production/Line1", "LINE", display_name="Polyol Line 1"),
    _asset("CovestroAG/Dormagen/Production/Line1/Cell1", "WORK_CELL"),
    _asset(MACHINE_PATH, "MACHINE", display_name="Mixer G1", manufacturer="Siemens", criticality="HIGH"),
]


class FakeRepository:
    """Stands in for AssetModelRepository at the same seam."""

    def __init__(self, ancestors: list[Asset], definitions: list[MetricDefinition] | None = None) -> None:
        self._ancestors = ancestors
        self._definitions = definitions or []
        self.ancestor_calls = 0

    async def ancestors_of(self, topic: str) -> list[Asset]:  # noqa: ARG002
        self.ancestor_calls += 1
        return self._ancestors

    async def metric_definitions_for(self, asset_id: int | None, metric_path_prefix: str = "") -> list[MetricDefinition]:  # noqa: ARG002
        return self._definitions


@pytest.mark.asyncio
async def test_resolve_names_every_level_and_splits_off_the_metric_path():
    resolver = TopicContextResolver(FakeRepository(SIMULATOR_BRANCH))

    context = await resolver.resolve(TOPIC)

    assert context is not None
    assert context.asset_path == MACHINE_PATH
    assert context.asset_level == "MACHINE"
    assert context.metric_path == "ProcessValue/Temperature"
    assert context.levels["SITE"] == "Dormagen"
    assert context.levels["LINE"] == "Line1"
    assert context.levels["MACHINE"] == "G1"
    # PRODUCTION_UNIT is skipped in this branch, which is why levels is a mapping
    # and not a fixed set of columns.
    assert "PRODUCTION_UNIT" not in context.levels


@pytest.mark.asyncio
async def test_display_names_are_available_separately_from_topic_segments():
    resolver = TopicContextResolver(FakeRepository(SIMULATOR_BRANCH))

    context = await resolver.resolve(TOPIC)

    assert context.levels["LINE"] == "Line1"
    assert context.level_names["LINE"] == "Polyol Line 1"
    assert context.asset_name == "Mixer G1"


@pytest.mark.asyncio
async def test_an_unmodelled_topic_resolves_to_none():
    resolver = TopicContextResolver(FakeRepository([]))

    assert await resolver.resolve("SomeoneElse/Plant/Sensor") is None


@pytest.mark.asyncio
async def test_unit_of_measure_comes_from_the_metric_definition_for_that_payload_leaf():
    definitions = [
        MetricDefinition(asset_id=None, metric_key="ProcessValue/Temperature/value", unit_of_measure="°C", min_value=0.0),
    ]
    resolver = TopicContextResolver(FakeRepository(SIMULATOR_BRANCH, definitions))

    context = await resolver.resolve(TOPIC)

    assert context.unit_of_measure("value") == "°C"
    assert context.metric("value").min_value == 0.0
    assert context.unit_of_measure("status") is None, "no definition was authored for the status leaf"


@pytest.mark.asyncio
async def test_an_asset_specific_definition_overrides_the_plant_wide_one():
    definitions = [
        # Ordered as the repository orders them: plant-wide first, Asset-specific last.
        MetricDefinition(asset_id=None, metric_key="ProcessValue/Temperature/value", unit_of_measure="°C"),
        MetricDefinition(asset_id=1, metric_key="ProcessValue/Temperature/value", unit_of_measure="K"),
    ]
    resolver = TopicContextResolver(FakeRepository(SIMULATOR_BRANCH, definitions))

    context = await resolver.resolve(TOPIC)

    assert context.unit_of_measure("value") == "K"


@pytest.mark.asyncio
async def test_enrich_is_flat_and_carries_the_metric_definition():
    definitions = [MetricDefinition(asset_id=None, metric_key="ProcessValue/Temperature/value", unit_of_measure="°C")]
    resolver = TopicContextResolver(FakeRepository(SIMULATOR_BRANCH, definitions))

    context = await resolver.resolve(TOPIC)
    enriched = context.enrich("value")

    assert enriched["site"] == "Dormagen"
    assert enriched["line"] == "Line1"
    assert enriched["machine"] == "G1"
    assert enriched["production_unit"] is None
    assert enriched["manufacturer"] == "Siemens"
    assert enriched["metric_key"] == "ProcessValue/Temperature/value"
    assert enriched["unit_of_measure"] == "°C"


@pytest.mark.asyncio
async def test_resolution_is_cached_so_a_hot_topic_hits_the_database_once():
    repository = FakeRepository(SIMULATOR_BRANCH)
    resolver = TopicContextResolver(repository)

    for _ in range(5):
        await resolver.resolve(TOPIC)

    assert repository.ancestor_calls == 1


@pytest.mark.asyncio
async def test_refresh_forces_the_next_resolve_to_reload():
    repository = FakeRepository(SIMULATOR_BRANCH)
    resolver = TopicContextResolver(repository)

    await resolver.resolve(TOPIC)
    resolver.refresh()
    await resolver.resolve(TOPIC)

    assert repository.ancestor_calls == 2


@pytest.mark.asyncio
async def test_the_cache_expires_so_a_model_edit_in_another_process_is_picked_up():
    repository = FakeRepository(SIMULATOR_BRANCH)
    resolver = TopicContextResolver(repository, ttl_seconds=0)

    await resolver.resolve(TOPIC)
    await resolver.resolve(TOPIC)

    assert repository.ancestor_calls == 2


@pytest.mark.asyncio
async def test_the_cache_is_bounded():
    repository = FakeRepository(SIMULATOR_BRANCH)
    resolver = TopicContextResolver(repository, cache_size=2)

    for index in range(5):
        await resolver.resolve(f"{MACHINE_PATH}/ProcessValue/Sensor{index}")

    assert len(resolver._cache) == 2  # noqa: SLF001
