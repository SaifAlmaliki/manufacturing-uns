"""Alembic runs migration SQL through asyncpg, which rejects two commands in one execute.

GitHub Actions and `uns_model_setup` both use the async engine. A CREATE VIEW glued
to its COMMENT, or a function glued to its trigger, fails with:
`cannot insert multiple commands into a prepared statement`.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"

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
