"""Plant RCA playbooks: map a classified `Kind` to a fixed sequence of the four read-only
tools, and narrate what each step found (or could not see) for the model's next turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from uns_factory_agent.classify import Kind
from uns_factory_agent.console_map import CONSOLE_MAP, PLATFORM_HEALTH_REPLY
from uns_factory_agent.context_pack import ContextPack, resolve_paths
from uns_factory_agent.scope_sql import Scope
from uns_factory_agent.tools_graphql import GraphqlPost, query_alarms, query_live
from uns_factory_agent.tools_sql import SqlExecutor, query_asset_model, query_historian

ADMIN_ROOTS_SQL = "SELECT path FROM model.asset WHERE level IN ('ENTERPRISE', 'SITE') ORDER BY path"

METRICS_ON_PATHS = """
SELECT a.path, md.key, md.display_name, md.unit
FROM model.metric_definition md
JOIN model.asset a ON a.id = md.asset_id
""".strip()

HISTORIAN_WINDOW = """
SELECT topic, time, value_double, value_bool, value_string
FROM uns_metrics
WHERE time > NOW() - INTERVAL '{hours} hours'
ORDER BY time DESC
""".strip()

PUBLISHERS_HOUR = """
SELECT topic, max(time) AS last_seen
FROM uns_metrics
WHERE time > NOW() - INTERVAL '1 hour'
GROUP BY topic
""".strip()

# `oee.downtime_event` has no `asset_path` column — the Asset path lives on `model.asset`,
# reached through `model.oee_unit`. Aliased as `topic` so `query_historian`'s Access Group
# wrap (which filters on a `topic` column) still applies.
DOWNTIME = """
SELECT a.path AS topic, d.started_at, d.ended_at, d.reason_code
FROM oee.downtime_event d
JOIN model.oee_unit u ON u.id = d.oee_unit_id
JOIN model.asset a ON a.id = u.asset_id
""".strip()

PLANT_MAP = """
SELECT path, name, level FROM model.asset
WHERE level IN ('ENTERPRISE', 'SITE', 'AREA')
ORDER BY path
""".strip()

_LAST_SHIFT_HOURS = 8
_THREE_WEEK_HOURS = 504  # 21 days


@dataclass(frozen=True, slots=True)
class PlaybookResult:
    kind: Kind
    tools_called: tuple[str, ...]
    observations: str


def _where(paths: tuple[str, ...]) -> str:
    return ", ".join(paths) if paths else "your Access Group"


def _record(rows: list[dict], *, store_label: str, paths: tuple[str, ...], chunks: list[str]) -> None:
    if not rows:
        chunks.append(f"I cannot see {store_label} for {_where(paths)} in that window.")
        return
    chunks.append(f"{store_label}: {json.dumps(rows, default=str)[:8000]}")


async def _sql_step(
    query_fn,
    sql: str,
    *,
    scope: Scope,
    execute: SqlExecutor,
    tool_name: str,
    store_label: str,
    paths: tuple[str, ...],
    called: list[str],
    chunks: list[str],
) -> list[dict]:
    rows = await query_fn(sql, scope=scope, execute=execute)
    called.append(tool_name)
    _record(rows, store_label=store_label, paths=paths, chunks=chunks)
    return rows


async def _live_step(
    paths: tuple[str, ...],
    *,
    token: str,
    graphql: GraphqlPost,
    called: list[str],
    chunks: list[str],
) -> list[dict]:
    topics = [f"{path}/#" for path in paths]
    rows = await query_live(topics, token=token, client=graphql)
    called.append("query_live")
    _record(rows, store_label="Live Nodes", paths=paths, chunks=chunks)
    return rows


def _under_a_path(topic: str, paths: tuple[str, ...]) -> bool:
    return any(topic == path or topic.startswith(path + "/") for path in paths)


async def _alarms_step(
    paths: tuple[str, ...],
    *,
    token: str,
    graphql: GraphqlPost,
    called: list[str],
    chunks: list[str],
) -> list[dict]:
    rows = await query_alarms(token=token, client=graphql)
    filtered = [row for row in rows if _under_a_path(str(row.get("topic", "")), paths)]
    called.append("query_alarms")
    _record(filtered, store_label="Alert Rules", paths=paths, chunks=chunks)
    return filtered


async def run_playbook(
    kind: Kind,
    pack: ContextPack,
    *,
    scope: Scope,
    sql_execute: SqlExecutor,
    graphql: GraphqlPost,
    token: str,
) -> PlaybookResult:
    if kind == "platform_map":
        return PlaybookResult(kind, (), CONSOLE_MAP)
    if kind == "platform_health":
        return PlaybookResult(kind, (), PLATFORM_HEALTH_REPLY)
    if kind == "other":
        return PlaybookResult(kind, (), "")

    paths = resolve_paths(pack)
    called: list[str] = []
    chunks: list[str] = []

    if kind == "alarms_on_focus":
        await _alarms_step(paths, token=token, graphql=graphql, called=called, chunks=chunks)

    elif kind == "metric_vs_window":
        await _sql_step(
            query_asset_model,
            METRICS_ON_PATHS,
            scope=scope,
            execute=sql_execute,
            tool_name="query_asset_model",
            store_label="Asset Model",
            paths=paths,
            called=called,
            chunks=chunks,
        )
        await _sql_step(
            query_historian,
            HISTORIAN_WINDOW.format(hours=_LAST_SHIFT_HOURS),
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            called=called,
            chunks=chunks,
        )
        await _live_step(paths, token=token, graphql=graphql, called=called, chunks=chunks)

    elif kind == "publishers_on_path":
        await _sql_step(
            query_historian,
            PUBLISHERS_HOUR,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            called=called,
            chunks=chunks,
        )
        await _live_step(paths, token=token, graphql=graphql, called=called, chunks=chunks)

    elif kind == "performance_rca":
        await _sql_step(
            query_asset_model,
            METRICS_ON_PATHS,
            scope=scope,
            execute=sql_execute,
            tool_name="query_asset_model",
            store_label="Asset Model",
            paths=paths,
            called=called,
            chunks=chunks,
        )
        await _sql_step(
            query_historian,
            HISTORIAN_WINDOW.format(hours=_THREE_WEEK_HOURS),
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            called=called,
            chunks=chunks,
        )
        await _sql_step(
            query_historian,
            DOWNTIME,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Downtime",
            paths=paths,
            called=called,
            chunks=chunks,
        )
        await _alarms_step(paths, token=token, graphql=graphql, called=called, chunks=chunks)
        await _live_step(paths, token=token, graphql=graphql, called=called, chunks=chunks)

    elif kind == "plant_overview":
        await _alarms_step(pack.default_plant, token=token, graphql=graphql, called=called, chunks=chunks)
        await _sql_step(
            query_historian,
            PUBLISHERS_HOUR,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            called=called,
            chunks=chunks,
        )
        await _sql_step(
            query_asset_model,
            PLANT_MAP,
            scope=scope,
            execute=sql_execute,
            tool_name="query_asset_model",
            store_label="Asset Model",
            paths=paths,
            called=called,
            chunks=chunks,
        )

    observations = "\n".join(chunks)
    return PlaybookResult(kind, tuple(called), observations)
