"""Enrollment, certificate issuance, and renewal tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from uns_graphql.edge_api.enrollment import (
    ENROLLMENT_TOKEN_VALIDITY,
    create_enrollment_attempt,
    hash_token,
    mint_enrollment_token,
    revoke_device,
)
from uns_graphql.edge_api.issuer import CERTIFICATE_LIFETIME, RENEWAL_WINDOW, generate_csr
from uns_graphql.edge_api.router import identity_headers
from uns_graphql.edge_api.service import EdgeManagementService

from test.edge_api.conftest import TEST_EDGE, enroll_edge, open_session


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_enroll_returns_server_derived_subjects_and_chains(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    management_csr, mqtt_csr = csrs
    payload = await enroll_edge(edge_service, client, TEST_EDGE, management_csr, mqtt_csr)
    assert payload["management_subject"] == f"CN={TEST_EDGE}.management.uns"
    assert payload["mqtt_subject"] == f"CN={TEST_EDGE}.mqtt.uns"
    assert len(payload["management_certificate_chain"]) == 2
    assert len(payload["mqtt_certificate_chain"]) == 2


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_same_csr_retry_after_response_loss_returns_same_identity(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    management_csr, mqtt_csr = csrs
    token = await edge_service.create_enrollment_token(TEST_EDGE)
    first = await client.post(
        "/api/edge/v1/enroll",
        json={
            "enrollment_token": token,
            "management_csr": management_csr,
            "mqtt_csr": mqtt_csr,
        },
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/edge/v1/enroll",
        json={
            "enrollment_token": token,
            "management_csr": management_csr,
            "mqtt_csr": mqtt_csr,
        },
    )
    assert second.status_code == 200
    assert second.json()["management_serial"] == first.json()["management_serial"]


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_different_csr_retry_rejected(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    management_csr, mqtt_csr = csrs
    token = await edge_service.create_enrollment_token(TEST_EDGE)
    first = await client.post(
        "/api/edge/v1/enroll",
        json={
            "enrollment_token": token,
            "management_csr": management_csr,
            "mqtt_csr": mqtt_csr,
        },
    )
    assert first.status_code == 200
    other_management_csr, _ = generate_csr("other")
    second = await client.post(
        "/api/edge/v1/enroll",
        json={
            "enrollment_token": token,
            "management_csr": other_management_csr,
            "mqtt_csr": mqtt_csr,
        },
    )
    assert second.status_code == 409
    assert second.json()["error"] == "token_reused"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_expired_enrollment_token_rejected(edge_service: EdgeManagementService, client: AsyncClient, csrs):
    management_csr, mqtt_csr = csrs
    token = mint_enrollment_token()
    expired_at = edge_service._now() - timedelta(minutes=1)  # noqa: SLF001
    async with edge_service._database.session() as session:  # noqa: SLF001
        await create_enrollment_attempt(
            session,
            edge_id=TEST_EDGE,
            token_hash=token.token_hash,
            expires_at=expired_at,
        )
        await session.commit()
    response = await client.post(
        "/api/edge/v1/enroll",
        json={
            "enrollment_token": token.token,
            "management_csr": management_csr,
            "mqtt_csr": mqtt_csr,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"] == "expired_token"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_fresh_token_after_prior_enrollment_can_issue_new_certificates(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    first = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    token = await edge_service.create_enrollment_token(TEST_EDGE)
    other_management_csr, other_mqtt_csr = generate_csr("new-mgmt")[0], generate_csr("new-mqtt")[0]
    response = await client.post(
        "/api/edge/v1/enroll",
        json={
            "enrollment_token": token,
            "management_csr": other_management_csr,
            "mqtt_csr": other_mqtt_csr,
        },
    )
    assert response.status_code == 200
    assert response.json()["management_serial"] != first["management_serial"]


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_parallel_enrollment_consumption_is_single_winner(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    management_csr, mqtt_csr = csrs
    token = await edge_service.create_enrollment_token(TEST_EDGE)

    async def attempt():
        return await client.post(
            "/api/edge/v1/enroll",
            json={
                "enrollment_token": token,
                "management_csr": management_csr,
                "mqtt_csr": mqtt_csr,
            },
        )

    results = await asyncio.gather(attempt(), attempt())
    statuses = {response.status_code for response in results}
    assert statuses.issubset({200, 409})
    serials = {response.json().get("management_serial") for response in results if response.status_code == 200}
    assert len(serials) == 1
    if 409 in statuses:
        conflict = next(response for response in results if response.status_code == 409)
        assert conflict.json()["error"] == "enrollment_in_progress"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_revoked_device_cannot_open_session(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
    frozen_now,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    async with edge_service._database.session() as session:  # noqa: SLF001
        await revoke_device(session, TEST_EDGE, frozen_now)
        await session.commit()
    response = await client.post(
        "/api/edge/v1/session",
        headers=identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        json={"boot_id": "boot-1"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "device_revoked"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_renew_after_day_twenty_with_overlap(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
    frozen_now,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    early = await client.post(
        "/api/edge/v1/renew",
        headers=identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        json={"purpose": "management", "csr": csrs[0]},
    )
    assert early.status_code == 409

    renewal_time = frozen_now + RENEWAL_WINDOW + timedelta(hours=1)
    edge_service._now = lambda: renewal_time  # noqa: SLF001
    renewed_csr, _ = generate_csr("renew")
    renewed = await client.post(
        "/api/edge/v1/renew",
        headers=identity_headers(TEST_EDGE, serial=enrolled["management_serial"]),
        json={"purpose": "management", "csr": renewed_csr},
    )
    assert renewed.status_code == 200
    assert renewed.json()["purpose"] == "management"
