# Factory Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Factory Copilot — a read-only plant colleague in a header drawer who turns questions into SQL/GraphQL tool calls and answers from live state, alarms, the Asset Model, and Timescale history.

**Architecture:** New stateless service `13_uns_factory_agent` (FastAPI on :8010) behind nginx/vite `/agent`. Four tools plus a `copilot` schema on `uns_historian` for the caller’s own threads. The console drawer is screenshot layout with this console’s dark / orange paint. OpenAI `gpt-4o` is mocked in CI.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy/asyncpg, PyJWT, httpx, OpenAI SDK, pytest; React 19, Vitest, existing console tokens. `frontend-design` for the bay.

**Spec:** `docs/superpowers/specs/2026-09-05-factory-copilot-design.md` (Approved)

## Global Constraints

- **Plant writes: none.** Conversation rows are the only writes, and only for the caller’s `Identity.subject`.
- **Four tools only:** `query_asset_model`, `query_historian`, `query_live`, `query_alarms`. No Cypher, MQTT, Kafka, Grafana, or `execute_sql`.
- **SQL:** one `SELECT` or `WITH … SELECT`; allowlisted tables; 5s timeout; 200-row cap; Access Group wrap except `admin`.
- **GraphQL tools forward the caller Bearer token.** No service account.
- **OpenAI `gpt-4o`.** Key in `conf/.secrets.yaml`. No live OpenAI in CI.
- **One-shot JSON.** No SSE.
- **Threads:** Postgres `copilot` on `uns_historian`; own only; 30 days from `updated_at`; user delete.
- **UI:** header drawer, not `#/copilot`. Screenshot layout + Oxanium / IBM Plex Mono / `#FF7A00`. No Inter, no purple, no forest-green island.
- **Job cards:** only live Metrics, alarms, last shift, Historic Events, downtime. No schedule/SOP copy.
- **Citations click:** historian → `#/historian` + `jumpToHistorian`; alarms → `#/alerts`; Asset/live → `#/condition-monitoring` + `jumpToTopicInTree`. Bay stays open.
- **Container publishes no host port.** Browser reaches it via `/agent` on the console origin (nginx 8088; vite proxies `/agent` to `http://localhost:8088`).
- **Domain words:** Unified Namespace, UNS Node, Historic Event, Metric, Asset, Alert Rule, Access Group, Console Role, Identity. Avoid “signal”, “tag”, “namespace” as synonyms.

---

## File Structure

```
13_uns_factory_agent/
  pyproject.toml                         CREATE  uns_factory_agent package
  Dockerfile                             CREATE  python:3.14-alpine, port 8010
  README.md                              CREATE
  src/uns_factory_agent/
    __init__.py                          CREATE
    sql_guard.py                         CREATE  parse + allowlist
    scope_sql.py                         CREATE  Access Group wrap
    schema_cards.py                      CREATE  curated tool schemas
    conversations.py                     CREATE  list/get/add/delete/purge
    tools_sql.py                         CREATE  query_asset_model / query_historian
    tools_graphql.py                     CREATE  query_live / query_alarms
    chat.py                              CREATE  mocked-model loop + persist
    auth.py                              CREATE  bearer → Identity (JWKS)
    app.py                               CREATE  FastAPI /health /conversations /chat
    health.py                            CREATE
    config.py                            CREATE  settings + secrets
  test/
    test_sql_guard.py                    CREATE
    test_scope_sql.py                    CREATE
    test_conversations.py                CREATE
    test_app_auth.py                     CREATE
    test_conversations_http.py           CREATE
    test_tools_sql.py                    CREATE
    test_tools_graphql.py                CREATE
    test_chat.py                         CREATE
    test_health.py                       CREATE
    keys.py                              CREATE  copy pattern from 07_uns_graphql/test/auth/keys.py

11_frontend/src/components/copilot/
  copilotContext.ts                      CREATE
  copilotContext.test.ts                 CREATE
  copilotApi.ts                          CREATE
  copilotApi.test.ts                     CREATE
  jobCards.ts                            CREATE
  jobCards.test.ts                       CREATE
  citationJump.ts                        CREATE
  citationJump.test.ts                   CREATE
  FactoryCopilotDrawer.tsx               CREATE
  FactoryCopilotDrawer.test.tsx          CREATE
  FactoryCopilotButton.tsx               CREATE

11_frontend/src/components/common/Header.tsx          MODIFY  Copilot button left of Bookmarks
11_frontend/src/components/layout/AppLayout.tsx        MODIFY  mount drawer
11_frontend/src/lib/platform/config.ts                 MODIFY  agentProxyTarget type
11_frontend/platform/settings.ts                       MODIFY  agentProxyTarget = localhost:8088
11_frontend/vite.config.ts                             MODIFY  /agent proxy
11_frontend/nginx.conf                                 MODIFY  location /agent/
conf/settings.yaml                                     MODIFY  applications.factory_agent + factory_agent:
conf/.secrets.yaml                                     MODIFY  factory_agent.openai_api_key placeholder
docker-compose.yml                                     MODIFY  factory_agent service
pyproject.toml                                         MODIFY  workspace member + testpaths
```

Do not invent a second chat UI, a `#/copilot` route, or a new Postgres instance.

---

### Task 1: SQL guard

