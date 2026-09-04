import asyncio

import pytest

from uns_simulator import devices as devices_module
from uns_simulator.models import ParameterType, expand_hierarchy_paths
from uns_simulator.plant import PlantClock
from uns_simulator.profiles import TIER_DEFAULTS, load_profile
from uns_simulator.simulator import (
    ReconfigurationError,
    UnifiedNamespaceSimulator,
    resolve_simulation_duration,
)


def test_resolve_duration_keeps_zero():
    assert resolve_simulation_duration(0, {"duration": 5}) == 0


def test_resolve_duration_keeps_string_zero():
    assert resolve_simulation_duration("0", {"duration": 5}) == 0


def test_resolve_duration_uses_explicit_value():
    assert resolve_simulation_duration(12, {"duration": 5}) == 12


def test_resolve_duration_falls_back_to_config():
    assert resolve_simulation_duration(None, {"duration": 5}) == 5


def test_resolve_duration_falls_back_to_duration_minutes():
    assert resolve_simulation_duration(None, {"duration_minutes": 3}) == 3


@pytest.mark.asyncio
async def test_run_until_zero_blocks_until_cancelled():
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    task = asyncio.create_task(sim._run_until(0))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_until_positive_sleeps_minutes(monkeypatch):
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await sim._run_until(5)
    assert sleeps == [300]


HIERARCHY = {
    "enterprise": "AcmeWater",
    "sites": [
        {
            "name": "Site1",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "nameplate_tph": 12.0, "cells": ["T101", "FT101"]}],
                },
            ],
        }
    ],
}

RAW = {
    "hierarchy": HIERARCHY,
    "plant": {},
    "wtp": {
        "devices": [
            {
                "id": "FT101",
                "equipment": "WTP_Flowmeter",
                "target": {"area": "RawWater", "cell": "FT101"},
                "signals": {
                    "PV": {
                        "shape": "derived",
                        "expr": "ctx.wtp.ft101_m3h",
                        "unit": "m³/h",
                        "precision": 2,
                        "tier": "process",
                    },
                    "Totalizer": {
                        "shape": "derived",
                        "expr": "ctx.wtp.ft101_total_m3",
                        "unit": "m³",
                        "precision": 2,
                        "tier": "meter",
                    },
                },
            }
        ]
    },
    "profiles": {
        "wtp": {"tier_scale": 1.0, "sites": ["Site1"], "families": ["wtp"]},
    },
    "simulation": {"seed": 1234, "interval": 5.0, "duration": 0},
}


@pytest.fixture(autouse=True)
def _dummy_broker(monkeypatch):
    """Same pattern as test_devices.py: never touch a real broker."""
    from test.test_devices import DummyClient

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
    sim.profile = load_profile(RAW, "wtp")
    sim.clock = PlantClock(sim.profile.context, tick_s=1.0)
    sim.signal_devices = sim.create_signal_devices()
    sim.raw_config = RAW
    sim._init_run_state()
    return sim


def test_create_signal_devices_builds_one_device_per_spec():
    sim = _sim()
    assert len(sim.signal_devices) == 1
    device = sim.signal_devices[0]
    assert device.spec.equipment == "WTP_Flowmeter"
    assert device.tiers == {"process", "meter"}


def test_a_device_sees_the_wtp_through_its_view():
    sim = _sim()
    view = sim.signal_devices[0].view
    assert view.site == "Site1"
    assert view.wtp is sim.profile.context.sites["Site1"].wtp


def test_tick_evaluates_every_device():
    sim = _sim()
    sim.clock.advance()
    sim.tick(1.0)
    values = sim.signal_devices[0].values
    assert values["PV"] >= 0.0
    assert values["Totalizer"] >= 0.0


