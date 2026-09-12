"""Connectivity management job status subscription."""

from __future__ import annotations

import asyncio
import logging
import typing

import strawberry

from uns_graphql.auth.require import OPC_PROBE_ROLES, require_role
from uns_graphql.queries.connectivity import _job_service
from uns_graphql.type.connectivity import ConnectivityJobType, connectivity_job_from_record

LOGGER = logging.getLogger(__name__)


@strawberry.type(description="Subscribe to edge management job lifecycle updates.")
class Subscription:
    @strawberry.subscription(
        description="Yield connectivity job status until the job reaches a terminal state."
    )
    async def connectivity_job_status(
        self,
        info: strawberry.Info,
        job_id: str,
    ) -> typing.AsyncGenerator[ConnectivityJobType]:
        require_role(info, OPC_PROBE_ROLES)
        terminal = {"completed", "failed", "expired"}
        while True:
            record = await _job_service().get_job(job_id)
            if record is None:
                raise ValueError(f"No connectivity job with id {job_id!r}")
            yield connectivity_job_from_record(record)
            if record.status in terminal:
                break
            await asyncio.sleep(1.0)

    @classmethod
    async def on_shutdown(cls):
        """Subscriptions own no process-wide resources."""
