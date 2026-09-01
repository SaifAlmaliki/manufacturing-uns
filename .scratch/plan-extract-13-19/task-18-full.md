## Task 18: `production.yaml` and `safety.yaml`

The last two families. `production.yaml` is where the plant model pays off — PackML state, OEE and batch identity all read the same `LineState` the utilities are reacting to — and it is where the legacy `G1`/`FillingMachine` templates move so that nothing that publishes today stops publishing. `safety.yaml` closes the loop: `WS-01` publishes the weather that `CT-01`'s approach temperature and `CH-01`'s power already depend on.

**Files:**
- Create: `conf/simulator/production.yaml`, `conf/simulator/safety.yaml`
- Modify: `99_simulator/test/test_conf_files.py` (extend the two tables, plus three tests)

**Interfaces:**
- Consumes: `read_simulator_conf` / `load_profile` (Task 16); `ctx.state`, `ctx.production_rate`, `ctx.running`, `ctx.time_in_state_s` (Task 8); `PACKML_STATES` (Task 4) as the domain of the `map` on `PackMlStateCode`.
- Produces: no new code.

**Read this before transcribing `ctx.state`.** Task 5's unit test for `SteppedSignal` uses a fake view and writes `source: ctx.line.state`, because `resolve_ctx_path` walks whatever attributes it is given. A real `DeviceView` is **flat**: the path is `ctx.state`, not `ctx.line.state` (Task 8, `DeviceView` properties). Copying the path out of the Task 5 test into a configuration file would raise at load time.

### Three decisions taken here, with reasons

**1. `WS-01` derives the weather from `ctx` instead of generating its own.**

Spec §8.6 marks `AmbientTemp` and `SolarIrradiance` as `diurnal`. `SolarIrradiance` stays `diurnal` — nothing in `PlantContext` models sunlight. `AmbientTemp`, `RelativeHumidity`, `WetBulbTemp`, `WindSpeed` and `BarometricPressure` do **not**, and instead read `ctx`, because `SiteState` already computes all five from that site's `ambient_mean_c` and `ambient_swing_c` in `plant.yaml`. A second sine on the same quantity would be a second, disagreeing weather: the cooling tower would be sizing its approach against one number while the weather station published another, and the spec's own closing sentence — "hot humid afternoons degrade cooling performance" — would be unverifiable, because the two would not be the same afternoon. It would also force one template per site to carry each site's amplitude, where one site-agnostic template now serves both.

**2. The four OEE percentages are instantaneous, not windowed.**

`window_agg` reads **numeric siblings only** — it resolves `source` against the sibling map and skips `bool` explicitly (Task 6). It cannot see `ctx.running`, so an availability computed as "fraction of the last hour spent in EXECUTE" is not expressible with the shapes this plan builds, and inventing a shape for one signal is not worth it. So `Availability`, `Performance`, `Quality` and `Oee` are the textbook ratios evaluated now, and windowing is Grafana's job — which is the division of labour spec B §2 already settled. `Availability` is consequently a 0-or-100 square wave; that is stated in a comment on the signal so nobody reads it as a rolling figure.

**3. `DowntimeReason` is mapped from `ctx.state`, not drawn from a list.**

A reason drawn independently would publish "MaterialShortage" while `PackMlState` said `EXECUTE`. Mapping the same `ctx.state` through a lookup table makes the two incapable of contradicting each other, which is exactly what `SteppedSignal`'s `map` exists for.

- [ ] **Step 1: Extend the test tables and add three tests**

In `99_simulator/test/test_conf_files.py`, add to each table:

```python
    "production": {"MES-01": 15, "QA-01": 6, "LAB-01": 6, "001": 2, "002": 1},
    "safety": {"GD-01": 7, "GD-02": 7, "CEMS-01": 9, "SIS-01": 6, "WS-01": 9},
```

