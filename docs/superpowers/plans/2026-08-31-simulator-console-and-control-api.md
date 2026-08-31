# Simulator Console and Control API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the simulator a small HTTP control surface, Prometheus metrics and MQTT self-telemetry, and a `/simulator` console route in `11_frontend` that starts, stops, reconfigures and diagnoses the plant model without a restart.

**Architecture:** The simulator serves a FastAPI app on port 8099 from inside its own event loop, so every handler reads live in-process state rather than a copy — there is no database, no cache and no second source of truth. Writes are runtime-only and never persisted back to YAML, and all of them serialise behind one `asyncio.Lock`. Prometheus scrapes port 9093 through a custom collector that renders counters the devices already keep, and a separate MQTT client publishes the simulator's own health under `uns/platform/simulator/...`, which no mapper subscribes to. The console is a normal protected route that polls the control API and holds no state the API does not own.

**Tech Stack:** Python ≥3.14, FastAPI, uvicorn, pydantic, prometheus-client, aiomqtt, Dynaconf, pytest/pytest-asyncio/httpx. React 19, react-router-dom 7 (`HashRouter`), TypeScript 5.8, Vite 6, Tailwind 4, `lucide-react`.

**Spec:** `docs/superpowers/specs/2026-08-31-simulator-console-and-control-api-design.md`

**Prerequisite plan (sub-project A, must land first):** `docs/superpowers/plans/2026-08-31-simulator-plant-model.md`. Every interface this plan consumes — `PlantContext`, `PlantClock`, `LoadedProfile`, `SignalDevice`, `LoadReport`, `load_simulator_config` — is produced there. This plan is unimplementable against today's `99_simulator`, which has neither a plant model nor cadence tiers.

## Global Constraints

- Python `>=3.14, <4`. No new Python dependency beyond the three added in Task 1 (`fastapi`, `uvicorn[standard]`, `prometheus-client`) and `httpx` in the test group.
- **No new npm dependency.** The console is built from React, `react-router-dom`, `lucide-react` and Tailwind classes that are already in `11_frontend/package.json`.
- ruff, from the repo root `pyproject.toml`: `line-length = 127`, `preview = true`, `select = ["A", "ARG", "B", "C", "E", "F", "UP", "W", "I", "N", "S", "T", "RUF", "LOG", "PERF"]`, and `S101` is ignored globally so `assert` needs no `noqa` anywhere. Consequences that bite in this plan: `S104` fires on the literal `"0.0.0.0"` (one `# noqa: S104`, in Task 1), `T201` forbids `print`, `LOG` forbids f-strings in logging calls (use `%s` placeholders), and `ARG` flags unused arguments.
- pytest, from `99_simulator/pyproject.toml`: `addopts = "-n auto --timeout=300 --durations=10"`, `testpaths = ["test"]`, `asyncio_default_fixture_loop_scope = "function"`. Every async test carries `@pytest.mark.asyncio`. Tests never bind a real socket, never contact a broker, and never sleep longer than a few hundredths of a second — they shorten `tick_s` and tier intervals instead of waiting.
- Ports, fixed and non-negotiable: historian metrics 9091, graph database metrics 9092, **simulator metrics 9093**, **simulator control API 8099**. Prometheus itself stays on 9090.
- Self-telemetry topic prefix: `uns/platform/simulator/<instance>/`, where `<instance>` is `platform.instance_name` (`"Instance01"` by default). This prefix must not match `graphdb.mqtt.topics`, `historian.mqtt.topics`, `kafka_mapper.mqtt.topics` or `sparkplugb.mqtt.topics`. Task 8 enforces that with a test, because convention alone does not survive a future topic change.
- Runtime configuration changes are never written back to YAML. `overrides_active` tells the operator that the running plant no longer matches the files on disk.
- The simulator is explicitly not production software (`99_simulator/Dockerfile:41`). The control API is unauthenticated by default; the only protection is the optional `X-Simulator-Token` shared secret from Task 1.
- `11_frontend` has no test runner. The gate for every frontend task is `npm run lint` (which is `tsc --noEmit`) **and** `npm run build`. Both must pass before the commit.
- Frontend palette, hardcoded exactly as the rest of the console does it: page `#050505`, panel `#111114`, inset `#0B0B0C`, borders `#1E293B` and `#334155`, text `#F8FAFC` / `#94A3B8` / `#64748B`, accent `#FFC107` (amber-500 in light mode). Body copy is `font-mono text-xs`.
- Vocabulary from `CONTEXT.md`, in user-visible copy: **Platform Observability** (everything in this plan is Platform Observability, never Process Visualization), **Instance**, **Unit of Measure** — never a bare "unit" in a label. JSON and TypeScript field names are not copy: plan A's `SignalSpec.unit` stays `unit`, and the console labels that column "Unit of Measure".

---

## Canonical Response Bodies

Tasks 5, 6 and 11 all describe the same seven JSON documents — the read model in Python, the routes that return it, and the TypeScript types that consume it. They are written out once here so they cannot drift. **When a task and this section disagree, this section is right.**

`GET /simulator/health` — the only endpoint that answers while the plant is stopped:

```json
{ "status": "ok", "uptime_s": 312.4, "git_hash": "8b165c1f", "version": "0.9.38" }
```

`GET /simulator/status` — the polled document; `uptime_s` here is the *current run*, and is `0.0` when `run_state` is `stopped`:

```json
{
  "run_state": "running",
  "profile": "small",
  "seed": 20260831,
  "device_count": 14,
  "signal_count": 96,
  "uptime_s": 42.0,
  "broker_connected": true,
  "msg_per_sec": { "fast": 2.0, "process": 3.2, "energy": 0.8, "status": 0.2, "meter": 0.01, "lab": 0.0, "event": 0.0 },
  "published_total": 1024,
  "failed_total": 0,
  "overrides_active": false,
  "tiers": { "fast": 6.0, "process": 30.0, "energy": 90.0, "status": 180.0, "meter": 5400.0, "lab": 10800.0, "event": 0.0 },
  "families": { "energy": true, "water": true, "utilities": true, "asset_health": false, "production": false, "safety": false },
  "per_tier": { "fast": 12, "process": 44, "energy": 24, "status": 12, "meter": 4, "lab": 0, "event": 0 },
  "tick_count": 42
}
```

`tiers` is seconds per publish for each cadence tier, already multiplied by the profile's `tier_scale`. `per_tier` is how many signals live in each tier. `msg_per_sec` is the arithmetic rate implied by those two, and is all zeros unless `run_state` is `running`. `broker_connected` is a boolean — true when *any* device holds a connection.

`GET /simulator/config` — read-only; the console mirrors it into its controls:

```json
{
  "profile": "small",
  "available_profiles": ["full", "single_line", "small"],
  "seed": 20260831,
  "tier_scale": 6.0,
  "tiers": { "fast": 6.0, "process": 30.0, "energy": 90.0, "status": 180.0, "meter": 5400.0, "lab": 10800.0, "event": 0.0 },
  "families": { "energy": true, "water": true, "utilities": true, "asset_health": false, "production": false, "safety": false },
  "sites": ["Dormagen"],
  "max_cells_per_line": 1,
  "hierarchy": [
    { "enterprise": "CovestroAG", "site": "Dormagen", "area": "Production", "line": "Line1", "cell": "Cell1", "kind": "production", "nameplate_tph": 12.0 }
  ],
  "devices": [
    {
      "id": "dormagen-powerhouse-main-meter",
      "equipment": "MainMeter",
      "family": "energy",
      "tier": "energy",
      "enabled": true,
      "topic_prefix": "CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainMeter",
      "signal_count": 8,
      "serves": ["Production/Line1", "Production/Line2"],
      "target": { "site": "Dormagen", "area": "Utilities", "line": "Powerhouse", "cell": "Cell1", "kind": "utilities" }
    }
  ]
}
```

`GET /simulator/plant`:

```json
{
  "sites": {
    "Dormagen": {
      "ambient_temp_c": 18.4,
      "ambient_rh_pct": 62.0,
      "wet_bulb_temp_c": 14.1,
      "wind_speed_ms": 3.2,
      "barometric_mbar": 1013.0,
      "shift": "A",
      "tariff": "peak",
      "grid_co2_g_per_kwh": 380.0,
      "lines": {
        "Production/Line1": {
          "state": "Execute",
          "previous": "Starting",
          "production_rate": 0.92,
          "throughput_tph": 11.04,
          "heat_load": 0.88,
          "air_demand": 0.9,
          "time_in_state_s": 184.0,
          "transition_count": 3
        }
      }
    }
  }
}
```

`GET /simulator/devices`:

```json
{
  "devices": [
    {
      "id": "dormagen-powerhouse-main-meter",
      "equipment": "MainMeter",
      "topic_prefix": "CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainMeter",
      "tier": "energy",
      "family": "energy",
      "enabled": true,
      "connected": true,
      "last_publish_ts": 1772323200.0,
      "publish_ok": 84,
      "publish_fail": 0,
      "last_error": null,
      "signal_count": 8
    }
  ]
}
```

`GET /simulator/devices/{device_id}/signals`:

```json
{
  "device_id": "dormagen-powerhouse-main-meter",
  "signals": [
    {
      "name": "ActivePower",
      "shape": "load_follow",
      "unit": "kW",
      "precision": 1,
      "range": [0.0, 2500.0],
      "limits": { "hi": 2200.0, "hihi": 2400.0 },
      "params": { "idle_fraction": 0.18 },
      "tier": "energy",
      "param_type": "ProcessValue",
      "value": 1840.5,
      "status": "Normal",
      "last_publish_ts": 1772323200.0,
      "topic": "CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainMeter/ProcessValue/ActivePower"
    }
  ]
}
```

`topic` is the only field here that `SignalDevice.snapshot()` does not already return. Task 5
adds it, because `ISA95Hierarchy.get_parameter_topic` is the single definition of a signal's
topic and the console needs one to subscribe to.

`GET /simulator/diagnostics`:

```json
{
  "report": {
    "devices": 14,
    "signals": 96,
    "per_family": { "energy": 4, "water": 3, "utilities": 7 },
    "per_tier": { "fast": 12, "process": 44, "energy": 24, "status": 12, "meter": 4 },
    "serves_links": 6,
    "unmatched_templates": ["asset_health/vibration-pack"],
    "warnings": ["profile 'small' caps cells per line at 1; 3 cells were dropped"]
  },
  "failing_devices": [
    {
      "device_id": "dormagen-line1-mixer",
      "client_id": "uns_simulator-dormagen-line1-mixer-1a2b3c4d",
      "connected": false,
      "publish_ok": 12,
      "publish_fail": 3,
      "reconnects": 2,
      "last_error": "[Errno 111] Connection refused",
      "last_publish_ts": 1772323100.0
    }
  ],
  "sample_topics": [
    "CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainMeter/ProcessValue/ActivePower"
  ]
}
```

The five writes all return the **`/simulator/status` body above**, so a caller never has to follow a write with a read. `PUT /simulator/profile` returns that body plus `"counters_reset": true`, and its `published_total` and `failed_total` are zero — the devices that were counting are gone, so a console that kept subtracting would compute negative rates.

Two different 422 shapes exist and the TypeScript client in Task 11 must parse both:

```json
{ "detail": { "field": "profile", "message": "unknown profile 'huge' (known: full, single_line, small)" } }
```

```json
{ "detail": [ { "type": "greater_than_equal", "loc": ["body", "fast"], "msg": "Input should be greater than or equal to 0", "input": -1.0 } ] }
```

The first is a domain refusal raised by the simulator; the second is pydantic rejecting the request body before a handler runs.

---

## Where This Plan Departs From the Spec

Every difference between the spec and the tasks below, recorded so a reviewer sees them as
decisions rather than drift. Anything not listed here follows the spec.

**Gaps the spec left open:**

1. **`devices.py` is missing from spec §11's "Modified backend" list**, but `uns_simulator_messages_published_total{tier,family}` (§5.3) cannot be derived from anything `SignalDevice` currently keeps — `publish_ok` is a single total with no tier breakdown. Task 2 adds `SignalDevice.published_by_tier`, a nine-line change, and modifies `devices.py`.
2. **`08_uns_observability/prometheus/prometheus.yml` is missing from spec §8's deployment table.** Without a fourth scrape job the metrics endpoint is served and never read. Task 9 adds the job.
3. **Spec §5.1 calls the per-line field `state_since`; plan A produces `time_in_state_s`.** This plan keeps `time_in_state_s` everywhere — in `/plant`, in the §6 plant telemetry payload and in the console. Seconds-in-state is also what §7.2 asks the inspector to display, and inventing a second name for one fact is how two fields that must agree stop agreeing.
4. **Spec §5.2's tier body names six tiers and omits `event`,** which plan A's `TIER_DEFAULTS` includes. `TiersRequest` in Task 7 accepts all seven. Excluding it would leave one tier permanently unreachable for no reason.

**Choices the spec described differently:**

5. **Write verbs are `PUT`, not `PATCH`.** Spec §5 uses both words in different places. `PUT` is right for all four write endpoints because each one replaces the whole value it names: `/tiers` takes a complete interval map, `/families` a complete flag map, `/devices/{id}` the device's whole mutable state (`enabled`), `/profile` the whole plant. None of them merges into an existing document, which is the only thing `PATCH` means.
6. **The diagnostics component is `SimulatorDiagnosticsPanel.tsx`, not spec §7.2's `SimulatorDiagnostics.tsx`.** `SimulatorDiagnostics` is already the name of the response type in `types/simulator.ts`, and a component and a type with the same name in one import block is a readability trap. The four sibling panels keep their spec names.
7. **The sidebar badge is a static `SIM`, not spec §7.1's `run_state`-driven `Live` badge.** `Sidebar` receives no simulator state — wiring the poll into it would mean either lifting `useSimulator` above the router (polling the control API on every page of the console, including for users without `simulator_ops`) or a second independent poller. The run state is on the page itself, one click away, where an operator acting on it already is.
8. **Signal rows carry a `topic` field the spec's §5 body does not list.** Task 5 adds it, because `ISA95Hierarchy.get_parameter_topic` is the single definition of a signal's topic and the console needs one to subscribe to. Rebuilding that string in TypeScript would duplicate the topic layout in a second language.
9. **The shared secret reaches the API from the browser as `VITE_SIMULATOR_TOKEN`, not through nginx's `proxy_set_header` as spec §10 suggests.** Injecting it in nginx would put the secret in an image layer and hand it to every client the proxy serves, including unauthenticated ones; the console would also then have no way to talk to a simulator it reaches directly in `npm run dev`. The header is set in one place (`client.ts`) either way. Both approaches share the same limitation — a token in a browser is not a secret — which is why §10's "not for production" scope still governs.
10. **`docker-compose.yml` gains a commented-out `8099:8099` mapping and `uns_frontend` gains `depends_on: uns_simulator`.** The first is exactly spec §10's dev-only opt-in. The second contradicts §8's "Frontend gains no `depends_on`", which assumed nginx tolerates an absent upstream; it does not — a literal `proxy_pass` hostname is resolved at startup and an unresolvable one is a fatal config error, so without the dependency a stack started without the simulator would have no frontend either. §8's intent (the *page* degrades when the simulator is absent) is preserved by Task 13's offline handling.

---

## File Structure

**Backend — `99_simulator/src/uns_simulator/`:**

| File | Responsibility |
|---|---|
| Create `metrics.py` | The Prometheus collector and its HTTP server. Reads the simulator; nothing imports it but `main.py`. |
| Create `api.py` | The FastAPI app factory, request models and HTTP status mapping. Holds **no** domain logic — every handler is one call into the simulator plus one exception translation. |
| Create `self_telemetry.py` | The MQTT publisher for `uns/platform/simulator/...`, with its own client because a Last Will has to be set at construction. |
| Modify `config.py` | Add `SimulatorAPIConfig` beside `MQTTConfig`. |
| Modify `simulator.py` | Run state, runtime reconfiguration, and the read model. The **only** file that mutates simulation state. |
| Modify `devices.py` | `SignalDevice.published_by_tier` and nothing else. |
| Modify `main.py` | Wiring: start the metrics server, the API task and the telemetry task alongside the simulation. |

Three new modules rather than one `console.py` because they have three different reasons to change (a metric name, an endpoint, a topic), three different third-party dependencies (`prometheus_client`, `fastapi`, `aiomqtt`) and three different failure modes. The read model lives on `UnifiedNamespaceSimulator` rather than in `api.py` so that it is testable without HTTP, and so `api.py` stays a translation layer thin enough to review at a glance.

**Backend tests — `99_simulator/test/`:** create `test_config.py`, `test_metrics.py`, `test_api.py`, `test_self_telemetry.py`; modify `test_simulator.py` and `test_main.py`.

**Frontend — `11_frontend/`:**

| File | Responsibility |
|---|---|
| Create `src/types/simulator.ts` | One TypeScript type per canonical response body. No logic. |
| Create `src/services/simulator/client.ts` | `fetch` against `/simulator`. Returns a result union; throws nothing. |
| Create `src/hooks/useSimulator.ts` | Polling, the write wrappers, and the platform-telemetry feed. |
| Create `src/components/simulator/SimulatorStatusPanel.tsx` | Run state, run controls, throughput. |
| Create `src/components/simulator/SimulatorConfigPanel.tsx` | Profile, seed, tier intervals, families, per-device enable. |
| Create `src/components/simulator/PlantStateInspector.tsx` | Ambient and shift per site; PackML state per line. |
| Create `src/components/simulator/SignalInspector.tsx` | One device's signals, with a live sparkline from the MQTT subscription. |
| Create `src/components/simulator/SimulatorDiagnosticsPanel.tsx` | Load report, warnings, failing devices, sample topics, telemetry feed, endpoints. |
| Create `src/components/simulator/SimulatorView.tsx` | The route shell and its three sub-tabs. |
| Modify `platform/settings.ts`, `src/lib/platform/config.ts` | `simulatorApiPort` and `simulatorProxyTarget`. |
| Modify `vite.config.ts`, `nginx.conf` | Proxy `/simulator` in dev and in the container. |
| Modify `src/App.tsx` | The `/simulator` route, and the line-3 comment it invalidates. |
| Modify `src/types/rbac.ts`, `src/context/AuthContext.tsx` | `simulator_ops` and `simulator_control`. |
| Modify `src/components/layout/AppLayout.tsx` | `getTabIdFromPath('/simulator')`, without which the route's own guard never fires. |
| Modify `src/components/layout/Sidebar.tsx` | The nav entry. |
| Modify `src/vite-env.d.ts` | `VITE_SIMULATOR_TOKEN` in the hand-written `ImportMetaEnv`. |
| Modify `README.md` | The second backend it now talks to. |

**Configuration, deployment and docs:** `conf/settings.yaml`, `conf/.secrets_template.yaml`, `99_simulator/pyproject.toml`, `uv.lock`, `99_simulator/Dockerfile`, `docker-compose.yml`, `08_uns_observability/prometheus/prometheus.yml`, `99_simulator/README.md`, `docs/adr/0007-simulator-control-api-outside-graphql.md`.

---

## Task 1: Ports, the optional token, and the three new dependencies

Nothing else can be built until the simulator knows which ports it owns. This task also
adds the dependencies the next eight tasks import, so no later task has to touch
`pyproject.toml` or re-lock.

**Files:**
- Modify: `conf/settings.yaml:28-29` (`default.applications.simulator`), `conf/settings.yaml:31-39` (`default.urls`), and after `conf/settings.yaml:77` (the end of `default.historian`)
- Modify: `conf/.secrets_template.yaml`
- Modify: `99_simulator/pyproject.toml`
- Modify: `99_simulator/src/uns_simulator/config.py`
- Modify: `uv.lock`, `99_simulator/uv.lock`
- Test: `99_simulator/test/test_config.py` (create)

**Interfaces:**
- Consumes: `settings = get_settings("simulator")`, already at `config.py:14`.
- Produces: `class SimulatorAPIConfig` with class attributes `api_host: str`, `api_port: int`, `metrics_port: int`, `token: str | None`, and `@classmethod is_token_required() -> bool`. Imported by `api.py` (Tasks 6, 7), `metrics.py` (Task 2) and `main.py` (Task 9).

- [ ] **Step 1: Write the failing test**

```python
# 99_simulator/test/test_config.py
"""The simulator's own ports. Read at import time, exactly as MQTTConfig does."""

from uns_simulator.config import SimulatorAPIConfig


def test_the_control_api_port_comes_from_settings():
    assert SimulatorAPIConfig.api_port == 8099


def test_the_metrics_port_comes_from_settings():
    assert SimulatorAPIConfig.metrics_port == 9093


def test_the_metrics_port_does_not_collide_with_another_client():
    """9090 is Prometheus, 9091 the historian, 9092 the graph database (spec 2, finding 8).

    A collision does not fail loudly: whichever container starts second logs an address-in-use
    error and keeps running with no metrics at all.
    """
    assert SimulatorAPIConfig.metrics_port not in (9090, 9091, 9092)


def test_the_api_binds_all_interfaces_so_the_container_is_reachable():
    assert SimulatorAPIConfig.api_host == "0.0.0.0"  # noqa: S104


def test_a_token_is_only_required_when_one_is_configured(monkeypatch):
    """Spec 10: no token in the secrets file means an open API, which is the default."""
    monkeypatch.setattr(SimulatorAPIConfig, "token", None)
    assert SimulatorAPIConfig.is_token_required() is False
    monkeypatch.setattr(SimulatorAPIConfig, "token", "s3cret")
    assert SimulatorAPIConfig.is_token_required() is True
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd 99_simulator && uv run pytest test/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'SimulatorAPIConfig' from 'uns_simulator.config'`.

- [ ] **Step 3: Add the three settings keys**

In `conf/settings.yaml`, give the simulator application a port. Replace lines 28-29:

```yaml
    simulator:
      name: "uns_simulator"
```

with:

```yaml
    simulator:
      name: "uns_simulator"
      # The simulator's own control API (99_simulator/src/uns_simulator/api.py).
      # Not part of the GraphQL surface: it commands a process, it does not query the
      # Unified Namespace. See docs/adr/0007-simulator-control-api-outside-graphql.md.
      api_port: 8099
```

In the same file, add the simulator's metrics port. Insert a new block immediately after
the `default.historian` block (which ends at line 77 with `metrics_port: 9091`), keeping
the blank-line-between-blocks style:

```yaml
  simulator:
    # Prometheus scrapes this. 9091 is the historian's and 9092 the graph database's.
    metrics_port: 9093
```

Finally, let the frontend build learn where the control API is. In `default.urls`
(lines 31-39), after `graphql_path`, add:

```yaml
    simulator_host: "localhost"
    simulator_port: 8099
```

- [ ] **Step 4: Add the optional token to the secrets template**

In `conf/.secrets_template.yaml`, after the `historian` block and before `kafka`, add:

```yaml
  simulator:
    api:
      # Optional. Leave unset for an open control API, which is the default and is
      # appropriate for the local Docker Compose stack. Set it and every request to
      # http://<host>:8099/simulator/* must carry X-Simulator-Token with this value.
      token:
```

- [ ] **Step 5: Add `SimulatorAPIConfig` to `config.py`**

Append to `99_simulator/src/uns_simulator/config.py`, after `MQTTConfig`:

```python
class SimulatorAPIConfig:
    """Where the control API and the metrics endpoint listen (spec 8).

    Class-level reads, matching MQTTConfig: by import time Dynaconf has already merged
    conf/settings.yaml, conf/.secrets.yaml and any UNS_* environment override, so there
    is nothing to defer.
    """

    # Binds every interface because the process runs in a container whose port is
    # published. `api_host` is deliberately absent from settings.yaml — override it with
    # UNS_SIMULATOR__API_HOST=127.0.0.1 when running the simulator directly on a host.
    api_host: str = settings.get("simulator.api_host", "0.0.0.0")  # noqa: S104
    api_port: int = settings.get("applications.simulator.api_port", 8099)
    metrics_port: int = settings.get("simulator.metrics_port", 9093)
    token: str | None = settings.get("simulator.api.token", None)

    @classmethod
    def is_token_required(cls) -> bool:
        """True when a shared secret is configured. An empty string counts as absent."""
        return bool(cls.token)
```

- [ ] **Step 6: Run the test and confirm it passes**

Run: `cd 99_simulator && uv run pytest test/test_config.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 7: Add the dependencies**

In `99_simulator/pyproject.toml`, extend `[project] dependencies` — the pins match the
rest of the repo, `uvicorn` from `07_uns_graphql` and `prometheus-client` from
`04_uns_historian`, so the workspace resolves to one version of each:

```toml
dependencies = [
    "logger~=1.4",
    "uns_config",
    "aiomqtt>=2.5.1,<3",
    "dynaconf~=3.2",
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.34,<0.53",
    "prometheus-client>=0.21.0,<1",
]
```

and add `httpx` to the `test` group, for `httpx.ASGITransport` in Task 7:

```toml
    "httpx>=0.28,<1",
```

- [ ] **Step 8: Re-lock and confirm the imports resolve**

```bash
cd 99_simulator && uv lock
cd .. && uv lock
```

Run: `cd 99_simulator && uv run python -c "import fastapi, uvicorn, prometheus_client, httpx"`
Expected: no output and exit status 0.

- [ ] **Step 9: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add conf/settings.yaml conf/.secrets_template.yaml 99_simulator/pyproject.toml 99_simulator/uv.lock uv.lock 99_simulator/src/uns_simulator/config.py 99_simulator/test/test_config.py
git commit -m "feat(simulator): reserve port 8099 for the control API and 9093 for metrics"
```

---

## Task 2: Prometheus metrics on 9093

Spec §5.3 names five metrics. Four of the five are numbers the devices already keep, so
this task exposes them through a custom collector rather than declaring module-level
`Counter` objects and incrementing them beside the existing fields. Two counters for one
event is how they drift, and the mirror is always the one that is wrong.

The fifth, `uns_simulator_messages_published_total{tier,family}`, needs a per-tier
breakdown that `publish_ok` does not have, so `SignalDevice` gains one dict.

