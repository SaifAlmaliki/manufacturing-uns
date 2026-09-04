# WTP plant simulation (replace Covestro facility)

Date: 2026-09-04
Module: `99_simulator` (config in `conf/simulator/`, mapper topic filters in `conf/settings.yaml`)
Status: Draft, awaiting review

Companion docs to write during implementation: `99_simulator/PROCESS.md` (what the plant is).

## 1. Problem

`99_simulator` publishes a Covestro Dormagen/Krefeld chemical facility: PackML production
lines, six sensor families, and water as a utility skid (`FM-01`, `DEMIN-01`, `CT-01`).
Values correlate through that model, but they are not a water treatment plant.

The UNS is now meant to be developed against a WTP: five process zones, project tags, and
equipment that behaves as one hydraulic train. Independent walks and the chemical-plant
topology are the wrong source of truth for that work.

## 2. Goals

- The simulator's only plant is this WTP. Dormagen, Krefeld, PackML, and the six families
  are removed, not kept as a profile.
- Five zones: RawWater → Treatment → Filtration → Storage → Distribution. Tags are those on
  the process drawing (section 6). Template *instances* that are not on the drawing (SF301,
  PID201, T401, V302–V314, M201, …) are not simulated.
- The plant runs itself. MQTT publishes only. No command subscribe, no per-tag writes.
- Levels, flows, and pressures follow actuator state (close V101 and T101 stops filling).
  AIT101 is a slow quality signal, not a chemistry model.
- Each device publishes the System Platform template attribute set as **read-only**
  telemetry, including command mirrors (`CmdStart` is whatever the sequencer last issued).
- Users can read what is being simulated without reading Python: `99_simulator/PROCESS.md`
  plus the README plant-model section.

## 3. Non-goals

- Not a hydraulics or chemistry solver. Tank balance is `dV/dt = Qin − Qout` with first-order
  lags on flow. That is the algebraic relation ADR 0006 already allowed, not the physics
  solver it rejected.
- No operator commands. `CmdOpen` / `CmdStart` / `Speed.SP` / `Reset` are published mirrors.
  They do not accept MQTT or API writes.
- No extra drawing-absent equipment (second filter, PID loops, mixers as tags, T401).
- No SparkplugB payload change. JSON on eight-level ISA-95 topics stays.
- No rewrite of OEE units, explore-view placeholders, or other Covestro-branded fixtures
  outside the mapper topic filters needed for this plant to be ingested.

## 4. Architecture

Keep the three-layer split from ADR 0006: signal math, plant state, MQTT transport.

| Piece | Role |
|---|---|
| `plant.py` | Replace PackML `LineState` with `WTPProcess`. `PlantClock` still ticks at 1 s. |
| `conf/simulator/plant.yaml` | Hierarchy: `AcmeWater` / `Site1` / five areas / `Train1` / cells = tags. |
| `conf/simulator/wtp.yaml` | 19 device templates, targeted at `area` + `cell`. `equipment` is the poster name. |
| `signals.py` / `devices.py` | Unchanged shapes and `SignalDevice`. Signals **read** `ctx`, never write it. |
| `profiles.py` | One family `wtp`, one profile `wtp`. `serves` and PackML timing blocks go away. |
| `99_simulator/PROCESS.md` | Process narrative, tag list, coupling rules, topic examples. |
| `conf/settings.yaml` | Default profile `wtp`. Mapper topic lists include `AcmeWater/#`. |

Data flow:

```
conf/simulator/plant.yaml + wtp.yaml
        → profiles.py → DeviceSpec[] + WTPProcess
        → PlantClock.tick(1 s) advances WTPProcess (sequencer + tanks + flows)
        → SignalDevice.evaluate reads ctx.wtp.*
        → publish_tier writes MQTT
```

`DeviceView.wtp` is the running `WTPProcess`. YAML uses paths such as `ctx.wtp.t101.level_pct`
and `ctx.wtp.p101.running`. Tag attributes on `WTPProcess` are lowercase (`t101`, `p101`).

## 5. Topic shape

Eight levels, unchanged depth:

`{enterprise}/{site}/{area}/{line}/{cell}/{equipment}/{param_type}/{signal}`

