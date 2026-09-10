"""Unit tests for the Kafka historian consumer offset and ownership rules."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from confluent_kafka import TopicPartition

from uns_historian.batch import BatchPersistResult, HISTORIC_KAFKA_TOPIC
from uns_historian.historian_handler import HistorianHandler
from uns_historian.kafka_consumer import (
    HistorianKafkaMapper,
    KafkaAheadOfSqlError,
    RetentionGapError,
    build_commit_partitions,
    may_commit_kafka,
    reconcile_partition_offset,
)


def test_reconcile_uses_sql_checkpoint_when_kafka_is_behind():
    assert reconcile_partition_offset(sql_checkpoint=10, kafka_committed=7, retained_low=0) == 10


def test_reconcile_raises_when_kafka_is_ahead_of_sql():
    with pytest.raises(KafkaAheadOfSqlError):
        reconcile_partition_offset(sql_checkpoint=10, kafka_committed=12, retained_low=0)


def test_reconcile_raises_when_checkpoint_before_retained_log():
    with pytest.raises(RetentionGapError):
        reconcile_partition_offset(sql_checkpoint=3, kafka_committed=3, retained_low=5)


def test_build_commit_partitions_sets_next_offset():
    partitions = build_commit_partitions({(HISTORIC_KAFKA_TOPIC, 0): 42})
    assert partitions == [TopicPartition(HISTORIC_KAFKA_TOPIC, 0, 42)]


def test_may_commit_kafka_requires_active_unrevoked_ownership():
    assert may_commit_kafka(ownership_active=True, revoked=False) is True
    assert may_commit_kafka(ownership_active=True, revoked=True) is False
    assert may_commit_kafka(ownership_active=False, revoked=False) is False


@pytest.mark.asyncio(loop_scope="function")
async def test_revoked_owner_does_not_commit_kafka_after_sql_success():
    handler = AsyncMock(spec=HistorianHandler)
    mapper = HistorianKafkaMapper(handler=handler)
    mapper.on_assign([TopicPartition(HISTORIC_KAFKA_TOPIC, 0, 0)])
    mapper.on_revoke([TopicPartition(HISTORIC_KAFKA_TOPIC, 0)])

    commits = mapper.record_sql_success(
        BatchPersistResult(
            inserted_count=1,
            duplicate_count=0,
            filtered_stale_count=0,
            quarantined_conflicts=(),
            next_offsets={(HISTORIC_KAFKA_TOPIC, 0): 11},
        ),
        revoked=mapper.revoked,
    )

    assert commits == {}
    assert mapper.pending_kafka_commits == {}


@pytest.mark.asyncio(loop_scope="function")
async def test_sql_success_commits_when_ownership_is_active():
    handler = AsyncMock(spec=HistorianHandler)
    mapper = HistorianKafkaMapper(handler=handler)
    mapper.on_assign([TopicPartition(HISTORIC_KAFKA_TOPIC, 0, 0)])

    commits = mapper.record_sql_success(
        BatchPersistResult(
            inserted_count=1,
            duplicate_count=0,
            filtered_stale_count=0,
            quarantined_conflicts=(),
            next_offsets={(HISTORIC_KAFKA_TOPIC, 0): 12},
        ),
        revoked=mapper.revoked,
    )

    assert commits == {(HISTORIC_KAFKA_TOPIC, 0): 12}


def test_should_pause_for_backpressure_calls_clock_function():
    handler = AsyncMock(spec=HistorianHandler)
    mapper = HistorianKafkaMapper(handler=handler)

    assert callable(mapper.monotonic)
    assert mapper.should_pause_for_backpressure() is False


def test_poison_offset_blocks_committing_later_contiguous_prefix():
    from uns_historian.batch import compute_next_offset

    handled = [10, 12]
    assert compute_next_offset(10, handled) == 11
