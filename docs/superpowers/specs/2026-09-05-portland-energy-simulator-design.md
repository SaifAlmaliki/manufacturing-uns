# Plant Portland energy mill (second simulator profile)

Date: 2026-09-05
Modules: `99_simulator`, `conf/simulator/`, `conf/settings.yaml`, `07_uns_graphql`, `09_uns_model`, `11_frontend`
Status: Approved

Companion docs to write during implementation: `99_simulator/ENERGY.md` (what the mill is).

This spec adds a second client plant. It does not replace
[2026-09-04-wtp-simulator-design.md](2026-09-04-wtp-simulator-design.md).
`wtp` stays the default profile. WTP YAML, `WTPProcess`, and `PROCESS.md` stay.

It extends [2026-09-04-admin-hierarchy-yaml-design.md](2026-09-04-admin-hierarchy-yaml-design.md)
with a demo switch that reseeds the Asset Model from a *different* file and drops
the previous client's UNS Nodes. It does not change what `saveHierarchy` writes
(`plant.yaml` only).

## 1. Problem

The simulator publishes one water treatment plant (`AcmeWater` / profile `wtp`).
A second client demo needs Plant Portland: a mill that consumes grid, renewables,
and heater energy. Some loads have Energy PLCs. The rest are allocated from
residuals and configuration ratios.

These are different use cases for different clients. The WTP must remain the
default and must not be rewritten. One plant publishes at a time; the console
switches the profile and then makes current state (graph + Asset Model) look
like that client only.

## 2. Goals

- Profile `wtp` remains the shipped default. Profile `portland` is added.
  `PUT /simulator/profile` accepts both and rebuilds the running plant.
- One plant publishes at a time. After a switch the other MQTT tree goes quiet.
- Portland topics are ingested: mapper lists gain `PlantPortland/#` beside
  `AcmeWater/#`.
- After a successful profile switch, the console calls GraphQL
  `switchDemoPlant`. That drops UNS Nodes under the other plant-file enterprise
  and reloads that profile's Asset Model seed so Explore current state and
  `/hierarchy` look like one client. Historian keeps old series. Access Groups
  are not rewritten.
- Measured vs allocated is the equipment class (`Energy_Meter` /
  `Energy_Allocated`). Every published energy device has `PV` (kW) and
  `Totalizer` (kWh).
- Users can read what Portland is without reading Python: `99_simulator/ENERGY.md`.

## 3. Non-goals

- Two plants publishing at once, or two Compose services.
- A generic allocation engine or YAML formula language.
- Historian purge or prefix-migrate of the previous client (that would rename
  AcmeWater into PlantPortland).
- Rewriting Access Groups, OEE, Sparkplug, or `platform.organization_name`.
- Physics of the battery (charge state). Storage output is a measured walk.
- MQTT commands or API writes to Portland tags.
- A hierarchy editor for the Portland seed. `saveHierarchy` still writes
  `plant.yaml` only.
- Publishing allocation intermediates (plant total, hot untracked, ratio
  setpoints) as topics.

## 4. Architecture

Keep the three-layer split from ADR 0006: signal math, plant state, MQTT
transport. Add a second process class. Do not generalize `WTPProcess`.

| Piece | Role |
|---|---|
| `PortlandProcess` (new module, e.g. `portland.py`) | Walks, machine on/off, residual allocation. Signals only read it. |
| `conf/simulator/portland-plant.yaml` | Portland ISA-95 tree + `profiles.portland`. |
| `conf/simulator/portland.yaml` | 19 device templates, family `portland`. |
| `conf/simulator/plant.yaml` + `wtp.yaml` | Unchanged WTP seed. |
| `profiles.py` | Families `wtp` and `portland`. Each profile is bound to the hierarchy file it was declared in. |
| Simulator control API | `available_profiles: ["portland", "wtp"]`. Plant snapshot is WTP-shaped or Portland-shaped. |
| GraphQL `switchDemoPlant` | Drop UNS Nodes under the other plant-file enterprise; `apply_plan` from the chosen seed. |
| Simulator console | `PUT /simulator/profile`, then `switchDemoPlant`. Simulator never talks to Neo4j or Postgres. |

Data flow (Portland):

```
portland-plant.yaml + portland.yaml
        → profiles.py → DeviceSpec[] + PortlandProcess
        → PlantClock.tick(1 s) advances PortlandProcess
        → SignalDevice.evaluate reads ctx.portland.*
        → publish_tier writes MQTT
```

