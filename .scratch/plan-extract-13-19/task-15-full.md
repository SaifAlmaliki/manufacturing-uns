## Task 15: Wire the simulator — profile loading, the clock, and one task per tier

The last code task. `run_simulation` currently schedules `device.start(interval)` for every device on one interval (`simulator.py:147-150`). It now runs the `PlantClock` as its own task, evaluates every `SignalDevice` on each tick, and schedules one publish task per `(device, tier)` pair. `PLC`/`SCADA`/`HMI` keep working exactly as they do, so the legacy `plc:` config in `conf/settings.yaml` remains valid.

**Files:**
- Modify: `99_simulator/src/uns_simulator/simulator.py`
- Test: `99_simulator/test/test_simulator.py`

**Interfaces:**
- Consumes: `load_profile`/`LoadedProfile`/`TIER_DEFAULTS` (Task 12), `PlantClock`/`DeviceView` (Tasks 8–9), `SignalDevice` (Task 14).
- Produces on `UnifiedNamespaceSimulator`:
  - `.profile: LoadedProfile | None`, `.clock: PlantClock | None`, `.signal_devices: list[SignalDevice]`.
  - `load_simulator_config(settings_obj: Any) -> dict[str, Any]` — module-level; assembles the mapping `load_profile` expects from the Dynaconf settings object, so tests can call `load_profile` with a plain dict and production goes through this one adapter.
  - `create_signal_devices(self) -> list[SignalDevice]` — builds one `SignalDevice` per `DeviceSpec`, each with its own `DeviceView`.
  - `tick(self, dt: float) -> None` — evaluates every enabled `SignalDevice`. Driven by `_run_clock`.
  - `async _run_clock(self) -> None` — the clock task: advance, evaluate, sleep, in that order.
  - `announce_device_count(self) -> None` — replaces `SCADA`'s random device count with the real one.
  - `status(self) -> dict[str, Any]` — `{profile, seed, device_count, signal_count, tiers, families, per_tier, broker_connected, published_total, failed_total, tick_count}`. Sub-project B's `GET /simulator/status` extends this rather than inventing it.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_simulator.py
from uns_simulator import devices as devices_module
from uns_simulator.models import expand_hierarchy_paths
from uns_simulator.plant import PlantClock
from uns_simulator.profiles import TIER_DEFAULTS, load_profile
from uns_simulator.simulator import UnifiedNamespaceSimulator

HIERARCHY = {
    "enterprise": "CovestroAG",
    "sites": [
        {
            "name": "Dormagen",
            "areas": [
                {
                    "name": "Production",
                    "kind": "production",
                    "lines": [{"name": "Line1", "nameplate_tph": 12.0, "cells": ["Cell1"]}],
                },
                {
                    "name": "Utilities",
                    "kind": "utilities",
                    "lines": [{"name": "Powerhouse", "cells": ["Cell1"]}],
                },
            ],
        }
    ],
}

RAW = {
    "hierarchy": HIERARCHY,
    # `starting_s` of 1 s and no holds, so 30 ticks are enough to reach EXECUTE and stay there.
    "plant": {"lines": {"Dormagen/Production/Line1": {"starting_s": 1.0, "hold_probability_per_hour": 0.0}}},
    "energy": {
        "devices": [
            {
                "id": "MAIN",
                "equipment": "MainIncomer",
                "target": {"kind": "utilities"},
                "tier": "energy",
                "serves": ["Dormagen/Production/Line1"],
                "signals": {
                    "ActivePower": {
                        "shape": "derived",
                        "unit": "kW",
                        "precision": 1,
                        "expr": "80 + ctx.served_production * 320",
                    },
                    "EnergyTotal": {
                        "shape": "counter",
                        "unit": "kWh",
                        "tier": "meter",
                        "precision": 4,
                        "rate": "ActivePower / 3600.0",
                    },
                },
            }
        ]
    },
    "profiles": {"full": {"families": ["energy"]}},
    "simulation": {"seed": 1234, "interval": 5.0, "duration": 0},
}


@pytest.fixture(autouse=True)
def _dummy_broker(monkeypatch):
    """Same pattern as test_devices.py: never touch a real broker."""
    from test.test_devices import DummyClient  # noqa: PLC0415

    monkeypatch.setattr(devices_module.aiomqtt, "Client", DummyClient)