**Files:**
- Create: `99_simulator/src/uns_simulator/metrics.py`
- Modify: `99_simulator/src/uns_simulator/devices.py` (`SignalDevice.__init__` and `publish_tier`)
- Test: `99_simulator/test/test_metrics.py` (create)

**Interfaces:**
- Consumes: `SignalDevice` with `.spec`, `.values`, `.connected`, `.publish_ok`, `.publish_fail`, `.reconnects`, `.tiers`, `async publish_tier(tier)` (plan A Task 14); `DeviceSpec.id`/`.family`/`.signals`; `SignalSpec.export_metric`; `UnifiedNamespaceSimulator.signal_devices` (plan A Task 16).
- Produces: `SignalDevice.published_by_tier: dict[str, int]`; `class SimulatorCollector` with `__init__(simulator)` and `collect()`; `start_metrics_server(simulator, port: int) -> CollectorRegistry`. `main.py` (Task 9) calls `start_metrics_server`.

- [ ] **Step 1: Write the failing tests**

```python
# 99_simulator/test/test_metrics.py
"""Platform Observability for the simulator itself (spec 5.3).

Self-contained on purpose: it builds one device rather than importing another test
module's fixtures, so a change to the plant-model tests cannot break the metric names
that Prometheus and Grafana depend on.
"""

import json

import pytest
from prometheus_client import generate_latest

from uns_simulator import devices as devices_module
from uns_simulator.devices import SignalDevice
from uns_simulator.metrics import SimulatorCollector
from uns_simulator.models import ISA95Hierarchy
from uns_simulator.plant import DeviceView, LineTiming, PlantContext
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import SignalSpec

PATH = ISA95Hierarchy("CovestroAG", "Dormagen", "Utilities", "Powerhouse", "Cell1", kind="utilities")


class DummyClient:
    """Records publishes instead of contacting a broker."""

    def __init__(self, *args, **kwargs):
        self.published: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def publish(self, topic, payload, **kwargs):
        self.published.append((topic, json.loads(payload)))


@pytest.fixture(autouse=True)
def _dummy_broker(monkeypatch):
    monkeypatch.setattr(devices_module.aiomqtt, "Client", DummyClient)


def _device() -> SignalDevice:
    context = PlantContext(global_seed=7)
    context.add_site("Dormagen")
    timing = LineTiming(starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=0.0)
    context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
    spec = DeviceSpec(
        id="main-meter",
        equipment="MainMeter",
        family="energy",
        tier="energy",
        path=PATH,
        signals=(
            SignalSpec(name="ActivePower", unit="kW", base_value=100.0, tier="energy", export_metric=True),
            SignalSpec(name="PowerFactor", unit="", base_value=0.95, tier="status"),
        ),
        serves=("Production/Line1",),
    )
    view = DeviceView(context, "Dormagen", None, spec.serves)
    return SignalDevice(spec, {}, view, 7)


class _Sim:
    """The one attribute SimulatorCollector reads."""

    def __init__(self, signal_devices):
        self.signal_devices = signal_devices


def _families(registry) -> dict[str, object]:
    return {family.name: family for family in registry.collect()}


@pytest.mark.asyncio
async def test_published_messages_are_counted_by_tier_and_family():
    device = _device()
    device.evaluate(1.0)
    await device.publish_tier("energy")
    assert device.published_by_tier["energy"] == 1
    assert device.published_by_tier["status"] == 0


@pytest.mark.asyncio
async def test_the_collector_renders_the_five_metrics_spec_5_3_names():
    device = _device()
    device.evaluate(1.0)
    await device.publish_tier("energy")
    registry = SimulatorCollector.build_registry(_Sim([device]))

    rendered = generate_latest(registry).decode()
    assert 'uns_simulator_messages_published_total{family="energy",tier="energy"} 1.0' in rendered
    assert 'uns_simulator_publish_failures_total{device="main-meter"} 0.0' in rendered
    assert 'uns_simulator_reconnects_total{device="main-meter"} 0.0' in rendered
    assert "uns_simulator_devices_connected 1.0" in rendered
    assert 'uns_simulator_signal_value{device="main-meter",signal="ActivePower"}' in rendered


@pytest.mark.asyncio
async def test_only_signals_flagged_export_metric_become_a_gauge():
    """A profile has hundreds of signals. Exporting all of them would make every
    Prometheus scrape a cardinality problem, so the flag is opt-in per signal."""
    device = _device()
    device.evaluate(1.0)
    registry = SimulatorCollector.build_registry(_Sim([device]))

    rendered = generate_latest(registry).decode()
    assert 'signal="ActivePower"' in rendered
    assert 'signal="PowerFactor"' not in rendered


def test_a_simulator_with_no_devices_still_renders_every_metric_name():
    """A stopped simulator must not produce an empty scrape: a missing series and a
    zero series look identical in a graph, and only one of them is true."""
    registry = SimulatorCollector.build_registry(_Sim([]))

    names = _families(registry).keys()
    assert "uns_simulator_messages_published" in names
    assert "uns_simulator_publish_failures" in names
    assert "uns_simulator_reconnects" in names
    assert "uns_simulator_devices_connected" in names
    assert "uns_simulator_signal_value" in names
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_simulator.metrics'`.

- [ ] **Step 3: Count publishes per tier in `devices.py`**

In `SignalDevice.__init__`, immediately after `self.tiers = frozenset(...)`, add:

```python
        # Prometheus wants a per-tier breakdown (spec 5.3) and `publish_ok` is one total.
        # Seeded with every tier the device owns so a tier that has not published yet is a
        # zero rather than a missing series.
        self.published_by_tier: dict[str, int] = dict.fromkeys(self.tiers, 0)
```

In `SignalDevice.publish_tier`, replace the final `return published` with:

```python
        self.published_by_tier[tier] = self.published_by_tier.get(tier, 0) + published
        return published
```

- [ ] **Step 4: Write `metrics.py`**

```python
# 99_simulator/src/uns_simulator/metrics.py
"""Platform Observability for the simulator: Prometheus metrics on their own port.

A custom collector rather than module-level Counter objects, because every number
already exists. AsyncMQTTDevice counts publish_ok / publish_fail / reconnects and
SignalDevice counts published_by_tier; mirroring those into prometheus_client Counters
would create a second source for one fact, and the copy is what goes stale.

This is Platform Observability, never Process Visualization: it says whether the
simulator is publishing, not what the simulated plant is doing. The one exception is
`uns_simulator_signal_value`, which exists so a Grafana panel can be built before the
historian has ingested anything, and which is opt-in per signal for that reason.
"""

import logging
from collections.abc import Iterator

from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric

LOGGER = logging.getLogger(__name__)


class SimulatorCollector:
    """Renders the simulator's live counters at scrape time.

    `collect()` runs on prometheus_client's HTTP thread, not the simulation's event loop,
    so every container it walks is copied before it is iterated. Walking a list the loop
    is appending to raises mid-scrape and loses the whole response, not just one series.
    """

    def __init__(self, simulator) -> None:
        self.simulator = simulator

    @classmethod
    def build_registry(cls, simulator) -> CollectorRegistry:
        """A registry holding only this collector.

        Its own registry rather than the default one: the default also carries the Python
        process and GC collectors, and 9093 exists to answer one question.
        """
        registry = CollectorRegistry()
        registry.register(cls(simulator))
        return registry

    def collect(self) -> Iterator[Metric]:
        devices = list(self.simulator.signal_devices)

        published = CounterMetricFamily(
            "uns_simulator_messages_published",
            "Payloads published by the simulator, by cadence tier and sensor family.",
            labels=["tier", "family"],
        )
        for device in devices:
            for tier, count in dict(device.published_by_tier).items():
                published.add_metric([tier, device.spec.family], count)
        yield published

        failures = CounterMetricFamily(
            "uns_simulator_publish_failures",
            "Publish attempts that raised, by device.",
            labels=["device"],
        )
        reconnects = CounterMetricFamily(
            "uns_simulator_reconnects",
            "Broker reconnections, by device.",
            labels=["device"],
        )
        for device in devices:
            failures.add_metric([device.spec.id], device.publish_fail)
            reconnects.add_metric([device.spec.id], device.reconnects)
        yield failures
        yield reconnects

        connected = GaugeMetricFamily(
            "uns_simulator_devices_connected",
            "Simulated devices currently holding a broker connection.",
        )
        connected.add_metric([], sum(1 for device in devices if device.connected))
        yield connected

        values = GaugeMetricFamily(
            "uns_simulator_signal_value",
            "Current value of signals declared with export_metric, by device and signal.",
            labels=["device", "signal"],
        )
        for device in devices:
            for spec in device.spec.signals:
                if not spec.export_metric:
                    continue
                value = device.values.get(spec.name)
                # Booleans are ints in Python and a bool gauge would silently read 1.0;
                # a signal worth exporting is numeric, so skip everything else.
                if isinstance(value, int | float) and not isinstance(value, bool):
                    values.add_metric([device.spec.id, spec.name], float(value))
        yield values


def start_metrics_server(simulator, port: int) -> CollectorRegistry:
    """Serve the collector on `port` in a background thread, and return its registry."""
    registry = SimulatorCollector.build_registry(simulator)
    start_http_server(port, registry=registry)
    LOGGER.info("Simulator metrics available on port %d", port)
    return registry
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd 99_simulator && uv run pytest test/test_metrics.py test/test_devices.py -v`
Expected: PASS. `test_devices.py` is included because Step 3 changed `publish_tier`.

- [ ] **Step 6: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/metrics.py 99_simulator/src/uns_simulator/devices.py 99_simulator/test/test_metrics.py
git commit -m "feat(simulator): expose Prometheus metrics through a custom collector on 9093"
```

---

## Task 3: Run state, and a pause that keeps the plant moving

Spec §5.2 needs four verbs, and `pause` is the one with a real design decision in it:
pausing **keeps `PlantClock` ticking and halts publishing**. A paused plant carries on
heating up, changing shift and moving through PackML states, so resuming shows where it
went. Stopping the clock instead would make pause an alias for stop with extra steps.

That is achievable without touching `devices.py` at all: the clock is one task and
publishing is a set of per-tier tasks, so pause cancels the second set and leaves the
first alone.

**Files:**
- Modify: `99_simulator/src/uns_simulator/simulator.py`
- Test: `99_simulator/test/test_simulator.py`

**Interfaces:**
- Consumes: `UnifiedNamespaceSimulator.__init__`, `.signal_devices`, `.profile`, `.clock`, `.tick`, `._run_clock`, `.run_simulation`, `._stop_simulation`, `.announce_device_count` (plan A Task 16); `PlantClock.tick_s`/`.tick_count`/`.running`/`.stop()`/`.on_transition()`; `LoadedProfile.tiers`; `SignalDevice.tiers`/`.enabled`/`.run_tier`/`.stop()`.
- Produces: `RUN_STATES`; `ReconfigurationError(field, message)`; `UnifiedNamespaceSimulator._init_run_state()`, `.run_state`, `.created_at`, `.started_at`, `.overrides_active`, `.lock`, `._clock_task`, `._publish_tasks`, `._transition_callbacks`, `._schedule_publish_tasks()`, `async _cancel_publish_tasks()`, `async start()`, `async pause()`, `async resume()`, `async stop()`, `_notify_transition(site, line, state)`, `on_plant_transition(callback)`. Task 4 adds the reconfiguration methods, Tasks 6-7 call the verbs, Task 8 calls `on_plant_transition`.

- [ ] **Step 1: Write the failing tests**

Add to `99_simulator/test/test_simulator.py`. The `_sim()` helper already there gains one
line — see Step 3 — and these tests use it:

```python
@pytest.mark.asyncio
async def test_a_fresh_simulator_is_stopped():
    sim = _sim()
    assert sim.run_state == "stopped"
    assert sim.started_at is None
    assert sim._publish_tasks == []


@pytest.mark.asyncio
async def test_start_runs_the_clock_and_schedules_one_task_per_device_tier():
    sim = _sim()
    sim.clock.tick_s = 0.01
    expected = sum(len(device.tiers) for device in sim.signal_devices)

    await sim.start()
    try:
        assert sim.run_state == "running"
        assert len(sim._publish_tasks) == expected
        assert sim._clock_task is not None
        await asyncio.sleep(0.05)
        assert sim.clock.tick_count > 0
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_start_twice_does_not_double_the_publishers():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        scheduled = len(sim._publish_tasks)
        await sim.start()
        assert len(sim._publish_tasks) == scheduled
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_pause_halts_publishing_and_keeps_the_plant_moving():
    """The point of pause: the world carries on so resuming shows where it went."""
    sim = _sim()
    sim.clock.tick_s = 0.01
    sim.profile.tiers = dict.fromkeys(sim.profile.tiers, 0.01)

    await sim.start()
    try:
        await asyncio.sleep(0.05)
        await sim.pause()
        assert sim.run_state == "paused"
        assert sim._publish_tasks == []

        published = sim.status()["published_total"]
        ticks = sim.clock.tick_count
        await asyncio.sleep(0.05)

        assert sim.status()["published_total"] == published
        assert sim.clock.tick_count > ticks
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_resume_restarts_publishing_without_restarting_the_clock():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        clock_task = sim._clock_task
        started_at = sim.started_at
        await sim.pause()
        await sim.resume()

        assert sim.run_state == "running"
        assert sim._clock_task is clock_task
        assert sim.started_at == started_at
        assert sim._publish_tasks != []
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_stop_cancels_every_task_and_forgets_the_run():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    await sim.stop()

    assert sim.run_state == "stopped"
    assert sim._publish_tasks == []
    assert sim._clock_task is None
    assert sim.started_at is None
    assert sim.clock.running is False


@pytest.mark.asyncio
async def test_stop_and_pause_are_idempotent():
    sim = _sim()
    await sim.pause()
    assert sim.run_state == "stopped"
    await sim.stop()
    await sim.stop()
    assert sim.run_state == "stopped"


@pytest.mark.asyncio
async def test_a_disabled_device_is_never_scheduled():
    sim = _sim()
    sim.clock.tick_s = 0.01
    sim.signal_devices[0].enabled = False
    expected = sum(len(d.tiers) for d in sim.signal_devices[1:])

    await sim.start()
    try:
        assert len(sim._publish_tasks) == expected
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_a_failing_transition_listener_does_not_silence_the_others():
    """PlantClock swallows callback exceptions, so a broken listener would otherwise be
    invisible and could starve the one that publishes self-telemetry."""
    sim = _sim()
    seen: list[str] = []
    sim.on_plant_transition(lambda site, line, state: (_ for _ in ()).throw(RuntimeError("boom")))
    sim.on_plant_transition(lambda site, line, state: seen.append(state))

    sim._notify_transition("Dormagen", "Production/Line1", "Execute")
    assert seen == ["Execute"]
```

`test_simulator.py` already imports `asyncio` and `pytest` for plan A's `run_simulation`
tests; if the import of `asyncio` is missing at the top of the file, add it.

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_simulator.py -k "run_state or start or pause or resume or stop or disabled or listener" -v`
Expected: FAIL — `AttributeError: 'UnifiedNamespaceSimulator' object has no attribute 'run_state'`.

- [ ] **Step 3: Have `_sim()` initialise the run state**

Plan A's `_sim()` builds the object with `__new__` and hand-sets its attributes. Add one
line at the end, immediately before it returns:

```python
    sim._init_run_state()
    return sim
```

One call rather than eight assignments, so the next attribute the control API needs does
not have to be remembered here as well.

- [ ] **Step 4: Add the run state machine to `simulator.py`**

Extend the imports at the top of `simulator.py`:

```python
import time
from collections.abc import Callable
```

Add, above the class:

```python
RUN_STATES = ("stopped", "starting", "running", "paused")


class ReconfigurationError(ValueError):
    """A runtime configuration change the simulator refuses, with the field to blame.

    Carries `field` separately so api.py can name it in a 422 without parsing the
    message, which is what spec 5.2 asks for.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message
```

Add these methods to `UnifiedNamespaceSimulator`:

```python
    def _init_run_state(self) -> None:
        """Everything the control API touches. Called from __init__ and from tests.

        A method rather than eight lines in __init__ so that test_simulator.py's `_sim()`,
        which constructs the object with __new__, has one thing to call and cannot fall
        silently behind when another attribute is added.
        """
        self.run_state = "stopped"
        # Two clocks on purpose: `created_at` is the process (GET /simulator/health) and
        # `started_at` is the current run (GET /simulator/status). Conflating them makes a
        # restarted plant look like it has been publishing for hours.
        self.created_at = time.monotonic()
        self.started_at: float | None = None
        self.overrides_active = False
        self.lock = asyncio.Lock()
        self._clock_task: asyncio.Task[None] | None = None
        self._publish_tasks: list[asyncio.Task[None]] = []
        self._transition_callbacks: list[Callable[[str, str, str], None]] = []
        self.clock.on_transition(self._notify_transition)

    def _schedule_publish_tasks(self) -> None:
        """One task per (device, tier), skipping disabled devices and zero intervals."""
        for device in self.signal_devices:
            if not device.enabled:
                continue
            for tier in sorted(device.tiers):
                # Already multiplied by the profile's tier_scale by load_profile.
                interval = self.profile.tiers.get(tier, 0.0)
                if interval <= 0.0:
                    # tier 'event' publishes on change from the tick; scheduling it would
                    # be a busy loop.
                    continue
                self._publish_tasks.append(asyncio.create_task(device.run_tier(tier, interval)))

    async def _cancel_publish_tasks(self) -> None:
        """Cancel, rather than set a flag.

        `run_tier` sleeps for its whole interval, so a cooperative flag would leave the
        5400 s meter tier publishing ninety minutes after the operator pressed pause.
        """
        tasks, self._publish_tasks = self._publish_tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self) -> None:
        """Start or resume publishing. Idempotent.

        From `paused` the clock was never stopped, so only the publishers are rebuilt and
        `started_at` is left alone: a pause is part of the same run.
        """
        if self.run_state == "running":
            return
        was_paused = self.run_state == "paused"
        self.run_state = "starting"
        if not was_paused:
            self.started_at = time.monotonic()
            self._clock_task = asyncio.create_task(self._run_clock())
        self._schedule_publish_tasks()
        self.run_state = "running"
        LOGGER.info(
            "Simulator running: profile %s, %d devices, %d publishers",
            self.profile.name,
            len(self.signal_devices),
            len(self._publish_tasks),
        )

    async def pause(self) -> None:
        """Stop publishing; keep simulating. A no-op unless currently running."""
        if self.run_state != "running":
            return
        await self._cancel_publish_tasks()
        self.run_state = "paused"
        LOGGER.info("Simulator paused; the plant clock keeps running")

    async def resume(self) -> None:
        """The inverse of pause. `start` already handles the paused branch."""
        await self.start()

    async def stop(self) -> None:
        """Stop publishing, stop the clock, disconnect. Idempotent."""
        if self.run_state == "stopped":
            return
        await self._cancel_publish_tasks()
        self.clock.stop()
        if self._clock_task is not None:
            self._clock_task.cancel()
            await asyncio.gather(self._clock_task, return_exceptions=True)
            self._clock_task = None
        for device in self.signal_devices:
            await device.stop()
        self.run_state = "stopped"
        self.started_at = None
        LOGGER.info("Simulator stopped")

    def _notify_transition(self, site: str, line: str, state: str) -> None:
        """The single PackML transition listener registered on the clock.

        PlantClock calls its listeners synchronously and swallows whatever they raise, so
        one broken listener must not take the others with it — and must not disappear.
        """
        LOGGER.info("Plant %s/%s -> %s", site, line, state)
        for callback in self._transition_callbacks:
            try:
                callback(site, line, state)
            except Exception:
                LOGGER.exception("Plant transition listener failed for %s/%s", site, line)

    def on_plant_transition(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a PackML transition listener.

        Used by self_telemetry.py, whose callback only enqueues: the clock is on the hot
        path and an awaited publish here would slow every tick.
        """
        self._transition_callbacks.append(callback)
```

- [ ] **Step 5: Call `_init_run_state()` from `__init__`**

At the very end of `__init__` — after `self.clock` and `self.signal_devices` exist, and
after plan A's log lines and warning loop — add:

```python
        # Last, because it registers a listener on self.clock.
        self._init_run_state()
```

- [ ] **Step 6: Have `run_simulation` and `_stop_simulation` use the verbs**

In `run_simulation`, replace plan A's clock-and-tier scheduling block — the
`self.clock.on_transition(lambda ...)`, the `self.tasks.append(asyncio.create_task(self._run_clock()))`
and the `for device in self.signal_devices:` loop that follows it — with one line:

```python
        await self.start()
```

The lambda goes with it: `_notify_transition` logs the same line and is already
registered, so keeping both would log every transition twice and would re-register a new
lambda on every run.

Keep the legacy loop that follows unchanged — `self.tasks` now holds only the PLC, SCADA
and HMI tasks, and `self._publish_tasks` and `self._clock_task` hold everything the plant
model owns.

In `_stop_simulation`, put the new verb first:

```python
    async def _stop_simulation(self):
        """Cleanly stop all devices"""
        await self.stop()
        for device in self.devices:
            await device.stop()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
```

`self.clock.stop()` moves inside `stop()`. Stopping a device twice is safe — plan A's
`test_disconnecting_twice_is_harmless` covers exactly that — and the second loop is what
ends the legacy devices.

- [ ] **Step 7: Run the whole suite**

Run: `cd 99_simulator && uv run pytest -v`
Expected: everything passes, including plan A's two `run_simulation` tests, which now
exercise `start()`.

