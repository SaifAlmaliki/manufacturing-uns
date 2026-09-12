"""Immutable MQTT route releases and the activation barrier contract.

Pure contract code: no Kafka, MQTT, database, or cloud SDK imports.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from uns_config.events import EnvelopeError
from uns_config.publication_routes import (
    PublicationRoute,
    publication_route_from_dict,
    validate_routes,
)

ReleasePhase = Literal[
    "pending",
    "validating",
    "activating_mapper",
    "activating_broker",
    "verifying",
    "active",
    "failed",
    "waiting_for_routes",
    "draining",
]

RELEASE_PHASES: frozenset[str] = frozenset(
    {
        "pending",
        "validating",
        "activating_mapper",
        "activating_broker",
        "verifying",
        "active",
        "failed",
        "waiting_for_routes",
        "draining",
    }
)


class RouteReleaseError(Exception):
    """Stable route-release failure."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PrincipalGrant:
    principal_id: str
    publish_filters: tuple[str, ...]
    deny_subscribe: bool = True


@dataclass(frozen=True, slots=True)
class RouteRelease:
    revision: int
    digest: str
    publication_routes: tuple[PublicationRoute, ...]
    principal_grants: tuple[PrincipalGrant, ...]


@dataclass(frozen=True, slots=True)
class ComponentActivation:
    revision: int
    digest: str
    activated_at: datetime | None
    reported_at: datetime | None


@dataclass(frozen=True, slots=True)
class ActivationSnapshot:
    release_revision: int
    release_digest: str
    phase: ReleasePhase
    mapper: ComponentActivation | None
    broker: ComponentActivation | None
    drain_until_revision: int | None


def principal_grant_from_dict(raw: dict[str, Any]) -> PrincipalGrant:
    publish_filters = tuple(raw.get("publish_filters") or ())
    if not publish_filters:
        raise RouteReleaseError("invalid_field", "publish_filters")
    principal_id = raw.get("principal_id")
    if not isinstance(principal_id, str) or not principal_id:
        raise RouteReleaseError("invalid_field", "principal_id")
    return PrincipalGrant(
        principal_id=principal_id,
        publish_filters=publish_filters,
        deny_subscribe=bool(raw.get("deny_subscribe", True)),
    )


def route_release_from_dict(raw: dict[str, Any]) -> RouteRelease:
    revision = raw.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise RouteReleaseError("invalid_field", "revision")
    digest = raw.get("digest")
    if not isinstance(digest, str) or not digest:
        raise RouteReleaseError("missing_field", "digest")
    routes = tuple(publication_route_from_dict(entry) for entry in raw.get("publication_routes") or [])
    grants = tuple(principal_grant_from_dict(entry) for entry in raw.get("principal_grants") or [])
    release = RouteRelease(
        revision=revision,
        digest=digest,
        publication_routes=routes,
        principal_grants=grants,
    )
    validate_route_release(release)
    return release


def route_release_digest(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "digest"}
    canonical = _sort_json(payload)
    wire = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


def validate_route_release(release: RouteRelease, *, expected_digest: str | None = None) -> None:
    if expected_digest is not None and release.digest != expected_digest:
        raise RouteReleaseError("digest_mismatch", release.digest)
    computed = route_release_digest(
        {
            "revision": release.revision,
            "publication_routes": [_route_to_dict(route) for route in release.publication_routes],
            "principal_grants": [_grant_to_dict(grant) for grant in release.principal_grants],
        }
    )
    if release.digest != computed:
        raise RouteReleaseError("digest_mismatch", release.digest)
    try:
        validate_routes(release.publication_routes)
    except EnvelopeError as exc:
        raise RouteReleaseError(exc.reason, str(exc)) from exc
    _validate_principal_grants(release)


def mapper_topic_filters(release: RouteRelease) -> tuple[str, ...]:
    return tuple(route.topic_filter for route in release.publication_routes)


def advance_activation(
    snapshot: ActivationSnapshot,
    release: RouteRelease,
    *,
    mapper_revision: int | None = None,
    broker_revision: int | None = None,
    broker_available: bool = True,
    now: datetime | None = None,
) -> ActivationSnapshot:
    if snapshot.release_revision != release.revision or snapshot.release_digest != release.digest:
        raise RouteReleaseError("release_mismatch", str(release.revision))

    mapper = snapshot.mapper
    broker = snapshot.broker
    phase = snapshot.phase

    if phase in {"pending", "validating"}:
        phase = "activating_mapper"

    if phase == "activating_mapper" and mapper_revision == release.revision:
        mapper = ComponentActivation(
            revision=release.revision,
            digest=release.digest,
            activated_at=now,
            reported_at=now,
        )
        phase = "activating_broker"

    if phase == "activating_broker":
        if mapper is None or mapper.revision != release.revision:
            phase = "activating_mapper"
        elif broker_revision == release.revision:
            broker = ComponentActivation(
                revision=release.revision,
                digest=release.digest,
                activated_at=now,
                reported_at=now,
            )
            phase = "active"
        elif not broker_available:
            phase = "waiting_for_routes"

    if phase == "waiting_for_routes" and broker_revision == release.revision:
        broker = ComponentActivation(
            revision=release.revision,
            digest=release.digest,
            activated_at=now,
            reported_at=now,
        )
        phase = "active"

    return ActivationSnapshot(
        release_revision=snapshot.release_revision,
        release_digest=snapshot.release_digest,
        phase=phase,
        mapper=mapper,
        broker=broker,
        drain_until_revision=snapshot.drain_until_revision,
    )


def can_release_edge_configuration(snapshot: ActivationSnapshot, required_revision: int) -> bool:
    if snapshot.phase != "active":
        return False
    if snapshot.mapper is None or snapshot.broker is None:
        return False
    if snapshot.mapper.revision != required_revision or snapshot.broker.revision != required_revision:
        return False
    return snapshot.release_revision >= required_revision


def is_stale_activation_report(*, reported_revision: int, active_revision: int) -> bool:
    return reported_revision < active_revision


def _validate_principal_grants(release: RouteRelease) -> None:
    route_filters = {route.topic_filter for route in release.publication_routes}
    seen_principals: set[str] = set()
    for grant in release.principal_grants:
        if grant.principal_id in seen_principals:
            raise RouteReleaseError("duplicate_principal", grant.principal_id)
        seen_principals.add(grant.principal_id)
        for publish_filter in grant.publish_filters:
            if publish_filter not in route_filters:
                raise RouteReleaseError("unknown_publish_filter", publish_filter)


def _route_to_dict(route: PublicationRoute) -> dict[str, Any]:
    return {
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


def _grant_to_dict(grant: PrincipalGrant) -> dict[str, Any]:
    return {
        "principal_id": grant.principal_id,
        "publish_filters": list(grant.publish_filters),
        "deny_subscribe": grant.deny_subscribe,
    }


def _sort_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    return value
