"""Contract tests for immutable MQTT route releases and the activation barrier."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uns_config.publication_routes import PublicationRoute, SchemaPair
from uns_config.route_release import (
    ActivationSnapshot,
    ComponentActivation,
    PrincipalGrant,
    RouteRelease,
    RouteReleaseError,
    advance_activation,
    can_release_edge_configuration,
    is_stale_activation_report,
    mapper_topic_filters,
    route_release_digest,
    route_release_from_dict,
    validate_route_release,
)


def _route(**overrides) -> PublicationRoute:
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


def _grant(**overrides) -> PrincipalGrant:
    defaults = {
        "principal_id": "edge-01-bridge",
        "publish_filters": ("Enterprise/PlantA/LIMS/results",),
        "deny_subscribe": True,
    }
    defaults.update(overrides)
    return PrincipalGrant(**defaults)


def _release(revision: int = 1, **overrides) -> RouteRelease:
    routes = overrides.pop("publication_routes", (_route(),))
    grants = overrides.pop("principal_grants", (_grant(),))
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
                        "payload_schema_id": pair.payload_schema_id,
                        "payload_schema_version": pair.payload_schema_version,
                    }
                    for pair in route.allowed_schema_pairs
                ],
                "default_schema_pair": (
                    {
                        "payload_schema_id": route.default_schema_pair.payload_schema_id,
                        "payload_schema_version": route.default_schema_pair.payload_schema_version,
                    }
                    if route.default_schema_pair is not None
                    else None
                ),
                "content_type": route.content_type,
                "event_kind": route.event_kind,
                "archive_eligible": route.archive_eligible,
            }
            for route in routes
        ],
        "principal_grants": [
            {
                "principal_id": grant.principal_id,
                "publish_filters": list(grant.publish_filters),
                "deny_subscribe": grant.deny_subscribe,
            }
            for grant in grants
        ],
    }
    payload.update(overrides)
    payload["digest"] = route_release_digest(payload)
    return route_release_from_dict(payload)


def test_route_release_digest_is_stable_and_excludes_only_top_level_digest():
    release = _release()
    payload = {
        "revision": release.revision,
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
                "publish_filters": ["Enterprise/PlantA/LIMS/results"],
                "deny_subscribe": True,
            }
        ],
    }
    assert route_release_digest(payload) == release.digest


def test_overlapping_filters_fail_validation():
    with pytest.raises(RouteReleaseError, match="ambiguous_route"):
        _release(
            publication_routes=(
                _route(topic_filter="E/S/+/results"),
                _route(topic_filter="E/S/LIMS/#"),
            ),
            principal_grants=(_grant(publish_filters=("E/S/+/results",)),),
        )


def test_bad_digest_rejected():
    release = _release()
    with pytest.raises(RouteReleaseError, match="digest_mismatch"):
        validate_route_release(release, expected_digest="deadbeef")


def test_mapper_topic_filters_are_derived_from_publication_routes():
    release = _release(
        publication_routes=(
            _route(topic_filter="Enterprise/PlantA/LIMS/results"),
            _route(
                topic_filter="Enterprise/PlantA/MES/orders",
                source_application="mes",
                allowed_schema_pairs=frozenset(
                    {SchemaPair(payload_schema_id="production-order", payload_schema_version="1")}
                ),
            ),
        )
    )
    assert mapper_topic_filters(release) == (
        "Enterprise/PlantA/LIMS/results",
        "Enterprise/PlantA/MES/orders",
    )


def test_activation_barrier_advances_mapper_then_broker_then_active():
    release = _release()
    snapshot = ActivationSnapshot(
        release_revision=release.revision,
        release_digest=release.digest,
        phase="pending",
        mapper=None,
        broker=None,
        drain_until_revision=None,
    )
    snapshot = advance_activation(snapshot, release, mapper_revision=release.revision)
    assert snapshot.phase == "activating_broker"
    assert snapshot.mapper is not None
    assert snapshot.mapper.revision == release.revision

    snapshot = advance_activation(snapshot, release, broker_revision=release.revision)
    assert snapshot.phase == "active"
    assert snapshot.broker is not None
    assert snapshot.broker.revision == release.revision


def test_half_activated_release_waits_when_broker_unavailable():
    release = _release()
    snapshot = ActivationSnapshot(
        release_revision=release.revision,
        release_digest=release.digest,
        phase="activating_broker",
        mapper=ComponentActivation(
            revision=release.revision,
            digest=release.digest,
            activated_at=datetime(2026, 9, 12, tzinfo=UTC),
            reported_at=datetime(2026, 9, 12, tzinfo=UTC),
        ),
        broker=None,
        drain_until_revision=None,
    )
    snapshot = advance_activation(snapshot, release, broker_revision=None, broker_available=False)
    assert snapshot.phase == "waiting_for_routes"
    assert not can_release_edge_configuration(snapshot, release.revision)


def test_late_activation_report_is_stale():
    assert is_stale_activation_report(reported_revision=1, active_revision=2)
    assert not is_stale_activation_report(reported_revision=2, active_revision=2)


def test_resumed_activation_after_restart_continues_from_mapper_phase():
    release = _release(revision=3)
    snapshot = ActivationSnapshot(
        release_revision=release.revision,
        release_digest=release.digest,
        phase="activating_mapper",
        mapper=None,
        broker=None,
        drain_until_revision=2,
    )
    snapshot = advance_activation(snapshot, release, mapper_revision=release.revision)
    assert snapshot.phase == "activating_broker"
    snapshot = advance_activation(snapshot, release, broker_revision=release.revision)
    assert snapshot.phase == "active"
    assert can_release_edge_configuration(snapshot, release.revision)


def test_edge_configuration_blocked_until_active_release_matches():
    release = _release(revision=4)
    active = ActivationSnapshot(
        release_revision=release.revision,
        release_digest=release.digest,
        phase="active",
        mapper=ComponentActivation(release.revision, release.digest, None, None),
        broker=ComponentActivation(release.revision, release.digest, None, None),
        drain_until_revision=None,
    )
    assert can_release_edge_configuration(active, release.revision)
    assert not can_release_edge_configuration(active, release.revision + 1)
