"""Unit tests for idempotent Kafka topic bootstrap."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from uns_kafka.bootstrap import (
    HISTORIC_TOPIC,
    SEVEN_DAYS_MS,
    THIRTY_DAYS_MS,
    TopicMismatchError,
    TopicSpec,
    ensure_pipeline_topics,
    ensure_topic,
    load_topic_specs,
    verify_existing_topic,
)
from uns_kafka.rejections import DLQ_TOPIC


def test_load_topic_specs_uses_settings_defaults():
    historic, dlq = load_topic_specs()
    assert historic.name == HISTORIC_TOPIC
    assert historic.partitions == 12
    assert historic.replication_factor == 1
    assert historic.retention_ms == SEVEN_DAYS_MS
    assert dlq.name == DLQ_TOPIC
    assert dlq.retention_ms == THIRTY_DAYS_MS


def test_topic_spec_includes_dev_cleanup_and_min_isr():
    historic, _ = load_topic_specs()
    assert historic.new_topic_configs() == {
        "cleanup.policy": "delete",
        "retention.ms": str(SEVEN_DAYS_MS),
        "min.insync.replicas": "1",
    }


def test_verify_existing_topic_raises_on_partition_mismatch():
    spec = TopicSpec(
        name=HISTORIC_TOPIC,
        partitions=12,
        replication_factor=1,
        retention_ms=SEVEN_DAYS_MS,
    )
    with pytest.raises(TopicMismatchError, match="partitions=8"):
        verify_existing_topic(spec=spec, partition_count=8, configs={})


def test_verify_existing_topic_raises_on_config_mismatch():
    spec = TopicSpec(
        name=HISTORIC_TOPIC,
        partitions=12,
        replication_factor=1,
        retention_ms=SEVEN_DAYS_MS,
    )
    configs = {
        "cleanup.policy": SimpleNamespace(value="compact"),
        "retention.ms": SimpleNamespace(value=str(SEVEN_DAYS_MS)),
        "min.insync.replicas": SimpleNamespace(value="1"),
    }
    with pytest.raises(TopicMismatchError, match="cleanup.policy=compact"):
        verify_existing_topic(spec=spec, partition_count=12, configs=configs)


def test_ensure_topic_creates_missing_topic():
    admin = MagicMock()
    admin.list_topics.return_value = SimpleNamespace(topics={})
    future = MagicMock()
    future.result.return_value = None
    admin.create_topics.return_value = {"uns.historic-events": future}

    spec = TopicSpec(
        name=HISTORIC_TOPIC,
        partitions=12,
        replication_factor=1,
        retention_ms=SEVEN_DAYS_MS,
    )
    ensure_topic(admin, spec)

    admin.create_topics.assert_called_once()
    new_topic = admin.create_topics.call_args.args[0][0]
    assert new_topic.topic == HISTORIC_TOPIC
    assert new_topic.num_partitions == 12
    assert new_topic.replication_factor == 1


def test_ensure_topic_verifies_existing_topic_without_recreate():
    admin = MagicMock()
    admin.list_topics.return_value = SimpleNamespace(
        topics={
            HISTORIC_TOPIC: SimpleNamespace(partitions={0: object(), 1: object()}),
        }
    )
    config_future = MagicMock()
    config_future.result.return_value = {
        key: SimpleNamespace(value=value)
        for key, value in TopicSpec(
            name=HISTORIC_TOPIC,
            partitions=2,
            replication_factor=1,
            retention_ms=SEVEN_DAYS_MS,
        ).new_topic_configs().items()
    }
    admin.describe_configs.return_value = {"topic": config_future}

    spec = TopicSpec(
        name=HISTORIC_TOPIC,
        partitions=2,
        replication_factor=1,
        retention_ms=SEVEN_DAYS_MS,
    )
    ensure_topic(admin, spec)

    admin.create_topics.assert_not_called()


def test_ensure_pipeline_topics_bootstraps_historic_and_dlq_topics():
    admin = MagicMock()
    admin.list_topics.return_value = SimpleNamespace(topics={})
    future = MagicMock()
    future.result.return_value = None
    admin.create_topics.return_value = {"created": future}

    ensure_pipeline_topics(admin)

    assert admin.create_topics.call_count == 2
