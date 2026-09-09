"""Canonical historic event envelope and identity helpers.

Pure contract code: no Kafka, MQTT, database, or cloud SDK imports.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from uns_config.uns_ingest import is_historic_event_topic

MAX_ENVELOPE_BYTES = 1_048_576
SUPPORTED_SCHEMA_VERSION = 1
_LEGACY_SECONDS_THRESHOLD = 100_000_000_000

IdentityQuality = Literal["source", "ingress"]
TimestampQuality = Literal["source", "ingress"]
EventKind = Literal["telemetry", "sparkplug_raw", "lifecycle", "command"]

_EVENT_KINDS: frozenset[str] = frozenset({"telemetry", "sparkplug_raw", "lifecycle", "command"})
_IDENTITY_QUALITIES: frozenset[str] = frozenset({"source", "ingress"})
_TIMESTAMP_QUALITIES: frozenset[str] = frozenset({"source", "ingress"})

_SOURCE_ID_PATTERN = re.compile(r"^source:[0-9a-f]{64}$")
_INGRESS_ID_PATTERN = re.compile(
    r"^ingress:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class EnvelopeError(ValueError):
    """Bounded contract failure with a stable reason code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


def tuple_digest(parts: tuple[Any, ...]) -> str:
    wire = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


def source_event_id(
    site_id: str,
    source_id: str,
    source_boot_id: str,
    source_sequence: int,
) -> str:
    digest = tuple_digest((site_id, source_id, source_boot_id, source_sequence))
    return f"source:{digest}"


def ingress_event_id(receipt_uuid: UUID) -> str:
    return f"ingress:{receipt_uuid}"


@dataclass(frozen=True, slots=True)
class HistoricEventEnvelope:
    schema_version: int
    event_id: str
    identity_quality: IdentityQuality
    source_id: str
    source_boot_id: str | None
    source_sequence: int | None
    site_id: str
    time: datetime
    received_at: datetime
    timestamp_quality: TimestampQuality
    topic: str
    event_kind: EventKind
    is_historical: bool
    payload: dict[str, Any]
    raw_payload_base64: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "time", _ensure_utc(self.time))
        object.__setattr__(self, "received_at", _ensure_utc(self.received_at))
        object.__setattr__(self, "payload", normalize_payload_timestamps(self.payload))


def normalize_payload_timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    if "timestamp" not in payload:
        return payload
    normalized = dict(payload)
    normalized["timestamp"] = normalize_legacy_timestamp_value(payload["timestamp"])
    return normalized