`DeviceView.portland` is the running `PortlandProcess`. YAML uses paths such as
`ctx.portland.grid_kw` and `ctx.portland.roughing.running`.

`SiteState` today always constructs `WTPProcess`. The profile's process class
decides: `wtp` → `WTPProcess` on `site.wtp`; `portland` → `PortlandProcess` on
`site.portland`. A site never holds both.

Two seams, one demo: the Portland publisher, and the console-orchestrated graph
+ Asset Model swap. Implementation may land the publisher first.

### 4.1 Profile files (do not put `portland` in `plant.yaml`)

`save_plant_tree` rewrites `plant.yaml` and only preserves `profiles.wtp`. A
`profiles.portland` block in that file would be stripped on the next hierarchy
save.

- `plant.yaml` — AcmeWater tree + `profiles.wtp` only.
- `portland-plant.yaml` — PlantPortland tree + `profiles.portland` only.

`read_simulator_conf` / `load_profile` unions `profiles` keys from `plant.yaml`
and every `*-plant.yaml` (or specifically `portland-plant.yaml`). Each profile
loads **only** the hierarchy document it was found in. Do not merge the two
enterprises' `sites` (both are named `Site1`).

`available_profiles` is the sorted union of those keys.

## 5. Topic shape

Eight levels, unchanged depth:

`{enterprise}/{site}/{area}/{line}/{cell}/{equipment}/{param_type}/{signal}`

| Level | Value |
|---|---|
| enterprise | `PlantPortland` |
| site | `Site1` |
| area | `Sources` · `Metering` · `ColdLocation` · `HotLocation` |
| line | `Mill1` |
| cell | instance tag (`GridInput`, `RoughingMill`, …) |
| equipment | `Energy_Meter` or `Energy_Allocated` |
| param_type | `ProcessValue` |
| signal | `PV` or `Totalizer` |

Examples:

```
PlantPortland/Site1/Sources/Mill1/GridInput/Energy_Meter/ProcessValue/PV
PlantPortland/Site1/Metering/Mill1/SharedEnergyMeter/Energy_Meter/ProcessValue/Totalizer
PlantPortland/Site1/HotLocation/Mill1/FurnaceHotLine/Energy_Allocated/ProcessValue/PV
```

Cell is the tag **once**. Equipment is the class. Do not repeat the tag as
`GridInput/GridInput`.

`PV` unit is `kW`, tier `energy` (15 s — already declared in settings, unused by
WTP). `Totalizer` unit is `kWh`, tier `meter` (900 s). Do not publish `Origin`,
`Running`, or `Fault` in this slice. Class is the measured-vs-allocated mark.

Boolean values are not used on these two signals. `unit` is required.

## 6. Device map

Nineteen devices. Intermediates listed in section 7.3 are not devices.

| Area | Cell | Equipment | Independent? |
|---|---|---|---|
| Sources | GridInput | Energy_Meter | walk |
| Sources | WindSystem | Energy_Meter | walk |
| Sources | SolarSystem | Energy_Meter | diurnal |
| Sources | EnergyStorage | Energy_Meter | walk (output) |
| Sources | HeaterSystem | Energy_Meter | walk |
| Metering | SharedEnergyMeter | Energy_Meter | `Grid + Storage` |
| Metering | InhouseEnergyMeter | Energy_Meter | `= Heater` |
| ColdLocation | ColdLocationTotal | Energy_Allocated | residual |
| ColdLocation | ColdAirConditioning | Energy_Allocated | residual share |
| ColdLocation | ColdHeater | Energy_Meter | walk |
| ColdLocation | ColdLighting | Energy_Meter | walk |
| ColdLocation | FurnaceColdLine | Energy_Meter | walk when on |
| ColdLocation | ColdMillScaleCleaner | Energy_Allocated | residual share |
| HotLocation | HotLocationTotal | Energy_Allocated | `SharedHot + Inhouse` |
| HotLocation | RoughingMill | Energy_Meter | walk when on |
| HotLocation | FurnaceHotLine | Energy_Allocated | ratio |
| HotLocation | HotMillScaleCleaner | Energy_Allocated | ratio |
| HotLocation | HotAirConditioning | Energy_Allocated | ratio |
| HotLocation | HotLighting | Energy_Allocated | ratio |

Cadence:

| Tier | Interval | What |
|---|---|---|
| energy | 15 s | `PV` |
| meter | 900 s | `Totalizer` |

One profile `portland`, `tier_scale: 1.0`, sites `[Site1]`, families `[portland]`.

## 7. Process model

`PortlandProcess` owns walks, machine dwell, residuals, and totalizers. Signals
never mutate it.

