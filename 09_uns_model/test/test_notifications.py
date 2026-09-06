"""Unit tests for LISTEN/NOTIFY readiness. No database.

`start()` used to return as soon as the background task was spawned. CI then
NOTIFYed before LISTEN, Postgres dropped the notice, and the integration test
timed out waiting for a callback that would never come.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from uns_model.notifications import AssetModelChangeListener


class _FakeConnection:
    def __init__(self, release_listen: asyncio.Event, listening_started: asyncio.Event) -> None:
        self._release_listen = release_listen
        self._listening_started = listening_started

    async def add_listener(self, _channel: str, _callback: object) -> None:
        self._listening_started.set()
        await self._release_listen.wait()

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_start_does_not_return_until_listen_is_ready():
    listening_started = asyncio.Event()
    release_listen = asyncio.Event()

    async def fake_connect(**_kwargs: object) -> _FakeConnection:
        return _FakeConnection(release_listen, listening_started)

    with (
        patch("uns_model.notifications.asyncpg.connect", fake_connect),
        patch(
            "uns_model.notifications.ModelConfig.from_settings",
            return_value=SimpleNamespace(
                hostname="localhost",
                port=5432,
                user="user",
                password="password",
                database="db",
                connect_args=lambda: {},
            ),
        ),
    ):
        listener = AssetModelChangeListener(database=SimpleNamespace(), on_change=lambda: None)
        start_task = asyncio.create_task(listener.start())
        await asyncio.wait_for(listening_started.wait(), timeout=1.0)
        assert not start_task.done(), "start() returned before LISTEN finished"
        release_listen.set()
        await asyncio.wait_for(start_task, timeout=1.0)
        await listener.stop()
