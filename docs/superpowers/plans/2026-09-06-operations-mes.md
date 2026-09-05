# Operations MES Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a console Operations feature with four tab routes, a separately scaled `13_uns_mes` API, and a `98_sap_mock` S/4 OData stand-in so the stack runs without a live SAP system.

**Architecture:** Pure operation state machine in `13_uns_mes`, persisted in Postgres schema `mes`. FastAPI on `/mes` (Keycloak bearer). Shop-floor tabs and the Connectivity SAP tab call MES; Downtimes stays on GraphQL `downtimeEvents` / `assignDowntimeReason`. Mock SAP speaks the same adapter contract as live S/4 OData.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy asyncio, PyJWT, pytest; React 19, TypeScript, Vite, Vitest, existing `console-ui` primitives. No new npm UI library.

**Spec:** `docs/superpowers/specs/2026-09-06-operations-mes-design.md`

## Global Constraints

- **Separate image.** Orders, bookings, start/pause/resume/complete, SAP connection, work-center binds, and the confirmation outbox live in `13_uns_mes`. Do not add order types to `07_uns_graphql`.
- **Downtime stays OEE.** `#/operations/downtime` uses GraphQL only. Do not create `mes.downtime_*`.
- **SAP is the order book.** This console does not create or edit Production Orders.
- **S/4 OData only.** One `SapAdapter` protocol; live and mock implement it. No BAPI/RFC/IDoc.
- **Operator bookings.** OK/NOK are typed in the console. Do not read UNS counters as quantity.
- **Confirmations:** enqueue `start` on Start and `complete` on Complete. Pause, resume, and bookings do not post.
- **One Running Operation per MACHINE `asset_path`.**
- **Unassigned:** work center with no bind is visible on Order Management; Start disabled with **Bind work center {code} to a Machine in Assets & Connectivity.**
- **Complete gap:** booked OK+NOK ≠ target requires `confirmQuantityGap: true` or HTTP 409.
- **Reuse:** OEE shift calendar, Keycloak bearer, Console Roles, Access Groups, `FilterToolbar` / `SegmentTabs` / `PageStat compact` / `PageContent fullWidth`. No in-page title banner. Header title **Operations**.
- **Routes:** `#/operations` → `#/operations/management`; also `/machines`, `/orders`, `/downtime`.
- **Roles:** read = all five Console Roles; write start/pause/resume/complete/book = `operator`/`engineer`/`admin`; SAP connection + binds = Connectivity permission; `viewer`/`auditor` have no write buttons and MES returns 403.
- **English only.** Every new behaviour gets a test. Python tests from the package that owns the file. Frontend tests from `11_frontend`.
- **Do not invent** an inventory-number field. Machine header is `display_name` (or segment) + Asset path.

---

## File Structure

```
13_uns_mes/
  pyproject.toml, Dockerfile, README.md, uv.lock
  src/uns_mes/
    __init__.py
    states.py              # pure apply(); no IO
    models.py              # dataclasses used by store + API
    store.py               # InMemoryStore then SQL
    adapter.py             # SapAdapter protocol + HttpSapAdapter
    outbox.py              # drain pending rows
    auth.py                # Identity + role gates
    api.py                 # FastAPI /mes
    main.py, health_check.py
  test/                    # pytest
98_sap_mock/
  pyproject.toml, Dockerfile
  src/uns_sap_mock/app.py
  test/
11_frontend/src/
  services/mes/client.ts
  components/operations/   # layout + four tabs + location
  components/connectivity/ # SAP tab
  App.tsx, Sidebar.tsx, Header.tsx, types/rbac.ts
11_frontend/nginx.conf, vite.config.ts, platform/settings.ts
docker-compose.yml
08_uns_observability/prometheus/prometheus.yml
root pyproject.toml        # workspace + pytest paths
CONTEXT.md                 # new glossary terms
```

Do not put MES tables in `09_uns_model` migrations. Do not publish `8100` or the mock port on the host by default.

---

### Task 1: Pure operation state machine

**Files:**

- Create: `13_uns_mes/src/uns_mes/__init__.py`
- Create: `13_uns_mes/src/uns_mes/models.py`
- Create: `13_uns_mes/src/uns_mes/states.py`
- Create: `13_uns_mes/test/test_states.py`
- Create: `13_uns_mes/pyproject.toml` (minimal package so pytest can import)
- Create: `13_uns_mes/README.md`

**Interfaces:**

- Consumes: nothing
- Produces:
  - `OperationStatus = Literal["released", "running", "paused", "completed"]`
  - `BookingKind = Literal["ok", "nok"]`
  - `OutboxKind = Literal["start", "complete"]`
  - `@dataclass(frozen=True, slots=True) class OperationSnapshot` with fields: `id: str`, `order_number: str`, `operation_number: str`, `work_center: str`, `asset_path: str | None`, `status: OperationStatus`, `target_qty: float`, `ok_qty: float`, `nok_qty: float`, `actual_start: datetime | None`, `actual_end: datetime | None`
  - `@dataclass(frozen=True, slots=True) class ApplyResult` with `operation: OperationSnapshot`, `outbox: tuple[OutboxKind, ...]`, `error: str | None`
  - `class ApplyError(ValueError)` — `error` is the operator-facing sentence
  - `def apply(command: str, op: OperationSnapshot, *, running_on_asset: str | None, confirm_quantity_gap: bool = False, now: datetime) -> ApplyResult`
  - Commands: `"start" | "pause" | "resume" | "complete"`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import UTC, datetime

import pytest

from uns_mes.models import OperationSnapshot
from uns_mes.states import apply

NOW = datetime(2026, 1, 9, 10, 21, tzinfo=UTC)


def _op(**overrides) -> OperationSnapshot:
    values = dict(
        id="op-1",
        order_number="202501092104033",
        operation_number="0010",
        work_center="HOTLINE",
        asset_path="CovestroAG/Dormagen/Production/Line1/Furnace",
        status="released",
        target_qty=70.0,
        ok_qty=0.0,
        nok_qty=0.0,
        actual_start=None,
        actual_end=None,
    )
    values.update(overrides)
    return OperationSnapshot(**values)


