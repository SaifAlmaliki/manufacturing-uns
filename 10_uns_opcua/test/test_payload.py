"""Unit tests for OPC UA DataValue -> UNS payload mapping."""

import datetime
import json

import pytest
from uns_opcua.opcua_config import ServerConfig, TagConfig
from uns_opcua.payload import build_payload, quality_from_code, serialise, to_epoch_ms
from uns_opcua.tag_map import build_bindings

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"
CLIENT_ID = "uns_opcua_dormagen"

SOURCE_TS = datetime.datetime(2026, 9, 1, 12, 0, 0, 123000, tzinfo=datetime.UTC)
SERVER_TS = datetime.datetime(2026, 9, 1, 12, 0, 0, 456000, tzinfo=datetime.UTC)
COLLECTED_AT = datetime.datetime(2026, 9, 1, 12, 0, 1, 0, tzinfo=datetime.UTC)


@pytest.fixture
def binding():
    server = ServerConfig(
        name="plc01",
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id="ns=2;i=5", asset=ASSET, metric_path="ProcessValue/Temperature", unit="°C"),),
    )
    return build_bindings(server)[0]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0x00000000, "Good"),        # Good
        (0x00000002, "Good"),        # Good with an info bit set
        (0x40000000, "Uncertain"),   # Uncertain
        (0x408F0000, "Uncertain"),   # Uncertain_LastUsableValue
        (0x80000000, "Bad"),         # Bad
        (0x80340000, "Bad"),         # BadDeviceFailure
        (0xC0000000, "Bad"),         # reserved severity is treated as Bad
    ],
)
def test_quality_from_code(code, expected):
    assert quality_from_code(code) == expected


def test_to_epoch_ms():
    # 2026-09-01T12:00:00.123Z. Verified against datetime rather than typed from memory.
    assert to_epoch_ms(SOURCE_TS) == pytest.approx(1788264000123.0)


def test_to_epoch_ms_treats_a_naive_datetime_as_utc():
    naive = SOURCE_TS.replace(tzinfo=None)
    assert to_epoch_ms(naive) == pytest.approx(to_epoch_ms(SOURCE_TS))


def test_build_payload_uses_source_timestamp(binding):
    mapped = build_payload(
        binding=binding,
        value=74.83,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=SERVER_TS,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.topic == f"{ASSET}/ProcessValue/Temperature"
    assert mapped.timestamp_fallback is None
    assert mapped.payload == {
        "value": 74.83,
        "unit": "°C",
        "quality": "Good",
        "timestamp": pytest.approx(to_epoch_ms(SOURCE_TS)),
        "source": CLIENT_ID,
        "equipment": "MixerTank",
    }


def test_build_payload_never_emits_a_status_field(binding):
    mapped = build_payload(
        binding=binding,
        value=74.83,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert "status" not in mapped.payload


def test_build_payload_omits_unit_when_not_configured():
    server = ServerConfig(
        name="plc01",
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id="ns=2;i=5", asset=ASSET, metric_path="Status/Running"),),
    )
    mapped = build_payload(
        binding=build_bindings(server)[0],
        value=True,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert "unit" not in mapped.payload
    assert mapped.payload["value"] is True


def test_build_payload_falls_back_to_server_timestamp(binding):
    mapped = build_payload(
        binding=binding,
        value=1.0,
        status_code=0,
        source_timestamp=None,
        server_timestamp=SERVER_TS,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.timestamp_fallback == "server_timestamp"
    assert mapped.payload["timestamp"] == pytest.approx(to_epoch_ms(SERVER_TS))


def test_build_payload_falls_back_to_collection_time(binding):
    mapped = build_payload(
        binding=binding,
        value=1.0,
        status_code=0,
        source_timestamp=None,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.timestamp_fallback == "collection_time"
    assert mapped.payload["timestamp"] == pytest.approx(to_epoch_ms(COLLECTED_AT))


def test_build_payload_publishes_bad_quality_rather_than_dropping_it(binding):
    mapped = build_payload(
        binding=binding,
        value=None,
        status_code=0x80340000,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.payload["quality"] == "Bad"
    assert mapped.payload["value"] is None


def test_serialise_round_trips_and_keeps_unicode_units(binding):
    mapped = build_payload(
        binding=binding,
        value=74.83,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    raw = serialise(mapped.payload)
    assert isinstance(raw, bytes)
    assert json.loads(raw.decode("utf-8"))["unit"] == "°C"
