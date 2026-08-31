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

The one place a connection to the Asset Model database is made.

Replaces the two hand-rolled asyncpg pool classes that `uns_historian` and
`uns_graphql` each carried (ADR-0004). Exposes both halves of SQLAlchemy
deliberately: `session()` for the authored tables, `begin()` for the ingest path,
which must not pay for a unit of work per MQTT message.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from uns_model.model_config import ModelConfig

LOGGER = logging.getLogger(__name__)

DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 5
DEFAULT_POOL_RECYCLE_SECONDS = 1800


class Database:
    """
    An engine and a session factory for the Asset Model database.

    Accepts its engine rather than always building one, so tests can hand in
    their own. `shared()` is the convenience for services that want the one
    configured connection and nothing else.
    """

    _shared: Database | None = None

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    @classmethod
    def from_config(cls, config: ModelConfig, *, echo: bool = False) -> Database:
        """Build a Database from platform configuration."""
        if not config.is_valid():
            raise ValueError("Asset Model database is not configured; see conf/settings.yaml and conf/.secrets.yaml")
        engine = create_async_engine(
            config.url,
            connect_args=config.connect_args(),
            pool_size=DEFAULT_POOL_SIZE,
            max_overflow=DEFAULT_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=DEFAULT_POOL_RECYCLE_SECONDS,
            echo=echo,
        )
        LOGGER.info("Asset Model engine created for %s:%s/%s", config.hostname, config.port, config.database)
        return cls(engine)

    @classmethod
    def shared(cls, module_env: str = "default") -> Database:
        """The process-wide Database, created on first use."""
        if cls._shared is None:
            cls._shared = cls.from_config(ModelConfig.from_settings(module_env))
        return cls._shared

    @classmethod
    async def close_shared(cls) -> None:
        """Dispose the process-wide Database. Safe to call when there isn't one."""
        if cls._shared is not None:
            await cls._shared.dispose()
            cls._shared = None

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        An ORM session that commits on success and rolls back on failure.

        For the authored tables. Do not use for per-message inserts.
        """
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncConnection]:
        """
        A Core connection inside a transaction, with no identity map or flush.

        For the ingest path and for raw Timescale SQL.
        """
        async with self._engine.begin() as connection:
            yield connection

    async def dispose(self) -> None:
        await self._engine.dispose()
        LOGGER.info("Asset Model engine disposed")
