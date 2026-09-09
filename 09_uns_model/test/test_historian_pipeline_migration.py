"""Integration tests for the historian event pipeline Alembic migration."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from uns_model.engine import Database
from uns_model.historian_pipeline import legacy_migration_content_hash, legacy_migration_event_id
from uns_model.model_config import ModelConfig

MODEL_DIR = Path(__file__).resolve().parents[1]
RAW_TABLE = "public.unifiednamespace"
METRICS_TABLE = "public.uns_metrics"
PIPELINE_SCHEMA = "historian"
REVISION = "0009_historian_event_pipeline"
LEGACY_TOPIC = "PyTestHistorianPipeline/Legacy/Device"


def _run_alembic(*args: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=MODEL_DIR,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(
            "alembic failed:\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def database():
    config = ModelConfig.from_settings()
    assert config.is_valid()
    db = Database.from_config(config)
    yield db
    await db.dispose()


async def _raw_table_exists(database: Database) -> bool:
    async with database.begin() as connection:
        return (
            await connection.execute(text("SELECT to_regclass(:table)"), {"table": RAW_TABLE})
        ).scalar() is not None


async def _clean_legacy_rows(database: Database) -> None:
    async with database.begin() as connection:
        if await _raw_table_exists(database):
            await connection.execute(
                text(f"DELETE FROM {RAW_TABLE} WHERE topic = :topic"),
                {"topic": LEGACY_TOPIC},
            )
        if (
            await connection.execute(text("SELECT to_regclass(:table)"), {"table": METRICS_TABLE})
        ).scalar() is not None:
            await connection.execute(
                text(f"DELETE FROM {METRICS_TABLE} WHERE topic = :topic"),
                {"topic": LEGACY_TOPIC},
            )
        if (
            await connection.execute(
                text(f"SELECT to_regclass('{PIPELINE_SCHEMA}.late_refresh_worklist')")
            )
        ).scalar() is not None:
            await connection.execute(
                text(
                    f"DELETE FROM {PIPELINE_SCHEMA}.late_refresh_worklist "
                    "WHERE utc_day = DATE '2026-09-01'"
                )
            )
        if (
            await connection.execute(
                text(f"SELECT to_regclass('{PIPELINE_SCHEMA}.kafka_partition_checkpoint')")
            )
        ).scalar() is not None:
            await connection.execute(
                text(
                    f"DELETE FROM {PIPELINE_SCHEMA}.kafka_partition_checkpoint "
                    "WHERE pipeline_epoch = 1 AND kafka_topic = 'uns.historic-events' AND partition_id = 0"
                )
            )


def test_legacy_migration_helpers_produce_stable_ids():
    event_time = datetime(2026, 9, 9, 10, 0, 0, 123456, tzinfo=UTC)
    payload = {"timestamp": 12345678, "value": 42.0}
    event_id = legacy_migration_event_id(event_time, LEGACY_TOPIC, "legacy-client", payload)
    content_hash = legacy_migration_content_hash(event_time, LEGACY_TOPIC, payload)
    assert event_id.startswith("legacy:")
    assert len(content_hash) == 64
    assert legacy_migration_event_id(event_time, LEGACY_TOPIC, "legacy-client", payload) == event_id


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_migration_upgrade_twice_and_pipeline_tables_exist(database: Database):
    if not await _raw_table_exists(database):
        pytest.skip(f"{RAW_TABLE} is missing: apply 04_uns_historian/sql_scripts first")

    await _clean_legacy_rows(database)
    _run_alembic("upgrade", REVISION)
    _run_alembic("upgrade", "head")

    async with database.begin() as connection:
        columns = (
            await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'unifiednamespace'"
                )
            )
        ).scalars().all()
        assert "event_id" in columns
        assert "immutable_content_hash" in columns
        checkpoint = (
            await connection.execute(
                text(f"SELECT to_regclass('{PIPELINE_SCHEMA}.kafka_partition_checkpoint')")
            )
        ).scalar()
        worklist = (
            await connection.execute(
                text(f"SELECT to_regclass('{PIPELINE_SCHEMA}.late_refresh_worklist')")
            )
        ).scalar()
        assert checkpoint is not None
        assert worklist is not None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_migration_backfills_legacy_rows_and_preserves_query_columns(database: Database):
    if not await _raw_table_exists(database):
        pytest.skip(f"{RAW_TABLE} is missing: apply 04_uns_historian/sql_scripts first")

    await _clean_legacy_rows(database)
    _run_alembic("downgrade", "0008_connectivity_plc_protocols")

    event_time = datetime(2026, 9, 9, 10, 15, 0, tzinfo=UTC)
    payload = {"timestamp": 12345678, "value": 99.5}
    expected_event_id = legacy_migration_event_id(event_time, LEGACY_TOPIC, "legacy-client", payload)
    expected_hash = legacy_migration_content_hash(event_time, LEGACY_TOPIC, payload)

    async with database.begin() as connection:
        await connection.execute(
            text(
                f"INSERT INTO {RAW_TABLE} (time, topic, client_id, mqtt_msg) "
                "VALUES (:time, :topic, :client_id, CAST(:mqtt_msg AS jsonb))"
            ),
            {
                "time": event_time,
                "topic": LEGACY_TOPIC,
                "client_id": "legacy-client",
                "mqtt_msg": json.dumps(payload),
            },
        )

    _run_alembic("upgrade", "head")

    async with database.begin() as connection:
        row = (
            await connection.execute(
                text(
                    f"SELECT time, topic, client_id, mqtt_msg, event_id, identity_quality, "
                    f"immutable_content_hash FROM {RAW_TABLE} WHERE topic = :topic"
                ),
                {"topic": LEGACY_TOPIC},
            )
        ).mappings().one()
        assert row["topic"] == LEGACY_TOPIC
        assert row["client_id"] == "legacy-client"
        assert row["mqtt_msg"] == payload
        assert row["event_id"] == expected_event_id
        assert row["identity_quality"] == "ingress"
        assert row["immutable_content_hash"] == expected_hash


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_time_event_id_unique_constraint_on_timescale(database: Database):
    if not await _raw_table_exists(database):
        pytest.skip(f"{RAW_TABLE} is missing: apply 04_uns_historian/sql_scripts first")

    event_time = datetime(2026, 9, 9, 11, 0, 0, tzinfo=UTC)
    event_id = "ingress:11111111-2222-4333-8444-555555555555"

    async with database.begin() as connection:
        await connection.execute(
            text(f"DELETE FROM {RAW_TABLE} WHERE event_id = :event_id"),
            {"event_id": event_id},
        )
        await connection.execute(
            text(
                f"INSERT INTO {RAW_TABLE} (time, topic, client_id, mqtt_msg, event_id, identity_quality, "
                "received_at, event_kind, is_historical, timestamp_quality, immutable_content_hash) "
                "VALUES (:time, :topic, NULL, CAST(:mqtt_msg AS jsonb), :event_id, 'ingress', :received_at, "
                "'telemetry', false, 'ingress', :content_hash)"
            ),
            {
                "time": event_time,
                "topic": LEGACY_TOPIC,
                "mqtt_msg": json.dumps({"value": 1}),
                "event_id": event_id,
                "received_at": event_time,
                "content_hash": "abc123",
            },
        )

    async with database.begin() as connection:
        with pytest.raises(Exception, match="unique_historic_event|duplicate key"):
            await connection.execute(
                text(
                    f"INSERT INTO {RAW_TABLE} (time, topic, client_id, mqtt_msg, event_id, identity_quality, "
                    "received_at, event_kind, is_historical, timestamp_quality, immutable_content_hash) "
                    "VALUES (:time, :topic, NULL, CAST(:mqtt_msg AS jsonb), :event_id, 'ingress', :received_at, "
                    "'telemetry', false, 'ingress', :content_hash)"
                ),
                {
                    "time": event_time,
                    "topic": "Other/Topic",
                    "mqtt_msg": json.dumps({"value": 2}),
                    "event_id": event_id,
                    "received_at": event_time,
                    "content_hash": "def456",
                },
            )

    async with database.begin() as connection:
        await connection.execute(
            text(f"DELETE FROM {RAW_TABLE} WHERE event_id = :event_id"),
            {"event_id": event_id},
        )


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_checkpoint_and_worklist_round_trip(database: Database):
    if not await _raw_table_exists(database):
        pytest.skip(f"{RAW_TABLE} is missing: apply 04_uns_historian/sql_scripts first")

    _run_alembic("upgrade", "head")

    async with database.begin() as connection:
        await connection.execute(
            text(
                f"INSERT INTO {PIPELINE_SCHEMA}.kafka_partition_checkpoint "
                "(pipeline_epoch, kafka_topic, partition_id, next_offset) "
                "VALUES (1, 'uns.historic-events', 0, 42) "
                "ON CONFLICT (pipeline_epoch, kafka_topic, partition_id) DO UPDATE SET next_offset = EXCLUDED.next_offset"
            )
        )
        await connection.execute(
            text(
                f"INSERT INTO {PIPELINE_SCHEMA}.late_refresh_worklist "
                "(utc_day, pending_generation, processed_generation) "
                "VALUES ('2026-09-01', 2, 1) "
                "ON CONFLICT (utc_day) DO UPDATE SET pending_generation = EXCLUDED.pending_generation, "
                "processed_generation = EXCLUDED.processed_generation"
            )
        )
        checkpoint = (
            await connection.execute(
                text(
                    f"SELECT next_offset FROM {PIPELINE_SCHEMA}.kafka_partition_checkpoint "
                    "WHERE pipeline_epoch = 1 AND kafka_topic = 'uns.historic-events' AND partition_id = 0"
                )
            )
        ).scalar_one()
        worklist = (
            await connection.execute(
                text(
                    f"SELECT pending_generation, processed_generation FROM {PIPELINE_SCHEMA}.late_refresh_worklist "
                    "WHERE utc_day = DATE '2026-09-01'"
                )
            )
        ).one()
        assert checkpoint == 42
        assert worklist.pending_generation == 2
        assert worklist.processed_generation == 1

    await _clean_legacy_rows(database)
