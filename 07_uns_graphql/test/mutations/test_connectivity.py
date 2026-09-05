"""Connectivity catalog writes and OPC UA probes through the schema.

The repository is replaced, and the `uns_opcua.browse` helpers are patched — no real
PLC is reachable from this suite. The point is what the resolvers do with the rows
the bridge helpers return, and who may call them.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uns_model.connectivity import ConnectivityServerSpec, ConnectivityTagSpec
from uns_model.tables import ConnectivityServer, ConnectivityTag

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity
from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.mutations.connectivity._repository"
QUERY_REPOSITORY = "uns_graphql.queries.connectivity._repository"

ADMIN = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000099",
        username="ada.admin",
        roles=frozenset({"admin"}),
    )
}
VIEWER = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000003",
        username="val.viewer",
        roles=frozenset({"viewer"}),
    )
}
ENDPOINT = "opc.tcp://plc1:4840"


def _server(
    server_id: str = "s1",
    name: str = "PLC1",
    endpoint: str = ENDPOINT,
    protocol: str = "opc_ua",
    tags: tuple[ConnectivityTag, ...] = (),
) -> ConnectivityServer:
    return ConnectivityServer(
        id=server_id,
        name=name,
        protocol=protocol,
        endpoint=endpoint,
        last_status="untested",
        last_error="",
        last_tested_at=None,
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        tags=list(tags),
    )


def _tag(
    server_id: str = "s1",
    node_id: str = "ns=2;s=Temperature",
    browse_path: str = "Objects/Temperature",
    display_name: str = "Temperature",
    mqtt_topic: str = "enterprise/site/temperature",
    subscribed: bool = True,
) -> ConnectivityTag:
    return ConnectivityTag(
        server_id=server_id,
        node_id=node_id,
        browse_path=browse_path,
        display_name=display_name,
        mqtt_topic=mqtt_topic,
        subscribed=subscribed,
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )


def _browse_node(node_id: str = "ns=2;s=Temperature", browse_name: str = "Temperature"):
    from uns_opcua.browse import BrowseNode

    return BrowseNode(
        node_id=node_id,
        browse_name=browse_name,
        display_name=browse_name,
        browse_path="Objects/" + browse_name,
        node_class="Variable",
        has_children=False,
    )


def _data_value(node_id: str = "ns=2;s=Temperature", value: float = 21.5):
    from uns_opcua.browse import DataValueRow

    return DataValueRow(
        node_id=node_id,
        display_name="Temperature",
        browse_path="Objects/Temperature",
        value=value,
        data_type="Double",
        source_timestamp=datetime(2026, 9, 5, 11, 0, tzinfo=UTC),
        server_timestamp=datetime(2026, 9, 5, 11, 0, tzinfo=UTC),
        status="good",
    )


# --------------------------------------------------------------- save / delete


@pytest.mark.asyncio(loop_scope="function")
async def test_save_connectivity_server_returns_the_server_as_stored():
    repository = AsyncMock()
    repository.save_server.return_value = _server()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id name protocol endpoint lastStatus }
            }
            """,
            variable_values={
                "server": {
                    "id": "s1",
                    "name": "PLC1",
                    "protocol": "OPC_UA",
                    "endpoint": ENDPOINT,
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveConnectivityServer"] == {
        "id": "s1",
        "name": "PLC1",
        "protocol": "OPC_UA",
        "endpoint": ENDPOINT,
        "lastStatus": "untested",
    }
    spec: ConnectivityServerSpec = repository.save_server.await_args.args[0]
    assert spec.id == "s1"
    assert spec.protocol == "opc_ua"


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("deleted", [True, False])
async def test_delete_connectivity_server_reports_whether_there_was_anything_to_delete(
    deleted: bool,
):
    repository = AsyncMock()
    repository.delete_server.return_value = deleted

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { deleteConnectivityServer(id: "s1") }', context_value=ADMIN
        )

    assert result.errors is None
    assert result.data["deleteConnectivityServer"] is deleted
    repository.delete_server.assert_awaited_once_with("s1")


# --------------------------------------------------------------- subscribe


