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

Integration tests for the Asset Model against a real Postgres/TimescaleDB.

The unit tests cover the decisions; these cover the SQL, which is where the
interesting mistakes are: longest-prefix binding, the derived Topic Bindings, and
the enrichment views. They need a migrated database reachable with the
`historian.*` settings — `uv run uns_model_setup`, or the compose stack.

Everything here is written under TEST_ROOT and removed again, so the tests are
safe to run against a database that already holds a seeded Asset Model.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from uns_model.alert_rules import AlertRuleRepository, AlertRuleSpec
from uns_model.asset_context import TopicContextResolver
from uns_model.engine import Database
from uns_model.model_config import ModelConfig
from uns_model.repositories import AssetModelRepository, AssetSpec

# Nothing outside this Enterprise is touched, which is what makes these tests
# runnable against a seeded database.
TEST_ROOT = "PyTestUNS"
TEST_METRIC_PREFIX = "PyTest/"
TEST_RULE_PREFIX = "pytest-"

METRICS_TABLE = "public.uns_metrics"
METRICS_1M_VIEW = "public.uns_metrics_1m"


def _branch(*levels: tuple[str, str], display_names: dict[str, str] | None = None) -> list[AssetSpec]:
    """AssetSpecs for one branch, given (segment, level) pairs."""
    names = display_names or {}
    return [AssetSpec(segment=segment, level=level, display_name=names.get(segment)) for segment, level in levels]


MIXER_BRANCH = _branch(
    (TEST_ROOT, "ENTERPRISE"),
    ("Plant1", "SITE"),
    ("Area1", "AREA"),
    ("Line1", "LINE"),
    ("Cell1", "WORK_CELL"),
    ("Mixer1", "MACHINE"),
    display_names={"Mixer1": "Mixer Tank 1", "Plant1": "Plant One"},
)
MIXER_PATH = f"{TEST_ROOT}/Plant1/Area1/Line1/Cell1/Mixer1"
CELL_PATH = f"{TEST_ROOT}/Plant1/Area1/Line1/Cell1"
AREA_PATH = f"{TEST_ROOT}/Plant1/Area1"


async def _clean(database: Database) -> None:
    """Remove everything these tests could have written, in FK-safe order."""
    async with database.begin() as connection:
        if (await connection.execute(text(f"SELECT to_regclass('{METRICS_TABLE}')"))).scalar() is not None:
            await connection.execute(
                text(f"DELETE FROM {METRICS_TABLE} WHERE starts_with(topic, :root)"), {"root": TEST_ROOT}
            )
        await connection.execute(text("DELETE FROM model.topic_binding WHERE starts_with(topic, :root)"), {"root": TEST_ROOT})
        await connection.execute(
            text("DELETE FROM model.metric_definition WHERE starts_with(metric_key, :prefix)"),
            {"prefix": TEST_METRIC_PREFIX},
        )
        # Cascades to every Asset and Metric Definition below it.
        await connection.execute(text("DELETE FROM model.asset WHERE path = :root"), {"root": TEST_ROOT})


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def database():
    """One engine for the whole session: asyncpg connections belong to a loop."""
    config = ModelConfig.from_settings()
    assert config.is_valid(), "historian.* settings are needed for the Asset Model integration tests"
    database = Database.from_config(config)
    yield database
    await database.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def repository(database: Database):
    """A repository against a database with no test data in it, before and after."""
    await _clean(database)
    yield AssetModelRepository(database)
    await _clean(database)


@pytest_asyncio.fixture(loop_scope="session")
async def alert_rules(database: Database):
    """An AlertRuleRepository with no test rules in it, before and after."""

    async def clean() -> None:
        async with database.begin() as connection:
            # Cascades to console.alert_rule_roles.
            await connection.execute(
                text("DELETE FROM console.alert_rules WHERE starts_with(id, :prefix)"),
                {"prefix": TEST_RULE_PREFIX},
            )

    await clean()
    yield AlertRuleRepository(database)
    await clean()


@pytest_asyncio.fixture(loop_scope="session")
async def metrics_table(database: Database):
    """The historian hypertable, without which the enrichment views do not exist."""
    async with database.begin() as connection:
        exists = (await connection.execute(text(f"SELECT to_regclass('{METRICS_TABLE}')"))).scalar()
    if exists is None:
        pytest.skip(f"{METRICS_TABLE} is missing: apply 04_uns_historian/sql_scripts first")
    return METRICS_TABLE


