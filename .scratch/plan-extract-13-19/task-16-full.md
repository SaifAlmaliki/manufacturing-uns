## Task 16: `conf/simulator/` on disk — the file reader, `plant.yaml`, `energy.yaml`, `water.yaml`

Every task so far has been driven by dict fixtures. This one puts the real plant on disk and connects the loader to it. Spec §7.1 is explicit that `profiles.py` reads these files itself rather than through `uns_config.get_settings()`, which hardcodes `settings_files=["settings.yaml", ".secrets.yaml"]` for all nine modules — widening that list for one module's benefit would change config loading platform-wide.

The two families in this task are the ones spec §8 leads with, and between them they prove the whole correlation claim end to end: a main incomer whose kW follows `ctx.served_production`, and a cooling tower whose ΔT follows `ctx.served_heat_load` with the first-order lag Task 7 built.

**Files:**
- Create: `conf/simulator/plant.yaml`, `conf/simulator/energy.yaml`, `conf/simulator/water.yaml`
- Modify: `99_simulator/src/uns_simulator/profiles.py`, `99_simulator/src/uns_simulator/simulator.py`, `99_simulator/pyproject.toml`
- Test: `99_simulator/test/test_conf_files.py`

**Interfaces:**
- Consumes: `FAMILIES` / `load_profile` (Task 12), `load_simulator_config` (Task 15), `uns_config.resolve_conf_dir`.
- Produces, in `profiles.py`:
  - `SIMULATOR_CONF_SUBDIR: Final[str] = "simulator"` — the directory under `conf/`.
  - `read_simulator_conf(conf_dir: Path | None = None) -> dict[str, Any]` — reads `<conf_dir>/simulator/plant.yaml` plus one file per family into exactly the mapping `load_profile` consumes. `conf_dir` defaults to `resolve_conf_dir()`. The parameter exists so tests read a `tmp_path` and so sub-project B's `PUT /simulator/profile` can reload from an explicit directory.
  - `load_simulator_config(settings_obj: Any, conf_dir: Path | None = None) -> dict[str, Any]` — Task 15's adapter, now overlaying the files on top of the Dynaconf values.

Three rules fix `read_simulator_conf`'s behaviour, and each one is a test below:

| Situation | Behaviour | Why |
|---|---|---|
| `conf/simulator/` or a family file is absent | Skipped silently | Spec §14's mitigation is "land and validate one family at a time", and spec §12 promises a deployment with no `conf/simulator/` still runs off `simulator.hierarchy` in `settings.yaml`. Both need absence to be ordinary. |
| A file exists but its top level is not a mapping | `ValueError` naming the file | A YAML file that parses to a list or a string is a typo, not a configuration choice, and the alternative is an empty family nobody can explain. |
| `plant.yaml` is present | Its `plant` and `profiles` keys are lifted out; **everything else** becomes `hierarchy` | `plant.yaml` writes `enterprise:` and `sites:` at the top level (spec §7.2) while `load_profile` wants them under `hierarchy`. Lifting by exclusion rather than by an allow-list means a future hierarchy key needs no change here. |

### Why a new dependency

`read_simulator_conf` needs a plain YAML parser. Dynaconf has loaders, but only for its own settings files, and `ruamel-yaml` is in `uv.lock` solely as a transitive dependency of the `safety` dev tool — depending on it from runtime code would be depending on an accident. Add `pyyaml` explicitly.

- [ ] **Step 1: Add the dependency**

In `99_simulator/pyproject.toml`, in the `[project]` `dependencies` list, after `"dynaconf~=3.2",`:

```toml
    "pyyaml~=6.0",
```

Then:

```bash
cd 99_simulator && uv lock && uv sync --all-groups
```

- [ ] **Step 2: Write the failing test file**

