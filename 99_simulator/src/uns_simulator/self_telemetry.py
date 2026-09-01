"""The simulator's own health, published into MQTT (spec 6).

Platform Observability, not Process Visualization. These topics live under
`uns/platform/simulator/<instance>/`, which no mapper subscribes to, so the simulator's
heartbeat is never persisted as though a machine had measured it. test_self_telemetry.py
enforces that against the real topic lists in conf/settings.yaml.

Its own aiomqtt client rather than borrowing a device's, for one reason that decides it: a
Last Will has to be set when the connection is made, and no plant device has one. The Last
Will is what makes `.../status` report `offline` after a `docker kill` — the one failure a
heartbeat cannot report about itself.
"""

import asyncio
import json
import logging
import time
from typing import Any
from uuid import uuid4

import aiomqtt

from uns_simulator.config import MQTTConfig

LOGGER = logging.getLogger(__name__)

# Bounded, because the producer is the plant clock. An unbounded queue would turn a broker
# outage into a memory leak that outlives the outage.
QUEUE_LIMIT = 1000
RECONNECT_DELAY_S = 5.0


def telemetry_prefix(instance: str) -> str:
    """The Platform Observability prefix for one Instance of the platform."""
    return f"uns/platform/simulator/{instance}"


class SelfTelemetry:
    """Publishes simulator status, plant transitions and device health.

    Three cadences, each chosen for what it is reporting:
      status         - every `interval_s`, because "still alive" is a heartbeat
      plant state    - on a PackML transition, because that is the event
      device health  - on change, because a hundred healthy devices repeating themselves
                       every ten seconds is more traffic than the plant they simulate
    """

    def __init__(self, simulator, instance: str, interval_s: float = 10.0) -> None:
        self.simulator = simulator
        self.prefix = telemetry_prefix(instance)
        self.interval_s = interval_s
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.client: aiomqtt.Client | None = None
        self.published = 0
        self.dropped = 0
        self._running = False
        self._device_health: dict[str, dict[str, Any]] = {}

    def _build_client(self) -> aiomqtt.Client:
        """A client whose Last Will is a retained `offline` status.

        Every connection parameter comes from MQTTConfig, exactly as AsyncMQTTDevice builds
        its own: telemetry that cannot reach a TLS broker would be worse than none, because
        its silence would look like the simulator being down.
        """
        will = aiomqtt.Will(
            topic=f"{self.prefix}/status",
            payload=json.dumps({"run_state": "offline", "reason": "mqtt last will"}),
            qos=1,
            retain=True,
        )
        return aiomqtt.Client(
            identifier=f"uns_simulator-telemetry-{uuid4().hex[:8]}",
            clean_session=MQTTConfig.clean_session,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            hostname=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            keepalive=MQTTConfig.keep_alive,
            tls_params=MQTTConfig.tls_params,
            tls_insecure=MQTTConfig.tls_insecure,
            will=will,
        )

    def status_payload(self) -> dict[str, Any]:
        """A summary, not the whole status body.

        The full document has the tier map and the per-tier signal counts in it, which are
        configuration rather than health, and a retained heartbeat is not where they belong.
        """
        body = self.simulator.status()
        return {
            "run_state": body["run_state"],
            "profile": body["profile"],
            "device_count": body["device_count"],
            "signal_count": body["signal_count"],
            "published_total": body["published_total"],
            "failed_total": body["failed_total"],
            "msg_per_sec": body["msg_per_sec"],
            "uptime_s": body["uptime_s"],
            "overrides_active": body["overrides_active"],
        }

    def device_health_changes(self) -> list[tuple[str, dict[str, Any]]]:
        """The devices whose health changed since this was last called."""
        changes: list[tuple[str, dict[str, Any]]] = []
        for device in self.simulator.signal_devices:
            current = {
                "connected": device.connected,
                "publish_fail": device.publish_fail,
                "last_error": device.last_error,
            }
            if self._device_health.get(device.spec.id) == current:
                continue
            self._device_health[device.spec.id] = current
            changes.append((f"{self.prefix}/device/{device.spec.id}/health", current))
        return changes

    def on_transition(self, site: str, line: str, state: str) -> None:
        """Registered with `simulator.on_plant_transition`. Enqueues; never publishes.

        Synchronous and non-blocking by contract: PlantClock calls this on the tick and
        swallows anything it raises, so an awaited publish here would put broker latency
        inside the plant's clock and an exception would vanish without a trace.
        """
        line_state = self.simulator.plant_snapshot()["sites"].get(site, {}).get("lines", {}).get(line, {})
        payload = {
            "state": state,
            "previous": line_state.get("previous"),
            "production_rate": line_state.get("production_rate"),
            "time_in_state_s": line_state.get("time_in_state_s"),
        }
        try:
            self.queue.put_nowait((f"{self.prefix}/plant/{site}/{line}/state", payload))
        except asyncio.QueueFull:
            # Counted rather than logged per event: a full queue means a broker outage, and
            # a log line per dropped transition would be its own denial of service.
            self.dropped += 1

    async def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self.client is None:
            return
        # Retained, so a console that connects later immediately learns the current state
        # instead of waiting a whole interval. The Last Will overwrites the retained status
        # when the process dies, which is the entire mechanism.
        await self.client.publish(topic, json.dumps(payload, default=str), qos=1, retain=True)
        self.published += 1

    async def _drain(self, window_s: float) -> None:
        """Publish queued transitions for up to `window_s` seconds, then return.

        A window rather than a plain sleep, so a burst of PackML transitions reaches the
        broker when it happens instead of on the next status beat.
        """
        deadline = time.monotonic() + window_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return
            try:
                topic, payload = await asyncio.wait_for(self.queue.get(), timeout=remaining)
            except TimeoutError:
                return
            await self._publish(topic, payload)

    async def run(self) -> None:
        """Connect, then publish until stopped. Reconnects on its own."""
        self._running = True
        while self._running:
            try:
                async with self._build_client() as client:
                    self.client = client
                    LOGGER.info("Simulator self-telemetry publishing under %s", self.prefix)
                    while self._running:
                        await self._publish(f"{self.prefix}/status", self.status_payload())
                        for topic, payload in self.device_health_changes():
                            await self._publish(topic, payload)
                        await self._drain(self.interval_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Simulator self-telemetry lost its connection; retrying")
                await asyncio.sleep(RECONNECT_DELAY_S)
            finally:
                self.client = None

    async def stop(self) -> None:
        """End the loop after the current window. Publishing a final `offline` status is
        deliberately not done here: the Last Will covers the crash case, and a clean stop
        is already visible in GET /simulator/status."""
        self._running = False
