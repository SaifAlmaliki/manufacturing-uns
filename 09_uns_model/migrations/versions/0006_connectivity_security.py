"""Add security and auth columns to the Connectivity catalog.

Revision ID: 0006_connectivity_security
Revises: 0005_console_connectivity
Create Date: 2026-09-05

0005 created `console.connectivity_servers` without channel-security fields.
The ORM already maps `auth_mode`, `security_policy`, `security_mode`, and
certificate paths, so a catalog list fails with UndefinedColumnError until
these columns exist. Defaults match Anonymous + SecurityPolicy None (OpcPlc).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_connectivity_security"
down_revision: str | None = "0005_console_connectivity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "auth_mode TEXT NOT NULL DEFAULT 'anonymous'",
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "security_policy TEXT NOT NULL DEFAULT 'None'",
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "security_mode TEXT NOT NULL DEFAULT 'None'",
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "username TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "password TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "certificate TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "private_key TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
    "server_certificate TEXT NOT NULL DEFAULT ''",
)

CONSTRAINTS = (
    "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
    "connectivity_servers_auth_mode_check",
    "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
    "connectivity_servers_auth_mode_check "
    "CHECK (auth_mode IN ('anonymous', 'username', 'x509'))",
    "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
    "connectivity_servers_security_policy_check",
    "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
    "connectivity_servers_security_policy_check "
    "CHECK (security_policy IN ('None', 'Basic256Sha256', 'Aes128Sha256RsaOaep', 'Aes256Sha256RsaPss'))",
    "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
    "connectivity_servers_security_mode_check",
    "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
    "connectivity_servers_security_mode_check "
    "CHECK (security_mode IN ('None', 'Sign', 'SignAndEncrypt'))",
)

COMMENTS = (
    "COMMENT ON COLUMN console.connectivity_servers.auth_mode IS "
    "'anonymous | username | x509. How the collector authenticates to the OPC UA server.'",
    "COMMENT ON COLUMN console.connectivity_servers.security_policy IS "
    "'OPC UA SecurityPolicy. None is the OpcPlc / development default.'",
)


def upgrade() -> None:
    for statement in COLUMNS:
        op.execute(statement)
    for statement in CONSTRAINTS:
        op.execute(statement)
    for statement in COMMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE console.connectivity_servers "
        "DROP CONSTRAINT IF EXISTS connectivity_servers_auth_mode_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers "
        "DROP CONSTRAINT IF EXISTS connectivity_servers_security_policy_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers "
        "DROP CONSTRAINT IF EXISTS connectivity_servers_security_mode_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers "
        "DROP COLUMN IF EXISTS auth_mode, "
        "DROP COLUMN IF EXISTS security_policy, "
        "DROP COLUMN IF EXISTS security_mode, "
        "DROP COLUMN IF EXISTS username, "
        "DROP COLUMN IF EXISTS password, "
        "DROP COLUMN IF EXISTS certificate, "
        "DROP COLUMN IF EXISTS private_key, "
        "DROP COLUMN IF EXISTS server_certificate"
    )
