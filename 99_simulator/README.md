# UNS Simulator (99_simulator)

A lightweight MQTT device simulator used to generate synthetic device data for the Unified Namespace (UNS) project. Use this module to exercise MQTT consumers (graphdb, historian, Kafka bridge, SparkplugB mappers, etc.) with configurable device/metric payloads.

Features

- Configurable device templates and randomized metric values
- Publishes messages to MQTT broker(s) using settings from the repository-root [`conf/settings.yaml`](../conf/settings.yaml)
- Docker Compose service (`uns_simulator`) so it starts the same way on every OS
- Optional local CLI for development
- Unit tests under test/

Repository layout

- Platform config lives at the repository root, not in this module:
  - [`../conf/settings.yaml`](../conf/settings.yaml) — shared settings; simulator overrides are under the Dynaconf `simulator` environment
  - [`../conf/.secrets_template.yaml`](../conf/.secrets_template.yaml) — template for secrets
- src/uns_simulator/
  - config.py — configuration loader ([src/uns_simulator/config.py](src/uns_simulator/config.py))
  - devices.py — device template / helper functions ([src/uns_simulator/devices.py](src/uns_simulator/devices.py))
  - models.py — data models used by the simulator ([src/uns_simulator/models.py](src/uns_simulator/models.py))
  - simulator.py — core simulator implementation ([src/uns_simulator/simulator.py](src/uns_simulator/simulator.py))
  - main.py — CLI / entrypoint ([src/uns_simulator/main.py](src/uns_simulator/main.py))
  - signals.py — the ten signal shapes and their status derivation ([src/uns_simulator/signals.py](src/uns_simulator/signals.py))
  - expressions.py — the whitelisted expression evaluator used by `derived` and `counter` ([src/uns_simulator/expressions.py](src/uns_simulator/expressions.py))
  - plant.py — PackML line state, site ambient conditions, the plant clock ([src/uns_simulator/plant.py](src/uns_simulator/plant.py))
  - profiles.py — device targeting, profile resolution, the conf/simulator reader ([src/uns_simulator/profiles.py](src/uns_simulator/profiles.py))
- Dockerfile — container image, same pattern as the other Python UNS services
- test/ — unit tests ([test/](test/))

## The plant model

The simulator is not a set of independent random generators. One `PlantClock` ticks every
second and drives a `PlantContext`: per site, ambient temperature, humidity, wet bulb, wind
and barometric pressure, plus the shift and the electricity tariff period; per production
line, a PackML state machine that only ever takes legal transitions, and the production
rate, throughput, heat load and air demand that follow from it.

Devices read that context. A compressor's load follows the air demand of the lines it
`serves`; a boiler's steam flow follows their heat load, but through a first-order lag, so
it trails a line stop by minutes while the compressors react in seconds. The cooling tower
sizes its approach temperature against the wet bulb the weather station publishes — the same
number, not a second model of it — so a warm humid stretch shows up as a hotter tower supply
**and** a higher chiller kW.

That is the point of the whole design: values that move together for a reason, so a consumer
built against this data behaves like one built against a plant.

### Profiles

`conf/simulator/plant.yaml` declares the whole plant; a profile narrows it. Select one with
`simulator.simulation.profile` in `conf/settings.yaml`.

| Profile | Sites | Families | Devices | Rate |
|---|---|---|---|---|
| `small` (default) | Dormagen, first cell per line | energy, water, production | 11 | ~2 msg/s |
| `full` | Dormagen, Krefeld | all six | 55 | ~120 msg/s |

`small` is the default because the graphdb mapper performs `MERGE` work once per topic level
on **every** message, and eight-level topics at `full` rate are a heavy sustained write load
on Neo4j. The historian only appends, so it is not the constraint. `test/test_volume.py`
enforces the default: a family added to the wrong profile fails a test rather than a mapper.

A profile also carries `tier_scale`, which multiplies every cadence interval — `small` uses
6.0, so its 5 s process tier publishes every 30 s.

### Cadence tiers

Every signal belongs to a tier, and the tier decides how often it publishes. Intervals are
configurable under `simulator.simulation.tiers`.

| Tier | Interval | What is on it |
|---|---|---|
| `fast` | 1 s | vibration, motor current |
| `process` | 5 s | temperatures, pressures, flows, levels, analysers |
| `energy` | 15 s | power, power factor, per-phase voltage and current |
| `status` | 30 s | PackML state, equipment status, SIS status |
| `meter` | 900 s | cumulative kWh, m³, Nm³ and tonne registers |
| `lab` | 1800 s | LIMS sample results |
| `event` | on change | alarms, trips, detector faults |

Evaluation and publishing are separate. Every signal is evaluated on every one-second tick
regardless of tier, so a 15-minute meter register has integrated all 900 seconds rather than
sampling 900 seconds apart. The tier controls publishing only.

### Signal shapes

