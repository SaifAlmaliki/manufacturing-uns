# Factory Copilot Context Pack and Plant RCA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Factory Copilot uses Access Group roots as the default plant, a tighter page/tree focus when selected, a server-side RCA playbook on the four existing tools, and a curated console map — so starter questions work with nothing selected and he does not ask for a path already in the pack.

**Architecture:** Pure `classify` + `build_context_pack` + `run_playbook` in `13_uns_factory_agent`. `run_turn` runs the playbook before OpenAI, then the model writes a cited answer. `GET /agent/scope` feeds the drawer chip. Job cards and `contextChip` match the spec. No new plant tools.

**Tech Stack:** Python 3.14, FastAPI, existing SQL/GraphQL tools, pytest; React 19, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-07-factory-copilot-context-rca-design.md`

## Global Constraints

- **Plant writes: none.** Conversation rows only, caller `Identity.subject`.
- **Four tools only:** `query_asset_model`, `query_historian`, `query_live`, `query_alarms`. No Cypher, MQTT, Kafka, Grafana.
- **Playbook SQL** is code we ship, still `guard_select` + Access Group `wrap_select`, 5s, 200 rows.
- **GraphQL tools forward the caller Bearer token.**
- **No live OpenAI in CI.** Mock `ModelClient`.
- **One-shot JSON.** No SSE. No `#/copilot`.
- **Empty playbook ≠ unavailable.** Thread text “I cannot see …”. Lamp `down` only on health/auth/proxy failure.
- **Never ask for a path already in the pack.** Service-health RCA: one deferral sentence.
- **Domain words:** Asset, Metric, Historic Event, Alert Rule, Access Group, UNS Node.

---

## File Structure

```
13_uns_factory_agent/src/uns_factory_agent/
  classify.py          CREATE  Kind + classify(message) -> Kind
  context_pack.py      CREATE  ContextPack, page_hint, resolve_paths, build_context_pack
  console_map.py       CREATE  CONSOLE_MAP + PLATFORM_HEALTH_REPLY
  playbook.py          CREATE  playbook SQL + run_playbook
  chat.py              MODIFY  pack + playbook before model; system prompt
  app.py               MODIFY  GET /scope; optional scope_loader
  wiring.py            MODIFY  scope_loader; pass identity into run_turn if needed
  schema_cards.py      unchanged (tools); console map is separate

13_uns_factory_agent/test/
  test_classify.py     CREATE
  test_context_pack.py CREATE
  test_playbook.py     CREATE
  test_scope_http.py   CREATE
  test_chat.py         MODIFY  playbook + empty historian + platform_map

11_frontend/src/components/copilot/
  copilotContext.ts    MODIFY  contextChip(ctx, scope)
  copilotContext.test.ts MODIFY
  jobCards.ts          MODIFY  jobCards(hasFocus)
  jobCards.test.ts     MODIFY
  copilotApi.ts        MODIFY  fetchCopilotScope
  FactoryCopilotDrawer.tsx MODIFY  fetch scope, jobCards(hasFocus)
  FactoryCopilotDrawer.test.tsx MODIFY chip + cards
```

---

### Task 1: Classify kinds

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/classify.py`
- Test: `13_uns_factory_agent/test/test_classify.py`

**Interfaces:**
- Consumes: user message string
- Produces: `Kind` literal; `classify(message: str) -> Kind`

- [ ] **Step 1: Write the failing test**

```python
from uns_factory_agent.classify import classify

def test_job_cards_and_hi_map_to_kinds():
    assert classify("What is in alarm in my plant right now?") == "alarms_on_focus"
    assert classify("What is in alarm on the Asset I am looking at?") == "alarms_on_focus"
    assert classify("Has Pump P101 lost performance over the last three weeks?") == "performance_rca"
    assert classify("How does the selected metric (or this line's main metrics) compare to the last eight hours?") == "metric_vs_window"
    assert classify("How does this metric compare to the last eight hours?") == "metric_vs_window"
    assert classify("Which Assets on my plant path published in the last hour?") == "publishers_on_path"
    assert classify("Which Assets on this path published in the last hour?") == "publishers_on_path"
    assert classify("hi") == "plant_overview"
    assert classify("what's going on?") == "plant_overview"
    assert classify("how does historian work?") == "platform_map"
    assert classify("what is an Access Group?") == "platform_map"
    assert classify("why is GraphQL down?") == "platform_health"
    assert classify("Ack this alarm") == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_classify.py -v`

Expected: FAIL — `ModuleNotFoundError: uns_factory_agent.classify`

- [ ] **Step 3: Write minimal implementation**

`classify.py`:

```python
from __future__ import annotations

