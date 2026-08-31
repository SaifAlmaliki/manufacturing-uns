# Simulator control API and console route

Date: 2026-08-31
Modules: `99_simulator`, `11_frontend`, `conf`
Status: Approved, not yet implemented
Companion spec: `2026-08-31-simulator-production-facility-design.md` (sub-project A)

## 1. Problem

The simulator is a headless process. To change what it publishes you edit YAML and restart
a container; to find out what it is doing you read container logs. Once sub-project A grows
it to ~50 devices and ~400 signals across four sensor families, neither is workable — and
in particular, when a value looks wrong there is no way to see the plant state that produced
it.

This spec adds a control and observation surface, and a console route in `11_frontend` that
consumes it.

## 2. Findings that shape the design

Established by reading the code, not assumed:

1. **`11_frontend` talks only to GraphQL.** `App.tsx:4` states it as an invariant.
2. **`07_uns_graphql` has exactly five mutations, all of them Alert Rules.**
   `uns_graphql_app.py:109` builds `strawberry.Schema(query=Query, mutation=Mutation,
   subscription=Subscription, ...)`, and every mutation lives in
   `mutations/alert_rule.py`. Accepted ADR 0005 records the decision and states the
   boundary in its own words: "The mutation surface is deliberately narrow, and stays
   narrow. Process data is written by publishing to the broker." So a write path exists,
   it is one page's configuration, and the ADR that created it already says a test
   fixture's run control does not belong in it.
3. **The frontend cannot publish to MQTT.** `payload_publish` exists as a `FeatureKey`
   (`rbac.ts:17`, `:79`) with role defaults assigned (`:126`–`:210`) and no publish
   implementation behind it anywhere in `src/`.
4. **`nginx.conf` proxies `/graphql` only.**
5. **`client.ts:349` already exposes `subscribeMqttMessages(topics, onMessage)`**, and the
   `getMqttMessages` subscription takes topics as an argument. Live status therefore needs
   **no** change to the GraphQL server or the client.
6. **Mapper topic subscriptions are narrow.** `graphdb.mqtt.topics` is
   `["test/uns/#", "CovestroAG/#", "spBv1.0/uns_group/#"]`; `historian.mqtt.topics` is
   equivalent. A `uns/platform/#` prefix is invisible to both.
7. **`11_frontend` has no test runner.** `package.json` scripts are `dev`, `build`,
   `preview`, `lint` (`tsc --noEmit`).
8. **Each module exposes a Prometheus port**: `graphdb.metrics_port: 9092`,
   `historian.metrics_port: 9091`. ADR 0001 already chose Grafana for observability.

Consequence of (1)–(4): **the platform's only write path is five Alert Rule mutations, and
nothing can drive a process.** Run control has to be created either way. The decision taken
is to give the simulator its own control API rather than widen the GraphQL surface, and
finding (2) is now the argument for it rather than against it: ADR 0005 opened that surface
for one thing — plant configuration with nowhere else to live — and committed it to staying
narrow. Start/stop/pause of a container labelled "Not for production" is the opposite of that:
it is not plant configuration, it does not survive a restart by design (§5.2), and it would
put a test fixture's lifecycle into the schema every real consumer reads.

Two further consequences follow, and both are cheaper because ADR 0005 exists. `client.ts`
already has five write methods (`saveAlertRule`, `saveAlertRules`, `deleteAlertRule`,
`setAlertRuleEnabled`, `recordAlertRuleEvaluation`), each checking `res.error` and throwing,
so §7.3's `fetch` wrapper has a house style to match rather than to invent — and the ADR's
own consequence, "Anyone who can reach `/graphql` can now change alarm configuration.
There is no authorization in this service", is the same unauthenticated-write posture §10
records for port 8099. §10 is therefore consistent with the platform's current stance rather
than introducing a new one; it is not thereby made good, and the simulator's mitigation (no
host port mapping) is stricter than `/graphql`'s.

Consequence of (5)+(6): status and diagnostics are close to free, and routing simulator
health through `uns/platform/` keeps Platform Observability out of the UNS graph and the
historian, which is what `CONTEXT.md` requires.

Consequence of (8): throughput metrics belong in Prometheus/Grafana, not in a React page.
The console covers what Grafana structurally cannot — the simulator's *internal plant state*.