- [ ] **Step 8: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/simulator.py 99_simulator/test/test_simulator.py
git commit -m "feat(simulator): add start/pause/resume/stop, where pause keeps the plant clock running"
```

---

## Task 4: Runtime reconfiguration

The four writes from spec §5.2 that change the plant rather than its run state. All of
them are runtime-only: nothing is written back to `conf/simulator/*.yaml`, and
`overrides_active` is how the console tells an operator that the running plant no longer
matches the files.

A profile switch is the expensive one — it rebuilds the `PlantContext`, the clock and
every device — so it validates and loads **before** it stops anything. A rejected switch
must leave a running plant running.

**Files:**
- Modify: `99_simulator/src/uns_simulator/simulator.py`
- Test: `99_simulator/test/test_simulator.py`

**Interfaces:**
- Consumes: everything Task 3 produced; `load_simulator_config(settings)`, `load_profile(raw, name, seed=...)`, `FAMILIES`, `LoadedProfile.tiers`/`.families`/`.name`/`.seed` (plan A Tasks 15-16); `create_signal_devices()`; `PlantClock(context, tick_s=...)`.
- Produces: `UnifiedNamespaceSimulator.raw_config` (now an attribute, not a local), `async apply_profile(name, seed=None)`, `async apply_tiers(intervals)`, `async apply_families(flags)`, `async set_device_enabled(device_id, enabled)`, `_device_by_id(device_id) -> SignalDevice` (raises `KeyError`), `_rebuild_clock()`, `async _reschedule()`. Task 7 calls all four `apply_*`/`set_*` methods; Task 5 reads `raw_config`.

- [ ] **Step 1: Write the failing tests**

Add to `99_simulator/test/test_simulator.py`:

```python
@pytest.mark.asyncio
async def test_switching_profile_rebuilds_the_devices_and_the_clock():
    sim = _sim()
    original_devices = sim.signal_devices
    original_clock = sim.clock

    await sim.apply_profile("small")

    assert sim.profile.name == "small"
    assert sim.signal_devices is not original_devices
    assert sim.clock is not original_clock
    assert sim.overrides_active is False


@pytest.mark.asyncio
async def test_switching_profile_keeps_a_running_plant_running():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        await sim.apply_profile("small")
        assert sim.run_state == "running"
        assert sim._publish_tasks != []
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_an_unknown_profile_is_refused_and_changes_nothing():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        with pytest.raises(ReconfigurationError) as excinfo:
            await sim.apply_profile("huge")
        assert excinfo.value.field == "profile"
        assert "huge" in excinfo.value.message
        assert sim.run_state == "running"
        assert sim.profile.name == "full"
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_a_new_seed_changes_the_plant_but_not_the_shape():
    sim = _sim()
    before = len(sim.signal_devices)
    await sim.apply_profile("full", seed=1234)

    assert sim.profile.seed == 1234
    assert len(sim.signal_devices) == before


@pytest.mark.asyncio
async def test_a_rebuilt_clock_still_reports_transitions():
    """The bug this guards: a profile switch replaces the clock, and every listener
    registered on the old one is silently gone."""
    sim = _sim()
    seen: list[str] = []
    sim.on_plant_transition(lambda site, line, state: seen.append(state))

    await sim.apply_profile("small")
    sim._notify_transition("Dormagen", "Production/Line1", "Execute")

    assert seen == ["Execute"]


@pytest.mark.asyncio
async def test_a_tier_interval_can_be_changed_at_runtime():
    sim = _sim()
    await sim.apply_tiers({"process": 12.5})

    assert sim.profile.tiers["process"] == 12.5
    assert sim.overrides_active is True


@pytest.mark.asyncio
async def test_an_unknown_tier_names_itself_in_the_refusal():
    sim = _sim()
    with pytest.raises(ReconfigurationError) as excinfo:
        await sim.apply_tiers({"turbo": 1.0})
    assert excinfo.value.field == "turbo"
    assert sim.overrides_active is False


@pytest.mark.asyncio
async def test_a_negative_tier_interval_is_refused():
    sim = _sim()
    with pytest.raises(ReconfigurationError) as excinfo:
        await sim.apply_tiers({"process": -1.0})
    assert excinfo.value.field == "process"


@pytest.mark.asyncio
async def test_changing_a_tier_while_running_reschedules_the_publishers():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        before = list(sim._publish_tasks)
        await sim.apply_tiers({"process": 0.02})
        assert all(task.cancelled() or task.done() for task in before)
        assert sim._publish_tasks != []
        assert all(task not in before for task in sim._publish_tasks)
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_changing_a_tier_while_paused_does_not_start_publishing():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        await sim.pause()
        await sim.apply_tiers({"process": 0.02})
        assert sim.run_state == "paused"
        assert sim._publish_tasks == []
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_disabling_a_family_disables_the_devices_it_contributed():
    sim = _sim()
    family = sim.signal_devices[0].spec.family
    await sim.apply_families({family: False})

    assert sim.profile.families[family] is False
    assert all(not d.enabled for d in sim.signal_devices if d.spec.family == family)
    assert sim.overrides_active is True


@pytest.mark.asyncio
async def test_an_unknown_family_names_itself_in_the_refusal():
    sim = _sim()
    with pytest.raises(ReconfigurationError) as excinfo:
        await sim.apply_families({"nonsense": True})
    assert excinfo.value.field == "nonsense"


@pytest.mark.asyncio
async def test_one_device_can_be_disabled_by_id():
    sim = _sim()
    device_id = sim.signal_devices[0].spec.id
    await sim.set_device_enabled(device_id, False)

    assert sim.signal_devices[0].enabled is False
    assert sim.overrides_active is True


@pytest.mark.asyncio
async def test_an_unknown_device_id_raises_key_error():
    sim = _sim()
    with pytest.raises(KeyError):
        await sim.set_device_enabled("no-such-device", False)
```

`ReconfigurationError` needs adding to `test_simulator.py`'s import of `uns_simulator.simulator`.

`apply_profile("small")` requires a `small` profile in the test fixture's `RAW`. Plan A's
`RAW` in `test_simulator.py` is the merged config dict; if it declares only `full`, add a
`small` profile to `RAW["profiles"]` with `tier_scale: 6.0` and the same families, and
have `_sim()` set `sim.raw_config = RAW` so that `apply_profile` reads the fixture rather
than the filesystem — see Step 3.

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_simulator.py -k "profile or tier or family or device_enabled or seed or clock_still" -v`
Expected: FAIL — `AttributeError: 'UnifiedNamespaceSimulator' object has no attribute 'apply_profile'`.

- [ ] **Step 3: Keep the merged config on the instance**

Plan A's `__init__` assigns the merged configuration to a local:

```python
        raw_config = load_simulator_config(settings)
```

Change that one line to keep it, and use `self.raw_config` in the `load_profile` call on
the following lines:

```python
        # Kept on the instance: GET /simulator/config lists the available profiles from it,
        # and apply_profile re-reads it so a profile added to conf/simulator/ while the
        # simulator is running can be switched to without a restart.
        self.raw_config = load_simulator_config(settings)
```

In `test_simulator.py`'s `_sim()`, add `sim.raw_config = RAW` beside the other hand-set
attributes, before the `sim._init_run_state()` line from Task 3.

- [ ] **Step 4: Add the reconfiguration methods**

Extend `simulator.py`'s imports:

```python
from collections.abc import Callable, Mapping
```

Add to `UnifiedNamespaceSimulator`:

```python
    def _device_by_id(self, device_id: str) -> SignalDevice:
        """The device with this id, or KeyError — which api.py turns into a 404."""
        for device in self.signal_devices:
            if device.spec.id == device_id:
                return device
        raise KeyError(device_id)

    def _rebuild_clock(self) -> None:
        """A new profile means a new PlantContext, so a new clock.

        Re-registering `_notify_transition` is the whole reason this is a method: the bug
        it prevents is a console that stops seeing PackML transitions after the first
        profile switch, with nothing in the log to say why.
        """
        self.clock = PlantClock(self.profile.context, tick_s=self.clock.tick_s)
        self.clock.on_transition(self._notify_transition)

    async def _reschedule(self) -> None:
        """Re-apply the publish schedule.

        A no-op unless publishing is actually happening, so a change made while paused
        takes effect on resume and not before.
        """
        if self.run_state != "running":
            return
        await self._cancel_publish_tasks()
        self._schedule_publish_tasks()

    async def apply_profile(self, name: str, seed: int | None = None) -> None:
        """Switch profile, optionally reseeding. Restores the previous run state.

        Everything that can fail happens before anything is stopped, so a refused switch
        leaves a running plant running rather than stopping it and then explaining why.
        """
        raw = load_simulator_config(settings)
        available = sorted(raw.get("profiles") or {})
        if name not in available:
            known = ", ".join(available) or "none"
            raise ReconfigurationError("profile", f"unknown profile {name!r} (known: {known})")
        try:
            profile = load_profile(raw, name, seed=seed)
        except (KeyError, ValueError) as exc:
            raise ReconfigurationError("profile", str(exc)) from exc

        was_running = self.run_state in ("running", "starting")
        await self.stop()
        self.raw_config = raw
        self.profile = profile
        self._rebuild_clock()
        self.signal_devices = self.create_signal_devices()
        self.announce_device_count()
        # The running plant now matches the files on disk again.
        self.overrides_active = False
        if was_running:
            await self.start()

    async def apply_tiers(self, intervals: Mapping[str, float]) -> None:
        """Override publish intervals, in seconds. Absent tiers are left alone.

        Validated in full before anything is applied, so a body with one good tier and one
        typo changes nothing rather than half of what was asked.
        """
        for tier, interval in intervals.items():
            if tier not in self.profile.tiers:
                known = ", ".join(sorted(self.profile.tiers))
                raise ReconfigurationError(tier, f"unknown tier {tier!r} (known: {known})")
            if interval < 0.0:
                raise ReconfigurationError(tier, f"tier {tier!r} interval must not be negative")
        self.profile.tiers.update(intervals)
        self.overrides_active = True
        await self._reschedule()

    async def apply_families(self, flags: Mapping[str, bool]) -> None:
        """Enable or disable the devices a sensor family contributed.

        This cannot conjure devices for a family the profile never loaded — the YAML for it
        was not read — so enabling such a family sets the flag and changes no device count.
        Switching profile is what loads a new family. GET /simulator/config reports both
        numbers so the console can say so.
        """
        for family in flags:
            if family not in FAMILIES:
                known = ", ".join(FAMILIES)
                raise ReconfigurationError(family, f"unknown family {family!r} (known: {known})")
        self.profile.families.update(flags)
        for device in self.signal_devices:
            if device.spec.family in flags:
                device.enabled = flags[device.spec.family]
        self.overrides_active = True
        await self._reschedule()

    async def set_device_enabled(self, device_id: str, enabled: bool) -> None:
        """Silence or unsilence one device. Raises KeyError if there is no such device."""
        device = self._device_by_id(device_id)
        device.enabled = enabled
        self.overrides_active = True
        await self._reschedule()
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd 99_simulator && uv run pytest test/test_simulator.py -v`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `cd 99_simulator && uv run pytest -v`
Expected: PASS. Step 3 changed `__init__`, so plan A's profile-loading tests are the check
that `self.raw_config` did not break the seed wiring.

- [ ] **Step 7: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/simulator.py 99_simulator/test/test_simulator.py
git commit -m "feat(simulator): reconfigure profile, tiers, families and devices at runtime"
```

---

## Task 5: The read model

Spec §5.1's seven documents, as methods on `UnifiedNamespaceSimulator`. They live here and
not in `api.py` for two reasons: they are testable without HTTP, and it keeps `api.py` thin
enough that a reviewer can see at a glance that no route mutates anything.

Every body in the **Canonical Response Bodies** section above is produced by exactly one
method here.

**Files:**
- Modify: `99_simulator/src/uns_simulator/simulator.py`
- Test: `99_simulator/test/test_simulator.py`

**Interfaces:**
- Consumes: `PlantContext.snapshot()` returning `{site_name: {ambient_temp_c, ambient_rh_pct, wet_bulb_temp_c, wind_speed_ms, barometric_mbar, shift, tariff, grid_co2_g_per_kwh, lines: {"<Area>/<Line>": {state, previous, production_rate, throughput_tph, heat_load, air_demand, time_in_state_s, transition_count}}}}`; `LoadReport.as_dict()` returning `{devices, signals, per_family, per_tier, serves_links, unmatched_templates, warnings}`; `LoadedProfile.messages_per_second()`, `.tier_scale`, `.sites`, `.max_cells_per_line`, `.report`; `SignalDevice.snapshot()`, `.health()`, `.last_publish_ts`; `filter_paths`; `ISA95Hierarchy.kind`/`.nameplate_tph` (plan A Tasks 10-16); `self.hierarchies`; `self.raw_config` (Task 4).
- Produces: `health_body()`, `message_rates()`, an extended `status()`, `plant_snapshot()`, `device_snapshots()`, `signal_snapshot(device_id)`, `config_snapshot()`, `diagnostics()`, `sample_topics(limit=20)`. Task 6 returns each of these verbatim; Task 11 types them.

- [ ] **Step 1: Write the failing tests**

Add to `99_simulator/test/test_simulator.py`. One import is needed at the top of the file,
beside the existing ones:

```python
from uns_simulator.models import ParameterType
```

```python
def test_health_answers_while_the_plant_is_stopped():
    sim = _sim()
    body = sim.health_body()

    assert body["status"] == "ok"
    assert body["uptime_s"] >= 0.0
    assert body["git_hash"]
    assert body["version"]


def test_status_carries_every_key_the_console_polls():
    sim = _sim()
    body = sim.status()

    assert set(body) == {
        "run_state",
        "profile",
        "seed",
        "device_count",
        "signal_count",
        "uptime_s",
        "broker_connected",
        "msg_per_sec",
        "published_total",
        "failed_total",
        "overrides_active",
        "tiers",
        "families",
        "per_tier",
        "tick_count",
    }
    assert body["run_state"] == "stopped"
    assert body["uptime_s"] == 0.0


def test_a_stopped_plant_reports_no_throughput():
    """A theoretical rate from a stopped simulator is the number that ends up in a
    capacity discussion as though it were measured."""
    sim = _sim()
    assert set(sim.status()["msg_per_sec"]) == set(sim.profile.tiers)
    assert all(rate == 0.0 for rate in sim.status()["msg_per_sec"].values())


@pytest.mark.asyncio
async def test_a_running_plant_reports_throughput_and_uptime():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        body = sim.status()
        assert body["run_state"] == "running"
        assert body["uptime_s"] >= 0.0
        assert sum(body["msg_per_sec"].values()) > 0.0
    finally:
        await sim.stop()


def test_the_plant_snapshot_is_keyed_by_site_then_line():
    sim = _sim()
    sites = sim.plant_snapshot()["sites"]

    site = next(iter(sites.values()))
    assert "ambient_temp_c" in site
    assert "shift" in site
    assert "tariff" in site
    line = next(iter(site["lines"].values()))
    assert {"state", "production_rate", "throughput_tph", "heat_load", "air_demand", "time_in_state_s"} <= set(line)


def test_every_device_reports_the_twelve_fields_the_table_shows():
    sim = _sim()
    row = sim.device_snapshots()[0]

    assert set(row) == {
        "id",
        "equipment",
        "topic_prefix",
        "tier",
        "family",
        "enabled",
        "connected",
        "last_publish_ts",
        "publish_ok",
        "publish_fail",
        "last_error",
        "signal_count",
    }


def test_signals_are_returned_for_one_device_by_id():
    sim = _sim()
    device_id = sim.signal_devices[0].spec.id
    body = sim.signal_snapshot(device_id)

    assert body["device_id"] == device_id
    assert len(body["signals"]) == len(sim.signal_devices[0].spec.signals)
    assert "last_publish_ts" in body["signals"][0]
    assert "unit" in body["signals"][0]


def test_each_signal_row_carries_the_topic_it_publishes_on():
    """The console keys its sparklines on this, and only Python knows how to build it."""
    sim = _sim()
    device = sim.signal_devices[0]
    row = sim.signal_snapshot(device.spec.id)["signals"][0]

    assert row["topic"] == f"{device.spec.topic_prefix}/{row['param_type']}/{row['name']}"
    # Exactly the topic ISA95Hierarchy.get_parameter_topic builds for the same signal.
    assert row["topic"] == device.spec.path.get_parameter_topic(
        device.spec.equipment, ParameterType(row["param_type"]), row["name"]
    )


def test_an_unknown_device_id_raises_key_error_from_the_read_model_too():
    sim = _sim()
    with pytest.raises(KeyError):
        sim.signal_snapshot("no-such-device")


def test_the_config_snapshot_lists_the_profiles_that_could_be_switched_to():
    sim = _sim()
    body = sim.config_snapshot()

    assert body["profile"] == "full"
    assert "small" in body["available_profiles"]
    assert body["hierarchy"]
    assert {"enterprise", "site", "area", "line", "cell", "kind"} <= set(body["hierarchy"][0])
    device = body["devices"][0]
    assert {"id", "equipment", "family", "tier", "enabled", "topic_prefix", "signal_count", "serves", "target"} == set(device)
    assert {"site", "area", "line", "cell", "kind"} == set(device["target"])


def test_diagnostics_reports_the_load_report_and_nothing_failing_yet():
    sim = _sim()
    body = sim.diagnostics()

    assert set(body) == {"report", "failing_devices", "sample_topics"}
    assert set(body["report"]) == {
        "devices",
        "signals",
        "per_family",
        "per_tier",
        "serves_links",
        "unmatched_templates",
        "warnings",
    }
    assert body["failing_devices"] == []


def test_a_device_with_failures_shows_up_in_diagnostics():
    sim = _sim()
    sim.signal_devices[0].publish_fail = 3
    sim.signal_devices[0].last_error = "[Errno 111] Connection refused"

    failing = sim.diagnostics()["failing_devices"]
    assert len(failing) == 1
    assert failing[0]["device_id"] == sim.signal_devices[0].device_id
    assert failing[0]["publish_fail"] == 3


def test_sample_topics_look_exactly_like_what_gets_published():
    sim = _sim()
    device = sim.signal_devices[0]
    signal = device.spec.signals[0]
    expected = f"{device.spec.topic_prefix}/{signal.param_type}/{signal.name}"

    topics = sim.sample_topics()
    assert expected in topics
    assert len(topics) <= 20
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_simulator.py -k "health or snapshot or msg_per_sec or throughput or diagnostics or sample_topics or twelve or config_snapshot or every_key" -v`
Expected: FAIL — `AttributeError: 'UnifiedNamespaceSimulator' object has no attribute 'health_body'`.

- [ ] **Step 3: Add the version helper**

Extend `simulator.py`'s imports:

```python
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from uns_simulator.models import ParameterType
```

`ParameterType` is what turns a signal's `param_type` string back into the enum
`get_parameter_topic` takes. `simulator.py` already imports from `models`, so add the name to
that import rather than adding a line.

and add, above the class:

```python
def _package_version() -> str:
    """The installed version of the simulator package.

    "unknown" rather than an exception when the package is not installed, because a health
    endpoint that raises is worse than one that admits ignorance.
    """
    try:
        return version("uns-simulator")
    except PackageNotFoundError:
        return "unknown"
```

- [ ] **Step 4: Add the read model methods**

Add to `UnifiedNamespaceSimulator`:

```python
    def health_body(self) -> dict[str, Any]:
        """Answers while the plant is stopped, which is what makes it a health check.

        `uptime_s` here is the *process*: a container up for an hour with a stopped plant
        is healthy. The *run* uptime lives in status(), and conflating the two makes a
        just-restarted plant look like it has been publishing all day.
        """
        return {
            "status": "ok",
            "uptime_s": round(time.monotonic() - self.created_at, 1),
            "git_hash": os.environ.get("GIT_HASH", "dev"),
            "version": _package_version(),
        }

    def message_rates(self) -> dict[str, float]:
        """Messages per second per tier — all zeros unless publishing is happening."""
        if self.run_state != "running":
            return dict.fromkeys(self.profile.tiers, 0.0)
        return self.profile.messages_per_second()

    def plant_snapshot(self) -> dict[str, Any]:
        """The correlated world: ambient and shift per site, PackML state per line."""
        return {"sites": self.profile.context.snapshot()}

    def device_snapshots(self) -> list[dict[str, Any]]:
        """One row per device, as the console's device table renders it."""
        return [
            {
                "id": device.spec.id,
                "equipment": device.spec.equipment,
                "topic_prefix": device.spec.topic_prefix,
                "tier": device.spec.tier,
                "family": device.spec.family,
                "enabled": device.enabled,
                "connected": device.connected,
                "last_publish_ts": device.last_publish_ts,
                "publish_ok": device.publish_ok,
                "publish_fail": device.publish_fail,
                "last_error": device.last_error,
                "signal_count": len(device.spec.signals),
            }
            for device in self.signal_devices
        ]

    def signal_snapshot(self, device_id: str) -> dict[str, Any]:
        """One device's signals. Raises KeyError for an unknown id."""
        device = self._device_by_id(device_id)
        return {
            "device_id": device_id,
            # last_publish_ts is the device's, not each signal's: a device publishes a whole
            # tier in one pass, so per-signal timestamps would be one number repeated.
            #
            # The topic is built here rather than in the browser. get_parameter_topic is the
            # one definition of what a signal's topic is, and a second copy of that join in
            # TypeScript would drift the day a segment moves — silently, because a
            # subscription to a topic nothing publishes on looks exactly like a quiet signal.
            "signals": [
                {
                    **row,
                    "last_publish_ts": device.last_publish_ts,
                    "topic": device.spec.path.get_parameter_topic(
                        device.spec.equipment, ParameterType(row["param_type"]), row["name"]
                    ),
                }
                for row in device.snapshot()
            ],
        }

    def config_snapshot(self) -> dict[str, Any]:
        """What is loaded and what could be loaded. Read-only; the writes are spec 5.2."""
        paths = filter_paths(
            self.hierarchies,
            sites=self.profile.sites or None,
            max_cells_per_line=self.profile.max_cells_per_line,
        )
        return {
            "profile": self.profile.name,
            "available_profiles": sorted(self.raw_config.get("profiles") or {}),
            "seed": self.profile.seed,
            "tier_scale": self.profile.tier_scale,
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "sites": list(self.profile.sites),
            "max_cells_per_line": self.profile.max_cells_per_line,
            "hierarchy": [
                {
                    "enterprise": path.enterprise,
                    "site": path.site,
                    "area": path.area,
                    "line": path.line,
                    "cell": path.cell,
                    "kind": path.kind,
                    "nameplate_tph": path.nameplate_tph,
                }
                for path in paths
            ],
            "devices": [
                {
                    "id": device.spec.id,
                    "equipment": device.spec.equipment,
                    "family": device.spec.family,
                    "tier": device.spec.tier,
                    "enabled": device.enabled,
                    "topic_prefix": device.spec.topic_prefix,
                    "signal_count": len(device.spec.signals),
                    # The paths the YAML declared, not the ones that resolved: a `serves`
                    # entry matching nothing is precisely what an operator needs to see, and
                    # GET /simulator/diagnostics reports how many of them resolved.
                    "serves": list(device.spec.serves),
                    # `DeviceSpec` keeps the resolved path rather than the selector that
                    # matched it, so this is where the device actually lives.
                    "target": {
                        "site": device.spec.path.site,
                        "area": device.spec.path.area,
                        "line": device.spec.path.line,
                        "cell": device.spec.path.cell,
                        "kind": device.spec.path.kind,
                    },
                }
                for device in self.signal_devices
            ],
        }

    def diagnostics(self) -> dict[str, Any]:
        """Why the inventory looks the way it does, and what is going wrong right now."""
        return {
            "report": self.profile.report.as_dict(),
            "failing_devices": [
                device.health()
                for device in self.signal_devices
                if device.publish_fail or device.reconnects or device.last_error
            ],
            "sample_topics": self.sample_topics(),
        }

    def sample_topics(self, limit: int = 20) -> list[str]:
        """Real topics this profile publishes to, for pasting into an MQTT client.

        Assembled the same way ISA95Hierarchy.get_parameter_topic assembles them, so the
        console cannot show a topic that is not on the broker.
        """
        topics: list[str] = []
        for device in self.signal_devices:
            for spec in device.spec.signals:
                topics.append(f"{device.spec.topic_prefix}/{spec.param_type}/{spec.name}")
                if len(topics) >= limit:
                    return topics
        return topics
```

Extend the `profiles` import to bring in `filter_paths`:

```python
from uns_simulator.profiles import FAMILIES, PRODUCTION_KIND, LoadedProfile, filter_paths, load_profile
```

- [ ] **Step 5: Extend `status()` with the four control-API keys**

Plan A's `status()` returns eleven keys. Replace its `return` statement with:

```python
        return {
            "run_state": self.run_state,
            "profile": self.profile.name,
            "seed": self.profile.seed,
            "device_count": len(self.signal_devices),
            "signal_count": sum(len(d.spec.signals) for d in self.signal_devices),
            "uptime_s": 0.0 if self.started_at is None else round(time.monotonic() - self.started_at, 1),
            "broker_connected": any(d.connected for d in self.signal_devices),
            "msg_per_sec": self.message_rates(),
            "published_total": sum(d.publish_ok for d in self.signal_devices),
            "failed_total": sum(d.publish_fail for d in self.signal_devices),
            "overrides_active": self.overrides_active,
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "per_tier": per_tier,
            "tick_count": self.clock.tick_count,
        }
```

and update its docstring to `"""Runtime status. Every write in spec 5.2 returns this body."""`

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd 99_simulator && uv run pytest test/test_simulator.py -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/simulator.py 99_simulator/test/test_simulator.py
git commit -m "feat(simulator): add the read model behind the seven control API GETs"
```

---

## Task 6: The read endpoints

`api.py` translates and nothing else: each handler is one call into the read model plus one
exception mapped to a status code.

Because it is only a translation layer, its tests drive it with a small fake simulator
rather than a real one. That is deliberate — it keeps these tests fast and, more
importantly, keeps them honest about what they check: routing, envelopes, status codes and
the token dependency. The read model itself is covered against the real object in Task 5.

**Files:**
- Create: `99_simulator/src/uns_simulator/api.py`
- Test: `99_simulator/test/test_api.py` (create)

**Interfaces:**
- Consumes: `SimulatorAPIConfig` (Task 1); `UnifiedNamespaceSimulator.health_body()`, `.status()`, `.config_snapshot()`, `.plant_snapshot()`, `.device_snapshots()`, `.signal_snapshot(device_id)`, `.diagnostics()` (Task 5).
- Produces: `create_app(simulator, token: str | None = None) -> FastAPI`, serving `GET /simulator/{health,status,config,plant,devices,devices/{device_id}/signals,diagnostics}` and OpenAPI docs at `/simulator/docs`. Task 7 adds the writes to the same router; Task 9 calls `create_app`.

- [ ] **Step 1: Write the failing tests**

```python
# 99_simulator/test/test_api.py
"""The control API's HTTP surface (spec 5).

Driven by a fake simulator on purpose. api.py is a translation layer — one call in, one
status code out — and these tests are about the translation. The read model behind it is
tested against the real simulator in test_simulator.py.
"""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from uns_simulator.api import create_app
from uns_simulator.simulator import ReconfigurationError

STATUS = {
    "run_state": "stopped",
    "profile": "small",
    "seed": 20260831,
    "device_count": 2,
    "signal_count": 5,
    "uptime_s": 0.0,
    "broker_connected": False,
    "msg_per_sec": {"fast": 0.0, "process": 0.0, "energy": 0.0, "status": 0.0, "meter": 0.0, "lab": 0.0, "event": 0.0},
    "published_total": 0,
    "failed_total": 0,
    "overrides_active": False,
    "tiers": {"fast": 6.0, "process": 30.0, "energy": 90.0, "status": 180.0, "meter": 5400.0, "lab": 10800.0, "event": 0.0},
    "families": {"energy": True, "water": False, "utilities": False, "asset_health": False, "production": False, "safety": False},
    "per_tier": {"process": 5},
    "tick_count": 0,
}


class FakeSimulator:
    """Records what the routes asked for, and can be told to fail or to be slow."""

    def __init__(self, *, slow: bool = False) -> None:
        self.lock = asyncio.Lock()
        self.slow = slow
        self.calls: list[tuple] = []
        self.depth = 0
        self.overlaps = 0
        self.reject: ReconfigurationError | None = None
        self.unknown_device = False

    def health_body(self):
        return {"status": "ok", "uptime_s": 1.5, "git_hash": "dev", "version": "0.9.38"}

    def status(self):
        return dict(STATUS)

    def config_snapshot(self):
        return {"profile": "small", "available_profiles": ["full", "small"], "devices": []}

    def plant_snapshot(self):
        return {"sites": {"Dormagen": {"shift": "A", "lines": {}}}}

    def device_snapshots(self):
        return [{"id": "main-meter", "equipment": "MainMeter"}]

    def signal_snapshot(self, device_id):
        if self.unknown_device:
            raise KeyError(device_id)
        return {"device_id": device_id, "signals": [{"name": "ActivePower"}]}

    def diagnostics(self):
        return {"report": {"devices": 2}, "failing_devices": [], "sample_topics": []}

    async def _serialised(self, name, *args):
        self.calls.append((name, *args))
        self.depth += 1
        self.overlaps += max(0, self.depth - 1)
        if self.slow:
            await asyncio.sleep(0.02)
        self.depth -= 1
        if self.reject is not None:
            raise self.reject

    async def start(self):
        await self._serialised("start")

    async def stop(self):
        await self._serialised("stop")

    async def pause(self):
        await self._serialised("pause")

    async def resume(self):
        await self._serialised("resume")

    async def apply_profile(self, name, seed=None):
        await self._serialised("apply_profile", name, seed)

    async def apply_tiers(self, intervals):
        await self._serialised("apply_tiers", dict(intervals))

    async def apply_families(self, flags):
        await self._serialised("apply_families", dict(flags))

    async def set_device_enabled(self, device_id, enabled):
        self.calls.append(("set_device_enabled", device_id, enabled))
        if self.unknown_device:
            raise KeyError(device_id)


def _client(sim=None, token=None) -> TestClient:
    return TestClient(create_app(sim if sim is not None else FakeSimulator(), token=token))


def test_health_is_served_under_the_simulator_prefix():
    """The prefix is not decoration: nginx and the Vite dev server both proxy on it,
    and an unprefixed route would be invisible from the browser."""
    response = _client().get("/simulator/health")

    assert response.status_code == 200
    assert set(response.json()) == {"status", "uptime_s", "git_hash", "version"}


def test_status_is_returned_verbatim():
    response = _client().get("/simulator/status")

    assert response.status_code == 200
    assert response.json() == STATUS


@pytest.mark.parametrize("path", ["/simulator/config", "/simulator/plant", "/simulator/diagnostics"])
def test_the_remaining_reads_answer(path):
    assert _client().get(path).status_code == 200


def test_devices_are_wrapped_in_an_envelope():
    """An envelope rather than a bare array, so a field can be added later without every
    consumer's type changing shape."""
    body = _client().get("/simulator/devices").json()

    assert list(body) == ["devices"]
    assert body["devices"][0]["id"] == "main-meter"


def test_signals_are_returned_for_a_named_device():
    body = _client().get("/simulator/devices/main-meter/signals").json()

    assert body["device_id"] == "main-meter"
    assert body["signals"][0]["name"] == "ActivePower"


def test_an_unknown_device_is_a_404_not_an_empty_list():
    sim = FakeSimulator()
    sim.unknown_device = True

    response = _client(sim).get("/simulator/devices/nope/signals")

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_the_openapi_document_is_served():
    assert _client().get("/simulator/openapi.json").status_code == 200


def test_without_a_configured_token_every_route_is_open():
    assert _client().get("/simulator/status").status_code == 200


def test_a_configured_token_is_required_on_every_route():
    """Including /health. The simulator has no Docker healthcheck to exempt, and one
    exempt route is how a shared secret becomes decorative."""
    client = _client(token="s3cret")

    assert client.get("/simulator/status").status_code == 401
    assert client.get("/simulator/health").status_code == 401
    assert client.get("/simulator/status", headers={"X-Simulator-Token": "s3cret"}).status_code == 200


def test_a_wrong_token_is_a_401():
    client = _client(token="s3cret")
    assert client.get("/simulator/status", headers={"X-Simulator-Token": "wrong"}).status_code == 401


@pytest.mark.asyncio
async def test_the_app_can_be_driven_without_a_server():
    """The transport Task 7's concurrency test needs; proven here on a read."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(FakeSimulator())), base_url="http://sim"
    ) as client:
        response = await client.get("/simulator/status")

    assert response.status_code == 200
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_simulator.api'`.

- [ ] **Step 3: Write `api.py`**

```python
# 99_simulator/src/uns_simulator/api.py
"""The simulator's control API (spec 5).

Served by uvicorn inside the simulation's own event loop, so every handler reads live
in-process state. There is no database, no cache and no snapshot thread: `simulator` *is*
the running plant.

This module translates and nothing else. Each handler is one call into the simulator plus
one exception mapped to a status code; all the behaviour lives in simulator.py, where it
can be tested without HTTP.

Deliberately not part of the GraphQL surface in 07_uns_graphql: GraphQL queries the
Unified Namespace, and this commands a process that happens to publish into it. See
docs/adr/0007-simulator-control-api-outside-graphql.md.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException

from uns_simulator.simulator import ReconfigurationError, UnifiedNamespaceSimulator

LOGGER = logging.getLogger(__name__)


def _unknown_device(device_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"unknown device {device_id!r}")


def _rejected(exc: ReconfigurationError) -> HTTPException:
    """A domain refusal, as a 422 naming the field to blame (spec 5.2).

    A dict rather than a string, so the console can highlight the offending control instead
    of showing a sentence in a toast.
    """
    return HTTPException(status_code=422, detail={"field": exc.field, "message": exc.message})


def create_app(simulator: UnifiedNamespaceSimulator, token: str | None = None) -> FastAPI:
    """Build the app around a live simulator.

    A factory rather than a module-level `app`, because the simulator has to exist first —
    and because the tests build several.
    """
    app = FastAPI(
        title="UNS simulator control API",
        description=(
            "Run control and observation for 99_simulator. Development and demonstration "
            "software: it generates synthetic plant data and is not for production use."
        ),
        docs_url="/simulator/docs",
        openapi_url="/simulator/openapi.json",
        redoc_url=None,
    )

    def require_token(x_simulator_token: Annotated[str | None, Header()] = None) -> None:
        """The optional shared secret from spec 10. No token configured means open."""
        if token is None or x_simulator_token == token:
            return
        raise HTTPException(status_code=401, detail="X-Simulator-Token is missing or wrong")

    # The prefix is what nginx and the Vite dev server proxy on, so it is part of the
    # contract rather than a tidy-looking default.
    router = APIRouter(prefix="/simulator", dependencies=[Depends(require_token)])

    @router.get("/health")
    async def get_health() -> dict[str, Any]:
        """Liveness. Answers while the plant is stopped."""
        return simulator.health_body()

    @router.get("/status")
    async def get_status() -> dict[str, Any]:
        """The document the console polls every two seconds."""
        return simulator.status()

    @router.get("/config")
    async def get_config() -> dict[str, Any]:
        """What is loaded, and what could be. Read-only."""
        return simulator.config_snapshot()

    @router.get("/plant")
    async def get_plant() -> dict[str, Any]:
        """The correlated plant state, per site and per line."""
        return simulator.plant_snapshot()

    @router.get("/devices")
    async def get_devices() -> dict[str, Any]:
        return {"devices": simulator.device_snapshots()}

    @router.get("/devices/{device_id}/signals")
    async def get_device_signals(device_id: str) -> dict[str, Any]:
        try:
            return simulator.signal_snapshot(device_id)
        except KeyError:
            raise _unknown_device(device_id) from None

    @router.get("/diagnostics")
    async def get_diagnostics() -> dict[str, Any]:
        """The load report, whatever is failing, and topics to paste into an MQTT client."""
        return simulator.diagnostics()

    app.include_router(router)
    return app
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd 99_simulator && uv run pytest test/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/api.py 99_simulator/test/test_api.py
git commit -m "feat(simulator): serve the seven control API read endpoints on /simulator"
```

---

## Task 7: The write endpoints

Spec §5.2's five writes. Three properties make them safe enough for a console to drive
without a confirmation dialogue on every click:

1. **Every write returns the full new `status` body**, so a caller never has to follow a
   write with a read and can never render a stale state.
2. **All of them serialise behind one `asyncio.Lock`.** Two profile switches arriving
   together would otherwise rebuild the device list from two directions at once.
3. **All of them are idempotent.** Starting a running plant is a no-op that returns
   success, because a double-clicked button is not an error.

Request bodies are pydantic models with `extra="forbid"` and one named field per tier and
per family. That is what turns a typo into a 422 naming the key, with no hand-written
validation: `{"turbo": 1.0}` and `{"fast": -1}` are both rejected before a handler runs.

**Files:**
- Modify: `99_simulator/src/uns_simulator/api.py`
- Test: `99_simulator/test/test_api.py`

**Interfaces:**
- Consumes: `UnifiedNamespaceSimulator.lock`, `.start()`, `.stop()`, `.pause()`, `.resume()`, `.apply_profile(name, seed=None)`, `.apply_tiers(intervals)`, `.apply_families(flags)`, `.set_device_enabled(device_id, enabled)`, `.status()` (Tasks 3-5); `ReconfigurationError.field`/`.message`.
- Produces: `POST /simulator/run`, `PUT /simulator/profile`, `PUT /simulator/tiers`, `PUT /simulator/families`, `PUT /simulator/devices/{device_id}`, and the models `RunRequest`, `ProfileRequest`, `TiersRequest`, `FamiliesRequest`, `DeviceRequest`. Task 11's TypeScript client mirrors these bodies.

- [ ] **Step 1: Write the failing tests**

Add to `99_simulator/test/test_api.py`:

```python
@pytest.mark.parametrize("action", ["start", "stop", "pause", "resume"])
def test_each_run_action_reaches_the_simulator_and_returns_the_new_status(action):
    sim = FakeSimulator()
    response = _client(sim).post("/simulator/run", json={"action": action})

    assert response.status_code == 200
    assert response.json() == STATUS
    assert sim.calls == [(action,)]


def test_an_unknown_run_action_is_rejected_before_anything_happens():
    sim = FakeSimulator()
    response = _client(sim).post("/simulator/run", json={"action": "explode"})

    assert response.status_code == 422
    assert sim.calls == []


def test_a_profile_switch_passes_the_optional_seed_through():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/profile", json={"profile": "small", "seed": 42})

    assert response.status_code == 200
    assert sim.calls == [("apply_profile", "small", 42)]


def test_a_profile_switch_says_that_the_counters_were_reset():
    """Spec 5.2. Without it a console keeps subtracting from a total that just went to
    zero and renders negative throughput."""
    body = _client().put("/simulator/profile", json={"profile": "small"}).json()

    assert body["counters_reset"] is True


def test_a_refused_profile_switch_is_a_422_naming_the_field():
    sim = FakeSimulator()
    sim.reject = ReconfigurationError("profile", "unknown profile 'huge' (known: full, small)")

    response = _client(sim).put("/simulator/profile", json={"profile": "huge"})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "profile"
    assert "huge" in response.json()["detail"]["message"]


def test_an_unexpected_body_key_is_refused():
    """extra="forbid": a misspelled key that is silently dropped is a control that
    appears to work and does nothing."""
    response = _client().put("/simulator/profile", json={"profile": "small", "sedd": 42})

    assert response.status_code == 422


def test_tiers_accepts_a_partial_body_and_forwards_only_what_was_sent():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"process": 12.5})

    assert response.status_code == 200
    assert sim.calls == [("apply_tiers", {"process": 12.5})]


def test_tiers_accepts_the_event_tier_too():
    """Spec 5.2's body names six tiers; plan A's TIER_DEFAULTS has seven. Excluding
    `event` would leave one tier permanently unreachable."""
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"event": 0.0})

    assert response.status_code == 200
    assert sim.calls == [("apply_tiers", {"event": 0.0})]


def test_an_unknown_tier_is_a_422_that_names_it():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"turbo": 1.0})

    assert response.status_code == 422
    assert any("turbo" in str(item["loc"]) for item in response.json()["detail"])
    assert sim.calls == []


def test_a_negative_tier_interval_is_a_422():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"fast": -1.0})

    assert response.status_code == 422
    assert sim.calls == []


def test_families_forwards_only_the_flags_that_were_sent():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/families", json={"energy": False})

    assert response.status_code == 200
    assert sim.calls == [("apply_families", {"energy": False})]


def test_an_unknown_family_is_a_422():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/families", json={"nonsense": True})

    assert response.status_code == 422
    assert sim.calls == []


def test_one_device_can_be_disabled_over_http():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/devices/main-meter", json={"enabled": False})

    assert response.status_code == 200
    assert sim.calls == [("set_device_enabled", "main-meter", False)]


def test_disabling_an_unknown_device_is_a_404():
    sim = FakeSimulator()
    sim.unknown_device = True

    response = _client(sim).put("/simulator/devices/nope", json={"enabled": False})

    assert response.status_code == 404


def test_a_write_with_no_body_is_a_422_rather_than_a_crash():
    assert _client().put("/simulator/devices/main-meter", json={}).status_code == 422


@pytest.mark.asyncio
async def test_concurrent_writes_are_serialised():
    """Two profile switches arriving together must not rebuild the device list from two
    directions at once. The lock is the only thing preventing it."""
    sim = FakeSimulator(slow=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(sim)), base_url="http://sim"
    ) as client:
        responses = await asyncio.gather(
            client.put("/simulator/profile", json={"profile": "small"}),
            client.put("/simulator/profile", json={"profile": "full"}),
        )

    assert [r.status_code for r in responses] == [200, 200]
    assert len(sim.calls) == 2
    assert sim.overlaps == 0
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_api.py -k "run or profile or tiers or families or device or concurrent" -v`
Expected: FAIL — `405 Method Not Allowed` on every write, because only the GETs exist.

- [ ] **Step 3: Add the request models**

Extend `api.py`'s imports:

```python
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
```

and add above `create_app`:

```python
class _StrictModel(BaseModel):
    """Rejects keys it does not recognise.

    A silently-dropped `sedd: 42` is a control that appears to work and changes nothing,
    which is worse than an error.
    """

    model_config = ConfigDict(extra="forbid")


class RunRequest(_StrictModel):
    action: Literal["start", "stop", "pause", "resume"]


class ProfileRequest(_StrictModel):
    profile: str
    seed: int | None = None


class TiersRequest(_StrictModel):
    """Seconds between publishes, per cadence tier. Absent fields are left unchanged.

    Named fields rather than a free `dict[str, float]`, so an unknown tier and a negative
    interval are both pydantic 422s that name the offending key with no validation code
    of our own. All seven of plan A's tiers, including `event`.
    """

    fast: float | None = Field(default=None, ge=0.0)
    process: float | None = Field(default=None, ge=0.0)
    energy: float | None = Field(default=None, ge=0.0)
    status: float | None = Field(default=None, ge=0.0)
    meter: float | None = Field(default=None, ge=0.0)
    lab: float | None = Field(default=None, ge=0.0)
    event: float | None = Field(default=None, ge=0.0)


class FamiliesRequest(_StrictModel):
    """One field per sensor family in plan A's FAMILIES. Absent means unchanged."""

    energy: bool | None = None
    water: bool | None = None
    utilities: bool | None = None
    asset_health: bool | None = None
    production: bool | None = None
    safety: bool | None = None


class DeviceRequest(_StrictModel):
    enabled: bool
```

- [ ] **Step 4: Add the five write routes**

Add inside `create_app`, after `get_diagnostics` and before `app.include_router(router)`:

```python
    @router.post("/run")
    async def post_run(request: RunRequest) -> dict[str, Any]:
        """Start, stop, pause or resume. Idempotent: a double-clicked button is not an error."""
        async with simulator.lock:
            if request.action == "start":
                await simulator.start()
            elif request.action == "stop":
                await simulator.stop()
            elif request.action == "pause":
                await simulator.pause()
            else:
                await simulator.resume()
        return simulator.status()

    @router.put("/profile")
    async def put_profile(request: ProfileRequest) -> dict[str, Any]:
        """Switch profile, optionally reseeding. Runtime only — nothing is written to YAML."""
        async with simulator.lock:
            try:
                await simulator.apply_profile(request.profile, seed=request.seed)
            except ReconfigurationError as exc:
                raise _rejected(exc) from exc
        body = simulator.status()
        # The devices that were counting are gone, so published_total and failed_total are
        # back to zero. Saying so stops a console computing a rate from a total that just
        # went backwards.
        body["counters_reset"] = True
        return body

    @router.put("/tiers")
    async def put_tiers(request: TiersRequest) -> dict[str, Any]:
        """Override publish intervals. `exclude_none` is what makes the body a patch."""
        async with simulator.lock:
            try:
                await simulator.apply_tiers(request.model_dump(exclude_none=True))
            except ReconfigurationError as exc:
                raise _rejected(exc) from exc
        return simulator.status()

    @router.put("/families")
    async def put_families(request: FamiliesRequest) -> dict[str, Any]:
        """Enable or disable the devices a sensor family contributed."""
        async with simulator.lock:
            try:
                await simulator.apply_families(request.model_dump(exclude_none=True))
            except ReconfigurationError as exc:
                raise _rejected(exc) from exc
        return simulator.status()

    @router.put("/devices/{device_id}")
    async def put_device(device_id: str, request: DeviceRequest) -> dict[str, Any]:
        """Silence or unsilence one device."""
        async with simulator.lock:
            try:
                await simulator.set_device_enabled(device_id, request.enabled)
            except KeyError:
                raise _unknown_device(device_id) from None
        return simulator.status()
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd 99_simulator && uv run pytest test/test_api.py -v`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `cd 99_simulator && uv run pytest -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/api.py 99_simulator/test/test_api.py
git commit -m "feat(simulator): add the five control API writes, serialised behind one lock"
```

---

## Task 8: MQTT self-telemetry, and the guard that keeps it out of the Unified Namespace

Spec §6's three topics, under `uns/platform/simulator/<instance>/`. This is **Platform
Observability**: it says whether the simulator is working, never what the simulated plant
measures. `CONTEXT.md` is explicit that the two never share a data source, and a simulator
publishing its own health into `CovestroAG/...` would be persisted by the historian and the
graph database as though a machine had reported it.

That separation currently holds because of how the mapper topic lists happen to be written.
This task makes it hold because a test says so.

**Files:**
- Create: `99_simulator/src/uns_simulator/self_telemetry.py`
- Test: `99_simulator/test/test_self_telemetry.py` (create)

**Interfaces:**
- Consumes: `MQTTConfig` (`config.py`); `UnifiedNamespaceSimulator.status()`, `.plant_snapshot()`, `.signal_devices`, `.on_plant_transition(callback)` (Tasks 3, 5); `SignalDevice.connected`/`.publish_fail`/`.last_error`/`.spec.id`; `resolve_conf_dir` from `uns_config`.
- Produces: `telemetry_prefix(instance) -> str`; `class SelfTelemetry` with `__init__(simulator, instance, interval_s=10.0)`, `.queue`, `.published`, `.dropped`, `status_payload()`, `device_health_changes()`, `on_transition(site, line, state)`, `async run()`, `async stop()`. Task 9 constructs it and registers `on_transition`.

- [ ] **Step 1: Write the failing tests**

```python
# 99_simulator/test/test_self_telemetry.py
"""The simulator's own health on MQTT (spec 6), and the guard that keeps it separate.

Platform Observability, never Process Visualization: these topics answer "is the simulator
publishing?", and must be invisible to every mapper that persists the Unified Namespace.
"""

import asyncio
import json

import pytest
import yaml
from uns_config import resolve_conf_dir

from uns_simulator import self_telemetry as telemetry_module
from uns_simulator.self_telemetry import SelfTelemetry, telemetry_prefix

STATUS = {
    "run_state": "running",
    "profile": "small",
    "seed": 1,
    "device_count": 2,
    "signal_count": 5,
    "uptime_s": 3.0,
    "broker_connected": True,
    "msg_per_sec": {"process": 1.0},
    "published_total": 10,
    "failed_total": 0,
    "overrides_active": False,
    "tiers": {"process": 30.0},
    "families": {"energy": True},
    "per_tier": {"process": 5},
    "tick_count": 3,
}

PLANT = {
    "sites": {
        "Dormagen": {
            "shift": "A",
            "lines": {
                "Production/Line1": {
                    "state": "Execute",
                    "previous": "Starting",
                    "production_rate": 0.92,
                    "time_in_state_s": 184.0,
                }
            },
        }
    }
}


class FakeDevice:
    def __init__(self, device_id):
        self.spec = type("Spec", (), {"id": device_id})()
        self.connected = True
        self.publish_fail = 0
        self.last_error = None


class FakeSimulator:
    def __init__(self):
        self.signal_devices = [FakeDevice("main-meter")]

    def status(self):
        return dict(STATUS)

    def plant_snapshot(self):
        return PLANT


class DummyClient:
    """Records publishes, and the Will it was constructed with."""

    instances: list["DummyClient"] = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.published: list[tuple[str, dict, bool]] = []
        DummyClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def publish(self, topic, payload, **kwargs):
        self.published.append((topic, json.loads(payload), bool(kwargs.get("retain"))))


@pytest.fixture(autouse=True)
def _dummy_broker(monkeypatch):
    DummyClient.instances = []
    monkeypatch.setattr(telemetry_module.aiomqtt, "Client", DummyClient)


def _telemetry(interval_s=0.01) -> SelfTelemetry:
    return SelfTelemetry(FakeSimulator(), "Instance01", interval_s=interval_s)


def test_the_prefix_is_platform_observability_not_the_plant():
    assert telemetry_prefix("Instance01") == "uns/platform/simulator/Instance01"


def test_the_status_payload_is_a_summary_and_not_the_whole_status_body():
    """An MQTT heartbeat every ten seconds is not the place for the full device inventory."""
    payload = _telemetry().status_payload()

    assert payload["run_state"] == "running"
    assert payload["published_total"] == 10
    assert "per_tier" not in payload
    assert "tiers" not in payload


def test_a_transition_is_enqueued_and_never_published_inline():
    """PlantClock calls its listeners synchronously on the tick and swallows what they
    raise. An awaited publish here would put broker latency inside the plant's clock."""
    telemetry = _telemetry()
    telemetry.on_transition("Dormagen", "Production/Line1", "Execute")

    topic, payload = telemetry.queue.get_nowait()
    assert topic == "uns/platform/simulator/Instance01/plant/Dormagen/Production/Line1/state"
    assert payload["state"] == "Execute"
    assert payload["previous"] == "Starting"
    assert payload["time_in_state_s"] == 184.0
    assert DummyClient.instances == []


def test_a_full_queue_drops_and_counts_rather_than_blocking_the_clock():
    telemetry = _telemetry()
    telemetry.queue = asyncio.Queue(maxsize=1)

    telemetry.on_transition("Dormagen", "Production/Line1", "Execute")
    telemetry.on_transition("Dormagen", "Production/Line1", "Holding")

    assert telemetry.queue.qsize() == 1
    assert telemetry.dropped == 1


def test_device_health_is_reported_on_change_only():
    """A hundred healthy devices republishing every ten seconds is more traffic than the
    plant they simulate."""
    telemetry = _telemetry()

    first = telemetry.device_health_changes()
    assert len(first) == 1
    assert first[0][0] == "uns/platform/simulator/Instance01/device/main-meter/health"
    assert telemetry.device_health_changes() == []

    telemetry.simulator.signal_devices[0].connected = False
    changed = telemetry.device_health_changes()
    assert len(changed) == 1
    assert changed[0][1]["connected"] is False


@pytest.mark.asyncio
async def test_the_client_is_built_with_a_retained_last_will_on_the_status_topic():
    """The only failure a heartbeat cannot report: `docker kill`. The Last Will is what
    makes the console say offline instead of showing a status that stopped updating."""
    telemetry = _telemetry()
    task = asyncio.create_task(telemetry.run())
    await asyncio.sleep(0.05)
    await telemetry.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    will = DummyClient.instances[0].kwargs["will"]
    assert will.topic == "uns/platform/simulator/Instance01/status"
    assert will.retain is True
    assert json.loads(will.payload)["run_state"] == "offline"


@pytest.mark.asyncio
async def test_run_publishes_status_retained_and_drains_queued_transitions():
    telemetry = _telemetry()
    telemetry.on_transition("Dormagen", "Production/Line1", "Execute")

    task = asyncio.create_task(telemetry.run())
    await asyncio.sleep(0.08)
    await telemetry.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    published = DummyClient.instances[0].published
    topics = [topic for topic, _, _ in published]
    assert "uns/platform/simulator/Instance01/status" in topics
    assert "uns/platform/simulator/Instance01/plant/Dormagen/Production/Line1/state" in topics
    assert "uns/platform/simulator/Instance01/device/main-meter/health" in topics
    assert all(retain for _, _, retain in published)


def _matches(pattern: str, topic: str) -> bool:
    """MQTT wildcard matching, enough of it for the patterns the platform uses."""
    if pattern == "#":
        return True
    if pattern.endswith("/#"):
        stem = pattern[:-2]
        return topic == stem or topic.startswith(f"{stem}/")
    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    if len(pattern_parts) != len(topic_parts):
        return False
    return all(expected in ("+", actual) for expected, actual in zip(pattern_parts, topic_parts, strict=True))


def test_the_wildcard_matcher_itself_is_right():
    """A broken matcher would make the guard below pass for the wrong reason."""
    assert _matches("#", "anything/at/all")
    assert _matches("CovestroAG/#", "CovestroAG/Dormagen/x")
    assert _matches("CovestroAG/#", "CovestroAG")
    assert not _matches("CovestroAG/#", "CovestroAGX/Dormagen")
    assert _matches("spBv1.0/+/NBIRTH/x", "spBv1.0/group/NBIRTH/x")
    assert not _matches("a/b", "a/b/c")


def test_no_mapper_subscribes_to_the_simulator_s_own_telemetry():
    """The separation CONTEXT.md requires, enforced rather than assumed.

    Widening one of these topic lists to `#` is a one-character change, and without this
    test its consequence — the simulator's own heartbeat persisted as plant history — would
    only show up as puzzling rows in the historian months later.
    """
    conf = yaml.safe_load((resolve_conf_dir() / "settings.yaml").read_text(encoding="utf-8"))
    prefix = telemetry_prefix("Instance01")
    telemetry_topics = [
        f"{prefix}/status",
        f"{prefix}/plant/Dormagen/Production/Line1/state",
        f"{prefix}/device/main-meter/health",
    ]

    for environment in ("graphdb", "historian", "kafka_mapper", "sparkplugb"):
        for pattern in conf[environment]["mqtt"]["topics"]:
            for topic in telemetry_topics:
                assert not _matches(pattern, topic), f"{environment} subscribes to {topic} via {pattern!r}"
```

Spec §9 asks for this guard against the graph database and the historian. It covers the
Kafka mapper and the Sparkplug mapper too, because they subscribe as well and a topic list
nobody checks is exactly where a `#` ends up.

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_self_telemetry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_simulator.self_telemetry'`.

- [ ] **Step 3: Write `self_telemetry.py`**

```python
# 99_simulator/src/uns_simulator/self_telemetry.py
"""The simulator's own health, published into MQTT (spec 6).

Platform Observability, not Process Visualization. These topics live under
`uns/platform/simulator/<instance>/`, which no mapper subscribes to, so the simulator's
heartbeat is never persisted as though a machine had measured it. test_self_telemetry.py
enforces that against the real topic lists in conf/settings.yaml.

Its own aiomqtt client rather than borrowing a device's, for one reason that decides it: a
Last Will has to be set when the connection is made, and no plant device has one. The Last
Will is what makes `.../status` report `offline` after a `docker kill` — the one failure a
heartbeat cannot report about itself.
"""

import asyncio
import json
import logging
import time
from typing import Any
from uuid import uuid4

import aiomqtt

from uns_simulator.config import MQTTConfig

LOGGER = logging.getLogger(__name__)

# Bounded, because the producer is the plant clock. An unbounded queue would turn a broker
# outage into a memory leak that outlives the outage.
QUEUE_LIMIT = 1000
RECONNECT_DELAY_S = 5.0


def telemetry_prefix(instance: str) -> str:
    """The Platform Observability prefix for one Instance of the platform."""
    return f"uns/platform/simulator/{instance}"


class SelfTelemetry:
    """Publishes simulator status, plant transitions and device health.

    Three cadences, each chosen for what it is reporting:
      status         - every `interval_s`, because "still alive" is a heartbeat
      plant state    - on a PackML transition, because that is the event
      device health  - on change, because a hundred healthy devices repeating themselves
                       every ten seconds is more traffic than the plant they simulate
    """

    def __init__(self, simulator, instance: str, interval_s: float = 10.0) -> None:
        self.simulator = simulator
        self.prefix = telemetry_prefix(instance)
        self.interval_s = interval_s
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.client: aiomqtt.Client | None = None
        self.published = 0
        self.dropped = 0
        self._running = False
        self._device_health: dict[str, dict[str, Any]] = {}

    def _build_client(self) -> aiomqtt.Client:
        """A client whose Last Will is a retained `offline` status.

        Every connection parameter comes from MQTTConfig, exactly as AsyncMQTTDevice builds
        its own: telemetry that cannot reach a TLS broker would be worse than none, because
        its silence would look like the simulator being down.
        """
        will = aiomqtt.Will(
            topic=f"{self.prefix}/status",
            payload=json.dumps({"run_state": "offline", "reason": "mqtt last will"}),
            qos=1,
            retain=True,
        )
        return aiomqtt.Client(
            identifier=f"uns_simulator-telemetry-{uuid4().hex[:8]}",
            clean_session=MQTTConfig.clean_session,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            hostname=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            keepalive=MQTTConfig.keep_alive,
            tls_params=MQTTConfig.tls_params,
            tls_insecure=MQTTConfig.tls_insecure,
            will=will,
        )

    def status_payload(self) -> dict[str, Any]:
        """A summary, not the whole status body.

        The full document has the tier map and the per-tier signal counts in it, which are
        configuration rather than health, and a retained heartbeat is not where they belong.
        """
        body = self.simulator.status()
        return {
            "run_state": body["run_state"],
            "profile": body["profile"],
            "device_count": body["device_count"],
            "signal_count": body["signal_count"],
            "published_total": body["published_total"],
            "failed_total": body["failed_total"],
            "msg_per_sec": body["msg_per_sec"],
            "uptime_s": body["uptime_s"],
            "overrides_active": body["overrides_active"],
        }

    def device_health_changes(self) -> list[tuple[str, dict[str, Any]]]:
        """The devices whose health changed since this was last called."""
        changes: list[tuple[str, dict[str, Any]]] = []
        for device in self.simulator.signal_devices:
            current = {
                "connected": device.connected,
                "publish_fail": device.publish_fail,
                "last_error": device.last_error,
            }
            if self._device_health.get(device.spec.id) == current:
                continue
            self._device_health[device.spec.id] = current
            changes.append((f"{self.prefix}/device/{device.spec.id}/health", current))
        return changes

    def on_transition(self, site: str, line: str, state: str) -> None:
        """Registered with `simulator.on_plant_transition`. Enqueues; never publishes.

        Synchronous and non-blocking by contract: PlantClock calls this on the tick and
        swallows anything it raises, so an awaited publish here would put broker latency
        inside the plant's clock and an exception would vanish without a trace.
        """
        line_state = self.simulator.plant_snapshot()["sites"].get(site, {}).get("lines", {}).get(line, {})
        payload = {
            "state": state,
            "previous": line_state.get("previous"),
            "production_rate": line_state.get("production_rate"),
            "time_in_state_s": line_state.get("time_in_state_s"),
        }
        try:
            self.queue.put_nowait((f"{self.prefix}/plant/{site}/{line}/state", payload))
        except asyncio.QueueFull:
            # Counted rather than logged per event: a full queue means a broker outage, and
            # a log line per dropped transition would be its own denial of service.
            self.dropped += 1

    async def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self.client is None:
            return
        # Retained, so a console that connects later immediately learns the current state
        # instead of waiting a whole interval. The Last Will overwrites the retained status
        # when the process dies, which is the entire mechanism.
        await self.client.publish(topic, json.dumps(payload, default=str), qos=1, retain=True)
        self.published += 1

    async def _drain(self, window_s: float) -> None:
        """Publish queued transitions for up to `window_s` seconds, then return.

        A window rather than a plain sleep, so a burst of PackML transitions reaches the
        broker when it happens instead of on the next status beat.
        """
        deadline = time.monotonic() + window_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return
            try:
                topic, payload = await asyncio.wait_for(self.queue.get(), timeout=remaining)
            except TimeoutError:
                return
            await self._publish(topic, payload)

    async def run(self) -> None:
        """Connect, then publish until stopped. Reconnects on its own."""
        self._running = True
        while self._running:
            try:
                async with self._build_client() as client:
                    self.client = client
                    LOGGER.info("Simulator self-telemetry publishing under %s", self.prefix)
                    while self._running:
                        await self._publish(f"{self.prefix}/status", self.status_payload())
                        for topic, payload in self.device_health_changes():
                            await self._publish(topic, payload)
                        await self._drain(self.interval_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Simulator self-telemetry lost its connection; retrying")
                await asyncio.sleep(RECONNECT_DELAY_S)
            finally:
                self.client = None

    async def stop(self) -> None:
        """End the loop after the current window. Publishing a final `offline` status is
        deliberately not done here: the Last Will covers the crash case, and a clean stop
        is already visible in GET /simulator/status."""
        self._running = False
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd 99_simulator && uv run pytest test/test_self_telemetry.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/self_telemetry.py 99_simulator/test/test_self_telemetry.py
git commit -m "feat(simulator): publish self-telemetry under uns/platform/simulator with a last will"
```

---

## Task 9: Wire it up — `main.py`, the image, and the deployment

The three surfaces exist and nothing starts them. This task also publishes port 8099,
exposes both ports on the image, and adds the fourth Prometheus scrape job without which
`/metrics` is served and never read.

The API runs as a task in the simulation's own event loop rather than in a thread or a
second process. That is the whole reason a handler can read `simulator.status()` and get
the truth: there is one copy of the state and one loop touching it.

**Files:**
- Modify: `99_simulator/src/uns_simulator/main.py`
- Modify: `99_simulator/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `08_uns_observability/prometheus/prometheus.yml`
- Test: `99_simulator/test/test_main.py`

**Interfaces:**
- Consumes: `create_app` (Tasks 6-7), `start_metrics_server` (Task 2), `SelfTelemetry` (Task 8), `SimulatorAPIConfig` (Task 1), `UnifiedNamespaceSimulator.run_simulation`/`.on_plant_transition` (Task 3), `settings`.
- Produces: `class _EmbeddedServer(uvicorn.Server)`, and a `run()` that owns the API task, the telemetry task and the metrics thread. Nothing consumes these; this is the top of the process.

- [ ] **Step 1: Write the failing test**

Add to `99_simulator/test/test_main.py`. The two existing tests, which monkeypatch
`uns_simulator.main.sys` and `uns_simulator.main.asyncio`, must keep passing untouched:

```python
@pytest.mark.asyncio
async def test_run_serves_the_api_the_metrics_and_the_telemetry_beside_the_simulation(monkeypatch):
    """The failure this guards: the app is built and never served. The simulator's own
    logs look perfect and the console shows nothing but 'offline'."""
    events: list[str] = []

    class FakeSimulator:
        def __init__(self):
            self.signal_devices = []
            self.listeners = []

        def on_plant_transition(self, callback):
            self.listeners.append(callback)

        async def run_simulation(self, duration):
            events.append(f"simulation:{duration}")

    class FakeTelemetry:
        def __init__(self, simulator, instance, interval_s=10.0):
            self.simulator = simulator
            self.instance = instance

        def on_transition(self, site, line, state):
            events.append(f"transition:{state}")

        async def run(self):
            events.append("telemetry")

        async def stop(self):
            events.append("telemetry:stopped")

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False

        async def serve(self):
            events.append(f"api:{self.config.port}")

    simulators: list[FakeSimulator] = []

    def _build_simulator():
        simulator = FakeSimulator()
        simulators.append(simulator)
        return simulator

    monkeypatch.setattr(main, "UnifiedNamespaceSimulator", _build_simulator)
    monkeypatch.setattr(main, "SelfTelemetry", FakeTelemetry)
    monkeypatch.setattr(main, "_EmbeddedServer", FakeServer)
    monkeypatch.setattr(main, "start_metrics_server", lambda simulator, port: events.append(f"metrics:{port}"))

    await main.run()

    assert "metrics:9093" in events
    assert "api:8099" in events
    assert "telemetry" in events
    assert "telemetry:stopped" in events
    assert any(event.startswith("simulation:") for event in events)
    # The telemetry has to be listening before the plant starts moving, or the first
    # transitions of a run are the ones nobody sees.
    assert len(simulators[0].listeners) == 1


def test_the_embedded_server_does_not_steal_the_interrupt():
    """uvicorn installs its own SIGINT handler on serve(). That would take Ctrl-C away
    from run_simulation's KeyboardInterrupt path and leave every device connected."""
    server = main._EmbeddedServer(uvicorn.Config(app=lambda scope, receive, send: None))

    with server.capture_signals():
        pass
```

Add `import uvicorn` and `import pytest` to `test_main.py` if they are not already there.

- [ ] **Step 2: Run and confirm failure**

Run: `cd 99_simulator && uv run pytest test/test_main.py -v`
Expected: FAIL — `AttributeError: <module 'uns_simulator.main'> does not have the attribute 'start_metrics_server'`.

- [ ] **Step 3: Rewrite `main.py`**

```python
# 99_simulator/src/uns_simulator/main.py
"""Entry point: the simulation, and the three surfaces that observe and command it.

The control API and the self-telemetry run as tasks in the simulation's own event loop
rather than in a thread or a second process. That is what lets an HTTP handler read
`simulator.status()` and get the truth — one copy of the state, one loop touching it.
"""

import asyncio
import contextlib
import logging
import sys

import uvicorn

from uns_simulator.api import create_app
from uns_simulator.config import SimulatorAPIConfig, settings
from uns_simulator.metrics import start_metrics_server
from uns_simulator.self_telemetry import SelfTelemetry
from uns_simulator.simulator import UnifiedNamespaceSimulator

LOGGER = logging.getLogger(__name__)


class _EmbeddedServer(uvicorn.Server):
    """A uvicorn server that leaves the process's signal handlers alone.

    uvicorn installs its own SIGINT handler in `serve()`. Here that would take Ctrl-C away
    from `run_simulation`'s KeyboardInterrupt path, so the plant would never shut down
    cleanly and every device would stay connected to the broker. This process is the
    simulation; the HTTP server is a guest in its event loop.
    """

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def configure_asyncio_for_mqtt() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run() -> None:
    simulator = UnifiedNamespaceSimulator()

    # A background thread of its own, from prometheus_client. Started before anything
    # publishes so a scrape during startup returns zeros rather than a refused connection.
    start_metrics_server(simulator, SimulatorAPIConfig.metrics_port)

    telemetry = SelfTelemetry(simulator, settings.get("platform.instance_name", "Instance01"))
    # Registered before the plant starts moving: the first transitions of a run are exactly
    # the ones worth seeing.
    simulator.on_plant_transition(telemetry.on_transition)

    server = _EmbeddedServer(
        uvicorn.Config(
            create_app(simulator, token=SimulatorAPIConfig.token),
            host=SimulatorAPIConfig.api_host,
            port=SimulatorAPIConfig.api_port,
            # The console polls twice a second. An access log line per poll would bury
            # every message that matters.
            access_log=False,
            log_level="warning",
        )
    )
    api_task = asyncio.create_task(server.serve())
    telemetry_task = asyncio.create_task(telemetry.run())
    LOGGER.info(
        "Simulator control API on http://%s:%d/simulator (docs at /simulator/docs)",
        SimulatorAPIConfig.api_host,
        SimulatorAPIConfig.api_port,
    )

    try:
        await simulator.run_simulation(settings.get("simulation.duration", 60))
    finally:
        await telemetry.stop()
        server.should_exit = True
        await asyncio.gather(api_task, telemetry_task, return_exceptions=True)


def main() -> None:
    configure_asyncio_for_mqtt()
    asyncio.run(run())


def run_simulator() -> None:
    main()
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd 99_simulator && uv run pytest test/test_main.py -v`
Expected: PASS, including the two pre-existing tests.

- [ ] **Step 5: Expose both ports on the image**

In `99_simulator/Dockerfile`, immediately before `VOLUME /app/conf` (line 80), add:

```dockerfile
# 8099 is the control API, 9093 the Prometheus endpoint.
EXPOSE 8099 9093
```

Leave `ENTRYPOINT ["uv", "run", "uns_simulator"]` exactly as it is — CI checks that shape.

- [ ] **Step 6: Add the control API port to Docker Compose, commented out**

In `docker-compose.yml`, add to `uns_simulator` (currently at line 240), between
`dockerfile:` and `volumes:`:

```yaml
    # Uncomment to reach the control API from the host — needed for `npm run dev` against a
    # composed stack, and for the curl checks in the plan's Manual Verification.
    #
    # Commented out by default because the API has no user identity: anyone who can reach
    # 8099 can stop the simulator, switch its profile, or disable a device (spec 10). Inside
    # the compose network `uns_frontend`'s nginx reaches it by service name and no host port
    # is needed, so publishing it by default would widen the reachable surface for nothing.
    #
    # 9093 stays unpublished either way: Prometheus scrapes it from inside the network,
    # exactly as it does the historian's 9091 and the graph database's 9092.
    # ports:
    #   - "8099:8099"
```

Then let the frontend container reach it. nginx resolves a literal upstream hostname when
it starts and refuses to start if it cannot, so `uns_frontend` needs the dependency —
change its `depends_on` from:

```yaml
    depends_on:
      - graphql_server
```

to:

```yaml
    depends_on:
      - graphql_server
      # nginx.conf proxies /simulator to it, and nginx will not start on an unresolvable
      # upstream hostname.
      - uns_simulator
```

And have Prometheus wait for it too — add `- uns_simulator` to `uns_prometheus`'s
`depends_on` list, after `- graphdb_client`.

Spec 8 says the frontend gains no `depends_on`. Add it anyway: that line was written
assuming nginx tolerates a missing upstream, and it does not. A literal hostname in
`proxy_pass` is resolved once at startup, and an unresolvable one is a fatal config error —
without the dependency, adding the `/simulator` proxy in Task 10 turns a stack started
without the simulator into a stack with no frontend at all.

- [ ] **Step 7: Add the fourth scrape job**

Append to `08_uns_observability/prometheus/prometheus.yml`:

```yaml
  - job_name: uns_simulator
    static_configs:
      - targets: ["uns_simulator:9093"]
```

Without this the endpoint is served and never read, which is indistinguishable from a
simulator that publishes nothing.

- [ ] **Step 8: Verify the stack end to end**

Uncomment the `ports:` block you just added — the two `curl` calls reach 8099 from the
host, which is exactly what the default configuration does not allow. Comment it back out
before Step 9 so the committed file keeps the mapping off.

```bash
docker compose up -d --build uns_mqtt_broker uns_simulator uns_prometheus
sleep 20
curl -s http://localhost:8099/simulator/health
curl -s http://localhost:8099/simulator/status
docker compose exec uns_prometheus wget -qO- http://uns_simulator:9093/metrics | head -20
```

Expected: `health` returns `{"status":"ok",...}`; `status` returns `run_state: "running"`;
the metrics output contains `uns_simulator_messages_published_total`. Then
`http://localhost:9090/targets` shows `uns_simulator` as `UP`. Tear down with
`docker compose down`.

- [ ] **Step 9: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
cd ..
git add 99_simulator/src/uns_simulator/main.py 99_simulator/test/test_main.py 99_simulator/Dockerfile docker-compose.yml 08_uns_observability/prometheus/prometheus.yml
git commit -m "feat(simulator): serve the control API, metrics and telemetry from the simulation loop"
```

---

## Task 10: Let the browser reach port 8099

Both ways it can be served. `npm run dev` proxies through Vite; the container proxies
through nginx. Neither knows about 8099 yet, so every request the next four tasks make
would 404 against `index.html` — which is worse than a network error, because `fetch`
succeeds and `response.json()` fails on `<!doctype html>`.

The port comes from `conf/settings.yaml`, like the GraphQL port already does. Hard-coding
8099 in `vite.config.ts` would mean the simulator's port lives in two places, and a plan
that adds `applications.simulator.api_port` in Task 1 and then ignores it has just written
its own bug.

**Files:**
- Modify: `conf/settings.yaml` (the `default.urls` block, after line 39)
- Modify: `11_frontend/platform/settings.ts`
- Modify: `11_frontend/src/lib/platform/config.ts`
- Modify: `11_frontend/vite.config.ts`
- Modify: `11_frontend/nginx.conf`

**Interfaces:**
- Consumes: `applications.simulator.api_port` (Task 1); the existing `PlatformSettings` type and `loadPlatformSettings()`.
- Produces: `PlatformSettings.simulatorApiPort: number`, `PlatformSettings.simulatorProxyTarget: string`, and a working `/simulator` path in both dev and container. Task 11's client relies on the relative path resolving.

- [ ] **Step 1: Add the simulator host beside the GraphQL host**

In `conf/settings.yaml`, inside `default.urls`, after `graphql_path: "/graphql"` (line 39):

```yaml
    # Where the Vite dev server proxies /simulator. The port itself is
    # applications.simulator.api_port, so it is configured exactly once.
    simulator_host: "localhost"
```

- [ ] **Step 2: Read the two new values in `platform/settings.ts`**

Add to the `PlatformSettings` type, after `frontendComposePort: number`:

```typescript
  simulatorApiPort: number
  simulatorProxyTarget: string
```

In `platformSettingsFromConfig`, after the `frontend` const, add:

```typescript
  const simulator = applications.simulator ?? {}
  const simulatorHost = String(urls.simulator_host ?? 'localhost')
  const simulatorApiPort = Number(simulator.api_port ?? 8099)
```

and add to the returned object, after `frontendComposePort`:

```typescript
    simulatorApiPort,
    simulatorProxyTarget: `http://${simulatorHost}:${simulatorApiPort}`,
```

- [ ] **Step 3: Mirror the type in `src/lib/platform/config.ts`**

That file re-declares `PlatformSettings` because it is compiled for the browser and cannot
import from `platform/`, which uses `node:fs`. Add the same two fields after
`frontendComposePort: number`:

```typescript
  simulatorApiPort: number
  simulatorProxyTarget: string
```

The two declarations must stay in step. They describe the same object — the one Vite
inlines as `__UNS_PLATFORM_CONFIG__` — and a field present in one and missing from the
other is a runtime `undefined` that the compiler will not catch.

- [ ] **Step 4: Proxy `/simulator` in dev**

In `11_frontend/vite.config.ts`, add a second entry to `server.proxy`, after the
`'/graphql'` block:

```typescript
        // The simulator's control API. No `ws: true`: the console polls it over HTTP and
        // gets its live feed from MQTT through /graphql.
        '/simulator': {
          target: platform.simulatorProxyTarget,
          changeOrigin: true,
        },
```

- [ ] **Step 5: Proxy `/simulator` in the container**

In `11_frontend/nginx.conf`, add a location block between the `/graphql` block and
`location /`. Order matters in nginx only for regex locations, but keeping the two proxies
together and the SPA fallback last is what makes the file readable:

```nginx
    # The simulator's control API. Must come before `location /`, whose try_files would
    # otherwise answer every /simulator request with index.html — a 200 full of HTML, which
    # is harder to diagnose than a refused connection.
    location /simulator {
        proxy_pass http://uns_simulator:8099;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
```

`proxy_pass` has no trailing path, so nginx forwards the URI unchanged and
`/simulator/status` arrives as `/simulator/status` — which is where FastAPI's router,
mounted under `prefix="/simulator"`, expects it.

- [ ] **Step 6: Verify**

```bash
cd 11_frontend && npm run lint && npm run build
```

Expected: both pass. Then, with the simulator running from Task 9. The dev proxy targets
`localhost:8099`, so uncomment `uns_simulator`'s `ports:` block first if the simulator is
running in compose — that mapping is off by default (Task 9, Step 6). Running the simulator
directly with `uv run uns_simulator` needs nothing uncommented, because then 8099 is already
a host port.

```bash
cd 11_frontend && npm run dev
# in another shell:
curl -s http://localhost:5173/simulator/status | head -5
```

Expected: the status JSON, not HTML.

- [ ] **Step 7: Commit**

```bash
git add conf/settings.yaml 11_frontend/platform/settings.ts 11_frontend/src/lib/platform/config.ts 11_frontend/vite.config.ts 11_frontend/nginx.conf
git commit -m "feat(frontend): proxy /simulator to the control API in dev and in the container"
```

---

## Task 11: The typed client

Spec §7.3. One file that knows the shape of every response and the two shapes of every
error, so no component ever touches `fetch`.

**Nothing here throws.** Every method returns a `SimulatorResult<T>`. That is a deliberate
choice about what the simulator being down means: it is a normal state of this console, not
an exception. The simulator is optional — it is not in the platform's critical path, and a
production install may not run one at all. A client that threw would put a `try`/`catch`
in every caller and one forgotten `catch` would blank the console.

**Files:**
- Create: `11_frontend/src/types/simulator.ts`
- Create: `11_frontend/src/services/simulator/client.ts`
- Modify: `11_frontend/src/vite-env.d.ts`

**Interfaces:**
- Consumes: the response bodies in **Canonical Response Bodies** above, which Tasks 5-7 produce.
- Produces: the types listed below, and `simulatorClient` (a module singleton, matching `unsGraphQLClient`) with `getHealth(), getStatus(), getConfig(), getPlant(), getDevices(), getSignals(deviceId), getDiagnostics(), run(action), setProfile(profile, seed?), setTiers(intervals), setFamilies(flags), setDeviceEnabled(deviceId, enabled)` — every one returning `Promise<SimulatorResult<T>>`. Task 13's hook is the only consumer.

- [ ] **Step 1: Write the types**

```typescript
// 11_frontend/src/types/simulator.ts
/**
 * The shapes 99_simulator's control API returns. Mirrors the response bodies in
 * docs/superpowers/specs/2026-08-31-simulator-console-and-control-api-design.md section 5.
 *
 * Field names are the API's, snake_case included. Renaming them to camelCase here would
 * add a mapping layer whose only job is to hide where the data came from, and every
 * mismatch would surface as `undefined` in the UI instead of a compile error.
 */

