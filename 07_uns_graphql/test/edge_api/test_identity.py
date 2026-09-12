"""Trusted-proxy identity verification tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from uns_graphql.edge_api.identity import (
    EDGE_ID_HEADER,
    EDGE_PURPOSE_HEADER,
    EDGE_SERIAL_HEADER,
    TRUSTED_PROXY_HEADER,
    trusted_proxy_value,
)
from uns_graphql.edge_api.router import identity_headers
from uns_graphql.edge_api.service import EdgeManagementService

from test.edge_api.conftest import TEST_EDGE, enroll_edge


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_forged_identity_header_without_trusted_proxy_rejected(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    response = await client.post(
        "/api/edge/v1/session",
        headers={
            EDGE_ID_HEADER: TEST_EDGE,
            EDGE_PURPOSE_HEADER: "management",
            EDGE_SERIAL_HEADER: enrolled["management_serial"],
        },
        json={"boot_id": "boot-1"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "missing_trusted_proxy"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_public_backend_bypass_without_proxy_marker_rejected(client: AsyncClient):
    response = await client.get("/api/edge/v1/configuration")
    assert response.status_code == 401
    assert response.json()["error"] == "missing_trusted_proxy"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_wrong_certificate_purpose_rejected(
    edge_service: EdgeManagementService,
    client: AsyncClient,
    csrs,
):
    enrolled = await enroll_edge(edge_service, client, TEST_EDGE, *csrs)
    response = await client.post(
        "/api/edge/v1/session",
        headers=identity_headers(TEST_EDGE, purpose="mqtt", serial=enrolled["mqtt_serial"]),
        json={"boot_id": "boot-1"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "invalid_purpose"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_incomplete_proxy_identity_rejected(client: AsyncClient):
    response = await client.post(
        "/api/edge/v1/session",
        headers={TRUSTED_PROXY_HEADER: trusted_proxy_value(), EDGE_ID_HEADER: TEST_EDGE},
        json={"boot_id": "boot-1"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "forged_identity_header"