| Level | Value |
|---|---|
| enterprise | `AcmeWater` |
| site | `Site1` |
| area | zone: `RawWater`, `Treatment`, `Filtration`, `Storage`, `Distribution` |
| line | `Train1` |
| cell | instance tag (`T101`, `P101`, `FT101`, …) |
| equipment | poster template name (`WTP_Level`, `WTP_MotorDOL`, …) |

Examples:

```
AcmeWater/Site1/RawWater/Train1/T101/WTP_Level/ProcessValue/PV
AcmeWater/Site1/RawWater/Train1/P101/WTP_MotorDOL/Status/Running
AcmeWater/Site1/RawWater/Train1/FT101/WTP_Flowmeter/ProcessValue/PV
AcmeWater/Site1/Treatment/Train1/B101/WTP_Basin/ProcessValue/LevelPct
AcmeWater/Site1/Filtration/Train1/F101/WTP_Filter/Status/InService
```

Cell is the tag **once**. Equipment is the class. Do not repeat the tag as `T101/T101`.

`param_type`:

- Analog PVs (`PV`, `Volume_m3`, `LevelPct`, `Totalizer`, `Speed.PV`, `Position`, `RuntimeH`, …): `ProcessValue`
- Sequencer mirrors (`CmdOpen`, `CmdClose`, `CmdStart`, `CmdStop`, `RunCmd`, `ResetFault`, `Auto`, `Reset`, `Speed.SP`): `Setpoint`
- Discrete status (`OpenFB`, `CloseFB`, `Running`, `Fault`, `FilterRun`, `Backwash`, `InService`): `Status`

Do **not** publish a separate `EngUnits` signal. The payload `unit` field is the Unit of Measure.

Boolean values publish as JSON booleans. Dimensionless flags use `unit: "1"`.

## 6. Tag map

Nineteen devices. B101's mixer is not a tag. F101 is one filter, not SF301/SF302. No PID
devices; distribution flow is the VFD `Speed.SP` the sequencer writes.

| Area | Cell (tag) | Equipment | Signals |
|---|---|---|---|
| RawWater | V101 | WTP_Valve | CmdOpen, CmdClose, OpenFB, CloseFB, Position, CycleCount |
| RawWater | P101, P102, P103 | WTP_MotorDOL | CmdStart, CmdStop, ResetFault, Running, Fault, RuntimeH, StartCount, Auto |
| RawWater | T101 | WTP_Level | PV (%), Capacity_m3, Volume_m3 |
| RawWater | FT101 | WTP_Flowmeter | PV (m³/h), Totalizer, Reset (constant false) |
| RawWater | PT101 | WTP_Pressure | PV (barg) |
| Treatment | B101 | WTP_Basin | PV (m), LevelPct |
| Treatment | DP101 | WTP_MotorDOL | same as P101 |
| Treatment | AIT101 | WTP_Analyzer | PV (pH) |
| Filtration | V201, V202 | WTP_Valve | same as V101 |
| Filtration | F101 | WTP_Filter | FilterRun, Backwash, InService |
| Storage | T201 | WTP_Level | same as T101 |
| Distribution | P201, P202 | WTP_VFD | RunCmd, Speed.SP, Speed.PV, ResetFault, Running, Fault, RuntimeH, StartCount |
| Distribution | FT201 | WTP_Flowmeter | same as FT101 |
| Distribution | PT201 | WTP_Pressure | PV |
| Distribution | V301 | WTP_Valve | same as V101 |

WTP_Level limits on `PV` (%): HH 95, H 85, L 20, LL 10, matching the template sheet.
WTP_Basin `PV` is level in metres; `LevelPct` is 0–100.

Cadence:

| Tier | Interval | What |
|---|---|---|
| process | 5 s | PV, Position, Speed.PV, LevelPct, Volume_m3 |
| status | 30 s | Running, OpenFB, FilterRun, InService, command mirrors, Auto |
| meter | 900 s | Totalizer, RuntimeH, CycleCount, StartCount, Capacity_m3 |
| event | on change | Fault, Backwash |

One profile `wtp`, `tier_scale: 1.0`. `small` and `full` are deleted.

## 7. Process model

`WTPProcess` owns actuator state, hold-up, hydraulics, quality, and the sequencer.
Signals never mutate it.

### 7.1 Capacities and nameplates

| Vessel | Capacity | Initial level |
|---|---|---|
| T101 | 250 m³ | 50 % |
| B101 | 40 m³ | 50 % (PV metres = LevelPct × 3.0 m side water depth) |
| F101 | 8 m³ hold-up | full when in service |
| T201 | 400 m³ | 50 % |