@pytest.mark.asyncio(loop_scope="function")
async def test_subscribe_opc_ua_variables_discovers_and_folds_into_catalog():
    """Discover every Variable on the endpoint and fold into the catalog via replace_subscribed_tags."""
    repository = AsyncMock()
    repository.list_servers.return_value = [_server()]
    repository.replace_subscribed_tags.return_value = [
        _tag(node_id="ns=2;s=Temperature", mqtt_topic="Objects/Temperature"),
        _tag(node_id="ns=2;s=Pressure", mqtt_topic="Objects/Pressure"),
    ]
    discovered = [
        _browse_node("ns=2;s=Temperature", "Temperature"),
        _browse_node("ns=2;s=Pressure", "Pressure"),
    ]

    with (
        patch(REPOSITORY, return_value=repository),
        patch(
            "uns_graphql.mutations.connectivity.open_client", new=AsyncMock()
        ) as open_client,
        patch(
            "uns_graphql.mutations.connectivity.opcua_browse.discover_variables",
            new=AsyncMock(return_value=discovered),
        ) as discover,
    ):
        result = await UNSGraphql.schema.execute(
            'mutation { subscribeOpcUaVariables(serverId: "s1") '
            "{ nodeId subscribed mqttTopic } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["subscribeOpcUaVariables"] == [
        {"nodeId": "ns=2;s=Temperature", "subscribed": True, "mqttTopic": "Objects/Temperature"},
        {"nodeId": "ns=2;s=Pressure", "subscribed": True, "mqttTopic": "Objects/Pressure"},
    ]
    open_client.assert_awaited_once_with(ENDPOINT)
    discover.assert_awaited_once()
    assert discover.await_args.args[1] is None
    tags: list[ConnectivityTagSpec] = repository.replace_subscribed_tags.await_args.args[1]
    assert [tag.node_id for tag in tags] == ["ns=2;s=Temperature", "ns=2;s=Pressure"]
    assert all(tag.subscribed for tag in tags)


@pytest.mark.asyncio(loop_scope="function")
async def test_subscribe_opc_ua_variables_fails_when_no_such_server():
    repository = AsyncMock()
    repository.list_servers.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { subscribeOpcUaVariables(serverId: "missing") { nodeId } }',
            context_value=ADMIN,
        )

    assert result.errors
    assert "missing" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_subscribe_opc_ua_variables_forwards_node_id():
    repository = AsyncMock()
    repository.list_servers.return_value = [_server()]
    repository.replace_subscribed_tags.return_value = [
        _tag(node_id="ns=3;s=WTP_T101_Level", mqtt_topic="RawWater/T101/Level"),
    ]
    discovered = [_browse_node("ns=3;s=WTP_T101_Level", "Level")]

    with (
        patch(REPOSITORY, return_value=repository),
        patch("uns_graphql.mutations.connectivity.open_client", new=AsyncMock()),
        patch(
            "uns_graphql.mutations.connectivity.opcua_browse.discover_variables",
            new=AsyncMock(return_value=discovered),
        ) as discover,
    ):
        result = await UNSGraphql.schema.execute(
            'mutation { subscribeOpcUaVariables(serverId: "s1", '
            'nodeId: "ns=3;s=WaterTreatmentPlant") { nodeId } }',
            context_value=ADMIN,
        )

    assert result.errors is None
    discover.assert_awaited_once()
    assert discover.await_args.args[1] == "ns=3;s=WaterTreatmentPlant"


# --------------------------------------------------------------- update / unsubscribe