**Files:**
- Create: `13_uns_factory_agent/pyproject.toml`
- Create: `13_uns_factory_agent/src/uns_factory_agent/__init__.py`
- Create: `13_uns_factory_agent/src/uns_factory_agent/sql_guard.py`
- Create: `13_uns_factory_agent/test/test_sql_guard.py`
- Create: `13_uns_factory_agent/README.md` (one paragraph: read-only Factory Copilot agent)
- Modify: `pyproject.toml` — add `uns_factory_agent` to `dependencies`, `[tool.uv.sources]`, `[tool.uv.workspace].members`, `testpaths`, `pythonpath`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `SQLGuardError(Exception)`
  - `ALLOWED_TABLES: frozenset[str]` = `{model.asset, model.metric_definition, model.access_group, model.access_group_member, model.access_group_asset, public.unifiednamespace, public.uns_metrics, oee.downtime_event}`
  - `guard_select(sql: str) -> str` — returns stripped SQL or raises `SQLGuardError`

`pyproject.toml` mirrors `12_uns_oee/pyproject.toml`: name `uns_factory_agent`, requires-python `>=3.14,<4`, deps `uns_config`, `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `httpx`, `pyjwt[crypto]`, `openai`, `dynaconf`. Hatch wheel from `src/uns_factory_agent`. pytest `testpaths = ["test"]`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from uns_factory_agent.sql_guard import SQLGuardError, guard_select


def test_accepts_a_select_on_uns_metrics():
    sql = "SELECT topic, value_double FROM uns_metrics WHERE topic LIKE 'Acme%' LIMIT 10"
    assert guard_select(sql) == sql


def test_accepts_qualified_model_asset():
    sql = "SELECT path, name FROM model.asset WHERE level = 'MACHINE'"
    assert guard_select(sql) == sql


def test_rejects_insert():
    with pytest.raises(SQLGuardError, match="SELECT"):
        guard_select("INSERT INTO uns_metrics (topic) VALUES ('x')")


def test_rejects_update():
    with pytest.raises(SQLGuardError, match="SELECT"):
        guard_select("UPDATE model.asset SET name = 'x'")


def test_rejects_delete():
    with pytest.raises(SQLGuardError, match="SELECT"):
        guard_select("DELETE FROM model.asset")


def test_rejects_second_statement():
    with pytest.raises(SQLGuardError, match="one statement"):
        guard_select("SELECT 1 FROM uns_metrics; DELETE FROM uns_metrics")


def test_rejects_unknown_table():
    with pytest.raises(SQLGuardError, match="allowlist"):
        guard_select("SELECT * FROM pg_stat_activity")


def test_rejects_copilot_schema():
    with pytest.raises(SQLGuardError, match="allowlist"):
        guard_select("SELECT * FROM copilot.conversation")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 13_uns_factory_agent/test/test_sql_guard.py -v -n 0`

Expected: FAIL — `ModuleNotFoundError: uns_factory_agent` or collection error.

- [ ] **Step 3: Write minimal implementation**

`sql_guard.py`:

```python
from __future__ import annotations

import re

ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "model.asset",
        "model.metric_definition",
        "model.access_group",
        "model.access_group_member",
        "model.access_group_asset",
        "unifiednamespace",
        "public.unifiednamespace",
        "uns_metrics",
        "public.uns_metrics",
        "oee.downtime_event",
    }
)

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SQLGuardError(ValueError):
    """The statement is not a single allowlisted SELECT."""


def guard_select(sql: str) -> str:
    text = sql.strip()
    if not text:
        raise SQLGuardError("SQL is empty.")
    if ";" in text.rstrip(";"):
        raise SQLGuardError("Only one statement is allowed.")
    text = text.rstrip(";").strip()
    head = text.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise SQLGuardError("Only a SELECT (or WITH … SELECT) is allowed.")
    if re.search(r"\b(insert|update|delete|drop|alter|create|grant|truncate)\b", head):
        raise SQLGuardError("Only a SELECT (or WITH … SELECT) is allowed.")
    tables = _tables(text)
    if not tables:
        raise SQLGuardError("SELECT must name an allowlisted table.")
    unknown = tables - ALLOWED_TABLES
    if unknown:
        raise SQLGuardError(f"Table not on the allowlist: {', '.join(sorted(unknown))}")
    return text


def _tables(sql: str) -> set[str]:
    found: set[str] = set()
    tokens = re.findall(r"(?i)\b(?:from|join)\s+((?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*)", sql)
    for raw in tokens:
        found.add(raw.lower() if raw.lower() in ALLOWED_TABLES else raw.lower())
        found.add(raw.lower())
    return found
```

Wire `pyproject.toml` and root workspace as in File Structure. Empty `__init__.py`. Run `uv lock` at the repo root after adding the source.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 13_uns_factory_agent/test/test_sql_guard.py -v -n 0`

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent pyproject.toml uv.lock
git commit -m "feat(copilot): reject anything but an allowlisted SELECT."
```

---

### Task 2: Access Group SQL wrap

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/scope_sql.py`
- Create: `13_uns_factory_agent/test/test_scope_sql.py`

**Interfaces:**
- Consumes: `uns_model.access.covers` (do not reimplement prefix rules)
- Produces:
  - `Scope(unrestricted: bool, root_paths: frozenset[str])`
  - `scope_for(*, is_admin: bool, root_paths: frozenset[str]) -> Scope`
  - `wrap_select(sql: str, scope: Scope, *, path_column: str) -> str`
    - `admin` / `unrestricted`: return `sql` unchanged
    - else: wrap as `SELECT * FROM ({sql}) AS _scoped WHERE (` + OR of `covers` predicates on `path_column` + `)`
    - `path_column` is `path` for `model.asset` and `topic` for historian tables
  - `covers_sql(column: str, root: str) -> str` — `column = :root OR column LIKE :root || '/%'` using bound params collected on the wrap result
- Simpler locked shape (use this, not dynamic params in v1):

```python
@dataclass(frozen=True)
class ScopedSql:
    sql: str
    params: dict[str, str]


def wrap_select(sql: str, scope: Scope, *, path_column: str) -> ScopedSql:
    ...
