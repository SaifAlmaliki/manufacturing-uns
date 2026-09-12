"""Explicit publisher wire contract for UNS-to-lake delivery.

Pure contract code: no Kafka, MQTT, database, or cloud SDK imports.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from uns_config.events import (
    EnvelopeError,
    HistoricEventEnvelope,
    MAX_ENVELOPE_BYTES,
    encode_event,
    source_event_id,
)
from uns_config.publication_routes import ROUTE_ID_PATTERN, PublicationRoute, SchemaPair

SUPPORTED_PUBLICATION_VERSION = 1
_SUPPORTED_PUBLICATION_VERSIONS: frozenset[int] = frozenset({1})


@dataclass(frozen=True, slots=True)
class PublisherMessage:
    source_application: str
    site_id: str
    payload_schema_id: str
    payload_schema_version: str
    content_type: str
    original_payload: bytes
    occurred_at: datetime | None = None
    source_boot_id: str | None = None
    source_sequence: int | None = None


def decode_publication(wire: bytes) -> PublisherMessage:
    try:
        parsed = json.loads(wire.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvelopeError("invalid_json") from exc

    if not isinstance(parsed, dict):
        raise EnvelopeError("invalid_json")

    publication_version = parsed.get("publication_version")
    if publication_version not in _SUPPORTED_PUBLICATION_VERSIONS:
        raise EnvelopeError("unsupported_publication_version")

    required_fields = (
        "source_application",
        "site_id",
        "payload_schema_id",
        "payload_schema_version",
        "content_type",
        "original_payload_base64",
    )
    for field in required_fields:
        if field not in parsed:
            raise EnvelopeError("missing_field", field)

    source_boot_id = parsed.get("source_boot_id")
    source_sequence = parsed.get("source_sequence")
    if (source_boot_id is None) ^ (source_sequence is None):
        raise EnvelopeError("invalid_field", "source_identity")

    occurred_at = None
    if "occurred_at" in parsed and parsed["occurred_at"] is not None:
        occurred_at = _parse_occurred_at(parsed["occurred_at"])

    message = PublisherMessage(
        source_application=parsed["source_application"],
        site_id=parsed["site_id"],
        payload_schema_id=parsed["payload_schema_id"],
        payload_schema_version=parsed["payload_schema_version"],
        content_type=parsed["content_type"],
        original_payload=_decode_original_payload_base64(parsed["original_payload_base64"]),
        occurred_at=occurred_at,
        source_boot_id=source_boot_id,
        source_sequence=source_sequence,
    )
    _validate_publisher_message_fields(message)
    return message


def resolve_publisher_message(wire: bytes, route: PublicationRoute) -> PublisherMessage:
    if route.wire_format == "raw":
        if route.default_schema_pair is None:
            raise EnvelopeError("missing_field", "default_schema_pair")
        message = PublisherMessage(
            source_application=route.source_application,
            site_id=route.site_id,
            payload_schema_id=route.default_schema_pair.payload_schema_id,
            payload_schema_version=route.default_schema_pair.payload_schema_version,
            content_type=route.content_type,
            original_payload=wire,
        )
        validate_publisher_message(message, route)
        return message

    message = decode_publication(wire)
    validate_publisher_message(message, route)
    return message


def validate_publisher_message(message: PublisherMessage, route: PublicationRoute) -> None:
    _validate_publisher_message_fields(message)

    if message.source_application != route.source_application:
        raise EnvelopeError("forged_application", message.source_application)

    if message.site_id != route.site_id:
        raise EnvelopeError("forged_site", message.site_id)

    pair = SchemaPair(
        payload_schema_id=message.payload_schema_id,
        payload_schema_version=message.payload_schema_version,
    )
    if pair not in route.allowed_schema_pairs:
        raise EnvelopeError("schema_pair_mismatch", f"{pair.payload_schema_id}:{pair.payload_schema_version}")


def _validate_publisher_message_fields(message: PublisherMessage) -> None:
    for field_name, value in (
        ("source_application", message.source_application),
        ("site_id", message.site_id),
        ("payload_schema_id", message.payload_schema_id),
        ("payload_schema_version", message.payload_schema_version),
    ):
        if not isinstance(value, str) or not ROUTE_ID_PATTERN.fullmatch(value):
            raise EnvelopeError("invalid_field", field_name)

    if not isinstance(message.content_type, str) or not message.content_type:
        raise EnvelopeError("invalid_field", "content_type")

    if not isinstance(message.original_payload, bytes):
        raise EnvelopeError("invalid_field", "original_payload")

    if message.source_boot_id is not None and not isinstance(message.source_boot_id, str):
        raise EnvelopeError("invalid_field", "source_boot_id")

    if message.source_sequence is not None and not isinstance(message.source_sequence, int):
        raise EnvelopeError("invalid_field", "source_sequence")


def _decode_original_payload_base64(value: Any) -> bytes:
    if not isinstance(value, str):
        raise EnvelopeError("invalid_field", "original_payload_base64")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EnvelopeError("invalid_field", "original_payload_base64") from exc


def _parse_occurred_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise EnvelopeError("invalid_field", "occurred_at")
    if not re.search(r"[+-]\d{2}:\d{2}|Z$", value):
        raise EnvelopeError("invalid_field", "occurred_at")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EnvelopeError("invalid_field", "occurred_at") from exc
    if parsed.tzinfo is None:
        raise EnvelopeError("invalid_field", "occurred_at")
    return parsed.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    utc_value = value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def schema_pair_for_route(route: PublicationRoute) -> SchemaPair:
    if route.default_schema_pair is not None:
        return route.default_schema_pair
    return next(iter(route.allowed_schema_pairs))


def build_publication_wrapper(
    *,
    route: PublicationRoute,
    original_payload: bytes,
    source_boot_id: str,
    source_sequence: int,
    occurred_at: datetime | None = None,
) -> bytes:
    """Build the explicit uns-publication-v1 MQTT wire payload."""
    pair = schema_pair_for_route(route)
    instant = occurred_at or datetime.now(UTC)
    wire = {
        "publication_version": SUPPORTED_PUBLICATION_VERSION,
        "source_application": route.source_application,
        "site_id": route.site_id,
        "payload_schema_id": pair.payload_schema_id,
        "payload_schema_version": pair.payload_schema_version,
        "content_type": route.content_type,
        "original_payload_base64": base64.b64encode(original_payload).decode("ascii"),
        "occurred_at": _iso_z(instant),
        "source_boot_id": source_boot_id,
        "source_sequence": source_sequence,
    }
    return json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def wrapper_bytes_for_http_admission(
    *,
    route: PublicationRoute,
    body: bytes,
    receipt_id: UUID,
    occurred_at: datetime | None,
) -> bytes:
    """Persist one wrapper for an HTTPS admission using receipt identity."""
    return build_publication_wrapper(
        route=route,
        original_payload=body,
        source_boot_id=str(receipt_id),
        source_sequence=0,
        occurred_at=occurred_at,
    )


def admission_envelope_size(
    *,
    route: PublicationRoute,
    mqtt_topic: str,
    wrapper_bytes: bytes,
    received_at: datetime,
) -> int:
    """Return the encoded v2 historic envelope size for admission checks."""
    message = resolve_publisher_message(wrapper_bytes, route)
    if message.source_boot_id is None or message.source_sequence is None:
        raise EnvelopeError("invalid_identity")
    event_id = source_event_id(
        route.site_id,
        route.source_id,
        message.source_boot_id,
        message.source_sequence,
    )
    if message.occurred_at is not None:
        event_time = message.occurred_at
        timestamp_quality = "source"
    else:
        event_time = received_at
        timestamp_quality = "ingress"

    envelope = HistoricEventEnvelope(
        schema_version=2,
        event_id=event_id,
        identity_quality="source",
        source_id=route.source_id,
        source_boot_id=message.source_boot_id,
        source_sequence=message.source_sequence,
        site_id=route.site_id,
        time=event_time,
        received_at=received_at,
        timestamp_quality=timestamp_quality,
        topic=mqtt_topic,
        event_kind=route.event_kind,
        is_historical=False,
        payload=_compatibility_payload(message),
        raw_payload_base64=None,
        source_application=message.source_application,
        payload_schema_id=message.payload_schema_id,
        payload_schema_version=message.payload_schema_version,
        content_type=message.content_type,
        original_payload=message.original_payload,
        archive_eligible=route.archive_eligible,
    )
    return len(encode_event(envelope))


def assert_admission_envelope_fits(
    *,
    route: PublicationRoute,
    mqtt_topic: str,
    wrapper_bytes: bytes,
    received_at: datetime,
) -> None:
    size = admission_envelope_size(
        route=route,
        mqtt_topic=mqtt_topic,
        wrapper_bytes=wrapper_bytes,
        received_at=received_at,
    )
    if size > MAX_ENVELOPE_BYTES:
        raise EnvelopeError("oversize")


def content_digest(body: bytes, metadata: dict[str, Any]) -> str:
    wire = json.dumps(
        {"body": base64.b64encode(body).decode("ascii"), "metadata": metadata},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


def _compatibility_payload(message: PublisherMessage) -> dict[str, Any]:
    if message.content_type == "application/json":
        try:
            parsed = json.loads(message.original_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}
