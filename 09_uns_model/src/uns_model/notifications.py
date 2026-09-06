"""Cross-process notice that the authored Asset Model changed.

Writers NOTIFY after a change; long-lived readers LISTEN and drop their caches.
That keeps enrichment fresh without polling or restarts (ADR-0003).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import asyncpg
from sqlalchemy import text

from uns_model.engine import Database
from uns_model.model_config import ModelConfig

LOGGER = logging.getLogger(__name__)

ASSET_MODEL_CHANGED_CHANNEL = "asset_model_changed"


async def announce_asset_model_changed(database: Database) -> None:
    """Tell every listener that bindings or authored facts may have changed."""
    async with database.begin() as connection:
        await connection.execute(text(f"NOTIFY {ASSET_MODEL_CHANGED_CHANNEL}, ''"))


OnChange = Callable[[], Awaitable[None] | None]


class AssetModelChangeListener:
    """
    LISTEN on a dedicated Postgres connection and invoke a callback on NOTIFY.

    Reconnects on failure so a dropped listener does not stay stale forever.
    `start()` does not return until LISTEN has been issued. A NOTIFY sent in the
    gap after spawn and before LISTEN is dropped by Postgres.
    """

    def __init__(
        self,
        database: Database,
        on_change: OnChange,
        *,
        module_env: str = "default",
        channel: str = ASSET_MODEL_CHANGED_CHANNEL,
    ) -> None:
        self._database = database
        self._on_change = on_change
        self._module_env = module_env
        self._channel = channel
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._listening = asyncio.Event()

    async def start(self, *, ready_timeout: float = 30.0) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._listening.clear()
        self._task = asyncio.create_task(self._run(), name="asset-model-change-listener")
        try:
            await asyncio.wait_for(self._listening.wait(), timeout=ready_timeout)
        except TimeoutError:
            await self.stop()
            raise RuntimeError(
                f"Asset Model change listener did not LISTEN on {self._channel!r} within {ready_timeout}s"
            ) from None

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        config = ModelConfig.from_settings(self._module_env)
        while not self._stop.is_set():
            connection: asyncpg.Connection | None = None
            try:
                connection = await asyncpg.connect(
                    host=config.hostname,
                    port=config.port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    ssl=config.connect_args().get("ssl", False),
                )
                queue: asyncio.Queue[None] = asyncio.Queue()

                def _on_notify(*_args: object) -> None:
                    queue.put_nowait(None)

                await connection.add_listener(self._channel, _on_notify)
                self._listening.set()
                LOGGER.debug("Listening for NOTIFY %s", self._channel)
                while not self._stop.is_set():
                    try:
                        await asyncio.wait_for(queue.get(), timeout=1.0)
                    except TimeoutError:
                        continue
                    await self._dispatch_change()
            except asyncio.CancelledError:
                raise
            except Exception as ex:  # noqa: BLE001 - listener must survive and retry
                if not self._stop.is_set():
                    LOGGER.warning("Asset Model change listener failed, retrying in 5s: %s", ex)
                    await asyncio.sleep(5)
            finally:
                if connection is not None:
                    await connection.close()

    async def _dispatch_change(self) -> None:
        try:
            result = self._on_change()
            if asyncio.iscoroutine(result):
                await result
        except Exception as ex:  # noqa: BLE001 - a bad callback must not kill the listener
            LOGGER.warning("Asset Model change handler failed: %s", ex)


__all__ = ["ASSET_MODEL_CHANGED_CHANNEL", "AssetModelChangeListener", "announce_asset_model_changed"]
