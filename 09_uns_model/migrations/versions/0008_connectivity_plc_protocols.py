"""Allow S7 / EtherNet/IP catalog rows and pending apply status.

Revision ID: 0008_connectivity_plc_protocols
Revises: 0007_signal_context
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_connectivity_plc_protocols"
down_revision: str | None = "0007_signal_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_protocol_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_protocol_check "
        "CHECK (protocol IN ('opc_ua', 's7', 'ethernet_ip'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_last_status_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_last_status_check "
        "CHECK (last_status IN ('untested', 'pending', 'connected', 'failed'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD COLUMN IF NOT EXISTS "
        "protocol_config JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE console.connectivity_servers DROP COLUMN IF EXISTS protocol_config")
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_protocol_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_protocol_check "
        "CHECK (protocol IN ('opc_ua'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers DROP CONSTRAINT IF EXISTS "
        "connectivity_servers_last_status_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_servers ADD CONSTRAINT "
        "connectivity_servers_last_status_check "
        "CHECK (last_status IN ('untested', 'connected', 'failed'))"
    )
