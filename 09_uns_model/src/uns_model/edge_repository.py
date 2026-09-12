"""Edge desired-state catalog with optimistic concurrency and lease fencing."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from uns_config.edge_config_digest import configuration_digest
from uns_config.edge_contracts import EdgeReport as EdgeReportContract
from uns_model.engine import Database
from uns_model.edge_tables import (
    EdgeAuditEvent,
    EdgeDesiredConfiguration,
    EdgeDevice,
    EdgeManagementLease,
    EdgeReport,
    EdgeUserGrant,
)
from uns_model.tables import ConnectivityServer

LEASE_DURATION = timedelta(seconds=120)
REPORT_RETENTION = timedelta(days=30)


class EdgeRepositoryError(Exception):
    """Stable edge catalog failure."""

    reason: str = "edge_repository_error"

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


class EdgeRevisionConflict(EdgeRepositoryError):
    def __init__(self, detail: str = "") -> None:
        super().__init__("revision_conflict", detail)


class EdgeLeaseRejected(EdgeRepositoryError):
    def __init__(self, detail: str = "") -> None:
        super().__init__("lease_rejected", detail)


class EdgeScopeViolation(EdgeRepositoryError):
    def __init__(self, detail: str = "") -> None:
        super().__init__("scope_violation", detail)


@dataclass(frozen=True, slots=True)
class EdgeIdentity:
    edge_id: str


@dataclass(frozen=True, slots=True)
class EdgeLease:
    edge_id: str
    boot_id: str
    generation: int
    lease_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SavedDesiredConfiguration:
    edge_id: str
    revision: int
    digest: str
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EdgeStatusSnapshot:
    """Public edge lifecycle fields separate from connection probe state."""

    edge_id: str
    desired_revision: int
    applied_revision: int
    applied_phase: str
    last_seen: datetime | None
    capabilities: dict[str, Any]


class EdgeRepository:
    """SQL-backed edge catalog with explicit edge scope on every read and write."""

    def __init__(self, database: Database, *, now: Callable[[], datetime] | None = None) -> None:
        self._database = database
        self._now = now or (lambda: datetime.now(UTC))

    async def register_device(self, edge_id: str, *, site_id: str | None = None, display_name: str = "") -> EdgeDevice:
        async with self._database.session() as session:
            device = EdgeDevice(edge_id=edge_id, site_id=site_id, display_name=display_name or edge_id)
            session.add(device)
            await session.flush()
            return device

    async def save_desired(
        self,
        edge_id: str,
        expected_revision: int,
        document: dict[str, Any],
        *,
        actor: str | None = None,
        session: AsyncSession | None = None,
    ) -> SavedDesiredConfiguration:
        if session is None:
            async with self._database.session() as owned:
                return await self.save_desired(
                    edge_id,
                    expected_revision,
                    document,
                    actor=actor,
                    session=owned,
                )

        device = await self._lock_device(session, edge_id)
        if device.desired_head_revision != expected_revision:
            raise EdgeRevisionConflict(
                f"expected {expected_revision}, head is {device.desired_head_revision}"
            )

        payload = dict(document)
        payload["edge_id"] = edge_id
        payload["revision"] = expected_revision + 1
        payload["digest"] = configuration_digest(payload)
        new_revision = expected_revision + 1

        session.add(
            EdgeDesiredConfiguration(
                edge_id=edge_id,
                revision=new_revision,
                digest=payload["digest"],
                document=payload,
            )
        )
        device.desired_head_revision = new_revision
        session.add(
            EdgeAuditEvent(
                edge_id=edge_id,
                event_type="desired_saved",
                actor=actor,
                details={"revision": new_revision, "digest": payload["digest"]},
            )
        )
        await session.flush()
        return SavedDesiredConfiguration(edge_id, new_revision, payload["digest"], payload)

    async def latest_desired(self, edge_id: str) -> SavedDesiredConfiguration | None:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(EdgeDesiredConfiguration)
                    .where(EdgeDesiredConfiguration.edge_id == edge_id)
                    .order_by(EdgeDesiredConfiguration.revision.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return SavedDesiredConfiguration(row.edge_id, row.revision, row.digest, dict(row.document))

    async def acquire_lease(self, edge_id: str, boot_id: str) -> EdgeLease:
        async with self._database.session() as session:
            device = await self._lock_device(session, edge_id)
            now = self._now()
            generation = device.current_lease_generation + 1
            lease_token = secrets.token_urlsafe(32)
            expires_at = now + LEASE_DURATION
            await session.execute(
                update(EdgeManagementLease)
                .where(
                    EdgeManagementLease.edge_id == edge_id,
                    EdgeManagementLease.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            session.add(
                EdgeManagementLease(
                    edge_id=edge_id,
                    boot_id=boot_id,
                    generation=generation,
                    lease_token=lease_token,
                    expires_at=expires_at,
                )
            )
            device.current_lease_generation = generation
            await session.flush()
            return EdgeLease(edge_id, boot_id, generation, lease_token, expires_at)

    async def accept_report(
        self,
        identity: EdgeIdentity,
        lease: EdgeLease,
        report: EdgeReportContract,
    ) -> EdgeReport:
        if identity.edge_id != report.edge_id or lease.edge_id != report.edge_id:
            raise EdgeScopeViolation("report edge_id does not match identity or lease")

        async with self._database.session() as session:
            device = await self._lock_device(session, identity.edge_id)
            await self._validate_lease(session, lease)
            existing = (
                await session.execute(
                    select(EdgeReport).where(
                        EdgeReport.edge_id == report.edge_id,
                        EdgeReport.boot_id == report.boot_id,
                        EdgeReport.report_sequence == report.report_sequence,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing

            now = self._now()
            row = EdgeReport(
                edge_id=report.edge_id,
                boot_id=report.boot_id,
                report_sequence=report.report_sequence,
                desired_revision=report.desired_revision,
                applied_revision=report.applied_revision,
                applied_digest=report.applied_digest,
                phase=report.phase,
                payload=_report_payload(report),
                retained_until=now + REPORT_RETENTION,
            )
            session.add(row)

            if self._should_update_applied(device, report):
                device.latest_applied_revision = report.applied_revision
                device.latest_applied_digest = report.applied_digest
                device.latest_applied_phase = report.phase
                session.add(
                    EdgeAuditEvent(
                        edge_id=report.edge_id,
                        event_type="report_applied",
                        actor=lease.boot_id,
                        details={
                            "applied_revision": report.applied_revision,
                            "applied_digest": report.applied_digest,
                            "phase": report.phase,
                        },
                    )
                )
            await session.flush()
            return row

    async def assign_legacy(self, connection_id: str, edge_id: str) -> ConnectivityServer:
        async with self._database.session() as session:
            await self._ensure_device(session, edge_id)
            server = (
                await session.execute(
                    select(ConnectivityServer)
                    .where(ConnectivityServer.id == connection_id)
                    .options(selectinload(ConnectivityServer.tags))
                )
            ).scalar_one_or_none()
            if server is None:
                raise EdgeRepositoryError("connection_not_found", connection_id)
            if server.edge_id is not None and server.edge_id != edge_id:
                raise EdgeRepositoryError(
                    "edge_assignment_conflict",
                    f"{connection_id} is assigned to {server.edge_id}",
                )
            server.edge_id = edge_id
            session.add(
                EdgeAuditEvent(
                    edge_id=edge_id,
                    event_type="legacy_assigned",
                    details={"connection_id": connection_id},
                )
            )
            await session.flush()
            return server

    async def list_devices(self) -> list[EdgeDevice]:
        async with self._database.session() as session:
            return list((await session.execute(select(EdgeDevice).order_by(EdgeDevice.edge_id))).scalars())

    async def get_device(self, edge_id: str) -> EdgeDevice | None:
        async with self._database.session() as session:
            return (
                await session.execute(select(EdgeDevice).where(EdgeDevice.edge_id == edge_id))
            ).scalar_one_or_none()

    async def grant_user(self, edge_id: str, user_id: str) -> None:
        async with self._database.session() as session:
            await self._ensure_device(session, edge_id)
            session.add(EdgeUserGrant(edge_id=edge_id, user_id=user_id))
            await session.flush()

    async def revoke_user(self, edge_id: str, user_id: str) -> bool:
        async with self._database.session() as session:
            result = await session.execute(
                delete(EdgeUserGrant).where(
                    EdgeUserGrant.edge_id == edge_id,
                    EdgeUserGrant.user_id == user_id,
                )
            )
            return bool(result.rowcount)

    async def user_has_grant(self, edge_id: str, user_id: str) -> bool:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(EdgeUserGrant.user_id).where(
                        EdgeUserGrant.edge_id == edge_id,
                        EdgeUserGrant.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            return row is not None

    async def device_status(self, edge_id: str) -> EdgeStatusSnapshot | None:
        async with self._database.session() as session:
            device = (
                await session.execute(select(EdgeDevice).where(EdgeDevice.edge_id == edge_id))
            ).scalar_one_or_none()
            if device is None:
                return None
            last_report = (
                await session.execute(
                    select(EdgeReport)
                    .where(EdgeReport.edge_id == edge_id)
                    .order_by(EdgeReport.received_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            capabilities: dict[str, Any] = {}
            last_seen: datetime | None = None
            if last_report is not None:
                last_seen = last_report.received_at
                payload = last_report.payload or {}
                raw_capabilities = payload.get("capabilities")
                if isinstance(raw_capabilities, dict):
                    capabilities = dict(raw_capabilities)
            return EdgeStatusSnapshot(
                edge_id=edge_id,
                desired_revision=device.desired_head_revision,
                applied_revision=device.latest_applied_revision,
                applied_phase=device.latest_applied_phase,
                last_seen=last_seen,
                capabilities=capabilities,
            )

    async def revoke_device(self, edge_id: str) -> None:
        async with self._database.session() as session:
            device = await self._lock_device(session, edge_id)
            device.status = "revoked"
            now = self._now()
            await session.execute(
                update(EdgeManagementLease)
                .where(
                    EdgeManagementLease.edge_id == edge_id,
                    EdgeManagementLease.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            session.add(
                EdgeAuditEvent(
                    edge_id=edge_id,
                    event_type="device_revoked",
                    details={},
                )
            )
            await session.flush()

    async def _lock_device(self, session: AsyncSession, edge_id: str) -> EdgeDevice:
        await self._ensure_device(session, edge_id)
        device = (
            await session.execute(
                select(EdgeDevice).where(EdgeDevice.edge_id == edge_id).with_for_update()
            )
        ).scalar_one()
        return device

    async def _ensure_device(self, session: AsyncSession, edge_id: str) -> EdgeDevice:
        device = (
            await session.execute(select(EdgeDevice).where(EdgeDevice.edge_id == edge_id))
        ).scalar_one_or_none()
        if device is not None:
            return device
        device = EdgeDevice(edge_id=edge_id, display_name=edge_id)
        session.add(device)
        await session.flush()
        return device

    async def _validate_lease(self, session: AsyncSession, lease: EdgeLease) -> None:
        now = self._now()
        row = (
            await session.execute(
                select(EdgeManagementLease).where(
                    EdgeManagementLease.edge_id == lease.edge_id,
                    EdgeManagementLease.generation == lease.generation,
                    EdgeManagementLease.lease_token == lease.lease_token,
                )
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            raise EdgeLeaseRejected("lease is missing, revoked, or expired")
        if row.boot_id != lease.boot_id:
            raise EdgeLeaseRejected("boot_id does not match active lease")

    @staticmethod
    def _should_update_applied(device: EdgeDevice, report: EdgeReportContract) -> bool:
        if report.applied_revision > device.desired_head_revision:
            return False
        if report.applied_revision < device.latest_applied_revision:
            return False
        if (
            report.applied_revision == device.latest_applied_revision
            and report.applied_digest == device.latest_applied_digest
        ):
            return False
        return True


def _report_payload(report: EdgeReportContract) -> dict[str, Any]:
    return {
        "edge_id": report.edge_id,
        "boot_id": report.boot_id,
        "report_sequence": report.report_sequence,
        "desired_revision": report.desired_revision,
        "applied_revision": report.applied_revision,
        "applied_digest": report.applied_digest,
        "phase": report.phase,
        "adapter_results": list(report.adapter_results),
        "last_error_code": report.last_error_code,
        "versions": dict(report.versions),
        "capabilities": dict(report.capabilities),
    }
