"""Historic Event object-store port: layout, envelope JSON, fake store.

A Mapper later puts Parquet via S3 or ADLS. That Mapper reads Kafka envelope
topic uns.historic-events (MQTT topic in the value). Do not subscribe to MQTT here.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

ENVELOPE_TOPIC = "uns.historic-events"
HISTORIC_EVENT_COLUMNS = ("time", "topic", "payload")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HistoricEventRecord:
    time: datetime
    topic: str
    payload: dict[str, Any]


class ObjectStore(Protocol):
    def put(self, path: str, parquet_bytes: bytes) -> None: ...


class FakeObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, path: str, parquet_bytes: bytes) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(parquet_bytes)


def topic_safe(topic: str) -> str:
    return topic.replace("/", "_")


def new_flush_id(*, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex}"


def historic_event_object_path(*, event_time: datetime, topic: str, flush_id: str) -> str:
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    day = event_time.astimezone(UTC).date().isoformat()
    return f"dt={day}/{topic_safe(topic)}-{flush_id}.parquet"


def _to_iso8601_utc(raw: Any, *, now: datetime) -> str:
    def normalize(value: datetime) -> str:
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()

    try:
        if isinstance(raw, datetime):
            instant = raw
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("non-finite timestamp")
            instant = datetime.fromtimestamp(value / 1000 if abs(value) >= 1e11 else value, UTC)
        elif isinstance(raw, str) and raw:
            instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            if raw is not None:
                LOGGER.warning("Invalid source timestamp type; using mapper clock")
            instant = now
        return normalize(instant)
    except (ValueError, OverflowError, OSError):
        LOGGER.warning("Invalid source timestamp value; using mapper clock")
        return normalize(now)


def build_envelope(
    mqtt_topic: str,
    payload: dict[str, Any],
    *,
    timestamp_key: str,
    now: datetime,
) -> dict[str, Any]:
    raw = payload.get(timestamp_key) if isinstance(payload, dict) else None
    return {"time": _to_iso8601_utc(raw, now=now), "topic": mqtt_topic, "payload": payload}


def parse_envelope(raw: bytes | None) -> HistoricEventRecord | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    time_raw, topic, payload = data.get("time"), data.get("topic"), data.get("payload")
    if not isinstance(time_raw, str) or not isinstance(topic, str) or not topic or not isinstance(payload, dict):
        return None
    try:
        when = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        when = when.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    return HistoricEventRecord(time=when, topic=topic, payload=payload)
