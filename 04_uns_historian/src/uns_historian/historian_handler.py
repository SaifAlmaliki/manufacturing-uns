"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Persist MQTT messages to the historian hypertables.

Uses SQLAlchemy Core on the shared `uns_model.engine.Database`, not a separate
asyncpg pool (ADR-0004). The ORM is deliberately not involved: each message is one
raw row plus N metric rows, written once and never updated in the same transaction.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import TIMESTAMP, Text, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from uns_model.engine import Database
from uns_model.historian_pipeline import legacy_migration_content_hash, legacy_migration_event_id

from uns_historian.batch import (
    BatchLimits,
    BatchPersistResult,
    ConsumedEvent,
    ContentConflictError,
    HISTORIC_KAFKA_TOPIC,
    PIPELINE_SCHEMA,
    build_metric_rows,
    compute_next_offset,
    raw_row_from_event,
    sorted_partition_keys,
    utc_day,
)
from uns_historian.historian_config import HistorianConfig
from uns_historian.metric_flattener import flatten_payload_to_metrics

LOGGER = logging.getLogger(__name__)

_RAW_INSERT = text(
    f"INSERT INTO {HistorianConfig.table} "  # noqa: S608
    "(time, topic, client_id, mqtt_msg, event_id, identity_quality, received_at, event_kind, "
    "is_historical, timestamp_quality, immutable_content_hash) "
    "VALUES (:time, :topic, :client_id, :mqtt_msg, :event_id, :identity_quality, :received_at, "
    ":event_kind, :is_historical, :timestamp_quality, :immutable_content_hash) "
    "ON CONFLICT ON CONSTRAINT unique_historic_event DO NOTHING "
    "RETURNING time, topic, client_id, mqtt_msg"
).bindparams(
    bindparam("time", type_=TIMESTAMP(timezone=True)),
    bindparam("topic", type_=Text),
    bindparam("client_id", type_=Text),
    bindparam("mqtt_msg", type_=JSONB),
    bindparam("event_id", type_=Text),
    bindparam("identity_quality", type_=Text),
    bindparam("received_at", type_=TIMESTAMP(timezone=True)),
    bindparam("event_kind", type_=Text),
    bindparam("is_historical"),
    bindparam("timestamp_quality", type_=Text),
    bindparam("immutable_content_hash", type_=Text),
)

_RAW_BATCH_INSERT = text(
    f"INSERT INTO {HistorianConfig.table} "  # noqa: S608
    "(time, topic, client_id, mqtt_msg, event_id, identity_quality, received_at, event_kind, "
    "is_historical, site_id, source_id, source_boot_id, source_sequence, timestamp_quality, "
    "immutable_content_hash) "
    "VALUES (:time, :topic, :client_id, :mqtt_msg, :event_id, :identity_quality, :received_at, "
    ":event_kind, :is_historical, :site_id, :source_id, :source_boot_id, :source_sequence, "
    ":timestamp_quality, :immutable_content_hash) "
    "ON CONFLICT ON CONSTRAINT unique_historic_event DO NOTHING "
    "RETURNING event_id, event_kind, time, is_historical"
).bindparams(
    bindparam("time", type_=TIMESTAMP(timezone=True)),
    bindparam("topic", type_=Text),
    bindparam("client_id", type_=Text),
    bindparam("mqtt_msg", type_=JSONB),
    bindparam("event_id", type_=Text),
    bindparam("identity_quality", type_=Text),
    bindparam("received_at", type_=TIMESTAMP(timezone=True)),
    bindparam("event_kind", type_=Text),
    bindparam("is_historical"),
    bindparam("site_id", type_=Text),
    bindparam("source_id", type_=Text),
    bindparam("source_boot_id", type_=Text),
    bindparam("source_sequence"),
    bindparam("timestamp_quality", type_=Text),
    bindparam("immutable_content_hash", type_=Text),
)

_METRICS_INSERT = text(
    f"INSERT INTO {HistorianConfig.metrics_table} "  # noqa: S608
    "(time, topic, metric_name, value_double, value_text, event_id) "
    "VALUES (:time, :topic, :metric_name, :value_double, :value_text, :event_id)"
)