```python
    # MES-01, QA-01 and the two legacy PLC templates land on all four Production cells.
    # LAB-01 is Dormagen's Quality area only.
    "production": {"MES-01": 4, "QA-01": 4, "LAB-01": 1, "001": 4, "002": 4},
    # GD_Zone1 and WS_01 exist at both sites; GD_Zone2 and Stack_S1 are Dormagen-only.
    "safety": {"GD-01": 2, "GD-02": 1, "CEMS-01": 1, "SIS-01": 1, "WS-01": 2},
```

Add `from uns_simulator.plant import PACKML_STATES` to the imports at the top of the file — at function scope ruff's preview `PLC0415` would reject it.

Then three tests. The first is the regression guard spec §12 asks for; the second and third pin the two decisions above:

```python
LEGACY_PLC_SENSORS = {
    ("001", "G1"): {"Temperature": (75.0, 2.0, "°C"), "Pressure": (150.0, 5.0, "psi")},
    ("002", "FillingMachine"): {"FlowRate": (450.0, 20.0, "L/min")},
}


@pytest.mark.parametrize("key", sorted(LEGACY_PLC_SENSORS))
def test_legacy_plc_templates_moved_across_unchanged(raw, key):
    """Spec 8.5 and 12: the pre-existing PLC signals must publish exactly as they did.

    `sensors:` became `signals:` and the file changed, but `equipment` decides the topic and
    base_value/variation/unit decide the payload, so those four are what this asserts. A
    `shape` key appearing on any of them would also be a change - `noise` is the default and
    the old generator had no other behaviour.
    """
    device_id, equipment = key
    sensors = LEGACY_PLC_SENSORS[key]
    template = next(item for item in raw["production"]["devices"] if str(item["id"]) == device_id)
    assert template["equipment"] == equipment
    assert template.get("target") is None, "an absent target means every production cell, which is what create_plc did"
    assert set(template["signals"]) == set(sensors)
    for name, (base_value, variation, unit) in sensors.items():
        signal = template["signals"][name]
        assert signal["base_value"] == base_value
        assert signal["variation"] == variation
        assert signal["unit"] == unit
        assert "shape" not in signal


def test_the_weather_station_reports_the_plant_context(raw):
    """The station must not be a second, disagreeing model of the same weather.

    SiteState already derives all five of these from plant.yaml. SolarIrradiance is exempt:
    PlantContext has no sunlight, so a `diurnal` of its own is the only option.
    """
    signals = next(item for item in raw["safety"]["devices"] if item["id"] == "WS-01")["signals"]
    from_context = {
        "AmbientTemp": "ctx.ambient_temp_c",
        "RelativeHumidity": "ctx.ambient_rh_pct",
        "WetBulbTemp": "ctx.wet_bulb_temp_c",
        "WindSpeed": "ctx.wind_speed_ms",
        "BarometricPressure": "ctx.barometric_mbar",
    }
    for name, path in from_context.items():
        assert signals[name]["shape"] == "derived"
        assert path in signals[name]["expr"], f"{name} must read {path}"
    assert signals["SolarIrradiance"]["shape"] == "diurnal"


def test_packml_state_code_maps_every_state(raw):
    """A state missing from the map publishes its own name where an integer is expected.

    SteppedSignal._translate falls through to the raw value on a miss, so an incomplete map
    fails as a type surprise on a consumer rather than at load time. Only this test catches it.
    """
    signals = next(item for item in raw["production"]["devices"] if item["id"] == "MES-01")["signals"]
    assert set(signals["PackMlStateCode"]["map"]) == set(PACKML_STATES)
    assert set(signals["DowntimeReason"]["map"]) == set(PACKML_STATES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -x`
Expected: `KeyError: 'production'` from the `raw` fixture.

- [ ] **Step 3: Write `conf/simulator/production.yaml`**

