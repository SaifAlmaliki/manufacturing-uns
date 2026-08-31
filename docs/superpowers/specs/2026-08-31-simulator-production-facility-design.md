# Simulator: production-facility plant model and correlated signal generation

Date: 2026-08-31
Module: `99_simulator`
Status: Approved, not yet implemented

## 1. Problem

`99_simulator` publishes 3 sensors across 8 PLCs — 2 device templates replicated
over 4 hierarchy cells. Every value is `base_value + uniform(-variation, +variation)`.
That is enough to prove a mapper consumes MQTT, and not enough for anything else.

Three properties of the current shape block growth to facility scale, and each is a
structural limit rather than a missing feature:

1. **Templates cannot be targeted.** `UnifiedNamespaceSimulator.create_plc` instantiates
   every template at every cell. An effluent analyser or a site main incomer has exactly
   one home; the cartesian product has no way to express that.
2. **Every signal is white noise around a constant.** A cumulative energy meter (kWh),
   a water meter (m³), a tank level, or a load that responds to production rate cannot be
   written as `base ± variation` at all. These are not edge cases — they are the majority
   of what a real facility publishes.
3. **`AsyncMQTTDevice.publish_parameter` opens a fresh broker connection per message**
   (`async with self.client:` at `devices.py:84`). At 8 devices × 3 signals this is merely
   wasteful. At ~50 devices × ~400 signals it is a connect/disconnect storm.

## 2. Goals

- Simulate a chemical/polymer production facility across four sensor families: utilities
  and energy, asset health, production/OEE/quality, and safety/environment.
- Generate values whose behaviour is physically plausible **and mutually correlated**, so
  that questions like "why did site consumption spike at 14:00" have an answer contained
  in the data.
- Keep message volume a deliberate, configurable choice with a conservative default.
- Preserve existing behaviour for existing configuration.

## 3. Non-goals

- Not a process simulator. No mass/energy balance, no thermodynamics, no solver. Signals
  are plausible and correlated, not physically rigorous.
- No SparkplugB payloads. The simulator keeps publishing JSON on ISA-95 topics; the
  existing `05_sparkplugb` mapper is unaffected.
- No change to the 8-level topic depth, and therefore no change to
  `graphdb.uns_node_types` in `conf/settings.yaml`.
- PackML state machines run on **production lines only**, not on utility skids. Real
  compressors and boilers have their own state models; modelling them adds machinery for
  little value here, because utilities are driven by demand instead.

## 4. Architecture

The dominant design constraint is that value generation must be testable without a broker.
Today `test/test_devices.py` monkeypatches `aiomqtt.Client` in order to assert on a number.
Signal math, plant state, and MQTT transport become three separate layers:

| File | Responsibility | Depends on |
|---|---|---|
| `signals.py` *(new)* | Signal shape classes; `next(dt, ctx) -> value`. Pure, no I/O. | — |
| `plant.py` *(new)* | `PlantContext`, `LineState` PackML machine, `PlantClock`. Pure, no I/O. | `signals` |
| `profiles.py` *(new)* | Load and validate `conf/simulator/*.yaml` into template objects | yaml |
| `expressions.py` *(new)* | Whitelisted AST expression evaluator for `derived` signals | — |
| `devices.py` *(modified)* | MQTT transport, connection lifecycle, device scheduling. **No value math.** | `signals`, `plant` |
| `simulator.py` *(modified)* | Template targeting, instantiation, cadence tier scheduling | all |
| `models.py` *(modified)* | `ISA95Hierarchy` gains area `kind`; hierarchy expansion gains filtering | — |

### 4.1 Data flow

```
conf/simulator/*.yaml
        |
        v
   profiles.py  --->  DeviceTemplate[] (with target selector + serves[])
        |
        v
  simulator.py  --- resolves target against expanded hierarchy paths --->
        |
        v
   SignalDevice(equipment, tier, Signal[])          PlantClock (1 s tick)
        |                                                   |
        |  reads ctx  <-------------------------------------+  PlantContext
        v                                                       (per site / per line)
   Signal.next(dt, ctx) -> value
        |
        v
   AsyncMQTTDevice.publish (persistent connection, one topic per signal)
```

