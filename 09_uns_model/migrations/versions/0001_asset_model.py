"""Authored Asset Model, Topic Bindings and the Enrichment views

Revision ID: 0001_asset_model
Revises:
Create Date: 2026-08-31

See ADR-0003 for why Enrichment is a read-time join, and ADR-0004 for why the
Timescale-specific DDL is not represented in the SQLAlchemy metadata.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

LOGGER = logging.getLogger("alembic.runtime.migration")

revision: str = "0001_asset_model"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "model"

ASSET_LEVELS = (
    ("ENTERPRISE", 0, "The organisation as a whole"),
    ("SITE", 1, "A physical plant or facility"),
    ("AREA", 2, "A production area within a Site"),
    ("PRODUCTION_UNIT", 3, "An ISA-95 production unit within an Area"),
    ("LINE", 4, "A production line"),
    ("WORK_CELL", 5, "A cell within a Line"),
    ("MACHINE", 6, "A machine or PLC that publishes Metrics"),
)

# Named ancestor segments per Asset. Recursion is needed here (unlike in Python,
# where the candidate paths are just the topic's prefixes) because SQL has no
# cheap way to split a path and look each prefix up.
ASSET_LINEAGE_VIEW = """
CREATE OR REPLACE VIEW model.asset_lineage AS
WITH RECURSIVE lineage AS (
    SELECT a.id AS asset_id, a.parent_id, a.level, a.segment, a.display_name
    FROM model.asset a
    UNION ALL
    SELECT l.asset_id, p.parent_id, p.level, p.segment, p.display_name
    FROM lineage l
    JOIN model.asset p ON p.id = l.parent_id
)
SELECT
    asset_id,
    jsonb_object_agg(level, segment) AS levels,
    jsonb_object_agg(level, COALESCE(display_name, segment)) AS level_names
FROM lineage
GROUP BY asset_id
"""

ASSET_LINEAGE_COMMENT = (
    "COMMENT ON VIEW model.asset_lineage IS "
    "'Named ancestor segments per Asset, keyed by Asset Level. Feeds the enrichment views.'"
)

UNMODELLED_TOPIC_VIEW = """
CREATE OR REPLACE VIEW model.unmodelled_topic AS
SELECT topic, first_seen_at, resolved_at
FROM model.topic_binding
WHERE asset_id IS NULL
"""

UNMODELLED_TOPIC_COMMENT = (
    "COMMENT ON VIEW model.unmodelled_topic IS "
    "'Topics that have published data but match no Asset. A non-empty result means the Asset Model is incomplete.'"
)

# The Asset columns each observed row gets. Shared by both enrichment views so
# they cannot drift apart.
_ENRICHMENT_COLUMNS = """
    a.path AS asset_path,
    a.level AS asset_level,
    COALESCE(a.display_name, a.segment) AS asset_name,
    ln.levels ->> 'ENTERPRISE' AS enterprise,
    ln.levels ->> 'SITE' AS site,
    ln.levels ->> 'AREA' AS area,
    ln.levels ->> 'PRODUCTION_UNIT' AS production_unit,
    ln.levels ->> 'LINE' AS line,
    ln.levels ->> 'WORK_CELL' AS work_cell,
    ln.levels ->> 'MACHINE' AS machine,
    a.manufacturer,
    a.criticality,
    a.attributes AS asset_attributes,
    COALESCE(d_asset.display_name, d_any.display_name) AS metric_display_name,
    COALESCE(d_asset.unit_of_measure, d_any.unit_of_measure) AS unit_of_measure,
    COALESCE(d_asset.decimals, d_any.decimals) AS decimals,
    COALESCE(d_asset.min_value, d_any.min_value) AS min_value,
    COALESCE(d_asset.max_value, d_any.max_value) AS max_value
"""

# Two plain LEFT JOINs rather than a LATERAL with ORDER BY: the Asset-specific
# definition and the plant-wide one are fetched separately and COALESCEd, which
# stays a hash join instead of a per-row subquery.
_ENRICHMENT_JOINS = """
LEFT JOIN model.asset a ON a.id = bound.asset_id
LEFT JOIN model.asset_lineage ln ON ln.asset_id = a.id
LEFT JOIN model.metric_definition d_asset
       ON d_asset.asset_id = bound.asset_id
      AND d_asset.metric_key = bound.metric_key
