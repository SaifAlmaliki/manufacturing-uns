"""The gate, at the one door this service has.

`uns_graphql_app.py` mounts exactly one GraphQLRouter at one path, so authentication is a
dependency and a WebSocket hook rather than a check each resolver has to remember. A resolver
reading a header would be a resolver that could forget to.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from starlette.requests import HTTPConnection
from strawberry.exceptions import ConnectionRejectionError
from strawberry.fastapi import GraphQLRouter

from uns_graphql.auth.jwks import JwksCache
from uns_graphql.auth.token import AuthError, Identity, bearer_from_header, identity_from_token
from uns_graphql.graphql_config import AuthConfig

LOGGER = logging.getLogger(__name__)

CONTEXT_KEY = "identity"

_UNAUTHENTICATED = {"WWW-Authenticate": "Bearer"}

_keys: JwksCache | None = None


def signing_keys() -> JwksCache:
    """The process-wide key cache, built on first use.

    One instance, so the document is fetched once for the whole service rather than once per
    request. Built lazily rather than at import so that importing this module does not depend
    on the realm being reachable.
    """
    global _keys
    if _keys is None:
        _keys = JwksCache(AuthConfig.jwks_url())
    return _keys


def use_signing_keys(cache: JwksCache | None) -> None:
    """Replace the process-wide cache. Tests only; pass None to clear it."""
    global _keys
    _keys = cache


def identity_in(context: Any) -> Identity | None:
    """The identity in a Strawberry context, or None.

    Tolerant on purpose. `schema.execute()` with no `context_value` gives resolvers a context
    of None, and a dozen files in this suite call it that way.
    """
    if context is None:
        return None
    if isinstance(context, dict):
        return context.get(CONTEXT_KEY)
    return getattr(context, CONTEXT_KEY, None)


def _is_ide_page(connection: HTTPConnection) -> bool:
    """A GET asking for HTML is GraphiQL fetching its own page, not an operation.

    The IDE has a Headers tab, so letting the page load and requiring a pasted token for the
    operations keeps it usable. `allow_queries_via_get` is on, so a GET *is* an operation
    transport - only the html-seeking one is the tool.
    """
    if connection.scope.get("method") != "GET":
        return False
    return "text/html" in connection.headers.get("accept", "")


async def graphql_context(connection: HTTPConnection) -> dict:
    """Validate the bearer token and hand the identity to the resolvers.

    `HTTPConnection` and not `Request`: it is the common base of Request and WebSocket, which
    is what lets one dependency serve both the POST route and the WS route.
    """
    if connection.scope.get("type") == "websocket":
        # A browser cannot set a header on a WebSocket handshake. The token arrives in
        # connection_init, and AuthenticatedGraphQLRouter.on_ws_connect checks it there.
        return {CONTEXT_KEY: None}

    if _is_ide_page(connection):
        return {CONTEXT_KEY: None}

    token = bearer_from_header(connection.headers.get("authorization"))
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="This endpoint requires a bearer token from the UNS realm.",
            headers=_UNAUTHENTICATED,
        )

    try:
        identity = await identity_from_token(token, signing_keys())
    except AuthError as ex:
        # The message is the point: "expired" and "wrong audience" are different problems and
        # an engineer reading a log needs to know which one happened.
        LOGGER.info("Rejected a request to /graphql: %s", ex)
        raise HTTPException(status_code=401, detail=str(ex), headers=_UNAUTHENTICATED) from ex

    return {CONTEXT_KEY: identity}


class AuthenticatedGraphQLRouter(GraphQLRouter):
    """A router whose subscriptions need an identity too.

    `on_ws_connect` runs after `connection_init` has been received and after Strawberry has
    put its payload on the context, which is the first moment a WebSocket token exists.
    Rejecting here closes the socket with 4403 rather than letting a subscription stream plant
    data to an anonymous client.
    """

    async def on_ws_connect(self, context: Any) -> dict[str, object]:
        params = _connection_params(context)
        token = bearer_from_header(params.get("Authorization") or params.get("authorization"))
        if token is None:
            LOGGER.info("Rejected a subscription: connection_init carried no bearer token")
            raise ConnectionRejectionError

        try:
            identity = await identity_from_token(token, signing_keys())
        except AuthError as ex:
            LOGGER.info("Rejected a subscription: %s", ex)
            raise ConnectionRejectionError from ex

        if isinstance(context, dict):
            context[CONTEXT_KEY] = identity
        else:
            setattr(context, CONTEXT_KEY, identity)
        # Echoed in connection_ack so the console can show who it connected as without
        # decoding its own token twice.
        return {"username": identity.username}


def _connection_params(context: Any) -> dict:
    params = (
        context.get("connection_params")
        if isinstance(context, dict)
        else getattr(context, "connection_params", None)
    )
    return params if isinstance(params, dict) else {}
