"""Checkpoint helper tests."""

from unittest.mock import MagicMock

import pytest

from confluent_kafka import TopicPartition

from uns_datalake.checkpoint import (
    ConsumedPrefix,
    build_commit_partitions,
    inspect_commit_result,
    may_commit_kafka,
)


def test_numeric_gap_does_not_block_but_unresolved_record_does():
    prefix = ConsumedPrefix()
    for offset in (10, 12, 15):
        prefix.observe(offset)
    prefix.resolve(15)
    assert prefix.next_offset() is None
    prefix.resolve(10)
    assert prefix.next_offset() == 11
    prefix.resolve(12)
    assert prefix.next_offset() == 16


def test_observe_rejects_duplicate_or_out_of_order_offsets():
    prefix = ConsumedPrefix()
    prefix.observe(10)
    with pytest.raises(ValueError, match="out-of-order"):
        prefix.observe(9)
    with pytest.raises(ValueError, match="out-of-order"):
        prefix.observe(10)


def test_resolve_rejects_unknown_offsets():
    prefix = ConsumedPrefix()
    prefix.observe(10)
    with pytest.raises(ValueError, match="unknown offset"):
        prefix.resolve(11)


def test_discard_committed_trims_resolved_prefix():
    prefix = ConsumedPrefix()
    for offset in (10, 11, 12):
        prefix.observe(offset)
    for offset in (10, 11, 12):
        prefix.resolve(offset)
    prefix.discard_committed(13)
    assert prefix.next_offset() is None
    prefix.observe(13)
    prefix.resolve(13)
    assert prefix.next_offset() == 14


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