## 3. Goals

- Start, stop, pause and reconfigure the simulator from the console without editing YAML.
- Show, live, what the simulator is publishing and the plant state that explains it.
- Diagnose a wrong-looking value down to the signal, its shape, and its inputs.
- Keep `07_uns_graphql`'s mutation surface at ADR 0005's five, and keep simulator health out of the UNS.

## 4. Non-goals

- No mutations added to `07_uns_graphql`. Its surface stays at ADR 0005's five Alert Rule mutations.
- No editing of signal definitions, ranges, limits or expressions from the browser. Those
  stay in `conf/simulator/*.yaml`. The console shows them read-only.
- No authentication system. See §10 — the API is unauthenticated by design and constrained
  by deployment instead, which is the posture ADR 0005 already records for `/graphql`.
- No test runner introduced into `11_frontend`.
- No Grafana dashboards in this spec. The `/metrics` endpoint makes them possible; building
  them is separate work.

## 5. Control API

New: `99_simulator/src/uns_simulator/api.py`. FastAPI, served by uvicorn **in the same event
loop** as the simulation tasks (`asyncio.create_task` on a `uvicorn.Server`), so the API
observes live in-process state rather than a copy. Port from
`applications.simulator.api_port`, default 8099.

### 5.1 Read endpoints

| Path | Returns |
|---|---|
| `GET /simulator/health` | `{status, uptime_s, git_hash, version}` |
| `GET /simulator/status` | `{run_state, profile, seed, device_count, signal_count, uptime_s, broker_connected, msg_per_sec: {<tier>: n}, published_total, failed_total, overrides_active}` |
| `GET /simulator/config` | Resolved loaded profile: hierarchy, tier intervals, families enabled, device list with target and `serves`. Read-only. |
| `GET /simulator/plant` | `PlantContext` snapshot — per site `{ambient_temp_c, ambient_rh_pct, wet_bulb_temp_c, shift, tariff, grid_co2_g_per_kwh}`; per line `{state, production_rate, throughput_tph, heat_load, air_demand, state_since}` |
| `GET /simulator/devices` | Per device `{id, equipment, topic_prefix, tier, family, enabled, connected, last_publish_ts, publish_ok, publish_fail, last_error, signal_count}` |
| `GET /simulator/devices/{id}/signals` | Per signal `{name, shape, unit, precision, range, limits, params, value, status, last_publish_ts}` |
| `GET /simulator/diagnostics` | Profile load report: templates resolved → device counts, unmatched `target` selectors, `serves` resolution, validation warnings, recent publish failures and reconnects |

`run_state` is one of `stopped`, `starting`, `running`, `paused`.

### 5.2 Write endpoints

| Path | Body | Effect |
|---|---|---|
| `POST /simulator/run` | `{action: start\|stop\|pause\|resume}` | Transitions `run_state`. `pause` halts publishing but keeps `PlantClock` ticking, so state continues to evolve. `stop` cancels device tasks and disconnects. |
| `PUT /simulator/profile` | `{profile, seed?}` | Reloads profiles from disk, rebuilds devices, restarts. Counters reset; response says so. |
| `PUT /simulator/tiers` | `{fast?, process?, energy?, status?, meter?, lab?}` seconds | Reschedules affected devices without a full rebuild. |
| `PUT /simulator/families` | `{<family>: bool}` | Starts or stops that family's devices. |
| `PUT /simulator/devices/{id}` | `{enabled: bool}` | Starts or stops one device. |

All writes are idempotent, return the full new `status` body, and are serialised behind a
single `asyncio.Lock` so two concurrent profile switches cannot interleave. Unknown device →
404. Invalid profile, negative interval, unknown family → 422 with the offending field named.

**Changes are runtime-only and are not written back to `conf/simulator/*.yaml`.** A restart
returns to the file-declared configuration. `GET /simulator/status` includes
`overrides_active: bool` so the console can say so plainly rather than letting someone
believe a change was persisted.

### 5.3 Prometheus metrics

`GET /metrics` on `simulator.metrics_port`, default **9093** (following `historian: 9091`,
`graphdb: 9092`). Exposes `uns_simulator_messages_published_total{tier,family}`,
`uns_simulator_publish_failures_total{device}`, `uns_simulator_reconnects_total{device}`,
`uns_simulator_devices_connected`, `uns_simulator_signal_value{device,signal}` (bounded to
signals flagged `export_metric: true`, to avoid a 400-series cardinality explosion).