def test_flow_totalizer_follows_the_plant_clock():
    """Signals read the WTP; advancing the clock is what makes the totalizer move."""
    sim = _sim()
    sim.tick(1.0)
    before = sim.signal_devices[0].values["Totalizer"]
    for _ in range(30):
        sim.clock.advance()
        sim.tick(1.0)
    after = sim.signal_devices[0].values["Totalizer"]
    assert after > before


def test_flow_totalizer_accumulates_monotonically_across_ticks():
    sim = _sim()
    readings = []
    for _ in range(20):
        sim.clock.advance()
        sim.tick(1.0)
        readings.append(sim.signal_devices[0].values["Totalizer"])
    assert all(b >= a for a, b in zip(readings, readings[1:], strict=False))
    assert readings[-1] > readings[0]


def test_status_reports_the_loaded_profile():
    sim = _sim()
    status = sim.status()
    assert status["profile"] == "wtp"
    assert status["seed"] == 1234
    assert status["device_count"] == 1
    assert status["signal_count"] == 2
    assert status["run_state"] == "stopped"
    assert status["uptime_s"] == 0.0
    # `wtp` leaves `tier_scale` at its 1.0 default, so the pre-scaled tiers are the defaults.
    assert status["tiers"]["meter"] == TIER_DEFAULTS["meter"]
    assert status["families"] == {
        "wtp": True,
    }
    assert status["per_tier"] == {"process": 1, "meter": 1}
    assert status["published_total"] == 0
    assert status["failed_total"] == 0
    assert all(rate == 0.0 for rate in status["msg_per_sec"].values())


@pytest.mark.asyncio
async def test_run_simulation_schedules_the_clock_and_one_task_per_device_tier(monkeypatch):
    sim = _sim()
    monkeypatch.setattr(sim, "create_plc", lambda: [])
    monkeypatch.setattr(sim, "create_scada", lambda: [])
    monkeypatch.setattr(sim, "create_hmi", lambda: [])
    sim.profile.tiers["process"] = 0.01
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
    assert "ProcessValue/PV" in topics
    assert "ProcessValue/Totalizer" in topics


@pytest.mark.asyncio
async def test_a_zero_interval_tier_is_not_scheduled_as_a_busy_loop(monkeypatch):
    """The 'event' tier has interval 0 and publishes on change from the tick, not a loop."""
    sim = _sim()
    monkeypatch.setattr(sim, "create_plc", lambda: [])
    monkeypatch.setattr(sim, "create_scada", lambda: [])
    monkeypatch.setattr(sim, "create_hmi", lambda: [])
    sim.profile.tiers["process"] = 0.0
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


@pytest.mark.asyncio
async def test_a_fresh_simulator_is_stopped():
    sim = _sim()
    assert sim.run_state == "stopped"
    assert sim.started_at is None
    assert sim._publish_tasks == []


@pytest.mark.asyncio
async def test_start_runs_the_clock_and_schedules_one_task_per_device_tier():
    sim = _sim()
    sim.clock.tick_s = 0.01
    expected = sum(len(device.tiers) for device in sim.signal_devices)

    await sim.start()
    try:
        assert sim.run_state == "running"
        assert len(sim._publish_tasks) == expected
        assert sim._clock_task is not None
        await asyncio.sleep(0.05)
        assert sim.clock.tick_count > 0
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_start_twice_does_not_double_the_publishers():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        scheduled = len(sim._publish_tasks)
        await sim.start()
        assert len(sim._publish_tasks) == scheduled
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_pause_halts_publishing_and_keeps_the_plant_moving():
    """The point of pause: the world carries on so resuming shows where it went."""
    sim = _sim()
    sim.clock.tick_s = 0.01
    sim.profile.tiers = dict.fromkeys(sim.profile.tiers, 0.01)

    await sim.start()
    try:
        await asyncio.sleep(0.05)
        await sim.pause()
        assert sim.run_state == "paused"
        assert sim._publish_tasks == []

        published = sim.status()["published_total"]
        ticks = sim.clock.tick_count
        await asyncio.sleep(0.05)

        assert sim.status()["published_total"] == published
        assert sim.clock.tick_count > ticks
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_resume_restarts_publishing_without_restarting_the_clock():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        clock_task = sim._clock_task
        started_at = sim.started_at
        await sim.pause()
        await sim.resume()

        assert sim.run_state == "running"
        assert sim._clock_task is clock_task
        assert sim.started_at == started_at
        assert sim._publish_tasks != []
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_stop_cancels_every_task_and_forgets_the_run():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    await sim.stop()

    assert sim.run_state == "stopped"
    assert sim._publish_tasks == []
    assert sim._clock_task is None
    assert sim.started_at is None
    assert sim.clock.running is False


