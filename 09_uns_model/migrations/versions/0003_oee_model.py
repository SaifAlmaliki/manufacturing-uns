"""OEE master data in schema `model` and shift results in schema `oee`.

Revision ID: 0003_oee_model
Revises: 0002_console_alert_rules
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_oee_model"
down_revision: str | None = "0002_console_alert_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_SCHEMA = "model"
OEE_SCHEMA = "oee"

# Duplicated from uns_model.oee_tables on purpose: a migration is a historical record and
# must keep applying even after the application constant changes.
DEFAULT_DOWNTIME_REASONS = (
    ("UNCLASSIFIED", "Unclassified", "Unknown", False),
    ("PLANNED_MAINTENANCE", "Planned maintenance", "Maintenance", True),
    ("CHANGEOVER", "Product changeover", "Setup", True),
    ("PLANNED_BREAK", "Planned break", "Organisational", True),
    ("BREAKDOWN", "Equipment breakdown", "Technical", False),
    ("MINOR_STOP", "Minor stop", "Technical", False),
    ("MATERIAL_SHORTAGE", "Material shortage", "Supply", False),
    ("OPERATOR_ABSENT", "No operator", "Organisational", False),
    ("QUALITY_HOLD", "Quality hold", "Quality", False),
)


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(OEE_SCHEMA, if_not_exists=True))
    op.execute(
        f"COMMENT ON SCHEMA {OEE_SCHEMA} IS "
        f"'Derived shift OEE results. Rebuildable from the historian at any time.'"
    )
    _create_master_data()
    _create_results()
    _seed_reasons()
    _grant()


def _create_master_data() -> None:
    op.create_table(
        "product",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_product_code"),
        sa.CheckConstraint("code <> ''", name="ck_product_code_not_empty"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "shift_pattern",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), server_default="UTC", nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("name", name="uq_shift_pattern_name"),
        sa.CheckConstraint("timezone <> ''", name="ck_shift_pattern_timezone_not_empty"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "shift_pattern_slot",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("shift_pattern_id", sa.BigInteger(), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(timezone=False), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["shift_pattern_id"], [f"{MODEL_SCHEMA}.shift_pattern.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "shift_pattern_id", "day_of_week", "start_time", name="uq_shift_slot_pattern_day_start"
        ),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_shift_slot_day_of_week"),
        sa.CheckConstraint(
            "duration_minutes > 0 AND duration_minutes <= 1440", name="ck_shift_slot_duration"
        ),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "shift_exception",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), server_default="PLANNED_DOWN", nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_shift_exception_range"),
        sa.CheckConstraint(
            "kind IN ('PLANNED_DOWN', 'NON_PRODUCING', 'HOLIDAY')", name="ck_shift_exception_kind"
        ),
        schema=MODEL_SCHEMA,
    )
    op.create_index(
        "idx_shift_exception_window", "shift_exception", ["starts_at", "ends_at"], schema=MODEL_SCHEMA
    )

    op.create_table(
        "downtime_reason",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), server_default="", nullable=False),
        sa.Column("is_planned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("code"),
        sa.CheckConstraint("code <> ''", name="ck_downtime_reason_code_not_empty"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "oee_unit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_pattern_id", sa.BigInteger(), nullable=False),
        sa.Column("state_metric_key", sa.Text(), nullable=False),
        sa.Column("good_count_metric_key", sa.Text(), nullable=False),
        sa.Column("reject_count_metric_key", sa.Text(), nullable=True),
        sa.Column("product_metric_key", sa.Text(), nullable=True),
        sa.Column(
            "producing_states",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{EXECUTE}'::text[]"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shift_pattern_id"], [f"{MODEL_SCHEMA}.shift_pattern.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("asset_id", name="uq_oee_unit_asset"),
        sa.CheckConstraint("state_metric_key <> ''", name="ck_oee_unit_state_metric_key"),
        sa.CheckConstraint(
            "array_length(producing_states, 1) >= 1", name="ck_oee_unit_producing_states"
        ),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "ideal_cycle_time",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("seconds_per_unit", sa.Double(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], [f"{MODEL_SCHEMA}.product.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "asset_id",
            "product_id",
            name="uq_ideal_cycle_time_asset_product",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("seconds_per_unit > 0", name="ck_ideal_cycle_time_positive"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "state_reason_map",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=True),
        sa.Column("state_value", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reason_code"],
            [f"{MODEL_SCHEMA}.downtime_reason.code"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "oee_unit_id",
            "state_value",
            name="uq_state_reason_map_unit_state",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("state_value <> ''", name="ck_state_reason_map_state_not_empty"),
        schema=MODEL_SCHEMA,
    )


def _create_results() -> None:
    op.create_table(
        "shift_result",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shift_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shift_label", sa.Text(), server_default="", nullable=False),
        sa.Column("loading_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("run_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("planned_down_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("unplanned_down_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("good_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("reject_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("availability", sa.Double(), nullable=True),
        sa.Column("performance", sa.Double(), nullable=True),
        sa.Column("performance_raw", sa.Double(), nullable=True),
        sa.Column("quality", sa.Double(), nullable=True),
        sa.Column("oee", sa.Double(), nullable=True),
        sa.Column("status", sa.Text(), server_default="OK", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_fingerprint", sa.Text(), server_default="", nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("oee_unit_id", "shift_start", name="uq_shift_result_unit_start"),
        sa.CheckConstraint("shift_end > shift_start", name="ck_shift_result_range"),
        sa.CheckConstraint(
            "status IN ('OK', 'NO_LOADING_TIME', 'NO_PRODUCTION', 'MISSING_IDEAL_CYCLE_TIME', "
            "'NO_INPUT_DATA')",
            name="ck_shift_result_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_shift_result_revision"),
        sa.CheckConstraint(
            "good_count >= 0 AND reject_count >= 0 AND total_count >= 0",
            name="ck_shift_result_counts_non_negative",
        ),
        schema=OEE_SCHEMA,
    )
    op.create_index("idx_shift_result_shift_start", "shift_result", ["shift_start"], schema=OEE_SCHEMA)

    op.create_table(
        "shift_result_product",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("shift_result_id", sa.BigInteger(), nullable=False),
        sa.Column("product_code", sa.Text(), server_default="", nullable=False),
        sa.Column("good_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("reject_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("ideal_cycle_time_s", sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["shift_result_id"], [f"{OEE_SCHEMA}.shift_result.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("shift_result_id", "product_code", name="uq_shift_result_product"),
        schema=OEE_SCHEMA,
    )

    op.create_table(
        "shift_result_revision",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("loading_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("run_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("good_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("reject_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("availability", sa.Double(), nullable=True),
        sa.Column("performance", sa.Double(), nullable=True),
        sa.Column("quality", sa.Double(), nullable=True),
        sa.Column("oee", sa.Double(), nullable=True),
        sa.Column("status", sa.Text(), server_default="OK", nullable=False),
        sa.Column("input_fingerprint", sa.Text(), server_default="", nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("oee_unit_id", "shift_start", "revision", name="uq_shift_result_revision"),
        schema=OEE_SCHEMA,
    )

    op.create_table(
        "downtime_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("state_value", sa.Text(), server_default="", nullable=False),
        sa.Column("reason_code", sa.Text(), server_default="UNCLASSIFIED", nullable=False),
        sa.Column("reason_source", sa.Text(), server_default="auto", nullable=False),
        sa.Column("assigned_by", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reason_code"],
            [f"{MODEL_SCHEMA}.downtime_reason.code"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("oee_unit_id", "started_at", name="uq_downtime_event_unit_start"),
        sa.CheckConstraint("ended_at > started_at", name="ck_downtime_event_range"),
        sa.CheckConstraint(
            "reason_source IN ('auto', 'manual')", name="ck_downtime_event_reason_source"
        ),
        schema=OEE_SCHEMA,
    )
    op.create_index(
        "idx_downtime_event_shift", "downtime_event", ["oee_unit_id", "shift_start"], schema=OEE_SCHEMA
    )
    op.create_index("idx_downtime_event_reason", "downtime_event", ["reason_code"], schema=OEE_SCHEMA)

    op.create_table(
        "recompute_request",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=True),
        sa.Column("range_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.CheckConstraint("range_end > range_start", name="ck_recompute_request_range"),
        schema=OEE_SCHEMA,
    )
    op.create_index(
        "idx_recompute_request_pending",
        "recompute_request",
        ["claimed_at", "requested_at"],
        schema=OEE_SCHEMA,
    )


def _seed_reasons() -> None:
    op.bulk_insert(
        sa.table(
            "downtime_reason",
            sa.column("code", sa.Text),
            sa.column("display_name", sa.Text),
            sa.column("category", sa.Text),
            sa.column("is_planned", sa.Boolean),
            schema=MODEL_SCHEMA,
        ),
        [
            {"code": code, "display_name": display, "category": category, "is_planned": is_planned}
            for code, display, category, is_planned in DEFAULT_DOWNTIME_REASONS
        ],
    )


def _grant() -> None:
    # Guarded: the role is created interactively, so it may not exist yet.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
                GRANT USAGE ON SCHEMA {OEE_SCHEMA} TO uns_dbuser;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {OEE_SCHEMA} TO uns_dbuser;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {MODEL_SCHEMA} TO uns_dbuser;
                ALTER DEFAULT PRIVILEGES IN SCHEMA {OEE_SCHEMA}
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uns_dbuser;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    for table in (
        "recompute_request",
        "downtime_event",
        "shift_result_revision",
        "shift_result_product",
        "shift_result",
    ):
        op.drop_table(table, schema=OEE_SCHEMA)
    op.execute(sa.schema.DropSchema(OEE_SCHEMA, if_exists=True))
    for table in (
        "state_reason_map",
        "ideal_cycle_time",
        "oee_unit",
        "downtime_reason",
        "shift_exception",
        "shift_pattern_slot",
        "shift_pattern",
        "product",
    ):
        op.drop_table(table, schema=MODEL_SCHEMA)