```python
# 99_simulator/test/test_conf_files.py
"""The real conf/simulator/*.yaml files, loaded from disk.

Every other suite hands `load_profile` a dict, which is what keeps them fast and
hermetic - and also what makes them blind to the files that actually ship. This is the
only place that would notice a family file nobody wrote, a device that lost half its
signals in transcription, or a `serves` path naming a line the hierarchy renamed.

The two tables are the point of the file. Asserting a single total device count would
pass just as happily on a wrong total that I miscomputed; a count per template cannot,
because a missing device names itself.
"""

from pathlib import Path

import pytest

from uns_simulator.profiles import load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"

# Signals declared by each device template, per spec 8.1-8.2. Tasks 17 and 18 extend
# these tables as they add family files; a family named in a profile whose file does not
# exist yet contributes nothing and is not an error, which is spec 14's
# land-one-family-at-a-time mitigation working as intended.
EXPECTED_SIGNAL_COUNT = {
    "energy": {"EM-01": 17, "EM-02": 17, "TR-01": 6, "MCC-01": 6, "MCC-02": 6},
    "water": {"FM-01": 5, "DEMIN-01": 6, "CT-01": 11, "CT-02": 11, "EFF-01": 9},
}

# Hierarchy paths each template expands to under the `full` profile. Anything other than
# 1 is a template deliberately left site-agnostic: FM-01 has no `serves`, so one entry
# can serve both sites' raw water intakes.
EXPECTED_DEVICE_COUNT = {
    "energy": {"EM-01": 1, "EM-02": 1, "TR-01": 1, "MCC-01": 1, "MCC-02": 1},
    "water": {"FM-01": 2, "DEMIN-01": 1, "CT-01": 1, "CT-02": 1, "EFF-01": 1},
}

FAMILY_TEMPLATES = [
    (family, template_id, count)
    for family, table in EXPECTED_SIGNAL_COUNT.items()
    for template_id, count in table.items()
]


@pytest.fixture(scope="module")
def raw():
    return read_simulator_conf(CONF_DIR)


def test_plant_yaml_supplies_the_hierarchy_at_the_top_level(raw):
    """Spec 7.2 writes `enterprise:` and `sites:` at the top of plant.yaml."""
    assert raw["hierarchy"]["enterprise"] == "CovestroAG"
    assert [site["name"] for site in raw["hierarchy"]["sites"]] == ["Dormagen", "Krefeld"]
    assert "profiles" not in raw["hierarchy"]
    assert "plant" not in raw["hierarchy"]


def test_both_shipped_profiles_are_declared(raw):
    assert set(raw["profiles"]) == {"small", "full"}
    assert raw["profiles"]["small"]["tier_scale"] == 6.0  # noqa: PLR2004
    assert raw["profiles"]["small"]["sites"] == ["Dormagen"]
    assert raw["profiles"]["small"]["max_cells_per_line"] == 1
    assert raw["profiles"]["full"]["sites"] == ["Dormagen", "Krefeld"]


def test_a_serves_list_never_names_another_sites_lines(raw):
    """A copied template with a Dormagen `serves` list is the mistake this catches.

    `load_profile` rejects a `serves` path that resolves to nothing, but Dormagen's lines
    do resolve - so a Krefeld meter carrying them would correlate against the wrong site's
    production and load perfectly cleanly. Only the site prefix betrays it.
    """
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            site = (template.get("target") or {}).get("site")
            if site is None:
                continue  # covered by the next test instead
            for served in template.get("serves") or []:
                assert served.startswith(f"{site}/"), f"{template['id']} serves {served} but sits on {site}"


def test_a_template_carrying_serves_never_replicates(raw):
    """The other half of the guard above, for templates that omit `target.site`.

    `TR-01` and `MCC-01` leave `site` out because `Transformer_T1` and `MCC_Production` are
    Dormagen-only cell names. If a Krefeld cell were ever given one of those names they
    would replicate silently, and the copy would carry Dormagen's `serves` list. A device
    count of 1 is what rules that out, so it is asserted rather than left to the table.
    """
    for family, table in EXPECTED_DEVICE_COUNT.items():
        for template in raw[family]["devices"]:
            if template.get("serves"):
                assert table[str(template["id"])] == 1, f"{template['id']} carries `serves` and replicates"


@pytest.mark.parametrize(("family", "template_id", "expected"), FAMILY_TEMPLATES)
def test_each_template_declares_the_expected_signal_count(raw, family, template_id, expected):
    by_id = {str(template["id"]): template for template in raw[family]["devices"]}
    assert len(by_id[template_id]["signals"]) == expected


def test_the_family_files_declare_exactly_the_expected_templates(raw):
    for family, table in EXPECTED_SIGNAL_COUNT.items():
        declared = [str(template["id"]) for template in raw[family]["devices"]]
        assert sorted(declared) == sorted(table), f"{family}.yaml template ids drifted from the table"
        assert len(declared) == len(set(declared)), f"{family}.yaml declares a duplicate id"


def test_every_signal_in_every_family_file_declares_a_unit(raw):
    """`expand_template` enforces this too; this test names the file and the signal."""
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            for name, signal in template["signals"].items():
                unit = (signal or {}).get("unit")
                assert unit is not None and str(unit).strip(), f"{family}.yaml {template['id']}/{name} has no unit"


def test_the_full_profile_loads_from_disk_with_the_expected_device_count(raw):
    profile = load_profile(raw, "full")
    expected = sum(count for table in EXPECTED_DEVICE_COUNT.values() for count in table.values())
    assert profile.report.devices == expected
    assert profile.report.warnings == []
    assert profile.report.unmatched_templates == []


def test_the_full_profile_signal_count_is_the_table_multiplied_out(raw):
    profile = load_profile(raw, "full")
    expected = sum(
        EXPECTED_SIGNAL_COUNT[family][template_id] * EXPECTED_DEVICE_COUNT[family][template_id]
        for family, table in EXPECTED_SIGNAL_COUNT.items()
        for template_id in table
    )
    assert profile.report.signals == expected


def test_the_small_profile_drops_krefeld_and_the_second_cell(raw):
    small = load_profile(raw, "small")
    full = load_profile(raw, "full")
    assert small.report.devices < full.report.devices
    assert {device.path.site for device in small.devices} == {"Dormagen"}
    assert small.tiers["process"] == pytest.approx(30.0), "5 s process tier times a tier_scale of 6"


def test_loading_the_same_directory_twice_gives_identical_reports(raw):
    """Spec 5.3: the seed is the only source of variation, and the files do not carry one."""
    assert load_profile(raw, "full").report.as_dict() == load_profile(read_simulator_conf(CONF_DIR), "full").report.as_dict()


def test_an_absent_conf_directory_is_not_an_error(tmp_path):
    """Spec 12: a deployment with no conf/simulator still runs off settings.yaml."""
    assert read_simulator_conf(tmp_path) == {}


def test_an_absent_family_file_is_skipped(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "plant.yaml").write_text("enterprise: E\nsites: []\n", encoding="utf-8")
    raw = read_simulator_conf(tmp_path)
    assert raw["hierarchy"] == {"enterprise": "E", "sites": []}
    assert "energy" not in raw


def test_a_family_file_that_is_not_a_mapping_is_rejected_by_name(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "energy.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="energy.yaml"):
        read_simulator_conf(tmp_path)
```

- [ ] **Step 3: Run the test file to verify it fails**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -x`
Expected: collection error — `ImportError: cannot import name 'read_simulator_conf' from 'uns_simulator.profiles'`.

- [ ] **Step 4: Implement the reader**

Add to the top of `profiles.py`:

```python
from pathlib import Path

import yaml
from uns_config import resolve_conf_dir
```

and at the end of the file:

```python
SIMULATOR_CONF_SUBDIR: Final = "simulator"

# Everything in plant.yaml that is *not* one of these is hierarchy. Lifting by exclusion
# rather than by an allow-list means a future hierarchy key needs no change here.
_PLANT_NON_HIERARCHY_KEYS: Final = frozenset({"plant", "profiles"})


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    """Parse one file, or None if it is absent. A non-mapping top level is fatal."""
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{path.name}: expected a YAML mapping at the top level, got {type(loaded).__name__}")
    return dict(loaded)


