"""The simulator's own health on MQTT (spec 6), and the guard that keeps it separate.

Platform Observability, never Process Visualization: these topics answer "is the simulator
publishing?", and must be invisible to every mapper that persists the Unified Namespace.
"""

import asyncio
import json

import pytest
import yaml
from uns_config import resolve_conf_dir

from uns_simulator import self_telemetry as telemetry_module
from uns_simulator.self_telemetry import SelfTelemetry, telemetry_prefix

STATUS = {
    "run_state": "running",
    "profile": "small",
    "seed": 1,
    "device_count": 2,
    "signal_count": 5,
    "uptime_s": 3.0,
    "broker_connected": True,
    "msg_per_sec": {"process": 1.0},
    "published_total": 10,
    "failed_total": 0,
    "overrides_active": False,
    "tiers": {"process": 30.0},
    "families": {"energy": True},
    "per_tier": {"process": 5},
    "tick_count": 3,
}

PLANT = {
    "sites": {
        "Site1": {
            "shift": "A",
            "lines": {
                "Train1": {
                    "state": "Execute",
                    "previous": "Starting",
                    "production_rate": 0.92,
                    "time_in_state_s": 184.0,
                }
            },
        }
    }
}


class FakeDevice:
    def __init__(self, device_id):
        self.spec = type("Spec", (), {"id": device_id})()
        self.connected = True
        self.publish_fail = 0
        self.last_error = None


class FakeSimulator:
    def __init__(self):
        self.signal_devices = [FakeDevice("main-meter")]

    def status(self):
        return dict(STATUS)

    def plant_snapshot(self):
        return PLANT


class DummyClient:
    """Records publishes, and the Will it was constructed with."""

    instances: list["DummyClient"] = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.published: list[tuple[str, dict, bool]] = []
        DummyClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def publish(self, topic, payload, **kwargs):
        self.published.append((topic, json.loads(payload), bool(kwargs.get("retain"))))


@pytest.fixture(autouse=True)
def _dummy_broker(monkeypatch):
    DummyClient.instances = []
    monkeypatch.setattr(telemetry_module.aiomqtt, "Client", DummyClient)


def _telemetry(interval_s=0.01) -> SelfTelemetry:
    return SelfTelemetry(FakeSimulator(), "Instance01", interval_s=interval_s)


def test_the_prefix_is_platform_observability_not_the_plant():
    assert telemetry_prefix("Instance01") == "uns/platform/simulator/Instance01"


def test_the_status_payload_is_a_summary_and_not_the_whole_status_body():
    """An MQTT heartbeat every ten seconds is not the place for the full device inventory."""
    payload = _telemetry().status_payload()

    assert payload["run_state"] == "running"
    assert payload["published_total"] == 10
    assert "per_tier" not in payload
    assert "tiers" not in payload


def test_a_transition_is_enqueued_and_never_published_inline():
    """PlantClock calls its listeners synchronously on the tick and swallows what they
    raise. An awaited publish here would put broker latency inside the plant's clock."""
    telemetry = _telemetry()
    telemetry.on_transition("Site1", "Train1", "Execute")

    topic, payload = telemetry.queue.get_nowait()
    assert topic == "uns/platform/simulator/Instance01/plant/Site1/Train1/state"
    assert payload["state"] == "Execute"
    assert payload["previous"] == "Starting"
    assert payload["time_in_state_s"] == 184.0
    assert DummyClient.instances == []


def test_a_full_queue_drops_and_counts_rather_than_blocking_the_clock():
    telemetry = _telemetry()
    telemetry.queue = asyncio.Queue(maxsize=1)

    telemetry.on_transition("Site1", "Train1", "Execute")
    telemetry.on_transition("Site1", "Train1", "Holding")

    assert telemetry.queue.qsize() == 1
    assert telemetry.dropped == 1


def test_device_health_is_reported_on_change_only():
    """A hundred healthy devices republishing every ten seconds is more traffic than the
    plant they simulate."""
    telemetry = _telemetry()

    first = telemetry.device_health_changes()
    assert len(first) == 1
    assert first[0][0] == "uns/platform/simulator/Instance01/device/main-meter/health"
    assert telemetry.device_health_changes() == []

    telemetry.simulator.signal_devices[0].connected = False
    changed = telemetry.device_health_changes()
    assert len(changed) == 1
    assert changed[0][1]["connected"] is False


@pytest.mark.asyncio
async def test_the_client_is_built_with_a_retained_last_will_on_the_status_topic():
    """The only failure a heartbeat cannot report: `docker kill`. The Last Will is what
    makes the console say offline instead of showing a status that stopped updating."""
    telemetry = _telemetry()
    task = asyncio.create_task(telemetry.run())
    await asyncio.sleep(0.05)
    await telemetry.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    will = DummyClient.instances[0].kwargs["will"]
    assert will.topic == "uns/platform/simulator/Instance01/status"
    assert will.retain is True
    assert json.loads(will.payload)["run_state"] == "offline"


@pytest.mark.asyncio
async def test_run_publishes_status_retained_and_drains_queued_transitions():
    telemetry = _telemetry()
    telemetry.on_transition("Site1", "Train1", "Execute")

    task = asyncio.create_task(telemetry.run())
    await asyncio.sleep(0.08)
    await telemetry.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    published = DummyClient.instances[0].published
    topics = [topic for topic, _, _ in published]
    assert "uns/platform/simulator/Instance01/status" in topics
    assert "uns/platform/simulator/Instance01/plant/Site1/Train1/state" in topics
    assert "uns/platform/simulator/Instance01/device/main-meter/health" in topics
    assert all(retain for _, _, retain in published)


def _matches(pattern: str, topic: str) -> bool:
    """MQTT wildcard matching, enough of it for the patterns the platform uses."""
    if pattern == "#":
        return True
    if pattern.endswith("/#"):
        stem = pattern[:-2]
        return topic == stem or topic.startswith(f"{stem}/")
    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    if len(pattern_parts) != len(topic_parts):
        return False
    return all(expected in ("+", actual) for expected, actual in zip(pattern_parts, topic_parts, strict=True))


def test_the_wildcard_matcher_itself_is_right():
    """A broken matcher would make the guard below pass for the wrong reason."""
    assert _matches("#", "anything/at/all")
    assert _matches("CovestroAG/#", "CovestroAG/Dormagen/x")
    assert _matches("CovestroAG/#", "CovestroAG")
    assert not _matches("CovestroAG/#", "CovestroAGX/Dormagen")
    assert _matches("spBv1.0/+/NBIRTH/x", "spBv1.0/group/NBIRTH/x")
    assert not _matches("a/b", "a/b/c")


def test_no_mapper_subscribes_to_the_simulator_s_own_telemetry():
    """The separation CONTEXT.md requires, enforced rather than assumed.

    Widening one of these topic lists to `#` is a one-character change, and without this
    test its consequence — the simulator's own heartbeat persisted as plant history — would
    only show up as puzzling rows in the historian months later.
    """
    conf = yaml.safe_load((resolve_conf_dir() / "settings.yaml").read_text(encoding="utf-8"))
    prefix = telemetry_prefix("Instance01")
    telemetry_topics = [
        f"{prefix}/status",
        f"{prefix}/plant/Site1/Train1/state",
        f"{prefix}/device/main-meter/health",
    ]

    for environment in ("graphdb", "historian", "kafka_mapper", "sparkplugb"):
        for pattern in conf[environment]["mqtt"]["topics"]:
            for topic in telemetry_topics:
                assert not _matches(pattern, topic), f"{environment} subscribes to {topic} via {pattern!r}"
