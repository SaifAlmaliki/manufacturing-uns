## Task 19: Settings, the volume guard, Docker, README and the ADR

Everything that makes the six family files reachable from a real deployment, plus the one test that stops `full` becoming the default by accident.

**Files:**
- Create: `99_simulator/test/test_volume.py`, `docs/adr/0006-simulator-plant-model-and-signal-generation.md`
- Modify: `conf/settings.yaml:141-175`, `99_simulator/src/uns_simulator/profiles.py`, `99_simulator/src/uns_simulator/simulator.py:35-43`, `99_simulator/test/test_targeting.py`, `99_simulator/Dockerfile:52`, `99_simulator/README.md`

**Interfaces:**
- Consumes: `LoadedProfile` (Task 12), `load_simulator_config` (Task 16), all six family files (Tasks 16–18).
- Produces: `LoadedProfile.messages_per_second(self) -> dict[str, float]` — periodic publish rate per cadence tier. Sub-project B's `GET /simulator/status` returns this as its `msg_per_sec` field, so it lives on the profile rather than in the test.

### The ADR number is 0006, not 0005

Spec §13 says `docs/adr/0005-simulator-plant-model-and-signal-generation.md`, and spec B §11 reasons from "`docs/adr/` currently ends at `0004`". Both are wrong: `docs/adr/0005-graphql-mutations-for-console-configuration.md` is committed and accepted (`58618df2`). This plan's ADR therefore takes **0006**. Reusing 0005 would give the directory two documents with one number, which is the one thing a numbered decision log cannot survive.

### The whole legacy `create_plc` block comes out of `conf/settings.yaml`

Spec §12 says the `simulator.plc` list is "still loaded and still instantiated per production cell", and spec §8.5 moves those same two templates into `production.yaml`. Both at once means both: `simulator.py` keeps `self.plc_templates = list(settings.get("plc") or [])` feeding the legacy `create_plc` path, and `production.yaml`'s `001`/`002` feed `SignalDevice`. The result is two devices publishing `.../Cell1/G1/ProcessValue/Temperature` with independently drawn values — a topic served by two publishers, which no consumer can detect and no test currently forbids.

Spec §13 settles it in one line — "PLC templates migrate out to `production.yaml` (the keys stay supported)" — and that is the reading that keeps §12 true as well: **the keys stay supported by the loader, and stop being declared in the shipped file.** A deployment carrying its own `settings.yaml` with `plc:` still works exactly as before — that is what §12's two rows promise, and Step 1's regression guard is what pins it. The repository's own configuration gets those devices from `production.yaml` instead, once.

**Read `create_plc` (`simulator.py:45-82`) before editing the file, because removing `plc:` alone makes things worse rather than better.** The two branches are mutually exclusive: with `plc_templates` non-empty it instantiates the templates and `continue`s; with `plc_templates` empty it falls through to `equipment_fallback` and creates `simulation.plc_count` copies of it *per cell*. So deleting only the `plc:` list flips the shipped configuration into the fallback branch and produces **eight `MixerTank` PLCs** — 2 per production cell, from `plc_count: 2` — publishing `Temperature` and `Pressure` on topics no family file declares. That is a worse outcome than the double-publish it was meant to fix, and it would not fail a single existing test.

So all three keys go: `plc:`, `simulation.plc_count`, and `equipment.mixer_tank`. `plc_count` is read *only* in the fallback branch, and `mixer_tank` is the only thing that branch can build, so the three are one feature and are removed together. `create_plc()` then returns `[]` for the shipped configuration, `SCADA` and `HMI` are untouched, and every plant signal comes from `SignalDevice`.

Spec §12's "`simulator.equipment.mixer_tank` fallback — still honoured when no templates resolve" is a statement about the loader, and it stays true: `self.equipment_fallback = settings.get("equipment.mixer_tank")` is unchanged, and Step 1's guard exercises that branch by supplying the key directly. A promise about supported configuration is kept by the code that reads it plus a test, not by shipping the configuration switched on.