def read_simulator_conf(conf_dir: Path | None = None) -> dict[str, Any]:
    """Read conf/simulator/*.yaml into the mapping `load_profile` consumes.

    Not routed through `uns_config.get_settings()`: that function hardcodes
    `settings_files=["settings.yaml", ".secrets.yaml"]` for all nine modules, so widening
    it for the simulator's benefit would change config loading platform-wide (spec 7.1).

    Absent files are skipped rather than defaulted. That is what lets spec 14's
    land-one-family-at-a-time work, and what keeps spec 12's promise that a deployment
    with no conf/simulator/ still runs off `simulator.hierarchy` in settings.yaml.
    """
    directory = (conf_dir if conf_dir is not None else resolve_conf_dir()) / SIMULATOR_CONF_SUBDIR
    raw: dict[str, Any] = {}

    if (plant_doc := _read_yaml_mapping(directory / "plant.yaml")) is not None:
        raw["hierarchy"] = {key: value for key, value in plant_doc.items() if key not in _PLANT_NON_HIERARCHY_KEYS}
        raw["plant"] = plant_doc.get("plant") or {}
        raw["profiles"] = plant_doc.get("profiles") or {}

    for family in FAMILIES:
        if (family_doc := _read_yaml_mapping(directory / f"{family}.yaml")) is not None:
            raw[family] = family_doc

    LOGGER.info("Read simulator configuration from %s: %s", directory, ", ".join(sorted(raw)) or "nothing")
    return raw
```

`Mapping` is already imported in `profiles.py` from Task 11; `Final` and `Any` from Task 12. `resolve_conf_dir` is exported from `uns_config` (`00_uns_config/src/uns_config/loader.py:34`) and is how every other module finds `conf/`, so the simulator does not invent its own search.

- [ ] **Step 5: Overlay the files on the Dynaconf settings**

Replace Task 15's `load_simulator_config` in `simulator.py`:

```python
def load_simulator_config(settings_obj: Any, conf_dir: Path | None = None) -> dict[str, Any]:
    """Assemble the mapping load_profile expects, files layered over Dynaconf.

    One adapter, so tests hand load_profile a plain dict and never depend on Dynaconf, and
    production has exactly one place where the two representations meet.

    `conf/simulator/*.yaml` wins over `settings.yaml` key by key, and only where the file
    supplies something. Whole-mapping replacement would be wrong in one direction and a
    deep merge wrong in the other: `simulation` only ever lives in settings.yaml, and a
    `hierarchy` half from each file would be a plant nobody authored. Per-key overlay is
    what keeps spec 12's promise that an untouched deployment with no conf/simulator/
    behaves exactly as it does today.
    """
    raw: dict[str, Any] = {
        "hierarchy": settings_obj.get("hierarchy") or {},
        "plant": settings_obj.get("plant") or {},
        "profiles": settings_obj.get("profiles") or {},
        "simulation": settings_obj.get("simulation") or {},
    }
    for family in FAMILIES:
        raw[family] = settings_obj.get(family) or {}
    for key, value in read_simulator_conf(conf_dir).items():
        if value:
            raw[key] = value
    return raw
```

Add `from pathlib import Path` and `read_simulator_conf` to `simulator.py`'s imports:

```python
from uns_simulator.profiles import FAMILIES, PRODUCTION_KIND, LoadedProfile, load_profile, read_simulator_conf
```

Then amend the two lines of `__init__` that Task 15 left reading Dynaconf directly, so the legacy devices and the signal devices cannot disagree about what the plant is:

```python
        raw_config = load_simulator_config(settings)
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(raw_config["hierarchy"])
        self.hierarchy = self.hierarchies[0]
```

and pass the same mapping to `load_profile` instead of rebuilding it:

```python
        self.profile: LoadedProfile = load_profile(raw_config, requested, seed=seed)
```

Without this, `SCADA` and `HMI` would publish under `settings.yaml`'s hierarchy while every `SignalDevice` published under `plant.yaml`'s — two plants in one topic tree, and nothing would fail to make it visible.

- [ ] **Step 6: Write `conf/simulator/plant.yaml`**

Spec §7.2 leaves Krefeld as a comment ("reduced mirror: Production/Line1/Cell1 plus PowerDistribution, WaterTreatment, CompressedAir, GasDetection, WeatherStation"). Write it out. A commented-out site cannot be targeted, cannot appear in a `serves` path, and cannot be counted by a test — and `full`'s `sites: [Dormagen, Krefeld]` would resolve to one site while claiming two.

```yaml
# conf/simulator/plant.yaml
#
# The whole plant: every site, area, line and cell, plus the profiles that narrow it.
# Read by uns_simulator.profiles.read_simulator_conf, NOT by Dynaconf (spec 7.1), so there
# are no environment sections here and no secrets.
#
# `kind` on an area is what keeps production templates out of utility areas: a device
# template with no `target` matches cells in `kind: production` areas only.

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

  # Spec 7.2's reduced mirror, written out rather than left as a comment: a `serves` path
  # and a device count have to resolve against something real.
  - name: Krefeld
    areas:
      - name: Production
        kind: production
        lines:
          - name: Line1
            nameplate_tph: 5.0
            cells: [Cell1]
      - name: Utilities
        kind: utilities
        lines:
          - name: PowerDistribution
            cells: [MainIncomer]
          - name: WaterTreatment
            cells: [RawWaterIntake, CoolingTower1]
          - name: CompressedAir
            cells: [Compressor_C1, AirHeader]
      - name: Safety
        kind: utilities
        lines:
          - name: GasDetection
            cells: [GD_Zone1]
          - name: WeatherStation
            cells: [WS_01]

