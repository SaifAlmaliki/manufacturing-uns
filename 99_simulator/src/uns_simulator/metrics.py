"""Platform Observability for the simulator: Prometheus metrics on their own port.

A custom collector rather than module-level Counter objects, because every number
already exists. AsyncMQTTDevice counts publish_ok / publish_fail / reconnects and
SignalDevice counts published_by_tier; mirroring those into prometheus_client Counters
would create a second source for one fact, and the copy is what goes stale.

This is Platform Observability, never Process Visualization: it says whether the
simulator is publishing, not what the simulated plant is doing. The one exception is
`uns_simulator_signal_value`, which exists so a Grafana panel can be built before the
historian has ingested anything, and which is opt-in per signal for that reason.
"""

import logging
from collections.abc import Iterator

from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric

LOGGER = logging.getLogger(__name__)


class SimulatorCollector:
    """Renders the simulator's live counters at scrape time.

    `collect()` runs on prometheus_client's HTTP thread, not the simulation's event loop,
    so every container it walks is copied before it is iterated. Walking a list the loop
    is appending to raises mid-scrape and loses the whole response, not just one series.
    """

    def __init__(self, simulator) -> None:
        self.simulator = simulator

    @classmethod
    def build_registry(cls, simulator) -> CollectorRegistry:
        """A registry holding only this collector.

        Its own registry rather than the default one: the default also carries the Python
        process and GC collectors, and 9093 exists to answer one question.
        """
        registry = CollectorRegistry()
        registry.register(cls(simulator))
        return registry

    def collect(self) -> Iterator[Metric]:
        devices = list(self.simulator.signal_devices)

        published = CounterMetricFamily(
            "uns_simulator_messages_published",
            "Payloads published by the simulator, by cadence tier and sensor family.",
            labels=["tier", "family"],
        )
        for device in devices:
            for tier, count in dict(device.published_by_tier).items():
                published.add_metric([tier, device.spec.family], count)
        yield published

        failures = CounterMetricFamily(
            "uns_simulator_publish_failures",
            "Publish attempts that raised, by device.",
            labels=["device"],
        )
        reconnects = CounterMetricFamily(
            "uns_simulator_reconnects",
            "Broker reconnections, by device.",
            labels=["device"],
        )
        for device in devices:
            failures.add_metric([device.spec.id], device.publish_fail)
            reconnects.add_metric([device.spec.id], device.reconnects)
        yield failures
        yield reconnects

        connected = GaugeMetricFamily(
            "uns_simulator_devices_connected",
            "Simulated devices currently holding a broker connection.",
        )
        connected.add_metric([], sum(1 for device in devices if device.connected))
        yield connected

        values = GaugeMetricFamily(
            "uns_simulator_signal_value",
            "Current value of signals declared with export_metric, by device and signal.",
            labels=["device", "signal"],
        )
        for device in devices:
            for spec in device.spec.signals:
                if not spec.export_metric:
                    continue
                value = device.values.get(spec.name)
                # Booleans are ints in Python and a bool gauge would silently read 1.0;
                # a signal worth exporting is numeric, so skip everything else.
                if isinstance(value, int | float) and not isinstance(value, bool):
                    values.add_metric([device.spec.id, spec.name], float(value))
        yield values


def start_metrics_server(simulator, port: int) -> CollectorRegistry:
    """Serve the collector on `port` in a background thread, and return its registry."""
    registry = SimulatorCollector.build_registry(simulator)
    start_http_server(port, registry=registry)
    LOGGER.info("Simulator metrics available on port %d", port)
    return registry
