import pytest
from datetime import UTC, datetime
from fastapi.testclient import TestClient

from uns_factory_agent.app import create_app
from uns_factory_agent.auth import AuthError, Identity
from uns_factory_agent.chat import ModelTurn, PageContext, ToolCall, run_turn
from uns_factory_agent.conversations import Citation, MemoryConversationStore
from uns_factory_agent.scope_sql import Scope

NOW = datetime(2026, 9, 6, tzinfo=UTC)


class ScriptedModel:
    def __init__(self, turns: list[ModelTurn]):
        self.turns = list(turns)
        self.seen_tools = []

    async def complete(self, messages, tools):
        self.seen_tools.append([t["function"]["name"] for t in tools])
        return self.turns.pop(0)


@pytest.mark.asyncio
async def test_ack_request_does_not_call_sql():
    store = MemoryConversationStore()
    conv = await store.create("alice", now=NOW)
    calls = []

    class BoomExec:
        async def fetch(self, sql, params):
            calls.append(sql)
            return []

    model = ScriptedModel([
        ModelTurn(text="I cannot change the plant. I only look things up.", tool_calls=(), citations=()),
    ])
    result = await run_turn(
        store=store,
        conversation_id=conv.id,
        subject="alice",
        token="t",
        message="Ack this alarm and raise the threshold.",
        context=PageContext("/alerts", "", "", "Acme/Plant/L1"),
        scope=Scope(True, frozenset()),
        model=model,
        sql_execute=BoomExec(),
        graphql=type("G", (), {"post": staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError()))})(),
        now=NOW,
    )
    assert calls == []
    assert "cannot" in result.text.lower() or "look" in result.text.lower()
    msgs = await store.last_messages(conv.id, "alice")
    assert msgs[-1].role == "assistant"


@pytest.mark.asyncio
async def test_historian_tool_is_dispatched():
    store = MemoryConversationStore()
    conv = await store.create("alice", now=NOW)
    seen = []

    class Exec:
        async def fetch(self, sql, params):
            seen.append(sql)
            return [{"topic": "Acme/Plant/L1", "value_double": 1.2}]

    model = ScriptedModel([
        ModelTurn(
            text=None,
            tool_calls=(ToolCall("query_historian", {"sql": "SELECT topic FROM uns_metrics"}),),
            citations=(),
        ),
        ModelTurn(
            text="Dryer last published 1.2 on Acme/Plant/L1.",
            tool_calls=(),
            citations=(Citation("Dryer", "Acme/Plant/L1", "2026-09-06T11:00:00Z", "historian"),),
        ),
    ])
    result = await run_turn(
        store=store,
        conversation_id=conv.id,
        subject="alice",
        token="t",
        message="What did Dryer do last shift?",
        context=PageContext("/condition-monitoring", "Acme/Plant/L1/Dryer", "", ""),
        scope=Scope(True, frozenset()),
        model=model,
        sql_execute=Exec(),
        graphql=type("G", (), {"post": staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError()))})(),
        now=NOW,
    )
    assert seen
    assert result.citations[0].source == "historian"


def test_chat_without_bearer_is_401():
    store = MemoryConversationStore()

    def get_identity(_header):
        raise AuthError("The request has no Authorization bearer token.")

    client = TestClient(create_app(store, get_identity=get_identity))
    assert client.post("/chat", json={"message": "hi", "conversationId": "x", "context": {}}).status_code == 401


def test_chat_foreign_conversation_is_404():
    import asyncio

    store = MemoryConversationStore()
    theirs = asyncio.run(store.create("bob", now=NOW))

    def get_identity(_header):
        return Identity(subject="alice", username="alice", roles=frozenset({"operator"}))

    client = TestClient(create_app(store, get_identity=get_identity))
    assert (
        client.post(
            "/chat",
            json={"message": "hi", "conversationId": theirs.id, "context": {}},
        ).status_code
        == 404
    )


