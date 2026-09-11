"""Edge management catalog, leases, secrets, and legacy connectivity scope.

Revision ID: 0010_edge_management
Revises: 0009_historian_event_pipeline
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_edge_management"
down_revision: str | None = "0009_historian_event_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EDGE_SCHEMA = "edge"
CONSOLE_SCHEMA = "console"

CREATE_EDGE_SCHEMA = f"CREATE SCHEMA IF NOT EXISTS {EDGE_SCHEMA}"

COMMENT_EDGE_SCHEMA = (
    f"COMMENT ON SCHEMA {EDGE_SCHEMA} IS "
    "'Cloud edge management: desired configuration, leases, secrets, reports, and audit.'"
)

EDGE_DEVICES_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.devices (
  edge_id TEXT PRIMARY KEY,
  site_id TEXT,
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'registered'
    CONSTRAINT edge_devices_status_check
    CHECK (status IN ('registered', 'enrolled', 'revoked')),
  desired_head_revision BIGINT NOT NULL DEFAULT 0,
  latest_applied_revision BIGINT NOT NULL DEFAULT 0,
  latest_applied_digest TEXT NOT NULL DEFAULT '',
  latest_applied_phase TEXT NOT NULL DEFAULT '',
  current_lease_generation BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

EDGE_USER_GRANTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.user_grants (
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (edge_id, user_id)
)
"""

EDGE_ENROLLMENT_ATTEMPTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.enrollment_attempts (
  attempt_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  management_csr_digest TEXT NOT NULL DEFAULT '',
  mqtt_csr_digest TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

EDGE_CERTIFICATES_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.certificates (
  certificate_id TEXT PRIMARY KEY,
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  purpose TEXT NOT NULL
    CONSTRAINT edge_certificates_purpose_check
    CHECK (purpose IN ('management', 'mqtt')),
  pem TEXT NOT NULL,
  not_before TIMESTAMPTZ NOT NULL,
  not_after TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

EDGE_DESIRED_CONFIGURATIONS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.desired_configurations (
  configuration_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  revision BIGINT NOT NULL,
  digest TEXT NOT NULL,
  document JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_edge_desired_revision UNIQUE (edge_id, revision),
  CONSTRAINT uq_edge_desired_digest UNIQUE (edge_id, digest)
)
"""

EDGE_MANAGEMENT_LEASES_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.management_leases (
  lease_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  boot_id TEXT NOT NULL,
  generation BIGINT NOT NULL,
  lease_token TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_edge_lease_generation UNIQUE (edge_id, generation)
)
"""

EDGE_REPORTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.reports (
  report_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  boot_id TEXT NOT NULL,
  report_sequence BIGINT NOT NULL,
  desired_revision BIGINT NOT NULL,
  applied_revision BIGINT NOT NULL,
  applied_digest TEXT NOT NULL,
  phase TEXT NOT NULL,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  retained_until TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_edge_report_sequence UNIQUE (edge_id, boot_id, report_sequence)
)
"""

EDGE_SECRET_VERSIONS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.secret_versions (
  secret_row_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  secret_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  key_id TEXT NOT NULL,
  nonce BYTEA NOT NULL,
  ciphertext BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_edge_secret_version UNIQUE (secret_id, version)
)
"""

EDGE_JOBS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.jobs (
  job_id TEXT PRIMARY KEY,
  edge_id TEXT NOT NULL
    REFERENCES {EDGE_SCHEMA}.devices (edge_id) ON DELETE CASCADE,
  connection_id TEXT NOT NULL,
  config_revision BIGINT NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CONSTRAINT edge_jobs_status_check
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'expired')),
  expires_at TIMESTAMPTZ NOT NULL,
  cursor TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

EDGE_AUDIT_EVENTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {EDGE_SCHEMA}.audit_events (
  event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  edge_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  actor TEXT,
  details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

ADD_CONNECTIVITY_EDGE_ID = (
    f"ALTER TABLE {CONSOLE_SCHEMA}.connectivity_servers "
    "ADD COLUMN IF NOT EXISTS edge_id TEXT"
)

INDEXES = (
    f"CREATE INDEX IF NOT EXISTS idx_edge_desired_edge_revision "
    f"ON {EDGE_SCHEMA}.desired_configurations (edge_id, revision)",
    f"CREATE INDEX IF NOT EXISTS idx_edge_leases_active "
    f"ON {EDGE_SCHEMA}.management_leases (edge_id, revoked_at, expires_at)",
    f"CREATE INDEX IF NOT EXISTS idx_edge_reports_retention "
    f"ON {EDGE_SCHEMA}.reports (retained_until)",
    f"CREATE INDEX IF NOT EXISTS idx_edge_secret_scope "
    f"ON {EDGE_SCHEMA}.secret_versions (edge_id, secret_id)",
    f"CREATE INDEX IF NOT EXISTS idx_edge_audit_edge_created "
    f"ON {EDGE_SCHEMA}.audit_events (edge_id, created_at)",
    f"CREATE INDEX IF NOT EXISTS idx_connectivity_servers_edge "
    f"ON {CONSOLE_SCHEMA}.connectivity_servers (edge_id) "
    "WHERE edge_id IS NOT NULL",
)

GRANTS = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
        GRANT USAGE ON SCHEMA {EDGE_SCHEMA} TO uns_dbuser;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {EDGE_SCHEMA} TO uns_dbuser;
        ALTER DEFAULT PRIVILEGES IN SCHEMA {EDGE_SCHEMA}
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uns_dbuser;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute(CREATE_EDGE_SCHEMA)
    op.execute(COMMENT_EDGE_SCHEMA)
    op.execute(EDGE_DEVICES_TABLE)
    op.execute(EDGE_USER_GRANTS_TABLE)
    op.execute(EDGE_ENROLLMENT_ATTEMPTS_TABLE)
    op.execute(EDGE_CERTIFICATES_TABLE)
    op.execute(EDGE_DESIRED_CONFIGURATIONS_TABLE)
    op.execute(EDGE_MANAGEMENT_LEASES_TABLE)
    op.execute(EDGE_REPORTS_TABLE)
    op.execute(EDGE_SECRET_VERSIONS_TABLE)
    op.execute(EDGE_JOBS_TABLE)
    op.execute(EDGE_AUDIT_EVENTS_TABLE)
    op.execute(ADD_CONNECTIVITY_EDGE_ID)
    for index in INDEXES:
        op.execute(index)
    op.execute(GRANTS)


def downgrade() -> None:
    op.execute(f"ALTER TABLE {CONSOLE_SCHEMA}.connectivity_servers DROP COLUMN IF EXISTS edge_id")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.audit_events")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.jobs")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.secret_versions")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.reports")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.management_leases")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.desired_configurations")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.certificates")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.enrollment_attempts")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.user_grants")
    op.execute(f"DROP TABLE IF EXISTS {EDGE_SCHEMA}.devices")
    op.execute(f"DROP SCHEMA IF EXISTS {EDGE_SCHEMA}")