## 5. Signal shapes

Ten shapes. `shape:` is the discriminator; **when absent it defaults to `noise`**, which is
what makes existing configuration behave identically.

### 5.1 Fields common to every signal

| Field | Required | Default | Meaning |
|---|---|---|---|
| `shape` | no | `noise` | Which generator |
| `unit` | **yes** | — | Unit of Measure, per `CONTEXT.md`. Written in full (`°C`, `m³/h`). |
| `precision` | no | `2` | Decimal places for the published `value` |
| `range` | no | — | `[min, max]` engineering range. Also the clamp for walk-type shapes. |
| `limits` | no | — | `{lolo, lo, hi, hihi}` → drives published `status` |
| `tier` | no | device's tier | Per-signal cadence override (a kWh counter on a `meter` tier inside an `energy`-tier device) |

`status` derivation: `hihi`/`lolo` breach → `"Alarm"`; `hi`/`lo` breach → `"Warning"`;
otherwise `"Normal"`. **When a signal declares no `limits` and uses `shape: noise`, the
existing heuristic is retained verbatim** (`deviation > variation*3` → Alarm,
`> variation*2` → Warning), so current output does not change.

### 5.2 The shapes

| Shape | Params | Semantics |
|---|---|---|
| `noise` | `base_value`, `variation` | `base_value + uniform(-variation, +variation)`. Backward-compatible default. |
| `constant` | `value` | Fixed. Setpoints, nameplate data. |
| `ou_walk` | `mean`, `sigma`, `tau` (s) | Ornstein–Uhlenbeck mean-reverting walk: `x += (mean - x) * dt/tau + sigma * sqrt(dt/tau) * N(0,1)`, clamped to `range`. The right default for temperatures, pressures and flows — it drifts and returns, producing trend lines rather than per-sample hash. |
| `counter` | `rate`, `initial`, `rollover` | `value += rate * dt`, monotonic non-decreasing. `rate` may be a number, the name of a sibling signal, or an expression. Wraps at `rollover` if set. **This is how kWh, m³, Nm³, run hours and piece counts are expressed.** |
| `sawtooth` | `low`, `high`, `fill_rate`, `drain_rate`, `start` | Ramps up at `fill_rate` to `high`, down at `drain_rate` to `low`, repeat. Tank, silo and basin levels. |
| `diurnal` | `mean`, `amplitude`, `period_s` (86400), `phase_s`, `noise` | Sinusoid plus noise. Ambient temperature, solar irradiance, grid carbon intensity. |
| `derived` | `expr`, `params` | Whitelisted expression over sibling signals, `params`, and `ctx`. Evaluated in dependency order. |
| `window_agg` | `source`, `agg` (`max`/`min`/`mean`), `window_s` | Rolling aggregate over a sibling signal. Peak demand (`max` over 900 s), rolling averages. |
| `stepped` | `source` or `choices`, `map` | Discrete value changing only on transition. `source` reads a `ctx` field (`line.state`); `choices` picks from a list on a dwell timer. PackML state, mode, tariff period, downtime reason, batch/recipe/sample IDs. |
| `bernoulli_event` | `p`, `choices` | With probability `p` per tick, emit an event payload from `choices`; otherwise publish nothing. Alarms, SIS trips, detector faults, lab samples. |

### 5.3 Determinism

Each signal owns a `random.Random` seeded from `hash((global_seed, topic))`. Two
consequences, both required by the test plan: identical seed reproduces an identical run,
and the draw order of one signal cannot perturb another's sequence.
`simulation.seed` defaults to a fixed integer, not to clock time.

### 5.4 Expression evaluation

