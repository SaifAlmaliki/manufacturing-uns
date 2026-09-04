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

Reads of the historian hypertable, and prefix rewrites when a hierarchy node is renamed.

The historian and the Asset Model share one Postgres/Timescale database, so they now
share one engine as well: `uns_model.engine.Database` (ADR-0004). This module used to
own an asyncpg pool of its own, which meant two pools, two sets of connection
settings, and two things to close on shutdown.

The SQL stays hand-written. The hypertable is not part of the authored model — the
historian writes it; this service reads it and rewrites topic prefixes on rename —
and the queries here do things the ORM has no vocabulary for: MQTT wildcards turned
into regex, `jsonb_path_exists` over an arbitrary payload, and prefix substitution.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import ARRAY, TIMESTAMP, Text, bindparam, text
from uns_mqtt.mqtt_listener import UnsMQTTClient

from uns_graphql.graphql_config import HistorianConfig
from uns_graphql.type.basetype import JSONPayload
from uns_graphql.type.historical_event import HistoricalUNSEvent

if TYPE_CHECKING:
    from sqlalchemy import TextClause
    from uns_model.engine import Database

LOGGER = logging.getLogger(__name__)

BINARY_OPERATORS = frozenset({"AND", "OR", "NOT"})


class HistorianRepository:
    """
    Historic UNS events from the historian hypertable.

    Two reads, one per method: "what was published on these topics, by these
    publishers, in this window", and "which events carry these keys anywhere in
    their payload". Plus a write that rewrites a topic prefix when a hierarchy
    node is renamed. Everything else — the wildcard translation, the parameter
    binding, the column-name-to-field mapping — is deliberately inside.

    Takes its `Database` rather than reaching for the shared one, so a test can hand
    in an engine pointed at anything.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_historic_events(
        self,
        topics: list[str] | None,
        publishers: list[str] | None,
        from_datetime: datetime | None,
        to_datetime: datetime | None,
    ) -> list[HistoricalUNSEvent]:
        """
        Historic events matching any combination of topics, publishers and a time window.

        Topics may contain MQTT wildcards. At least one criterion is required: an
        unfiltered read of a hypertable is not a query, it is an outage.

        Raises:
            ValueError: if no criteria were provided.
        """
        if topics is None and publishers is None and from_datetime is None and to_datetime is None:
            raise ValueError("At least one criteria for fetching historic events needs to be provided")

        conditions: list[str] = []
        params: dict[str, object] = {}
        types: list = []

        if topics:
            # MQTT wildcards have no meaning to Postgres; the regex does.
            conditions.append("( topic ~ ANY (:topics) )")
            params["topics"] = [UnsMQTTClient.get_regex_for_topic_with_wildcard(topic) for topic in topics]
            types.append(bindparam("topics", type_=ARRAY(Text)))

        if publishers:
            conditions.append("( client_id ~ ANY (:publishers) )")
            params["publishers"] = list(publishers)
            types.append(bindparam("publishers", type_=ARRAY(Text)))

        if from_datetime:
            conditions.append("( time >= :from_datetime )")
            params["from_datetime"] = from_datetime
            types.append(bindparam("from_datetime", type_=TIMESTAMP(timezone=True)))

        if to_datetime:
            conditions.append("( time <= :to_datetime )")
            params["to_datetime"] = to_datetime
            types.append(bindparam("to_datetime", type_=TIMESTAMP(timezone=True)))

        return await self._fetch(conditions, params, types)

    async def get_historic_events_for_property_keys(
        self,
        property_keys: list[str],
        binary_operator: Literal["AND", "OR", "NOT"] | None,
        topics: list[str] | None,
        from_datetime: datetime | None,
        to_datetime: datetime | None,
    ) -> list[HistoricalUNSEvent]:
        """
        Historic events whose payload contains the given keys at any depth.

        `binary_operator` chains the keys and defaults to OR. The other criteria are
        always ANDed onto the result.

        Raises:
            ValueError: if no property keys were given, or the operator is not one of
                AND / OR / NOT.
        """
        if not property_keys:
            raise ValueError("Mandatory criteria for fetching historic events by property_keys needs to be provided")
        if binary_operator is not None and binary_operator not in BINARY_OPERATORS:
            raise ValueError(f"Should be on of ['AND', 'OR', 'NOT']. Got: {binary_operator}")
        if binary_operator is None:
            binary_operator = "OR"

        conditions: list[str] = []
        params: dict[str, object] = {}
        types: list = []

        if topics:
            conditions.append("( topic ~ ANY (:topics) )")
            params["topics"] = [UnsMQTTClient.get_regex_for_topic_with_wildcard(topic) for topic in topics]
            types.append(bindparam("topics", type_=ARRAY(Text)))

        if from_datetime:
            conditions.append("( time >= :from_datetime )")
            params["from_datetime"] = from_datetime
            types.append(bindparam("from_datetime", type_=TIMESTAMP(timezone=True)))

        if to_datetime:
            conditions.append("( time <= :to_datetime )")
            params["to_datetime"] = to_datetime
            types.append(bindparam("to_datetime", type_=TIMESTAMP(timezone=True)))

        key_conditions: list[str] = []
        for index, property_key in enumerate(property_keys):
            name = f"property_{index}"
            # CAST because a plain text() bind is sent as text, and jsonb_path_exists
            # wants a jsonpath.
            key_conditions.append(f"( jsonb_path_exists( mqtt_msg, CAST(:{name} AS jsonpath) ) )")
            # Quoted so that a key containing a space is still one path step.
            params[name] = '$.**."' + property_key + '"'
            types.append(bindparam(name, type_=Text))

        if binary_operator == "NOT":
            conditions.append("NOT ( " + " OR ".join(key_conditions) + " )")
        else:
            conditions.append(" ( " + f" {binary_operator} ".join(key_conditions) + " ) ")

        return await self._fetch(conditions, params, types)

    async def rewrite_topic_prefix(self, old_prefix: str, new_prefix: str) -> int:
        """Rewrite stored topics under ``old_prefix`` to sit under ``new_prefix``.

        Updates ``HistorianConfig.table`` and ``uns_metrics`` (when that table
        exists). Returns rows changed on the raw table. Does not refresh CAGGs.

        Raises:
            ValueError: if ``old_prefix`` and ``new_prefix`` are the same.
        """
        if old_prefix == new_prefix:
            raise ValueError("old_prefix and new_prefix must differ")

        params = {"old_prefix": old_prefix, "new_prefix": new_prefix}
        # starts_with, not LIKE: `_` in a topic segment is a character, not a wildcard.
        assignment = ":new_prefix || substring(topic from (char_length(:old_prefix) + 1))"
        match = "topic = :old_prefix OR starts_with(topic, :old_prefix || '/')"
        raw_sql = text(
            f"UPDATE {HistorianConfig.table} SET topic = {assignment} WHERE {match}"  # noqa: S608
        )

        async with self._database.begin() as connection:
            result = await connection.execute(raw_sql, params)
            present = (await connection.execute(text("SELECT to_regclass('public.uns_metrics')"))).scalar()
            if present is not None:
                await connection.execute(
                    text(f"UPDATE uns_metrics SET topic = {assignment} WHERE {match}"),
                    params,
                )
            return result.rowcount or 0

    async def _fetch(
        self,
        conditions: list[str],
        params: dict[str, object],
        types: list,
    ) -> list[HistoricalUNSEvent]:
        """
        Run the assembled WHERE clause and map rows to the GraphQL type.

        No SQL injection risk: every value travels as a bound parameter, and the only
        interpolated strings are condition fragments written in this module.
        """
        where = " AND ".join(conditions)
        query = f"SELECT time, topic, client_id, mqtt_msg FROM {HistorianConfig.table} WHERE {where}"  # noqa: S608
        statement: TextClause = text(query).bindparams(*types)
        LOGGER.debug("Historian query: %s\nParams: %s", query, params)

        async with self._database.begin() as connection:
            rows = (await connection.execute(statement, params)).all()

        # The database column names are deliberately not exposed: `time` becomes
        # timestamp, `client_id` becomes publisher, `mqtt_msg` becomes payload.
        # `mqtt_msg` arrives as the raw JSON text; JSONPayload takes either that or a
        # dict, so there is no deserialise-then-reserialise in between.
        return [
            HistoricalUNSEvent(
                timestamp=row.time,
                topic=row.topic,
                publisher=row.client_id,
                payload=JSONPayload(row.mqtt_msg),
            )
            for row in rows
        ]