_CHECKPOINT_ENSURE = text(
    f"INSERT INTO {PIPELINE_SCHEMA}.kafka_partition_checkpoint "  # noqa: S608
    "(pipeline_epoch, kafka_topic, partition_id, next_offset) "
    "VALUES (:pipeline_epoch, :kafka_topic, :partition_id, 0) "
    "ON CONFLICT (pipeline_epoch, kafka_topic, partition_id) DO NOTHING"
)

_CHECKPOINT_LOCK = text(
    f"SELECT partition_id, next_offset FROM {PIPELINE_SCHEMA}.kafka_partition_checkpoint "  # noqa: S608
    "WHERE pipeline_epoch = :pipeline_epoch AND kafka_topic = :kafka_topic "
    "AND partition_id = :partition_id "
    "ORDER BY partition_id FOR UPDATE"
)

_EXISTING_CONTENT = text(
    f"SELECT immutable_content_hash FROM {HistorianConfig.table} "  # noqa: S608
    "WHERE time = :time AND event_id = :event_id"
)

_CHECKPOINT_READ = text(
    f"SELECT next_offset FROM {PIPELINE_SCHEMA}.kafka_partition_checkpoint "  # noqa: S608
    "WHERE pipeline_epoch = :pipeline_epoch AND kafka_topic = :kafka_topic "
    "AND partition_id = :partition_id"
)

_CHECKPOINT_ADVANCE = text(
    f"UPDATE {PIPELINE_SCHEMA}.kafka_partition_checkpoint "  # noqa: S608
    "SET next_offset = :next_offset, updated_at = now() "
    "WHERE pipeline_epoch = :pipeline_epoch AND kafka_topic = :kafka_topic "
    "AND partition_id = :partition_id AND next_offset <= :next_offset"
)

_LATE_REFRESH_BUMP = text(
    f"INSERT INTO {PIPELINE_SCHEMA}.late_refresh_worklist "  # noqa: S608
    "(utc_day, pending_generation, processed_generation) "
    "VALUES (:utc_day, 1, 0) "
    "ON CONFLICT (utc_day) DO UPDATE SET "
    f"pending_generation = {PIPELINE_SCHEMA}.late_refresh_worklist.pending_generation + 1, "
    "updated_at = now()"
)


def _asyncpg_params_to_sqlalchemy(query: str, args: tuple[object, ...]) -> tuple[str, dict[str, object]]:
    """Tests still pass `$1` SQL from the asyncpg era; Core wants `:p1` binds."""
    params = {f"p{i}": arg for i, arg in enumerate(args, start=1)}
    converted = query
    for index in range(len(args), 0, -1):
        converted = converted.replace(f"${index}", f":p{index}")
    return converted, params