def _sim():
    """A simulator with the profile loaded but `__init__` bypassed.

    `__init__` reads the global Dynaconf `settings`; these tests need a fixture dict instead,
    so they assemble the same attributes by hand. Everything `run_simulation` touches is set.
    """
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sim.mqtt_config = {}
    sim.simulation_config = RAW["simulation"]
    sim.hierarchies = expand_hierarchy_paths(HIERARCHY)
    sim.hierarchy = sim.hierarchies[0]
    sim.plc_templates = []
    sim.equipment_fallback = None
    sim.devices = []
    sim.tasks = []
    sim.profile = load_profile(RAW, "full")
    sim.clock = PlantClock(sim.profile.context, tick_s=1.0)
    sim.signal_devices = sim.create_signal_devices()
    return sim


def test_create_signal_devices_builds_one_device_per_spec():
    sim = _sim()
    assert len(sim.signal_devices) == 1
    device = sim.signal_devices[0]
    assert device.spec.equipment == "MainIncomer"
    assert device.tiers == {"energy", "meter"}


def test_a_utility_device_has_no_line_of_its_own_but_serves_one():
    """MAIN sits in the Utilities area, which spec 6.1 gives no `LineState`."""
    sim = _sim()
    view = sim.signal_devices[0].view
    assert view.site == "Dormagen"
    assert view.line is None
    assert view.served_line_count == 1


def test_tick_evaluates_every_device():
    sim = _sim()
    sim.tick(1.0)
    values = sim.signal_devices[0].values
    assert values["ActivePower"] >= 80.0  # noqa: PLR2004
    assert values["EnergyTotal"] > 0.0


def test_utility_power_follows_the_production_it_serves():
    """The whole point of the plant context: an idle line means an idle chiller."""
    sim = _sim()
    sim.tick(1.0)
    idle_power = sim.signal_devices[0].values["ActivePower"]
    for _ in range(30):
        sim.clock.advance()
        sim.tick(1.0)
    running_power = sim.signal_devices[0].values["ActivePower"]
    # Keyed `<Area>/<Line>` within the site, so `Line1` in two areas cannot collide.
    assert sim.profile.context.sites["Dormagen"].lines["Production/Line1"].state == "EXECUTE"
    # 80 kW idle against 80 + ~0.9 * 320 running: comfortably more than double.
    assert running_power > idle_power * 2


def test_energy_accumulates_monotonically_across_ticks():
    sim = _sim()
    readings = []
    for _ in range(20):
        sim.clock.advance()
        sim.tick(1.0)
        readings.append(sim.signal_devices[0].values["EnergyTotal"])
    assert all(b >= a for a, b in zip(readings, readings[1:], strict=False))
    assert readings[-1] > readings[0]


def test_status_reports_the_loaded_profile():
    sim = _sim()
    status = sim.status()
    assert status["profile"] == "full"
    assert status["seed"] == 1234  # noqa: PLR2004
    assert status["device_count"] == 1
    assert status["signal_count"] == 2  # noqa: PLR2004
    # `full` leaves `tier_scale` at its 1.0 default, so the pre-scaled tiers are the defaults.
    assert status["tiers"]["meter"] == TIER_DEFAULTS["meter"]
    assert status["families"] == {
        "energy": True,
        "water": False,
        "utilities": False,
        "asset_health": False,
        "production": False,
        "safety": False,
    }
    assert status["per_tier"] == {"energy": 1, "meter": 1}
    assert status["published_total"] == 0
    assert status["failed_total"] == 0


@pytest.mark.asyncio
async def test_run_simulation_schedules_the_clock_and_one_task_per_device_tier(monkeypatch):
    sim = _sim()
    monkeypatch.setattr(sim, "create_plc", lambda: [])
    monkeypatch.setattr(sim, "create_scada", lambda: [])
    monkeypatch.setattr(sim, "create_hmi", lambda: [])
    sim.profile.tiers["energy"] = 0.01
    sim.profile.tiers["meter"] = 0.01

    task = asyncio.create_task(sim.run_simulation(0))
    await asyncio.sleep(0.1)
    await sim._stop_simulation()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Both tiers were scheduled, so both signals published even though they run on separate
    # tasks at separate intervals. The last two segments of the eight-level topic are
    # ParameterType/ParameterName.
    published = sim.signal_devices[0].client.published
    topics = {"/".join(topic.split("/")[-2:]) for topic, _ in published}
    assert "ProcessValue/ActivePower" in topics
    assert "ProcessValue/EnergyTotal" in topics


