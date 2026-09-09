import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uns_config.datalake import (
    ENVELOPE_TOPIC,
    HISTORIC_EVENT_COLUMNS,
    FakeObjectStore,
    HistoricEventRecord,
    build_envelope,
    historic_event_object_path,
    parse_envelope,
    topic_safe,
)


def test_envelope_topic_name():
    assert ENVELOPE_TOPIC == "uns.historic-events"


def test_columns_are_historic_event_only():
    assert HISTORIC_EVENT_COLUMNS == ("time", "topic", "payload")
    assert "asset" not in HISTORIC_EVENT_COLUMNS


def test_topic_safe_replaces_slash_not_dot():
    assert topic_safe("Acme/Line/Temp") == "Acme_Line_Temp"


def test_object_path_date_partition_and_unique_flush():
    when = datetime(2026, 9, 8, 15, 4, tzinfo=UTC)
    path = historic_event_object_path(event_time=when, topic="Acme/Line/Temp", flush_id="20260908T150400-abcd1234")
    assert path == "dt=2026-09-08/Acme_Line_Temp-20260908T150400-abcd1234.parquet"
    assert "Acme/Line" not in path


def test_build_envelope_uses_payload_timestamp():
    payload = {"timestamp": 1788868800000, "value": 1.2}
    env = build_envelope("Acme/Line/Temp", payload, timestamp_key="timestamp", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert env["topic"] == "Acme/Line/Temp"
    assert env["payload"] == payload
    assert env["time"] == "2026-09-08T12:00:00+00:00"


def test_build_envelope_falls_back_to_now_when_timestamp_missing():
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    env = build_envelope("t", {"value": 1}, timestamp_key="timestamp", now=now)
    assert env["time"].startswith("2026-09-08T12:00:00")


def test_parse_envelope_round_trip():
    record = parse_envelope(json.dumps({
        "time": "2026-09-08T12:00:00+00:00",
        "topic": "Acme/Line/Temp",
        "payload": {"value": 1},
    }).encode())
    assert record.topic == "Acme/Line/Temp"
    assert record.payload == {"value": 1}


def test_parse_envelope_poison_returns_none():
    assert parse_envelope(b"not-json") is None
    assert parse_envelope(b'{"topic": "t"}') is None
    assert parse_envelope(json.dumps({"time": "t", "topic": "x", "payload": "nope"}).encode()) is None


def test_fake_store_writes_bytes(tmp_path: Path):
    store = FakeObjectStore(tmp_path)
    store.put("dt=2026-09-08/x.parquet", b"PARQUET")
    assert (tmp_path / "dt=2026-09-08/x.parquet").read_bytes() == b"PARQUET"


@pytest.mark.parametrize("raw", [None, "", "bad-date", True, float("nan"), float("inf"), 10**100])
def test_invalid_timestamp_falls_back_to_clock(raw):
    now = datetime(2026, 9, 8, 12, tzinfo=UTC)
    assert build_envelope("t", {"timestamp": raw}, timestamp_key="timestamp", now=now)["time"] == now.isoformat()


def test_offset_timestamp_is_normalized_to_utc():
    env = build_envelope("t", {"timestamp": "2026-09-09T00:30:00+02:00"}, timestamp_key="timestamp", now=datetime.now(UTC))
    assert env["time"] == "2026-09-08T22:30:00+00:00"


@pytest.mark.parametrize("raw", [None, b"null", b"[]", b'{"time":"bad","topic":"t","payload":{}}'])
def test_tombstone_and_invalid_envelopes_are_poison(raw):
    assert parse_envelope(raw) is None