`simulator.hierarchy` is the opposite case and stays: it is the fallback for a deployment with no `conf/simulator/` directory at all (Task 16), so deleting it would make `raw_config["hierarchy"]` a `KeyError` in exactly the situation it exists to cover. A comment says which file wins, because a hierarchy that is silently ignored is worse than one that is absent.

- [ ] **Step 1: Write the failing tests**

Two files. First, `99_simulator/test/test_volume.py`, which is new:

```python
"""Spec 9 and 14: the shipped default must not be a firehose.

`full` is roughly 100 msg/s of eight-level topics, and the graphdb mapper MERGEs once per
topic level on every message - so the volume risk is Neo4j's write path, not Timescale's.
`small` is the shipped default for that reason, and this file is what keeps it small: a
family added to the wrong profile, or a tier_scale dropped from 6.0 to 1.0, shows up here
rather than in a mapper falling quietly behind in production.

The assertions are bands, not numbers. A tight figure would break on every legitimate device
added, which trains people to edit the test; an order-of-magnitude band breaks only when the
shipped default has genuinely changed character.
"""

from pathlib import Path

import pytest
import yaml
from uns_simulator.profiles import TIER_DEFAULTS, load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"

# Spec 9: "small (default) ~5 msg/s". The ceiling is that figure; the floor catches the
# opposite failure, a profile that resolves to almost nothing and passes by being broken.
SMALL_MAX_MSG_PER_SEC = 5.0
SMALL_MIN_MSG_PER_SEC = 0.5

# Spec 9: "full ~100 msg/s". Bands wide enough to absorb a family gaining a few devices.
FULL_MIN_MSG_PER_SEC = 70.0
FULL_MAX_MSG_PER_SEC = 160.0


@pytest.fixture
def raw():
    return read_simulator_conf(CONF_DIR)


@pytest.fixture
def settings_doc():
    return yaml.safe_load((CONF_DIR / "settings.yaml").read_text(encoding="utf-8"))


def test_the_shipped_default_profile_is_small(settings_doc):
    """The default is a deployment decision, so it is asserted against the shipped file."""
    assert settings_doc["simulator"]["simulation"]["profile"] == "small"


def test_the_shipped_config_declares_a_seed(settings_doc):
    """Spec 14 mitigates flaky correlation tests with a fixed default seed.

    Absent, every restart reshuffles every signal and two runs of the same profile cannot be
    compared - which is most of the value of having a profile.
    """
    assert isinstance(settings_doc["simulator"]["simulation"]["seed"], int)


def test_the_legacy_create_plc_config_is_no_longer_declared_in_settings(settings_doc):
    """The three keys of the legacy generator are one feature and leave together.

    `plc:` leaves because production.yaml declares those two templates now, and declared in
    both they publish twice. `equipment.mixer_tank` and `plc_count` leave with it because
    create_plc's two branches are mutually exclusive: with no `plc:` list it falls through to
    the fallback and builds `plc_count` MixerTanks per cell, so removing one key and not the
    other three would replace a double-publish with eight undeclared devices.

    simulator.py still reads all three for deployments that carry their own settings.yaml;
    test_targeting.py exercises both branches. This asserts about the shipped file only.
    """
    simulator = settings_doc["simulator"]
    assert "plc" not in simulator
    assert "mixer_tank" not in simulator.get("equipment", {})
    assert "plc_count" not in simulator["simulation"]


def test_the_settings_hierarchy_is_kept_as_the_no_conf_simulator_fallback(settings_doc):
    """Removing it would make raw_config["hierarchy"] a KeyError when conf/simulator/ is absent."""
    assert settings_doc["simulator"]["hierarchy"]["enterprise"] == "CovestroAG"


def test_small_stays_under_the_default_ceiling(raw):
    rate = sum(load_profile(raw, "small").messages_per_second().values())
    assert SMALL_MIN_MSG_PER_SEC < rate < SMALL_MAX_MSG_PER_SEC, f"small resolved to {rate:.2f} msg/s"


def test_full_is_in_the_band_the_spec_claims(raw):
    rate = sum(load_profile(raw, "full").messages_per_second().values())
    assert FULL_MIN_MSG_PER_SEC < rate < FULL_MAX_MSG_PER_SEC, f"full resolved to {rate:.2f} msg/s"


def test_full_is_at_least_an_order_of_magnitude_busier_than_small(raw):
    """The two profiles must be genuinely different, not two names for the same load.

    This is the assertion that survives the device inventory growing: both bands above move
    together, this ratio does not.
    """
    small = sum(load_profile(raw, "small").messages_per_second().values())
    full = sum(load_profile(raw, "full").messages_per_second().values())
    assert full / small > 20.0


def test_the_fast_tier_is_absent_from_small(raw):
    """A 1 s tier in the default profile would dominate everything else in this file."""
    assert load_profile(raw, "small").messages_per_second()["fast"] == 0.0


def test_every_signal_lands_on_a_known_tier(raw):
    """The only check that a per-signal `tier` is spelled correctly.

    `_resolve_tiers` validates the keys of a `simulation.tiers` override, and nothing
    validates a `tier:` written on a signal. A typo there does not raise - the signal is
    simply never scheduled, and a silently unpublished topic is the hardest kind of bug to
    notice in a simulator whose whole output is topics.
    """
    for profile_name in ("small", "full"):
        for device in load_profile(raw, profile_name).devices:
            for signal in device.signals:
                assert signal.tier in TIER_DEFAULTS, f"{device.id}/{signal.name}: unknown tier {signal.tier!r}"


def test_messages_per_second_reports_every_tier(raw):
    """Sub-project B renders this per tier, so a missing key is a missing row, not a zero."""
    rates = load_profile(raw, "full").messages_per_second()
    assert set(rates) == set(TIER_DEFAULTS)
    assert rates["event"] == 0.0  # `event` publishes on change; it has no periodic rate
```

