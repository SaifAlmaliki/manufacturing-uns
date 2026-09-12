"""Cloud-only route release worker owning broker/mapper activation."""

from __future__ import annotations

import asyncio
import logging
import uuid

from uns_model.engine import Database
from uns_model.model_config import ModelConfig

from uns_graphql.edge_api.route_release import RouteReleaseService

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 2.0


async def run_worker(service: RouteReleaseService) -> None:
    holder_id = str(uuid.uuid4())
    lease = await service.acquire_worker_lease(holder_id)
    LOGGER.info("route release worker acquired lease holder_id=%s", lease.holder_id)
    while True:
        try:
            lease = await service.renew_worker_lease(lease)
            snapshot = await service.activate_pending_release(lease)
            if snapshot is not None and snapshot.phase == "active":
                LOGGER.info(
                    "route release active revision=%s digest=%s",
                    snapshot.release_revision,
                    snapshot.release_digest,
                )
        except Exception:  # noqa: BLE001
            LOGGER.exception("route release activation tick failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = ModelConfig.from_settings()
    if not config.is_valid():
        raise SystemExit("database configuration is invalid")
    database = Database.from_config(config)
    service = RouteReleaseService(database)
    try:
        asyncio.run(run_worker(service))
    finally:
        asyncio.run(database.dispose())


if __name__ == "__main__":
    main()