# Per-site ambient and tariff, per-line PackML timing. Keys map onto SiteState's keyword
# arguments and LineTiming's fields; anything absent keeps its default. A `lines` key that
# names no production line anywhere in the hierarchy fails the load, so this block cannot
# quietly describe a line that was renamed.
plant:
  sites:
    Dormagen:
      ambient_mean_c: 11.0
      ambient_swing_c: 9.0
      tariff_peak_hours: [7, 21]
    Krefeld:
      ambient_mean_c: 11.5
      ambient_swing_c: 8.0
      tariff_peak_hours: [7, 21]
  lines:
    # Line1 runs long batches; Line2 is the short-batch line, so it cycles through
    # STARTING and COMPLETING far more often and is the one that exercises the ramps.
    Dormagen/Production/Line1:
      execute_s: 3600.0
      hold_probability_per_hour: 2.0
    Dormagen/Production/Line2:
      execute_s: 1200.0
      completing_s: 45.0
      resetting_s: 30.0
      hold_probability_per_hour: 3.0
    Krefeld/Production/Line1:
      execute_s: 5400.0
      hold_probability_per_hour: 1.0

profiles:
  # `small` is the shipped default. Spec 9: `full` is roughly 100 msg/s, and the graphdb
  # mapper MERGEs per topic level on every message, so `full` is opt-in via
  # `simulation.profile` rather than the default.
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

Both `families` lists are spec §7.2's final lists, naming families whose files Tasks 17 and 18 have yet to write. That is deliberate and it is not a placeholder: `load_profile` iterates `FAMILIES` and skips a family with no `devices` (Task 12, Step 4), so an unwritten family contributes zero devices and no error. Writing the final lists once means `plant.yaml` is authored exactly once, and the test tables — not the profile — are what each later task extends.

- [ ] **Step 7: Write `conf/simulator/energy.yaml`**

Three things worth understanding before transcribing, because they are the difference between a plant model and 52 independent random walks:

1. **`ActivePower` is the only primary signal on a meter.** `ReactivePower`, `ApparentPower`, `PowerFactor` and the three phase currents are `derived` from it, so a production hold moves all seven together and the power triangle stays internally consistent. Deriving `PowerFactor` from two signals that were each walking independently would produce a power factor that violates its own definition.
2. **A device declares `serves` only if it genuinely feeds those lines.** `MCC_Utilities` feeds the utility side, has no production line under it, and so gets an `ou_walk` and no `serves`. Handing it a `serves` it does not have would make it track production it does not feed — worse than not correlating at all, because it looks correct.
3. **A template naming no `site` replicates to every matching cell.** `Transformer_T1` is a Dormagen-only cell name, so `TR-01`'s `target` omits `site` and still resolves to exactly one device. `EM-01` and `EM-02` *do* name their site, because a `serves` list is site-specific and cannot be shared — which is also why the two meters are written out in full rather than sharing a YAML anchor. An anchor would give Krefeld Dormagen's 1450 kW connected load, and since `range` and `limits` drive `status`, a wrong rating shows up as a permanently alarming meter.

