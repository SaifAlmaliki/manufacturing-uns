"""
Moves collected messages from memory to disk, and from disk to the broker.

The spool writer is a single task so there is no SQLite lock contention, and it batches
because a transaction per message would not keep up. The forwarder holds one long-lived
MQTT connection — deliberately not the simulator's connect-per-publish.
"""

import asyncio
import contextlib
import logging
import random
import time
from typing import Protocol

import aiomqtt
from uns_opcua import prometheus_metrics as metrics
from uns_opcua.opcua_config import MQTTConfig
from uns_opcua.spool import Spool, SpoolRow

LOGGER = logging.getLogger(__name__)


class Publisher(Protocol):
    """Just enough of aiomqtt.Client to let the forwarder be tested without a broker."""

    async def publish(self, topic: str, payload: bytes, qos: int) -> None: ...


class SpoolWriter:
    """Drains the in-memory queue into the spool in batches."""

    def __init__(
        self,
        spool: Spool,
        queue: asyncio.Queue[SpoolRow],
        batch_size: int = 500,
        flush_interval_s: float = 0.05,
    ) -> None:
        self._spool = spool
        self._queue = queue
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s

    async def drain_once(self, now: float) -> int:
        """Write whatever is already queued, up to one batch, then enforce the bounds."""
        rows: list[SpoolRow] = []
        while len(rows) < self._batch_size:
            try:
                rows.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not rows:
            return 0

        try:
            written = await asyncio.to_thread(self._spool.enqueue, rows, now)
        except Exception:
            # A full or failing disk must not take the process down; collection continues
            # and the queue's drop-oldest policy becomes the pressure valve.
            metrics.SPOOL_WRITE_ERRORS.inc()
            LOGGER.exception("Failed to write %s rows to the spool", len(rows))
            return 0

        dropped = await asyncio.to_thread(self._spool.trim, now)
        if dropped:
            metrics.SPOOL_DROPPED.inc(dropped)
        await self._publish_gauges(now)
        return written

    async def _publish_gauges(self, now: float) -> None:
        rows = await asyncio.to_thread(self._spool.row_count)
        size = await asyncio.to_thread(self._spool.byte_size)
        oldest = await asyncio.to_thread(self._spool.oldest_spooled_at)
        metrics.SPOOL_ROWS.set(rows)
        metrics.SPOOL_BYTES.set(size)
        metrics.SPOOL_LAG_SECONDS.set(0.0 if oldest is None else max(0.0, now - oldest))

    async def run(self) -> None:
        """Batch by size or by `flush_interval_s`, whichever comes first."""
        while True:
            if await self.drain_once(now=time.time()) == 0:
                await asyncio.sleep(self._flush_interval_s)


class Forwarder:
    """Drains the spool to MQTT, oldest first, deleting only what was acknowledged."""

    def __init__(
        self,
        spool: Spool,
        client_id: str,
        qos: int,
        batch_size: int = 200,
        backoff_max_s: float = 60.0,
        idle_interval_s: float = 0.1,
    ) -> None:
        self._spool = spool
        self._client_id = client_id
        self._qos = qos
        self._batch_size = batch_size
        self._backoff_max_s = backoff_max_s
        self._idle_interval_s = idle_interval_s

    async def forward_batch(self, publisher: Publisher) -> int:
        """
        Publish one batch and delete through the last acknowledged id.

        Deleting after publishing is what makes this at-least-once: a crash in between
        replays on restart, which the historian's ON CONFLICT DO NOTHING absorbs. Losing
        the message instead would be unrecoverable, so this is the right way round.
        """
        batch = await asyncio.to_thread(self._spool.peek, self._batch_size)
        if not batch:
            return 0

        acknowledged_through: int | None = None
        try:
            for row_id, row in batch:
                await publisher.publish(row.topic, row.payload, row.qos or self._qos)
                metrics.PUBLISH_TOTAL.inc()
                acknowledged_through = row_id
        except Exception:
            metrics.PUBLISH_ERRORS.inc()
            raise
        finally:
            if acknowledged_through is not None:
                await asyncio.to_thread(self._spool.delete_through, acknowledged_through)

        return len(batch)

    async def run(self) -> None:
        """
        Keep one connection open and drain. While the broker is down the spool grows;
        that is the intended behaviour, not an error state.
        """
        backoff = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=MQTTConfig.host,
                    port=MQTTConfig.port,
                    username=MQTTConfig.username,
                    password=MQTTConfig.password,
                    identifier=self._client_id,
                    protocol=MQTTConfig.version,
                    tls_params=MQTTConfig.tls_params,
                    tls_insecure=MQTTConfig.tls_insecure,
                    keepalive=MQTTConfig.keep_alive,
                    transport=MQTTConfig.transport,
                ) as client:
                    LOGGER.info("Forwarder connected to %s:%s", MQTTConfig.host, MQTTConfig.port)
                    backoff = 1.0
                    while True:
                        if await self.forward_batch(client) == 0:
                            await asyncio.sleep(self._idle_interval_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = min(backoff, self._backoff_max_s) * (0.5 + random.random())
                LOGGER.exception("Forwarder lost the broker; retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, self._backoff_max_s)


@contextlib.asynccontextmanager
async def opened_spool(spool: Spool):
    """Open the spool off the event loop and always close it."""
    await asyncio.to_thread(spool.open)
    try:
        yield spool
    finally:
        await asyncio.to_thread(spool.close)
