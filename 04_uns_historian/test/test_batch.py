"""Unit tests for historian batch assembly and offset math."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from uns_config.events import HistoricEventEnvelope, encode_event, ingress_event_id, source_event_id

from uns_historian.batch import (
    BatchCollector,
    BatchLimits,
    ConsumedEvent,
    build_metric_rows,
    compute_next_offset,
    raw_row_from_event,
)
from uns_historian.metric_flattener import MetricExpansionLimitError


def _telemetry_envelope(**overrides) -> HistoricEventEnvelope:
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    defaults = {
        "schema_version": 1,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": time,
        "received_at": datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC),
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"value": 21.4, "timestamp": 1_788_948_000_000},
        "raw_payload_base64": None,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


def _consumed(
    envelope: HistoricEventEnvelope,
    *,
    partition: int = 0,
    offset: int = 0,
    kafka_topic: str = "uns.historic-events",
) -> ConsumedEvent:
    return ConsumedEvent(
        kafka_topic=kafka_topic,
        partition=partition,
        offset=offset,
        envelope=envelope,
        envelope_bytes=encode_event(envelope),
    )


def _ingress_envelope(**overrides) -> HistoricEventEnvelope:
    defaults = {
        "identity_quality": "ingress",
        "source_boot_id": None,
        "source_sequence": None,
        "event_id": ingress_event_id(uuid4()),
    }
    defaults.update(overrides)
    return _telemetry_envelope(**defaults)


def test_batch_collector_respects_event_count_limit():
    limits = BatchLimits(max_events=2, max_bytes=10_000, max_age_seconds=10.0)
    collector = BatchCollector(limits=limits)
    first = _consumed(_telemetry_envelope())
    second = _consumed(_ingress_envelope())
    third = _consumed(_ingress_envelope())

    assert collector.try_add(first, monotonic=0.0)
    assert collector.try_add(second, monotonic=0.0)
    assert collector.try_add(third, monotonic=0.0) is False
    assert len(collector.events) == 2


def test_batch_collector_respects_byte_limit():
    limits = BatchLimits(max_events=10, max_bytes=100, max_age_seconds=10.0)
    collector = BatchCollector(limits=limits)
    large_payload = {"value": "x" * 200, "timestamp": 1}
    event = _consumed(_telemetry_envelope(payload=large_payload))

    assert collector.try_add(event, monotonic=0.0) is False
    assert collector.events == []


def test_batch_collector_respects_age_limit():
    limits = BatchLimits(max_events=10, max_bytes=10_000, max_age_seconds=0.1)
    collector = BatchCollector(limits=limits)
    assert collector.try_add(_consumed(_telemetry_envelope()), monotonic=0.0)
    assert collector.is_full(monotonic=0.05) is False
    assert collector.is_full(monotonic=0.11) is True


def test_batch_collector_spans_partitions():
    collector = BatchCollector(limits=BatchLimits())
    collector.try_add(_consumed(_telemetry_envelope(), partition=0), monotonic=0.0)
    collector.try_add(_consumed(_telemetry_envelope(), partition=1), monotonic=0.0)
    assert collector.spans_partitions() is True


def test_metric_expansion_limit_raises_for_oversized_payload():
    payload = {f"metric_{index}": index for index in range(25)}
    raw_row = raw_row_from_event(_consumed(_telemetry_envelope(payload=payload)))
    with pytest.raises(MetricExpansionLimitError):
        build_metric_rows(raw_row, limits=BatchLimits(max_metric_rows=20))


def test_compute_next_offset_requires_contiguous_prefix():
    assert compute_next_offset(10, [10, 11, 12]) == 13
    assert compute_next_offset(10, [10, 12]) == 11
    assert compute_next_offset(10, [9, 10, 11]) == 12


def test_sparkplug_events_do_not_expand_metrics():
    envelope = _telemetry_envelope(event_kind="sparkplug_raw", payload={"raw": "bytes"})
    raw_row = raw_row_from_event(_consumed(envelope))
    assert build_metric_rows(raw_row, limits=BatchLimits()) == []