@pytest.mark.asyncio(loop_scope="function")
async def test_update_connectivity_tag_topic_sets_the_topic():
    repository = AsyncMock()
    repository.update_tag_topic.return_value = _tag(mqtt_topic="enterprise/site/temp")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { updateConnectivityTagTopic(serverId: "s1", '
            'nodeId: "ns=2;s=Temperature", mqttTopic: "enterprise/site/temp") '
            "{ nodeId mqttTopic } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["updateConnectivityTagTopic"] == {
        "nodeId": "ns=2;s=Temperature",
        "mqttTopic": "enterprise/site/temp",
    }
    repository.update_tag_topic.assert_awaited_once_with(
        "s1", "ns=2;s=Temperature", "enterprise/site/temp"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_update_connectivity_tag_topic_fails_for_an_unknown_tag():
    repository = AsyncMock()
    repository.update_tag_topic.return_value = None

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { updateConnectivityTagTopic(serverId: "s1", nodeId: "nope", '
            'mqttTopic: "a/b") { nodeId } }',
            context_value=ADMIN,
        )

    assert result.errors
    assert "nope" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    ("tag", "expected"),
    [(_tag(subscribed=False), True), (None, False)],
)
async def test_unsubscribe_connectivity_tag_reports_whether_there_was_anything_to_unsubscribe(
    tag, expected
):
    repository = AsyncMock()
    repository.unsubscribe_tag.return_value = tag

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { unsubscribeConnectivityTag(serverId: "s1", '
            'nodeId: "ns=2;s=Temperature") }',
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["unsubscribeConnectivityTag"] is expected
    repository.unsubscribe_tag.assert_awaited_once_with("s1", "ns=2;s=Temperature")


# --------------------------------------------------------------- role gate


@pytest.mark.asyncio(loop_scope="function")
async def test_a_viewer_cannot_save_a_connectivity_server_and_is_told_which_role_they_need():
    repository = AsyncMock()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id }
            }
            """,
            variable_values={
                "server": {
                    "id": "s1",
                    "name": "PLC1",
                    "protocol": "OPC_UA",
                    "endpoint": ENDPOINT,
                }
            },
            context_value=VIEWER,
        )

    assert result.errors
    assert "engineer" in result.errors[0].message
    repository.save_server.assert_not_awaited()


# --------------------------------------------------------------- queries (probes)


@pytest.mark.asyncio(loop_scope="function")
async def test_get_connectivity_servers_returns_the_catalog():
    repository = AsyncMock()
    repository.list_servers.return_value = [_server(tags=(_tag(),))]

    with patch(QUERY_REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "{ getConnectivityServers { id name protocol endpoint "
            "tags { nodeId subscribed } } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["getConnectivityServers"] == [
        {
            "id": "s1",
            "name": "PLC1",
            "protocol": "OPC_UA",
            "endpoint": ENDPOINT,
            "tags": [{"nodeId": "ns=2;s=Temperature", "subscribed": True}],
        }
    ]
    repository.list_servers.assert_awaited_once_with(protocol=None)


@pytest.mark.asyncio(loop_scope="function")
async def test_get_connectivity_servers_filters_by_protocol():
    repository = AsyncMock()
    repository.list_servers.return_value = []

    with patch(QUERY_REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "{ getConnectivityServers(protocol: OPC_UA) { id } }", context_value=ADMIN
        )

    assert result.errors is None
    repository.list_servers.assert_awaited_once_with(protocol="opc_ua")


@pytest.mark.asyncio(loop_scope="function")
async def test_test_opc_ua_connection_returns_the_result_and_records_against_a_saved_server():
    repository = AsyncMock()
    repository.list_servers.return_value = [_server()]
    repository.record_test.return_value = _server()

    with (
        patch(
            "uns_graphql.queries.connectivity.opcua_browse.test_connection",
            new=AsyncMock(return_value=(True, None, 42.5)),
        ),
        patch(QUERY_REPOSITORY, return_value=repository),
    ):
        result = await UNSGraphql.schema.execute(
            '{ testOpcUaConnection(endpoint: "opc.tcp://plc1:4840") '
            "{ ok error elapsedMs } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["testOpcUaConnection"] == {
        "ok": True,
        "error": None,
        "elapsedMs": 42.5,
    }
    repository.record_test.assert_awaited_once_with("s1", ok=True, error=None)


@pytest.mark.asyncio(loop_scope="function")
async def test_test_opc_ua_connection_does_not_record_when_no_saved_server_matches():
    repository = AsyncMock()
    repository.list_servers.return_value = []

    with (
        patch(
            "uns_graphql.queries.connectivity.opcua_browse.test_connection",
            new=AsyncMock(return_value=(False, "timeout", 100.0)),
        ),
        patch(QUERY_REPOSITORY, return_value=repository),
    ):
        result = await UNSGraphql.schema.execute(
            '{ testOpcUaConnection(endpoint: "opc.tcp://elsewhere:4840") '
            "{ ok error } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["testOpcUaConnection"] == {"ok": False, "error": "timeout"}
    repository.record_test.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_browse_opc_ua_returns_browse_nodes():
    rows = [_browse_node("i=85", "Server"), _browse_node("i=2258", "ServerStatus")]

    with (
        patch("uns_graphql.queries.connectivity.open_client", new=AsyncMock()),
        patch(
            "uns_graphql.queries.connectivity.opcua_browse.browse_children",
            new=AsyncMock(return_value=rows),
        ) as browse,
    ):
        result = await UNSGraphql.schema.execute(
            '{ browseOpcUa(endpoint: "opc.tcp://plc1:4840", nodeId: "i=84") '
            "{ nodeId browseName nodeClass hasChildren } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["browseOpcUa"] == [
        {"nodeId": "i=85", "browseName": "Server", "nodeClass": "Variable",
         "hasChildren": False},
        {"nodeId": "i=2258", "browseName": "ServerStatus", "nodeClass": "Variable",
         "hasChildren": False},
    ]
    browse.assert_awaited_once()
    assert browse.await_args.args[1] == "i=84"


@pytest.mark.asyncio(loop_scope="function")
async def test_discover_opc_ua_variables_returns_variable_nodes():
    rows = [_browse_node("ns=2;s=Temperature", "Temperature")]

    with (
        patch("uns_graphql.queries.connectivity.open_client", new=AsyncMock()),
        patch(
            "uns_graphql.queries.connectivity.opcua_browse.discover_variables",
            new=AsyncMock(return_value=rows),
        ) as discover,
    ):
        result = await UNSGraphql.schema.execute(
            '{ discoverOpcUaVariables(endpoint: "opc.tcp://plc1:4840") '
            "{ nodeId browseName } }",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["discoverOpcUaVariables"] == [
        {"nodeId": "ns=2;s=Temperature", "browseName": "Temperature"}
    ]
    discover.assert_awaited_once()
    assert discover.await_args.args[1] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_discover_opc_ua_variables_forwards_node_id():
    rows = [_browse_node("ns=3;s=WTP_T101_Level", "Level")]

    with (
        patch("uns_graphql.queries.connectivity.open_client", new=AsyncMock()),
        patch(
            "uns_graphql.queries.connectivity.opcua_browse.discover_variables",
            new=AsyncMock(return_value=rows),
        ) as discover,
    ):
        result = await UNSGraphql.schema.execute(
            '{ discoverOpcUaVariables(endpoint: "opc.tcp://plc1:4840", '
            'nodeId: "ns=3;s=WaterTreatmentPlant") { nodeId browseName } }',
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["discoverOpcUaVariables"] == [
        {"nodeId": "ns=3;s=WTP_T101_Level", "browseName": "Level"}
    ]
    discover.assert_awaited_once()
    assert discover.await_args.args[1] == "ns=3;s=WaterTreatmentPlant"


@pytest.mark.asyncio(loop_scope="function")
async def test_read_opc_ua_nodes_returns_data_values():
    rows = [_data_value()]

    with (
        patch("uns_graphql.queries.connectivity.open_client", new=AsyncMock()),
        patch(
            "uns_graphql.queries.connectivity.opcua_browse.read_nodes",
            new=AsyncMock(return_value=rows),
        ) as read,
    ):
        result = await UNSGraphql.schema.execute(
            '{ readOpcUaNodes(endpoint: "opc.tcp://plc1:4840", '
            'nodeIds: ["ns=2;s=Temperature"]) { nodeId value dataType status } }',
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["readOpcUaNodes"] == [
        {"nodeId": "ns=2;s=Temperature", "value": 21.5, "dataType": "Double",
         "status": "good"}
    ]
    read.assert_awaited_once()
    assert read.await_args.args[1] == ["ns=2;s=Temperature"]


# --------------------------------------------------------------- role gate on probes


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    "document",
    [
        "{ getConnectivityServers { id } }",
        '{ testOpcUaConnection(endpoint: "opc.tcp://plc1:4840") { ok } }',
        '{ browseOpcUa(endpoint: "opc.tcp://plc1:4840") { nodeId } }',
        '{ discoverOpcUaVariables(endpoint: "opc.tcp://plc1:4840") { nodeId } }',
        '{ readOpcUaNodes(endpoint: "opc.tcp://plc1:4840", nodeIds: ["i=1"]) { nodeId } }',
    ],
    ids=[
        "getConnectivityServers",
        "testOpcUaConnection",
        "browseOpcUa",
        "discoverOpcUaVariables",
        "readOpcUaNodes",
    ],
)
async def test_a_viewer_cannot_run_an_opc_ua_probe_and_is_told_which_role_they_need(document: str):
    repository = AsyncMock()

    with patch(QUERY_REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(document, context_value=VIEWER)

    assert result.errors
    assert "engineer" in result.errors[0].message
    repository.list_servers.assert_not_awaited()

