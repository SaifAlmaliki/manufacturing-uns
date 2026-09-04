# WTP Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Covestro PackML facility in `99_simulator` with one autonomous, hydraulically coupled water-treatment plant that publishes the drawing’s 19 tags under `AcmeWater/Site1/<Area>/Train1/<Tag>/WTP_<Template>/…`.

**Architecture:** `WTPProcess` owns sequencer + tank balance + lagged flows; YAML devices only publish `ctx.wtp.*`. `PlantClock` still ticks at 1 s. MQTT stays publish-only. Mapper topic filters switch to `AcmeWater/#`.

**Tech Stack:** Python ≥3.14, existing `uns_simulator` (pyyaml, fastapi, aiomqtt, pytest). No new runtime dependencies. Frontend: React + existing `ConsoleCard`.

**Spec:** `docs/superpowers/specs/2026-09-04-wtp-simulator-design.md`

## Global Constraints

- Topics remain eight ISA-95 levels. Cell = tag, equipment = poster name (`WTP_Valve`, `WTP_MotorDOL`, `WTP_VFD`, `WTP_Level`, `WTP_Basin`, `WTP_Flowmeter`, `WTP_Pressure`, `WTP_Analyzer`, `WTP_Filter`).
- Enterprise/site: `AcmeWater` / `Site1`. Line: `Train1`. Areas: `RawWater`, `Treatment`, `Filtration`, `Storage`, `Distribution`.
- No MQTT subscribe, no per-tag API writes. Command fields are read-only sequencer mirrors.
- No SF301, PID201, T401, V302–V314, M201, or other drawing-absent instances.
- `unit` required on every signal; dimensionless uses `"1"`. No separate `EngUnits` topic.
- `eval()`/`exec()` remain forbidden. Expressions stay on the existing AST walker.
- Test command from `99_simulator`: `uv run pytest test/<file>.py::test_name -v`. Format with `uv run ruff check .` and `uv run ruff format .` in `99_simulator` before each commit.
- Do not rewrite OEE units, explore-view Covestro placeholders, or SparkplugB.

### Canonical numbers (spec §7)

| Constant | Value |
|---|---|
| T101 / B101 / T201 capacity | 250 / 40 / 400 m³ |
| Initial level | 50 % |
| B101 side depth | 3.0 m (`PV` m = LevelPct/100 × 3) |
| Raw pump / VFD nameplate | 80 m³/h |
| Distribution Speed.SP | 87.5 (70 m³/h) |
| Flow lag τ | 5 s |
| VFD Speed.PV lag τ | 8 s |
| Duty rotate | 900 s, order P101 → P102 → P103 |
| Backwash | every 1800 s of Running, lasts 45 s |
| Fault p | 1/3600 per tick per running motor/VFD |
| Fault hold / ResetFault | 120 s / 30 s |
| LL | 10 % |
| Residual pressure | 0.2 barg |
| AIT101 | OU mean 7.2 (7.6 if DP101 off), σ 0.08, τ 600 s, clamp 6.5–8.5 |

---

## File Structure

**Replace in `99_simulator/src/uns_simulator/plant.py`:** PackML `LineState` / `LineTiming` / weather `SiteState` / `serves` on `DeviceView`. Keep `PlantClock`. Add `WTPProcess` and a thin `SiteState` that holds one `WTPProcess`.

**Modify:** `profiles.py` (`FAMILIES = ("wtp",)`, `build_plant_context` attaches WTP, drop PackML line overrides), `simulator.py` (`DeviceView(context, site)` only; `plant_snapshot` returns spec §8.1), `api.py` (`FamiliesRequest.wtp` only), `self_telemetry.py` (event names).

**Replace config:** delete `conf/simulator/{energy,water,utilities,asset_health,production,safety}.yaml`. Rewrite `plant.yaml`. Create `wtp.yaml`.

**Docs:** create `99_simulator/PROCESS.md`; rewrite plant-model sections of `99_simulator/README.md`.

**Platform:** `conf/settings.yaml` profile `wtp`, mapper topics `AcmeWater/#`, organization_name. HiveMQ Edge northbound → `test/uns/edge/sim` so it does not collide with WTP tags. `00_uns_config/test/test_loader.py` graphdb topics assertion.

**Frontend:** `11_frontend/src/types/simulator.ts`, `PlantStateInspector.tsx`.

**Tests:** new `99_simulator/test/test_wtp.py`; rewrite `test_plant.py`, `test_conf_files.py`, `test_volume.py`, `test_profiles.py` fixtures, `test_targeting.py` hierarchy, `test_api.py` families, `test_self_telemetry.py` plant path, `test_devices.py` / `test_metrics.py` DeviceView helpers.

---

### Task 1: WTPProcess hydraulics (no sequencer)

Actuators are set by the test (or later by the sequencer). This task only integrates tanks, lagged flows, and pressures.

**Files:**
- Modify: `99_simulator/src/uns_simulator/plant.py` (append new types; do not delete PackML yet)
- Test: `99_simulator/test/test_wtp.py`

**Interfaces:**
- Consumes: nothing from later tasks.
- Produces:
  - `FLOW_TAU_S = 5.0`, `SPEED_TAU_S = 8.0`, `RAW_PUMP_M3H = 80.0`, `DIST_NAMEPLATE_M3H = 80.0`, `LL_PCT = 10.0`, `RESIDUAL_BARG = 0.2`
  - `class ValveState` with `set_open(open_: bool) -> None`, fields `cmd_open`, `cmd_close`, `open_fb`, `close_fb`, `position`, `cycle_count`
  - `class MotorDOLState` fields `cmd_start`, `cmd_stop`, `reset_fault`, `running`, `fault`, `runtime_h`, `start_count`, `auto`
  - `class VFDState` fields `run_cmd`, `speed_sp`, `speed_pv`, `reset_fault`, `running`, `fault`, `runtime_h`, `start_count`
  - `class TankState` fields `capacity_m3`, `volume_m3`; properties `level_pct`
  - `class BasinState` same plus `depth_m = 3.0`; properties `level_pct`, `pv_m`
  - `class FilterState` fields `filter_run`, `backwash`, `in_service`
  - `class WTPProcess` attributes named by lowercase tag (`v101`, `p101`, …, `t101`, `b101`, `t201`, `f101`, `ft101_m3h`, `ft201_m3h`, `inlet_m3h`, `pt101`, `pt201`, `ait101`)
  - `WTPProcess.__init__(self, rng: random.Random, *, fault_p: float = 1.0 / 3600.0) -> None`
  - `WTPProcess.advance_hydraulics(self, dt: float) -> None`
  - `WTPProcess.advance_quality(self, dt: float) -> None` (can be a no-op until Task 2, but AIT101 must exist as a float)

