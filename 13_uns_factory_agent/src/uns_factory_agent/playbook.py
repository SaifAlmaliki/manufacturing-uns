"""Plant RCA playbooks: map a classified `Kind` to a fixed sequence of the four read-only
tools, and narrate what each step found (or could not see) for the model's next turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from uns_factory_agent.classify import Kind
from uns_factory_agent.console_map import CONSOLE_MAP, PLATFORM_HEALTH_REPLY
from uns_factory_agent.context_pack import ContextPack, resolve_paths
from uns_factory_agent.scope_sql import Scope, covers_sql
from uns_factory_agent.tools_graphql import GraphqlPost, query_alarms, query_live
from uns_factory_agent.tools_sql import SqlExecutor, query_asset_model, query_historian

ADMIN_ROOTS_SQL = "SELECT path FROM model.asset WHERE level IN ('ENTERPRISE', 'SITE') ORDER BY path"

# Every template below carries a `{predicate}` placeholder filled in by `_sql_step` from
# the caller's focus paths (see `_path_predicate`), so a Copilot turn scoped to P101 only
# ever reads P101's rows — not "whatever the Access Group wrap happens to allow" — and a
# literal `LIMIT 200` so a run-away query cannot outrun `tools_sql.ROW_CAP` at the source.
#
# Real column names (see `09_uns_model/src/uns_model/tables.py` and
# `04_uns_historian/sql_scripts/04_setup_metrics_hypertable.sql`):
# - model.metric_definition: metric_key, display_name, unit_of_measure (never `key`/`unit`).
# - uns_metrics: time, topic, metric_name, value_double, value_text (no value_bool/value_string).
# - model.asset: path, segment, display_name, level (no `name`; use COALESCE(display_name, segment)).
METRICS_ON_PATHS = """
SELECT a.path, md.metric_key, md.display_name, md.unit_of_measure
FROM model.metric_definition md
JOIN model.asset a ON a.id = md.asset_id
WHERE {predicate}
LIMIT 200
""".strip()

HISTORIAN_WINDOW = """
SELECT topic, time, metric_name, value_double, value_text
FROM uns_metrics
WHERE time > NOW() - INTERVAL '{hours} hours'
AND {predicate}
ORDER BY time DESC
LIMIT 200
""".strip()

PUBLISHERS_HOUR = """
SELECT topic, max(time) AS last_seen
FROM uns_metrics
WHERE time > NOW() - INTERVAL '1 hour'
AND {predicate}
GROUP BY topic
LIMIT 200
""".strip()

# `oee.downtime_event` has no `asset_path` column — the Asset path lives on `model.asset`,
# reached through `model.oee_unit`. Aliased as `topic` so `query_historian`'s Access Group
# wrap (which filters on a `topic` column) still applies.
DOWNTIME = """
SELECT a.path AS topic, d.started_at, d.ended_at, d.reason_code
FROM oee.downtime_event d
JOIN model.oee_unit u ON u.id = d.oee_unit_id
JOIN model.asset a ON a.id = u.asset_id
WHERE {predicate}
LIMIT 200
""".strip()

PLANT_MAP = """
SELECT path, COALESCE(display_name, segment) AS name, level
FROM model.asset
WHERE level IN ('ENTERPRISE', 'SITE', 'AREA')
AND {predicate}
ORDER BY path
LIMIT 200
""".strip()

_LAST_SHIFT_HOURS = 8
_THREE_WEEK_HOURS = 504  # 21 days

#: Total characters across every "## Playbook observations" chunk for one turn, so one
#: chatty step (e.g. a wide historian window) cannot crowd out every other step's evidence
#: — or blow past the model's context budget outright.
OBSERVATION_BUDGET_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class PlaybookResult:
    kind: Kind
    tools_called: tuple[str, ...]
    observations: str


def _where(paths: tuple[str, ...]) -> str:
    return ", ".join(paths) if paths else "your Access Group"


def _path_predicate(column: str, paths: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    """A WHERE-clause fragment (and its bind params) scoping `column` to `paths`.

    Reuses `scope_sql.covers_sql` — the same prefix-covering predicate the Access Group
    wrap uses — so "under this path" means the same thing everywhere. Falls back to an
    unconditional `TRUE` when there is no focus (the Access Group wrap in `tools_sql`
    still applies on top of this).
    """
    if not paths:
        return "TRUE", {}
    clauses: list[str] = []
    params: dict[str, str] = {}
    for i, path in enumerate(paths):
        key = f"foc{i}"
        params[key] = path
        clauses.append(covers_sql(column, key))
    return "(" + " OR ".join(clauses) + ")", params


class _Budget:
    """A shared, mutable character budget spent across one playbook run's observations."""

    __slots__ = ("remaining",)

    def __init__(self, total: int) -> None:
        self.remaining = total


def _record(
    rows: list[dict],
    *,
    store_label: str,
    paths: tuple[str, ...],
    chunks: list[str],
    budget: _Budget,
) -> None:
    if not rows:
        note = f"I cannot see {store_label} for {_where(paths)} in that window."
        if budget.remaining >= len(note):
            chunks.append(note)
            budget.remaining -= len(note)
        return
    # Drop whole rows from the end until the chunk fits the remaining budget, so a
    # truncation always lands on a row boundary and every emitted chunk stays valid JSON
    # after the "{label}: " prefix — never a JSON string sliced off mid-object.
    kept = list(rows)
    while kept:
        omitted = len(rows) - len(kept)
        suffix = f" (+{omitted} more rows omitted for space)" if omitted else ""
        text = f"{store_label}: {json.dumps(kept, default=str)}{suffix}"
        if len(text) <= budget.remaining:
            chunks.append(text)
            budget.remaining -= len(text)
            return
        kept.pop()
    # Not even one row fits what's left of the budget: skip this store's observation
    # entirely rather than emit a half-written fragment.


