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
