"""Enrollment token hashing and transactional CSR digest reservation."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uns_model.edge_tables import EdgeCertificate, EdgeDevice, EdgeEnrollmentAttempt

ENROLLMENT_TOKEN_VALIDITY = timedelta(minutes=15)
MAX_ENROLLMENT_BODY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class EnrollmentToken:
    token: str
    token_hash: str


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    edge_id: str
    management_certificate_chain: tuple[str, ...]
    mqtt_certificate_chain: tuple[str, ...]
    management_subject: str
    mqtt_subject: str
    management_serial: str
    mqtt_serial: str


class EnrollmentError(Exception):
    def __init__(self, reason: str, status_code: int, detail: str = "") -> None:
        self.reason = reason
        self.status_code = status_code
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csr_digest(csr_pem: str) -> str:
    normalized = csr_pem.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def mint_enrollment_token() -> EnrollmentToken:
    token = secrets.token_urlsafe(32)
    return EnrollmentToken(token=token, token_hash=hash_token(token))


class EnrollmentRateLimiter:
    """Simple in-memory enrollment rate limiter for tests and single-process deploys."""

    def __init__(self, *, limit_per_minute: int = 10) -> None:
        self._limit = limit_per_minute
        self._buckets: dict[str, list[float]] = {}

    def check(self, client_key: str, now: float) -> None:
        window_start = now - 60.0
        events = [ts for ts in self._buckets.get(client_key, []) if ts >= window_start]
        if len(events) >= self._limit:
            raise EnrollmentError("rate_limited", 429)
        events.append(now)
        self._buckets[client_key] = events


async def create_enrollment_attempt(
    session: AsyncSession,
    *,
    edge_id: str,
    token_hash: str,
    expires_at: datetime,
) -> EdgeEnrollmentAttempt:
    attempt = EdgeEnrollmentAttempt(
        edge_id=edge_id,
        token_hash=token_hash,
        expires_at=expires_at,
        status="pending",
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def load_enrollment_result(
    session: AsyncSession,
    edge_id: str,
    issuer_subject: Callable[[str, str], str],
    authority_pem: str,
) -> EnrollmentResult:
    from uns_graphql.edge_api.issuer import certificate_serial_hex

    chains: dict[str, tuple[str, ...]] = {}
    subjects: dict[str, str] = {}
    serials: dict[str, str] = {}
    for purpose in ("management", "mqtt"):
        row = (
            await session.execute(
                select(EdgeCertificate)
                .where(
                    EdgeCertificate.edge_id == edge_id,
                    EdgeCertificate.purpose == purpose,
                    EdgeCertificate.revoked_at.is_(None),
                )
                .order_by(EdgeCertificate.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            raise EnrollmentError("certificates_missing", 503)
        chains[purpose] = (row.pem, authority_pem)
        subjects[purpose] = issuer_subject(edge_id, purpose)
        serials[purpose] = certificate_serial_hex(row.pem)
    return EnrollmentResult(
        edge_id=edge_id,
        management_certificate_chain=chains["management"],
        mqtt_certificate_chain=chains["mqtt"],
        management_subject=subjects["management"],
        mqtt_subject=subjects["mqtt"],
        management_serial=serials["management"],
        mqtt_serial=serials["mqtt"],
    )


async def reserve_or_replay_enrollment(
    session: AsyncSession,
    attempt: EdgeEnrollmentAttempt,
    *,
    management_csr_digest: str,
    mqtt_csr_digest: str,
    now: datetime,
    issue_certificates: Callable[[], Awaitable[EnrollmentResult]],
    replay_certificates: Callable[[], Awaitable[EnrollmentResult]],
) -> EnrollmentResult:
    """Consume a token once; replay the same CSR digests within the token window."""
    edge_id = attempt.edge_id

    if attempt.expires_at <= now:
        raise EnrollmentError("expired_token", 401)

    if attempt.status == "reserved":
        raise EnrollmentError("enrollment_in_progress", 409)

    if attempt.status == "consumed":
        if (
            attempt.management_csr_digest == management_csr_digest
            and attempt.mqtt_csr_digest == mqtt_csr_digest
        ):
            return await replay_certificates()
        raise EnrollmentError("token_reused", 409, "different CSR digests")

    if attempt.management_csr_digest and attempt.management_csr_digest != management_csr_digest:
        raise EnrollmentError("csr_mismatch", 409)
    if attempt.mqtt_csr_digest and attempt.mqtt_csr_digest != mqtt_csr_digest:
        raise EnrollmentError("csr_mismatch", 409)

    attempt.management_csr_digest = management_csr_digest
    attempt.mqtt_csr_digest = mqtt_csr_digest
    attempt.status = "reserved"
    await session.flush()

    result = await issue_certificates()

    attempt.status = "consumed"
    attempt.consumed_at = now
    device = (
        await session.execute(select(EdgeDevice).where(EdgeDevice.edge_id == edge_id).with_for_update())
    ).scalar_one()
    device.status = "enrolled"
    await session.flush()
    return result


async def store_certificate(
    session: AsyncSession,
    *,
    certificate_id: str,
    edge_id: str,
    purpose: str,
    pem: str,
    not_before: datetime,
    not_after: datetime,
) -> EdgeCertificate:
    row = EdgeCertificate(
        certificate_id=certificate_id,
        edge_id=edge_id,
        purpose=purpose,
        pem=pem,
        not_before=not_before,
        not_after=not_after,
    )
    session.add(row)
    await session.flush()
    return row


async def active_certificate(
    session: AsyncSession,
    *,
    edge_id: str,
    purpose: str,
    serial_hex: str,
    now: datetime,
) -> EdgeCertificate | None:
    from uns_graphql.edge_api.issuer import certificate_serial_hex

    rows = (
        await session.execute(
            select(EdgeCertificate).where(
                EdgeCertificate.edge_id == edge_id,
                EdgeCertificate.purpose == purpose,
                EdgeCertificate.revoked_at.is_(None),
            )
        )
    ).scalars()
    for row in rows:
        if certificate_serial_hex(row.pem) == serial_hex and row.not_after > now:
            return row
    return None


async def revoke_device(session: AsyncSession, edge_id: str, now: datetime) -> None:
    await session.execute(
        update(EdgeDevice).where(EdgeDevice.edge_id == edge_id).values(status="revoked")
    )
    await session.execute(
        update(EdgeCertificate)
        .where(
            EdgeCertificate.edge_id == edge_id,
            EdgeCertificate.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.flush()


async def ensure_device_active(session: AsyncSession, edge_id: str) -> EdgeDevice:
    device = (
        await session.execute(select(EdgeDevice).where(EdgeDevice.edge_id == edge_id).with_for_update())
    ).scalar_one_or_none()
    if device is None:
        raise EnrollmentError("unknown_edge", 403, edge_id)
    if device.status == "revoked":
        raise EnrollmentError("device_revoked", 403)
    if device.status not in {"registered", "enrolled"}:
        raise EnrollmentError("device_not_enrollable", 403, device.status)
    return device


def utc_now() -> datetime:
    return datetime.now(UTC)
