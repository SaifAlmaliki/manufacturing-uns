import asyncio
import json
import random

import pytest

# Import the module under test
from uns_simulator import devices
from uns_simulator.devices import AsyncMQTTDevice, SignalDevice
from uns_simulator.models import ISA95Hierarchy, ParameterType
from uns_simulator.plant import DeviceView, LineTiming, PlantContext
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import SignalSpec


# Dummy replacements to avoid external dependencies and network I/O
class DummyClient:
    def __init__(self, *args, **kwargs):
        self.published: list[tuple[str, dict]] = []
        self.enter_count = 0
        self.fail_on_enter = 0
        self.fail_on_publish = False

    async def __aenter__(self):
        self.enter_count += 1
        if self.fail_on_enter > 0:
            self.fail_on_enter -= 1
            raise OSError("broker refused the connection")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def publish(self, topic, payload, **kwargs):
        if self.fail_on_publish:
            raise OSError("broker went away")
        self.published.append((topic, json.loads(payload)))


class DummyEquipment:
    def __init__(self, name, sensors):
        self.name = name
        self.sensors = sensors


class FakeHierarchy:
    def get_parameter_topic(self, equipment, param_type, param_name):
        # simple deterministic topic for assertions
        return f"factory/{equipment}/{getattr(param_type, '__name__', str(param_type))}/{param_name}"


@pytest.fixture(autouse=True)
def patch_mqtt_and_models(monkeypatch):
    # Patch aiomqtt.Client used inside devices module
    # ensure attribute exists
    monkeypatch.setattr(devices, "aiomqtt", devices.aiomqtt)
    monkeypatch.setattr(devices, "Equipment", DummyEquipment)
    # replace the Client class used by AsyncMQTTDevice with DummyClient factory
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    yield


@pytest.mark.asyncio
async def test_publish_parameter_enriches_and_publishes():
    hierarchy = FakeHierarchy()
    mqtt_conf = {}
    # Create a PLC instance but we will call publish_parameter directly
    plc = devices.PLC("T1", hierarchy, mqtt_conf, equipment_config={"name": "Boiler1", "sensors": {}})
    # Replace instance client with our DummyClient (constructed by patched aiomqtt.Client)
    plc.client = DummyClient()

    payload = {"value": 42}
    ok = await plc.publish_parameter("Boiler1", devices.ParameterType, "Temp", payload)
    assert ok is True
    # ensure one publish recorded
    assert len(plc.client.published) == 1
    topic, published_payload = plc.client.published[0]
    assert "factory/Boiler1" in topic
    # enriched fields present
    assert published_payload["value"] == 42
    assert published_payload["source"] == plc.device_id
    assert published_payload["equipment"] == "Boiler1"
    assert "timestamp" in published_payload


@pytest.mark.asyncio
async def test_plc_generate_sensor_status_and_alarm(monkeypatch):
    hierarchy = FakeHierarchy()
    mqtt_conf = {}

    sensors_cfg = {
        "Temp": {"base_value": 75.0, "variation": 2.0, "unit": "F"},
        "Pressure": {"base_value": 30.0, "variation": 1.0, "unit": "psi"},
    }

    # Patch random functions for deterministic outputs
    monkeypatch.setattr(random, "uniform", lambda a, b: (a + b) / 2.0)
    # ensure no alarm triggered by setting random.random to a value > 0.05 for sensor/status generation
    monkeypatch.setattr(random, "random", lambda: 0.5)
    # ensure deterministic randint used for operating_hours initial value
    monkeypatch.setattr(random, "randint", lambda a, _b: a)

    plc = devices.PLC("T2", hierarchy, mqtt_conf, equipment_config={"name": "Unit1", "sensors": sensors_cfg})
    # Test sensor data generation
    sensors = await plc.generate_sensor_data()
    assert isinstance(sensors, list)
    assert any(s["param_name"] == "Temp" for s in sensors)
    assert any(s["param_name"] == "Pressure" for s in sensors)
    for m in sensors:
        assert "data" in m and "value" in m["data"] and "unit" in m["data"]

    # Test status data
    status = await plc.generate_status_data()
    assert status["param_type"] == devices.ParameterType.STATUS
    assert status["param_name"] == "EquipmentStatus"
    assert "operational" in status["data"]

    # Force alarm by returning a small random()
    monkeypatch.setattr(random, "random", lambda: 0.01)
    # deterministic choice and randint for alarm id
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(random, "randint", lambda _a, _b: 1234)

    alarm = await plc.generate_alarm_data()
    assert alarm is not None
    assert alarm["param_type"] == devices.ParameterType.ALARM
    assert alarm["param_name"] == "ActiveAlarms"
    assert "alarms" in alarm["data"]
    assert alarm["data"]["alarms"][0]["id"].startswith("ALM_")
    assert alarm["data"]["alarms"][0]["acknowledged"] is False


