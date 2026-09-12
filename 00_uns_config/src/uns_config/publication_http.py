"""Registered HTTPS publication routes for business-system ingress.

Pure contract code: no Kafka, MQTT, database, or cloud SDK imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from uns_config.events import EnvelopeError
from uns_config.publication_routes import (
    ROUTE_ID_PATTERN,
    PublicationRoute,
    publication_route_from_dict,
    validate_routes,
)

HTTP_ROUTE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True, slots=True)
class HttpPublicationRoute:
    route_id: str
    mqtt_topic: str
    principal_id: str
    route: PublicationRoute


def http_route_from_dict(raw: dict[str, Any]) -> HttpPublicationRoute:
    route_id = raw.get("route_id")
    mqtt_topic = raw.get("mqtt_topic")
    principal_id = raw.get("principal_id")
    if not isinstance(route_id, str) or not HTTP_ROUTE_ID_PATTERN.fullmatch(route_id):
        raise EnvelopeError("invalid_field", "route_id")
    if not isinstance(mqtt_topic, str) or not mqtt_topic or "+" in mqtt_topic or "#" in mqtt_topic:
        raise EnvelopeError("invalid_field", "mqtt_topic")
    if not isinstance(principal_id, str) or not ROUTE_ID_PATTERN.fullmatch(principal_id):
        raise EnvelopeError("invalid_field", "principal_id")
    route_fields = dict(raw)
    for key in ("route_id", "mqtt_topic", "principal_id"):
        route_fields.pop(key, None)
    publication_route = publication_route_from_dict(route_fields)
    if publication_route.wire_format != "uns-publication-v1":
        raise EnvelopeError("invalid_field", "wire_format")
    return HttpPublicationRoute(
        route_id=route_id,
        mqtt_topic=mqtt_topic,
        principal_id=principal_id,
        route=publication_route,
    )


def validate_http_routes(routes: tuple[HttpPublicationRoute, ...] | list[HttpPublicationRoute]) -> None:
    normalized = tuple(routes)
    validate_routes(tuple(route.route for route in normalized))
    seen_ids: set[str] = set()
    for route in normalized:
        if route.route_id in seen_ids:
            raise EnvelopeError("ambiguous_route", route.route_id)
        seen_ids.add(route.route_id)


def resolve_http_route(route_id: str, routes: tuple[HttpPublicationRoute, ...]) -> HttpPublicationRoute:
    for route in routes:
        if route.route_id == route_id:
            return route
    raise EnvelopeError("unknown_route", route_id)
