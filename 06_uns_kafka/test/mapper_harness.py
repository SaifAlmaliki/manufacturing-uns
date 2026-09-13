"""Helpers for live MQTT+Kafka mapper tests.

UNSKafkaMapper.run() only connects; production then calls loop_forever().
Tests must start the Paho loop, wait for subscribe, and use a unique MQTT
client id so pytest-xdist workers do not steal each other's MQTT 5 sessions.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace

import pytest
from confluent_kafka import OFFSET_END, Consumer

from uns_kafka.uns_kafka_config import IngestionSettings
from uns_kafka.uns_kafka_listener import UNSKafkaMapper


def wait_until(condition: Callable[[], bool], *, timeout_s: float = 10.0, sleep_s: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(sleep_s)
    return condition()


def patch_unique_ingestion_config(monkeypatch: pytest.MonkeyPatch) -> str:
    """Give this test its own MQTT client id so parallel workers do not collide."""
    suffix = uuid.uuid4().hex[:12]
    client_id = f"uns_kafka_ingest-test-{suffix}"
    monkeypatch.setattr(
        IngestionSettings,
        "config",
        replace(IngestionSettings.config, shard_id=f"test-{suffix}", client_id=client_id),
    )
    return client_id


def start_live_mapper(monkeypatch: pytest.MonkeyPatch) -> UNSKafkaMapper:
    """Connect, start the MQTT loop, and wait until the mapper is subscribed."""
    patch_unique_ingestion_config(monkeypatch)
    mapper = UNSKafkaMapper()
    subscribed = threading.Event()
    previous_on_subscribe = mapper.uns_client.on_subscribe

    def on_subscribe(client, userdata, mid, reason_codes, properties=None):
        if previous_on_subscribe is not None:
            previous_on_subscribe(client, userdata, mid, reason_codes, properties)
        subscribed.set()

    mapper.uns_client.on_subscribe = on_subscribe
    mapper.uns_client.loop_start()
    if not wait_until(lambda: mapper.uns_client.is_connected() and subscribed.is_set()):
        stop_live_mapper(mapper)
        pytest.fail("MQTT mapper did not connect and subscribe before publish")
    return mapper


def stop_live_mapper(mapper: UNSKafkaMapper | None) -> None:
    if mapper is None:
        return
    mapper.uns_client.disconnect()
    mapper.uns_client.loop_stop()


@contextmanager
def live_mapper(monkeypatch: pytest.MonkeyPatch) -> Iterator[UNSKafkaMapper]:
    mapper = start_live_mapper(monkeypatch)
    try:
        yield mapper
    finally:
        stop_live_mapper(mapper)


def wait_for_kafka_assignment(consumer: Consumer, topic: str, *, from_end: bool = False) -> None:
    """Block until subscribe() has assigned partitions; poll() is required to trigger it."""
    assigned = threading.Event()

    def on_assign(consumer_obj, partitions):
        if from_end:
            for part in partitions:
                part.offset = OFFSET_END
        consumer_obj.assign(partitions)
        assigned.set()

    consumer.subscribe([topic], on_assign=on_assign)
    if not wait_until(lambda: _poll_until_assigned(consumer, assigned)):
        pytest.fail(f"Kafka consumer did not assign {topic}")


def _poll_until_assigned(consumer: Consumer, assigned: threading.Event) -> bool:
    if assigned.is_set():
        return True
    consumer.poll(0.1)
    return assigned.is_set()