### 7.1 Balance (every tick, after clamps)

```
SharedMeter     = Grid + Storage
InhouseMeter    = Heater
PlantTotal      = Grid + Storage + Heater          # snapshot only
HotTotal        = SharedHot + InhouseMeter
ColdTotal       = PlantTotal − HotTotal            # = SharedMeter − SharedHot
```

Wind and solar **publish** and **do not** enter `PlantTotal`. They sit upstream
of storage, as on the drawing. Storage output may disagree with wind+solar;
that is the buffer, not a bug. There is no state of charge.

`SharedHot` is process state (nameplate 200 kW). It is not a topic.

### 7.2 Independent walks

Nameplate is the walk mean, not a fixed publish. Units kW.

| State | Shape | Nameplate |
|---|---|---|
| Grid | OU | 1000 |
| Wind | OU | 800 |
| Solar | diurnal | 200 peak, ~0 at night |
| Storage out | OU, clamped ≥ 0 | 400 |
| Heater | OU | 600 |
| SharedHot | OU, clamped to `[0, SharedMeter]` | 200 |
| ColdHeater | OU | 100 |
| ColdLighting | OU | 150 |
| FurnaceColdLine | OU when on, idle ~10 when off | 380 |
| RoughingMill | OU when on, idle ~10 when off | 333 |

Furnace Cold Line and Roughing Mill cycle with a dwell (on for minutes, off for
minutes). Allocated leaves do not cycle; they follow the residual.

If Roughing > HotTotal this tick, clamp Roughing to HotTotal.

### 7.3 Hot allocation (config ratios, not topics)

Ratios live under `plant:` in `portland-plant.yaml` (or a `ratios:` block in
`portland.yaml`). They are not MQTT signals.

```
HotUntracked     = max(0, HotTotal − RoughingMill)
HotSharedSources = HotUntracked × 2/3
HotMachinesRest  = HotUntracked × 1/3
HotAirConditioning     = HotSharedSources × 2/3
HotLighting            = HotSharedSources × 1/3
FurnaceHotLine         = HotMachinesRest × 2/3
HotMillScaleCleaner    = HotMachinesRest × 1/3
```

When the roughing mill stops, `HotUntracked` rises and the four allocated hot
leaves rise with it.

### 7.4 Cold allocation

Measured cold leaves are truth. The hall residual is the rest, split by config
ratios that **must sum to 1**. Load-time error if they do not.

Poster defaults so both unmetered leaves are visible (not the drawing's
`r_cleaner = 1`, which would leave Cold AC at 0 kW forever):

```
ColdMeasured   = ColdHeater + ColdLighting + FurnaceColdLine
ColdUntracked  = max(0, ColdTotal − ColdMeasured)
ColdAirConditioning      = ColdUntracked × r_ac        # default 170/570
ColdMillScaleCleaner     = ColdUntracked × r_cleaner   # default 400/570
```

If measured cold exceeds `ColdTotal`, untracked is 0 and allocated cold leaves
are 0. Hall total still follows section 7.1; the hall will not equal the sum of
leaves on that tick.

### 7.5 Totalizers

Each tick: `Totalizer += PV_kW × dt / 3600` (kWh). Allocated meters integrate
allocated kW. No rollover in this slice.

## 8. Control API and console

Routes stay. Profile list widens.

| Endpoint | Change |
|---|---|
| `GET /simulator/plant` | WTP body (section 8.1 of the WTP spec) **or** Portland body (8.1 below). |
| `PUT /simulator/profile` | `wtp` or `portland`. Any other name is 422 `field: profile`. |
| `PUT /simulator/families` | Fields `wtp` and `portland`. |
| `GET /simulator/config` | `available_profiles: ["portland", "wtp"]`. |

Pause still advances the process and stops publishing.

Default `simulator.simulation.profile` in `settings.yaml` stays `wtp`. A process
restart returns to the file, not to the last switched profile.

### 8.1 `GET /simulator/plant` body (Portland)