```yaml
# conf/simulator/production.yaml
# Spec 8.5. What the line is doing, how well, and what it is making.
#
# Every device here sits on a Production cell, so it reads its own line's state directly -
# ctx.state, ctx.production_rate, ctx.running - and carries no `serves` list. A `serves` list
# would be wrong by definition: a filling machine on Line1 is not serving Line1, it is Line1.
#
# NOTE the ctx path. DeviceView is flat: `ctx.state`, not `ctx.line.state`. The unit test in
# Task 5 uses a fake view with a nested attribute; a configuration file cannot.

devices:
  - id: MES-01
    equipment: MES-01
    target: {area: Production}
    tier: process
    signals:
      PackMlState:
        # Mirrored, not invented. The whole reason PlantContext exists is so that the state
        # on this topic is the same object the compressors and the boiler are reacting to.
        shape: stepped
        unit: "1"
        source: ctx.state
        tier: status
        param_type: Status
      PackMlStateCode:
        # The OMAC PackML numeric codes. Same source, same instant, lookup table attached -
        # so the code and the name can never disagree.
        shape: stepped
        unit: "1"
        source: ctx.state
        map:
          CLEARING: 1
          STOPPED: 2
          STARTING: 3
          IDLE: 4
          SUSPENDED: 5
          EXECUTE: 6
          STOPPING: 7
          ABORTING: 8
          ABORTED: 9
          HOLDING: 10
          HELD: 11
          UNHOLDING: 12
          SUSPENDING: 13
          UNSUSPENDING: 14
          RESETTING: 15
          COMPLETING: 16
          COMPLETE: 17
        tier: status
        param_type: Status
      ProductionRate:
        shape: derived
        unit: ea/h
        expr: nameplate_ea_h * ctx.production_rate
        params: {nameplate_ea_h: 1800.0}
        precision: 1
        range: [0, 2200]
      ThroughputTph:
        # ctx.throughput_tph is already nameplate_tph * production_rate, and nameplate_tph is
        # per-line in plant.yaml - so this one template publishes 12 t/h on Dormagen Line1 and
        # 5 t/h on Krefeld Line1 without knowing either number.
        shape: derived
        unit: t/h
        expr: ctx.throughput_tph
        precision: 3
        range: [0, 20]
        export_metric: true
      GoodCount:
        shape: counter
        unit: ea
        rate: ProductionRate * (1.0 - reject_fraction) / 3600.0
        params: {reject_fraction: 0.014}
        initial: 0.0
        tier: meter
        precision: 0
      RejectCount:
        shape: counter
        unit: ea
        rate: ProductionRate * reject_fraction / 3600.0
        params: {reject_fraction: 0.014}
        initial: 0.0
        tier: meter
        precision: 0
      TotalCount:
        shape: derived
        unit: ea
        expr: GoodCount + RejectCount
        precision: 0
        tier: meter
      CycleTime:
        # Seconds per unit. The 1.0 floor is the idle case: at zero rate the true cycle time
        # is infinite, and `cycle_time_max_s` says what gets published instead.
        shape: derived
        unit: s
        expr: min(3600.0 / max(ProductionRate, 1.0), cycle_time_max_s)
        params: {cycle_time_max_s: 600.0}
        precision: 3
        range: [0, 600]
      Availability:
        # Instantaneous, so this is a 0-or-100 square wave and NOT a rolling percentage.
        # window_agg reads numeric siblings only and skips bools, so it cannot see
        # ctx.running; the rolling view belongs in Grafana. ctx.running is a boolean and
        # Python's True is 1 in arithmetic.
        shape: derived
        unit: "%"
        expr: 100.0 * ctx.running
        precision: 1
        range: [0, 100]
      Performance:
        # Actual rate over ideal rate, which is what ctx.production_rate already is. Zero
        # while the line is down, 85-100 while it executes.
        shape: derived
        unit: "%"
        expr: 100.0 * ctx.production_rate
        precision: 2
        range: [0, 100]
        limits: {lo: 80.0, lolo: 70.0}
      Quality:
        # The 1.0 floor makes this 100 % before the first unit is made rather than 0 %,
        # which would alarm on every restart. Both counters start at zero, so this converges
        # on the true ratio within a minute of running.
        shape: derived
        unit: "%"
        expr: 100.0 * (1.0 - RejectCount / max(TotalCount, 1.0))
        precision: 3
        range: [0, 100]
        limits: {lo: 97.0, lolo: 95.0}
      Oee:
        shape: derived
        unit: "%"
        expr: Availability * Performance * Quality / 10000.0
        precision: 2
        range: [0, 100]
        limits: {lo: 65.0, lolo: 50.0}
        export_metric: true
      DowntimeReason:
        # Mapped from the same ctx.state as PackMlState, so a reason can never contradict the
        # state it is explaining. A reason drawn from a list would eventually publish
        # "MaterialShortage" on a line that was running.
        shape: stepped
        unit: "1"
        source: ctx.state
        map:
          IDLE: NoOrder
          STARTING: Startup
          EXECUTE: None
          HOLDING: ProcessHold
          HELD: MaterialShortage
          UNHOLDING: Recovering
          SUSPENDING: UpstreamBlocked
          SUSPENDED: UpstreamBlocked
          UNSUSPENDING: Recovering
          COMPLETING: OrderFinishing
          COMPLETE: OrderComplete
          RESETTING: Changeover
          ABORTING: Fault
          ABORTED: Fault
          CLEARING: FaultClearing
          STOPPING: OperatorStop
          STOPPED: OperatorStop
        tier: status
        param_type: Status
      BatchId:
        # dwell_s tracks Dormagen Line1's execute_s of 3600 s, so a batch id holds for about
        # as long as a batch. Krefeld's longer batches will see it change mid-batch; a
        # per-line batch identity would need a per-line template and buys nothing.
        shape: stepped
        unit: "1"
        choices: ["B-24101", "B-24102", "B-24103", "B-24104", "B-24105", "B-24106"]
        dwell_s: 3600.0
        tier: status
        param_type: Status
      RecipeId:
        shape: stepped
        unit: "1"
        choices: ["R-100-STD", "R-100-HIGH", "R-220-STD", "R-330-LOW"]
        weights: [6, 2, 3, 1]
        dwell_s: 7200.0
        tier: status
        param_type: Status

  - id: QA-01
    equipment: QA-01
    target: {area: Production}
    tier: process
    signals:
      Viscosity:
        # Inline quality: it degrades as the line runs harder, which is what makes the
        # limits worth watching rather than decorative.
        shape: derived
        unit: "mPa·s"
        expr: base_mpas + span_mpas * ctx.production_rate
        params: {base_mpas: 780.0, span_mpas: 145.0}
        precision: 1
        range: [0, 1500]
        limits: {lo: 750, lolo: 700, hi: 980, hihi: 1050}
        export_metric: true
      Density:
        shape: ou_walk
        unit: "kg/m³"
        mean: 1042.0
        sigma: 3.5
        tau: 600.0
        precision: 2
        range: [900, 1200]
        limits: {lo: 1030, hi: 1055}
      Moisture:
        shape: ou_walk
        unit: "%"
        mean: 0.062
        sigma: 0.012
        tau: 900.0
        precision: 4
        range: [0, 1]
        limits: {hi: 0.1, hihi: 0.15}
      RefractiveIndex:
        shape: ou_walk
        unit: "1"
        mean: 1.4712
        sigma: 0.0008
        tau: 1200.0
        precision: 5
        range: [1.3, 1.6]
        limits: {lo: 1.468, hi: 1.474}
      NirIndex:
        shape: ou_walk
        unit: "1"
        mean: 0.842
        sigma: 0.018
        tau: 300.0
        precision: 4
        range: [0, 2]
        limits: {lo: 0.78, hi: 0.9}
      ColorB:
        # CIE b*: yellowing is the classic thermal-history defect, so this one tracks
        # ambient rather than rate.
        shape: derived
        unit: "1"
        expr: base_b + ambient_k * (ctx.ambient_temp_c - 20.0) / 10.0
        params: {base_b: 2.4, ambient_k: 0.35}
        precision: 3
        range: [-10, 30]
        limits: {hi: 4.0, hihi: 6.0}

  - id: LAB-01
    equipment: LAB-01
    # The Quality area, not a Production cell - so no ctx.state is available here and every
    # signal is either a walk or a discrete. That is honest: a lab result is a sample taken
    # at some earlier time, not a live reading of the line.
    target: {area: Quality, line: Lab, cell: LIMS_01}
    tier: lab
    signals:
      SampleId:
        shape: stepped
        unit: "1"
        choices: ["S-88201", "S-88202", "S-88203", "S-88204", "S-88205"]
        dwell_s: 1800.0
        param_type: Status
      Viscosity:
        shape: ou_walk
        unit: "mPa·s"
        mean: 845.0
        sigma: 42.0
        tau: 7200.0
        precision: 1
        range: [0, 1500]
        limits: {lo: 750, lolo: 700, hi: 980, hihi: 1050}
      HydroxylNumber:
        shape: ou_walk
        unit: mgKOH/g
        mean: 56.2
        sigma: 1.4
        tau: 7200.0
        precision: 2
        range: [0, 120]
        limits: {lo: 52.0, hi: 60.0}
      WaterContent:
        shape: ou_walk
        unit: ppm
        mean: 320.0
        sigma: 65.0
        tau: 7200.0
        precision: 1
        range: [0, 2000]
        limits: {hi: 500, hihi: 800}
      Acidity:
        shape: ou_walk
        unit: mgKOH/g
        mean: 0.042
        sigma: 0.011
        tau: 7200.0
        precision: 4
        range: [0, 1]
        limits: {hi: 0.08, hihi: 0.12}
      ResultStatus:
        # Weighted 9:1 rather than an even draw: a lab that failed half its samples would be
        # a plant in crisis, and the console's alarm view should look like a working plant.
        shape: stepped
        unit: "1"
        choices: ["Pass", "Fail"]
        weights: [9, 1]
        dwell_s: 1800.0
        param_type: Status

  # Spec 8.5 and 12: the two pre-existing PLC templates, moved from conf/settings.yaml's
  # `plc:` key with their ids, equipment names, base values, variations and Units of Measure
  # untouched. `sensors:` became `signals:` because that is the key expand_template reads;
  # nothing that reaches the broker changes. `shape` is omitted, so both fall through to
  # `noise` - the only behaviour the old generator had.
  #
  # No `target`, which means every cell in a `kind: production` area. That is exactly what
  # create_plc's cartesian product did, so the topic set is unchanged too.
  - id: "001"
    equipment: "G1"
    tier: process
    signals:
      Temperature:
        base_value: 75.0
        variation: 2.0
        unit: "°C"
      Pressure:
        base_value: 150.0
        variation: 5.0
        unit: "psi"

  - id: "002"
    equipment: "FillingMachine"
    tier: process
    signals:
      FlowRate:
        base_value: 450.0
        variation: 20.0
        unit: "L/min"
```

