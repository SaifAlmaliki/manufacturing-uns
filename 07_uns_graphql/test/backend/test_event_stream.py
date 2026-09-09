"""Tests for the process-scoped canonical live event dispatcher."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from confluent_kafka import OFFSET_END, TopicPartition
from uns_config.events import HistoricEventEnvelope, source_event_id

from uns_graphql.auth.scope import AccessScope
from uns_graphql.backend import event_stream as event_stream_module
from uns_graphql.backend.event_stream import (
    DispatchedEvent,
    LiveEventDispatcher,
    LiveStreamCapacityError,
    LiveStreamResyncError,
    assign_live_end,
    build_broadcast_consumer_config,
    envelope_to_dispatched,
    reset_dispatcher_for_tests,
    start_dispatcher,
    stop_dispatcher,
)
from uns_graphql.type.streaming_event import StreamingMessage


def _source_envelope(**overrides) -> HistoricEventEnvelope:
    event_time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 1,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": event_time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"value": 21.4, "timestamp": 1_788_948_000_000},
        "raw_payload_base64": None,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


class FakeConsumer:
    def __init__(self) -> None:
        self.subscribed_topics: list[str] = []
        self.on_assign = None
        self.on_revoke = None
        self.closed = False

    def subscribe(self, topics, on_assign, on_revoke) -> None:
        self.subscribed_topics = list(topics)
        self.on_assign = on_assign
        self.on_revoke = on_revoke

    def poll(self, timeout: float):
        return None

    def close(self) -> None:
        self.closed = True


@pytest_asyncio.fixture(loop_scope="function")
async def dispatcher():
    reset_dispatcher_for_tests()
    loop = asyncio.get_running_loop()
    fake_consumer = FakeConsumer()
    live_dispatcher = LiveEventDispatcher(loop=loop, consumer=fake_consumer, max_clients=200)
    await live_dispatcher.start()
    event_stream_module._dispatcher = live_dispatcher
    yield live_dispatcher, fake_consumer
    await live_dispatcher.stop()
    reset_dispatcher_for_tests()


def _admin_scope() -> AccessScope:
    return AccessScope(unrestricted=True, root_paths=frozenset())


def _dispatched(topic: str, payload: dict | None = None) -> DispatchedEvent:
    envelope = _source_envelope(topic=topic, payload=payload or {"value": 1, "timestamp": 123456})
    payload_json = json.dumps(envelope.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return DispatchedEvent(
        topic=envelope.topic,
        payload_json=payload_json,
        event_id=envelope.event_id,
        event_time=envelope.time,
    )


def test_assign_live_end_seeks_to_end():
    consumer = MagicMock()
    partitions = [TopicPartition("uns.historic-events", 0, -1001)]
    assign_live_end(consumer, partitions)
    assert partitions[0].offset == OFFSET_END
    consumer.assign.assert_called_once_with(partitions)


def test_build_broadcast_consumer_config_uses_ephemeral_group_and_latest():
    config_a = build_broadcast_consumer_config(group_suffix="process-a")
    config_b = build_broadcast_consumer_config(group_suffix="process-b")
    assert config_a["group.id"] != config_b["group.id"]
    assert config_a["auto.offset.reset"] == "latest"
    assert config_a["enable.auto.commit"] is True


def test_envelope_to_dispatched_skips_malformed_payload():
    assert envelope_to_dispatched(b"{not-json") is None


@pytest.mark.asyncio
async def test_two_clients_share_one_consumer_and_both_receive_event(dispatcher):
    live_dispatcher, fake_consumer = dispatcher
    assert fake_consumer.subscribed_topics == ["uns.historic-events"]

    client_a = asyncio.create_task(
        anext(live_dispatcher.subscribe(["Enterprise/PlantA/Area/Line/Device/Temperature"], _admin_scope(), None))
    )
    client_b = asyncio.create_task(
        anext(live_dispatcher.subscribe(["Enterprise/PlantA/Area/Line/Device/Temperature"], _admin_scope(), None))
    )
    await asyncio.sleep(0)

    event = _dispatched("Enterprise/PlantA/Area/Line/Device/Temperature", {"value": 42, "timestamp": 123456})
    live_dispatcher._fan_out(event)

    message_a = await asyncio.wait_for(client_a, timeout=1)
    message_b = await asyncio.wait_for(client_b, timeout=1)
    assert message_a == message_b
    assert message_a.topic == event.topic
    assert message_a.event_id == event.event_id


@pytest.mark.asyncio
async def test_client_does_not_receive_unsubscribed_topic(dispatcher):
    live_dispatcher, _fake_consumer = dispatcher
    stream = live_dispatcher.subscribe(["Enterprise/PlantA/Area/Line/Device/Temperature"], _admin_scope(), None)
    subscription = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    live_dispatcher._fan_out(_dispatched("Enterprise/PlantA/Area/Line/Device/Pressure", {"value": 9, "timestamp": 1}))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(subscription, timeout=0.2)


@pytest.mark.asyncio
async def test_slow_client_is_closed_with_resync_error(dispatcher):
    live_dispatcher, _fake_consumer = dispatcher
    registration = await live_dispatcher._register(["Enterprise/PlantA/Area/Line/Device/Temperature"])
    registration.budget.max_messages = 1

    event = _dispatched("Enterprise/PlantA/Area/Line/Device/Temperature")
    live_dispatcher._fan_out(event)
    live_dispatcher._fan_out(event)

    first = await asyncio.wait_for(registration.queue.get(), timeout=1)
    assert first is event
    second = await asyncio.wait_for(registration.queue.get(), timeout=1)
    assert second is event_stream_module.RESYNC_SENTINEL


@pytest.mark.asyncio
async def test_subscribe_raises_resync_error_for_slow_client(dispatcher):
    live_dispatcher, _fake_consumer = dispatcher
    stream = live_dispatcher.subscribe(["Enterprise/PlantA/Area/Line/Device/Temperature"], _admin_scope(), None)
    iterator = stream.__aiter__()
    first_task = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)

    registration_id = next(iter(live_dispatcher._clients))
    live_dispatcher._clients[registration_id].budget.max_messages = 1

    event = _dispatched("Enterprise/PlantA/Area/Line/Device/Temperature")
    live_dispatcher._fan_out(event)
    await asyncio.wait_for(first_task, timeout=1)

    live_dispatcher._fan_out(event)
    with pytest.raises(LiveStreamResyncError):
        await asyncio.wait_for(iterator.__anext__(), timeout=1)


@pytest.mark.asyncio
async def test_capacity_limit_enforced(dispatcher):
    live_dispatcher, _fake_consumer = dispatcher
    live_dispatcher._max_clients = 1
    await live_dispatcher._register(["Enterprise/PlantA/Area/Line/Device/Temperature"])
    with pytest.raises(LiveStreamCapacityError):
        await live_dispatcher._register(["Enterprise/PlantA/Area/Line/Device/Pressure"])


@pytest.mark.asyncio
async def test_unauthorized_topic_is_filtered(dispatcher):
    live_dispatcher, _fake_consumer = dispatcher
    restricted_scope = AccessScope(unrestricted=False, root_paths=frozenset({"Enterprise/PlantA"}))
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=None)

    with patch("uns_graphql.backend.event_stream.allowed_topic", new=AsyncMock(return_value=False)):
        stream = live_dispatcher.subscribe(["Enterprise/PlantA/Area/Line/Device/Temperature"], restricted_scope, resolver)
        subscription = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        live_dispatcher._fan_out(_dispatched("Enterprise/PlantA/Area/Line/Device/Temperature"))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(subscription, timeout=0.2)


@pytest.mark.asyncio
async def test_access_revocation_drops_later_events(dispatcher):
    live_dispatcher, _fake_consumer = dispatcher
    allowed = AsyncMock(side_effect=[True, False])
    stream = live_dispatcher.subscribe(["Enterprise/PlantA/Area/Line/Device/Temperature"], _admin_scope(), None)

    with patch("uns_graphql.backend.event_stream.allowed_topic", allowed):
        iterator = stream.__aiter__()
        first_task = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)
        live_dispatcher._fan_out(
            _dispatched("Enterprise/PlantA/Area/Line/Device/Temperature", {"value": 1, "timestamp": 1})
        )
        first = await asyncio.wait_for(first_task, timeout=1)
        assert isinstance(first, StreamingMessage)

        live_dispatcher._fan_out(
            _dispatched("Enterprise/PlantA/Area/Line/Device/Temperature", {"value": 2, "timestamp": 2})
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(iterator.__anext__(), timeout=0.2)


@pytest.mark.asyncio
async def test_subscribe_unregisters_on_cancel(dispatcher):
    live_dispatcher, _fake_consumer = dispatcher
    stream = live_dispatcher.subscribe(["Enterprise/PlantA/Area/Line/Device/Temperature"], _admin_scope(), None)
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert live_dispatcher._clients == {}


@pytest.mark.asyncio
async def test_start_dispatcher_and_shutdown():
    reset_dispatcher_for_tests()
    loop = asyncio.get_running_loop()
    fake_consumer = FakeConsumer()
    live_dispatcher = await start_dispatcher(loop, consumer=fake_consumer)
    assert live_dispatcher is event_stream_module.get_dispatcher()
    await stop_dispatcher()
    with pytest.raises(RuntimeError):
        event_stream_module.get_dispatcher()