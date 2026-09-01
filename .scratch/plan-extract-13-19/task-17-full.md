## Task 17: `utilities.yaml` and `asset_health.yaml`

Compressed air, steam, nitrogen, HVAC and chilled water, then condition monitoring on the rotating equipment. This is the bulk of the device inventory and the bulk of the message rate: `asset_health` publishes on the `fast` tier, which is why it is in `full` and not in `small`.

Nothing in the loader changes. Both files are transcription against interfaces Tasks 11, 12 and 16 already fixed, which is why they are one task and not four.

**Files:**
- Create: `conf/simulator/utilities.yaml`, `conf/simulator/asset_health.yaml`
- Modify: `99_simulator/test/test_conf_files.py` (extend the two tables)

**Interfaces:**
- Consumes: `read_simulator_conf` / `load_profile` (Task 16), and the `ctx` surface from Task 8 — this task is the first to use `ctx.served_air_demand` and the first to read `ctx.production_rate` and `ctx.running` *directly* rather than through `serves`, because an asset-health device sits on a production cell and therefore has a `LineState` of its own.
- Produces: no new code. The deliverable is two configuration files and the extended tables that prove they are complete.

Two placement rules carry over from Task 16 and decide the whole device list:

1. **A template that needs `serves` is per-site.** `CMP-01`/`CMP-02` (Dormagen) and `CMP-03` (Krefeld) are three templates rather than one because `FlowRate` derives from `ctx.served_air_demand`, and `AH-01`/`AH-02` are two for the same reason. `served_air_demand` is a **sum** over served lines, each in 0–1, so every one of them carries a `served_lines` parameter and divides by it.
2. **Everything else is site-agnostic.** `AirDryer`, `Boiler_B1`, `SteamHeader`, `CondensateReturn`, `N2Generator`, `N2Header`, `AHU_01` and `ChillerPlant` are Dormagen-only cell names (Krefeld's `CompressedAir` line has only `Compressor_C1` and `AirHeader`), so those templates omit `site` and still resolve to one device each.

Device tags are unique plant-wide — Krefeld's compressor is `CMP-03`, not a second `CMP-01`. Real plants often reuse tags per site, but template `id`s must be unique (Task 12 raises on a duplicate) and having `id` and `equipment` disagree would make the diagnostics table in sub-project B unreadable.

### The one honest limitation, stated once

Spec §8.4 wants condition monitoring that responds to load, and the shape catalogue has no "noise around a derived value" — `derived` is smooth, `ou_walk`'s `mean` is a float and not an expression. Rather than fake it, the split is physical:

- **Load-following signals are `derived`**: `MotorCurrent`, `MotorWindingTemp`, `BearingTempDe`/`Nde`, `LubeOilTemp`. These genuinely track duty, and they are what demonstrate the correlation.
- **Condition signals are `ou_walk`**: `VibrationRmsVelocity`, `VibrationAccelPeak`, `BearingEnvelope`, `FilterDp`. A bearing degrades on its own clock, not the line's, so a mean-reverting walk against ISO 10816 zones is the truthful model rather than a shortcoming.

- [ ] **Step 1: Extend the test tables**

In `99_simulator/test/test_conf_files.py`, add two entries to each table:

```python
EXPECTED_SIGNAL_COUNT = {
    "energy": {"EM-01": 17, "EM-02": 17, "TR-01": 6, "MCC-01": 6, "MCC-02": 6},
    "water": {"FM-01": 5, "DEMIN-01": 6, "CT-01": 11, "CT-02": 11, "EFF-01": 9},
    "utilities": {
        "CMP-01": 8,
        "CMP-02": 8,
        "CMP-03": 8,
        "DRY-01": 4,
        "AH-01": 4,
        "AH-02": 4,
        "BLR-01": 11,
        "SH-01": 3,
        "CR-01": 4,
        "N2-01": 5,
        "N2H-01": 2,
        "AHU-01": 8,
        "CH-01": 7,
    },
    "asset_health": {"VIB-01": 15, "VIB-02": 12},
}

EXPECTED_DEVICE_COUNT = {
    "energy": {"EM-01": 1, "EM-02": 1, "TR-01": 1, "MCC-01": 1, "MCC-02": 1},
    "water": {"FM-01": 2, "DEMIN-01": 1, "CT-01": 1, "CT-02": 1, "EFF-01": 1},
    "utilities": {
        "CMP-01": 1,
        "CMP-02": 1,
        "CMP-03": 1,
        "DRY-01": 1,
        "AH-01": 1,
        "AH-02": 1,
        "BLR-01": 1,
        "SH-01": 1,
        "CR-01": 1,
        "N2-01": 1,
        "N2H-01": 1,
        "AHU-01": 1,
        "CH-01": 1,
    },
    # VIB-01 lands on every Production cell: Dormagen Line1/Cell1, Line1/Cell2,
    # Line2/Cell1, and Krefeld Line1/Cell1. VIB-02 lands on the three compressor cells.
    "asset_health": {"VIB-01": 4, "VIB-02": 3},
}
```

Then add one test, because `asset_health` is the first family whose templates deliberately replicate and the first that must stay out of `small`:

```python
def test_asset_health_is_excluded_from_the_small_profile(raw):
    """Spec 9: asset_health publishes on the `fast` tier, so `small` must not load it.

    `small` is the shipped default and its whole purpose is to keep the graphdb mapper's
    per-topic-level MERGE load survivable. A fast-tier family creeping into it would undo
    that quietly - the simulator would still work, and Neo4j would simply fall behind.
    """
    small = load_profile(raw, "small")
    assert "asset_health" not in small.report.per_family
    assert small.families["asset_health"] is False
    assert load_profile(raw, "full").report.per_family["asset_health"] == 7  # noqa: PLR2004


def test_every_asset_health_signal_is_on_a_deliberate_tier(raw):
    """A `fast` tier is 1 s per signal per device; nothing lands there by accident.

    Counters and the ISO 4406 oil class are explicitly demoted, so this test is what stops
    a 15-minute register from being republished every second on 7 devices.
    """
    slow = {"RunHours": "meter", "StartCount": "meter", "LubeOilParticleCount": "status"}
    for template in raw["asset_health"]["devices"]:
        assert template["tier"] == "fast"
        for name, signal in template["signals"].items():
            assert signal.get("tier") == slow.get(name), f"{template['id']}/{name} is on the wrong tier"
```

`LoadedProfile.families` is the `dict[str, bool]` Task 12 produces, so `small.families["asset_health"] is False` reads the resolved decision rather than re-deriving it from `plant.yaml`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -x`
Expected: `KeyError: 'utilities'` from the `raw` fixture — `read_simulator_conf` skips files that do not exist, so an unwritten family is simply absent from the mapping.

- [ ] **Step 3: Write `conf/simulator/utilities.yaml`**

```yaml
# conf/simulator/utilities.yaml
# Spec 8.3. Compressed air, steam, nitrogen, HVAC, chilled water.
#
# Air and steam are the two utilities that visibly follow production: ctx.served_air_demand
# is fast and jittery (Task 7 gives it a noise term, modelling intermittent actuator draw)
# while ctx.served_heat_load is slow (a first-order lag), so the compressors chase the line
# and the boiler trails it. That difference is the point of having both.

devices:
  - id: CMP-01
    equipment: CMP-01
    target: {site: Dormagen, area: Utilities, line: CompressedAir, cell: Compressor_C1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      LoadPercent:
        shape: derived
        unit: "%"
        expr: idle_pct + span_pct * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_pct: 22.0, span_pct: 71.0, served_lines: 2.0}
        precision: 1
        range: [0, 110]
        limits: {hi: 97, hihi: 103}
      MotorPower:
        # An unloaded screw compressor still draws roughly a quarter of rated power, which
        # is why this interpolates from `unload_kw` rather than scaling from zero.
        shape: derived
        unit: kW
        expr: unload_kw + (rated_kw - unload_kw) * LoadPercent / 100.0
        params: {unload_kw: 46.0, rated_kw: 185.0}
        precision: 1
        range: [0, 220]
        limits: {hi: 195, hihi: 210}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: rated_nm3h * LoadPercent / 100.0
        params: {rated_nm3h: 1750.0}
        precision: 1
        range: [0, 2000]
      DischargePressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {setpoint_barg: 7.6, droop_bar: 0.55, served_lines: 2.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.5, lolo: 6.0}
      DischargeTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 62.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 95, hihi: 110}
      RunHours:
        # 1.0 / 3600.0 rather than 0.000278: the arithmetic is legal in an expression and
        # the intent survives being read six months later.
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 41200.0
        tier: meter
        precision: 2
      LoadUnloadCycles:
        # Cycling is worst at part load and near zero at full load, which is exactly the
        # wear mechanism an energy engineer is looking for on this topic.
        shape: counter
        unit: "1"
        rate: cycles_per_hour_max * (1.0 - LoadPercent / 100.0) / 3600.0
        params: {cycles_per_hour_max: 14.0}
        initial: 210400.0
        tier: meter
        precision: 0
      SpecificPower:
        shape: derived
        unit: "kW/(m³/min)"
        expr: MotorPower / max(FlowRate / 60.0, 0.1)
        precision: 3
        range: [0, 40]
        limits: {hi: 8.0, hihi: 11.0}

  - id: CMP-02
    equipment: CMP-02
    target: {site: Dormagen, area: Utilities, line: CompressedAir, cell: Compressor_C2}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      LoadPercent:
        # The trim machine: it idles lower and swings harder than the base-load C1, which
        # is how two compressors on one header actually share duty.
        shape: derived
        unit: "%"
        expr: idle_pct + span_pct * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_pct: 8.0, span_pct: 84.0, served_lines: 2.0}
        precision: 1
        range: [0, 110]
        limits: {hi: 97, hihi: 103}
      MotorPower:
        shape: derived
        unit: kW
        expr: unload_kw + (rated_kw - unload_kw) * LoadPercent / 100.0
        params: {unload_kw: 38.0, rated_kw: 160.0}
        precision: 1
        range: [0, 200]
        limits: {hi: 170, hihi: 185}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: rated_nm3h * LoadPercent / 100.0
        params: {rated_nm3h: 1480.0}
        precision: 1
        range: [0, 1700]
      DischargePressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {setpoint_barg: 7.5, droop_bar: 0.6, served_lines: 2.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.5, lolo: 6.0}
      DischargeTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 58.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 95, hihi: 110}
      RunHours:
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 28650.0
        tier: meter
        precision: 2
      LoadUnloadCycles:
        shape: counter
        unit: "1"
        rate: cycles_per_hour_max * (1.0 - LoadPercent / 100.0) / 3600.0
        params: {cycles_per_hour_max: 22.0}
        initial: 318900.0
        tier: meter
        precision: 0
      SpecificPower:
        shape: derived
        unit: "kW/(m³/min)"
        expr: MotorPower / max(FlowRate / 60.0, 0.1)
        precision: 3
        range: [0, 40]
        limits: {hi: 8.0, hihi: 11.0}

  - id: CMP-03
    equipment: CMP-03
    target: {site: Krefeld, area: Utilities, line: CompressedAir, cell: Compressor_C1}
    serves: [Krefeld/Production/Line1]
    tier: process
    signals:
      LoadPercent:
        # served_lines is 1.0: Krefeld has one line, and served_air_demand is a sum.
        shape: derived
        unit: "%"
        expr: idle_pct + span_pct * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_pct: 20.0, span_pct: 73.0, served_lines: 1.0}
        precision: 1
        range: [0, 110]
        limits: {hi: 97, hihi: 103}
      MotorPower:
        shape: derived
        unit: kW
        expr: unload_kw + (rated_kw - unload_kw) * LoadPercent / 100.0
        params: {unload_kw: 18.0, rated_kw: 75.0}
        precision: 1
        range: [0, 100]
        limits: {hi: 82, hihi: 90}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: rated_nm3h * LoadPercent / 100.0
        params: {rated_nm3h: 690.0}
        precision: 1
        range: [0, 800]
      DischargePressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {setpoint_barg: 7.4, droop_bar: 0.5, served_lines: 1.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.5, lolo: 6.0}
      DischargeTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 60.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 95, hihi: 110}
      RunHours:
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 16400.0
        tier: meter
        precision: 2
      LoadUnloadCycles:
        shape: counter
        unit: "1"
        rate: cycles_per_hour_max * (1.0 - LoadPercent / 100.0) / 3600.0
        params: {cycles_per_hour_max: 18.0}
        initial: 94300.0
        tier: meter
        precision: 0
      SpecificPower:
        shape: derived
        unit: "kW/(m³/min)"
        expr: MotorPower / max(FlowRate / 60.0, 0.1)
        precision: 3
        range: [0, 40]
        limits: {hi: 8.0, hihi: 11.0}

  - id: DRY-01
    equipment: DRY-01
    # No `site`: AirDryer is a Dormagen-only cell name.
    target: {area: Utilities, line: CompressedAir, cell: AirDryer}
    tier: process
    signals:
      DewPoint:
        # Spec 8.3 puts the hi limit at -20 °C. This is the one number that decides whether
        # instrument air is fit to use, so the alarm is on the warm side of the walk.
        shape: ou_walk
        unit: "°C"
        mean: -38.0
        sigma: 2.4
        tau: 900.0
        precision: 2
        range: [-70, 10]
        limits: {hi: -20.0, hihi: -10.0}
        export_metric: true
      InletTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k
        params: {rise_k: 14.0}
        precision: 1
        range: [-20, 80]
        limits: {hi: 45, hihi: 55}
      DifferentialPressure:
        shape: ou_walk
        unit: bar
        mean: 0.16
        sigma: 0.02
        tau: 1800.0
        precision: 3
        range: [0, 1.5]
        limits: {hi: 0.4, hihi: 0.7}
      RegenCycleState:
        shape: stepped
        unit: "1"
        choices: ["TowerA", "TowerB", "Purge"]
        weights: [5, 5, 1]
        dwell_s: 300.0
        tier: status
        param_type: Status

  - id: AH-01
    equipment: AH-01
    target: {site: Dormagen, area: Utilities, line: CompressedAir, cell: AirHeader}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      HeaderPressure:
        shape: derived
        unit: barg
        expr: idle_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_barg: 7.2, droop_bar: 0.9, served_lines: 2.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.0, lolo: 5.5}
        export_metric: true
      FlowRate:
        # `leak_nm3h` is the floor, not an addition on top of nothing: a header always
        # flows, because a plant always leaks.
        shape: derived
        unit: "Nm³/h"
        expr: leak_nm3h + process_nm3h * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {leak_nm3h: 190.0, process_nm3h: 2400.0, served_lines: 2.0}
        precision: 1
        range: [0, 3200]
      VolumeTotal:
        shape: counter
        unit: "Nm³"
        rate: FlowRate / 3600.0
        initial: 74500000.0
        tier: meter
        precision: 1
      LeakageEstimate:
        # Spec 8.3: "visible at idle". min() rather than a subtraction - at idle the whole
        # header flow *is* leakage, and under load the estimate caps at the leak rate
        # instead of going negative.
        shape: derived
        unit: "Nm³/h"
        expr: min(FlowRate, leak_nm3h)
        params: {leak_nm3h: 190.0}
        precision: 1
        range: [0, 500]
        limits: {hi: 250, hihi: 350}

  - id: AH-02
    equipment: AH-02
    target: {site: Krefeld, area: Utilities, line: CompressedAir, cell: AirHeader}
    serves: [Krefeld/Production/Line1]
    tier: process
    signals:
      HeaderPressure:
        shape: derived
        unit: barg
        expr: idle_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_barg: 7.1, droop_bar: 0.8, served_lines: 1.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.0, lolo: 5.5}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: leak_nm3h + process_nm3h * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {leak_nm3h: 95.0, process_nm3h: 620.0, served_lines: 1.0}
        precision: 1
        range: [0, 900]
      VolumeTotal:
        shape: counter
        unit: "Nm³"
        rate: FlowRate / 3600.0
        initial: 19800000.0
        tier: meter
        precision: 1
      LeakageEstimate:
        shape: derived
        unit: "Nm³/h"
        expr: min(FlowRate, leak_nm3h)
        params: {leak_nm3h: 95.0}
        precision: 1
        range: [0, 300]
        limits: {hi: 140, hihi: 200}

  - id: BLR-01
    equipment: BLR-01
    target: {area: Utilities, line: SteamPlant, cell: Boiler_B1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      SteamFlow:
        # On ctx.served_heat_load, the lagged follower - so the boiler trails a line stop
        # by minutes while the compressors react in seconds. Spec 6.1 built that lag
        # precisely so the utility side does not step in lockstep with production.
        shape: derived
        unit: t/h
        expr: min_t_h + span_t_h * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {min_t_h: 3.5, span_t_h: 22.0, served_lines: 2.0}
        precision: 2
        range: [0, 32]
        limits: {hi: 28, hihi: 30}
        export_metric: true
      SteamPressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * SteamFlow / rated_t_h
        params: {setpoint_barg: 13.5, droop_bar: 1.1, rated_t_h: 25.0}
        precision: 3
        range: [0, 20]
        limits: {lo: 11.5, lolo: 10.5, hi: 15.0, hihi: 16.0}
      SteamTemp:
        shape: derived
        unit: "°C"
        expr: base_c + rise_k * SteamFlow / rated_t_h
        params: {base_c: 192.0, rise_k: 14.0}
        precision: 1
        range: [0, 300]
        limits: {hi: 225, hihi: 240}
      DrumLevel:
        shape: sawtooth
        unit: "%"
        low: 44.0
        high: 58.0
        fill_rate: 0.6
        drain_rate: 0.4
        start: 50.0
        precision: 1
        range: [0, 100]
        limits: {lo: 35, lolo: 25, hi: 70, hihi: 80}
      FeedwaterFlow:
        # Slightly above steam flow: what leaves as blowdown never leaves as steam.
        shape: derived
        unit: t/h
        expr: SteamFlow * (1.0 + blowdown_fraction)
        params: {blowdown_fraction: 0.03}
        precision: 2
        range: [0, 35]
      FuelGasFlow:
        shape: derived
        unit: "Nm³/h"
        expr: standby_nm3h + nm3h_per_tonne * SteamFlow
        params: {standby_nm3h: 40.0, nm3h_per_tonne: 74.0}
        precision: 1
        range: [0, 2200]
      FuelGasTotal:
        shape: counter
        unit: "Nm³"
        rate: FuelGasFlow / 3600.0
        initial: 12750000.0
        tier: meter
        precision: 1
        export_metric: true
      FlueGasTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + base_rise_k + load_rise_k * SteamFlow / rated_t_h
        params: {base_rise_k: 95.0, load_rise_k: 78.0, rated_t_h: 25.0}
        precision: 1
        range: [0, 350]
        limits: {hi: 210, hihi: 240}
      FlueGasO2:
        # Excess air falls as the burner turns up, which is why this runs the other way
        # from every other load-following signal in the file.
        shape: derived
        unit: "%"
        expr: o2_idle_pct - o2_span_pct * clamp(SteamFlow / rated_t_h, 0.0, 1.0)
        params: {o2_idle_pct: 7.4, o2_span_pct: 4.2, rated_t_h: 25.0}
        precision: 2
        range: [0, 21]
        limits: {lo: 1.5, lolo: 0.8, hi: 8.5, hihi: 10.0}
      Efficiency:
        # The two real losses: stack temperature above ambient, and excess air. Both are
        # already on their own topics, so this signal is a genuine calculation rather than
        # a number invented alongside them.
        shape: derived
        unit: "%"
        expr: eff_max - stack_k * (FlueGasTemp - ctx.ambient_temp_c) / 100.0 - o2_k * FlueGasO2
        params: {eff_max: 94.5, stack_k: 3.1, o2_k: 0.55}
        precision: 2
        range: [0, 100]
        limits: {lo: 84.0, lolo: 78.0}
        export_metric: true
      BurnerState:
        shape: stepped
        unit: "1"
        choices: ["HighFire", "LowFire", "Modulating", "Standby"]
        weights: [3, 2, 6, 1]
        dwell_s: 600.0
        tier: status
        param_type: Status

  - id: SH-01
    equipment: SH-01
    target: {area: Utilities, line: SteamPlant, cell: SteamHeader}
    tier: process
    signals:
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 12.4
        sigma: 0.18
        tau: 240.0
        precision: 3
        range: [0, 20]
        limits: {lo: 10.5, lolo: 9.5}
      Temperature:
        shape: ou_walk
        unit: "°C"
        mean: 196.0
        sigma: 2.2
        tau: 300.0
        precision: 1
        range: [0, 300]
        limits: {lo: 175, hi: 225}
      FlowTotal:
        # A literal rate: the header totaliser has no flow transmitter of its own on this
        # skid, so 15 t/h is a nameplate figure written as arithmetic to keep the unit
        # conversion visible.
        shape: counter
        unit: t
        rate: 15.0 / 3600.0
        initial: 486000.0
        tier: meter
        precision: 2

  - id: CR-01
    equipment: CR-01
    target: {area: Utilities, line: SteamPlant, cell: CondensateReturn}
    tier: process
    signals:
      ReturnFlow:
        shape: ou_walk
        unit: t/h
        mean: 11.5
        sigma: 1.1
        tau: 600.0
        precision: 2
        range: [0, 25]
        limits: {lo: 6.0, lolo: 4.0}
      ReturnPercent:
        # Against a nameplate steam rate rather than BLR-01's SteamFlow: expressions see
        # sibling signals only, and reaching across devices is exactly the coupling the
        # `serves` mechanism exists to avoid.
        shape: derived
        unit: "%"
        expr: 100.0 * ReturnFlow / max(nominal_steam_t_h, 0.1)
        params: {nominal_steam_t_h: 16.0}
        precision: 1
        range: [0, 120]
        limits: {lo: 55, lolo: 40}
        export_metric: true
      Conductivity:
        # Condensate conductivity is the contamination alarm: a failed heat exchanger puts
        # process fluid straight into the boiler feed.
        shape: ou_walk
        unit: "µS/cm"
        mean: 8.5
        sigma: 1.8
        tau: 1200.0
        precision: 2
        range: [0, 200]
        limits: {hi: 25.0, hihi: 50.0}
      TrapFailureCount:
        shape: counter
        unit: "1"
        rate: 0.0000015
        initial: 27.0
        tier: meter
        precision: 0

  - id: N2-01
    equipment: N2-01
    target: {area: Utilities, line: Nitrogen, cell: N2Generator}
    tier: process
    signals:
      FlowRate:
        shape: ou_walk
        unit: "Nm³/h"
        mean: 320.0
        sigma: 22.0
        tau: 300.0
        precision: 1
        range: [0, 500]
      Purity_O2:
        # Spec 8.3 puts the hi limit at 10 ppm. Residual oxygen is what an inerting duty
        # actually cares about, so purity is expressed as the contaminant, not the product.
        shape: ou_walk
        unit: ppm
        mean: 4.2
        sigma: 0.9
        tau: 900.0
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 25.0}
        export_metric: true
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 8.1
        sigma: 0.15
        tau: 240.0
        precision: 3
        range: [0, 14]
        limits: {lo: 7.0, lolo: 6.5}
      VolumeTotal:
        shape: counter
        unit: "Nm³"
        rate: FlowRate / 3600.0
        initial: 9860000.0
        tier: meter
        precision: 1
      MotorPower:
        shape: derived
        unit: kW
        expr: standby_kw + kw_per_nm3h * FlowRate
        params: {standby_kw: 12.0, kw_per_nm3h: 0.115}
        precision: 1
        range: [0, 90]
        limits: {hi: 72, hihi: 80}

  - id: N2H-01
    equipment: N2H-01
    target: {area: Utilities, line: Nitrogen, cell: N2Header}
    tier: process
    signals:
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 7.6
        sigma: 0.2
        tau: 300.0
        precision: 3
        range: [0, 14]
        limits: {lo: 6.5, lolo: 6.0}
      FlowRate:
        shape: ou_walk
        unit: "Nm³/h"
        mean: 295.0
        sigma: 28.0
        tau: 180.0
        precision: 1
        range: [0, 500]

  - id: AHU-01
    equipment: AHU-01
    target: {area: Utilities, line: HVAC, cell: AHU_01}
    tier: process
    signals:
      SupplyAirTemp:
        # Control holds the setpoint; how well it holds it degrades as ambient runs away
        # from it. The 0.06 coefficient is that droop, not a physical mixing ratio.
        shape: derived
        unit: "°C"
        expr: setpoint_c + droop * (ctx.ambient_temp_c - setpoint_c)
        params: {setpoint_c: 20.0, droop: 0.06}
        precision: 2
        range: [0, 45]
        limits: {lo: 16, hi: 26}
      ReturnAirTemp:
        shape: derived
        unit: "°C"
        expr: SupplyAirTemp + room_gain_k
        params: {room_gain_k: 3.4}
        precision: 2
        range: [0, 45]
        limits: {hi: 28, hihi: 32}
      SupplyAirRh:
        shape: ou_walk
        unit: "%"
        mean: 46.0
        sigma: 3.5
        tau: 900.0
        precision: 1
        range: [0, 100]
        limits: {lo: 30, hi: 65}
      FanSpeed:
        shape: ou_walk
        unit: Hz
        mean: 38.0
        sigma: 2.0
        tau: 600.0
        precision: 1
        range: [0, 60]
      FilterDp:
        # Spec 8.3: "slow-rising, resets on service". A sawtooth is literally that - the
        # fast drain edge is the filter change.
        shape: sawtooth
        unit: Pa
        low: 90.0
        high: 320.0
        fill_rate: 0.0009
        drain_rate: 4.0
        start: 140.0
        precision: 1
        range: [0, 500]
        limits: {hi: 250, hihi: 300}
      DamperPosition:
        # Free cooling: the damper opens when outside air is close to setpoint and closes
        # when using it would cost more than it saves.
        shape: derived
        unit: "%"
        expr: clamp(max_pct - gain * abs(ctx.ambient_temp_c - setpoint_c), min_pct, max_pct)
        params: {max_pct: 85.0, min_pct: 12.0, gain: 4.5, setpoint_c: 20.0}
        precision: 1
        range: [0, 100]
      HeatingValvePosition:
        shape: derived
        unit: "%"
        expr: clamp(gain * (setpoint_c - ctx.ambient_temp_c), 0.0, 100.0)
        params: {gain: 5.5, setpoint_c: 20.0}
        precision: 1
        range: [0, 100]
      CoolingValvePosition:
        # The mirror image of the heating valve, so the pair can never both be open. Two
        # independent walks would sit there heating and cooling the same air.
        shape: derived
        unit: "%"
        expr: clamp(gain * (ctx.ambient_temp_c - setpoint_c), 0.0, 100.0)
        params: {gain: 6.5, setpoint_c: 20.0}
        precision: 1
        range: [0, 100]

  - id: CH-01
    equipment: CH-01
    target: {area: Utilities, line: HVAC, cell: ChillerPlant}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      ChilledWaterSupply:
        shape: ou_walk
        unit: "°C"
        mean: 6.5
        sigma: 0.25
        tau: 300.0
        precision: 2
        range: [0, 20]
        limits: {hi: 9.0, hihi: 11.0}
      ChilledWaterReturn:
        shape: derived
        unit: "°C"
        expr: ChilledWaterSupply + delta_max_k * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {delta_max_k: 6.2, served_lines: 2.0}
        precision: 2
        range: [0, 30]
        limits: {hi: 16.0, hihi: 19.0}
      CoolingLoad:
        # 1.163 kWh/(m³·K) is water's volumetric heat capacity, so this is flow times delta
        # T and not a fitted constant.
        shape: derived
        unit: kW
        expr: flow_m3h * 1.163 * (ChilledWaterReturn - ChilledWaterSupply)
        params: {flow_m3h: 145.0}
        precision: 1
        range: [0, 1400]
        export_metric: true
      CompressorPower:
        # Efficiency degrades as the condenser gets hotter, which is why ambient appears
        # here: a hot afternoon costs more kW for the same kW of cooling.
        shape: derived
        unit: kW
        expr: standby_kw + CoolingLoad / max(cop_nominal - ambient_penalty * (ctx.ambient_temp_c - 20.0) / 10.0, 1.2)
        params: {standby_kw: 9.0, cop_nominal: 4.6, ambient_penalty: 0.9}
        precision: 1
        range: [0, 400]
        limits: {hi: 320, hihi: 360}
        export_metric: true
      COP:
        shape: derived
        unit: "1"
        expr: CoolingLoad / max(CompressorPower, 1.0)
        precision: 3
        range: [0, 8]
        limits: {lo: 2.5, lolo: 1.8}
      EvaporatorPressure:
        shape: derived
        unit: barg
        expr: base_barg + slope * ChilledWaterSupply
        params: {base_barg: 2.6, slope: 0.085}
        precision: 3
        range: [0, 12]
        limits: {lo: 2.2, lolo: 1.8}
      CondenserPressure:
        shape: derived
        unit: barg
        expr: base_barg + slope * ctx.ambient_temp_c
        params: {base_barg: 8.4, slope: 0.19}
        precision: 3
        range: [0, 25]
        limits: {hi: 15.0, hihi: 17.5}
