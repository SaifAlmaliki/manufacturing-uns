"""Turn a bearer token into an identity, or raise."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import jwt
from uns_config import AuthConfig

CONSOLE_ROLES: frozenset[str] = frozenset({"admin", "engineer", "operator", "auditor", "viewer"})
_BEARER = "bearer "


class AuthError(Exception):
    """The request carried no usable identity. The message is shown to the caller."""


@dataclass(frozen=True)
class Identity:
    subject: str
    username: str
    roles: frozenset[str]

    def has_any(self, roles: Iterable[str]) -> bool:
        return bool(self.roles & frozenset(roles))

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


class UnknownSigningKeyError(Exception):
    """The JWKS document does not publish the kid the token names."""


class JwksCache(Protocol):
    async def signing_key(self, kid: str) -> str: ...


def bearer_from_header(value: str | None) -> str | None:
    if not value:
        return None
    if not value.lower().startswith(_BEARER):
        return None
    token = value[len(_BEARER) :].strip()
    return token or None


def _roles_from_claims(claims: dict) -> frozenset[str]:
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
        username=str(claims.get("preferred_username") or claims["sub"]),
        roles=_roles_from_claims(claims),
    )
