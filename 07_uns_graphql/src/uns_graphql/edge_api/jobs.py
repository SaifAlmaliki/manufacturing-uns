"""Bounded outbound management jobs for edge discovery and connection tests."""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from uns_config.edge_jobs import (
    BROWSE_PROTOCOLS,
    JOB_EXECUTION,
    JOB_EXPIRY,
    JOB_KIND_BROWSE_TAGS,
    JOB_KIND_TEST_CONNECTION,
    JOB_KINDS,
    JOB_RESULT_RETENTION,
    MAX_PENDING_JOBS_PER_EDGE,
    MAX_RESULT_BYTES,
    parse_cursor_offset,
)
from uns_model.edge_repository import EdgeLeaseRejected, EdgeRepository
from uns_model.edge_tables import EdgeJob
from uns_model.engine import Database
from uns_model.tables import ConnectivityServer

from uns_graphql.edge_api.identity import VerifiedEdgeIdentity
from uns_graphql.edge_api.service import EdgeManagementService, EdgeServiceError, LeaseHeaders


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    edge_id: str
    connection_id: str
    config_revision: int
    kind: str
    status: str
    cursor: str | None
    node_id: str | None
    expires_at: datetime
    result_payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None


def _job_record(row: EdgeJob) -> JobRecord:
    payload = dict(row.result_payload) if isinstance(row.result_payload, dict) else None
    return JobRecord(
        job_id=row.job_id,
        edge_id=row.edge_id,
        connection_id=row.connection_id,
        config_revision=row.config_revision,
        kind=row.job_type,
        status=row.status,
        cursor=row.cursor,
        node_id=row.node_id,
        expires_at=row.expires_at,
        result_payload=payload,
        error_code=row.error_code,
        error_detail=row.error_detail,
    )


