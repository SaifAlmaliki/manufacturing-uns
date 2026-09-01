## Task 14: `SignalDevice` — publish a `SignalSpec` set on cadence tiers

The device that replaces the hardcoded `PLC`. It separates the two things `PLC.generate_sensor_data` welds together: computing a value, and publishing it. Values advance on the plant tick; publishing happens per tier. `PLC`, `SCADA` and `HMI` stay in place untouched so nothing existing breaks.

**Files:**
- Modify: `99_simulator/src/uns_simulator/devices.py`
- Test: `99_simulator/test/test_devices.py`

**Interfaces:**
- Consumes: `AsyncMQTTDevice` (Task 13), `DeviceSpec` (Task 11), `DeviceView` (Task 8), `build_signal`/`Signal` (Tasks 2–6), `ParameterType` (`models.py`).
- Produces `class SignalDevice(AsyncMQTTDevice)`:
  - `__init__(self, spec: DeviceSpec, mqtt_config: dict[str, Any], view: DeviceView, global_seed: int)`; attributes `.spec`, `.view`, `.signals: list[Signal]`, `.values: dict[str, Any]`, `.enabled: bool`, `.tiers: frozenset[str]`.
  - `evaluate(self, dt: float) -> dict[str, Any]` — advances every signal in dependency order and returns the new `values`. Synchronous; called from the clock tick, never from a publish task.
  - `async publish_tier(self, tier: str) -> int` — publishes every signal whose `tier` matches, returning how many succeeded.
  - `async run_tier(self, tier: str, interval: float) -> None` — the loop the simulator schedules per tier.
  - `snapshot(self) -> list[dict[str, Any]]` — per-signal `{name, shape, unit, precision, range, limits, params, value, status, tier}`; the body of sub-project B's `GET /simulator/devices/{id}/signals`.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_devices.py
import random

from uns_simulator.devices import SignalDevice
from uns_simulator.models import ISA95Hierarchy
from uns_simulator.plant import DeviceView, LineTiming, PlantContext
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import SignalSpec

PATH = ISA95Hierarchy("CovestroAG", "Dormagen", "Utilities", "Powerhouse", "Cell1", kind="utilities")


def _view():
    """A utility device's view: no PackML line of its own, one served production line.

    `line=None` is deliberate and is what a real utility device gets — spec 6.1 gives
    `LineState` to production lines only, so a powerhouse reads production through `serves`.
    """
    context = PlantContext(global_seed=7)
    context.add_site("Dormagen")
    timing = LineTiming(starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=0.0)
    context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
    for _ in range(10):
        context.tick(1.0)
    return DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1"])


def _device(*signals, tier="energy"):
    spec = DeviceSpec(
        id="MAIN@Dormagen.Utilities.Powerhouse.Cell1",
        equipment="MainIncomer",
        family="energy",
        tier=tier,
        path=PATH,
        signals=tuple(signals),
    )
    return SignalDevice(spec, {}, _view(), global_seed=7)


def test_evaluate_advances_every_signal_and_returns_the_values():
    device = _device(
        SignalSpec(name="ActivePower", shape="ou_walk", unit="kW", params={"mean": 400.0, "sigma": 10.0, "tau": 120.0}),
        SignalSpec(name="EnergyTotal", shape="counter", unit="kWh", params={"rate": "ActivePower / 3600.0"}),
    )
    values = device.evaluate(1.0)
    assert set(values) == {"ActivePower", "EnergyTotal"}
    assert values["EnergyTotal"] > 0.0


def test_a_derived_signal_sees_this_tick_not_the_last_one():
    device = _device(
        SignalSpec(name="ActivePower", shape="constant", base_value=400.0),
        SignalSpec(name="ApparentPower", shape="derived", precision=1, params={"expr": "ActivePower / 0.9"}),
    )
    assert device.evaluate(1.0)["ApparentPower"] == pytest.approx(444.4)


def test_a_derived_signal_reads_the_plant_through_ctx():
    """Spec 6.3's name is `served_production`; the served line sits in EXECUTE at 0.85-1.0."""
    device = _device(SignalSpec(name="ChillerLoad", shape="derived", precision=2, params={"expr": "ctx.served_production * 200"}))
    assert device.evaluate(1.0)["ChillerLoad"] == pytest.approx(185.0, abs=20.0)


def test_publish_tier_only_publishes_that_tier():
    device = _device(
        SignalSpec(name="ActivePower", shape="ou_walk", tier="energy", params={"mean": 400.0}),
        SignalSpec(name="EnergyTotal", shape="counter", tier="meter", params={"rate": 1.0}),
    )
    device.evaluate(1.0)
    published = asyncio.run(device.publish_tier("energy"))
    assert published == 1
    topics = [topic for topic, _ in device.client.published]
    assert topics == ["CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainIncomer/ProcessValue/ActivePower"]


