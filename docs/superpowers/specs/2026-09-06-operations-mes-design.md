# Operations cockpit (mini-MES)

Date: 2026-09-06
Modules: `13_uns_mes` (new), `98_sap_mock` (new), `11_frontend` (`components/operations`,
Connectivity SAP tab, `/mes` proxy), `docker-compose.yml`, `08_uns_observability`
(Prometheus scrape). Reads `model` and `oee` via existing services; does not extend
`07_uns_graphql` with order types.
Status: Approved
Extends: [OEE engine](./2026-09-01-oee-engine-design.md),
ADR-0008 (OEE computed, downtime reasons), ADR-0009 (OIDC)

A shop-floor Operations page in the console, backed by a separately scaled MES image.
Production orders come from SAP S/4HANA OData (or a mock that speaks the same). Operators
start, pause, resume, complete, and book OK/NOK. Start and complete post confirmations to
SAP. Downtime stays on the existing OEE events.

## 1. Problem

The console can show plant state and closed-shift OEE. It cannot run a shift: there is no
place to see the SAP order book, start an operation on a Machine, book yield, or post a
confirmation. Those jobs today live in a Worker Cockpit outside this platform.

Putting that work in `07_uns_graphql` would couple execution load to the platform read API.
Putting it in `12_uns_oee` would mix a batch calculator (ADR-0008) with a transactional
execution store. The cockpit needs its own image, its own schema, and a modular console
feature that reuses the Alarms route pattern and the compact layout primitives.

## 2. Goals

- One console feature **Operations** with four tab routes, each with real logic (not stubs).
- A new Docker image `13_uns_mes` that owns orders, operations, bookings, SAP connection,
  work-center binds, and the confirmation outbox. It scales independently of GraphQL.
- A mock S/4 OData service so `npm run stack` works without a live SAP system.
- Assets & Connectivity gains a **SAP** tab: endpoint, credentials, test, work-center →
  Machine binds.
- Operators type OK/NOK in the console. Those bookings become the complete confirmation.
- Downtimes tab reuses `downtimeEvents` / `assignDowntimeReason`. No second downtime store.
- Reuse: OEE shift calendar, Keycloak bearer, Console Roles, Access Groups, `FilterToolbar`
  / `SegmentTabs` / `PageStat compact`, Connectivity page chrome.

## 3. Non-goals

- Apply sequence / drag-to-reorder the shift queue.
- MES-owned downtime, or posting downtime to SAP.
- Extra SAP interfaces (BAPI/RFC, IDoc). The adapter is a seam; only S/4 OData ships.
- Creating or editing production orders in this console. SAP (or the mock) is the system
  of record for the order book.
- Deriving quantities from Unified Namespace counters.
- Live OEE gauges (ADR-0008 still holds).
- New GraphQL types for orders or operations.
- Writing to OPC UA, a PLC, or any process interface.

## 4. Architecture

```
Browser
  #/operations/*          → 11_frontend operations feature → /mes  → 13_uns_mes
  #/operations/downtime   → 11_frontend                    → /graphql → 07_uns_graphql → oee.*
  #/connectivity (SAP)    → 11_frontend                    → /mes  → 13_uns_mes

13_uns_mes
  reads  model.asset, model shift calendar (same Postgres as OEE)
  writes mes.*
  calls  SapAdapter  →  live S/4 OData  OR  98_sap_mock
```

`13_uns_mes` is a FastAPI service. The console proxies `/mes` in Vite and in nginx the
same way it proxies `/simulator`. Port **8100** inside the compose network; do not publish
it on the host by default. Prometheus metrics on **9096**.

`98_sap_mock` is a compose-only image. It is not in a production-style profile. MES reaches
it by service name. Nobody else calls it.

GraphQL `ConnectivityProtocol` stays `OPC_UA`. The SAP tab is UI on the Connectivity page
that talks to MES. That keeps S/4 credentials and binds out of the GraphQL schema.

`13_uns_mes` creates and migrates schema `mes` on startup. `09_uns_model` does not gain
MES tables.

## 5. Console routes and shell