Neither 8099 nor 9093 is currently taken: `docker-compose.yml` publishes 8080, 8088, 8090,
8000, 9090, 9091 and 9092 on the host, and this compose file gives Kafka only a 9092 host
listener (internal 29092), so 9093 is free in practice.

Out-of-scope observation, recorded because it was found while choosing these ports and is
otherwise easy to miss: **`uns_kafka_broker` (`docker-compose.yml:82`) and `uns_graphdb`
(`docker-compose.yml:165`) both publish `9092:9092`.** Those two services cannot both start
on the same host. The simulator's ports are chosen not to extend the problem, but fixing the
existing collision is separate work and is not part of this spec.

## 6. Self-telemetry over MQTT

The simulator publishes its own health into a **Platform Observability** prefix, distinct
from the plant data it fabricates:

| Topic | Cadence | Payload |
|---|---|---|
| `uns/platform/simulator/<instance>/status` | 10 s | Same body as `GET /simulator/status` |
| `uns/platform/simulator/<instance>/plant/<site>/<line>/state` | on PackML transition | `{state, previous, production_rate, since}` |
| `uns/platform/simulator/<instance>/device/<id>/health` | on change | `{connected, publish_fail, last_error}` |

`<instance>` is `platform.instance_name`. An MQTT Last Will on `.../status` marks the
simulator offline when its process dies.

Because `graphdb` and `historian` subscribe only to `test/uns/#`, `CovestroAG/#` and
`spBv1.0/#`, **none of this reaches the UNS graph or the historian.** That is enforced by a
test (§9), not left to convention, because the failure mode — simulator health silently
persisted as if it were plant data — is exactly what `CONTEXT.md` warns against and would be
hard to notice.

The console reads these topics through the existing `subscribeMqttMessages` path. No
GraphQL or client change.

## 7. Frontend

### 7.1 Route and navigation

- `App.tsx`: `<Route path="/simulator" element={<SimulatorView />} />` inside
  `ProtectedConsoleLayout`.
- `App.tsx:4`: the header comment claiming exclusive GraphQL communication is corrected to
  name the simulator control API. Leaving it would be a falsehood in the file a newcomer
  reads first.
- `Sidebar.tsx`: entry appended to `opsNavItems` (Platform Ops section), icon
  `FlaskConical`, label "Simulator Control", description "Synthetic Plant Data Generator",
  `featureKey: 'simulator_ops'`, badge driven by `run_state` (`Live` when running).

### 7.2 Components — `src/components/simulator/`

| File | Content |
|---|---|
| `SimulatorView.tsx` | Page shell; tabs Status / Configure / Diagnostics; offline banner when the API is unreachable |
| `SimulatorStatusPanel.tsx` | Run state chip, profile, seed, uptime, device/signal counts, msg/s per tier, broker state, start/stop/pause/resume buttons |
| `SimulatorConfigPanel.tsx` | Profile select (`small`/`full`), seed field, tier interval inputs, family toggles, per-device enable table; `overrides_active` notice stating changes are runtime-only |
| `PlantStateInspector.tsx` | Per-site card with ambient/shift/tariff; per-line PackML state chip, `production_rate` and `heat_load` bars, time-in-state; updates live from MQTT |
| `SignalInspector.tsx` | Device picker → signal table (name, shape, unit, value, status, limits) with a sparkline built from the live feed |
| `SimulatorDiagnostics.tsx` | Profile load report, unmatched targets, validation warnings, per-device publish failures / reconnects / last error, sample of published topics |

`PlantStateInspector` is the page's reason to exist. Grafana can chart the resulting values
but has no visibility of the simulator's internal state, so it cannot answer "why did site
kW spike" — this can.

### 7.3 Services and state

- `src/services/simulator/client.ts` — typed `fetch` wrapper over `/simulator/*`. Base URL
  from `platformConfig.simulatorApiUrl`. Non-2xx responses are surfaced as typed errors
  carrying the 422 field detail; network failure resolves to an `offline` sentinel rather
  than throwing, so the page degrades instead of blanking.
