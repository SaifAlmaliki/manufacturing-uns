"""Integration tests for the edge management Alembic migration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from uns_model.cli import _project_dir
from uns_model.engine import Database
from uns_model.model_config import EDGE_SCHEMA, ModelConfig

MODEL_DIR = Path(__file__).resolve().parents[1]
REVISION = "0010_edge_management"


def _run_alembic(*args: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=MODEL_DIR,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(
            "alembic failed:\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def database():
    config = ModelConfig.from_settings()
    assert config.is_valid()
    db = Database.from_config(config)
    yield db
    await db.dispose()


def test_project_dir_discovers_packaged_alembic_files():
    project_dir = _project_dir()
    assert (project_dir / "alembic.ini").is_file()
    assert (project_dir / "migrations" / "versions" / f"{REVISION}.py").is_file()


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_migration_creates_edge_tables_and_connectivity_edge_id(database: Database):
    _run_alembic("upgrade", REVISION)
    _run_alembic("upgrade", "head")

    async with database.begin() as connection:
        for table in (
            "devices",
            "user_grants",
            "enrollment_attempts",
            "certificates",
            "desired_configurations",
            "management_leases",
            "reports",
            "secret_versions",
            "jobs",
            "audit_events",
        ):
            regclass = (
                await connection.execute(text(f"SELECT to_regclass('{EDGE_SCHEMA}.{table}')"))
            ).scalar()
            assert regclass is not None, table

        edge_column = (
            await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'console' AND table_name = 'connectivity_servers' "
                    "AND column_name = 'edge_id'"
                )
            )
        ).scalar_one_or_none()
        assert edge_column == "edge_id"
