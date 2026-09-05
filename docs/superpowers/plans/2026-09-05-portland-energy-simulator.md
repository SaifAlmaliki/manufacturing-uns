# Plant Portland Energy Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second simulator profile `portland` (Plant Portland energy mill) beside the default `wtp` plant, and switch the live UNS (Asset Model + graph current state) when the console applies that profile.

**Architecture:** `PortlandProcess` owns walks and residual allocation; YAML devices only publish `ctx.portland.*`. Profile `portland` is declared in `portland-plant.yaml` so `save_plant_tree` cannot strip it. After `PUT /simulator/profile`, the console calls `switchDemoPlant`, which reseeds Postgres from that file and `DETACH DELETE`s the other plant-file enterprise in Neo4j.

**Tech Stack:** Python ≥3.14, existing `uns_simulator` / `uns_graphql` / `uns_model` (pyyaml, fastapi, strawberry, pytest). No new runtime dependencies. Frontend: React + existing `ConsoleCard` / `CompactKpiRow`.

**Spec:** `docs/superpowers/specs/2026-09-05-portland-energy-simulator-design.md`

Part A (Tasks 1–5) is a working Portland publisher with WTP still the default. Part B (Tasks 6–9) is the client switch. Each part is independently testable.

## Global Constraints

- Do not delete or rewrite WTP YAML, `WTPProcess`, `PROCESS.md`, or the default `settings.yaml` profile `wtp`.
- Topics remain eight ISA-95 levels. Cell = tag. Equipment is `Energy_Meter` or `Energy_Allocated`.
- Enterprise/site/line: `PlantPortland` / `Site1` / `Mill1`. Areas: `Sources`, `Metering`, `ColdLocation`, `HotLocation`.
- `PV` unit `kW`, tier `energy` (15 s). `Totalizer` unit `kWh`, tier `meter` (900 s). No `Origin`, `Running`, or `Fault` topics.
- Wind and solar publish and do **not** enter `PlantTotal`. `PlantTotal = Grid + Storage + Heater`.
- `r_ac + r_cleaner` must equal 1.0 at load time (defaults `170/570` and `400/570`).
- `eval()`/`exec()` remain forbidden. Expressions stay on the existing AST walker.
- `unit` required on every signal.
- Simulator never opens Neo4j or Postgres. `switchDemoPlant` is GraphQL, admin-only.
- `saveHierarchy` still writes `plant.yaml` only. It must keep `PlantPortland/#` in mapper lists.
- Test simulator from `99_simulator`: `uv run pytest test/<file>.py::test_name -v`. Format with `uv run ruff check .` and `uv run ruff format .` in that module before each commit.
- Test GraphQL from `07_uns_graphql`: `uv run pytest test/<path>.py::test_name -v`.
- Test model from `09_uns_model`: `uv run pytest test/<file>.py::test_name -v`.
- Test frontend from `11_frontend`: `npx vitest run src/<path> -t "<name>"`.

### Canonical numbers (spec §7)

| Constant | Value |
|---|---|
| Grid / Wind / Solar peak / Storage out / Heater | 1000 / 800 / 200 / 400 / 600 kW |
| SharedHot nameplate | 200 kW |
| ColdHeater / ColdLighting / FurnaceCold on | 100 / 150 / 380 kW |
| Roughing on | 333 kW |
| Machine idle | ~10 kW |
| OU tau / sigma fraction | 120 s / 0.02 × nameplate |
| Machine dwell on / off | 600 s / 180 s |
| Hot shared / machines of untracked | 2/3 / 1/3 |
| Hot AC / lighting of shared sources | 2/3 / 1/3 |
| FurnaceHot / HotCleaner of machines rest | 2/3 / 1/3 |
| `R_AC` / `R_CLEANER` | 170/570 / 400/570 |

---

## File Structure

**Create:** `99_simulator/src/uns_simulator/portland.py`, `99_simulator/test/test_portland.py`, `conf/simulator/portland-plant.yaml`, `conf/simulator/portland.yaml`, `99_simulator/ENERGY.md`.

**Modify (simulator):** `plant.py` (`SiteState` / `PlantContext` / `DeviceView` grow a `portland` slot; do not delete WTP), `profiles.py` (`FAMILIES`, multi-file profile bind), `api.py` (`FamiliesRequest.portland`), `simulator.py` (snapshot branch, event line `Mill1`).

**Modify (platform):** `conf/settings.yaml` mapper topics; `09_uns_model/src/uns_model/hierarchy_io.py` (union of plant-file enterprises); `07_uns_graphql` graph delete + `switchDemoPlant` + `saveHierarchy` 409; auth tables.

**Modify (frontend):** `types/simulator.ts`, `PlantStateInspector.tsx`, `useSimulator.ts`, GraphQL client/queries.

**Docs:** `99_simulator/README.md`; one-line pointer in `PROCESS.md`.

---

### Task 1: PortlandProcess (walks, balance, allocation)

**Files:**
- Create: `99_simulator/src/uns_simulator/portland.py`
- Test: `99_simulator/test/test_portland.py`

**Interfaces:**
- Consumes: `_mean_reverting` — import from `uns_simulator.plant` (already public in that module).
- Produces:
  - `R_AC = 170.0 / 570.0`, `R_CLEANER = 400.0 / 570.0`
  - `class MachineWalk` fields `running: bool`, `kw: float`, `nameplate: float`, `idle_kw: float = 10.0`
  - `class PortlandProcess`
    - `__init__(self, rng: random.Random, *, r_ac: float = R_AC, r_cleaner: float = R_CLEANER) -> None`
    - Raises `ValueError` naming `r_ac`/`r_cleaner` if `abs(r_ac + r_cleaner - 1.0) > 1e-9`
    - Public kW: `grid_kw`, `wind_kw`, `solar_kw`, `storage_kw`, `heater_kw`, `shared_hot_kw`, `shared_meter_kw`, `inhouse_meter_kw`, `plant_total_kw`, `hot_total_kw`, `cold_total_kw`, `hot_untracked_kw`, `hot_shared_sources_kw`, `hot_machines_rest_kw`, `cold_heater_kw`, `cold_lighting_kw`, `cold_ac_kw`, `cold_cleaner_kw`, `furnace_hot_kw`, `hot_cleaner_kw`, `hot_ac_kw`, `hot_lighting_kw`
    - Matching `*_kwh` totalizers (start 0.0)
    - `furnace_cold: MachineWalk`, `roughing: MachineWalk`
    - `sim_time_s: float`
    - `tick(self, dt: float) -> list[str]`
    - `snapshot(self) -> dict[str, Any]` matching spec §8.1 **without** `enterprise`/`site` (PlantContext adds those)