LEFT JOIN model.metric_definition d_any
       ON d_any.asset_id IS NULL
      AND d_any.metric_key = bound.metric_key
"""

METRICS_ENRICHED_VIEW = f"""
CREATE OR REPLACE VIEW public.uns_metrics_enriched AS
WITH bound AS (
    SELECT
        m.time, m.topic, m.metric_name, m.value_double, m.value_text,
        b.asset_id,
        COALESCE(b.metric_path, '') AS metric_path,
        CASE
            WHEN COALESCE(b.metric_path, '') = '' THEN m.metric_name
            ELSE b.metric_path || '/' || m.metric_name
        END AS metric_key
    FROM public.uns_metrics m
    LEFT JOIN model.topic_binding b ON b.topic = m.topic
)
SELECT
    bound.time, bound.topic, bound.metric_name, bound.value_double, bound.value_text,
    bound.metric_path, bound.metric_key,
{_ENRICHMENT_COLUMNS}
FROM bound
{_ENRICHMENT_JOINS}
"""

METRICS_ENRICHED_COMMENT = (
    "COMMENT ON VIEW public.uns_metrics_enriched IS "
    "'uns_metrics joined to the Asset Model. Rows for Unmodelled Topics survive with null Asset columns.'"
)
METRICS_1M_ENRICHED_VIEW = f"""
CREATE OR REPLACE VIEW public.uns_metrics_1m_enriched AS
WITH bound AS (
    SELECT
        m.bucket, m.topic, m.metric_name, m.avg_value_double, m.sample_count,
        b.asset_id,
        COALESCE(b.metric_path, '') AS metric_path,
        CASE
            WHEN COALESCE(b.metric_path, '') = '' THEN m.metric_name
            ELSE b.metric_path || '/' || m.metric_name
        END AS metric_key
    FROM public.uns_metrics_1m m
    LEFT JOIN model.topic_binding b ON b.topic = m.topic
)
SELECT
    bound.bucket, bound.topic, bound.metric_name, bound.avg_value_double, bound.sample_count,
    bound.metric_path, bound.metric_key,
{_ENRICHMENT_COLUMNS}
FROM bound
{_ENRICHMENT_JOINS}
"""

METRICS_1M_ENRICHED_COMMENT = (
    "COMMENT ON VIEW public.uns_metrics_1m_enriched IS "
    "'The 1-minute continuous aggregate joined to the Asset Model. This is what Grafana panels should query.'"
)


def _execute_view(view_sql: str, comment_sql: str) -> None:
    # Separate executes: asyncpg rejects CREATE VIEW and COMMENT in one prepared statement.
    op.execute(view_sql)
    op.execute(comment_sql)


def _create_view_if_source_exists(source: str, view_sql: str, comment_sql: str, view_name: str) -> None:
    """
    Create an enrichment view only when its hypertable is present.

    `alembic upgrade head` has to succeed on a database where
    04_uns_historian/sql_scripts have not been applied yet (ADR-0004), so a
    missing hypertable is a warning rather than a failure. The check is done here
    rather than in a plpgsql DO block so that the view SQL stays plain SQL.
    """
    if context.is_offline_mode():
        # Nothing to query, and whoever asked for the SQL wants to see all of it.
        _execute_view(view_sql, comment_sql)
        return

    exists = op.get_bind().execute(sa.text("SELECT to_regclass(:source)"), {"source": source}).scalar()
    if exists is None:
        LOGGER.warning(
            "%s does not exist, so %s was not created. Apply 04_uns_historian/sql_scripts, "
            "then `alembic downgrade -1 && alembic upgrade head` to add it.",
            source,
            view_name,
        )
        return
    _execute_view(view_sql, comment_sql)


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(SCHEMA, if_not_exists=True))
    op.execute(
        f"COMMENT ON SCHEMA {SCHEMA} IS "
        "'The authored Asset Model: what the plant is, as maintained by engineers. Not time-series.'"
    )

    op.create_table(
        "asset_level",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("name"),
        sa.UniqueConstraint("rank"),
        schema=SCHEMA,
    )
    op.bulk_insert(
        sa.table(
            "asset_level",
            sa.column("name", sa.Text),
            sa.column("rank", sa.SmallInteger),
            sa.column("description", sa.Text),
            schema=SCHEMA,
        ),
        [{"name": name, "rank": rank, "description": description} for name, rank, description in ASSET_LEVELS],
    )

    op.create_table(
        "asset",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("segment", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("manufacturer", sa.Text(), nullable=True),
        sa.Column("model_number", sa.Text(), nullable=True),
        sa.Column("serial_number", sa.Text(), nullable=True),
        sa.Column("criticality", sa.Text(), nullable=True),
        sa.Column("commissioned_on", sa.Date(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parent_id"], [f"{SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["level"], [f"{SCHEMA}.asset_level.name"], onupdate="CASCADE"),
        sa.UniqueConstraint("path", name="uq_asset_path"),
        sa.UniqueConstraint("parent_id", "segment", name="uq_asset_sibling_segment"),
        sa.CheckConstraint("segment <> ''", name="ck_asset_segment_not_empty"),
        # right()/length() rather than LIKE: '%/' || segment would treat an
        # underscore in the segment as a wildcard and let a wrong path through.
        sa.CheckConstraint(
            "path = segment OR right(path, length(segment) + 1) = '/' || segment",
            name="ck_asset_path_ends_with_segment",
        ),
        sa.CheckConstraint("id <> parent_id", name="ck_asset_not_its_own_parent"),
        schema=SCHEMA,
    )
    op.create_index("idx_asset_parent", "asset", ["parent_id"], schema=SCHEMA)
    op.create_index("idx_asset_level", "asset", ["level"], schema=SCHEMA)

    op.create_table(
        "metric_definition",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("unit_of_measure", sa.Text(), nullable=True),
        sa.Column("decimals", sa.SmallInteger(), nullable=True),
        sa.Column("min_value", sa.Double(), nullable=True),
        sa.Column("max_value", sa.Double(), nullable=True),
        sa.Column("deadband", sa.Double(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{SCHEMA}.asset.id"], ondelete="CASCADE"),
        # NULLS NOT DISTINCT so that the one plant-wide row per Metric Key is
        # actually unique; without it Postgres would allow any number of them.
        sa.UniqueConstraint(
            "asset_id",
            "metric_key",
            name="uq_metric_definition_asset_key",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("metric_key <> ''", name="ck_metric_definition_key_not_empty"),
        sa.CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_metric_definition_range",
        ),
        schema=SCHEMA,
    )
    op.create_index("idx_metric_definition_key", "metric_definition", ["metric_key"], schema=SCHEMA)

    op.create_table(
        "topic_binding",
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("metric_path", sa.Text(), server_default="", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("topic"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{SCHEMA}.asset.id"], ondelete="SET NULL"),
        schema=SCHEMA,
    )
    op.create_index("idx_topic_binding_asset", "topic_binding", ["asset_id"], schema=SCHEMA)

    _execute_view(ASSET_LINEAGE_VIEW, ASSET_LINEAGE_COMMENT)
    _execute_view(UNMODELLED_TOPIC_VIEW, UNMODELLED_TOPIC_COMMENT)
    _create_view_if_source_exists(
        "public.uns_metrics", METRICS_ENRICHED_VIEW, METRICS_ENRICHED_COMMENT, "public.uns_metrics_enriched"
    )
    _create_view_if_source_exists(
        "public.uns_metrics_1m",
        METRICS_1M_ENRICHED_VIEW,
        METRICS_1M_ENRICHED_COMMENT,
        "public.uns_metrics_1m_enriched",
    )
    # Same grant pattern as 04_uns_historian/sql_scripts: the role is created
    # interactively, so it may not exist yet.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
                GRANT USAGE ON SCHEMA {SCHEMA} TO uns_dbuser;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO uns_dbuser;
                ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uns_dbuser;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public.uns_metrics_1m_enriched")
    op.execute("DROP VIEW IF EXISTS public.uns_metrics_enriched")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.unmodelled_topic")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.asset_lineage")
    op.drop_table("topic_binding", schema=SCHEMA)
    op.drop_table("metric_definition", schema=SCHEMA)
    op.drop_table("asset", schema=SCHEMA)
    op.drop_table("asset_level", schema=SCHEMA)