export type RunState = 'stopped' | 'starting' | 'running' | 'paused'

export type RunAction = 'start' | 'pause' | 'resume' | 'stop'

export interface SimulatorHealth {
  status: string
  uptime_s: number
  git_hash: string
  version: string
}

export interface SimulatorStatus {
  run_state: RunState
  profile: string
  seed: number
  device_count: number
  signal_count: number
  uptime_s: number
  broker_connected: boolean
  msg_per_sec: Record<string, number>
  published_total: number
  failed_total: number
  /** True when the running plant no longer matches the profile files on disk. */
  overrides_active: boolean
  tiers: Record<string, number>
  families: Record<string, boolean>
  per_tier: Record<string, number>
  tick_count: number
  /** Only present on the body returned by PUT /simulator/profile. */
  counters_reset?: boolean
}

/**
 * One resolved ISA-95 location. Flat, not a tree: the API returns the rows the profile
 * expanded to, and the console groups them for display. A nested shape would have to be
 * built somewhere, and building it in Python would mean testing it twice.
 */
export interface SimulatorHierarchyRow {
  enterprise: string
  site: string
  area: string
  line: string
  cell: string
  kind: string
  nameplate_tph: number
}

export interface SimulatorDeviceTarget {
  site: string
  area: string
  line: string
  cell: string
  kind: string
}

