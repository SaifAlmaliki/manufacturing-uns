"""Connectivity catalog writes and OPC UA probes through the schema.

The repository is replaced, and the `uns_opcua.browse` helpers are patched — no real
PLC is reachable from this suite. The point is what the resolvers do with the rows
the bridge helpers return, and who may call them.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from uns_config.hivemq_edge_xml import EdgeAdapterInput
from uns_model.connectivity import EDGE_APPLY_ERROR, ConnectivityServerSpec, ConnectivityTagSpec
from uns_model.tables import ConnectivityServer, ConnectivityTag

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity
from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.mutations.connectivity._repository"
QUERY_REPOSITORY = "uns_graphql.queries.connectivity._repository"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_HIVEMQ_XML = (_REPO_ROOT / "conf" / "hivemq" / "config.xml").read_text(encoding="utf-8")

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
async def test_save_connectivity_server_persists_credentials_without_echoing_the_password():
    """Username/password belong in Postgres, not in the payload the console reads back."""
    repository = AsyncMock()
    stored = _server()
    stored.auth_mode = "username"
    stored.username = "eng"
    stored.password = "s3cret"
    repository.save_server.return_value = stored

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) {
                    id authMode username hasPassword
                }
            }
            """,
            variable_values={
                "server": {
                    "id": "s1",
                    "name": "PLC1",
                    "protocol": "OPC_UA",
                    "endpoint": ENDPOINT,
                    "authMode": "USERNAME",
                    "username": "eng",
                    "password": "s3cret",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveConnectivityServer"] == {
        "id": "s1",
        "authMode": "USERNAME",
        "username": "eng",
        "hasPassword": True,
    }
    spec: ConnectivityServerSpec = repository.save_server.await_args.args[0]
    assert spec.auth_mode == "username"
    assert spec.username == "eng"
    assert spec.password == "s3cret"


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
    repository.delete_server.assert_awaited_once()
    call = repository.delete_server.await_args
    assert call.args == ("s1",)
    assert call.kwargs["after_flush"] is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_save_connectivity_server_s7_calls_after_flush(monkeypatch, tmp_path):
    """Saving an S7 server wires the repository's `after_flush` to the HiveMQ Edge XML write."""
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)

    async def _save_server(spec, *, after_flush=None):
        assert after_flush is not None
        after_flush(
            [
                EdgeAdapterInput(
                    server_id=spec.id,
                    protocol=spec.protocol,
                    host="10.0.0.5",
                    port=102,
                    controller_type="S7_1500",
                    tags=(),
                )
            ]
        )
        return _server(server_id=spec.id, protocol=spec.protocol, endpoint=spec.endpoint)

    repository = AsyncMock()
    repository.save_server.side_effect = _save_server

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id protocol }
            }
            """,
            variable_values={
                "server": {
                    "id": "srv-s7",
                    "name": "Line1 PLC",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveConnectivityServer"] == {"id": "srv-s7", "protocol": "S7"}
    text = config_path.read_text(encoding="utf-8")
    assert "<adapterId>catalog-srv-s7</adapterId>" in text
    assert "<adapterId>sim</adapterId>" in text


@pytest.mark.asyncio(loop_scope="function")
async def test_save_s7_live_apply_success_records_untested(monkeypatch, tmp_path):
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()
    saved = _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")
    saved.last_status = "pending"

    async def _save_server(spec, *, after_flush=None):
        after_flush(
            [
                EdgeAdapterInput(
                    server_id=spec.id,
                    protocol="s7",
                    host="10.0.0.5",
                    port=102,
                    controller_type="S7_1500",
                    tags=(),
                )
            ]
        )
        return saved

    repository.save_server.side_effect = _save_server
    repository.list_servers.return_value = [saved]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id lastStatus }
            }
            """,
            variable_values={
                "server": {
                    "id": "srv-s7",
                    "name": "s7",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    live.assert_called_once()
    repository.record_live_apply.assert_awaited()
    kwargs = repository.record_live_apply.await_args
    assert kwargs.kwargs["ok"] is True


@pytest.mark.asyncio(loop_scope="function")
async def test_save_s7_live_apply_failure_keeps_save(monkeypatch, tmp_path):
    from uns_config.hivemq_edge_api import EdgeApplyError

    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.apply_catalog_adapters_live",
        Mock(side_effect=EdgeApplyError("down")),
    )
    repository = AsyncMock()
    saved = _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")

    async def _save_server(spec, *, after_flush=None):
        after_flush([])
        return saved

    repository.save_server.side_effect = _save_server
    repository.list_servers.return_value = [saved]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id }
            }
            """,
            variable_values={
                "server": {
                    "id": "srv-s7",
                    "name": "s7",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveConnectivityServer"]["id"] == "srv-s7"
    repository.record_live_apply.assert_awaited()
    assert repository.record_live_apply.await_args.kwargs["ok"] is False


@pytest.mark.asyncio(loop_scope="function")
async def test_save_opc_ua_live_apply_success_records_untested(monkeypatch, tmp_path):
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()
    saved = _server(server_id="srv-opc", protocol="opc_ua", endpoint="opc.tcp://h:4840")
    saved.last_status = "pending"

    async def _save_server(spec, *, after_flush=None):
        after_flush(
            [
                EdgeAdapterInput(
                    server_id=spec.id,
                    protocol="opc_ua",
                    host="",
                    port=0,
                    uri=spec.endpoint,
                    tags=(),
                )
            ]
        )
        return saved

    repository.save_server.side_effect = _save_server
    repository.list_servers.return_value = [saved]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id lastStatus }
            }
            """,
            variable_values={
                "server": {
                    "id": "srv-opc",
                    "name": "opc",
                    "protocol": "OPC_UA",
                    "endpoint": "opc.tcp://h:4840",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    live.assert_called_once()
    repository.record_live_apply.assert_awaited()
    assert repository.record_live_apply.await_args.kwargs["ok"] is True


# --------------------------------------------------------------- subscribe


@pytest.mark.asyncio(loop_scope="function")
async def test_subscribe_opc_ua_variables_discovers_and_folds_into_catalog(monkeypatch, tmp_path):
    """Discover every Variable on the endpoint and fold into the catalog via replace_subscribed_tags."""
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
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
    assert repository.replace_subscribed_tags.await_args.kwargs["after_flush"] is not None
    live.assert_called_once()
    repository.record_live_apply.assert_awaited()


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


@pytest.mark.asyncio(loop_scope="function")
async def test_subscribe_opc_ua_variables_rejects_s7():
    """OPC UA browse discovery has no meaning against an S7/EtherNet-IP catalog row."""
    repository = AsyncMock()
    repository.list_servers.return_value = [
        _server(server_id="s1", protocol="s7", endpoint="10.0.0.5:102")
    ]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { subscribeOpcUaVariables(serverId: "s1") { nodeId } }',
            context_value=ADMIN,
        )

    assert result.errors
    assert "OPC UA" in result.errors[0].message
    repository.replace_subscribed_tags.assert_not_awaited()


# --------------------------------------------------------------- catalogs / tag context


@pytest.mark.asyncio(loop_scope="function")
async def test_save_unit_of_measure_persists_other_symbol():
    repository = AsyncMock()
    repository.save_unit_of_measure.return_value = SimpleNamespace(symbol="NTU", name="turbidity")
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { saveUnitOfMeasure(symbol: "NTU", name: "turbidity") { symbol name } }',
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["saveUnitOfMeasure"] == {"symbol": "NTU", "name": "turbidity"}
    repository.save_unit_of_measure.assert_awaited_once_with("NTU", "turbidity")


@pytest.mark.asyncio(loop_scope="function")
async def test_update_connectivity_tag_passes_unit_and_asset():
    repository = AsyncMock()
    stored = _tag()
    stored.unit_of_measure = "°C"
    stored.asset_id = 42
    stored.labels = ["Cycle"]
    repository.update_tag.return_value = stored
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation ($patch: ConnectivityTagUpdateInput!) {
              updateConnectivityTag(serverId: "s1", nodeId: "ns=2;s=Temperature", patch: $patch) {
                unitOfMeasure labels
              }
            }
            """,
            variable_values={"patch": {"unitOfMeasure": "°C", "assetId": 42, "labels": ["Cycle"]}},
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["updateConnectivityTag"]["unitOfMeasure"] == "°C"


@pytest.mark.asyncio(loop_scope="function")
async def test_save_signal_label_returns_the_stored_name():
    repository = AsyncMock()
    repository.save_signal_label.return_value = SimpleNamespace(name="Cycle")
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { saveSignalLabel(name: "Cycle") }',
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["saveSignalLabel"] == "Cycle"
    repository.save_signal_label.assert_awaited_once_with("Cycle")


@pytest.mark.asyncio(loop_scope="function")
async def test_units_of_measure_returns_the_catalog():
    repository = AsyncMock()
    repository.list_units_of_measure.return_value = [
        SimpleNamespace(symbol="°C", name="degree Celsius"),
        SimpleNamespace(symbol="NTU", name="turbidity"),
    ]
    with patch(QUERY_REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "{ unitsOfMeasure { symbol name } }",
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["unitsOfMeasure"] == [
        {"symbol": "°C", "name": "degree Celsius"},
        {"symbol": "NTU", "name": "turbidity"},
    ]
    repository.list_units_of_measure.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_signal_labels_returns_catalog_names():
    repository = AsyncMock()
    repository.list_signal_labels.return_value = [
        SimpleNamespace(name="Cycle"),
        SimpleNamespace(name="Quality"),
    ]
    with patch(QUERY_REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "{ signalLabels }",
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["signalLabels"] == ["Cycle", "Quality"]
    repository.list_signal_labels.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_get_subscribed_signals_skips_unsubscribed_tags():
    repository = AsyncMock()
    repository.list_servers.return_value = [_server(name="PLC1")]
    repository.list_subscribed_tags.return_value = [
        _tag(node_id="ns=2;s=Temperature", subscribed=True),
        _tag(node_id="ns=2;s=Pressure", subscribed=False),
    ]
    with patch(QUERY_REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "{ getSubscribedSignals { nodeId serverId serverName subscribed } }",
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["getSubscribedSignals"] == [
        {
            "nodeId": "ns=2;s=Temperature",
            "serverId": "s1",
            "serverName": "PLC1",
            "subscribed": True,
        }
    ]
    repository.list_subscribed_tags.assert_awaited_once_with("s1")


def _tag_with_asset() -> SimpleNamespace:
    return SimpleNamespace(
        server_id="s1",
        node_id="ns=2;s=Temperature",
        browse_path="Objects/Temperature",
        display_name="Temperature",
        mqtt_topic="enterprise/site/temperature",
        subscribed=True,
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        asset_id=42,
        asset=SimpleNamespace(path="AcmeWater/Site1/Furnace", name="Furnace 1"),
        unit_of_measure="°C",
        semantic_class=None,
        data_type=None,
        labels=["Cycle"],
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_get_subscribed_signals_returns_asset_path_and_display_name():
    repository = AsyncMock()
    repository.list_servers.return_value = [_server(name="PLC1")]
    repository.list_subscribed_tags.return_value = [_tag_with_asset()]
    with patch(QUERY_REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "{ getSubscribedSignals { assetPath assetDisplayName } }",
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["getSubscribedSignals"] == [
        {"assetPath": "AcmeWater/Site1/Furnace", "assetDisplayName": "Furnace 1"}
    ]


@pytest.mark.asyncio(loop_scope="function")
async def test_update_connectivity_tag_coerces_null_labels_and_drops_null_not_null_fields():
    """labels is NOT NULL; display_name / mqtt_topic are NOT NULL. Null must not land in SQL."""
    repository = AsyncMock()
    stored = _tag()
    stored.labels = []
    repository.update_tag.return_value = stored
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation ($patch: ConnectivityTagUpdateInput!) {
              updateConnectivityTag(serverId: "s1", nodeId: "ns=2;s=Temperature", patch: $patch) {
                nodeId labels
              }
            }
            """,
            variable_values={
                "patch": {"labels": None, "displayName": None, "mqttTopic": None}
            },
            context_value=ADMIN,
        )
    assert result.errors is None
    kwargs = repository.update_tag.await_args.kwargs
    assert kwargs["labels"] == []
    assert "display_name" not in kwargs
    assert "mqtt_topic" not in kwargs


