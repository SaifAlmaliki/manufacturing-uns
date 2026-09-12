"""Route release staging, activation barrier, and worker lease fencing."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import text

from uns_config.route_release import (
    ActivationSnapshot,
    ComponentActivation,
    RouteRelease,
    advance_activation,
    can_release_edge_configuration,
    route_release_from_dict,
)
from uns_model.engine import Database

WORKER_LEASE_NAME = "route_release_worker"
WORKER_LEASE_DURATION = timedelta(seconds=30)


class RouteReleaseServiceError(Exception):
    def __init__(self, reason: str, status_code: int, detail: str = "") -> None:
        self.reason = reason
        self.status_code = status_code
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


class BrokerAdminClient(Protocol):
    async def activate_grants(self, release: RouteRelease) -> int: ...

    async def current_revision(self) -> int | None: ...

    async def is_available(self) -> bool: ...


class MapperControlClient(Protocol):
    async def enqueue_release(self, release: RouteRelease) -> None: ...

    async def current_revision(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class WorkerLease:
    holder_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RouteReleaseRecord:
    revision: int
    digest: str
    status: str
    document: dict[str, Any]


@dataclass
class InMemoryRouteReleaseBackend:
    """Test and qualification harness backend without PostgreSQL."""

    releases: dict[int, dict[str, Any]] = field(default_factory=dict)
    release_status: dict[int, str] = field(default_factory=dict)
    activation: ActivationSnapshot = field(
        default_factory=lambda: ActivationSnapshot(
            release_revision=0,
            release_digest="",
            phase="pending",
            mapper=None,
            broker=None,
            drain_until_revision=None,
        )
    )
    lease_holder: str | None = None
    lease_expires: datetime | None = None


class RouteReleaseService:
    def __init__(
        self,
        database: Database | None = None,
        *,
        memory: InMemoryRouteReleaseBackend | None = None,
        broker_admin: BrokerAdminClient | None = None,
        mapper_control: MapperControlClient | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if database is None and memory is None:
            raise ValueError("database or memory backend is required")
        self._database = database
        self._memory = memory
        self._broker_admin = broker_admin
        self._mapper_control = mapper_control
        self._now = now or (lambda: datetime.now(UTC))

    async def stage_release(self, document: dict[str, Any]) -> RouteReleaseRecord:
        release = route_release_from_dict(document)
        if self._memory is not None:
            if release.revision in self._memory.releases:
                raise RouteReleaseServiceError("release_exists", 409, str(release.revision))
            self._memory.releases[release.revision] = document
            self._memory.release_status[release.revision] = "pending"
            return RouteReleaseRecord(
                revision=release.revision,
                digest=release.digest,
                status="pending",
                document=document,
            )
        async with self._database.session() as session:
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT revision
                        FROM routes.releases
                        WHERE revision = :revision OR digest = :digest
                        """
                    ),
                    {"revision": release.revision, "digest": release.digest},
                )
            ).first()
            if existing is not None:
                raise RouteReleaseServiceError("release_exists", 409, str(release.revision))
            await session.execute(
                text(
                    """
                    INSERT INTO routes.releases (revision, digest, document, status)
                    VALUES (:revision, :digest, CAST(:document AS JSONB), 'pending')
                    """
                ),
                {
                    "revision": release.revision,
                    "digest": release.digest,
                    "document": _json_document(release),
                },
            )
            await session.commit()
        return RouteReleaseRecord(
            revision=release.revision,
            digest=release.digest,
            status="pending",
            document=document,
        )

    async def get_activation_snapshot(self) -> ActivationSnapshot:
        if self._memory is not None:
            return self._memory.activation
        async with self._database.session() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT release_revision, release_digest, phase,
                               mapper_revision, mapper_digest,
                               broker_revision, broker_digest,
                               drain_until_revision
                        FROM routes.activation_state
                        WHERE state_id = 1
                        """
                    )
                )
            ).one()
        mapper = None
        if row.mapper_revision is not None and row.mapper_digest:
            mapper = ComponentActivation(
                revision=int(row.mapper_revision),
                digest=str(row.mapper_digest),
                activated_at=None,
                reported_at=None,
            )
        broker = None
        if row.broker_revision is not None and row.broker_digest:
            broker = ComponentActivation(
                revision=int(row.broker_revision),
                digest=str(row.broker_digest),
                activated_at=None,
                reported_at=None,
            )
        return ActivationSnapshot(
            release_revision=int(row.release_revision),
            release_digest=str(row.release_digest),
            phase=str(row.phase),
            mapper=mapper,
            broker=broker,
            drain_until_revision=(
                int(row.drain_until_revision) if row.drain_until_revision is not None else None
            ),
        )

    async def acquire_worker_lease(self, holder_id: str | None = None) -> WorkerLease:
        holder = holder_id or str(uuid.uuid4())
        now = self._now()
        expires_at = now + WORKER_LEASE_DURATION
        if self._memory is not None:
            if (
                self._memory.lease_holder is not None
                and self._memory.lease_expires is not None
                and self._memory.lease_expires > now
                and self._memory.lease_holder != holder
            ):
                raise RouteReleaseServiceError("lease_held", 409, self._memory.lease_holder)
            self._memory.lease_holder = holder
            self._memory.lease_expires = expires_at
            return WorkerLease(holder_id=holder, expires_at=expires_at)
        async with self._database.begin() as connection:
            current = (
                await connection.execute(
                    text(
                        """
                        SELECT holder_id, expires_at
                        FROM routes.worker_leases
                        WHERE lease_name = :lease_name
                        FOR UPDATE
                        """
                    ),
                    {"lease_name": WORKER_LEASE_NAME},
                )
            ).one_or_none()
            if current is not None and current.expires_at > now and current.holder_id != holder:
                raise RouteReleaseServiceError("lease_held", 409, str(current.holder_id))
            await connection.execute(
                text(
                    """
                    INSERT INTO routes.worker_leases (lease_name, holder_id, expires_at, updated_at)
                    VALUES (:lease_name, :holder_id, :expires_at, :updated_at)
                    ON CONFLICT (lease_name) DO UPDATE
                    SET holder_id = EXCLUDED.holder_id,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "lease_name": WORKER_LEASE_NAME,
                    "holder_id": holder,
                    "expires_at": expires_at,
                    "updated_at": now,
                },
            )
        return WorkerLease(holder_id=holder, expires_at=expires_at)

    async def renew_worker_lease(self, lease: WorkerLease) -> WorkerLease:
        now = self._now()
        expires_at = now + WORKER_LEASE_DURATION
        if self._memory is not None:
            if self._memory.lease_holder != lease.holder_id:
                raise RouteReleaseServiceError("lease_lost", 409)
            self._memory.lease_expires = expires_at
            return WorkerLease(holder_id=lease.holder_id, expires_at=expires_at)
        async with self._database.begin() as connection:
            current = (
                await connection.execute(
                    text(
                        """
                        SELECT holder_id
                        FROM routes.worker_leases
                        WHERE lease_name = :lease_name AND holder_id = :holder_id
                        FOR UPDATE
                        """
                    ),
                    {"lease_name": WORKER_LEASE_NAME, "holder_id": lease.holder_id},
                )
            ).one_or_none()
            if current is None:
                raise RouteReleaseServiceError("lease_lost", 409)
            await connection.execute(
                text(
                    """
                    UPDATE routes.worker_leases
                    SET expires_at = :expires_at, updated_at = :updated_at
                    WHERE lease_name = :lease_name AND holder_id = :holder_id
                    """
                ),
                {
                    "lease_name": WORKER_LEASE_NAME,
                    "holder_id": lease.holder_id,
                    "expires_at": expires_at,
                    "updated_at": now,
                },
            )
        return WorkerLease(holder_id=lease.holder_id, expires_at=expires_at)

    async def next_pending_release(self) -> RouteRelease | None:
        if self._memory is not None:
            for revision in sorted(self._memory.releases):
                if self._memory.release_status.get(revision) == "pending":
                    return route_release_from_dict(self._memory.releases[revision])
            return None
        async with self._database.session() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT document
                        FROM routes.releases
                        WHERE status = 'pending'
                        ORDER BY revision ASC
                        LIMIT 1
                        """
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        return route_release_from_dict(dict(row.document))

    async def activate_pending_release(self, lease: WorkerLease) -> ActivationSnapshot | None:
        release = await self.next_pending_release()
        if release is None:
            return await self.get_activation_snapshot()
        snapshot = await self.get_activation_snapshot()
        if snapshot.release_revision == release.revision and snapshot.phase == "active":
            return snapshot

        if self._mapper_control is not None:
            await self._mapper_control.enqueue_release(release)
            mapper_revision = await self._mapper_control.current_revision()
        else:
            mapper_revision = release.revision

        broker_available = True
        broker_revision = None
        if self._broker_admin is not None:
            broker_available = await self._broker_admin.is_available()
            if broker_available:
                broker_revision = await self._broker_admin.activate_grants(release)
        else:
            broker_revision = release.revision

        snapshot = advance_activation(
            snapshot if snapshot.release_revision == release.revision else ActivationSnapshot(
                release_revision=release.revision,
                release_digest=release.digest,
                phase="pending",
                mapper=None,
                broker=None,
                drain_until_revision=snapshot.release_revision if snapshot.release_revision else None,
            ),
            release,
            mapper_revision=mapper_revision,
            broker_revision=broker_revision,
            broker_available=broker_available,
            now=self._now(),
        )
        await self._persist_activation(snapshot, release_status="activating" if snapshot.phase != "active" else "active")
        await self.renew_worker_lease(lease)
        return snapshot

    async def report_component_activation(
        self,
        *,
        component: str,
        revision: int,
        digest: str,
    ) -> ActivationSnapshot:
        snapshot = await self.get_activation_snapshot()
        if snapshot.release_revision != revision:
            raise RouteReleaseServiceError("stale_activation_report", 409, str(revision))
        release = await self._release_by_revision(revision)
        if release.digest != digest:
            raise RouteReleaseServiceError("digest_mismatch", 409, digest)
        mapper_revision = revision if component == "mapper" else (
            snapshot.mapper.revision if snapshot.mapper is not None else None
        )
        broker_revision = revision if component == "broker" else (
            snapshot.broker.revision if snapshot.broker is not None else None
        )
        snapshot = advance_activation(
            snapshot,
            release,
            mapper_revision=mapper_revision,
            broker_revision=broker_revision,
            now=self._now(),
        )
        await self._persist_activation(
            snapshot,
            release_status="active" if snapshot.phase == "active" else "activating",
        )
        return snapshot

    async def edge_release_ready(self, required_revision: int) -> bool:
        snapshot = await self.get_activation_snapshot()
        return can_release_edge_configuration(snapshot, required_revision)

    async def _release_by_revision(self, revision: int) -> RouteRelease:
        if self._memory is not None:
            document = self._memory.releases.get(revision)
            if document is None:
                raise RouteReleaseServiceError("release_not_found", 404, str(revision))
            return route_release_from_dict(document)
        async with self._database.session() as session:
            row = (
                await session.execute(
                    text("SELECT document FROM routes.releases WHERE revision = :revision"),
                    {"revision": revision},
                )
            ).one_or_none()
        if row is None:
            raise RouteReleaseServiceError("release_not_found", 404, str(revision))
        return route_release_from_dict(dict(row.document))

    async def _persist_activation(self, snapshot: ActivationSnapshot, *, release_status: str) -> None:
        if self._memory is not None:
            self._memory.activation = snapshot
            self._memory.release_status[snapshot.release_revision] = release_status
            return
        async with self._database.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE routes.activation_state
                    SET release_revision = :release_revision,
                        release_digest = :release_digest,
                        phase = :phase,
                        mapper_revision = :mapper_revision,
                        mapper_digest = :mapper_digest,
                        broker_revision = :broker_revision,
                        broker_digest = :broker_digest,
                        drain_until_revision = :drain_until_revision,
                        updated_at = :updated_at
                    WHERE state_id = 1
                    """
                ),
                {
                    "release_revision": snapshot.release_revision,
                    "release_digest": snapshot.release_digest,
                    "phase": snapshot.phase,
                    "mapper_revision": snapshot.mapper.revision if snapshot.mapper else None,
                    "mapper_digest": snapshot.mapper.digest if snapshot.mapper else None,
                    "broker_revision": snapshot.broker.revision if snapshot.broker else None,
                    "broker_digest": snapshot.broker.digest if snapshot.broker else None,
                    "drain_until_revision": snapshot.drain_until_revision,
                    "updated_at": self._now(),
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE routes.releases
                    SET status = :status
                    WHERE revision = :revision
                    """
                ),
                {"status": release_status, "revision": snapshot.release_revision},
            )


def _json_document(release: RouteRelease) -> str:
    import json

    return json.dumps(
        {
            "revision": release.revision,
            "digest": release.digest,
            "publication_routes": [
                {
                    "topic_filter": route.topic_filter,
                    "source_id": route.source_id,
                    "source_application": route.source_application,
                    "site_id": route.site_id,
                    "wire_format": route.wire_format,
                    "allowed_schema_pairs": [
                        {
                            "payload_schema_id": pair.payload_schema_id,
                            "payload_schema_version": pair.payload_schema_version,
                        }
                        for pair in route.allowed_schema_pairs
                    ],
                    "default_schema_pair": (
                        {
                            "payload_schema_id": route.default_schema_pair.payload_schema_id,
                            "payload_schema_version": route.default_schema_pair.payload_schema_version,
                        }
                        if route.default_schema_pair is not None
                        else None
                    ),
                    "content_type": route.content_type,
                    "event_kind": route.event_kind,
                    "archive_eligible": route.archive_eligible,
                }
                for route in release.publication_routes
            ],
            "principal_grants": [
                {
                    "principal_id": grant.principal_id,
                    "publish_filters": list(grant.publish_filters),
                    "deny_subscribe": grant.deny_subscribe,
                }
                for grant in release.principal_grants
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