- `src/types/simulator.ts` — response types mirroring §5.
- `src/hooks/useSimulator.ts` — polls `GET /simulator/status` every 2 s, fetches
  `config`/`devices`/`diagnostics` on demand, and subscribes to
  `uns/platform/simulator/#`. A hook rather than a context: exactly one route consumes it,
  and a provider in `App.tsx` would make every route pay for it.

### 7.4 RBAC

Two new `FeatureKey`s in `src/types/rbac.ts`, each with a `SYSTEM_FEATURES` entry:

| Key | Grants | Category |
|---|---|---|
| `simulator_ops` | See the route, status, plant state, diagnostics | Core Navigation |
| `simulator_control` | Start/stop/pause, change profile, tiers, families, devices | System & Admin |

Defaults per role — `admin`: both; `engineer`: both; `operator`: `simulator_ops` only;
`auditor`: `simulator_ops` only; `viewer`: neither. Every `defaultPermissions` record in
`ROLE_CONFIGS` must gain both keys or `Record<FeatureKey, boolean>` fails to type-check;
that is the compile-time guard that no role is missed.

Write controls render `disabled` with the existing read-only `Lock` chip pattern from
`SystemHealthView.tsx:222`.

## 8. Configuration and deployment

| File | Change |
|---|---|
| `conf/settings.yaml` | `applications.simulator.api_port: 8099`; `simulator.metrics_port: 9093`; `urls.simulator_host` / `simulator_port` |
| `11_frontend/platform/settings.ts` | `simulatorApiUrl`, `simulatorProxyTarget` added to `PlatformSettings` and `platformSettingsFromConfig` |
| `11_frontend/src/lib/platform/config.ts` | Same two fields on the exported type |
| `11_frontend/vite.config.ts` | `'/simulator'` proxy entry → `platform.simulatorProxyTarget` |
| `11_frontend/nginx.conf` | `location /simulator { proxy_pass http://uns_simulator:8099/simulator; ... }` |
| `docker-compose.yml` | No host port mapping for 8099 by default (see §10). Frontend gains no `depends_on` — the page degrades when the simulator is absent. |
| `99_simulator/Dockerfile` | `EXPOSE 8099 9093`; plus the `COPY ./conf/simulator /app/conf/simulator` line from sub-project A |
| `99_simulator/pyproject.toml` | `fastapi`, `uvicorn`, `prometheus-client` added |

## 9. Testing

**Backend — `99_simulator/test/`**

`test_api.py` (FastAPI `TestClient`, no broker):
- every read endpoint returns the documented shape
- `POST /run` walks `stopped → running → paused → running → stopped`; each response carries
  the resulting `run_state`
- repeating a write is idempotent and does not error
- `PUT /profile` with an unknown profile → 422 naming `profile`; negative tier interval →
  422 naming the tier; unknown family → 422; unknown device id → 404
- `overrides_active` becomes true after any runtime write and false after a profile reload
- concurrent `PUT /profile` calls serialise rather than interleaving

`test_self_telemetry.py`:
- status, plant-state and device-health messages publish under `uns/platform/simulator/…`
- **regression guard: no self-telemetry topic matches any pattern in `graphdb.mqtt.topics`
  or `historian.mqtt.topics`.** Asserted against the topic lists read from
  `conf/settings.yaml`, so adding a mapper subscription that would swallow platform
  telemetry breaks this test.
- the Last Will topic is registered on `.../status`

`test_metrics.py`:
- `/metrics` parses as Prometheus text format
- only signals marked `export_metric: true` appear, bounding cardinality

**Frontend — `11_frontend`**

No test runner exists and this spec does not add one. The gate is `npm run lint`
(`tsc --noEmit`) and `npm run build`, both of which must pass. Type safety carries real
weight here: `Record<FeatureKey, boolean>` in `ROLE_CONFIGS` makes a forgotten role a
compile error, and the `types/simulator.ts` definitions make a drifted API response a
compile error at the call site.

Manual verification checklist, to be recorded in the module README:
1. Simulator stopped → `/simulator` shows the offline banner, no console errors.
2. Start from the console → `run_state` flips to `running`, msg/s becomes non-zero.
3. Switch `small` → `full` → device count rises, `overrides_active` is shown as true.
4. Force a family off → its devices disappear from the device table and msg/s drops.
5. Log in as `operator` → page renders, every write control is disabled with the lock chip.
6. Kill the simulator container → offline banner returns via the LWT, page does not crash.

