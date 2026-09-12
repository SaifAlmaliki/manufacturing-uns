"""Edge management orchestration kept out of GraphQL resolvers."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uns_config.edge_contracts import EdgeReport as EdgeReportContract
from uns_model.edge_repository import (
    EdgeIdentity,
    EdgeLease,
    EdgeLeaseRejected,
    EdgeRepository,
    EdgeScopeViolation,
)
from uns_model.edge_secrets import EdgeSecretStore, EncryptedSecret
from uns_model.edge_tables import EdgeDevice, EdgeEnrollmentAttempt, EdgeSecretVersion
from uns_model.engine import Database

from uns_graphql.edge_api.enrollment import (
    ENROLLMENT_TOKEN_VALIDITY,
    EnrollmentError,
    EnrollmentRateLimiter,
    EnrollmentResult,
    active_certificate,
    create_enrollment_attempt,
    csr_digest,
    ensure_device_active,
    hash_token,
    load_enrollment_result,
    mint_enrollment_token,
    reserve_or_replay_enrollment,
    store_certificate,
)
from uns_graphql.edge_api.identity import VerifiedEdgeIdentity
from uns_graphql.edge_api.issuer import (
    EdgeCertificateIssuer,
    EdgeCertPurpose,
    IssuedCertificate,
    certificate_serial_hex,
)


class EdgeServiceError(Exception):
    def __init__(self, reason: str, status_code: int, detail: str = "") -> None:
        self.reason = reason
        self.status_code = status_code
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LeaseHeaders:
    boot_id: str
    generation: int
    lease_token: str


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    revision: int
    digest: str
    document: dict[str, Any]


class EdgeManagementService:
    def __init__(
        self,
        database: Database,
        repository: EdgeRepository,
        issuer: EdgeCertificateIssuer,
        secret_store: EdgeSecretStore | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        rate_limiter: EnrollmentRateLimiter | None = None,
    ) -> None:
        self._database = database
        self._repository = repository
        self._issuer = issuer
        self._secret_store = secret_store
        self._now = now or (lambda: datetime.now(UTC))
        self._rate_limiter = rate_limiter or EnrollmentRateLimiter()

    async def create_enrollment_token(self, edge_id: str) -> str:
        token = mint_enrollment_token()
        async with self._database.session() as session:
            await ensure_device_active(session, edge_id)
            await create_enrollment_attempt(
                session,
                edge_id=edge_id,
                token_hash=token.token_hash,
                expires_at=self._now() + ENROLLMENT_TOKEN_VALIDITY,
            )
            await session.commit()
        return token.token

    async def enroll(
        self,
        *,
        enrollment_token: str,
        management_csr: str,
        mqtt_csr: str,
        client_key: str,
    ) -> EnrollmentResult:
        self._rate_limiter.check(client_key, time.monotonic())
        token_hash = hash_token(enrollment_token)
        management_digest = csr_digest(management_csr)
        mqtt_digest = csr_digest(mqtt_csr)
        now = self._now()

        async with self._database.session() as session:
            attempt = (
                await session.execute(
                    select(EdgeEnrollmentAttempt)
                    .where(EdgeEnrollmentAttempt.token_hash == token_hash)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if attempt is None:
                raise EnrollmentError("invalid_token", 401)
            edge_id = attempt.edge_id
            await ensure_device_active(session, edge_id)

            async def issue_and_store() -> EnrollmentResult:
                management = self._issuer.issue_from_csr(
                    management_csr, edge_id=edge_id, purpose="management", now=now
                )
                mqtt = self._issuer.issue_from_csr(mqtt_csr, edge_id=edge_id, purpose="mqtt", now=now)
                await store_certificate(
                    session,
                    certificate_id=management.certificate_id,
                    edge_id=edge_id,
                    purpose="management",
                    pem=management.pem,
                    not_before=management.not_before,
                    not_after=management.not_after,
                )
                await store_certificate(
                    session,
                    certificate_id=mqtt.certificate_id,
                    edge_id=edge_id,
                    purpose="mqtt",
                    pem=mqtt.pem,
                    not_before=mqtt.not_before,
                    not_after=mqtt.not_after,
                )
                return EnrollmentResult(
                    edge_id=edge_id,
                    management_certificate_chain=management.chain_pem,
                    mqtt_certificate_chain=mqtt.chain_pem,
                    management_subject=management.subject,
                    mqtt_subject=mqtt.subject,
                    management_serial=certificate_serial_hex(management.pem),
                    mqtt_serial=certificate_serial_hex(mqtt.pem),
                )

            async def replay() -> EnrollmentResult:
                return await load_enrollment_result(
                    session,
                    edge_id,
                    self._issuer.derived_subject,
                    self._issuer._authority.certificate_pem,  # noqa: SLF001
                )

            result = await reserve_or_replay_enrollment(
                session,
                attempt,
                management_csr_digest=management_digest,
                mqtt_csr_digest=mqtt_digest,
                now=now,
                issue_certificates=issue_and_store,
                replay_certificates=replay,
            )
            await session.commit()
            return result

    async def verify_identity_record(
        self,
        session: AsyncSession,
        identity: VerifiedEdgeIdentity,
    ) -> EdgeDevice:
        device = await ensure_device_active(session, identity.edge_id)
        if device.status != "enrolled":
            raise EdgeServiceError("device_not_enrolled", 403)
        cert = await active_certificate(
            session,
            edge_id=identity.edge_id,
            purpose=identity.purpose,
            serial_hex=identity.certificate_serial,
            now=self._now(),
        )
        if cert is None:
            raise EdgeServiceError("expired_identity", 401)
        return device

    async def open_session(self, identity: VerifiedEdgeIdentity, boot_id: str) -> EdgeLease:
        async with self._database.session() as session:
            await self.verify_identity_record(session, identity)
            await session.commit()
        return await self._repository.acquire_lease(identity.edge_id, boot_id)

    async def get_configuration(
        self,
        identity: VerifiedEdgeIdentity,
        lease: LeaseHeaders,
        *,
        if_none_match: str | None,
    ) -> ConfigurationSnapshot | None:
        async with self._database.session() as session:
            await self.verify_identity_record(session, identity)
            await session.commit()
        await self._validate_lease(identity.edge_id, lease)
        desired = await self._repository.latest_desired(identity.edge_id)
        if desired is None:
            raise EdgeServiceError("no_configuration", 404)
        if if_none_match and if_none_match.strip('"') == desired.digest:
            return None
        return ConfigurationSnapshot(
            revision=desired.revision,
            digest=desired.digest,
            document=desired.document,
        )

    async def submit_report(
        self,
        identity: VerifiedEdgeIdentity,
        lease: LeaseHeaders,
        report: EdgeReportContract,
    ) -> dict[str, Any]:
        if report.edge_id != identity.edge_id:
            raise EdgeServiceError("scope_violation", 403)
        async with self._database.session() as session:
            await self.verify_identity_record(session, identity)
            desired = await self._repository.latest_desired(identity.edge_id)
            if desired is None or report.desired_revision > desired.revision:
                raise EdgeServiceError("unknown_revision", 409)
            if report.desired_revision == desired.revision and report.applied_digest != desired.digest:
                raise EdgeServiceError("digest_mismatch", 409)
            await session.commit()

        edge_lease = EdgeLease(
            edge_id=identity.edge_id,
            boot_id=lease.boot_id,
            generation=lease.generation,
            lease_token=lease.lease_token,
            expires_at=self._now(),
        )
        try:
            row = await self._repository.accept_report(EdgeIdentity(identity.edge_id), edge_lease, report)
        except EdgeLeaseRejected as exc:
            raise EdgeServiceError("lease_rejected", 409, str(exc)) from exc
        except EdgeScopeViolation as exc:
            raise EdgeServiceError("scope_violation", 403, str(exc)) from exc
        return {
            "edge_id": row.edge_id,
            "boot_id": row.boot_id,
            "report_sequence": row.report_sequence,
            "received_at": row.received_at.isoformat(),
        }

    async def fetch_secret(
        self,
        identity: VerifiedEdgeIdentity,
        lease: LeaseHeaders,
        secret_id: str,
        version: int,
    ) -> bytes:
        await self._validate_lease(identity.edge_id, lease)
        desired = await self._repository.latest_desired(identity.edge_id)
        if desired is None:
            raise EdgeServiceError("no_configuration", 404)
        allowed = {
            (ref["secret_id"], int(ref["version"]))
            for ref in desired.document.get("secret_refs", [])
        }
        if (secret_id, version) not in allowed:
            raise EdgeServiceError("secret_not_authorized", 403)
        if self._secret_store is None:
            raise EdgeServiceError("secrets_unavailable", 503)

        async with self._database.session() as session:
            await self.verify_identity_record(session, identity)
            row = (
                await session.execute(
                    select(EdgeSecretVersion).where(
                        EdgeSecretVersion.edge_id == identity.edge_id,
                        EdgeSecretVersion.secret_id == secret_id,
                        EdgeSecretVersion.version == version,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise EdgeServiceError("secret_not_found", 404)
            encrypted = EncryptedSecret(row.key_id, row.nonce, row.ciphertext)
            return self._secret_store.decrypt(
                edge_id=identity.edge_id,
                secret_id=secret_id,
                version=version,
                encrypted=encrypted,
            )

    async def renew(
        self,
        identity: VerifiedEdgeIdentity,
        purpose: EdgeCertPurpose,
        csr_pem: str,
    ) -> IssuedCertificate:
        if purpose != "management":
            raise EdgeServiceError("invalid_purpose", 403, purpose)
        now = self._now()
        async with self._database.session() as session:
            await self.verify_identity_record(session, identity)
            current = await active_certificate(
                session,
                edge_id=identity.edge_id,
                purpose=purpose,
                serial_hex=identity.certificate_serial,
                now=now,
            )
            if current is None:
                raise EdgeServiceError("expired_identity", 401)
            if not self._issuer.renewal_allowed(current.not_before, now):
                raise EdgeServiceError("renewal_too_early", 409)
            issued = self._issuer.renew_from_csr(
                csr_pem,
                edge_id=identity.edge_id,
                purpose=purpose,
                previous_not_after=current.not_after,
            )
            await store_certificate(
                session,
                certificate_id=issued.certificate_id,
                edge_id=identity.edge_id,
                purpose=purpose,
                pem=issued.pem,
                not_before=issued.not_before,
                not_after=issued.not_after,
            )
            await session.commit()
            return issued

    async def _validate_lease(self, edge_id: str, lease: LeaseHeaders) -> None:
        edge_lease = EdgeLease(
            edge_id=edge_id,
            boot_id=lease.boot_id,
            generation=lease.generation,
            lease_token=lease.lease_token,
            expires_at=self._now(),
        )
        async with self._database.session() as session:
            try:
                await self._repository._validate_lease(session, edge_lease)  # noqa: SLF001
            except EdgeLeaseRejected as exc:
                raise EdgeServiceError("lease_rejected", 409, str(exc)) from exc
