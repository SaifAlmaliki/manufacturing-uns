import json
from datetime import UTC, datetime
from io import BytesIO

import pyarrow.parquet as pq

from uns_config.datalake import HISTORIC_EVENT_COLUMNS, HistoricEventRecord
from uns_datalake.parquet import records_to_parquet


def test_parquet_columns_and_payload_json():
    records = [
        HistoricEventRecord(datetime(2026, 9, 8, tzinfo=UTC), "Acme/Line/Temp", {"value": 1.2}),
    ]
    data = records_to_parquet(records)
    assert isinstance(data, bytes)
    table = pq.read_table(source=BytesIO(data))
    assert tuple(table.column_names) == HISTORIC_EVENT_COLUMNS
    assert str(table.schema.field("time").type) == "timestamp[us, tz=UTC]"
    assert json.loads(table.column("payload")[0].as_py()) == {"value": 1.2}
