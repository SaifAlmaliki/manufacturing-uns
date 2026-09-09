"""Contract tests for the canonical historic event envelope."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime

import pytest

from uns_config.events import (
    EnvelopeError,
    HistoricEventEnvelope,
    decode_event,
    encode_event,
    event_key,
    immutable_content_hash,
    ingress_event_id,
    source_event_id,
)
from uns_config.uns_ingest import PLATFORM_OBSERVABILITY_PREFIX


def _source_envelope(**overrides) -> HistoricEventEnvelope:
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


def test_round_trip_json_matches_design_example_fields():
    envelope = _source_envelope()
    restored = decode_event(encode_event(envelope))
    assert restored == envelope


def test_source_event_id_is_stable_and_collision_free():
    first = source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42)
    second = source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42)
    different = source_event_id("plant-a", "plant-a/gateway-01", "boot-18", 42)
    assert first == second
    assert first.startswith("source:")
    assert first != different


def test_ingress_event_id_is_frozen_per_receipt():
    receipt = uuid.UUID("11111111-2222-4333-8444-555555555555")
    first = ingress_event_id(receipt)
    second = ingress_event_id(receipt)
    other = ingress_event_id(uuid.uuid4())
    assert first == second
    assert first == "ingress:11111111-2222-4333-8444-555555555555"
    assert first != other


def test_two_legacy_receipts_with_equal_payloads_get_distinct_ingress_ids():
    receipt_a = uuid.uuid4()
    receipt_b = uuid.uuid4()
    shared = {
        "identity_quality": "ingress",
        "source_id": "plant-a/legacy-mqtt",
        "source_boot_id": None,
        "source_sequence": None,
        "site_id": "plant-a",
        "time": datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        "received_at": datetime(2026, 9, 9, 10, 0, 0, 5000, tzinfo=UTC),
        "timestamp_quality": "ingress",
        "topic": "Enterprise/PlantA/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"value": 21.4},
        "raw_payload_base64": None,
    }
    envelope_a = HistoricEventEnvelope(
        schema_version=1,
        event_id=ingress_event_id(receipt_a),
        **shared,
    )
    envelope_b = HistoricEventEnvelope(
        schema_version=1,
        event_id=ingress_event_id(receipt_b),
        **shared,
    )
    assert envelope_a.event_id != envelope_b.event_id
    assert decode_event(encode_event(envelope_a)).event_id == envelope_a.event_id


def test_immutable_content_hash_ignores_received_at():
    base = _source_envelope()
    shifted = _source_envelope(
        received_at=datetime(2026, 9, 9, 10, 5, 0, tzinfo=UTC),
    )
    assert immutable_content_hash(base) == immutable_content_hash(shifted)


def test_immutable_content_hash_detects_payload_topic_and_time_changes():
    base = _source_envelope()
    changed_payload = _source_envelope(payload={"value": 99.0})
    changed_topic = _source_envelope(topic="Enterprise/PlantA/Other")
    changed_time = _source_envelope(time=datetime(2026, 9, 9, 11, 0, 0, tzinfo=UTC))
    base_hash = immutable_content_hash(base)
    assert immutable_content_hash(changed_payload) != base_hash
    assert immutable_content_hash(changed_topic) != base_hash
    assert immutable_content_hash(changed_time) != base_hash


def test_event_key_uses_mqtt_topic_for_uns_events():
    envelope = _source_envelope()
    assert event_key(envelope) == json.dumps(
        ["plant-a", "mqtt", envelope.topic],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_event_key_uses_sparkplug_tuple_for_transport_topics():
    envelope = _source_envelope(
        topic="spBv1.0/uns_group/NDATA/eon1",
        event_kind="sparkplug_raw",
        raw_payload_base64="cGF5bG9hZA==",
    )
    assert event_key(envelope) == json.dumps(
        ["plant-a", "sparkplug", "uns_group", "eon1"],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_event_key_uses_host_scoped_state_key():
    envelope = _source_envelope(
        topic="spBv1.0/STATE/scada_1",
        event_kind="lifecycle",
        payload={"online": True},
    )
    assert event_key(envelope) == json.dumps(
        ["plant-a", "sparkplug", "STATE", "scada_1"],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_decode_rejects_unsupported_schema_version():
    wire = encode_event(_source_envelope())
    payload = json.loads(wire)
    payload["schema_version"] = 99
    with pytest.raises(EnvelopeError, match="unsupported_schema"):
        decode_event(json.dumps(payload).encode("utf-8"))


def test_decode_rejects_missing_required_field():
    wire = encode_event(_source_envelope())
    payload = json.loads(wire)
    del payload["topic"]
    with pytest.raises(EnvelopeError, match="missing_field"):
        decode_event(json.dumps(payload).encode("utf-8"))


def test_decode_rejects_invalid_json():
    with pytest.raises(EnvelopeError, match="invalid_json"):
        decode_event(b"{")


def test_decode_rejects_platform_observability_topic():
    envelope = _source_envelope(topic=f"{PLATFORM_OBSERVABILITY_PREFIX}simulator/status")
    with pytest.raises(EnvelopeError, match="platform_topic"):
        encode_event(envelope)


def test_decode_accepts_timezone_offsets_and_normalizes_to_utc():
    envelope = _source_envelope(
        time=datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC),
    )
    wire = encode_event(envelope)
    payload = json.loads(wire)
    payload["time"] = "2026-09-09T14:00:00+02:00"
    payload["received_at"] = "2026-09-09T14:00:00.010000+02:00"
    restored = decode_event(json.dumps(payload).encode("utf-8"))
    assert restored.time == datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    assert restored.received_at == datetime(2026, 9, 9, 12, 0, 0, 10000, tzinfo=UTC)


@pytest.mark.parametrize(
    ("timestamp_value", "expected_seconds"),
    [
        (1_788_948_000, 1_788_948_000),
        (1_788_948_000_000, 1_788_948_000),
    ],
)
def test_payload_timestamp_seconds_and_milliseconds_normalization(
    timestamp_value: int,
    expected_seconds: int,
):
    envelope = _source_envelope(payload={"value": 1.0, "timestamp": timestamp_value})
    wire = encode_event(envelope)
    payload = json.loads(wire)
    assert payload["payload"]["timestamp"] == expected_seconds


@pytest.mark.parametrize("bad_timestamp", [True, False, math.nan, math.inf, -math.inf])
def test_payload_timestamp_rejects_non_numeric_source_timestamps(bad_timestamp):
    with pytest.raises(EnvelopeError, match="invalid_timestamp"):
        _source_envelope(payload={"value": 1.0, "timestamp": bad_timestamp})


def test_encode_rejects_oversize_envelope():
    huge = "x" * (1024 * 1024)
    envelope = _source_envelope(payload={"blob": huge})
    with pytest.raises(EnvelopeError, match="oversize"):
        encode_event(envelope)


def test_encode_accepts_envelope_at_one_mib_boundary():
    pad = "a" * (1024 * 1024 - 512)
    wire = encode_event(_source_envelope(payload={"value": 1.0, "pad": pad}))
    assert len(wire) <= 1024 * 1024
    with pytest.raises(EnvelopeError, match="oversize"):
        encode_event(_source_envelope(payload={"value": 1.0, "pad": pad + ("b" * 2048)}))


def test_ingress_identity_accepts_generated_uuid_without_boot_sequence():
    receipt = uuid.uuid4()
    envelope = HistoricEventEnvelope(
        schema_version=1,
        event_id=ingress_event_id(receipt),
        identity_quality="ingress",
        source_id="plant-a/legacy-mqtt",
        source_boot_id=None,
        source_sequence=None,
        site_id="plant-a",
        time=datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 9, 9, 10, 0, 0, 5000, tzinfo=UTC),
        timestamp_quality="ingress",
        topic="Enterprise/PlantA/Device/Temperature",
        event_kind="telemetry",
        is_historical=False,
        payload={"value": 21.4},
        raw_payload_base64=None,
    )
    restored = decode_event(encode_event(envelope))
    assert restored.identity_quality == "ingress"
    assert restored.source_boot_id is None
    assert restored.source_sequence is None


def test_source_identity_requires_boot_and_sequence():
    envelope = _source_envelope(source_boot_id=None, source_sequence=None)
    with pytest.raises(EnvelopeError, match="invalid_identity"):
        encode_event(envelope)
