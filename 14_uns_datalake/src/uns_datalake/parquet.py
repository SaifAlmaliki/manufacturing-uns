"""Parquet encoding for archived historic events."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from uns_config.events import HistoricEventEnvelope

PARQUET_COLUMNS: tuple[str, ...] = (
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

_TIME_TYPE = pa.timestamp("us", tz="UTC")


def _payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def envelope_to_row(envelope: HistoricEventEnvelope) -> dict[str, Any]:
    return {
        "schema_version": envelope.schema_version,
        "event_id": envelope.event_id,
        "identity_quality": envelope.identity_quality,
        "time": envelope.time,
        "received_at": envelope.received_at,
        "site_id": envelope.site_id,
        "source_id": envelope.source_id,
        "topic": envelope.topic,
        "event_kind": envelope.event_kind,
        "is_historical": envelope.is_historical,
        "payload": _payload_json(envelope.payload),
        "raw_payload_base64": envelope.raw_payload_base64,
    }


def rows_to_table(rows: Sequence[dict[str, Any]]) -> pa.Table:
    schema = pa.schema(
        [
            ("schema_version", pa.int32()),
            ("event_id", pa.string()),
            ("identity_quality", pa.string()),
            ("time", _TIME_TYPE),
            ("received_at", _TIME_TYPE),
            ("site_id", pa.string()),
            ("source_id", pa.string()),
            ("topic", pa.string()),
            ("event_kind", pa.string()),
            ("is_historical", pa.bool_()),
            ("payload", pa.string()),
            ("raw_payload_base64", pa.string()),
        ]
    )
    return pa.Table.from_pylist(list(rows), schema=schema)


def records_to_parquet(records: Sequence[HistoricEventEnvelope]) -> bytes:
    rows = [envelope_to_row(record) for record in records]
    table = rows_to_table(rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def read_parquet_rows(parquet_bytes: bytes) -> list[dict[str, Any]]:
    table = pq.read_table(pa.BufferReader(parquet_bytes))
    return table.to_pylist()