@pytest.mark.asyncio(loop_scope="function")
async def test_update_connectivity_tag_returns_asset_path_and_display_name():
    repository = AsyncMock()
    repository.update_tag.return_value = _tag_with_asset()
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation ($patch: ConnectivityTagUpdateInput!) {
              updateConnectivityTag(serverId: "s1", nodeId: "ns=2;s=Temperature", patch: $patch) {
                assetPath assetDisplayName
              }
            }
            """,
            variable_values={"patch": {"assetId": 42}},
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["updateConnectivityTag"] == {
        "assetPath": "AcmeWater/Site1/Furnace",
        "assetDisplayName": "Furnace 1",
    }


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
    repository.update_tag_topic.assert_awaited_once()
    call = repository.update_tag_topic.await_args
    assert call.args == ("s1", "ns=2;s=Temperature", "enterprise/site/temp")
    assert call.kwargs["after_flush"] is not None
    assert call.kwargs["on_topic_rewrite"] is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_update_connectivity_tag_topic_syncs_edge_xml(monkeypatch, tmp_path):
    """A topic-only edit must regenerate HiveMQ Edge's config.xml, same as updateConnectivityTag."""
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)

    async def _update_tag_topic(server_id, node_id, mqtt_topic, **kwargs):
        assert kwargs.get("after_flush") is not None
        kwargs["after_flush"](
            [
                EdgeAdapterInput(
                    server_id=server_id,
                    protocol="s7",
                    host="10.0.0.5",
                    port=102,
                    controller_type="S7_1500",
                    tags=(),
                )
            ]
        )
        return _tag(server_id=server_id, node_id=node_id, mqtt_topic=mqtt_topic)

    repository = AsyncMock()
    repository.update_tag_topic.side_effect = _update_tag_topic
    repository.list_servers.return_value = [
        _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")
    ]
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", Mock())

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { updateConnectivityTagTopic(serverId: "srv-s7", '
            'nodeId: "%ID103", mqttTopic: "Acme/Line/Speed") { nodeId } }',
            context_value=ADMIN,
        )

    assert result.errors is None
    text = config_path.read_text(encoding="utf-8")
    assert "<adapterId>catalog-srv-s7</adapterId>" in text


@pytest.mark.asyncio(loop_scope="function")
async def test_update_tag_topic_rewrites_historian_then_live_applies(monkeypatch, tmp_path):
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    rewrite = AsyncMock()

    async def fake_rewrite(session, old_topic, new_topic):
        await rewrite(old_topic, new_topic)

    monkeypatch.setattr("uns_graphql.mutations.connectivity._rewrite_topics", fake_rewrite)
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()
    tag = _tag(mqtt_topic="Server/OpcPlc/Temp")
    captured: dict[str, object] = {}

    async def _update(server_id, node_id, mqtt_topic, **kwargs):
        captured["rewrite"] = kwargs.get("on_topic_rewrite")
        hook = kwargs.get("on_topic_rewrite")
        if hook:
            await hook(None, "Server/OpcPlc/Temp", mqtt_topic)
        after = kwargs.get("after_flush")
        if after:
            after([])
        tag.mqtt_topic = mqtt_topic
        return tag

    repository.update_tag_topic.side_effect = _update
    repository.list_servers.return_value = [
        _server(server_id="srv-opc", protocol="opc_ua", endpoint="opc.tcp://h:4840")
    ]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              updateConnectivityTagTopic(serverId: "srv-opc", nodeId: "ns=1;i=1", mqttTopic: "Acme/Line/Temp") {
                mqttTopic
              }
            }
            """,
            context_value=ADMIN,
        )

    assert result.errors is None
    assert captured["rewrite"] is not None
    rewrite.assert_awaited_once_with("Server/OpcPlc/Temp", "Acme/Line/Temp")
    live.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_update_tag_topic_rewrite_failure_skips_live_apply(monkeypatch):
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)

    async def failing_rewrite(session, old_topic, new_topic):
        raise RuntimeError("timescale down")

    monkeypatch.setattr("uns_graphql.mutations.connectivity._rewrite_topics", failing_rewrite)
    repository = AsyncMock()

    async def _update(server_id, node_id, mqtt_topic, **kwargs):
        hook = kwargs.get("on_topic_rewrite")
        if hook:
            await hook(None, "old/topic", mqtt_topic)
        return _tag(mqtt_topic=mqtt_topic)

    repository.update_tag_topic.side_effect = _update

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              updateConnectivityTagTopic(serverId: "srv-opc", nodeId: "ns=1;i=1", mqttTopic: "Acme/Line/Temp") {
                mqttTopic
              }
            }
            """,
            context_value=ADMIN,
        )

    assert result.errors
    live.assert_not_called()


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
    repository.unsubscribe_tag.assert_awaited_once()
    call = repository.unsubscribe_tag.await_args
    assert call.args == ("s1", "ns=2;s=Temperature")
    assert call.kwargs["after_flush"] is not None