`derived` and `counter.rate` expressions are **not** passed to `eval()`. `expressions.py`
parses with `ast.parse(mode="eval")` and walks the tree against a node whitelist:

- Permitted nodes: `Expression`, `BinOp`, `UnaryOp`, `Compare`, `BoolOp`, `IfExp`, `Call`,
  `Name`, `Constant`, `Attribute` (only on the `ctx` root), `Load`, and the arithmetic /
  comparison / boolean operators.
- Permitted names: sibling signal names, keys of `params`, `ctx`, `dt`.
- Permitted calls: `min`, `max`, `abs`, `round`, `clamp`, `sqrt`, `exp`.
- Anything else raises at **profile load time**, not at runtime.

Dependency resolution: sibling references form a graph, topologically sorted once per
device at construction. **A cycle is a load-time error.**

## 6. `PlantContext` — the correlation carrier

This is the mechanism that separates "many numbers" from a usable dataset.

### 6.1 Per-line state: PackML

Each `Production` line owns a `LineState` implementing the ISA-88/PackML state model. Legal
transitions only:

```
IDLE       -> STARTING -> EXECUTE
EXECUTE    -> HOLDING     -> HELD        -> UNHOLDING    -> EXECUTE
EXECUTE    -> SUSPENDING  -> SUSPENDED   -> UNSUSPENDING -> EXECUTE
EXECUTE    -> COMPLETING  -> COMPLETE    -> RESETTING    -> IDLE
<any>      -> ABORTING    -> ABORTED     -> CLEARING     -> STOPPED -> RESETTING -> IDLE
<any>      -> STOPPING    -> STOPPED
```

Transitions fire on a per-state dwell time plus a per-transition probability, both
configurable per line in `production.yaml`. Derived from the state:

| Field | Behaviour |
|---|---|
| `production_rate` | 0..1 of nameplate. `EXECUTE` 0.85–1.0; `STARTING` ramps 0→0.85; `COMPLETING` ramps down; `HELD`/`SUSPENDED`/`ABORTED`/`STOPPED`/`IDLE` = 0 |
| `throughput_tph` | `production_rate × nameplate_tph` |
| `heat_load` | 0..1, lags `production_rate` with a thermal time constant, so cooling responds *slowly* — a first-order lag, not an instant step |
| `air_demand` | 0..1, tracks `production_rate` with a fast noisy component for intermittent actuator draw |

### 6.2 Per-site state

`ambient_temp_c` (diurnal), `ambient_rh_pct`, `wet_bulb_temp_c` (derived), `wind_speed_ms`,
`barometric_mbar`, `shift` (A/B/C on an 8-hour rotation), `tariff` (peak/off-peak on a clock
schedule), `grid_co2_g_per_kwh` (diurnal).

### 6.3 Aggregation via `serves`

A utility device declares which production lines it serves. The context exposes, for that
device only:

- `ctx.served_production` — mean `production_rate` over served lines
- `ctx.served_throughput_tph` — sum
- `ctx.served_heat_load` — sum
- `ctx.served_air_demand` — sum

So the Dormagen main incomer's active power is
`base_load + ctx.served_production * connected_kw`. When Line1 enters `HELD`, site kW drops,
the kWh counter slows, cooling tower ΔT narrows over the following minutes (thermal lag),
and air header pressure recovers. One mechanism, facility-wide coherence.

A `serves` entry naming a path that does not exist is a **load-time error**.

### 6.4 `PlantClock`

A single asyncio task ticks all `PlantContext` state on a fixed 1-second step, independent
of any device's publish cadence. Devices only ever *read* the context. This is what lets a
1 s vibration sample and a 15-minute meter read observe one consistent world; per-device
ticking would let them drift apart.

## 7. Configuration

### 7.1 Layout

`conf/settings.yaml` keeps only MQTT and run options under the `simulator` env. The plant
definition moves to per-family files:

