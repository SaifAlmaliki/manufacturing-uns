"""Historian event pipeline helpers shared by migrations and tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def _jsonb_key_sort(key: str) -> tuple[int, bytes]:
    encoded = key.encode("utf-8")
    return (len(encoded), encoded)


def _canonicalize_jsonb(value: Any) -> Any:
    """Match PostgreSQL jsonb object pair order: shorter keys first, then memcmp."""
    if isinstance(value, dict):
        return {
            key: _canonicalize_jsonb(item)
            for key, item in sorted(value.items(), key=lambda kv: _jsonb_key_sort(str(kv[0])))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_jsonb(item) for item in value]
    return value


def legacy_migration_digest(parts: tuple[Any, ...]) -> str:
    wire = json.dumps(
        _canonicalize_jsonb(parts),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def legacy_migration_event_id(
    time: datetime,
    topic: str,
    client_id: str | None,
    mqtt_msg: dict[str, Any],
) -> str:
    parts = (_format_time(time), topic, client_id or "", mqtt_msg)
    return f"legacy:{legacy_migration_digest(parts)}"


def legacy_migration_content_hash(
    time: datetime,
    topic: str,
    mqtt_msg: dict[str, Any],
) -> str:
    parts = (_format_time(time), topic, mqtt_msg)
    return legacy_migration_digest(parts)


def _payload_dict(mqtt_msg: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(mqtt_msg, str):
        loaded = json.loads(mqtt_msg)
        if not isinstance(loaded, dict):
            raise TypeError("legacy historian inserts require a JSON object payload")
        return loaded
    return mqtt_msg


def legacy_raw_insert_params(
    time: datetime,
    topic: str,
    client_id: str | None,
    mqtt_msg: dict[str, Any] | str,
) -> dict[str, Any]:
    """Columns required for a post-0009 insert into unifiednamespace."""
    payload = _payload_dict(mqtt_msg)
    return {
        "time": time,
        "topic": topic,
        "client_id": client_id,
        "mqtt_msg": mqtt_msg,
        "event_id": legacy_migration_event_id(time, topic, client_id, payload),
        "received_at": time,
        "immutable_content_hash": legacy_migration_content_hash(time, topic, payload),
    }
