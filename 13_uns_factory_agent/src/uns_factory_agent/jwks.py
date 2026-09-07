from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from jwt import PyJWK

from uns_factory_agent.auth import UnknownSigningKeyError

LOGGER = logging.getLogger(__name__)


async def _fetch_over_http(url: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


class JwksCache:
    def __init__(
        self,
        url: str,
        *,
        fetch: Callable[[str], Awaitable[dict]] | None = None,
    ) -> None:
        self._url = url
        self._fetch = fetch or _fetch_over_http
        self._keys: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def signing_key(self, kid: str) -> Any:
        if kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            if kid in self._keys:
                return self._keys[kid]
            await self._refresh()
        if kid not in self._keys:
            raise UnknownSigningKeyError(f"The realm has no signing key {kid!r}")
        return self._keys[kid]

    async def _refresh(self) -> None:
        try:
            document = await self._fetch(self._url)
        except Exception:
            LOGGER.warning(
                "Could not refresh JWKS from %s; keeping %s cached key(s)",
                self._url,
                len(self._keys),
            )
            return

        refreshed: dict[str, Any] = {}
        for jwk in document.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            # Keycloak publishes RSA-OAEP encryption keys alongside RS256 signing keys.
            # PyJWK cannot load the enc key; skip it so the sig key still validates tokens.
            if jwk.get("use") == "enc":
                continue
            try:
                refreshed[kid] = PyJWK.from_dict(jwk).key
            except Exception:
                LOGGER.warning("Skipping unusable JWK %s from the realm", kid)
        if refreshed:
            self._keys = refreshed