@pytest.mark.asyncio
async def test_stop_and_pause_are_idempotent():
    sim = _sim()
    await sim.pause()
    assert sim.run_state == "stopped"
    await sim.stop()
    await sim.stop()
    assert sim.run_state == "stopped"


@pytest.mark.asyncio
async def test_a_disabled_device_is_never_scheduled():
    sim = _sim()
    sim.clock.tick_s = 0.01
    sim.signal_devices[0].enabled = False
    expected = sum(len(d.tiers) for d in sim.signal_devices[1:])

    await sim.start()
    try:
        assert len(sim._publish_tasks) == expected
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_a_failing_transition_listener_does_not_silence_the_others():
    """PlantClock swallows callback exceptions, so a broken listener would otherwise be
    invisible and could starve the one that publishes self-telemetry."""
    sim = _sim()
    seen: list[str] = []
    sim.on_plant_transition(lambda site, line, state: (_ for _ in ()).throw(RuntimeError("boom")))
    sim.on_plant_transition(lambda site, line, state: seen.append(state))

    sim._notify_transition("Site1", "Train1", "DutyP102")
    assert seen == ["DutyP102"]


@pytest.fixture
def _use_raw_config(monkeypatch):
    """apply_profile reloads from load_simulator_config; tests use RAW, not live settings."""
    monkeypatch.setattr("uns_simulator.simulator.load_simulator_config", lambda settings_obj, conf_dir=None: RAW)


@pytest.mark.asyncio
async def test_switching_profile_rebuilds_the_devices_and_the_clock(_use_raw_config):
    sim = _sim()
    original_devices = sim.signal_devices
    original_clock = sim.clock

    await sim.apply_profile("wtp")

    assert sim.profile.name == "wtp"
    assert sim.signal_devices is not original_devices
    assert sim.clock is not original_clock
    assert sim.overrides_active is False


@pytest.mark.asyncio
async def test_switching_profile_keeps_a_running_plant_running(_use_raw_config):
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        await sim.apply_profile("wtp")
        assert sim.run_state == "running"
        assert sim._publish_tasks != []
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_an_unknown_profile_is_refused_and_changes_nothing(_use_raw_config):
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        with pytest.raises(ReconfigurationError) as excinfo:
            await sim.apply_profile("huge")
        assert excinfo.value.field == "profile"
        assert "huge" in excinfo.value.message
        assert sim.run_state == "running"
        assert sim.profile.name == "wtp"
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_a_new_seed_changes_the_plant_but_not_the_shape(_use_raw_config):
    sim = _sim()
    before = len(sim.signal_devices)
    await sim.apply_profile("wtp", seed=1234)

    assert sim.profile.seed == 1234
    assert len(sim.signal_devices) == before


@pytest.mark.asyncio
async def test_a_rebuilt_clock_still_reports_transitions(_use_raw_config):
    """The bug this guards: a profile switch replaces the clock, and every listener
    registered on the old one is silently gone."""
    sim = _sim()
    seen: list[str] = []
    sim.on_plant_transition(lambda site, line, state: seen.append(state))

    await sim.apply_profile("wtp")
    sim._notify_transition("Site1", "Train1", "DutyP102")

    assert seen == ["DutyP102"]


