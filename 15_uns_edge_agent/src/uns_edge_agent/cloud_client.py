"""HTTPS client for the cloud edge management API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

from uns_config.edge_contracts import EdgeReport

from uns_edge_agent.credentials import CredentialStore


class CloudClientError(Exception):
    """Cloud API failure."""

    def __init__(self, reason: str, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class Lease:
    edge_id: str
    boot_id: str
    generation: int
    lease_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    revision: int
    digest: str
    document: dict[str, Any]
    etag: str


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        timeout: float | None = None,
    ) -> Any: ...


class CloudClient:
    """Outbound HTTPS client for /api/edge/v1 endpoints."""

    def __init__(
        self,
        base_url: str,
        credentials: CredentialStore,
        *,
        request_timeout_seconds: float = 30.0,
        connect_timeout_seconds: float = 10.0,
        transport: HttpTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credentials = credentials
        self._timeout = httpx.Timeout(request_timeout_seconds, connect=connect_timeout_seconds)
        self._transport = transport

    def _client(self) -> httpx.Client:
        if self._transport is not None:
            return httpx.Client(transport=self._transport, timeout=self._timeout)
        return httpx.Client(
            verify=self._credentials.management_ssl_context(),
            timeout=self._timeout,
        )

    def enroll(
        self,
        *,
        enrollment_token: str,
        management_csr: str,
        mqtt_csr: str,
    ) -> dict[str, Any]:
        payload = {
            "enrollment_token": enrollment_token,
            "management_csr": management_csr,
            "mqtt_csr": mqtt_csr,
        }
        with self._client() as client:
            response = client.post(f"{self._base_url}/api/edge/v1/enroll", json=payload)
        if response.status_code != 200:
            raise CloudClientError(_error_reason(response), response.status_code)
        return response.json()

    def open_session(self, boot_id: str) -> Lease:
        manifest = self._credentials.load_manifest()
        with self._client() as client:
            response = client.post(
                f"{self._base_url}/api/edge/v1/session",
                json={"boot_id": boot_id},
                headers=_identity_headers(manifest),
            )
        if response.status_code != 200:
            raise CloudClientError(_error_reason(response), response.status_code)
        payload = response.json()
        return Lease(
            edge_id=payload["edge_id"],
            boot_id=payload["boot_id"],
            generation=int(payload["generation"]),
            lease_token=payload["lease_token"],
            expires_at=datetime.fromisoformat(payload["expires_at"]),
        )

    def get_configuration(
        self,
        lease: Lease,
        *,
        if_none_match: str | None = None,
    ) -> ConfigurationSnapshot | None:
        headers = _identity_headers(self._credentials.load_manifest())
        headers.update(_lease_headers(lease))
        if if_none_match:
            headers["If-None-Match"] = if_none_match
        with self._client() as client:
            response = client.get(
                f"{self._base_url}/api/edge/v1/configuration",
                headers=headers,
            )
        if response.status_code == 304:
            return None
        if response.status_code != 200:
            raise CloudClientError(_error_reason(response), response.status_code)
        etag = response.headers.get("ETag", "").strip('"')
        revision = int(response.headers.get("X-Edge-Revision", "0"))
        document = response.json()
        return ConfigurationSnapshot(
            revision=revision,
            digest=etag,
            document=document,
            etag=etag,
        )

    def submit_report(self, lease: Lease, report: EdgeReport | dict[str, Any]) -> dict[str, Any]:
        manifest = self._credentials.load_manifest()
        payload = _report_payload(report)
        headers = _identity_headers(manifest)
        headers.update(_lease_headers(lease))
        with self._client() as client:
            response = client.post(
                f"{self._base_url}/api/edge/v1/reports",
                json=payload,
                headers=headers,
            )
        if response.status_code != 200:
            raise CloudClientError(_error_reason(response), response.status_code)
        return response.json()

    def fetch_secret(self, lease: Lease, secret_id: str, version: int) -> bytes:
        headers = _identity_headers(self._credentials.load_manifest())
        headers.update(_lease_headers(lease))
        with self._client() as client:
            response = client.get(
                f"{self._base_url}/api/edge/v1/secrets/{secret_id}/{version}",
                headers=headers,
            )
        if response.status_code != 200:
            raise CloudClientError(_error_reason(response), response.status_code)
        return response.content


def _identity_headers(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "x-edge-id": str(manifest["edge_id"]),
        "x-edge-cert-purpose": "management",
        "x-edge-cert-serial": str(manifest["management_serial"]),
        "x-uns-trusted-proxy": "1",
    }


def _lease_headers(lease: Lease) -> dict[str, str]:
    return {
        "x-edge-boot-id": lease.boot_id,
        "x-edge-lease-generation": str(lease.generation),
        "x-edge-lease-token": lease.lease_token,
    }


def _report_payload(report: EdgeReport | dict[str, Any]) -> dict[str, Any]:
    if isinstance(report, dict):
        return dict(report)
    return {
        "edge_id": report.edge_id,
        "boot_id": report.boot_id,
        "report_sequence": report.report_sequence,
        "desired_revision": report.desired_revision,
        "applied_revision": report.applied_revision,
        "applied_digest": report.applied_digest,
        "phase": report.phase,
        "adapter_results": list(report.adapter_results),
        "last_error_code": report.last_error_code,
        "versions": dict(report.versions),
        "capabilities": dict(report.capabilities),
    }


def _error_reason(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return f"http_{response.status_code}"
    if isinstance(payload, dict) and "error" in payload:
        return str(payload["error"])
    return f"http_{response.status_code}"
