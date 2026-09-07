import pytest
from fastapi.testclient import TestClient

from uns_factory_agent.app import create_app
from uns_factory_agent.auth import AuthError, Identity, bearer_from_header, identity_from_token
from uns_factory_agent.conversations import MemoryConversationStore
from uns_factory_agent.jwks import JwksCache
from keys import jwks_document, make_key

REALM_KEY = make_key("copilot-test-key")


def _cache(*keys) -> JwksCache:
    document = jwks_document(*keys)

    async def fetch(_url: str) -> dict:
        return document

    return JwksCache("http://keys.test/certs", fetch=fetch)


def test_missing_bearer_is_401():
    def get_identity(header):
        raise AuthError("The request has no Authorization bearer token.")

    client = TestClient(create_app(MemoryConversationStore(), get_identity=get_identity))
    assert client.get("/conversations").status_code == 401


@pytest.mark.asyncio
async def test_valid_bearer_resolves_identity():
    token = REALM_KEY.mint(roles=["operator"], username="operator.user")
    identity = await identity_from_token(token, _cache(REALM_KEY))
    assert identity.username == "operator.user"
    assert identity.roles == frozenset({"operator"})


def test_bearer_header_is_extracted():
    token = REALM_KEY.mint()
    assert bearer_from_header(f"Bearer {token}") == token
