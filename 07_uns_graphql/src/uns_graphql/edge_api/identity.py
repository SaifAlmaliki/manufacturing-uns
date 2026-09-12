"""Trusted-proxy mTLS identity forwarded from the TLS terminator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Request
from uns_config import get_settings

from uns_graphql.edge_api.issuer import EdgeCertPurpose

TRUSTED_PROXY_HEADER = "x-uns-trusted-proxy"
EDGE_ID_HEADER = "x-edge-id"
EDGE_PURPOSE_HEADER = "x-edge-cert-purpose"
EDGE_SERIAL_HEADER = "x-edge-cert-serial"

EdgeIdentityFailure = Literal[
    "missing_trusted_proxy",
    "forged_identity_header",
    "missing_identity",
    "invalid_purpose",
    "expired_identity",
]


class EdgeIdentityError(Exception):
    """Identity verification failure with a stable HTTP status."""

    def __init__(self, reason: EdgeIdentityFailure, status_code: int, detail: str = "") -> None:
        self.reason = reason
        self.status_code = status_code
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class VerifiedEdgeIdentity:
    edge_id: str
    purpose: EdgeCertPurpose
    certificate_serial: str


def _settings_block() -> dict:
    return get_settings("graphql").get("edge_management", {}) or {}


def trusted_proxy_value() -> str:
    return str(_settings_block().get("trusted_proxy_value", "1"))


def require_trusted_proxy(request: Request) -> None:
    """Reject requests that bypass the private TLS terminator."""
    if request.headers.get(TRUSTED_PROXY_HEADER) != trusted_proxy_value():
        raise EdgeIdentityError("missing_trusted_proxy", 401)


def verify_management_identity(request: Request) -> VerifiedEdgeIdentity:
    """Parse proxy-injected identity and require management certificate purpose."""
    require_trusted_proxy(request)
    edge_id = request.headers.get(EDGE_ID_HEADER, "").strip()
    purpose = request.headers.get(EDGE_PURPOSE_HEADER, "").strip()
    serial = request.headers.get(EDGE_SERIAL_HEADER, "").strip()
    if not edge_id or not purpose or not serial:
        raise EdgeIdentityError("forged_identity_header", 401, "incomplete proxy identity")
    if purpose != "management":
        raise EdgeIdentityError("invalid_purpose", 403, purpose)
    return VerifiedEdgeIdentity(edge_id=edge_id, purpose="management", certificate_serial=serial)