@pytest.mark.asyncio
async def test_metric_question_runs_playbook_sql_before_model():
    store = MemoryConversationStore()
    conv = await store.create("alice", now=NOW)
    seen = []

    class Exec:
        async def fetch(self, sql, params):
            seen.append(sql)
            return []

    class Graphql:
        async def post(self, query, variables, token):
            return {"data": {"getUnsNodes": [], "getAlertRules": []}}

    model = ScriptedModel([
        ModelTurn(
            text="I cannot see historian values for that Metric in the last eight hours.",
            tool_calls=(),
            citations=(),
        ),
    ])
    result = await run_turn(
        store=store,
        conversation_id=conv.id,
        subject="alice",
        token="t",
        message="How does this metric compare to the last eight hours?",
        context=PageContext("/condition-monitoring", "Acme/P101", "", ""),
        scope=Scope(True, frozenset()),
        model=model,
        sql_execute=Exec(),
        graphql=Graphql(),
        now=NOW,
    )
    assert seen, "playbook must hit SQL before the model"
    assert "cannot see" in result.text.lower()
    assert "12.3" not in result.text


@pytest.mark.asyncio
async def test_platform_map_does_not_dispatch_sql():
    store = MemoryConversationStore()
    conv = await store.create("alice", now=NOW)
    calls = []

    class Boom:
        async def fetch(self, sql, params):
            calls.append(sql)
            return []

    class Boomql:
        async def post(self, query, variables, token):
            raise AssertionError("no graphql")

    model = ScriptedModel([
        ModelTurn(text="Postgres holds the Asset Model. Timescale holds history.", tool_calls=(), citations=()),
    ])
    await run_turn(
        store=store,
        conversation_id=conv.id,
        subject="alice",
        token="t",
        message="how does historian work?",
        context=PageContext("", "", "", ""),
        scope=Scope(True, frozenset()),
        model=model,
        sql_execute=Boom(),
        graphql=Boomql(),
        now=NOW,
    )
    assert calls == []


@pytest.mark.asyncio
async def test_platform_health_falls_back_to_static_reply_when_model_is_empty():
    from uns_factory_agent.console_map import PLATFORM_HEALTH_REPLY

    store = MemoryConversationStore()
    conv = await store.create("alice", now=NOW)

    class Boom:
        async def fetch(self, sql, params):
            raise AssertionError("no sql")

    class Boomql:
        async def post(self, query, variables, token):
            raise AssertionError("no graphql")

    model = ScriptedModel([ModelTurn(text=None, tool_calls=(), citations=()) for _ in range(4)])
    result = await run_turn(
        store=store,
        conversation_id=conv.id,
        subject="alice",
        token="t",
        message="why is graphql down?",
        context=PageContext("", "", "", ""),
        scope=Scope(True, frozenset()),
        model=model,
        sql_execute=Boom(),
        graphql=Boomql(),
        now=NOW,
    )
    assert result.text == PLATFORM_HEALTH_REPLY


@pytest.mark.asyncio
async def test_alarms_on_focus_playbook_calls_graphql_before_model():
    store = MemoryConversationStore()
    conv = await store.create("alice", now=NOW)
    queries = []

    class Exec:
        async def fetch(self, sql, params):
            raise AssertionError("no sql expected for alarms_on_focus")

    class Graphql:
        async def post(self, query, variables, token):
            queries.append(query)
            return {"data": {"getAlertRules": [], "getUnsNodes": []}}

    model = ScriptedModel([
        ModelTurn(text="No Alert Rules are firing on that Asset.", tool_calls=(), citations=()),
    ])
    result = await run_turn(
        store=store,
        conversation_id=conv.id,
        subject="alice",
        token="t",
        message="Is P101 in alarm?",
        context=PageContext("/alerts", "Acme/P101", "", ""),
        scope=Scope(True, frozenset()),
        model=model,
        sql_execute=Exec(),
        graphql=Graphql(),
        now=NOW,
    )
    assert queries, "alarms_on_focus playbook must call GraphQL before the model"
    assert "firing" in result.text.lower()


def test_chat_returns_assistant_text():
    import asyncio

    from uns_factory_agent.chat import ChatResult

    store = MemoryConversationStore()
    conv = asyncio.run(store.create("alice", now=NOW))

    async def chat_handler(**_kwargs):
        return ChatResult(text="Pump flow is declining.", citations=())

    def get_identity(_header):
        return Identity(subject="alice", username="alice", roles=frozenset({"operator"}))

    client = TestClient(
        create_app(store, get_identity=get_identity, chat_handler=chat_handler),
    )
    body = client.post(
        "/chat",
        json={"message": "How is P101?", "conversationId": conv.id, "context": {}},
    ).json()
    assert body["text"] == "Pump flow is declining."
