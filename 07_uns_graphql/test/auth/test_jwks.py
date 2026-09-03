"""Spec test 7: fetched once and cached; an unknown kid triggers exactly one refetch."""

import pytest

from uns_graphql.auth.jwks import JwksCache, UnknownSigningKeyError

from .keys import jwks_document, make_key

KEY_A = make_key("key-a")
KEY_B = make_key("key-b")


def _recording_fetch(*documents: dict):
    """Return a fetch that yields each document in turn, and the list of calls it recorded."""
    calls: list[str] = []
    remaining = list(documents)

    async def fetch(url: str) -> dict:
        calls.append(url)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return fetch, calls


@pytest.mark.asyncio
async def test_the_first_lookup_fetches_and_the_second_does_not():
    fetch, calls = _recording_fetch(jwks_document(KEY_A))
    cache = JwksCache("http://keys.test/certs", fetch=fetch)

    assert await cache.signing_key("key-a") is not None
    assert await cache.signing_key("key-a") is not None

    # A fetch per request would make every query wait on Keycloak, and an outage would stop
    # reads that a cached key can still validate (spec section 13).
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_an_unknown_kid_refetches_once_and_then_finds_the_rotated_key():
    fetch, calls = _recording_fetch(jwks_document(KEY_A), jwks_document(KEY_A, KEY_B))
    cache = JwksCache("http://keys.test/certs", fetch=fetch)

    await cache.signing_key("key-a")
    assert len(calls) == 1

    # Key rotation is the normal case this exists for.
    assert await cache.signing_key("key-b") is not None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_kid_that_is_still_unknown_after_the_refetch_raises_and_does_not_loop():
    fetch, calls = _recording_fetch(jwks_document(KEY_A))
    cache = JwksCache("http://keys.test/certs", fetch=fetch)

    with pytest.raises(UnknownSigningKeyError):
        await cache.signing_key("forged-kid")

    # Exactly one refetch. A token with an attacker-chosen kid must not be able to make this
    # service hammer Keycloak once per request.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_failed_refetch_leaves_the_cached_keys_usable():
    calls: list[str] = []

    async def fetch(url: str) -> dict:
        calls.append(url)
        if len(calls) == 1:
            return jwks_document(KEY_A)
        raise ConnectionError("Keycloak is down")

    cache = JwksCache("http://keys.test/certs", fetch=fetch)
    await cache.signing_key("key-a")

    with pytest.raises(UnknownSigningKeyError):
        await cache.signing_key("key-b")

    # Spec section 13: "Cached JWKS keeps validation working until a key rotates."
    assert await cache.signing_key("key-a") is not None