class HistorianHandler:
    """
    Class to encapsulate logic of persisting messages to the historian database
    """

    _database: Database | None = None

    @classmethod
    def _shared_database(cls) -> Database:
        if cls._database is None:
            cls._database = Database.shared("historian")
        return cls._database

    @classmethod
    async def warm(cls) -> Database:
        """Ensure the shared engine exists. Called once at startup."""
        return cls._shared_database()

    @classmethod
    async def close_pool(cls) -> None:
        """Dispose the shared engine."""
        await cls.close()

    @classmethod
    async def close(cls) -> None:
        cls._database = None
        await Database.close_shared()

    def __init__(self, database: Database | None = None) -> None:
        self._database = database or self._shared_database()

    async def __aenter__(self) -> HistorianHandler:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute_prepared(self, query: str, *args: object) -> list[Mapping[str, Any]]:
        """
        Run a parameterised SQL statement and return any rows.

        Accepts legacy `$1` placeholders for integration tests written against asyncpg.
        """
        converted, params = _asyncpg_params_to_sqlalchemy(query, args)
        async with self._database.begin() as connection:
            result = await connection.execute(text(converted), params)
            if result.returns_rows:
                return result.mappings().all()
            return []

    @staticmethod
    def to_utc_datetime(timestamp: float | None) -> datetime:
        """
        Convert an MQTT epoch timestamp to a timezone-aware UTC datetime.

        Accepts seconds or milliseconds. Values below 1e12 are treated as seconds
        because some publishers send seconds.
        """
        if timestamp is None:
            return datetime.now(UTC)
        ts = float(timestamp)
        if ts < 1e12:
            ts *= 1000
        return datetime.fromtimestamp(ts / 1000, UTC)

    @staticmethod
    def batch_limits() -> BatchLimits:
        return BatchLimits(
            max_events=HistorianConfig.batch_max_events,
            max_bytes=HistorianConfig.batch_max_bytes,
            max_age_seconds=HistorianConfig.batch_max_age_seconds,
            max_metric_rows=HistorianConfig.batch_max_metric_rows,
        )

    @staticmethod
    def _metrics_insert_rows(
        db_timestamp: datetime,
        topic: str,
        message: dict,
        *,
        event_id: str | None = None,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for metric_name, value_double, value_text in flatten_payload_to_metrics(message):
            row = {
                "time": db_timestamp,
                "topic": topic,
                "metric_name": metric_name,
                "value_double": value_double,
                "value_text": value_text,
            }
            if event_id is not None:
                row["event_id"] = event_id
            rows.append(row)
        return rows

    async def persist_batch(
        self,
        events: Sequence[ConsumedEvent],
        pipeline_epoch: int,
        *,
        limits: BatchLimits | None = None,
    ) -> BatchPersistResult:
        if not events:
            return BatchPersistResult(
                inserted_count=0,
                duplicate_count=0,
                filtered_stale_count=0,
                quarantined_conflicts=(),
                next_offsets={},
            )

        limits = limits or self.batch_limits()
        sorted_events = sorted(events, key=lambda event: (event.kafka_topic, event.partition, event.offset))
        raw_rows = [raw_row_from_event(event) for event in sorted_events]

        metric_rows: list = []
        for raw_row in raw_rows:
            metric_rows.extend(build_metric_rows(raw_row, limits=limits))

        async with self._database.begin() as connection:
            checkpoints: dict[tuple[str, int], int] = {}
            for kafka_topic_name, partition_id in sorted_partition_keys(sorted_events):
                await connection.execute(
                    _CHECKPOINT_ENSURE,
                    {
                        "pipeline_epoch": pipeline_epoch,
                        "kafka_topic": kafka_topic_name,
                        "partition_id": partition_id,
                    },
                )
                locked = (
                    await connection.execute(
                        _CHECKPOINT_LOCK,
                        {
                            "pipeline_epoch": pipeline_epoch,
                            "kafka_topic": kafka_topic_name,
                            "partition_id": partition_id,
                        },
                    )
                ).mappings().one()
                checkpoints[(kafka_topic_name, partition_id)] = locked["next_offset"]

            accepted_rows: list = []
            handled_by_partition: dict[tuple[str, int], list[int]] = {}
            filtered_stale_count = 0
            duplicate_count = 0
            quarantined: list[ContentConflictError] = []

            for raw_row in raw_rows:
                partition_key = (raw_row.kafka_topic, raw_row.partition)
                checkpoint = checkpoints[partition_key]
                if raw_row.offset < checkpoint:
                    filtered_stale_count += 1
                    continue

                existing_hash = (
                    await connection.execute(
                        _EXISTING_CONTENT,
                        {"time": raw_row.time, "event_id": raw_row.event_id},
                    )
                ).scalar_one_or_none()
                if existing_hash is not None:
                    handled_by_partition.setdefault(partition_key, []).append(raw_row.offset)
                    if existing_hash != raw_row.immutable_content_hash:
                        quarantined.append(
                            ContentConflictError(
                                raw_row.event_id,
                                existing_hash=existing_hash,
                                incoming_hash=raw_row.immutable_content_hash,
                            )
                        )
                    else:
                        duplicate_count += 1
                    continue

                accepted_rows.append(raw_row)
                handled_by_partition.setdefault(partition_key, []).append(raw_row.offset)

            inserted_event_ids: set[str] = set()
            if accepted_rows:
                insert_result = await connection.execute(
                    _RAW_BATCH_INSERT,
                    [
                        {
                            "time": row.time,
                            "topic": row.topic,
                            "client_id": row.client_id,
                            "mqtt_msg": row.mqtt_msg,
                            "event_id": row.event_id,
                            "identity_quality": row.identity_quality,
                            "received_at": row.received_at,
                            "event_kind": row.event_kind,
                            "is_historical": row.is_historical,
                            "site_id": row.site_id,
                            "source_id": row.source_id,
                            "source_boot_id": row.source_boot_id,
                            "source_sequence": row.source_sequence,
                            "timestamp_quality": row.timestamp_quality,
                            "immutable_content_hash": row.immutable_content_hash,
                        }
                        for row in accepted_rows
                    ],
                )
                returned = insert_result.mappings().all()
                inserted_event_ids = {row["event_id"] for row in returned}
                duplicate_count += len(accepted_rows) - len(returned)

                metric_payload = [
                    {
                        "time": metric.time,
                        "topic": metric.topic,
                        "metric_name": metric.metric_name,
                        "value_double": metric.value_double,
                        "value_text": metric.value_text,
                        "event_id": metric.event_id,
                    }
                    for metric in metric_rows
                    if metric.event_id in inserted_event_ids
                ]
                if metric_payload:
                    await connection.execute(_METRICS_INSERT, metric_payload)

                for row in returned:
                    if row["event_kind"] == "telemetry" and row["is_historical"]:
                        await connection.execute(_LATE_REFRESH_BUMP, {"utc_day": utc_day(row["time"])})

            next_offsets: dict[tuple[str, int], int] = {}
            for partition_key, handled_offsets in handled_by_partition.items():
                kafka_topic_name, partition_id = partition_key
                advanced = compute_next_offset(checkpoints[partition_key], handled_offsets)
                if advanced > checkpoints[partition_key]:
                    await connection.execute(
                        _CHECKPOINT_ADVANCE,
                        {
                            "pipeline_epoch": pipeline_epoch,
                            "kafka_topic": kafka_topic_name,
                            "partition_id": partition_id,
                            "next_offset": advanced,
                        },
                    )
                    next_offsets[partition_key] = advanced

            return BatchPersistResult(
                inserted_count=len(inserted_event_ids),
                duplicate_count=duplicate_count,
                filtered_stale_count=filtered_stale_count,
                quarantined_conflicts=tuple(quarantined),
                next_offsets=next_offsets,
            )

    async def read_partition_checkpoints(
        self,
        pipeline_epoch: int,
        kafka_topic: str,
        partition_ids: Sequence[int],
    ) -> dict[int, int]:
        checkpoints: dict[int, int] = {}
        if not partition_ids:
            return checkpoints
        async with self._database.begin() as connection:
            for partition_id in sorted(partition_ids):
                await connection.execute(
                    _CHECKPOINT_ENSURE,
                    {
                        "pipeline_epoch": pipeline_epoch,
                        "kafka_topic": kafka_topic,
                        "partition_id": partition_id,
                    },
                )
                next_offset = (
                    await connection.execute(
                        _CHECKPOINT_READ,
                        {
                            "pipeline_epoch": pipeline_epoch,
                            "kafka_topic": kafka_topic,
                            "partition_id": partition_id,
                        },
                    )
                ).scalar_one_or_none()
                checkpoints[partition_id] = 0 if next_offset is None else int(next_offset)
        return checkpoints

    async def persist_mqtt_msg(
        self,
        client_id: str,
        topic: str,
        timestamp: float | None,
        message: dict,
    ) -> list[Mapping[str, Any]]:
        """
        Persists all mqtt message in the historian
        ----------
        client_id:
            Identifier for the Subscriber
        topic: str
            The topic on which the message was sent
        timestamp
            The timestamp of the message received in epoch seconds or milliseconds
        message: str
            The MQTT message. String is expected to be JSON formatted
        """
        db_timestamp = self.to_utc_datetime(timestamp)
        stored_payload = message if isinstance(message, dict) else json.loads(json.dumps(message))
        event_id = legacy_migration_event_id(db_timestamp, topic, client_id, stored_payload)
        content_hash = legacy_migration_content_hash(db_timestamp, topic, stored_payload)
        metric_rows = self._metrics_insert_rows(
            db_timestamp,
            topic,
            stored_payload,
            event_id=event_id,
        )

        async with self._database.begin() as connection:
            raw_result = await connection.execute(
                _RAW_INSERT,
                {
                    "time": db_timestamp,
                    "topic": topic,
                    "client_id": client_id,
                    "mqtt_msg": stored_payload,
                    "event_id": event_id,
                    "identity_quality": "ingress",
                    "received_at": db_timestamp,
                    "event_kind": "telemetry",
                    "is_historical": False,
                    "timestamp_quality": "ingress",
                    "immutable_content_hash": content_hash,
                },
            )
            inserted = raw_result.mappings().all()
            if inserted and metric_rows:
                await connection.execute(_METRICS_INSERT, metric_rows)
            return inserted