```json
{
  "enterprise": "PlantPortland",
  "site": "Site1",
  "plant_total_kw": 2000.0,
  "shared_meter_kw": 1400.0,
  "inhouse_meter_kw": 600.0,
  "shared_hot_kw": 200.0,
  "hot_total_kw": 800.0,
  "cold_total_kw": 1200.0,
  "hot_untracked_kw": 467.0,
  "hot_shared_sources_kw": 311.3,
  "hot_machines_rest_kw": 155.7,
  "machines_on": ["FurnaceColdLine", "RoughingMill"],
  "leaves_kw": {
    "GridInput": 1000.0,
    "WindSystem": 800.0,
    "SolarSystem": 200.0,
    "EnergyStorage": 400.0,
    "HeaterSystem": 600.0,
    "ColdAirConditioning": 170.0,
    "ColdHeater": 100.0,
    "ColdLighting": 150.0,
    "FurnaceColdLine": 380.0,
    "ColdMillScaleCleaner": 400.0,
    "RoughingMill": 333.0,
    "FurnaceHotLine": 103.8,
    "HotMillScaleCleaner": 51.9,
    "HotAirConditioning": 207.6,
    "HotLighting": 103.8
  }
}
```

No `tanks`, `filter_mode`, `duty_raw_pump`, or `flows_m3h`. Frontend branches on
`tanks` (WTP) vs `plant_total_kw` (Portland).

### 8.2 Console orchestration

The profile picker in `SimulatorConfigPanel` already lists `available_profiles`.

Strict order:

1. `PUT /simulator/profile` with the new name.
2. Only if that succeeds: GraphQL `switchDemoPlant(profile:)`.
3. If step 2 fails: MQTT is already the new plant; Asset Model and graph are
   still the old client. Banner + **Retry swap** (step 2 only). Do not call
   `PUT /profile` again on Retry.

Simulator writes stay on the existing token / `simulator_control` browser gate.
`switchDemoPlant` is `admin` (same gate as `saveHierarchy`).

### 8.3 Frontend inspector

Same `PlantStateInspector` card, two bodies. WTP: tanks, duty pump, filter
mode, flows (unchanged). Portland: plant / cold / hot kW, grid, storage,
heater, `machines_on`.

### 8.4 Self-telemetry

`uns/platform/simulator/<instance>/` is unchanged as a prefix. Plant events may
fire on machine on/off (`plant/Site1/Mill1/state`). Prefix still must not match
mapper filters.

## 9. `switchDemoPlant` and `saveHierarchy`

### 9.1 `switchDemoPlant(profile: String!)`

`profile` is `wtp` or `portland`. Anything else is a GraphQL error.

| Step | Does | Does not |
|---|---|---|
| Load seed | `wtp` → `conf/simulator/plant.yaml`; `portland` → `conf/simulator/portland-plant.yaml` | Write either file |
| Target enterprise | The seed file's `enterprise` (`AcmeWater` or `PlantPortland`) | Guess from MQTT |
| Asset Model | `apply_plan` from that tree (prunes the other client) | Touch Access Groups |
| Graph | `DETACH DELETE` UNS Nodes under every **other** enterprise declared in `plant.yaml` / `*-plant.yaml` (reuse the prefix walker `saveHierarchy` migrate already uses; delete, do not rename) | Prefix-migrate; delete the target enterprise |
| Historian | Leave series in place | Delete or rename topics |
| Settings | Leave `organization_name` | Rewrite branding |

Retry after a Postgres-success / Neo4j-failure is the same mutation: `apply_plan` is
idempotent, and the graph delete key is “enterprises in the plant files except the
target,” not “whatever Postgres currently says.” That still removes leftover
AcmeWater nodes after a Portland reseed.

Mapper topic lists are **static** in `conf/settings.yaml`: add `PlantPortland/#`
beside `AcmeWater/#` (keep `test/uns/#` and Sparkplug entries). Both stay
subscribed so a switch does not need a mapper bounce.

If Neo4j fails after Postgres `apply_plan` commits, Retry re-runs the whole
mutation. `apply_plan` is idempotent.

### 9.2 `saveHierarchy` guard

`saveHierarchy` still writes `plant.yaml` only and still derives branding from
the submitted WTP tree.

While the live Asset Model enterprise is `PlantPortland`, `saveHierarchy`
returns 409. The hierarchy editor is for the WTP seed. Switch back to `wtp` to
edit Acme Water. Portland's tree is file-authored this slice.

When `saveHierarchy` derives mapper `mqtt.topics` from the WTP enterprise, it
must **keep** `PlantPortland/#` (union of enterprises declared in `plant.yaml`
and `portland-plant.yaml`, plus `test/uns/#` and Sparkplug). A WTP save must
not drop the Portland filter.

Hand edits to the live Asset Model are discarded on the next
`switchDemoPlant`. Always reload that profile's seed.

### 9.3 Access Groups

Left as they are. Demo as admin, or re-point roots by hand after a switch.
Seeded groups that name `AcmeWater/…` will not cover `PlantPortland/…`.

