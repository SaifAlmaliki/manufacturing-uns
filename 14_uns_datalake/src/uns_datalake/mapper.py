"""Kafka consumer that batches Historic Events into Parquet object uploads."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from confluent_kafka import KafkaError, TopicPartition

from uns_config.datalake import HistoricEventRecord, historic_event_object_path, new_flush_id, parse_envelope
from uns_datalake.batch import HistoricEventBatch
from uns_datalake.checkpoint import Checkpoint
from uns_datalake.config import DatalakeConfig
from uns_datalake.metrics import DatalakeMetrics
from uns_datalake.parquet import records_to_parquet

LOGGER = logging.getLogger(__name__)

_RETRY_BACKOFFS = (1.0, 2.0)


@dataclass
class _FrozenFlush:
    groups: list[tuple[date, str, list[HistoricEventRecord]]] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    offsets: list[TopicPartition] = field(default_factory=list)
    upload_index: int = 0
    attempts: int = 0
    retry_deadline: float = 0.0
    pending_bytes: bytes | None = None
    had_rows: bool = False


class KafkaLakeMapper:
    def __init__(
        self,
        consumer: Any,
        store: Any,
        config: DatalakeConfig,
        metrics: DatalakeMetrics,
        *,
        clock: Callable[[], float] = time.monotonic,
        serialize: Callable[[list[HistoricEventRecord]], bytes] = records_to_parquet,
    ) -> None:
        self._consumer = consumer
        self._store = store
        self._config = config
        self._metrics = metrics
        self._clock = clock
        self._serialize = serialize
        self._batch = HistoricEventBatch(
            interval_seconds=config.interval_seconds,
            max_bytes=config.max_bytes,
            clock=clock,
            max_records=config.max_records,
        )
        self._checkpoint = Checkpoint()
        self._frozen: _FrozenFlush | None = None
        self._ownership_valid = True
        self._assigned = False
        self._paused = False
        self._closed = False

    def on_assign(self, consumer: Any, partitions: list[TopicPartition]) -> None:
        self._assigned = True
        self._metrics.set_ready(True)

    def on_revoke(self, consumer: Any, partitions: list[TopicPartition]) -> None:
        if self._checkpoint.has_offsets() or self._batch.snapshot() or self._frozen is not None:
            self._ownership_valid = False
        else:
            self._assigned = False
            self._metrics.set_ready(False)

    def on_lost(self, consumer: Any, partitions: list[TopicPartition]) -> None:
        self._ownership_valid = False

    def handle_message(self, msg: Any) -> None:
        self._assert_ownership()
        error = msg.error()
        if error is not None:
            if error.code() == KafkaError._PARTITION_EOF:
                return
            raise RuntimeError(f"kafka message error: {error}")

        raw = msg.value()
        if raw is not None and len(raw) > self._config.max_record_bytes:
            raise RuntimeError("envelope exceeds max_record_bytes")

        topic = msg.topic()
        partition = msg.partition()
        offset = msg.offset()
        record = parse_envelope(raw)
        if record is None:
            LOGGER.warning(
                "poison envelope at %s partition=%s offset=%s",
                topic,
                partition,
                offset,
            )
            self._metrics.record_skip()
        else:
            self._batch.add(record)

        self._checkpoint.observe(topic, partition, offset)

    def tick(self) -> None:
        self._metrics.record_loop()
        self._assert_ownership()

        if self._frozen is None and self._should_freeze():
            self._freeze()

        if self._frozen is not None:
            self._poll_callbacks_only()
            if self._clock() < self._frozen.retry_deadline:
                return
            self._advance_flush_step()
            return

        self._poll_callbacks_only()
        msg = self._consumer.poll(0.5)
        if msg is None:
            return
        if msg.error() is not None and msg.error().code() == KafkaError._PARTITION_EOF:
            return
        self.handle_message(msg)

    def flush_batch(self) -> None:
        self._assert_ownership()
        if self._frozen is None:
            self._freeze(force=True)
        if self._frozen is not None:
            if self._clock() < self._frozen.retry_deadline:
                self._poll_callbacks_only()
                return
            self._advance_flush_step()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._metrics.set_up(False)
        self._metrics.set_ready(False)
        self._consumer.close()

    def _assert_ownership(self) -> None:
        if not self._ownership_valid:
            raise RuntimeError("partition ownership lost")

    def _should_freeze(self, *, force: bool = False) -> bool:
        if force:
            return bool(self._batch.snapshot() or self._checkpoint.has_offsets())
        if self._batch.should_flush():
            return True
        return bool(self._checkpoint.has_offsets() and not self._batch.snapshot())

    def _freeze(self, *, force: bool = False) -> bool:
        if self._frozen is not None:
            return True
        if not self._should_freeze(force=force):
            return False

        records = list(self._batch.snapshot())
        offsets = self._checkpoint.next_offsets()
        if not records and not offsets:
            return False

        grouped: dict[tuple[date, str], list[HistoricEventRecord]] = defaultdict(list)
        for record in records:
            day = record.time.astimezone(UTC).date()
            grouped[(day, record.topic)].append(record)

        groups = sorted(
            [(day, topic, grouped[(day, topic)]) for (day, topic) in grouped],
            key=lambda item: (item[0], item[1]),
        )
        now = datetime.now(UTC)
        keys = [
            historic_event_object_path(event_time=group_records[0].time, topic=topic, flush_id=new_flush_id(now=now))
            for _, topic, group_records in groups
        ]

        if records:
            assignment = self._consumer.assignment()
            if assignment:
                self._consumer.pause(assignment)
                self._paused = True
            self._metrics.set_ready(False)

        self._frozen = _FrozenFlush(
            groups=groups,
            keys=keys,
            offsets=offsets,
            had_rows=bool(records),
        )
        return True

    def _advance_flush_step(self) -> None:
        flush = self._frozen
        if flush is None:
            return

        self._assert_ownership()

        if flush.had_rows and flush.upload_index < len(flush.groups):
            self._upload_current_group(flush)
            return

        self._commit_flush(flush)

    def _upload_current_group(self, flush: _FrozenFlush) -> None:
        if flush.pending_bytes is None:
            _, _, group_records = flush.groups[flush.upload_index]
            try:
                flush.pending_bytes = self._serialize(group_records)
            except Exception as exc:
                raise RuntimeError(f"serialization failed: {exc}") from exc

        key = flush.keys[flush.upload_index]
        try:
            self._store.put(key, flush.pending_bytes)
        except Exception:
            flush.attempts += 1
            self._metrics.record_put_error()
            self._metrics.set_ready(False)
            if flush.attempts >= 3:
                raise RuntimeError("store unavailable after retries")
            backoff = _RETRY_BACKOFFS[min(flush.attempts - 1, len(_RETRY_BACKOFFS) - 1)]
            flush.retry_deadline = self._clock() + backoff
            return

        self._metrics.record_put_success()
        flush.upload_index += 1
        flush.attempts = 0
        flush.pending_bytes = None
        flush.retry_deadline = 0.0

    def _commit_flush(self, flush: _FrozenFlush) -> None:
        self._assert_ownership()
        try:
            result = self._consumer.commit(offsets=flush.offsets, asynchronous=False)
        except Exception as exc:
            self._metrics.record_commit_error()
            raise RuntimeError(f"commit failed: {exc}") from exc

        if result:
            for partition in result:
                if partition.error is not None:
                    self._metrics.record_commit_error()
                    raise RuntimeError(f"partition commit failed: {partition.error}")

        if flush.had_rows:
            self._metrics.record_flush()

        self._batch.take()
        self._checkpoint.clear()
        self._frozen = None

        if self._paused:
            assignment = self._consumer.assignment()
            if assignment:
                self._consumer.resume(assignment)
            self._paused = False

        self._metrics.set_ready(self._assigned)

    def _poll_callbacks_only(self) -> None:
        if self._frozen is not None:
            msg = self._consumer.poll(0.5)
            if msg is not None and msg.error() is None and msg.value() is not None:
                raise RuntimeError("unexpected message while flush frozen")
            return
        self._consumer.poll(0)


def run_forever(mapper: KafkaLakeMapper, stop: Callable[[], bool]) -> None:
    try:
        while not stop():
            mapper.tick()
    finally:
        mapper.close()