| Shape | Behaviour | Key parameters |
|---|---|---|
| `noise` (default) | Gaussian around `base_value` | `base_value`, `variation` |
| `constant` | A fixed value | `value` |
| `ou_walk` | Mean-reverting random walk; drifts and returns | `mean`, `sigma`, `tau` |
| `diurnal` | Sine over `period_s`, plus optional noise | `mean`, `amplitude`, `period_s`, `phase_s` |
| `sawtooth` | Fills to `high`, drains to `low`, independent rates | `low`, `high`, `fill_rate`, `drain_rate` |
| `counter` | Monotonic register; `rate` is an expression in units per second | `rate`, `initial`, `rollover` |
| `window_agg` | Rolling min/max/mean of a **sibling** over `window_s` | `source`, `window_s`, `agg` |
| `derived` | An expression over siblings and `ctx` | `expr`, `params` |
| `stepped` | A discrete: mirrored from a `ctx` path, or drawn from `choices` | `source`, `choices`, `map`, `weights`, `dwell_s` |
| `bernoulli_event` | With probability `p` per tick, emit one of `choices` | `p`, `choices` |

`derived` and `counter.rate` take arithmetic over sibling signal names, keys of the signal's
own `params`, and `ctx.*`. Permitted calls are `min`, `max`, `abs`, `round`, `clamp`, `sqrt`
and `exp`. It is a whitelisted AST walk, never `eval`: attribute access off anything but
`ctx`, subscripts, lambdas, comprehensions and imports are all rejected when the file loads,
and a reference cycle between `derived` signals is rejected the same way.

`unit` is required on every signal. A dimensionless ratio declares `unit: "1"` rather than
omitting the key, so an omission is always a mistake and never a choice.

### Adding a device

1. Pick the family file in `conf/simulator/` — or add a family name to `FAMILIES` in
   `profiles.py` and create the file.
2. Add an entry under `devices:` with `id`, `equipment`, a `target`, a `tier`, and `signals`.
   An absent `target` means every cell in a `kind: production` area.
3. If it should follow production, give it `serves: [Site/Area/Line, ...]` and read
   `ctx.served_*` in its expressions. `served_throughput_tph`, `served_heat_load` and
   `served_air_demand` are **sums** over the served lines, so divide by a `served_lines`
   parameter if the device should behave the same at a one-line site as at a two-line one.
4. Update `EXPECTED_SIGNAL_COUNT` and `EXPECTED_DEVICE_COUNT` in `test/test_conf_files.py`.
   Those tables are per template, so the suite's totals are derived from them rather than
   asserted, and a device that fails to resolve names itself in the failure.

Quick start (Docker Compose)

The simulator is part of the repository-root [`docker-compose.yml`](../docker-compose.yml). From the repository root:

```bash
docker compose up -d --build
```

That starts the MQTT broker **and** the simulator (plus the rest of the local stack). Same command on Windows, macOS, and Linux.

Start or stop **only** the simulator:

```bash
docker compose up -d uns_simulator
docker compose stop uns_simulator
docker compose start uns_simulator
docker compose logs -f uns_simulator
```

`docker compose up -d uns_simulator` also starts `uns_mqtt_broker` when it is not already running (`depends_on`). Compose **profiles** are not used: a profile would hide the simulator from default `docker compose up`.

The Compose service sets `UNS_mqtt__host=uns_mqtt_broker` and `UNS_simulation__duration=0` so the container publishes until you stop it. `duration: 0` means run until stopped; a positive value is minutes.

Build the image on its own (from `99_simulator/`, context is the repo root):

```bash
docker build -t uns/simulator:local --build-arg GIT_HASH=local -f ./Dockerfile ..
```

Quick start (local Python)

Use this only if you are iterating on the simulator code without Docker. Use the single `.venv` at the **repository root** — do not run `uv venv` in this folder.

1. Create the workspace venv from the repository root (see [Setting up the development environment](../README.md#setting-up-the-development-environment)):

   ```bash
   python -m pip install --upgrade pip uv
   uv venv
   uv sync
   ```

2. Configure the simulator
   - Copy [`../conf/.secrets_template.yaml`](../conf/.secrets_template.yaml) to `../conf/.secrets.yaml` and fill any secrets required.
   - Edit [`../conf/settings.yaml`](../conf/settings.yaml) to point to your MQTT broker and tune simulator options (the `simulator` environment).

3. Run locally

   ```bash
   uv run uns_simulator
   ```

   - Point `mqtt.host` at `localhost` (the default) so the process can reach the Compose broker on host port 1883.
   - The module entrypoint is `uns_simulator.main:main`.

Core code pointers

- Entrypoint / CLI: `uns_simulator.main:main`
- Simulator implementation: `uns_simulator.simulator.Simulator`
- Device templates & helpers: `uns_simulator.devices`
- Config loader: `uns_simulator.config`
- Models: `uns_simulator.models`

Configuration notes

- MQTT settings are loaded from the repository-root `conf/settings.yaml` and secrets from `conf/.secrets.yaml` (based on the provided template).
- Typical keys:
  - mqtt.host (required)
  - mqtt.port (default 1883)
  - mqtt.transport ("tcp" or "websockets")
  - simulator.\* — device_count, publish_interval, device templates
  - simulation.duration — minutes to run; **0** means run until stopped (used by the Compose service)

Running tests

- Run unit tests (exclude integration tests):

  ```bash
  uv run pytest -m "not integrationtest" test/
  ```

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