`id: "001"` stays quoted. Unquoted, YAML reads it as the integer `1`, `expand_template` builds `1@Dormagen.Production.Line1.Cell1`, and the MQTT client id becomes `uns-sim-1@…` — a change to what appears on the wire, in a task whose whole point is that nothing changes.

- [ ] **Step 4: Write `conf/simulator/safety.yaml`**

```yaml
# conf/simulator/safety.yaml
# Spec 8.6. Gas detection, stack emissions, the safety instrumented system, and the weather.
#
# WS-01 is the family's reason to exist. Its five ambient signals derive from ctx rather than
# running sines of their own, because SiteState already computes them from each site's
# ambient_mean_c and ambient_swing_c in plant.yaml. That is what makes the correlation
# checkable end to end: the wet bulb WS-01 publishes is the same wet bulb CT-01 sizes its
# approach against, so a warm humid stretch really does show up as a hotter tower supply and
# a higher chiller kW - on three different topics, from one number.

devices:
  - id: GD-01
    equipment: GD-01
    # No `site`: GD_Zone1 exists at both, and a gas detector reads the air in front of it -
    # there is nothing site-specific to parameterise.
    target: {area: Safety, line: GasDetection, cell: GD_Zone1}
    tier: process
    signals:
      Lel:
        # Spec 8.6: hi 10, hihi 20. Percent of the lower explosive limit, and the two
        # thresholds are the conventional alarm and trip points.
        shape: ou_walk
        unit: "%"
        mean: 1.8
        sigma: 0.9
        tau: 120.0
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 20.0}
        export_metric: true
      H2S:
        shape: ou_walk
        unit: ppm
        mean: 0.6
        sigma: 0.35
        tau: 180.0
        precision: 2
        range: [0, 200]
        limits: {hi: 5.0, hihi: 10.0}
      CO:
        shape: ou_walk
        unit: ppm
        mean: 3.4
        sigma: 1.6
        tau: 180.0
        precision: 2
        range: [0, 500]
        limits: {hi: 25.0, hihi: 50.0}
      O2:
        # Spec 8.6: lo 19.5. The only signal in the file whose alarm is on the low side -
        # oxygen depletion, not accumulation.
        shape: ou_walk
        unit: "%"
        mean: 20.9
        sigma: 0.08
        tau: 300.0
        precision: 2
        range: [0, 25]
        limits: {lo: 19.5, lolo: 18.0}
        export_metric: true
      VOC:
        shape: ou_walk
        unit: ppm
        mean: 2.1
        sigma: 1.1
        tau: 240.0
        precision: 2
        range: [0, 500]
        limits: {hi: 20.0, hihi: 50.0}
      DetectorFault:
        # p is per one-second tick, so 3e-6 is roughly one fault a fortnight per detector.
        # bernoulli_event publishes nothing on a quiet tick and its tier is 0.0 (on change),
        # so this costs one message per fault rather than one per second.
        shape: bernoulli_event
        unit: "1"
        p: 0.000003
        choices: ["SensorDrift", "BeamBlocked", "CalibrationDue"]
        tier: event
        param_type: Alarm
      ZoneAlarmState:
        shape: stepped
        unit: "1"
        choices: ["Clear", "Warning", "Alarm", "Inhibited"]
        weights: [40, 4, 1, 2]
        dwell_s: 600.0
        tier: status
        param_type: Status

  - id: GD-02
    equipment: GD-02
    # Dormagen only: GD_Zone2 has no Krefeld counterpart. Written out in full rather than
    # sharing a YAML anchor with GD-01, for the same reason as EM-01/EM-02 in Task 16 -
    # `range` and `limits` drive `status`, so a silently inherited threshold is a silently
    # wrong alarm.
    target: {area: Safety, line: GasDetection, cell: GD_Zone2}
    tier: process
    signals:
      Lel:
        shape: ou_walk
        unit: "%"
        mean: 2.6
        sigma: 1.2
        tau: 120.0
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 20.0}
        export_metric: true
      H2S:
        shape: ou_walk
        unit: ppm
        mean: 1.1
        sigma: 0.5
        tau: 180.0
        precision: 2
        range: [0, 200]
        limits: {hi: 5.0, hihi: 10.0}
      CO:
        shape: ou_walk
        unit: ppm
        mean: 4.8
        sigma: 2.1
        tau: 180.0
        precision: 2
        range: [0, 500]
        limits: {hi: 25.0, hihi: 50.0}
      O2:
        shape: ou_walk
        unit: "%"
        mean: 20.8
        sigma: 0.1
        tau: 300.0
        precision: 2
        range: [0, 25]
        limits: {lo: 19.5, lolo: 18.0}
        export_metric: true
      VOC:
        shape: ou_walk
        unit: ppm
        mean: 3.6
        sigma: 1.7
        tau: 240.0
        precision: 2
        range: [0, 500]
        limits: {hi: 20.0, hihi: 50.0}
      DetectorFault:
        shape: bernoulli_event
        unit: "1"
        p: 0.000003
        choices: ["SensorDrift", "BeamBlocked", "CalibrationDue"]
        tier: event
        param_type: Alarm
      ZoneAlarmState:
        shape: stepped
        unit: "1"
        choices: ["Clear", "Warning", "Alarm", "Inhibited"]
        weights: [30, 5, 2, 2]
        dwell_s: 600.0
        tier: status
        param_type: Status

  - id: CEMS-01
    equipment: CEMS-01
    # Stack_S1 is Dormagen-only. No `serves`: the stack is the boiler's, and the boiler's own
    # load already lives on BLR-01. Coupling the two would need a serves list pointing at
    # production lines, which would say something false about what a stack serves.
    target: {area: Safety, line: Emissions, cell: Stack_S1}
    tier: process
    signals:
      NOx:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 118.0
        sigma: 14.0
        tau: 600.0
        precision: 1
        range: [0, 600]
        limits: {hi: 200.0, hihi: 250.0}
        export_metric: true
      SOx:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 22.0
        sigma: 6.0
        tau: 900.0
        precision: 1
        range: [0, 600]
        limits: {hi: 100.0, hihi: 150.0}
      CO:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 34.0
        sigma: 11.0
        tau: 300.0
        precision: 1
        range: [0, 600]
        limits: {hi: 100.0, hihi: 150.0}
      Particulate:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 4.2
        sigma: 1.3
        tau: 900.0
        precision: 2
        range: [0, 100]
        limits: {hi: 20.0, hihi: 30.0}
      O2:
        shape: ou_walk
        unit: "%"
        mean: 5.4
        sigma: 0.7
        tau: 600.0
        precision: 2
        range: [0, 21]
        limits: {lo: 1.5, hi: 9.0}
      FlueGasFlow:
        shape: ou_walk
        unit: "Nm³/h"
        mean: 24500.0
        sigma: 1800.0
        tau: 600.0
        precision: 1
        range: [0, 40000]
      StackTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k
        params: {rise_k: 148.0}
        precision: 1
        range: [0, 350]
        limits: {hi: 210, hihi: 240}
      Opacity:
        shape: derived
        unit: "%"
        expr: base_pct + slope * Particulate
        params: {base_pct: 1.2, slope: 0.42}
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 20.0}
      NoxMassTotal:
        # mg/Nm³ times Nm³/h is mg/h; the 1e-6 converts to kg/s along with the 3600. Getting
        # this factor wrong is invisible in the number and obvious in the trend a month later.
        shape: counter
        unit: kg
        rate: NOx * FlueGasFlow * 0.000000001 / 3.6
        initial: 18400.0
        tier: meter
        precision: 3
        export_metric: true

  - id: SIS-01
    equipment: SIS-01
    target: {area: Safety, line: Emissions, cell: Stack_S1}
    # Spec 8.6 puts this device on the `status` tier: interlocks are step changes, and
    # republishing "Healthy" every five seconds says nothing new.
    tier: status
    signals:
      TripStatus:
        shape: stepped
        unit: "1"
        choices: ["Healthy", "PreTrip", "Tripped", "Bypassed"]
        weights: [60, 4, 1, 2]
        dwell_s: 1800.0
        param_type: Status
      InterlockStatus:
        shape: stepped
        unit: "1"
        choices: ["Enabled", "Overridden"]
        weights: [40, 1]
        dwell_s: 3600.0
        param_type: Status
      EStopStatus:
        shape: stepped
        unit: "1"
        choices: ["Released", "Pressed"]
        weights: [200, 1]
        dwell_s: 1800.0
        param_type: Status
      GuardDoorStatus:
        shape: stepped
        unit: "1"
        choices: ["Closed", "Open"]
        weights: [25, 1]
        dwell_s: 900.0
        param_type: Status
      SafetyDemandCount:
        # A safety demand is a genuinely rare event. 2e-7 per second is roughly one every
        # eight weeks, which is the point: a demand counter that ticks visibly means the
        # protection layer is being used as a control layer.
        shape: counter
        unit: "1"
        rate: 0.0000002
        initial: 6.0
        tier: meter
        precision: 0
      ProofTestDueDays:
        # Counts down, so it is a `derived` off nothing but its own constants - a counter
        # cannot decrease (Task 6 clamps a negative rate to zero, deliberately).
        shape: constant
        unit: d
        value: 214.0
        precision: 0
        range: [0, 730]
        limits: {lo: 30.0, lolo: 7.0}

  - id: WS-01
    equipment: WS-01
    # Both sites, one template: every signal reads ctx, and ctx is already per-site. This is
    # the payoff of deriving instead of generating - a second diurnal per quantity would have
    # needed a second template carrying Krefeld's amplitudes.
    target: {area: Safety, line: WeatherStation, cell: WS_01}
    tier: process
    signals:
      AmbientTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c
        precision: 2
        range: [-30, 50]
        export_metric: true
      RelativeHumidity:
        shape: derived
        unit: "%"
        expr: ctx.ambient_rh_pct
        precision: 1
        range: [0, 100]
      WetBulbTemp:
        # The number CT-01's approach temperature is written against. Same value, two
        # families, one source.
        shape: derived
        unit: "°C"
        expr: ctx.wet_bulb_temp_c
        precision: 2
        range: [-30, 40]
        export_metric: true
      DewPoint:
        # The Magnus-Tetens rule of thumb, accurate to about half a degree above 50 % RH,
        # which is where this plant's humidity sits. Deriving it from the same two ctx
        # values keeps it consistent with the wet bulb rather than merely near it.
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c - (100.0 - ctx.ambient_rh_pct) / 5.0
        precision: 2
        range: [-40, 40]
      WindSpeed:
        shape: derived
        unit: m/s
        expr: ctx.wind_speed_ms
        precision: 2
        range: [0, 40]
      WindDirection:
        # The one genuinely independent signal here: PlantContext models wind speed because
        # it affects the cooling tower, and has no reason to model direction.
        shape: ou_walk
        unit: "°"
        mean: 232.0
        sigma: 35.0
        tau: 1800.0
        precision: 1
        range: [0, 360]
      SolarIrradiance:
        # `diurnal` because PlantContext has no sunlight. elapsed_s is time since process
        # start, not time of day, so phase_s positions the curve against startup rather than
        # against noon - and `range` clamps the trough to zero, which is what makes a sine a
        # usable irradiance curve at all.
        shape: diurnal
        unit: "W/m²"
        mean: 210.0
        amplitude: 480.0
        period_s: 86400.0
        phase_s: 0.0
        noise: 18.0
        precision: 1
        range: [0, 1000]
      RainfallTotal:
        shape: counter
        unit: mm
        rate: 0.0000023
        initial: 812.4
        tier: meter
        precision: 2
      BarometricPressure:
        shape: derived
        unit: mbar
        expr: ctx.barometric_mbar
        precision: 2
        range: [900, 1080]
        limits: {lo: 970, hi: 1040}
```

