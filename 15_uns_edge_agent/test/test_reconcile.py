"""Reconciler crash-aware apply tests."""

from __future__ import annotations

import json

import pytest

from uns_config.edge_config_digest import configuration_digest
from uns_config.edge_contracts import AdapterConfig, decode_edge_config
from uns_edge_agent.edge_client import FakeEdgeClient, snapshot_owned
from uns_edge_agent.reconcile import AppliedState, ReconcileError, Reconciler

from test_protocols import ALLOWLIST, _modbus_adapter, _opc_ua_adapter, _s7_adapter


def _minimal_document(*, revision: int = 1, adapters: list[dict] | None = None, deleted: list[str] | None = None):
    document = {
        "contract_version": 1,
        "edge_id": "edge-test-01",
        "revision": revision,
        "adapters": adapters or [],
        "required_route_revision": 1,
        "secret_refs": [],
        "deleted_adapter_ids": deleted or [],
    }
    document["digest"] = configuration_digest(document)
    return document


def _adapter_dict(adapter) -> dict:
    return {
        "adapter_id": adapter.adapter_id,
        "protocol": adapter.protocol,
        "connection": dict(adapter.connection),
        "tags": [dict(tag) for tag in adapter.tags],
        "northbound_mappings": [dict(mapping) for mapping in adapter.northbound_mappings],
    }


def _config(*, revision: int = 1, adapters=(), deleted=()):
    document = _minimal_document(
        revision=revision,
        adapters=[_adapter_dict(adapter) for adapter in adapters],
        deleted=list(deleted),
    )
    return decode_edge_config(json.dumps(document).encode("utf-8"))


def _reconciler(edge: FakeEdgeClient, *, revision: int = 0, digest: str = "") -> Reconciler:
    return Reconciler(
        edge,
        boot_id="boot-1",
        endpoint_allowlist=ALLOWLIST,
        applied_state=AppliedState(revision=revision, digest=digest),
    )


def _modified_s7_adapter() -> AdapterConfig:
    return AdapterConfig(
        adapter_id="catalog-fixture-s7",
        protocol="s7",
        connection={
            "host": "192.0.2.1",
            "port": 102,
            "controller_type": "S7_1500",
            "read_only": True,
        },
        tags=(
            {
                "tag_id": "speed",
                "address": "%ID104",
                "data_type": "Integer",
            },
        ),
        northbound_mappings=(
            {
                "tag_id": "speed",
                "topic": "Acme/Test/Area/Line/Cell/S7/ProcessValue/Speed2",
            },
        ),
    )


def _assert_failed_apply_keeps_revision(
    report,
    *,
    expected_revision: int,
    edge: FakeEdgeClient,
    adapter_id: str,
    expected_tag_address: str,
) -> None:
    assert report.phase == "failed"
    assert report.applied_revision == expected_revision
    current = edge.read_owned("edge-test-01")
    assert current[adapter_id].tags[0]["definition"]["tagAddress"] == expected_tag_address


def test_apply_creates_owned_adapters_and_preserves_unmanaged_ids():
    edge = FakeEdgeClient()
    edge.seed_adapter({"id": "simulation", "type": "simulation", "config": {}})
    reconciler = _reconciler(edge)
    config = _config(revision=1, adapters=(_modbus_adapter(), _opc_ua_adapter()))
    report = reconciler.apply(config)
    assert report.phase == "applied"
    assert report.applied_revision == 1
    owned = edge.read_owned("edge-test-01")
    assert set(owned) == {"catalog-modbus-sim", "catalog-opcua-sim"}
    assert "simulation" in edge._adapters


def test_same_revision_and_digest_is_noop_after_readback():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    config = _config(revision=1, adapters=(_s7_adapter(),))
    first = reconciler.apply(config)
    second = reconciler.apply(config)
    assert first.phase == "applied"
    assert second.phase == "applied"
    assert edge.calls.count(("apply", "catalog-fixture-s7")) == 1


def test_same_revision_different_digest_fails():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge, revision=1, digest="digest-old")
    config = _config(revision=1, adapters=(_s7_adapter(),))
    with pytest.raises(ReconcileError, match="digest_mismatch"):
        reconciler.apply(config)


def test_older_revision_is_ignored():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge, revision=8, digest="digest-8")
    config = _config(revision=7, adapters=(_s7_adapter(),))
    report = reconciler.apply(config)
    assert report.phase == "ignored"
    assert report.applied_revision == 8


def test_adapter_failure_reports_failed_and_keeps_previous_revision():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    reconciler.apply(_config(revision=8, adapters=(_s7_adapter(),)))
    edge.failures["catalog-fixture-s7"] = "adapter"
    report = reconciler.apply(_config(revision=9, adapters=(_modified_s7_adapter(),)))
    _assert_failed_apply_keeps_revision(
        report,
        expected_revision=8,
        edge=edge,
        adapter_id="catalog-fixture-s7",
        expected_tag_address="%ID103",
    )


def test_tags_failure_reports_failed_and_keeps_previous_revision():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    reconciler.apply(_config(revision=8, adapters=(_s7_adapter(),)))
    edge.failures["catalog-fixture-s7"] = "tags"
    report = reconciler.apply(_config(revision=9, adapters=(_modified_s7_adapter(),)))
    _assert_failed_apply_keeps_revision(
        report,
        expected_revision=8,
        edge=edge,
        adapter_id="catalog-fixture-s7",
        expected_tag_address="%ID103",
    )


