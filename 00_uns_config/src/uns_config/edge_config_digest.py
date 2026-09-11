"""Deterministic digest helpers for edge desired-state documents."""

from __future__ import annotations

import hashlib
import json
from typing import Any

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


def canonical_config_bytes(document: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in document.items() if key != "digest"}
    canonical = _sort_json(payload)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def configuration_digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_config_bytes(document)).hexdigest()


def _sort_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    return value
