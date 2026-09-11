"""Compatibility adapters for legacy telemetry consumers."""

from __future__ import annotations

from uns_config.events import (
    SUPPORTED_SCHEMA_VERSION,
    EnvelopeError,
    HistoricEventEnvelope,
    normalize_payload_timestamps,
)

_LEGACY_TELEMETRY_KINDS = frozenset(
    {
        "telemetry",
        "sparkplug_raw",
        "lifecycle",
        "command",
    }
)

_NON_METRIC_KINDS = frozenset(
    {
        "business_event",
        "state_snapshot",
    }
)


def as_legacy_telemetry(event: HistoricEventEnvelope) -> HistoricEventEnvelope | None:
    """Return a v1 telemetry view or None when the event is not metric input."""
    if event.event_kind in _NON_METRIC_KINDS:
        return None

    if event.schema_version == SUPPORTED_SCHEMA_VERSION:
        if event.event_kind not in _LEGACY_TELEMETRY_KINDS:
            raise EnvelopeError("invalid_field", "event_kind")
        return event

    if event.event_kind not in _LEGACY_TELEMETRY_KINDS:
        raise EnvelopeError("invalid_field", "event_kind")

    if not isinstance(event.payload, dict):
        raise EnvelopeError("invalid_field", "payload")

    return HistoricEventEnvelope(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        event_id=event.event_id,
        identity_quality=event.identity_quality,
        source_id=event.source_id,
        source_boot_id=event.source_boot_id,
        source_sequence=event.source_sequence,
        site_id=event.site_id,
        time=event.time,
        received_at=event.received_at,
        timestamp_quality=event.timestamp_quality,
        topic=event.topic,
        event_kind=event.event_kind,
        is_historical=event.is_historical,
        payload=normalize_payload_timestamps(event.payload),
        raw_payload_base64=None,
    )
