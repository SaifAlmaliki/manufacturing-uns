"""FastAPI routes for business HTTPS publication ingress."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from uns_model.publication_outbox import OutboxError

from uns_graphql.publication_api.identity import (
    PublisherIdentityError,
    verify_publisher_identity,
)
from uns_graphql.publication_api.service import (
    IDEMPOTENCY_HEADER,
    OCCURRED_AT_HEADER,
    PublicationIngressService,
)


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})
    if isinstance(exc, PublisherIdentityError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.reason, "detail": str(exc)},
        )
    if isinstance(exc, OutboxError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.reason, "detail": str(exc)},
        )
    return JSONResponse(status_code=500, content={"error": "internal_error"})


def _receipt_payload(receipt) -> dict[str, object]:
    return {
        "receipt_id": receipt.receipt_id,
        "status": receipt.status,
        "route_id": receipt.route_id,
        "mqtt_topic": receipt.mqtt_topic,
        "byte_size": receipt.byte_size,
        "created_at": receipt.created_at.isoformat(),
        "updated_at": receipt.updated_at.isoformat(),
        "broker_accepted_at": (
            receipt.broker_accepted_at.isoformat() if receipt.broker_accepted_at else None
        ),
        "error_code": receipt.error_code,
    }


def create_publication_router(service: PublicationIngressService) -> APIRouter:
    router = APIRouter(prefix="/api/publications/v1", tags=["publications"])

    @router.post("/routes/{route_id}")
    async def publish_route(
        route_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_HEADER),
        occurred_at: str | None = Header(default=None, alias=OCCURRED_AT_HEADER),
    ) -> JSONResponse:
        if not idempotency_key:
            return JSONResponse(status_code=400, content={"error": "missing_idempotency_key"})
        body = await request.body()
        try:
            identity = verify_publisher_identity(request)
            receipt = await service.admit(
                principal_id=identity.principal_id,
                route_id=route_id,
                idempotency_key=idempotency_key,
                body=body,
                occurred_at_header=occurred_at,
            )
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(status_code=202, content=_receipt_payload(receipt))

    @router.get("/receipts/{receipt_id}")
    async def get_receipt(request: Request, receipt_id: str) -> JSONResponse:
        try:
            identity = verify_publisher_identity(request)
            receipt = await service.get_receipt(receipt_id, identity.principal_id)
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(status_code=200, content=_receipt_payload(receipt))

    return router
