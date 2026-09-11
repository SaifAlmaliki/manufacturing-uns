"""Parquet schema and encoding tests."""

from datetime import UTC, datetime

from uns_datalake.parquet import PARQUET_COLUMNS, read_parquet_rows, records_to_parquet, resolved_event_to_row
from conftest import lake_record_from_envelope, legacy_route_map, source_envelope


def test_parquet_columns_match_design():
    assert PARQUET_COLUMNS == (
        "schema_version",
        "event_id",
        "identity_quality",
        "time",
        "received_at",
        "timestamp_quality",
        "site_id",
        "source_id",
        "source_boot_id",
        "source_sequence",
        "topic",
        "event_kind",
        "is_historical",
        "payload",
        "raw_payload_base64",
        "source_application",
        "payload_schema_id",
        "payload_schema_version",
        "content_type",
        "archive_eligible",
        "original_payload",
        "payload_fidelity",
        "legacy_route_revision",
        "kafka_topic",
        "kafka_partition",
        "kafka_offset",
        "batch_id",
        "canonical_envelope",
    )


def test_records_to_parquet_preserves_identity_and_unicode():
    envelope = source_envelope(
        topic="Enterprise/PlantA/温度",
        payload={"value": "μ", "timestamp": 123456},
        raw_payload_base64="c3Bhcms=",
    )
    record = lake_record_from_envelope(envelope, legacy_map=legacy_route_map())
    rows = read_parquet_rows(records_to_parquet([record], batch_id="batch1"))
    assert len(rows) == 1
    row = rows[0]
    assert row["event_id"] == envelope.event_id
    assert row["topic"] == "Enterprise/PlantA/温度"
    assert '"μ"' in row["payload"]
    assert row["raw_payload_base64"] == "c3Bhcms="
    assert row["time"].tzinfo is not None


def test_resolved_event_to_row_serializes_payload_as_json_text():
    envelope = source_envelope(payload={"value": 1, "timestamp": 1})
    record = lake_record_from_envelope(envelope, legacy_map=legacy_route_map())
    row = resolved_event_to_row(record, batch_id="batch1")
    assert isinstance(row["payload"], str)
    assert row["time"] == envelope.time
    assert row["received_at"] == envelope.received_at
