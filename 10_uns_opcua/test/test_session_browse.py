import pytest
import pytest_asyncio
from asyncua import Server

from uns_opcua.browse import browse_children, discover_variables, read_nodes, test_connection
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
    fast = await server.nodes.objects.add_object(idx, "Fast")
    await fast.add_variable(idx, "FastUInt1", 1)
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


async def test_discover_from_a_folder_stays_inside_that_folder(opcua_server):
    async with await open_client(ENDPOINT) as client:
        children = await browse_children(client, None)
        raw = next(node for node in children if node.browse_name == "RawWater")
        nodes = await discover_variables(client, raw.node_id)
    assert any(node.browse_path.endswith("RawWater/T101/Level") for node in nodes)
    assert not any("Fast" in node.browse_path for node in nodes)


async def test_discover_and_read_share_browse_path(opcua_server):
    async with await open_client(ENDPOINT) as client:
        nodes = await discover_variables(client)
        level = next(n for n in nodes if n.browse_path.endswith("RawWater/T101/Level"))
        rows = await read_nodes(client, [level.node_id])
    assert rows[0].browse_path == level.browse_path
    assert level.browse_path == "RawWater/T101/Level"
    assert not rows[0].browse_path.startswith("Objects/")


async def test_good_endpoint_reports_ok(opcua_server):
    ok, error, elapsed_ms = await test_connection(ENDPOINT)
    assert ok is True
    assert error is None
    assert elapsed_ms >= 0


async def test_bad_endpoint_fails_cleanly():
    ok, error, elapsed_ms = await test_connection("opc.tcp://127.0.0.1:1/")
    assert ok is False
    assert error
    assert elapsed_ms >= 0


class _BrowseName:
    def __init__(self, name: str) -> None:
        self.Name = name


class _DisplayName:
    def __init__(self, text: str) -> None:
        self.Text = text


class _NodeId:
    def to_string(self) -> str:
        return "ns=2;s=Level"


class _ReadableVariable:
    nodeid = _NodeId()

    async def get_children(self):
        return []

    async def read_browse_name(self):
        return _BrowseName("Level")

    async def read_display_name(self):
        return _DisplayName("Level")

    async def read_node_class(self):
        from asyncua import ua

        return ua.NodeClass.Variable


class _DeniedChild:
    async def get_children(self):
        from asyncua import ua

        raise ua.UaStatusCodeError(ua.StatusCodes.BadSecurityModeInsufficient)

    async def read_browse_name(self):
        from asyncua import ua

        raise ua.UaStatusCodeError(ua.StatusCodes.BadSecurityModeInsufficient)


class _MixedParent:
    async def get_children(self):
        return [_DeniedChild(), _ReadableVariable()]


def test_unique_by_node_id_keeps_the_first_browse_path():
    from uns_opcua.browse import BrowseNode, unique_by_node_id

    first = BrowseNode(
        node_id="ns=4;i=6218",
        browse_name="A",
        display_name="A",
        browse_path="Refs/A",
        node_class="Variable",
        has_children=False,
    )
    second = BrowseNode(
        node_id="ns=4;i=6218",
        browse_name="A",
        display_name="A",
        browse_path="Inverse/A",
        node_class="Variable",
        has_children=False,
    )
    other = BrowseNode(
        node_id="ns=3;s=WTP_T101_Level",
        browse_name="Level",
        display_name="Level",
        browse_path="RawWater/T101/Level",
        node_class="Variable",
        has_children=False,
    )
    unique = unique_by_node_id([first, second, other])
    assert [row.node_id for row in unique] == ["ns=4;i=6218", "ns=3;s=WTP_T101_Level"]
    assert unique[0].browse_path == "Refs/A"


async def test_discover_skips_nodes_that_require_a_secure_channel():
    from uns_opcua.browse import _collect_variables

    rows = []
    await _collect_variables(_MixedParent(), [], rows)
    assert [row.display_name for row in rows] == ["Level"]
    assert rows[0].browse_path == "Level"