Second, the regression guard spec §11 asks `test_targeting.py` for: "the existing `simulator.plc` + `equipment.mixer_tank` config still produces exactly today's 8 devices with today's topics". It could not be written before now, because until this task the legacy config was still live and the guard would have been asserting the status quo against itself. Now that the shipped file no longer declares it, the guard is the only thing standing between "the keys stay supported" and a quiet regression.

The legacy literal below is deliberately a second, independent copy of frozen history — Task 18's `LEGACY_PLC_SENSORS` in `test_conf_files.py` pins `production.yaml` to the same past. Two independent witnesses is what a regression guard wants: edit either one and the other still testifies. Sharing a constant between them would let one edit move both.

Append to `99_simulator/test/test_targeting.py`:

```python
# The `simulator.plc` and `simulator.equipment.mixer_tank` blocks as conf/settings.yaml held
# them before Task 19 removed them, and the hierarchy they expanded against. Frozen history:
# nothing should ever edit these to make a test pass. `create_plc` is legacy and its output
# is what spec 12 promises stays identical for a deployment that still configures it.
LEGACY_HIERARCHY = {
    "enterprise": "CovestroAG",
    "sites": [
        {
            "name": "Dormagen",
            "areas": [
                {
                    "name": "Production",
                    "lines": [
                        {"name": "Line1", "cells": ["Cell1", "Cell2"]},
                        {"name": "Line2", "cells": ["Cell1"]},
                    ],
                }
            ],
        },
        {"name": "Krefeld", "areas": [{"name": "Production", "lines": [{"name": "Line1", "cells": ["Cell1"]}]}]},
    ],
}

LEGACY_PLC = [
    {
        "id": "001",
        "equipment": "G1",
        "sensors": {
            "Temperature": {"base_value": 75.0, "variation": 2.0, "unit": "°C"},
            "Pressure": {"base_value": 150.0, "variation": 5.0, "unit": "psi"},
        },
    },
    {"id": "002", "equipment": "FillingMachine", "sensors": {"FlowRate": {"base_value": 450.0, "variation": 20.0, "unit": "L/min"}}},
]

LEGACY_MIXER_TANK = {
    "name": "MixerTank",
    "sensors": {
        "Temperature": {"base_value": 75.0, "variation": 2.0, "unit": "°C"},
        "Pressure": {"base_value": 150.0, "variation": 5.0, "unit": "psi"},
    },
}

TODAYS_LEGACY_TOPIC_PREFIXES = {
    "CovestroAG/Dormagen/Production/Line1/Cell1/G1",
    "CovestroAG/Dormagen/Production/Line1/Cell2/G1",
    "CovestroAG/Dormagen/Production/Line2/Cell1/G1",
    "CovestroAG/Krefeld/Production/Line1/Cell1/G1",
    "CovestroAG/Dormagen/Production/Line1/Cell1/FillingMachine",
    "CovestroAG/Dormagen/Production/Line1/Cell2/FillingMachine",
    "CovestroAG/Dormagen/Production/Line2/Cell1/FillingMachine",
    "CovestroAG/Krefeld/Production/Line1/Cell1/FillingMachine",
}


def _legacy_simulator(plc_templates, equipment_fallback, plc_count=2):
    """A UnifiedNamespaceSimulator with only the attributes create_plc reads.

    `__new__` rather than `__init__` for the same reason test_hierarchy.py does it: `__init__`
    loads profiles, builds a PlantContext and constructs MQTT devices, none of which the
    legacy path touches.
    """
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sim.mqtt_config = {}
    sim.hierarchies = expand_hierarchy_paths(LEGACY_HIERARCHY)
    sim.plc_templates = plc_templates
    sim.equipment_fallback = equipment_fallback
    sim.simulation_config = {"plc_count": plc_count}
    return sim


def test_the_legacy_plc_config_still_produces_todays_eight_devices(monkeypatch):
    """Spec 11's regression guard: two templates times four production cells, same topics."""
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    plcs = _legacy_simulator(LEGACY_PLC, None).create_plc()

    assert len(plcs) == 8  # noqa: PLR2004
    prefixes = {
        plc.hierarchy.get_parameter_topic(plc.equipment.name, ParameterType.PROCESS_VALUE, "x").rsplit("/", 2)[0]
        for plc in plcs
    }
    assert prefixes == TODAYS_LEGACY_TOPIC_PREFIXES
    assert len({plc.plc_id for plc in plcs}) == 8, "device ids stay unique per cell"  # noqa: PLR2004


def test_the_mixer_tank_fallback_is_still_honoured_when_no_templates_resolve(monkeypatch):
    """Spec 12's second row. Also the branch that makes removing only `plc:` a mistake.

    Empty templates plus a fallback is `plc_count` MixerTanks per cell - eight here - which is
    why Task 19 removes `plc_count` and `equipment.mixer_tank` alongside `plc:` rather than
    leaving the shipped file one deletion away from publishing them.
    """
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    plcs = _legacy_simulator([], LEGACY_MIXER_TANK).create_plc()

    assert len(plcs) == 8  # noqa: PLR2004
    assert {plc.equipment.name for plc in plcs} == {"MixerTank"}


def test_no_legacy_devices_are_created_without_templates_or_a_fallback(monkeypatch):
    """What the shipped configuration now resolves to: nothing from the legacy path."""
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    assert _legacy_simulator([], None).create_plc() == []
```