```yaml
# conf/simulator/energy.yaml
# Spec 8.1. Electrical metering: incomer, transformer, two motor control centres.
# ActivePower is the only primary signal on a meter; the rest of the power triangle is
# derived from it, so the seven values stay mutually consistent on every tick.

devices:
  - id: EM-01
    equipment: EM-01
    target: {site: Dormagen, area: Utilities, line: PowerDistribution, cell: MainIncomer}
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
        export_metric: true
      ReactivePower:
        shape: derived
        unit: kVAr
        expr: ActivePower * tan_phi
        params: {tan_phi: 0.44}
        precision: 1
        range: [0, 1200]
      ApparentPower:
        shape: derived
        unit: kVA
        expr: sqrt(ActivePower * ActivePower + ReactivePower * ReactivePower)
        precision: 1
        range: [0, 2400]
      PowerFactor:
        # max(..., 1.0) rather than a raw divide: at a dead plant both powers are zero and
        # this is a division by zero, not a small number.
        shape: derived
        unit: "1"
        expr: ActivePower / max(ApparentPower, 1.0)
        precision: 3
        range: [0, 1]
        limits: {lo: 0.9, lolo: 0.85}
      VoltageL1:
        shape: ou_walk
        unit: V
        mean: 400.0
        sigma: 1.2
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL2:
        shape: ou_walk
        unit: V
        mean: 399.4
        sigma: 1.2
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL3:
        shape: ou_walk
        unit: V
        mean: 400.6
        sigma: 1.2
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      CurrentL1:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL1, 1.0))
        precision: 1
        range: [0, 3500]
      CurrentL2:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL2, 1.0))
        precision: 1
        range: [0, 3500]
      CurrentL3:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL3, 1.0))
        precision: 1
        range: [0, 3500]
      Frequency:
        shape: ou_walk
        unit: Hz
        mean: 50.0
        sigma: 0.015
        tau: 30.0
        precision: 3
        range: [49.0, 51.0]
        limits: {lo: 49.8, hi: 50.2}
      VoltageThd:
        shape: ou_walk
        unit: "%"
        mean: 2.4
        sigma: 0.35
        tau: 180.0
        precision: 2
        range: [0, 12]
        limits: {hi: 5.0, hihi: 8.0}
      EnergyTotal:
        # kW divided by 3600 is kWh per second, and `rate` is per second. Getting this
        # wrong by 3600 is the easiest mistake in the file and the hardest to spot: the
        # register still rises monotonically, just absurdly fast.
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 84000.0
        tier: meter
        precision: 1
        export_metric: true
      ReactiveEnergyTotal:
        shape: counter
        unit: kVArh
        rate: ReactivePower / 3600.0
        initial: 31000.0
        tier: meter
        precision: 1
      PeakDemand:
        shape: window_agg
        unit: kW
        source: ActivePower
        agg: max
        window_s: 900.0
        tier: meter
        precision: 1
      EnergyIntensity:
        # kWh per tonne. The 0.1 floor is not cosmetic: an idle line makes the true
        # intensity infinite, and a topic reporting 1/0 is worse than one reporting the
        # intensity a very slow line would have.
        shape: derived
        unit: kWh/t
        expr: ActivePower / max(ctx.served_throughput_tph, 0.1)
        tier: meter
        precision: 2
        range: [0, 2000]
      CarbonRate:
        shape: derived
        unit: kgCO2/h
        expr: ActivePower * ctx.grid_co2_g_per_kwh / 1000.0
        precision: 2
        range: [0, 900]

  - id: EM-02
    equipment: EM-02
    target: {site: Krefeld, area: Utilities, line: PowerDistribution, cell: MainIncomer}
    serves: [Krefeld/Production/Line1]
    tier: energy
    signals:
      ActivePower:
        shape: derived
        unit: kW
        expr: base_load + ctx.served_production * connected_kw
        params: {base_load: 90.0, connected_kw: 520.0}
        precision: 1
        range: [0, 800]
        limits: {hi: 700, hihi: 760}
        export_metric: true
      ReactivePower:
        shape: derived
        unit: kVAr
        expr: ActivePower * tan_phi
        params: {tan_phi: 0.48}
        precision: 1
        range: [0, 500]
      ApparentPower:
        shape: derived
        unit: kVA
        expr: sqrt(ActivePower * ActivePower + ReactivePower * ReactivePower)
        precision: 1
        range: [0, 1000]
      PowerFactor:
        shape: derived
        unit: "1"
        expr: ActivePower / max(ApparentPower, 1.0)
        precision: 3
        range: [0, 1]
        limits: {lo: 0.9, lolo: 0.85}
      VoltageL1:
        shape: ou_walk
        unit: V
        mean: 400.0
        sigma: 1.4
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL2:
        shape: ou_walk
        unit: V
        mean: 400.8
        sigma: 1.4
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL3:
        shape: ou_walk
        unit: V
        mean: 399.2
        sigma: 1.4
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      CurrentL1:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL1, 1.0))
        precision: 1
        range: [0, 1500]
      CurrentL2:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL2, 1.0))
        precision: 1
        range: [0, 1500]
      CurrentL3:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL3, 1.0))
        precision: 1
        range: [0, 1500]
      Frequency:
        shape: ou_walk
        unit: Hz
        mean: 50.0
        sigma: 0.015
        tau: 30.0
        precision: 3
        range: [49.0, 51.0]
        limits: {lo: 49.8, hi: 50.2}
      VoltageThd:
        shape: ou_walk
        unit: "%"
        mean: 2.8
        sigma: 0.4
        tau: 180.0
        precision: 2
        range: [0, 12]
        limits: {hi: 5.0, hihi: 8.0}
      EnergyTotal:
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 29500.0
        tier: meter
        precision: 1
        export_metric: true
      ReactiveEnergyTotal:
        shape: counter
        unit: kVArh
        rate: ReactivePower / 3600.0
        initial: 11200.0
        tier: meter
        precision: 1
      PeakDemand:
        shape: window_agg
        unit: kW
        source: ActivePower
        agg: max
        window_s: 900.0
        tier: meter
        precision: 1
      EnergyIntensity:
        shape: derived
        unit: kWh/t
        expr: ActivePower / max(ctx.served_throughput_tph, 0.1)
        tier: meter
        precision: 2
        range: [0, 2000]
      CarbonRate:
        shape: derived
        unit: kgCO2/h
        expr: ActivePower * ctx.grid_co2_g_per_kwh / 1000.0
        precision: 2
        range: [0, 400]

  - id: TR-01
    equipment: TR-01
    # No `site`: Transformer_T1 is a Dormagen-only cell name, so the cell is the selector.
    target: {area: Utilities, line: PowerDistribution, cell: Transformer_T1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: energy
    signals:
      LoadPercent:
        shape: derived
        unit: "%"
        expr: idle_pct + ctx.served_production * span_pct
        params: {idle_pct: 14.0, span_pct: 62.0}
        precision: 1
        range: [0, 120]
        limits: {hi: 95, hihi: 110}
      OilTemperature:
        # Spec 8.1: rises with load and with ambient. Ambient sets the floor the oil can
        # never cool below; load sets how far above that floor it sits.
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 48.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 85, hihi: 95}
      WindingTemperature:
        shape: derived
        unit: "°C"
        expr: OilTemperature + hotspot_k * LoadPercent / 100.0
        params: {hotspot_k: 22.0}
        precision: 1
        range: [-20, 150]
        limits: {hi: 105, hihi: 120}
      TapPosition:
        # `weights` rather than a repeated 0 in `choices`: both bias the draw towards the
        # nominal tap, but only one of them says so.
        shape: stepped
        unit: "1"
        choices: [-2, -1, 0, 1, 2]
        weights: [1, 2, 6, 2, 1]
        dwell_s: 3600.0
        tier: status
        param_type: Status
        precision: 0
      CoolingFanStatus:
        # Spec 8.1 says stepped, and stepped's `source` reads `ctx`, not siblings - so this
        # cannot be driven from OilTemperature and is an honest dwell-timer discrete rather
        # than a fake correlation. The temperature signals above carry the load story.
        shape: stepped
        unit: "1"
        choices: ["Off", "Stage1", "Stage2"]
        weights: [4, 3, 1]
        dwell_s: 900.0
        tier: status
        param_type: Status
      EnergyThroughput:
        shape: counter
        unit: kWh
        rate: LoadPercent * rated_kva / 100.0 / 3600.0
        params: {rated_kva: 2500.0}
        initial: 156000.0
        tier: meter
        precision: 1

  - id: MCC-01
    equipment: MCC-01
    target: {area: Utilities, line: PowerDistribution, cell: MCC_Production}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: energy
    signals:
      ActivePower:
        shape: derived
        unit: kW
        expr: base_load + ctx.served_production * connected_kw
        params: {base_load: 35.0, connected_kw: 610.0}
        precision: 1
        range: [0, 800]
        limits: {hi: 700, hihi: 760}
      Current:
        shape: derived
        unit: A
        expr: ActivePower * 1000.0 / (sqrt(3.0) * nominal_v * pf)
        params: {nominal_v: 400.0, pf: 0.91}
        precision: 1
        range: [0, 1400]
      EnergyTotal:
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 42000.0
        tier: meter
        precision: 1
      FeederTripCount:
        # `rate` is per second, so this is about one trip a fortnight. A counter rather
        # than an event because what a maintenance engineer asks for is the running total.
        shape: counter
        unit: "1"
        rate: 0.0000008
        initial: 3.0
        tier: meter
        precision: 0
      InsulationResistance:
        shape: ou_walk
        unit: "MΩ"
        mean: 180.0
        sigma: 12.0
        tau: 3600.0
        precision: 1
        range: [0, 500]
        limits: {lo: 50, lolo: 20}
      BusbarTemperature:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * ctx.served_production
        params: {rise_k: 26.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 70, hihi: 85}

  - id: MCC-02
    equipment: MCC-02
    # No `serves`: this centre feeds the utility side, so there is no production for its
    # load to follow and an ou_walk is the honest shape.
    target: {area: Utilities, line: PowerDistribution, cell: MCC_Utilities}
    tier: energy
    signals:
      ActivePower:
        shape: ou_walk
        unit: kW
        mean: 310.0
        sigma: 18.0
        tau: 240.0
        precision: 1
        range: [0, 600]
        limits: {hi: 520, hihi: 560}
      Current:
        shape: derived
        unit: A
        expr: ActivePower * 1000.0 / (sqrt(3.0) * nominal_v * pf)
        params: {nominal_v: 400.0, pf: 0.89}
        precision: 1
        range: [0, 1100]
      EnergyTotal:
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 61000.0
        tier: meter
        precision: 1
      FeederTripCount:
        shape: counter
        unit: "1"
        rate: 0.0000005
        initial: 1.0
        tier: meter
        precision: 0
      InsulationResistance:
        shape: ou_walk
        unit: "MΩ"
        mean: 165.0
        sigma: 14.0
        tau: 3600.0
        precision: 1
        range: [0, 500]
        limits: {lo: 50, lolo: 20}
      BusbarTemperature:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * ActivePower / rated_kw
        params: {rise_k: 24.0, rated_kw: 600.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 70, hihi: 85}
```