- [ ] **Step 1: Write the failing tests**

Create `99_simulator/test/test_portland.py`:

```python
import math
import random

import pytest

from uns_simulator.portland import R_AC, R_CLEANER, PortlandProcess


def _p(*, r_ac: float = R_AC, r_cleaner: float = R_CLEANER) -> PortlandProcess:
    return PortlandProcess(random.Random(0), r_ac=r_ac, r_cleaner=r_cleaner)


def test_ratios_must_sum_to_one():
    with pytest.raises(ValueError, match="r_ac"):
        PortlandProcess(random.Random(0), r_ac=0.5, r_cleaner=0.6)


def test_nameplates_at_t0():
    p = _p()
    assert p.grid_kw == pytest.approx(1000.0)
    assert p.wind_kw == pytest.approx(800.0)
    assert p.storage_kw == pytest.approx(400.0)
    assert p.heater_kw == pytest.approx(600.0)
    assert p.shared_hot_kw == pytest.approx(200.0)
    assert p.cold_heater_kw == pytest.approx(100.0)
    assert p.cold_lighting_kw == pytest.approx(150.0)
    assert p.furnace_cold.kw == pytest.approx(380.0)
    assert p.roughing.kw == pytest.approx(333.0)
    assert p.furnace_cold.running is True
    assert p.roughing.running is True


def test_plant_total_excludes_wind_and_solar():
    p = _p()
    p.tick(1.0)
    assert p.plant_total_kw == pytest.approx(p.grid_kw + p.storage_kw + p.heater_kw)
    assert p.shared_meter_kw == pytest.approx(p.grid_kw + p.storage_kw)
    assert p.inhouse_meter_kw == pytest.approx(p.heater_kw)
    assert p.hot_total_kw == pytest.approx(p.shared_hot_kw + p.inhouse_meter_kw)
    assert p.cold_total_kw == pytest.approx(p.plant_total_kw - p.hot_total_kw)
    assert p.wind_kw + p.solar_kw != pytest.approx(0.0)
    assert p.plant_total_kw != pytest.approx(p.grid_kw + p.wind_kw + p.solar_kw + p.storage_kw + p.heater_kw)


def test_hot_leaves_partition_untracked():
    p = _p()
    p.tick(1.0)
    untracked = max(0.0, p.hot_total_kw - p.roughing.kw)
    assert p.hot_untracked_kw == pytest.approx(untracked)
    assert p.hot_ac_kw + p.hot_lighting_kw == pytest.approx(untracked * 2.0 / 3.0, rel=1e-6)
    assert p.furnace_hot_kw + p.hot_cleaner_kw == pytest.approx(untracked / 3.0, rel=1e-6)


def test_roughing_off_raises_allocated_hot_leaves():
    p = _p()
    p.tick(1.0)
    before = p.furnace_hot_kw
    p.roughing.running = False
    p.roughing.kw = 10.0
    p.tick(0.0)  # recompute only; implement tick so dt==0 still allocates
    assert p.hot_untracked_kw > 300.0
    assert p.furnace_hot_kw > before


def test_cold_untracked_split_uses_config_ratios():
    p = _p()
    p.tick(1.0)
    measured = p.cold_heater_kw + p.cold_lighting_kw + p.furnace_cold.kw
    untracked = max(0.0, p.cold_total_kw - measured)
    assert p.cold_ac_kw == pytest.approx(untracked * R_AC)
    assert p.cold_cleaner_kw == pytest.approx(untracked * R_CLEANER)


def test_measured_cold_overflow_zeros_allocated_cold():
    p = _p()
    p.cold_heater_kw = 10_000.0
    p.cold_lighting_kw = 10_000.0
    p.furnace_cold.kw = 10_000.0
    p.tick(0.0)
    assert p.cold_ac_kw == 0.0
    assert p.cold_cleaner_kw == 0.0


def test_totalizer_integrates_kw():
    p = _p()
    p.grid_kw = 3600.0
    p.tick(1.0)
    assert p.grid_kwh == pytest.approx(1.0)


def test_solar_is_near_zero_at_night_and_peaks_midday():
    p = _p()
    p.sim_time_s = 0.0  # implement noon = 12*3600
    p.tick(0.0)
    night = p.solar_kw
    p.sim_time_s = 12.0 * 3600.0
    p.tick(0.0)
    assert p.solar_kw > night
    assert p.solar_kw == pytest.approx(200.0, abs=1.0)


def test_snapshot_has_plant_total_not_tanks():
    body = _p().snapshot()
    assert "tanks" not in body
    assert "plant_total_kw" in body
    assert "leaves_kw" in body
    assert "machines_on" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest test/test_portland.py -v` from `99_simulator`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `uns_simulator.portland`

- [ ] **Step 3: Write minimal implementation**

Create `99_simulator/src/uns_simulator/portland.py`. Import `_mean_reverting` from `uns_simulator.plant`.

`tick(dt)` order:

