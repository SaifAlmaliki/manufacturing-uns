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

Rewrite stored historian topics when a hierarchy prefix is renamed.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from uns_graphql.backend.historian import HistorianRepository
from uns_graphql.graphql_config import HistorianConfig
from uns_model.engine import Database

CLIENT_ID = "pytest-historian-rewrite"
REWRITE_AT = datetime.fromtimestamp(1999999999, UTC)

INSERT_SQL = f"""INSERT INTO {HistorianConfig.table} ( time, topic, client_id, mqtt_msg )
                 VALUES (:time, :topic, :client_id, CAST(:mqtt_msg AS jsonb));"""  # noqa: S608
SELECT_SQL = f"""SELECT topic FROM {HistorianConfig.table}
                 WHERE client_id = :client_id ORDER BY topic;"""  # noqa: S608
DELETE_SQL = f"""DELETE FROM {HistorianConfig.table} WHERE client_id = :client_id;"""  # noqa: S608
METRICS_INSERT_SQL = """INSERT INTO uns_metrics (time, topic, metric_name, value_double, value_text)
                        VALUES (:time, :topic, :metric_name, :value_double, :value_text);"""
METRICS_SELECT_SQL = """SELECT topic FROM uns_metrics WHERE topic = ANY(:topics) ORDER BY topic;"""
METRICS_DELETE_SQL = """DELETE FROM uns_metrics WHERE topic = ANY(:topics);"""
TEST_TOPICS = ["E/S1/a", "E/S2/b", "E/Nord/a", "E/S_1/a", "E/SX1/a"]


class _FakeResult:
    def __init__(self, rowcount: int = 0, scalar_value=None) -> None:
        self.rowcount = rowcount
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "to_regclass" in sql:
            return _FakeResult(scalar_value=None)
        return _FakeResult(rowcount=1)


class _FakeDatabase:
    """Stands in for `uns_model.engine.Database`; only `begin()` is used here."""

    def __init__(self) -> None:
        self.connection = _FakeConnection()

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_rewrite_rejects_identical_prefixes():
    historian = HistorianRepository(_FakeDatabase())
    with pytest.raises(ValueError):
        await historian.rewrite_topic_prefix("E/S1", "E/S1")


@pytest.mark.asyncio
async def test_rewrite_matches_prefix_with_starts_with_not_like():
    database = _FakeDatabase()
    changed = await HistorianRepository(database).rewrite_topic_prefix("E/S_1", "E/Nord")
    assert changed == 1
    sql, params = database.connection.calls[0]
    assert "starts_with" in sql
    assert " LIKE " not in sql
    assert params == {"old_prefix": "E/S_1", "new_prefix": "E/Nord"}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def historian_database():
    yield Database.shared("graphql")
    await Database.close_shared()


@pytest.fixture
def historian(historian_database: Database) -> HistorianRepository:
    return HistorianRepository(historian_database)


async def _insert_raw(database: Database, topics: list[str]) -> None:
    rows = [
        {"time": REWRITE_AT, "topic": topic, "client_id": CLIENT_ID, "mqtt_msg": "{}"}
        for topic in topics
    ]
    async with database.begin() as connection:
        await connection.execute(text(DELETE_SQL), {"client_id": CLIENT_ID})
        for row in rows:
            await connection.execute(text(INSERT_SQL), row)


async def _topics(database: Database) -> list[str]:
    async with database.begin() as connection:
        rows = (await connection.execute(text(SELECT_SQL), {"client_id": CLIENT_ID})).all()
    return [row.topic for row in rows]


async def _cleanup(database: Database) -> None:
    async with database.begin() as connection:
        await connection.execute(text(DELETE_SQL), {"client_id": CLIENT_ID})
        present = (await connection.execute(text("SELECT to_regclass('public.uns_metrics')"))).scalar()
        if present is not None:
            await connection.execute(text(METRICS_DELETE_SQL), {"topics": TEST_TOPICS})


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integrationtest
@pytest.mark.xdist_group(name="graphql_historian")
async def test_rewrite_topic_prefix_renames_matching_rows(
    historian_database: Database,
    historian: HistorianRepository,
):
    await _insert_raw(historian_database, ["E/S1/a", "E/S2/b"])
    try:
        changed = await historian.rewrite_topic_prefix("E/S1", "E/Nord")
        assert changed == 1
        assert await _topics(historian_database) == ["E/Nord/a", "E/S2/b"]
    finally:
        await _cleanup(historian_database)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integrationtest
@pytest.mark.xdist_group(name="graphql_historian")
async def test_rewrite_topic_prefix_does_not_treat_underscore_as_wildcard(
    historian_database: Database,
    historian: HistorianRepository,
):
    await _insert_raw(historian_database, ["E/S_1/a", "E/SX1/a"])
    try:
        changed = await historian.rewrite_topic_prefix("E/S_1", "E/Nord")
        assert changed == 1
        assert await _topics(historian_database) == ["E/Nord/a", "E/SX1/a"]
    finally:
        await _cleanup(historian_database)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integrationtest
@pytest.mark.xdist_group(name="graphql_historian")
async def test_rewrite_topic_prefix_updates_uns_metrics_when_present(
    historian_database: Database,
    historian: HistorianRepository,
):
    async with historian_database.begin() as connection:
        present = (await connection.execute(text("SELECT to_regclass('public.uns_metrics')"))).scalar()
    if present is None:
        pytest.skip("uns_metrics is missing")

    await _insert_raw(historian_database, ["E/S1/a", "E/S2/b"])
    async with historian_database.begin() as connection:
        await connection.execute(text(METRICS_DELETE_SQL), {"topics": TEST_TOPICS})
        for topic in ("E/S1/a", "E/S2/b"):
            await connection.execute(
                text(METRICS_INSERT_SQL),
                {
                    "time": REWRITE_AT,
                    "topic": topic,
                    "metric_name": "temp",
                    "value_double": 1.0,
                    "value_text": None,
                },
            )
    try:
        await historian.rewrite_topic_prefix("E/S1", "E/Nord")
        async with historian_database.begin() as connection:
            rows = (
                await connection.execute(
                    text(METRICS_SELECT_SQL),
                    {"topics": ["E/Nord/a", "E/S1/a", "E/S2/b"]},
                )
            ).all()
        assert [row.topic for row in rows] == ["E/Nord/a", "E/S2/b"]
    finally:
        await _cleanup(historian_database)