def test_the_payload_carries_value_unit_status_and_quality():
    device = _device(SignalSpec(name="ActivePower", shape="constant", unit="kW", base_value=400.0, tier="energy"))
    device.evaluate(1.0)
    asyncio.run(device.publish_tier("energy"))
    _, payload = device.client.published[0]
    assert payload["value"] == pytest.approx(400.0)
    assert payload["unit"] == "kW"
    assert payload["status"] == "Normal"
    assert payload["quality"] == "Good"
    assert payload["source"] == device.device_id
    assert payload["equipment"] == "MainIncomer"
    assert "timestamp" in payload


def test_param_type_selects_the_topic_segment():
    device = _device(
        SignalSpec(name="Mode", shape="stepped", tier="status", param_type="Status", params={"choices": ["Auto"]}),
    )
    device.evaluate(1.0)
    asyncio.run(device.publish_tier("status"))
    assert device.client.published[0][0].endswith("/Status/Mode")


def test_an_unknown_param_type_is_rejected_at_construction_by_name():
    with pytest.raises(ValueError, match="Banana"):
        _device(SignalSpec(name="X", param_type="Banana"))


def test_a_none_valued_signal_is_not_published():
    device = _device(SignalSpec(name="Avg", shape="window_agg", tier="energy", params={"source": "absent"}))
    device.evaluate(1.0)
    assert asyncio.run(device.publish_tier("energy")) == 0
    assert device.client.published == []


def test_an_event_tier_signal_publishes_only_when_its_value_changes():
    device = _device(
        SignalSpec(name="Door", shape="stepped", tier="event", param_type="EVENT", params={"choices": ["Closed"], "dwell_s": 1e9}),
    )
    for _ in range(5):
        device.evaluate(1.0)
        asyncio.run(device.publish_tier("event"))
    assert len(device.client.published) == 1, "an unchanged event value must not republish"


def test_tiers_lists_only_the_tiers_this_device_actually_uses():
    device = _device(
        SignalSpec(name="A", tier="fast"),
        SignalSpec(name="B", tier="meter"),
        SignalSpec(name="C", tier="fast"),
    )
    assert device.tiers == frozenset({"fast", "meter"})


def test_a_disabled_device_publishes_nothing():
    device = _device(SignalSpec(name="A", tier="fast", base_value=1.0))
    device.enabled = False
    device.evaluate(1.0)
    assert asyncio.run(device.publish_tier("fast")) == 0


def test_snapshot_describes_every_signal():
    device = _device(SignalSpec(name="ActivePower", shape="ou_walk", unit="kW", params={"mean": 400.0}, limits={"hi": 600.0}))
    device.evaluate(1.0)
    entry = device.snapshot()[0]
    assert entry["name"] == "ActivePower"
    assert entry["shape"] == "ou_walk"
    assert entry["unit"] == "kW"
    assert entry["limits"] == {"hi": 600.0}
    assert entry["status"] in {"Normal", "Warning", "Alarm"}
    assert isinstance(entry["value"], float)


