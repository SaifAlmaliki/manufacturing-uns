"""Shared test helpers for the datalake mapper."""

from __future__ import annotations

from datetime import UTC, datetime

from uns_config.events import HistoricEventEnvelope, encode_event, source_event_id


def source_envelope(**overrides) -> HistoricEventEnvelope:
    event_time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 1,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": event_time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"value": 21.4, "timestamp": 1_788_948_000_000},
        "raw_payload_base64": None,
    }
    defaults.update(overrides)
    if defaults["identity_quality"] == "source":
        defaults["event_id"] = source_event_id(
            defaults["site_id"],
            defaults["source_id"],
            defaults["source_boot_id"],
            defaults["source_sequence"],
        )
    return HistoricEventEnvelope(**defaults)


def envelope_bytes(**overrides) -> bytes:
    return encode_event(source_envelope(**overrides))
