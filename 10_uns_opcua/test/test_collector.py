"""Unit tests for monitored-item construction and the data change handler."""

import asyncio
import datetime
import json
from types import SimpleNamespace

import pytest
from asyncua import ua
from uns_opcua.collector import (
    SubscriptionHandler,
    build_monitored_item_request,
    enqueue_drop_oldest,
)
from uns_opcua.opcua_config import Deadband, ServerConfig, TagConfig
from uns_opcua.spool import SpoolRow
from uns_opcua.tag_map import build_bindings

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"
NODE_ID_STRING = "ns=2;i=5"
SOURCE_TS = datetime.datetime(2026, 9, 1, 12, 0, 0, 123000, tzinfo=datetime.UTC)


@pytest.fixture
def bindings():
    server = ServerConfig(
        name="plc01",
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id=NODE_ID_STRING, asset=ASSET, metric_path="ProcessValue/Temperature", unit="°C"),),
    )
    return build_bindings(server)


def test_request_without_a_deadband_carries_no_filter():
    request = build_monitored_item_request(
        node_id=ua.NodeId.from_string(NODE_ID_STRING),
        client_handle=1,
        sampling_interval_ms=200.0,
        deadband=None,
    )
    assert request.RequestedParameters.Filter is None
    assert request.ItemToMonitor.AttributeId == ua.AttributeIds.Value
    assert request.MonitoringMode == ua.MonitoringMode.Reporting


@pytest.mark.parametrize(
    ("deadband", "expected_type"),
    [
        (Deadband(type="absolute", value=0.2), int(ua.DeadbandType.Absolute)),
        (Deadband(type="percent", value=1.0), int(ua.DeadbandType.Percent)),
    ],
)
def test_request_with_a_deadband_carries_a_datachange_filter(deadband, expected_type):
    request = build_monitored_item_request(
        node_id=ua.NodeId.from_string(NODE_ID_STRING),
        client_handle=7,
        sampling_interval_ms=200.0,
        deadband=deadband,
    )
    data_filter = request.RequestedParameters.Filter
    assert isinstance(data_filter, ua.DataChangeFilter)
    assert data_filter.DeadbandType == expected_type
    assert data_filter.DeadbandValue == pytest.approx(deadband.value)
    assert data_filter.Trigger == ua.DataChangeTrigger.StatusValue
    assert request.RequestedParameters.ClientHandle == 7
    assert request.RequestedParameters.SamplingInterval == pytest.approx(200.0)


def _notification(value, source_timestamp=SOURCE_TS, status_code=0):
    """The shape asyncua hands a handler: data.monitored_item.Value is the DataValue."""
    data_value = SimpleNamespace(
        Value=SimpleNamespace(Value=value),
        SourceTimestamp=source_timestamp,
        ServerTimestamp=None,
        StatusCode=SimpleNamespace(value=status_code),
    )
    return SimpleNamespace(monitored_item=SimpleNamespace(Value=data_value))


@pytest.mark.asyncio
async def test_handler_enqueues_a_serialised_payload(bindings):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    handler = SubscriptionHandler(
        bindings_by_node_id={NODE_ID_STRING: bindings[0]},
        queue=queue,
        client_id="uns_opcua_dormagen",
        server_name="plc01",
        qos=1,
    )
    node = SimpleNamespace(nodeid=ua.NodeId.from_string(NODE_ID_STRING))

    handler.datachange_notification(node, 74.83, _notification(74.83))

    row = queue.get_nowait()
    assert row.topic == f"{ASSET}/ProcessValue/Temperature"
    assert row.qos == 1
    payload = json.loads(row.payload.decode("utf-8"))
    assert payload["value"] == 74.83
    assert payload["quality"] == "Good"
    assert payload["source"] == "uns_opcua_dormagen"
    assert payload["timestamp"] == pytest.approx(SOURCE_TS.timestamp() * 1000)
    assert "status" not in payload


@pytest.mark.asyncio
async def test_handler_ignores_a_node_it_has_no_binding_for(bindings):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    handler = SubscriptionHandler(
        bindings_by_node_id={NODE_ID_STRING: bindings[0]},
        queue=queue,
        client_id="c",
        server_name="plc01",
        qos=1,
    )
    node = SimpleNamespace(nodeid=ua.NodeId.from_string("ns=2;i=999"))

    handler.datachange_notification(node, 1.0, _notification(1.0))

    assert queue.empty()


@pytest.mark.asyncio
async def test_handler_publishes_bad_quality_rather_than_dropping_it(bindings):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    handler = SubscriptionHandler(
        bindings_by_node_id={NODE_ID_STRING: bindings[0]},
        queue=queue,
        client_id="c",
        server_name="plc01",
        qos=1,
    )
    node = SimpleNamespace(nodeid=ua.NodeId.from_string(NODE_ID_STRING))

    handler.datachange_notification(node, None, _notification(None, status_code=0x80340000))

    payload = json.loads(queue.get_nowait().payload.decode("utf-8"))
    assert payload["quality"] == "Bad"


@pytest.mark.asyncio
async def test_enqueue_drop_oldest_discards_the_oldest_when_full():
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue(maxsize=2)
    rows = [SpoolRow(topic=f"t{i}", payload=b"{}", qos=1) for i in range(3)]

    assert enqueue_drop_oldest(queue, rows[0]) is True
    assert enqueue_drop_oldest(queue, rows[1]) is True
    assert enqueue_drop_oldest(queue, rows[2]) is False  # something had to go

    assert [queue.get_nowait().topic for _ in range(2)] == ["t1", "t2"]
