"""Route release staging, activation state, and worker lease tables.

Revision ID: 0012_route_release
Revises: 0011_edge_job_details
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_route_release"
down_revision: str | None = "0011_edge_job_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUTES_SCHEMA = "routes"

STATEMENTS = (
    f"CREATE SCHEMA IF NOT EXISTS {ROUTES_SCHEMA}",
    f"""
CREATE TABLE IF NOT EXISTS {ROUTES_SCHEMA}.releases (
  release_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  revision BIGINT NOT NULL UNIQUE,
  digest TEXT NOT NULL UNIQUE,
  document JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CONSTRAINT routes_releases_status_check
    CHECK (status IN ('pending', 'activating', 'active', 'failed', 'superseded')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""",
    f"""
CREATE TABLE IF NOT EXISTS {ROUTES_SCHEMA}.activation_state (
  state_id SMALLINT PRIMARY KEY DEFAULT 1
    CONSTRAINT routes_activation_singleton CHECK (state_id = 1),
  release_revision BIGINT NOT NULL DEFAULT 0,
  release_digest TEXT NOT NULL DEFAULT '',
  phase TEXT NOT NULL DEFAULT 'pending',
  mapper_revision BIGINT,
  mapper_digest TEXT,
  broker_revision BIGINT,
  broker_digest TEXT,
  drain_until_revision BIGINT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""",
    f"""
INSERT INTO {ROUTES_SCHEMA}.activation_state (state_id)
VALUES (1)
ON CONFLICT (state_id) DO NOTHING
""",
    f"""
CREATE TABLE IF NOT EXISTS {ROUTES_SCHEMA}.worker_leases (
  lease_name TEXT PRIMARY KEY,
  holder_id TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {ROUTES_SCHEMA}.worker_leases")
    op.execute(f"DROP TABLE IF EXISTS {ROUTES_SCHEMA}.activation_state")
    op.execute(f"DROP TABLE IF EXISTS {ROUTES_SCHEMA}.releases")
    op.execute(f"DROP SCHEMA IF EXISTS {ROUTES_SCHEMA}")