`ProofTestDueDays` is `shape: constant`, not `counter`. A counter cannot count down — Task 6 clamps a negative rate to zero on purpose, so that a totaliser never runs backwards — and no shape in the catalogue decreases monotonically. A constant is the truthful option: the days-remaining figure genuinely changes only when somebody reschedules the proof test, which is a configuration change, not a signal.

- [ ] **Step 5: Run the tests**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -v`
Expected: all pass.

Triage, if they do not:
- `ValueError: unknown target selector(s)` names the key — the `target` blocks here use `area`, `line` and `cell` only.
- A `serves` load error from `production.yaml` means a `serves` list was added to a device on a production cell. None belongs there; those devices read `ctx.state` directly.
- `test_packml_state_code_maps_every_state` failing with a set difference means a PackML state was dropped from one of the two `map` blocks. There are seventeen, and both maps need all of them.
- A cycle error naming `MES-01` means a `derived` expression was pointed the wrong way — `TotalCount` reads the counters, `Quality` reads `TotalCount`, and `Oee` reads `Quality`, in that order.

- [ ] **Step 6: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add conf/simulator/production.yaml conf/simulator/safety.yaml 99_simulator/test/test_conf_files.py
git commit -m "feat(simulator): add the production and safety device families"
```

With all six families landed, `full` resolves to **55 devices and 427 signal instances** — spec §8's "~50 devices, ~400 signals". The per-template tables in `test_conf_files.py` are what make those two totals derived rather than asserted, so the next person to add a device changes one table entry and the totals follow.

---