```
conf/
  settings.yaml           # simulator: mqtt, simulation.{profile,seed,tiers}
  simulator/
    plant.yaml            # hierarchy (all sites/areas/lines/cells) + profiles block
    energy.yaml
    water.yaml
    utilities.yaml
    asset_health.yaml
    production.yaml
    safety.yaml
```

`uns_config.get_settings()` hardcodes `settings_files=["settings.yaml", ".secrets.yaml"]`.
Rather than change shared config loading for all nine modules, `profiles.py` loads
`conf/simulator/*.yaml` itself, resolving the directory from
`uns_config.resolve_conf_dir()`. Profile files are flat YAML with no Dynaconf environment
sections; they carry no secrets and need no env-var layering.

### 7.2 `plant.yaml`

Areas gain a `kind`, which is how production templates are kept out of utility areas:

```yaml
enterprise: CovestroAG
sites:
  - name: Dormagen
    areas:
      - name: Production
        kind: production
        lines:
          - name: Line1
            nameplate_tph: 12.0
            cells: [Cell1, Cell2]
          - name: Line2
            nameplate_tph: 8.0
            cells: [Cell1]
      - name: Utilities
        kind: utilities
        lines:
          - name: PowerDistribution
            cells: [MainIncomer, Transformer_T1, MCC_Production, MCC_Utilities]
          - name: WaterTreatment
            cells: [RawWaterIntake, DeminPlant, CoolingTower1, EffluentOutfall]
          - name: CompressedAir
            cells: [Compressor_C1, Compressor_C2, AirDryer, AirHeader]
          - name: SteamPlant
            cells: [Boiler_B1, SteamHeader, CondensateReturn]
          - name: Nitrogen
            cells: [N2Generator, N2Header]
          - name: HVAC
            cells: [AHU_01, ChillerPlant]
      - name: Safety
        kind: utilities
        lines:
          - name: GasDetection
            cells: [GD_Zone1, GD_Zone2]
          - name: Emissions
            cells: [Stack_S1]
          - name: WeatherStation
            cells: [WS_01]
      - name: Quality
        kind: utilities
        lines:
          - name: Lab
            cells: [LIMS_01]
  - name: Krefeld
    # reduced mirror: Production/Line1/Cell1 plus PowerDistribution, WaterTreatment,
    # CompressedAir, GasDetection, WeatherStation

profiles:
  small:
    tier_scale: 6.0
    sites: [Dormagen]
    families: [energy, water, production]
    max_cells_per_line: 1
  full:
    tier_scale: 1.0
    sites: [Dormagen, Krefeld]
    families: [energy, water, utilities, asset_health, production, safety]
```

A profile filters the expanded hierarchy by `sites` and `max_cells_per_line`, selects which
family files load, and multiplies every tier interval by `tier_scale`.

### 7.3 Device template and targeting

```yaml
devices:
  - id: EM-01
    equipment: EM-01                    # the meter itself; cell is its location
    target:
      site: Dormagen
      area: Utilities
      line: PowerDistribution
      cell: MainIncomer
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: energy
    signals:
      ActivePower:
        shape: derived
        unit: kW
        expr: base_load + ctx.served_production * connected_kw
        params: {base_load: 220.0, connected_kw: 1450.0}
        precision: 1
        range: [0, 2000]
        limits: {hi: 1800, hihi: 1950}
      EnergyTotal:
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0      # kW -> kWh per second
        initial: 84000.0
        tier: meter
        precision: 1
```

`target` is a filter; **omitted keys mean "any"**. A template instantiates once per matching
hierarchy path, so one entry can pin a single meter or replicate an asset-health device
across every production cell:

```yaml
  - id: VIB
    equipment: PumpP101
    target: {area: Production}          # every Production cell, every site
    tier: fast
```

Templates with **no** `target` match cells in areas of `kind: production` only. This is the
compatibility rule that keeps the legacy `simulator.plc` list behaving exactly as today
while preventing it from leaking into the newly added utility areas.

