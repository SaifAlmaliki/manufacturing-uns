"""The realm's signing keys, fetched once and kept.

Fetching per request would put Keycloak in the path of every query, and an outage would then
stop reads that a key already in memory can validate perfectly well. So: cache by `kid`, and
refetch at most once when a `kid` is unknown, because that is what key rotation looks like.

`fetch` is injectable so the tests never open a socket.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from jwt import PyJWK

LOGGER = logging.getLogger(__name__)


class UnknownSigningKeyError(Exception):
    """No key with that `kid`, and a refetch did not produce one."""


async def _fetch_over_http(url: str) -> dict:
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        response.raise_for_status()
        return await response.json()


class JwksCache:
    """Signing keys by `kid`, with one refetch on a miss."""

    def __init__(
        self,
        url: str,
        *,
        fetch: Callable[[str], Awaitable[dict]] | None = None,
    ) -> None:
        self._url = url
        self._fetch = fetch or _fetch_over_http
        self._keys: dict[str, Any] = {}
        self._fetches = 0
        # One refetch at a time: a hundred requests arriving after a rotation must not become
        # a hundred requests to Keycloak.
        self._lock = asyncio.Lock()

    def fetch_count(self) -> int:
        """How many times the document has been fetched. Exists for the caching test."""
        return self._fetches

    async def signing_key(self, kid: str) -> Any:
        if kid in self._keys:
            return self._keys[kid]

        async with self._lock:
            # Another coroutine may have refreshed while this one waited.
            if kid in self._keys:
                return self._keys[kid]
            await self._refresh()

        if kid not in self._keys:
            raise UnknownSigningKeyError(f"The realm has no signing key {kid!r}")
        return self._keys[kid]

    async def _refresh(self) -> None:
        try:
            document = await self._fetch(self._url)
            self._fetches += 1
        except Exception:
            # Keep whatever is cached. Spec section 13: cached keys keep validation working
            # until a key rotates, and a rotation during an outage is the unlucky case.
            LOGGER.warning("Could not refresh JWKS from %s; keeping %s cached key(s)",
                           self._url, len(self._keys))
            return

        refreshed: dict[str, Any] = {}
        for jwk in document.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            try:
                refreshed[kid] = PyJWK.from_dict(jwk).key
            except Exception:
                # One unusable key in the document must not cost us the rest of them.
                LOGGER.warning("Skipping unusable JWK %s from the realm", kid)
        if refreshed:
            self._keys = refreshed

    async def close(self) -> None:
        """Nothing to close: each fetch owns its session. Here so callers can be symmetric."""
        return None
