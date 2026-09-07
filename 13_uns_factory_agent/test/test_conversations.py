import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from uns_factory_agent.conversations import MemoryConversationStore

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
ALICE = "alice-subject"
BOB = "bob-subject"


@pytest.mark.asyncio
async def test_list_is_only_mine():
    store = MemoryConversationStore()
    mine = await store.create(ALICE, now=NOW)
    await store.create(BOB, now=NOW)
    assert [c.id for c in await store.list_for(ALICE, now=NOW)] == [mine.id]


@pytest.mark.asyncio
async def test_get_foreign_is_none():
    store = MemoryConversationStore()
    theirs = await store.create(BOB, now=NOW)
    assert await store.get(theirs.id, ALICE, now=NOW) is None


@pytest.mark.asyncio
async def test_expired_is_hidden():
    store = MemoryConversationStore()
    old = await store.create(ALICE, now=NOW - timedelta(days=31))
    assert await store.list_for(ALICE, now=NOW) == []
    assert await store.get(old.id, ALICE, now=NOW) is None


@pytest.mark.asyncio
async def test_first_user_line_becomes_title():
    store = MemoryConversationStore()
    conv = await store.create(ALICE, now=NOW)
    await store.append(conv.id, ALICE, "user", "What is in alarm on Dryer?", (), now=NOW)
    assert (await store.get(conv.id, ALICE, now=NOW)).title == "What is in alarm on Dryer?"


@pytest.mark.asyncio
async def test_delete_foreign_is_false():
    store = MemoryConversationStore()
    theirs = await store.create(BOB, now=NOW)
    assert await store.delete(theirs.id, ALICE) is False
    assert await store.get(theirs.id, BOB, now=NOW) is not None


@pytest.mark.asyncio
async def test_purge_expired_removes_old_threads():
    store = MemoryConversationStore()
    await store.create(ALICE, now=NOW - timedelta(days=31))
    keep = await store.create(ALICE, now=NOW)
    assert await store.purge_expired(now=NOW) == 1
    assert [c.id for c in await store.list_for(ALICE, now=NOW)] == [keep.id]