Resulting topic, unchanged at 8 levels:

```
CovestroAG/Dormagen/Utilities/PowerDistribution/MainIncomer/EM-01/ProcessValue/ActivePower
```

## 8. Device inventory (`full` profile)

Dormagen ~33 devices, Krefeld ~15, ≈400 signals.

### 8.1 `energy.yaml`

| Device | Signals |
|---|---|
| `MainIncomer/EM-01` | ActivePower kW, ReactivePower kVAr, ApparentPower kVA, PowerFactor, VoltageL1/L2/L3 V, CurrentL1/L2/L3 A, Frequency Hz, VoltageThd %, **EnergyTotal kWh** (counter), **ReactiveEnergyTotal kVArh** (counter), PeakDemand kW (`window_agg` max/900 s), EnergyIntensity kWh/t (derived on `ctx.served_throughput_tph`), CarbonRate kgCO2/h (derived on `ctx.grid_co2_g_per_kwh`) |
| `Transformer_T1/TR-01` | LoadPercent %, OilTemperature °C (rises with load and ambient), WindingTemperature °C, TapPosition (stepped), CoolingFanStatus (stepped), **EnergyThroughput kWh** (counter) |
| `MCC_Production/MCC-01`, `MCC_Utilities/MCC-02` | ActivePower kW, Current A, **EnergyTotal kWh** (counter), FeederTripCount (counter), InsulationResistance MΩ, BusbarTemperature °C |

### 8.2 `water.yaml`

| Device | Signals |
|---|---|
| `RawWaterIntake/FM-01` | FlowRate m³/h, **VolumeTotal m³** (counter), Pressure barg, Temperature °C, Turbidity NTU |
| `DeminPlant/DEMIN-01` | ProductFlow m³/h, Conductivity µS/cm (limits hi 0.2), Silica ppb, ResinBedDp bar, RegenerationState (stepped), **ProductVolumeTotal m³** (counter) |
| `CoolingTower1/CT-01` | SupplyTemp °C, ReturnTemp °C (derived on `ctx.served_heat_load`), **DeltaT K** (derived), CirculationFlow m³/h, BasinLevel % (sawtooth), **MakeupVolumeTotal m³** (counter), BlowdownFlow m³/h, Conductivity µS/cm, FanSpeed Hz, ApproachTemp K (derived vs `ctx.wet_bulb_temp_c`), BiocideDosingRate L/h |
| `EffluentOutfall/EFF-01` | FlowRate m³/h, **VolumeTotal m³** (counter), pH (limits lo 6.5 / hi 9.0), COD mg/L, TSS mg/L, Turbidity NTU, Temperature °C (limits hi 35), Conductivity µS/cm, AmmoniumN mg/L |

### 8.3 `utilities.yaml`

| Device | Signals |
|---|---|
| `Compressor_C1/C2 · CMP-01/02` | MotorPower kW, DischargePressure barg, FlowRate Nm³/h (on `ctx.served_air_demand`), LoadPercent %, DischargeTemp °C, **RunHours h** (counter), **LoadUnloadCycles** (counter), SpecificPower kW/(m³/min) (derived) |
| `AirDryer/DRY-01` | DewPoint °C (limits hi −20), InletTemp °C, DifferentialPressure bar, RegenCycleState (stepped) |
| `AirHeader/AH-01` | HeaderPressure barg (droops with air demand), FlowRate Nm³/h, **VolumeTotal Nm³** (counter), LeakageEstimate Nm³/h (derived; visible at idle) |
| `Boiler_B1/BLR-01` | SteamFlow t/h, SteamPressure barg, SteamTemp °C, DrumLevel % (sawtooth), FeedwaterFlow t/h, FuelGasFlow Nm³/h, **FuelGasTotal Nm³** (counter), FlueGasTemp °C, FlueGasO2 %, Efficiency % (derived), BurnerState (stepped) |
| `SteamHeader/SH-01` | Pressure barg, Temperature °C, **FlowTotal t** (counter) |
| `CondensateReturn/CR-01` | ReturnFlow t/h, ReturnPercent % (derived), Conductivity µS/cm, **TrapFailureCount** (counter) |
| `N2Generator/N2-01` | FlowRate Nm³/h, Purity_O2 ppm (limits hi 10), Pressure barg, **VolumeTotal Nm³** (counter), MotorPower kW |
| `N2Header/N2H-01` | Pressure barg, FlowRate Nm³/h |
| `AHU_01/AHU-01` | SupplyAirTemp °C, ReturnAirTemp °C, SupplyAirRh %, FanSpeed Hz, FilterDp Pa (slow-rising, resets on service), DamperPosition %, HeatingValvePosition %, CoolingValvePosition % |
| `ChillerPlant/CH-01` | ChilledWaterSupply °C, ChilledWaterReturn °C, CoolingLoad kW (derived), CompressorPower kW, COP (derived), EvaporatorPressure barg, CondenserPressure barg |

