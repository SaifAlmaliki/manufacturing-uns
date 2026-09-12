"""Shared fixtures for publication API tests."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from uns_config.publication_http import HttpPublicationRoute
from uns_config.publication_routes import PublicationRoute, SchemaPair
from uns_model.publication_outbox import InMemoryOutboxBackend, Outbox

from uns_graphql.publication_api.identity import publisher_identity_headers
from uns_graphql.publication_api.router import create_publication_router
from uns_graphql.publication_api.service import PublicationApiConfig, PublicationIngressService

TEST_PRINCIPAL = "plant-a-lims-publisher"
TEST_SERIAL = "pytest-publisher-serial"


def lims_http_route() -> HttpPublicationRoute:
    publication = PublicationRoute(
        topic_filter="Enterprise/PlantA/LIMS/results",
        source_id="plant-a/lims-01",
        source_application="lims",
        site_id="plant-01",
        wire_format="uns-publication-v1",
        allowed_schema_pairs=frozenset(
            {SchemaPair(payload_schema_id="lab-result", payload_schema_version="1")}
        ),
        default_schema_pair=None,
        content_type="application/json",
        event_kind="business_event",
        archive_eligible=True,
    )
    return HttpPublicationRoute(
        route_id="plant-a-lims",
        mqtt_topic="Enterprise/PlantA/LIMS/results",
        principal_id=TEST_PRINCIPAL,
        route=publication,
    )


@pytest.fixture
def publication_config():
    return PublicationApiConfig(
        routes=(lims_http_route(),),
        global_budget_bytes=1_048_576,
        principal_budget_bytes=262_144,
    )


@pytest.fixture
def publication_backend():
    return InMemoryOutboxBackend()


@pytest.fixture
def publication_service(publication_config, publication_backend):
    outbox = Outbox(memory=publication_backend, global_budget_bytes=1_048_576, principal_budget_bytes=262_144)
    return PublicationIngressService(outbox=outbox, config=publication_config)


@pytest_asyncio.fixture
async def publication_app(publication_service: PublicationIngressService):
    app = FastAPI()
    app.include_router(create_publication_router(publication_service))
    return app


@pytest_asyncio.fixture
async def publication_client(publication_app: FastAPI):
    transport = ASGITransport(app=publication_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def publisher_headers(**overrides) -> dict[str, str]:
    headers = publisher_identity_headers(TEST_PRINCIPAL, serial=TEST_SERIAL)
    headers.update(overrides)
    return headers