def test_mappings_failure_reports_failed_and_keeps_previous_revision():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    reconciler.apply(_config(revision=8, adapters=(_s7_adapter(),)))
    edge.failures["catalog-fixture-s7"] = "mappings"
    report = reconciler.apply(_config(revision=9, adapters=(_modified_s7_adapter(),)))
    _assert_failed_apply_keeps_revision(
        report,
        expected_revision=8,
        edge=edge,
        adapter_id="catalog-fixture-s7",
        expected_tag_address="%ID103",
    )


def test_fail_after_write_reports_failed_and_keeps_previous_revision():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    reconciler.apply(_config(revision=8, adapters=(_s7_adapter(),)))
    edge.fail_after_write.add("catalog-fixture-s7")
    report = reconciler.apply(_config(revision=9, adapters=(_modified_s7_adapter(),)))
    _assert_failed_apply_keeps_revision(
        report,
        expected_revision=8,
        edge=edge,
        adapter_id="catalog-fixture-s7",
        expected_tag_address="%ID103",
    )


def test_delete_failure_reports_failed_and_keeps_previous_revision():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    old = _s7_adapter(adapter_id="catalog-old-s7")
    new = _modbus_adapter(adapter_id="catalog-modbus-sim")
    reconciler.apply(_config(revision=1, adapters=(old,)))
    edge.failures["catalog-old-s7"] = "delete"
    report = reconciler.apply(
        _config(revision=2, adapters=(new,), deleted=("catalog-old-s7",)),
    )
    assert report.phase == "failed"
    assert report.applied_revision == 1
    owned = edge.read_owned("edge-test-01")
    assert set(owned) == {"catalog-old-s7"}


def test_recovery_failure_reports_degraded_with_actual_state():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    reconciler.apply(_config(revision=8, adapters=(_s7_adapter(),)))
    edge.failures["catalog-fixture-s7"] = "mappings"

    def failing_restore(_snapshot):
        raise RuntimeError("recovery failed")

    edge.restore_snapshot = failing_restore  # type: ignore[method-assign]

    report = reconciler.apply(_config(revision=9, adapters=(_modified_s7_adapter(),)))
    assert report.phase == "degraded"
    assert report.applied_revision == 8
    assert report.last_error_code == "mappings_failed"
    assert report.adapter_results == (
        {
            "adapter_id": "catalog-fixture-s7",
            "protocol_type": "s7",
            "status": "present",
        },
    )
    current = edge.read_owned("edge-test-01")
    assert current["catalog-fixture-s7"].tags[0]["definition"]["tagAddress"] == "%ID104"
    assert current["catalog-fixture-s7"].northbound_mappings == ()


def test_restart_resumes_journal_without_claiming_unapplied_revision(journal):
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    config = _config(revision=9, adapters=(_s7_adapter(),))
    snapshot = snapshot_owned(edge.read_owned("edge-test-01"))
    journal.begin_apply(
        {
            "contract_version": config.contract_version,
            "edge_id": config.edge_id,
            "revision": config.revision,
            "digest": config.digest,
            "adapters": [_adapter_dict(adapter) for adapter in config.adapters],
            "required_route_revision": config.required_route_revision,
            "secret_refs": [],
            "deleted_adapter_ids": [],
        },
        snapshot,
    )
    report = reconciler.resume_pending(journal)
    assert report is not None
    assert report.desired_revision == 9
    assert report.phase == "applied"
    assert report.applied_revision == 9
    journal.finish_apply(
        {
            "edge_id": report.edge_id,
            "boot_id": report.boot_id,
            "report_sequence": 0,
            "desired_revision": report.desired_revision,
            "applied_revision": report.applied_revision,
            "applied_digest": report.applied_digest,
            "phase": report.phase,
            "adapter_results": list(report.adapter_results),
            "last_error_code": report.last_error_code,
            "versions": dict(report.versions),
            "capabilities": dict(report.capabilities),
        }
    )
    assert journal.pending_apply() is None


def test_empty_readback_cannot_delete_owned_adapters():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    old = _s7_adapter(adapter_id="catalog-old-s7")
    reconciler.apply(_config(revision=1, adapters=(old,)))
    edge.corrupt_readback = True
    new = _modbus_adapter()
    report = reconciler.apply(
        _config(revision=2, adapters=(new,), deleted=("catalog-old-s7",)),
    )
    assert report.phase in {"failed", "degraded"}
    assert "catalog-old-s7" in edge._adapters


def test_explicit_deletions_run_after_replacements_verify():
    edge = FakeEdgeClient()
    reconciler = _reconciler(edge)
    old = _s7_adapter(adapter_id="catalog-old-s7")
    new = _modbus_adapter(adapter_id="catalog-modbus-sim")
    reconciler.apply(_config(revision=1, adapters=(old,)))
    report = reconciler.apply(
        _config(revision=2, adapters=(new,), deleted=("catalog-old-s7",)),
    )
    assert report.phase == "applied"
    owned = edge.read_owned("edge-test-01")
    assert "catalog-old-s7" not in owned
    assert "catalog-modbus-sim" in owned