@pytest.mark.asyncio
async def test_run_tier_publishes_then_sleeps_and_stops():
    device = _device(SignalSpec(name="A", tier="fast", shape="constant", base_value=1.0))
    device.evaluate(1.0)
    task = asyncio.create_task(device.run_tier("fast", 0.01))
    await asyncio.sleep(0.05)
    await device.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert len(device.client.published) >= 2  # noqa: PLR2004
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_devices.py -k "signal or tier or snapshot or param_type or derived" -v`
Expected: FAIL — `ImportError: cannot import name 'SignalDevice'`.

- [ ] **Step 3: Implement `SignalDevice`**

Append to `devices.py`:

```python
class SignalDevice(AsyncMQTTDevice):
    """A device whose behaviour is entirely declared by its DeviceSpec.

    Two responsibilities, deliberately kept apart:
      evaluate(dt)      - advance the signals. Called once per plant tick.
      publish_tier(t)   - send the current values for one cadence tier.

    Splitting them is what makes a 900 s meter reading and a 1 s vibration sample describe
    the same instant of the same world. The old PLC computed a value at publish time, so a
    slow publisher necessarily saw a coarser simulation.
    """

    def __init__(
        self,
        spec: DeviceSpec,
        mqtt_config: dict[str, Any],
        view: DeviceView,
        global_seed: int,
    ) -> None:
        super().__init__(spec.id, spec.path, mqtt_config)
        self.spec = spec
        self.view = view
        self.enabled = spec.enabled
        self.values: dict[str, Any] = {}
        self._last_published: dict[str, Any] = {}

        self._param_types: dict[str, ParameterType] = {}
        for signal_spec in spec.signals:
            try:
                self._param_types[signal_spec.name] = ParameterType(signal_spec.param_type)
            except ValueError:
                allowed = ", ".join(member.value for member in ParameterType)
                raise ValueError(
                    f"device {spec.id!r} signal {signal_spec.name!r}: unknown param_type "
                    f"{signal_spec.param_type!r} (allowed: {allowed})"
                ) from None

        # spec.signals is already in dependency order (profiles.expand_template sorted it),
        # so evaluating in sequence guarantees a derived signal sees this tick's siblings.
        self.signals = [
            build_signal(signal_spec, f"{spec.topic_prefix}/{signal_spec.name}", global_seed)
            for signal_spec in spec.signals
        ]
        self.tiers = frozenset(signal_spec.tier for signal_spec in spec.signals)

    def evaluate(self, dt: float) -> dict[str, Any]:
        """Advance every signal by `dt` seconds. Synchronous, and never publishes."""
        for signal in self.signals:
            self.values[signal.spec.name] = signal.next(dt, self.view, self.values)
        return self.values

    async def publish_tier(self, tier: str) -> int:
        """Publish the current value of every signal in `tier`. Returns the success count."""
        if not self.enabled:
            return 0
        published = 0
        for signal in self.signals:
            if signal.spec.tier != tier:
                continue
            value = self.values.get(signal.spec.name)
            if value is None:
                continue
            # The 'event' tier means "on change" - a door that stays shut says so once.
            if tier == "event" and self._last_published.get(signal.spec.name, object()) == value:
                continue
            payload = {
                "value": value,
                "unit": signal.spec.unit,
                "status": signal.status(),
                "quality": "Good",
            }
            if signal.spec.limits:
                payload["limits"] = signal.spec.limits
            if await self.publish_parameter(
                self.spec.equipment, self._param_types[signal.spec.name], signal.spec.name, payload
            ):
                self._last_published[signal.spec.name] = value
                published += 1
        return published

    async def run_tier(self, tier: str, interval: float) -> None:
        """Publish `tier` every `interval` seconds until stopped or cancelled."""
        self._running = True
        LOGGER.info("Device %s publishing tier %s every %.1fs", self.device_id, tier, interval)
        try:
            while self._running:
                await self.publish_tier(tier)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            LOGGER.info("Device %s tier %s cancelled", self.device_id, tier)
            raise

    def snapshot(self) -> list[dict[str, Any]]:
        """Describe every signal. Rendered by sub-project B's SignalInspector."""
        return [
            {
                "name": signal.spec.name,
                "shape": signal.spec.shape,
                "unit": signal.spec.unit,
                "precision": signal.spec.precision,
                "range": list(signal.spec.value_range) if signal.spec.value_range else None,
                "limits": dict(signal.spec.limits),
                "params": dict(signal.spec.params),
                "tier": signal.spec.tier,
                "param_type": signal.spec.param_type,
                "value": self.values.get(signal.spec.name),
                "status": signal.status(),
            }
            for signal in self.signals
        ]
```

Add to `devices.py`'s imports:

```python
from uns_simulator.plant import DeviceView
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import build_signal
```

Two things to get right, both load-bearing:
- `super().__init__(spec.id, spec.path, mqtt_config)` passes the `DeviceSpec.path` as the hierarchy, so `publish_parameter`'s existing `self.hierarchy.get_parameter_topic(...)` produces the full 8-level topic with no change to that method.
- `run_tier` re-raises `CancelledError` rather than swallowing it (which is what `PLC.start` does at `devices.py:331`). Swallowing it makes `asyncio.gather` on shutdown hang, and it is not worth reproducing.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_devices.py -v`
Expected: all pass, old and new.

- [ ] **Step 5: Fix `SCADA.connected_devices` while in this file**

`devices.py:371` reports `random.randint(5, 10)` as the connected device count — a number that contradicts the ~50 devices this plan creates and that would make the SCADA payload actively misleading. `SCADA.__init__` already has a `self.connected_devices = 0` attribute nobody writes. Make the simulator's real count settable and report it:

```python
        status_data = {
            'system_name': self.system_name,
            'system_status': 'Operational',
            'connected_devices': self.connected_devices,
            'data_points_per_second': random.randint(500, 1500),  # noqa: S311
```

Task 15 sets `scada.connected_devices` from the device inventory. Add a test:

```python
# append to 99_simulator/test/test_devices.py
@pytest.mark.asyncio
async def test_scada_reports_the_real_connected_device_count():
    scada = devices.SCADA(FakeHierarchy(), {})
    scada.connected_devices = 47
    status = await scada.generate_system_status()
    assert status["connected_devices"] == 47  # noqa: PLR2004
```

- [ ] **Step 6: Run the whole suite, lint and commit**

```bash
cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/devices.py 99_simulator/test/test_devices.py
git commit -m "feat(simulator): add SignalDevice publishing declarative signals on cadence tiers"
```

---

