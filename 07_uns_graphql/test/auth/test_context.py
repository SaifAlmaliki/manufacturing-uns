"""The context dependency, tested without a server.

The dependency takes a starlette HTTPConnection, which is the common base of Request and
WebSocket - the same annotation Strawberry's own context dependency uses
(fastapi/dependencies/utils.py:359 is what makes FastAPI inject it for both route types).
A stub with a scope and headers is therefore enough, and is faster than a TestClient.
"""

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from uns_graphql.auth.context import (
    graphql_context,
    identity_in,
    use_signing_keys,
)
from uns_graphql.auth.jwks import JwksCache
from uns_graphql.auth.token import Identity

from .keys import jwks_document, make_key

REALM_KEY = make_key("gate-key")


class FakeConnection:
    """Enough of starlette's HTTPConnection for the dependency to read."""

    def __init__(self, *, headers: dict | None = None, kind: str = "http", method: str = "POST"):
        self.scope = {"type": kind, "method": method}
        self.headers = Headers(headers or {})


@pytest.fixture(autouse=True)
def realm_keys():
    document = jwks_document(REALM_KEY)

    async def fetch(_url: str) -> dict:
        return document

    use_signing_keys(JwksCache("http://keys.test/certs", fetch=fetch))
    yield
    # Leave no cache behind: a later test getting this one's keys would pass for the wrong reason.
    use_signing_keys(None)


@pytest.mark.asyncio
async def test_a_valid_token_becomes_an_identity_in_the_context():
    token = REALM_KEY.mint(roles=["operator"], username="olga.operator")

    context = await graphql_context(FakeConnection(headers={"authorization": f"Bearer {token}"}))

    identity = identity_in(context)
    assert isinstance(identity, Identity)
    assert identity.username == "olga.operator"


@pytest.mark.asyncio
async def test_no_authorization_header_is_a_401():
    with pytest.raises(HTTPException) as raised:
        await graphql_context(FakeConnection())

    assert raised.value.status_code == 401
    # Without this header a browser's fetch cannot tell an expired session from a server
    # fault, and the console's refresh-once path (Task 9) has nothing to key on.
    assert raised.value.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_a_bad_token_is_a_401_that_says_why():
    other_realm = make_key("gate-key")  # same kid, different key
    token = other_realm.mint(roles=["admin"])

    with pytest.raises(HTTPException) as raised:
        await graphql_context(FakeConnection(headers={"authorization": f"Bearer {token}"}))

    assert raised.value.status_code == 401
    assert "signature" in str(raised.value.detail).lower()


@pytest.mark.asyncio
async def test_a_websocket_handshake_is_allowed_through_with_no_identity():
    # A browser cannot set headers on a WebSocket handshake, so the token arrives later in
    # connection_init. Rejecting here would make subscriptions impossible from a browser.
    context = await graphql_context(FakeConnection(kind="websocket"))

    assert identity_in(context) is None


@pytest.mark.asyncio
async def test_the_graphiql_page_loads_without_a_token():
    # The IDE is a static HTML page with a Headers tab. Letting the page load and requiring a
    # pasted token for the operations keeps the dev tool usable; 401ing the page reads as an
    # outage.
    context = await graphql_context(
        FakeConnection(kind="http", method="GET", headers={"accept": "text/html"})
    )

    assert identity_in(context) is None


@pytest.mark.asyncio
async def test_a_get_query_still_needs_a_token():
    # allow_queries_via_get is on by default, so GET is a real operation transport. Only the
    # html-seeking GET is the IDE.
    with pytest.raises(HTTPException):
        await graphql_context(
            FakeConnection(kind="http", method="GET", headers={"accept": "application/json"})
        )


def test_identity_in_tolerates_the_contexts_the_test_suite_uses():
    # UNSGraphql.schema.execute() with no context_value gives resolvers info.context of None,
    # and the existing suite calls it that way in a dozen files.
    assert identity_in(None) is None
    assert identity_in({}) is None
    assert identity_in({"identity": None}) is None