`test_targeting.py` gains four imports for this — put them with the existing ones at the top of the file, since a function-scope import trips ruff's preview `PLC0415`:

```python
from uns_simulator import devices
from uns_simulator.models import ParameterType, expand_hierarchy_paths
from uns_simulator.simulator import UnifiedNamespaceSimulator
```

`DummyClient` is the two-method async context manager already defined in `test_hierarchy.py`; copy it into `test_targeting.py` rather than importing across test modules. It is nine lines, and `test_devices.py` (Task 13) has its own richer copy for the same reason.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd 99_simulator && uv run pytest test/test_volume.py -x`
Expected: `AttributeError: 'LoadedProfile' object has no attribute 'messages_per_second'`.

Run: `cd 99_simulator && uv run pytest test/test_targeting.py -k "legacy or mixer" -v`
Expected: the three new cases fail on the missing imports, then — once those are added — `test_the_legacy_create_plc_config_is_no_longer_declared_in_settings` in `test_volume.py` is the only remaining failure, because the settings edit has not happened yet. The three `create_plc` cases supply their own configuration and should pass as soon as they import, which is the point: they do not depend on what `settings.yaml` says.

- [ ] **Step 3: Add `messages_per_second` to `LoadedProfile`**

In `99_simulator/src/uns_simulator/profiles.py`, add the method to `LoadedProfile`:

```python
    def messages_per_second(self) -> dict[str, float]:
        """Periodic publish rate per cadence tier, for the volume guard and the control API.

        Counts periodic publishing only. A `tier` whose interval is 0.0 - `event`, by
        default - publishes on change and contributes nothing here, which is honest rather
        than convenient: the two `bernoulli_event` detector faults in safety.yaml average
        about one message a fortnight each, and rounding that to zero is the right rounding.

        A signal on an unrecognised tier is skipped rather than crashing a status endpoint;
        `test_volume.py` is what makes such a signal fail loudly at the right time.
        """
        rates = dict.fromkeys(self.tiers, 0.0)
        for device in self.devices:
            if not device.enabled:
                continue
            for signal in device.signals:
                interval = self.tiers.get(signal.tier, 0.0)
                if interval > 0.0:
                    rates[signal.tier] += 1.0 / interval
        return rates