export interface SimulatorDeviceConfig {
  id: string
  equipment: string
  family: string
  tier: string
  enabled: boolean
  topic_prefix: string
  signal_count: number
  /** Site-relative line paths this device supplies, e.g. `Production/Line1`. */
  serves: string[]
  target: SimulatorDeviceTarget
}

export interface SimulatorConfig {
  profile: string
  available_profiles: string[]
  seed: number
  tier_scale: number
  tiers: Record<string, number>
  families: Record<string, boolean>
  sites: string[]
  max_cells_per_line: number
  hierarchy: SimulatorHierarchyRow[]
  devices: SimulatorDeviceConfig[]
}

export interface PlantLineState {
  state: string
  previous: string | null
  /** 0.0-1.0. */
  production_rate: number
  throughput_tph: number
  heat_load: number
  air_demand: number
  time_in_state_s: number
  transition_count: number
}

export interface PlantSiteState {
  ambient_temp_c: number
  ambient_rh_pct: number
  wet_bulb_temp_c: number
  wind_speed_ms: number
  barometric_mbar: number
  shift: string
  tariff: string
  grid_co2_g_per_kwh: number
  /** Keyed by the site-relative line path, e.g. `Production/Line1`. */
  lines: Record<string, PlantLineState>
}

export interface PlantSnapshot {
  sites: Record<string, PlantSiteState>
}

export interface SimulatorDevice {
  id: string
  equipment: string
  topic_prefix: string
  tier: string
  family: string
  enabled: boolean
  connected: boolean
  /** Unix seconds, or null before the first publish. */
  last_publish_ts: number | null
  publish_ok: number
  publish_fail: number
  last_error: string | null
  signal_count: number
}

export interface SimulatorDeviceList {
  devices: SimulatorDevice[]
}

export interface SimulatorSignal {
  name: string
  shape: string
  /** The Unit of Measure. Named `unit` because that is the API's field name. */
  unit: string
  precision: number
  /** `[low, high]`, or null when the signal is unbounded. */
  range: [number, number] | null
  limits: Record<string, number>
  params: Record<string, unknown>
  tier: string
  param_type: string
  value: number | boolean | string | null
  /** `Normal` | `Warning` | `Alarm`, from the signal's own limit check. */
  status: string
  last_publish_ts: number | null
  /** The full ISA-95 topic this signal publishes on. Built by the API, not the browser. */
  topic: string
}

