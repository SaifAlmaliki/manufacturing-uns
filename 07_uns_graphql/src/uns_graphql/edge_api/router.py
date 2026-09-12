"""FastAPI routes for cloud edge management."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from uns_config.edge_contracts import EdgeReport as EdgeReportContract

from uns_graphql.edge_api.enrollment import MAX_ENROLLMENT_BODY_BYTES, EnrollmentError
from uns_graphql.edge_api.identity import (
    EDGE_ID_HEADER,
    EDGE_PURPOSE_HEADER,
    EDGE_SERIAL_HEADER,
    TRUSTED_PROXY_HEADER,
    EdgeIdentityError,
    VerifiedEdgeIdentity,
    verify_management_identity,
)
from uns_graphql.edge_api.service import EdgeManagementService, EdgeServiceError, LeaseHeaders


class EnrollRequest(BaseModel):
    enrollment_token: str
    management_csr: str
    mqtt_csr: str


class SessionRequest(BaseModel):
    boot_id: str


class RenewRequest(BaseModel):
    purpose: str
    csr: str


class ReportRequest(BaseModel):
    edge_id: str
    boot_id: str
    report_sequence: int
    desired_revision: int
    applied_revision: int
    applied_digest: str
    phase: str
    adapter_results: list[dict[str, Any]] = Field(default_factory=list)
    last_error_code: str | None = None
    versions: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})
    if isinstance(exc, (EnrollmentError, EdgeIdentityError, EdgeServiceError)):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.reason, "detail": str(exc)},
        )
    return JSONResponse(status_code=500, content={"error": "internal_error"})


def _lease_headers(
    boot_id: Annotated[str | None, Header(alias="x-edge-boot-id")] = None,
    generation: Annotated[int | None, Header(alias="x-edge-lease-generation")] = None,
    lease_token: Annotated[str | None, Header(alias="x-edge-lease-token")] = None,
) -> LeaseHeaders:
    if not boot_id or generation is None or not lease_token:
        raise HTTPException(status_code=409, detail={"error": "lease_headers_missing"})
    return LeaseHeaders(boot_id=boot_id, generation=generation, lease_token=lease_token)


def create_edge_router(service: EdgeManagementService) -> APIRouter:
    router = APIRouter(prefix="/api/edge/v1", tags=["edge"])

    @router.post("/enroll")
    async def enroll(request: Request, body: EnrollRequest) -> JSONResponse:
        raw = await request.body()
        if len(raw) > MAX_ENROLLMENT_BODY_BYTES:
            return JSONResponse(status_code=413, content={"error": "body_too_large"})
        client_key = request.client.host if request.client else "unknown"
        try:
            result = await service.enroll(
                enrollment_token=body.enrollment_token,
                management_csr=body.management_csr,
                mqtt_csr=body.mqtt_csr,
                client_key=client_key,
            )
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(
            status_code=200,
            content={
                "edge_id": result.edge_id,
                "management_certificate_chain": list(result.management_certificate_chain),
                "mqtt_certificate_chain": list(result.mqtt_certificate_chain),
                "management_subject": result.management_subject,
                "mqtt_subject": result.mqtt_subject,
                "management_serial": result.management_serial,
                "mqtt_serial": result.mqtt_serial,
            },
        )

    @router.post("/session")
    async def open_session(
        request: Request,
        body: SessionRequest,
    ) -> JSONResponse:
        try:
            identity = verify_management_identity(request)
            lease = await service.open_session(identity, body.boot_id)
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(
            status_code=200,
            content={
                "edge_id": lease.edge_id,
                "boot_id": lease.boot_id,
                "generation": lease.generation,
                "lease_token": lease.lease_token,
                "expires_at": lease.expires_at.isoformat(),
            },
        )

    @router.get("/configuration")
    async def get_configuration(
        request: Request,
        if_none_match: Annotated[str | None, Header()] = None,
    ) -> Response:
        try:
            identity = verify_management_identity(request)
            lease = _lease_headers(
                request.headers.get("x-edge-boot-id"),
                int(request.headers["x-edge-lease-generation"])
                if request.headers.get("x-edge-lease-generation") is not None
                else None,
                request.headers.get("x-edge-lease-token"),
            )
            snapshot = await service.get_configuration(
                identity,
                lease,
                if_none_match=if_none_match,
            )
        except Exception as exc:
            return _error_response(exc)
        if snapshot is None:
            return Response(status_code=304)
        body = json.dumps(snapshot.document, separators=(",", ":"), sort_keys=True)
        return Response(
            status_code=200,
            content=body,
            media_type="application/json",
            headers={"ETag": f'"{snapshot.digest}"', "X-Edge-Revision": str(snapshot.revision)},
        )

    @router.post("/reports")
    async def submit_report(
        request: Request,
        body: ReportRequest,
        lease: Annotated[LeaseHeaders, Depends(_lease_headers)],
    ) -> JSONResponse:
        report = EdgeReportContract(
            edge_id=body.edge_id,
            boot_id=body.boot_id,
            report_sequence=body.report_sequence,
            desired_revision=body.desired_revision,
            applied_revision=body.applied_revision,
            applied_digest=body.applied_digest,
            phase=body.phase,
            adapter_results=tuple(body.adapter_results),
            last_error_code=body.last_error_code,
            versions=body.versions,
            capabilities=body.capabilities,
        )
        try:
            identity = verify_management_identity(request)
            payload = await service.submit_report(identity, lease, report)
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(status_code=200, content=payload)

    @router.get("/secrets/{secret_id}/{version}")
    async def fetch_secret(
        request: Request,
        secret_id: str,
        version: int,
        lease: Annotated[LeaseHeaders, Depends(_lease_headers)],
    ) -> Response:
        try:
            identity = verify_management_identity(request)
            plaintext = await service.fetch_secret(identity, lease, secret_id, version)
        except Exception as exc:
            return _error_response(exc)
        return Response(status_code=200, content=plaintext, media_type="application/octet-stream")

    @router.post("/renew")
    async def renew_certificate(request: Request, body: RenewRequest) -> JSONResponse:
        try:
            identity = verify_management_identity(request)
            issued = await service.renew(identity, body.purpose, body.csr)
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(
            status_code=200,
            content={
                "certificate_id": issued.certificate_id,
                "purpose": issued.purpose,
                "certificate_chain": list(issued.chain_pem),
                "subject": issued.subject,
                "not_before": issued.not_before.isoformat(),
                "not_after": issued.not_after.isoformat(),
            },
        )

    return router


def identity_headers(
    edge_id: str,
    *,
    purpose: str = "management",
    serial: str,
    trusted: bool = True,
) -> dict[str, str]:
    headers = {
        EDGE_ID_HEADER: edge_id,
        EDGE_PURPOSE_HEADER: purpose,
        EDGE_SERIAL_HEADER: serial,
    }
    if trusted:
        from uns_graphql.edge_api.identity import trusted_proxy_value

        headers[TRUSTED_PROXY_HEADER] = trusted_proxy_value()
    return headers
