"""Tests for v2 envelope compatibility in the GraphQL live event stream."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from uns_config.events import HistoricEventEnvelope, encode_event, source_event_id

from uns_graphql.auth.scope import AccessScope
from uns_graphql.backend import event_stream as event_stream_module
from uns_graphql.backend.event_stream import (
    LiveEventDispatcher,
    envelope_to_dispatched,
    reset_dispatcher_for_tests,
)
from uns_graphql.type.streaming_event import StreamingMessage


def _v2_business_event(**overrides) -> HistoricEventEnvelope:
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 2,
        "event_id": source_event_id("plant-01", "plant-a/lims-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/lims-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-01",
        "time": time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/LIMS/results",
        "event_kind": "business_event",
        "is_historical": False,
        "payload": {},
        "raw_payload_base64": None,
        "source_application": "lims",
        "payload_schema_id": "lab-result",
        "payload_schema_version": "1",
        "content_type": "application/json",
        "original_payload": b'{"result": 4.2}',
        "archive_eligible": True,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


def _v2_telemetry(**overrides) -> HistoricEventEnvelope:
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 2,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"value": 42.0, "timestamp": 1_788_948_000_000},
        "raw_payload_base64": None,
        "source_application": "machine",
        "payload_schema_id": "temperature",
        "payload_schema_version": "1",
        "content_type": "application/json",
        "original_payload": b'{"value": 42.0, "timestamp": 1788948000000}',
        "archive_eligible": True,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


def _v1_telemetry(**overrides) -> HistoricEventEnvelope:
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 1,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": time,
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


def _admin_scope() -> AccessScope:
    return AccessScope(unrestricted=True, root_paths=frozenset())


@pytest.fixture
def v2_business_event():
    return _v2_business_event()


def test_business_event_is_not_metric_input(v2_business_event):
    from uns_config.event_compatibility import as_legacy_telemetry

    assert as_legacy_telemetry(v2_business_event) is None


def test_envelope_to_dispatched_ignores_business_event():
    assert envelope_to_dispatched(encode_event(_v2_business_event())) is None


def test_envelope_to_dispatched_accepts_v2_telemetry():
    envelope = _v2_telemetry()
    dispatched = envelope_to_dispatched(encode_event(envelope))
    assert dispatched is not None
    assert dispatched.event_id == envelope.event_id
    assert dispatched.topic == envelope.topic
    payload = json.loads(dispatched.payload_json.decode("utf-8"))
    assert payload["value"] == envelope.payload["value"]
    assert payload["timestamp"] == 1_788_948_000


def test_envelope_to_dispatched_accepts_v1_telemetry():
    envelope = _v1_telemetry()
    dispatched = envelope_to_dispatched(encode_event(envelope))
    assert dispatched is not None
    assert dispatched.event_id == envelope.event_id


@pytest_asyncio.fixture(loop_scope="function")
async def live_dispatcher_fixture():
    reset_dispatcher_for_tests()
    loop = asyncio.get_running_loop()
    fake_consumer = FakeConsumer()
    live_dispatcher = LiveEventDispatcher(loop=loop, consumer=fake_consumer, max_clients=200)
    await live_dispatcher.start()
    event_stream_module._dispatcher = live_dispatcher
    yield live_dispatcher, fake_consumer
    await live_dispatcher.stop()
    reset_dispatcher_for_tests()


@pytest.mark.asyncio
async def test_live_stream_ignores_business_but_broadcasts_telemetry(live_dispatcher_fixture):
    live_dispatcher, _fake_consumer = live_dispatcher_fixture
    topic = "Enterprise/PlantA/Area/Line/Device/Temperature"
    stream = live_dispatcher.subscribe([topic], _admin_scope(), None)
    subscription = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    business = envelope_to_dispatched(encode_event(_v2_business_event(topic=topic)))
    assert business is None

    telemetry = envelope_to_dispatched(encode_event(_v2_telemetry(topic=topic)))
    assert telemetry is not None
    live_dispatcher._fan_out(telemetry)

    message = await asyncio.wait_for(subscription, timeout=1)
    assert isinstance(message, StreamingMessage)
    assert message.event_id == telemetry.event_id


@pytest.mark.asyncio
async def test_business_event_does_not_reach_subscribed_clients(live_dispatcher_fixture):
    live_dispatcher, _fake_consumer = live_dispatcher_fixture
    topic = "Enterprise/PlantA/LIMS/results"
    stream = live_dispatcher.subscribe([topic], _admin_scope(), None)
    subscription = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    dispatched = envelope_to_dispatched(encode_event(_v2_business_event(topic=topic)))
    assert dispatched is None

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(subscription, timeout=0.2)


@pytest.mark.asyncio
async def test_unauthorized_v2_telemetry_still_filtered(live_dispatcher_fixture):
    live_dispatcher, _fake_consumer = live_dispatcher_fixture
    topic = "Enterprise/PlantA/Area/Line/Device/Temperature"
    restricted_scope = AccessScope(unrestricted=False, root_paths=frozenset({"Enterprise/PlantA"}))
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=None)

    with patch("uns_graphql.backend.event_stream.allowed_topic", new=AsyncMock(return_value=False)):
        stream = live_dispatcher.subscribe([topic], restricted_scope, resolver)
        subscription = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)

        telemetry = envelope_to_dispatched(encode_event(_v2_telemetry(topic=topic)))
        assert telemetry is not None
        live_dispatcher._fan_out(telemetry)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(subscription, timeout=0.2)
