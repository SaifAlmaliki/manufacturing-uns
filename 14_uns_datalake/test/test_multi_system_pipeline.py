"""Four-domain acceptance and fault-matrix qualification for UNS-to-lake delivery.

Integration prerequisites
---------------------------

The ``pipeline`` fixture requires a live stack with:

1. **MQTT** — ``mqtt.host`` configured and reachable (HiveMQ Edge or equivalent).
2. **Kafka** — bootstrap broker reachable; topic ``uns.historic-events`` exists.
3. **MinIO/S3** — datalake backend configured and reachable.
4. **Publication routes** — four representative domains registered in
   ``conf/settings.yaml`` under ``kafka_mapper.ingestion.publication_routes``.
5. **v2 writer** — ``ingestion.v2_publications_enabled: true`` for acceptance runs
   (disabled by default until reader-first rollout completes).

Missing services must skip with ``blocked:`` reasons, not pass silently.

Live fault injection (store outage, kill-after-upload, rebalance, ADLS staging)
requires orchestrated stack control documented in
``docs/benchmarks/uns-to-lake-delivery.md``. Unit and contract tests below map
each fault to automated evidence; integration rows remain blocked until an
operator executes the manual scenario and records results in the benchmark report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pytest

from conftest import (
    LAKE_PREFIX_V2,
    PublicationCase,
    _require_pipeline_stack,
    _route_from_object_key,
)

QualificationStatus = Literal["unit", "integration", "manual", "not_qualified"]


@dataclass(frozen=True, slots=True)
class FaultMatrixEntry:
    """One row in the UNS-to-lake acceptance fault matrix."""

    scenario: str
    invariant: str
    unit_tests: tuple[str, ...]
    qualification: QualificationStatus


def kafka_coordinate(row: dict[str, Any]) -> tuple[str, int, int] | None:
    """Return the transport coordinate that identifies duplicate delivery."""
    topic = row.get("kafka_topic")
    partition = row.get("kafka_partition")
    offset = row.get("kafka_offset")
    if topic is None or partition is None or offset is None:
        return None
    return (str(topic), int(partition), int(offset))


def rows_for_event_id(rows: list[dict[str, Any]], event_id: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("event_id") == event_id]


def duplicate_kafka_coordinates(rows: list[dict[str, Any]]) -> dict[tuple[str, int, int], int]:
    """Count physical rows per Kafka coordinate (replay duplicates share coordinates)."""
    counts: dict[tuple[str, int, int], int] = {}
    for row in rows:
        coordinate = kafka_coordinate(row)
        if coordinate is None:
            continue
        counts[coordinate] = counts.get(coordinate, 0) + 1
    return {coordinate: count for coordinate, count in counts.items() if count > 1}


def assert_lake_evidence(
    rows: list[dict[str, Any]],
    expected: dict[str, PublicationCase],
) -> None:
    """Verify four-domain acceptance evidence: body bytes, route tuple, and coordinates."""
    for event_id, case in expected.items():
        matches = rows_for_event_id(rows, event_id)
        assert matches, f"missing lake rows for event_id={event_id}"
        assert all(row.get("original_payload") == case.body for row in matches)
        assert all(row.get("route") == case.route for row in matches)
        for row in matches:
            key = row.get("object_key", "")
            if key.startswith(LAKE_PREFIX_V2):
                assert _route_from_object_key(key) == case.route


def fault_matrix() -> tuple[FaultMatrixEntry, ...]:
    """Full acceptance matrix from the multi-system UNS-to-lake plan (Task 12)."""
    return (
        FaultMatrixEntry(
            scenario="historian_stopped_throughout",
            invariant="Four domains archive without SQL/Metric dependency.",
            unit_tests=(
                "test_four_domains_reach_lake_with_historian_stopped",
            ),
            qualification="integration",
        ),
        FaultMatrixEntry(
            scenario="store_stopped_during_second_route_upload",
            invariant="Earlier objects remain; no unsafe commit; recovery includes every expected coordinate.",
            unit_tests=(
                "14_uns_datalake/test/test_multi_route_mapper.py::test_multi_route_flush_resolves_lims_before_mes_and_commits_after_both",
                "14_uns_datalake/test/test_mapper.py::test_upload_failure_after_retries_does_not_commit",
            ),
            qualification="manual",
        ),
        FaultMatrixEntry(
            scenario="kill_after_upload_before_commit",
            invariant="Replay may duplicate rows; identical Kafka coordinates identify repeated delivery.",
            unit_tests=(
                "14_uns_datalake/test/test_mapper.py::test_duplicate_event_ids_survive_replay_in_separate_files",
                "test_kafka_coordinate_identifies_duplicate_delivery",
            ),
            qualification="manual",
        ),
        FaultMatrixEntry(
            scenario="rebalance_during_delayed_upload",
            invariant="Old generation cannot commit; new owner completes unresolved work.",
            unit_tests=(
                "14_uns_datalake/test/test_multi_route_mapper.py::test_ownership_revoked_during_flush_does_not_commit",
                "14_uns_datalake/test/test_mapper.py::test_revoked_owner_does_not_commit_after_upload",
            ),
            qualification="manual",
        ),
        FaultMatrixEntry(
            scenario="dlq_timeout_or_failure",
            invariant="No rejection is checkpointed without acknowledged delivery.",
            unit_tests=(
                "14_uns_datalake/test/test_multi_route_mapper.py::test_dlq_unavailable_does_not_resolve_or_commit",
                "14_uns_datalake/test/test_mapper.py::test_malformed_envelope_goes_to_dlq_before_commit",
            ),
            qualification="unit",
        ),
        FaultMatrixEntry(
            scenario="existing_key_different_content",
            invariant="No overwrite; integrity readiness fails.",
            unit_tests=(
                "14_uns_datalake/test/test_publication.py::test_existing_mismatch_is_not_overwritten",
            ),
            qualification="unit",
        ),
        FaultMatrixEntry(
            scenario="partial_adls_staging_upload",
            invariant="No partial final .parquet object; separate live-Azure evidence.",
            unit_tests=(
                "14_uns_datalake/test/test_publication.py::test_adls_staging_key_is_outside_raw_v2",
                "14_uns_datalake/test/test_publication.py::test_adls_unsupported_finalize_fails_readiness",
            ),
            qualification="not_qualified",
        ),
        FaultMatrixEntry(
            scenario="committed_offset_older_than_retained_log",
            invariant="Explicit data-gap failure rather than auto-reset success.",
            unit_tests=(
                "14_uns_datalake/test/test_replay.py::test_committed_before_retained_low_is_data_gap_even_with_earliest",
            ),
            qualification="unit",
        ),
        FaultMatrixEntry(
            scenario="two_schema_versions_two_sites_two_applications",
            invariant="Exact intended paths with original body bytes and full provenance.",
            unit_tests=(
                "14_uns_datalake/test/test_routing.py::test_two_sites_route_separately",
                "14_uns_datalake/test/test_routing.py::test_two_applications_route_separately",
                "14_uns_datalake/test/test_routing.py::test_two_schema_versions_route_separately",
                "14_uns_datalake/test/test_parquet_v2.py::test_v2_parquet_round_trip_preserves_original_payload_bytes",
            ),
            qualification="unit",
        ),
        FaultMatrixEntry(
            scenario="legacy_map_or_live_registration_changed",
            invariant="V2 routing unchanged; v1 map digest change refused unless explicit new replay decision.",
            unit_tests=(
                "14_uns_datalake/test/test_routing.py::test_v2_route_ignores_changed_live_registration",
                "14_uns_datalake/test/test_routing.py::test_legacy_map_digest_mismatch_is_refused",
            ),
            qualification="unit",
        ),
        FaultMatrixEntry(
            scenario="many_small_routes_near_limit_records",
            invariant="Application and encoded buffers remain bounded; record RSS/scratch overhead.",
            unit_tests=(
                "14_uns_datalake/test/test_multi_route_batch.py::test_sixty_fifth_route_group_triggers_pressure",
                "14_uns_datalake/test/test_multi_route_batch.py::test_batch_byte_budget_blocks_admission",
            ),
            qualification="unit",
        ),
        FaultMatrixEntry(
            scenario="retained_bootstrap_and_fresh_retained_publication",
            invariant="Bootstrap not duplicated as history; live eligible publication delivered.",
            unit_tests=(
                "06_uns_kafka/test/test_publication_ingest.py",
            ),
            qualification="integration",
        ),
    )


def _require_fault_orchestration() -> None:
    _require_pipeline_stack()
    pytest.skip(
        "blocked: live fault injection requires orchestrated stack control; "
        "record evidence in docs/benchmarks/uns-to-lake-delivery.md"
    )


# --- Unit-testable fault-matrix helpers ---


def test_fault_matrix_covers_all_plan_scenarios():
    scenarios = {entry.scenario for entry in fault_matrix()}
    expected = {
        "historian_stopped_throughout",
        "store_stopped_during_second_route_upload",
        "kill_after_upload_before_commit",
        "rebalance_during_delayed_upload",
        "dlq_timeout_or_failure",
        "existing_key_different_content",
        "partial_adls_staging_upload",
        "committed_offset_older_than_retained_log",
        "two_schema_versions_two_sites_two_applications",
        "legacy_map_or_live_registration_changed",
        "many_small_routes_near_limit_records",
        "retained_bootstrap_and_fresh_retained_publication",
    }
    assert scenarios == expected


def test_fault_matrix_entries_reference_unit_evidence():
    for entry in fault_matrix():
        assert entry.invariant
        assert entry.unit_tests
        if entry.qualification == "unit":
            assert any("test_" in ref for ref in entry.unit_tests)


def test_kafka_coordinate_identifies_duplicate_delivery():
    rows = [
        {
            "event_id": "source:a",
            "kafka_topic": "uns.historic-events",
            "kafka_partition": 3,
            "kafka_offset": 42,
            "object_key": "raw/v2/.../a.parquet",
        },
        {
            "event_id": "source:a",
            "kafka_topic": "uns.historic-events",
            "kafka_partition": 3,
            "kafka_offset": 42,
            "object_key": "raw/v2/.../b.parquet",
        },
        {
            "event_id": "source:b",
            "kafka_topic": "uns.historic-events",
            "kafka_partition": 3,
            "kafka_offset": 43,
            "object_key": "raw/v2/.../c.parquet",
        },
    ]
    duplicates = duplicate_kafka_coordinates(rows)
    assert duplicates == {("uns.historic-events", 3, 42): 2}


def test_assert_lake_evidence_checks_body_route_and_path():
    expected = {
        "evt-1": PublicationCase(
            body=b'{"result": 4.2}',
            route=("lims", "plant-01", "lab-result", "1"),
            topic="Enterprise/plant-01/LIMS/results",
        ),
    }
    rows = [
        {
            "event_id": "evt-1",
            "original_payload": b'{"result": 4.2}',
            "route": ("lims", "plant-01", "lab-result", "1"),
            "object_key": (
                "raw/v2/application=lims/site=plant-01/schema=lab-result/"
                "version=1/ingestion_date=2026-09-11/batch1.parquet"
            ),
            "kafka_topic": "uns.historic-events",
            "kafka_partition": 0,
            "kafka_offset": 10,
        },
    ]
    assert_lake_evidence(rows, expected)


def test_route_from_object_key_parses_v2_hive_layout():
    key = (
        "raw/v2/application=mes/site=plant-01/schema=production-order/"
        "version=1/ingestion_date=2026-09-11/batch1.parquet"
    )
    assert _route_from_object_key(key) == ("mes", "plant-01", "production-order", "1")
    assert _route_from_object_key("v1/ingest_date=2026-09-09/hour=10/partition=0/x.parquet") is None


# --- Integration acceptance ---


@pytest.mark.integrationtest
def test_four_domains_reach_lake_with_historian_stopped(pipeline):
    pipeline.stop_historian()
    expected = pipeline.publish_cases()
    pipeline.wait_for_lake_records(expected, timeout=120)
    rows = pipeline.read_lake_records()
    assert_lake_evidence(rows, expected)
    assert not pipeline.historian_running


@pytest.mark.integrationtest
@pytest.mark.parametrize(
    "scenario",
    [entry.scenario for entry in fault_matrix() if entry.qualification in {"manual", "integration"}],
)
def test_live_fault_scenario_requires_orchestration(scenario: str):
    _require_fault_orchestration()
    pytest.fail(f"unexpected live execution for scenario {scenario}")
