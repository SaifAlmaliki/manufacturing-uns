"""Translates an OPC UA DataValue into the Unified Namespace payload shape."""

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Any

from uns_opcua.tag_map import TagBinding

LOGGER = logging.getLogger(__name__)

_SEVERITY_SHIFT = 30
_SEVERITY_MASK = 0b11
_QUALITY_BY_SEVERITY: dict[int, str] = {0: "Good", 1: "Uncertain", 2: "Bad", 3: "Bad"}


def quality_from_code(code: int) -> str:
    """
    Map an OPC UA StatusCode to Good / Uncertain / Bad.

    Severity lives in the top two bits (OPC UA Part 4, 7.34): 00 Good, 01 Uncertain,
    10 Bad. 11 is reserved, and treating it as Bad is the safe reading. Taking an int
    rather than an `ua.StatusCode` keeps this testable without an OPC UA session.
    """
    return _QUALITY_BY_SEVERITY[(code >> _SEVERITY_SHIFT) & _SEVERITY_MASK]


def to_epoch_ms(moment: datetime.datetime) -> float:
    """
    Epoch milliseconds, matching `mqtt.timestamp_attribute` so this becomes the
    historian's `time` column. A naive datetime is read as UTC, which is what every
    OPC UA server means by one.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.timestamp() * 1000


@dataclass(frozen=True, slots=True)
class MappedPayload:
    """A topic and payload ready to be spooled, plus why the timestamp was chosen."""

    topic: str
    payload: dict[str, Any]
    timestamp_fallback: str | None


def build_payload(
    binding: TagBinding,
    value: Any,
    status_code: int,
    source_timestamp: datetime.datetime | None,
    server_timestamp: datetime.datetime | None,
    collected_at: datetime.datetime,
    client_id: str,
) -> MappedPayload:
    """
    Build the payload for one data change.

    Rule 1 lives here: `timestamp` is the SourceTimestamp, and this function is called
    exactly once per notification — at collection. Nothing downstream recomputes it.
    """
    fallback: str | None = None
    moment = source_timestamp
    if moment is None:
        moment, fallback = server_timestamp, "server_timestamp"
    if moment is None:
        moment, fallback = collected_at, "collection_time"

    payload: dict[str, Any] = {
        "value": value,
        "quality": quality_from_code(status_code),
        "timestamp": to_epoch_ms(moment),
        "source": client_id,
        "equipment": binding.equipment,
    }
    if binding.unit is not None:
        # Insert after `value` so the JSON reads the way the README documents it.
        payload = {"value": payload.pop("value"), "unit": binding.unit, **payload}

    return MappedPayload(topic=binding.topic, payload=payload, timestamp_fallback=fallback)


def serialise(payload: dict[str, Any]) -> bytes:
    """
    Serialise once, at collection, and spool the bytes.

    The historian's `mqtt_msg` is JSONB and compares semantically, so byte-stability is
    not what makes replay idempotent — not re-deriving any field is. Serialising here and
    republishing the bytes verbatim is how that is guaranteed rather than hoped for.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
