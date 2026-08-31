"""
Unit tests for the ingest-side binder. No database: the binder is handed a fake
repository, which is the whole reason it accepts one.
"""

from __future__ import annotations

import asyncio

import pytest

from uns_model.topic_binder import TopicBinder

TOPIC = "CovestroAG/Dormagen/Production/Line1/Cell1/G1/ProcessValue/Temperature"


class FakeRepository:
    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[str] = []
        self._fail_times = fail_times

    async def bind_topic(self, topic: str) -> None:
        self.calls.append(topic)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("database is down")


@pytest.mark.asyncio
async def test_a_hot_topic_is_bound_once_no_matter_the_message_rate():
    repository = FakeRepository()
    binder = TopicBinder(repository)

    for _ in range(1000):
        await binder.observe(TOPIC)

    assert repository.calls == [TOPIC]


@pytest.mark.asyncio
async def test_concurrent_first_messages_on_a_topic_bind_once():
    repository = FakeRepository()
    binder = TopicBinder(repository)

    await asyncio.gather(*(binder.observe(TOPIC) for _ in range(10)))

    assert repository.calls == [TOPIC]


@pytest.mark.asyncio
async def test_a_database_failure_does_not_reach_the_ingest_loop():
    binder = TopicBinder(FakeRepository(fail_times=1))

    await binder.observe(TOPIC)  # must not raise

    assert binder.bound_count == 0


@pytest.mark.asyncio
async def test_a_failed_bind_is_retried_on_the_next_message():
    repository = FakeRepository(fail_times=1)
    binder = TopicBinder(repository)

    await binder.observe(TOPIC)
    await binder.observe(TOPIC)

    assert repository.calls == [TOPIC, TOPIC]
    assert binder.bound_count == 1


@pytest.mark.asyncio
async def test_what_is_remembered_is_bounded_by_capacity_not_by_topic_churn():
    repository = FakeRepository()
    binder = TopicBinder(repository, capacity=10)

    for index in range(100):
        await binder.observe(f"{TOPIC}/{index}")

    assert binder.bound_count == 10
    assert len(repository.calls) == 100


@pytest.mark.asyncio
async def test_forgetting_forces_a_rebind_after_the_asset_model_changed():
    repository = FakeRepository()
    binder = TopicBinder(repository)

    await binder.observe(TOPIC)
    binder.forget()
    await binder.observe(TOPIC)

    assert repository.calls == [TOPIC, TOPIC]


def test_a_useless_capacity_is_rejected_at_construction():
    with pytest.raises(ValueError, match="capacity"):
        TopicBinder(FakeRepository(), capacity=0)
