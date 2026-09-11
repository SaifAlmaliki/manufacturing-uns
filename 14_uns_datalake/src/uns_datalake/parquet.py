"""Parquet encoding for archived historic events."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from uns_datalake.routing import LakeRecord

PARQUET_COLUMNS: tuple[str, ...] = (
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

_TIME_TYPE = pa.timestamp("us", tz="UTC")


def _payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def resolved_event_to_row(record: LakeRecord, *, batch_id: str) -> dict[str, Any]:
    resolved = record.resolved
    envelope = resolved.envelope
    return {
        "schema_version": envelope.schema_version,
        "event_id": envelope.event_id,
        "identity_quality": envelope.identity_quality,
        "time": envelope.time,
        "received_at": envelope.received_at,
        "timestamp_quality": envelope.timestamp_quality,
        "site_id": envelope.site_id,
        "source_id": envelope.source_id,
        "source_boot_id": envelope.source_boot_id,
        "source_sequence": envelope.source_sequence,
        "topic": envelope.topic,
        "event_kind": envelope.event_kind,
        "is_historical": envelope.is_historical,
        "payload": _payload_json(envelope.payload),
        "raw_payload_base64": envelope.raw_payload_base64,
        "source_application": envelope.source_application,
        "payload_schema_id": envelope.payload_schema_id,
        "payload_schema_version": envelope.payload_schema_version,
        "content_type": envelope.content_type,
        "archive_eligible": envelope.archive_eligible,
        "original_payload": resolved.original_payload,
        "payload_fidelity": resolved.payload_fidelity,
        "legacy_route_revision": resolved.legacy_route_revision,
        "kafka_topic": record.kafka_topic,
        "kafka_partition": record.partition,
        "kafka_offset": record.offset,
        "batch_id": batch_id,
        "canonical_envelope": record.envelope_bytes,
    }

def rows_to_table(rows: Sequence[dict[str, Any]]) -> pa.Table:
    schema = pa.schema(
        [
            ("schema_version", pa.int32()),
            ("event_id", pa.string()),
            ("identity_quality", pa.string()),
            ("time", _TIME_TYPE),
            ("received_at", _TIME_TYPE),
            ("timestamp_quality", pa.string()),
            ("site_id", pa.string()),
            ("source_id", pa.string()),
            ("source_boot_id", pa.string()),
            ("source_sequence", pa.int64()),
            ("topic", pa.string()),
            ("event_kind", pa.string()),
            ("is_historical", pa.bool_()),
            ("payload", pa.string()),
            ("raw_payload_base64", pa.string()),
            ("source_application", pa.string()),
            ("payload_schema_id", pa.string()),
            ("payload_schema_version", pa.string()),
            ("content_type", pa.string()),
            ("archive_eligible", pa.bool_()),
            ("original_payload", pa.binary()),
            ("payload_fidelity", pa.string()),
            ("legacy_route_revision", pa.string()),
            ("kafka_topic", pa.string()),
            ("kafka_partition", pa.int32()),
            ("kafka_offset", pa.int64()),
            ("batch_id", pa.string()),
            ("canonical_envelope", pa.binary()),
        ]
    )
    return pa.Table.from_pylist(list(rows), schema=schema)


def records_to_parquet(records: Sequence[LakeRecord], *, batch_id: str) -> bytes:
    rows = [resolved_event_to_row(record, batch_id=batch_id) for record in records]
    table = rows_to_table(rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def read_parquet_rows(parquet_bytes: bytes) -> list[dict[str, Any]]:
    table = pq.read_table(pa.BufferReader(parquet_bytes))
    return table.to_pylist()
