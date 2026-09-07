import pytest
from uns_factory_agent.chat import PageContext
from uns_factory_agent.context_pack import build_context_pack
from uns_factory_agent.playbook import run_playbook
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
