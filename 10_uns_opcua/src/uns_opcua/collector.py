"""
Collects data changes from one OPC UA server by subscription.

Report-by-exception is done by the server: each monitored item carries a
`DataChangeFilter` deadband, so the server notifies only when a value moves far enough to
matter. `subscribe_data_change` cannot express a filter, so monitored items are built by
hand and passed to `create_monitored_items`.
"""

import asyncio
import datetime
import logging
import random
from collections.abc import Mapping, Sequence

from asyncua import Client, ua
from uns_opcua import prometheus_metrics as metrics
from uns_opcua.opcua_config import Deadband, ServerConfig
from uns_opcua.payload import build_payload, serialise
from uns_opcua.spool import SpoolRow
from uns_opcua.tag_map import TagBinding

LOGGER = logging.getLogger(__name__)

_DEADBAND_TYPES: dict[str, int] = {
    "absolute": int(ua.DeadbandType.Absolute),
    "percent": int(ua.DeadbandType.Percent),
}


def build_monitored_item_request(
    node_id: ua.NodeId,
    client_handle: int,
    sampling_interval_ms: float,
    deadband: Deadband | None,
) -> ua.MonitoredItemCreateRequest:
    """
    One monitored item, with a server-side deadband when one is configured.

    QueueSize is 1 with DiscardOldest: the namespace carries current state, so if we
    fall behind, the newest value is the one worth keeping.
    """
    parameters = ua.MonitoringParameters(
        ClientHandle=client_handle,
        SamplingInterval=sampling_interval_ms,
        QueueSize=1,
        DiscardOldest=True,
    )
    if deadband is not None:
        parameters.Filter = ua.DataChangeFilter(
            Trigger=ua.DataChangeTrigger.StatusValue,
            DeadbandType=_DEADBAND_TYPES[deadband.type],
            DeadbandValue=float(deadband.value),
        )
    else:
        # asyncua defaults Filter to an empty ExtensionObject; the spec is no filter.
        parameters.Filter = None
    return ua.MonitoredItemCreateRequest(
        ItemToMonitor=ua.ReadValueId(NodeId=node_id, AttributeId=ua.AttributeIds.Value),
        MonitoringMode=ua.MonitoringMode.Reporting,
        RequestedParameters=parameters,
    )


def enqueue_drop_oldest(queue: asyncio.Queue[SpoolRow], row: SpoolRow) -> bool:
    """
    Enqueue without ever blocking the OPC UA callback, dropping the oldest if full.

    A full queue means the spool writer cannot keep up — a disk problem, not a broker
    problem, since a broker outage only grows the spool. Dropping the oldest keeps the
    freshest state moving and is counted, never silent.
    """
    try:
        queue.put_nowait(row)
        return True
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover - a consumer raced us
            pass
        metrics.QUEUE_DROPPED.inc()
        try:
            queue.put_nowait(row)
        except asyncio.QueueFull:  # pragma: no cover - a producer raced us
            pass
        return False


class SubscriptionHandler:
    """
    asyncua's handler protocol. Called from the client's task, so it must not block:
    it maps, serialises and enqueues, and nothing else.
    """

    def __init__(
        self,
        bindings_by_node_id: Mapping[str, TagBinding],
        queue: asyncio.Queue[SpoolRow],
        client_id: str,
        server_name: str,
        qos: int,
    ) -> None:
        self._bindings = bindings_by_node_id
        self._queue = queue
        self._client_id = client_id
        self._server_name = server_name
        self._qos = qos

    def datachange_notification(self, node, val, data) -> None:  # noqa: ANN001 - asyncua protocol
        binding = self._bindings.get(node.nodeid.to_string())
        if binding is None:
            LOGGER.debug("Ignoring a data change for unmapped node %s", node.nodeid)
            return

        data_value = data.monitored_item.Value
        mapped = build_payload(
            binding=binding,
            value=val,
            status_code=int(data_value.StatusCode.value),
            source_timestamp=data_value.SourceTimestamp,
            server_timestamp=data_value.ServerTimestamp,
            collected_at=datetime.datetime.now(tz=datetime.UTC),
            client_id=self._client_id,
        )
        if mapped.timestamp_fallback is not None:
            metrics.TIMESTAMP_FALLBACK.labels(reason=mapped.timestamp_fallback).inc()

        metrics.DATACHANGES.labels(server=self._server_name).inc()
        enqueue_drop_oldest(
            self._queue,
            SpoolRow(topic=mapped.topic, payload=serialise(mapped.payload), qos=self._qos),
        )


