"""RSA keys and tokens minted in-process, so no test in this suite needs Keycloak.

A test that borrowed a real token would expire, and a test that skipped signature
verification would be testing nothing. So the suite is its own certificate authority.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "http://localhost:8088/auth/realms/uns"
AUDIENCE = "uns-console"


def _b64u(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class TestKey:
    """One RSA keypair, its JWK, and a mint() that signs with it."""

    kid: str
    private_pem: bytes
    jwk: dict

    def mint(
        self,
        *,
        roles: list[str] | None = None,
        username: str = "operator.user",
        subject: str = "11111111-2222-3333-4444-555555555555",
        issuer: str = ISSUER,
        audience: str | list[str] = AUDIENCE,
        expires_in: int = 900,
        issued_at: int | None = None,
    ) -> str:
        now = int(time.time()) if issued_at is None else issued_at
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "preferred_username": username,
            "iat": now,
            "exp": now + expires_in,
            # Keycloak's shape for realm roles. Client roles live under resource_access and
            # this platform does not use them.
            "realm_access": {"roles": list(roles if roles is not None else ["operator"])},
        }
        return jwt.encode(claims, self.private_pem, algorithm="RS256", headers={"kid": self.kid})


def make_key(kid: str = "test-key-1") -> TestKey:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    return TestKey(
        kid=kid,
        private_pem=private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        jwk={
            "kty": "RSA",
            "kid": kid,
            "alg": "RS256",
            "use": "sig",
            "n": _b64u(numbers.n),
            "e": _b64u(numbers.e),
        },
    )


def jwks_document(*keys: TestKey) -> dict:
    return {"keys": [key.jwk for key in keys]}