- [ ] **Step 1: Write the failing tests**

Create `99_simulator/test/test_wtp.py`:

```python
import random

import pytest

from uns_simulator.plant import LL_PCT, RAW_PUMP_M3H, WTPProcess


def _wtp() -> WTPProcess:
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.v101.set_open(True)
    wtp.v201.set_open(True)
    wtp.v202.set_open(True)
    wtp.v301.set_open(True)
    wtp.p101.running = True
    wtp.p101.cmd_start = True
    wtp.f101.in_service = True
    wtp.p201.running = True
    wtp.p201.run_cmd = True
    wtp.p201.speed_sp = 87.5
    wtp.p201.speed_pv = 87.5
    return wtp


def test_tanks_start_half_full():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    assert wtp.t101.level_pct == pytest.approx(50.0)
    assert wtp.t101.volume_m3 == pytest.approx(125.0)
    assert wtp.b101.level_pct == pytest.approx(50.0)
    assert wtp.t201.level_pct == pytest.approx(50.0)
    assert wtp.b101.pv_m == pytest.approx(1.5)


def test_closed_v101_stops_inlet_and_t101_does_not_fill():
    wtp = _wtp()
    wtp.v101.set_open(False)
    before = wtp.t101.volume_m3
    for _ in range(30):
        wtp.advance_hydraulics(1.0)
    assert wtp.inlet_m3h == pytest.approx(0.0, abs=0.5)
    assert wtp.t101.volume_m3 <= before + 0.01


def test_open_inlet_and_running_raw_pump_fill_t101_when_outlet_is_blocked():
    wtp = _wtp()
    wtp.v201.set_open(False)
    wtp.v202.set_open(False)
    before = wtp.t101.volume_m3
    for _ in range(20):
        wtp.advance_hydraulics(1.0)
    assert wtp.inlet_m3h == pytest.approx(RAW_PUMP_M3H, abs=5.0)
    assert wtp.t101.volume_m3 > before


def test_both_distribution_pumps_stopped_drops_ft201_and_pt201():
    wtp = _wtp()
    for _ in range(20):
        wtp.advance_hydraulics(1.0)
    flowing = wtp.ft201_m3h
    pressured = wtp.pt201
    wtp.p201.running = False
    wtp.p202.running = False
    wtp.p201.speed_pv = 0.0
    wtp.p202.speed_pv = 0.0
    for _ in range(40):
        wtp.advance_hydraulics(1.0)
    assert flowing > 10.0
    assert wtp.ft201_m3h < flowing * 0.2
    assert wtp.pt201 < pressured
    assert wtp.pt201 == pytest.approx(0.2 + 0.015 * wtp.t201.level_pct, abs=0.3)


def test_v301_closed_stops_distribution_flow():
    wtp = _wtp()
    for _ in range(15):
        wtp.advance_hydraulics(1.0)
    wtp.v301.set_open(False)
    for _ in range(40):
        wtp.advance_hydraulics(1.0)
    assert wtp.ft201_m3h == pytest.approx(0.0, abs=1.0)


def test_backwash_isolates_filter_and_stops_ft101():
    wtp = _wtp()
    wtp.f101.in_service = False
    wtp.f101.backwash = True
    wtp.v201.set_open(False)
    wtp.v202.set_open(False)
    for _ in range(20):
        wtp.advance_hydraulics(1.0)
    assert wtp.ft101_m3h == pytest.approx(0.0, abs=1.0)


def test_level_interlock_stops_outlet_at_ll():
    wtp = _wtp()
    wtp.t101.volume_m3 = wtp.t101.capacity_m3 * (LL_PCT / 100.0) * 0.5
    for _ in range(10):
        wtp.advance_hydraulics(1.0)
    assert wtp.ft101_m3h == pytest.approx(0.0, abs=1.0)


def test_valve_set_open_counts_a_cycle():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.v101.set_open(True)
    wtp.v101.set_open(False)
    assert wtp.v101.cycle_count == 2
    assert wtp.v101.position == 0.0
    assert wtp.v101.close_fb is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest test/test_wtp.py -v` from `99_simulator`.

Expected: FAIL with `ImportError` or `cannot import name 'WTPProcess'`.

- [ ] **Step 3: Implement hydraulics**

Append to `plant.py` (keep existing PackML classes). Required behaviour:

```python
def _approach(value: float, target: float, tau_s: float, dt: float) -> float:
    ratio = min(1.0, dt / max(tau_s, 1e-6))
    return value + (target - value) * ratio


class ValveState:
    def __init__(self) -> None:
        self.cmd_open = False
        self.cmd_close = True
        self.open_fb = False
        self.close_fb = True
        self.position = 0.0
        self.cycle_count = 0

    def set_open(self, open_: bool) -> None:
        changed = self.open_fb != open_
        self.cmd_open = open_
        self.cmd_close = not open_
        self.open_fb = open_
        self.close_fb = not open_
        self.position = 100.0 if open_ else 0.0
        if changed:
            self.cycle_count += 1


class MotorDOLState:
    def __init__(self) -> None:
        self.cmd_start = False
        self.cmd_stop = True
        self.reset_fault = False
        self.running = False
        self.fault = False
        self.runtime_h = 0.0
        self.start_count = 0
        self.auto = True


class VFDState:
    def __init__(self) -> None:
        self.run_cmd = False
        self.speed_sp = 0.0
        self.speed_pv = 0.0
        self.reset_fault = False
        self.running = False
        self.fault = False
        self.runtime_h = 0.0
        self.start_count = 0


class TankState:
    def __init__(self, capacity_m3: float, initial_pct: float = 50.0) -> None:
        self.capacity_m3 = capacity_m3
        self.volume_m3 = capacity_m3 * initial_pct / 100.0

    @property
    def level_pct(self) -> float:
        return 100.0 * self.volume_m3 / self.capacity_m3 if self.capacity_m3 else 0.0

    def add_m3(self, delta: float) -> None:
        self.volume_m3 = min(self.capacity_m3, max(0.0, self.volume_m3 + delta))


class BasinState(TankState):
    def __init__(self, capacity_m3: float, depth_m: float = 3.0, initial_pct: float = 50.0) -> None:
        super().__init__(capacity_m3, initial_pct)
        self.depth_m = depth_m

    @property
    def pv_m(self) -> float:
        return self.level_pct / 100.0 * self.depth_m


class FilterState:
    def __init__(self) -> None:
        self.filter_run = True
        self.backwash = False
        self.in_service = True
```

