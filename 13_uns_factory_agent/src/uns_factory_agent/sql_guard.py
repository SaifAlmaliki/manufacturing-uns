from __future__ import annotations

import re

ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "model.asset",
        "model.metric_definition",
        "model.access_group",
        "model.access_group_member",
        "model.access_group_root",
        "unifiednamespace",
        "public.unifiednamespace",
        "uns_metrics",
        "public.uns_metrics",
        "oee.downtime_event",
    }
)


class SQLGuardError(ValueError):
    """The statement is not a single allowlisted SELECT."""


def guard_select(sql: str) -> str:
    text = sql.strip()
    if not text:
        raise SQLGuardError("SQL is empty.")
    if ";" in text.rstrip(";"):
        raise SQLGuardError("Only one statement is allowed.")
    text = text.rstrip(";").strip()
    head = text.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise SQLGuardError("Only a SELECT (or WITH … SELECT) is allowed.")
    if re.search(r"\b(insert|update|delete|drop|alter|create|grant|truncate)\b", head):
        raise SQLGuardError("Only a SELECT (or WITH … SELECT) is allowed.")
    tables = _tables(text)
    if not tables:
        raise SQLGuardError("SELECT must name an allowlisted table.")
    unknown = tables - ALLOWED_TABLES
    if unknown:
        raise SQLGuardError(f"Table not on the allowlist: {', '.join(sorted(unknown))}")
    return text


def _tables(sql: str) -> set[str]:
    found: set[str] = set()
    tokens = re.findall(
        r"(?i)\b(?:from|join)\s+((?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*)",
        sql,
    )
    for raw in tokens:
        lower = raw.lower()
        found.add(lower)
        if "." not in lower and lower in {"unifiednamespace", "uns_metrics"}:
            found.add(f"public.{lower}")
    return found
