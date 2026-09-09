"""Durable rejection records for the historic event DLQ topic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DLQ_TOPIC = "uns.historic-events.dlq"
MAX_REJECTION_BYTES = 65_536
REJECTION_SCHEMA_VERSION = 1


class RejectionError(ValueError):
    """Bounded rejection encoding failure."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RejectionRecord:
    stage: str
    origin: str
    reason: str
    captured_at: datetime
    topic: str
    original_bytes: bytes
    event_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_at", _ensure_utc(self.captured_at))
        if len(self.original_bytes) > MAX_REJECTION_BYTES:
            raise RejectionError("oversize", "original_bytes exceeds DLQ capture limit")


def encode_rejection(record: RejectionRecord) -> bytes:
    wire = {
        "schema_version": REJECTION_SCHEMA_VERSION,
        "stage": record.stage,
        "origin": record.origin,
        "reason": record.reason,
        "captured_at": _format_time(record.captured_at),
        "topic": record.topic,
        "event_id": record.event_id,
        "original_base64": _encode_bytes(record.original_bytes),
    }
    encoded = json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REJECTION_BYTES:
        raise RejectionError("oversize")
    return encoded


def decode_rejection(data: bytes) -> RejectionRecord:
    if len(data) > MAX_REJECTION_BYTES:
        raise RejectionError("oversize")
    parsed = json.loads(data.decode("utf-8"))
    if parsed.get("schema_version") != REJECTION_SCHEMA_VERSION:
        raise RejectionError("unsupported_schema")
    return RejectionRecord(
        stage=parsed["stage"],
        origin=parsed["origin"],
        reason=parsed["reason"],
        captured_at=_parse_time(parsed["captured_at"]),
        topic=parsed["topic"],
        original_bytes=_decode_bytes(parsed["original_base64"]),
        event_id=parsed.get("event_id"),
    )


def rejection_key(record: RejectionRecord) -> bytes:
    parts = [record.origin, record.stage, record.reason, record.topic, _format_time(record.captured_at)]
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise RejectionError("invalid_field", "captured_at must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RejectionError("invalid_field", "captured_at")
    return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _format_time(value: datetime) -> str:
    return _ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _encode_bytes(value: bytes) -> str:
    import base64

    return base64.b64encode(value).decode("ascii")


def _decode_bytes(value: Any) -> bytes:
    import base64

    if not isinstance(value, str):
        raise RejectionError("invalid_field", "original_base64")
    return base64.b64decode(value, validate=True)
