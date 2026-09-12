"""Management job execution on the edge agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from uns_config.edge_jobs import MAX_TAGS_PER_PAGE
from uns_edge_agent.jobs import JobExecutionError, JobExecutor, PolledJob, connection_from_config


def _job(**overrides) -> PolledJob:
    base = {
        "job_id": "job-1",
        "edge_id": "edge-01",
        "connection_id": "srv-opc",
        "config_revision": 1,
        "kind": "test_connection",
        "cursor": None,
        "node_id": None,
        "expires_at": "2026-09-12T12:05:00+00:00",
    }
    base.update(overrides)
    return PolledJob(**base)


def _config_document():
    return {
        "edge_id": "edge-01",
        "revision": 1,
        "adapters": [
            {
                "adapter_id": "catalog-srv-opc",
                "protocol": "opc_ua",
                "connection": {"uri": "opc.tcp://plc1:4840", "read_only": True},
                "tags": [],
                "northbound_mappings": [],
            },
            {
                "adapter_id": "catalog-srv-s7",
                "protocol": "s7",
                "connection": {"host": "10.0.0.5", "port": 102, "read_only": True},
                "tags": [],
                "northbound_mappings": [],
            },
        ],
    }


@pytest.mark.asyncio(loop_scope="function")
async def test_test_connection_opc_ua_success():
    executor = JobExecutor()
    with patch(
        "uns_edge_agent.jobs.opcua_browse.test_connection",
        new=AsyncMock(return_value=(True, None, 15.0)),
    ):
        result = await executor.execute(
            _job(kind="test_connection"),
            {"protocol": "opc_ua", "endpoint": "opc.tcp://plc1:4840"},
        )
    assert result["status"] == "completed"
    assert result["result"]["ok"] is True
    assert result["result"]["elapsed_ms"] == 15.0


@pytest.mark.asyncio(loop_scope="function")
async def test_test_connection_tcp_for_s7():
    executor = JobExecutor()
    with patch("uns_edge_agent.jobs._probe_tcp", return_value=(True, None)):
        result = await executor.execute(
            _job(kind="test_connection"),
            {"protocol": "s7", "endpoint": "10.0.0.5:102"},
        )
    assert result["status"] == "completed"
    assert result["result"]["ok"] is True


@pytest.mark.asyncio(loop_scope="function")
async def test_test_connection_failure_records_error():
    executor = JobExecutor()
    with patch("uns_edge_agent.jobs._probe_tcp", return_value=(False, "refused")):
        result = await executor.execute(
            _job(kind="test_connection"),
            {"protocol": "modbus", "endpoint": "10.0.0.5:502"},
        )
    assert result["status"] == "failed"
    assert result["error_code"] == "connection_failed"


@pytest.mark.asyncio(loop_scope="function")
async def test_browse_tags_returns_paged_results():
    from uns_opcua.browse import BrowseNode

    rows = [
        BrowseNode(
            node_id=f"ns=2;s=Tag{i}",
            browse_name=f"Tag{i}",
            display_name=f"Tag{i}",
            browse_path=f"Objects/Tag{i}",
            node_class="Variable",
            has_children=False,
        )
        for i in range(MAX_TAGS_PER_PAGE + 3)
    ]
    executor = JobExecutor()
    with (
        patch("uns_opcua.session.open_client", new=AsyncMock()),
        patch(
            "uns_edge_agent.jobs.opcua_browse.browse_children",
            new=AsyncMock(return_value=rows),
        ),
    ):
        result = await executor.execute(
            _job(kind="browse_tags", node_id="i=84"),
            {"protocol": "opc_ua", "endpoint": "opc.tcp://plc1:4840"},
        )
    assert result["status"] == "completed"
    assert len(result["result"]["tags"]) == MAX_TAGS_PER_PAGE
    assert result["result"]["has_more"] is True
    assert result["result"]["next_cursor"]


@pytest.mark.asyncio(loop_scope="function")
async def test_browse_tags_unsupported_for_s7():
    executor = JobExecutor()
    result = await executor.execute(
        _job(kind="browse_tags"),
        {"protocol": "s7", "endpoint": "10.0.0.5:102"},
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "discovery_unsupported"


def test_connection_from_config_resolves_adapter():
    connection = connection_from_config(_config_document(), "srv-opc")
    assert connection["protocol"] == "opc_ua"
    assert connection["endpoint"] == "opc.tcp://plc1:4840"


def test_connection_from_config_missing_raises():
    with pytest.raises(JobExecutionError) as exc:
        connection_from_config(_config_document(), "missing")
    assert exc.value.reason == "connection_not_in_config"


@pytest.mark.asyncio(loop_scope="function")
async def test_endpoint_allowlist_blocks_disallowed_host():
    executor = JobExecutor(endpoint_allowlist=frozenset({"allowed.local"}))
    with pytest.raises(JobExecutionError) as exc:
        await executor.execute(
            _job(kind="test_connection"),
            {"protocol": "s7", "endpoint": "10.0.0.5:102"},
        )
    assert exc.value.reason == "endpoint_not_allowed"