| Stream | Nameplate |
|---|---|
| One raw-water pump (P101–P103) | 80 m³/h |
| Inlet with V101 open and one pump running | 80 m³/h |
| Distribution target (sequencer `Speed.SP`) | 70 m³/h |
| One distribution VFD at 100 % | 80 m³/h |

Start filled at 50 % so the plant produces data immediately, not after a fill-from-empty.

### 7.2 Hydraulics

Each tick:

1. **Inlet to T101.** Flow is 80 m³/h if V101 is open and at least one of P101–P103 is
   running and not faulted; otherwise 0. If T101 is at 100 %, inlet is 0 (level interlock).
2. **T101 outlet (FT101).** Flow if T101 is above LL and the downstream path can take water
   (treatment not blocked). Capped by available volume in T101 this tick.
3. **B101.** Integrates FT101 in, minus outlet to the filter. DP101 `Running` is true while
   B101 outlet flow > 0.
4. **F101.** Forward flow to T201 only if V201 and V202 are open **and** `InService`.
   During `Backwash`, V201/V202 are closed, F101 forward flow is 0, B101 outlet is 0, and
   FT101 (T101 outlet) is 0 so B101 cannot overflow. T201 is not filled from F101.
5. **T201 outlet / FT201.** Flow if V301 is open and at least one of P201/P202 is running.
   Speed.PV lags Speed.SP (first-order, τ = 8 s). FT201 = sum of running VFD contributions.
6. **Pressures.** PT101 = static head from T101 level plus a pump term if a raw pump runs;
   0.2 barg residual if idle. PT201 = T201 head plus distribution pump term; falls toward
   residual when both VFDs are stopped or V301 is closed.
7. **Lags.** Commanded flows approach the algebraic target with τ = 5 s so traces do not
   step.

Tanks clamp 0–100 %. Pulling below LL stops the outlet pump path that would empty them.

### 7.3 Quality

AIT101 pH is an Ornstein–Uhlenbeck walk, mean 7.2, σ 0.08, τ 600 s, range 6.5–8.5.
While DP101 is running the mean is 7.2; while it is off the mean drifts toward 7.6 over
the same τ. No other chemistry.

### 7.4 Sequencer (autonomous)

Mode starts at `Running` (train already live).

- **Valves in Running:** V101, V201, V202, V301 open (Position 100, OpenFB true).
- **Raw pumps:** exactly one duty among P101–P103; others stopped. Rotate duty every
  900 s in order P101 → P102 → P103 → P101. `Auto` is always true.
- **Distribution:** P201 is lead at Speed.SP = 87.5 (70 m³/h of 80 m³/h nameplate). P202
  is lag: stopped, Speed.SP = 0, unless the lead is faulted — then P202 takes SP 87.5.
  Speed.PV follows as in 7.2.
- **Backwash:** every 1800 s of Running, enter Backwash for 45 s. F101 Backwash true,
  InService false, V201/V202 close, T201 is not filled from F101. Then return to Running.
- **Faults:** each running motor/VFD has probability 1/3600 per tick of latching `Fault`
  (about once an hour). Sequencer stops that machine and starts the standby (next raw pump
  in the rotation order, or the lag VFD). `Fault` stays true for 120 s, then clears.
  `ResetFault` is true for 30 s at the moment of clear (one status period, not a 1 s pulse).
- **Interlocks:** do not run a pump against a closed discharge (V301 closed ⇒ VFDs stop;
  V101 closed ⇒ raw pumps stop). Do not start a pump that is faulted.

Command mirrors always equal the last sequencer action (`CmdStart` true while the
sequencer wants the motor running, even if `Fault` has already dropped `Running`).

## 8. Control API and console

Routes stay. Bodies that named PackML or six families change.

| Endpoint | Change |
|---|---|
| `GET /simulator/plant` | Snapshot in section 8.1. Not PackML lines. |
| `PUT /simulator/profile` | Only `wtp`. Any other name is 422 `field: profile`. |
| `PUT /simulator/families` | One field: `wtp`. Remove energy/water/utilities/asset_health/production/safety. |
| `GET /simulator/config` | `available_profiles: ["wtp"]`, `families: {wtp: true}`. |

Pause still advances `WTPProcess` and stops publishing.

### 8.1 `GET /simulator/plant` body

