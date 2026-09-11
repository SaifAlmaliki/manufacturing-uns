"""Parquet v2 full-fidelity encoding tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uns_config.events import encode_event, source_event_id
from uns_datalake.parquet import read_parquet_rows, records_to_parquet
from conftest import lake_record_from_envelope, v2_envelope


@pytest.mark.parametrize(
    "body",
    [
        b'{ "timestamp": "2026-09-11T09:00:00Z", "result": 4.2 }',
        b'[1, {"a": true}]',
        b'"released"',
        b"\x00\xff",
        b"",
    ],
)
def test_v2_parquet_round_trip_preserves_original_payload_bytes(body):
    envelope = v2_envelope(original_payload=body, payload={})
    record = lake_record_from_envelope(
        envelope,
        kafka_topic="uns.historic-events",
        partition=3,
        offset=99,
    )
    batch_id = "batch-2026-09-11-001"
    rows = read_parquet_rows(records_to_parquet([record], batch_id=batch_id))
    assert len(rows) == 1
    row = rows[0]
    assert row["original_payload"] == body
    assert row["payload_fidelity"] == "original"
    assert row["legacy_route_revision"] is None
    assert row["batch_id"] == batch_id
    assert row["canonical_envelope"] == record.envelope_bytes


def test_v2_parquet_round_trip_preserves_source_provenance():
    envelope = v2_envelope()
    record = lake_record_from_envelope(envelope, partition=1, offset=7)
    row = read_parquet_rows(records_to_parquet([record], batch_id="batch1"))[0]
    assert row["source_boot_id"] == "boot-17"
    assert row["source_sequence"] == 42
    assert row["timestamp_quality"] == "source"
    assert row["source_application"] == "lims"
    assert row["payload_schema_id"] == "lab-result"
    assert row["payload_schema_version"] == "1"
    assert row["content_type"] == "application/json"
    assert row["archive_eligible"] is True


def test_v2_parquet_round_trip_preserves_transport_coordinates():
    envelope = v2_envelope()
    record = lake_record_from_envelope(
        envelope,
        kafka_topic="uns.historic-events",
        partition=5,
        offset=1234,
    )
    row = read_parquet_rows(records_to_parquet([record], batch_id="batch1"))[0]
    assert row["kafka_topic"] == "uns.historic-events"
    assert row["kafka_partition"] == 5
    assert row["kafka_offset"] == 1234


def test_v2_parquet_timestamps_are_timezone_aware_microseconds():
    envelope = v2_envelope(
        time=datetime(2026, 9, 9, 10, 0, 0, 123456, tzinfo=UTC),
        received_at=datetime(2026, 9, 11, 8, 30, 0, 654321, tzinfo=UTC),
    )
    record = lake_record_from_envelope(envelope)
    row = read_parquet_rows(records_to_parquet([record], batch_id="batch1"))[0]
    assert row["time"].tzinfo is not None
    assert row["received_at"].tzinfo is not None
    assert row["time"].microsecond == 123456
    assert row["received_at"].microsecond == 654321


def test_legacy_v1_parquet_has_null_original_payload_and_revision():
    from conftest import legacy_route_map, source_envelope

    envelope = source_envelope(raw_payload_base64=None)
    record = lake_record_from_envelope(envelope, legacy_map=legacy_route_map())
    row = read_parquet_rows(records_to_parquet([record], batch_id="batch1"))[0]
    assert row["original_payload"] is None
    assert row["payload_fidelity"] == "legacy_normalized"
    assert row["legacy_route_revision"] == "baseline-v1"
    assert row["source_application"] is None


def test_all_records_share_batch_id():
    first = lake_record_from_envelope(v2_envelope(original_payload=b"one"), offset=1)
    second = lake_record_from_envelope(
        v2_envelope(
            original_payload=b"two",
            event_id=source_event_id("plant-01", "plant-01/lims-01", "boot-17", 43),
            source_sequence=43,
        ),
        offset=2,
    )
    batch_id = "shared-batch"
    rows = read_parquet_rows(records_to_parquet([first, second], batch_id=batch_id))
    assert all(row["batch_id"] == batch_id for row in rows)


def test_canonical_envelope_bytes_match_accepted_wire_form():
    envelope = v2_envelope()
    wire = encode_event(envelope)
    record = lake_record_from_envelope(envelope, envelope_bytes=wire)
    row = read_parquet_rows(records_to_parquet([record], batch_id="batch1"))[0]
    assert row["canonical_envelope"] == wire
