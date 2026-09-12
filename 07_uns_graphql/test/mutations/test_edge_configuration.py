"""Cloud-mode connectivity writes use transactional desired state, not local apply."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from uns_model.connectivity import EDGE_APPLY_ERROR, ConnectivityServerSpec
from uns_model.tables import ConnectivityServer

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity
from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.mutations.connectivity._repository"
EDGE_REPOSITORY = "uns_graphql.mutations.connectivity._edge_repository"
AUTH_EDGE_REPOSITORY = "uns_graphql.auth.require._edge_repository"

ADMIN = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000099",
        username="ada.admin",
        roles=frozenset({"admin"}),
    )
}
ENGINEER = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000003",
        username="val.engineer",
        roles=frozenset({"engineer"}),
    )
}


def _server(**overrides) -> ConnectivityServer:
    base = dict(
        id="srv-s7",
        name="Line1 PLC",
        protocol="s7",
        endpoint="10.0.0.5:102",
        edge_id="edge-01",
        last_status="pending",
        last_error=EDGE_APPLY_ERROR,
        last_tested_at=None,
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        tags=[],
    )
    base.update(overrides)
    return ConnectivityServer(**base)


@pytest.fixture
def cloud_mode(monkeypatch):
    monkeypatch.setattr("uns_graphql.mutations.connectivity.is_cloud_edge_mode", lambda: True)
    monkeypatch.setattr("uns_model.connectivity.is_cloud_edge_mode", lambda: True)


@pytest.fixture
def forbid_local_apply(monkeypatch):
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.apply_catalog_adapters_file",
        Mock(side_effect=AssertionError("XML writer must not run in cloud mode")),
    )
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.apply_catalog_adapters_live",
        Mock(side_effect=AssertionError("Edge HTTP client must not run in cloud mode")),
    )
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.probe_tcp",
        Mock(side_effect=AssertionError("PLC client must not run in cloud mode")),
    )
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.opcua_browse.test_connection",
        Mock(side_effect=AssertionError("PLC client must not run in cloud mode")),
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_save_commits_pending_without_local_apply(
    cloud_mode, forbid_local_apply, monkeypatch
):
    repository = AsyncMock()
    edge_repo = AsyncMock()
    edge_repo.device_status.return_value = None
    saved = _server()
    repository.save_server.return_value = saved

    with patch(REPOSITORY, return_value=repository), patch(EDGE_REPOSITORY, return_value=edge_repo):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) {
                    id
                    lastStatus
                    connectionHealth
                    edgeId
                }
            }
            """,
            variable_values={
                "server": {
                    "id": "srv-s7",
                    "name": "Line1 PLC",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                    "edgeId": "edge-01",
                    "expectedRevision": 0,
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    payload = result.data["saveConnectivityServer"]
    assert payload["id"] == "srv-s7"
    assert payload["lastStatus"] == "pending"
    assert payload["connectionHealth"] == "pending"
    assert payload["edgeId"] == "edge-01"
    kwargs = repository.save_server.await_args.kwargs
    assert kwargs.get("after_flush") is None
    assert kwargs.get("after_flush_async") is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_save_does_not_call_finish_live_apply(cloud_mode, monkeypatch):
    repository = AsyncMock()
    edge_repo = AsyncMock()
    edge_repo.device_status.return_value = None
    repository.save_server.return_value = _server()
    finish = AsyncMock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity._finish_live_apply", finish)

    with patch(REPOSITORY, return_value=repository), patch(EDGE_REPOSITORY, return_value=edge_repo):
        await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id }
            }
            """,
            variable_values={
                "server": {
                    "id": "srv-s7",
                    "name": "Line1 PLC",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                    "edgeId": "edge-01",
                    "expectedRevision": 0,
                }
            },
            context_value=ADMIN,
        )

    finish.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_requires_edge_id_and_expected_revision(cloud_mode):
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
                    "id": "srv-s7",
                    "name": "Line1 PLC",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is not None
    assert "edge_id" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_engineer_requires_edge_grant(cloud_mode):
    repository = AsyncMock()
    edge_repo = AsyncMock()
    edge_repo.user_has_grant = AsyncMock(return_value=False)

    with (
        patch(REPOSITORY, return_value=repository),
        patch(AUTH_EDGE_REPOSITORY, return_value=edge_repo),
    ):
        result = await UNSGraphql.schema.execute(
            """
            mutation Save($server: ConnectivityServerInput!) {
                saveConnectivityServer(server: $server) { id }
            }
            """,
            variable_values={
                "server": {
                    "id": "srv-s7",
                    "name": "Line1 PLC",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                    "edgeId": "edge-01",
                    "expectedRevision": 0,
                }
            },
            context_value=ENGINEER,
        )

    assert result.errors is not None
    assert "outside your Access Groups" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_subscribe_opc_ua_is_unavailable(cloud_mode):
    with patch(REPOSITORY, return_value=AsyncMock()):
        result = await UNSGraphql.schema.execute(
            """
            mutation Subscribe($serverId: String!) {
                subscribeOpcUaVariables(serverId: $serverId) { nodeId }
            }
            """,
            variable_values={"serverId": "s1"},
            context_value=ADMIN,
        )

    assert result.errors is not None
    assert "cloud edge mode" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_local_mode_still_uses_sync_edge(monkeypatch):
    monkeypatch.setattr("uns_graphql.mutations.connectivity.is_cloud_edge_mode", lambda: False)
    repository = AsyncMock()
    repository.save_server.return_value = _server(edge_id=None, last_status="untested", last_error="")
    repository.list_servers.return_value = []
    finish = AsyncMock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity._finish_live_apply", finish)

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
                    "name": "Line1 PLC",
                    "protocol": "S7",
                    "endpoint": "10.0.0.5:102",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    assert repository.save_server.await_args.kwargs.get("after_flush") is not None
    finish.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_test_connectivity_server_returns_job(cloud_mode, monkeypatch):
    repository = AsyncMock()
    edge_repo = AsyncMock()
    edge_repo.device_status.return_value = SimpleNamespace(
        desired_revision=3,
        applied_revision=2,
        applied_phase="applied",
        last_seen=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        capabilities={},
    )
    server = _server(id="srv-opc", protocol="opc_ua", endpoint="opc.tcp://plc1:4840")
    repository.list_servers.return_value = [server]
    job = SimpleNamespace(
        job_id="job-123",
        status="queued",
        edge_id="edge-01",
        connection_id="srv-opc",
        kind="test_connection",
        cursor=None,
        node_id=None,
        result_payload=None,
        error_code=None,
        error_detail=None,
    )
    job_service = AsyncMock()
    job_service.create_job.return_value = job
    monkeypatch.setattr("uns_graphql.mutations.connectivity._job_service", lambda: job_service)

    with patch(REPOSITORY, return_value=repository), patch(EDGE_REPOSITORY, return_value=edge_repo):
        result = await UNSGraphql.schema.execute(
            """
            mutation Test($id: String!) {
                testConnectivityServer(id: $id) {
                    id
                    activeJobId
                    activeJobStatus
                }
            }
            """,
            variable_values={"id": "srv-opc"},
            context_value=ADMIN,
        )

    assert result.errors is None
    payload = result.data["testConnectivityServer"]
    assert payload["activeJobId"] == "job-123"
    assert payload["activeJobStatus"] == "queued"
    job_service.create_job.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_test_rejects_disconnected_edge(cloud_mode):
    repository = AsyncMock()
    edge_repo = AsyncMock()
    edge_repo.device_status.return_value = SimpleNamespace(
        desired_revision=3,
        applied_revision=2,
        applied_phase="applied",
        last_seen=None,
        capabilities={},
    )
    server = _server(id="srv-opc", protocol="opc_ua", endpoint="opc.tcp://plc1:4840")
    repository.list_servers.return_value = [server]

    with patch(REPOSITORY, return_value=repository), patch(EDGE_REPOSITORY, return_value=edge_repo):
        result = await UNSGraphql.schema.execute(
            'mutation { testConnectivityServer(id: "srv-opc") { id } }',
            context_value=ADMIN,
        )

    assert result.errors is not None
    assert "not connected" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_cloud_mode_opc_probes_are_unavailable(cloud_mode, monkeypatch):
    monkeypatch.setattr("uns_graphql.queries.connectivity.is_cloud_edge_mode", lambda: True)
    with patch("uns_graphql.queries.connectivity._repository", return_value=AsyncMock()):
        result = await UNSGraphql.schema.execute(
            '{ browseOpcUa(endpoint: "opc.tcp://plc1:4840") { nodeId } }',
            context_value=ADMIN,
        )
    assert result.errors is not None
    assert "cloud edge mode" in result.errors[0].message


def test_cloud_context_attaches_secret_store(monkeypatch):
    from uns_graphql.mutations.connectivity import _cloud_context

    store = object()
    monkeypatch.setattr("uns_graphql.mutations.connectivity._edge_secret_store", lambda: store)
    monkeypatch.setattr(EDGE_REPOSITORY, lambda: object())
    info = SimpleNamespace(context=ADMIN)
    ctx = _cloud_context(info, "edge-01", 3)
    assert ctx.secret_store is store
    assert ctx.edge_id == "edge-01"
    assert ctx.expected_revision == 3
