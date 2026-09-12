"""Cloud-only worker that drains the publication outbox to central MQTT."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from uns_model.engine import Database
from uns_model.model_config import ModelConfig
from uns_model.publication_outbox import (
    DEFAULT_LEASE_DURATION,
    LeasedOutboxRecord,
    Outbox,
    OutboxLease,
)

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 1.0


class MqttPublishClient(Protocol):
    async def publish_qos1(self, topic: str, payload: bytes) -> None: ...


class PublicationOutboxWorker:
    def __init__(
        self,
        outbox: Outbox,
        mqtt_client: MqttPublishClient,
        *,
        worker_id: str | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._outbox = outbox
        self._mqtt_client = mqtt_client
        self._worker_id = worker_id or str(uuid.uuid4())
        self._sleep = sleep or asyncio.sleep

    async def run_forever(self) -> None:
        LOGGER.info("publication outbox worker started holder_id=%s", self._worker_id)
        while True:
            try:
                leased = await self._outbox.lease_batch(self._worker_id, 100)
                for record in leased:
                    await self._process_record(record)
            except Exception:  # noqa: BLE001
                LOGGER.exception("publication outbox worker tick failed")
            await self._sleep(POLL_INTERVAL_SECONDS)

    async def _process_record(self, record: LeasedOutboxRecord) -> None:
        try:
            await self._mqtt_client.publish_qos1(record.mqtt_topic, record.wrapper_bytes)
            await self._outbox.confirm_broker(record.receipt_id, record.lease)
            LOGGER.info(
                "publication broker accepted receipt_id=%s topic=%s",
                record.receipt_id,
                record.mqtt_topic,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "publication publish failed receipt_id=%s error=%s",
                record.receipt_id,
                exc,
            )
            await self._outbox.retry(record.receipt_id, record.lease, _error_code(exc))


def _error_code(exc: Exception) -> str:
    message = str(exc).lower()
    if "auth" in message or "forbidden" in message:
        return "auth_failed"
    if "timeout" in message:
        return "broker_timeout"
    return "broker_error"


async def run_worker(outbox: Outbox, mqtt_client: MqttPublishClient) -> None:
    worker = PublicationOutboxWorker(outbox, mqtt_client)
    await worker.run_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from uns_graphql.publication_api.mqtt_client import AiomqttPublicationClient

    config = ModelConfig.from_settings()
    if not config.is_valid():
        raise SystemExit("database configuration is invalid")
    database = Database.from_config(config)
    outbox = Outbox(database)
    mqtt_client = AiomqttPublicationClient()
    try:
        asyncio.run(run_worker(outbox, mqtt_client))
    finally:
        asyncio.run(database.dispose())


if __name__ == "__main__":
    main()
