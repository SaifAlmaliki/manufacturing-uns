"""Shared fixtures for edge management API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from uns_model.edge_repository import EdgeRepository
from uns_model.edge_secrets import EdgeKeyMaterial, EdgeKeyRing, EdgeSecretStore
from uns_model.engine import Database
from uns_model.model_config import ModelConfig

from uns_graphql.edge_api.enrollment import EnrollmentRateLimiter, revoke_device
from uns_graphql.edge_api.issuer import EdgeCertificateIssuer, generate_authority, generate_csr
from uns_graphql.edge_api.router import create_edge_router, identity_headers
from uns_graphql.edge_api.service import EdgeManagementService

TEST_EDGE = "pytest-edge-api"
TEST_EDGE_OTHER = "pytest-edge-api-other"


@pytest.fixture
def authority():
    return generate_authority()


@pytest.fixture
def issuer(authority):
    return EdgeCertificateIssuer(authority)


@pytest.fixture
def secret_store():
    key_ring = EdgeKeyRing.from_key_material(
        EdgeKeyMaterial("edge-secrets-v1", b"k" * 32),
        active_key_id="edge-secrets-v1",
    )
    return EdgeSecretStore(key_ring)


@pytest.fixture
def frozen_now():
    return datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


async def _require_edge_schema(database: Database) -> None:
    async with database.begin() as connection:
        jobs = (await connection.execute(text("SELECT to_regclass('edge.jobs')"))).scalar()
        devices = (await connection.execute(text("SELECT to_regclass('edge.devices')"))).scalar()
    if jobs is None or devices is None:
        pytest.fail(
            "Edge catalog tables are missing. Apply Asset Model migrations first: "
            "`uv run uns_model_setup --skip-seed --skip-oee-import`."
        )


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def database():
    config = ModelConfig.from_settings()
    assert config.is_valid()
    db = Database.from_config(config)
    await _require_edge_schema(db)
    yield db
    await db.dispose()


async def _clean(database: Database) -> None:
    async with database.begin() as connection:
        for edge_id in (TEST_EDGE, TEST_EDGE_OTHER):
            await connection.execute(
                text("DELETE FROM edge.jobs WHERE edge_id = :edge_id"),
                {"edge_id": edge_id},
            )
            await connection.execute(
                text("DELETE FROM edge.devices WHERE edge_id = :edge_id"),
                {"edge_id": edge_id},
            )


@pytest_asyncio.fixture(loop_scope="session")
async def edge_service(database: Database, issuer, secret_store, frozen_now):
    await _clean(database)
    repo = EdgeRepository(database, now=lambda: frozen_now)
    service = EdgeManagementService(
        database,
        repo,
        issuer,
        secret_store,
        now=lambda: frozen_now,
        rate_limiter=EnrollmentRateLimiter(limit_per_minute=100),
    )
    await repo.register_device(TEST_EDGE)
    await repo.register_device(TEST_EDGE_OTHER)
    yield service
    await _clean(database)


@pytest_asyncio.fixture(loop_scope="session")
async def edge_app(edge_service: EdgeManagementService):
    app = FastAPI()
    app.include_router(create_edge_router(edge_service))
    return app


@pytest_asyncio.fixture(loop_scope="session")
async def client(edge_app: FastAPI):
    transport = ASGITransport(app=edge_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def csrs():
    management_csr, _ = generate_csr("ignored-management")
    mqtt_csr, _ = generate_csr("ignored-mqtt")
    return management_csr, mqtt_csr


async def enroll_edge(
    service: EdgeManagementService,
    client: AsyncClient,
    edge_id: str,
    management_csr: str,
    mqtt_csr: str,
) -> dict:
    token = await service.create_enrollment_token(edge_id)
    response = await client.post(
        "/api/edge/v1/enroll",
        json={
            "enrollment_token": token,
            "management_csr": management_csr,
            "mqtt_csr": mqtt_csr,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def open_session(
    client: AsyncClient,
    edge_id: str,
    management_serial: str,
    boot_id: str = "boot-1",
) -> dict:
    response = await client.post(
        "/api/edge/v1/session",
        headers=identity_headers(edge_id, serial=management_serial),
        json={"boot_id": boot_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def lease_headers(session_payload: dict) -> dict[str, str]:
    return {
        "x-edge-boot-id": session_payload["boot_id"],
        "x-edge-lease-generation": str(session_payload["generation"]),
        "x-edge-lease-token": session_payload["lease_token"],
    }