`WTPProcess.__init__` constructs `v101,v201,v202,v301`, `p101,p102,p103,dp101`, `p201,p202`, tanks `t101=250`, `b101=40`, `t201=400`, `f101=FilterState()`, flows `inlet_m3h=ft101_m3h=ft201_m3h=0`, `pt101=pt201=RESIDUAL_BARG`, `ait101=7.2`.

`advance_hydraulics(dt)`:

1. `raw_on = any(p.running and not p.fault for p in (p101,p102,p103))`
2. `inlet_target = RAW_PUMP_M3H if v101.open_fb and raw_on and t101.level_pct < 100.0 else 0.0`
3. `inlet_m3h = _approach(inlet_m3h, inlet_target, FLOW_TAU_S, dt)`
4. Filter forward allowed iff `v201.open_fb and v202.open_fb and f101.in_service and not f101.backwash`
5. `ft101_target = RAW_PUMP_M3H if t101.level_pct > LL_PCT and filter_forward else 0.0`
6. `ft101_m3h = _approach(...)`
7. `b101` outlet = `ft101_m3h` if filter_forward else 0 (same stream)
8. Integrate: `t101.add_m3((inlet_m3h - ft101_m3h) * dt / 3600.0)`; `b101.add_m3((ft101_m3h - b101_out) * dt / 3600.0)` with `b101_out = ft101_m3h` when filter_forward else 0
9. Filtrate into T201: `filtrate = ft101_m3h if filter_forward else 0`
10. Each VFD contribution: `DIST_NAMEPLATE_M3H * speed_pv/100` if `running and not fault` else 0. `speed_pv = _approach(speed_pv, speed_sp if running else 0.0, SPEED_TAU_S, dt)`
11. `ft201_target = sum(contributions) if v301.open_fb else 0`; lag with FLOW_TAU_S
12. `t201.add_m3((filtrate - ft201_m3h) * dt / 3600.0)`
13. If T201 or T101 would go below LL on outlet, zero that outlet target next approach (already gated by LL_PCT)
14. `pt101 = RESIDUAL_BARG + 0.015 * t101.level_pct + (1.8 if raw_on else 0.0)`
15. `pt201 = RESIDUAL_BARG + 0.015 * t201.level_pct + (2.2 * (ft201_m3h / DIST_NAMEPLATE_M3H))`
16. `dp101.running` is not set here (sequencer). Hydraulics do not require DP101.
17. Runtime: if motor.running: `runtime_h += dt/3600`

If T101 is at 100 %, inlet_target is 0 even if pumps run.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest test/test_wtp.py -v` from `99_simulator`.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 99_simulator/src/uns_simulator/plant.py 99_simulator/test/test_wtp.py
git commit -m "feat(simulator): add WTP hydraulic mass balance"
```

---

### Task 2: Autonomous sequencer, quality, snapshot

**Files:**
- Modify: `99_simulator/src/uns_simulator/plant.py` (`WTPProcess`)
- Modify: `99_simulator/test/test_wtp.py`

**Interfaces:**
- Consumes: `WTPProcess.advance_hydraulics` from Task 1.
- Produces:
  - `WTPProcess.mode: str` (`"Running"` | `"Backwash"`)
  - `WTPProcess.duty_raw_pump: str` (`"P101"` etc.)
  - `WTPProcess.lead_dist_pump: str`
  - `WTPProcess.tick(self, dt: float) -> list[str]` — sequencer, then hydraulics, then quality; returns event names
  - `WTPProcess.snapshot(self) -> dict[str, Any]` matching spec §8.1 inner fields (caller adds enterprise/site)
  - `WTPProcess.advance_sequencer(self, dt: float) -> list[str]`
  - Events: `"DutyP102"`, `"Backwash"`, `"Running"`, `"FaultP101"` (tag in the name)

- [ ] **Step 1: Write the failing tests** (append to `test_wtp.py`)

```python
def test_tick_starts_in_running_with_one_duty_raw_pump():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    assert wtp.mode == "Running"
    running = [name for name in ("p101", "p102", "p103") if getattr(wtp, name).running]
    assert running == ["p101"]
    assert wtp.v101.open_fb is True
    assert wtp.p201.running is True
    assert wtp.p201.speed_sp == pytest.approx(87.5)
    assert wtp.p202.running is False
    assert wtp.p202.speed_sp == 0.0
    assert wtp.dp101.running is True  # after hydraulics produce b101 outlet; allow a few ticks
    for _ in range(20):
        wtp.tick(1.0)
    assert wtp.dp101.running is True


def test_duty_rotates_p101_to_p102_after_900s():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    events = []
    for _ in range(901):
        events.extend(wtp.tick(1.0))
    assert wtp.p101.running is False
    assert wtp.p102.running is True
    assert "DutyP102" in events


def test_backwash_closes_filter_valves_and_returns():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    events = []
    for _ in range(1801):
        events.extend(wtp.tick(1.0))
    assert "Backwash" in events
    assert wtp.mode == "Backwash"
    assert wtp.f101.backwash is True
    assert wtp.v201.open_fb is False
    assert wtp.ft101_m3h == pytest.approx(0.0, abs=2.0)
    for _ in range(45):
        events.extend(wtp.tick(1.0))
    assert wtp.mode == "Running"
    assert "Running" in events
    assert wtp.v201.open_fb is True


def test_fault_on_duty_pump_starts_the_next():
    wtp = WTPProcess(random.Random(0), fault_p=1.0)
    wtp.tick(1.0)
    assert wtp.p101.fault is True
    assert wtp.p101.running is False
    assert wtp.p102.running is True


def test_cmd_start_stays_true_while_sequencer_wants_the_pump_even_if_faulted():
    wtp = WTPProcess(random.Random(0), fault_p=1.0)
    wtp.tick(1.0)
    assert wtp.p101.fault is True
    assert wtp.p101.running is False
    assert wtp.p101.cmd_start is True


def test_snapshot_has_spec_keys():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    snap = wtp.snapshot()
    assert snap["mode"] == "Running"
    assert snap["filter_mode"] == "InService"
    assert snap["duty_raw_pump"] == "P101"
    assert snap["lead_dist_pump"] == "P201"
    assert set(snap["tanks"]) == {"T101", "B101", "T201"}
    assert set(snap["flows_m3h"]) == {"inlet", "FT101", "FT201"}
    assert set(snap["pressures_barg"]) == {"PT101", "PT201"}


def test_ait101_stays_in_band():
    wtp = WTPProcess(random.Random(1), fault_p=0.0)
    values = []
    for _ in range(500):
        wtp.tick(1.0)
        values.append(wtp.ait101)
    assert min(values) >= 6.5
    assert max(values) <= 8.5
```

