import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from uns_factory_agent.app import create_app
from uns_factory_agent.auth import Identity
from uns_factory_agent.conversations import MemoryConversationStore

NOW = datetime(2026, 9, 6, tzinfo=UTC)


def _client(store: MemoryConversationStore, subject: str = "alice-subject"):
    def get_identity(_header):
        return Identity(subject=subject, username="alice", roles=frozenset({"operator"}))

    return TestClient(create_app(store, get_identity=get_identity))


def test_list_returns_only_caller_threads():
    store = MemoryConversationStore()
    asyncio.run(store.create("alice-subject", now=NOW))
    asyncio.run(store.create("bob-subject", now=NOW))
    client = _client(store)
    body = client.get("/conversations").json()
    assert len(body) == 1


def test_post_creates_conversation():
    store = MemoryConversationStore()
    client = _client(store)
    body = client.post("/conversations").json()
    assert body["title"] == "New chat"
    assert "id" in body


def test_get_foreign_is_404():
    store = MemoryConversationStore()
    theirs = asyncio.run(store.create("bob-subject", now=NOW))
    client = _client(store)
    assert client.get(f"/conversations/{theirs.id}").status_code == 404


def test_delete_mine_is_204():
    store = MemoryConversationStore()
    conv = asyncio.run(store.create("alice-subject", now=NOW))
    client = _client(store)
    assert client.delete(f"/conversations/{conv.id}").status_code == 204


def test_delete_foreign_is_404():
    store = MemoryConversationStore()
    theirs = asyncio.run(store.create("bob-subject", now=NOW))
    client = _client(store)
    assert client.delete(f"/conversations/{theirs.id}").status_code == 404
