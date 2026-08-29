import asyncio

import pytest

from uns_simulator.simulator import (
    UnifiedNamespaceSimulator,
    resolve_simulation_duration,
)


def test_resolve_duration_keeps_zero():
    assert resolve_simulation_duration(0, {"duration": 5}) == 0


def test_resolve_duration_keeps_string_zero():
    assert resolve_simulation_duration("0", {"duration": 5}) == 0


def test_resolve_duration_uses_explicit_value():
    assert resolve_simulation_duration(12, {"duration": 5}) == 12  # noqa: PLR2004


def test_resolve_duration_falls_back_to_config():
    assert resolve_simulation_duration(None, {"duration": 5}) == 5  # noqa: PLR2004


def test_resolve_duration_falls_back_to_duration_minutes():
    assert resolve_simulation_duration(None, {"duration_minutes": 3}) == 3  # noqa: PLR2004


@pytest.mark.asyncio
async def test_run_until_zero_blocks_until_cancelled():
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    task = asyncio.create_task(sim._run_until(0))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_until_positive_sleeps_minutes(monkeypatch):
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await sim._run_until(5)
    assert sleeps == [300]
