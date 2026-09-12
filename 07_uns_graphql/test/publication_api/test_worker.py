"""Publication outbox worker tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uns_model.publication_outbox import InMemoryOutboxBackend, Outbox, OutboxError, OutboxLease

from uns_graphql.publication_api.worker import PublicationOutboxWorker

from test.publication_api.conftest import lims_http_route


class FakeMqttClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, bytes]] = []

    async def publish_qos1(self, topic: str, payload: bytes) -> None:
        if self.fail:
            raise TimeoutError("broker timeout")
        self.calls.append((topic, payload))


@pytest.mark.asyncio
async def test_worker_publishes_and_confirms_broker():
    backend = InMemoryOutboxBackend()
    outbox = Outbox(memory=backend)
    route = lims_http_route()
    receipt = await outbox.admit(route.principal_id, route, "order-42", b"A", {"route_id": route.route_id})
    mqtt = FakeMqttClient()
    worker = PublicationOutboxWorker(outbox, mqtt, worker_id="worker-a", sleep=lambda _s: None)
    leased = await outbox.lease_batch("worker-a", 1)
    await worker._process_record(leased[0])
    assert mqtt.calls == [(route.mqtt_topic, leased[0].wrapper_bytes)]
    stored = await outbox.get_receipt(receipt.receipt_id, route.principal_id)
    assert stored.status == "broker_accepted"


@pytest.mark.asyncio
async def test_worker_retry_on_mqtt_failure_keeps_identical_bytes():
    backend = InMemoryOutboxBackend()
    outbox = Outbox(memory=backend)
    route = lims_http_route()
    await outbox.admit(route.principal_id, route, "order-42", b"A", {"route_id": route.route_id})
    mqtt = FakeMqttClient(fail=True)
    worker = PublicationOutboxWorker(outbox, mqtt, worker_id="worker-a", sleep=lambda _s: None)
    leased = await outbox.lease_batch("worker-a", 1)
    original = leased[0].wrapper_bytes
    await worker._process_record(leased[0])
    backend.receipts[leased[0].receipt_id]["next_attempt_at"] = datetime(2000, 1, 1, tzinfo=UTC)
    backend.receipts[leased[0].receipt_id]["lease_expires_at"] = None
    retried = await outbox.lease_batch("worker-b", 1)
    assert retried[0].wrapper_bytes == original


@pytest.mark.asyncio
async def test_confirm_requires_active_lease():
    backend = InMemoryOutboxBackend()
    outbox = Outbox(memory=backend)
    route = lims_http_route()
    receipt = await outbox.admit(route.principal_id, route, "order-42", b"A", {"route_id": route.route_id})
    lease = OutboxLease(holder_id="other", expires_at=receipt.created_at)
    with pytest.raises(OutboxError, match="lease_lost"):
        await outbox.confirm_broker(receipt.receipt_id, lease)
