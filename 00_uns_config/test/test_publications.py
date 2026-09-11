"""Contract tests for the explicit publisher wire wrapper."""

from __future__ import annotations

import base64
import json

import pytest

from uns_config.events import EnvelopeError
from uns_config.publication_routes import PublicationRoute, SchemaPair
from uns_config.publications import (
    decode_publication,
    resolve_publisher_message,
    validate_publisher_message,
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


def _wrapper_bytes(**overrides) -> bytes:
    payload = {
        "publication_version": 1,
        "source_application": "lims",
        "site_id": "plant-01",
        "payload_schema_id": "lab-result",
        "payload_schema_version": "1",
        "content_type": "application/json",
        "original_payload_base64": base64.b64encode(b'{"result": 4.2}').decode("ascii"),
        "occurred_at": "2026-09-11T09:00:00Z",
        "source_boot_id": "lims-session-1",
        "source_sequence": 42,
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def test_decode_publication_round_trip(route):
    wire = _wrapper_bytes()
    message = decode_publication(wire)
    assert message.source_application == "lims"
    assert message.site_id == "plant-01"
    assert message.payload_schema_id == "lab-result"
    assert message.payload_schema_version == "1"
    assert message.original_payload == b'{"result": 4.2}'
    assert message.source_boot_id == "lims-session-1"
    assert message.source_sequence == 42
    validate_publisher_message(message, route())


def test_unsupported_wrapper_version():
    wire = _wrapper_bytes(publication_version=2)
    with pytest.raises(EnvelopeError, match="unsupported_publication_version"):
        decode_publication(wire)


def test_schema_pair_mismatch(route):
    message = decode_publication(_wrapper_bytes(payload_schema_id="other-schema"))
    with pytest.raises(EnvelopeError, match="schema_pair_mismatch"):
        validate_publisher_message(message, route())


def test_forged_application(route):
    message = decode_publication(_wrapper_bytes(source_application="mes"))
    with pytest.raises(EnvelopeError, match="forged_application"):
        validate_publisher_message(message, route())


def test_forged_site(route):
    message = decode_publication(_wrapper_bytes(site_id="plant-99"))
    with pytest.raises(EnvelopeError, match="forged_site"):
        validate_publisher_message(message, route())


def test_valid_shared_scope(route):
    shared = route(
        topic_filter="Enterprise/shared/inventory",
        source_application="enterprise",
        site_id="shared",
        allowed_schema_pairs=frozenset(
            {SchemaPair(payload_schema_id="inventory-movement", payload_schema_version="1")}
        ),
    )
    wire = _wrapper_bytes(
        source_application="enterprise",
        site_id="shared",
        payload_schema_id="inventory-movement",
        payload_schema_version="1",
        original_payload_base64=base64.b64encode(b'{"sku":"ABC"}').decode("ascii"),
    )
    message = decode_publication(wire)
    validate_publisher_message(message, shared)


def test_literal_business_json_configured_as_raw(route):
    envelope_like = json.dumps(
        {
            "publication_version": 1,
            "source_application": "lims",
            "site_id": "plant-01",
            "payload_schema_id": "lab-result",
            "payload_schema_version": "1",
            "content_type": "application/json",
            "original_payload_base64": base64.b64encode(b'{"result": 4.2}').decode("ascii"),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    raw_route = route(
        wire_format="raw",
        default_schema_pair=SchemaPair(payload_schema_id="lab-result", payload_schema_version="1"),
    )
    message = resolve_publisher_message(envelope_like, raw_route)
    assert message.original_payload == envelope_like
    assert message.source_application == "lims"
    assert message.payload_schema_id == "lab-result"
    assert message.payload_schema_version == "1"


def test_partial_source_identity_rejected():
    with pytest.raises(EnvelopeError, match="source_identity"):
        decode_publication(_wrapper_bytes(source_sequence=None, source_boot_id="only-boot"))
