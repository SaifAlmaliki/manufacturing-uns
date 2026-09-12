"""Route release staging, worker lease failover, and stale activation tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uns_config.route_release import route_release_digest

from uns_graphql.edge_api.route_release import (
    InMemoryRouteReleaseBackend,
    RouteReleaseService,
    RouteReleaseServiceError,
)


def _release_document(revision: int = 1) -> dict:
    route = {
        "topic_filter": "Enterprise/PlantA/LIMS/results",
        "source_id": "plant-a/lims-01",
        "source_application": "lims",
        "site_id": "plant-01",
        "wire_format": "uns-publication-v1",
        "allowed_schema_pairs": [
            {"payload_schema_id": "lab-result", "payload_schema_version": "1"}
        ],
        "default_schema_pair": None,
        "content_type": "application/json",
        "event_kind": "business_event",
        "archive_eligible": True,
    }
    document = {
        "revision": revision,
        "publication_routes": [route],
        "principal_grants": [
            {
                "principal_id": "edge-01-bridge",
                "publish_filters": [route["topic_filter"]],
                "deny_subscribe": True,
            }
        ],
    }
    document["digest"] = route_release_digest(document)
    return document


class FakeBrokerAdmin:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.revision: int | None = None

    async def activate_grants(self, release) -> int:
        self.revision = release.revision
        return release.revision

    async def current_revision(self) -> int | None:
        return self.revision

    async def is_available(self) -> bool:
        return self.available


class FakeMapperControl:
    def __init__(self) -> None:
        self.revision: int | None = None
        self.queued: list = []

    async def enqueue_release(self, release) -> None:
        self.queued.append(release)
        self.revision = release.revision

    async def current_revision(self) -> int | None:
        return self.revision


@pytest.fixture
def route_service():
    broker = FakeBrokerAdmin()
    mapper = FakeMapperControl()
    frozen = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    service = RouteReleaseService(
        memory=InMemoryRouteReleaseBackend(),
        broker_admin=broker,
        mapper_control=mapper,
        now=lambda: frozen,
    )
    return service, broker, mapper


@pytest.mark.asyncio
async def test_stage_and_activate_release(route_service):
    service, broker, mapper = route_service
    staged = await service.stage_release(_release_document())
    assert staged.status == "pending"
    lease = await service.acquire_worker_lease("worker-a")
    snapshot = await service.activate_pending_release(lease)
    assert snapshot is not None
    assert snapshot.phase == "active"
    assert broker.revision == staged.revision
    assert mapper.revision == staged.revision
    assert await service.edge_release_ready(staged.revision)


@pytest.mark.asyncio
async def test_worker_failover_rejects_second_holder(route_service):
    service, _, _ = route_service
    await service.acquire_worker_lease("worker-a")
    with pytest.raises(RouteReleaseServiceError, match="lease_held"):
        await service.acquire_worker_lease("worker-b")


@pytest.mark.asyncio
async def test_stale_activation_report_rejected(route_service):
    service, _, _ = route_service
    await service.stage_release(_release_document(revision=1))
    lease = await service.acquire_worker_lease("worker-a")
    await service.activate_pending_release(lease)
    await service.stage_release(_release_document(revision=2))
    lease = await service.acquire_worker_lease("worker-a")
    await service.activate_pending_release(lease)
    with pytest.raises(RouteReleaseServiceError, match="stale_activation_report"):
        await service.report_component_activation(
            component="mapper",
            revision=1,
            digest=_release_document(1)["digest"],
        )


@pytest.mark.asyncio
async def test_waiting_for_routes_when_broker_unavailable(route_service):
    service, broker, mapper = route_service
    broker.available = False
    await service.stage_release(_release_document())
    lease = await service.acquire_worker_lease("worker-a")
    snapshot = await service.activate_pending_release(lease)
    assert snapshot.phase == "waiting_for_routes"
    assert mapper.revision == 1
    assert not await service.edge_release_ready(1)