async def _sql_step(
    query_fn,
    sql_template: str,
    *,
    scope: Scope,
    execute: SqlExecutor,
    tool_name: str,
    store_label: str,
    paths: tuple[str, ...],
    path_column: str,
    called: list[str],
    chunks: list[str],
    budget: _Budget,
    extra_format: dict | None = None,
) -> list[dict]:
    predicate, params = _path_predicate(path_column, paths)
    sql = sql_template.format(predicate=predicate, **(extra_format or {}))
    called.append(tool_name)
    try:
        rows = await query_fn(sql, scope=scope, execute=execute, params=params)
    except Exception:  # noqa: BLE001 — a broken query narrates "cannot see", it never 500s.
        _record([], store_label=store_label, paths=paths, chunks=chunks, budget=budget)
        return []
    _record(rows, store_label=store_label, paths=paths, chunks=chunks, budget=budget)
    return rows


async def _live_step(
    paths: tuple[str, ...],
    *,
    token: str,
    graphql: GraphqlPost,
    called: list[str],
    chunks: list[str],
    budget: _Budget,
) -> list[dict]:
    topics = [f"{path}/#" for path in paths]
    called.append("query_live")
    try:
        rows = await query_live(topics, token=token, client=graphql)
    except Exception:  # noqa: BLE001 — see `_sql_step`.
        _record([], store_label="Live Nodes", paths=paths, chunks=chunks, budget=budget)
        return []
    _record(rows, store_label="Live Nodes", paths=paths, chunks=chunks, budget=budget)
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
    budget: _Budget,
) -> list[dict]:
    called.append("query_alarms")
    try:
        rows = await query_alarms(token=token, client=graphql)
    except Exception:  # noqa: BLE001 — see `_sql_step`.
        _record([], store_label="Alert Rules", paths=paths, chunks=chunks, budget=budget)
        return []
    filtered = [row for row in rows if _under_a_path(str(row.get("topic", "")), paths)]
    _record(filtered, store_label="Alert Rules", paths=paths, chunks=chunks, budget=budget)
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
    budget = _Budget(OBSERVATION_BUDGET_CHARS)

    if kind == "alarms_on_focus":
        await _alarms_step(paths, token=token, graphql=graphql, called=called, chunks=chunks, budget=budget)

    elif kind == "metric_vs_window":
        await _sql_step(
            query_asset_model,
            METRICS_ON_PATHS,
            scope=scope,
            execute=sql_execute,
            tool_name="query_asset_model",
            store_label="Asset Model",
            paths=paths,
            path_column="a.path",
            called=called,
            chunks=chunks,
            budget=budget,
        )
        await _sql_step(
            query_historian,
            HISTORIAN_WINDOW,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            path_column="topic",
            called=called,
            chunks=chunks,
            budget=budget,
            extra_format={"hours": _LAST_SHIFT_HOURS},
        )
        await _live_step(paths, token=token, graphql=graphql, called=called, chunks=chunks, budget=budget)

    elif kind == "publishers_on_path":
        await _sql_step(
            query_historian,
            PUBLISHERS_HOUR,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            path_column="topic",
            called=called,
            chunks=chunks,
            budget=budget,
        )
        await _live_step(paths, token=token, graphql=graphql, called=called, chunks=chunks, budget=budget)

    elif kind == "performance_rca":
        await _sql_step(
            query_asset_model,
            METRICS_ON_PATHS,
            scope=scope,
            execute=sql_execute,
            tool_name="query_asset_model",
            store_label="Asset Model",
            paths=paths,
            path_column="a.path",
            called=called,
            chunks=chunks,
            budget=budget,
        )
        await _sql_step(
            query_historian,
            HISTORIAN_WINDOW,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            path_column="topic",
            called=called,
            chunks=chunks,
            budget=budget,
            extra_format={"hours": _THREE_WEEK_HOURS},
        )
        await _sql_step(
            query_historian,
            DOWNTIME,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Downtime",
            paths=paths,
            path_column="a.path",
            called=called,
            chunks=chunks,
            budget=budget,
        )
        await _alarms_step(paths, token=token, graphql=graphql, called=called, chunks=chunks, budget=budget)
        await _live_step(paths, token=token, graphql=graphql, called=called, chunks=chunks, budget=budget)

    elif kind == "plant_overview":
        # M10: use the resolved focus paths (falls back to default_plant when nothing is
        # selected) so a focused plant_overview does not silently widen back out.
        await _alarms_step(paths, token=token, graphql=graphql, called=called, chunks=chunks, budget=budget)
        await _sql_step(
            query_historian,
            PUBLISHERS_HOUR,
            scope=scope,
            execute=sql_execute,
            tool_name="query_historian",
            store_label="Historian",
            paths=paths,
            path_column="topic",
            called=called,
            chunks=chunks,
            budget=budget,
        )
        await _sql_step(
            query_asset_model,
            PLANT_MAP,
            scope=scope,
            execute=sql_execute,
            tool_name="query_asset_model",
            store_label="Asset Model",
            paths=paths,
            path_column="path",
            called=called,
            chunks=chunks,
            budget=budget,
        )

    observations = "\n".join(chunks)
    return PlaybookResult(kind, tuple(called), observations)