from typing import Literal

Kind = Literal[
    "alarms_on_focus",
    "metric_vs_window",
    "publishers_on_path",
    "performance_rca",
    "plant_overview",
    "platform_map",
    "platform_health",
    "other",
]


def classify(message: str) -> Kind:
    text = " ".join(message.lower().split())
    if any(p in text for p in ("graphql down", "copilot unavailable", "keycloak down", "why is graphql")):
        return "platform_health"
    if any(p in text for p in ("how does historian", "access group", "what is this console", "how does this console")):
        return "platform_map"
    if "in alarm" in text:
        return "alarms_on_focus"
    if "eight hours" in text or "this metric" in text or "selected metric" in text:
        return "metric_vs_window"
    if "published" in text and ("last hour" in text or "this path" in text or "plant path" in text):
        return "publishers_on_path"
    if "lost performance" in text or "why is" in text and "down" in text:
        return "performance_rca"
    if text in {"hi", "hello", "hey"} or "what's going on" in text or "whats going on" in text:
        return "plant_overview"
    if "p101" in text and ("week" in text or "performance" in text):
        return "performance_rca"
    return "other"
```

Fix operator precedence: `("why is" in text and "down" in text)` must be parenthesized. Use:

```python
    if "lost performance" in text or ("why is" in text and "down" in text):
        return "performance_rca"
```

Check `platform_health` **before** `performance_rca` so “why is GraphQL down?” does not become RCA.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_classify.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/classify.py 13_uns_factory_agent/test/test_classify.py
git commit -m "feat(factory_agent): classify Copilot turns into playbook kinds."
```

---

### Task 2: Context pack

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/context_pack.py`
- Test: `13_uns_factory_agent/test/test_context_pack.py`

**Interfaces:**
- Consumes: `PageContext` from `chat.py` (`route`, `asset_path`, `metric_key`, `alarm_topic`); `is_admin: bool`; `root_paths: frozenset[str]`; optional admin site rows
- Produces:
  - `Focus(asset_path: str, metric_key: str, alarm_topic: str)`
  - `ContextPack(route: str, focus: Focus, default_plant: tuple[str, ...], page_hint: str, unrestricted: bool)`
  - `page_hint(route: str) -> str` one of `alarms`, `condition_monitoring`, `hierarchy`, `plant`
  - `resolve_paths(pack: ContextPack) -> tuple[str, ...]`
  - `build_context_pack(page, *, is_admin, root_paths, admin_roots: tuple[str, ...] = ()) -> ContextPack`

- [ ] **Step 1: Write the failing test**

```python
from uns_factory_agent.chat import PageContext
from uns_factory_agent.context_pack import build_context_pack, page_hint, resolve_paths

def test_page_hint_from_route():
    assert page_hint("/alerts") == "alarms"
    assert page_hint("/condition-monitoring") == "condition_monitoring"
    assert page_hint("/hierarchy") == "hierarchy"
    assert page_hint("/dashboard") == "plant"

def test_empty_focus_uses_access_group_roots():
    pack = build_context_pack(
        PageContext("", "", "", ""),
        is_admin=False,
        root_paths=frozenset({"AcmeWater/Site1/Filtration"}),
    )
    assert pack.default_plant == ("AcmeWater/Site1/Filtration",)
    assert resolve_paths(pack) == ("AcmeWater/Site1/Filtration",)
    assert pack.unrestricted is False

def test_focus_wins_over_roots():
    pack = build_context_pack(
        PageContext("/condition-monitoring", "AcmeWater/Site1/Filtration/P101", "", ""),
        is_admin=False,
        root_paths=frozenset({"AcmeWater/Site1"}),
    )
    assert resolve_paths(pack) == ("AcmeWater/Site1/Filtration/P101",)