Fix `test_tick_starts_in_running...` so DP101 is asserted after 20 ticks only (remove the first `assert wtp.dp101.running is True`).

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest test/test_wtp.py::test_duty_rotates_p101_to_p102_after_900s test/test_wtp.py::test_backwash_closes_filter_valves_and_returns -v`

Expected: FAIL (`tick` missing or sequencer not rotating).

- [ ] **Step 3: Implement sequencer + quality + snapshot**

`tick(dt)`:

```python
def tick(self, dt: float) -> list[str]:
    events = self.advance_sequencer(dt)
    self.advance_hydraulics(dt)
    self.dp101.running = self.ft101_m3h > 1.0 and not self.dp101.fault
    self.dp101.cmd_start = self.ft101_m3h > 1.0
    self.dp101.cmd_stop = not self.dp101.cmd_start
    self.advance_quality(dt)
    return events
```

`advance_sequencer`:

- On first tick (or `__init__` end): `mode="Running"`, `v101/v201/v202/v301.set_open(True)`, start P101 (`_start_motor`), stop P102/P103, start P201 at SP 87.5, stop P202 SP 0, `f101.in_service=True`, `backwash=False`, `filter_run=True`. `_start_motor` sets `cmd_start=True`, `cmd_stop=False`, `running=not fault`, increments `start_count` on rising edge of running.
- Accumulate `running_s` only while `mode=="Running"`. At `>= 900` rotate duty, emit `DutyP102` etc., reset a separate `duty_s` (or reuse modulo). Spec: rotate every 900 s — use `duty_s` independent of backwash. Pause `duty_s` during Backwash.
- At `running_s >= 1800`: enter Backwash 45 s, emit `"Backwash"`, close V201/V202, `f101.backwash=True`, `in_service=False`, `filter_run=False`. After 45 s: reopen V201/V202, restore filter flags, `mode="Running"`, emit `"Running"`, set `running_s=0`.
- Faults: for each running motor/VFD, if `rng.random() < fault_p`: latch fault, `running=False`, emit `FaultP101`. Keep `cmd_start`/`run_cmd` as sequencer intent. After 120 s clear fault, `reset_fault=True` for 30 s then False. On raw-pump fault, start next in `(p101,p102,p103)` that is not faulted. On P201 fault, start P202 at 87.5.
- Interlocks: if not `v101.open_fb`, stop raw pumps (`running=False`) but keep cmd mirrors if sequencer still wants inlet (in Running, V101 is open — tests that close V101 call `advance_hydraulics` only). Sequencer does not close V101.
- Lead pump: `lead_dist_pump` is P201 unless P201.fault then P202.

`advance_quality`: OU on `ait101` with mean `7.2 if dp101.running else 7.6`, σ 0.08, τ 600, clamp 6.5–8.5. Same `_mean_reverting` helper already in `plant.py` (reuse it; if Task 3 later deletes it, copy a private `_ou` onto `WTPProcess`).

`snapshot()` returns dict with `mode`, `filter_mode` (`"Backwash"` if `f101.backwash` else `"InService"`), `duty_raw_pump`, `lead_dist_pump`, `tanks` (T101/B101/T201 each `{level_pct, volume_m3, capacity_m3}` rounded), `flows_m3h`, `pressures_barg`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest test/test_wtp.py -v` from `99_simulator`.

Expected: PASS. If `test_fault_on_duty_pump_starts_the_next` is racy, seed `Random(0)` and `fault_p=1.0` so the first running pump faults on the first `random()` call — call `rng.random()` only for faults, in pump order p101, p102, p103, p201, p202, dp101.

- [ ] **Step 5: Commit**

```bash
git add 99_simulator/src/uns_simulator/plant.py 99_simulator/test/test_wtp.py
git commit -m "feat(simulator): add WTP sequencer, quality, and plant snapshot"
```

---

### Task 3: Replace PackML world with WTP DeviceView

**Files:**
- Modify: `99_simulator/src/uns_simulator/plant.py` — delete `LineState`, `LineTiming`, `PACKML_STATES`, weather/`serves` on `DeviceView`. `SiteState` holds `wtp: WTPProcess` and `tick` calls `wtp.tick`. `PlantContext.add_site` creates that. `PlantContext.tick` yields `(site, "Train1", event)` for each event. Remove `add_line`, `resolve_line`, `resolve_serves`.
- Modify: `99_simulator/src/uns_simulator/simulator.py` — `DeviceView(self.profile.context, spec.path.site)`; `plant_snapshot` as spec §8.1; drop `PRODUCTION_KIND` line logic.
- Modify: `99_simulator/src/uns_simulator/profiles.py` — `build_plant_context` only `add_site`; delete `validate_line_overrides` usage of PackML; `FAMILIES` still old until Task 4 (keep loading old YAML until Task 5, OR this task will break `load_profile` of current files). **Do this task in the same commit window as Task 4–5 if tests cannot go red across commits.** Prefer: finish Task 3 call-site updates so `uv run pytest test/test_wtp.py test/test_signals.py test/test_expressions.py` stay green, then immediately Task 4–5 in the next tasks. `test_plant.py` is rewritten here.
- Modify call sites: `test_devices.py` `_view`, `test_metrics.py`, `test_main.py` if it uses `on_transition`.
- Rewrite: `99_simulator/test/test_plant.py` — only clock + DeviceView.wtp + context.tick events. Delete PackML tests.

**Interfaces:**
- Consumes: `WTPProcess` from Tasks 1–2.
- Produces:
  - `DeviceView.__init__(self, context: PlantContext, site: str) -> None`
  - `DeviceView.wtp -> WTPProcess`
  - `DeviceView.site -> str`
  - `PlantContext.snapshot() -> dict` with keys `enterprise` (set on context), `site`, plus `WTPProcess.snapshot()`
  - `PlantContext.add_site(self, name: str) -> SiteState` — no ambient kwargs
  - `PlantClock` unchanged

- [ ] **Step 1: Rewrite `test_plant.py` as the failing contract**

Replace the file with:

```python
import random

from uns_simulator.plant import DeviceView, PlantClock, PlantContext, WTPProcess


def test_device_view_exposes_wtp():
    ctx = PlantContext(global_seed=7)
    ctx.add_site("Site1")
    ctx.tick(1.0)
    view = DeviceView(ctx, "Site1")
    assert view.wtp is ctx.sites["Site1"].wtp
    assert view.wtp.p101.running is True


def test_context_tick_emits_train_events_on_duty_rotate():
    ctx = PlantContext(global_seed=7)
    ctx.add_site("Site1")
    ctx.sites["Site1"].wtp.fault_p = 0.0
    seen = []
    for _ in range(901):
        seen.extend(ctx.tick(1.0))
    assert ("Site1", "Train1", "DutyP102") in seen


def test_clock_forwards_transitions():
    ctx = PlantContext(global_seed=7)
    ctx.add_site("Site1")
    ctx.sites["Site1"].wtp.fault_p = 0.0
    clock = PlantClock(ctx)
    seen = []
    clock.on_transition(lambda site, line, state: seen.append((site, line, state)))
    for _ in range(901):
        clock.advance()
    assert any(event[2].startswith("Duty") for event in seen)


def test_context_snapshot_matches_control_api_shape():
    ctx = PlantContext(global_seed=7)
    ctx.enterprise = "AcmeWater"
    ctx.add_site("Site1")
    ctx.tick(1.0)
    snap = ctx.snapshot()
    assert snap["enterprise"] == "AcmeWater"
    assert snap["site"] == "Site1"
    assert "tanks" in snap
    assert "sites" not in snap
```

Give `WTPProcess` a public `fault_p` attribute (already a ctor arg — store as `self.fault_p`). Give `PlantContext` `enterprise: str = "AcmeWater"` settable.

- [ ] **Step 2: Run `test_plant.py` — expect FAIL** on `DeviceView` signature / missing `wtp`.

- [ ] **Step 3: Implement** the `plant.py` and `DeviceView` changes. `PlantContext.tick`:

```python
def tick(self, dt: float) -> list[tuple[str, str, str]]:
    self.sim_time_s += dt
    out: list[tuple[str, str, str]] = []
    for site_name, site in self.sites.items():
        for event in site.wtp.tick(dt):
            out.append((site_name, "Train1", event))
    return out
```

`PlantContext.snapshot`: merge `{"enterprise": self.enterprise, "site": next(iter(self.sites))}` with that site's `wtp.snapshot()`. One-site plant; if no sites, `{"enterprise": self.enterprise, "site": None}`.

Update `simulator.create_signal_devices`:

```python
view = DeviceView(self.profile.context, spec.path.site)
```

Update `simulator.plant_snapshot`:

```python
return self.profile.context.snapshot()
```

Update `test_devices.py` `_view`:

```python
def _view():
    context = PlantContext(global_seed=7)
    context.add_site("Site1")
    context.tick(1.0)
    return DeviceView(context, "Site1")
```

Same pattern for `test_metrics.py`. Drop `LineTiming` imports.

`test_main.py` transition callback: still `(site, line, state)` — keep.

- [ ] **Step 4: Run** `uv run pytest test/test_plant.py test/test_wtp.py test/test_devices.py test/test_metrics.py test/test_signals.py test/test_expressions.py -v`

Expected: those pass. `test_conf_files.py` / `test_profiles.py` / `test_targeting.py` / `test_volume.py` may still fail until Tasks 4–5 — **do not commit a red default suite**. If they fail, continue immediately to Task 4 without committing, or commit only if you temporarily skip those modules (do not skip). **Preferred: land Tasks 3–6 as one logical series; commit Task 3 only if `pytest test/ -q` is green.** If Task 3 alone cannot be green, do not commit until Task 6.

Practical sequence: implement Task 3 code, then Task 4–6 in the same working tree, then one commit per task once the whole suite is green — or commit Task 3 with plant tests only if CI runs the whole folder (it does). **So Tasks 3–6 are one implementer session with four commits after the suite is green, or four commits if you keep the old YAML loading until Task 5.**

Keep `build_plant_context` working: if it still calls `add_line`, change it now to:

```python
def build_plant_context(paths, raw_plant, seed):
    context = PlantContext(global_seed=seed)
    context.enterprise = str((raw_plant.get("enterprise") or "AcmeWater"))
    # enterprise also comes from hierarchy — set in load_profile from raw["hierarchy"]["enterprise"]
    for path in paths:
        if path.site not in context.sites:
            context.add_site(path.site)
    return context
```

Set `context.enterprise` from hierarchy in `load_profile` after `build_plant_context`.

Remove `validate_line_overrides` call from `load_profile` (delete the function).

- [ ] **Step 5: Commit** only when `uv run pytest test/test_plant.py test/test_wtp.py -v` passes. If the rest of `test/` is red, proceed to Task 4 before committing.

```bash
git add 99_simulator/src/uns_simulator/plant.py 99_simulator/src/uns_simulator/simulator.py 99_simulator/src/uns_simulator/profiles.py 99_simulator/test/test_plant.py 99_simulator/test/test_devices.py 99_simulator/test/test_metrics.py
git commit -m "refactor(simulator): replace PackML plant context with WTP DeviceView"
```

---

### Task 4: Profile `wtp` only

**Files:**
- Modify: `99_simulator/src/uns_simulator/profiles.py` — `FAMILIES: tuple[str, ...] = ("wtp",)`
- Modify: `99_simulator/src/uns_simulator/api.py` — `FamiliesRequest` only `wtp: bool | None = None`
- Modify: `99_simulator/test/test_profiles.py` — fixtures use one site `Site1`, family `wtp`, no `serves`
- Modify: `99_simulator/test/test_api.py` — `STATUS["families"] = {"wtp": True}`, `available_profiles: ["wtp"]`, PUT families `{"wtp": False}`
- Modify: `99_simulator/test/test_simulator.py` — family loop uses `FAMILIES`

**Interfaces:**
- Consumes: `FAMILIES` as `("wtp",)`.
- Produces: profile name `wtp` is the only valid `profiles:` key once YAML exists (Task 5).

- [ ] **Step 1: Change `test_profiles.py` assertion**

```python
assert FAMILIES == ("wtp",)
```

Replace `RAW` hierarchy in that file with AcmeWater/Site1/RawWater/Train1/V101 (minimal) so `load_profile` tests that do not use disk still work. Include `"profiles": {"wtp": {"tier_scale": 1.0, "sites": ["Site1"], "families": ["wtp"]}}` and `"wtp": {"devices": []}`.