export interface SimulatorSignalList {
  device_id: string
  signals: SimulatorSignal[]
}

/** What the profile expanded to, and what it could not resolve. */
export interface SimulatorLoadReport {
  devices: number
  signals: number
  per_family: Record<string, number>
  per_tier: Record<string, number>
  serves_links: number
  unmatched_templates: string[]
  warnings: string[]
}

export interface SimulatorDeviceHealth {
  device_id: string
  client_id: string
  connected: boolean
  publish_ok: number
  publish_fail: number
  reconnects: number
  last_error: string | null
  last_publish_ts: number | null
}

export interface SimulatorDiagnostics {
  report: SimulatorLoadReport
  failing_devices: SimulatorDeviceHealth[]
  sample_topics: string[]
}

/**
 * `offline` means the request never reached the simulator; `http` means it answered and
 * refused. The console says very different things for the two, so they stay distinct:
 * "no simulator here" is a normal deployment, "your profile name is wrong" is a mistake.
 */
export interface SimulatorApiError {
  kind: 'offline' | 'http'
  status?: number
  /** Set when the API named the field it rejected. */
  field?: string
  message: string
}

export type SimulatorResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: SimulatorApiError }
```

- [ ] **Step 2: Write the client**

```typescript
// 11_frontend/src/services/simulator/client.ts
/**
 * The only place in the console that talks to 99_simulator's control API.
 *
 * Reads and writes both return SimulatorResult and never throw. The simulator is optional
 * infrastructure — a production install may not run one — so "not there" is a state to
 * render, not an exception to catch. A throwing client would need a try/catch in every
 * caller, and the one that got forgotten would blank the page.
 */

import type {
  PlantSnapshot,
  RunAction,
  SimulatorApiError,
  SimulatorConfig,
  SimulatorDeviceList,
  SimulatorDiagnostics,
  SimulatorHealth,
  SimulatorResult,
  SimulatorSignalList,
  SimulatorStatus,
} from '../../types/simulator'

/** Long enough for a loaded simulator, short enough that the console does not look hung. */
const REQUEST_TIMEOUT_MS = 5000

interface FieldErrorBody {
  detail?: { field?: string; message?: string } | Array<{ loc?: unknown[]; msg?: string }> | string
}

export class SimulatorClient {
  private baseUrl: string
  private token: string | null

  /**
   * Relative by default, so the same build works behind the Vite dev proxy and behind
   * nginx in the container without knowing which one it is behind.
   */
  constructor(baseUrl = '/simulator', token: string | null = null) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
    this.token = token
  }

  public setToken(token: string | null) {
    this.token = token
  }

  /**
   * Pull the field name and the message out of whichever 422 body arrived.
   *
   * There are two, and both are real: the API raises `{detail: {field, message}}` for
   * rejections its own validation found, and FastAPI raises pydantic's array form before
   * the handler ever runs. Handling only the first would show "Unprocessable Entity" for
   * exactly the mistakes a form is meant to explain.
   */
  private parseError(status: number, body: FieldErrorBody | null): SimulatorApiError {
    const detail = body?.detail

    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      return {
        kind: 'http',
        status,
        field: detail.field,
        message: detail.message || `Request refused with ${status}`,
      }
    }

    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0]
      const loc = Array.isArray(first.loc) ? first.loc : []
      return {
        kind: 'http',
        status,
        field: loc.length > 0 ? String(loc[loc.length - 1]) : undefined,
        message: first.msg || `Request refused with ${status}`,
      }
    }

    if (typeof detail === 'string') {
      return { kind: 'http', status, message: detail }
    }

    return { kind: 'http', status, message: `Request refused with ${status}` }
  }

  private async request<T>(
    path: string,
    method: 'GET' | 'POST' | 'PUT' = 'GET',
    body?: unknown,
  ): Promise<SimulatorResult<T>> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }
    if (this.token) {
      headers['X-Simulator-Token'] = this.token
    }

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      })

      if (!response.ok) {
        // A 404 for a device is an error body; a 404 from a proxy with no upstream is
        // HTML. Failing to parse must not become a thrown SyntaxError.
        let parsed: FieldErrorBody | null = null
        try {
          parsed = (await response.json()) as FieldErrorBody
        } catch {
          parsed = null
        }
        return { ok: false, error: this.parseError(response.status, parsed) }
      }

      return { ok: true, data: (await response.json()) as T }
    } catch {
      // Refused, DNS failure, timeout, or a body that was not JSON. From the console's
      // point of view these are one condition: there is no simulator answering here.
      return {
        ok: false,
        error: { kind: 'offline', message: 'No simulator is answering on /simulator' },
      }
    }
  }

  public getHealth(): Promise<SimulatorResult<SimulatorHealth>> {
    return this.request<SimulatorHealth>('/health')
  }

  public getStatus(): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/status')
  }

  public getConfig(): Promise<SimulatorResult<SimulatorConfig>> {
    return this.request<SimulatorConfig>('/config')
  }

  public getPlant(): Promise<SimulatorResult<PlantSnapshot>> {
    return this.request<PlantSnapshot>('/plant')
  }

  public getDevices(): Promise<SimulatorResult<SimulatorDeviceList>> {
    return this.request<SimulatorDeviceList>('/devices')
  }

  public getSignals(deviceId: string): Promise<SimulatorResult<SimulatorSignalList>> {
    return this.request<SimulatorSignalList>(`/devices/${encodeURIComponent(deviceId)}/signals`)
  }

  public getDiagnostics(): Promise<SimulatorResult<SimulatorDiagnostics>> {
    return this.request<SimulatorDiagnostics>('/diagnostics')
  }

  /**
   * Every write returns the full status body, so a caller never has to guess what the
   * simulator now looks like or fire a follow-up GET to find out.
   */
  public run(action: RunAction): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/run', 'POST', { action })
  }

  /**
   * The body key is `profile`, not `name` — Task 7's `ProfileRequest` forbids extra fields,
   * so `{name}` would come back as a 422 about an unexpected key rather than switching
   * anything.
   */
  public setProfile(profile: string, seed?: number): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>(
      '/profile',
      'PUT',
      seed === undefined ? { profile } : { profile, seed },
    )
  }

  public setTiers(intervals: Record<string, number>): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/tiers', 'PUT', intervals)
  }

  public setFamilies(flags: Record<string, boolean>): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/families', 'PUT', flags)
  }

  public setDeviceEnabled(deviceId: string, enabled: boolean): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>(
      `/devices/${encodeURIComponent(deviceId)}`,
      'PUT',
      { enabled },
    )
  }
}

export const simulatorClient = new SimulatorClient()

/**
 * Hand the browser the token, if this deployment configured one.
 *
 * Without this line a configured `simulator.api.token` locks the console out of its own
 * simulator: Task 6 answers 401 to every request that arrives without the header, and
 * nothing else in the console ever calls `setToken`. Vite inlines `import.meta.env` at
 * build time, exactly as `VITE_GRAPHQL_URL` is already used in `src/config/`, so an
 * unset variable leaves the token null and the unauthenticated default keeps working.
 *
 * A token that reaches the browser is readable in the bundle. That is understood and
 * accepted: spec §10 scopes this token to keeping other containers on the compose
 * network from driving the simulator, not to keeping it from the operator who is
 * already logged into the console.
 */
simulatorClient.setToken(import.meta.env.VITE_SIMULATOR_TOKEN ?? null)
```

- [ ] **Step 3: Declare the environment variable**

`11_frontend/src/vite-env.d.ts` declares its own `ImportMetaEnv` listing each variable by
name. Vite's own `ImportMetaEnv` carries an index signature, so the access would compile
either way — but the two GraphQL variables are listed there explicitly and a third that is
not would read as an accident. Add the third line:

```typescript
interface ImportMetaEnv {
  readonly VITE_GRAPHQL_URL?: string
  readonly VITE_GRAPHQL_WS_URL?: string
  /** Sent as X-Simulator-Token. Unset means the simulator's API takes no token. */
  readonly VITE_SIMULATOR_TOKEN?: string
}
```

- [ ] **Step 4: Verify it compiles**

```bash
cd 11_frontend && npm run lint
```

Expected: PASS. `11_frontend` has no test runner, so `tsc --noEmit` is the gate — which is
why every response type is written out in full rather than left as `any`. The types *are*
the test: if Task 5's body and this file disagree, only a reader catches it, so the
**Canonical Response Bodies** section at the top of this plan is the thing to check against.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/types/simulator.ts 11_frontend/src/services/simulator/client.ts \
  11_frontend/src/vite-env.d.ts
git commit -m "feat(frontend): add a typed client for the simulator control API"
```

---

## Task 12: Two permissions, because looking and commanding are different

Spec §7.4. `simulator_ops` to see the console; `simulator_control` to change anything.

Reusing `system_ops` would have been less work and wrong: every engineer already has it,
and stopping the simulator would silently become an engineer-level power. Reusing
`payload_publish` would be worse — it means "publish a payload", not "restart the plant".

**Files:**
- Modify: `11_frontend/src/types/rbac.ts`
- Modify: `11_frontend/src/context/AuthContext.tsx:371-405`

**Interfaces:**
- Consumes: `FeatureKey`, `SYSTEM_FEATURES`, `ROLE_CONFIGS`, `canAccessTab`.
- Produces: `FeatureKey` values `'simulator_ops'` and `'simulator_control'`, and `canAccessTab('simulator')`. Tasks 14-16 gate on `hasPermission('simulator_control')`; Task 16's route and Sidebar entry gate on `simulator_ops`.

- [ ] **Step 1: Add the two keys**

In `11_frontend/src/types/rbac.ts`, extend the `FeatureKey` union. Add after
`| 'system_ops'`:

```typescript
  | 'simulator_ops'
  | 'simulator_control'
```

- [ ] **Step 2: Describe them in `SYSTEM_FEATURES`**

Add after the `system_ops` entry:

```typescript
  {
    key: 'simulator_ops',
    label: 'Simulator Console',
    description: 'View simulator run state, plant state, device inventory, and diagnostics',
    category: 'Core Navigation',
  },
  {
    key: 'simulator_control',
    label: 'Simulator Control',
    description: 'Start, pause and stop the simulator, switch profiles, and change publish rates',
    category: 'System & Admin',
  },
```

`simulator_control` is filed under System & Admin rather than Core Navigation because it is
the only permission in the console that changes what the platform publishes. Everything
else reads.

- [ ] **Step 3: Grant them per role**

`defaultPermissions` is `Record<FeatureKey, boolean>`, so `tsc` now fails on all five role
configs until each is given both keys. That is the point of the exhaustive record: a new
permission cannot be added and quietly default to false — or to true — for anybody.

Add to each of the five `defaultPermissions` blocks, after its `system_ops` line:

```typescript
      // admin
      simulator_ops: true,
      simulator_control: true,
```

```typescript
      // engineer — owns the test data, so it configures the simulator
      simulator_ops: true,
      simulator_control: true,
```

```typescript
      // operator — sees whether test data is flowing, cannot change it
      simulator_ops: true,
      simulator_control: false,
```

```typescript
      // auditor — needs to know which data was simulated, never commands it
      simulator_ops: true,
      simulator_control: false,
```

```typescript
      // viewer
      simulator_ops: false,
      simulator_control: false,
```

An operator gets read access because "is the data I am looking at real?" is an operational
question, and the honest answer is on this page. An auditor gets it for the same reason and
more strongly: a compliance record that cannot distinguish simulated history from measured
history is not a compliance record.

- [ ] **Step 4: Teach `canAccessTab` about the tab**

In `11_frontend/src/context/AuthContext.tsx`, in the `switch (tab)` inside `canAccessTab`,
add a case after `case 'system':`:

```typescript
        case 'simulator':
          requiredFeature = 'simulator_ops';
          featureName = 'Simulator Console & Diagnostics';
          break;
```

Note what this gates: seeing the page. `simulator_control` is checked separately by the
components that write, because a viewer-shaped experience of this page — read everything,
command nothing — is the useful one for two of the five roles.

- [ ] **Step 5: Verify**

```bash
cd 11_frontend && npm run lint
```

Expected: PASS. If it reports missing properties on a `defaultPermissions` object, one of
the five roles was missed in Step 3.

- [ ] **Step 6: Commit**

```bash
git add 11_frontend/src/types/rbac.ts 11_frontend/src/context/AuthContext.tsx
git commit -m "feat(frontend): add simulator_ops and simulator_control permissions"
```

---

## Task 13: One hook, one source of truth for the numbers

Spec §7.3. Every simulator panel reads from `useSimulator()`, which polls `/status` and
`/plant` every two seconds.

**Polling, not the MQTT self-telemetry, is what the numbers on screen come from.** Both
carry a status, and one of them has to win. HTTP wins because it is a request: it returns
the state as of now, it fails visibly when the simulator is gone, and it cannot show a
retained message from a process that died an hour ago as though it were current. The MQTT
feed is used for what polling cannot do — the live event stream on the diagnostics page,
and the retained Last Will that proves the process is gone rather than merely slow.

**Files:**
- Create: `11_frontend/src/hooks/useSimulator.ts`

**Interfaces:**
- Consumes: `simulatorClient` and every type from Task 11; `unsGraphQLClient.subscribeMqttMessages` (`src/services/graphql/client.ts:512`); `platformConfig.instanceName`.
- Produces: `useSimulator()` returning the object below. Tasks 14-16 consume it; no component calls `simulatorClient` directly.

- [ ] **Step 1: Write the hook**

