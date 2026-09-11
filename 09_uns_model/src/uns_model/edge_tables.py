"""Declarative models for cloud edge management in schema ``edge``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from uns_model.model_config import EDGE_SCHEMA
from uns_model.tables import Base


class EdgeDevice(Base):
    """One registered edge site/agent identity."""

    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('registered', 'enrolled', 'revoked')",
            name="edge_devices_status_check",
        ),
        {"schema": EDGE_SCHEMA},
    )

    edge_id: Mapped[str] = mapped_column(Text, primary_key=True)
    site_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'registered'"))
    desired_head_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    latest_applied_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    latest_applied_digest: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    latest_applied_phase: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    current_lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    desired_configurations: Mapped[list[EdgeDesiredConfiguration]] = relationship(back_populates="device")
    leases: Mapped[list[EdgeManagementLease]] = relationship(back_populates="device")


class EdgeUserGrant(Base):
    """Explicit edge-to-user authorization for console engineers."""

    __tablename__ = "user_grants"
    __table_args__ = {"schema": EDGE_SCHEMA}

    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EdgeEnrollmentAttempt(Base):
    """Single-use enrollment token consumption and CSR binding."""

    __tablename__ = "enrollment_attempts"
    __table_args__ = {"schema": EDGE_SCHEMA}

    attempt_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    management_csr_digest: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    mqtt_csr_digest: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EdgeCertificate(Base):
    """Issued device certificate material and lifecycle."""

    __tablename__ = "certificates"
    __table_args__ = (
        CheckConstraint("purpose IN ('management', 'mqtt')", name="edge_certificates_purpose_check"),
        {"schema": EDGE_SCHEMA},
    )

    certificate_id: Mapped[str] = mapped_column(Text, primary_key=True)
    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    pem: Mapped[str] = mapped_column(Text, nullable=False)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EdgeDesiredConfiguration(Base):
    """Immutable desired-state snapshot for one edge revision."""

    __tablename__ = "desired_configurations"
    __table_args__ = (
        UniqueConstraint("edge_id", "revision", name="uq_edge_desired_revision"),
        UniqueConstraint("edge_id", "digest", name="uq_edge_desired_digest"),
        Index("idx_edge_desired_edge_revision", "edge_id", "revision"),
        {"schema": EDGE_SCHEMA},
    )

    configuration_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    device: Mapped[EdgeDevice] = relationship(back_populates="desired_configurations")


class EdgeManagementLease(Base):
    """Active management lease fencing cloud-side edge effects."""

    __tablename__ = "management_leases"
    __table_args__ = (
        UniqueConstraint("edge_id", "generation", name="uq_edge_lease_generation"),
        Index("idx_edge_leases_active", "edge_id", "revoked_at", "expires_at"),
        {"schema": EDGE_SCHEMA},
    )

    lease_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        nullable=False,
    )
    boot_id: Mapped[str] = mapped_column(Text, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    device: Mapped[EdgeDevice] = relationship(back_populates="leases")


class EdgeReport(Base):
    """Historical agent report with bounded retention."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("edge_id", "boot_id", "report_sequence", name="uq_edge_report_sequence"),
        Index("idx_edge_reports_retention", "retained_until"),
        {"schema": EDGE_SCHEMA},
    )

    report_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        nullable=False,
    )
    boot_id: Mapped[str] = mapped_column(Text, nullable=False)
    report_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    desired_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_digest: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    retained_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EdgeSecretVersion(Base):
    """Encrypted connection secret scoped to one edge and version."""

    __tablename__ = "secret_versions"
    __table_args__ = (
        UniqueConstraint("secret_id", "version", name="uq_edge_secret_version"),
        Index("idx_edge_secret_scope", "edge_id", "secret_id"),
        {"schema": EDGE_SCHEMA},
    )

    secret_row_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    secret_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        nullable=False,
    )
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EdgeJob(Base):
    """Bounded management job dispatched through the poll/report flow."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'expired')",
            name="edge_jobs_status_check",
        ),
        {"schema": EDGE_SCHEMA},
    )

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    edge_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{EDGE_SCHEMA}.devices.edge_id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[str] = mapped_column(Text, nullable=False)
    config_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EdgeAuditEvent(Base):
    """Immutable audit trail for edge catalog mutations."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("idx_edge_audit_edge_created", "edge_id", "created_at"),
        {"schema": EDGE_SCHEMA},
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    edge_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
