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
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import TIMESTAMP, Text, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from uns_model.engine import Database

from uns_historian.historian_config import HistorianConfig
from uns_historian.metric_flattener import flatten_payload_to_metrics

LOGGER = logging.getLogger(__name__)

_RAW_INSERT = text(
    f"INSERT INTO {HistorianConfig.table} (time, topic, client_id, mqtt_msg) "  # noqa: S608
    "VALUES (:time, :topic, :client_id, :mqtt_msg) "
    "ON CONFLICT DO NOTHING "
    "RETURNING time, topic, client_id, mqtt_msg"
).bindparams(
    bindparam("time", type_=TIMESTAMP(timezone=True)),
    bindparam("topic", type_=Text),
    bindparam("client_id", type_=Text),
    bindparam("mqtt_msg", type_=JSONB),
)

_METRICS_INSERT = text(
    f"INSERT INTO {HistorianConfig.metrics_table} "  # noqa: S608
    "(time, topic, metric_name, value_double, value_text) "
    "VALUES (:time, :topic, :metric_name, :value_double, :value_text)"
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
    async def get_shared_pool(cls) -> Database:
        """Backward-compatible alias for startup warm-up."""
        return await cls.warm()

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
        because some publishers (including the simulator) send seconds.
        """
        if timestamp is None:
            return datetime.now(UTC)
        ts = float(timestamp)
        if ts < 1e12:
            ts *= 1000
        return datetime.fromtimestamp(ts / 1000, UTC)

    @staticmethod
    def _metrics_insert_rows(
        db_timestamp: datetime,
        topic: str,
        message: dict,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for metric_name, value_double, value_text in flatten_payload_to_metrics(message):
            rows.append(
                {
                    "time": db_timestamp,
                    "topic": topic,
                    "metric_name": metric_name,
                    "value_double": value_double,
                    "value_text": value_text,
                }
            )
        return rows

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
        metric_rows = self._metrics_insert_rows(db_timestamp, topic, message)

        async with self._database.begin() as connection:
            raw_result = await connection.execute(
                _RAW_INSERT,
                {
                    "time": db_timestamp,
                    "topic": topic,
                    "client_id": client_id,
                    "mqtt_msg": stored_payload,
                },
            )
            inserted = raw_result.mappings().all()
            if inserted and metric_rows:
                await connection.execute(_METRICS_INSERT, metric_rows)
            return inserted