1. If `dt > 0`: increment `sim_time_s`; OU-walk independents (grid, wind, storage≥0, heater, shared_hot, cold_heater, cold_lighting); walk machine nameplates when `running` else set `kw = idle_kw`; dwell-toggle machines every 600 s on / 180 s off (only when `dt > 0`).
2. Clamp `shared_hot_kw` to `[0, grid_kw + storage_kw]`.
3. `solar_kw = max(0.0, 100.0 + 100.0 * math.sin(2 * math.pi * (sim_time_s - 6 * 3600) / 86400))` so t=0 is night (~0) and t=12h is 200.
4. `shared_meter_kw = grid_kw + storage_kw`; `inhouse_meter_kw = heater_kw`; `plant_total_kw = grid + storage + heater`; `hot_total_kw = shared_hot + inhouse`; `cold_total_kw = plant_total - hot_total`.
5. If `roughing.kw > hot_total_kw`: `roughing.kw = hot_total_kw`.
6. Hot allocation formulas from spec §7.3.
7. Cold allocation formulas from spec §7.4 (overflow → allocated cold = 0).
8. If `dt > 0`: every published kW (including hall totals and allocated leaves) `*_kwh += kw * dt / 3600`.
9. Return events `["RoughingMill:on"]` / `off` / `FurnaceColdLine:on` / `off` on dwell edges.

`snapshot()` keys: `plant_total_kw`, `shared_meter_kw`, `inhouse_meter_kw`, `shared_hot_kw`, `hot_total_kw`, `cold_total_kw`, `hot_untracked_kw`, `hot_shared_sources_kw`, `hot_machines_rest_kw`, `machines_on` (list of `"FurnaceColdLine"` / `"RoughingMill"` when running), `leaves_kw` dict with the 17 leaf+source keys from spec §8.1 (not the two hall totals — those are top-level). Round floats to 2 decimals in the snapshot only.

Start all independents at nameplate so `test_nameplates_at_t0` passes **before** the first tick.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest test/test_portland.py -v` from `99_simulator`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 99_simulator/src/uns_simulator/portland.py 99_simulator/test/test_portland.py
git commit -m "feat(simulator): add PortlandProcess energy balance and allocation."
```

---

### Task 2: Bind `portland` to its own hierarchy file

**Files:**
- Create: `conf/simulator/portland-plant.yaml`, `conf/simulator/portland.yaml`
- Modify: `99_simulator/src/uns_simulator/profiles.py`
- Modify: `99_simulator/src/uns_simulator/plant.py` (`SiteState`, `PlantContext`, `DeviceView`)
- Modify: `99_simulator/test/test_conf_files.py`, `99_simulator/test/test_profiles.py` (`FAMILIES` assertion), `99_simulator/test/test_volume.py` (profiles set only — default stays `wtp`)
- Test: `99_simulator/test/test_portland.py` (add inventory tests)

**Interfaces:**
- Consumes: `PortlandProcess` from Task 1.
- Produces:
  - `FAMILIES = ("wtp", "portland")`
  - `read_simulator_conf` returns `profiles` as the union of `plant.yaml` and `portland-plant.yaml`, plus `profile_docs: dict[str, dict]` mapping profile name → `{"hierarchy": ..., "plant": ...}` from the file that declared it.
  - `load_profile` uses `profile_docs[profile_name]["hierarchy"]` (not the WTP hierarchy) when present.
  - `build_plant_context(paths, raw_plant, seed, *, process: str = "wtp")`
  - `SiteState.wtp: WTPProcess | None`, `SiteState.portland: PortlandProcess | None` — exactly one is set.
  - `DeviceView.portland -> PortlandProcess`
  - `PlantContext.tick` calls `site.wtp.tick` or `site.portland.tick`; Portland events use line `"Mill1"`.
  - `PlantContext.snapshot` spreads `wtp.snapshot()` or `portland.snapshot()`.

- [ ] **Step 1: Write the failing inventory tests**

Append to `99_simulator/test/test_portland.py`:

```python
from pathlib import Path

from uns_simulator.profiles import load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"


def test_portland_profile_loads_nineteen_devices():
    raw = read_simulator_conf(CONF_DIR)
    profile = load_profile(raw, "portland")
    assert profile.report.devices == 19
    assert profile.context.enterprise == "PlantPortland"
    prefixes = {d.topic_prefix for d in profile.devices}
    assert all(p.startswith("PlantPortland/Site1/") for p in prefixes)
    assert all("/Mill1/" in p for p in prefixes)
    classes = {d.equipment for d in profile.devices}
    assert classes == {"Energy_Meter", "Energy_Allocated"}


def test_wtp_profile_still_loads_acme_water():
    raw = read_simulator_conf(CONF_DIR)
    profile = load_profile(raw, "wtp")
    assert profile.context.enterprise == "AcmeWater"
    assert profile.report.devices == 19
```

In `test_conf_files.py` change `test_the_shipped_profile_is_declared` to:

```python
assert set(raw["profiles"]) == {"portland", "wtp"}
```

Add `EXPECTED_SIGNAL_COUNT["portland"]` with every template id → `2` (PV + Totalizer). Template ids: `GridInput`, `WindSystem`, `SolarSystem`, `EnergyStorage`, `HeaterSystem`, `SharedEnergyMeter`, `InhouseEnergyMeter`, `ColdLocationTotal`, `ColdAirConditioning`, `ColdHeater`, `ColdLighting`, `FurnaceColdLine`, `ColdMillScaleCleaner`, `HotLocationTotal`, `RoughingMill`, `FurnaceHotLine`, `HotMillScaleCleaner`, `HotAirConditioning`, `HotLighting`.

In `test_profiles.py` change `assert FAMILIES == ("wtp",)` to `assert FAMILIES == ("wtp", "portland")`.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest test/test_portland.py::test_portland_profile_loads_nineteen_devices test/test_conf_files.py::test_the_shipped_profile_is_declared -v` from `99_simulator`

Expected: FAIL (`unknown profile 'portland'` or missing file)

- [ ] **Step 3: Write YAML and loader**

`conf/simulator/portland-plant.yaml`:

```yaml
# Plant Portland mill. Narrative: 99_simulator/ENERGY.md
enterprise: PlantPortland
sites:
  - name: Site1
    areas:
      - name: Sources
        kind: production
        lines:
          - name: Mill1
            cells: [GridInput, WindSystem, SolarSystem, EnergyStorage, HeaterSystem]
      - name: Metering
        kind: production
        lines:
          - name: Mill1
            cells: [SharedEnergyMeter, InhouseEnergyMeter]
      - name: ColdLocation
        kind: production
        lines:
          - name: Mill1
            cells: [ColdLocationTotal, ColdAirConditioning, ColdHeater, ColdLighting, FurnaceColdLine, ColdMillScaleCleaner]
      - name: HotLocation
        kind: production
        lines:
          - name: Mill1
            cells: [HotLocationTotal, RoughingMill, FurnaceHotLine, HotMillScaleCleaner, HotAirConditioning, HotLighting]
