"""Bounded route-group batching and admission pressure tests."""

from __future__ import annotations

import uuid

import pytest

from uns_datalake.batch import BatchManager, freeze_partition_records, new_object_id
from uns_datalake.config import FlushLimits
from uns_datalake.routing import lake_object_path
from conftest import lake_record_from_envelope, v2_envelope


def _route_record(
    offset: int,
    *,
    application: str,
    schema: str = "lab-result",
    payload_size: int = 64,
    partition: int = 0,
) -> object:
    envelope = v2_envelope(
        source_application=application,
        payload_schema_id=schema,
        original_payload=b"x" * payload_size,
    )
    return lake_record_from_envelope(
        envelope,
        partition=partition,
        offset=offset,
        envelope_bytes=b"x" * payload_size,
    )


def test_sixty_fifth_route_group_triggers_pressure():
    limits = FlushLimits(
        max_records=10_000,
        max_bytes=100_000_000,
        interval_seconds=60,
        worker_max_buffered_bytes=100_000_000,
        max_active_route_groups=64,
    )
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    for index in range(64):
        assert manager.try_add(_route_record(index, application=f"app-{index}"))
    assert manager.active_route_group_count(("uns.historic-events", 0)) == 64
    assert not manager.try_add(_route_record(64, application="app-64"))
    assert manager.should_flush_partition(("uns.historic-events", 0))


def test_batch_byte_budget_blocks_admission():
    limits = FlushLimits(
        max_records=10_000,
        max_bytes=200,
        max_record_bytes=200,
        interval_seconds=60,
        worker_max_buffered_bytes=1_000_000,
    )
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    assert manager.try_add(_route_record(0, application="lims", payload_size=120))
    assert not manager.try_add(_route_record(1, application="mes", payload_size=120))
    assert manager.buffers[("uns.historic-events", 0)].byte_total == 120


def test_batch_record_limit_blocks_admission():
    limits = FlushLimits(
        max_records=2,
        max_bytes=1_000_000,
        max_record_bytes=1_000_000,
        interval_seconds=60,
        worker_max_buffered_bytes=1_000_000,
    )
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    assert manager.try_add(_route_record(0, application="lims"))
    assert manager.try_add(_route_record(1, application="mes"))
    assert not manager.try_add(_route_record(2, application="logistics"))
    assert manager.choose_flush_partition() == ("uns.historic-events", 0)


def test_admission_reservation_counts_toward_worker_budget():
    limits = FlushLimits(
        max_records=10,
        max_bytes=300,
        max_record_bytes=200,
        interval_seconds=60,
        worker_max_buffered_bytes=300,
    )
    manager = BatchManager(limits=limits, monotonic=lambda: 0.0)
    assert manager.try_add(_route_record(0, application="lims", payload_size=120))
    manager.reserve_admission(120)
    assert manager.total_buffered_bytes() == 240
    pending = _route_record(1, application="mes", payload_size=120)
    assert manager.admission_would_exceed_limits(pending)


def test_freeze_assigns_full_uuid_object_ids_per_route_group():
    records = (
        _route_record(10, application="lims"),
        _route_record(12, application="mes"),
        _route_record(15, application="lims"),
    )
    frozen = freeze_partition_records(("uns.historic-events", 0), records)
    assert len(frozen.route_groups) == 2
    for group in frozen.route_groups:
        parsed = uuid.UUID(group.object_id)
        assert str(parsed) == group.object_id
        assert group.object_path == lake_object_path(group.route, group.object_id)
        assert group.parquet_bytes is None


def test_freeze_preserves_route_membership_and_offsets():
    records = (
        _route_record(10, application="lims"),
        _route_record(12, application="mes"),
        _route_record(15, application="lims"),
    )
    frozen = freeze_partition_records(("uns.historic-events", 0), records)
    lims_group = next(group for group in frozen.route_groups if group.route.application == "lims")
    mes_group = next(group for group in frozen.route_groups if group.route.application == "mes")
    assert [record.offset for record in lims_group.records] == [10, 15]
    assert [record.offset for record in mes_group.records] == [12]


def test_new_object_id_is_full_uuid():
    value = new_object_id()
    assert str(uuid.UUID(value)) == value
