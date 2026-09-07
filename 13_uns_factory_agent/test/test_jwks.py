"""JWKS cache must keep signing keys even when Keycloak also publishes encryption keys."""

import pytest

from uns_factory_agent.jwks import JwksCache

from keys import jwks_document, make_key

KEY_A = make_key("key-a")

# Keycloak publishes both a sig key and an RSA-OAEP enc key in the same document.
# PyJWK cannot load the enc key; GraphQL already skips it.
ENC_JWK = {
    "kid": "enc-key",
    "kty": "RSA",
    "alg": "RSA-OAEP",
    "use": "enc",
    "n": KEY_A.jwk["n"],
    "e": KEY_A.jwk["e"],
}


@pytest.mark.asyncio
async def test_encryption_keys_in_the_jwks_document_are_skipped():
    document = jwks_document(KEY_A)
    document["keys"].append(ENC_JWK)

    async def fetch(_url: str) -> dict:
        return document

    cache = JwksCache("http://keys.test/certs", fetch=fetch)
    assert await cache.signing_key("key-a") is not None