@pytest.mark.asyncio
async def test_a_zero_interval_tier_is_not_scheduled_as_a_busy_loop(monkeypatch):
    """The 'event' tier has interval 0 and publishes on change from the tick, not a loop."""
    sim = _sim()
    monkeypatch.setattr(sim, "create_plc", lambda: [])
    monkeypatch.setattr(sim, "create_scada", lambda: [])
    monkeypatch.setattr(sim, "create_hmi", lambda: [])
    sim.profile.tiers["energy"] = 0.0
    sim.profile.tiers["meter"] = 0.0
    task = asyncio.create_task(sim.run_simulation(0))
    await asyncio.sleep(0.05)
    await sim._stop_simulation()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sim.signal_devices[0].client.published == []


def test_scada_is_told_the_real_device_count():
    sim = _sim()
    sim.devices = [*sim.signal_devices, *sim.create_scada()]
    sim.announce_device_count()
    scada = [d for d in sim.devices if isinstance(d, devices_module.SCADA)]
    assert scada
    assert scada[0].connected_devices == len(sim.signal_devices)
```

The five pre-existing tests in `test_simulator.py` (`resolve_simulation_duration` × 5 and `_run_until` × 2) must stay untouched and green.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_simulator.py -v`
Expected: the seven pre-existing tests pass; the new ones fail on `AttributeError: 'UnifiedNamespaceSimulator' object has no attribute 'create_signal_devices'`.

- [ ] **Step 3: Add the settings adapter and extend `__init__`**

```python
# add to simulator.py, module level
def load_simulator_config(settings_obj: Any) -> dict[str, Any]:
    """Assemble the mapping load_profile expects out of the Dynaconf settings object.

    One adapter, so tests hand load_profile a plain dict and never depend on Dynaconf, and
    production has exactly one place where the two representations meet.
    """
    raw: dict[str, Any] = {
        "hierarchy": settings_obj.get("hierarchy") or {},
        "plant": settings_obj.get("plant") or {},
        "profiles": settings_obj.get("profiles") or {},
        "simulation": settings_obj.get("simulation") or {},
    }
    for family in FAMILIES:
        raw[family] = settings_obj.get(family) or {}
    return raw
```

Extend `UnifiedNamespaceSimulator.__init__` (`simulator.py:35-43`), keeping every existing line:

```python
    def __init__(self, profile_name: str | None = None, seed: int | None = None):
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(settings.hierarchy)
        self.hierarchy = self.hierarchies[0]
        self.plc_templates = list(settings.get("plc") or [])
        self.equipment_fallback = settings.get("equipment.mixer_tank")
        self.devices: list = []
        self.tasks: list[asyncio.Task] = []

        requested = profile_name or self.simulation_config.get("profile", "full")
        self.profile: LoadedProfile = load_profile(load_simulator_config(settings), requested, seed=seed)
        self.clock = PlantClock(self.profile.context, tick_s=float(self.simulation_config.get("tick_s", 1.0)))
        self.signal_devices: list[SignalDevice] = self.create_signal_devices()
        LOGGER.info(
            "Loaded profile %s: %d devices, %d signals across %s",
            self.profile.name,
            self.profile.report.devices,
            self.profile.report.signals,
            ", ".join(sorted(self.profile.report.per_family)) or "no families",
        )
        for warning in self.profile.report.warnings + self.profile.report.unmatched_templates:
            LOGGER.warning("profile %s: %s", self.profile.name, warning)
```

- [ ] **Step 4: Add `create_signal_devices`, `tick`, `status` and `announce_device_count`**

```python
    def create_signal_devices(self) -> list[SignalDevice]:
        """One SignalDevice per resolved DeviceSpec, each with its own read-only view."""
        built: list[SignalDevice] = []
        for spec in self.profile.devices:
            # Only production areas have a LineState (spec 6.1: a compressor house has no
            # batch to be IDLE between), so a utility device's view carries `line=None` and
            # reads production through `serves` instead. The line key is `<Area>/<Line>`,
            # matching how `build_plant_context` registered it.
            line = f"{spec.path.area}/{spec.path.line}" if spec.path.kind == PRODUCTION_KIND else None
            view = DeviceView(self.profile.context, spec.path.site, line, spec.serves)
            built.append(SignalDevice(spec, self.mqtt_config, view, self.profile.seed))
        return built

    def tick(self, dt: float) -> None:
        """Advance every enabled device's signals. Called once per plant tick."""
        for device in self.signal_devices:
            if device.enabled:
                device.evaluate(dt)

    def announce_device_count(self) -> None:
        """Tell every SCADA how many devices actually exist, instead of a random guess."""
        count = len(self.signal_devices)
        for device in self.devices:
            if isinstance(device, SCADA):
                device.connected_devices = count

    def status(self) -> dict[str, Any]:
        """Runtime status. Sub-project B's GET /simulator/status extends this body."""
        per_tier: dict[str, int] = {}
        for device in self.signal_devices:
            for spec in device.spec.signals:
                per_tier[spec.tier] = per_tier.get(spec.tier, 0) + 1
        return {
            "profile": self.profile.name,
            "seed": self.profile.seed,
            "device_count": len(self.signal_devices),
            "signal_count": sum(len(d.spec.signals) for d in self.signal_devices),
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "per_tier": per_tier,
            "broker_connected": any(d.connected for d in self.signal_devices),
            "published_total": sum(d.publish_ok for d in self.signal_devices),
            "failed_total": sum(d.publish_fail for d in self.signal_devices),
            "tick_count": self.clock.tick_count,
        }
```

