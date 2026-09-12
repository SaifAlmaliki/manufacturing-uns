"""Outbound management job poll/result contract tests."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from uns_config.edge_jobs import (
    JOB_KIND_BROWSE_TAGS,
    JOB_KIND_TEST_CONNECTION,
    MAX_PENDING_JOBS_PER_EDGE,
    MAX_RESULT_BYTES,
)
from uns_graphql.edge_api.jobs import EdgeJobService
from uns_graphql.edge_api.router import identity_headers
from uns_graphql.edge_api.service import EdgeManagementService

from test.edge_api.conftest import TEST_EDGE, TEST_EDGE_OTHER, enroll_edge, lease_headers, open_session


def _desired_document(**overrides):
    document = {
        "contract_version": 1,
        "adapters": [],
        "required_route_revision": 1,
        "secret_refs": [],
        "deleted_adapter_ids": [],
    }
    document.update(overrides)
    return document


async def _seed_connection(database, edge_id: str, connection_id: str, protocol: str = "opc_ua") -> None:
    async with database.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO console.connectivity_servers
                    (id, name, protocol, endpoint, edge_id, last_status, last_error)
                VALUES
                    (:id, :name, :protocol, :endpoint, :edge_id, 'pending', '')
                ON CONFLICT (id) DO UPDATE SET edge_id = EXCLUDED.edge_id, protocol = EXCLUDED.protocol
                """
            ),
            {
                "id": connection_id,
                "name": connection_id,
                "protocol": protocol,
                "endpoint": "opc.tcp://plc1:4840",
                "edge_id": edge_id,
            },
        )
        await session.commit()


async def _job_service(edge_service: EdgeManagementService) -> EdgeJobService:
    return EdgeJobService(
        edge_service._database,  # noqa: SLF001
        edge_service._repository,  # noqa: SLF001
        edge_service,
        now=edge_service._now,  # noqa: SLF001
    )


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_poll_returns_queued_job_and_marks_running(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    created = await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    response = await client.get("/api/edge/v1/jobs", headers=headers)
    assert response.status_code == 200
    payload = response.json()["jobs"]
    assert len(payload) == 1
    assert payload[0]["job_id"] == created.job_id
    assert payload[0]["kind"] == JOB_KIND_TEST_CONNECTION
    fetched = await jobs.get_job(created.job_id)
    assert fetched is not None
    assert fetched.status == "running"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_submit_result_completes_job(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    created = await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    await client.get("/api/edge/v1/jobs", headers=headers)
    response = await client.post(
        f"/api/edge/v1/jobs/{created.job_id}/result",
        headers=headers,
        json={"status": "completed", "result": {"ok": True, "elapsed_ms": 12.0}},
    )
    assert response.status_code == 200
    fetched = await jobs.get_job(created.job_id)
    assert fetched is not None
    assert fetched.status == "completed"
    assert fetched.result_payload == {"ok": True, "elapsed_ms": 12.0}


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_wrong_edge_cannot_submit_result(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled_a = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    enrolled_b = await enroll_edge(edge_service, client, TEST_EDGE_OTHER, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    created = await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    session_a = await open_session(client, TEST_EDGE, enrolled_a["management_serial"])
    headers_a = {
        **identity_headers(TEST_EDGE, serial=enrolled_a["management_serial"]),
        **lease_headers(session_a),
    }
    await client.get("/api/edge/v1/jobs", headers=headers_a)
    session_b = await open_session(client, TEST_EDGE_OTHER, enrolled_b["management_serial"])
    headers_b = {
        **identity_headers(TEST_EDGE_OTHER, serial=enrolled_b["management_serial"]),
        **lease_headers(session_b),
    }
    response = await client.post(
        f"/api/edge/v1/jobs/{created.job_id}/result",
        headers=headers_b,
        json={"status": "completed", "result": {"ok": True}},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "scope_violation"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_revision_mismatch_rejects_new_job(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    with pytest.raises(Exception) as exc:
        await jobs.create_job(
            edge_id=TEST_EDGE,
            connection_id="srv-opc",
            kind=JOB_KIND_TEST_CONNECTION,
            config_revision=99,
        )
    assert "revision_mismatch" in str(exc.value)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_duplicate_result_is_idempotent(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    created = await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    await client.get("/api/edge/v1/jobs", headers=headers)
    body = {"status": "completed", "result": {"ok": True}}
    first = await client.post(f"/api/edge/v1/jobs/{created.job_id}/result", headers=headers, json=body)
    second = await client.post(f"/api/edge/v1/jobs/{created.job_id}/result", headers=headers, json=body)
    assert first.status_code == 200
    assert second.status_code == 200


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_expired_job_rejects_result(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
    frozen_now,
):
    from datetime import UTC, datetime, timedelta

    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    created = await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    async with edge_service._database.session() as session:  # noqa: SLF001
        await session.execute(
            text("UPDATE edge.jobs SET expires_at = :expires_at WHERE job_id = :job_id"),
            {
                "expires_at": datetime.now(UTC) - timedelta(minutes=1),
                "job_id": created.job_id,
            },
        )
        await session.commit()
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    response = await client.post(
        f"/api/edge/v1/jobs/{created.job_id}/result",
        headers=headers,
        json={"status": "completed", "result": {"ok": True}},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "job_expired"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_browse_job_rejects_unsupported_protocol(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-s7", protocol="s7")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    with pytest.raises(Exception) as exc:
        await jobs.create_job(
            edge_id=TEST_EDGE,
            connection_id="srv-s7",
            kind=JOB_KIND_BROWSE_TAGS,
            config_revision=saved.revision,
        )
    assert "discovery_unsupported" in str(exc.value)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_pending_jobs_limit(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    for _ in range(MAX_PENDING_JOBS_PER_EDGE):
        await jobs.create_job(
            edge_id=TEST_EDGE,
            connection_id="srv-opc",
            kind=JOB_KIND_TEST_CONNECTION,
            config_revision=saved.revision,
        )
    with pytest.raises(Exception) as exc:
        await jobs.create_job(
            edge_id=TEST_EDGE,
            connection_id="srv-opc",
            kind=JOB_KIND_TEST_CONNECTION,
            config_revision=saved.revision,
        )
    assert "pending_jobs_limit" in str(exc.value)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_only_one_running_job_at_a_time(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    first = await client.get("/api/edge/v1/jobs", headers=headers)
    second = await client.get("/api/edge/v1/jobs", headers=headers)
    assert len(first.json()["jobs"]) == 1
    assert second.json()["jobs"] == []


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_result_too_large_rejected(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    await _seed_connection(edge_service._database, TEST_EDGE, "srv-opc")  # noqa: SLF001
    jobs = await _job_service(edge_service)
    created = await jobs.create_job(
        edge_id=TEST_EDGE,
        connection_id="srv-opc",
        kind=JOB_KIND_TEST_CONNECTION,
        config_revision=saved.revision,
    )
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    await client.get("/api/edge/v1/jobs", headers=headers)
    oversized = {"blob": "x" * (MAX_RESULT_BYTES + 1)}
    response = await client.post(
        f"/api/edge/v1/jobs/{created.job_id}/result",
        headers=headers,
        json={"status": "completed", "result": oversized},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "result_too_large"
