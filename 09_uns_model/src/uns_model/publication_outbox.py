"""Durable HTTPS publication outbox with idempotency and byte budgets."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text

from uns_config.events import EnvelopeError
from uns_config.publication_http import HttpPublicationRoute
from uns_config.publications import (
    assert_admission_envelope_fits,
    content_digest,
    wrapper_bytes_for_http_admission,
)
from uns_model.engine import Database

ReceiptStatus = Literal["queued", "broker_accepted", "failed"]
DEFAULT_GLOBAL_BUDGET_BYTES = 1_073_741_824
DEFAULT_PRINCIPAL_BUDGET_BYTES = 134_217_728
DEFAULT_TERMINAL_RETENTION = timedelta(days=7)
DEFAULT_LEASE_DURATION = timedelta(seconds=60)
MAX_LEASE_BATCH = 100
MAX_ACTIVE_LEASE_BYTES = 8 * 1024 * 1024
MAX_RETRY_ATTEMPTS = 8
TERMINAL_ERROR_CODES = frozenset({"auth_failed", "route_misconfigured", "forbidden_route"})


class OutboxError(Exception):
    def __init__(self, reason: str, status_code: int, detail: str = "") -> None:
        self.reason = reason
        self.status_code = status_code
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Receipt:
    receipt_id: str
    principal_id: str
    route_id: str
    status: ReceiptStatus
    content_digest: str
    mqtt_topic: str
    byte_size: int
    created_at: datetime
    updated_at: datetime
    broker_accepted_at: datetime | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class OutboxLease:
    holder_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LeasedOutboxRecord:
    receipt_id: str
    principal_id: str
    route_id: str
    mqtt_topic: str
    wrapper_bytes: bytes
    byte_size: int
    lease: OutboxLease


@dataclass
class InMemoryOutboxBackend:
    receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    budgets: dict[str, int] = field(default_factory=lambda: {"global": 0})
    fail_admit: bool = False


class Outbox:
    def __init__(
        self,
        database: Database | None = None,
        *,
        memory: InMemoryOutboxBackend | None = None,
        global_budget_bytes: int = DEFAULT_GLOBAL_BUDGET_BYTES,
        principal_budget_bytes: int = DEFAULT_PRINCIPAL_BUDGET_BYTES,
        terminal_retention: timedelta = DEFAULT_TERMINAL_RETENTION,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if database is None and memory is None:
            raise ValueError("database or memory backend is required")
        self._database = database
        self._memory = memory
        self._global_budget_bytes = global_budget_bytes
        self._principal_budget_bytes = principal_budget_bytes
        self._terminal_retention = terminal_retention
        self._now = now or (lambda: datetime.now(UTC))

    async def admit(
        self,
        principal_id: str,
        route: HttpPublicationRoute,
        idempotency_key: str,
        body: bytes,
        metadata: dict[str, Any],
        *,
        occurred_at: datetime | None = None,
    ) -> Receipt:
        if principal_id != route.principal_id:
            raise OutboxError("forbidden_route", 403, route.route_id)
        if not idempotency_key:
            raise OutboxError("missing_idempotency_key", 400)
        digest = content_digest(body, metadata)
        now = self._now()
        receipt_id = str(uuid.uuid4())
        wrapper_bytes = wrapper_bytes_for_http_admission(
            route=route.route,
            body=body,
            receipt_id=uuid.UUID(receipt_id),
            occurred_at=occurred_at,
        )
        try:
            assert_admission_envelope_fits(
                route=route.route,
                mqtt_topic=route.mqtt_topic,
                wrapper_bytes=wrapper_bytes,
                received_at=now,
            )
        except EnvelopeError as exc:
            if exc.reason == "oversize":
                raise OutboxError("oversize", 413) from exc
            raise OutboxError(exc.reason, 400, str(exc)) from exc

        byte_size = len(wrapper_bytes) + _metadata_overhead(metadata)
        if self._memory is not None:
            return self._admit_memory(
                principal_id=principal_id,
                route=route,
                idempotency_key=idempotency_key,
                digest=digest,
                receipt_id=receipt_id,
                wrapper_bytes=wrapper_bytes,
                byte_size=byte_size,
                metadata=metadata,
                occurred_at=occurred_at,
                now=now,
            )

        try:
            return await self._admit_sql(
                principal_id=principal_id,
                route=route,
                idempotency_key=idempotency_key,
                digest=digest,
                receipt_id=receipt_id,
                wrapper_bytes=wrapper_bytes,
                byte_size=byte_size,
                metadata=metadata,
                occurred_at=occurred_at,
                now=now,
            )
        except OutboxError:
            raise
        except Exception as exc:
            raise OutboxError("database_unavailable", 503, str(exc)) from exc

    async def get_receipt(self, receipt_id: str, principal_id: str) -> Receipt:
        if self._memory is not None:
            record = self._memory.receipts.get(receipt_id)
            if record is None or record["principal_id"] != principal_id:
                raise OutboxError("receipt_not_found", 404)
            return _receipt_from_record(record)
        async with self._database.session() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT receipt_id, principal_id, route_id, status, content_digest,
                               mqtt_topic, byte_size, created_at, updated_at,
                               broker_accepted_at, error_code
                        FROM publications.outbox
                        WHERE receipt_id = CAST(:receipt_id AS UUID)
                          AND principal_id = :principal_id
                        """
                    ),
                    {"receipt_id": receipt_id, "principal_id": principal_id},
                )
            ).one_or_none()
        if row is None:
            raise OutboxError("receipt_not_found", 404)
        return _receipt_from_row(row)

    async def lease_batch(self, worker_id: str, limit: int) -> list[LeasedOutboxRecord]:
        bounded = min(limit, MAX_LEASE_BATCH)
        now = self._now()
        expires_at = now + DEFAULT_LEASE_DURATION
        if self._memory is not None:
            return self._lease_batch_memory(worker_id, bounded, now, expires_at)
        async with self._database.begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT receipt_id, principal_id, route_id, mqtt_topic,
                               wrapper_bytes, byte_size
                        FROM publications.outbox
                        WHERE status = 'queued'
                          AND next_attempt_at <= :now
                          AND (lease_expires_at IS NULL OR lease_expires_at <= :now)
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT :limit
                        """
                    ),
                    {"now": now, "limit": bounded},
                )
            ).all()
            leased: list[LeasedOutboxRecord] = []
            active_bytes = 0
            for row in rows:
                if active_bytes + int(row.byte_size) > MAX_ACTIVE_LEASE_BYTES:
                    break
                await connection.execute(
                    text(
                        """
                        UPDATE publications.outbox
                        SET lease_holder = :holder_id,
                            lease_expires_at = :expires_at,
                            updated_at = :now
                        WHERE receipt_id = :receipt_id
                        """
                    ),
                    {
                        "holder_id": worker_id,
                        "expires_at": expires_at,
                        "now": now,
                        "receipt_id": row.receipt_id,
                    },
                )
                active_bytes += int(row.byte_size)
                leased.append(
                    LeasedOutboxRecord(
                        receipt_id=str(row.receipt_id),
                        principal_id=str(row.principal_id),
                        route_id=str(row.route_id),
                        mqtt_topic=str(row.mqtt_topic),
                        wrapper_bytes=bytes(row.wrapper_bytes),
                        byte_size=int(row.byte_size),
                        lease=OutboxLease(holder_id=worker_id, expires_at=expires_at),
                    )
                )
        return leased

    async def confirm_broker(self, receipt_id: str, lease: OutboxLease) -> None:
        now = self._now()
        if self._memory is not None:
            record = self._memory.receipts.get(receipt_id)
            if record is None or record.get("lease_holder") != lease.holder_id:
                raise OutboxError("lease_lost", 409)
            record["status"] = "broker_accepted"
            record["broker_accepted_at"] = now
            record["updated_at"] = now
            record["lease_holder"] = None
            record["lease_expires_at"] = None
            return
        async with self._database.begin() as connection:
            updated = (
                await connection.execute(
                    text(
                        """
                        UPDATE publications.outbox
                        SET status = 'broker_accepted',
                            broker_accepted_at = :now,
                            updated_at = :now,
                            lease_holder = NULL,
                            lease_expires_at = NULL
                        WHERE receipt_id = CAST(:receipt_id AS UUID)
                          AND lease_holder = :holder_id
                          AND status = 'queued'
                        """
                    ),
                    {"receipt_id": receipt_id, "holder_id": lease.holder_id, "now": now},
                )
            ).rowcount
        if updated != 1:
            raise OutboxError("lease_lost", 409)

    async def retry(self, receipt_id: str, lease: OutboxLease, error_code: str) -> None:
        now = self._now()
        if error_code in TERMINAL_ERROR_CODES:
            await self._mark_failed(receipt_id, lease, error_code, now)
            return
        if self._memory is not None:
            record = self._memory.receipts.get(receipt_id)
            if record is None or record.get("lease_holder") != lease.holder_id:
                raise OutboxError("lease_lost", 409)
            retry_count = int(record.get("retry_count", 0)) + 1
            if retry_count >= MAX_RETRY_ATTEMPTS:
                record["status"] = "failed"
                record["error_code"] = error_code
            else:
                delay = min(300, 2 ** retry_count)
                record["next_attempt_at"] = now + timedelta(seconds=delay)
                record["retry_count"] = retry_count
            record["lease_holder"] = None
            record["lease_expires_at"] = None
            record["updated_at"] = now
            return
        async with self._database.begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT retry_count
                        FROM publications.outbox
                        WHERE receipt_id = CAST(:receipt_id AS UUID)
                          AND lease_holder = :holder_id
                          AND status = 'queued'
                        FOR UPDATE
                        """
                    ),
                    {"receipt_id": receipt_id, "holder_id": lease.holder_id},
                )
            ).one_or_none()
            if row is None:
                raise OutboxError("lease_lost", 409)
            retry_count = int(row.retry_count) + 1
            if retry_count >= MAX_RETRY_ATTEMPTS:
                await connection.execute(
                    text(
                        """
                        UPDATE publications.outbox
                        SET status = 'failed',
                            error_code = :error_code,
                            updated_at = :now,
                            lease_holder = NULL,
                            lease_expires_at = NULL,
                            terminal_at = :now
                        WHERE receipt_id = CAST(:receipt_id AS UUID)
                        """
                    ),
                    {"receipt_id": receipt_id, "error_code": error_code, "now": now},
                )
                return
            delay = min(300, 2 ** retry_count)
            await connection.execute(
                text(
                    """
                    UPDATE publications.outbox
                    SET retry_count = :retry_count,
                        next_attempt_at = :next_attempt_at,
                        updated_at = :now,
                        lease_holder = NULL,
                        lease_expires_at = NULL
                    WHERE receipt_id = CAST(:receipt_id AS UUID)
                    """
                ),
                {
                    "receipt_id": receipt_id,
                    "retry_count": retry_count,
                    "next_attempt_at": now + timedelta(seconds=delay),
                    "now": now,
                },
            )

    async def _mark_failed(
        self,
        receipt_id: str,
        lease: OutboxLease,
        error_code: str,
        now: datetime,
    ) -> None:
        if self._memory is not None:
            record = self._memory.receipts.get(receipt_id)
            if record is None or record.get("lease_holder") != lease.holder_id:
                raise OutboxError("lease_lost", 409)
            record["status"] = "failed"
            record["error_code"] = error_code
            record["lease_holder"] = None
            record["lease_expires_at"] = None
            record["updated_at"] = now
            return
        async with self._database.begin() as connection:
            updated = (
                await connection.execute(
                    text(
                        """
                        UPDATE publications.outbox
                        SET status = 'failed',
                            error_code = :error_code,
                            updated_at = :now,
                            lease_holder = NULL,
                            lease_expires_at = NULL,
                            terminal_at = :now
                        WHERE receipt_id = CAST(:receipt_id AS UUID)
                          AND lease_holder = :holder_id
                        """
                    ),
                    {
                        "receipt_id": receipt_id,
                        "error_code": error_code,
                        "holder_id": lease.holder_id,
                        "now": now,
                    },
                )
            ).rowcount
        if updated != 1:
            raise OutboxError("lease_lost", 409)

    def _admit_memory(
        self,
        *,
        principal_id: str,
        route: HttpPublicationRoute,
        idempotency_key: str,
        digest: str,
        receipt_id: str,
        wrapper_bytes: bytes,
        byte_size: int,
        metadata: dict[str, Any],
        occurred_at: datetime | None,
        now: datetime,
    ) -> Receipt:
        if self._memory.fail_admit:
            raise OutboxError("database_unavailable", 503)
        self._purge_expired_idempotency(now)
        key = (principal_id, route.route_id, idempotency_key)
        existing = self._memory.idempotency.get(key)
        if existing is not None:
            if existing["content_digest"] != digest:
                raise OutboxError("content_conflict", 409)
            return _receipt_from_record(self._memory.receipts[existing["receipt_id"]])
        self._reserve_budget_memory(principal_id, byte_size)
        record = {
            "receipt_id": receipt_id,
            "principal_id": principal_id,
            "route_id": route.route_id,
            "status": "queued",
            "content_digest": digest,
            "mqtt_topic": route.mqtt_topic,
            "wrapper_bytes": wrapper_bytes,
            "byte_size": byte_size,
            "metadata": metadata,
            "occurred_at": occurred_at,
            "created_at": now,
            "updated_at": now,
            "broker_accepted_at": None,
            "error_code": None,
            "retry_count": 0,
            "next_attempt_at": now,
            "lease_holder": None,
            "lease_expires_at": None,
        }
        self._memory.receipts[receipt_id] = record
        self._memory.idempotency[key] = {
            "receipt_id": receipt_id,
            "content_digest": digest,
            "expires_at": now + self._terminal_retention,
        }
        return _receipt_from_record(record)

    async def _admit_sql(
        self,
        *,
        principal_id: str,
        route: HttpPublicationRoute,
        idempotency_key: str,
        digest: str,
        receipt_id: str,
        wrapper_bytes: bytes,
        byte_size: int,
        metadata: dict[str, Any],
        occurred_at: datetime | None,
        now: datetime,
    ) -> Receipt:
        async with self._database.begin() as connection:
            await connection.execute(
                text(
                    """
                    DELETE FROM publications.idempotency_keys
                    WHERE expires_at <= :now
                    """
                ),
                {"now": now},
            )
            existing = (
                await connection.execute(
                    text(
                        """
                        SELECT receipt_id, content_digest
                        FROM publications.idempotency_keys
                        WHERE principal_id = :principal_id
                          AND route_id = :route_id
                          AND idempotency_key = :idempotency_key
                        FOR UPDATE
                        """
                    ),
                    {
                        "principal_id": principal_id,
                        "route_id": route.route_id,
                        "idempotency_key": idempotency_key,
                    },
                )
            ).one_or_none()
            if existing is not None:
                if str(existing.content_digest) != digest:
                    raise OutboxError("content_conflict", 409)
                row = (
                    await connection.execute(
                        text(
                            """
                            SELECT receipt_id, principal_id, route_id, status, content_digest,
                                   mqtt_topic, byte_size, created_at, updated_at,
                                   broker_accepted_at, error_code
                            FROM publications.outbox
                            WHERE receipt_id = :receipt_id
                            """
                        ),
                        {"receipt_id": existing.receipt_id},
                    )
                ).one()
                return _receipt_from_row(row)

            await self._reserve_budget_sql(connection, principal_id, byte_size, now)
            await connection.execute(
                text(
                    """
                    INSERT INTO publications.outbox (
                        receipt_id, principal_id, route_id, idempotency_key, content_digest,
                        mqtt_topic, wrapper_bytes, byte_size, metadata, occurred_at,
                        status, created_at, updated_at, next_attempt_at
                    ) VALUES (
                        CAST(:receipt_id AS UUID), :principal_id, :route_id, :idempotency_key,
                        :content_digest, :mqtt_topic, :wrapper_bytes, :byte_size,
                        CAST(:metadata AS JSONB), :occurred_at, 'queued', :now, :now, :now
                    )
                    """
                ),
                {
                    "receipt_id": receipt_id,
                    "principal_id": principal_id,
                    "route_id": route.route_id,
                    "idempotency_key": idempotency_key,
                    "content_digest": digest,
                    "mqtt_topic": route.mqtt_topic,
                    "wrapper_bytes": wrapper_bytes,
                    "byte_size": byte_size,
                    "metadata": _json_dumps(metadata),
                    "occurred_at": occurred_at,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO publications.idempotency_keys (
                        principal_id, route_id, idempotency_key, receipt_id,
                        content_digest, expires_at
                    ) VALUES (
                        :principal_id, :route_id, :idempotency_key,
                        CAST(:receipt_id AS UUID), :content_digest, :expires_at
                    )
                    """
                ),
                {
                    "principal_id": principal_id,
                    "route_id": route.route_id,
                    "idempotency_key": idempotency_key,
                    "receipt_id": receipt_id,
                    "content_digest": digest,
                    "expires_at": now + self._terminal_retention,
                },
            )
        return Receipt(
            receipt_id=receipt_id,
            principal_id=principal_id,
            route_id=route.route_id,
            status="queued",
            content_digest=digest,
            mqtt_topic=route.mqtt_topic,
            byte_size=byte_size,
            created_at=now,
            updated_at=now,
        )

    async def _reserve_budget_sql(
        self,
        connection,
        principal_id: str,
        byte_size: int,
        now: datetime,
    ) -> None:
        await connection.execute(
            text(
                """
                INSERT INTO publications.budget_reservations (scope, reserved_bytes, updated_at)
                VALUES ('global', 0, :now)
                ON CONFLICT (scope) DO NOTHING
                """
            ),
            {"now": now},
        )
        principal_scope = f"principal:{principal_id}"
        await connection.execute(
            text(
                """
                INSERT INTO publications.budget_reservations (scope, reserved_bytes, updated_at)
                VALUES (:scope, 0, :now)
                ON CONFLICT (scope) DO NOTHING
                """
            ),
            {"scope": principal_scope, "now": now},
        )
        global_row = (
            await connection.execute(
                text(
                    """
                    SELECT reserved_bytes
                    FROM publications.budget_reservations
                    WHERE scope = 'global'
                    FOR UPDATE
                    """
                )
            )
        ).one()
        principal_row = (
            await connection.execute(
                text(
                    """
                    SELECT reserved_bytes
                    FROM publications.budget_reservations
                    WHERE scope = :scope
                    FOR UPDATE
                    """
                ),
                {"scope": principal_scope},
            )
        ).one()
        if int(global_row.reserved_bytes) + byte_size > self._global_budget_bytes:
            raise OutboxError("capacity_exhausted", 503)
        if int(principal_row.reserved_bytes) + byte_size > self._principal_budget_bytes:
            raise OutboxError("capacity_exhausted", 503)
        await connection.execute(
            text(
                """
                UPDATE publications.budget_reservations
                SET reserved_bytes = reserved_bytes + :byte_size, updated_at = :now
                WHERE scope = 'global'
                """
            ),
            {"byte_size": byte_size, "now": now},
        )
        await connection.execute(
            text(
                """
                UPDATE publications.budget_reservations
                SET reserved_bytes = reserved_bytes + :byte_size, updated_at = :now
                WHERE scope = :scope
                """
            ),
            {"scope": principal_scope, "byte_size": byte_size, "now": now},
        )

    def _reserve_budget_memory(self, principal_id: str, byte_size: int) -> None:
        principal_scope = f"principal:{principal_id}"
        global_used = self._memory.budgets.get("global", 0)
        principal_used = self._memory.budgets.get(principal_scope, 0)
        if global_used + byte_size > self._global_budget_bytes:
            raise OutboxError("capacity_exhausted", 503)
        if principal_used + byte_size > self._principal_budget_bytes:
            raise OutboxError("capacity_exhausted", 503)
        self._memory.budgets["global"] = global_used + byte_size
        self._memory.budgets[principal_scope] = principal_used + byte_size

    def _purge_expired_idempotency(self, now: datetime) -> None:
        expired = [
            key
            for key, value in self._memory.idempotency.items()
            if value["expires_at"] <= now
        ]
        for key in expired:
            self._memory.idempotency.pop(key, None)

    def _lease_batch_memory(
        self,
        worker_id: str,
        limit: int,
        now: datetime,
        expires_at: datetime,
    ) -> list[LeasedOutboxRecord]:
        candidates = [
            record
            for record in self._memory.receipts.values()
            if record["status"] == "queued"
            and record["next_attempt_at"] <= now
            and (record["lease_expires_at"] is None or record["lease_expires_at"] <= now)
        ]
        candidates.sort(key=lambda item: item["created_at"])
        leased: list[LeasedOutboxRecord] = []
        active_bytes = 0
        for record in candidates[:limit]:
            if active_bytes + int(record["byte_size"]) > MAX_ACTIVE_LEASE_BYTES:
                break
            record["lease_holder"] = worker_id
            record["lease_expires_at"] = expires_at
            active_bytes += int(record["byte_size"])
            leased.append(
                LeasedOutboxRecord(
                    receipt_id=record["receipt_id"],
                    principal_id=record["principal_id"],
                    route_id=record["route_id"],
                    mqtt_topic=record["mqtt_topic"],
                    wrapper_bytes=bytes(record["wrapper_bytes"]),
                    byte_size=int(record["byte_size"]),
                    lease=OutboxLease(holder_id=worker_id, expires_at=expires_at),
                )
            )
        return leased


def _metadata_overhead(metadata: dict[str, Any]) -> int:
    return len(_json_dumps(metadata))


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _receipt_from_record(record: dict[str, Any]) -> Receipt:
    return Receipt(
        receipt_id=str(record["receipt_id"]),
        principal_id=str(record["principal_id"]),
        route_id=str(record["route_id"]),
        status=record["status"],
        content_digest=str(record["content_digest"]),
        mqtt_topic=str(record["mqtt_topic"]),
        byte_size=int(record["byte_size"]),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        broker_accepted_at=record.get("broker_accepted_at"),
        error_code=record.get("error_code"),
    )


def _receipt_from_row(row) -> Receipt:
    return Receipt(
        receipt_id=str(row.receipt_id),
        principal_id=str(row.principal_id),
        route_id=str(row.route_id),
        status=row.status,
        content_digest=str(row.content_digest),
        mqtt_topic=str(row.mqtt_topic),
        byte_size=int(row.byte_size),
        created_at=row.created_at,
        updated_at=row.updated_at,
        broker_accepted_at=row.broker_accepted_at,
        error_code=row.error_code,
    )
