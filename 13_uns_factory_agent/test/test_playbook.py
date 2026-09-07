import json
import re

import pytest
from uns_factory_agent import playbook as playbook_module
from uns_factory_agent.chat import PageContext
from uns_factory_agent.context_pack import build_context_pack
from uns_factory_agent.playbook import OBSERVATION_BUDGET_CHARS, _under_a_path, run_playbook
from uns_factory_agent.scope_sql import Scope


class RecordingSql:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []

    async def fetch(self, sql, params):
        self.calls.append((sql, params))
        return list(self.rows)


class RecordingGraphql:
    def __init__(self):
        self.queries = []

    async def post(self, query, variables, token):
        self.queries.append((query, variables, token))
        if "getAlertRules" in query:
            return {
                "data": {
                    "getAlertRules": [
                        {
                            "id": "1",
                            "name": "Hi",
                            "topic": "Acme/Site1/P101/Fault",
                            "severity": "HIGH",
                            "enabled": True,
                        }
                    ]
                }
            }
        return {"data": {"getUnsNodes": []}}


@pytest.mark.asyncio
async def test_empty_focus_historian_uses_root_in_scope_params():
    pack = build_context_pack(PageContext("", "", "", ""), is_admin=False, root_paths=frozenset({"Acme/Site1"}))
    sql = RecordingSql()
    gql = RecordingGraphql()
    result = await run_playbook(
        "publishers_on_path",
        pack,
        scope=Scope(False, frozenset({"Acme/Site1"})),
        sql_execute=sql,
        graphql=gql,
        token="tok",
    )
    assert "query_historian" in result.tools_called
    assert any("Acme/Site1" in str(params.values()) for _, params in sql.calls)


@pytest.mark.asyncio
async def test_p101_focus_does_not_use_all_roots_as_live_topic():
    pack = build_context_pack(
        PageContext("", "Acme/Site1/P101", "", ""),
        is_admin=False,
        root_paths=frozenset({"Acme/Site1", "Acme/Site2"}),
    )
    sql = RecordingSql()
    gql = RecordingGraphql()
    result = await run_playbook(
        "publishers_on_path",
        pack,
        scope=Scope(False, frozenset({"Acme/Site1", "Acme/Site2"})),
        sql_execute=sql,
        graphql=gql,
        token="tok",
    )
    live_topics = []
    for query, variables, _ in gql.queries:
        if "getUnsNodes" in query:
            live_topics.extend(t["topic"] for t in variables["topics"])
    assert any(t.startswith("Acme/Site1/P101") for t in live_topics)
    assert not any(t.startswith("Acme/Site2/") for t in live_topics)


@pytest.mark.asyncio
async def test_platform_map_calls_no_sql_or_graphql():
    pack = build_context_pack(PageContext("", "", "", ""), is_admin=True, root_paths=frozenset(), admin_roots=("Acme",))
    sql = RecordingSql()
    gql = RecordingGraphql()
    result = await run_playbook(
        "platform_map",
        pack,
        scope=Scope(True, frozenset()),
        sql_execute=sql,
        graphql=gql,
        token="tok",
    )
    assert sql.calls == []
    assert gql.queries == []
    assert "Asset Model" in result.observations or "Postgres" in result.observations


@pytest.mark.asyncio
async def test_empty_historian_observations_say_cannot_see():
    pack = build_context_pack(PageContext("", "Acme/P101", "", ""), is_admin=True, root_paths=frozenset(), admin_roots=("Acme",))
    sql = RecordingSql(rows=[])
    gql = RecordingGraphql()
    result = await run_playbook(
        "metric_vs_window",
        pack,
        scope=Scope(True, frozenset()),
        sql_execute=sql,
        graphql=gql,
        token="tok",
    )
    assert "cannot see" in result.observations.lower()


# --- C1: real schema columns ------------------------------------------------------


def test_playbook_sql_does_not_reference_stale_columns():
    all_sql = "\n".join(
        [
            playbook_module.ADMIN_ROOTS_SQL,
            playbook_module.METRICS_ON_PATHS,
            playbook_module.HISTORIAN_WINDOW,
            playbook_module.PUBLISHERS_HOUR,
            playbook_module.DOWNTIME,
            playbook_module.PLANT_MAP,
        ]
    )
    assert not re.search(r"\bmd\.key\b", all_sql), "metric_definition column is metric_key, not key"
    assert not re.search(r"\bmd\.unit\b", all_sql), "metric_definition column is unit_of_measure, not unit"
    assert "value_bool" not in all_sql
    assert "value_string" not in all_sql
    assert "SELECT path, name, level" not in all_sql, "model.asset has no name column"