plant:
  r_ac: 0.2982456140350877   # 170/570
  r_cleaner: 0.7017543859649122
profiles:
  portland:
    tier_scale: 1.0
    sites: [Site1]
    families: [portland]
```

`conf/simulator/portland.yaml`: one device per cell. Copy this pattern for every cell (expr names below):

```yaml
# Nineteen energy points. Narrative: 99_simulator/ENERGY.md
devices:
  - id: GridInput
    equipment: Energy_Meter
    target: {area: Sources, cell: GridInput}
    signals:
      PV: {shape: derived, expr: ctx.portland.grid_kw, unit: kW, precision: 1, tier: energy, param_type: ProcessValue}
      Totalizer: {shape: derived, expr: ctx.portland.grid_kwh, unit: kWh, precision: 2, tier: meter, param_type: ProcessValue}
```

Expr map (all `ctx.portland.<name>`):

| Cell | Class | PV expr |
|---|---|---|
| GridInput | Energy_Meter | `grid_kw` |
| WindSystem | Energy_Meter | `wind_kw` |
| SolarSystem | Energy_Meter | `solar_kw` |
| EnergyStorage | Energy_Meter | `storage_kw` |
| HeaterSystem | Energy_Meter | `heater_kw` |
| SharedEnergyMeter | Energy_Meter | `shared_meter_kw` |
| InhouseEnergyMeter | Energy_Meter | `inhouse_meter_kw` |
| ColdLocationTotal | Energy_Allocated | `cold_total_kw` |
| ColdAirConditioning | Energy_Allocated | `cold_ac_kw` |
| ColdHeater | Energy_Meter | `cold_heater_kw` |
| ColdLighting | Energy_Meter | `cold_lighting_kw` |
| FurnaceColdLine | Energy_Meter | `furnace_cold.kw` |
| ColdMillScaleCleaner | Energy_Allocated | `cold_cleaner_kw` |
| HotLocationTotal | Energy_Allocated | `hot_total_kw` |
| RoughingMill | Energy_Meter | `roughing.kw` |
| FurnaceHotLine | Energy_Allocated | `furnace_hot_kw` |
| HotMillScaleCleaner | Energy_Allocated | `hot_cleaner_kw` |
| HotAirConditioning | Energy_Allocated | `hot_ac_kw` |
| HotLighting | Energy_Allocated | `hot_lighting_kw` |

Totalizer expr is the matching `*_kwh` (add `furnace_cold_kwh` / `roughing_kwh` on `PortlandProcess` if dotted machine totalizers are awkward — prefer flat `furnace_cold_kwh` and `roughing_kwh` on the process, and use those in YAML).

In `profiles.py`:

1. `FAMILIES = ("wtp", "portland")`.
2. After reading `plant.yaml`, also read every `*-plant.yaml` except `plant.yaml` itself. For each, merge `profiles` keys (duplicate profile name is `ValueError`). Store `raw["profile_docs"][name] = {"hierarchy": keys except plant/profiles, "plant": plant_doc.get("plant") or {}}`.
3. Also set `profile_docs["wtp"]` from `plant.yaml` the same way.
4. In `load_profile`, if `profile_name` is in `profile_docs`, set `hierarchy` and `raw_plant` from that doc. Pass `process=profile_name` if it is `wtp` or `portland`.
5. `build_plant_context`: `context.add_site(name, process=process)`.
6. Load `r_ac` / `r_cleaner` from `raw_plant` when constructing `PortlandProcess`.

`SiteState.__init__(self, name, rng, *, process: str = "wtp")`: if `process == "portland"` set `self.portland = PortlandProcess(rng, r_ac=..., r_cleaner=...)` and `self.wtp = None`; else today's WTP. `tick` delegates to the non-None process.

`DeviceView.portland` returns `self._context.sites[self._site].portland` (must be non-None).

`PlantContext.snapshot`: if the site has `portland`, return `{enterprise, site, **portland.snapshot()}`; else today's WTP spread.

Do **not** put `profiles.portland` in `plant.yaml`.

- [ ] **Step 4: Run tests**

Run from `99_simulator`:

```
uv run pytest test/test_portland.py test/test_conf_files.py test/test_profiles.py test/test_wtp.py test/test_volume.py::test_the_shipped_default_profile_is_wtp -v
```

Expected: PASS. Default profile still `wtp`. WTP still 19 devices on `AcmeWater`.

- [ ] **Step 5: Commit**

```bash
git add conf/simulator/portland-plant.yaml conf/simulator/portland.yaml 99_simulator/src/uns_simulator/profiles.py 99_simulator/src/uns_simulator/plant.py 99_simulator/test/test_portland.py 99_simulator/test/test_conf_files.py 99_simulator/test/test_profiles.py
git commit -m "feat(simulator): load portland profile from its own plant file."
```

---

### Task 3: Control API, families, volume band, docs

**Files:**
- Modify: `99_simulator/src/uns_simulator/api.py` (`FamiliesRequest.portland: bool | None = None`)
- Modify: `99_simulator/test/test_api.py` fixtures that hard-code `available_profiles: ["wtp"]` and `families: {wtp}` — they must accept both names when using a real simulator; mock tests that invent `["wtp"]` stay as mocks unless they import `FAMILIES`
- Modify: `99_simulator/test/test_volume.py` — add `test_portland_rate_is_small_and_is_not_the_default` asserting portland msg/s `< 5` and settings profile still `wtp`
- Modify: `99_simulator/test/test_simulator.py` if it asserts `available_profiles == ["wtp"]` against a live `load_profile` of shipped conf
- Create: `99_simulator/ENERGY.md`
- Modify: `99_simulator/README.md`, `99_simulator/PROCESS.md` (one sister-plant sentence)
- Modify: `conf/settings.yaml` mapper topics
- Modify: `00_uns_config/test/test_loader.py` expected topic lists
- Modify: `99_simulator/test/test_self_telemetry.py` — add `assert _matches("PlantPortland/#", "PlantPortland/Site1/x")` next to the AcmeWater matcher tests; the “no mapper subscribes to telemetry” test already reads shipped lists

**Interfaces:**
- Consumes: `load_profile(..., "portland")` from Task 2.
- Produces: `GET /simulator/plant` Portland body from `PlantContext.snapshot`; `available_profiles` already comes from `raw_config["profiles"]` keys.

- [ ] **Step 1: Write the failing tests**

Add to `test_portland.py`:

```python
def test_energy_md_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "ENERGY.md").is_file()
```

Add to `test_volume.py`:

```python
def test_portland_rate_is_small_and_is_not_the_default(raw, settings_doc):
    assert settings_doc["simulator"]["simulation"]["profile"] == "wtp"
    rate = sum(load_profile(raw, "portland").messages_per_second().values())
    assert 0.5 < rate < 5.0