### 8.4 `asset_health.yaml` — tier `fast`

Targets every `Production` cell plus rotating utility equipment (compressors, pumps).

`PumpP101/VIB-01`: VibrationRmsVelocity mm/s (**ISO 10816 zones**: limits hi 4.5, hihi 7.1),
VibrationAccelPeak g, BearingEnvelope gE, BearingTempDe °C, BearingTempNde °C, MotorCurrent A,
MotorWindingTemp °C, SuctionPressure barg, DischargePressure barg, DifferentialPressure bar
(derived), **RunHours h** (counter), **StartCount** (counter), LubeOilTemp °C,
LubeOilParticleCount (stepped, ISO 4406 class), FilterDp bar.

### 8.5 `production.yaml`

| Device | Signals |
|---|---|
| `<Production cell>/MES-01` | PackMlState (stepped from `ctx.line.state`), PackMlStateCode, ProductionRate ea/h, ThroughputTph t/h, **GoodCount ea** (counter), **RejectCount ea** (counter), TotalCount ea (derived), CycleTime s, Availability % (derived), Performance % (derived), Quality % (derived), **Oee %** (derived), DowntimeReason (stepped), BatchId (stepped), RecipeId (stepped) |
| `<Production cell>/QA-01` (tier `process`) | Viscosity mPa·s, Density kg/m³, Moisture %, RefractiveIndex, NirIndex, ColorB |
| `LIMS_01/LAB-01` (tier `lab`) | SampleId (stepped), Viscosity mPa·s, HydroxylNumber mgKOH/g, WaterContent ppm, Acidity mgKOH/g, ResultStatus (stepped Pass/Fail) |

The existing `G1` and `FillingMachine` PLC templates move into `production.yaml` unchanged
(`shape` omitted ⇒ `noise`), so their published values are unaffected.

### 8.6 `safety.yaml`

| Device | Signals |
|---|---|
| `GD_Zone1/2 · GD-01/02` | Lel % (limits hi 10, hihi 20), H2S ppm, CO ppm, O2 % (limits lo 19.5), VOC ppm, DetectorFault (bernoulli), ZoneAlarmState (stepped) |
| `Stack_S1/CEMS-01` | NOx mg/Nm³, SOx mg/Nm³, CO mg/Nm³, Particulate mg/Nm³, O2 %, FlueGasFlow Nm³/h, StackTemp °C, Opacity %, **NoxMassTotal kg** (counter) |
| `Stack_S1/SIS-01` (tier `status`) | TripStatus (stepped), InterlockStatus, EStopStatus, GuardDoorStatus, **SafetyDemandCount** (counter), ProofTestDueDays d |
| `WS_01/WS-01` | AmbientTemp °C (diurnal), RelativeHumidity %, WetBulbTemp °C (derived), DewPoint °C (derived), WindSpeed m/s, WindDirection °, SolarIrradiance W/m² (diurnal), **RainfallTotal mm** (counter), BarometricPressure mbar |