## 10. Platform config so the UNS sees Portland

In `conf/settings.yaml`:

- `simulator.simulation.profile` stays `wtp`.
- Mapper `mqtt.topics` (graphdb, historian, kafka) include `PlantPortland/#`
  next to `AcmeWater/#`.
- Fallback `simulator.hierarchy` stays AcmeWater (used only if `plant.yaml` is
  absent). Do not point it at PlantPortland.

OEE `conf/oee/units.yaml` stays WTP/Covestro. Leave it. Portland has no OEE
unit.

## 11. Documentation

- **`99_simulator/ENERGY.md`** (required): four-area narrative; tag table from
  section 6; residual rules in operator language; one example topic per class;
  explicit "not modelled" list (SOC, commands, intermediates as topics,
  Running/Fault).
- **`99_simulator/README.md`**: two profiles; WTP is default; point at
  `PROCESS.md` and `ENERGY.md`.
- **`portland.yaml` / `portland-plant.yaml` headers**: one short paragraph and
  a link to `ENERGY.md`.
- **`PROCESS.md`**: optional one-line sister-plant pointer to `ENERGY.md` /
  profile `portland`. Do not rewrite the WTP narrative.

## 12. Testing

WTP tests stay. Do not delete WTP fixtures.

### 12.1 Simulator

- Profile `portland` loads 19 devices; every topic prefix is
  `PlantPortland/Site1/<Area>/Mill1/<Cell>/Energy_Meter` or `Energy_Allocated`.
- `wtp` inventory, topics, and `PROCESS.md` path assertion stay green.
- Unknown profile still 422. Default profile is `wtp`.
- Balance: `ColdTotal + HotTotal = PlantTotal`,
  `PlantTotal = Grid + Storage + Heater`, `SharedMeter = Grid + Storage`.
  Wind + solar do not enter `PlantTotal`.
- Roughing mill off → `HotUntracked` rises and the four allocated hot leaves
  rise.
- Measured cold > `ColdTotal` → allocated cold leaves are 0.
- Totalizer increases by `PV * dt / 3600`.
- `GET /simulator/plant` on Portland has no `tanks`; on WTP has no
  `hot_untracked`.
- `ENERGY.md` exists (path assertion).
- `r_ac + r_cleaner ≠ 1` is a load-time error naming the key.

### 12.2 Volume

`test_volume.py` still asserts the shipped default is `wtp` and that default's
rate. Portland is opt-in (~19 × (1/15 + 1/900) ≈ 1.3 msg/s). A Portland rate
assertion may exist; it must not change the default.

### 12.3 Platform

- `switchDemoPlant("portland")` reseeds Asset Model to `PlantPortland/…`;
  AcmeWater assets are gone.
- Graph has no UNS Nodes under the other plant-file enterprise after the swap
  (AcmeWater gone after Portland, and the reverse). A second call with the same
  profile is idempotent and does not delete the target enterprise's nodes.
- Historian still has rows for the previous enterprise (fixture).
- `switchDemoPlant` does not write `plant.yaml` or `portland-plant.yaml`.
- `saveHierarchy` is 409 while live enterprise is `PlantPortland`.
- `saveHierarchy` on a WTP tree keeps `PlantPortland/#` in mapper topic lists.
- Mapper topic lists include both `AcmeWater/#` and `PlantPortland/#`.
  Self-telemetry still matches neither.
- Access Groups untouched.
- Mutation is admin-only.

### 12.4 Frontend

- Profile picker shows `portland` and `wtp`.
- Inspector renders energy KPIs for a Portland snapshot and tanks for a WTP
  snapshot.
- Failed `switchDemoPlant` after a successful profile PUT shows Retry and does
  not call `PUT /profile` again.

## 13. Error handling

Load-time (fatal, named key): missing `unit`, unknown template target, unknown
`ctx` path used by a `derived`/`stepped` signal, signal cycles, unknown profile
name, missing hierarchy file for the profile, `r_ac + r_cleaner ≠ 1`.

Run-time: a `derived` eval failure still yields `None` for that signal; the
device keeps publishing siblings. Allocation clamps never raise.

`switchDemoPlant` failures are GraphQL errors. The console Retry path is
section 8.2.

## 14. Out of scope (repeat)

Two live plants; generic allocation engine; historian purge; Access Group
rewrite; `organization_name` rewrite; OEE; SparkplugB payload change; MQTT
command subscribe; API tag writes; hierarchy editor for Portland; publishing
orange ratios or snapshot-only intermediates as topics; battery SOC; Running /
Fault / Origin signals.
