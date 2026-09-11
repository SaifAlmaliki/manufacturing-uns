"""Contract tests for registered MQTT publication routes."""

from __future__ import annotations

import pytest

from uns_config.events import EnvelopeError
from uns_config.publication_routes import (
    PublicationRoute,
    SchemaPair,
    resolve_route,
    validate_routes,
)


@pytest.fixture
def route():
    def _factory(**overrides) -> PublicationRoute:
        defaults = {
            "topic_filter": "Enterprise/PlantA/LIMS/results",
            "source_id": "plant-a/lims-01",
            "source_application": "lims",
            "site_id": "plant-01",
            "wire_format": "uns-publication-v1",
            "allowed_schema_pairs": frozenset(
                {SchemaPair(payload_schema_id="lab-result", payload_schema_version="1")}
            ),
            "default_schema_pair": None,
            "content_type": "application/json",
            "event_kind": "business_event",
            "archive_eligible": True,
        }
        defaults.update(overrides)
        return PublicationRoute(**defaults)

    return _factory


def test_disjoint_filters_pass_validation(route):
    validate_routes(
        [
            route(topic_filter="Enterprise/PlantA/LIMS/results"),
            route(
                topic_filter="Enterprise/PlantA/MES/orders",
                source_application="mes",
                allowed_schema_pairs=frozenset(
                    {SchemaPair(payload_schema_id="production-order", payload_schema_version="1")}
                ),
            ),
        ]
    )


def test_overlapping_filters_fail_startup(route):
    with pytest.raises(EnvelopeError, match="ambiguous_route"):
        validate_routes(
            [
                route(topic_filter="E/S/+/results"),
                route(topic_filter="E/S/LIMS/#"),
            ]
        )


def test_duplicate_filters_fail_startup(route):
    with pytest.raises(EnvelopeError, match="ambiguous_route"):
        validate_routes(
            [
                route(topic_filter="Enterprise/PlantA/LIMS/results"),
                route(topic_filter="Enterprise/PlantA/LIMS/results"),
            ]
        )


def test_mqtt_plus_and_hash_matching(route):
    routes = (
        route(topic_filter="Enterprise/+/LIMS/+"),
        route(
            topic_filter="Enterprise/PlantA/MES/orders",
            source_application="mes",
            allowed_schema_pairs=frozenset(
                {SchemaPair(payload_schema_id="production-order", payload_schema_version="1")}
            ),
        ),
    )
    validate_routes(routes)
    assert resolve_route("Enterprise/PlantA/LIMS/results", routes).source_application == "lims"
    assert resolve_route("Enterprise/PlantA/MES/orders", routes).source_application == "mes"


def test_terminal_hash_matches_zero_or_more_suffix_segments(route):
    routes = (route(topic_filter="Enterprise/PlantA/LIMS/#"),)
    validate_routes(routes)
    assert resolve_route("Enterprise/PlantA/LIMS/results", routes).topic_filter.endswith("#")
    assert resolve_route("Enterprise/PlantA/LIMS", routes).topic_filter.endswith("#")


@pytest.mark.parametrize(
    "topic_filter",
    [
        "Enterprise/foo+bar/results",
        "Enterprise/foo#bar",
        "Enterprise/#/results",
        "#/Enterprise",
        "+/Enterprise",
        "$SYS/broker/metrics",
    ],
)
def test_invalid_embedded_wildcards_fail(route, topic_filter):
    with pytest.raises(EnvelopeError, match="invalid_topic_filter"):
        validate_routes([route(topic_filter=topic_filter)])


def test_resolve_unknown_route(route):
    routes = (route(),)
    validate_routes(routes)
    with pytest.raises(EnvelopeError, match="unknown_route"):
        resolve_route("Enterprise/PlantB/LIMS/results", routes)


def test_raw_route_requires_default_schema_pair(route):
    with pytest.raises(EnvelopeError, match="default_schema_pair"):
        validate_routes(
            [
                route(
                    wire_format="raw",
                    default_schema_pair=None,
                )
            ]
        )


def test_invalid_route_id_rejected(route):
    with pytest.raises(EnvelopeError, match="invalid_field"):
        validate_routes([route(source_application="bad/id")])