- [ ] **Step 5: Rewrite the scheduling block in `run_simulation` (`simulator.py:143-150`)**

Replace those eight lines with:

```python
        self.devices = [
            *self.signal_devices,
            *self.create_plc(),
            *self.create_scada(),
            *self.create_hmi(),
        ]
        self.announce_device_count()

        # The clock is a task of its own: it advances the world, and self.tick evaluates
        # every signal on that same advance. Publishing is scheduled separately, per tier.
        self.clock.on_transition(
            lambda site, line, state: LOGGER.info("Plant %s/%s -> %s", site, line, state)
        )
        self.tasks.append(asyncio.create_task(self._run_clock()))

        for device in self.signal_devices:
            for tier in sorted(device.tiers):
                # Already multiplied by the profile's `tier_scale` by `load_profile`, so a
                # slow profile cannot be defeated by forgetting to scale here.
                interval = self.profile.tiers.get(tier, 0.0)
                if interval <= 0.0:
                    # tier 'event' (and any tier explicitly set to 0) publishes on change
                    # from the tick itself; scheduling it would be a busy loop.
                    continue
                self.tasks.append(asyncio.create_task(device.run_tier(tier, interval)))

        # `.get`, not `.interval`: the legacy devices keep the single flat interval, and tests
        # hand this class a plain dict rather than the Dynaconf settings object.
        interval = float(self.simulation_config.get("interval", 5.0))
        for device in self.devices:
            if isinstance(device, SignalDevice):
                continue
            self.tasks.append(asyncio.create_task(device.start(interval)))
```

and add the clock runner:

```python
    async def _run_clock(self) -> None:
        """Advance the plant and evaluate every signal on the same tick."""
        tick_s = self.clock.tick_s
        self.clock.running = True
        try:
            while self.clock.running:
                self.clock.advance()
                self.tick(tick_s)
                await asyncio.sleep(tick_s)
        except asyncio.CancelledError:
            LOGGER.info("Plant clock cancelled")
            raise
        finally:
            self.clock.running = False
```

`_run_clock` rather than `PlantClock.run` because the evaluation has to happen between the advance and the sleep, in that order, on the same tick — that ordering is exactly what `test_energy_accumulates_monotonically_across_ticks` and `test_utility_power_follows_the_production_it_serves` verify. `PlantClock.run` stays as the standalone loop its own tests cover and as the entry point sub-project B can drive while paused.

It loops on `self.clock.running` rather than `while True` for the same reason the legacy devices loop on their own flag: `_stop_simulation` gathers `self.tasks` **without cancelling them**, so a task that never returns would hang the shutdown. Which is the next step.

- [ ] **Step 6: Stop the clock in `_stop_simulation` (`simulator.py:159-165`)**

`_stop_simulation` currently stops the devices and then gathers. Add the clock, before the gather:

```python
    async def _stop_simulation(self):
        """Cleanly stop all devices"""
        self.clock.stop()
        for device in self.devices:
            await device.stop()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
```

One line, and it is the line that makes `await sim._stop_simulation()` in the two `run_simulation` tests return instead of hanging until the pytest timeout. `SignalDevice.stop()` (Task 14) already ends its `run_tier` loops the same way.

Add to `simulator.py`'s imports:

```python
from uns_simulator.devices import HMI, PLC, SCADA, SignalDevice
from uns_simulator.plant import DeviceView, PlantClock
from uns_simulator.profiles import FAMILIES, PRODUCTION_KIND, LoadedProfile, load_profile
```

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -v`
Expected: everything passes. `test_a_zero_interval_tier_is_not_scheduled_as_a_busy_loop` is the guard that a tier interval of 0 never becomes `asyncio.sleep(0)` in a `while True`.

- [ ] **Step 8: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/simulator.py 99_simulator/test/test_simulator.py
git commit -m "feat(simulator): run the plant clock and schedule publishing per cadence tier"
```

---