# --- C2: a broken tool step narrates, it never raises -----------------------------


class BoomSql:
    async def fetch(self, sql, params):
        raise RuntimeError("db exploded")


class BoomGraphql:
    async def post(self, query, variables, token):
        raise RuntimeError("graphql exploded")


@pytest.mark.asyncio
async def test_sql_exception_becomes_cannot_see_not_a_raise():
    pack = build_context_pack(PageContext("", "Acme/P101", "", ""), is_admin=True, root_paths=frozenset(), admin_roots=("Acme",))
    result = await run_playbook(
        "metric_vs_window",
        pack,
        scope=Scope(True, frozenset()),
        sql_execute=BoomSql(),
        graphql=RecordingGraphql(),
        token="tok",
    )
    assert "cannot see" in result.observations.lower()


@pytest.mark.asyncio
async def test_graphql_exception_becomes_cannot_see_not_a_raise():
    pack = build_context_pack(PageContext("", "Acme/P101", "", ""), is_admin=True, root_paths=frozenset(), admin_roots=("Acme",))
    result = await run_playbook(
        "alarms_on_focus",
        pack,
        scope=Scope(True, frozenset()),
        sql_execute=RecordingSql(),
        graphql=BoomGraphql(),
        token="tok",
    )
    assert "cannot see" in result.observations.lower()


# --- C3: focus paths reach the SQL, not just live GraphQL topics ------------------


@pytest.mark.asyncio
async def test_p101_focus_scopes_sql_to_the_focus_path():
    pack = build_context_pack(
        PageContext("", "Acme/Site1/P101", "", ""),
        is_admin=True,
        root_paths=frozenset(),
        admin_roots=("Acme",),
    )
    sql = RecordingSql()
    gql = RecordingGraphql()
    await run_playbook(
        "metric_vs_window",
        pack,
        scope=Scope(True, frozenset()),
        sql_execute=sql,
        graphql=gql,
        token="tok",
    )
    assert sql.calls, "metric_vs_window must issue SQL"
    assert any(
        "Acme/Site1/P101" in str(params.values()) or "Acme/Site1/P101" in sql_text
        for sql_text, params in sql.calls
    )
    assert all("LIMIT 200" in sql_text for sql_text, _ in sql.calls)


# --- M10: plant_overview alarms follow the resolved focus, not only default_plant -


@pytest.mark.asyncio
async def test_plant_overview_alarms_use_focus_path_when_present():
    pack = build_context_pack(
        PageContext("", "Acme/Site1/P101", "", ""),
        is_admin=False,
        root_paths=frozenset({"Acme/Site1", "Acme/Site2"}),
    )
    gql = RecordingGraphql()
    result = await run_playbook(
        "plant_overview",
        pack,
        scope=Scope(False, frozenset({"Acme/Site1", "Acme/Site2"})),
        sql_execute=RecordingSql(),
        graphql=gql,
        token="tok",
    )
    assert "Acme/Site1/P101/Fault" in result.observations


# --- I6: one observation budget, truncated at a row boundary ----------------------


@pytest.mark.asyncio
async def test_observations_stay_under_budget_and_truncate_on_row_boundaries():
    pack = build_context_pack(PageContext("", "Acme/P101", "", ""), is_admin=True, root_paths=frozenset(), admin_roots=("Acme",))
    big_rows = [{"topic": "Acme/P101", "value_double": i, "blob": "x" * 500} for i in range(100)]
    sql = RecordingSql(rows=big_rows)
    gql = RecordingGraphql()
    result = await run_playbook(
        "performance_rca",
        pack,
        scope=Scope(True, frozenset()),
        sql_execute=sql,
        graphql=gql,
        token="tok",
    )
    assert len(result.observations) <= OBSERVATION_BUDGET_CHARS
    for line in result.observations.split("\n"):
        if ": [" not in line:
            continue
        _, _, payload = line.partition(": ")
        payload = payload.rsplit(" (+", 1)[0] if " (+" in payload else payload
        json.loads(payload)  # every emitted chunk is whole, valid JSON — never a mid-object slice


# --- I8: prefix matching does not confuse Site1 with Site10 -----------------------


def test_under_a_path_matches_descendants_not_similarly_named_siblings():
    assert _under_a_path("Acme/Site1/P101/Fault", ("Acme/Site1",)) is True
    assert _under_a_path("Acme/Site1", ("Acme/Site1",)) is True
    assert _under_a_path("Acme/Site10/P101/Fault", ("Acme/Site1",)) is False