- [ ] **Step 2: Run `test_profiles.py` — FAIL** on FAMILIES tuple.

- [ ] **Step 3: Set `FAMILIES = ("wtp",)`.** Update `api.py` `FamiliesRequest`. Update `test_api.py` STATUS and the PUT test that sent `{"energy": False}` to `{"wtp": False}`. Update `FakeSimulator.config_snapshot` profiles to `["wtp"]`.

- [ ] **Step 4: Run** `uv run pytest test/test_profiles.py test/test_api.py -v`

Expected: pass if RAW fixtures updated. `test_conf_files.py` still needs Task 5–6.

- [ ] **Step 5: Commit** with Task 5 if conf files would break CI; otherwise:

```bash
git add 99_simulator/src/uns_simulator/profiles.py 99_simulator/src/uns_simulator/api.py 99_simulator/test/test_profiles.py 99_simulator/test/test_api.py 99_simulator/test/test_simulator.py
git commit -m "feat(simulator): collapse sensor families to wtp"
```

---

### Task 5: Hierarchy and device YAML

**Files:**
- Create: `conf/simulator/wtp.yaml`
- Modify: `conf/simulator/plant.yaml`
- Delete: `conf/simulator/energy.yaml`, `water.yaml`, `utilities.yaml`, `asset_health.yaml`, `production.yaml`, `safety.yaml`

**Interfaces:**
- Consumes: `FAMILIES=("wtp",)`, targeting `area` + `cell`.
- Produces: 19 devices, topic prefix `AcmeWater/Site1/<Area>/Train1/<Tag>/WTP_<Template>`.

`plant.yaml` (complete):

```yaml
# Five-area WTP. Narrative: 99_simulator/PROCESS.md
enterprise: AcmeWater
sites:
  - name: Site1
    areas:
      - name: RawWater
        kind: production
        lines:
          - name: Train1
            cells: [V101, P101, P102, P103, T101, FT101, PT101]
      - name: Treatment
        kind: production
        lines:
          - name: Train1
            cells: [B101, DP101, AIT101]
      - name: Filtration
        kind: production
        lines:
          - name: Train1
            cells: [F101, V201, V202]
      - name: Storage
        kind: production
        lines:
          - name: Train1
            cells: [T201]
      - name: Distribution
        kind: production
        lines:
          - name: Train1
            cells: [P201, P202, FT201, PT201, V301]
plant: {}
profiles:
  wtp:
    tier_scale: 1.0
    sites: [Site1]
    families: [wtp]
```

Do **not** set `max_cells_per_line` (that would keep only V101).

`wtp.yaml` — every device `target: {area: <Area>, cell: <Tag>}`, `equipment` as poster name. Signals use `shape: stepped` + `source: ctx.wtp.<tag>.<field>` or `derived` + `expr: ctx.wtp.<tag>.<field>`. Booleans are fine as stepped. Tiers and `param_type` per spec §5–6.

Field map (Python attr → signal name):

| Signal | Attr | tier | param_type | unit |
|---|---|---|---|---|
| CmdOpen | cmd_open | status | Setpoint | 1 |
| CmdClose | cmd_close | status | Setpoint | 1 |
| OpenFB | open_fb | status | Status | 1 |
| CloseFB | close_fb | status | Status | 1 |
| Position | position | process | ProcessValue | % |
| CycleCount | cycle_count | meter | ProcessValue | 1 |
| CmdStart / CmdStop / ResetFault / Auto | cmd_start / cmd_stop / reset_fault / auto | status | Setpoint | 1 |
| Running / Fault | running / fault | status / **event** | Status | 1 |
| RuntimeH | runtime_h | meter | ProcessValue | h |
| StartCount | start_count | meter | ProcessValue | 1 |
| RunCmd | run_cmd | status | Setpoint | 1 |
| Speed.SP | speed_sp | status | Setpoint | % |
| Speed.PV | speed_pv | process | ProcessValue | % |
| PV (level %) | level_pct | process | ProcessValue | % |
| Capacity_m3 | capacity_m3 | meter | ProcessValue | m³ |
| Volume_m3 | volume_m3 | process | ProcessValue | m³ |
| PV (basin m) | pv_m | process | ProcessValue | m |
| LevelPct | level_pct | process | ProcessValue | % |
| PV (flow) | use `ctx.wtp.ft101_m3h` / `ft201_m3h` | process | ProcessValue | m³/h |
| Totalizer | integrate in process: add `ft101_total_m3` on WTPProcess in this task if missing (`+= ft101_m3h * dt / 3600`) | meter | ProcessValue | m³ |
| Reset | `constant` `value: false` | status | Setpoint | 1 |
| PV (pressure) | pt101 / pt201 | process | ProcessValue | barg |
| PV (AIT) | ait101 | process | ProcessValue | pH |
| FilterRun / Backwash / InService | f101.filter_run / backwash / in_service | status / **event for Backwash** / status | Status | 1 |

T101/T201 `PV` limits: `{lolo: 10, lo: 20, hi: 85, hihi: 95}`.

Example device (copy this pattern for all 19):

```yaml
devices:
  - id: V101
    equipment: WTP_Valve
    target: {area: RawWater, cell: V101}
    signals:
      CmdOpen: {shape: stepped, source: ctx.wtp.v101.cmd_open, unit: "1", tier: status, param_type: Setpoint}
      CmdClose: {shape: stepped, source: ctx.wtp.v101.cmd_close, unit: "1", tier: status, param_type: Setpoint}
      OpenFB: {shape: stepped, source: ctx.wtp.v101.open_fb, unit: "1", tier: status, param_type: Status}
      CloseFB: {shape: stepped, source: ctx.wtp.v101.close_fb, unit: "1", tier: status, param_type: Status}
      Position: {shape: derived, expr: ctx.wtp.v101.position, unit: "%", precision: 1, tier: process}
      CycleCount: {shape: derived, expr: ctx.wtp.v101.cycle_count, unit: "1", precision: 0, tier: meter}
```

V201/V202/V301: same with `ctx.wtp.v201` etc.

P101–P103 and DP101: MotorDOL attrs on `p101`… `dp101`. Fault `tier: event`.

P201/P202: VFD attrs. `Speed.SP` YAML key must be quoted: `"Speed.SP"`.

T101:

