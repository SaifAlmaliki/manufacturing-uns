"""Process-scoped canonical live event dispatcher for GraphQL subscriptions."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from confluent_kafka import OFFSET_END, Consumer, KafkaError, TopicPartition
from uns_config.event_compatibility import as_legacy_telemetry
from uns_config.events import EnvelopeError, decode_event

from uns_graphql.auth.scope import AccessScope, allowed_topic
from uns_graphql.graphql_config import EventStreamConfig, KAFKAConfig
from uns_graphql.type.streaming_event import StreamingMessage

LOGGER = logging.getLogger(__name__)

RESYNC_SENTINEL = object()


class LiveStreamResyncError(RuntimeError):
    """Raised when a slow client exceeds its bounded queue and must resubscribe."""


class LiveStreamCapacityError(RuntimeError):
    """Raised when the process live-stream client limit is reached."""


@dataclass(frozen=True, slots=True)
class DispatchedEvent:
    topic: str
    payload_json: bytes
    event_id: str
    event_time: datetime


@dataclass(slots=True)
class ClientBudget:
    max_messages: int = EventStreamConfig.max_client_messages
    max_bytes: int = EventStreamConfig.max_client_bytes
    message_count: int = 0
    byte_count: int = 0

    def admit(self, payload_size: int) -> bool:
        if self.message_count >= self.max_messages:
            return False
        if self.byte_count + payload_size > self.max_bytes:
            return False
        self.message_count += 1
        self.byte_count += payload_size
        return True


@dataclass(slots=True)
class LiveStreamRegistration:
    registration_id: str
    topics: frozenset[str]
    queue: asyncio.Queue
    budget: ClientBudget = field(default_factory=ClientBudget)


class ConsumerPort(Protocol):
    def poll(self, timeout: float) -> object | None: ...

    def subscribe(self, topics: list[str], on_assign, on_revoke) -> None: ...

    def close(self) -> None: ...


def build_broadcast_consumer_config(*, group_suffix: str | None = None) -> dict:
    suffix = group_suffix or uuid.uuid4().hex
    config = dict(KAFKAConfig.config_map)
    config.update(
        {
            "group.id": f"{EventStreamConfig.broadcast_group_prefix}-{suffix}",
            "enable.auto.commit": True,
            "enable.auto.offset.store": True,
            "auto.offset.reset": "latest",
        }
    )
    return config


def assign_live_end(_consumer, partitions) -> None:
    for partition in partitions:
        partition.offset = OFFSET_END
    _consumer.assign(partitions)


def envelope_to_dispatched(payload: bytes) -> DispatchedEvent | None:
    try:
        envelope = decode_event(payload)
        legacy = as_legacy_telemetry(envelope)
    except EnvelopeError as exc:
        LOGGER.warning("Skipping invalid live envelope: %s", exc)
        return None
    if legacy is None:
        return None
    payload_json = json.dumps(legacy.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return DispatchedEvent(
        topic=legacy.topic,
        payload_json=payload_json,
        event_id=legacy.event_id,
        event_time=legacy.time,
    )


class LiveEventDispatcher:
    """One Kafka consumer per process fanning out to bounded GraphQL client queues."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        consumer: ConsumerPort,
        historic_topic: str = EventStreamConfig.historic_topic,
        max_clients: int = EventStreamConfig.max_clients,
    ) -> None:
        self._loop = loop
        self._consumer = consumer
        self._historic_topic = historic_topic
        self._max_clients = max_clients
        self._clients: dict[str, LiveStreamRegistration] = {}
        self._clients_lock = asyncio.Lock()
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._consumer.subscribe(
            [self._historic_topic],
            on_assign=assign_live_end,
            on_revoke=lambda *_args, **_kwargs: None,
        )
        self._poll_thread = threading.Thread(target=self._poll_loop, name="graphql-live-events", daemon=True)
        self._poll_thread.start()
        self._started = True

    async def stop(self) -> None:
        self._stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
        self._consumer.close()
        async with self._clients_lock:
            self._clients.clear()
        self._started = False

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            message = self._consumer.poll(EventStreamConfig.consumer_poll_timeout)
            if message is None:
                continue
            if hasattr(message, "error") and message.error():
                error = message.error()
                if error.code() != KafkaError._PARTITION_EOF:
                    LOGGER.error("Live event consumer error: %s", error)
                continue
            dispatched = envelope_to_dispatched(message.value() or b"")
            if dispatched is not None:
                self._loop.call_soon_threadsafe(self._fan_out, dispatched)

    def _fan_out(self, event: DispatchedEvent) -> None:
        payload_size = len(event.payload_json)
        for registration in list(self._clients.values()):
            if event.topic not in registration.topics:
                continue
            if not registration.budget.admit(payload_size):
                registration.queue.put_nowait(RESYNC_SENTINEL)
                continue
            registration.queue.put_nowait(event)

    async def _register(self, topics: Iterable[str]) -> LiveStreamRegistration:
        async with self._clients_lock:
            if len(self._clients) >= self._max_clients:
                raise LiveStreamCapacityError(
                    f"live stream client limit of {self._max_clients} reached for this process"
                )
            registration = LiveStreamRegistration(
                registration_id=uuid.uuid4().hex,
                topics=frozenset(topics),
                queue=asyncio.Queue(maxsize=EventStreamConfig.max_client_messages),
            )
            self._clients[registration.registration_id] = registration
            return registration

    async def _unregister(self, registration_id: str) -> None:
        async with self._clients_lock:
            self._clients.pop(registration_id, None)

    async def subscribe(
        self,
        topics: Iterable[str],
        scope: AccessScope,
        resolver: Any,
    ) -> AsyncIterator[StreamingMessage]:
        registration = await self._register(topics)
        try:
            while True:
                item = await registration.queue.get()
                if item is RESYNC_SENTINEL:
                    raise LiveStreamResyncError(
                        "live stream client exceeded message/byte budget; resubscribe to resync"
                    )
                event: DispatchedEvent = item
                if event.topic not in registration.topics:
                    continue
                if not await allowed_topic(scope, event.topic, resolver):
                    continue
                yield StreamingMessage(
                    topic=event.topic,
                    payload=event.payload_json,
                    event_id=event.event_id,
                    event_time=event.event_time,
                )
        finally:
            await self._unregister(registration.registration_id)


_dispatcher: LiveEventDispatcher | None = None


def get_dispatcher() -> LiveEventDispatcher:
    if _dispatcher is None:
        raise RuntimeError("LiveEventDispatcher has not been started")
    return _dispatcher


async def start_dispatcher(loop: asyncio.AbstractEventLoop, *, consumer: ConsumerPort | None = None) -> LiveEventDispatcher:
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher
    live_consumer = consumer or Consumer(build_broadcast_consumer_config())
    _dispatcher = LiveEventDispatcher(loop=loop, consumer=live_consumer)
    await _dispatcher.start()
    return _dispatcher


async def stop_dispatcher() -> None:
    global _dispatcher
    if _dispatcher is None:
        return
    await _dispatcher.stop()
    _dispatcher = None


def reset_dispatcher_for_tests() -> None:
    global _dispatcher
    _dispatcher = None
