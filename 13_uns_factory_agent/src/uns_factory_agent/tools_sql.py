from __future__ import annotations

from typing import Protocol

from uns_factory_agent.scope_sql import Scope, wrap_select
from uns_factory_agent.sql_guard import guard_select

ROW_CAP = 200


class SqlExecutor(Protocol):
    async def fetch(self, sql: str, params: dict) -> list[dict]: ...


async def query_asset_model(sql: str, *, scope: Scope, execute: SqlExecutor) -> list[dict]:
    guarded = guard_select(sql)
    scoped = wrap_select(guarded, scope, path_column="path")
    rows = await execute.fetch(scoped.sql, scoped.params)
    return rows[:ROW_CAP]


async def query_historian(sql: str, *, scope: Scope, execute: SqlExecutor) -> list[dict]:
    guarded = guard_select(sql)
    scoped = wrap_select(guarded, scope, path_column="topic")
    rows = await execute.fetch(scoped.sql, scoped.params)
    return rows[:ROW_CAP]
