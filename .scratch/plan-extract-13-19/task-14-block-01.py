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