class Collector:
    """One supervised task: session, subscription, and reconnect for a single server."""

    def __init__(
        self,
        server: ServerConfig,
        bindings: Sequence[TagBinding],
        queue: asyncio.Queue[SpoolRow],
        client_id: str,
        qos: int,
        backoff_max_s: float = 60.0,
    ) -> None:
        self._server = server
        self._bindings = tuple(bindings)
        self._queue = queue
        self._client_id = client_id
        self._qos = qos
        self._backoff_max_s = backoff_max_s

    async def connect_once(self, client: Client) -> int:
        """
        Resolve the tags, subscribe, and return how many items the server accepted.

        Creating a monitored item delivers its current value immediately, so this is also
        what heals the gap after an outage — with the server's real SourceTimestamp,
        which an explicit read pass could not provide.
        """
        bindings_by_node_id: dict[str, TagBinding] = {}
        requests: list[ua.MonitoredItemCreateRequest] = []
        deadbands: list[Deadband | None] = []

        for handle, binding in enumerate(self._bindings, start=1):
            try:
                node_id = ua.NodeId.from_string(binding.node_id)
            except Exception:
                LOGGER.exception(
                    "%s: node_id %r is not parsable; skipping that tag", self._server.name, binding.node_id
                )
                metrics.UNRESOLVED_NODES.labels(server=self._server.name).inc()
                continue
            bindings_by_node_id[node_id.to_string()] = binding
            requests.append(
                build_monitored_item_request(
                    node_id=node_id,
                    client_handle=handle,
                    sampling_interval_ms=float(self._server.publishing_interval_ms),
                    deadband=binding.deadband,
                )
            )
            deadbands.append(binding.deadband)

        if not requests:
            raise RuntimeError(f"{self._server.name}: no usable tags")

        handler = SubscriptionHandler(
            bindings_by_node_id=bindings_by_node_id,
            queue=self._queue,
            client_id=self._client_id,
            server_name=self._server.name,
            qos=self._qos,
        )
        subscription = await client.create_subscription(
            float(self._server.publishing_interval_ms), handler
        )

        results = await subscription.create_monitored_items(requests)
        accepted = await self._retry_rejected(subscription, requests, deadbands, results)
        metrics.MONITORED_ITEMS.labels(server=self._server.name).set(accepted)
        LOGGER.info("%s: monitoring %s of %s tags", self._server.name, accepted, len(requests))
        return accepted

    async def _retry_rejected(
        self,
        subscription,  # noqa: ANN001 - asyncua Subscription
        requests: Sequence[ua.MonitoredItemCreateRequest],
        deadbands: Sequence[Deadband | None],
        results: Sequence[int | ua.StatusCode],
    ) -> int:
        """
        A rejected item comes back as a StatusCode instead of an int handle. The usual
        cause is a server that will not accept a deadband, so retry those without one:
        losing report-by-exception on one tag beats losing the tag.
        """
        accepted = sum(1 for result in results if not isinstance(result, ua.StatusCode))
        retries = [
            build_monitored_item_request(
                node_id=requests[index].ItemToMonitor.NodeId,
                client_handle=requests[index].RequestedParameters.ClientHandle,
                sampling_interval_ms=requests[index].RequestedParameters.SamplingInterval,
                deadband=None,
            )
            for index, result in enumerate(results)
            if isinstance(result, ua.StatusCode) and deadbands[index] is not None
        ]
        for index, result in enumerate(results):
            if isinstance(result, ua.StatusCode):
                LOGGER.warning(
                    "%s: server rejected monitored item for %s (%s)",
                    self._server.name,
                    requests[index].ItemToMonitor.NodeId,
                    result,
                )
                metrics.DEADBAND_REJECTED.labels(server=self._server.name).inc()

        if retries:
            retry_results = await subscription.create_monitored_items(retries)
            accepted += sum(1 for result in retry_results if not isinstance(result, ua.StatusCode))
        return accepted

    async def run(self) -> None:
        """Reconnect forever with exponential backoff and jitter."""
        backoff = 1.0
        while True:
            client = Client(url=self._server.url)
            if self._server.security is not None:
                await client.set_security_string(self._server.security.to_security_string())
            try:
                async with client:
                    await self.connect_once(client)
                    metrics.SERVER_UP.labels(server=self._server.name).set(1)
                    backoff = 1.0
                    # The subscription runs on the client's own task; keep the session open.
                    while True:
                        await asyncio.sleep(3600)
            except asyncio.CancelledError:
                metrics.SERVER_UP.labels(server=self._server.name).set(0)
                raise
            except Exception:
                metrics.SERVER_UP.labels(server=self._server.name).set(0)
                metrics.MONITORED_ITEMS.labels(server=self._server.name).set(0)
                delay = min(backoff, self._backoff_max_s) * (0.5 + random.random())
                LOGGER.exception("%s: session lost; reconnecting in %.1fs", self._server.name, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, self._backoff_max_s)