```

Add to `00_uns_config/test/test_loader.py` (the assertion that lists graphdb topics): include `"PlantPortland/#"` next to `"AcmeWater/#"` in graphdb, historian, and kafka_mapper expected lists.

- [ ] **Step 2: Run them to verify fail**

Run: `uv run pytest test/test_portland.py::test_energy_md_exists test/test_volume.py::test_portland_rate_is_small_and_is_not_the_default -v` from `99_simulator`

Expected: FAIL on missing `ENERGY.md`

- [ ] **Step 3: Implement**

`FamiliesRequest` gains `portland: bool | None = None`.

Write `ENERGY.md`: four areas, the section-6 tag table, residual rules in operator language, one example topic per class, “not modelled” (SOC, commands, intermediates as topics, Running/Fault).

README profiles section: two profiles; WTP default; links to `PROCESS.md` and `ENERGY.md`.

`PROCESS.md`: one sentence pointing at `ENERGY.md` / profile `portland`.

`conf/settings.yaml`:

```yaml
graphdb.mqtt.topics: ["test/uns/#", "AcmeWater/#", "PlantPortland/#", "spBv1.0/uns_group/#"]
historian.mqtt.topics: ["test/uns/#", "AcmeWater/#", "PlantPortland/#", "spBv1.0/#"]
kafka_mapper.mqtt.topics: ["test/uns/#", "AcmeWater/#", "PlantPortland/#"]
```

`simulation.profile` stays `"wtp"`.

Grep `99_simulator/test` for `available_profiles == ["wtp"]` and `known: wtp` on a **live** shipped config; widen to both names. Leave unit tests that construct their own raw dicts alone unless they import `FAMILIES`.

- [ ] **Step 4: Run tests**

```
uv run pytest test/test_portland.py test/test_volume.py test/test_api.py test/test_self_telemetry.py -v
```

from `99_simulator`, and `uv run pytest test/test_loader.py -v` from `00_uns_config`.

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 99_simulator/ENERGY.md 99_simulator/README.md 99_simulator/PROCESS.md 99_simulator/src/uns_simulator/api.py conf/settings.yaml 00_uns_config/test/test_loader.py 99_simulator/test
git commit -m "docs(simulator): describe Portland and subscribe PlantPortland/#."
```

---

### Task 4: Simulator console inspector

**Files:**
- Modify: `11_frontend/src/types/simulator.ts`
- Modify: `11_frontend/src/components/simulator/PlantStateInspector.tsx`
- Create: `11_frontend/src/components/simulator/PlantStateInspector.test.tsx`

**Interfaces:**
- Consumes: Portland snapshot keys from spec §8.1 (`plant_total_kw`, no `tanks`).
- Produces: `PlantSnapshot` as a union the inspector can narrow.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PlantStateInspector } from './PlantStateInspector'
import type { SimulatorState } from './SimulatorStatusPanel'

function wrap(plant: SimulatorState['plant']): SimulatorState {
  return { status: { tick_count: 3 } as SimulatorState['status'], plant, /* other fields unused */ } as SimulatorState
}

it('renders energy KPIs for a Portland snapshot', () => {
  render(
    <PlantStateInspector
      simulator={wrap({
        enterprise: 'PlantPortland',
        site: 'Site1',
        plant_total_kw: 2000,
        cold_total_kw: 1200,
        hot_total_kw: 800,
        leaves_kw: { GridInput: 1000, EnergyStorage: 400, HeaterSystem: 600 },
        machines_on: ['RoughingMill'],
      } as never)}
    />,
  )
  expect(screen.getByText(/PlantPortland/)).toBeInTheDocument()
  expect(screen.getByText(/2000/)).toBeInTheDocument()
  expect(screen.queryByText(/Duty raw/i)).not.toBeInTheDocument()
})
```

Fill `SimulatorState` with the minimum the component reads (`status.tick_count`, `plant`). If `SimulatorState` requires more fields, satisfy the type with dummy `null`s matching `PlantStateInspector.tsx`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/simulator/PlantStateInspector.test.tsx` from `11_frontend`

Expected: FAIL (types reject the snapshot, or Duty raw still renders)

- [ ] **Step 3: Implement the union and the second body**

In `types/simulator.ts` replace `PlantSnapshot` with:

```ts
export interface WtpPlantSnapshot {
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

export interface PortlandPlantSnapshot {
  enterprise: string
  site: string
  plant_total_kw: number
  shared_meter_kw: number
  inhouse_meter_kw: number
  shared_hot_kw: number
  hot_total_kw: number
  cold_total_kw: number
  hot_untracked_kw: number
  hot_shared_sources_kw: number
  hot_machines_rest_kw: number
  machines_on: string[]
  leaves_kw: Record<string, number>
}

export type PlantSnapshot = WtpPlantSnapshot | PortlandPlantSnapshot

export function isWtpPlant(plant: PlantSnapshot | null | undefined): plant is WtpPlantSnapshot {
  return plant != null && 'tanks' in plant && plant.tanks != null
}

export function isPortlandPlant(plant: PlantSnapshot | null | undefined): plant is PortlandPlantSnapshot {
  return plant != null && 'plant_total_kw' in plant
}
```