| Tab | Hash route |
| --- | --- |
| Operation Management | `#/operations/management` |
| Machine Operations | `#/operations/machines` |
| Order Management | `#/operations/orders` |
| Downtimes | `#/operations/downtime` |

`#/operations` redirects to `#/operations/management`.

Sidebar: one **Operations** item in the main menu, next to Alarms. Feature key
`operations` (Core Navigation). App header title is **Operations** only — no in-page
title banner (`console-compact-layout`).

Tabs are `SegmentTabs` in an `OperationsLayout` + `<Outlet>` (copy the Alarms layout
seam, not the alarm KPIs).

### 5.1 Location and shift

Operation Management and Machine Operations share a session location:

- Header: Machine `display_name` (or segment) and Asset path, **Change location**, date
  stepper, shift stepper. Do not invent an inventory-number field.
- Change location lists MACHINE Assets the caller’s Access Groups allow.
- Location is held in `sessionStorage` so both shop-floor tabs see the same Machine until
  the operator changes it or the session ends.
- No Machine selected: blocking empty state, copy **Select a Machine to see this shift’s
  work**, primary action **Change location**. No tables.

Shift windows come from the existing OEE calendar (`conf/oee/shifts.yaml` / `model`
shift tables). “Selected shift” means operations whose planned or actual window overlaps
that shift on the selected Machine.

Order Management has no location header. Downtimes has no location header; it uses the
existing OEE Asset + time-range query.

### 5.2 Roles

Reuse Console Roles. MES validates the same Keycloak bearer GraphQL uses (ADR-0009).

| Action | Roles |
| --- | --- |
| Read operations, orders, SAP connection status | `viewer`, `auditor`, `operator`, `engineer`, `admin` |
| Start, pause, resume, complete, book OK/NOK | `operator`, `engineer`, `admin` |
| Assign downtime reason | existing GraphQL: `operator`, `engineer`, `admin` |
| Save SAP connection, test, bind work centers | existing Connectivity permission (`connectivity`) |

`viewer` and `auditor` see the pages and no write controls. MES rejects writes from
them; the UI hiding buttons is not the security boundary.

Access Groups hide Machines the caller cannot see. MES filters orders and operations by
the bound Asset’s Access Groups. An unbound (Unassigned) operation is visible on Order
Management to anyone who can read Operations — it has no Asset to check yet.

## 6. Domain and `mes` schema

Terms used here. Add to `CONTEXT.md` when this ships.

**Production Order:** A SAP production order imported into `mes`. Identity is the SAP
order number. This console does not create one.

**Operation:** One step on a Production Order (SAP operation number + work center +
target quantity + planned times). The executable unit on the shop floor.

**Work Center:** SAP’s resource code. Bound to exactly one MACHINE Asset per SAP
connection, or unbound.

**Booking:** An operator-entered OK or NOK quantity increment on an Operation. Local to
`mes` until Complete.

**Confirmation:** A payload posted to SAP. In this slice: **start** (operation began)
and **complete** (final OK/NOK + actual start/finish). Pause, resume, and Bookings do
not post.

**Outbox entry:** A Confirmation waiting to be sent. States: `pending`, `sent`, `failed`.

### 6.1 Operation status

`released` → `running` → `paused` → `running` → `completed`.

Imported operations start as `released` (or the SAP status mapped to that). `completed`
is terminal. There is no cancel in this slice.

Rules:

1. At most one Operation may be `running` per MACHINE Asset. A second Start is rejected
   with a readable error that names the order already running.
2. Start is rejected when the work center is unbound. Error copy: **Bind work center
   {code} to a Machine in Assets & Connectivity.**
3. Pause is allowed only from `running`. Resume is allowed only from `paused`. Either
   called in the wrong status is 409. Pause and resume do not touch SAP.
4. Complete when booked OK + NOK ≠ target requires `confirmQuantityGap: true` on the
   request. Without the flag, MES returns 409 and the UI shows the confirm dialog
   (“Target {n}, booked {m}. Complete anyway?”). Equal totals complete without the flag.
   Complete is allowed from `running` or `paused`.
