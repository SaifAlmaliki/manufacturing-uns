"""Historian event pipeline helpers shared by migrations and tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def legacy_migration_digest(parts: tuple[Any, ...]) -> str:
    wire = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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
