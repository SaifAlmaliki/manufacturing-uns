from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from jwt import PyJWK

from uns_factory_agent.auth import UnknownSigningKeyError


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
        document = await self._fetch(self._url)
        refreshed: dict[str, Any] = {}
        for jwk in document.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            refreshed[kid] = PyJWK.from_dict(jwk).key
        if refreshed:
            self._keys = refreshed