`PlantStateInspector`: if `isPortlandPlant(plant)`, show enterprise/site, KPIs plant/cold/hot kW, grid/storage/heater from `leaves_kw`, and `machines_on`. Else keep the existing WTP body (gate it with `isWtpPlant`). Empty card when neither.

- [ ] **Step 4: Run tests**

`npx vitest run src/components/simulator/PlantStateInspector.test.tsx`

Expected: PASS. Also run any existing simulator tests that construct a WTP `PlantSnapshot`.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/types/simulator.ts 11_frontend/src/components/simulator/PlantStateInspector.tsx 11_frontend/src/components/simulator/PlantStateInspector.test.tsx
git commit -m "feat(console): show Portland energy KPIs on the simulator plant card."
```

---

### Task 5: Mapper-filter union of plant-file enterprises

**Files:**
- Modify: `09_uns_model/src/uns_model/hierarchy_io.py`
- Modify: `09_uns_model/test/test_hierarchy_io.py`

**Interfaces:**
- Consumes: `portland-plant.yaml` from Task 2.
- Produces:
  - `demo_enterprises_from_conf(conf_dir: Path) -> tuple[str, ...]`
  - `apply_enterprise_to_settings(settings_text: str, enterprise: str, extra_enterprises: Sequence[str] = ()) -> str`
  - `write_enterprise_settings(conf_dir, enterprise)` passes extras = other names from `demo_enterprises_from_conf`

- [ ] **Step 1: Write the failing tests**

Append to `09_uns_model/test/test_hierarchy_io.py`:

```python
def test_apply_enterprise_keeps_extra_demo_enterprises(tmp_path: Path):
    _write_settings(tmp_path)
    text = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    out = apply_enterprise_to_settings(text, "Contoso", extra_enterprises=("PlantPortland",))
    doc = yaml.safe_load(out)
    assert "Contoso/#" in doc["graphdb"]["mqtt"]["topics"]
    assert "PlantPortland/#" in doc["graphdb"]["mqtt"]["topics"]
    assert "test/uns/#" in doc["graphdb"]["mqtt"]["topics"]


def test_write_enterprise_settings_keeps_portland_filter_from_sibling_file(tmp_path: Path):
    _write_settings(tmp_path)
    sim = tmp_path / "simulator"
    sim.mkdir()
    (sim / "plant.yaml").write_text("enterprise: Contoso\nsites: []\n", encoding="utf-8")
    (sim / "portland-plant.yaml").write_text("enterprise: PlantPortland\nsites: []\n", encoding="utf-8")
    write_enterprise_settings(tmp_path, "Contoso")
    doc = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    assert "PlantPortland/#" in doc["graphdb"]["mqtt"]["topics"]
    assert "Contoso/#" in doc["graphdb"]["mqtt"]["topics"]
```

Change `test_apply_enterprise_to_settings_round_trips_the_shipped_file` so graphdb/historian/kafka lists include **both** `Contoso/#` and `PlantPortland/#` (the shipped tree now has `portland-plant.yaml`).

Change `test_write_enterprise_settings_writes_the_derived_file` only if that helper writes into a tmp tree **without** a portland file — it should still be a single `Contoso/#`.

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest test/test_hierarchy_io.py::test_apply_enterprise_keeps_extra_demo_enterprises -v` from `09_uns_model`

Expected: FAIL (`apply_enterprise_to_settings` unexpected keyword or missing `PlantPortland/#`)

- [ ] **Step 3: Implement**

```python
def demo_enterprises_from_conf(conf_dir: Path) -> tuple[str, ...]:
    names: list[str] = []
    directory = conf_dir / PLANT_SUBDIR
    for path in (directory / PLANT_FILENAME, *sorted(directory.glob("*-plant.yaml"))):
        if not path.is_file() or path.name == PLANT_FILENAME and path != directory / PLANT_FILENAME:
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        enterprise = doc.get("enterprise")
        if enterprise and str(enterprise) not in names:
            names.append(str(enterprise))
    return tuple(names)
```

Iterate `plant.yaml` plus `*-plant.yaml` (skip duplicating `plant.yaml` if it also matches the glob — it does not).

`_rewrite_topic_filters(topics, new_filters: list[str])`: keep `test/uns/#` and Sparkplug; replace every other `*/#` with the `new_filters` list (unique, first-seen order: saved enterprise first, then extras).

- [ ] **Step 4: Run tests**

`uv run pytest test/test_hierarchy_io.py -v` from `09_uns_model`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/hierarchy_io.py 09_uns_model/test/test_hierarchy_io.py
git commit -m "fix(model): keep sibling demo enterprise filters on hierarchy save."
```

---

### Task 6: Delete other-enterprise UNS Nodes

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/backend/graphdb.py`
- Test: `07_uns_graphql/test/backend/test_graphdb.py` (or new `test/backend/test_graph_delete.py`)

**Interfaces:**
- Consumes: the same `node_name` + `PARENT_OF` chain `rewrite_graph_prefix` uses.
- Produces: `async def delete_graph_enterprise(enterprise: str) -> int` — number of deleted nodes. No-op (return 0) if the root is absent. Must not delete a different enterprise's root.

- [ ] **Step 1: Write the failing test**

Follow the existing graph-prefix test fixtures in `07_uns_graphql/test/backend/`. If those tests mock the driver, mock `execute_write` and assert the Cypher contains `DETACH DELETE` and binds `$enterprise`. If they use a real Neo4j, create `AcmeWater` and `PlantPortland` roots with one child each, call `delete_graph_enterprise("AcmeWater")`, assert only that root (and descendants) are gone.

```python
import pytest
from uns_graphql.backend.graphdb import delete_graph_enterprise

@pytest.mark.asyncio
async def test_delete_graph_enterprise_is_defined():
    assert callable(delete_graph_enterprise)
```

Then a fixture-based test that a missing root returns 0 (mock session returning 0).