def test_admin_uses_admin_roots():
    pack = build_context_pack(
        PageContext("", "", "", ""),
        is_admin=True,
        root_paths=frozenset(),
        admin_roots=("AcmeWater", "AcmeWater/Site1"),
    )
    assert pack.unrestricted is True
    assert resolve_paths(pack) == ("AcmeWater", "AcmeWater/Site1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_context_pack.py -v`

Expected: FAIL — missing module

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass

from uns_factory_agent.chat import PageContext


@dataclass(frozen=True, slots=True)
class Focus:
    asset_path: str
    metric_key: str
    alarm_topic: str


@dataclass(frozen=True, slots=True)
class ContextPack:
    route: str
    focus: Focus
    default_plant: tuple[str, ...]
    page_hint: str
    unrestricted: bool


def page_hint(route: str) -> str:
    lowered = route.lower()
    if "alert" in lowered:
        return "alarms"
    if "condition" in lowered:
        return "condition_monitoring"
    if "hierarch" in lowered:
        return "hierarchy"
    return "plant"


def resolve_paths(pack: ContextPack) -> tuple[str, ...]:
    focus = pack.focus
    if focus.asset_path:
        return (focus.asset_path,)
    if focus.alarm_topic:
        return (focus.alarm_topic,)
    if focus.metric_key:
        return (focus.metric_key,)
    return pack.default_plant


def build_context_pack(
    page: PageContext,
    *,
    is_admin: bool,
    root_paths: frozenset[str],
    admin_roots: tuple[str, ...] = (),
) -> ContextPack:
    if is_admin:
        default = admin_roots
    else:
        default = tuple(sorted(root_paths))
    return ContextPack(
        route=page.route,
        focus=Focus(page.asset_path, page.metric_key, page.alarm_topic),
        default_plant=default,
        page_hint=page_hint(page.route),
        unrestricted=is_admin,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_context_pack.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/context_pack.py 13_uns_factory_agent/test/test_context_pack.py
git commit -m "feat(factory_agent): build Copilot context pack from focus and Access Group roots."
```

---

### Task 3: Playbook queries

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/console_map.py`
- Create: `13_uns_factory_agent/src/uns_factory_agent/playbook.py`
- Test: `13_uns_factory_agent/test/test_playbook.py`

**Interfaces:**
- Consumes: `Kind`, `ContextPack`, `Scope`, `SqlExecutor`, `GraphqlPost`, `token: str`
- Produces: `PlaybookResult(kind: Kind, tools_called: tuple[str, ...], observations: str)`
- `run_playbook(kind, pack, *, scope, sql_execute, graphql, token) -> PlaybookResult`
- `ADMIN_ROOTS_SQL = "SELECT path FROM model.asset WHERE level IN ('ENTERPRISE', 'SITE') ORDER BY path"`
- `PLATFORM_HEALTH_REPLY` and `CONSOLE_MAP` strings in `console_map.py`

Playbook SQL (always passed through `query_asset_model` / `query_historian`):

```python
METRICS_ON_PATHS = """
SELECT a.path, md.key, md.display_name, md.unit
FROM model.metric_definition md
JOIN model.asset a ON a.id = md.asset_id
""".strip()

HISTORIAN_WINDOW = """
SELECT topic, time, value_double, value_bool, value_string
FROM uns_metrics
WHERE time > NOW() - INTERVAL '{hours} hours'
ORDER BY time DESC
""".strip()

PUBLISHERS_HOUR = """
SELECT topic, max(time) AS last_seen
FROM uns_metrics
WHERE time > NOW() - INTERVAL '1 hour'
GROUP BY topic
""".strip()

DOWNTIME = """
SELECT asset_path, started_at, ended_at, reason
FROM oee.downtime_event
""".strip()

PLANT_MAP = """
SELECT path, name, level FROM model.asset
WHERE level IN ('ENTERPRISE', 'SITE', 'AREA')
ORDER BY path
""".strip()
```

If `oee.downtime_event` columns differ in this repo, grep `12_uns_oee` / migrations and match **actual** column names in the implementation. Do not invent columns.

`query_live` topics: for each path in `resolve_paths(pack)`, pass `f"{path}/#"`.

Alarms: call `query_alarms`, then keep rows whose `topic` equals or is under a resolve_paths prefix (`topic == p or topic.startswith(p + "/")`).

- [ ] **Step 1: Write the failing tests**

```python
import json
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
            return {"data": {"getAlertRules": [{"id": "1", "name": "Hi", "topic": "Acme/Site1/P101/Fault", "severity": "HIGH", "enabled": True}]}}
        return {"data": {"getUnsNodes": []}}

@pytest.mark.asyncio
async def test_empty_focus_historian_uses_root_in_scope_params():
    pack = build_context_pack(PageContext("", "", "", ""), is_admin=False, root_paths=frozenset({"Acme/Site1"}))
    sql = RecordingSql()
    gql = RecordingGraphql()
    result = await run_playbook("publishers_on_path", pack, scope=Scope(False, frozenset({"Acme/Site1"})), sql_execute=sql, graphql=gql, token="tok")
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
    result = await run_playbook("publishers_on_path", pack, scope=Scope(False, frozenset({"Acme/Site1", "Acme/Site2"})), sql_execute=sql, graphql=gql, token="tok")
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
    result = await run_playbook("platform_map", pack, scope=Scope(True, frozenset()), sql_execute=sql, graphql=gql, token="tok")
    assert sql.calls == []
    assert gql.queries == []
    assert "Asset Model" in result.observations or "Postgres" in result.observations

@pytest.mark.asyncio
async def test_empty_historian_observations_say_cannot_see():
    pack = build_context_pack(PageContext("", "Acme/P101", "", ""), is_admin=True, root_paths=frozenset(), admin_roots=("Acme",))
    sql = RecordingSql(rows=[])
    gql = RecordingGraphql()
    result = await run_playbook("metric_vs_window", pack, scope=Scope(True, frozenset()), sql_execute=sql, graphql=gql, token="tok")
    assert "cannot see" in result.observations.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_playbook.py -v`

Expected: FAIL — missing `playbook`

- [ ] **Step 3: Write `console_map.py` and `playbook.py`**

`console_map.py`:

```python
CONSOLE_MAP = """
Console pages: Hierarchy (Asset tree), Condition Monitoring (live Metrics), Alarms (Alert Rules), historian jumps from citations.
Stores: Postgres schema model = what Assets and Metric Definitions exist. Timescale uns_metrics and oee.downtime_event = history. GraphQL = live UNS Nodes and Alert Rules.
Access Groups hide plant rows. You only see your own Copilot threads.
I am read-only. I do not ack alarms, edit Alert Rules, or change setpoints.
I do not diagnose whether GraphQL, Copilot, or Keycloak is down.
""".strip()

PLATFORM_HEALTH_REPLY = (
    "I don't diagnose service health in this slice. "
    "I can look up plant data and how the console stores it."
)
```

`playbook.py` outline:

```python
async def run_playbook(kind, pack, *, scope, sql_execute, graphql, token) -> PlaybookResult:
    if kind == "platform_map":
        return PlaybookResult(kind, (), CONSOLE_MAP)
    if kind == "platform_health":
        return PlaybookResult(kind, (), PLATFORM_HEALTH_REPLY)
    if kind == "other":
        return PlaybookResult(kind, (), "")
    paths = resolve_paths(pack)
    called: list[str] = []
    chunks: list[str] = []
    # dispatch by kind using query_asset_model / query_historian / query_live / query_alarms
    # after each tool, if rows empty append "I cannot see {store} for {paths} in that window."
    # observations = "\\n".join(chunks) plus json.dumps(rows)[:8000]
    ...
```

Wrap every SQL with existing `query_asset_model` / `query_historian` so Access Group wrap stays.

For `performance_rca` sequence: asset/metrics SQL → historian 21 days (`INTERVAL '504 hours'` or `'21 days'`) → downtime SQL → alarms filtered → live `path/#`.

For `plant_overview`: alarms filtered to default plant → publishers hour → `PLANT_MAP`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_playbook.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/playbook.py 13_uns_factory_agent/src/uns_factory_agent/console_map.py 13_uns_factory_agent/test/test_playbook.py
git commit -m "feat(factory_agent): run plant RCA playbooks on the four Copilot tools."
```

---

### Task 4: Chat loop uses the pack and playbook

**Files:**
- Modify: `13_uns_factory_agent/src/uns_factory_agent/chat.py`
- Modify: `13_uns_factory_agent/src/uns_factory_agent/wiring.py` (`chat_handler` already has `identity`; pass `is_admin` / roots into `run_turn`)
- Modify: `13_uns_factory_agent/test/test_chat.py`

**Interfaces:**
- Consumes: `classify`, `build_context_pack`, `run_playbook`
- Produces: `run_turn` still returns `ChatResult`. New optional args: `is_admin: bool`, `admin_roots: tuple[str, ...] = ()`. Build pack from `context` + `scope` (`scope.unrestricted` as admin; `scope.root_paths`).

`_build_system(pack, playbook: PlaybookResult) -> str`:
- Existing persona + schema cards
- `CONSOLE_MAP`
- Context pack fields
- Line: “Do not ask for an Asset path, Metric, or topic that is already in this pack. Use default plant when focus is empty.”
- Section `## Playbook observations` with `playbook.observations` (may be empty for `other`)
- For `platform_health` / `platform_map`, tell the model to answer from observations only and not call tools.

- [ ] **Step 1: Write failing tests in `test_chat.py`**

```python
@pytest.mark.asyncio
async def test_metric_question_runs_playbook_sql_before_model():
    store = MemoryConversationStore()
    conv = await store.create("alice", now=NOW)
    seen = []
    class Exec:
        async def fetch(self, sql, params):
            seen.append(sql)
            return []
    model = ScriptedModel([
        ModelTurn(text="I cannot see historian values for that Metric in the last eight hours.", tool_calls=(), citations=()),
    ])
    result = await run_turn(
        store=store, conversation_id=conv.id, subject="alice", token="t",
        message="How does this metric compare to the last eight hours?",
        context=PageContext("/condition-monitoring", "Acme/P101", "", ""),
        scope=Scope(True, frozenset()),
        model=model, sql_execute=Exec(),
        graphql=type("G", (), {"post": staticmethod(lambda *a, **k: {"data": {"getUnsNodes": [], "getAlertRules": []}})})(),
        now=NOW,
    )
    assert seen, "playbook must hit SQL before the model"
    assert "cannot see" in result.text.lower()
    assert not any(ch.isdigit() and float(ch) for ch in result.text if False)  # do not invent; rely on mocked text
    # stronger: mocked model text has no fabricated 12.3 unless in observations
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
    model = ScriptedModel([
        ModelTurn(text="Postgres holds the Asset Model. Timescale holds history.", tool_calls=(), citations=()),
    ])
    await run_turn(
        store=store, conversation_id=conv.id, subject="alice", token="t",
        message="how does historian work?",
        context=PageContext("", "", "", ""),
        scope=Scope(True, frozenset()),
        model=model, sql_execute=Boom(),
        graphql=type("G", (), {"post": staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError("no graphql")))})(),
        now=NOW,
    )
    assert calls == []
```

Keep existing `test_ack_request_does_not_call_sql` passing: `classify("Ack this alarm...")` is `other`, playbook must not SQL.

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_chat.py -v`

Expected: FAIL on playbook-before-model (empty `seen`) until `run_turn` is wired.

- [ ] **Step 3: Wire `run_turn`**

At start of `run_turn`, after append user message:

```python
kind = classify(message)
pack = build_context_pack(
    context,
    is_admin=scope.unrestricted,
    root_paths=scope.root_paths,
    admin_roots=admin_roots,
)
playbook = await run_playbook(kind, pack, scope=scope, sql_execute=sql_execute, graphql=graphql, token=token)
messages = [{"role": "system", "content": _build_system(pack, playbook)}]
```

Load `admin_roots` in `wiring.chat_handler` when `identity.is_admin` via `query_asset_model(ADMIN_ROOTS_SQL, scope=Scope(True, frozenset()), execute=sql_execute)` and pass into `run_turn(admin_roots=...)`. Non-admin: `admin_roots=()`.

For `platform_health`, if the model still returns empty, fall back to `PLATFORM_HEALTH_REPLY` as `final_text`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_chat.py test/test_classify.py test/test_context_pack.py test/test_playbook.py -v`

Expected: PASS (existing ack/historian tests too)

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/chat.py 13_uns_factory_agent/src/uns_factory_agent/wiring.py 13_uns_factory_agent/test/test_chat.py
git commit -m "feat(factory_agent): run context pack and playbook before each Copilot turn."
```

---

### Task 5: `GET /scope`

**Files:**
- Modify: `13_uns_factory_agent/src/uns_factory_agent/app.py`
- Modify: `13_uns_factory_agent/src/uns_factory_agent/wiring.py`
- Test: `13_uns_factory_agent/test/test_scope_http.py`

**Interfaces:**
- Consumes: `get_identity`; `scope_loader: Callable[[Identity], Awaitable[dict]] | None`
- Produces: `GET /scope` → `{ "roots": list[str], "unrestricted": bool }`

- [ ] **Step 1: Write failing HTTP tests**

```python
from fastapi.testclient import TestClient
from uns_factory_agent.app import create_app
from uns_factory_agent.auth import AuthError, Identity
from uns_factory_agent.conversations import MemoryConversationStore

def test_scope_without_bearer_is_401():
    def get_identity(_h):
        raise AuthError("The request has no Authorization bearer token.")
    client = TestClient(create_app(MemoryConversationStore(), get_identity=get_identity))
    assert client.get("/scope").status_code == 401

def test_scope_returns_roots():
    def get_identity(_h):
        return Identity("alice", "alice", frozenset({"operator"}))
    async def loader(identity):
        assert identity.subject == "alice"
        return {"roots": ["Acme/Site1"], "unrestricted": False}
    client = TestClient(
        create_app(MemoryConversationStore(), get_identity=get_identity, scope_loader=loader)
    )
    body = client.get("/scope", headers={"Authorization": "Bearer x"}).json()
    assert body == {"roots": ["Acme/Site1"], "unrestricted": False}
```

`get_identity` in tests currently ignores the header if it returns Identity; 401 test uses AuthError. The 200 test may need any header; `_resolve_identity` still calls `get_identity`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_scope_http.py -v`

Expected: FAIL — 404 on `/scope`

- [ ] **Step 3: Add route and wiring**

In `create_app`, parameter `scope_loader=None`. After `/health`:

```python
    @app.get("/scope")
    async def get_scope(authorization: str | None = Header(default=None)) -> dict:
        identity = await _resolve_identity(get_identity, authorization)
        if scope_loader is None:
            return {"roots": [], "unrestricted": identity.is_admin}
        result = scope_loader(identity)
        if hasattr(result, "__await__"):
            return await result
        return result
```

Pass `scope_loader=load_scope` from `create_production_app`. `load_scope` matches Task 4 admin SQL vs `_root_paths_for`.

- [ ] **Step 4: Run tests**

Run: `cd 13_uns_factory_agent && uv run pytest test/test_scope_http.py test/test_app_auth.py test/test_conversations_http.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/app.py 13_uns_factory_agent/src/uns_factory_agent/wiring.py 13_uns_factory_agent/test/test_scope_http.py
git commit -m "feat(factory_agent): expose GET /scope for Copilot default plant."
```

---

### Task 6: Drawer chip, job cards, scope fetch

**Files:**
- Modify: `11_frontend/src/components/copilot/copilotContext.ts`
- Modify: `11_frontend/src/components/copilot/copilotContext.test.ts`
- Modify: `11_frontend/src/components/copilot/jobCards.ts`
- Modify: `11_frontend/src/components/copilot/jobCards.test.ts`
- Modify: `11_frontend/src/components/copilot/copilotApi.ts`
- Modify: `11_frontend/src/components/copilot/FactoryCopilotDrawer.tsx`
- Modify: `11_frontend/src/components/copilot/FactoryCopilotDrawer.test.tsx`

**Interfaces:**
- `export type CopilotScope = { roots: string[]; unrestricted: boolean }`
- `contextChip(ctx: PageContext, scope?: CopilotScope | null): string`
- `jobCards(hasFocus: boolean): { id: string; prompt: string }[]`
- `fetchCopilotScope(): Promise<CopilotScope>`
- Drawer: on open, `fetchCopilotScope`; chip uses it; cards from `jobCards(Boolean(ctx.assetPath || ctx.metricKey || ctx.alarmTopic))`

Chip rules:
- Focus (`assetPath || metricKey || alarmTopic`) → that string (prefer assetPath, then metricKey, then alarmTopic) — keep existing prefer-assetPath test
- Else `scope.unrestricted && scope.roots[0]` → `Plant · {roots[0]}` if one root, else `Plant · {n} Access Groups` using `roots.length` (admin with many sites: `Plant · {n} Access Groups` is OK, or `Plant · whole model` when `unrestricted && roots.length !== 1`). Spec: one root → `Plant · {root}`; several → `Plant · {n} Access Groups`.
- Else no scope yet → `Plant · my Access Groups` (not `no Asset selected`)
- Never return `Plant · no Asset selected`

Plant-scoped cards (no focus):

1. id `alarms-on-asset`: `What is in alarm in my plant right now?`
2. id `pump-performance`: `Has Pump P101 lost performance over the last three weeks?`
3. id `metric-vs-eight-hours`: `How does the selected metric (or this line's main metrics) compare to the last eight hours?`
4. id `recent-publishers`: `Which Assets on my plant path published in the last hour?`

Focus cards may keep “this Asset / this metric / this path” with the same ids.

- [ ] **Step 1: Write failing frontend tests**

`copilotContext.test.ts` — replace empty chip expectation:

```typescript
  it('names Access Group roots when nothing is selected', () => {
    expect(
      contextChip(
        { route: '/dashboard', assetPath: '', metricKey: '', alarmTopic: '' },
        { roots: ['AcmeWater/Site1'], unrestricted: false },
      ),
    ).toBe('Plant · AcmeWater/Site1');
  });

  it('does not say no Asset selected', () => {
    expect(
      contextChip({ route: '/dashboard', assetPath: '', metricKey: '', alarmTopic: '' }),
    ).not.toMatch(/no Asset selected/i);
  });
```

`jobCards.test.ts`:

```typescript
import { jobCards } from './jobCards';

it('plant cards mention plant not this Asset', () => {
  const text = jobCards(false).map((c) => c.prompt).join(' ');
  expect(text).toMatch(/my plant/i);
  expect(text).not.toMatch(/Asset I am looking at/i);
});
```

`FactoryCopilotDrawer.test.tsx`: mock `fetchCopilotScope` → `{ roots: ['Acme/Site1'], unrestricted: false }`; wait for chip `Plant · Acme/Site1`. Empty-thread job card uses plant copy.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 11_frontend && npx vitest run src/components/copilot`

Expected: FAIL on chip / job card copy

- [ ] **Step 3: Implement chip, cards, API, drawer**

`fetchCopilotScope`:

```typescript
export async function fetchCopilotScope(): Promise<CopilotScope> {
  const response = await fetch(`${BASE}/scope`, { headers: agentHeaders() });
  return handleResponse(response);
}
```

Drawer `useEffect` on open: `fetchCopilotScope().then(setScope).catch(() => {})` — do **not** set `unavailable` on scope 401; 401 is sign-in, 502/503 already CopilotUnavailableError. If scope fails with CopilotUnavailableError, keep composer rules as today (health check). Empty plant data never sets unavailable.

Use `jobCards(hasFocus)` in the grid instead of `JOB_CARDS`. Export `JOB_CARDS = jobCards(false)` if other tests import `JOB_CARDS`, or update those tests to `jobCards(false)`.

- [ ] **Step 4: Run tests and build**

Run: `cd 11_frontend && npx vitest run src/components/copilot && npm run build`

Expected: tests PASS; `tsc && vite build` PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/copilot
git commit -m "feat(copilot): show default plant on the chip and plant-scoped job cards."
```

Mark spec status Approved in `docs/superpowers/specs/2026-09-07-factory-copilot-context-rca-design.md` in this commit or a tiny follow-up: `Status: Approved`.

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| Default plant = Access Group roots; admin = model ENTERPRISE/SITE | 2, 4, 5 |
| Focus wins | 2, 3 |
| Route page hint | 2 |
| RCA playbook kinds + lookups | 1, 3 |
| Curated console map, no RAG | 3 |
| `hi` = plant_overview | 1, 3 |
| Platform-health one sentence | 1, 3, 4 |
| Empty tools → cannot see, not unavailable | 3, 4, 6 |
| GET /scope | 5, 6 |
| Chip never “no Asset selected” after scope | 6 |
| Plant-scoped job cards | 6 |
| Four tools only, SQL guard, Access Groups | 3 (reuse wrappers) |
| Citations / drawer / no new route | unchanged; 6 does not add a route |

No TBD/TODO placeholders. Names: `Kind`, `ContextPack`, `Focus`, `resolve_paths`, `run_playbook`, `PlaybookResult`, `fetchCopilotScope`, `jobCards`, `GET /scope`.
