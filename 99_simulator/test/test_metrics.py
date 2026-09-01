"""Platform Observability for the simulator itself (spec 5.3).

Self-contained on purpose: it builds one device rather than importing another test
module's fixtures, so a change to the plant-model tests cannot break the metric names
that Prometheus and Grafana depend on.
"""

import json

import pytest
from prometheus_client import generate_latest

from uns_simulator import devices as devices_module
from uns_simulator.devices import SignalDevice
from uns_simulator.metrics import SimulatorCollector
from uns_simulator.models import ISA95Hierarchy
from uns_simulator.plant import DeviceView, LineTiming, PlantContext
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import SignalSpec

PATH = ISA95Hierarchy("CovestroAG", "Dormagen", "Utilities", "Powerhouse", "Cell1", kind="utilities")


class DummyClient:
    """Records publishes instead of contacting a broker."""

    def __init__(self, *args, **kwargs):
        self.published: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def publish(self, topic, payload, **kwargs):
        self.published.append((topic, json.loads(payload)))


@pytest.fixture(autouse=True)
def _dummy_broker(monkeypatch):
    monkeypatch.setattr(devices_module.aiomqtt, "Client", DummyClient)


def _device() -> SignalDevice:
    context = PlantContext(global_seed=7)
    context.add_site("Dormagen")
    timing = LineTiming(starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=0.0)
    context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
    spec = DeviceSpec(
        id="main-meter",
        equipment="MainMeter",
        family="energy",
        tier="energy",
        path=PATH,
        signals=(
            SignalSpec(name="ActivePower", unit="kW", base_value=100.0, tier="energy", export_metric=True),
            SignalSpec(name="PowerFactor", unit="", base_value=0.95, tier="status"),
        ),
        serves=("Production/Line1",),
    )
    view = DeviceView(context, "Dormagen", None, spec.serves)
    return SignalDevice(spec, {}, view, 7)


class _Sim:
    """The one attribute SimulatorCollector reads."""

    def __init__(self, signal_devices):
        self.signal_devices = signal_devices


def _families(registry) -> dict[str, object]:
    return {family.name: family for family in registry.collect()}


@pytest.mark.asyncio
async def test_published_messages_are_counted_by_tier_and_family():
    device = _device()
    device.evaluate(1.0)
    await device.publish_tier("energy")
    assert device.published_by_tier["energy"] == 1
    assert device.published_by_tier["status"] == 0


@pytest.mark.asyncio
async def test_the_collector_renders_the_five_metrics_spec_5_3_names():
    device = _device()
    device.evaluate(1.0)
    await device.publish_tier("energy")
    registry = SimulatorCollector.build_registry(_Sim([device]))

    rendered = generate_latest(registry).decode()
    assert 'uns_simulator_messages_published_total{family="energy",tier="energy"} 1.0' in rendered
    assert 'uns_simulator_publish_failures_total{device="main-meter"} 0.0' in rendered
    assert 'uns_simulator_reconnects_total{device="main-meter"} 0.0' in rendered
    assert "uns_simulator_devices_connected 1.0" in rendered
    assert 'uns_simulator_signal_value{device="main-meter",signal="ActivePower"}' in rendered


@pytest.mark.asyncio
async def test_only_signals_flagged_export_metric_become_a_gauge():
    """A profile has hundreds of signals. Exporting all of them would make every
    Prometheus scrape a cardinality problem, so the flag is opt-in per signal."""
    device = _device()
    device.evaluate(1.0)
    registry = SimulatorCollector.build_registry(_Sim([device]))

    rendered = generate_latest(registry).decode()
    assert 'signal="ActivePower"' in rendered
    assert 'signal="PowerFactor"' not in rendered


def test_a_simulator_with_no_devices_still_renders_every_metric_name():
    """A stopped simulator must not produce an empty scrape: a missing series and a
    zero series look identical in a graph, and only one of them is true."""
    registry = SimulatorCollector.build_registry(_Sim([]))

    names = _families(registry).keys()
    assert "uns_simulator_messages_published" in names
    assert "uns_simulator_publish_failures" in names
    assert "uns_simulator_reconnects" in names
    assert "uns_simulator_devices_connected" in names
    assert "uns_simulator_signal_value" in names
