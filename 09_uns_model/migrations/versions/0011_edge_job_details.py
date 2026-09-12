"""Add result and lease columns to edge management jobs.

Revision ID: 0011_edge_job_details
Revises: 0010_edge_management
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_edge_job_details"
down_revision: str | None = "0010_edge_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EDGE_SCHEMA = "edge"

ALTER_JOBS = (
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS node_id TEXT",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS lease_generation BIGINT",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS execution_deadline TIMESTAMPTZ",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS result_payload JSONB",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS error_code TEXT",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS error_detail TEXT",
    f"ALTER TABLE {EDGE_SCHEMA}.jobs ADD COLUMN IF NOT EXISTS result_retained_until TIMESTAMPTZ",
    f"CREATE INDEX IF NOT EXISTS idx_edge_jobs_edge_status "
    f"ON {EDGE_SCHEMA}.jobs (edge_id, status)",
)


def upgrade() -> None:
    for statement in ALTER_JOBS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {EDGE_SCHEMA}.idx_edge_jobs_edge_status")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS result_retained_until")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS error_detail")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS error_code")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS result_payload")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS execution_deadline")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS completed_at")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS started_at")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS lease_generation")
    op.execute(f"ALTER TABLE {EDGE_SCHEMA}.jobs DROP COLUMN IF EXISTS node_id")
