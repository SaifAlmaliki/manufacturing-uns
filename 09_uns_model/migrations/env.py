"""Alembic environment for the authored Asset Model.

The URL comes from the platform conf/ directory rather than alembic.ini, so
there is exactly one place that knows the database credentials.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from uns_model.model_config import MODEL_SCHEMA, ModelConfig
from uns_model.tables import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_model_config = ModelConfig.from_settings()


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:  # noqa: ARG001
    """Autogenerate must ignore the historian's hypertables and Timescale internals."""
    if type_ == "schema":
        return name == MODEL_SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_model_config.url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=MODEL_SCHEMA,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        # Emitted before the version table, which Alembic itself puts in this schema.
        context.execute(sa.schema.CreateSchema(MODEL_SCHEMA, if_not_exists=True))
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # Alembic creates its version table before running any migration, so the
    # schema that holds it has to exist first.
    connection.execute(sa.schema.CreateSchema(MODEL_SCHEMA, if_not_exists=True))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=MODEL_SCHEMA,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _model_config.url},
        prefix="sqlalchemy.",
        poolclass=NullPool,
        connect_args=_model_config.connect_args(),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