class EdgeJobService:
    """Create, poll, and complete bounded management jobs for enrolled edges."""

    def __init__(
        self,
        database: Database,
        repository: EdgeRepository,
        management_service: EdgeManagementService,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._repository = repository
        self._management = management_service
        self._now = now or (lambda: datetime.now(UTC))

    async def create_job(
        self,
        *,
        edge_id: str,
        connection_id: str,
        kind: str,
        config_revision: int,
        node_id: str | None = None,
        cursor: str | None = None,
    ) -> JobRecord:
        if kind not in JOB_KINDS:
            raise EdgeServiceError("invalid_job_kind", 400, kind)
        now = self._now()
        async with self._database.session() as session:
            desired = await self._repository.latest_desired(edge_id)
            if desired is None or desired.revision != config_revision:
                raise EdgeServiceError("revision_mismatch", 409)
            server = (
                await session.execute(
                    select(ConnectivityServer).where(
                        ConnectivityServer.id == connection_id,
                        ConnectivityServer.edge_id == edge_id,
                    )
                )
            ).scalar_one_or_none()
            if server is None:
                raise EdgeServiceError("connection_not_found", 404, connection_id)
            if kind == JOB_KIND_BROWSE_TAGS and server.protocol not in BROWSE_PROTOCOLS:
                raise EdgeServiceError("discovery_unsupported", 400, server.protocol)
            pending = (
                await session.execute(
                    select(func.count())
                    .select_from(EdgeJob)
                    .where(
                        EdgeJob.edge_id == edge_id,
                        EdgeJob.status.in_(("queued", "running")),
                    )
                )
            ).scalar_one()
            if pending >= MAX_PENDING_JOBS_PER_EDGE:
                raise EdgeServiceError("pending_jobs_limit", 429)
            job_id = str(uuid.uuid4())
            row = EdgeJob(
                job_id=job_id,
                edge_id=edge_id,
                connection_id=connection_id,
                config_revision=config_revision,
                job_type=kind,
                status="queued",
                expires_at=now + JOB_EXPIRY,
                cursor=cursor,
                node_id=node_id,
            )
            session.add(row)
            await session.commit()
            return _job_record(row)

    async def get_job(self, job_id: str) -> JobRecord | None:
        async with self._database.session() as session:
            row = (await session.execute(select(EdgeJob).where(EdgeJob.job_id == job_id))).scalar_one_or_none()
            if row is None:
                return None
            await self._expire_if_needed(session, row)
            await session.commit()
            return _job_record(row)

    async def poll_jobs(self, identity: VerifiedEdgeIdentity, lease: LeaseHeaders) -> list[JobRecord]:
        now = self._now()
        async with self._database.session() as session:
            await self._management.verify_identity_record(session, identity)
            edge_lease = _lease_from_headers(identity.edge_id, lease, now)
            try:
                await self._repository._validate_lease(session, edge_lease)  # noqa: SLF001
            except EdgeLeaseRejected as exc:
                raise EdgeServiceError("lease_rejected", 409, str(exc)) from exc

            await session.execute(
                update(EdgeJob)
                .where(
                    EdgeJob.edge_id == identity.edge_id,
                    EdgeJob.status.in_(("queued", "running")),
                    EdgeJob.expires_at <= now,
                )
                .values(status="expired", updated_at=now)
            )

            running = (
                await session.execute(
                    select(EdgeJob).where(
                        EdgeJob.edge_id == identity.edge_id,
                        EdgeJob.status == "running",
                    )
                )
            ).scalar_one_or_none()
            if running is not None:
                if running.execution_deadline is not None and running.execution_deadline <= now:
                    running.status = "expired"
                    running.updated_at = now
                    await session.flush()
                else:
                    await session.commit()
                    return []

            queued = (
                await session.execute(
                    select(EdgeJob)
                    .where(
                        EdgeJob.edge_id == identity.edge_id,
                        EdgeJob.status == "queued",
                        EdgeJob.expires_at > now,
                    )
                    .order_by(EdgeJob.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if queued is None:
                await session.commit()
                return []

            queued.status = "running"
            queued.lease_generation = lease.generation
            queued.started_at = now
            queued.execution_deadline = now + JOB_EXECUTION
            queued.updated_at = now
            await session.commit()
            return [_job_record(queued)]

    async def submit_result(
        self,
        identity: VerifiedEdgeIdentity,
        lease: LeaseHeaders,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> JobRecord:
        if status not in {"completed", "failed"}:
            raise EdgeServiceError("invalid_result_status", 400, status)
        encoded = json.dumps(result or {}, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(encoded) > MAX_RESULT_BYTES:
            raise EdgeServiceError("result_too_large", 413)

        now = self._now()
        async with self._database.session() as session:
            await self._management.verify_identity_record(session, identity)
            edge_lease = _lease_from_headers(identity.edge_id, lease, now)
            try:
                await self._repository._validate_lease(session, edge_lease)  # noqa: SLF001
            except EdgeLeaseRejected as exc:
                raise EdgeServiceError("lease_rejected", 409, str(exc)) from exc

            row = (
                await session.execute(
                    select(EdgeJob).where(EdgeJob.job_id == job_id).with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise EdgeServiceError("job_not_found", 404, job_id)
            if row.edge_id != identity.edge_id:
                raise EdgeServiceError("scope_violation", 403)
            if row.status in {"completed", "failed"}:
                await session.commit()
                return _job_record(row)
            if row.status == "expired" or row.expires_at <= now:
                row.status = "expired"
                row.updated_at = now
                await session.commit()
                raise EdgeServiceError("job_expired", 409)
            if row.lease_generation is not None and row.lease_generation != lease.generation:
                raise EdgeServiceError("lease_mismatch", 409)
            desired = await self._repository.latest_desired(identity.edge_id)
            if desired is None or row.config_revision != desired.revision:
                raise EdgeServiceError("revision_mismatch", 409)

            row.status = status
            row.completed_at = now
            row.updated_at = now
            row.result_payload = result
            row.error_code = error_code
            row.error_detail = error_detail
            row.result_retained_until = now + JOB_RESULT_RETENTION
            await session.commit()
            if row.job_type == JOB_KIND_TEST_CONNECTION:
                await self._record_connection_test(row, status, result)
            return _job_record(row)

    async def _record_connection_test(
        self,
        row: EdgeJob,
        status: str,
        result: dict[str, Any] | None,
    ) -> None:
        from uns_model.connectivity import ConnectivityRepository

        payload = result or {}
        ok = status == "completed" and bool(payload.get("ok"))
        error = row.error_detail or payload.get("error_detail")
        repo = ConnectivityRepository(self._database)
        await repo.record_test(row.connection_id, ok=ok, error=error)

    async def _expire_if_needed(self, session, row: EdgeJob) -> None:
        now = self._now()
        if row.status in {"completed", "failed", "expired"}:
            if (
                row.result_retained_until is not None
                and row.result_retained_until <= now
                and row.status in {"completed", "failed"}
            ):
                row.result_payload = None
                row.updated_at = now
            return
        if row.expires_at <= now or (
            row.execution_deadline is not None and row.execution_deadline <= now and row.status == "running"
        ):
            row.status = "expired"
            row.updated_at = now


def _lease_from_headers(edge_id: str, lease: LeaseHeaders, expires_at: datetime):
    from uns_model.edge_repository import EdgeLease

    return EdgeLease(
        edge_id=edge_id,
        boot_id=lease.boot_id,
        generation=lease.generation,
        lease_token=lease.lease_token,
        expires_at=expires_at,
    )


def mint_cursor(offset: int) -> str:
    return secrets.token_urlsafe(16) + f".{offset}"
