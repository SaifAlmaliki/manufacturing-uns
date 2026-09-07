from fastapi.testclient import TestClient
from uns_factory_agent.app import create_app
from uns_factory_agent.auth import AuthError, Identity
from uns_factory_agent.conversations import MemoryConversationStore


def test_scope_without_bearer_is_401():
    def get_identity(_h):
        raise AuthError("The request has no Authorization bearer token.")

    client = TestClient(create_app(MemoryConversationStore(), get_identity=get_identity))
    assert client.get("/scope").status_code == 401


def test_scope_returns_roots():
    def get_identity(_h):
        return Identity("alice", "alice", frozenset({"operator"}))

    async def loader(identity):
        assert identity.subject == "alice"
        return {"roots": ["Acme/Site1"], "unrestricted": False}

    client = TestClient(
        create_app(MemoryConversationStore(), get_identity=get_identity, scope_loader=loader)
    )
    body = client.get("/scope", headers={"Authorization": "Bearer x"}).json()
    assert body == {"roots": ["Acme/Site1"], "unrestricted": False}
