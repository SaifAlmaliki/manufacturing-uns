"""Multi-route mapper lifecycle, DLQ confirmation, and ownership fencing tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from confluent_kafka import TopicPartition

from uns_datalake.batch import FlushLimits
from uns_datalake.mapper import DatalakeMapper, OwnershipLostError
from uns_datalake.stores import FakeObjectStore
from conftest import lake_record_from_envelope, legacy_route_map, v2_envelope


@dataclass
class FakeMessage:
    _topic: str
    _partition: int
    _offset: int
    _value: bytes

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


def _commit_offsets(consumer: FakeConsumer) -> list[list[tuple[str, int, int]]]:
    return [[(part.topic, part.partition, part.offset) for part in batch] for batch in consumer.commits]


@dataclass
class FakeConsumer:
    messages: list[FakeMessage] = field(default_factory=list)
    commits: list[list[TopicPartition]] = field(default_factory=list)
    paused: list[TopicPartition] = field(default_factory=list)
    fail_commits: set[int] = field(default_factory=set)
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
        items = list(offsets or [])
        for item in items:
            if item.offset in self.fail_commits:
                failed = MagicMock()
                failed.partition = item.partition
                failed.error = MagicMock(code=MagicMock(return_value=42))
                return [failed]
        self.commits.append(items)
        return []

    def close(self):
        pass


class FakeDlq:
    def __init__(self):
        self.messages: list[tuple[str, bytes, bytes]] = []
        self.fail = False

    def publish(self, *, topic: str, key: bytes, value: bytes) -> None:
        if self.fail:
            raise RuntimeError("dlq unavailable")
        self.messages.append((topic, key, value))


def _lims_record(offset: int, *, partition: int = 0) -> object:
    return lake_record_from_envelope(
        v2_envelope(source_application="lims", source_sequence=offset),
        partition=partition,
        offset=offset,
        envelope_bytes=b"lims" + bytes([offset]),
    )


def _mes_record(offset: int, *, partition: int = 0) -> object:
    return lake_record_from_envelope(
        v2_envelope(
            source_application="mes",
            payload_schema_id="production-order",
            original_payload=b'{"order":"x"}',
            source_sequence=offset,
        ),
        partition=partition,
        offset=offset,
        envelope_bytes=b"mes" + bytes([offset]),
    )


def _test_limits(**overrides) -> FlushLimits:
    defaults = {
        "max_records": 10,
        "max_bytes": 8_388_608,
        "max_record_bytes": 1_048_576,
        "interval_seconds": 60,
        "worker_max_buffered_bytes": 32 * 1024 * 1024,
    }
    defaults.update(overrides)
    return FlushLimits(**defaults)


def _mapper(
    tmp_path: Path,
    *,
    limits: FlushLimits | None = None,
    consumer: FakeConsumer | None = None,
) -> tuple[DatalakeMapper, FakeConsumer, FakeObjectStore, FakeDlq]:
    consumer = consumer or FakeConsumer()
    store = FakeObjectStore(root=tmp_path)
    dlq = FakeDlq()
    mapper = DatalakeMapper(
        consumer=consumer,
        store=store,
        dlq=dlq,
        limits=limits or _test_limits(),
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )
    mapper.on_assign([TopicPartition("uns.historic-events", 0, 0)])
    return mapper, consumer, store, dlq


def _buffer_three_route_records(mapper: DatalakeMapper) -> None:
    topic = "uns.historic-events"
    partition_key = (topic, 0)
    for record in (_lims_record(10), _mes_record(12), _lims_record(15)):
        mapper._prefix(partition_key).observe(record.offset)
        assert mapper.batch.try_add(record)


def test_multi_route_flush_resolves_lims_before_mes_and_commits_after_both(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(tmp_path)
    _buffer_three_route_records(mapper)
    mapper.freeze_partition_for_test(("uns.historic-events", 0))

    assert len(mapper.frozen_flush.route_groups) == 2
    lims_group = next(g for g in mapper.frozen_flush.route_groups if g.route.application == "lims")
    mes_group = next(g for g in mapper.frozen_flush.route_groups if g.route.application == "mes")
    assert [record.offset for record in lims_group.records] == [10, 15]
    assert [record.offset for record in mes_group.records] == [12]

    assert mapper.run_once()
    assert lims_group.object_path in store.objects
    assert mes_group.object_path not in store.objects
    assert consumer.commits == []

    store.fail_paths.add(mes_group.object_path)
    assert mapper.run_once()
    assert consumer.commits == []

    store.fail_paths.clear()
    assert mapper.run_once()
    assert mes_group.object_path in store.objects
    assert mapper.run_once()
    assert _commit_offsets(consumer) == [[("uns.historic-events", 0, 16)]]


def test_commit_failure_keeps_resolved_ledger_without_reencoding(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(tmp_path, consumer=FakeConsumer(fail_commits={16}))
    _buffer_three_route_records(mapper)
    mapper.freeze_partition_for_test(("uns.historic-events", 0))

    while mapper.pending_commit_offset is None:
        assert mapper.run_once()

    mes_group = next(g for g in mapper.frozen_flush.route_groups if g.route.application == "mes")
    mes_bytes = store.objects[mes_group.object_path]
    encoded_bytes = mapper.frozen_object.data if mapper.frozen_object is not None else mes_bytes

    assert mapper.run_once()
    assert consumer.commits == []
    assert mapper.pending_commit_offset == 16
    assert mapper.frozen_object is None or mapper.frozen_object.data == encoded_bytes

    consumer.fail_commits.clear()
    assert mapper.run_once()
    assert _commit_offsets(consumer) == [[("uns.historic-events", 0, 16)]]
    assert store.objects[mes_group.object_path] == mes_bytes


def test_ownership_revoked_during_flush_does_not_commit(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(tmp_path)
    _buffer_three_route_records(mapper)
    mapper.freeze_partition_for_test(("uns.historic-events", 0))

    assert mapper.run_once()
    mapper.revoked = True
    mapper.ownership_active = False
    with pytest.raises(OwnershipLostError):
        mapper.run_once()
    assert consumer.commits == []


def test_archive_eligible_false_resolves_without_lake_write(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(tmp_path)
    topic = "uns.historic-events"
    partition_key = (topic, 0)
    eligible = _lims_record(10)
    excluded = lake_record_from_envelope(
        v2_envelope(source_application="mes", archive_eligible=False, source_sequence=11),
        partition=0,
        offset=11,
        envelope_bytes=b"excluded",
    )
    mapper._prefix(partition_key).observe(10)
    mapper._prefix(partition_key).observe(11)
    assert mapper.batch.try_add(eligible)
    assert mapper.batch.try_add(excluded)
    mapper.freeze_partition_for_test(partition_key)

    assert len(mapper.frozen_flush.route_groups) == 1
    assert mapper.run_once()
    assert mapper.run_once()
    assert len(store.objects) == 1
    assert _commit_offsets(consumer) == [[("uns.historic-events", 0, 12)]]


def test_exclusion_cannot_advance_past_unresolved_upload(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(tmp_path)
    topic = "uns.historic-events"
    partition_key = (topic, 0)
    eligible = _mes_record(10)
    excluded = lake_record_from_envelope(
        v2_envelope(source_application="lims", archive_eligible=False, source_sequence=12),
        partition=0,
        offset=12,
        envelope_bytes=b"excluded",
    )
    mapper._prefix(partition_key).observe(10)
    mapper._prefix(partition_key).observe(12)
    assert mapper.batch.try_add(eligible)
    assert mapper.batch.try_add(excluded)
    mapper.freeze_partition_for_test(partition_key)

    mes_group = mapper.frozen_flush.route_groups[0]
    store.fail_paths.add(mes_group.object_path)
    assert mapper.run_once()
    assert mapper.run_once()
    assert consumer.commits == []


def test_unknown_envelope_version_goes_to_dlq_after_prefix_unblocks(tmp_path: Path):
    mapper, consumer, _store, dlq = _mapper(tmp_path)
    consumer.messages = [
        FakeMessage("uns.historic-events", 0, 0, b'{"schema_version":99}'),
    ]
    assert mapper.run_once()
    assert dlq.messages
    assert _commit_offsets(consumer) == [[("uns.historic-events", 0, 1)]]


def test_missing_legacy_route_goes_to_dlq(tmp_path: Path):
    mapper, consumer, _store, dlq = _mapper(tmp_path)
    from conftest import envelope_bytes

    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, envelope_bytes())]
    assert mapper.run_once()
    assert dlq.messages
    assert _commit_offsets(consumer) == [[("uns.historic-events", 0, 1)]]


def test_dlq_unavailable_does_not_resolve_or_commit(tmp_path: Path):
    mapper, consumer, _store, dlq = _mapper(tmp_path)
    dlq.fail = True
    consumer.messages = [FakeMessage("uns.historic-events", 0, 0, b"not-json")]
    assert mapper.run_once()
    assert dlq.messages == []
    assert consumer.commits == []


def test_mixed_topics_with_equal_partition_ids_are_isolated(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(tmp_path)
    mapper.on_assign(
        [
            TopicPartition("uns.historic-events", 0, 0),
            TopicPartition("uns.other-events", 0, 0),
        ]
    )
    topic_a = "uns.historic-events"
    topic_b = "uns.other-events"
    record_a = lake_record_from_envelope(
        v2_envelope(source_application="lims"),
        kafka_topic=topic_a,
        partition=0,
        offset=1,
        envelope_bytes=b"a",
    )
    record_b = lake_record_from_envelope(
        v2_envelope(source_application="mes", payload_schema_id="production-order"),
        kafka_topic=topic_b,
        partition=0,
        offset=1,
        envelope_bytes=b"b",
    )
    mapper._prefix((topic_a, 0)).observe(1)
    mapper._prefix((topic_b, 0)).observe(1)
    assert mapper.batch.try_add(record_a)
    assert mapper.batch.try_add(record_b)
    mapper.freeze_partition_for_test((topic_a, 0))
    assert mapper.run_once()
    assert len(store.objects) == 1
    assert ("uns.other-events", 0) in mapper.batch.buffers
    assert mapper.frozen_flush is None


def test_upload_retry_reuses_frozen_bytes(tmp_path: Path):
    mapper, consumer, store, _dlq = _mapper(
        tmp_path,
        limits=_test_limits(max_records=1),
    )
    consumer.messages = [
        FakeMessage(
            "uns.historic-events",
            0,
            0,
            lake_record_from_envelope(v2_envelope()).envelope_bytes,
        )
    ]
    mapper.run_once()
    path = mapper.frozen_flush.route_groups[0].object_path
    store.fail_paths.add(path)
    assert mapper.run_once()
    frozen_bytes = mapper.frozen_object.data
    assert consumer.commits == []
    store.fail_paths.clear()
    assert mapper.run_once()
    assert store.objects[path] == frozen_bytes