```

`dict.fromkeys(self.tiers, 0.0)` rather than a comprehension over `TIER_DEFAULTS`: `self.tiers` is already the scaled, override-merged mapping with exactly the default tier names as keys, so this reports the tiers this profile actually runs.

- [ ] **Step 4: Amend `conf/settings.yaml`**

Replace the `plc:` block (lines 141–159) and the `simulation:` block (lines 160–163) with a `simulation:` block only:

```yaml
  # The legacy `plc:` list moved to conf/simulator/production.yaml as templates `001` and
  # `002`, unchanged. `simulator.py` still reads this key, so a deployment carrying its own
  # settings.yaml with `plc:` keeps working - but declaring it here as well as in
  # production.yaml would put two publishers on every G1 and FillingMachine topic.
  simulation:
    # Spec 9: `small` is the shipped default because the graphdb mapper MERGEs once per topic
    # level on every message. Switch to `full` for the complete ~55-device plant.
    profile: "small"
    # A fixed seed makes two runs of one profile comparable. Change it to get a different
    # plant with the same shape.
    seed: 20260831
    # Superseded by `tiers` below, which is why it still reads 5.0: spec 12 requires
    # `interval` to be honoured as the `process` tier when no `tiers` block exists, and a
    # deployment that deletes `tiers` should land back on today's behaviour, not on a default.
    interval: 5.0
    duration: 5  # minutes; 0 = run until stopped (Compose sets this to 0)
    # Seconds per cadence tier, before the profile's `tier_scale` multiplies them. `event` is
    # 0.0 meaning "publish on change", and scaling zero keeps it zero - a slow profile must
    # not turn an alarm topic into a slow periodic one.
    tiers:
      fast: 1.0
      process: 5.0
      energy: 15.0
      status: 30.0
      meter: 900.0
      lab: 1800.0
      event: 0.0
```

Then delete the `equipment:` block (lines 164–175 of the original file) as well, so the region from the old `plc:` through the old `equipment.mixer_tank` is replaced by the `simulation:` block above and nothing else. `dynaconf_merge: true` on the last line stays.

The file's `simulator` section afterwards is exactly three keys — `mqtt`, `hierarchy`, `simulation` — and `create_plc()` returns `[]`. If a diff shows `plc_count` or `mixer_tank` surviving, the shipped configuration publishes eight `MixerTank` PLCs; `test_the_legacy_create_plc_config_is_no_longer_declared_in_settings` is what catches that.

Add one comment above the existing `hierarchy:` key, which is otherwise indistinguishable from live configuration:

```yaml
  # Fallback only. conf/simulator/plant.yaml replaces this whole block when it exists, and it
  # does in this repository - so edits here have no effect unless that file is removed. Kept
  # because a deployment with no conf/simulator/ directory still has to have a plant.
  hierarchy:
```

- [ ] **Step 5: Wire `simulation.seed` in `simulator.py`**

Task 15 left `__init__` passing only its own `seed` argument, so `simulation.seed` in `settings.yaml` would be read by nobody. Change the one line:

```python
        requested = profile_name or self.simulation_config.get("profile", "full")
        configured_seed = seed if seed is not None else self.simulation_config.get("seed")
        raw_config = load_simulator_config(settings)
        self.profile: LoadedProfile = load_profile(raw_config, requested, seed=configured_seed)
```

The constructor argument still wins, because that is how sub-project B's `PUT /simulator/profile` will pass a seed chosen in the console, and a file must not override a deliberate runtime choice.

- [ ] **Step 6: Run the tests**

Run: `cd 99_simulator && uv run pytest test/test_volume.py test/test_targeting.py -v`
Expected: all pass.

If `test_small_stays_under_the_default_ceiling` fails high, print the breakdown before changing the threshold:

```bash
cd 99_simulator && uv run python -c "
from pathlib import Path
from uns_simulator.profiles import load_profile, read_simulator_conf
p = load_profile(read_simulator_conf(Path('../conf')), 'small')
print(p.report.per_family)
print({k: round(v, 3) for k, v in p.messages_per_second().items()})
"
```

A non-zero `fast` entry means `asset_health` reached `small`. A `process` figure six times what you expected means `tier_scale` is 1.0 rather than 6.0.

- [ ] **Step 7: Add the Docker copy line**

In `99_simulator/Dockerfile`, after line 52:

```dockerfile
COPY ./conf/settings.yaml /app/conf/settings.yaml
COPY ./conf/simulator /app/conf/simulator
```

Compose and the `docker run` in the file's own header comment both bind-mount the whole of `./conf`, so neither is affected. The line is for the case where nothing is mounted: without it the image starts, finds no `conf/simulator/` directory, silently falls back to `simulator.hierarchy`, and — with the legacy generator now gone from that file too — publishes nothing but `SCADA` and `HMI`. A container that starts, connects, logs no error and simulates no plant. `COPY ./conf/settings.yaml` on the line above exists for exactly that reason, and the new directory is now half of the configuration it was standing in for.

- [ ] **Step 8: Write the README section**

Add to `99_simulator/README.md`, after the "Repository layout" section. Also add the four new modules to that layout list:

```markdown
- src/uns_simulator/
  - signals.py — the ten signal shapes and their status derivation ([src/uns_simulator/signals.py](src/uns_simulator/signals.py))
  - expressions.py — the whitelisted expression evaluator used by `derived` and `counter` ([src/uns_simulator/expressions.py](src/uns_simulator/expressions.py))
  - plant.py — PackML line state, site ambient conditions, the plant clock ([src/uns_simulator/plant.py](src/uns_simulator/plant.py))
  - profiles.py — device targeting, profile resolution, the conf/simulator reader ([src/uns_simulator/profiles.py](src/uns_simulator/profiles.py))
```

Then the section itself:

````markdown
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
````

- [ ] **Step 9: Write the ADR**

Create `docs/adr/0006-simulator-plant-model-and-signal-generation.md`, following the shape of `0005`:

```markdown
---
status: accepted
---

# Simulator plant model and signal generation

The simulator published two PLC templates of Gaussian noise per production cell. It now
publishes about 55 devices and 430 signals across six families — energy, water, utilities,
asset health, production and safety — and every value is computed from one shared plant
state rather than drawn independently.

Independent noise is enough to prove a mapper writes what it receives, and that is all the
old simulator was for. It is not enough to develop against. A console showing site kW, a
cooling tower supply temperature and a line's PackML state side by side is showing three
unrelated random walks, so nothing built on top can be checked: an OEE calculation cannot be
wrong, a correlation cannot be missing, an alarm cannot be spurious, because there is no
underlying fact for any of them to disagree with. Every consumer in this platform — the
graphdb mapper's node model, the historian's Metric extraction, the frontend's Process
Visualization, the Alert Rules of ADR 0005 — is developed against this data.