5. Complete on an already `completed` operation is a no-op: no second Outbox entry.

### 6.2 Tables (schema `mes`)

- `sap_connection` — one active S/4 OData connection in this slice: name, base URL,
  client, credentials ref, poll interval (default 60s), last sync at/status.
- `work_center_bind` — `(connection_id, work_center_code) → asset_path` unique.
- `production_order` — SAP order number unique, material, material description,
  customer if present, target quantity, SAP status text, imported at.
- `operation` — SAP order + operation number unique, work center code, bound
  `asset_path` (nullable), local status, planned start/end, actual start/end, target
  quantity, last confirmation outbox state.
- `booking` — operation id, kind `ok` | `nok`, quantity, booked by, booked at.
- `confirmation_outbox` — id (UUID, idempotency key), kind `start` | `complete`,
  operation id, payload snapshot, state, attempt count, last error, sent at.

Credentials are not written to `settings.yaml`. Use the existing secrets mechanism
(`conf/.secrets.yaml` / env), referenced from `sap_connection`.

## 7. SAP adapter and mock

One interface, two implementations:

```
pull_orders() -> list[SapOrder]
post_start(idempotency_id, operation) -> None
post_complete(idempotency_id, operation, ok, nok, started_at, finished_at) -> None
```

Live implementation: S/4HANA OData (production order read + confirmation write). Exact
service names live in the adapter module, not in the console.

Mock implementation: HTTP client to `98_sap_mock`, same paths and payloads.

`98_sap_mock`:

- Seeds a small order book (enough rows for all four tabs: mapped and Unassigned,
  in-progress and finished, at least one late vs target end).
- `GET` production orders.
- `POST` start and complete confirmations keyed by the outbox UUID.
- Unknown order → 404. Replay of the same UUID → 200, no second apply.
- Accepts the MES service token or a shared compose secret; not published to the host.

Future SAP protocols (BAPI, IDoc) are new adapter classes behind the same interface.
The Connectivity SAP tab stays; it will grow a protocol field later. Do not leak
OData types into `mes.operation`.

Pull upserts by SAP order + operation number. Local status, bookings, and actual times
win if the operation is `running`, `paused`, or `completed`. A pull must not reset an
in-flight operation back to `released`.

## 8. MES HTTP API

All routes under `/mes`. Bearer required. JSON.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness (no auth) |
| GET | `/orders` | Order Management list + filters |
| GET | `/orders/{orderNumber}` | Order + operations (Details) |
| GET | `/operations` | Shop-floor lists (`assetPath`, `shiftStart`, `shiftEnd`, status) |
| POST | `/operations/{id}/start` | Start |
| POST | `/operations/{id}/pause` | Pause |
| POST | `/operations/{id}/resume` | Resume |
| POST | `/operations/{id}/complete` | Body: `{ confirmQuantityGap?: bool }` |
| POST | `/operations/{id}/bookings` | Body: `{ kind: ok\|nok, quantity: number }` |
| GET | `/sap/connection` | Current connection (secrets redacted) |
| PUT | `/sap/connection` | Save endpoint / client / credentials / poll |
| POST | `/sap/connection/test` | Dial adapter, return ok/error |
| POST | `/sap/connection/sync` | Pull now |
| GET | `/sap/work-centers` | Codes seen on imported operations + binds |
| PUT | `/sap/work-centers/{code}` | Bind to `assetPath` (MACHINE only) |
| DELETE | `/sap/work-centers/{code}` | Unbind |

Unassigned means `operation.asset_path` is null. Those rows appear on `GET /orders`
and are omitted from `GET /operations` (shop-floor queries are Asset-scoped).

## 9. Four tabs

Shared UI: status chip, progress (OK / NOK / target bar), outbox chip
(Pending / Sent / Failed), disabled-reason text, complete-gap dialog. Feature files
live under `11_frontend/src/components/operations/`. One MES client module
`11_frontend/src/services/mes/client.ts` (same idea as `services/simulator/client.ts`).