# --------------------------------------------------------------- saveConnectivityTag


@pytest.mark.asyncio(loop_scope="function")
async def test_save_connectivity_tag_returns_the_tag_as_stored():
    """An engineer authors a tag directly (no OPC UA discovery), same catalog write as save_tag."""
    repository = AsyncMock()
    repository.save_tag.return_value = _tag(mqtt_topic="Acme/Test/Area/Line/Cell/S7/Speed")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($tag: ConnectivityTagInput!) {
                saveConnectivityTag(serverId: "s1", tag: $tag) { nodeId mqttTopic subscribed }
            }
            """,
            variable_values={
                "tag": {
                    "nodeId": "ns=2;s=Temperature",
                    "browsePath": "Objects/Temperature",
                    "displayName": "Temperature",
                    "mqttTopic": "Acme/Test/Area/Line/Cell/S7/Speed",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveConnectivityTag"] == {
        "nodeId": "ns=2;s=Temperature",
        "mqttTopic": "Acme/Test/Area/Line/Cell/S7/Speed",
        "subscribed": True,
    }
    spec: ConnectivityTagSpec = repository.save_tag.await_args.args[1]
    assert spec.node_id == "ns=2;s=Temperature"
    assert spec.mqtt_topic == "Acme/Test/Area/Line/Cell/S7/Speed"
    assert repository.save_tag.await_args.kwargs["after_flush"] is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_save_connectivity_tag_passes_data_type_in_one_mutation():
    """`dataType` on `ConnectivityTagInput` lets the console save address, topic, and type together."""
    repository = AsyncMock()
    repository.save_tag.return_value = _tag(mqtt_topic="Acme/Line/Speed")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($tag: ConnectivityTagInput!) {
                saveConnectivityTag(serverId: "s2", tag: $tag) { nodeId }
            }
            """,
            variable_values={
                "tag": {
                    "nodeId": "%ID103",
                    "browsePath": "",
                    "displayName": "Speed",
                    "mqttTopic": "Acme/Line/Speed",
                    "dataType": "Integer",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    spec: ConnectivityTagSpec = repository.save_tag.await_args.args[1]
    assert spec.data_type == "Integer"


@pytest.mark.asyncio(loop_scope="function")
async def test_save_connectivity_tag_defaults_data_type_to_none():
    repository = AsyncMock()
    repository.save_tag.return_value = _tag()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($tag: ConnectivityTagInput!) {
                saveConnectivityTag(serverId: "s1", tag: $tag) { nodeId }
            }
            """,
            variable_values={
                "tag": {
                    "nodeId": "ns=2;s=Temperature",
                    "browsePath": "Objects/Temperature",
                    "displayName": "Temperature",
                    "mqttTopic": "enterprise/site/temperature",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    spec: ConnectivityTagSpec = repository.save_tag.await_args.args[1]
    assert spec.data_type is None


# --------------------------------------------------------------- testConnectivityServer


@pytest.mark.asyncio(loop_scope="function")
async def test_test_connectivity_server_tcp_success_keeps_pending_error():
    """A successful TCP probe of a server still `pending` its first Edge apply keeps EDGE_APPLY_ERROR."""
    repository = AsyncMock()
    pending = _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")
    pending.last_status = "pending"
    repository.list_servers.return_value = [pending]
    tested = _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")
    tested.last_status = "connected"
    repository.record_test.return_value = tested

    with (
        patch(REPOSITORY, return_value=repository),
        patch(
            "uns_graphql.mutations.connectivity.probe_tcp", return_value=(True, None)
        ) as probe,
    ):
        result = await UNSGraphql.schema.execute(
            'mutation { testConnectivityServer(id: "srv-s7") { id lastStatus } }',
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["testConnectivityServer"] == {"id": "srv-s7", "lastStatus": "connected"}
    probe.assert_called_once_with("10.0.0.5", 102)
    repository.record_test.assert_awaited_once_with("srv-s7", ok=True, error=EDGE_APPLY_ERROR)


@pytest.mark.asyncio(loop_scope="function")
async def test_test_connectivity_server_tcp_failure_records_the_error():
    repository = AsyncMock()
    untested = _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")
    repository.list_servers.return_value = [untested]
    repository.record_test.return_value = untested

    with (
        patch(REPOSITORY, return_value=repository),
        patch(
            "uns_graphql.mutations.connectivity.probe_tcp",
            return_value=(False, "Connection refused"),
        ),
    ):
        result = await UNSGraphql.schema.execute(
            'mutation { testConnectivityServer(id: "srv-s7") { id } }',
            context_value=ADMIN,
        )

    assert result.errors is None
    repository.record_test.assert_awaited_once_with(
        "srv-s7", ok=False, error="Connection refused"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_test_connectivity_server_opc_ua_uses_the_probe_not_tcp():
    repository = AsyncMock()
    repository.list_servers.return_value = [_server()]
    repository.record_test.return_value = _server()

    with (
        patch(REPOSITORY, return_value=repository),
        patch(
            "uns_graphql.mutations.connectivity.opcua_browse.test_connection",
            new=AsyncMock(return_value=(True, None, 12.0)),
        ) as test_connection,
        patch("uns_graphql.mutations.connectivity.probe_tcp") as probe,
    ):
        result = await UNSGraphql.schema.execute(
            'mutation { testConnectivityServer(id: "s1") { id } }', context_value=ADMIN
        )

    assert result.errors is None
    test_connection.assert_awaited_once_with(ENDPOINT)
    probe.assert_not_called()
    repository.record_test.assert_awaited_once_with("s1", ok=True, error=None)


@pytest.mark.asyncio(loop_scope="function")
async def test_test_connectivity_server_fails_when_no_such_server():
    repository = AsyncMock()
    repository.list_servers.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { testConnectivityServer(id: "missing") { id } }', context_value=ADMIN
        )

    assert result.errors
    assert "missing" in result.errors[0].message


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

