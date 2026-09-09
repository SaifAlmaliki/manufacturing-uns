"""Failure-contract tests for bounded ingestion and manual MQTT acknowledgment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from uns_kafka.ingest import (
    HISTORIC_TOPIC,
    IngestionConfig,
    IngestionOwner,
    OwnershipMapping,
    ReceiptToken,
    validate_ownership_mappings,
    validate_shard_client_id,
)
from uns_kafka.rejections import DLQ_TOPIC


class FakeMqttAck:
    def __init__(self) -> None:
        self.acks: list[ReceiptToken] = []

    def ack(self, token: ReceiptToken) -> None:
        self.acks.append(token)


class FakePublisher:
    def __init__(self, *, fail_buffer: bool = False, fail_delivery: bool = False) -> None:
        self.fail_buffer = fail_buffer
        self.fail_delivery = fail_delivery
        self.calls: list[tuple[str, bytes | None, bytes]] = []
        self._callbacks: list = []

    def publish_event(self, topic, key, value, on_delivery) -> None:
        if self.fail_buffer:
            raise BufferError("queue full")
        self.calls.append((topic, key, value))
        self._callbacks.append(on_delivery)

    def complete_next(self, *, success: bool = True) -> None:
        callback = self._callbacks.pop(0)
        if success and not self.fail_delivery:
            callback(None, object())
        else:
            callback(RuntimeError("delivery failed"), None)


def _config(**overrides) -> IngestionConfig:
    defaults = {
        "shard_id": "shard-a",
        "client_id": "uns_kafka_ingest-shard-a",
        "ownership_mappings": (OwnershipMapping("plant-a", "plant-a/ingress", ""),),
    }
    defaults.update(overrides)
    return IngestionConfig(**defaults)


def _owner(**overrides) -> tuple[IngestionOwner, FakeMqttAck, FakePublisher, FakePublisher]:
    mqtt = FakeMqttAck()
    events = FakePublisher()
    dlq = FakePublisher()
    owner = IngestionOwner(
        config=_config(),
        mqtt=mqtt,
        events=events,
        dlq=dlq,
        clock=lambda: datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        sleep=lambda _seconds: None,
    )
    return owner, mqtt, events, dlq


def _token(generation: int = 1, packet_id: int = 7) -> ReceiptToken:
    return ReceiptToken(connection_generation=generation, packet_id=packet_id, qos=1)


def _payload(message: str = "hello") -> tuple[bytes, dict[str, Any]]:
    body = {"value": message, "timestamp": 1_788_948_000}
    encoded = json.dumps(body).encode("utf-8")
    return encoded, body


def test_qos1_enqueue_does_not_ack_until_kafka_success():
    owner, mqtt, events, _dlq = _owner()
    raw, decoded = _payload()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Device/Temperature", raw, decoded)
    assert mqtt.acks == []
    assert len(events.calls) == 1
    assert events.calls[0][0] == HISTORIC_TOPIC
    events.complete_next(success=True)
    assert mqtt.acks == [_token()]


def test_kafka_delivery_failure_leaves_message_unacked_and_not_ready():
    owner, mqtt, events, _dlq = _owner()
    raw, decoded = _payload()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Device/Temperature", raw, decoded)
    events.complete_next(success=False)
    assert mqtt.acks == []
    assert owner.ready is False
    assert owner.disconnect_requested is True


def test_reconnect_stale_delivery_success_does_not_ack_new_generation():
    owner, mqtt, events, _dlq = _owner()
    raw, decoded = _payload()
    owner.ingest_qos1(_token(generation=1), "Enterprise/PlantA/Device/Temperature", raw, decoded)
    owner.on_reconnect()
    events.complete_next(success=True)
    assert mqtt.acks == []


def test_pending_budget_overflow_does_not_ack_or_enqueue():
    mqtt = FakeMqttAck()
    events = FakePublisher()
    dlq = FakePublisher()
    owner = IngestionOwner(
        config=_config(pending_record_limit=0),
        mqtt=mqtt,
        events=events,
        dlq=dlq,
        clock=lambda: datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        sleep=lambda _seconds: None,
    )
    raw, decoded = _payload()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Device/Temperature", raw, decoded)
    assert mqtt.acks == []
    assert events.calls == []
    assert owner.ready is False


def test_invalid_json_routes_to_dlq_and_acks_on_success():
    owner, mqtt, _events, dlq = _owner()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Device/Temperature", b"{", None)
    assert dlq.calls
    assert dlq.calls[0][0] == DLQ_TOPIC
    dlq.complete_next(success=True)
    assert mqtt.acks == [_token()]


def test_invalid_json_dlq_failure_does_not_ack():
    owner, mqtt, _events, dlq = _owner()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Device/Temperature", b"{", None)
    dlq.complete_next(success=False)
    assert mqtt.acks == []


def test_qos0_is_best_effort_without_manual_ack():
    owner, mqtt, events, _dlq = _owner()
    raw, decoded = _payload()
    owner.ingest_qos0("Enterprise/PlantA/Device/Temperature", raw, decoded)
    assert mqtt.acks == []
    assert owner.qos0_delivered == 1
    assert events.calls


def test_buffer_error_on_publish_marks_backpressure_without_ack():
    owner, mqtt, events, _dlq = _owner()
    events.fail_buffer = True
    raw, decoded = _payload()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Device/Temperature", raw, decoded)
    assert mqtt.acks == []
    assert owner.ready is False


def test_ownership_validation_rejects_duplicate_prefixes():
    mappings = (
        OwnershipMapping("a", "a/ingress", "Site/"),
        OwnershipMapping("b", "b/ingress", "Site/"),
    )
    with pytest.raises(ValueError, match="unique"):
        validate_ownership_mappings(mappings)


def test_shard_client_id_must_be_stable():
    with pytest.raises(ValueError, match="stable"):
        validate_shard_client_id("uns_kafka_listener-123")
