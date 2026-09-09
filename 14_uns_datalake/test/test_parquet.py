"""Parquet schema and encoding tests."""

from datetime import UTC, datetime

from uns_datalake.parquet import PARQUET_COLUMNS, envelope_to_row, read_parquet_rows, records_to_parquet
from conftest import source_envelope


def test_parquet_columns_match_design():
    assert PARQUET_COLUMNS == (
        "schema_version",
        "event_id",
        "identity_quality",
        "time",
        "received_at",
        "site_id",
        "source_id",
        "topic",
        "event_kind",
        "is_historical",
        "payload",
        "raw_payload_base64",
    )


def test_records_to_parquet_preserves_identity_and_unicode():
    envelope = source_envelope(
        topic="Enterprise/PlantA/温度",
        payload={"value": "μ", "timestamp": 123456},
        raw_payload_base64="c3Bhcms=",
    )
    rows = read_parquet_rows(records_to_parquet([envelope]))
    assert len(rows) == 1
    row = rows[0]
    assert row["event_id"] == envelope.event_id
    assert row["topic"] == "Enterprise/PlantA/温度"
    assert '"μ"' in row["payload"]
    assert row["raw_payload_base64"] == "c3Bhcms="
    assert row["time"].tzinfo is not None


def test_envelope_to_row_serializes_payload_as_json_text():
    envelope = source_envelope(payload={"value": 1, "timestamp": 1})
    row = envelope_to_row(envelope)
    assert isinstance(row["payload"], str)
    assert row["time"] == envelope.time