**Operation Management.** Selected-shift table (Released / Running / Paused overlapping
the shift on the session Machine) and Order pipeline (upcoming on that Machine).
Filters: material, status via `FilterToolbar`. Actions: start, pause, resume, complete,
book. No Apply sequence.

**Machine Operations.** Same location + shift. `CompactKpiRow`: downtime count for this
Asset + window (GraphQL `downtimeEvents` length), booked OK, booked NOK, clock. Active
section: at most one Running row. Pipeline below. Late target end is red.

**Order Management.** Plant-wide list. Filters: status, material, order, duration
(actual start → actual end, or actual start → now if still open; the filter is a
minimum duration). Columns: order, material, quantity, status, actual start/end, last
operation, progress, duration, expected end, Details. Unassigned rows visible; Start disabled with the bind
message. Details shows that order’s operations; writes still obey one-Running-per-Machine.

**Downtimes.** GraphQL only. Asset + range from the OEE calendar. Assign reason records
the signed-in Identity. No MES calls.

## 10. Connectivity SAP tab

On `#/connectivity`, add a **SAP** protocol tab beside OPC UA (the placeholder tabs
Modbus / S7 / … stay “not in this slice”). This tab is in-slice.

- Save / test connection (MES `PUT` + `POST .../test`).
- Bind table: work center code → Machine picker (MACHINE Assets only, Access Groups
  applied). Empty bind = Unassigned.
- Sync now. Last sync time and last error.

OPC UA browse/subscribe is unchanged and still GraphQL.

## 11. Failures

| Case | Behaviour |
| --- | --- |
| No Machine selected | Blocking empty state; no shop-floor tables |
| Unbound work center | On Order Management; Start disabled; bind message names the code |
| Second Start on a Machine | 409 naming the running order |
| Complete with gap, no flag | 409; UI opens the confirm dialog |
| MES unreachable | Page error + retry; no optimistic writes |
| S/4 or mock down | Shop floor writes succeed; outbox `pending` then `failed`; retry does not require re-complete |
| Duplicate confirmation | Same outbox UUID; adapter/mock apply once |
| Unauthorized write | 403 |
| Asset outside Access Groups | Omitted from lists; MES enforces |
| Complete already completed | 200 no-op, no new outbox row |
| Pull while operation in flight | Local status and bookings preserved |

Outbox worker retries `failed` with backoff. The row always shows the current outbox
state so the operator can see a confirmation that has not reached SAP.

## 12. Tests

Red-green. No UI or compose work until the MES state machine and adapter tests pass.

**`13_uns_mes`:** start/pause/resume/complete; one Running per `asset_path`; unbound
Start rejected; booking totals; complete without gap flag rejected when totals differ;
complete with flag allowed; completed is idempotent; outbox states; pull does not clobber
in-flight rows; Access Group filter; viewer cannot write.

**`98_sap_mock`:** list seed orders; start/complete; unknown order 404; same UUID twice
is one apply.

**`11_frontend`:** `#/operations` redirect and four tab routes; empty location; Unassigned
disabled + message; complete dialog copy; viewer has no write buttons; Downtimes module
imports the GraphQL client and not the MES client; SAP Connectivity tab calls `/mes`.

**Compose:** `mes_server` and `sap_mock` start; frontend `/mes` proxy; `sap_mock` absent
from a prod-style profile.

## 13. Compose and observability

- Service `mes_server`: build `13_uns_mes/Dockerfile`, depends on `uns_timescale_db`,
  `asset_model_setup`, `uns_keycloak`. Env: historian DSN, Keycloak issuer, mock/live
  adapter URL.
- Service `sap_mock`: build `98_sap_mock/Dockerfile`. No host port.
- `uns_frontend` depends on `mes_server`. nginx + Vite: `/mes` → `mes_server:8100`.
- Prometheus scrape `mes_server:9096`.

## 14. Later scale (explicitly not this spec)

Apply sequence; MES downtime and SAP downtime post; BAPI/RFC/IDoc adapters; UNS counter
bookings; more than one live SAP connection; Operation Output as a fifth tab.
