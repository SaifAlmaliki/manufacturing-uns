import json
from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock

import pyarrow.parquet as pq
import pytest
from confluent_kafka import TopicPartition

from uns_datalake.config import DatalakeConfig
from uns_datalake.mapper import KafkaLakeMapper


class FakeMsg:
    def __init__(self, value, offset, partition=0):
        self._value, self._offset, self._partition = value, offset, partition

    def value(self):
        return self._value

    def error(self):
        return None

    def topic(self):
        return "uns.historic-events"

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset


def event(offset, *, partition=0, topic="Acme/Line/Temp", time="2026-09-08T12:00:00Z"):
    return FakeMsg(json.dumps({"time": time, "topic": topic, "payload": {"v": offset}}).encode(), offset, partition)


def harness(**overrides):
    log, objects, now = [], {}, [0.0]
    consumer, store, metrics = Mock(), Mock(), Mock()
    consumer.poll.return_value = None
    consumer.assignment.return_value = [TopicPartition("uns.historic-events", 0), TopicPartition("uns.historic-events", 1)]

    def put(key, data):
        log.append(("put", key))
        objects[key] = data

    def commit(*, offsets, asynchronous):
        assert asynchronous is False
        log.append(("commit", {(p.partition, p.offset) for p in offsets}))
        return offsets

    store.put.side_effect, consumer.commit.side_effect = put, commit
    config = replace(DatalakeConfig(), **overrides)
    mapper = KafkaLakeMapper(consumer, store, config, metrics, clock=lambda: now[0])
    mapper.on_assign(consumer, consumer.assignment())
    return mapper, consumer, store, metrics, log, objects, now


def finish_flush(mapper, consumer):
    before = consumer.commit.call_count
    for _ in range(20):
        mapper.flush_batch()
        if consumer.commit.call_count > before:
            return
    pytest.fail("flush did not reach commit")


def test_poison_cannot_commit_past_buffered_valid_event():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.handle_message(FakeMsg(b"bad-json", 11))
    consumer.commit.assert_not_called()
    finish_flush(mapper, consumer)
    assert [kind for kind, _ in log] == ["put", "commit"]
    assert log[-1][1] == {(0, 12)}


def test_poison_only_commits_without_object():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(FakeMsg(None, 7))
    mapper.tick()
    store.put.assert_not_called()
    assert log == [("commit", {(0, 8)})]


def test_mixed_dates_topics_and_partitions_put_before_explicit_commit():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10, time="2026-09-08T23:59:59Z"))
    mapper.handle_message(event(11, time="2026-09-09T00:00:01Z"))
    mapper.handle_message(event(40, partition=1, topic="Acme/Line/Pressure", time="2026-09-09T00:30:00+02:00"))
    finish_flush(mapper, consumer)
    assert len(objects) == 3
    assert log[-1] == ("commit", {(0, 12), (1, 41)})
    for key, data in objects.items():
        rows = pq.read_table(BytesIO(data)).to_pylist()
        assert len({row["topic"] for row in rows}) == 1
        assert all(key.startswith(f"dt={row['time'].date().isoformat()}/") for row in rows)


def test_second_object_failure_keeps_first_and_defers_all_offsets():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.handle_message(event(11, topic="z"))
    good_put = store.put.side_effect
    attempts = []

    def fail_second_once(key, data):
        attempts.append(key)
        if len(attempts) == 2:
            raise RuntimeError("store unavailable")
        good_put(key, data)

    store.put.side_effect = fail_second_once
    mapper.flush_batch()
    mapper.flush_batch()
    consumer.commit.assert_not_called()
    assert len(objects) == 1
    mapper.tick()
    assert len(attempts) == 2
    consumer.pause.assert_called()
    consumer.poll.assert_called()
    now[0] = 1.0
    finish_flush(mapper, consumer)
    assert attempts[1] == attempts[2]
    assert len(objects) == 2
    assert log[-1] == ("commit", {(0, 12)})


def test_commit_failure_exits_after_put_without_reupload():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()
    consumer.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        mapper.flush_batch()
    assert len(objects) == 1
    assert store.put.call_count == 1