@pytest.mark.asyncio
async def test_a_tier_interval_can_be_changed_at_runtime():
    sim = _sim()
    await sim.apply_tiers({"process": 12.5})

    assert sim.profile.tiers["process"] == 12.5
    assert sim.overrides_active is True


@pytest.mark.asyncio
async def test_an_unknown_tier_names_itself_in_the_refusal():
    sim = _sim()
    with pytest.raises(ReconfigurationError) as excinfo:
        await sim.apply_tiers({"turbo": 1.0})
    assert excinfo.value.field == "turbo"
    assert sim.overrides_active is False


@pytest.mark.asyncio
async def test_a_negative_tier_interval_is_refused():
    sim = _sim()
    with pytest.raises(ReconfigurationError) as excinfo:
        await sim.apply_tiers({"process": -1.0})
    assert excinfo.value.field == "process"


@pytest.mark.asyncio
async def test_changing_a_tier_while_running_reschedules_the_publishers():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        before = list(sim._publish_tasks)
        await sim.apply_tiers({"process": 0.02})
        assert all(task.cancelled() or task.done() for task in before)
        assert sim._publish_tasks != []
        assert all(task not in before for task in sim._publish_tasks)
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_changing_a_tier_while_paused_does_not_start_publishing():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        await sim.pause()
        await sim.apply_tiers({"process": 0.02})
        assert sim.run_state == "paused"
        assert sim._publish_tasks == []
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_disabling_a_family_disables_the_devices_it_contributed():
    sim = _sim()
    family = sim.signal_devices[0].spec.family
    await sim.apply_families({family: False})

    assert sim.profile.families[family] is False
    assert all(not d.enabled for d in sim.signal_devices if d.spec.family == family)
    assert sim.overrides_active is True


@pytest.mark.asyncio
async def test_an_unknown_family_names_itself_in_the_refusal():
    sim = _sim()
    with pytest.raises(ReconfigurationError) as excinfo:
        await sim.apply_families({"nonsense": True})
    assert excinfo.value.field == "nonsense"


@pytest.mark.asyncio
async def test_one_device_can_be_disabled_by_id():
    sim = _sim()
    device_id = sim.signal_devices[0].spec.id
    await sim.set_device_enabled(device_id, False)

    assert sim.signal_devices[0].enabled is False
    assert sim.overrides_active is True


@pytest.mark.asyncio
async def test_an_unknown_device_id_raises_key_error():
    sim = _sim()
    with pytest.raises(KeyError):
        await sim.set_device_enabled("no-such-device", False)


def test_health_answers_while_the_plant_is_stopped():
    sim = _sim()
    body = sim.health_body()

    assert body["status"] == "ok"
    assert body["uptime_s"] >= 0.0
    assert body["git_hash"]
    assert body["version"]


def test_status_carries_every_key_the_console_polls():
    sim = _sim()
    body = sim.status()

    assert set(body) == {
        "run_state",
        "profile",
        "seed",
        "device_count",
        "signal_count",
        "uptime_s",
        "broker_connected",
        "msg_per_sec",
        "published_total",
        "failed_total",
        "overrides_active",
        "tiers",
        "families",
        "per_tier",
        "tick_count",
    }
    assert body["run_state"] == "stopped"
    assert body["uptime_s"] == 0.0


def test_a_stopped_plant_reports_no_throughput():
    """A theoretical rate from a stopped simulator is the number that ends up in a
    capacity discussion as though it were measured."""
    sim = _sim()
    assert set(sim.status()["msg_per_sec"]) == set(sim.profile.tiers)
    assert all(rate == 0.0 for rate in sim.status()["msg_per_sec"].values())


