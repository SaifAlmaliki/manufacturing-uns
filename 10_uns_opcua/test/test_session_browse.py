import pytest
import pytest_asyncio
from asyncua import Server

from uns_opcua.browse import discover_variables, read_nodes, test_connection
from uns_opcua.session import open_client

ENDPOINT = "opc.tcp://127.0.0.1:48411/uns/browse/"

pytestmark = [pytest.mark.asyncio]


@pytest_asyncio.fixture
async def opcua_server():
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    idx = await server.register_namespace("http://uns/wtp")
    raw = await server.nodes.objects.add_object(idx, "RawWater")
    t101 = await raw.add_object(idx, "T101")
    await t101.add_variable(idx, "Level", 99.3)
    async with server:
        yield


async def test_discover_returns_browse_path_and_node_id(opcua_server):
    async with await open_client(ENDPOINT) as client:
        nodes = await discover_variables(client)
    level = next(n for n in nodes if n.browse_path.endswith("RawWater/T101/Level"))
    assert level.display_name == "Level"
    assert level.browse_path.endswith("RawWater/T101/Level")
    assert level.node_id
    assert level.node_id.count(";") == 1


async def test_read_reports_good_double(opcua_server):
    async with await open_client(ENDPOINT) as client:
        nodes = await discover_variables(client)
        level = next(n for n in nodes if n.browse_path.endswith("T101/Level"))
        rows = await read_nodes(client, [level.node_id])
    assert rows[0].status == "Good"
    assert rows[0].value == pytest.approx(99.3)


async def test_discover_and_read_share_browse_path(opcua_server):
    async with await open_client(ENDPOINT) as client:
        nodes = await discover_variables(client)
        level = next(n for n in nodes if n.browse_path.endswith("RawWater/T101/Level"))
        rows = await read_nodes(client, [level.node_id])
    assert rows[0].browse_path == level.browse_path
    assert level.browse_path == "RawWater/T101/Level"
    assert not rows[0].browse_path.startswith("Objects/")


async def test_bad_endpoint_fails_cleanly():
    ok, error, elapsed_ms = await test_connection("opc.tcp://127.0.0.1:1/")
    assert ok is False
    assert error
    assert elapsed_ms >= 0
