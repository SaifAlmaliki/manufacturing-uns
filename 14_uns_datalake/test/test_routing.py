"""Frozen lake routing tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from uns_config.events import EnvelopeError, source_event_id
from uns_datalake.routing import lake_object_path, resolve_lake_event
from conftest import legacy_route_map, source_envelope, v2_envelope


def test_path_uses_frozen_received_date(resolved_lims_event):
    assert lake_object_path(resolved_lims_event.route, "batch1") == (
        "raw/v2/application=lims/site=plant-01/schema=lab-result/"
        "version=1/ingestion_date=2026-09-11/batch1.parquet"
    )
    assert resolved_lims_event.envelope.time.date().isoformat() == "2026-09-09"


def test_ingestion_date_uses_utc_rollover_not_local_event_time():
    envelope = v2_envelope(
        time=datetime(2026, 9, 11, 23, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 9, 12, 0, 30, 0, tzinfo=UTC),
    )
    resolved = resolve_lake_event(envelope, None)
    assert resolved.route.ingestion_date.isoformat() == "2026-09-12"
    assert lake_object_path(resolved.route, "batch1").endswith("ingestion_date=2026-09-12/batch1.parquet")


def test_ingestion_date_rolls_back_to_previous_utc_day():
    # 2026-09-12T01:30:00+02:00 == 2026-09-11T23:30:00Z
    envelope = v2_envelope(
        received_at=datetime(2026, 9, 12, 1, 30, 0, tzinfo=timezone(timedelta(hours=2))),
    )
    resolved = resolve_lake_event(envelope, None)
    assert resolved.route.ingestion_date.isoformat() == "2026-09-11"


def test_v2_route_ignores_changed_live_registration():
    envelope = v2_envelope(
        source_application="lims",
        payload_schema_id="lab-result",
        payload_schema_version="1",
    )
    resolved = resolve_lake_event(envelope, None)
    assert resolved.route.application == "lims"
    assert resolved.route.schema == "lab-result"
    assert resolved.route.version == "1"


def test_unknown_v1_route_raises():
    envelope = source_envelope()
    with pytest.raises(EnvelopeError, match="missing_legacy_route"):
        resolve_lake_event(envelope, None)


def test_legacy_sparkplug_preserves_original_bytes():
    raw_bytes = b"\x00\xffspark"
    envelope = source_envelope(
        topic="spBv1.0/PlantA/DDATA/plant-a/device-01",
        event_kind="sparkplug_raw",
        raw_payload_base64="AP9zcGFyaw==",
        payload={},
    )
    resolved = resolve_lake_event(envelope, legacy_route_map())
    assert resolved.payload_fidelity == "original"
    assert resolved.original_payload == raw_bytes
    assert resolved.route.application == "machine"
    assert resolved.route.schema == "sparkplug"


def test_legacy_v1_without_raw_bytes_is_normalized():
    envelope = source_envelope(raw_payload_base64=None)
    resolved = resolve_lake_event(envelope, legacy_route_map())
    assert resolved.payload_fidelity == "legacy_normalized"
    assert resolved.original_payload is None
    assert resolved.legacy_route_revision == "baseline-v1"


def test_two_sites_route_separately():
    plant_a = resolve_lake_event(v2_envelope(site_id="plant-01"), None)
    plant_b = resolve_lake_event(
        v2_envelope(
            site_id="plant-02",
            event_id=source_event_id("plant-02", "plant-02/lims-01", "boot-17", 43),
            source_id="plant-02/lims-01",
        ),
        None,
    )
    assert plant_a.route.site == "plant-01"
    assert plant_b.route.site == "plant-02"
    assert lake_object_path(plant_a.route, "a") != lake_object_path(plant_b.route, "a")


def test_two_applications_route_separately():
    lims = resolve_lake_event(v2_envelope(source_application="lims"), None)
    mes = resolve_lake_event(
        v2_envelope(
            source_application="mes",
            payload_schema_id="production-order",
            event_id=source_event_id("plant-01", "plant-01/mes-01", "boot-17", 44),
            source_id="plant-01/mes-01",
        ),
        None,
    )
    assert lims.route.application == "lims"
    assert mes.route.application == "mes"
    assert lake_object_path(lims.route, "a") != lake_object_path(mes.route, "a")


def test_two_schema_versions_route_separately():
    v1 = resolve_lake_event(v2_envelope(payload_schema_version="1"), None)
    v2 = resolve_lake_event(v2_envelope(payload_schema_version="2"), None)
    assert v1.route.version == "1"
    assert v2.route.version == "2"
    assert lake_object_path(v1.route, "a") != lake_object_path(v2.route, "a")


def test_legacy_map_digest_mismatch_is_refused():
    routes = legacy_route_map().routes
    with pytest.raises(EnvelopeError, match="legacy_map_digest_mismatch"):
        from uns_datalake.routing import LegacyRouteMap

        LegacyRouteMap(revision="baseline-v1", content_digest="deadbeef", routes=routes)