```yaml
  - id: T101
    equipment: WTP_Level
    target: {area: RawWater, cell: T101}
    signals:
      PV: {shape: derived, expr: ctx.wtp.t101.level_pct, unit: "%", precision: 1, range: [0, 100], limits: {lolo: 10, lo: 20, hi: 85, hihi: 95}, export_metric: true}
      Capacity_m3: {shape: derived, expr: ctx.wtp.t101.capacity_m3, unit: "m³", precision: 1, tier: meter}
      Volume_m3: {shape: derived, expr: ctx.wtp.t101.volume_m3, unit: "m³", precision: 2}
```

B101: `PV` → `pv_m` unit `m`; `LevelPct` → `level_pct`.

FT101: `PV` expr `ctx.wtp.ft101_m3h`; add `ft101_total_m3` / `ft201_total_m3` on `WTPProcess.advance_hydraulics`. `Totalizer` derived from that. `Reset: {shape: constant, value: 0, unit: "1", tier: status, param_type: Setpoint}` — constant false: use `value: 0` and treat as 0, or stepped from a `reset` attr always False. Use `shape: constant`, `value: 0`, `precision: 0`.

If `constant` with `value: 0` publishes a number not boolean, spec asked boolean false — use `stepped` `source: ctx.wtp.flow_reset` with `WTPProcess.flow_reset = False`.

PT101: `expr: ctx.wtp.pt101`, unit `barg`.

AIT101: `expr: ctx.wtp.ait101`, unit `pH`, limits `{lo: 6.5, hi: 8.5}`.

F101: three status/event signals from `ctx.wtp.f101.*`.

- [ ] **Step 1: Write `test_conf_files.py` expected tables first** (Task 6 Step 1) — or write YAML then immediately Task 6. Combined: after YAML exists, Task 6 tests fail until tables match.

- [ ] **Step 2: Write the files, delete the six old family files.**

- [ ] **Step 3: Add totalizer fields to `WTPProcess` if not present; keep `test_wtp.py` green.**

- [ ] **Step 4: `uv run pytest test/test_conf_files.py -v` will fail until Task 6 rewrites the tables — that is Task 6.**

- [ ] **Step 5: Commit YAML with Task 6** (do not leave EXPECTED_* pointing at Covestro templates).

---

### Task 6: Conf inventory, targeting, volume

**Files:**
- Modify: `99_simulator/test/test_conf_files.py`
- Modify: `99_simulator/test/test_targeting.py`
- Modify: `99_simulator/test/test_volume.py`
- Modify: `99_simulator/test/test_hierarchy.py` if it still expects Covestro paths from `plant.yaml`

**EXPECTED_SIGNAL_COUNT** (per template id, family `wtp`):

```python
EXPECTED_SIGNAL_COUNT = {
    "wtp": {
        "V101": 6, "V201": 6, "V202": 6, "V301": 6,
        "P101": 8, "P102": 8, "P103": 8, "DP101": 8,
        "P201": 8, "P202": 8,
        "T101": 3, "T201": 3, "B101": 2,
        "FT101": 3, "FT201": 3,
        "PT101": 1, "PT201": 1,
        "AIT101": 1, "F101": 3,
    }
}
EXPECTED_DEVICE_COUNT = {k: {i: 1 for i in v} for k, v in EXPECTED_SIGNAL_COUNT.items()}
```

Remove PackML / MES / `RETIRED_MES_SIGNALS` assertions. Add:

```python
def test_every_topic_prefix_is_acmewater_wtp():
    profile = load_profile(read_simulator_conf(CONF_DIR), "wtp")
    assert len(profile.devices) == 19
    for device in profile.devices:
        parts = device.topic_prefix.split("/")
        assert parts[0] == "AcmeWater"
        assert parts[1] == "Site1"
        assert parts[3] == "Train1"
        assert parts[4] == device.path.cell
        assert parts[5] == device.equipment
        assert parts[5].startswith("WTP_")
        assert parts[4] != parts[5]
```

Wait: `DeviceSpec` uses `.path.cell` and `.equipment`. Prefix is `enterprise/site/area/line/cell/equipment`. Assert `parts[4] == tag` and `parts[5] == equipment`.

Remove `PACKML_STATES` import.

`test_volume.py`:

```python
def test_the_shipped_default_profile_is_wtp(settings_doc):
    assert settings_doc["simulator"]["simulation"]["profile"] == "wtp"

def test_wtp_stays_under_the_volume_ceiling(raw):
    profile = load_profile(raw, "wtp")
    total = sum(profile.messages_per_second().values())
    assert 1.0 < total < 40.0
```

Delete `small`/`full` tests. Settings test `enterprise == "AcmeWater"` (Task 7 may land the settings change in the same commit).

`test_targeting.py`: replace `PRODUCTION` fixtures with AcmeWater paths; drop utility/`serves` cases that no longer apply. Keep `matches_target` unit tests (they are generic).

- [ ] **Step 1: Write the new assertions (they fail on old YAML / old settings).**
- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: YAML from Task 5 + settings profile from Task 7 as needed.**
- [ ] **Step 4: `uv run pytest test/test_conf_files.py test/test_volume.py test/test_targeting.py -v` PASS.**
- [ ] **Step 5: Commit**

```bash
git add conf/simulator 99_simulator/test/test_conf_files.py 99_simulator/test/test_volume.py 99_simulator/test/test_targeting.py 99_simulator/src/uns_simulator/plant.py
git commit -m "feat(simulator): ship the five-area WTP device inventory"
```

---

### Task 7: Platform config so mappers ingest AcmeWater

**Files:**
- Modify: `conf/settings.yaml` — `platform.organization_name: AcmeWater`, `display_name: Acme Water UNS`, `simulator.simulation.profile: wtp`, `simulator.hierarchy.enterprise: AcmeWater` with a minimal Site1 fallback, graphdb/historian/kafka_mapper `CovestroAG/#` → `AcmeWater/#`
- Modify: `00_uns_config/test/test_loader.py` — graphdb topics list
- Modify: `conf/hivemq/config.xml` — northbound topic `test/uns/edge/sim` (already on mapper `test/uns/#`, not a WTP tag)
- Modify: `99_simulator/test/test_self_telemetry.py` — matcher examples may keep `CovestroAG/#` as a generic wildcard test **or** switch to `AcmeWater/#`; plant telemetry sample path `plant/Site1/Train1/state`

