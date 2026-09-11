"""Registered MQTT publication routes for UNS-to-lake delivery.

Pure contract code: no Kafka, MQTT, database, or cloud SDK imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from uns_config.events import EnvelopeError, EventKind, _EVENT_KINDS

WireFormat = Literal["raw", "uns-publication-v1"]
ROUTE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_WIRE_FORMATS: frozenset[str] = frozenset({"raw", "uns-publication-v1"})


@dataclass(frozen=True, slots=True)
class SchemaPair:
    payload_schema_id: str
    payload_schema_version: str


@dataclass(frozen=True, slots=True)
class PublicationRoute:
    topic_filter: str
    source_id: str
    source_application: str
    site_id: str
    wire_format: WireFormat
    allowed_schema_pairs: frozenset[SchemaPair]
    default_schema_pair: SchemaPair | None
    content_type: str
    event_kind: EventKind
    archive_eligible: bool


def schema_pair_from_dict(raw: dict[str, Any]) -> SchemaPair:
    return SchemaPair(
        payload_schema_id=raw["payload_schema_id"],
        payload_schema_version=raw["payload_schema_version"],
    )


def publication_route_from_dict(raw: dict[str, Any]) -> PublicationRoute:
    allowed = frozenset(schema_pair_from_dict(entry) for entry in raw["allowed_schema_pairs"])
    default_raw = raw.get("default_schema_pair")
    default = schema_pair_from_dict(default_raw) if default_raw is not None else None
    return PublicationRoute(
        topic_filter=raw["topic_filter"],
        source_id=raw["source_id"],
        source_application=raw["source_application"],
        site_id=raw["site_id"],
        wire_format=raw["wire_format"],
        allowed_schema_pairs=allowed,
        default_schema_pair=default,
        content_type=raw["content_type"],
        event_kind=raw["event_kind"],
        archive_eligible=bool(raw["archive_eligible"]),
    )


def validate_routes(routes: tuple[PublicationRoute, ...] | list[PublicationRoute]) -> None:
    normalized = tuple(routes)
    parsed_filters: list[tuple[str, list[str]]] = []
    for route in normalized:
        _validate_route(route)
        segments = _parse_topic_filter(route.topic_filter)
        parsed_filters.append((route.topic_filter, segments))

    for index, (left_filter, left_segments) in enumerate(parsed_filters):
        for right_filter, right_segments in parsed_filters[index + 1 :]:
            if left_filter == right_filter or _filters_overlap(left_segments, right_segments):
                raise EnvelopeError("ambiguous_route", f"{left_filter} overlaps {right_filter}")


def resolve_route(topic: str, routes: tuple[PublicationRoute, ...] | list[PublicationRoute]) -> PublicationRoute:
    matches = [route for route in routes if _topic_matches_filter(topic, route.topic_filter)]
    if not matches:
        raise EnvelopeError("unknown_route", topic)
    if len(matches) > 1:
        raise EnvelopeError("ambiguous_route", topic)
    return matches[0]


def _validate_route(route: PublicationRoute) -> None:
    _parse_topic_filter(route.topic_filter)

    if not route.source_id:
        raise EnvelopeError("invalid_field", "source_id")

    for field_name, value in (
        ("source_application", route.source_application),
        ("site_id", route.site_id),
    ):
        if not ROUTE_ID_PATTERN.fullmatch(value):
            raise EnvelopeError("invalid_field", field_name)

    if route.wire_format not in _WIRE_FORMATS:
        raise EnvelopeError("invalid_field", "wire_format")

    if not route.allowed_schema_pairs:
        raise EnvelopeError("invalid_field", "allowed_schema_pairs")

    for pair in route.allowed_schema_pairs:
        _validate_schema_pair(pair)

    if route.wire_format == "raw":
        if route.default_schema_pair is None:
            raise EnvelopeError("missing_field", "default_schema_pair")
        if route.default_schema_pair not in route.allowed_schema_pairs:
            raise EnvelopeError("invalid_field", "default_schema_pair")
    elif route.default_schema_pair is not None and route.default_schema_pair not in route.allowed_schema_pairs:
        raise EnvelopeError("invalid_field", "default_schema_pair")

    if not isinstance(route.content_type, str) or not route.content_type:
        raise EnvelopeError("invalid_field", "content_type")

    if route.event_kind not in _EVENT_KINDS:
        raise EnvelopeError("invalid_field", "event_kind")

    if not isinstance(route.archive_eligible, bool):
        raise EnvelopeError("invalid_field", "archive_eligible")


def _validate_schema_pair(pair: SchemaPair) -> None:
    for field_name, value in (
        ("payload_schema_id", pair.payload_schema_id),
        ("payload_schema_version", pair.payload_schema_version),
    ):
        if not ROUTE_ID_PATTERN.fullmatch(value):
            raise EnvelopeError("invalid_field", field_name)


def _parse_topic_filter(topic_filter: str) -> list[str]:
    if not topic_filter:
        raise EnvelopeError("invalid_topic_filter", "empty")

    if topic_filter.startswith("$"):
        raise EnvelopeError("invalid_topic_filter", "dollar_root")

    segments = topic_filter.split("/")
    for index, segment in enumerate(segments):
        if not segment:
            raise EnvelopeError("invalid_topic_filter", "empty_segment")
        if "+" in segment and segment != "+":
            raise EnvelopeError("invalid_topic_filter", "embedded_plus")
        if "#" in segment and segment != "#":
            raise EnvelopeError("invalid_topic_filter", "embedded_hash")
        if segment == "#" and index != len(segments) - 1:
            raise EnvelopeError("invalid_topic_filter", "embedded_hash")

    if segments[0] in {"+", "#"}:
        raise EnvelopeError("invalid_topic_filter", "dollar_root_wildcard")

    return segments


def _topic_matches_filter(topic: str, topic_filter: str) -> bool:
    topic_segments = topic.split("/") if topic else [""]
    filter_segments = _parse_topic_filter(topic_filter)
    return _segments_match(topic_segments, filter_segments, topic_index=0, filter_index=0)


def _segments_match(
    topic_segments: list[str],
    filter_segments: list[str],
    *,
    topic_index: int,
    filter_index: int,
) -> bool:
    if filter_index >= len(filter_segments):
        return topic_index >= len(topic_segments)

    filter_segment = filter_segments[filter_index]
    if filter_segment == "#":
        return True

    if topic_index >= len(topic_segments):
        return False

    topic_segment = topic_segments[topic_index]
    if filter_segment == "+":
        return _segments_match(
            topic_segments,
            filter_segments,
            topic_index=topic_index + 1,
            filter_index=filter_index + 1,
        )

    if filter_segment != topic_segment:
        return False

    return _segments_match(
        topic_segments,
        filter_segments,
        topic_index=topic_index + 1,
        filter_index=filter_index + 1,
    )


def _filters_overlap(left: list[str], right: list[str]) -> bool:
    return _segments_overlap(left, right, left_index=0, right_index=0)


def _segments_overlap(
    left: list[str],
    right: list[str],
    *,
    left_index: int,
    right_index: int,
) -> bool:
    if left_index >= len(left) and right_index >= len(right):
        return True

    if left_index >= len(left):
        return right and right[-1] == "#"

    if right_index >= len(right):
        return left and left[-1] == "#"

    left_segment = left[left_index]
    right_segment = right[right_index]

    if left_segment == "#" or right_segment == "#":
        return True

    if left_segment == "+" or right_segment == "+":
        return _segments_overlap(left, right, left_index=left_index + 1, right_index=right_index + 1)

    if left_segment != right_segment:
        return False

    return _segments_overlap(left, right, left_index=left_index + 1, right_index=right_index + 1)