```typescript
// 11_frontend/src/hooks/useSimulator.ts
/**
 * Live simulator state for every panel under /simulator.
 *
 * Polls GET /status and GET /plant every two seconds. The MQTT self-telemetry carries a
 * status too, but polling is what the rendered numbers come from: a request returns the
 * state as of now and fails visibly when there is nothing to ask, while a retained MQTT
 * message from a process that died an hour ago looks exactly like a current one. The
 * subscription is here for what polling cannot give — the event feed, and the retained
 * Last Will that distinguishes "gone" from "slow".
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { platformConfig } from '../lib/platform/config'
import { simulatorClient } from '../services/simulator/client'
import { unsGraphQLClient } from '../services/graphql/client'
import type {
  PlantSnapshot,
  RunAction,
  SimulatorApiError,
  SimulatorConfig,
  SimulatorDevice,
  SimulatorDiagnostics,
  SimulatorResult,
  SimulatorSignal,
  SimulatorStatus,
} from '../types/simulator'
import type { MqttMessage } from '../types/uns'

const POLL_INTERVAL_MS = 2000

/** Enough to show a trend without turning the diagnostics page into a memory leak. */
const TELEMETRY_BUFFER = 100

export interface SimulatorTelemetryEvent {
  topic: string
  /** Whatever the broker sent, unnarrowed. The feed renders it; it does not interpret it. */
  payload: MqttMessage['payload']
  receivedAt: string
}

export function useSimulator() {
  const [status, setStatus] = useState<SimulatorStatus | null>(null)
  const [plant, setPlant] = useState<PlantSnapshot | null>(null)
  const [config, setConfig] = useState<SimulatorConfig | null>(null)
  const [devices, setDevices] = useState<SimulatorDevice[]>([])
  const [diagnostics, setDiagnostics] = useState<SimulatorDiagnostics | null>(null)
  const [telemetry, setTelemetry] = useState<SimulatorTelemetryEvent[]>([])
  const [offline, setOffline] = useState(false)
  const [lastError, setLastError] = useState<SimulatorApiError | null>(null)
  const [busy, setBusy] = useState(false)

  // A ref, not state: the poller reads it and must not be restarted when it changes.
  const busyRef = useRef(false)

  const refreshStatus = useCallback(async () => {
    const result = await simulatorClient.getStatus()
    if (result.ok) {
      setStatus(result.data)
      setOffline(false)
      return
    }
    if (result.error.kind === 'offline') {
      setOffline(true)
      // The last known status is deliberately kept on screen. Blanking it would lose the
      // reason the simulator stopped, which is the one thing worth reading afterwards.
      return
    }
    setLastError(result.error)
  }, [])

  const refreshPlant = useCallback(async () => {
    const result = await simulatorClient.getPlant()
    if (result.ok) {
      setPlant(result.data)
    }
  }, [])

  const refreshConfig = useCallback(async () => {
    const result = await simulatorClient.getConfig()
    if (result.ok) {
      setConfig(result.data)
    } else if (result.error.kind !== 'offline') {
      setLastError(result.error)
    }
  }, [])

  const refreshDevices = useCallback(async () => {
    const result = await simulatorClient.getDevices()
    if (result.ok) {
      setDevices(result.data.devices)
    } else if (result.error.kind !== 'offline') {
      setLastError(result.error)
    }
  }, [])

  const refreshDiagnostics = useCallback(async () => {
    const result = await simulatorClient.getDiagnostics()
    if (result.ok) {
      setDiagnostics(result.data)
    } else if (result.error.kind !== 'offline') {
      setLastError(result.error)
    }
  }, [])

  const signals = useCallback(async (deviceId: string): Promise<SimulatorSignal[]> => {
    const result = await simulatorClient.getSignals(deviceId)
    return result.ok ? result.data.signals : []
  }, [])

  // Poll status and plant together. Two requests rather than one wider endpoint, because
  // the plant snapshot is the only body whose size grows with the profile.
  useEffect(() => {
    let cancelled = false

    const tick = async () => {
      // Skipped while a write is in flight: a poll that lands between the write and its
      // effect would paint the old run state over the new one, and the button would look
      // like it did nothing.
      if (cancelled || busyRef.current) {
        return
      }
      await Promise.all([refreshStatus(), refreshPlant()])
    }

    void tick()
    const timer = window.setInterval(() => void tick(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [refreshStatus, refreshPlant])

  // Load once. Configuration and inventory change only when a write changes them, and the
  // write handlers below refresh them explicitly.
  useEffect(() => {
    void refreshConfig()
    void refreshDevices()
  }, [refreshConfig, refreshDevices])

  // The Platform Observability feed. Subscribed through the existing GraphQL MQTT
  // subscription, so the console needs no second transport and no broker credentials.
  useEffect(() => {
    const prefix = `uns/platform/simulator/${platformConfig.instanceName}/#`
    return unsGraphQLClient.subscribeMqttMessages([prefix], (message) => {
      setTelemetry((previous) =>
        [
          {
            topic: message.topic,
            payload: message.payload,
            receivedAt: new Date().toISOString(),
          },
          ...previous,
        ].slice(0, TELEMETRY_BUFFER),
      )
    })
  }, [])

  /**
   * Run one write, then refresh from the write's own response.
   *
   * Every write returns the status body, so there is no window in which the screen shows
   * a state the simulator has already left.
   */
  const write = useCallback(
    async (action: () => Promise<SimulatorResult<SimulatorStatus>>, reloadConfig = false) => {
      setBusy(true)
      busyRef.current = true
      setLastError(null)
      try {
        const result = await action()
        if (result.ok) {
          setStatus(result.data)
          setOffline(false)
          if (reloadConfig) {
            await Promise.all([refreshConfig(), refreshDevices()])
          }
          return true
        }
        setLastError(result.error)
        setOffline(result.error.kind === 'offline')
        return false
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [refreshConfig, refreshDevices],
  )

  const run = useCallback((action: RunAction) => write(() => simulatorClient.run(action)), [write])

  // A profile switch replaces every device, so the inventory and the hierarchy are stale
  // the moment it returns.
  const setProfile = useCallback(
    (name: string, seed?: number) => write(() => simulatorClient.setProfile(name, seed), true),
    [write],
  )

  const setTiers = useCallback(
    (intervals: Record<string, number>) => write(() => simulatorClient.setTiers(intervals)),
    [write],
  )

  const setFamilies = useCallback(
    (flags: Record<string, boolean>) => write(() => simulatorClient.setFamilies(flags), true),
    [write],
  )

  const setDeviceEnabled = useCallback(
    (deviceId: string, enabled: boolean) =>
      write(() => simulatorClient.setDeviceEnabled(deviceId, enabled), true),
    [write],
  )

  return {
    status,
    plant,
    config,
    devices,
    diagnostics,
    telemetry,
    offline,
    lastError,
    busy,
    refreshStatus,
    refreshPlant,
    refreshConfig,
    refreshDevices,
    refreshDiagnostics,
    signals,
    run,
    setProfile,
    setTiers,
    setFamilies,
    setDeviceEnabled,
  }
}
```

- [ ] **Step 2: Verify**

```bash
cd 11_frontend && npm run lint
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add 11_frontend/src/hooks/useSimulator.ts
git commit -m "feat(frontend): add useSimulator, polling status and plant every two seconds"
```

---

## Task 14: Status and configuration

Spec §7.2. Two panels: what the simulator is doing, and what it is set to do.

They are separate files because they answer separate questions and are looked at at
different times — an operator checks status and never opens configuration. They are one
task because neither is testable without the other's context: a run-state chip with no way
to change the run state cannot be reviewed.

**Files:**
- Create: `11_frontend/src/components/simulator/SimulatorStatusPanel.tsx`
- Create: `11_frontend/src/components/simulator/SimulatorConfigPanel.tsx`

**Interfaces:**
- Consumes: `useSimulator()` (Task 13) — the whole return value is passed in as a prop rather than each panel calling the hook, because four panels each calling it would mean four independent pollers hitting `/status` every two seconds. `useAuth().hasPermission` (Task 12). `TIER_LABELS` is defined here and reused by Task 16.
- Produces: `type SimulatorState = ReturnType<typeof useSimulator>`; `TIER_LABELS: Record<string, string>`; `SimulatorStatusPanel({ simulator })`; `SimulatorConfigPanel({ simulator })`.

- [ ] **Step 1: Write the status panel**

```tsx
// 11_frontend/src/components/simulator/SimulatorStatusPanel.tsx
/**
 * What the simulator is doing right now, and the four buttons that change it (spec 7.1).
 *
 * Every number here comes from the polled /status body. Nothing is derived, accumulated or
 * remembered locally: a console that counted messages itself would drift from the
 * simulator within minutes and there would be no way to tell which of the two was right.
 */

import React from 'react'
import { Activity, AlertTriangle, Pause, Play, RotateCcw, Square, Lock, WifiOff } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import type { useSimulator } from '../../hooks/useSimulator'
import type { RunAction, RunState } from '../../types/simulator'

export type SimulatorState = ReturnType<typeof useSimulator>

/**
 * The seven cadence tiers, in the order an engineer thinks about them: fastest first.
 *
 * The keys are plan A's tier names exactly. A label map keyed on anything else silently
 * renders the raw tier name, which is the one failure `Record<string, string>` cannot
 * catch for us.
 */
export const TIER_LABELS: Record<string, string> = {
  fast: 'Fast (sub-second)',
  process: 'Process',
  energy: 'Energy & Utilities',
  status: 'Status & Condition',
  meter: 'Meters & Totalisers',
  lab: 'Lab & Quality',
  event: 'Event-driven',
}

const RUN_STATE_STYLES: Record<RunState, string> = {
  running: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30',
  paused: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107] border-amber-200 dark:border-[#FFC107]/30',
  starting: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  stopped: 'bg-slate-100 dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] border-[#E2E8F0] dark:border-[#334155]',
}

function formatUptime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m ${total % 60}s`
}

const Tile: React.FC<{ label: string; value: string; tone?: string }> = ({ label, value, tone }) => (
  <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B]">
    <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">{label}</div>
    <div className={`text-base font-mono font-bold tabular-nums ${tone ?? 'text-[#0F172A] dark:text-[#F8FAFC]'}`}>
      {value}
    </div>
  </div>
)

export const SimulatorStatusPanel: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { hasPermission } = useAuth()
  const canControl = hasPermission('simulator_control')
  const { status, offline, lastError, busy, run } = simulator

  // The four transitions the API accepts, and when each one is meaningful. Offering
  // `resume` on a stopped simulator would produce a 422 the operator cannot act on, so the
  // button that cannot work is the button that is not enabled.
  const runState: RunState = status?.run_state ?? 'stopped'
  const actions: Array<{ action: RunAction; label: string; icon: typeof Play; enabledIn: RunState[] }> = [
    { action: 'start', label: 'Start', icon: Play, enabledIn: ['stopped'] },
    { action: 'pause', label: 'Pause', icon: Pause, enabledIn: ['running'] },
    { action: 'resume', label: 'Resume', icon: RotateCcw, enabledIn: ['paused'] },
    { action: 'stop', label: 'Stop', icon: Square, enabledIn: ['running', 'paused', 'starting'] },
  ]

  const totalRate = status
    ? Object.values(status.msg_per_sec).reduce((sum, rate) => sum + rate, 0)
    : 0

  return (
    <div className="p-3 md:p-4 space-y-3">
      {offline && (
        <div className="p-3 rounded-lg bg-[#111114] border border-[#334155] flex items-start gap-2">
          <WifiOff className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
          <div className="text-[11px] text-[#94A3B8] font-mono">
            <div className="text-[#F8FAFC] font-bold">No simulator is answering on /simulator</div>
            {/* Stated plainly, because on most installs this is correct rather than broken. */}
            <div className="mt-0.5">
              The simulator is optional. If one should be running, check that 99_simulator is up and
              that port 8099 is reachable. Values below are the last that were read.
            </div>
          </div>
        </div>
      )}

      {status?.overrides_active && (
        <div className="p-3 rounded-lg bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-200 dark:border-[#FFC107]/30 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-[#FFC107] shrink-0 mt-0.5" />
          <div className="text-[11px] font-mono text-amber-800 dark:text-[#FFC107]">
            <span className="font-bold">Runtime overrides are active.</span> The running plant no longer
            matches the profile files on disk, and nothing here is written back to them. A restart
            returns the simulator to <code>conf/simulator/</code>.
          </div>
        </div>
      )}

      {lastError && lastError.kind === 'http' && (
        <div className="p-2.5 rounded-lg bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/30 text-[11px] font-mono text-rose-700 dark:text-rose-400">
          {lastError.field ? `${lastError.field}: ${lastError.message}` : lastError.message}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`px-2.5 py-1 rounded border text-[10px] font-mono font-bold uppercase tracking-wider ${RUN_STATE_STYLES[runState]}`}
        >
          {runState}
        </span>
        <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px]">
          profile: {status?.profile ?? '—'}
        </span>
        <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px]">
          seed: {status?.seed ?? '—'}
        </span>

        <div className="flex-1" />

        {!canControl && (
          <span className="px-2 py-0.5 rounded bg-[#1E293B] border border-[#334155] text-[#94A3B8] text-[9px] flex items-center gap-1">
            <Lock className="w-3 h-3 text-rose-400" />
            <span>Read-Only Mode</span>
          </span>
        )}

        <div className="flex items-center gap-1.5">
          {actions.map(({ action, label, icon: Icon, enabledIn }) => {
            const disabled = !canControl || busy || offline || !enabledIn.includes(runState)
            return (
              <button
                key={action}
                id={`simulator-run-${action}`}
                disabled={disabled}
                onClick={() => void run(action)}
                title={canControl ? label : 'Requires the Simulator Control permission'}
                className={`px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 transition-colors ${
                  disabled
                    ? 'bg-[#F1F5F9] dark:bg-[#1E293B] border-[#E2E8F0] dark:border-[#334155] text-[#94A3B8] cursor-not-allowed'
                    : 'bg-amber-500 dark:bg-[#FFC107] border-amber-500 dark:border-[#FFC107] text-slate-950 dark:text-[#0B0B0C] hover:brightness-110 cursor-pointer'
                }`}
              >
                <Icon className="w-3 h-3" />
                <span>{label}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
        <Tile label="Devices" value={String(status?.device_count ?? 0)} />
        <Tile label="Signals" value={String(status?.signal_count ?? 0)} />
        <Tile label="Msg / sec" value={totalRate.toFixed(1)} />
        <Tile label="Published" value={(status?.published_total ?? 0).toLocaleString()} />
        <Tile
          label="Failed"
          value={(status?.failed_total ?? 0).toLocaleString()}
          tone={
            (status?.failed_total ?? 0) > 0
              ? 'text-rose-600 dark:text-rose-400'
              : 'text-[#0F172A] dark:text-[#F8FAFC]'
          }
        />
        <Tile label="Uptime" value={formatUptime(status?.uptime_s ?? 0)} />
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B]">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider flex items-center gap-1.5 mb-2">
          <Activity className="w-3.5 h-3.5" />
          <span>Publish rate by cadence tier</span>
        </div>
        <div className="space-y-1">
          {Object.entries(status?.msg_per_sec ?? {}).map(([tier, rate]) => (
            <div key={tier} className="flex items-center justify-between font-mono text-[11px]">
              <span className="text-[#64748B] dark:text-[#94A3B8]">{TIER_LABELS[tier] ?? tier}</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {rate.toFixed(2)} /s
                <span className="text-[#64748B] ml-2">({status?.per_tier[tier] ?? 0} signals)</span>
              </span>
            </div>
          ))}
          {Object.keys(status?.msg_per_sec ?? {}).length === 0 && (
            <div className="text-[11px] font-mono text-[#64748B]">Nothing is publishing.</div>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Write the configuration panel**

```tsx
// 11_frontend/src/components/simulator/SimulatorConfigPanel.tsx
/**
 * What the simulator is set to do, and the four things that can be changed (spec 7.2):
 * the profile, the tier intervals, the sensor families, and whether a device publishes.
 *
 * Interval fields are local state until Apply. Sending a PUT per keystroke would
 * reschedule every publish task on the way from "3" to "30" and the plant would stutter
 * while somebody typed.
 */

import React, { useEffect, useState } from 'react'
import { Check, Layers, Lock, Save, Sliders } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'

export const SimulatorConfigPanel: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { hasPermission } = useAuth()
  const canControl = hasPermission('simulator_control')
  const { config, status, devices, busy, offline, setProfile, setTiers, setFamilies, setDeviceEnabled } =
    simulator

  const [profileDraft, setProfileDraft] = useState('')
  const [seedDraft, setSeedDraft] = useState('')
  const [tierDrafts, setTierDrafts] = useState<Record<string, string>>({})

  // Reseed the drafts whenever the server's own view changes — after a profile switch, the
  // tier map is a different map. Keyed on the values themselves rather than a mount, so a
  // switch made in another browser tab does not leave stale numbers in these boxes.
  useEffect(() => {
    if (!config) {
      return
    }
    setProfileDraft(config.profile)
    setSeedDraft(String(config.seed))
    setTierDrafts(
      Object.fromEntries(Object.entries(config.tiers).map(([tier, seconds]) => [tier, String(seconds)])),
    )
  }, [config])

  const disabled = !canControl || busy || offline

  const applyTiers = () => {
    const intervals: Record<string, number> = {}
    for (const [tier, raw] of Object.entries(tierDrafts)) {
      const parsed = Number(raw)
      // Only what actually changed, and only what is a number. The API rejects negatives
      // itself; sending NaN would get a pydantic error naming a field the operator did not
      // touch, which is a worse message than silently skipping it.
      if (Number.isFinite(parsed) && parsed !== config?.tiers[tier]) {
        intervals[tier] = parsed
      }
    }
    if (Object.keys(intervals).length > 0) {
      void setTiers(intervals)
    }
  }

  const applyProfile = () => {
    const seed = seedDraft.trim() === '' ? undefined : Number(seedDraft)
    void setProfile(profileDraft, Number.isFinite(seed) ? seed : undefined)
  }

  return (
    <div className="p-3 md:p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
          <Sliders className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
          <span>Simulator Configuration</span>
        </h3>
        {!canControl && (
          <span className="px-2 py-0.5 rounded bg-[#1E293B] border border-[#334155] text-[#94A3B8] text-[9px] flex items-center gap-1">
            <Lock className="w-3 h-3 text-rose-400" />
            <span>Read-Only Mode</span>
          </span>
        )}
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-2">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
          Profile &amp; seed
        </div>
        {/* Said once, here: switching profiles rebuilds the plant and resets the counters. */}
        <div className="text-[10px] font-mono text-[#64748B] dark:text-[#94A3B8]">
          Switching the profile replaces every device and resets the published and failed counters.
          A refused switch leaves the running simulator untouched.
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[180px]">
            <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor="simulator-profile">
              PROFILE:
            </label>
            <select
              id="simulator-profile"
              disabled={disabled}
              value={profileDraft}
              onChange={(event) => setProfileDraft(event.target.value)}
              className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded px-2.5 py-1.5 text-[#0F172A] dark:text-[#F8FAFC] text-[11px] font-mono focus:outline-none focus:border-[#FFC107] disabled:opacity-50"
            >
              {(config?.available_profiles ?? []).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div className="w-28">
            <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor="simulator-seed">
              SEED:
            </label>
            <input
              id="simulator-seed"
              type="number"
              disabled={disabled}
              value={seedDraft}
              onChange={(event) => setSeedDraft(event.target.value)}
              className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded px-2.5 py-1.5 text-[#0F172A] dark:text-[#F8FAFC] text-[11px] font-mono tabular-nums focus:outline-none focus:border-[#FFC107] disabled:opacity-50"
            />
          </div>
          <button
            id="simulator-apply-profile"
            disabled={disabled || profileDraft === ''}
            onClick={applyProfile}
            className="px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 bg-amber-500 dark:bg-[#FFC107] border-amber-500 dark:border-[#FFC107] text-slate-950 dark:text-[#0B0B0C] hover:brightness-110 cursor-pointer disabled:bg-[#1E293B] disabled:border-[#334155] disabled:text-[#94A3B8] disabled:cursor-not-allowed"
          >
            <Save className="w-3 h-3" />
            <span>Apply profile</span>
          </button>
        </div>
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-2">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
          Cadence tiers — seconds between publishes
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
          {Object.keys(tierDrafts).map((tier) => (
            <div key={tier}>
              <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor={`simulator-tier-${tier}`}>
                {(TIER_LABELS[tier] ?? tier).toUpperCase()}:
              </label>
              <input
                id={`simulator-tier-${tier}`}
                type="number"
                min={0}
                step="0.1"
                disabled={disabled}
                value={tierDrafts[tier]}
                onChange={(event) =>
                  setTierDrafts((previous) => ({ ...previous, [tier]: event.target.value }))
                }
                className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded px-2.5 py-1.5 text-[#0F172A] dark:text-[#F8FAFC] text-[11px] font-mono tabular-nums focus:outline-none focus:border-[#FFC107] disabled:opacity-50"
              />
            </div>
          ))}
        </div>
        <button
          id="simulator-apply-tiers"
          disabled={disabled}
          onClick={applyTiers}
          className="px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 bg-amber-500 dark:bg-[#FFC107] border-amber-500 dark:border-[#FFC107] text-slate-950 dark:text-[#0B0B0C] hover:brightness-110 cursor-pointer disabled:bg-[#1E293B] disabled:border-[#334155] disabled:text-[#94A3B8] disabled:cursor-not-allowed"
        >
          <Check className="w-3 h-3" />
          <span>Apply intervals</span>
        </button>
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-2">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
          Sensor families
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-1.5">
          {Object.entries(status?.families ?? config?.families ?? {}).map(([family, enabled]) => (
            <label
              key={family}
              className="flex items-center gap-2 px-2 py-1.5 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] font-mono text-[11px] text-[#0F172A] dark:text-[#F8FAFC] cursor-pointer"
            >
              <input
                type="checkbox"
                disabled={disabled}
                checked={enabled}
                onChange={(event) => void setFamilies({ [family]: event.target.checked })}
                className="accent-[#FFC107]"
              />
              <span>{family}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-1.5">
          <Layers className="w-3.5 h-3.5" />
          <span>Devices ({devices.length})</span>
        </div>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Device</th>
                <th className="text-left px-3 py-1.5">Equipment</th>
                <th className="text-left px-3 py-1.5">Family</th>
                <th className="text-left px-3 py-1.5">Tier</th>
                <th className="text-right px-3 py-1.5">Signals</th>
                <th className="text-right px-3 py-1.5">Published</th>
                <th className="text-right px-3 py-1.5">Enabled</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {devices.map((device) => (
                <tr key={device.id} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  {/* `id` is the device's name — plan A's DeviceSpec has no separate label,
                      and the topic prefix is the disambiguator when two ids read alike. */}
                  <td className="px-3 py-1.5" title={device.topic_prefix}>{device.id}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{device.equipment}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{device.family}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">
                    {TIER_LABELS[device.tier] ?? device.tier}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{device.signal_count}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{device.publish_ok.toLocaleString()}</td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      type="checkbox"
                      aria-label={`Enable ${device.id}`}
                      disabled={disabled}
                      checked={device.enabled}
                      onChange={(event) => void setDeviceEnabled(device.id, event.target.checked)}
                      className="accent-[#FFC107]"
                    />
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-center text-[#64748B]">
                    No devices. Start the simulator, or check that a profile is loaded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify**

```bash
cd 11_frontend && npm run lint
```

Expected: PASS. Nothing renders these yet — Task 16 mounts them — so the compiler is the
only check available at this point, which is exactly why both files are fully typed against
Task 11's interfaces.

- [ ] **Step 4: Commit**

```bash
git add 11_frontend/src/components/simulator/SimulatorStatusPanel.tsx 11_frontend/src/components/simulator/SimulatorConfigPanel.tsx
git commit -m "feat(frontend): add the simulator status and configuration panels"
```

---

## Task 15: The plant, and the signals

Spec §7.2. The two panels that answer "is the simulated plant behaving like a plant?" — the
PackML state of every line with the ambient conditions driving it, and the current value of
every signal on a device.

This is the pair that makes the simulator debuggable rather than merely controllable. A
publish rate tells you messages are leaving; only these tell you the numbers in them mean
something.

**Files:**
- Create: `11_frontend/src/components/simulator/PlantStateInspector.tsx`
- Create: `11_frontend/src/components/simulator/SignalInspector.tsx`

**Interfaces:**
- Consumes: `SimulatorState` and `TIER_LABELS` (Task 14); `simulator.plant`, `simulator.devices`, `simulator.signals(deviceId)` (Task 13); `unsGraphQLClient.subscribeMqttMessages`; `SimulatorSignal` (Task 11).
- Produces: `PlantStateInspector({ simulator })`, `SignalInspector({ simulator })`. Task 16 mounts both.

- [ ] **Step 1: Write the plant state inspector**

```tsx
// 11_frontend/src/components/simulator/PlantStateInspector.tsx
/**
 * The PackML state of every line, per site, with the ambient conditions, shift and tariff
 * that drive it (spec 7.2).
 *
 * The ambient block is not decoration. It is the shared input every utility signal in plan
 * A is derived from — chiller load follows wet-bulb, compressor efficiency follows ambient
 * temperature, and the energy cost follows the tariff. Showing them beside the line states
 * is what makes "why did power jump at 14:00?" answerable from one screen.
 *
 * Read from the polled /plant snapshot rather than accumulated from the MQTT transition
 * events. The events say what changed; the snapshot says what is true, including for a
 * console that was opened after the transition happened.
 */

import React from 'react'
import { Factory } from 'lucide-react'
import type { SimulatorState } from './SimulatorStatusPanel'

/**
 * PackML's states, coloured by what an operator would do about them. Execute is green,
 * Held and Aborted are red, and everything in between is a transition worth noticing but
 * not worth alarming about.
 */
const STATE_STYLES: Record<string, string> = {
  Execute: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30',
  Idle: 'bg-slate-100 dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] border-[#E2E8F0] dark:border-[#334155]',
  Starting: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  Completing: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  Complete: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/30',
  Holding: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107] border-amber-200 dark:border-[#FFC107]/30',
  Held: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-500/30',
  Aborted: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-500/30',
  Stopped: 'bg-slate-100 dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] border-[#E2E8F0] dark:border-[#334155]',
}

function stateStyle(state: string): string {
  return STATE_STYLES[state] ?? STATE_STYLES.Idle
}

function formatSeconds(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(total / 60)
  return minutes > 0 ? `${minutes}m ${total % 60}s` : `${total}s`
}

/** Tariff, coloured by cost, because the peak window is the one worth noticing. */
const TARIFF_STYLES: Record<string, string> = {
  peak: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-500/30',
  shoulder: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107] border-amber-200 dark:border-[#FFC107]/30',
  off_peak: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30',
}

const Ambient: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="px-2 py-1.5 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]">
    <div className="text-[9px] text-[#64748B] uppercase tracking-wider">{label}</div>
    <div className="text-[11px] font-mono tabular-nums text-[#0F172A] dark:text-[#F8FAFC]">{value}</div>
  </div>
)

export const PlantStateInspector: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { status, plant } = simulator
  const sites = Object.entries(plant?.sites ?? {})

  return (
    <div className="p-3 md:p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
          <Factory className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
          <span>Plant State</span>
        </h3>
        {/* The tick count is on /status, not /plant — the clock belongs to the simulator,
            not to any one site. */}
        <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px] tabular-nums">
          tick {status?.tick_count ?? 0}
        </span>
      </div>

      {sites.length === 0 && (
        <div className="p-4 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] text-[11px] font-mono text-[#64748B] text-center">
          No plant state. The simulator is stopped, or no profile is loaded.
        </div>
      )}

      {sites.map(([site, siteState]) => (
        <div
          key={site}
          className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden"
        >
          <div className="px-3 py-2 border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center justify-between gap-2">
            <span className="font-mono text-[11px] font-bold text-[#0F172A] dark:text-[#F8FAFC]">{site}</span>
            <div className="flex items-center gap-1.5">
              <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[9px] uppercase">
                shift {siteState.shift}
              </span>
              <span
                className={`px-2 py-0.5 rounded border font-mono text-[9px] font-bold uppercase ${
                  TARIFF_STYLES[siteState.tariff] ?? TARIFF_STYLES.shoulder
                }`}
              >
                {siteState.tariff.replace('_', ' ')}
              </span>
            </div>
          </div>

          <div className="px-3 py-2 grid grid-cols-3 xl:grid-cols-6 gap-1.5 border-b border-[#E2E8F0] dark:border-[#1E293B]">
            <Ambient label="Ambient" value={`${siteState.ambient_temp_c.toFixed(1)} °C`} />
            <Ambient label="Humidity" value={`${siteState.ambient_rh_pct.toFixed(0)} %`} />
            <Ambient label="Wet bulb" value={`${siteState.wet_bulb_temp_c.toFixed(1)} °C`} />
            <Ambient label="Wind" value={`${siteState.wind_speed_ms.toFixed(1)} m/s`} />
            <Ambient label="Pressure" value={`${siteState.barometric_mbar.toFixed(0)} mbar`} />
            <Ambient label="Grid CO₂" value={`${siteState.grid_co2_g_per_kwh.toFixed(0)} g/kWh`} />
          </div>

          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Line</th>
                <th className="text-left px-3 py-1.5">PackML state</th>
                <th className="text-left px-3 py-1.5">Previous</th>
                <th className="text-right px-3 py-1.5">Rate</th>
                <th className="text-right px-3 py-1.5">Throughput</th>
                <th className="text-right px-3 py-1.5">Heat load</th>
                <th className="text-right px-3 py-1.5">Air demand</th>
                <th className="text-right px-3 py-1.5">Time in state</th>
                <th className="text-right px-3 py-1.5">Transitions</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {Object.entries(siteState.lines).map(([line, lineState]) => (
                <tr key={line} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  <td className="px-3 py-1.5">{line}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`px-2 py-0.5 rounded border text-[9px] font-bold uppercase ${stateStyle(lineState.state)}`}
                    >
                      {lineState.state}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.previous ?? '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {(lineState.production_rate * 100).toFixed(0)}%
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {lineState.throughput_tph.toFixed(1)} t/h
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.heat_load.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.air_demand.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {formatSeconds(lineState.time_in_state_s)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {lineState.transition_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Write the signal inspector**

```tsx
// 11_frontend/src/components/simulator/SignalInspector.tsx
/**
 * Every signal on one device: name, Unit of Measure, tier, current value, limit status and
 * topic (spec 7.2), plus a live sparkline per topic.
 *
 * The table is a snapshot from GET /devices/{id}/signals; the sparkline comes from the
 * device's own MQTT topics through the existing GraphQL subscription. Both, because they
 * answer different questions: the table proves the signal exists and is configured, the
 * sparkline proves it is moving. A signal frozen at a plausible value is the failure this
 * page is here to catch, and only the second one shows it.
 */

import React, { useEffect, useMemo, useState } from 'react'
import { Gauge, RefreshCw } from 'lucide-react'
import { unsGraphQLClient } from '../../services/graphql/client'
import type { SimulatorSignal } from '../../types/simulator'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'

/** Points kept per topic. Twenty is a shape; a hundred would be a chart nobody asked for. */
const SPARK_POINTS = 20

/**
 * The three values `Signal.status()` returns in plan A, from its own limit check. This is
 * not MQTT quality — every value here was generated successfully, so a `quality` column
 * would read `Good` on every row forever and teach an operator to ignore the column that
 * does mean something.
 */
const SIGNAL_STATUS_STYLES: Record<string, string> = {
  Normal: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  Warning: 'bg-amber-50 dark:bg-[#FFC107]/10 text-amber-700 dark:text-[#FFC107]',
  Alarm: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400',
}

const Sparkline: React.FC<{ points: number[] }> = ({ points }) => {
  if (points.length < 2) {
    return <span className="text-[#64748B] text-[9px]">waiting…</span>
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const path = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 60
      const y = 14 - ((value - min) / span) * 12
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg width="60" height="16" viewBox="0 0 60 16" className="overflow-visible">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1" className="text-[#FFC107]" />
    </svg>
  )
}

function formatValue(value: SimulatorSignal['value']): string {
  if (value === null) {
    return '—'
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(3)
  }
  return String(value)
}

export const SignalInspector: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { devices, signals } = simulator
  const [selectedId, setSelectedId] = useState('')
  const [rows, setRows] = useState<SimulatorSignal[]>([])
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<Record<string, number[]>>({})

  const selected = useMemo(
    () => devices.find((device) => device.id === selectedId),
    [devices, selectedId],
  )

  // Select the first device once there is one, and hold that choice while the inventory
  // refreshes underneath — resetting on every poll would fight whoever is reading.
  useEffect(() => {
    if (selectedId === '' && devices.length > 0) {
      setSelectedId(devices[0].id)
    }
  }, [devices, selectedId])

  useEffect(() => {
    if (selectedId === '') {
      return
    }
    let cancelled = false
    setLoading(true)
    setHistory({})
    void signals(selectedId).then((result) => {
      if (!cancelled) {
        setRows(result)
        setLoading(false)
      }
    })
    return () => {
      cancelled = true
    }
  }, [selectedId, signals])

  // One wildcard subscription for the whole device rather than one per signal: a hundred
  // subscriptions would mean a hundred GraphQL operations for one table.
  useEffect(() => {
    if (!selected) {
      return
    }
    return unsGraphQLClient.subscribeMqttMessages([`${selected.topic_prefix}/#`], (message) => {
      const payload = message.payload
      if (payload === null || typeof payload !== 'object') {
        return
      }
      const numbers = Object.values(payload).filter(
        (candidate): candidate is number => typeof candidate === 'number',
      )
      if (numbers.length === 0) {
        return
      }
      setHistory((previous) => ({
        ...previous,
        [message.topic]: [...(previous[message.topic] ?? []), numbers[0]].slice(-SPARK_POINTS),
      }))
    })
  }, [selected])

  return (
    <div className="p-3 md:p-4 space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[220px]">
          <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor="simulator-signal-device">
            DEVICE:
          </label>
          <select
            id="simulator-signal-device"
            value={selectedId}
            onChange={(event) => setSelectedId(event.target.value)}
            className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded px-2.5 py-1.5 text-[#0F172A] dark:text-[#F8FAFC] text-[11px] font-mono focus:outline-none focus:border-[#FFC107]"
          >
            <option value="">— select a device —</option>
            {devices.map((device) => (
              <option key={device.id} value={device.id}>
                {device.id} — {device.equipment} ({device.signal_count})
              </option>
            ))}
          </select>
        </div>
        <button
          id="simulator-refresh-signals"
          disabled={selectedId === '' || loading}
          onClick={() => void signals(selectedId).then(setRows)}
          className="px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 bg-[#F1F5F9] dark:bg-[#1E293B] border-[#E2E8F0] dark:border-[#334155] text-[#0F172A] dark:text-[#F8FAFC] hover:brightness-110 cursor-pointer disabled:text-[#94A3B8] disabled:cursor-not-allowed"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh values</span>
        </button>
        {selected && (
          <span className="px-2 py-0.5 rounded bg-[#F1F5F9] dark:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] font-mono text-[10px] truncate max-w-full">
            {selected.topic_prefix}
          </span>
        )}
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-1.5">
          <Gauge className="w-3.5 h-3.5" />
          <span>Signals ({rows.length})</span>
        </div>
        <div className="max-h-[28rem] overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Signal</th>
                <th className="text-left px-3 py-1.5">Unit of Measure</th>
                <th className="text-left px-3 py-1.5">Tier</th>
                <th className="text-right px-3 py-1.5">Value</th>
                <th className="text-left px-3 py-1.5">Status</th>
                <th className="text-left px-3 py-1.5">Live</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {rows.map((signal) => (
                <tr key={signal.topic} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  <td className="px-3 py-1.5" title={signal.topic}>
                    {signal.name}
                  </td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{signal.unit || '—'}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">
                    {TIER_LABELS[signal.tier] ?? signal.tier}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{formatValue(signal.value)}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${SIGNAL_STATUS_STYLES[signal.status] ?? SIGNAL_STATUS_STYLES.Normal}`}
                    >
                      {signal.status}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    <Sparkline points={history[signal.topic] ?? []} />
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-[#64748B]">
                    {selectedId === '' ? 'Select a device.' : 'This device publishes no signals.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify**

```bash
cd 11_frontend && npm run lint
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add 11_frontend/src/components/simulator/PlantStateInspector.tsx 11_frontend/src/components/simulator/SignalInspector.tsx
git commit -m "feat(frontend): add the plant state and signal inspectors"
```

---

## Task 16: The diagnostics page, and the route that reaches all of it

Spec §7.2 and §7.1. The diagnostics panel, the view that holds the four sub-tabs, the route,
the tab-id mapping that enforces the permission, and the sidebar entry.

These are one task because a route without a view is dead code and a view nobody can reach
is untestable. This is the task where the feature becomes usable, so it is the one a
reviewer can actually accept or reject.

**One thing to get right, and it is easy to miss:** the app uses `HashRouter`. The console
route is `#/simulator`, so the browser's HTTP path stays `/` and never collides with the
`/simulator` proxy location added in Task 10. With `BrowserRouter` these two would fight
over the same URL and nginx would win.

**Files:**
- Create: `11_frontend/src/components/simulator/SimulatorDiagnosticsPanel.tsx`
- Create: `11_frontend/src/components/simulator/SimulatorView.tsx`
- Modify: `11_frontend/src/App.tsx`
- Modify: `11_frontend/src/components/layout/AppLayout.tsx:32-41`
- Modify: `11_frontend/src/components/layout/Sidebar.tsx:3-19` and `:108-131`

**Interfaces:**
- Consumes: everything from Tasks 12-15; `canAccessTab('simulator')`; `AccessRestricted`.
- Produces: `SimulatorDiagnosticsPanel({ simulator })`, `SimulatorView` (the default-exported-style named route component), the `/simulator` route, `getTabIdFromPath('/simulator') === 'simulator'`, and the sidebar entry.

- [ ] **Step 1: Write the diagnostics panel**

```tsx
// 11_frontend/src/components/simulator/SimulatorDiagnosticsPanel.tsx
/**
 * Why the simulator is not doing what was expected (spec 7.2).
 *
 * Named ...Panel rather than ...Diagnostics so it does not read as the SimulatorDiagnostics
 * response type it consumes.
 *
 * Five things, in the order they get checked when something is wrong: the broker, what the
 * profile actually expanded to against what it asked for, the templates that matched nothing,
 * the devices that are failing to publish, and the live Platform Observability feed.
 */

import React, { useEffect } from 'react'
import { AlertTriangle, Radio, Server, Stethoscope } from 'lucide-react'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'

export const SimulatorDiagnosticsPanel: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { status, diagnostics, telemetry, refreshDiagnostics } = simulator

  // Fetched when this sub-tab is opened, not polled. The diagnostics body walks every
  // device, and paying for that every two seconds to serve a page nobody has open is the
  // kind of load a diagnostics page should not itself create.
  useEffect(() => {
    void refreshDiagnostics()
    const timer = window.setInterval(() => void refreshDiagnostics(), 5000)
    return () => window.clearInterval(timer)
  }, [refreshDiagnostics])

  // The broker line comes from /status, not /diagnostics: `broker_connected` is polled every
  // two seconds there and would be a second, staler copy of the same fact here.
  const report = diagnostics?.report
  const failing = diagnostics?.failing_devices ?? []

  return (
    <div className="p-3 md:p-4 space-y-3">
      <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
        <Stethoscope className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
        <span>Simulator Diagnostics</span>
      </h3>

      {/* The profile loader's own complaints: a cap that dropped cells, a family that was
          asked for and is not configured. These are the reasons a device count is not the
          count somebody expected. */}
      {(report?.warnings ?? []).map((warning) => (
        <div
          key={warning}
          className="p-2.5 rounded-lg bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-200 dark:border-[#FFC107]/30 text-[11px] font-mono text-amber-800 dark:text-[#FFC107] flex items-start gap-2"
        >
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{warning}</span>
        </div>
      ))}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1.5">
          <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider flex items-center gap-1.5">
            <Server className="w-3.5 h-3.5" />
            <span>MQTT broker</span>
          </div>
          <div className="font-mono text-[11px] space-y-1">
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Connected</span>
              <span
                className={
                  status?.broker_connected
                    ? 'text-emerald-600 dark:text-emerald-400 font-bold'
                    : 'text-rose-600 dark:text-rose-400 font-bold'
                }
              >
                {status ? (status.broker_connected ? 'YES' : 'NO') : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Failed publishes</span>
              <span
                className={`tabular-nums ${
                  (status?.failed_total ?? 0) > 0
                    ? 'text-rose-600 dark:text-rose-400 font-bold'
                    : 'text-[#0F172A] dark:text-[#F8FAFC]'
                }`}
              >
                {(status?.failed_total ?? 0).toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Devices failing</span>
              {/* Connected and stable are different questions. A broker that answers while
                  a third of the devices cannot publish reads as healthy without this row. */}
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {failing.length} / {status?.device_count ?? 0}
              </span>
            </div>
          </div>
        </div>

        <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1.5">
          <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
            What the profile expanded to
          </div>
          <div className="font-mono text-[11px] space-y-1">
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Devices</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {report?.devices ?? '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Signals</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {report?.signals ?? '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Serves links</span>
              {/* Zero here with utilities enabled means no chiller is tied to any line, and
                  every utility signal is a free-running number rather than a correlated one. */}
              <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">
                {report?.serves_links ?? '—'}
              </span>
            </div>
            {Object.entries(report?.per_tier ?? {}).map(([tier, count]) => (
              <div key={tier} className="flex justify-between">
                <span className="text-[#64748B] dark:text-[#94A3B8]">
                  {TIER_LABELS[tier] ?? tier}
                </span>
                <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">{count}</span>
              </div>
            ))}
            {Object.entries(report?.per_family ?? {}).map(([family, count]) => (
              <div key={family} className="flex justify-between">
                <span className="text-[#64748B] dark:text-[#94A3B8]">family: {family}</span>
                <span className="text-[#0F172A] dark:text-[#F8FAFC] tabular-nums">{count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {(report?.unmatched_templates ?? []).length > 0 && (
        <div className="p-2.5 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B]">
          <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider mb-1.5">
            Templates that matched nothing ({report?.unmatched_templates.length})
          </div>
          {/* The most common profile mistake, and invisible without this list: a template
              referenced by a name no equipment carries expands to no devices at all. */}
          <div className="font-mono text-[10px] text-amber-700 dark:text-[#FFC107] space-y-0.5">
            {(report?.unmatched_templates ?? []).map((template) => (
              <div key={template} className="break-all">
                {template}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B]">
          Devices needing attention ({failing.length})
        </div>
        <div className="max-h-56 overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Device</th>
                <th className="text-left px-3 py-1.5">Client id</th>
                <th className="text-left px-3 py-1.5">Connected</th>
                <th className="text-right px-3 py-1.5">OK</th>
                <th className="text-right px-3 py-1.5">Failed</th>
                <th className="text-right px-3 py-1.5">Reconnects</th>
                <th className="text-left px-3 py-1.5">Last error</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {/* The API has already decided which devices belong here — anything
                  disconnected or with a failure. Re-filtering in the browser would be a
                  second, disagreeing definition of "needs attention". */}
              {failing.map((device) => (
                <tr key={device.device_id} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  <td className="px-3 py-1.5">{device.device_id}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{device.client_id}</td>
                  <td className="px-3 py-1.5">{device.connected ? 'yes' : 'no'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {device.publish_ok.toLocaleString()}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-rose-600 dark:text-rose-400">
                    {device.publish_fail.toLocaleString()}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#64748B] dark:text-[#94A3B8]">
                    {device.reconnects}
                  </td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8] truncate max-w-xs">
                    {device.last_error ?? '—'}
                  </td>
                </tr>
              ))}
              {failing.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-3 text-center text-emerald-600 dark:text-emerald-400">
                    Every device is connected and publishing.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-1.5">
          <Radio className="w-3.5 h-3.5" />
          <span>Platform Observability feed — uns/platform/simulator/#</span>
        </div>
        {/* Deliberately labelled with its prefix. This feed is the simulator talking about
            itself; nothing here is plant data, and no mapper persists it. */}
        <div className="max-h-64 overflow-y-auto divide-y divide-[#E2E8F0]/60 dark:divide-[#1E293B]/60">
          {telemetry.map((event, index) => (
            <div key={`${event.receivedAt}-${index}`} className="px-3 py-1.5 font-mono text-[10px]">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-amber-700 dark:text-[#FFC107] truncate">{event.topic}</span>
                <span className="text-[#64748B] shrink-0 tabular-nums">
                  {event.receivedAt.slice(11, 19)}
                </span>
              </div>
              <div className="text-[#64748B] dark:text-[#94A3B8] break-all">
                {typeof event.payload === 'object' && event.payload !== null
                  ? JSON.stringify(event.payload)
                  : String(event.payload)}
              </div>
            </div>
          ))}
          {telemetry.length === 0 && (
            <div className="px-3 py-3 text-center font-mono text-[10px] text-[#64748B]">
              Nothing received yet. The status heartbeat publishes every ten seconds.
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] p-3">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider mb-1.5">
          Sample topics
        </div>
        <div className="font-mono text-[10px] text-[#64748B] dark:text-[#94A3B8] space-y-0.5">
          {(diagnostics?.sample_topics ?? []).map((topic) => (
            <div key={topic} className="break-all">
              {topic}
            </div>
          ))}
          {(diagnostics?.sample_topics ?? []).length === 0 && <div>—</div>}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Write the view that holds the sub-tabs**

```tsx
// 11_frontend/src/components/simulator/SimulatorView.tsx
/**
 * The /simulator console route (spec 7.1).
 *
 * Calls useSimulator once and passes the result down. Four panels each calling the hook
 * would mean four independent pollers on /status, and they would disagree with each other
 * on screen.
 */

import React, { useState } from 'react'
import { Cpu, Factory, Gauge, Sliders, Stethoscope } from 'lucide-react'
import { useSimulator } from '../../hooks/useSimulator'
import { PlantStateInspector } from './PlantStateInspector'
import { SignalInspector } from './SignalInspector'
import { SimulatorConfigPanel } from './SimulatorConfigPanel'
import { SimulatorDiagnosticsPanel } from './SimulatorDiagnosticsPanel'
import { SimulatorStatusPanel } from './SimulatorStatusPanel'

type SubTab = 'status' | 'configure' | 'plant' | 'diagnostics'

const SUB_TABS: Array<{ id: SubTab; label: string; icon: typeof Cpu }> = [
  { id: 'status', label: 'Status & Run Control', icon: Cpu },
  { id: 'configure', label: 'Configuration', icon: Sliders },
  { id: 'plant', label: 'Plant & Signals', icon: Factory },
  { id: 'diagnostics', label: 'Diagnostics', icon: Stethoscope },
]

export const SimulatorView: React.FC = () => {
  const simulator = useSimulator()
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('status')

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-3 md:px-4 py-2.5 bg-white dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-2 shrink-0">
        <Gauge className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
        <div className="min-w-0">
          <h2 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider">
            Simulator Console
          </h2>
          {/* Says what this data is, on the page that commands it. */}
          <p className="text-[10px] font-mono text-[#64748B] dark:text-[#94A3B8] truncate">
            99_simulator — synthetic plant telemetry. Everything it publishes is simulated.
          </p>
        </div>
      </div>

      <div className="px-3 md:px-4 bg-white dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center shrink-0 overflow-x-auto scrollbar-none">
        <div className="flex items-center gap-1 min-w-max">
          {SUB_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              id={`subtab-simulator-${id}`}
              onClick={() => setActiveSubTab(id)}
              className={`px-3 py-2.5 border-b-2 font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
                activeSubTab === id
                  ? 'border-amber-500 dark:border-[#FFC107] text-amber-700 dark:text-[#FFC107]'
                  : 'border-transparent text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {activeSubTab === 'status' && <SimulatorStatusPanel simulator={simulator} />}
        {activeSubTab === 'configure' && <SimulatorConfigPanel simulator={simulator} />}
        {activeSubTab === 'plant' && (
          <>
            <PlantStateInspector simulator={simulator} />
            <SignalInspector simulator={simulator} />
          </>
        )}
        {activeSubTab === 'diagnostics' && <SimulatorDiagnosticsPanel simulator={simulator} />}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Add the route**

In `11_frontend/src/App.tsx`, add the import after the `SystemHealthView` import:

```typescript
import { SimulatorView } from './components/simulator/SimulatorView';
```

and the route inside `ProtectedConsoleLayout`'s block, after the `/system` route:

```tsx
                  {/* HashRouter, so this is #/simulator — the HTTP path stays / and does
                      not collide with the /simulator proxy that reaches the control API. */}
                  <Route path="/simulator" element={<SimulatorView />} />
```

- [ ] **Step 4: Map the path to the tab id — this is the access check**

In `11_frontend/src/components/layout/AppLayout.tsx`, add to `getTabIdFromPath`, after the
`/system` line:

```typescript
    if (path.startsWith('/simulator')) return 'simulator';
```

Without this line the path falls through to the `return 'home'` default, `canAccessTab`
checks `uns_tree`, and every role including `viewer` — which was given
`simulator_ops: false` in Task 12 — reaches the console anyway. The permission would exist
and do nothing.

- [ ] **Step 5: Add the sidebar entry**

In `11_frontend/src/components/layout/Sidebar.tsx`, add `FlaskConical` to the `lucide-react`
import list, then add an entry to `opsNavItems`, between `/system` and `/users`:

```tsx
    {
      to: '/simulator',
      tabId: 'simulator',
      label: 'Simulator Control',
      shortLabel: 'Simulator',
      icon: FlaskConical,
      description: 'Synthetic Plant Data Generator',
      featureKey: 'simulator_ops',
      badge: 'SIM',
    },
```

A static `'SIM'` badge, not the live `run_state` badge spec §7.1 asks for. The sidebar is
rendered on every route, so a live badge needs either a provider above the router — which
spec §7.3 rejects, because the console must not poll a service most users never visit — or a
second poller of its own on every page. `'SIM'` still carries the information the badge is
for: this entry commands synthetic data. The run state is one click away, on the page that
owns it.

`renderNavLink` already reads `canAccessTab(item.tabId)` and renders a lock for a role that
lacks the feature, so a viewer sees the entry disabled rather than missing. That is the
existing pattern for every other tab and the reason nothing else here needs changing.

- [ ] **Step 6: Correct the claim at the top of `App.tsx`**

`11_frontend/src/App.tsx:4` says the console communicates exclusively with
`07_uns_graphql`. After Step 3 that is false, and it is in the header comment of the file a
newcomer opens first. Spec §7.1 calls for fixing it. Replace that line with:

```typescript
 * Communicates with 07_uns_graphql for all platform data, and — only on the /simulator
 * route — directly with 99_simulator's control API. See docs/adr/0007.
```

Keep the surrounding comment lines as they are; this is a one-line correction, not a
rewrite.

- [ ] **Step 7: Verify**

```bash
cd 11_frontend && npm run lint && npm run build
```

Expected: both pass. Then, with the stack from Task 9 running:

```bash
cd 11_frontend && npm run dev
```

Open `http://localhost:5173/#/simulator` and check, in this order:
1. The run state chip reads `running` and the message counters climb.
2. Configuration lists the profiles from `conf/simulator/`.
3. Plant & Signals shows PackML states that change over a minute or two.
4. Diagnostics shows `Connected: YES` and the Platform Observability feed fills within ten
   seconds.
5. Switch to the `viewer` role from the login portal: the sidebar entry shows a lock and
   the route renders `AccessRestricted`.
6. Switch to `operator`: the page renders, and every button and input is disabled with a
   Read-Only Mode chip.

- [ ] **Step 8: Commit**

```bash
git add 11_frontend/src/components/simulator/ 11_frontend/src/App.tsx 11_frontend/src/components/layout/AppLayout.tsx 11_frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(frontend): add the /simulator console route with diagnostics and RBAC"
```

---

## Task 17: Write down why it is built this way

Spec §11. The ADR, both READMEs, and the checklist that verifies the whole thing by hand.

The ADR is the part that matters in a year. This platform's write path is GraphQL — every
other mutation in the console goes through `07_uns_graphql` — and this feature deliberately
does not. Somebody will find that and want to fix it, and the argument against needs to be
on record rather than reconstructed.

**Files:**
- Create: `docs/adr/0007-simulator-control-api-outside-graphql.md`
- Modify: `99_simulator/README.md`
- Modify: `11_frontend/README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation only.

- [ ] **Step 1: Write the ADR**

`docs/adr/0007-simulator-control-api-outside-graphql.md`. Follow the format of the existing
ADRs in `docs/adr/` (read `0003-postgres-asset-model-and-read-time-enrichment.md` first for
the house style):

```markdown
# 7. The simulator's control API sits outside GraphQL

Date: 2026-09-01

## Status

Accepted

## Context

The simulator console needs to read live simulator state and write to it: start and stop
the run, switch profiles, change publish intervals, disable a device.

Every other mutation in `11_frontend` goes through `07_uns_graphql`. Doing the same here
would mean the GraphQL server importing `99_simulator`, or reaching it over a network call
it would then wrap. Both make the platform's read API depend on a component that is not
part of the platform: the simulator is a development tool, it is not deployed in
production, and `99_simulator/Dockerfile:41` says so.

There is also a state problem. The values the console needs — run state, per-tier publish
rates, the PackML state of each line — exist only inside the running simulator process, in
memory, changing every tick. A GraphQL resolver would have to ask the simulator for them
anyway. The question is not whether to add a hop, but whether to add two.

## Decision

The simulator serves its own FastAPI control API on port 8099 under `/simulator`, in the
simulation's own event loop. `11_frontend` calls it directly through a proxy path that Vite
serves in development and nginx serves in the container.

The GraphQL schema does not mention the simulator.

Three consequences follow from running the API in the simulation's loop rather than in a
thread or a sidecar process:

- A request handler reads live in-process state. There is one copy of it and one loop
  touching it, so `GET /simulator/status` cannot be stale.
- All writes serialise behind a single `asyncio.Lock`, which is what makes "switch the
  profile" and "change the tier intervals" safe to issue concurrently.
- uvicorn must not install its own signal handlers, or it takes Ctrl-C away from the
  simulation's shutdown path. `main._EmbeddedServer` overrides `capture_signals` to a no-op.

Runtime changes are never written back to `conf/simulator/*.yaml`. `overrides_active` in
the status body says when the running plant has diverged from the files, and a restart
returns to them.

Observability follows the same separation. Prometheus metrics are on 9093, beside the
historian's 9091 and the graph database's 9092. MQTT self-telemetry publishes under
`uns/platform/simulator/<instance>/`, which no mapper subscribes to — enforced by
`99_simulator/test/test_self_telemetry.py`, which reads the real topic lists from
`conf/settings.yaml` and matches them against the telemetry topics with an MQTT wildcard
matcher.

## Consequences

**Good.** `07_uns_graphql` stays free of a development-only dependency. The console's
numbers come from the process that owns them. The simulator can be removed from a
deployment and the console degrades to an "offline" banner instead of a broken schema.

**Bad.** `11_frontend` now talks to two backends, so both `vite.config.ts` and `nginx.conf`
need a proxy entry, and a missing one produces `index.html` with a 200 status rather than a
clear failure. Authentication is a shared bearer token
(`simulator.api.token`, optional and unset by default) rather than the console's RBAC —
the API has no user identity, so `simulator_control` is enforced in the browser only.
Anyone who can reach port 8099 can command the simulator, which is why neither 8099 nor 9093
is published to the host in `docker-compose.yml` — the mapping is present but commented out,
to be uncommented deliberately on a development machine.

**Neutral.** A future production-grade control plane would move this behind GraphQL with
real authorization. Nothing here prevents that: the console talks to one client module
(`src/services/simulator/client.ts`), so the transport is replaceable in one file.
```

Check the actual next free ADR number before committing — plan A adds 0006, so 0007 is
correct only if plan A landed first, as its prerequisite note requires.

- [ ] **Step 2: Document the API in the simulator's README**

Append to `99_simulator/README.md`:

```markdown
## Control API

The simulator serves a FastAPI control API on port 8099 (`applications.simulator.api_port`)
in the simulation's own event loop, so every handler reads live in-process state.

Interactive docs: `http://localhost:8099/simulator/docs` — reachable when the simulator runs
directly (`uv run uns_simulator`). Under Docker Compose, `uns_simulator`'s `ports:` block is
commented out on purpose; uncomment it to reach 8099 from the host. The console does not
need it, because nginx proxies `/simulator` inside the compose network.

| Method | Path | Purpose |
|---|---|---|
| GET | `/simulator/health` | Liveness, uptime, git hash, version |
| GET | `/simulator/status` | Run state, counters, publish rates, `overrides_active` |
| GET | `/simulator/config` | Profile, available profiles, hierarchy, tiers, families, devices |
| GET | `/simulator/plant` | PackML state and production rate per line, per site |
| GET | `/simulator/devices` | Device inventory with per-device publish counters |
| GET | `/simulator/devices/{id}/signals` | Current value, Unit of Measure, tier and topic per signal |
| GET | `/simulator/diagnostics` | What the profile expanded to, unmatched templates, failing devices, sample topics |
| POST | `/simulator/run` | `{"action": "start" \| "pause" \| "resume" \| "stop"}` |
| PUT | `/simulator/profile` | `{"profile": "...", "seed": 42}` — rebuilds the plant, resets counters |
| PUT | `/simulator/tiers` | Seconds between publishes, per tier |
| PUT | `/simulator/families` | Enable or disable a sensor family |
| PUT | `/simulator/devices/{id}` | `{"enabled": false}` |

Every write returns the `/status` body, so a caller never has to poll to find out what
changed.

**Pause keeps the plant moving.** It cancels the publish tasks and leaves the clock running,
so PackML states keep advancing and resuming does not restart the plant from Idle.

**Nothing is written back to `conf/simulator/`.** `overrides_active` in the status body is
true once the running plant has diverged from the files on disk; a restart returns to them.

### Authentication

Set `simulator.api.token` in `conf/.secrets.yaml` to require an `X-Simulator-Token` header.
Unset by default, which is right for a development tool on a development network and wrong
for anything else — the API has no user identity and anyone who can reach port 8099 can
stop the simulator.

### Observability

- **Prometheus** on port 9093, scraped by `08_uns_observability/prometheus/prometheus.yml`:
  - `uns_simulator_messages_published_total{tier,family}` (counter)
  - `uns_simulator_publish_failures_total{device}` (counter)
  - `uns_simulator_reconnects_total{device}` (counter)
  - `uns_simulator_devices_connected` (gauge)
  - `uns_simulator_signal_value{device,signal}` (gauge) — only for signals whose profile
    sets `export_metric: true`. Exporting every signal would put the plant's whole state
    into Prometheus, which is the historian's job and not a metric.
- **MQTT self-telemetry** under `uns/platform/simulator/<instance>/`:
  `status` every ten seconds, `plant/<site>/<line>/state` on each PackML transition, and
  `device/<id>/health` on change. All retained, with a Last Will on `status` so the topic
  reads `offline` if the process is killed.

This prefix is Platform Observability, not plant data. No mapper subscribes to it, so none
of it is persisted as though a machine had measured it. `test/test_self_telemetry.py`
enforces that against the real topic lists in `conf/settings.yaml`.
```

- [ ] **Step 3: Document the console route in the frontend README**

Append to `11_frontend/README.md`:

```markdown
## Simulator Console (`#/simulator`)

Four sub-tabs over `99_simulator`'s control API: Status & Run Control, Configuration,
Plant & Signals, Diagnostics.

This is the one route that does not talk to `07_uns_graphql`. It calls the simulator
directly through a `/simulator` proxy path — `vite.config.ts` in development,
`nginx.conf` in the container. Both are required; a missing entry answers with
`index.html` and a 200 status, which looks like a JSON parse bug rather than a routing one.
See `docs/adr/0007-simulator-control-api-outside-graphql.md`.

**Permissions.** `simulator_ops` to see the page, `simulator_control` to change anything.
Operators and auditors get the first and not the second, so they see whether the data they
are looking at is simulated without being able to alter it. Enforcement is in the browser
only — the control API has no user identity.

**Where the numbers come from.** `useSimulator()` polls `GET /simulator/status` and
`GET /simulator/plant` every two seconds, and that is the single source for everything
rendered. The `uns/platform/simulator/#` MQTT subscription feeds only the diagnostics event
list: a retained message from a dead process looks identical to a current one, so it is not
allowed to drive a status display.

**When no simulator is running** the page shows an offline banner and keeps the last values
it read. That is a normal state — the simulator is optional and is not deployed in
production.
```

- [ ] **Step 4: Verify the docs against the code**

Read back each table row and each topic against Tasks 6-8. A README that lists an endpoint
the API does not serve is worse than no README, because it gets believed.

```bash
cd 99_simulator && uv run pytest -q
cd ../11_frontend && npm run lint && npm run build
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0007-simulator-control-api-outside-graphql.md 99_simulator/README.md 11_frontend/README.md
git commit -m "docs: record the simulator control API decision and document the console"
```

---

## Manual Verification

Run all six against a full stack after Task 17. Each one is here because it fails
differently from the automated tests, and four of them cannot be caught by a unit test at
all.

Checks 1 and 3 curl 8099 from the host, so uncomment `uns_simulator`'s `ports:` block
(Task 9, Step 6) before bringing the stack up, and comment it back out afterwards. Nothing
the console itself does needs it — the browser only ever talks to 8088, and nginx reaches
8099 inside the compose network.

```bash
docker compose up -d --build
```

- [ ] **1. The API answers, and the console reaches it both ways.**

```bash
curl -s http://localhost:8099/simulator/status
curl -s http://localhost:8088/simulator/status
```

Both return the same JSON. The second goes through nginx, which is the one that breaks when
`uns_frontend` starts before `uns_simulator` resolves. Then open
`http://localhost:8088/#/simulator` and confirm the counters climb.

- [ ] **2. Pause keeps the plant moving.**

Pause from the console. Watch Plant & Signals for a minute: `time_in_state_s` keeps rising
and PackML states still change, while `msg_per_sec` goes to zero and `published_total`
stops. Resume: publishing continues from the state the plant reached, not from Idle. This
is the behaviour most likely to be quietly broken by a refactor and no test can prove the
clock is *still* running as convincingly as watching it.

- [ ] **3. A rejected profile switch leaves the running plant alone.**

```bash
curl -s -X PUT http://localhost:8099/simulator/profile \
  -H 'Content-Type: application/json' -d '{"profile":"no-such-profile"}'
```

Returns 422 with `{"detail": {"field": "profile", ...}}`. The console shows the message
beside the field, `run_state` is still `running`, and `published_total` has not reset.

Sending `{"name":"small"}` instead is a useful second check: `ProfileRequest` forbids extra
fields, so it answers 422 naming `name` rather than switching to a profile that exists.

- [ ] **4. The simulator's telemetry is not in the Unified Namespace.**

```bash
docker compose exec uns_mqtt_broker mosquitto_sub -t 'uns/platform/simulator/#' -C 3 -v
```

Three retained messages. Then check the historian:

```sql
SELECT count(*) FROM unifiednamespace WHERE topic LIKE 'uns/platform/%';
```

Zero. The test in Task 8 proves no mapper *subscribes*; this proves nothing *arrived*.

- [ ] **5. The Last Will fires.**

```bash
docker kill uns_simulator
docker compose exec uns_mqtt_broker mosquitto_sub -t 'uns/platform/simulator/+/status' -C 1 -v
```

The retained payload reads `"run_state": "offline"`. Reload the console: the offline banner
appears and the last known values are still on screen. Then `docker compose up -d
uns_simulator`. Nothing but a real kill exercises this path.

- [ ] **6. Both roles behave.**

Log in as `viewer`: the sidebar shows a locked Simulator entry and `#/simulator` renders
`AccessRestricted`. Log in as `operator`: the page renders fully, every button and input is
disabled, and the Read-Only Mode chip is visible. This is the check that the tab-id mapping
in `AppLayout.getTabIdFromPath` is present — without it the viewer gets in.

```bash
docker compose down
```