def test_start_sets_running_and_enqueues_start():
    result = apply("start", _op(), running_on_asset=None, now=NOW)
    assert result.error is None
    assert result.operation.status == "running"
    assert result.operation.actual_start == NOW
    assert result.outbox == ("start",)


def test_start_unbound_is_rejected():
    result = apply("start", _op(asset_path=None), running_on_asset=None, now=NOW)
    assert result.outbox == ()
    assert result.operation.status == "released"
    assert result.error == "Bind work center HOTLINE to a Machine in Assets & Connectivity."


def test_start_rejected_when_machine_already_running():
    result = apply(
        "start",
        _op(),
        running_on_asset="202501010000001",
        now=NOW,
    )
    assert result.outbox == ()
    assert "202501010000001" in (result.error or "")
    assert result.operation.status == "released"


def test_pause_and_resume_do_not_enqueue():
    running = apply("start", _op(), running_on_asset=None, now=NOW).operation
    paused = apply("pause", running, running_on_asset=None, now=NOW)
    assert paused.operation.status == "paused"
    assert paused.outbox == ()
    resumed = apply("resume", paused.operation, running_on_asset=None, now=NOW)
    assert resumed.operation.status == "running"
    assert resumed.outbox == ()


def test_pause_from_released_is_rejected():
    result = apply("pause", _op(), running_on_asset=None, now=NOW)
    assert result.error
    assert result.operation.status == "released"


def test_complete_equal_qty_enqueues_complete_without_flag():
    running = apply("start", _op(), running_on_asset=None, now=NOW).operation
    booked = running.__class__(**{**running.__dict__, "ok_qty": 70.0})
    result = apply("complete", booked, running_on_asset=None, now=NOW)
    assert result.error is None
    assert result.operation.status == "completed"
    assert result.operation.actual_end == NOW
    assert result.outbox == ("complete",)


def test_complete_gap_without_flag_is_rejected():
    running = apply("start", _op(), running_on_asset=None, now=NOW).operation
    booked = running.__class__(**{**running.__dict__, "ok_qty": 40.0})
    result = apply("complete", booked, running_on_asset=None, now=NOW)
    assert result.operation.status == "running"
    assert result.outbox == ()
    assert result.error


def test_complete_gap_with_flag_is_allowed():
    running = apply("start", _op(), running_on_asset=None, now=NOW).operation
    booked = running.__class__(**{**running.__dict__, "ok_qty": 40.0})
    result = apply(
        "complete", booked, running_on_asset=None, confirm_quantity_gap=True, now=NOW
    )
    assert result.error is None
    assert result.operation.status == "completed"
    assert result.outbox == ("complete",)


def test_complete_already_completed_is_noop():
    done = _op(status="completed", ok_qty=70.0, actual_start=NOW, actual_end=NOW)
    result = apply("complete", done, running_on_asset=None, now=NOW)
    assert result.error is None
    assert result.outbox == ()
    assert result.operation == done


def test_complete_from_paused_is_allowed():
    running = apply("start", _op(), running_on_asset=None, now=NOW).operation
    paused = apply("pause", running, running_on_asset=None, now=NOW).operation
    booked = paused.__class__(**{**paused.__dict__, "ok_qty": 70.0})
    result = apply("complete", booked, running_on_asset=None, now=NOW)
    assert result.operation.status == "completed"
    assert result.outbox == ("complete",)
```

`13_uns_mes/pyproject.toml` (enough to import):

```toml
[project]
name = "uns_mes"
version = "0.1.0"
description = "Shop-floor MES: SAP orders, operation execution, confirmation outbox"
requires-python = ">=3.14, <4"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/uns_mes"]