- [ ] **Step 2: Run to verify fail**

`uv run pytest test/backend/test_graphdb.py -k delete_graph_enterprise -v` from `07_uns_graphql`

Expected: FAIL import

- [ ] **Step 3: Implement**

```python
_DELETE_ENTERPRISE_CYPHER = f"""
MATCH (root {{node_name: $enterprise}})
WHERE NOT ()-[:PARENT_OF]->(root)
  AND NOT root:{_NESTED_ATTRIBUTE_LABEL}
OPTIONAL MATCH (root)-[:PARENT_OF*0..10]->(desc)
WHERE NONE(n IN nodes(path) WHERE n:{_NESTED_ATTRIBUTE_LABEL})
WITH root, collect(DISTINCT desc) AS descendants
FOREACH (d IN descendants | DETACH DELETE d)
DETACH DELETE root
RETURN 1 AS deleted
"""
```

Use a path variable correctly (`OPTIONAL MATCH path = (root)-[:PARENT_OF*0..10]->(desc)`). Skip nested-attribute nodes. Return `0` when `record is None`.

- [ ] **Step 4: Run tests**

`uv run pytest test/backend/ -k graph -v` from `07_uns_graphql`

Expected: PASS, including existing prefix-rewrite tests

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/backend/graphdb.py 07_uns_graphql/test/backend
git commit -m "feat(graphql): detach-delete one enterprise's UNS Node tree."
```

---

### Task 7: `switchDemoPlant` mutation

**Files:**
- Modify: `07_uns_graphql/schema/uns_schema.graphql`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/hierarchy.py`
- Modify: `07_uns_graphql/src/uns_graphql/auth/require.py`
- Modify: `07_uns_graphql/test/auth/test_require.py` (`EXPECTED["switchDemoPlant"] = {"admin"}`)
- Modify: `07_uns_graphql/test/auth/test_graphql_gate.py` (add a row like `saveHierarchy`)
- Create: `07_uns_graphql/test/mutations/test_switch_demo_plant.py`

**Interfaces:**
- Consumes: `demo_enterprises_from_conf`, `load_plant_tree` (WTP), `tree_from_mapping` for portland file, `apply_plan`, `plan_from_hierarchy_tree`, `delete_graph_enterprise` from Task 6.
- Produces:
  - GraphQL `switchDemoPlant(profile: String!): DemoPlantSwitchResult!`
  - `DemoPlantSwitchResult { profile: String!, enterprise: String!, deletedEnterprises: [String!]! }`
  - Python: `async def switch_demo_plant(self, info, profile: str) -> DemoPlantSwitchResult`
  - Does **not** write `plant.yaml` or `portland-plant.yaml`
  - Does **not** call `write_enterprise_settings`
  - Does **not** prefix-migrate historian

- [ ] **Step 1: Write the failing tests**

`07_uns_graphql/test/mutations/test_switch_demo_plant.py` — mirror `test_hierarchy.py` patches (`_reseed`, `apply_plan`, graph). Cases:

1. `profile: "huge"` → GraphQL error, `apply_plan` not called.
2. `profile: "portland"` → `apply_plan` called with a tree whose `enterprise == "PlantPortland"`; `delete_graph_enterprise` called with `"AcmeWater"` (the other name from the two files); neither YAML file’s mtime/content changes.
3. Second call with `"portland"` → `delete_graph_enterprise` is **not** called with `"PlantPortland"`; it may be called with `"AcmeWater"` again (idempotent).
4. `profile: "wtp"` after portland → deletes `"PlantPortland"`, reseeds AcmeWater.
5. Unauthenticated / operator identity → `NotPermittedError` (or add the gate-table row and rely on `test_require.py`).

Also add `EXPECTED["switchDemoPlant"] = {"admin"}` in `test_require.py` **in the same commit as** `MUTATION_ROLES["switchDemoPlant"]`.

- [ ] **Step 2: Run to verify fail**

`uv run pytest test/auth/test_require.py test/mutations/test_switch_demo_plant.py -v` from `07_uns_graphql`

Expected: FAIL (unknown mutation / missing key)

- [ ] **Step 3: Implement**

```python
PROFILE_FILES = {"wtp": "plant.yaml", "portland": "portland-plant.yaml"}

def _load_profile_tree(conf_dir: Path, profile: str) -> HierarchyTree:
    filename = PROFILE_FILES.get(profile)
    if filename is None:
        raise GraphQLError(
            f"unknown profile {profile!r} (known: portland, wtp)",
            extensions={"field": "profile"},
        )
    path = conf_dir / "simulator" / filename
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return tree_from_mapping(doc)
```

Resolver:

```python
require(info, "switchDemoPlant")
tree = _load_profile_tree(conf_dir, profile)
validate_tree(tree)
await _reseed(tree)
deleted: list[str] = []
for name in demo_enterprises_from_conf(conf_dir):
    if name != tree.enterprise:
        await delete_graph_enterprise(name)
        deleted.append(name)
return DemoPlantSwitchResult(profile=profile, enterprise=tree.enterprise, deleted_enterprises=deleted)
```

Add the field to `uns_schema.graphql` and a `@strawberry.type` result. Register in `MUTATION_ROLES`.

- [ ] **Step 4: Run tests**

`uv run pytest test/auth/test_require.py test/auth/test_graphql_gate.py test/mutations/test_switch_demo_plant.py test/mutations/test_hierarchy.py -v` from `07_uns_graphql`

Expected: PASS. `saveHierarchy` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/schema/uns_schema.graphql 07_uns_graphql/src/uns_graphql/mutations/hierarchy.py 07_uns_graphql/src/uns_graphql/auth/require.py 07_uns_graphql/test
git commit -m "feat(graphql): switchDemoPlant reseeds one client and drops the other graph."
```

---

### Task 8: Block `saveHierarchy` while Portland is live

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/mutations/hierarchy.py` (`save_hierarchy`)
- Modify: `07_uns_graphql/test/mutations/test_hierarchy.py`

