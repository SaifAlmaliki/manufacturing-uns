"""Tests for the authenticated mapper route-control endpoint."""

from __future__ import annotations

import json
from http.client import HTTPConnection

import pytest

from uns_config.publication_routes import PublicationRoute, SchemaPair
from uns_config.route_release import PrincipalGrant, RouteRelease, route_release_digest
from uns_kafka.route_control import RouteControlServer, RouteControlState


def _release(revision: int = 1) -> RouteRelease:
    route = PublicationRoute(
        topic_filter="Enterprise/PlantA/LIMS/results",
        source_id="plant-a/lims-01",
        source_application="lims",
        site_id="plant-01",
        wire_format="uns-publication-v1",
        allowed_schema_pairs=frozenset(
            {SchemaPair(payload_schema_id="lab-result", payload_schema_version="1")}
        ),
        default_schema_pair=None,
        content_type="application/json",
        event_kind="business_event",
        archive_eligible=True,
    )
    grant = PrincipalGrant(
        principal_id="edge-01-bridge",
        publish_filters=(route.topic_filter,),
        deny_subscribe=True,
    )
    payload = {
        "revision": revision,
        "publication_routes": [
            {
                "topic_filter": route.topic_filter,
                "source_id": route.source_id,
                "source_application": route.source_application,
                "site_id": route.site_id,
                "wire_format": route.wire_format,
                "allowed_schema_pairs": [
                    {
                        "payload_schema_id": "lab-result",
                        "payload_schema_version": "1",
                    }
                ],
                "default_schema_pair": None,
                "content_type": route.content_type,
                "event_kind": route.event_kind,
                "archive_eligible": route.archive_eligible,
            }
        ],
        "principal_grants": [
            {
                "principal_id": grant.principal_id,
                "publish_filters": list(grant.publish_filters),
                "deny_subscribe": grant.deny_subscribe,
            }
        ],
    }
    payload["digest"] = route_release_digest(payload)
    return RouteRelease(
        revision=revision,
        digest=payload["digest"],
        publication_routes=(route,),
        principal_grants=(grant,),
    )


@pytest.fixture
def route_server():
    state = RouteControlState()
    server = RouteControlServer(state, host="127.0.0.1", port=0, token="mapper-secret")
    server.start()
    try:
        yield server, state
    finally:
        server.stop()


def _request(server: RouteControlServer, method: str, path: str, body: dict | None = None):
    host, port = server.address
    connection = HTTPConnection(host, port, timeout=5)
    headers = {"Authorization": "Bearer mapper-secret"}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    parsed = json.loads(raw.decode("utf-8")) if raw else {}
    return response.status, parsed


def test_enqueue_and_activate_mapper_release(route_server):
    server, state = route_server
    release = _release()
    status, payload = _request(
        server,
        "POST",
        "/internal/route-control/v1/releases",
        {
            "revision": release.revision,
            "digest": release.digest,
            "publication_routes": [
                {
                    "topic_filter": release.publication_routes[0].topic_filter,
                    "source_id": release.publication_routes[0].source_id,
                    "source_application": release.publication_routes[0].source_application,
                    "site_id": release.publication_routes[0].site_id,
                    "wire_format": release.publication_routes[0].wire_format,
                    "allowed_schema_pairs": [
                        {
                            "payload_schema_id": "lab-result",
                            "payload_schema_version": "1",
                        }
                    ],
                    "default_schema_pair": None,
                    "content_type": "application/json",
                    "event_kind": "business_event",
                    "archive_eligible": True,
                }
            ],
            "principal_grants": [
                {
                    "principal_id": "edge-01-bridge",
                    "publish_filters": [release.publication_routes[0].topic_filter],
                    "deny_subscribe": True,
                }
            ],
        },
    )
    assert status == 202
    assert payload["queued_revision"] == release.revision
    activated = state.drain_pending()
    assert activated is not None
    assert activated.revision == release.revision
    state.apply_release(activated)
    status, active = _request(server, "GET", "/internal/route-control/v1/active")
    assert status == 200
    assert active["revision"] == release.revision


def test_stale_activation_report_rejected(route_server):
    server, state = route_server
    first = _release(revision=1)
    second = _release(revision=2)
    state.apply_release(second)
    status, payload = _request(
        server,
        "POST",
        "/internal/route-control/v1/activation-report",
        {"revision": first.revision, "digest": first.digest},
    )
    assert status == 409
    assert payload["error"] == "stale_activation_report"
    status, payload = _request(
        server,
        "POST",
        "/internal/route-control/v1/activation-report",
        {"revision": second.revision, "digest": second.digest},
    )
    assert status == 200
    assert payload["revision"] == second.revision