- [ ] **Step 8: Write `conf/simulator/water.yaml`**

Two decisions to carry over from the energy file, plus one that is specific to water:

- **`CT-01` and `CT-02` are per-site**, because `ReturnTemp` derives from `ctx.served_heat_load` and that needs a site-specific `serves` list. `served_heat_load` is a **sum** over served lines, each in 0–1 (Task 8), so Dormagen's two lines give 0–2 and Krefeld's one gives 0–1. Each tower therefore carries a `served_lines` parameter and divides by it — without that, Krefeld's tower would run at half the ΔT for the same relative load, and the two sites' numbers would not be comparable.
- **`FM-01` is site-agnostic and has no `serves`.** Raw water intake sits behind storage, so it does not track production tick for tick; an `ou_walk` is the honest shape and one template covers both sites' `RawWaterIntake` cells.
- **The cooling tower is where the weather station earns its place.** `SupplyTemp` is the wet-bulb temperature plus an approach that widens under load, so a hot humid afternoon degrades cooling exactly as it does in a real plant. `ApproachTemp` then derives back off `ctx.wet_bulb_temp_c` and varies rather than being a restated constant.

```yaml
# conf/simulator/water.yaml
# Spec 8.2. Raw water, demineralisation, cooling tower, effluent.
# The tower is the correlation showcase: heat load (a lagged follower of production, Task
# 7) sets its delta T, and the site wet-bulb temperature sets the supply temperature it
# can achieve at all.

devices:
  - id: FM-01
    equipment: FM-01
    # No `site` and no `serves`: intake sits behind storage, so it does not follow
    # production tick for tick, and one template covers both sites' intakes.
    target: {area: Utilities, line: WaterTreatment, cell: RawWaterIntake}
    tier: process
    signals:
      FlowRate:
        shape: ou_walk
        unit: "m³/h"
        mean: 145.0
        sigma: 6.0
        tau: 300.0
        precision: 2
        range: [0, 300]
        limits: {hi: 260, hihi: 285}
        export_metric: true
      VolumeTotal:
        shape: counter
        unit: "m³"
        rate: FlowRate / 3600.0
        initial: 1875000.0
        tier: meter
        precision: 2
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 4.2
        sigma: 0.12
        tau: 120.0
        precision: 2
        range: [0, 10]
        limits: {lo: 3.0, lolo: 2.5}
      Temperature:
        # River water follows ambient slowly and from below, which is what the 0.55
        # coefficient and the 4 K offset say.
        shape: derived
        unit: "°C"
        expr: offset_c + slope * ctx.ambient_temp_c
        params: {offset_c: 4.0, slope: 0.55}
        precision: 2
        range: [0, 40]
      Turbidity:
        shape: ou_walk
        unit: NTU
        mean: 3.4
        sigma: 0.8
        tau: 900.0
        precision: 2
        range: [0, 50]
        limits: {hi: 12.0, hihi: 25.0}

  - id: DEMIN-01
    equipment: DEMIN-01
    target: {area: Utilities, line: WaterTreatment, cell: DeminPlant}
    tier: process
    signals:
      ProductFlow:
        shape: ou_walk
        unit: "m³/h"
        mean: 42.0
        sigma: 2.5
        tau: 240.0
        precision: 2
        range: [0, 90]
      Conductivity:
        # Spec 8.2 puts the hi limit at 0.2 µS/cm. Demineralised water is judged on
        # conductivity, so this is the signal an operator actually watches here.
        shape: ou_walk
        unit: "µS/cm"
        mean: 0.09
        sigma: 0.02
        tau: 600.0
        precision: 3
        range: [0, 2]
        limits: {hi: 0.2, hihi: 0.5}
      Silica:
        shape: ou_walk
        unit: ppb
        mean: 8.0
        sigma: 1.6
        tau: 1800.0
        precision: 2
        range: [0, 100]
        limits: {hi: 20.0, hihi: 40.0}
      ResinBedDp:
        shape: ou_walk
        unit: bar
        mean: 0.35
        sigma: 0.04
        tau: 3600.0
        precision: 3
        range: [0, 2]
        limits: {hi: 0.9, hihi: 1.3}
      RegenerationState:
        shape: stepped
        unit: "1"
        choices: ["Service", "Backwash", "Regenerate", "Rinse"]
        weights: [20, 1, 1, 1]
        dwell_s: 1800.0
        tier: status
        param_type: Status
      ProductVolumeTotal:
        shape: counter
        unit: "m³"
        rate: ProductFlow / 3600.0
        initial: 512000.0
        tier: meter
        precision: 2

  - id: CT-01
    equipment: CT-01
    target: {site: Dormagen, area: Utilities, line: WaterTreatment, cell: CoolingTower1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      SupplyTemp:
        # What the tower can deliver: wet bulb plus an approach that widens with load. No
        # tower beats its wet-bulb temperature, so this is the physical floor.
        shape: derived
        unit: "°C"
        expr: ctx.wet_bulb_temp_c + approach_min + approach_span * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {approach_min: 3.2, approach_span: 3.4, served_lines: 2.0}
        precision: 2
        range: [-5, 45]
        limits: {hi: 32.0, hihi: 36.0}
        export_metric: true
      ReturnTemp:
        # Hot water back from the plant. Spec 8.2: derived on ctx.served_heat_load, which
        # is the lagged follower of production - so a hold narrows this over the following
        # minutes rather than in the same second.
        shape: derived
        unit: "°C"
        expr: SupplyTemp + delta_max_k * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {delta_max_k: 9.5, served_lines: 2.0}
        precision: 2
        range: [-5, 60]
        limits: {hi: 42.0, hihi: 46.0}
      DeltaT:
        shape: derived
        unit: K
        expr: ReturnTemp - SupplyTemp
        precision: 2
        range: [0, 20]
        export_metric: true
      CirculationFlow:
        shape: ou_walk
        unit: "m³/h"
        mean: 1150.0
        sigma: 25.0
        tau: 300.0
        precision: 1
        range: [0, 1600]
        limits: {lo: 800, lolo: 600}
      BasinLevel:
        shape: sawtooth
        unit: "%"
        low: 58.0
        high: 84.0
        fill_rate: 0.09
        drain_rate: 0.035
        start: 70.0
        precision: 1
        range: [0, 100]
        limits: {lo: 45, lolo: 30}
      MakeupVolumeTotal:
        # Makeup replaces what evaporates plus what is blown down. Evaporation is the load
        # term, which is why this counter is worth having: it moves with production.
        shape: counter
        unit: "m³"
        rate: (BlowdownFlow + evap_m3h_max * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)) / 3600.0
        params: {evap_m3h_max: 17.5, served_lines: 2.0}
        initial: 268000.0
        tier: meter
        precision: 2
      BlowdownFlow:
        shape: derived
        unit: "m³/h"
        expr: blowdown_fraction * CirculationFlow
        params: {blowdown_fraction: 0.004}
        precision: 3
        range: [0, 20]
      Conductivity:
        shape: ou_walk
        unit: "µS/cm"
        mean: 1450.0
        sigma: 60.0
        tau: 1800.0
        precision: 1
        range: [0, 4000]
        limits: {hi: 2400, hihi: 3000}
      FanSpeed:
        shape: derived
        unit: Hz
        expr: fan_min_hz + fan_span_hz * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {fan_min_hz: 18.0, fan_span_hz: 32.0, served_lines: 2.0}
        precision: 1
        range: [0, 60]
      ApproachTemp:
        # Spec 8.2: derived against ctx.wet_bulb_temp_c. Not a restatement of the constant
        # in SupplyTemp - the approach widens under load, and this is the signal that says
        # so on its own topic.
        shape: derived
        unit: K
        expr: SupplyTemp - ctx.wet_bulb_temp_c
        precision: 2
        range: [0, 15]
        limits: {hi: 8.0, hihi: 11.0}
      BiocideDosingRate:
        shape: stepped
        unit: L/h
        choices: [0.0, 1.8, 3.5]
        weights: [6, 2, 1]
        dwell_s: 3600.0
        tier: status
        precision: 2

  - id: CT-02
    equipment: CT-02
    target: {site: Krefeld, area: Utilities, line: WaterTreatment, cell: CoolingTower1}
    serves: [Krefeld/Production/Line1]
    tier: process
    signals:
      SupplyTemp:
        # served_lines is 1.0 here, not 2.0: served_heat_load is a sum over served lines,
        # so dividing by the wrong count would give Krefeld half the delta T for the same
        # relative load and make the two sites incomparable.
        shape: derived
        unit: "°C"
        expr: ctx.wet_bulb_temp_c + approach_min + approach_span * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {approach_min: 3.6, approach_span: 3.2, served_lines: 1.0}
        precision: 2
        range: [-5, 45]
        limits: {hi: 32.0, hihi: 36.0}
        export_metric: true
      ReturnTemp:
        shape: derived
        unit: "°C"
        expr: SupplyTemp + delta_max_k * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {delta_max_k: 8.5, served_lines: 1.0}
        precision: 2
        range: [-5, 60]
        limits: {hi: 42.0, hihi: 46.0}
      DeltaT:
        shape: derived
        unit: K
        expr: ReturnTemp - SupplyTemp
        precision: 2
        range: [0, 20]
        export_metric: true
      CirculationFlow:
        shape: ou_walk
        unit: "m³/h"
        mean: 480.0
        sigma: 14.0
        tau: 300.0
        precision: 1
        range: [0, 700]
        limits: {lo: 330, lolo: 250}
      BasinLevel:
        shape: sawtooth
        unit: "%"
        low: 60.0
        high: 82.0
        fill_rate: 0.08
        drain_rate: 0.03
        start: 72.0
        precision: 1
        range: [0, 100]
        limits: {lo: 45, lolo: 30}
      MakeupVolumeTotal:
        shape: counter
        unit: "m³"
        rate: (BlowdownFlow + evap_m3h_max * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)) / 3600.0
        params: {evap_m3h_max: 7.2, served_lines: 1.0}
        initial: 96000.0
        tier: meter
        precision: 2
      BlowdownFlow:
        shape: derived
        unit: "m³/h"
        expr: blowdown_fraction * CirculationFlow
        params: {blowdown_fraction: 0.0045}
        precision: 3
        range: [0, 20]
      Conductivity:
        shape: ou_walk
        unit: "µS/cm"
        mean: 1520.0
        sigma: 70.0
        tau: 1800.0
        precision: 1
        range: [0, 4000]
        limits: {hi: 2400, hihi: 3000}
      FanSpeed:
        shape: derived
        unit: Hz
        expr: fan_min_hz + fan_span_hz * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {fan_min_hz: 20.0, fan_span_hz: 30.0, served_lines: 1.0}
        precision: 1
        range: [0, 60]
      ApproachTemp:
        shape: derived
        unit: K
        expr: SupplyTemp - ctx.wet_bulb_temp_c
        precision: 2
        range: [0, 15]
        limits: {hi: 8.0, hihi: 11.0}
      BiocideDosingRate:
        shape: stepped
        unit: L/h
        choices: [0.0, 1.2, 2.4]
        weights: [6, 2, 1]
        dwell_s: 3600.0
        tier: status
        precision: 2

  - id: EFF-01
    equipment: EFF-01
    target: {site: Dormagen, area: Utilities, line: WaterTreatment, cell: EffluentOutfall}
    tier: process
    signals:
      FlowRate:
        shape: ou_walk
        unit: "m³/h"
        mean: 118.0
        sigma: 7.0
        tau: 420.0
        precision: 2
        range: [0, 300]
        limits: {hi: 240, hihi: 270}
      VolumeTotal:
        shape: counter
        unit: "m³"
        rate: FlowRate / 3600.0
        initial: 1420000.0
        tier: meter
        precision: 2
      pH:
        # Spec 8.2: lo 6.5, hi 9.0. Both sides matter - a discharge consent is a band, not
        # a ceiling - which is why this signal has limits in both directions.
        shape: ou_walk
        unit: pH
        mean: 7.6
        sigma: 0.09
        tau: 900.0
        precision: 2
        range: [0, 14]
        limits: {lo: 6.5, hi: 9.0, lolo: 6.0, hihi: 9.5}
      COD:
        shape: ou_walk
        unit: mg/L
        mean: 85.0
        sigma: 9.0
        tau: 1800.0
        precision: 1
        range: [0, 600]
        limits: {hi: 180, hihi: 250}
      TSS:
        shape: ou_walk
        unit: mg/L
        mean: 22.0
        sigma: 4.0
        tau: 1800.0
        precision: 1
        range: [0, 300]
        limits: {hi: 60, hihi: 100}
      Turbidity:
        shape: ou_walk
        unit: NTU
        mean: 6.5
        sigma: 1.4
        tau: 1200.0
        precision: 2
        range: [0, 100]
        limits: {hi: 20.0, hihi: 35.0}
      Temperature:
        # Spec 8.2 puts the hi limit at 35 °C. Effluent leaves warmer than the river it
        # came from, so this tracks ambient with an offset from process heat.
        shape: derived
        unit: "°C"
        expr: offset_c + slope * ctx.ambient_temp_c
        params: {offset_c: 12.0, slope: 0.6}
        precision: 2
        range: [0, 60]
        limits: {hi: 35.0, hihi: 40.0}
      Conductivity:
        shape: ou_walk
        unit: "µS/cm"
        mean: 1180.0
        sigma: 55.0
        tau: 1800.0
        precision: 1
        range: [0, 5000]
        limits: {hi: 2500, hihi: 3200}
      AmmoniumN:
        shape: ou_walk
        unit: mg/L
        mean: 1.4
        sigma: 0.3
        tau: 1800.0
        precision: 3
        range: [0, 20]
        limits: {hi: 5.0, hihi: 8.0}
```

- [ ] **Step 9: Run the new test file**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -v`
Expected: all pass.

If `test_the_full_profile_signal_count_is_the_table_multiplied_out` fails, read the number in the assertion error rather than adjusting the table: a shortfall of exactly one device's worth of signals means a template lost signals in transcription, and a shortfall that is not a multiple of any table entry means a signal was dropped from a device that is otherwise intact.

If a `derived` signal raises `ValueError: unknown name`, the name is a sibling that does not exist or a `params` key that was not declared — both are load-time errors by design (Task 6), and the message names the signal.

- [ ] **Step 10: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes, including the seven pre-existing tests in `test_simulator.py` and the legacy-`plc` regression guard in `test_targeting.py`.

- [ ] **Step 11: Commit**

```bash
git add conf/simulator/plant.yaml conf/simulator/energy.yaml conf/simulator/water.yaml \
        99_simulator/src/uns_simulator/profiles.py 99_simulator/src/uns_simulator/simulator.py \
        99_simulator/pyproject.toml 99_simulator/uv.lock 99_simulator/test/test_conf_files.py
git commit -m "feat(simulator): read conf/simulator YAML and add the energy and water families"
```

---

