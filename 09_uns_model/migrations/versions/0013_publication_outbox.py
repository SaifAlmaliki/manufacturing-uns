"""Publication outbox, idempotency, and byte-budget tables.

Revision ID: 0013_publication_outbox
Revises: 0012_route_release
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_publication_outbox"
down_revision: str | None = "0012_route_release"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PUBLICATIONS_SCHEMA = "publications"

STATEMENTS = (
    f"CREATE SCHEMA IF NOT EXISTS {PUBLICATIONS_SCHEMA}",
    f"""
CREATE TABLE IF NOT EXISTS {PUBLICATIONS_SCHEMA}.budget_reservations (
  scope TEXT PRIMARY KEY,
  reserved_bytes BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""",
    f"""
CREATE TABLE IF NOT EXISTS {PUBLICATIONS_SCHEMA}.outbox (
  receipt_id UUID PRIMARY KEY,
  principal_id TEXT NOT NULL,
  route_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  content_digest TEXT NOT NULL,
  mqtt_topic TEXT NOT NULL,
  wrapper_bytes BYTEA NOT NULL,
  byte_size INTEGER NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
  occurred_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'queued'
    CONSTRAINT publications_outbox_status_check
    CHECK (status IN ('queued', 'broker_accepted', 'failed')),
  error_code TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  lease_holder TEXT,
  lease_expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  broker_accepted_at TIMESTAMPTZ,
  terminal_at TIMESTAMPTZ
)
""",
    f"""
CREATE INDEX IF NOT EXISTS idx_publications_outbox_lease
ON {PUBLICATIONS_SCHEMA}.outbox (status, next_attempt_at, lease_expires_at, created_at)
""",
    f"""
CREATE TABLE IF NOT EXISTS {PUBLICATIONS_SCHEMA}.idempotency_keys (
  principal_id TEXT NOT NULL,
  route_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  receipt_id UUID NOT NULL REFERENCES {PUBLICATIONS_SCHEMA}.outbox(receipt_id),
  content_digest TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (principal_id, route_id, idempotency_key)
)
""",
    f"""
CREATE INDEX IF NOT EXISTS idx_publications_idempotency_expires
ON {PUBLICATIONS_SCHEMA}.idempotency_keys (expires_at)
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {PUBLICATIONS_SCHEMA}.idempotency_keys")
    op.execute(f"DROP TABLE IF EXISTS {PUBLICATIONS_SCHEMA}.outbox")
    op.execute(f"DROP TABLE IF EXISTS {PUBLICATIONS_SCHEMA}.budget_reservations")
    op.execute(f"DROP SCHEMA IF EXISTS {PUBLICATIONS_SCHEMA}")
