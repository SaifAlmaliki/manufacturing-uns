"""Mapper loop, upload-before-commit and DLQ tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from confluent_kafka import TopicPartition

from uns_datalake.batch import FlushLimits
from uns_datalake.mapper import DatalakeMapper, OwnershipLostError
from uns_datalake.routing import LakeRecord
from uns_datalake.stores import FakeObjectStore
from conftest import envelope_bytes, lake_record_from_envelope, legacy_route_map, source_envelope


@dataclass
class FakeMessage:
    _topic: str
    _partition: int
    _offset: int
    _value: bytes

    def __init__(self, topic: str, partition: int, offset: int, value: bytes) -> None:
        self._topic = topic
        self._partition = partition
        self._offset = offset
        self._value = value

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def value(self) -> bytes:
        return self._value

    def error(self):
        return False


@dataclass
class FakeConsumer:
    messages: list[FakeMessage] = field(default_factory=list)
    commits: list[list[TopicPartition]] = field(default_factory=list)
    paused: list[TopicPartition] = field(default_factory=list)
    assigned: list[TopicPartition] = field(default_factory=list)
    on_assign = None
    on_revoke = None

    def subscribe(self, topics, on_assign, on_revoke):
        self.on_assign = on_assign
        self.on_revoke = on_revoke

    def poll(self, timeout: float):
        return self.messages.pop(0) if self.messages else None

    def pause(self, partitions):
        self.paused.extend(partitions)

    def resume(self, partitions):
        for partition in partitions:
            if partition in self.paused:
                self.paused.remove(partition)

    def assign(self, partitions):
        self.assigned = list(partitions)

    def committed(self, partitions, timeout: float):
        return [TopicPartition(part.topic, part.partition, 0) for part in partitions]

    def get_watermark_offsets(self, partition: TopicPartition, timeout: float):
        return 0, 100

    def position(self, partitions):
        return list(partitions)

    def commit(self, offsets=None, asynchronous=False):
        self.commits.append(list(offsets or []))
        return []

    def close(self):
        pass


def _commit_offsets(consumer: FakeConsumer) -> list[list[tuple[str, int, int]]]:
    return [[(part.topic, part.partition, part.offset) for part in batch] for batch in consumer.commits]


class FakeDlq:
    def __init__(self):
        self.messages: list[tuple[str, bytes, bytes]] = []
        self.fail = False

    def publish(self, *, topic: str, key: bytes, value: bytes) -> None:
        if self.fail:
            raise RuntimeError("dlq unavailable")
        self.messages.append((topic, key, value))


def _test_limits(**overrides) -> FlushLimits:
    defaults = {
        "max_records": 2,
        "max_bytes": 8_388_608,
        "max_record_bytes": 1_048_576,
        "interval_seconds": 60,
        "worker_max_buffered_bytes": 32 * 1024 * 1024,
    }
    defaults.update(overrides)
    return FlushLimits(**defaults)


def _mapper(tmp_path: Path, *, limits: FlushLimits | None = None) -> tuple[DatalakeMapper, FakeConsumer, FakeObjectStore, FakeDlq]:
    consumer = FakeConsumer()
    store = FakeObjectStore(root=tmp_path)
    dlq = FakeDlq()
    legacy = legacy_route_map()
    mapper = DatalakeMapper(
        consumer=consumer,
        store=store,
        dlq=dlq,
        legacy_map=legacy,
        limits=limits or _test_limits(),
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )
    mapper.on_assign([TopicPartition("uns.historic-events", 0, 0)])
    return mapper, consumer, store, dlq


def _complete_frozen_flush(mapper: DatalakeMapper) -> bool:
    while mapper.frozen_flush is not None:
        if not mapper.run_once():
            return False
    return True


def test_kafka_callbacks_accept_consumer_argument(tmp_path: Path):
    mapper, consumer, _store, _dlq = _mapper(tmp_path)
    mapper.start()
    consumer.on_assign(object(), [TopicPartition("uns.historic-events", 0, 0)])
    assert mapper.ownership_active is True
    consumer.on_revoke(object(), [TopicPartition("uns.historic-events", 0)])
    assert mapper.ownership_active is False


def test_upload_happens_before_commit(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(
        tmp_path,
        limits=_test_limits(max_records=1),
    )
    consumer.messages = [
        FakeMessage("uns.historic-events", 0, 0, envelope_bytes(source_sequence=1)),
    ]
    assert mapper.run_once()
    assert mapper.frozen_flush is not None
    assert consumer.commits == []
    assert mapper.run_once()
    assert store.objects
    assert _complete_frozen_flush(mapper)
    assert _commit_offsets(consumer) == [[("uns.historic-events", 0, 1)]]


def test_malformed_envelope_goes_to_dlq_before_commit(tmp_path: Path):
    mapper, consumer, _store, dlq = _mapper(tmp_path)
    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, b"not-json")]
    assert mapper.run_once()
    assert dlq.messages
    assert _commit_offsets(consumer) == [[("uns.historic-events", 0, 1)]]


def test_poison_after_buffered_valid_record_waits_for_flush(tmp_path: Path):
    mapper, consumer, store, dlq = _mapper(
        tmp_path,
        limits=_test_limits(max_records=1),
    )
    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, envelope_bytes(source_sequence=1))]
    assert mapper.run_once()
    assert mapper.frozen_flush is not None
    assert dlq.messages == []
    assert _complete_frozen_flush(mapper)
    consumer.messages = [FakeMessage("uns.historic-events", 0, 1, b"{bad json")]
    assert mapper.run_once()
    assert store.objects
    assert dlq.messages
    assert _commit_offsets(consumer)[-1] == [("uns.historic-events", 0, 2)]


def test_upload_retry_reuses_frozen_bytes(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(
        tmp_path,
        limits=_test_limits(max_records=1),
    )
    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, envelope_bytes(source_sequence=1))]
    mapper.run_once()
    path = mapper.frozen_flush.route_groups[0].object_path
    store.fail_paths.add(path)
    assert mapper.run_once()
    frozen_bytes = mapper.frozen_object.data
    assert consumer.commits == []
    store.fail_paths.clear()
    assert _complete_frozen_flush(mapper)
    assert store.objects[path] == frozen_bytes


def test_upload_failure_after_retries_does_not_commit(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(
        tmp_path,
        limits=_test_limits(max_records=1),
    )
    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, envelope_bytes(source_sequence=1))]
    mapper.run_once()
    path = mapper.frozen_flush.route_groups[0].object_path
    store.fail_paths.add(path)
    assert mapper.run_once() is True
    assert mapper.run_once() is True
    assert mapper.run_once() is False
    assert consumer.commits == []


def test_ownership_loss_with_pending_buffer_exits(tmp_path: Path):
    mapper, _consumer, _store, _dlq = _mapper(tmp_path)
    record = lake_record_from_envelope(
        source_envelope(),
        legacy_map=legacy_route_map(),
        offset=0,
        envelope_bytes=envelope_bytes(),
    )
    mapper._prefix(record.partition_key).observe(0)
    mapper.batch.try_add(record)
    with pytest.raises(OwnershipLostError):
        mapper.on_revoke([TopicPartition("uns.historic-events", 0)])


def test_revoked_owner_does_not_commit_after_upload(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(
        tmp_path,
        limits=_test_limits(max_records=1),
    )
    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, envelope_bytes(source_sequence=1))]
    mapper.run_once()
    mapper.revoked = True
    mapper.ownership_active = False
    with pytest.raises(OwnershipLostError):
        mapper.run_once()
    assert consumer.commits == []


def test_duplicate_event_ids_survive_replay_in_separate_files(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(
        tmp_path,
        limits=_test_limits(max_records=1),
    )
    payload = envelope_bytes(source_sequence=99)
    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, payload)]
    mapper.run_once()
    _complete_frozen_flush(mapper)
    first_key = next(iter(store.objects))

    mapper.frozen_flush = None
    mapper.batch = mapper.batch.__class__(limits=mapper.limits, monotonic=mapper.monotonic)
    consumer.messages = [FakeMessage("uns.historic-events", 0, 5, payload)]
    mapper.run_once()
    _complete_frozen_flush(mapper)
    assert len(store.objects) == 2
    assert first_key in store.objects
