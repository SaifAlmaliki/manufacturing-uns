"""Frozen lake routing and legacy provenance resolution."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date
from typing import Literal

from uns_config.events import EnvelopeError, HistoricEventEnvelope

PayloadFidelity = Literal["original", "legacy_normalized"]
LAKE_PREFIX_V2 = "raw/v2"
LegacyRouteKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class LakeRoute:
    application: str
    site: str
    schema: str
    version: str
    ingestion_date: date


@dataclass(frozen=True, slots=True)
class LegacyRouteEntry:
    application: str
    schema: str
    version: str


@dataclass(frozen=True, slots=True)
class LegacyRouteMap:
    revision: str
    content_digest: str
    routes: dict[LegacyRouteKey, LegacyRouteEntry]

    def __post_init__(self) -> None:
        expected = compute_legacy_map_digest(self.revision, self.routes)
        if expected != self.content_digest:
            raise EnvelopeError("legacy_map_digest_mismatch")


@dataclass(frozen=True, slots=True)
class ResolvedLakeEvent:
    envelope: HistoricEventEnvelope
    route: LakeRoute
    original_payload: bytes | None
    payload_fidelity: PayloadFidelity
    legacy_route_revision: str | None


@dataclass(frozen=True, slots=True)
class LakeRecord:
    kafka_topic: str
    partition: int
    offset: int
    resolved: ResolvedLakeEvent
    envelope_bytes: bytes

    @property
    def envelope(self) -> HistoricEventEnvelope:
        return self.resolved.envelope

    @property
    def partition_key(self) -> tuple[str, int]:
        return (self.kafka_topic, self.partition)


def compute_legacy_map_digest(revision: str, routes: dict[LegacyRouteKey, LegacyRouteEntry]) -> str:
    canonical = {
        "revision": revision,
        "routes": [
            {
                "topic": topic,
                "source_id": source_id,
                "site_id": site_id,
                "application": entry.application,
                "schema": entry.schema,
                "version": entry.version,
            }
            for (topic, source_id, site_id), entry in sorted(routes.items())
        ],
    }
    wire = json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


def build_legacy_route_map(revision: str, routes: dict[LegacyRouteKey, LegacyRouteEntry]) -> LegacyRouteMap:
    return LegacyRouteMap(
        revision=revision,
        content_digest=compute_legacy_map_digest(revision, routes),
        routes=routes,
    )


def _ingestion_date(envelope: HistoricEventEnvelope) -> date:
    return envelope.received_at.astimezone(UTC).date()


def _resolve_v2(envelope: HistoricEventEnvelope) -> ResolvedLakeEvent:
    if envelope.source_application is None:
        raise EnvelopeError("missing_field", "source_application")
    if envelope.payload_schema_id is None:
        raise EnvelopeError("missing_field", "payload_schema_id")
    if envelope.payload_schema_version is None:
        raise EnvelopeError("missing_field", "payload_schema_version")

    route = LakeRoute(
        application=envelope.source_application,
        site=envelope.site_id,
        schema=envelope.payload_schema_id,
        version=envelope.payload_schema_version,
        ingestion_date=_ingestion_date(envelope),
    )
    return ResolvedLakeEvent(
        envelope=envelope,
        route=route,
        original_payload=envelope.original_payload,
        payload_fidelity="original",
        legacy_route_revision=None,
    )


def _resolve_v1(envelope: HistoricEventEnvelope, legacy_map: LegacyRouteMap) -> ResolvedLakeEvent:
    key: LegacyRouteKey = (envelope.topic, envelope.source_id, envelope.site_id)
    entry = legacy_map.routes.get(key)
    if entry is None:
        raise EnvelopeError("missing_legacy_route")

    if envelope.raw_payload_base64:
        try:
            original_payload = base64.b64decode(envelope.raw_payload_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise EnvelopeError("invalid_field", "raw_payload_base64") from exc
        payload_fidelity: PayloadFidelity = "original"
    else:
        original_payload = None
        payload_fidelity = "legacy_normalized"

    route = LakeRoute(
        application=entry.application,
        site=envelope.site_id,
        schema=entry.schema,
        version=entry.version,
        ingestion_date=_ingestion_date(envelope),
    )
    return ResolvedLakeEvent(
        envelope=envelope,
        route=route,
        original_payload=original_payload,
        payload_fidelity=payload_fidelity,
        legacy_route_revision=legacy_map.revision,
    )


def resolve_lake_event(
    envelope: HistoricEventEnvelope,
    legacy_map: LegacyRouteMap | None,
) -> ResolvedLakeEvent:
    if envelope.schema_version == 2:
        return _resolve_v2(envelope)
    if envelope.schema_version == 1:
        if legacy_map is None:
            raise EnvelopeError("missing_legacy_route")
        return _resolve_v1(envelope, legacy_map)
    raise EnvelopeError("unsupported_schema")


def lake_object_path(route: LakeRoute, object_id: str) -> str:
    filename = object_id if object_id.endswith(".parquet") else f"{object_id}.parquet"
    return (
        f"{LAKE_PREFIX_V2}/"
        f"application={route.application}/"
        f"site={route.site}/"
        f"schema={route.schema}/"
        f"version={route.version}/"
        f"ingestion_date={route.ingestion_date.isoformat()}/"
        f"{filename}"
    )
