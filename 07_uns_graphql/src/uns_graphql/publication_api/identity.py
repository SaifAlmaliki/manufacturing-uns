"""Trusted-proxy mTLS identity for business publishers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from uns_config import get_settings

TRUSTED_PROXY_HEADER = "x-uns-trusted-proxy"
PUBLISHER_ID_HEADER = "x-publisher-id"
PUBLISHER_PURPOSE_HEADER = "x-publisher-cert-purpose"
PUBLISHER_SERIAL_HEADER = "x-publisher-cert-serial"

FORBIDDEN_ROUTE_HEADERS = (
    "x-source-application",
    "x-site-id",
    "x-payload-schema-id",
    "x-payload-schema-version",
    "x-content-type",
    "x-mqtt-topic",
)


class PublisherIdentityError(Exception):
    def __init__(self, reason: str, status_code: int, detail: str = "") -> None:
        self.reason = reason
        self.status_code = status_code
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class VerifiedPublisherIdentity:
    principal_id: str
    certificate_serial: str


def _settings_block() -> dict:
    return get_settings("graphql").get("publication_api", {}) or {}


def trusted_proxy_value() -> str:
    return str(_settings_block().get("trusted_proxy_value", "1"))


def require_trusted_proxy(request: Request) -> None:
    if request.headers.get(TRUSTED_PROXY_HEADER) != trusted_proxy_value():
        raise PublisherIdentityError("missing_trusted_proxy", 401)


def reject_conflicting_headers(request: Request) -> None:
    for header in FORBIDDEN_ROUTE_HEADERS:
        if request.headers.get(header):
            raise PublisherIdentityError("conflicting_header", 400, header)


def verify_publisher_identity(request: Request) -> VerifiedPublisherIdentity:
    require_trusted_proxy(request)
    reject_conflicting_headers(request)
    principal_id = request.headers.get(PUBLISHER_ID_HEADER, "").strip()
    purpose = request.headers.get(PUBLISHER_PURPOSE_HEADER, "").strip()
    serial = request.headers.get(PUBLISHER_SERIAL_HEADER, "").strip()
    if not principal_id or not purpose or not serial:
        raise PublisherIdentityError("forged_identity_header", 401, "incomplete proxy identity")
    if purpose != "business":
        raise PublisherIdentityError("invalid_purpose", 403, purpose)
    return VerifiedPublisherIdentity(principal_id=principal_id, certificate_serial=serial)


def publisher_identity_headers(
    principal_id: str,
    *,
    serial: str,
    trusted: bool = True,
) -> dict[str, str]:
    headers = {
        PUBLISHER_ID_HEADER: principal_id,
        PUBLISHER_PURPOSE_HEADER: "business",
        PUBLISHER_SERIAL_HEADER: serial,
    }
    if trusted:
        headers[TRUSTED_PROXY_HEADER] = trusted_proxy_value()
    return headers
