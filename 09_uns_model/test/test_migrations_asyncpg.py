"""Alembic runs migration SQL through asyncpg, which rejects two commands in one execute.

GitHub Actions and `uns_model_setup` both use the async engine. A CREATE VIEW glued
to its COMMENT, or a function glued to its trigger, fails with:
`cannot insert multiple commands into a prepared statement`.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

MODEL_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS = MODEL_DIR / "migrations" / "versions"
ENV_PY = MODEL_DIR / "migrations" / "env.py"

# Semicolons inside $tag$ ... $tag$ bodies (plpgsql) are not command separators.
_DOLLAR_BODY = re.compile(r"\$[^$]*\$[\s\S]*?\$[^$]*\$")


def _load_revision(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _top_level_commands(sql: str) -> list[str]:
    stripped = _DOLLAR_BODY.sub("$$BODY$$", sql)
    return [part.strip() for part in stripped.split(";") if part.strip()]


def _sql_constants(module) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if isinstance(value, str) and re.search(r"\b(CREATE|COMMENT|DROP|GRANT|DO)\b", value, re.I):
            found.append((name, value))
        elif isinstance(value, (tuple, list)) and value and all(isinstance(item, str) for item in value):
            for index, item in enumerate(value):
                if re.search(r"\b(CREATE|COMMENT|DROP|GRANT|DO)\b", item, re.I):
                    found.append((f"{name}[{index}]", item))
    return found


@pytest.mark.parametrize("path", sorted(MIGRATIONS.glob("*.py")))
def test_each_migration_sql_constant_is_one_asyncpg_command(path: Path):
    module = _load_revision(path)
    bundled = [
        f"{name} has {len(commands)} commands"
        for name, sql in _sql_constants(module)
        if len(commands := _top_level_commands(sql)) > 1
    ]
    assert bundled == [], (
        f"{path.name} bundles multiple SQL commands in one string; "
        f"asyncpg will reject them: {bundled}"
    )


def _do_run_migrations_source() -> ast.FunctionDef:
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "do_run_migrations":
            return node
    raise AssertionError("migrations/env.py has no do_run_migrations()")


def test_online_env_creates_model_schema_inside_alembics_transaction():
    """CreateSchema before context.configure() autobegins a SQLAlchemy 2.0 transaction.

    Alembic then sets _in_external_transaction and begin_transaction() is a no-op,
    so upgrade head logs success while the connect() context rolls the DDL back.
    GitHub Actions then seeds into a database that has no model.asset_level.
    """
    func = _do_run_migrations_source()
    source_order: list[str] = []
    inside_begin_transaction = False

    def visit(node: ast.AST, *, in_begin: bool) -> None:
        nonlocal inside_begin_transaction
        if isinstance(node, ast.With):
            in_begin = in_begin or any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "begin_transaction"
                for item in node.items
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "configure"
        ):
            source_order.append("configure")
        if (isinstance(node, ast.Name) and node.id == "CreateSchema") or (
            isinstance(node, ast.Attribute) and node.attr == "CreateSchema"
        ):
            source_order.append("CreateSchema")
            inside_begin_transaction = in_begin
        for child in ast.iter_child_nodes(node):
            visit(child, in_begin=in_begin)

    visit(func, in_begin=False)

    assert source_order == ["configure", "CreateSchema"], (
        "CreateSchema must run after context.configure() so Alembic owns the "
        "transaction and commits it. Executing it first makes SQLAlchemy autobegin, "
        "Alembic skip the commit, and seed fail with 'relation model.asset_level "
        f"does not exist'. Saw {source_order}."
    )
    assert inside_begin_transaction, (
        "CreateSchema must run inside context.begin_transaction(), not before it"
    )

