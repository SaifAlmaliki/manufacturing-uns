"""Publishing a closed shift's OEE back onto the unit's own Asset path.

The engine reads history and writes a result, and this module is the only part of it that
touches MQTT. One message per unit per shift on `<asset path>/KPI/ShiftOee`, over one
long-lived connection - the scheduler wakes every few minutes, and a connect-publish-
disconnect per result would spend more time in handshakes than in work.

`publish` returns False rather than raising. Whether the message reached the broker decides
whether `ResultStore.mark_published` is called, and a NULL `published_at` is what makes the
next scan try again. That is the entire retry mechanism: no queue, no backoff, nothing to
drain on shutdown, and nothing that can silently lose a result because a process died.
"""

import contextlib
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import aiomqtt

from uns_oee.oee_config import OeeConfig
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.shift_calendar import ShiftWindow

LOGGER = logging.getLogger(__name__)

#: The sixth ParameterType, added to the simulator's enum in Task 17. A computed shift KPI is
#: not a ProcessValue, and the graph database and alert engine both type topics by this segment.
KPI_PARAMETER_TYPE = "KPI"
KPI_PARAMETER_NAME = "ShiftOee"

#: `source` on every payload, so a consumer can tell a computed number from a measured one.
PAYLOAD_SOURCE = "uns_oee"

#: Percentages are published to this many decimals. One is what a shift report shows.
_PERCENT_DECIMALS = 1

#: Spec section 11's field set, asserted against rather than described.
PAYLOAD_FIELDS = frozenset(
    {
        "value",
        "unit",
        "quality",
        "timestamp",
        "source",
        "equipment",
        "availability",
        "performance",
        "good_count",
        "reject_count",
        "total_count",
        "shift_label",
        "shift_start",
        "status",
        "revision",
    }
)


def shift_oee_topic(asset_path: str) -> str:
    """The unit's own Asset path plus the KPI parameter. No new topic namespace."""
    return f"{asset_path}/{KPI_PARAMETER_TYPE}/{KPI_PARAMETER_NAME}"


def equipment_of(asset_path: str) -> str:
    """The last segment of the Asset path, which is the platform's `equipment` convention.

    Imprecise at line level - `Line1` is not a piece of equipment - but it is the existing
    convention, and a second field name for the same idea would be worse than a loose word.
    """
    return asset_path.rsplit("/", 1)[-1]


def epoch_millis(at: datetime) -> float:
    """A timezone-aware instant as epoch milliseconds.

    Milliseconds because `conf/settings.yaml:57` makes `timestamp` the historian's `time`
    column, and every other publisher on this platform already uses that unit.
    """
    return at.timestamp() * 1000.0


def as_percent(ratio: float | None) -> float | None:
    """A 0-1 factor as a percentage, or None if it is undefined.

    None survives as None: `flatten_payload_to_metrics` skips a null leaf entirely
    (`metric_flattener.py:52`), so an undefined factor produces no `uns_metrics` row instead
    of a zero that would drag every rollup down.
    """
    return None if ratio is None else round(ratio * 100.0, _PERCENT_DECIMALS)


def shift_oee_payload(
    asset_path: str, window: ShiftWindow, metrics: ShiftMetrics, revision: int
) -> dict[str, Any]:
    """Spec section 11's payload for one closed shift.

    `timestamp` is `shift_end`, so the historian stamps the result at the moment the shift
    finished - which is where a trend line needs it, not where the engine happened to run.
    Counts stay floats: a counter delta need not be discrete, and `value_double` holds both.
    """
    return {
        "value": as_percent(metrics.oee),
        "unit": "%",
        "quality": as_percent(metrics.quality),
        "timestamp": epoch_millis(window.end),
        "source": PAYLOAD_SOURCE,
        "equipment": equipment_of(asset_path),
        "availability": as_percent(metrics.availability),
        "performance": as_percent(metrics.performance),
        "good_count": metrics.good_count,
        "reject_count": metrics.reject_count,
        "total_count": metrics.total_count,
        "shift_label": window.label,
        "shift_start": epoch_millis(window.start),
        "status": metrics.status,
        "revision": revision,
    }


class ResultPublisher:
    """One MQTT connection, opened on the first publish and kept.

    `client_factory` exists so a test can hand in a stand-in; production leaves it unset and
    gets a client built from `OeeConfig`.
    """

    def __init__(
        self, config: OeeConfig, client_factory: Callable[[], Any] | None = None
    ) -> None:
        self._config = config
        self._client_factory = client_factory or self._build_client
        self._stack: contextlib.AsyncExitStack | None = None
        self._client: Any | None = None
        self.published = 0
        self.failed = 0

    @property
    def connected(self) -> bool:
        return self._client is not None

    def _build_client(self) -> aiomqtt.Client:
        """A client from the platform's shared `mqtt:` settings.

        `clean_session` is deliberately left unset: aiomqtt rejects it under MQTT 5, and the
        platform's `mqtt.version` is 5. No Last Will either - the engine has no online state
        worth announcing, unlike the simulator's heartbeat.
        """
        return aiomqtt.Client(
            identifier=self._config.mqtt_client_id,
            hostname=self._config.mqtt_host,
            port=self._config.mqtt_port,
            username=self._config.mqtt_username,
            password=self._config.mqtt_password,
            keepalive=self._config.mqtt_keep_alive,
            protocol=aiomqtt.ProtocolVersion(self._config.mqtt_version),
            transport=self._config.mqtt_transport,
        )

    async def _connect(self) -> Any:
        """The live client, connecting first if there is not one."""
        if self._client is None:
            stack = contextlib.AsyncExitStack()
            self._client = await stack.enter_async_context(self._client_factory())
            self._stack = stack
            LOGGER.info(
                "OEE publisher connected to %s:%s as %s",
                self._config.mqtt_host,
                self._config.mqtt_port,
                self._config.mqtt_client_id,
            )
        return self._client

    async def _drop(self) -> None:
        """Forget the connection, so the next publish makes a new one.

        Errors while closing are suppressed: this is called because publishing already failed,
        and a second exception from the same broken socket says nothing new.
        """
        stack = self._stack
        self._stack = None
        self._client = None
        if stack is not None:
            with contextlib.suppress(Exception):
                await stack.aclose()

    async def publish(
        self, asset_path: str, window: ShiftWindow, metrics: ShiftMetrics, revision: int
    ) -> bool:
        """Send one shift result. True if the broker took it.

        Not retained: a shift result is a historical fact stamped at its own `shift_end`, and
        retaining it would hand every new subscriber the last closed shift as though it were
        the current one.
        """
        topic = shift_oee_topic(asset_path)
        body = json.dumps(shift_oee_payload(asset_path, window, metrics, revision))
        try:
            client = await self._connect()
            await client.publish(topic, body, qos=self._config.mqtt_qos, retain=False)
        except Exception:
            self.failed += 1
            LOGGER.exception("OEE publish to %s failed; leaving it unpublished for retry", topic)
            await self._drop()
            return False
        self.published += 1
        LOGGER.debug("Published %s revision %d", topic, revision)
        return True

    async def aclose(self) -> None:
        """Close the connection if there is one. Safe to call when there is not."""
        await self._drop()


__all__ = [
    "KPI_PARAMETER_NAME",
    "KPI_PARAMETER_TYPE",
    "PAYLOAD_FIELDS",
    "PAYLOAD_SOURCE",
    "ResultPublisher",
    "as_percent",
    "epoch_millis",
    "equipment_of",
    "shift_oee_payload",
    "shift_oee_topic",
]
