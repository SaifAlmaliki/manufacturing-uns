"""Business HTTPS publication admission and receipt lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from uns_config import get_settings
from uns_config.publication_http import (
    HttpPublicationRoute,
    http_route_from_dict,
    resolve_http_route,
    validate_http_routes,
)
from uns_config.publications import _parse_occurred_at
from uns_model.engine import Database
from uns_model.publication_outbox import Outbox, OutboxError, Receipt

IDEMPOTENCY_HEADER = "idempotency-key"
OCCURRED_AT_HEADER = "x-occurred-at"


@dataclass(frozen=True, slots=True)
class PublicationApiConfig:
    routes: tuple[HttpPublicationRoute, ...]
    global_budget_bytes: int
    principal_budget_bytes: int


def load_publication_api_config() -> PublicationApiConfig:
    block = get_settings("graphql").get("publication_api", {}) or {}
    raw_routes = block.get("http_routes", [])
    routes = tuple(http_route_from_dict(entry) for entry in raw_routes)
    validate_http_routes(routes)
    return PublicationApiConfig(
        routes=routes,
        global_budget_bytes=int(block.get("global_queue_budget_bytes", 1_073_741_824)),
        principal_budget_bytes=int(block.get("principal_queue_budget_bytes", 134_217_728)),
    )


class PublicationIngressService:
    def __init__(
        self,
        database: Database | None = None,
        *,
        outbox: Outbox | None = None,
        config: PublicationApiConfig | None = None,
    ) -> None:
        self._config = config or load_publication_api_config()
        if outbox is not None:
            self._outbox = outbox
        elif database is not None:
            self._outbox = Outbox(
                database,
                global_budget_bytes=self._config.global_budget_bytes,
                principal_budget_bytes=self._config.principal_budget_bytes,
            )
        else:
            raise ValueError("database or outbox is required")

    def resolve_route(self, route_id: str) -> HttpPublicationRoute:
        try:
            return resolve_http_route(route_id, self._config.routes)
        except Exception as exc:
            raise OutboxError("unknown_route", 404, route_id) from exc

    async def admit(
        self,
        *,
        principal_id: str,
        route_id: str,
        idempotency_key: str,
        body: bytes,
        occurred_at_header: str | None,
    ) -> Receipt:
        route = self.resolve_route(route_id)
        metadata = _immutable_metadata(route)
        occurred_at = _parse_optional_occurred_at(occurred_at_header)
        return await self._outbox.admit(
            principal_id,
            route,
            idempotency_key,
            body,
            metadata,
            occurred_at=occurred_at,
        )

    async def get_receipt(self, receipt_id: str, principal_id: str) -> Receipt:
        return await self._outbox.get_receipt(receipt_id, principal_id)


def _immutable_metadata(route: HttpPublicationRoute) -> dict[str, Any]:
    pair = route.route.default_schema_pair
    if pair is None:
        pair = next(iter(route.route.allowed_schema_pairs))
    return {
        "route_id": route.route_id,
        "mqtt_topic": route.mqtt_topic,
        "source_id": route.route.source_id,
        "source_application": route.route.source_application,
        "site_id": route.route.site_id,
        "payload_schema_id": pair.payload_schema_id,
        "payload_schema_version": pair.payload_schema_version,
        "content_type": route.route.content_type,
        "event_kind": route.route.event_kind,
        "archive_eligible": route.route.archive_eligible,
        "wire_format": route.route.wire_format,
    }


def _parse_optional_occurred_at(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    return _parse_occurred_at(value.strip())