- [ ] **Step 1: Change `test_loader.py` expected topics to `["test/uns/#", "AcmeWater/#", "spBv1.0/uns_group/#"]`. Run — FAIL.**
- [ ] **Step 2: Edit `settings.yaml`.**
- [ ] **Step 3: Run** `uv run pytest 00_uns_config/test/test_loader.py 99_simulator/test/test_volume.py 99_simulator/test/test_self_telemetry.py -v` from repo root as appropriate (`cd 00_uns_config` / `cd 99_simulator`).
- [ ] **Step 4: Commit**

```bash
git add conf/settings.yaml conf/hivemq/config.xml 00_uns_config/test/test_loader.py 99_simulator/test/test_self_telemetry.py
git commit -m "chore(conf): point UNS ingest and default profile at AcmeWater WTP"
```

---

### Task 8: Control API plant body + unknown profile

**Files:**
- Modify: `99_simulator/src/uns_simulator/simulator.py` `plant_snapshot` (already context.snapshot in Task 3)
- Modify: `99_simulator/test/test_simulator.py` / `test_api.py` FakeSimulator `plant_snapshot` to spec shape
- Confirm `PUT /simulator/profile` `{"profile":"small"}` → 422 `field: profile`

- [ ] **Step 1: Test in `test_simulator.py`:**

```python
def test_plant_snapshot_is_the_wtp_body():
    sim = _sim()
    snap = sim.plant_snapshot()
    assert snap["enterprise"] == "AcmeWater"
    assert "T101" in snap["tanks"]
    assert "sites" not in snap
```

```python
async def test_unknown_profile_is_422_profile():
    # via API client as existing profile tests do
```

Use the existing FastAPI client pattern in `test_api.py` if profile PUT is already tested — change available profiles to `wtp` only.

- [ ] **Step 2: Run fail if snapshot still wraps `sites`.**
- [ ] **Step 3: Fix snapshot.**
- [ ] **Step 4: Pass + commit**

```bash
git add 99_simulator/src/uns_simulator/simulator.py 99_simulator/test/test_simulator.py 99_simulator/test/test_api.py
git commit -m "feat(simulator): serve WTP snapshot from GET /simulator/plant"
```

---

### Task 9: PROCESS.md and README

**Files:**
- Create: `99_simulator/PROCESS.md`
- Modify: `99_simulator/README.md`
- Modify: `99_simulator/test/test_conf_files.py` — `assert (Path(__file__).resolve().parents[1] / "PROCESS.md").is_file()`

`PROCESS.md` must include: five-area narrative; tag table from spec §6; coupling (V101, pumps, backwash, LL); sequencer (duty 900 s, backwash 1800/45, faults); example topics (one per template class); not modelled (chemistry, commands, second filter, PID). Point YAML headers at this file.

README: delete Dormagen/`small`/`full`/PackML tables. Describe WTP + link PROCESS.md. Control API `GET /simulator/plant` is the WTP snapshot. Profile name `wtp`.

- [ ] **Step 1: Add the path assertion; run FAIL.**
- [ ] **Step 2: Write PROCESS.md and README.**
- [ ] **Step 3: Pass + commit**

```bash
git add 99_simulator/PROCESS.md 99_simulator/README.md conf/simulator/plant.yaml conf/simulator/wtp.yaml 99_simulator/test/test_conf_files.py
git commit -m "docs(simulator): describe the WTP process and tags"
```

---

### Task 10: Simulator console plant inspector

**Files:**
- Modify: `11_frontend/src/types/simulator.ts`
- Modify: `11_frontend/src/components/simulator/PlantStateInspector.tsx`

Replace `PlantLineState` / `PlantSiteState` / `PlantSnapshot` with:

```typescript
export interface PlantTankState {
  level_pct: number
  volume_m3: number
  capacity_m3: number
}

export interface PlantSnapshot {
  enterprise: string
  site: string
  mode: string
  filter_mode: string
  duty_raw_pump: string
  lead_dist_pump: string
  tanks: Record<string, PlantTankState>
  flows_m3h: Record<string, number>
  pressures_barg: Record<string, number>
}
```

Rewrite `PlantStateInspector` to use `ConsoleCard`: header `AcmeWater / Site1` + tick; KPI chips for `mode`, `filter_mode`, duty raw, lead VFD; a compact row of tank %; flows and pressures as mono figures. Running = emerald chip, Backwash = orange. No PackML table, no ambient/tariff.

Grep `11_frontend` for `PlantSnapshot` / `production_rate` / `plant?.sites` and update those types/usages.

- [ ] **Step 1: `npx tsc --noEmit` in `11_frontend` after type change — FAIL on inspector props.**
- [ ] **Step 2: Rewrite inspector.**
- [ ] **Step 3: `npx tsc --noEmit` PASS.**
- [ ] **Step 4: Commit**

```bash
git add 11_frontend/src/types/simulator.ts 11_frontend/src/components/simulator/PlantStateInspector.tsx
git commit -m "feat(console): show WTP tanks and duty on the simulator plant view"
```

---

### Task 11: Full simulator suite + leftover Covestro strings in 99_simulator

**Files:** any remaining `99_simulator/test` failures (`test_hierarchy.py` settings fallback, `test_simulator.py` profile `small`, seed tests that mention Dormagen).

- [ ] **Step 1: Run** `uv run pytest test/ -q` from `99_simulator`.
- [ ] **Step 2: Fix every failure. Do not skip PackML tests — they should already be gone.**
- [ ] **Step 3: Run** `uv run ruff check .` and `uv run ruff format .` in `99_simulator`.
- [ ] **Step 4: Commit leftovers**

```bash
git add 99_simulator
git commit -m "test(simulator): align remaining tests with the WTP plant"
```

---

## Spec coverage (self-review)

| Spec section | Task |
|---|---|
| §2 replace Covestro / 5 zones / drawing tags | 5–6 |
| §2 autonomous, no commands | 2, 5 (mirrors only) |
| §2 coupled hydraulics, AIT quality | 1–2 |
| §2 template fields read-only | 5 |
| §2 PROCESS.md | 9 |
| §4 DeviceView.wtp / clock | 3 |
| §5 topic shape, WTP_* equipment, param_type | 5–6 |
| §6 19 devices, cadence | 5–6 |
| §7 capacities, hydraulics, sequencer, faults | 1–2 |
| §8 API plant body, families, profile | 4, 8 |
| §8.2 frontend inspector | 10 |
| §8.3 self-telemetry path | 7 |
| §9 settings + mapper topics | 7 |
| §11 tests listed | 1–2, 6, 8, 9, 11 |
| §13 HiveMQ one-liner | 7 (`test/uns/edge/sim`) |

No command subscribe. No PID/SF301. Eight-level topics unchanged.
