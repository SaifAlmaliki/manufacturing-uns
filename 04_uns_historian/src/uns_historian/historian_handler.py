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

Encapsulate logic of persisting messages to the historian database
"""

import json
import logging
from datetime import UTC, datetime

import asyncpg
from asyncpg import Pool
from asyncpg.connection import Connection

from uns_historian.historian_config import HistorianConfig
from uns_historian.metric_flattener import flatten_payload_to_metrics

LOGGER = logging.getLogger(__name__)


class HistorianHandler:
    """
    Class to encapsulate logic of persisting messages to the historian database
    """

    # Class variable to hold the shared pool
    _shared_pool: Pool = None

    @classmethod
    async def get_shared_pool(cls) -> Pool:
        """
        Retrieves the shared connection pool.
        Creates a new pool if it doesn't exist.

        Returns:
            Pool: The shared connection pool.
        """
        try:
            LOGGER.debug("DB Shared connection pool requested")
            if cls._shared_pool is None:
                cls._shared_pool = await cls.create_pool()
            return cls._shared_pool
        except Exception as ex:
            LOGGER.error(f"Error while getting shared pool: {ex}")
            raise

    @classmethod
    async def create_pool(cls) -> Pool:
        """
        Creates a connection pool.
        Returns:
            Pool: The created connection pool.
        Raises:
            asyncpg.PostgresError: If there's an error creating the pool.
        """
        try:
            pool: Pool = await asyncpg.create_pool(
                host=HistorianConfig.hostname,
                user=HistorianConfig.user,
                password=HistorianConfig.password,
                database=HistorianConfig.database,
                port=HistorianConfig.port,
                ssl=HistorianConfig.get_ssl_context(),
            )
            LOGGER.info("Connection pool created successfully")
            return pool
        except asyncpg.PostgresError as e:
            LOGGER.error(f"Error creating connection pool: {e}")
            raise

    @classmethod
    async def close_pool(cls):
        """
        Close the connection pool
        """
        if cls._shared_pool is not None and not cls._shared_pool.is_closing():
            await cls._shared_pool.close()
            cls._shared_pool = None
            LOGGER.info("Connection pool closed successfully")
        else:
            LOGGER.warning("Connection pool was already closed ")

    async def __aenter__(self):
        # Acquire the shared pool directly
        self._pool: Pool = await self.get_shared_pool()
        # Acquire a connection from the pool
        self._conn: Connection = await self._pool.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._pool.release(self._conn)  # Release the acquired connection

    async def __aiter__(self):
        """
        Allow usage in asynchronous for loops.
        """
        self._conn: Connection = await self.get_shared_pool().acquire()
        return self

    async def __anext__(self) -> Connection:
        """
        Use with asynchronous for loops.
        """
        return self._conn

    async def execute_prepared(self, query: str, *args) -> list:
        """
        Executes a prepared query to fetch historical events.
        Returns a list of Records

        Args:
            query (str): The SQL query to execute.
            *args: Query parameters.

        Returns:
            list[HistoricalUNSEvent]: list of historical events.

        Raises:
            asyncpg.PostgresError: If there's an error executing the prepared statement.
        """
        try:
            if self._conn is None or self._conn.is_closed():
                self._conn = await self._pool.acquire()
            return await self._conn.fetch(query, *args)

        except asyncpg.PostgresError as ex:
            LOGGER.error(f"Error executing prepared statement: {ex}")
            raise

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
    ) -> list[tuple[datetime, str, str, float | None, str | None]]:
        rows: list[tuple[datetime, str, str, float | None, str | None]] = []
        for metric_name, value_double, value_text in flatten_payload_to_metrics(message):
            rows.append((db_timestamp, topic, metric_name, value_double, value_text))
        return rows

    async def persist_mqtt_msg(self, client_id: str, topic: str, timestamp: float | None, message: dict):
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
        metric_rows = self._metrics_insert_rows(db_timestamp, topic, message)

        # sometimes when qos is not 2, the mqtt message may be delivered multiple times. in such case avoid duplicate inserts
        raw_sql = (
            f"INSERT INTO {HistorianConfig.table} ( time, topic, client_id, mqtt_msg ) \n"  # noqa:S608:
            + "VALUES ($1,$2,$3,$4) \n"
            + "ON CONFLICT DO NOTHING \n"
            + "RETURNING *;"
        )
        metrics_sql = (
            f"INSERT INTO {HistorianConfig.metrics_table} "  # noqa:S608:
            + "( time, topic, metric_name, value_double, value_text ) \n"
            + "VALUES ($1,$2,$3,$4,$5);"
        )

        try:
            async with self._conn.transaction():
                raw_result = await self._conn.fetch(
                    raw_sql,
                    db_timestamp,
                    topic,
                    client_id,
                    json.dumps(message),
                )
                if raw_result and metric_rows:
                    await self._conn.executemany(metrics_sql, metric_rows)
                return raw_result
        except asyncpg.PostgresError as ex:
            LOGGER.error(f"Error persisting message in transaction: {ex}")
            raise
