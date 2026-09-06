"""Add signal context columns and unit/label catalogs.

Revision ID: 0007_signal_context
Revises: 0006_connectivity_security
Create Date: 2026-09-06

Adds reference catalogs for units of measure and signal labels, and extends
`console.connectivity_tags` with asset binding, semantic metadata, and labels.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0007_signal_context"
down_revision: str | None = "0006_connectivity_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEEDED_UNITS: tuple[str, ...] = (
    "°C",
    "K",
    "bar",
    "Pa",
    "kPa",
    "%",
    "kWh",
    "kW",
    "L/min",
    "m³",
    "Hz",
    "rpm",
    "A",
    "V",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS console.units_of_measure (
          symbol TEXT PRIMARY KEY,
          name TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS console.signal_labels (
          name TEXT PRIMARY KEY,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for symbol in SEEDED_UNITS:
        op.execute(
            text(
                "INSERT INTO console.units_of_measure (symbol) VALUES (:s) ON CONFLICT DO NOTHING"
            ),
            {"s": symbol},
        )
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS asset_id BIGINT")
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_asset_id_fkey"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD CONSTRAINT connectivity_tags_asset_id_fkey "
        "FOREIGN KEY (asset_id) REFERENCES model.asset (id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS unit_of_measure TEXT")
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS semantic_class TEXT")
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS data_type TEXT")
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS labels TEXT[] NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_semantic_class_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD CONSTRAINT connectivity_tags_semantic_class_check "
        "CHECK (semantic_class IS NULL OR semantic_class IN "
        "('MeasuredValue', 'EnergyConsumption', 'CounterOK', 'CounterNOK', 'State'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_data_type_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD CONSTRAINT connectivity_tags_data_type_check "
        "CHECK (data_type IS NULL OR data_type IN ('Double', 'Boolean', 'Integer', 'String'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_data_type_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_semantic_class_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_asset_id_fkey"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags "
        "DROP COLUMN IF EXISTS labels, "
        "DROP COLUMN IF EXISTS data_type, "
        "DROP COLUMN IF EXISTS semantic_class, "
        "DROP COLUMN IF EXISTS unit_of_measure, "
        "DROP COLUMN IF EXISTS asset_id"
    )
    op.execute("DROP TABLE IF EXISTS console.signal_labels")
    op.execute("DROP TABLE IF EXISTS console.units_of_measure")
