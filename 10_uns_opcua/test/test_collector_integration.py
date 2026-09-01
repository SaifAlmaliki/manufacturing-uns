"""
End-to-end collector tests against an in-process OPC UA server.

These assert the two behaviours the whole design rests on: the server-side deadband
suppresses sub-threshold changes, and subscribing delivers the current value immediately
(which is what heals an outage gap).
"""

import asyncio

import pytest
import pytest_asyncio
from asyncua import Server, ua
from uns_opcua.collector import Collector
from uns_opcua.opcua_config import Deadband, ServerConfig, TagConfig
from uns_opcua.spool import SpoolRow
from uns_opcua.tag_map import build_bindings

ENDPOINT = "opc.tcp://127.0.0.1:48401/uns/test/"
ASSET = "TestCo/Site/Area/Line1/Cell1/Mixer"

pytestmark = [pytest.mark.integrationtest, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def opcua_server():
    """A minimal server exposing one writable Double, with no security."""
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    namespace = await server.register_namespace("http://uns/test")
    objects = server.nodes.objects
    device = await objects.add_object(namespace, "Mixer")
    temperature = await device.add_variable(namespace, "Temp_PV", 75.0)
    await temperature.set_writable()
    async with server:
        yield server, temperature


def _server_config(node_id: str, deadband: Deadband | None) -> ServerConfig:
    return ServerConfig(
        name="test-plc",
        url=ENDPOINT,
        publishing_interval_ms=50,
        tags=(
            TagConfig(
                node_id=node_id,
                asset=ASSET,
                metric_path="ProcessValue/Temperature",
                unit="°C",
                deadband=deadband,
            ),
        ),
    )


async def _drain(queue: asyncio.Queue[SpoolRow], expected: int, timeout: float = 5.0) -> list[SpoolRow]:
    """Collect until `expected` rows arrive or the timeout expires."""
    rows: list[SpoolRow] = []
    async with asyncio.timeout(timeout):
        while len(rows) < expected:
            rows.append(await queue.get())
    return rows


async def _collect(server_config, queue) -> asyncio.Task:
    collector = Collector(
        server=server_config,
        bindings=build_bindings(server_config),
        queue=queue,
        client_id="uns_opcua_test",
        qos=1,
    )
    task = asyncio.create_task(collector.run())
    await asyncio.sleep(1.0)  # let the session and subscription establish
    return task


async def test_subscribing_delivers_the_current_value_immediately(opcua_server):
    """This is what recovers the gap after a session drop - no explicit read needed."""
    _, temperature = opcua_server
    # Read the id off the live node: the numeric part depends on how many nodes the
    # server created first, so hardcoding ns=2;i=2 would be guessing.
    node_id = temperature.nodeid.to_string()
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()

    task = await _collect(_server_config(node_id, deadband=None), queue)
    try:
        rows = await _drain(queue, expected=1)
        assert rows[0].topic == f"{ASSET}/ProcessValue/Temperature"
        assert b'"value":75.0' in rows[0].payload
        assert b'"quality":"Good"' in rows[0].payload
        assert b'"status"' not in rows[0].payload
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_server_side_deadband_suppresses_sub_threshold_changes(opcua_server):
    _, temperature = opcua_server
    node_id = temperature.nodeid.to_string()
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()

    task = await _collect(_server_config(node_id, Deadband(type="absolute", value=2.0)), queue)
    try:
        await _drain(queue, expected=1)  # the initial value
        for value in (75.5, 80.0, 80.4, 90.0):
            await temperature.write_value(ua.DataValue(ua.Variant(value, ua.VariantType.Double)))
            await asyncio.sleep(0.3)

        rows = await _drain(queue, expected=2)
        # 75.5 (0.5 from 75.0) and 80.4 (0.4 from 80.0) are inside the deadband.
        assert b'"value":80.0' in rows[0].payload
        assert b'"value":90.0' in rows[1].payload
        assert queue.empty()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_an_unparsable_node_id_does_not_stop_the_rest_of_the_server(opcua_server):
    _, temperature = opcua_server
    good = temperature.nodeid.to_string()
    server_config = ServerConfig(
        name="test-plc",
        url=ENDPOINT,
        publishing_interval_ms=50,
        tags=(
            TagConfig(node_id="not-a-node-id", asset=ASSET, metric_path="ProcessValue/Bogus"),
            TagConfig(node_id=good, asset=ASSET, metric_path="ProcessValue/Temperature"),
        ),
    )
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    task = await _collect(server_config, queue)
    try:
        rows = await _drain(queue, expected=1)
        assert rows[0].topic == f"{ASSET}/ProcessValue/Temperature"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
