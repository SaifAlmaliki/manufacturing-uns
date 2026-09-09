"""Tests for the live event GraphQL subscription."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from uns_config.events import HistoricEventEnvelope, source_event_id

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity
from uns_graphql.backend import event_stream as event_stream_module
from uns_graphql.backend.event_stream import DispatchedEvent, LiveEventDispatcher, reset_dispatcher_for_tests
from uns_graphql.input.kafka import KAFKATopicInput
from uns_graphql.subscriptions.kafka import KAFKASubscription
from uns_graphql.type.streaming_event import StreamingMessage


class FakeConsumer:
    def __init__(self) -> None:
        self.subscribed_topics: list[str] = []
        self.on_assign = None
        self.on_revoke = None

    def subscribe(self, topics, on_assign, on_revoke) -> None:
        self.subscribed_topics = list(topics)
        self.on_assign = on_assign
        self.on_revoke = on_revoke

    def poll(self, timeout: float):
        return None

    def close(self) -> None:
        pass


def _admin_info() -> SimpleNamespace:
    return SimpleNamespace(
        context={
            CONTEXT_KEY: Identity(subject="s", username="ada.admin", roles=frozenset({"admin"})),
        }
    )


def _source_envelope(topic: str, payload: dict) -> HistoricEventEnvelope:
    event_time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    return HistoricEventEnvelope(
        schema_version=1,
        event_id=source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        identity_quality="source",
        source_id="plant-a/gateway-01",
        source_boot_id="boot-17",
        source_sequence=42,
        site_id="plant-a",
        time=event_time,
        received_at=received_at,
        timestamp_quality="source",
        topic=topic,
        event_kind="telemetry",
        is_historical=False,
        payload=payload,
        raw_payload_base64=None,
    )


def _dispatched(topic: str, payload: dict) -> DispatchedEvent:
    envelope = _source_envelope(topic, payload)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return DispatchedEvent(
        topic=topic,
        payload_json=payload_json,
        event_id=envelope.event_id,
        event_time=envelope.time,
    )


@pytest_asyncio.fixture(loop_scope="function")
async def dispatcher():
    reset_dispatcher_for_tests()
    loop = asyncio.get_running_loop()
    fake_consumer = FakeConsumer()
    live_dispatcher = LiveEventDispatcher(loop=loop, consumer=fake_consumer)
    await live_dispatcher.start()
    event_stream_module._dispatcher = live_dispatcher
    yield live_dispatcher
    await live_dispatcher.stop()
    reset_dispatcher_for_tests()


TWO_TOPICS_MULTIPLE_MSGS = (
    [
        KAFKATopicInput(topic="Enterprise/PlantA/Area/Line/Device/Temperature"),
        KAFKATopicInput(topic="Enterprise/PlantA/Area/Line/Device/Pressure"),
    ],
    [
        ("Enterprise/PlantA/Area/Line/Device/Temperature", {"timestamp": 123456, "val1": 1234}),
        ("Enterprise/PlantA/Area/Line/Device/Pressure", {"timestamp": 123987, "val1": 9876}),
        ("Enterprise/PlantA/Area/Line/Device/Temperature", {"timestamp": 234567, "val1": 2345}),
        ("Enterprise/PlantA/Area/Line/Device/Pressure", {"timestamp": 456789, "val2": "test different"}),
    ],
)

ONE_TOPIC_MULTIPLE_MSGS = (
    [KAFKATopicInput(topic="Enterprise/PlantA/Area/Line/Device/Flow")],
    [
        ("Enterprise/PlantA/Area/Line/Device/Flow", {"timestamp": 123456, "val1": 1234}),
        ("Enterprise/PlantA/Area/Line/Device/Flow", {"timestamp": 123457, "val1": 5678}),
        ("Enterprise/PlantA/Area/Line/Device/Flow", {"timestamp": 123458, "val1": 9012}),
    ],
)

ONE_TOPIC_ONE_MSG = (
    [KAFKATopicInput(topic="Enterprise/PlantA/Area/Line/Device/Speed")],
    [("Enterprise/PlantA/Area/Line/Device/Speed", {"timestamp": 123456, "val1": 1234})],
)


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    "topics, message_vals",
    [
        TWO_TOPICS_MULTIPLE_MSGS,
        ONE_TOPIC_MULTIPLE_MSGS,
        ONE_TOPIC_ONE_MSG,
    ],
)
async def test_get_kafka_messages_mock(dispatcher, topics: list[KAFKATopicInput], message_vals: tuple):
    subscription = KAFKASubscription()
    received_messages: list[StreamingMessage] = []
    async_message_list = subscription.get_kafka_messages(_admin_info(), topics)
    consume_task = asyncio.create_task(_collect_messages(async_message_list, received_messages, len(message_vals)))
    await asyncio.sleep(0)

    for topic, payload in message_vals:
        dispatcher._fan_out(_dispatched(topic, payload))

    await asyncio.wait_for(consume_task, timeout=2)
    await async_message_list.aclose()

    assert len(received_messages) == len(message_vals)
    for topic, payload in message_vals:
        expected_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        assert any(
            message.topic == topic and message.payload.data == expected_payload.decode("utf-8")
            for message in received_messages
        )


async def _collect_messages(stream, received_messages: list[StreamingMessage], expected_count: int) -> None:
    index = 0
    async for message in stream:
        assert isinstance(message, StreamingMessage)
        received_messages.append(message)
        index += 1
        if index == expected_count:
            break


@pytest.mark.asyncio
async def test_get_kafka_messages_rejects_excessive_topic_count(dispatcher):
    topics = [KAFKATopicInput(topic=f"Enterprise/PlantA/Area/Line/Device/Metric{i}") for i in range(101)]
    subscription = KAFKASubscription()
    with pytest.raises(ValueError, match="At most 100"):
        async for _message in subscription.get_kafka_messages(_admin_info(), topics):
            pass
