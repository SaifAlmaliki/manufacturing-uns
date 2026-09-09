"""Checkpoint helper tests."""

from unittest.mock import MagicMock

from confluent_kafka import TopicPartition

from uns_datalake.batch import LakeRecord
from uns_datalake.checkpoint import (
    build_commit_partitions,
    compute_next_offset,
    inspect_commit_result,
    may_commit_kafka,
    next_offsets_for_records,
)
from conftest import source_envelope


def _record(partition: int, offset: int) -> LakeRecord:
    envelope = source_envelope()
    return LakeRecord(
        kafka_topic="uns.historic-events",
        partition=partition,
        offset=offset,
        envelope=envelope,
        envelope_bytes=b"{}",
    )


def test_compute_next_offset_requires_contiguous_prefix():
    assert compute_next_offset(0, [0, 1, 2]) == 3
    assert compute_next_offset(0, [0, 2]) == 1


def test_next_offsets_for_records():
    records = (_record(0, 10), _record(0, 11), _record(1, 5))
    assert next_offsets_for_records(records) == {("uns.historic-events", 0): 12, ("uns.historic-events", 1): 6}


def test_build_commit_partitions():
    partitions = build_commit_partitions({("uns.historic-events", 2): 42})
    assert partitions == [TopicPartition("uns.historic-events", 2, 42)]


def test_inspect_commit_result_collects_partition_errors():
    failed = MagicMock()
    failed.partition = 0
    failed.error = MagicMock(code=MagicMock(return_value=42))
    assert inspect_commit_result([failed]) == [(0, 42)]


def test_may_commit_kafka():
    assert may_commit_kafka(ownership_active=True, revoked=False)
    assert not may_commit_kafka(ownership_active=True, revoked=True)
