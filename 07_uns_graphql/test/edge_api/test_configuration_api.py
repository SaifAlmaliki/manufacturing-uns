"""Configuration polling, reports, secrets, and scope tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from uns_model.edge_secrets import EncryptedSecret
from uns_model.edge_tables import EdgeSecretVersion

from uns_graphql.edge_api.router import identity_headers
from uns_graphql.edge_api.service import EdgeManagementService

from test.edge_api.conftest import TEST_EDGE, TEST_EDGE_OTHER, enroll_edge, lease_headers, open_session


def _desired_document(**overrides):
    document = {
        "contract_version": 1,
        "adapters": [],
        "required_route_revision": 1,
        "secret_refs": [{"secret_id": "conn-password", "version": 1}],
        "deleted_adapter_ids": [],
    }
    document.update(overrides)
    return document


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_configuration_requires_active_lease(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    response = await client.get(
        "/api/edge/v1/configuration",
        headers=identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
    )
    assert response.status_code == 409
    assert response.json()["error"] == "lease_headers_missing"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_configuration_returns_snapshot_and_honors_etag(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    first = await client.get("/api/edge/v1/configuration", headers=headers)
    assert first.status_code == 200
    assert first.headers["etag"] == f'"{saved.digest}"'
    second = await client.get(
        "/api/edge/v1/configuration",
        headers={**headers, "if-none-match": saved.digest},
    )
    assert second.status_code == 304


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_report_rejects_digest_mismatch(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    response = await client.post(
        "/api/edge/v1/reports",
        headers=headers,
        json={
            "edge_id": TEST_EDGE,
            "boot_id": session["boot_id"],
            "report_sequence": 1,
            "desired_revision": saved.revision,
            "applied_revision": saved.revision,
            "applied_digest": "deadbeef",
            "phase": "applied",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "digest_mismatch"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_report_scope_tampering_rejected(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    session = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session),
    }
    response = await client.post(
        "/api/edge/v1/reports",
        headers=headers,
        json={
            "edge_id": TEST_EDGE_OTHER,
            "boot_id": session["boot_id"],
            "report_sequence": 1,
            "desired_revision": saved.revision,
            "applied_revision": saved.revision,
            "applied_digest": saved.digest,
            "phase": "applied",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"] == "scope_violation"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_secret_fetch_only_authorized_versions(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
    secret_store,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    saved = await edge_service._repository.save_desired(TEST_EDGE, 0, _desired_document())  # noqa: SLF001
    encrypted = secret_store.encrypt(
        edge_id=TEST_EDGE,
        secret_id="conn-password",
        version=1,
        plaintext=b"s3cret!",
    )
    async with edge_service._database.session() as session:  # noqa: SLF001
        session.add(
            EdgeSecretVersion(
                secret_id="conn-password",
                version=1,
                edge_id=TEST_EDGE,
                key_id=encrypted.key_id,
                nonce=encrypted.nonce,
                ciphertext=encrypted.ciphertext,
            )
        )
        await session.commit()

    session_payload = await open_session(client, TEST_EDGE, enrolled["management_serial"])
    headers = {
        **identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        **lease_headers(session_payload),
    }
    allowed = await client.get("/api/edge/v1/secrets/conn-password/1", headers=headers)
    assert allowed.status_code == 200
    assert allowed.content == b"s3cret!"

    denied = await client.get("/api/edge/v1/secrets/other-secret/1", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"] == "secret_not_authorized"