def test_two_explicit_flushes_create_two_keys():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    finish_flush(mapper, consumer)
    mapper.handle_message(event(11))
    finish_flush(mapper, consumer)
    assert len(objects) == 2
    assert consumer.commit.call_count == 2


@pytest.mark.parametrize("callback", ["on_revoke", "on_lost"])
def test_ownership_loss_never_commits_buffered_data(callback):
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    getattr(mapper, callback)(consumer, consumer.assignment())
    with pytest.raises(RuntimeError):
        mapper.tick()
    consumer.commit.assert_not_called()


def test_retry_exhaustion_is_bounded_and_never_commits():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    store.put.side_effect = RuntimeError("store down")
    mapper.flush_batch()
    now[0] = 1.0
    mapper.tick()
    now[0] = 3.0
    with pytest.raises(RuntimeError):
        mapper.tick()
    assert store.put.call_count == 3
    consumer.commit.assert_not_called()


def test_shutdown_abandons_uncommitted_batch_for_replay():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.close()
    store.put.assert_not_called()
    consumer.commit.assert_not_called()
    consumer.close.assert_called_once()


def test_idle_poll_flushes_after_interval():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.tick()
    store.put.assert_not_called()
    now[0] = 60.0
    mapper.tick()
    mapper.tick()
    assert log[-1] == ("commit", {(0, 11)})


def test_oversize_valid_envelope_exits_without_skipping():
    mapper, consumer, store, metrics, log, objects, now = harness(max_record_bytes=10)
    with pytest.raises(RuntimeError):
        mapper.handle_message(event(10))
    consumer.commit.assert_not_called()


def test_per_partition_commit_error_is_not_success():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()
    consumer.commit.side_effect = None
    consumer.commit.return_value = [Mock(error=RuntimeError("partition commit failed"))]
    with pytest.raises(RuntimeError):
        mapper.flush_batch()
    assert store.put.call_count == 1


def test_serialization_failure_never_commits():
    mapper, consumer, store, metrics, log, objects, now = harness()
    broken = Mock(side_effect=ValueError("serialization failed"))
    mapper = KafkaLakeMapper(consumer, store, DatalakeConfig(), metrics, clock=lambda: now[0], serialize=broken)
    mapper.on_assign(consumer, consumer.assignment())
    mapper.handle_message(event(10))
    with pytest.raises(RuntimeError):
        mapper.flush_batch()
    store.put.assert_not_called()
    consumer.commit.assert_not_called()


def test_crash_after_put_replays_without_losing_event():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()
    mapper.close()
    consumer.commit.assert_not_called()
    replay = KafkaLakeMapper(consumer, store, DatalakeConfig(), metrics, clock=lambda: now[0])
    replay.on_assign(consumer, consumer.assignment())
    replay.handle_message(event(10))
    finish_flush(replay, consumer)
    assert len(objects) == 2
    rows = [row for data in objects.values() for row in pq.read_table(BytesIO(data)).to_pylist()]
    assert {json.loads(row["payload"])["v"] for row in rows} == {10}
    assert log[-1] == ("commit", {(0, 11)})


@pytest.mark.parametrize("limits", [{"max_bytes": 1}, {"max_records": 1}])
def test_size_or_count_threshold_pauses_before_more_data(limits):
    mapper, consumer, store, metrics, log, objects, now = harness(**limits)
    mapper.handle_message(event(10))
    mapper.tick()
    consumer.pause.assert_called_once()
    store.put.assert_called_once()
    mapper.tick()
    assert log[-1] == ("commit", {(0, 11)})


def test_unexpected_delivery_while_frozen_fails_closed():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()
    consumer.poll.return_value = event(11)
    with pytest.raises(RuntimeError):
        mapper.tick()
    consumer.commit.assert_not_called()


def test_kafka_message_error_exits_without_commit():
    mapper, consumer, store, metrics, log, objects, now = harness()
    msg = Mock()
    msg.error.return_value.code.return_value = -1
    with pytest.raises(RuntimeError):
        mapper.handle_message(msg)
    consumer.commit.assert_not_called()
