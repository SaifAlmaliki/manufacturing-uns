"""Unit tests for literal Kafka event publication without a live broker."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from confluent_kafka import KafkaException

from uns_kafka.kafka_handler import KafkaHandler
from uns_kafka.uns_kafka_config import build_producer_config


class FakeProducer:
    def __init__(self, config: dict):
        self.config = config
        self.messages: list[tuple] = []
        self.poll_calls: list[float] = []
        self.fail_buffer = False
        self.pending_callbacks: list = []

    def produce(self, topic, key=None, value=None, callback=None):
        if self.fail_buffer:
            raise BufferError("producer queue full")
        self.messages.append((topic, key, value, callback))
        if callback is not None:
            self.pending_callbacks.append(callback)

    def poll(self, timeout):
        self.poll_calls.append(timeout)

    def flush(self, timeout=-1):
        return 0

    def list_topics(self, timeout=10):
        return MagicMock()

    def purge(self):
        return None


def test_build_producer_config_applies_bounded_delivery_defaults():
    config = build_producer_config(
        {
            "bootstrap.servers": "localhost:9092",
            "client.id": "uns_kafka_client",
        }
    )
    assert config["enable.idempotence"] is True
    assert config["acks"] == "all"
    assert config["queue.buffering.max.messages"] == 1000
    assert config["queue.buffering.max.kbytes"] == 16384
    assert config["delivery.timeout.ms"] == 120_000


def test_publish_event_enqueues_literal_topic_key_and_bytes(monkeypatch):
    fake = FakeProducer({})
    monkeypatch.setattr("uns_kafka.kafka_handler.Producer", lambda config: fake)

    handler = KafkaHandler({"bootstrap.servers": "localhost:9092"})
    deliveries: list[tuple] = []

    handler.publish_event(
        "uns.historic-events",
        b"partition-key",
        b'{"schema_version":1}',
        lambda err, msg: deliveries.append((err, msg)),
    )

    assert fake.messages == [
        ("uns.historic-events", b"partition-key", b'{"schema_version":1}', fake.messages[0][3]),
    ]
    assert deliveries == []
    assert fake.poll_calls == [0]


def test_publish_event_does_not_report_success_before_delivery_callback(monkeypatch):
    fake = FakeProducer({})
    monkeypatch.setattr("uns_kafka.kafka_handler.Producer", lambda config: fake)

    handler = KafkaHandler({"bootstrap.servers": "localhost:9092"})
    seen: list[str] = []

    handler.publish_event(
        "uns.historic-events",
        b"k",
        b"v",
        lambda err, msg: seen.append("delivered" if err is None else "failed"),
    )
    assert seen == []

    fake.pending_callbacks[0](None, MagicMock(topic=lambda: "uns.historic-events"))
    assert seen == ["delivered"]


def test_publish_event_propagates_buffer_error(monkeypatch):
    fake = FakeProducer({})
    fake.fail_buffer = True
    monkeypatch.setattr("uns_kafka.kafka_handler.Producer", lambda config: fake)

    handler = KafkaHandler({"bootstrap.servers": "localhost:9092"})
    with pytest.raises(BufferError):
        handler.publish_event("uns.historic-events", b"k", b"v", lambda *_: None)


def test_publish_event_reports_delivery_failures(monkeypatch):
    fake = FakeProducer({})
    monkeypatch.setattr("uns_kafka.kafka_handler.Producer", lambda config: fake)

    handler = KafkaHandler({"bootstrap.servers": "localhost:9092"})
    failures: list[str] = []

    handler.publish_event(
        "uns.historic-events",
        b"k",
        b"v",
        lambda err, msg: failures.append(str(err)),
    )
    fake.pending_callbacks[0](KafkaException("broker down"), None)
    assert failures == ["broker down"]
    assert handler.failed_delivery_count == 1