def normalize_legacy_timestamp_value(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EnvelopeError("invalid_timestamp", "payload.timestamp must be numeric")
    if not math.isfinite(value):
        raise EnvelopeError("invalid_timestamp", "payload.timestamp must be finite")
    numeric = float(value)
    if abs(numeric) >= _LEGACY_SECONDS_THRESHOLD:
        numeric /= 1000.0
    return int(numeric)


def immutable_content_hash(envelope: HistoricEventEnvelope) -> str:
    parts = (
        envelope.schema_version,
        envelope.event_id,
        envelope.identity_quality,
        envelope.source_id,
        envelope.source_boot_id,
        envelope.source_sequence,
        envelope.site_id,
        _format_time(envelope.time),
        envelope.timestamp_quality,
        envelope.topic,
        envelope.event_kind,
        envelope.is_historical,
        envelope.payload,
        envelope.raw_payload_base64,
    )
    return tuple_digest(parts)


def event_key(envelope: HistoricEventEnvelope) -> bytes:
    topic = envelope.topic
    if topic.startswith("spBv1.0/STATE/"):
        host_id = topic.split("/", 3)[2]
        key_parts = [envelope.site_id, "sparkplug", "STATE", host_id]
    elif topic.startswith("spBv1.0/"):
        parts = topic.split("/")
        if len(parts) < 4:
            raise EnvelopeError("invalid_field", "sparkplug topic is too short for partition key")
        key_parts = [envelope.site_id, "sparkplug", parts[1], parts[3]]
    else:
        key_parts = [envelope.site_id, "mqtt", topic]
    return json.dumps(key_parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def encode_event(envelope: HistoricEventEnvelope) -> bytes:
    _validate_envelope(envelope)
    wire = _envelope_to_dict(envelope)
    encoded = json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise EnvelopeError("oversize")
    return encoded


def decode_event(data: bytes) -> HistoricEventEnvelope:
    if len(data) > MAX_ENVELOPE_BYTES:
        raise EnvelopeError("oversize")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvelopeError("invalid_json") from exc
    if not isinstance(parsed, dict):
        raise EnvelopeError("invalid_json")
    envelope = _dict_to_envelope(parsed)
    _validate_envelope(envelope)
    return envelope


def _envelope_to_dict(envelope: HistoricEventEnvelope) -> dict[str, Any]:
    return {
        "schema_version": envelope.schema_version,
        "event_id": envelope.event_id,
        "identity_quality": envelope.identity_quality,
        "source_id": envelope.source_id,
        "source_boot_id": envelope.source_boot_id,
        "source_sequence": envelope.source_sequence,
        "site_id": envelope.site_id,
        "time": _format_time(envelope.time),
        "received_at": _format_time(envelope.received_at),
        "timestamp_quality": envelope.timestamp_quality,
        "topic": envelope.topic,
        "event_kind": envelope.event_kind,
        "is_historical": envelope.is_historical,
        "payload": envelope.payload,
        "raw_payload_base64": envelope.raw_payload_base64,
    }


def _dict_to_envelope(parsed: dict[str, Any]) -> HistoricEventEnvelope:
    required_fields = (
        "schema_version",
        "event_id",
        "identity_quality",
        "source_id",
        "site_id",
        "time",
        "received_at",
        "timestamp_quality",
        "topic",
        "event_kind",
        "is_historical",
        "payload",
    )
    for field in required_fields:
        if field not in parsed:
            raise EnvelopeError("missing_field", field)

    raw_payload_base64 = parsed.get("raw_payload_base64")
    if raw_payload_base64 is not None and not isinstance(raw_payload_base64, str):
        raise EnvelopeError("invalid_field", "raw_payload_base64")

    if not isinstance(parsed["payload"], dict):
        raise EnvelopeError("invalid_field", "payload")

    return HistoricEventEnvelope(
        schema_version=parsed["schema_version"],
        event_id=parsed["event_id"],
        identity_quality=parsed["identity_quality"],
        source_id=parsed["source_id"],
        source_boot_id=parsed.get("source_boot_id"),
        source_sequence=parsed.get("source_sequence"),
        site_id=parsed["site_id"],
        time=_parse_time(parsed["time"], "time"),
        received_at=_parse_time(parsed["received_at"], "received_at"),
        timestamp_quality=parsed["timestamp_quality"],
        topic=parsed["topic"],
        event_kind=parsed["event_kind"],
        is_historical=parsed["is_historical"],
        payload=parsed["payload"],
        raw_payload_base64=raw_payload_base64,
    )


def _validate_envelope(envelope: HistoricEventEnvelope) -> None:
    if envelope.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise EnvelopeError("unsupported_schema")

    if envelope.identity_quality not in _IDENTITY_QUALITIES:
        raise EnvelopeError("invalid_field", "identity_quality")
    if envelope.timestamp_quality not in _TIMESTAMP_QUALITIES:
        raise EnvelopeError("invalid_field", "timestamp_quality")
    if envelope.event_kind not in _EVENT_KINDS:
        raise EnvelopeError("invalid_field", "event_kind")

    if not envelope.site_id or not envelope.source_id or not envelope.topic:
        raise EnvelopeError("invalid_field", "site_id/source_id/topic")

    if not is_historic_event_topic(envelope.topic):
        raise EnvelopeError("platform_topic")

    if envelope.identity_quality == "source":
        if envelope.source_boot_id is None or envelope.source_sequence is None:
            raise EnvelopeError("invalid_identity")
        if not _SOURCE_ID_PATTERN.fullmatch(envelope.event_id):
            raise EnvelopeError("invalid_identity")
        expected = source_event_id(
            envelope.site_id,
            envelope.source_id,
            envelope.source_boot_id,
            envelope.source_sequence,
        )
        if envelope.event_id != expected:
            raise EnvelopeError("invalid_identity")
    else:
        if envelope.source_boot_id is not None or envelope.source_sequence is not None:
            raise EnvelopeError("invalid_identity")
        if not _INGRESS_ID_PATTERN.fullmatch(envelope.event_id):
            raise EnvelopeError("invalid_identity")

    if envelope.raw_payload_base64 is not None:
        try:
            base64.b64decode(envelope.raw_payload_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise EnvelopeError("invalid_field", "raw_payload_base64") from exc


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise EnvelopeError("invalid_field", "timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise EnvelopeError("invalid_field", field_name)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EnvelopeError("invalid_field", field_name) from exc
    return _ensure_utc(parsed)


def _format_time(value: datetime) -> str:
    utc_value = _ensure_utc(value)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