The weather station is not decoration: `ctx.wet_bulb_temp_c` sets the cooling tower's
achievable approach temperature, so hot humid afternoons degrade cooling performance and
raise chiller power. That is a real correlation worth demonstrating.

## 9. Cadence tiers and volume

One global `simulation.interval` becomes per-tier intervals, because a 15-minute meter read
is how utility meters actually report and 1 s is how condition monitoring actually samples.

| Tier | Interval (`full`) | Content |
|---|---|---|
| `fast` | 1 s | vibration, motor current |
| `process` | 5 s | temperatures, pressures, flows, levels, analysers |
| `energy` | 15 s | power, power factor, per-phase V/I |
| `status` | 30 s | PackML state, equipment status, SIS status |
| `meter` | 900 s | cumulative kWh / m³ / Nm³ / t counters |
| `lab` | 1800 s | LIMS sample results |
| `event` | on occurrence | alarms, trips, state transitions, operator actions |

Tier intervals are configurable under `simulation.tiers` in `settings.yaml` and multiplied
by the profile's `tier_scale`.

Volume: `full` ≈ 100 msg/s ≈ 8.6 M messages/day. `small` (default) ≈ 5 msg/s.

**Volume risk is Neo4j, not Timescale.** The historian appends; the graphdb mapper performs
`MERGE` work per topic level on *every* message, and sustained 100 msg/s of 8-level topics
is heavy write load. Hence `small` is the shipped default and `full` is opt-in via
`simulation.profile`.

One topic per signal is retained. It is what the module does today, and it matches the
Metric Key model in `CONTEXT.md` (`ProcessValue/Temperature/value`). Bundling signals into
nested payloads would cut message count but change Metric Key shape.

## 10. MQTT transport

`AsyncMQTTDevice` changes:

1. **Connect once.** The client is entered in `start()` and held for the device's lifetime.
   `publish_parameter` publishes on the open connection and no longer contains
   `async with self.client`.
2. **Reconnect with backoff.** On `aiomqtt.MqttError`, reconnect with exponential backoff
   capped at `mqtt.retry_interval`, and resume publishing. A device must not die silently
   on a transient broker restart, which is current behaviour.
3. **Last Will.** Each device registers an MQTT LWT on
   `<hierarchy>/<equipment>/Status/Availability` so a killed device looks genuinely offline.
   Per-device clients rather than one shared client is both more realistic — real field
   devices each hold their own session and LWT — and trivial for the broker at ~50
   connections.
4. **Client identifier.** `devices.py:34` currently builds `f"graphql-{time.time()}-..."`,
   which is a copy-paste artefact. It becomes `f"uns-sim-{device_id}"`, stable across
   reconnects so `clean_session` semantics behave.

## 11. Testing

New pure-logic suites requiring no broker:

**`test_signals.py`**
- `counter` never decreases across any tick sequence, including `dt` jitter; honours `rollover`
- `ou_walk` stays within `range` clamp and reverts toward `mean` over many ticks
- `sawtooth` stays within `[low, high]` and its period matches fill/drain rates
- `diurnal` peaks at the expected phase
- `window_agg` max equals the true max over the window and forgets values outside it
- `derived` evaluates in dependency order; **a reference cycle raises at load**
- identical `seed` ⇒ identical sequence; one signal's draws do not perturb another's

**`test_expressions.py`**
- permitted arithmetic, comparisons, `ctx.*` access and whitelisted calls evaluate
- rejected at load: attribute access off non-`ctx` roots, calls to non-whitelisted names,
  imports, subscripts, lambdas, walrus, comprehensions, dunder access

**`test_plant.py`**
- no illegal PackML transition is ever taken, over a long randomised run
- `production_rate` stays in `[0, 1]`; is 0 in `HELD`/`SUSPENDED`/`IDLE`/`ABORTED`/`STOPPED`
- `heat_load` lags `production_rate` rather than stepping with it
- `serves` aggregation sums exactly the named lines
- `PlantClock` advances all contexts on one clock; two tiers sampling the same tick agree

