"""Spec tests 2, 3 and 6, plus the claim mapping every later task depends on."""

import time

import pytest

from uns_graphql.auth.jwks import JwksCache
from uns_graphql.auth.token import AuthError, Identity, bearer_from_header, identity_from_token

from .keys import AUDIENCE, ISSUER, jwks_document, make_key

REALM_KEY = make_key("realm-key")
ATTACKER_KEY = make_key("realm-key")  # same kid, different key: the substitution attack


def _cache(*keys) -> JwksCache:
    document = jwks_document(*keys)

    async def fetch(_url: str) -> dict:
        return document

    return JwksCache("http://keys.test/certs", fetch=fetch)


@pytest.mark.asyncio
async def test_a_token_signed_by_the_realm_resolves_to_an_identity():
    token = REALM_KEY.mint(roles=["engineer"], username="erin.engineer")

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert isinstance(identity, Identity)
    assert identity.username == "erin.engineer"
    assert identity.roles == frozenset({"engineer"})


@pytest.mark.asyncio
async def test_a_token_signed_by_the_wrong_key_is_rejected():
    # Same kid, so the cache finds a key. Only signature verification catches this.
    token = ATTACKER_KEY.mint(roles=["admin"])

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_an_expired_token_is_rejected():
    token = REALM_KEY.mint(issued_at=int(time.time()) - 7200, expires_in=900)

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_from_another_issuer_is_rejected():
    token = REALM_KEY.mint(issuer="http://evil.example/realms/uns")

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_for_another_audience_is_rejected():
    # Grafana's tokens are signed by the same realm with the same key. Without an audience
    # check, a Grafana token would be accepted as a console token.
    token = REALM_KEY.mint(audience="uns-grafana")

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_naming_an_unknown_role_is_accepted_with_that_role_dropped():
    # Spec test 6, and the precedent in map-alert-rules.ts:50-56: "Anything unrecognised is
    # dropped rather than guessed."
    token = REALM_KEY.mint(roles=["engineer", "offline_access", "default-roles-uns"])

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert identity.roles == frozenset({"engineer"})


@pytest.mark.asyncio
async def test_a_token_with_no_recognised_role_is_still_an_identity():
    # Spec section 13: "A user with no recognised role can read and cannot mutate." Rejecting
    # them here would make an unrecognised role look like a broken login.
    token = REALM_KEY.mint(roles=["offline_access"])

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert identity.roles == frozenset()
    assert identity.username == "operator.user"


@pytest.mark.asyncio
async def test_a_token_with_no_realm_access_claim_is_an_identity_with_no_roles():
    token = REALM_KEY.mint(roles=[])

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert identity.roles == frozenset()


@pytest.mark.asyncio
async def test_a_token_that_is_not_a_jwt_is_rejected_without_a_key_lookup():
    with pytest.raises(AuthError):
        await identity_from_token("not.a.token", _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_with_no_kid_is_rejected():
    import jwt

    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "s", "exp": int(time.time()) + 60},
        REALM_KEY.private_pem,
        algorithm="RS256",
    )

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


def test_bearer_is_read_case_insensitively_and_nothing_else_is():
    assert bearer_from_header("Bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_from_header("bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_from_header(None) is None
    assert bearer_from_header("") is None
    assert bearer_from_header("Basic dXNlcjpwYXNz") is None
    # A bare token is not a bearer token. Accepting it would be one more shape to reason about.
    assert bearer_from_header("abc.def.ghi") is None


def test_identity_has_any():
    identity = Identity(subject="s", username="u", roles=frozenset({"operator"}))
    assert identity.has_any(["operator", "engineer"]) is True
    assert identity.has_any(["engineer", "admin"]) is False
    assert identity.has_any([]) is False
