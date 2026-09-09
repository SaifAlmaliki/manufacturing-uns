"""Parquet serialization for Historic Event records."""

from __future__ import annotations

import json
from collections.abc import Sequence
from io import BytesIO

import pyarrow as pa
import pyarrow.parquet as pq

from uns_config.datalake import HistoricEventRecord

_SCHEMA = pa.schema([
    ("time", pa.timestamp("us", tz="UTC")),
    ("topic", pa.string()),
    ("payload", pa.string()),
])


def records_to_parquet(records: Sequence[HistoricEventRecord]) -> bytes:
    """Serialize records to Parquet bytes with the historic-event schema."""
    if not records:
        table = pa.table(
            {
                "time": pa.array([], type=pa.timestamp("us", tz="UTC")),
                "topic": pa.array([], type=pa.string()),
                "payload": pa.array([], type=pa.string()),
            },
            schema=_SCHEMA,
        )
    else:
        table = pa.table(
            {
                "time": [record.time for record in records],
                "topic": [record.topic for record in records],
                "payload": [json.dumps(record.payload) for record in records],
            },
            schema=_SCHEMA,
        )
    buffer = BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()