```

Non-admin with roots `{"Acme/Plant/Filtration"}` and `path_column="topic"` produces params `p0="Acme/Plant/Filtration"` and SQL:

```sql
SELECT * FROM (
  <original>
) AS _scoped
WHERE (topic = :p0 OR topic LIKE :p0 || '/%')
```

Zero roots and not admin: `WHERE false` (no rows). Unmodelled topics stay hidden because they do not match a root (ADR-0010).

- [ ] **Step 1: Write the failing test**

```python
from uns_factory_agent.scope_sql import Scope, wrap_select


def test_admin_is_unscoped():
    scoped = wrap_select(
        "SELECT topic FROM uns_metrics",
        Scope(unrestricted=True, root_paths=frozenset()),
        path_column="topic",
    )
    assert scoped.sql == "SELECT topic FROM uns_metrics"
    assert scoped.params == {}


def test_operator_gains_a_prefix_filter():
    scoped = wrap_select(
        "SELECT topic FROM uns_metrics",
        Scope(unrestricted=False, root_paths=frozenset({"Acme/Plant/Filtration"})),
        path_column="topic",
    )
    assert "_scoped" in scoped.sql
    assert "topic = :p0" in scoped.sql
    assert scoped.params["p0"] == "Acme/Plant/Filtration"


def test_empty_roots_match_nothing():
    scoped = wrap_select(
        "SELECT path FROM model.asset",
        Scope(unrestricted=False, root_paths=frozenset()),
        path_column="path",
    )
    assert "WHERE false" in scoped.sql.lower() or "WHERE FALSE" in scoped.sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 13_uns_factory_agent/test/test_scope_sql.py -v -n 0`

Expected: FAIL — `ModuleNotFoundError: wrap_select`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scope:
    unrestricted: bool
    root_paths: frozenset[str]


@dataclass(frozen=True, slots=True)
class ScopedSql:
    sql: str
    params: dict[str, str]


def wrap_select(sql: str, scope: Scope, *, path_column: str) -> ScopedSql:
    if scope.unrestricted:
        return ScopedSql(sql=sql, params={})
    if not scope.root_paths:
        return ScopedSql(sql=f"SELECT * FROM ({sql}) AS _scoped WHERE false", params={})
    clauses: list[str] = []
    params: dict[str, str] = {}
    for i, root in enumerate(sorted(scope.root_paths)):
        key = f"p{i}"
        params[key] = root
        clauses.append(f"({path_column} = :{key} OR {path_column} LIKE :{key} || '/%')")
    joined = " OR ".join(clauses)
    return ScopedSql(sql=f"SELECT * FROM ({sql}) AS _scoped WHERE {joined}", params=params)
```

Do **not** use `LIKE` with an unescaped user root that contains `%` or `_` — roots come from `model.access_group_asset`, not the model. If a root contains `%`, still bind it; do not expand wildcards yourself.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 13_uns_factory_agent/test/test_scope_sql.py -v -n 0`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/scope_sql.py 13_uns_factory_agent/test/test_scope_sql.py
git commit -m "feat(copilot): wrap plant SQL with Access Group prefixes."
```

---

### Task 3: Conversation store

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/conversations.py`
- Create: `13_uns_factory_agent/test/test_conversations.py`

**Interfaces:**
- Consumes: nothing (in-memory first; Postgres adapter in Task 8)
- Produces:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Role = Literal["user", "assistant"]

@dataclass(frozen=True)
class Citation:
    asset: str
    topic: str
    time: str
    source: Literal["model", "historian", "live", "alarms"]

@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: Role
    body: str
    citations: tuple[Citation, ...]
    created_at: datetime

@dataclass(frozen=True)
class Conversation:
    id: str
    subject: str
    title: str
    created_at: datetime
    updated_at: datetime

class ConversationStore(Protocol):
    def list_for(self, subject: str, *, now: datetime) -> list[Conversation]: ...
    def get(self, conversation_id: str, subject: str, *, now: datetime) -> Conversation | None: ...
    def create(self, subject: str, *, now: datetime) -> Conversation: ...
    def delete(self, conversation_id: str, subject: str) -> bool: ...
    def append(self, conversation_id: str, subject: str, role: Role, body: str, citations: tuple[Citation, ...], *, now: datetime) -> Message: ...
    def last_messages(self, conversation_id: str, subject: str, *, limit: int = 20) -> list[Message]: ...
    def purge_expired(self, *, now: datetime) -> int: ...

class MemoryConversationStore:
    ...
```

Rules:
- `list_for` / `get` omit rows where `now - updated_at > 30 days`. `get` of an expired or foreign id returns `None` (HTTP layer maps to 404).
- `create` title is `New chat`. First `append` of a `user` line sets `title` to the first 60 characters of `body`.
- `append` updates `updated_at`.
- `delete` is False when the id is missing or owned by someone else (HTTP still 404).
- `purge_expired` deletes conversations (and their messages) older than 30 days.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime, timedelta

from uns_factory_agent.conversations import MemoryConversationStore

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
ALICE = "alice-subject"
BOB = "bob-subject"


def test_list_is_only_mine():
    store = MemoryConversationStore()
    mine = store.create(ALICE, now=NOW)
    store.create(BOB, now=NOW)
    assert [c.id for c in store.list_for(ALICE, now=NOW)] == [mine.id]


def test_get_foreign_is_none():
    store = MemoryConversationStore()
    theirs = store.create(BOB, now=NOW)
    assert store.get(theirs.id, ALICE, now=NOW) is None


def test_expired_is_hidden():
    store = MemoryConversationStore()
    old = store.create(ALICE, now=NOW - timedelta(days=31))
    assert store.list_for(ALICE, now=NOW) == []
    assert store.get(old.id, ALICE, now=NOW) is None