**Interfaces:**
- Consumes: `AssetModelRepository.list_assets(levels=["ENTERPRISE"])`.
- Produces: HTTP/GraphQL 409 when any live enterprise asset path is `PlantPortland` (segment or path equals `PlantPortland`). Message: `saveHierarchy writes plant.yaml (Acme Water). Switch the simulator profile back to wtp before editing the hierarchy.`

- [ ] **Step 1: Write the failing test**

In `test_hierarchy.py`, patch `list_assets` to return an object with `path="PlantPortland"`, `segment="PlantPortland"`. Call `saveHierarchy` with a valid WTP tree. Expect an error containing `409` or `PlantPortland` / `wtp`, and `save_plant_tree` / `_reseed` **not** called.

- [ ] **Step 2: Run to verify fail**

`uv run pytest test/mutations/test_hierarchy.py -k portland -v` from `07_uns_graphql`

Expected: FAIL (no such guard)

- [ ] **Step 3: Implement**

At the top of `save_hierarchy`, after `require`:

```python
repository = AssetModelRepository(Database.from_settings())
enterprises = await repository.list_assets(levels=["ENTERPRISE"])
if any(asset.segment == "PlantPortland" or asset.path == "PlantPortland" for asset in enterprises):
    raise GraphQLError(
        "saveHierarchy writes plant.yaml (Acme Water). Switch the simulator profile back to wtp before editing the hierarchy.",
        extensions={"code": "409", "field": "tree"},
    )
```

Reuse the same `Database` / repository construction `_reseed` already uses (do not open a second engine style).

- [ ] **Step 4: Run tests**

`uv run pytest test/mutations/test_hierarchy.py -v` from `07_uns_graphql`

Expected: PASS, including existing save-and-reseed tests (they mock or seed AcmeWater)

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/mutations/hierarchy.py 07_uns_graphql/test/mutations/test_hierarchy.py
git commit -m "fix(graphql): reject hierarchy saves while the Portland seed is live."
```

---

### Task 9: Console applies profile then `switchDemoPlant`

**Files:**
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/services/graphql/client.ts`
- Modify: `11_frontend/src/hooks/useSimulator.ts`
- Modify: `11_frontend/src/components/simulator/SimulatorConfigPanel.tsx` (banner + Retry if needed)
- Create or modify: `11_frontend/src/hooks/useSimulator.test.ts` (or the nearest existing simulator hook/panel test)

**Interfaces:**
- Consumes: `simulatorClient.setProfile`, new `unsGraphQLClient.switchDemoPlant(profile: string)`
- Produces: `setProfile` on success of PUT then calls `switchDemoPlant` with the same name. On GraphQL failure, `lastError` explains MQTT already switched; `retryDemoSwitch()` calls **only** `switchDemoPlant`.

- [ ] **Step 1: Write the failing tests**

```ts
it('does not call setProfile again when retrying a failed demo switch', async () => {
  const setProfile = vi.fn().mockResolvedValue({ data: { profile: 'portland' } })
  const switchDemoPlant = vi.fn().mockRejectedValueOnce(new Error('graph down')).mockResolvedValueOnce({
    profile: 'portland',
    enterprise: 'PlantPortland',
    deletedEnterprises: ['AcmeWater'],
  })
  // mount hook / panel with those mocks, apply portland, click Retry
  expect(setProfile).toHaveBeenCalledTimes(1)
  expect(switchDemoPlant).toHaveBeenCalledTimes(2)
})
```

Adapt to however `useSimulator` is tested today (if there is no hook test, put this in a new `useSimulator.test.ts` wrapping the hook with `renderHook` and mocked clients).

- [ ] **Step 2: Run to verify fail**

`npx vitest run src/hooks/useSimulator.test.ts` from `11_frontend`

Expected: FAIL (no `switchDemoPlant`)

- [ ] **Step 3: Implement**

`queries.ts`:

```ts
export const SWITCH_DEMO_PLANT_MUTATION = `
  mutation SwitchDemoPlant($profile: String!) {
    switchDemoPlant(profile: $profile) {
      profile
      enterprise
      deletedEnterprises
    }
  }
`
```

`client.ts` method `switchDemoPlant(profile: string)` via `executeQuery`.

`useSimulator.setProfile`:

```ts
const ok = await write(() => simulatorClient.setProfile(name, seed), true)
if (!ok) return false
try {
  await unsGraphQLClient.switchDemoPlant(name)
  setSwapError(null)
  return true
} catch (error) {
  setSwapError('MQTT is on the new plant; Asset Model and graph are still the previous client.')
  return false
}
```

`retryDemoSwitch` calls `unsGraphQLClient.switchDemoPlant(status.profile)` only.

`SimulatorConfigPanel`: if `swapError`, show that sentence and a Retry button bound to `retryDemoSwitch`.

- [ ] **Step 4: Run tests**

`npx vitest run src/hooks/useSimulator.test.ts src/components/simulator src/components/hierarchy/HierarchyView.test.tsx` from `11_frontend`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/services/graphql/queries.ts 11_frontend/src/services/graphql/client.ts 11_frontend/src/hooks/useSimulator.ts 11_frontend/src/components/simulator/SimulatorConfigPanel.tsx 11_frontend/src/hooks/useSimulator.test.ts
git commit -m "feat(console): swap Asset Model and graph after a simulator profile change."
```

---

## Self-review (plan vs spec)

| Spec section | Task |
|---|---|
| §2 profile `portland`, WTP default | 2, 3 |
| §5–6 topics and 19 devices | 2 |
| §7 process / residuals / totalizers | 1 |
| §8 control API + inspector | 3, 4 |
| §9.1 `switchDemoPlant` delete-other-enterprise | 6, 7 |
| §9.2 `saveHierarchy` 409 + keep `PlantPortland/#` | 5, 8 |
| §9.3 Access Groups untouched | 7 (no access-group calls) |
| §10 mapper topics | 3, 5 |
| §11 ENERGY.md / README | 3 |
| §12 tests listed | spread across 1–9 |
| Console PUT then GraphQL, Retry | 9 |

No historian purge task (correct). No second Compose service. No `profiles.portland` in `plant.yaml`.
