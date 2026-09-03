"""Turn a bearer token into an identity, or raise.

Pure given a key, so the tests mint their own tokens and no test needs Keycloak. Every
rejection raises `AuthError` with a sentence, because the message reaches the client and
"invalid token" tells an engineer nothing about which of six things went wrong.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import jwt
from uns_config import AuthConfig

from uns_graphql.auth.jwks import JwksCache, UnknownSigningKeyError

LOGGER = logging.getLogger(__name__)

# The five in ConsoleRole (type/alert_rule.py:70) and UserRole (11_frontend/src/types/rbac.ts:5).
CONSOLE_ROLES: frozenset[str] = frozenset({"admin", "engineer", "operator", "auditor", "viewer"})

_BEARER = "bearer "


class AuthError(Exception):
    """The request carried no usable identity. The message is shown to the caller."""


@dataclass(frozen=True)
class Identity:
    """Who the realm says is calling. Constructed only by `identity_from_token`."""

    subject: str
    username: str
    roles: frozenset[str]

    def has_any(self, roles: Iterable[str]) -> bool:
        return bool(self.roles & frozenset(roles))


def bearer_from_header(value: str | None) -> str | None:
    """The token out of an Authorization header, or None. Case-insensitive on the scheme only."""
    if not value:
        return None
    if not value.lower().startswith(_BEARER):
        return None
    token = value[len(_BEARER):].strip()
    return token or None


def _roles_from_claims(claims: dict) -> frozenset[str]:
    """Realm roles, filtered to the five this platform knows.

    Keycloak issues `offline_access`, `uma_authorization` and `default-roles-<realm>` to
    everybody. Dropping the unrecognised rather than guessing follows
    11_frontend/src/lib/alarms/map-alert-rules.ts:50-56.
    """
    realm_access = claims.get("realm_access") or {}
    granted = realm_access.get("roles") or []
    return frozenset(role for role in granted if role in CONSOLE_ROLES)


async def identity_from_token(token: str, keys: JwksCache) -> Identity:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as ex:
        raise AuthError("The Authorization header is not a JSON Web Token.") from ex

    kid = header.get("kid")
    if not kid:
        # Every Keycloak token has one. A token without it cannot be matched to a key, and
        # searching every key for one that happens to verify is how algorithm-confusion bugs
        # get in.
        raise AuthError("The token names no signing key (no `kid` header).")

    try:
        key = await keys.signing_key(kid)
    except UnknownSigningKeyError as ex:
        raise AuthError(
            f"The token was signed by key {kid!r}, which this realm does not publish."
        ) from ex

    try:
        claims = jwt.decode(
            token,
            key,
            # RS256 only, from the algorithm in the realm export. Never read the header's
            # `alg`: that is how a token arrives signed with `none` or with HMAC over the
            # public key.
            algorithms=["RS256"],
            issuer=AuthConfig.issuer,
            audience=AuthConfig.audience,
            leeway=AuthConfig.leeway_seconds,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as ex:
        raise AuthError("The token has expired. Sign in again.") from ex
    except jwt.InvalidIssuerError as ex:
        raise AuthError(f"The token was issued by somebody other than {AuthConfig.issuer}.") from ex
    except jwt.InvalidAudienceError as ex:
        raise AuthError(
            f"The token was issued for a different application, not {AuthConfig.audience}."
        ) from ex
    except jwt.PyJWTError as ex:
        raise AuthError("The token's signature could not be verified.") from ex

    return Identity(
        subject=str(claims["sub"]),
        # `preferred_username` and not the subject UUID: this is what gets stored on a
        # downtime reassignment, and a UUID is unreadable to the next shift lead
        # (spec section 16).
        username=str(claims.get("preferred_username") or claims["sub"]),
        roles=_roles_from_claims(claims),
    )