def test_first_user_line_becomes_title():
    store = MemoryConversationStore()
    conv = store.create(ALICE, now=NOW)
    store.append(conv.id, ALICE, "user", "What is in alarm on Dryer?", (), now=NOW)
    assert store.get(conv.id, ALICE, now=NOW).title == "What is in alarm on Dryer?"


def test_delete_foreign_is_false():
    store = MemoryConversationStore()
    theirs = store.create(BOB, now=NOW)
    assert store.delete(theirs.id, ALICE) is False
    assert store.get(theirs.id, BOB, now=NOW) is not None


def test_purge_expired_removes_old_threads():
    store = MemoryConversationStore()
    store.create(ALICE, now=NOW - timedelta(days=31))
    keep = store.create(ALICE, now=NOW)
    assert store.purge_expired(now=NOW) == 1
    assert [c.id for c in store.list_for(ALICE, now=NOW)] == [keep.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 13_uns_factory_agent/test/test_conversations.py -v -n 0`

Expected: FAIL — import error

- [ ] **Step 3: Write minimal implementation**

In-memory dicts keyed by id. Use `uuid.uuid4().hex` for ids. Keep messages in a list per conversation. Implement every method the tests call. 30 days = `timedelta(days=30)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 13_uns_factory_agent/test/test_conversations.py -v -n 0`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/conversations.py 13_uns_factory_agent/test/test_conversations.py
git commit -m "feat(copilot): store only the caller’s threads for 30 days."
```

---

### Task 4: HTTP gate and conversation routes

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/auth.py`
- Create: `13_uns_factory_agent/src/uns_factory_agent/app.py`
- Create: `13_uns_factory_agent/test/keys.py` — copy `07_uns_graphql/test/auth/keys.py` (`TestKey.mint`, `ISSUER`, `AUDIENCE`)
- Create: `13_uns_factory_agent/test/test_app_auth.py`
- Create: `13_uns_factory_agent/test/test_conversations_http.py`

**Interfaces:**
- Consumes: `Identity` shape (`subject`, `username`, `roles`) — duplicate the dataclass from `07_uns_graphql/src/uns_graphql/auth/token.py` (do **not** import `uns_graphql`; that pulls Neo4j). Copy `bearer_from_header`, `CONSOLE_ROLES`, and `identity_from_token` against a `JwksCache` protocol with `async def signing_key(self, kid: str)`.
- Produces FastAPI app:

```python
def create_app(store: ConversationStore, *, get_identity):
    # get_identity(authorization_header: str | None) -> Identity
    # raises AuthError
```

  - `GET /health` → `{ "status": "ok" }` (no auth). Degraded shape comes in Task 8.
  - `GET /conversations` → list of `{id, title, updatedAt}` for the caller, newest first
  - `POST /conversations` → new `{id, title, updatedAt}`
  - `GET /conversations/{id}` → `{id, title, updatedAt, messages: [...]}` or 404
  - `DELETE /conversations/{id}` → 204 or 404
  - Missing/bad Bearer → 401 `{"detail": "<AuthError sentence>"}`
  - Foreign or expired id → **404** (never 403)

- [ ] **Step 1: Write the failing tests**

```python
from fastapi.testclient import TestClient
from uns_factory_agent.app import create_app
from uns_factory_agent.auth import AuthError, Identity
from uns_factory_agent.conversations import MemoryConversationStore


def test_missing_bearer_is_401():
    def get_identity(header):
        raise AuthError("The request has no Authorization bearer token.")
    client = TestClient(create_app(MemoryConversationStore(), get_identity=get_identity))
    assert client.get("/conversations").status_code == 401


def test_list_returns_only_caller_threads():
    store = MemoryConversationStore()
    from datetime import UTC, datetime
    now = datetime(2026, 9, 6, tzinfo=UTC)
    store.create("alice-subject", now=now)
    store.create("bob-subject", now=now)

    def get_identity(header):
        return Identity(subject="alice-subject", username="alice", roles=frozenset({"operator"}))

    client = TestClient(create_app(store, get_identity=get_identity))
    body = client.get("/conversations").json()
    assert len(body) == 1
```

Plus: POST creates; GET foreign 404; DELETE foreign 404; DELETE mine 204.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest 13_uns_factory_agent/test/test_app_auth.py 13_uns_factory_agent/test/test_conversations_http.py -v -n 0`

Expected: FAIL — `create_app` missing

- [ ] **Step 3: Write minimal implementation**

FastAPI routes only. No `/chat` yet (Task 7). `GET /health` returns ok. Use `JSONResponse` 401 on `AuthError`. ISO timestamps in JSON as `updatedAt` (camelCase for the console).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest 13_uns_factory_agent/test/test_app_auth.py 13_uns_factory_agent/test/test_conversations_http.py -v -n 0`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/auth.py 13_uns_factory_agent/src/uns_factory_agent/app.py 13_uns_factory_agent/test
git commit -m "feat(copilot): gate conversations on the caller’s bearer token."
```

---

### Task 5: SQL tools

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/schema_cards.py`
- Create: `13_uns_factory_agent/src/uns_factory_agent/tools_sql.py`
- Create: `13_uns_factory_agent/test/test_tools_sql.py`

**Interfaces:**
- Consumes: `guard_select`, `wrap_select`, `Scope`
- Produces:

```python
class SqlExecutor(Protocol):
    async def fetch(self, sql: str, params: dict) -> list[dict]: ...

async def query_asset_model(sql: str, *, scope: Scope, execute: SqlExecutor) -> list[dict]:
    guarded = guard_select(sql)
    scoped = wrap_select(guarded, scope, path_column="path")
    rows = await execute.fetch(scoped.sql, scoped.params)
    return rows[:200]

async def query_historian(sql: str, *, scope: Scope, execute: SqlExecutor) -> list[dict]:
    guarded = guard_select(sql)
    scoped = wrap_select(guarded, scope, path_column="topic")
    rows = await execute.fetch(scoped.sql, scoped.params)
    return rows[:200]
```

`schema_cards.py` exports `SCHEMA_CARDS: dict[str, str]` — one card per tool. Historian card **must** say: last shift is the previous OEE shift window if `oee` shift rows exist, else the last 8 hours. Asset card lists `model.asset(path, name, level)` and `model.metric_definition`. Do not dump `information_schema`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from uns_factory_agent.scope_sql import Scope
from uns_factory_agent.sql_guard import SQLGuardError
from uns_factory_agent.tools_sql import query_historian


class FakeExec:
    def __init__(self):
        self.sql = None
        self.params = None

    async def fetch(self, sql, params):
        self.sql = sql
        self.params = params
        return [{"topic": "Acme/Plant/Filtration/L1/Dryer"}]


@pytest.mark.asyncio
async def test_historian_wraps_and_runs():
    exe = FakeExec()
    rows = await query_historian(
        "SELECT topic FROM uns_metrics",
        scope=Scope(unrestricted=False, root_paths=frozenset({"Acme/Plant/Filtration"})),
        execute=exe,
    )
    assert rows[0]["topic"].endswith("Dryer")
    assert "p0" in exe.params


@pytest.mark.asyncio
async def test_insert_never_reaches_execute():
    exe = FakeExec()
    with pytest.raises(SQLGuardError):
        await query_historian("INSERT INTO uns_metrics (topic) VALUES ('x')", scope=Scope(True, frozenset()), execute=exe)
    assert exe.sql is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 13_uns_factory_agent/test/test_tools_sql.py -v -n 0`

Expected: FAIL — import error

- [ ] **Step 3: Write minimal implementation** plus `schema_cards.py` strings (historian card includes the 8-hour / OEE shift sentence).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 13_uns_factory_agent/test/test_tools_sql.py -v -n 0`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/schema_cards.py 13_uns_factory_agent/src/uns_factory_agent/tools_sql.py 13_uns_factory_agent/test/test_tools_sql.py
git commit -m "feat(copilot): run allowlisted plant SQL through Access Groups."
```

---

### Task 6: GraphQL tools

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/tools_graphql.py`
- Create: `13_uns_factory_agent/test/test_tools_graphql.py`

**Interfaces:**
- Consumes: caller token (string)
- Produces:

```python
class GraphqlPost(Protocol):
    async def post(self, query: str, variables: dict, token: str) -> dict: ...

async def query_live(topics: list[str], *, token: str, client: GraphqlPost) -> list[dict]:
    # POST getUnsNodes(topics: [{topic}])
    ...

async def query_alarms(*, token: str, client: GraphqlPost, enabled_only: bool = True) -> list[dict]:
    # POST getAlertRules(enabledOnly)
    ...
```

Exact GraphQL (camelCase as the console already uses):

```graphql
query CopilotLive($topics: [MQTTTopicInput!]!) {
  getUnsNodes(topics: $topics) { namespace nodeName nodeType }
}

query CopilotAlarms($enabledOnly: Boolean!) {
  getAlertRules(enabledOnly: $enabledOnly) { id name topic severity enabled }
}
```

The tool **must** send `Authorization: Bearer <token>`. If `post` is called without that token, tests fail.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from uns_factory_agent.tools_graphql import query_alarms, query_live


class FakeGql:
    def __init__(self, payload):
        self.payload = payload
        self.token = None
        self.query = None

    async def post(self, query, variables, token):
        self.token = token
        self.query = query
        return self.payload


@pytest.mark.asyncio
async def test_live_forwards_the_caller_token():
    fake = FakeGql({"data": {"getUnsNodes": [{"namespace": "Acme/Plant", "nodeName": "Plant"}]}})
    rows = await query_live(["Acme/#"], token="caller.jwt", client=fake)
    assert fake.token == "caller.jwt"
    assert "getUnsNodes" in fake.query
    assert rows[0]["namespace"] == "Acme/Plant"


@pytest.mark.asyncio
async def test_alarms_forwards_the_caller_token():
    fake = FakeGql({"data": {"getAlertRules": [{"id": "r1", "topic": "Acme/Plant/L1", "severity": "HIGH"}]}})
    rows = await query_alarms(token="caller.jwt", client=fake)
    assert fake.token == "caller.jwt"
    assert rows[0]["id"] == "r1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 13_uns_factory_agent/test/test_tools_graphql.py -v -n 0`

Expected: FAIL — import error

- [ ] **Step 3: Write minimal implementation** — extract `data.getUnsNodes` / `data.getAlertRules`; on GraphQL `errors` raise a `GraphqlToolError` with the first message (no stack).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 13_uns_factory_agent/test/test_tools_graphql.py -v -n 0`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/tools_graphql.py 13_uns_factory_agent/test/test_tools_graphql.py
git commit -m "feat(copilot): query live UNS Nodes and Alert Rules with the caller token."
```

---

### Task 7: Chat loop (mocked model)

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/chat.py`
- Create: `13_uns_factory_agent/test/test_chat.py`
- Modify: `13_uns_factory_agent/src/uns_factory_agent/app.py` — add `POST /chat`

**Interfaces:**
- Consumes: store, four tools, `Scope`, page context
- Produces:

```python
@dataclass(frozen=True)
class PageContext:
    route: str
    asset_path: str
    metric_key: str
    alarm_topic: str

@dataclass(frozen=True)
class ChatResult:
    text: str
    citations: tuple[Citation, ...]

class ModelClient(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn: ...

@dataclass(frozen=True)
class ModelTurn:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    citations: tuple[Citation, ...]

@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict

async def run_turn(
    *,
    store: ConversationStore,
    conversation_id: str,
    subject: str,
    token: str,
    message: str,
    context: PageContext,
    scope: Scope,
    model: ModelClient,
    sql_execute: SqlExecutor,
    graphql: GraphqlPost,
    now,
) -> ChatResult:
```

Loop: append user message; build system prompt (persona + `SCHEMA_CARDS` + context); send last 20 messages; for each `ToolCall` dispatch to the matching tool (unknown name → tool error string; `query_asset_model` / `query_historian` / `query_live` / `query_alarms` only). After the model returns `text`, persist assistant message + citations. If the model asks to write/ack, the **test model** returns a refusal with no tool calls — production system prompt says he has no write tools.

`POST /chat` body: `{ "message": str, "conversationId": str, "context": { route, assetPath, metricKey, alarmTopic } }`. 404 if conversation missing/foreign. 401 without identity. Returns `{ "text": str, "citations": [...] }`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from datetime import UTC, datetime
from uns_factory_agent.chat import ModelTurn, PageContext, run_turn
from uns_factory_agent.conversations import MemoryConversationStore
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
    conv = store.create("alice", now=NOW)
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
    assert store.last_messages(conv.id, "alice")[-1].role == "assistant"


@pytest.mark.asyncio
async def test_historian_tool_is_dispatched():
    store = MemoryConversationStore()
    conv = store.create("alice", now=NOW)
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
```

Fill `...` with the same kwargs as the first test. Import `Citation`, `ToolCall`.

Also HTTP: `POST /chat` without bearer 401; foreign `conversationId` 404.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 13_uns_factory_agent/test/test_chat.py -v -n 0`

Expected: FAIL — import error

- [ ] **Step 3: Write `run_turn` and `/chat`.** System prompt (exact opening):

```
You are Factory Copilot, a plant colleague. Speak in first person, short sentences.
Cite Asset, topic, and time. If tools return nothing, say you cannot see it.
You cannot ack alarms, change Alert Rules, edit the Asset Model, or write values.
Use only these tools: query_asset_model, query_historian, query_live, query_alarms.
```

Then append schema cards and page context. Cap tool rounds at 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 13_uns_factory_agent/test/test_chat.py -v -n 0`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent/src/uns_factory_agent/chat.py 13_uns_factory_agent/src/uns_factory_agent/app.py 13_uns_factory_agent/test/test_chat.py
git commit -m "feat(copilot): answer from tool results, never from invented numbers."
```

---

### Task 8: Process wiring (Postgres, OpenAI, compose, nginx, vite)

**Files:**
- Create: `13_uns_factory_agent/src/uns_factory_agent/config.py`
- Create: `13_uns_factory_agent/src/uns_factory_agent/health.py`
- Create: `13_uns_factory_agent/src/uns_factory_agent/pg_store.py` — SQLAlchemy `ConversationStore` on schema `copilot`
- Create: `13_uns_factory_agent/src/uns_factory_agent/openai_model.py` — `OpenAIModelClient` implementing `ModelClient`
- Create: `13_uns_factory_agent/Dockerfile` — copy `12_uns_oee/Dockerfile` shape; `UNS_MODULE=13_uns_factory_agent`; `EXPOSE 8010`; entrypoint `uv run uvicorn uns_factory_agent.app:app --host 0.0.0.0 --port 8010`; healthcheck `uv run uns_factory_agent_health`
- Create: `13_uns_factory_agent/test/test_health.py`
- Modify: `docker-compose.yml` — service `factory_agent` (no host ports), `UNS_MODULE=13_uns_factory_agent`, historian + graphQL env, depends on `uns_timescale_db`, `tsdb_setup_script`, `asset_model_setup`, `graphql_server`, `uns_keycloak`
- Modify: `11_frontend/nginx.conf` — `location /agent/` before `location /`, variable upstream `factory_agent:8010`, `proxy_pass http://$agent_upstream:8010/` (trailing slash)
- Modify: `11_frontend/vite.config.ts` — `/agent` proxy to `platform.agentProxyTarget`
- Modify: `11_frontend/platform/settings.ts` + `11_frontend/src/lib/platform/config.ts` + `11_frontend/src/lib/platform/config.test.ts` — `agentProxyTarget: 'http://localhost:8088'`
- Modify: `conf/settings.yaml` — `applications.factory_agent.port: 8010` and

```yaml
  factory_agent:
    model: "gpt-4o"
    graphql_url: "http://localhost:8000/graphql"
```

- Modify: `conf/.secrets.yaml` — add under `default:`:

```yaml
  factory_agent:
    openai_api_key: "#<enter the OpenAI API key>"
```

Do not commit a real key.

**Postgres:** on startup `pg_store.ensure_schema(engine)` runs:

```sql
CREATE SCHEMA IF NOT EXISTS copilot;
CREATE TABLE IF NOT EXISTS copilot.conversation (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  title TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS copilot.message (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES copilot.conversation(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  body TEXT NOT NULL,
  citations JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS conversation_subject_updated ON copilot.conversation (subject, updated_at DESC);
```

Conversation role: reuse `uns_dbuser` for v1 (YAGNI — do not invent a second DB user this slice). Plant SQL also uses that user; **the SQL guard is what blocks writes**, plus `guard_select` before execute. Document that in `README.md`.

Health: `ok` if OpenAI key non-empty and non-placeholder (`#<enter`) and a `SELECT 1` works; else `{ "status": "degraded", "reason": "openai_key_missing" | "database_unreachable" }`. Compose healthcheck treats only `ok` as healthy so the console can still start (do **not** add `factory_agent` to `uns_frontend.depends_on` with `service_healthy` — a missing key must not block the console). Nginx will 502 the drawer; the drawer shows “Factory Copilot is unavailable.”

`openai_model.py`: `AsyncOpenAI(api_key=...).chat.completions.create(model=settings.model, messages=..., tools=OPENAI_TOOLS)`. Map tool calls into `ModelTurn`. Parse citations from a final JSON field if present; else empty citations (the loop may also accept `citations` on the last message content as a trailing JSON block). Locked: last assistant message is plain text; citations are a separate argument the model fills via a fifth **non-SQL** tool `submit_answer` `{ text, citations }` OR the HTTP layer accepts `citations` from a `citations` array the model puts in a known trailer. Simplest locked path: `ModelTurn.citations` parsed from tool `submit_answer`. Add `submit_answer` as an internal tool (not a data tool). Tests in Task 7 already pass citations on `ModelTurn` — `OpenAIModelClient` maps `submit_answer` to that.

- [ ] **Step 1: Write the failing health test**

```python
from uns_factory_agent.health import health_payload

def test_missing_key_is_degraded():
    body = health_payload(openai_key="#<enter the OpenAI API key>", db_ok=True)
    assert body["status"] == "degraded"
    assert body["reason"] == "openai_key_missing"

def test_ok_when_key_and_db_present():
    assert health_payload(openai_key="sk-test", db_ok=True)["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 13_uns_factory_agent/test/test_health.py -v -n 0`

Expected: FAIL

- [ ] **Step 3: Implement health, `create_app` default wiring, Dockerfile, compose, nginx, vite, settings, secrets placeholder.** `GET /health` uses `health_payload`.

Add `11_frontend/src/lib/platform/config.test.ts` assertion: `expect(platformConfig.agentProxyTarget).toBe('http://localhost:8088')`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest 13_uns_factory_agent/test/test_health.py -v -n 0`

Run: `cd 11_frontend && npx vitest run src/lib/platform/config.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_factory_agent docker-compose.yml 11_frontend/nginx.conf 11_frontend/vite.config.ts 11_frontend/platform/settings.ts 11_frontend/src/lib/platform/config.ts 11_frontend/src/lib/platform/config.test.ts conf/settings.yaml conf/.secrets.yaml
git commit -m "feat(copilot): run the agent as its own container behind /agent."
```

If `.secrets.yaml` is gitignored, commit only `settings.yaml` and document the new key in `13_uns_factory_agent/README.md`.

---

### Task 9: Console client (context, API, job cards, citation jump)

**Files:**
- Create: `11_frontend/src/components/copilot/copilotContext.ts`
- Create: `11_frontend/src/components/copilot/copilotContext.test.ts`
- Create: `11_frontend/src/components/copilot/copilotApi.ts`
- Create: `11_frontend/src/components/copilot/copilotApi.test.ts`
- Create: `11_frontend/src/components/copilot/jobCards.ts`
- Create: `11_frontend/src/components/copilot/jobCards.test.ts`
- Create: `11_frontend/src/components/copilot/citationJump.ts`
- Create: `11_frontend/src/components/copilot/citationJump.test.ts`

**Interfaces:**

```ts
export type CopilotSource = 'model' | 'historian' | 'live' | 'alarms';

export type PageContext = {
  route: string;
  assetPath: string;
  metricKey: string;
  alarmTopic: string;
};

export function pageContext(input: {
  pathname: string;
  selectedTopic?: string;
  selectedMetricKey?: string;
  selectedAlarmTopic?: string;
}): PageContext;

export const JOB_CARDS: { id: string; prompt: string }[];

export function citationTarget(source: CopilotSource): '#/historian' | '#/alerts/active' | '#/condition-monitoring';

export type CopilotConversation = { id: string; title: string; updatedAt: string };
export type CopilotCitation = { asset: string; topic: string; time: string; source: CopilotSource };
export type CopilotMessage = { role: 'user' | 'assistant'; body: string; citations: CopilotCitation[] };

export function agentHeaders(): HeadersInit; // Bearer from authClient.accessToken(), same as directory.ts
export function listConversations(): Promise<CopilotConversation[]>;
export function createConversation(): Promise<CopilotConversation>;
export function getConversation(id: string): Promise<{ id: string; title: string; updatedAt: string; messages: CopilotMessage[] }>;
export function deleteConversation(id: string): Promise<void>;
export function sendChat(body: { message: string; conversationId: string; context: PageContext }): Promise<{ text: string; citations: CopilotCitation[] }>;
```

`pageContext`: `assetPath` = `selectedTopic` if it looks like a path (contains `/`), else `''`. Empty selection → `assetPath: ''` (drawer chip shows `Plant · no Asset selected`). `route` is `pathname`.

`JOB_CARDS` exact prompts (spec §5):

1. `What is in alarm on the Asset I am looking at?`
2. `Last-shift Historic Events / downtime for this line.`
3. `Current Metric value versus the last eight hours.`
4. `Which Assets on this path have published in the last hour?`

API base path is `/agent` (vite/nginx). `sendChat` POSTs `/agent/chat`. 401 → throw `CopilotAuthError`. 502/unavailable → throw `CopilotUnavailableError`.

- [ ] **Step 1: Write the failing tests**

`jobCards.test.ts`: assert four prompts; `expect(JOB_CARDS.map(c => c.prompt).join(' ')).not.toMatch(/schedule|instruction|SOP|Brent|Hot Rolling/i)`.

`copilotContext.test.ts`: `{ pathname: '/alerts/active', selectedAlarmTopic: 'Acme/L1' }` → `alarmTopic` set; no selection → empty strings; chip helper `contextChip(ctx)` → `Plant · no Asset selected` when all empty, else the first non-empty of assetPath / metricKey / alarmTopic.

`citationJump.test.ts`: historian → `#/historian`; alarms → `#/alerts/active`; live/model → `#/condition-monitoring`.

`copilotApi.test.ts`: mock `fetch` + `authClient.accessToken` → `Bearer`; `sendChat` posts `/agent/chat` with `conversationId` and `context`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 11_frontend && npx vitest run src/components/copilot/jobCards.test.ts src/components/copilot/copilotContext.test.ts src/components/copilot/citationJump.test.ts src/components/copilot/copilotApi.test.ts`

Expected: FAIL — modules missing

- [ ] **Step 3: Write the four modules.** Reuse `authClient.accessToken()` from `11_frontend/src/lib/auth/oidc.ts` the same way `directory.ts` does.

- [ ] **Step 4: Run tests to verify they pass**

Run: same vitest command

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/copilot
git commit -m "feat(copilot): add the console client for context, jobs, and /agent."
```

---

### Task 10: Control-desk radio drawer

**Files:**
- Create: `11_frontend/src/components/copilot/FactoryCopilotButton.tsx`
- Create: `11_frontend/src/components/copilot/FactoryCopilotDrawer.tsx`
- Create: `11_frontend/src/components/copilot/FactoryCopilotDrawer.test.tsx`
- Modify: `11_frontend/src/components/common/Header.tsx` — render `FactoryCopilotButton` **left of** Bookmarks; new prop `onOpenCopilot: () => void`
- Modify: `11_frontend/src/components/layout/AppLayout.tsx` — `isCopilotOpen` state; mount `FactoryCopilotDrawer`

**UI (frontend-design, locked):**

- Overlay: existing `fixed inset-0 z-50 ... bg-black/70` pattern from `BookmarksDrawer`, panel `max-w-3xl` (`48rem`), `instrument-grain` / theme tokens, **not** `bg-white`.
- Left rail `w-44`: button `New chat +` (Oxanium, orange text), list of title + `toLocaleString()` datetime, X on each row.
- Nameplate: `FACTORY COPILOT` tracking-widest; 2px lamp `#FF7A00` (`data-testid="copilot-lamp"`). `data-state="idle"|"busy"|"down"`. Pulse only when `busy` (`animate-pulse`).
- Context chip under nameplate, mono, `data-testid="copilot-context"`.
- Empty thread: greeting `Hello, how can I help you today?` + 2×2 `JOB_CARDS` as rectangular stamps (`role="button"`), not rounded SaaS chips.
- His turns: left, Oxanium, `border-l-2 border-[#FF7A00]`. Yours: right, quieter surface.
- Citations: rectangular tickets, mono, `data-testid="copilot-citation"`. Click: `citationTarget` navigate + `jumpToHistorian` / `jumpToTopicInTree` when topic is set. **Do not close the drawer.**
- Composer: placeholder `Message Factory Copilot...`; send is a square hardware key (not a paper-plane on a gradient). Disabled while busy.
- Unavailable: `Factory Copilot is unavailable.` lamp `down`.
- Escape and nameplate X close the bay.

Follow `console-compact-layout`: no `PageToolbar`, no new `getPageHeading`.

- [ ] **Step 1: Write the failing drawer test**

Mock `copilotApi` (`listConversations`, `createConversation`, `sendChat`, `deleteConversation`, `getConversation`) and `useUNS` / `useAuth` / `useLocation`.

```tsx
it('opens from the header control and shows job cards on an empty thread', async () => { ... });
it('POSTs page context and conversationId on send', async () => { ... });
it('lists threads and deletes one', async () => { ... });
it('shows a spinner while the reply is in flight', async () => { ... });
it('renders citation tickets that navigate and leave the bay open', async () => { ... });
it('shows unavailable when sendChat throws CopilotUnavailableError', async () => { ... });
it('does not mention schedule or work instructions on the job cards', () => { ... });
```

Also a small Header test or include in the drawer test that `getByLabelText('Factory Copilot')` exists when Header is rendered with `onOpenCopilot`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 11_frontend && npx vitest run src/components/copilot/FactoryCopilotDrawer.test.tsx`

Expected: FAIL

- [ ] **Step 3: Implement button, drawer, Header, AppLayout.** Keep `BookmarksDrawer` markup out of this file — new JSX.

- [ ] **Step 4: Run tests and build**

Run: `cd 11_frontend && npx vitest run src/components/copilot && npm run build`

Expected: tests PASS; `tsc && vite build` PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/copilot 11_frontend/src/components/common/Header.tsx 11_frontend/src/components/layout/AppLayout.tsx
git commit -m "feat(copilot): open Factory Copilot from any console page."
```

---

## Self-review

**Spec coverage**

| Spec | Task |
|---|---|
| Separate scalable container, `/agent`, no host port | 8 |
| Four tools, SQL allowlist, Access Groups | 1, 2, 5, 6 |
| Live + alarms via GraphQL + caller token | 6, 7 |
| Timescale + Asset Model SQL | 5 |
| Own Postgres threads, 30 days, delete | 3, 4, 8 |
| OpenAI gpt-4o, mocked in CI | 7, 8 |
| One-shot JSON | 7, 10 |
| Drawer, screenshot layout, radio paint | 10 |
| Honest job cards | 9, 10 |
| Citation jumps, bay stays open | 9, 10 |
| Header on every signed-in page | 10 |
| Unavailable / 401 / 404 | 4, 7, 8, 10 |
| No `#/copilot`, no plant writes, no SSE | all (non-goals) |

**Placeholders:** none. **Types:** `Citation`, `PageContext`, `Scope`, `ConversationStore`, `ModelClient` are named once in Tasks 2–3 and reused.

---