```json
{
  "enterprise": "AcmeWater",
  "site": "Site1",
  "mode": "Running",
  "filter_mode": "InService",
  "duty_raw_pump": "P101",
  "lead_dist_pump": "P201",
  "tanks": {
    "T101": {"level_pct": 51.2, "volume_m3": 128.0, "capacity_m3": 250.0},
    "B101": {"level_pct": 48.0, "volume_m3": 19.2, "capacity_m3": 40.0},
    "T201": {"level_pct": 50.1, "volume_m3": 200.4, "capacity_m3": 400.0}
  },
  "flows_m3h": {"inlet": 80.0, "FT101": 78.4, "FT201": 69.8},
  "pressures_barg": {"PT101": 2.1, "PT201": 3.8}
}
```

`filter_mode` is `InService` or `Backwash`. `mode` is `Running` or `Backwash`.

### 8.2 Frontend

`11_frontend` `PlantStateInspector` and `PlantSnapshot` types today assume PackML
`production_rate`. They must render this snapshot (tanks, duty pump, filter mode, flows)
or the simulator page is false. That contract update is in scope. Explore-view copy that
still says `CovestroAG` is not.

### 8.3 Self-telemetry

`uns/platform/simulator/<instance>/` is unchanged as a prefix (Platform Observability).
Plant events fire on duty rotation, backwash enter/leave, and fault latch, on
`plant/Site1/Train1/state`, not PackML names.

## 9. Platform config so the UNS actually sees the plant

Graphdb, historian, and kafka mapper subscriptions today are `CovestroAG/#`. Publishing
`AcmeWater/...` without updating them means the WTP is invisible.

In scope in `conf/settings.yaml`:

- `simulator.simulation.profile: wtp`
- mapper `mqtt.topics` replace `CovestroAG/#` with `AcmeWater/#` (keep `test/uns/#` and
  Sparkplug entries)
- fallback `simulator.hierarchy.enterprise: AcmeWater` (only used if `plant.yaml` is absent)
- `platform.organization_name` and `display_name` set to `AcmeWater` / `Acme Water UNS`

OEE `conf/oee/units.yaml` still names a Covestro line. Leave it. The WTP has no OEE unit.

## 10. Documentation

- **`99_simulator/PROCESS.md`** (required): five-area narrative; tag table from section 6;
  hydraulic and sequencer rules in operator language; one example topic per template;
  explicit "not modelled" list (chemistry, commands, second filter, PID).
- **`99_simulator/README.md`**: replace the Dormagen/PackML/profile table with this WTP.
  Point at `PROCESS.md`.
- **`plant.yaml` / `wtp.yaml` headers**: one short paragraph and a link to `PROCESS.md`.

## 11. Testing

Replace PackML / Covestro assertions. Do not keep dual-plant fixtures.

Must-have:

- Sequencer: one duty raw pump; lead VFD running in Running; backwash closes V201/V202 and
  zeros F101 forward flow; duty fault starts the next pump.
- Coupling: V101 closed ⇒ T101 volume does not rise and inlet flow is 0; both VFDs stopped
  or V301 closed ⇒ FT201 and PT201 fall.
- Inventory: 19 devices; equipment names match section 6; every topic prefix is
  `AcmeWater/Site1/<Area>/Train1/<Tag>/WTP_<Template>`.
- Profile `wtp` is the default; unknown profile 422.
- `PROCESS.md` exists (path assertion, not content poetry).
- Self-telemetry topics still do not match mapper filters.
- Signal/expression/MQTT tests that do not assume PackML stay.

`test_volume.py` is rewritten for this inventory, not deleted: the graphdb MERGE constraint
is still real.

## 12. Error handling

Load-time (fatal, named key): missing `unit`, unknown template target, unknown `ctx` path
used by a `derived`/`stepped` signal, signal cycles, unknown profile name in settings.

Run-time: a `derived` eval failure still yields `None` for that signal; the device keeps
publishing siblings. Sequencer interlocks never raise.

## 13. Out of scope (repeat)

MQTT command subscribe; API tag writes; SF301/PID201/T401 and other poster-only instances;
changing eight-level depth; SparkplugB; OEE; HiveMQ adapter fixtures unless they subscribe
only to `CovestroAG/#` and would then see nothing — if they do, add `AcmeWater/#` there too
as a one-line config fix, not a HiveMQ redesign.
