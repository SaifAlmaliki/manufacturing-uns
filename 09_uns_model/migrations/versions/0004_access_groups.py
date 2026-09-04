"""Access Groups: named Asset-tree roots and Keycloak member subjects.

Revision ID: 0004_access_groups
Revises: 0003_oee_model
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_access_groups"
down_revision: str | None = "0003_oee_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_SCHEMA = "model"


def upgrade() -> None:
    op.create_table(
        "access_group",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_access_group_name"),
        sa.CheckConstraint("name <> ''", name="ck_access_group_name_not_empty"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "access_group_root",
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "asset_id"),
        sa.ForeignKeyConstraint(["group_id"], [f"{MODEL_SCHEMA}.access_group.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "asset_id", name="uq_access_group_root"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "access_group_member",
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "subject"),
        sa.ForeignKeyConstraint(["group_id"], [f"{MODEL_SCHEMA}.access_group.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "subject", name="uq_access_group_member"),
        sa.CheckConstraint("subject <> ''", name="ck_access_group_member_subject_not_empty"),
        schema=MODEL_SCHEMA,
    )
    _grant()


def _grant() -> None:
    # Guarded: the role is created interactively, so it may not exist yet.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {MODEL_SCHEMA} TO uns_dbuser;
                ALTER DEFAULT PRIVILEGES IN SCHEMA {MODEL_SCHEMA}
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uns_dbuser;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("access_group_member", schema=MODEL_SCHEMA)
    op.drop_table("access_group_root", schema=MODEL_SCHEMA)
    op.drop_table("access_group", schema=MODEL_SCHEMA)