async def _binding(database: Database, topic: str) -> dict | None:
    async with database.begin() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT b.topic, b.metric_path, a.path AS asset_path "
                    "FROM model.topic_binding b LEFT JOIN model.asset a ON a.id = b.asset_id "
                    "WHERE b.topic = :topic"
                ),
                {"topic": topic},
            )
        ).mappings().one_or_none()
    return dict(row) if row else None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_ensure_branch_creates_every_level_and_is_idempotent(repository: AssetModelRepository):
    leaf = await repository.ensure_branch(MIXER_BRANCH)

    assert leaf.path == MIXER_PATH
    assert leaf.level == "MACHINE"
    assert leaf.name == "Mixer Tank 1"
    assert [asset.path for asset in await repository.list_assets(under=TEST_ROOT)] == [
        TEST_ROOT,
        f"{TEST_ROOT}/Plant1",
        AREA_PATH,
        f"{TEST_ROOT}/Plant1/Area1/Line1",
        CELL_PATH,
        MIXER_PATH,
    ]

    # Re-seeding is how the model is updated, so it must not duplicate or fail.
    renamed = list(MIXER_BRANCH)
    renamed[-1] = AssetSpec(segment="Mixer1", level="MACHINE", display_name="Mixer Tank One")
    again = await repository.ensure_branch(renamed)

    assert again.id == leaf.id
    assert again.name == "Mixer Tank One"
    assert len(await repository.list_assets(under=TEST_ROOT)) == 6


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_branch_may_skip_an_asset_level(repository: AssetModelRepository):
    # The simulator publishes no PRODUCTION_UNIT, so this has to be legal.
    leaf = await repository.ensure_branch(MIXER_BRANCH)

    levels = [asset.level for asset in await repository.list_assets(under=TEST_ROOT)]

    assert "PRODUCTION_UNIT" not in levels
    assert levels == ["ENTERPRISE", "SITE", "AREA", "LINE", "WORK_CELL", "MACHINE"]
    assert leaf.level == "MACHINE"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_inverted_branch_is_rejected(repository: AssetModelRepository):
    with pytest.raises(ValueError, match="cannot sit under"):
        await repository.ensure_branch(_branch((TEST_ROOT, "SITE"), ("Nonsense", "ENTERPRISE")))


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_children_and_ancestors_walk_the_tree(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    children = await repository.children_of(CELL_PATH)
    ancestors = await repository.ancestors_of(f"{MIXER_PATH}/ProcessValue/Temperature")

    assert [child.path for child in children] == [MIXER_PATH]
    # Coarsest first, and the topic's own trailing segments are not Assets.
    assert [asset.level for asset in ancestors] == ["ENTERPRISE", "SITE", "AREA", "LINE", "WORK_CELL", "MACHINE"]
    assert ancestors[-1].path == MIXER_PATH


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_bind_topic_resolves_to_the_deepest_matching_asset(repository: AssetModelRepository, database: Database):
    await repository.ensure_branch(MIXER_BRANCH)
    topic = f"{MIXER_PATH}/ProcessValue/Temperature"

    binding = await repository.bind_topic(topic)

    assert binding.metric_path == "ProcessValue/Temperature"
    assert await _binding(database, topic) == {
        "topic": topic,
        "metric_path": "ProcessValue/Temperature",
        "asset_path": MIXER_PATH,
    }


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_binding_a_topic_twice_is_the_same_binding(repository: AssetModelRepository, database: Database):
    await repository.ensure_branch(MIXER_BRANCH)
    topic = f"{MIXER_PATH}/ProcessValue/Temperature"

    await repository.bind_topic(topic)
    await repository.bind_topic(topic)

    # The upsert, not a second row: `topic` is the primary key.
    assert await _binding(database, topic) is not None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_underscore_in_an_asset_path_is_not_a_wildcard(repository: AssetModelRepository, database: Database):
    """
    Regression: prefix matching uses starts_with, not LIKE.

    With `topic LIKE path || '/%'`, an Asset at `.../Line_1` would swallow a topic
    published under `.../LineX1`, because `_` is a LIKE wildcard and plant segments
    are full of underscores.
    """
    await repository.ensure_branch(
        _branch((TEST_ROOT, "ENTERPRISE"), ("Plant1", "SITE"), ("Area1", "AREA"), ("Line_1", "LINE"))
    )
    topic = f"{AREA_PATH}/LineX1/Cell1/Temperature"

    await repository.bind_topic(topic)

    binding = await _binding(database, topic)
    assert binding["asset_path"] == AREA_PATH, "the underscore matched a segment it should not have"
    assert binding["metric_path"] == "LineX1/Cell1/Temperature"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_sibling_with_a_longer_name_is_not_a_match(repository: AssetModelRepository, database: Database):
    await repository.ensure_branch(
        _branch((TEST_ROOT, "ENTERPRISE"), ("Plant1", "SITE"), ("Area1", "AREA"), ("Line1", "LINE"))
    )
    # 'Line10' starts with 'Line1', so only the '/' in the comparison keeps them apart.
    topic = f"{AREA_PATH}/Line10/Cell1/Temperature"

    await repository.bind_topic(topic)

    assert (await _binding(database, topic))["asset_path"] == AREA_PATH


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_unmodelled_topic_is_recorded_rather_than_ignored(repository: AssetModelRepository, database: Database):
    topic = f"{TEST_ROOT}/NotModelled/Ghost/ProcessValue/Temperature"

    binding = await repository.bind_topic(topic)

    assert binding.asset_id is None
    async with database.begin() as connection:
        listed = (
            await connection.execute(text("SELECT topic FROM model.unmodelled_topic WHERE topic = :topic"), {"topic": topic})
        ).scalar()
    assert listed == topic
    assert topic in await repository.unmodelled_topics(limit=1000)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_rebind_all_moves_topics_when_a_deeper_asset_appears(repository: AssetModelRepository, database: Database):
    await repository.ensure_branch(MIXER_BRANCH[:-1])  # down to the Work Cell only
    topic = f"{MIXER_PATH}/ProcessValue/Temperature"
    await repository.bind_topic(topic)
    assert (await _binding(database, topic))["asset_path"] == CELL_PATH

    await repository.ensure_branch(MIXER_BRANCH)  # the Machine is commissioned
    moved = await repository.rebind_all()

    assert moved >= 1
    assert await _binding(database, topic) == {
        "topic": topic,
        "metric_path": "ProcessValue/Temperature",
        "asset_path": MIXER_PATH,
    }


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_rebind_all_is_a_no_op_when_the_model_has_not_changed(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.bind_topic(f"{MIXER_PATH}/ProcessValue/Temperature")
    await repository.rebind_all()

    assert await repository.rebind_all() == 0, "an unchanged model must not rewrite bindings"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_asset_specific_metric_definition_wins_over_the_plant_wide_one(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    key = f"{TEST_METRIC_PREFIX}Temperature/value"
    await repository.define_metric(key, unit_of_measure="°C", decimals=1)
    await repository.define_metric(key, asset_path=MIXER_PATH, unit_of_measure="K", decimals=3)

    resolver = TopicContextResolver(repository)
    context = await resolver.resolve(f"{MIXER_PATH}/{TEST_METRIC_PREFIX}Temperature")

    assert context is not None
    assert context.unit_of_measure("value") == "K"
    assert context.metric("value").decimals == 3


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_the_resolver_reads_lineage_names_and_units(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.define_metric(f"{TEST_METRIC_PREFIX}Temperature/value", unit_of_measure="°C")

    resolver = TopicContextResolver(repository)
    context = await resolver.resolve(f"{MIXER_PATH}/{TEST_METRIC_PREFIX}Temperature")

    assert context is not None
    assert context.levels["SITE"] == "Plant1"
    assert context.level_names["SITE"] == "Plant One"  # the authored name, not the segment
    assert context.levels.get("PRODUCTION_UNIT") is None
    assert context.asset_name == "Mixer Tank 1"
    assert context.metric_path == f"{TEST_METRIC_PREFIX}Temperature"
    assert context.unit_of_measure("value") == "°C"
    assert context.enrich("value")["machine"] == "Mixer1"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_unmodelled_topic_resolves_to_nothing(repository: AssetModelRepository):
    resolver = TopicContextResolver(repository)

    assert await resolver.resolve(f"{TEST_ROOT}/NotModelled/Ghost/ProcessValue/Temperature") is None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_the_enriched_view_joins_asset_context_onto_a_measurement(
    repository: AssetModelRepository,
    database: Database,
    metrics_table: str,
):
    branch = list(MIXER_BRANCH)
    branch[-1] = AssetSpec(
        segment="Mixer1",
        level="MACHINE",
        display_name="Mixer Tank 1",
        attributes={"volume_litres": 5000},
    )
    await repository.ensure_branch(branch)
    await repository.define_metric(f"{TEST_METRIC_PREFIX}Temperature/value", unit_of_measure="°C", decimals=2)
    topic = f"{MIXER_PATH}/{TEST_METRIC_PREFIX}Temperature"
    await repository.bind_topic(topic)

    async with database.begin() as connection:
        await connection.execute(
            text(
                f"INSERT INTO {metrics_table} (time, topic, metric_name, value_double) "
                "VALUES (now(), :topic, 'value', 42.5)"
            ),
            {"topic": topic},
        )
        row = (
            await connection.execute(
                text("SELECT * FROM public.uns_metrics_enriched WHERE topic = :topic"), {"topic": topic}
            )
        ).mappings().one()

    assert row["value_double"] == pytest.approx(42.5)
    assert row["asset_path"] == MIXER_PATH
    assert row["asset_name"] == "Mixer Tank 1"
    assert row["asset_level"] == "MACHINE"
    assert row["enterprise"] == TEST_ROOT
    assert row["site"] == "Plant1"
    assert row["line"] == "Line1"
    assert row["work_cell"] == "Cell1"
    assert row["machine"] == "Mixer1"
    assert row["production_unit"] is None
    assert row["metric_key"] == f"{TEST_METRIC_PREFIX}Temperature/value"
    assert row["unit_of_measure"] == "°C"
    assert row["decimals"] == 2
    assert row["asset_attributes"] == {"volume_litres": 5000}


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_the_enriched_view_keeps_measurements_for_an_unmodelled_topic(
    repository: AssetModelRepository,
    database: Database,
    metrics_table: str,
):
    """Enrichment is additive: a topic nobody modelled must not lose its data."""
    topic = f"{TEST_ROOT}/NotModelled/Ghost/ProcessValue/Temperature"
    await repository.bind_topic(topic)

    async with database.begin() as connection:
        await connection.execute(
            text(
                f"INSERT INTO {metrics_table} (time, topic, metric_name, value_double) "
                "VALUES (now(), :topic, 'value', 7.5)"
            ),
            {"topic": topic},
        )
        row = (
            await connection.execute(
                text("SELECT * FROM public.uns_metrics_enriched WHERE topic = :topic"), {"topic": topic}
            )
        ).mappings().one()

    assert row["value_double"] == pytest.approx(7.5)
    assert row["asset_path"] is None
    assert row["site"] is None
    assert row["metric_key"] == "value"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_the_aggregate_enriched_view_exists_and_is_queryable(database: Database):
    """Grafana reads this one, so a broken definition would only show up at runtime."""
    async with database.begin() as connection:
        if (await connection.execute(text(f"SELECT to_regclass('{METRICS_1M_VIEW}')"))).scalar() is None:
            pytest.skip(f"{METRICS_1M_VIEW} is missing: apply 04_uns_historian/sql_scripts first")
        columns = (
            await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'uns_metrics_1m_enriched'"
                )
            )
        ).scalars()
        names = set(columns)
        await connection.execute(text("SELECT * FROM public.uns_metrics_1m_enriched LIMIT 1"))

    assert {"bucket", "avg_value_double", "site", "machine", "unit_of_measure", "metric_key"} <= names


def _rule(rule_id: str = f"{TEST_RULE_PREFIX}mixer-temp", **overrides) -> AlertRuleSpec:
    defaults = {
        "id": rule_id,
        "name": "Mixer over temperature",
        "severity": "HIGH",
        "category": "TEMPERATURE",
        "topic": f"{MIXER_PATH}/ProcessValue/Temperature",
        "metric_field": "value",
        "condition": "GREATER_THAN",
        "threshold_value": 85.0,
    }
    return AlertRuleSpec(**(defaults | overrides))


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_saved_alert_rule_comes_back_whole(alert_rules: AlertRuleRepository):
    await alert_rules.save_rule(
        _rule(
            description="Cooling loop check",
            unit="°C",
            delay_seconds=30,
            escalation_role="engineer",
            escalation_timeout_minutes=15,
            mqtt_publish_on_trigger=True,
            mqtt_alarm_topic="Enterprise/Plant1/Alarm",
            roles=["operator", "engineer"],
        )
    )

    rule = await alert_rules.get_rule(f"{TEST_RULE_PREFIX}mixer-temp")

    assert rule is not None
    assert rule.name == "Mixer over temperature"
    assert rule.severity == "HIGH"
    assert rule.threshold_value == pytest.approx(85.0)
    assert rule.unit == "°C"
    assert rule.delay_seconds == 30
    assert rule.escalation_role == "engineer"
    assert rule.mqtt_publish_on_trigger is True
    assert rule.roles == ["engineer", "operator"]
    # Defaults come from the table, not from the console.
    assert rule.enabled is True
    assert rule.trigger_count == 0
    assert rule.last_triggered_at is None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_saving_the_same_rule_id_edits_it_rather_than_duplicating_it(alert_rules: AlertRuleRepository):
    await alert_rules.save_rule(_rule(threshold_value=85.0))
    await alert_rules.save_rule(_rule(threshold_value=90.0, name="Mixer over temperature (revised)"))

    rules = [rule for rule in await alert_rules.list_rules() if rule.id.startswith(TEST_RULE_PREFIX)]

    assert len(rules) == 1
    assert rules[0].threshold_value == pytest.approx(90.0)
    assert rules[0].name == "Mixer over temperature (revised)"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_removing_a_role_from_a_rule_actually_unsubscribes_it(alert_rules: AlertRuleRepository):
    """A role surviving a removal is how somebody gets paged after unsubscribing."""
    await alert_rules.save_rule(_rule(roles=["operator", "engineer"]))

    rule = await alert_rules.save_rule(_rule(roles=["operator"]))

    assert rule.roles == ["operator"]
    assert (await alert_rules.get_rule(rule.id)).roles == ["operator"]


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_rule_outside_the_vocabulary_never_reaches_the_database(alert_rules: AlertRuleRepository):
    with pytest.raises(ValueError, match="severity must be one of"):
        await alert_rules.save_rule(_rule(severity="CATASTROPHIC"))

    assert await alert_rules.get_rule(f"{TEST_RULE_PREFIX}mixer-temp") is None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_disabling_a_rule_leaves_its_threshold_alone(alert_rules: AlertRuleRepository):
    saved = await alert_rules.save_rule(_rule())

    disabled = await alert_rules.set_enabled(saved.id, enabled=False)

    assert disabled.enabled is False
    assert disabled.threshold_value == pytest.approx(85.0)
    assert [rule.id for rule in await alert_rules.list_rules(enabled_only=True) if rule.id == saved.id] == []


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_enabling_a_rule_that_does_not_exist_returns_nothing(alert_rules: AlertRuleRepository):
    assert await alert_rules.set_enabled(f"{TEST_RULE_PREFIX}ghost", enabled=True) is None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_evaluation_that_fires_counts_and_is_timestamped_by_the_server(alert_rules: AlertRuleRepository):
    saved = await alert_rules.save_rule(_rule())

    quiet = await alert_rules.record_evaluation(saved.id, triggered=False)
    assert quiet.last_evaluated_at is not None
    assert quiet.trigger_count == 0
    assert quiet.last_triggered_at is None

    fired = await alert_rules.record_evaluation(saved.id, triggered=True)
    fired_again = await alert_rules.record_evaluation(saved.id, triggered=True)

    assert fired.trigger_count == 1
    assert fired_again.trigger_count == 2
    assert fired_again.last_triggered_at >= fired.last_triggered_at


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deleting_a_rule_takes_its_roles_with_it(alert_rules: AlertRuleRepository, database: Database):
    saved = await alert_rules.save_rule(_rule(roles=["operator"]))

    assert await alert_rules.delete_rule(saved.id) is True
    assert await alert_rules.get_rule(saved.id) is None
    async with database.begin() as connection:
        orphans = (
            await connection.execute(
                text("SELECT count(*) FROM console.alert_rule_roles WHERE rule_id = :id"), {"id": saved.id}
            )
        ).scalar()
    assert orphans == 0
    assert await alert_rules.delete_rule(saved.id) is False


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_the_console_can_ask_what_changed_and_how_much_is_armed(alert_rules: AlertRuleRepository):
    before = await alert_rules.counts()

    await alert_rules.save_rule(_rule())
    await alert_rules.save_rule(_rule(f"{TEST_RULE_PREFIX}pressure", category="PRESSURE", enabled=False))

    after = await alert_rules.counts()
    assert after["rules"] == before["rules"] + 2
    assert after["enabled_rules"] == before["enabled_rules"] + 1
    # A console polls this to decide whether to refetch the rules at all.
    assert await alert_rules.last_changed_at() is not None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deleting_a_site_removes_its_branch_and_unbinds_its_topics(
    repository: AssetModelRepository,
    database: Database,
):
    await repository.ensure_branch(MIXER_BRANCH)
    topic = f"{MIXER_PATH}/ProcessValue/Temperature"
    await repository.bind_topic(topic)

    removed = await repository.delete_asset(f"{TEST_ROOT}/Plant1")

    assert removed == 1
    assert await repository.list_assets(under=f"{TEST_ROOT}/Plant1") == []
    # The binding survives with no Asset rather than taking the measurement with it,
    # which is exactly what makes it an Unmodelled Topic again.
    assert (await _binding(database, topic))["asset_path"] is None