**`test_profiles.py`**
- both shipped profiles load clean and produce the expected device counts
- load-time failures: unknown `shape`, **missing `unit`**, malformed `target`, dangling
  `serves` path, `derived` cycle, unknown signal reference in `counter.rate`

**`test_targeting.py`**
- a `target` filter resolves to exactly the expected hierarchy paths; omitted keys mean any
- **regression guard: the existing `simulator.plc` + `equipment.mixer_tank` config still
  produces exactly today's 8 devices with today's topics**
- untargeted templates never instantiate in areas of `kind: utilities`

**`test_devices.py`** (extended, existing cases kept)
- exactly one connect per device lifetime — guards the churn fix, the whole point of §10
- LWT is registered with the expected topic
- reconnect path resumes publishing after a simulated `MqttError`
- topic shape stays at 8 levels

**`test_volume.py`**
- computed msg/s for the shipped `small` profile is below a threshold, so a firehose cannot
  become the default by accident

All existing tests must stay green.

## 12. Backward compatibility

| Existing behaviour | After |
|---|---|
| `shape:` absent on a sensor | Defaults to `noise`; values bit-for-bit identical |
| No `limits` on a `noise` signal | Existing `variation*2` / `variation*3` status heuristic retained |
| `simulator.plc` list in `settings.yaml` | Still loaded and still instantiated per production cell; covered by `test_targeting.py` |
| `simulator.equipment.mixer_tank` fallback | Still honoured when no templates resolve |
| `simulation.interval` | Honoured as the `process` tier interval when `simulation.tiers` is absent |
| `simulation.duration`, `= 0` semantics | Unchanged |
| `SCADA`, `HMI` devices | Behaviour unchanged, except `SCADA.connected_devices` now reports the real device count instead of `random.randint(5, 10)` |
| Topic depth, `graphdb.uns_node_types` | Unchanged at 8 levels |

## 13. Deliverables

**New source**: `signals.py`, `plant.py`, `profiles.py`, `expressions.py`.
**Modified source**: `devices.py`, `simulator.py`, `models.py`, `config.py`.
**New config**: `conf/simulator/{plant,energy,water,utilities,asset_health,production,safety}.yaml`.
**Modified config**: `conf/settings.yaml` — `simulation.{profile,seed,tiers}` added; PLC
templates migrate out to `production.yaml` (the keys stay supported).
**New tests**: `test_signals.py`, `test_expressions.py`, `test_plant.py`, `test_profiles.py`,
`test_targeting.py`, `test_volume.py`. Extended: `test_devices.py`.
**Docker**: one added `COPY ./conf/simulator /app/conf/simulator` in `99_simulator/Dockerfile`
(it currently copies only `conf/settings.yaml`; Compose already bind-mounts `./conf`, so this
is for bare `docker run`).
**Docs**: `99_simulator/README.md` section on profiles, tiers and signal shapes;
`docs/adr/0005-simulator-plant-model-and-signal-generation.md`.

## 14. Risks

| Risk | Mitigation |
|---|---|
| Neo4j write load at `full` profile | `small` is the default; volume documented; `test_volume.py` guards the default |
| Expression language becomes a mini-DSL nobody can debug | Whitelisted AST with load-time validation and precise errors; no `eval`; kept to arithmetic over named signals |
| ~400 YAML signal definitions drift from reality | Validation requires `unit` on every signal; `range`/`limits` optional but used for status, so wrong ranges surface as constant alarms |
| Correlation logic makes tests flaky | Fixed default seed, `PlantClock` on a fixed step, and property-style assertions (bounds, monotonicity, legal transitions) rather than exact-value assertions |
| Scope is large for one pass | Family files are independent; `profiles.families` allows landing and validating one family at a time |
