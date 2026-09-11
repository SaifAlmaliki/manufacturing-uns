"""Contract tests for the v2 byte-preserving historic event envelope."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from uns_config.events import (
    EnvelopeError,
    HistoricEventEnvelope,
    decode_event,
    encode_event,
    immutable_content_hash,
    source_event_id,
)


@pytest.fixture
def v2_event():
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)

    def _factory(**overrides) -> HistoricEventEnvelope:
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

    return _factory


@pytest.mark.parametrize(
    "body",
    [
        b'{ "timestamp": "2026-09-11T09:00:00Z", "result": 4.2 }',
        b'[1, {"a": true}]',
        b'"released"',
        b"\x00\xff",
        b"",
    ],
)
def test_v2_preserves_body_without_timestamp_normalization(v2_event, body):
    event = v2_event(original_payload=body)
    decoded = decode_event(encode_event(event))
    assert decoded.original_payload == body
    assert decoded.payload_schema_version == "1"
    assert decoded.schema_version == 2


def test_v2_round_trip_matches_envelope(v2_event):
    envelope = v2_event()
    restored = decode_event(encode_event(envelope))
    assert restored == envelope


def test_v2_wire_uses_original_payload_base64(v2_event):
    body = b'{ "timestamp": "2026-09-11T09:00:00Z" }'
    wire = json.loads(encode_event(v2_event(original_payload=body)))
    assert wire["original_payload_base64"] == base64.b64encode(body).decode("ascii")
    assert "raw_payload_base64" not in wire or wire.get("raw_payload_base64") is None


def test_v2_payload_dict_is_not_normalized(v2_event):
    payload = {"timestamp": "2026-09-11T09:00:00Z", "value": 1}
    envelope = v2_event(payload=payload, original_payload=b"{}")
    restored = decode_event(encode_event(envelope))
    assert restored.payload == payload


def test_v2_immutable_content_hash_ignores_received_at(v2_event):
    base = v2_event()
    shifted = v2_event(received_at=datetime(2026, 9, 9, 10, 5, 0, tzinfo=UTC))
    assert immutable_content_hash(base) == immutable_content_hash(shifted)


def test_v2_immutable_content_hash_detects_body_and_route_changes(v2_event):
    base = v2_event()
    changed_body = v2_event(original_payload=b'{"result": 9.9}')
    changed_route = v2_event(payload_schema_id="production-order")
    base_hash = immutable_content_hash(base)
    assert immutable_content_hash(changed_body) != base_hash
    assert immutable_content_hash(changed_route) != base_hash


@pytest.mark.parametrize("event_kind", ["business_event", "state_snapshot"])
def test_v2_accepts_new_event_kinds(v2_event, event_kind):
    envelope = v2_event(event_kind=event_kind)
    restored = decode_event(encode_event(envelope))
    assert restored.event_kind == event_kind


def test_v2_rejects_unknown_event_kind(v2_event):
    envelope = v2_event(event_kind="not_a_kind")
    with pytest.raises(EnvelopeError, match="invalid_field"):
        encode_event(envelope)


@pytest.mark.parametrize(
    "field_name",
    [
        "source_application",
        "payload_schema_id",
        "payload_schema_version",
        "content_type",
        "original_payload",
        "archive_eligible",
    ],
)
def test_v2_rejects_missing_required_field(v2_event, field_name):
    envelope = v2_event(**{field_name: None})
    with pytest.raises(EnvelopeError, match="missing_field|invalid_field"):
        encode_event(envelope)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("source_application", 42),
        ("payload_schema_id", ["lab-result"]),
        ("payload_schema_version", True),
        ("content_type", 1),
        ("original_payload", "not-bytes"),
        ("archive_eligible", "yes"),
        ("payload", "not-a-dict"),
    ],
)
def test_v2_rejects_invalid_field_types(v2_event, field_name, value):
    envelope = v2_event(**{field_name: value})
    with pytest.raises((EnvelopeError, TypeError)):
        encode_event(envelope)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "lims/evil",
        "../escape",
        "a" * 129,
        "",
    ],
)
def test_v2_rejects_unsafe_route_ids(v2_event, unsafe_value):
    envelope = v2_event(source_application=unsafe_value)
    with pytest.raises(EnvelopeError, match="invalid_field"):
        encode_event(envelope)


def test_v2_rejects_partial_source_identity(v2_event):
    envelope = v2_event(source_boot_id=None, source_sequence=None)
    with pytest.raises(EnvelopeError, match="invalid_identity"):
        encode_event(envelope)


def test_v2_rejects_invalid_base64_on_decode(v2_event):
    wire = json.loads(encode_event(v2_event()))
    wire["original_payload_base64"] = "not!!!valid"
    with pytest.raises(EnvelopeError, match="invalid_field"):
        decode_event(json.dumps(wire).encode("utf-8"))


def test_v2_rejects_raw_payload_base64(v2_event):
    envelope = v2_event(raw_payload_base64="cGF5bG9hZA==")
    with pytest.raises(EnvelopeError, match="invalid_field"):
        encode_event(envelope)


def test_v2_encode_rejects_oversize_envelope(v2_event):
    huge = b"x" * (1024 * 1024)
    envelope = v2_event(original_payload=huge)
    with pytest.raises(EnvelopeError, match="oversize"):
        encode_event(envelope)


def test_v2_accepts_empty_original_payload(v2_event):
    envelope = v2_event(original_payload=b"")
    restored = decode_event(encode_event(envelope))
    assert restored.original_payload == b""


def test_decode_rejects_unsupported_v2_schema_version(v2_event):
    wire = encode_event(v2_event())
    payload = json.loads(wire)
    payload["schema_version"] = 99
    with pytest.raises(EnvelopeError, match="unsupported_schema"):
        decode_event(json.dumps(payload).encode("utf-8"))


def test_v1_envelope_unchanged_serialization_and_hash():
    from test_events import _source_envelope

    envelope = _source_envelope()
    wire = encode_event(envelope)
    payload = json.loads(wire)
    assert payload["schema_version"] == 1
    assert "original_payload_base64" not in payload
    assert "source_application" not in payload
    expected_hash = immutable_content_hash(envelope)
    assert immutable_content_hash(decode_event(wire)) == expected_hash
