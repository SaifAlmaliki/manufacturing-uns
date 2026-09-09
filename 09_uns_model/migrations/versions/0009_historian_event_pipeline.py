"""Historian event identity, checkpoints and late-refresh worklist.

Revision ID: 0009_historian_event_pipeline
Revises: 0008_connectivity_plc_protocols
Create Date: 2026-09-09
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0009_historian_event_pipeline"
down_revision: str | None = "0008_connectivity_plc_protocols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOGGER = logging.getLogger("alembic.runtime.migration")

PIPELINE_SCHEMA = "historian"
RAW_TABLE = "public.unifiednamespace"
METRICS_TABLE = "public.uns_metrics"

CREATE_PGCRYPTO = "CREATE EXTENSION IF NOT EXISTS pgcrypto"

CREATE_PIPELINE_SCHEMA = f"CREATE SCHEMA IF NOT EXISTS {PIPELINE_SCHEMA}"

COMMENT_PIPELINE_SCHEMA = (
    f"COMMENT ON SCHEMA {PIPELINE_SCHEMA} IS "
    "'Kafka historian pipeline metadata: partition checkpoints and late aggregate refresh work.'"
)

DECOMPRESS_RAW_CHUNKS = f"""
DO $$
DECLARE
  chunk regclass;
BEGIN
  IF to_regclass('{RAW_TABLE}') IS NOT NULL THEN
    FOR chunk IN SELECT show_chunks('{RAW_TABLE}') LOOP
      PERFORM decompress_chunk(chunk, if_compressed => true);
    END LOOP;
  END IF;
END
$$"""

ADD_RAW_EVENT_ID = f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS event_id TEXT"
ADD_RAW_IDENTITY_QUALITY = (
    f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS identity_quality TEXT DEFAULT 'ingress'"
)
ADD_RAW_RECEIVED_AT = f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ"
ADD_RAW_EVENT_KIND = (
    f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS event_kind TEXT DEFAULT 'telemetry'"
)
ADD_RAW_IS_HISTORICAL = (
    f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS is_historical BOOLEAN DEFAULT false"
)
ADD_RAW_SITE_ID = f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS site_id TEXT"
ADD_RAW_SOURCE_ID = f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS source_id TEXT"
ADD_RAW_SOURCE_BOOT_ID = f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS source_boot_id TEXT"
ADD_RAW_SOURCE_SEQUENCE = f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS source_sequence BIGINT"
ADD_RAW_TIMESTAMP_QUALITY = (
    f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS timestamp_quality TEXT DEFAULT 'ingress'"
)
ADD_RAW_CONTENT_HASH = f"ALTER TABLE {RAW_TABLE} ADD COLUMN IF NOT EXISTS immutable_content_hash TEXT"

_LEGACY_JSON_ARRAY = """
regexp_replace(
  regexp_replace(
    json_build_array({parts})::text,
    ', ',
    ',',
    'g'
  ),
  ': ',
  ':',
  'g'
)
"""

BACKFILL_RAW_IDENTITY = f"""
UPDATE {RAW_TABLE}
SET
  received_at = COALESCE(received_at, time),
  event_kind = COALESCE(event_kind, 'telemetry'),
  is_historical = COALESCE(is_historical, false),
  identity_quality = COALESCE(identity_quality, 'ingress'),
  timestamp_quality = COALESCE(timestamp_quality, 'ingress'),
  immutable_content_hash = COALESCE(
    immutable_content_hash,
    encode(
      digest(
        convert_to(
          {_LEGACY_JSON_ARRAY.format(
              parts=(
                  "to_char(time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), "
                  "topic, mqtt_msg::jsonb"
              )
          )},
          'UTF8'
        ),
        'sha256'
      ),
      'hex'
    )
  ),
  event_id = COALESCE(
    event_id,
    'legacy:' || encode(
      digest(
        convert_to(
          {_LEGACY_JSON_ARRAY.format(
              parts=(
                  "to_char(time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), "
                  "topic, coalesce(client_id, ''), mqtt_msg::jsonb"
              )
          )},
          'UTF8'
        ),
        'sha256'
      ),
      'hex'
    )
  )
WHERE event_id IS NULL
"""

SET_RAW_NOT_NULL = f"""
ALTER TABLE {RAW_TABLE}
  ALTER COLUMN event_id SET NOT NULL,
  ALTER COLUMN identity_quality SET NOT NULL,
  ALTER COLUMN received_at SET NOT NULL,
  ALTER COLUMN event_kind SET NOT NULL,
  ALTER COLUMN is_historical SET NOT NULL,
  ALTER COLUMN timestamp_quality SET NOT NULL,
  ALTER COLUMN immutable_content_hash SET NOT NULL
