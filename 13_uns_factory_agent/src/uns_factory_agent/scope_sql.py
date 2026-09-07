from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scope:
    unrestricted: bool
    root_paths: frozenset[str]


@dataclass(frozen=True, slots=True)
class ScopedSql:
    sql: str
    params: dict[str, str]


def scope_for(*, is_admin: bool, root_paths: frozenset[str]) -> Scope:
    if is_admin:
        return Scope(unrestricted=True, root_paths=frozenset())
    return Scope(unrestricted=False, root_paths=root_paths)


def covers_sql(column: str, param: str) -> str:
    """Prefix coverage without LIKE — mirrors uns_model.access.covers."""
    return (
        f"({column} = :{param} OR "
        f"(length({column}) > length(:{param}) AND left({column}, length(:{param}) + 1) = :{param} || '/'))"
    )


def wrap_select(sql: str, scope: Scope, *, path_column: str) -> ScopedSql:
    if scope.unrestricted:
        return ScopedSql(sql=sql, params={})
    if not scope.root_paths:
        return ScopedSql(sql=f"SELECT * FROM ({sql}) AS _scoped WHERE false", params={})
    clauses: list[str] = []
    params: dict[str, str] = {}
    for i, root in enumerate(sorted(scope.root_paths)):
        key = f"p{i}"
        params[key] = root
        clauses.append(covers_sql(path_column, key))
    joined = " OR ".join(clauses)
    return ScopedSql(sql=f"SELECT * FROM ({sql}) AS _scoped WHERE {joined}", params=params)