[tool.pytest.ini_options]
testpaths = ["test"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 13_uns_mes && uv run pytest test/test_states.py -v`

Expected: FAIL — `ModuleNotFoundError: uns_mes` or `apply` is not defined.

- [ ] **Step 3: Write minimal implementation**

`models.py`: frozen `OperationSnapshot` with the fields in Interfaces.

`states.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from uns_mes.models import OperationSnapshot, OutboxKind

WRITE_ROLES = frozenset({"operator", "engineer", "admin"})


@dataclass(frozen=True, slots=True)
class ApplyResult:
    operation: OperationSnapshot
    outbox: tuple[OutboxKind, ...]
    error: str | None


def apply(
    command: str,
    op: OperationSnapshot,
    *,
    running_on_asset: str | None,
    confirm_quantity_gap: bool = False,
    now: datetime,
) -> ApplyResult:
    if command == "start":
        if op.asset_path is None:
            return ApplyResult(
                op,
                (),
                f"Bind work center {op.work_center} to a Machine in Assets & Connectivity.",
            )
        if running_on_asset:
            return ApplyResult(
                op,
                (),
                f"{running_on_asset} is already running on this Machine.",
            )
        if op.status != "released":
            return ApplyResult(op, (), f"Cannot start an operation that is {op.status}.")
        return ApplyResult(
            replace(op, status="running", actual_start=now),
            ("start",),
            None,
        )
    if command == "pause":
        if op.status != "running":
            return ApplyResult(op, (), "Pause is only allowed when the operation is running.")
        return ApplyResult(replace(op, status="paused"), (), None)
    if command == "resume":
        if op.status != "paused":
            return ApplyResult(op, (), "Resume is only allowed when the operation is paused.")
        return ApplyResult(replace(op, status="running"), (), None)
    if command == "complete":
        if op.status == "completed":
            return ApplyResult(op, (), None)
        if op.status not in {"running", "paused"}:
            return ApplyResult(op, (), f"Cannot complete an operation that is {op.status}.")
        booked = op.ok_qty + op.nok_qty
        if booked != op.target_qty and not confirm_quantity_gap:
            return ApplyResult(
                op,
                (),
                f"Target {op.target_qty:g}, booked {booked:g}. Complete anyway?",
            )
        return ApplyResult(replace(op, status="completed", actual_end=now), ("complete",), None)
    return ApplyResult(op, (), f"Unknown command {command!r}.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_mes && uv run pytest test/test_states.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_mes
git commit -m "feat(mes): add pure operation state machine"
```

---

### Task 2: In-memory store, bookings, one-Running lookup

**Files:**

- Create: `13_uns_mes/src/uns_mes/store.py`
- Create: `13_uns_mes/test/test_store.py`
- Modify: `13_uns_mes/src/uns_mes/models.py` — add `Booking`, `OutboxEntry`

**Interfaces:**

- Consumes: `apply`, `OperationSnapshot`
- Produces:
  - `@dataclass(frozen=True, slots=True) class Booking` — `id, operation_id, kind: BookingKind, quantity: float, booked_by: str, booked_at: datetime`
  - `@dataclass(frozen=True, slots=True) class OutboxEntry` — `id: str` (UUID string), `kind: OutboxKind`, `operation_id: str`, `state: Literal["pending","sent","failed"]`, `payload: dict`, `attempt_count: int`, `last_error: str | None`, `sent_at: datetime | None`
  - `class InMemoryStore:`
    - `put_operation(op: OperationSnapshot) -> None`
    - `get_operation(id: str) -> OperationSnapshot | None`
    - `running_order_on(asset_path: str) -> str | None`  # order_number or None
    - `book(operation_id: str, kind: BookingKind, quantity: float, booked_by: str, now: datetime) -> OperationSnapshot`
    - `transition(operation_id: str, command: str, *, confirm_quantity_gap: bool, now: datetime) -> ApplyResult` — looks up running-on-asset, calls `apply`, persists, appends outbox rows
    - `pending_outbox() -> list[OutboxEntry]`
    - `list_operations(*, asset_path: str | None = None) -> list[OperationSnapshot]`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import UTC, datetime

import pytest

from uns_mes.models import OperationSnapshot
from uns_mes.store import InMemoryStore

NOW = datetime(2026, 1, 9, 10, 21, tzinfo=UTC)
ASSET = "CovestroAG/Dormagen/Production/Line1/Furnace"


def _op(id="op-1", order="ORD-1", **kw) -> OperationSnapshot:
    base = dict(
        id=id,
        order_number=order,
        operation_number="0010",
        work_center="HOTLINE",
        asset_path=ASSET,
        status="released",
        target_qty=70.0,
        ok_qty=0.0,
        nok_qty=0.0,
        actual_start=None,
        actual_end=None,
    )
    base.update(kw)
    return OperationSnapshot(**base)


def test_book_adds_to_ok_total():
    store = InMemoryStore()
    store.put_operation(_op())
    op = store.book("op-1", "ok", 10.0, "olga.operator", NOW)
    assert op.ok_qty == 10.0
    op = store.book("op-1", "nok", 2.0, "olga.operator", NOW)
    assert op.ok_qty == 10.0
    assert op.nok_qty == 2.0


def test_second_start_on_same_asset_is_rejected():
    store = InMemoryStore()
    store.put_operation(_op(id="a", order="ORD-A"))
    store.put_operation(_op(id="b", order="ORD-B"))
    first = store.transition("a", "start", confirm_quantity_gap=False, now=NOW)
    assert first.error is None
    second = store.transition("b", "start", confirm_quantity_gap=False, now=NOW)
    assert second.error
    assert "ORD-A" in second.error
    assert store.get_operation("b").status == "released"


def test_start_appends_pending_outbox():
    store = InMemoryStore()
    store.put_operation(_op())
    store.transition("op-1", "start", confirm_quantity_gap=False, now=NOW)
    pending = store.pending_outbox()
    assert [row.kind for row in pending] == ["start"]
    assert pending[0].state == "pending"
    assert pending[0].id  # uuid


def test_complete_already_completed_does_not_add_outbox():
    store = InMemoryStore()
    store.put_operation(_op())
    store.transition("op-1", "start", confirm_quantity_gap=False, now=NOW)
    store.book("op-1", "ok", 70.0, "olga.operator", NOW)
    store.transition("op-1", "complete", confirm_quantity_gap=False, now=NOW)
    before = len(store.pending_outbox())
    store.transition("op-1", "complete", confirm_quantity_gap=False, now=NOW)
    assert len(store.pending_outbox()) == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 13_uns_mes && uv run pytest test/test_store.py -v`

Expected: FAIL — `InMemoryStore` is not defined.

- [ ] **Step 3: Write minimal implementation**

`InMemoryStore` holds dicts of operations, bookings, and outbox. `book` adds a `Booking` and returns a replaced snapshot with updated totals. `transition` computes `running_on_asset` via `running_order_on` (skip the current id), calls `apply`, on success replaces the snapshot and for each `outbox` kind appends `OutboxEntry(id=str(uuid4()), state="pending", payload={"operation_id", "kind", "ok_qty", "nok_qty", "actual_start", "actual_end"})`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_mes && uv run pytest test/test_store.py test/test_states.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_mes
git commit -m "feat(mes): store bookings and enqueue confirmation outbox"
```

---

### Task 3: SapAdapter protocol and outbox drain

**Files:**

- Create: `13_uns_mes/src/uns_mes/adapter.py`
- Create: `13_uns_mes/src/uns_mes/outbox.py`
- Create: `13_uns_mes/test/test_outbox.py`

**Interfaces:**

- Consumes: `InMemoryStore`, `OutboxEntry`
- Produces:
  - `@dataclass(frozen=True) class SapOrder` — `order_number, operation_number, work_center, material, material_description, customer, target_qty, planned_start, planned_end, sap_status`
  - `class SapAdapter(Protocol):`
    - `async def pull_orders(self) -> list[SapOrder]`
    - `async def post_start(self, idempotency_id: str, operation: OperationSnapshot) -> None`
    - `async def post_complete(self, idempotency_id: str, operation: OperationSnapshot) -> None`
  - `class FakeSapAdapter` — records calls; `fail_next: str | None`; `seen_ids: set[str]` (second post with same id is a no-op success)
  - `async def drain_outbox(store: InMemoryStore, adapter: SapAdapter) -> None` — for each `pending`/`failed`, call adapter, mark `sent` or `failed` with `last_error`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from uns_mes.adapter import FakeSapAdapter
from uns_mes.models import OperationSnapshot
from uns_mes.outbox import drain_outbox
from uns_mes.store import InMemoryStore
from datetime import UTC, datetime

NOW = datetime(2026, 1, 9, 10, 21, tzinfo=UTC)
ASSET = "CovestroAG/Dormagen/Production/Line1/Furnace"


@pytest.mark.asyncio
async def test_drain_posts_start_once():
    store = InMemoryStore()
    store.put_operation(OperationSnapshot(
        id="op-1", order_number="ORD-1", operation_number="0010",
        work_center="HOTLINE", asset_path=ASSET, status="released",
        target_qty=70, ok_qty=0, nok_qty=0, actual_start=None, actual_end=None,
    ))
    store.transition("op-1", "start", confirm_quantity_gap=False, now=NOW)
    adapter = FakeSapAdapter()
    await drain_outbox(store, adapter)
    assert adapter.starts == ["op-1"]
    assert store.pending_outbox() == []
    await drain_outbox(store, adapter)
    assert adapter.starts == ["op-1"]


@pytest.mark.asyncio
async def test_adapter_failure_marks_failed_and_retries():
    store = InMemoryStore()
    store.put_operation(OperationSnapshot(
        id="op-1", order_number="ORD-1", operation_number="0010",
        work_center="HOTLINE", asset_path=ASSET, status="released",
        target_qty=70, ok_qty=0, nok_qty=0, actual_start=None, actual_end=None,
    ))
    store.transition("op-1", "start", confirm_quantity_gap=False, now=NOW)
    adapter = FakeSapAdapter(fail_next="down")
    await drain_outbox(store, adapter)
    row = store.all_outbox()[0]
    assert row.state == "failed"
    assert row.last_error == "down"
    adapter.fail_next = None
    await drain_outbox(store, adapter)
    assert store.all_outbox()[0].state == "sent"


@pytest.mark.asyncio
async def test_same_idempotency_id_is_one_apply():
    adapter = FakeSapAdapter()
    op = OperationSnapshot(
        id="op-1", order_number="ORD-1", operation_number="0010",
        work_center="HOTLINE", asset_path=ASSET, status="running",
        target_qty=70, ok_qty=0, nok_qty=0, actual_start=NOW, actual_end=None,
    )
    await adapter.post_start("same-id", op)
    await adapter.post_start("same-id", op)
    assert adapter.starts == ["op-1"]
```

Add `InMemoryStore.all_outbox()` and `mark_outbox(id, state, error=None)` if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 13_uns_mes && uv run pytest test/test_outbox.py -v`

Expected: FAIL — `drain_outbox` / `FakeSapAdapter` missing.

- [ ] **Step 3: Write minimal implementation**

`FakeSapAdapter.seen_ids` short-circuits. `drain_outbox` iterates `pending` then `failed`, calls `post_start` or `post_complete`, increments `attempt_count`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_mes && uv run pytest test/test_outbox.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_mes
git commit -m "feat(mes): drain confirmation outbox through SapAdapter"
```

---

### Task 4: `98_sap_mock` OData stand-in

**Files:**

- Create: `98_sap_mock/pyproject.toml`
- Create: `98_sap_mock/src/uns_sap_mock/app.py`
- Create: `98_sap_mock/src/uns_sap_mock/seed.py`
- Create: `98_sap_mock/test/test_app.py`
- Create: `98_sap_mock/Dockerfile` (copy `12_uns_oee/Dockerfile` shape: python 3.14 alpine, `uv sync`, ENTRYPOINT `uns_sap_mock`, no host port)

**Interfaces:**

- Consumes: nothing from MES (HTTP only)
- Produces:
  - `GET /sap/opu/odata/sap/API_PRODUCTION_ORDER_2_SRV/A_ProductionOrder` → JSON list of seed orders
  - `POST /sap/confirmations` body `{ "id": uuid, "kind": "start"|"complete", "orderNumber", "operationNumber", "ok", "nok" }`
  - Seed includes: one mapped `HOTLINE` order, one `UNBOUND` work-center order, one finished order, one late vs planned end
  - Unknown order → 404; same `id` twice → 200, `applied` stays 1

- [ ] **Step 1: Write the failing tests**

Use FastAPI `TestClient`. Assert seed length ≥ 4, distinct work centers include `HOTLINE` and `UNBOUND`, POST start 200, replay same id does not increment `applied`, unknown order 404.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 98_sap_mock && uv run pytest test/test_app.py -v`

Expected: FAIL — app missing.

- [ ] **Step 3: Write minimal FastAPI app + seed**

In-memory dicts. No Keycloak. Optional shared header `X-Mock-Token` if `UNS_sap_mock__token` is set; unset in compose default so MES can call it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 98_sap_mock && uv run pytest test/test_app.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 98_sap_mock
git commit -m "feat(sap-mock): seed S/4 OData orders and idempotent confirmations"
```

---

### Task 5: MES FastAPI health, auth gate, write routes

**Files:**

- Create: `13_uns_mes/src/uns_mes/auth.py`
- Create: `13_uns_mes/src/uns_mes/api.py`
- Create: `13_uns_mes/src/uns_mes/main.py`
- Create: `13_uns_mes/src/uns_mes/health_check.py`
- Create: `13_uns_mes/test/test_api_writes.py`
- Modify: `13_uns_mes/pyproject.toml` — add `fastapi`, `uvicorn`, `httpx` (test)

**Interfaces:**

- Consumes: `InMemoryStore.transition`, `InMemoryStore.book`
- Produces:
  - `@dataclass(frozen=True) class Identity` — `subject, username, roles: frozenset[str]` with `has_any`
  - `WRITE_ROLES = frozenset({"operator", "engineer", "admin"})`
  - `CONNECTIVITY_ROLES` = roles that have Connectivity in the console: `engineer`, `admin` (operator does not)
  - `create_app(store: InMemoryStore, identity: Identity | None = None)` — tests inject Identity; live app will resolve bearer in Task 6
  - Routes (all under prefix `/mes`):
    - `GET /health` — `{"status":"ok"}` no auth
    - `POST /operations/{id}/start|pause|resume|complete`
    - `POST /operations/{id}/bookings` body `{kind, quantity}`
  - Write without WRITE_ROLES → 403
  - `apply` error → 409 `{ "detail": error }`
  - Complete body `{ "confirmQuantityGap": bool }`

- [ ] **Step 1: Write the failing tests**

```python
from fastapi.testclient import TestClient
from uns_mes.api import create_app
from uns_mes.auth import Identity
from uns_mes.store import InMemoryStore
from uns_mes.models import OperationSnapshot

ASSET = "CovestroAG/Dormagen/Production/Line1/Furnace"
OP = OperationSnapshot(
    id="op-1", order_number="ORD-1", operation_number="0010",
    work_center="HOTLINE", asset_path=ASSET, status="released",
    target_qty=70, ok_qty=0, nok_qty=0, actual_start=None, actual_end=None,
)

def _client(roles=("operator",), store=None):
    store = store or InMemoryStore()
    store.put_operation(OP)
    app = create_app(store, Identity("s", "olga.operator", frozenset(roles)))
    return TestClient(app), store

def test_health_has_no_auth():
    app = create_app(InMemoryStore(), identity=None)
    assert TestClient(app).get("/mes/health").status_code == 200

def test_viewer_cannot_start():
    client, _ = _client(roles=("viewer",))
    assert client.post("/mes/operations/op-1/start").status_code == 403

def test_operator_start_and_book():
    client, store = _client()
    assert client.post("/mes/operations/op-1/start").status_code == 200
    r = client.post("/mes/operations/op-1/bookings", json={"kind": "ok", "quantity": 10})
    assert r.status_code == 200
    assert r.json()["okQty"] == 10

def test_complete_gap_without_flag_is_409():
    client, _ = _client()
    client.post("/mes/operations/op-1/start")
    client.post("/mes/operations/op-1/bookings", json={"kind": "ok", "quantity": 10})
    r = client.post("/mes/operations/op-1/complete", json={})
    assert r.status_code == 409
    r = client.post("/mes/operations/op-1/complete", json={"confirmQuantityGap": True})
    assert r.status_code == 200
```

JSON field names are camelCase to match the console (`okQty`, `confirmQuantityGap`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 13_uns_mes && uv run pytest test/test_api_writes.py -v`

Expected: FAIL — `create_app` missing.

- [ ] **Step 3: Write `create_app`**

FastAPI, `app.include_router(router, prefix="/mes")`. Dependency `require_write` checks `identity.has_any(WRITE_ROLES)`. Map snapshot to camelCase dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_mes && uv run pytest test/test_api_writes.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_mes
git commit -m "feat(mes): FastAPI write routes with role gate"
```

---

### Task 6: List APIs, Access Groups, pull upsert

**Files:**

- Modify: `13_uns_mes/src/uns_mes/api.py`
- Modify: `13_uns_mes/src/uns_mes/store.py` — `upsert_from_sap`, `list_orders`, `visible`
- Create: `13_uns_mes/test/test_api_lists.py`
- Create: `13_uns_mes/test/test_pull.py`

**Interfaces:**

- Consumes: `SapOrder`, `InMemoryStore`
- Produces:
  - `GET /mes/orders?status&material&order&minDurationHours`
  - `GET /mes/orders/{orderNumber}`
  - `GET /mes/operations?assetPath&status` — **omits** `asset_path is None`
  - `create_app(..., allowed_asset_paths: frozenset[str] | None = None)` — `None` means no extra filter (tests that do not care); when set, hide bound operations whose path is outside the set. Unassigned (`asset_path is None`) remain on `GET /orders`.
  - `store.upsert_from_sap(orders: list[SapOrder], binds: dict[str, str])` — insert/update released rows; **do not** change status/bookings/actuals when local status is `running`, `paused`, or `completed`. Set `asset_path` from `binds.get(work_center)`.
  - `POST /mes/sap/connection/sync` — `WRITE` not required; Connectivity roles only. Calls `adapter.pull_orders` then upsert.

- [ ] **Step 1: Write the failing tests**

Cover: operations list hides Unassigned; orders list shows Unassigned; Access Group hides another plant’s bound row; pull of a running operation does not reset status or ok_qty; pull of a new SAP order inserts `released` with bind applied.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 13_uns_mes && uv run pytest test/test_api_lists.py test/test_pull.py -v`

Expected: FAIL

- [ ] **Step 3: Implement list filters and upsert**

Duration: actual_start → actual_end, or actual_start → now if open. `minDurationHours` is a minimum.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_mes && uv run pytest test/ -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_mes
git commit -m "feat(mes): list orders and protect in-flight rows on SAP pull"
```

---

### Task 7: SAP connection + work-center binds

**Files:**

- Modify: `13_uns_mes/src/uns_mes/store.py` — `SapConnection`, binds
- Modify: `13_uns_mes/src/uns_mes/api.py`
- Create: `13_uns_mes/src/uns_mes/adapter.py` `HttpSapAdapter` (if not already) pointing at mock/live base URL
- Create: `13_uns_mes/test/test_sap_connection.py`

**Interfaces:**

- Produces:
  - `GET /mes/sap/connection` — redacted (`password` absent)
  - `PUT /mes/sap/connection` — `{ name, baseUrl, client, password, pollIntervalSeconds }` — Connectivity roles
  - `POST /mes/sap/connection/test` — adapter pull or HTTP GET; `{ ok, error }`
  - `GET /mes/sap/work-centers` — codes from imported operations + current bind
  - `PUT /mes/sap/work-centers/{code}` `{ assetPath }` — MACHINE path string; reject empty
  - `DELETE /mes/sap/work-centers/{code}`
  - After bind/unbind, refresh `operation.asset_path` for **released** operations only

- [ ] **Step 1: Write the failing tests**

Operator PUT connection → 403. Engineer PUT → 200, GET has no password. Bind `HOTLINE` → released op gains `assetPath`. Unbind → `assetPath` null. Running op bind change does not move `asset_path` (in-flight stays on the Machine it started on).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 13_uns_mes && uv run pytest test/test_sap_connection.py -v`

Expected: FAIL

- [ ] **Step 3: Implement connection + binds**

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_mes && uv run pytest test/ -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 13_uns_mes
git commit -m "feat(mes): SAP connection and work-center binds"
```

---

### Task 8: Compose, Docker, proxy, workspace

**Files:**

- Create: `13_uns_mes/Dockerfile` (clone `12_uns_oee/Dockerfile`: `UNS_MODULE=13_uns_mes`, copy `00_uns_config` + this src; ENTRYPOINT `uns_mes`; HEALTHCHECK `uns_mes_health`; no 8100 publish)
- Create: `13_uns_mes/src/uns_mes/main.py` uvicorn on `0.0.0.0:8100`
- Modify: `13_uns_mes/pyproject.toml` `[project.scripts] uns_mes`, `uns_mes_health`
- Create: `98_sap_mock/Dockerfile`
- Modify: `docker-compose.yml` — services `mes_server`, `sap_mock`
- Modify: `11_frontend/nginx.conf` — `location /mes` before `location /`
- Modify: `11_frontend/vite.config.ts` — proxy `/mes`
- Modify: `11_frontend/platform/settings.ts` — `mesProxyTarget`
- Modify: `11_frontend/src/lib/platform/config.test.ts` — default `/mes` path if you add one
- Modify: `08_uns_observability/prometheus/prometheus.yml` — `mes_server:9096`
- Modify: root `pyproject.toml` — workspace member `uns_mes`, pytest paths `13_uns_mes/test`, `98_sap_mock/test`
- Create: `13_uns_mes/test/test_deployment.py` — Dockerfile ENTRYPOINT and compose service names (copy `12_uns_oee/test/test_deployment.py` style)

**Interfaces:**

- Consumes: Task 5 `create_app`, Task 2 `InMemoryStore` method names
- Produces: compose service names `mes_server`, `sap_mock`; proxy path `/mes` → `mes_server:8100`; mock URL `http://sap_mock:8080` as default adapter base
- Also produces (same task — needed for a real container):
  - `class SqlStore` with the same public methods as `InMemoryStore`, schema `mes`, `CREATE SCHEMA IF NOT EXISTS` on startup
  - `identity_from_bearer(header, jwks)` in `auth.py` — copy the GraphQL rules (kid required, realm roles filtered to the five Console Roles). Tests mint HS256 tokens; do not import `uns_graphql`
  - `allowed_asset_paths_for(identity)` — reads Access Groups from schema `model` the same way GraphQL does; tests stub this function. Unassigned orders stay visible.

- [ ] **Step 1: Write the failing deployment and persistence tests**

Read `13_uns_mes/Dockerfile` and `docker-compose.yml` as text. Assert `UNS_MODULE="13_uns_mes"`, `uns_mes` entrypoint, `mes_server:` and `sap_mock:` keys, nginx `location /mes`, prometheus `9096`.

Add `test/test_sql_store.py`: put + get an operation through `SqlStore` on SQLite (`sqlite+aiosqlite:///:memory:` is fine in tests). Add `test/test_auth.py`: token without `kid` → `AuthError` with the GraphQL sentence **The token names no signing key (no `kid` header).**; viewer token cannot pass `require_write`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 13_uns_mes && uv run pytest test/test_deployment.py -v`

Expected: FAIL — compose/nginx snippets missing.

- [ ] **Step 3: Wire compose + Docker + proxies**

`mes_server` environment:

```
UNS_MODULE: 13_uns_mes
UNS_historian__hostname: uns_timescale_db
UNS_historian__database: uns_historian
UNS_historian__username: uns_dbuser
UNS_historian__password: ${UNS_historian__password}
UNS_mes__metrics_port: 9096
UNS_mes__adapter_url: http://sap_mock:8080
```

`depends_on`: `uns_timescale_db` healthy, `asset_model_setup` completed, `uns_keycloak` healthy, `sap_mock` started.

`uns_frontend.depends_on` add `mes_server`.

Do not publish `8100` or the mock port.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 13_uns_mes && uv run pytest test/test_deployment.py test/test_sql_store.py test/test_auth.py -v`

Expected: PASS. `main.py` uses `SqlStore` + JWKS in compose; unit tests keep `InMemoryStore` + injected `Identity`.

- [ ] **Step 5: Commit**

```bash
git add 13_uns_mes 98_sap_mock docker-compose.yml 11_frontend/nginx.conf 11_frontend/vite.config.ts 11_frontend/platform/settings.ts 08_uns_observability/prometheus/prometheus.yml pyproject.toml
git commit -m "feat(mes): compose mes_server and sap_mock behind /mes"
```

---

### Task 9: Console shell — routes, header, sidebar, RBAC, location

**Files:**

- Modify: `11_frontend/src/types/rbac.ts` — add `operations` to `FeatureKey`, `SYSTEM_FEATURES`, every `defaultPermissions` (`true` for all five roles)
- Modify: `11_frontend/src/App.tsx`
- Modify: `11_frontend/src/App.redirect.test.tsx` — or create `11_frontend/src/App.operations.test.tsx`
- Modify: `11_frontend/src/components/layout/Sidebar.tsx` — MAIN_MENU item
- Modify: `11_frontend/src/components/common/Header.tsx` — `getPageHeading` `/operations` → `{ title: 'Operations' }`
- Create: `11_frontend/src/components/operations/operationsPaths.ts`
- Create: `11_frontend/src/components/operations/OperationsLayout.tsx`
- Create: `11_frontend/src/components/operations/useSessionLocation.ts`
- Create: `11_frontend/src/components/operations/useSessionLocation.test.ts`
- Create: `11_frontend/src/components/operations/LocationEmptyState.tsx`
- Create: `11_frontend/src/components/operations/OperationManagementView.tsx` (empty-state only this task)
- Create: `11_frontend/src/components/operations/MachineOperationsView.tsx` (empty-state only)
- Create: `11_frontend/src/components/operations/OrderManagementView.tsx` (placeholder heading `Orders`)
- Create: `11_frontend/src/components/operations/DowntimesView.tsx` (placeholder heading `Downtimes`)
- Modify: any `FeatureKey` exhaustiveness tests that list every key

**Interfaces:**

- Consumes: Alarms layout pattern (`SegmentTabs` + `Outlet`)
- Produces:
  - `OPERATIONS_TAB_PATHS = { management: '/operations/management', machines: '/operations/machines', orders: '/operations/orders', downtime: '/operations/downtime' }`
  - `useSessionLocation(): { assetPath: string | null, displayName: string | null, setLocation, clear }` keyed `sessionStorage` `uns_operations_location`
  - Tabs: Operation Management, Machine Operations, Order Management, Downtimes
  - Sidebar label **Operations**, `to: '/operations'`, `featureKey: 'operations'`, `tabId: 'operations'`

- [ ] **Step 1: Write the failing tests**

`useSessionLocation.test.ts`: default null; `setLocation` persists JSON `{ assetPath, displayName }`; `clear` removes it.

`App.operations.test.tsx` (read source like `App.redirect.test.tsx`):

```ts
expect(src).toMatch(/path="\/operations"/);
expect(src).toMatch(/operations\/management/);
expect(src).toMatch(/OperationsLayout/);
expect(header).toMatch(/title: 'Operations'/);
expect(sidebar).toMatch(/label: 'Operations'/);
expect(rbac).toMatch(/'operations'/);
```

`LocationEmptyState` test: render with no location, expect **Select a Machine to see this shift’s work** and a **Change location** button. Do not render a table (`queryByRole('table')` is null).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 11_frontend && npx vitest run src/App.operations.test.tsx src/components/operations/useSessionLocation.test.ts -v`

Expected: FAIL — files missing.

- [ ] **Step 3: Wire routes and empty state**

`App.tsx` inside `ProtectedConsoleLayout`:

```tsx
<Route path="/operations" element={<OperationsLayout />}>
  <Route index element={<Navigate to="management" replace />} />
  <Route path="management" element={<OperationManagementView />} />
  <Route path="machines" element={<MachineOperationsView />} />
  <Route path="orders" element={<OrderManagementView />} />
  <Route path="downtime" element={<DowntimesView />} />
</Route>
```

`OperationsLayout`: `PageShell` + `PageContent fullWidth` + `SegmentTabs` (hrefs, not local state). Shop-floor views call `useSessionLocation` and return `LocationEmptyState` when `assetPath` is null.

`canAccessTab('operations')` — add `operations` to the tab map in `roles.ts` / `AuthContext` the same way `alarms` is wired. Use `tabId: 'operations'` and `featureKey: 'operations'`. Do not invent a second permission table.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 11_frontend && npx vitest run src/App.operations.test.tsx src/components/operations/useSessionLocation.test.ts src/lib/auth -v`

Expected: PASS. Fix any `Record<FeatureKey, boolean>` compile errors by adding `operations` to every role.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src
git commit -m "feat(operations): add tab routes, sidebar, and location empty state"
```

---

### Task 10: MES client + Operation Management table

**Files:**

- Create: `11_frontend/src/services/mes/client.ts`
- Create: `11_frontend/src/services/mes/client.test.ts`
- Create: `11_frontend/src/types/operations.ts`
- Create: `11_frontend/src/components/operations/OperationTable.tsx`
- Create: `11_frontend/src/components/operations/CompleteGapDialog.tsx`
- Create: `11_frontend/src/components/operations/CompleteGapDialog.test.tsx`
- Modify: `11_frontend/src/components/operations/OperationManagementView.tsx`
- Create: `11_frontend/src/components/operations/OperationManagementView.test.tsx`

**Interfaces:**

- Consumes: `/mes` proxy; `useSessionLocation`
- Produces:
  - `type MesOperation` — camelCase matching API: `id, orderNumber, operationNumber, workCenter, assetPath, status, targetQty, okQty, nokQty, actualStart, actualEnd, plannedEnd, material, outboxState, disabledReason`
  - `class MesClient` constructor `(baseUrl = '/mes', token: string | null = null)` — same 404-HTML guard as `simulator/client.ts`
  - `listOperations({ assetPath, status? })`, `start(id)`, `pause(id)`, `resume(id)`, `complete(id, confirmQuantityGap?)`, `book(id, kind, quantity)`
  - `CompleteGapDialog` copy: `Target {n}, booked {m}. Complete anyway?`

- [ ] **Step 1: Write the failing tests**

`client.test.ts`: mock `fetch`; `complete(id)` POSTs `{}`; `complete(id, true)` POSTs `{ confirmQuantityGap: true }`; 409 body `detail` thrown.

`CompleteGapDialog.test.tsx`: shows the gap sentence; Confirm calls `onConfirm`.

`OperationManagementView.test.tsx`: with a location, mock client returns one released row; Start enabled. With `assetPath: null` on a row, Start disabled and text matches `/Bind work center HOTLINE/`. Viewer: no Start button (`canWrite` false). No `Apply sequence` string in the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 11_frontend && npx vitest run src/services/mes src/components/operations/CompleteGapDialog.test.tsx src/components/operations/OperationManagementView.test.tsx -v`

Expected: FAIL

- [ ] **Step 3: Implement client, table, management view**

Use `FilterToolbar` for material + status. Two sections: **Selected shift** (status Released/Running/Paused) and **Order pipeline** (Released only is fine if shift overlap is server-side; pass `assetPath` always). Attach bearer from `useAuth()` the same way GraphQL does.

On complete 409 whose `detail` includes `Complete anyway?`, open the dialog and retry with `confirmQuantityGap: true`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 11_frontend && npx vitest run src/services/mes src/components/operations -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src
git commit -m "feat(operations): Operation Management talks to /mes"
```

---

### Task 11: Machine Operations + Order Management

**Files:**

- Modify: `11_frontend/src/components/operations/MachineOperationsView.tsx`
- Create: `11_frontend/src/components/operations/MachineOperationsView.test.tsx`
- Modify: `11_frontend/src/components/operations/OrderManagementView.tsx`
- Create: `11_frontend/src/components/operations/OrderManagementView.test.tsx`
- Modify: `11_frontend/src/services/mes/client.ts` — `listOrders`, `getOrder`

**Interfaces:**

- Consumes: `MesClient`, `useSessionLocation`, GraphQL `downtimeEvents` for the KPI count only
- Produces:
  - Machine Operations: `CompactKpiRow` with compact `PageStat` — Downtimes (count), Actual Output (okQty sum), Output NOK, clock (`toLocaleTimeString`)
  - Active: rows with `status === 'running'` (at most one)
  - Pipeline: the rest for this Machine
  - Late: `plannedEnd < now` && not completed → red class
  - Order Management: no location header; `listOrders`; Unassigned row Start disabled + bind message; Details expands operations via `getOrder`
  - Filters: status, material, order, duration (`minDurationHours`)

- [ ] **Step 1: Write the failing tests**

Machine view without location: empty state, no table, no KPI **Actual Output**.

Machine view with location and one running row: **Active** contains the order number; Start on a second released row is disabled if you render it in Active (pipeline Start still shown).

Order Management: mock two orders, one `assetPath: null`; Unassigned has bind message; no **Select a Machine** empty state.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 11_frontend && npx vitest run src/components/operations/MachineOperationsView.test.tsx src/components/operations/OrderManagementView.test.tsx -v`

Expected: FAIL

- [ ] **Step 3: Implement both views**

Reuse `OperationTable` and `CompleteGapDialog`. Do not duplicate booking/complete logic — pass callbacks from a small `useOperationActions` hook next to the client if the views would otherwise copy paste.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 11_frontend && npx vitest run src/components/operations -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src
git commit -m "feat(operations): Machine Operations and Order Management"
```

---

### Task 12: Downtimes tab + Connectivity SAP tab + glossary

**Files:**

- Modify: `11_frontend/src/components/operations/DowntimesView.tsx`
- Create: `11_frontend/src/components/operations/DowntimesView.test.tsx`
- Modify: `11_frontend/src/lib/connectivity/map-servers.ts` — add `'sap'` to `ConnectivityTabId`, `PROTOCOL_TABS`, and `PROTOCOLS_IN_SLICE`
- Create: `11_frontend/src/components/connectivity/SapConnectionPanel.tsx`
- Create: `11_frontend/src/components/connectivity/SapConnectionPanel.test.tsx`
- Modify: `11_frontend/src/components/connectivity/ConnectivityView.tsx` — render `SapConnectionPanel` when tab is `sap`
- Modify: `11_frontend/src/services/mes/client.ts` — connection + bind methods
- Modify: `CONTEXT.md` — terms from spec §6
- Modify: `docs/superpowers/specs/2026-09-06-operations-mes-design.md` only if a name drifted (do not change decisions)

**Interfaces:**

- Consumes: GraphQL `downtimeEvents` / `assignDowntimeReason`; MES SAP endpoints
- Produces:
  - Downtimes: Asset select + OEE date range + table of events + reason assign. **File must not import** `services/mes/client`.
  - SAP panel: endpoint, client, password, Test, Sync, bind table (work center → Machine path input or existing Machine picker if Connectivity already has one — reuse, do not invent a second asset tree)

- [ ] **Step 1: Write the failing tests**

`DowntimesView.test.tsx`: read source, `expect(src).not.toMatch(/services\/mes/)`; render with mocked GraphQL showing one event; assign control present for operator.

`SapConnectionPanel.test.tsx`: Test button calls `POST /mes/sap/connection/test`; bind save calls `PUT /mes/sap/work-centers/HOTLINE`.

`map-servers` test if one exists: `isProtocolInSlice('sap') === true`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 11_frontend && npx vitest run src/components/operations/DowntimesView.test.tsx src/components/connectivity/SapConnectionPanel.test.tsx -v`

Expected: FAIL

- [ ] **Step 3: Implement Downtimes (GraphQL) and SAP panel (MES)**

Copy query/mutation names from `07_uns_graphql/schema/uns_schema.graphql`: `downtimeEvents(assetPath, from, to)`, `assignDowntimeReason(eventId, reasonCode, note)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 11_frontend && npx vitest run src/components/operations src/components/connectivity src/lib/connectivity -v`

Expected: PASS. Then `cd 11_frontend && npm run build` — Expected: success.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend CONTEXT.md
git commit -m "feat(operations): Downtimes via GraphQL and SAP connection tab"
```

---

## Spec coverage (self-review)

| Spec section | Task |
| --- | --- |
| §4 images, `/mes` proxy, 9096, mock compose-only | 8 |
| §5 routes, header, sidebar, location, roles | 9, 5 |
| §6 status machine, gap flag, one Running, unassigned copy | 1, 2 |
| §6.2 / §7 adapter + outbox + mock seed | 3, 4 |
| §8 HTTP API | 5, 6, 7 |
| §9 four tabs | 9–12 |
| §10 Connectivity SAP tab | 12 |
| §11 failures | 1, 2, 3, 5, 9, 10 |
| §12 tests | each task |
| §13 compose | 8 |
| §14 later scale | not tasked |

No TBD. Names stay `OperationSnapshot`, `apply`, `InMemoryStore`, `SapAdapter`, `drain_outbox`, `create_app`, `MesClient`, `OPERATIONS_TAB_PATHS`.
