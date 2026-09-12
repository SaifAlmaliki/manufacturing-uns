"""Unit tests for the durable publication outbox."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime

import pytest

from uns_config.publication_http import HttpPublicationRoute
from uns_config.publication_routes import PublicationRoute, SchemaPair
from uns_model.publication_outbox import InMemoryOutboxBackend, Outbox, OutboxError


def _route(route_id: str = "plant-a-lims") -> HttpPublicationRoute:
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
        route_id=route_id,
        mqtt_topic="Enterprise/PlantA/LIMS/results",
        principal_id="plant-a-lims-publisher",
        route=publication,
    )


@pytest.fixture
def outbox():
    frozen = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    backend = InMemoryOutboxBackend()
    return Outbox(
        memory=backend,
        global_budget_bytes=1_048_576,
        principal_budget_bytes=262_144,
        now=lambda: frozen,
    ), backend


def _metadata() -> dict:
    return {"route_id": "plant-a-lims", "wire_format": "uns-publication-v1"}


@pytest.mark.asyncio
async def test_exact_bytes_preserved_whitespace_binary_and_empty(outbox):
    service, backend = outbox
    route = _route()
    cases = [b"A", b" \t\n", b"\x00\xff", b""]
    for index, body in enumerate(cases):
        receipt = await service.admit(
            route.principal_id,
            route,
            f"key-{index}",
            body,
            _metadata(),
        )
        wrapper = backend.receipts[receipt.receipt_id]["wrapper_bytes"]
        payload = json.loads(wrapper.decode("utf-8"))
        decoded = base64.b64decode(payload["original_payload_base64"], validate=True)
        assert decoded == body


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_same_receipt(outbox):
    service, _backend = outbox
    route = _route()
    first = await service.admit(route.principal_id, route, "order-42", b"A", _metadata())
    second = await service.admit(route.principal_id, route, "order-42", b"A", _metadata())
    assert first.receipt_id == second.receipt_id


@pytest.mark.asyncio
async def test_content_conflict_returns_409(outbox):
    service, _backend = outbox
    route = _route()
    await service.admit(route.principal_id, route, "order-42", b"A", _metadata())
    with pytest.raises(OutboxError, match="content_conflict") as exc:
        await service.admit(route.principal_id, route, "order-42", b"B", _metadata())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_oversize_envelope_rejected_with_413(outbox):
    service, _backend = outbox
    route = _route()
    huge = b"x" * 900_000
    with pytest.raises(OutboxError, match="oversize") as exc:
        await service.admit(route.principal_id, route, "huge", huge, _metadata())
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_database_failure_returns_503_without_202(outbox):
    service, backend = outbox
    backend.fail_admit = True
    route = _route()
    with pytest.raises(OutboxError, match="database_unavailable") as exc:
        await service.admit(route.principal_id, route, "order-42", b"A", _metadata())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_capacity_exhaustion_returns_503():
    backend = InMemoryOutboxBackend()
    service = Outbox(
        memory=backend,
        global_budget_bytes=2_000,
        principal_budget_bytes=1_000,
        now=lambda: datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
    )
    route = _route()
    body = b"x" * 200
    await service.admit(route.principal_id, route, "one", body, _metadata())
    with pytest.raises(OutboxError, match="capacity_exhausted") as exc:
        await service.admit(route.principal_id, route, "two", body, _metadata())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_worker_crash_before_confirm_releases_lease_for_retry(outbox):
    service, backend = outbox
    route = _route()
    receipt = await service.admit(route.principal_id, route, "order-42", b"A", _metadata())
    leased = await service.lease_batch("worker-a", 1)
    assert leased[0].receipt_id == receipt.receipt_id
    backend.receipts[receipt.receipt_id]["lease_expires_at"] = datetime(2000, 1, 1, tzinfo=UTC)
    retried = await service.lease_batch("worker-b", 1)
    assert retried[0].wrapper_bytes == leased[0].wrapper_bytes


@pytest.mark.asyncio
async def test_broker_callback_failure_does_not_mark_broker_accepted(outbox):
    service, _backend = outbox
    route = _route()
    receipt = await service.admit(route.principal_id, route, "order-42", b"A", _metadata())
    leased = await service.lease_batch("worker-a", 1)
    await service.retry(leased[0].receipt_id, leased[0].lease, "broker_timeout")
    stored = await service.get_receipt(receipt.receipt_id, route.principal_id)
    assert stored.status == "queued"


@pytest.mark.asyncio
async def test_concurrent_duplicate_keys_yield_one_receipt(outbox):
    service, _backend = outbox
    route = _route()

    async def admit_once() -> str:
        receipt = await service.admit(route.principal_id, route, "order-42", b"A", _metadata())
        return receipt.receipt_id

    results = await asyncio.gather(admit_once(), admit_once())
    assert results[0] == results[1]