## 10. Security

**The control API is unauthenticated.** RBAC in `11_frontend` is client-side only, so anyone
who can reach port 8099 can `POST /simulator/run` regardless of role. This is stated here
rather than left to be discovered.

Accepted because the simulator is a test fixture — its own Docker label reads "Not for
production" — and mitigated by deployment rather than by an auth system:

- **Port 8099 is not mapped to the host in `docker-compose.yml`.** The browser reaches the
  API through the nginx `location /simulator` block from inside the Compose network.
- Vite dev mode runs on the host and therefore does need the port. That is documented as a
  dev-only opt-in (`docker compose run --publish 8099:8099`, or a commented-out mapping),
  not the default.
- An optional shared secret is supported: when `simulator.api.token` is present in
  `conf/.secrets.yaml`, the API requires a matching `X-Simulator-Token` header and nginx
  injects it via `proxy_set_header`. Absent, the API is open. Off by default; documented.
- The API binds `0.0.0.0` inside the container only because Docker requires it for the
  nginx hop; there is no host exposure without an explicit mapping.

This is a deliberate, bounded trade-off for a development tool, and it must not be copied
into a module that handles real plant data.

## 11. Deliverables

**New backend**: `99_simulator/src/uns_simulator/api.py`, `metrics.py`, `self_telemetry.py`.
**Modified backend**: `simulator.py` (run-state machine, runtime reconfiguration, lock),
`main.py` (start uvicorn alongside the simulation), `config.py`, `pyproject.toml`,
`Dockerfile`.
**New frontend**: `src/components/simulator/{SimulatorView, SimulatorStatusPanel,
SimulatorConfigPanel, PlantStateInspector, SignalInspector, SimulatorDiagnostics}.tsx`,
`src/services/simulator/client.ts`, `src/types/simulator.ts`, `src/hooks/useSimulator.ts`.
**Modified frontend**: `App.tsx`, `components/layout/Sidebar.tsx`, `types/rbac.ts`,
`lib/platform/config.ts`, `platform/settings.ts`, `vite.config.ts`, `nginx.conf`.
**Modified config**: `conf/settings.yaml`, `docker-compose.yml`.
**New tests**: `test_api.py`, `test_self_telemetry.py`, `test_metrics.py`.
**Docs**: `99_simulator/README.md` (control API, endpoints, security caveat),
`11_frontend/README.md` (the new route and its proxy), and
`docs/adr/0007-simulator-control-api-outside-graphql.md` recording why the simulator got its
own write surface instead of a sixth GraphQL mutation, and why ADR 0005's "stays narrow" is
the reason rather than an obstacle. (`docs/adr/0005-graphql-mutations-for-console-configuration.md`
already exists, accepted and committed; sub-project A's spec claims `0005` and has been
corrected to `0006` in its implementation plan, so this one takes `0007`.)

## 12. Risks

| Risk | Mitigation |
|---|---|
| Unauthenticated write API | §10: no host port mapping, optional shared-secret header, scope limited to a tool labelled not-for-production |
| The `/simulator` proxy erodes the single-client architecture | Confined to one nginx location and one Vite proxy entry; `07_uns_graphql`'s mutation surface stays at ADR 0005's five; ADR 0007 records the boundary so the next module does not repeat it |
| Self-telemetry leaks into the UNS if a mapper subscription widens | `test_self_telemetry.py` asserts against the live topic lists in `conf/settings.yaml`, so the widening breaks a test |
| Prometheus cardinality from ~400 signals | `uns_simulator_signal_value` limited to signals flagged `export_metric: true`, asserted by `test_metrics.py` |
| Runtime overrides mistaken for persisted config | `overrides_active` in the status body, surfaced as a notice in `SimulatorConfigPanel` |
| No frontend test coverage | Explicit non-goal; `tsc --noEmit` plus `vite build` gate, reinforced by `Record<FeatureKey, boolean>` and typed API responses turning drift into compile errors; manual checklist in the README |
| Uvicorn sharing the simulation event loop could starve publishing | API handlers do no blocking work; they read in-memory state and enqueue commands. `test_api.py` runs against a live loop with devices scheduled. |