@pytest.mark.asyncio
async def test_hmi_operator_actions_and_publish(monkeypatch):
    hierarchy = FakeHierarchy()
    mqtt_conf = {}
    # Make HMI generate an action by forcing random.random < 0.3
    monkeypatch.setattr(random, "random", lambda: 0.1)
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(random, "randint", lambda _a, _b: 1)
    monkeypatch.setattr(random, "uniform", lambda a, b: (a + b) / 2.0)

    hmi = devices.HMI("01", hierarchy, mqtt_conf)
    # replace client with DummyClient to capture publishes
    hmi.client = DummyClient()

    actions = await hmi.generate_operator_actions()
    assert "actions" in actions
    # If actions list non-empty, ensure publish_parameter works
    if actions["actions"]:
        ok = await hmi.publish_parameter("HMI", devices.ParameterType, "OperatorActions", actions)
        assert ok is True
        assert len(hmi.client.published) == 1
        _, payload = hmi.client.published[0]
        assert payload["workstation_id"] == hmi.device_id


@pytest.mark.asyncio
async def test_scada_system_status_sync():
    hierarchy = FakeHierarchy()
    mqtt_conf = {}
    scada = devices.SCADA(hierarchy, mqtt_conf, system_name="TestSCADA")
    # generate_system_status is async in implementation; call via asyncio.run if needed
    status = await scada.generate_system_status()
    assert isinstance(status, dict)
    expected_keys = {
        "system_name",
        "system_status",
        "connected_devices",
        "data_points_per_second",
        "system_uptime_hours",
        "cpu_usage_percent",
        "memory_usage_percent",
        "alarms_active",
        "version",
    }
    assert expected_keys.issubset(set(status.keys()))
    assert status["system_name"] == "TestSCADA"


@pytest.mark.asyncio
async def test_scada_reports_the_real_connected_device_count():
    scada = devices.SCADA(FakeHierarchy(), {})
    scada.connected_devices = 47
    status = await scada.generate_system_status()
    assert status["connected_devices"] == 47


@pytest.mark.asyncio
async def test_client_id_is_unique_per_device_and_names_the_simulator():
    first = AsyncMQTTDevice("dev-a", FakeHierarchy(), {})
    second = AsyncMQTTDevice("dev-a", FakeHierarchy(), {})
    assert first.client_id.startswith("uns_simulator-")
    assert "dev-a" in first.client_id
    assert first.client_id != second.client_id


@pytest.mark.asyncio
async def test_the_connection_is_opened_once_for_many_publishes():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    for index in range(20):
        assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, f"S{index}", {"value": index})
    assert device.client.enter_count == 1, "one connection, not one per message"
    assert len(device.client.published) == 20
    assert device.connected is True
    assert device.publish_ok == 20
    assert device.publish_fail == 0


@pytest.mark.asyncio
async def test_connect_retries_with_backoff_and_counts_reconnects(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(devices.asyncio, "sleep", fake_sleep)
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    device.client.fail_on_enter = 3
    assert await device.connect() is True
    assert device.connected is True
    assert sleeps == [1.0, 2.0, 4.0], "backoff must double"
    assert device.reconnects == 3


@pytest.mark.asyncio
async def test_backoff_is_capped_at_the_configured_retry_interval(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(devices.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(devices.MQTTConfig, "retry_interval", 5, raising=False)
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    device.client.fail_on_enter = 6
    await device.connect()
    assert max(sleeps) == 5.0
    assert sleeps[-1] == 5.0


@pytest.mark.asyncio
async def test_a_publish_failure_marks_the_device_disconnected_and_is_counted():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    device.client.fail_on_publish = True
    assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1}) is False
    assert device.connected is False
    assert device.publish_fail == 1
    assert "broker went away" in device.last_error


@pytest.mark.asyncio
async def test_a_publish_failure_is_followed_by_a_reconnect_on_the_next_attempt():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    device.client.fail_on_publish = True
    await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1})
    device.client.fail_on_publish = False
    assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 2}) is True
    assert device.client.enter_count == 2


@pytest.mark.asyncio
async def test_disconnect_is_idempotent():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    await device.disconnect()
    await device.disconnect()
    assert device.connected is False


@pytest.mark.asyncio
async def test_health_reports_the_publish_counters():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1})
    health = device.health()
    assert health["connected"] is True
    assert health["publish_ok"] == 1
    assert health["publish_fail"] == 0
    assert health["last_error"] is None
    assert isinstance(health["last_publish_ts"], float)


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
    device = _device(
        SignalSpec(name="ChillerLoad", shape="derived", precision=2, params={"expr": "ctx.served_production * 200"})
    )
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
        SignalSpec(
            name="Door", shape="stepped", tier="event", param_type="EVENT", params={"choices": ["Closed"], "dwell_s": 1e9}
        ),
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
    assert len(device.client.published) >= 2