"""

DROP_LEGACY_UNIQUE = f"ALTER TABLE {RAW_TABLE} DROP CONSTRAINT IF EXISTS unique_event"

ADD_EVENT_ID_UNIQUE = (
    f"ALTER TABLE {RAW_TABLE} ADD CONSTRAINT unique_historic_event UNIQUE (time, event_id)"
)

ADD_METRICS_EVENT_ID = f"ALTER TABLE {METRICS_TABLE} ADD COLUMN IF NOT EXISTS event_id TEXT"

CREATE_CHECKPOINT_TABLE = f"""
CREATE TABLE IF NOT EXISTS {PIPELINE_SCHEMA}.kafka_partition_checkpoint (
  pipeline_epoch INTEGER NOT NULL,
  kafka_topic TEXT NOT NULL,
  partition_id INTEGER NOT NULL,
  next_offset BIGINT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (pipeline_epoch, kafka_topic, partition_id),
  CONSTRAINT kafka_partition_checkpoint_next_offset_nonneg CHECK (next_offset >= 0)
)
"""

COMMENT_CHECKPOINT_TABLE = (
    f"COMMENT ON TABLE {PIPELINE_SCHEMA}.kafka_partition_checkpoint IS "
    "'Authoritative Kafka next offset per pipeline epoch, topic and partition.'"
)

CREATE_LATE_REFRESH_TABLE = f"""
CREATE TABLE IF NOT EXISTS {PIPELINE_SCHEMA}.late_refresh_worklist (
  utc_day DATE NOT NULL PRIMARY KEY,
  pending_generation BIGINT NOT NULL DEFAULT 0,
  processed_generation BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT late_refresh_generation_order CHECK (processed_generation <= pending_generation)
)
"""

COMMENT_LATE_REFRESH_TABLE = (
    f"COMMENT ON TABLE {PIPELINE_SCHEMA}.late_refresh_worklist IS "
    "'UTC-day coalesced late telemetry refresh generations for continuous aggregates.'"
)

GRANT_PIPELINE = f"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
    GRANT USAGE ON SCHEMA {PIPELINE_SCHEMA} TO uns_dbuser;
    GRANT SELECT, INSERT, UPDATE, DELETE ON {PIPELINE_SCHEMA}.kafka_partition_checkpoint TO uns_dbuser;
    GRANT SELECT, INSERT, UPDATE, DELETE ON {PIPELINE_SCHEMA}.late_refresh_worklist TO uns_dbuser;
  END IF;
END
$$"""


def _raw_table_exists() -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    return bind.execute(sa.text("SELECT to_regclass(:table)"), {"table": RAW_TABLE}).scalar() is not None


def _metrics_table_exists() -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    return bind.execute(sa.text("SELECT to_regclass(:table)"), {"table": METRICS_TABLE}).scalar() is not None


def _upgrade_raw_table() -> None:
    if not _raw_table_exists():
        LOGGER.warning(
            "%s does not exist; skipping raw hypertable identity migration. "
            "Apply 04_uns_historian/sql_scripts first, then downgrade and upgrade this revision.",
            RAW_TABLE,
        )
        return

    op.execute(DECOMPRESS_RAW_CHUNKS)
    op.execute(ADD_RAW_EVENT_ID)
    op.execute(ADD_RAW_IDENTITY_QUALITY)
    op.execute(ADD_RAW_RECEIVED_AT)
    op.execute(ADD_RAW_EVENT_KIND)
    op.execute(ADD_RAW_IS_HISTORICAL)
    op.execute(ADD_RAW_SITE_ID)
    op.execute(ADD_RAW_SOURCE_ID)
    op.execute(ADD_RAW_SOURCE_BOOT_ID)
    op.execute(ADD_RAW_SOURCE_SEQUENCE)
    op.execute(ADD_RAW_TIMESTAMP_QUALITY)
    op.execute(ADD_RAW_CONTENT_HASH)
    op.execute(BACKFILL_RAW_IDENTITY)
    op.execute(SET_RAW_NOT_NULL)
    op.execute(DROP_LEGACY_UNIQUE)
    op.execute(ADD_EVENT_ID_UNIQUE)


def _upgrade_metrics_table() -> None:
    if not _metrics_table_exists():
        LOGGER.warning(
            "%s does not exist; skipping metrics event_id column. "
            "Apply 04_uns_historian/sql_scripts first, then downgrade and upgrade this revision.",
            METRICS_TABLE,
        )
        return
    op.execute(ADD_METRICS_EVENT_ID)


def upgrade() -> None:
    op.execute(CREATE_PGCRYPTO)
    op.execute(CREATE_PIPELINE_SCHEMA)
    op.execute(COMMENT_PIPELINE_SCHEMA)
    _upgrade_raw_table()
    _upgrade_metrics_table()
    op.execute(CREATE_CHECKPOINT_TABLE)
    op.execute(COMMENT_CHECKPOINT_TABLE)
    op.execute(CREATE_LATE_REFRESH_TABLE)
    op.execute(COMMENT_LATE_REFRESH_TABLE)
    op.execute(GRANT_PIPELINE)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {PIPELINE_SCHEMA}.late_refresh_worklist")
    op.execute(f"DROP TABLE IF EXISTS {PIPELINE_SCHEMA}.kafka_partition_checkpoint")
    op.execute(f"DROP SCHEMA IF EXISTS {PIPELINE_SCHEMA} CASCADE")

    if _metrics_table_exists():
        op.execute(f"ALTER TABLE {METRICS_TABLE} DROP COLUMN IF EXISTS event_id")

    if not _raw_table_exists():
        return

    op.execute(DECOMPRESS_RAW_CHUNKS)
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP CONSTRAINT IF EXISTS unique_historic_event")
    op.execute(
        f"ALTER TABLE {RAW_TABLE} ADD CONSTRAINT unique_event UNIQUE (time, topic, client_id, mqtt_msg)"
    )
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS immutable_content_hash")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS timestamp_quality")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS source_sequence")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS source_boot_id")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS source_id")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS site_id")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS is_historical")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS event_kind")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS received_at")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS identity_quality")
    op.execute(f"ALTER TABLE {RAW_TABLE} DROP COLUMN IF EXISTS event_id")
