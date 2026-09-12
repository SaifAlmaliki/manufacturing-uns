"""Deterministic load fixture and reconciliation helpers for pipeline qualification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from uns_config.events import source_event_id


@dataclass(frozen=True, slots=True)
class SourcePublication:
    """One expected source-identified publication in the qualification manifest."""

    site_id: str
    source_id: str
    source_boot_id: str
    source_sequence: int
    topic: str
    payload: dict[str, Any]
    expected_event_id: str

    @classmethod
    def build(
        cls,
        *,
        site_id: str,
        source_id: str,
        source_boot_id: str,
        source_sequence: int,
        topic: str,
        value: float,
        timestamp_ms: int,
    ) -> SourcePublication:
        payload = {"value": value, "timestamp": timestamp_ms}
        return cls(
            site_id=site_id,
            source_id=source_id,
            source_boot_id=source_boot_id,
            source_sequence=source_sequence,
            topic=topic,
            payload=payload,
            expected_event_id=source_event_id(site_id, source_id, source_boot_id, source_sequence),
        )


@dataclass(frozen=True, slots=True)
class PipelineManifest:
    """Expected publications for a deterministic qualification run."""

    boot_id: str
    sites: int
    topics: int
    publications: tuple[SourcePublication, ...]

    @property
    def expected_source_receipts(self) -> int:
        return len(self.publications)

    @property
    def expected_kafka_accepted(self) -> int:
        return len(self.publications)

    @property
    def manifest_digest(self) -> str:
        wire = json.dumps(
            [
                {
                    "topic": item.topic,
                    "event_id": item.expected_event_id,
                    "sequence": item.source_sequence,
                }
                for item in self.publications
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(wire).hexdigest()


@dataclass(slots=True)
class PipelineCounters:
    """Observed counts from each pipeline stage."""

    source_receipts: int = 0
    kafka_accepted: int = 0
    dlq_records: int = 0
    sql_event_ids: int = 0
    archived_ids: int = 0


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    ok: bool
    missing_kafka: int
    extra_kafka: int
    missing_sql: int
    extra_sql: int
    missing_archive: int
    extra_archive: int
    dlq_records: int

    def summary(self) -> str:
        if self.ok:
            return "reconciled"
        return (
            f"missing_kafka={self.missing_kafka} extra_kafka={self.extra_kafka} "
            f"missing_sql={self.missing_sql} extra_sql={self.extra_sql} "
            f"missing_archive={self.missing_archive} extra_archive={self.extra_archive} "
            f"dlq_records={self.dlq_records}"
        )


def generate_fixture(
    *,
    sites: int,
    topics: int,
    boot_id: str = "acceptance-boot",
    start_time: datetime | None = None,
) -> PipelineManifest:
    """Build a deterministic manifest across sites and topics."""
    if sites < 1:
        raise ValueError("sites must be at least 1")
    if topics < 1:
        raise ValueError("topics must be at least 1")

    start = start_time or datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    publications: list[SourcePublication] = []
    sequence = 0
    for site_index in range(sites):
        site_id = f"site-{site_index + 1}"
        source_id = f"{site_id}/gateway-01"
        for topic_index in range(topics):
            topic = f"Enterprise/{site_id}/Line/Device-{topic_index + 1}/Temperature"
            timestamp_ms = int((start + timedelta(milliseconds=sequence)).timestamp() * 1000)
            publications.append(
                SourcePublication.build(
                    site_id=site_id,
                    source_id=source_id,
                    source_boot_id=boot_id,
                    source_sequence=sequence,
                    topic=topic,
                    value=float(topic_index + 1),
                    timestamp_ms=timestamp_ms,
                )
            )
            sequence += 1
    return PipelineManifest(
        boot_id=boot_id,
        sites=sites,
        topics=topics,
        publications=tuple(publications),
    )


def reconcile_manifest(
    manifest: PipelineManifest,
    *,
    observed_kafka_event_ids: set[str],
    observed_sql_event_ids: set[str],
    observed_archive_event_ids: set[str],
    counters: PipelineCounters | None = None,
) -> ReconciliationResult:
    """Compare observed stage outputs against the deterministic manifest."""
    expected = {item.expected_event_id for item in manifest.publications}
    missing_kafka = len(expected - observed_kafka_event_ids)
    extra_kafka = len(observed_kafka_event_ids - expected)
    missing_sql = len(expected - observed_sql_event_ids)
    extra_sql = len(observed_sql_event_ids - expected)
    missing_archive = len(expected - observed_archive_event_ids)
    extra_archive = len(observed_archive_event_ids - expected)
    dlq_records = counters.dlq_records if counters is not None else 0
    ok = (
        missing_kafka == 0
        and extra_kafka == 0
        and missing_sql == 0
        and extra_sql == 0
        and missing_archive == 0
        and extra_archive == 0
        and dlq_records == 0
    )
    return ReconciliationResult(
        ok=ok,
        missing_kafka=missing_kafka,
        extra_kafka=extra_kafka,
        missing_sql=missing_sql,
        extra_sql=extra_sql,
        missing_archive=missing_archive,
        extra_archive=extra_archive,
        dlq_records=dlq_records,
    )


def validate_report_parent(report_path: Path) -> None:
    """Ensure the report parent exists before writing qualification output."""
    parent = report_path.parent
    if not parent.exists() or not parent.is_dir():
        raise FileNotFoundError(f"report parent directory does not exist: {parent}")


@dataclass(slots=True)
class LoadReport:
    """JSON-serializable benchmark report payload."""

    sites: int
    topics: int
    rate: float
    seconds: float
    burst_rate: float | None
    burst_seconds: float | None
    manifest_digest: str
    source_receipts: int
    counters: PipelineCounters = field(default_factory=PipelineCounters)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sites": self.sites,
            "topics": self.topics,
            "rate": self.rate,
            "seconds": self.seconds,
            "burst_rate": self.burst_rate,
            "burst_seconds": self.burst_seconds,
            "manifest_digest": self.manifest_digest,
            "source_receipts": self.source_receipts,
            "counters": {
                "source_receipts": self.counters.source_receipts,
                "kafka_accepted": self.counters.kafka_accepted,
                "dlq_records": self.counters.dlq_records,
                "sql_event_ids": self.counters.sql_event_ids,
                "archived_ids": self.counters.archived_ids,
            },
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
