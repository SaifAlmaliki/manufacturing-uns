"""HTTPS publication ingress contract tests."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from test.publication_api.conftest import publisher_headers


@pytest.mark.asyncio
async def test_post_returns_202_and_receipt(publication_client: AsyncClient):
    body = b'{"result": 4.2}'
    response = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=body,
        headers={
            **publisher_headers(),
            "Idempotency-Key": "order-42",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["route_id"] == "plant-a-lims"


@pytest.mark.asyncio
async def test_duplicate_key_same_body_returns_same_receipt(publication_client: AsyncClient):
    headers = {**publisher_headers(), "Idempotency-Key": "order-42"}
    first = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=b"A",
        headers=headers,
    )
    second = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=b"A",
        headers=headers,
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["receipt_id"] == second.json()["receipt_id"]


@pytest.mark.asyncio
async def test_content_conflict_returns_409(publication_client: AsyncClient):
    headers = {**publisher_headers(), "Idempotency-Key": "order-42"}
    await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=b"A",
        headers=headers,
    )
    conflict = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=b"B",
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "content_conflict"


@pytest.mark.asyncio
async def test_missing_idempotency_key_rejected(publication_client: AsyncClient):
    response = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=b"A",
        headers=publisher_headers(),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_unknown_route_returns_404(publication_client: AsyncClient):
    response = await publication_client.post(
        "/api/publications/v1/routes/unknown",
        content=b"A",
        headers={**publisher_headers(), "Idempotency-Key": "k1"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_forged_identity_rejected(publication_client: AsyncClient):
    response = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=b"A",
        headers={"Idempotency-Key": "k1", "X-Publisher-Id": "other"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_conflicting_route_header_rejected(publication_client: AsyncClient):
    response = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=b"A",
        headers={
            **publisher_headers(),
            "Idempotency-Key": "k1",
            "X-Source-Application": "mes",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_receipt_requires_matching_principal(publication_client: AsyncClient):
    post = await publication_client.post(
        "/api/publications/v1/routes/plant-a-lims",
        content=json.dumps({"result": 1}).encode("utf-8"),
        headers={**publisher_headers(), "Idempotency-Key": "order-99"},
    )
    receipt_id = post.json()["receipt_id"]
    get = await publication_client.get(
        f"/api/publications/v1/receipts/{receipt_id}",
        headers=publisher_headers(),
    )
    assert get.status_code == 200
    assert get.json()["receipt_id"] == receipt_id
