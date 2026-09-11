"""Publication-route ingestion with durable Kafka delivery and manual MQTT ACK."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from uns_config.events import decode_event
from uns_config.publication_routes import PublicationRoute, SchemaPair
from uns_kafka.ingest import (
    HISTORIC_TOPIC,
    IngestionConfig,
    IngestionOwner,
    OwnershipMapping,
    ReceiptToken,
)
from uns_kafka.rejections import DLQ_TOPIC


class FakeMqttAck:
    def __init__(self) -> None:
        self.acks: list[ReceiptToken] = []

    def ack(self, token: ReceiptToken) -> None:
        self.acks.append(token)


class FakePublisher:
    def __init__(self, *, fail_buffer: bool = False) -> None:
        self.fail_buffer = fail_buffer
        self.calls: list[tuple[str, bytes | None, bytes]] = []
        self._callbacks: list = []

    def publish_event(self, topic, key, value, on_delivery) -> None:
        if self.fail_buffer:
            raise BufferError("queue full")
        self.calls.append((topic, key, value))
        self._callbacks.append(on_delivery)

    def complete_next(self, *, success: bool = True) -> None:
        callback = self._callbacks.pop(0)
        if success:
            callback(None, object())
        else:
            callback(RuntimeError("delivery failed"), None)


def _lims_route(**overrides) -> PublicationRoute:
    defaults = {
        "topic_filter": "Enterprise/PlantA/LIMS/results",
        "source_id": "plant-a/lims-01",
        "source_application": "lims",
        "site_id": "plant-01",
        "wire_format": "uns-publication-v1",
        "allowed_schema_pairs": frozenset(
            {SchemaPair(payload_schema_id="lab-result", payload_schema_version="1")}
        ),
        "default_schema_pair": None,
        "content_type": "application/json",
        "event_kind": "business_event",
        "archive_eligible": True,
    }
    defaults.update(overrides)
    return PublicationRoute(**defaults)


def _raw_route(**overrides) -> PublicationRoute:
    defaults = {
        "topic_filter": "Enterprise/PlantA/MES/orders",
        "source_id": "plant-a/mes-01",
        "source_application": "mes",
        "site_id": "plant-01",
        "wire_format": "raw",
        "allowed_schema_pairs": frozenset(
            {SchemaPair(payload_schema_id="production-order", payload_schema_version="1")}
        ),
        "default_schema_pair": SchemaPair(
            payload_schema_id="production-order",
            payload_schema_version="1",
        ),
        "content_type": "application/json",
        "event_kind": "business_event",
        "archive_eligible": True,
    }
    defaults.update(overrides)
    return PublicationRoute(**defaults)


def _config(**overrides) -> IngestionConfig:
    defaults = {
        "shard_id": "shard-a",
        "client_id": "uns_kafka_ingest-shard-a",
        "ownership_mappings": (OwnershipMapping("plant-a", "plant-a/ingress", "Enterprise/PlantA/Device/"),),
        "publication_routes": (_lims_route(), _raw_route()),
        "v2_publications_enabled": True,
    }
    defaults.update(overrides)
    return IngestionConfig(**defaults)


def _owner(**config_overrides) -> tuple[IngestionOwner, FakeMqttAck, FakePublisher, FakePublisher]:
    mqtt = FakeMqttAck()
    events = FakePublisher()
    dlq = FakePublisher()
    owner = IngestionOwner(
        config=_config(**config_overrides),
        mqtt=mqtt,
        events=events,
        dlq=dlq,
        clock=lambda: datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        sleep=lambda _seconds: None,
    )
    return owner, mqtt, events, dlq


def _token(generation: int = 1, packet_id: int = 7) -> ReceiptToken:
    return ReceiptToken(connection_generation=generation, packet_id=packet_id, qos=1)


def _wrapper_bytes(**overrides) -> bytes:
    payload = {
        "publication_version": 1,
        "source_application": "lims",
        "site_id": "plant-01",
        "payload_schema_id": "lab-result",
        "payload_schema_version": "1",
        "content_type": "application/json",
        "original_payload_base64": base64.b64encode(b'{"result": 4.2}').decode("ascii"),
        "occurred_at": "2026-09-11T09:00:00Z",
        "source_boot_id": "lims-session-1",
        "source_sequence": 42,
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def test_wrapped_lims_queues_v2_bytes_without_ack_until_kafka_success():
    owner, mqtt, events, _dlq = _owner()
    owner.ingest_qos1(
        _token(),
        "Enterprise/PlantA/LIMS/results",
        _wrapper_bytes(),
        None,
    )
    assert mqtt.acks == []
    assert len(events.calls) == 1
    assert events.calls[0][0] == HISTORIC_TOPIC
    envelope = decode_event(events.calls[0][2])
    assert envelope.schema_version == 2
    assert envelope.source_application == "lims"
    assert envelope.original_payload == b'{"result": 4.2}'
    events.complete_next(success=True)
    assert mqtt.acks == [_token()]


def test_kafka_delivery_failure_and_stale_generation_do_not_ack():
    owner, mqtt, events, _dlq = _owner()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/LIMS/results", _wrapper_bytes(), None)
    events.complete_next(success=False)
    assert mqtt.acks == []
    assert owner.ready is False

    owner.ready = True
    owner.disconnect_requested = False
    owner.ingest_qos1(_token(generation=1), "Enterprise/PlantA/LIMS/results", _wrapper_bytes(), None)
    owner.on_reconnect()
    events.complete_next(success=True)
    assert mqtt.acks == []


def test_forged_metadata_routes_to_dlq_and_acks_only_after_dlq_success():
    owner, mqtt, _events, dlq = _owner()
    owner.ingest_qos1(
        _token(),
        "Enterprise/PlantA/LIMS/results",
        _wrapper_bytes(source_application="mes"),
        None,
    )
    assert dlq.calls
    assert dlq.calls[0][0] == DLQ_TOPIC
    dlq.complete_next(success=True)
    assert mqtt.acks == [_token()]


def test_unknown_ownership_routes_to_dlq():
    owner, mqtt, events, dlq = _owner(
        ownership_mappings=(),
        publication_routes=(_lims_route(),),
        v2_publications_enabled=True,
    )
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Unknown/topic", b"{}", None)
    assert events.calls == []
    assert dlq.calls
    dlq.complete_next(success=True)
    assert mqtt.acks == [_token()]


@pytest.mark.parametrize(
    "body",
    [
        b'[1, {"a": true}]',
        b'"released"',
        b"\x00\xff",
    ],
)
def test_raw_business_body_accepted_without_dict_decode(body: bytes):
    owner, mqtt, events, _dlq = _owner()
    owner.ingest_qos1(_token(), "Enterprise/PlantA/MES/orders", body, None)
    assert mqtt.acks == []
    envelope = decode_event(events.calls[0][2])
    assert envelope.schema_version == 2
    assert envelope.original_payload == body
    events.complete_next(success=True)
    assert mqtt.acks == [_token()]


def test_equal_raw_bodies_without_source_identity_get_distinct_ingress_ids():
    owner, _mqtt, events, _dlq = _owner()
    body = b'{"sku":"ABC"}'
    owner.ingest_qos1(_token(packet_id=1), "Enterprise/PlantA/MES/orders", body, None)
    owner.ingest_qos1(_token(packet_id=2), "Enterprise/PlantA/MES/orders", body, None)
    first = decode_event(events.calls[0][2])
    second = decode_event(events.calls[1][2])
    assert first.event_id != second.event_id
    assert first.event_id.startswith("ingress:")
    assert second.event_id.startswith("ingress:")


def test_v2_disabled_keeps_legacy_v1_ownership_path():
    owner, mqtt, events, _dlq = _owner(v2_publications_enabled=False)
    decoded: dict[str, Any] = {"value": 1, "timestamp": 1_788_948_000}
    raw = json.dumps(decoded).encode("utf-8")
    owner.ingest_qos1(_token(), "Enterprise/PlantA/Device/Temperature", raw, decoded)
    envelope = decode_event(events.calls[0][2])
    assert envelope.schema_version == 1
    events.complete_next(success=True)
    assert mqtt.acks == [_token()]