```

- [ ] **Step 4: Write `conf/simulator/asset_health.yaml`**

`VIB-01` is the first template that reads the line's own state rather than an aggregate. It sits on a production cell, so `build_plant_context` gave it a `LineState` and its `DeviceView` exposes `ctx.production_rate` and `ctx.running` directly — no `serves` list, and none would be correct, because a pump on Line1 is not serving Line1, it *is* Line1.

```yaml
# conf/simulator/asset_health.yaml
# Spec 8.4. Condition monitoring on the `fast` tier - 1 s per signal per device, which is
# how vibration is actually sampled and why this family is in `full` and not in `small`.
#
# The split between shapes here is physical, not a workaround: load-following signals are
# `derived` (they genuinely track duty), and condition signals are `ou_walk` (a bearing
# degrades on its own clock, not the line's). Counters and the oil-cleanliness class carry
# an explicit slower tier, because a 15-minute register republished every second would be
# 7 devices' worth of noise.

devices:
  - id: VIB-01
    equipment: PumpP101
    # Every Production cell at every site. No `serves`: a pump on Line1 is not serving
    # Line1, it is part of it, so it reads ctx.production_rate directly.
    target: {area: Production}
    tier: fast
    signals:
      VibrationRmsVelocity:
        # ISO 10816 zones: 4.5 mm/s is the boundary into "unsatisfactory", 7.1 into
        # "unacceptable". The walk's mean sits in zone A/B so the alarms mean something.
        shape: ou_walk
        unit: mm/s
        mean: 2.1
        sigma: 0.35
        tau: 600.0
        precision: 3
        range: [0, 20]
        limits: {hi: 4.5, hihi: 7.1}
        export_metric: true
      VibrationAccelPeak:
        shape: ou_walk
        unit: g
        mean: 1.4
        sigma: 0.28
        tau: 300.0
        precision: 3
        range: [0, 15]
        limits: {hi: 4.0, hihi: 6.5}
      BearingEnvelope:
        shape: ou_walk
        unit: gE
        mean: 0.9
        sigma: 0.2
        tau: 1200.0
        precision: 3
        range: [0, 10]
        limits: {hi: 2.5, hihi: 4.0}
      MotorCurrent:
        shape: derived
        unit: A
        expr: idle_a + span_a * ctx.production_rate
        params: {idle_a: 11.0, span_a: 27.0}
        precision: 2
        range: [0, 60]
        limits: {hi: 44, hihi: 50}
        export_metric: true
      MotorWindingTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 68.0, rated_a: 38.0}
        precision: 1
        range: [-20, 180]
        limits: {hi: 130, hihi: 145}
      BearingTempDe:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 34.0, rated_a: 38.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 85, hihi: 95}
      BearingTempNde:
        # Runs cooler than the drive end: no radial load from the coupling.
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 28.0, rated_a: 38.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 85, hihi: 95}
      SuctionPressure:
        shape: ou_walk
        unit: barg
        mean: 1.35
        sigma: 0.06
        tau: 120.0
        precision: 3
        range: [-1, 10]
        limits: {lo: 0.6, lolo: 0.3}
      DischargePressure:
        shape: derived
        unit: barg
        expr: SuctionPressure + shutoff_bar * (deadhead_frac + duty_frac * ctx.production_rate)
        params: {shutoff_bar: 5.8, deadhead_frac: 0.55, duty_frac: 0.45}
        precision: 3
        range: [0, 16]
        limits: {hi: 8.5, hihi: 9.5}
      DifferentialPressure:
        shape: derived
        unit: bar
        expr: DischargePressure - SuctionPressure
        precision: 3
        range: [0, 12]
        limits: {lo: 2.0, lolo: 1.2}
      RunHours:
        # ctx.running is a boolean, and Python's True is 1 in arithmetic - so run hours
        # accrue only while the line is in EXECUTE, which is what a run-hour meter means.
        # The only place in this file where a boolean enters an expression; MES-01's
        # Availability in production.yaml is the other one.
        shape: counter
        unit: h
        rate: ctx.running / 3600.0
        initial: 22400.0
        tier: meter
        precision: 2
      StartCount:
        shape: counter
        unit: "1"
        rate: 0.00028
        initial: 4180.0
        tier: meter
        precision: 0
      LubeOilTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 22.0, rated_a: 38.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 70, hihi: 80}
      LubeOilParticleCount:
        # ISO 4406 cleanliness class, published as the code engineers actually quote.
        shape: stepped
        unit: "1"
        choices: ["16/14/11", "17/15/12", "18/16/13", "19/17/14"]
        weights: [4, 6, 3, 1]
        dwell_s: 3600.0
        tier: status
        param_type: Status
      FilterDp:
        shape: ou_walk
        unit: bar
        mean: 0.42
        sigma: 0.05
        tau: 3600.0
        precision: 3
        range: [0, 3]
        limits: {hi: 1.2, hihi: 1.8}

  - id: VIB-02
    equipment: CompressorDrive
    # Spec 8.4: "plus rotating utility equipment (compressors, pumps)". A generic equipment
    # tag because one template covers three compressor cells and the cell already
    # disambiguates the topic.
    #
    # Twelve signals, not fifteen: suction, discharge and differential pressure belong to
    # the compressor itself and are already published by CMP-01/02/03. Duplicating them
    # here would put two different walks on the same physical measurement.
    target: {area: Utilities, line: CompressedAir, cell: [Compressor_C1, Compressor_C2]}
    tier: fast
    signals:
      VibrationRmsVelocity:
        shape: ou_walk
        unit: mm/s
        mean: 2.6
        sigma: 0.4
        tau: 600.0
        precision: 3
        range: [0, 20]
        limits: {hi: 4.5, hihi: 7.1}
        export_metric: true
      VibrationAccelPeak:
        shape: ou_walk
        unit: g
        mean: 1.8
        sigma: 0.32
        tau: 300.0
        precision: 3
        range: [0, 15]
        limits: {hi: 4.0, hihi: 6.5}
      BearingEnvelope:
        shape: ou_walk
        unit: gE
        mean: 1.2
        sigma: 0.24
        tau: 1200.0
        precision: 3
        range: [0, 10]
        limits: {hi: 2.5, hihi: 4.0}
      MotorCurrent:
        # ctx.served_air_demand would need a `serves` list, and a template that replicates
        # across three cells at two sites cannot carry one (Task 16). ctx.production_rate is
        # unavailable too - a utility cell has no LineState. So this is an ou_walk, and the
        # compressor's own load story lives on CMP-01/02/03's LoadPercent.
        shape: ou_walk
        unit: A
        mean: 196.0
        sigma: 22.0
        tau: 180.0
        precision: 2
        range: [0, 400]
        limits: {hi: 320, hihi: 355}
      MotorWindingTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 74.0, rated_a: 300.0}
        precision: 1
        range: [-20, 180]
        limits: {hi: 130, hihi: 145}
      BearingTempDe:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 42.0, rated_a: 300.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 90, hihi: 100}
      BearingTempNde:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 35.0, rated_a: 300.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 90, hihi: 100}
      RunHours:
        # A literal rate, unlike VIB-01's: a compressor runs whether or not any line is in
        # EXECUTE, and a utility cell has no ctx.running to read anyway.
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 39800.0
        tier: meter
        precision: 2
      StartCount:
        shape: counter
        unit: "1"
        rate: 0.00011
        initial: 1620.0
        tier: meter
        precision: 0
      LubeOilTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 46.0, rated_a: 300.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 88, hihi: 98}
      LubeOilParticleCount:
        shape: stepped
        unit: "1"
        choices: ["16/14/11", "17/15/12", "18/16/13", "19/17/14"]
        weights: [3, 6, 4, 2]
        dwell_s: 3600.0
        tier: status
        param_type: Status
      FilterDp:
        shape: ou_walk
        unit: bar
        mean: 0.55
        sigma: 0.07
        tau: 3600.0
        precision: 3
        range: [0, 3]
        limits: {hi: 1.4, hihi: 2.0}
```

`target.cell` takes a list here — `matches_target` accepts a string or a list of strings for every selector key (Task 11), which is what lets one template cover `Compressor_C1` and `Compressor_C2` without a wildcard that would also catch the dryer and the header.

- [ ] **Step 5: Run the tests**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -v`
Expected: all pass, including the two new tests and the extended parametrised cases.

If `test_a_template_carrying_serves_never_replicates` fails on `VIB-02`, a `serves` list was added to it — that template covers three cells across two sites, so no single `serves` list can be right for all of them, which is exactly why its `MotorCurrent` is an `ou_walk`.

- [ ] **Step 6: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add conf/simulator/utilities.yaml conf/simulator/asset_health.yaml 99_simulator/test/test_conf_files.py
git commit -m "feat(simulator): add the utilities and asset_health device families"
```

---