@pytest.mark.asyncio
async def test_a_running_plant_reports_throughput_and_uptime():
    sim = _sim()
    sim.clock.tick_s = 0.01
    await sim.start()
    try:
        body = sim.status()
        assert body["run_state"] == "running"
        assert body["uptime_s"] >= 0.0
        assert sum(body["msg_per_sec"].values()) > 0.0
    finally:
        await sim.stop()


def test_plant_snapshot_is_the_wtp_body():
    sim = _sim()
    snap = sim.plant_snapshot()
    assert snap["enterprise"] == "AcmeWater"
    assert "T101" in snap["tanks"]
    assert "sites" not in snap


def test_every_device_reports_the_twelve_fields_the_table_shows():
    sim = _sim()
    row = sim.device_snapshots()[0]

    assert set(row) == {
        "id",
        "equipment",
        "topic_prefix",
        "tier",
        "family",
        "enabled",
        "connected",
        "last_publish_ts",
        "publish_ok",
        "publish_fail",
        "last_error",
        "signal_count",
    }


def test_signals_are_returned_for_one_device_by_id():
    sim = _sim()
    device_id = sim.signal_devices[0].spec.id
    body = sim.signal_snapshot(device_id)

    assert body["device_id"] == device_id
    assert len(body["signals"]) == len(sim.signal_devices[0].spec.signals)
    assert "last_publish_ts" in body["signals"][0]
    assert "unit" in body["signals"][0]


def test_each_signal_row_carries_the_topic_it_publishes_on():
    """The console keys its sparklines on this, and only Python knows how to build it."""
    sim = _sim()
    device = sim.signal_devices[0]
    row = sim.signal_snapshot(device.spec.id)["signals"][0]

    assert row["topic"] == f"{device.spec.topic_prefix}/{row['param_type']}/{row['name']}"
    # Exactly the topic ISA95Hierarchy.get_parameter_topic builds for the same signal.
    assert row["topic"] == device.spec.path.get_parameter_topic(
        device.spec.equipment, ParameterType(row["param_type"]), row["name"]
    )


def test_an_unknown_device_id_raises_key_error_from_the_read_model_too():
    sim = _sim()
    with pytest.raises(KeyError):
        sim.signal_snapshot("no-such-device")


def test_the_config_snapshot_lists_the_profiles_that_could_be_switched_to():
    sim = _sim()
    body = sim.config_snapshot()

    assert body["profile"] == "wtp"
    assert body["available_profiles"] == ["wtp"]
    assert body["hierarchy"]
    assert {"enterprise", "site", "area", "line", "cell", "kind"} <= set(body["hierarchy"][0])
    device = body["devices"][0]
    assert {"id", "equipment", "family", "tier", "enabled", "topic_prefix", "signal_count", "serves", "target"} == set(device)
    assert {"site", "area", "line", "cell", "kind"} == set(device["target"])


def test_diagnostics_reports_the_load_report_and_nothing_failing_yet():
    sim = _sim()
    body = sim.diagnostics()

    assert set(body) == {"report", "failing_devices", "sample_topics"}
    assert set(body["report"]) == {
        "devices",
        "signals",
        "per_family",
        "per_tier",
        "serves_links",
        "unmatched_templates",
        "warnings",
    }
    assert body["failing_devices"] == []


def test_a_device_with_failures_shows_up_in_diagnostics():
    sim = _sim()
    sim.signal_devices[0].publish_fail = 3
    sim.signal_devices[0].last_error = "[Errno 111] Connection refused"

    failing = sim.diagnostics()["failing_devices"]
    assert len(failing) == 1
    assert failing[0]["device_id"] == sim.signal_devices[0].device_id
    assert failing[0]["publish_fail"] == 3


def test_sample_topics_look_exactly_like_what_gets_published():
    sim = _sim()
    device = sim.signal_devices[0]
    signal = device.spec.signals[0]
    expected = f"{device.spec.topic_prefix}/{signal.param_type}/{signal.name}"

    topics = sim.sample_topics()
    assert expected in topics
    assert len(topics) <= 20