So the simulator gained a model of the plant: a PackML state machine per production line
taking only legal transitions, ambient conditions per site, and a `PlantContext` that every
device reads. A compressor's load follows the air demand of the lines it serves. A cooling
tower's approach temperature is set by the wet bulb the weather station publishes. Values
move together because they are computed from the same state, which is what makes them worth
developing against.

## Considered Options

**More templates of the same kind** was rejected. Reaching 400 signals by adding 400 more
independent generators multiplies the output and adds nothing: the failure is that the values
are unrelated, and more unrelated values is more of the failure.

**Replaying a recorded plant dataset** was rejected. It would be the most realistic option
and the least usable one: a fixed recording cannot be started, stopped, held or reconfigured,
it cannot exercise a state the recording never entered, and the recording itself would be
plant data with all the handling that implies.

**A physics solver** was rejected as the wrong tool. Mass and energy balances would buy
accuracy nobody consuming this data can use, at the cost of a component whose behaviour is
harder to predict than the platform it exists to test. First-order lags and algebraic
relations between named signals are enough for every correlation the platform needs to show.

**One topic per signal** was retained rather than bundling signals into nested payloads.
Bundling would cut the message count several-fold, which is tempting given that the volume
constraint is real. It was rejected because the Metric Key in `CONTEXT.md` is the topic
segments below the Asset plus the dotted path within the payload, so bundling changes the
shape of every Metric Key in the platform — a data-model change, made to relieve a load
problem that a profile already solves.

## Consequences

Volume is now a real constraint, and it lands on Neo4j rather than Timescale: the graphdb
mapper performs `MERGE` work per topic level on every message, while the historian appends.
`full` is roughly 120 msg/s of eight-level topics. So `small` — one site, three families, all
cadences scaled by six, about 2 msg/s — is the shipped default, `full` is opt-in through
`simulator.simulation.profile`, and `test_volume.py` asserts the default stays small.

Configuration moved out of `conf/settings.yaml` into `conf/simulator/*.yaml`, read directly
rather than through Dynaconf, because `uns_config.get_settings()` hardcodes its settings
files for all nine modules and widening it for one would change config loading platform-wide.
The `simulator.plc` and `simulator.equipment.mixer_tank` keys stay supported by the loader but
are no longer declared in the shipped file, because `create_plc`'s two branches are mutually
exclusive and leaving either key in place would have the legacy generator publishing on top of
the new devices — the same topics twice from `plc:`, or eight undeclared `MixerTank`s from the
fallback. The two PLC templates are declared in `conf/simulator/production.yaml` instead, with
their equipment names, base values, variations and Units of Measure unchanged, so the topics
and payloads they produced before are the topics and payloads they produce now.

`derived` signals introduced an expression language, which is a cost. It is bounded by being
a whitelisted AST walk over arithmetic, comparisons, `ctx.*` and seven named functions, with
every rejection raised when the file loads and naming the offending construct. There is no
`eval` anywhere in it.
```

- [ ] **Step 10: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes, including the seven pre-existing `test_simulator.py` cases and `test_targeting.py`'s legacy-`plc` regression guard — that guard builds its own template list rather than reading `conf/settings.yaml`, so removing the shipped `plc:` block does not weaken it.

Then confirm the container still starts with no bind mount, which is the only thing Step 7 changes:

```bash
docker build -t uns/simulator:local --build-arg GIT_HASH=local -f 99_simulator/Dockerfile .
docker run --rm --name uns_sim_smoke uns/simulator:local
```

Expected: the startup log line `Loaded profile small: 11 devices, 76 signals across energy, production, water`. It will then fail to reach a broker, which is correct for a container with no network — the profile line is what this checks.

- [ ] **Step 11: Commit**

```bash
git add conf/settings.yaml 99_simulator/src/uns_simulator/profiles.py 99_simulator/src/uns_simulator/simulator.py \
        99_simulator/test/test_volume.py 99_simulator/test/test_targeting.py \
        99_simulator/Dockerfile 99_simulator/README.md \
        docs/adr/0006-simulator-plant-model-and-signal-generation.md
git commit -m "feat(simulator): ship the small profile by default, guard message volume, document the plant model"
```
