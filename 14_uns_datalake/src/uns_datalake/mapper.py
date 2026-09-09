"""Kafka-to-object-store archival loop for canonical historic events."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from confluent_kafka import Consumer, KafkaError, TopicPartition
from uns_config.events import EnvelopeError, decode_event
from uns_kafka.rejections import DLQ_TOPIC, RejectionRecord, encode_rejection

from uns_datalake import health_check as datalake_health
from uns_datalake.batch import (
    BatchManager,
    FlushLimits,
    FrozenPartitionFlush,
    LakeRecord,
    lake_object_path,
    new_flush_id,
)
from uns_datalake.checkpoint import build_commit_partitions, inspect_commit_result, may_commit_kafka, next_offsets_for_records
from uns_datalake.config import DatalakeConfig, FlushLimits as ConfigFlushLimits
from uns_datalake.metrics import (
    COMMIT_FAILURE,
    DECODE_FAILURE,
    DLQ_FAILURE,
    EVENTS_BUFFERED,
    FLUSH_COUNT,
    FLUSH_DURATION,
    LAST_LOOP_TIMESTAMP,
    LAST_PUT_TIMESTAMP,
    MAPPER_READY,
    MAPPER_UP,
    PUT_FAILURE,
)
from uns_datalake.parquet import records_to_parquet
from uns_datalake.stores import ObjectStore

LOGGER = logging.getLogger(__name__)


class ConsumerPort(Protocol):
    def poll(self, timeout: float) -> object | None: ...

    def commit(self, offsets: list[TopicPartition] | None = None, asynchronous: bool = False) -> list[TopicPartition] | None: ...

    def pause(self, partitions: list[TopicPartition]) -> None: ...

    def resume(self, partitions: list[TopicPartition]) -> None: ...

    def subscribe(self, topics: list[str], on_assign, on_revoke) -> None: ...

    def close(self) -> None: ...


class DlqPublisherPort(Protocol):
    def publish(self, *, topic: str, key: bytes, value: bytes) -> None: ...


class OwnershipLostError(RuntimeError):
    """Consumer ownership was revoked while uncommitted records were buffered."""


@dataclass(slots=True)
class PendingRejection:
    kafka_topic: str
    partition: int
    offset: int
    payload: bytes
    reason: str


@dataclass(slots=True)
class DatalakeMapper:
    consumer: ConsumerPort
    store: ObjectStore
    dlq: DlqPublisherPort
    historic_topic: str = DatalakeConfig.historic_topic
    limits: FlushLimits = field(default_factory=lambda: ConfigFlushLimits())
    batch: BatchManager = field(init=False)
    owned_partitions: set[tuple[str, int]] = field(default_factory=set)
    revoked: bool = False
    ownership_active: bool = False
    frozen_flush: FrozenPartitionFlush | None = None
    frozen_next_offsets: dict[tuple[str, int], int] = field(default_factory=dict)
    pending_rejections: list[PendingRejection] = field(default_factory=list)
    upload_attempts: int = 0
    monotonic: Callable[[], float] = field(default=time.monotonic)
    sleep: Callable[[float], None] = field(default=time.sleep)
    now: Callable[[], datetime] = field(default_factory=lambda: (lambda: datetime.now(tz=UTC)))

    def __post_init__(self) -> None:
        self.batch = BatchManager(limits=self.limits, monotonic=self.monotonic)

    def on_assign(self, partitions: Sequence[TopicPartition]) -> None:
        self.revoked = False
        self.ownership_active = True
        self.owned_partitions = {(part.topic, part.partition) for part in partitions}
        MAPPER_READY.set(1)
        datalake_health.set_consumer_ready(True)

    def on_revoke(self, partitions: Sequence[TopicPartition]) -> None:
        revoked_keys = {(part.topic, part.partition) for part in partitions}
        self.owned_partitions -= revoked_keys
        if not self.owned_partitions:
            self.ownership_active = False
            MAPPER_READY.set(0)
            datalake_health.set_consumer_ready(False)
        self.revoked = True
        if self.batch.total_buffered_bytes() > 0 or self.frozen_flush is not None or self.pending_rejections:
            raise OwnershipLostError("ownership lost with uncommitted lake state")

    def start(self) -> None:
        self.consumer.subscribe(
            [self.historic_topic],
            on_assign=self.on_assign,
            on_revoke=self.on_revoke,
        )
        MAPPER_UP.set(1)

    def stop(self) -> None:
        self.consumer.close()
        MAPPER_UP.set(0)
        MAPPER_READY.set(0)
        datalake_health.set_consumer_ready(False)

    def run_once(self, *, poll_timeout: float = DatalakeConfig.consumer_poll_timeout) -> bool:
        datalake_health.touch_heartbeat()
        LAST_LOOP_TIMESTAMP.set(time.time())
        if self.frozen_flush is not None:
            return self._complete_frozen_flush()
        self._flush_ready_partitions()
        self._try_advance_rejections()
        message = self.consumer.poll(poll_timeout)
        if message is None:
            return True
        if hasattr(message, "error") and message.error():
            error = message.error()
            if error.code() == KafkaError._PARTITION_EOF:
                return True
            LOGGER.error("Kafka consumer error: %s", error)
            return False
        return self._handle_message(message)

    def _handle_message(self, message) -> bool:
        topic = message.topic()
        partition = message.partition()
        offset = message.offset()
        payload = message.value() or b""
        try:
            envelope = decode_event(payload)
        except EnvelopeError as exc:
            DECODE_FAILURE.labels(reason=exc.reason).inc()
            self.pending_rejections.append(
                PendingRejection(
                    kafka_topic=topic,
                    partition=partition,
                    offset=offset,
                    payload=payload,
                    reason=exc.reason,
                )
            )
            return self._try_advance_rejections()

        record = LakeRecord(
            kafka_topic=topic,
            partition=partition,
            offset=offset,
            envelope=envelope,
            envelope_bytes=payload,
        )
        try:
            accepted = self.batch.try_add(record)
        except ValueError:
            self.pending_rejections.append(
                PendingRejection(
                    kafka_topic=topic,
                    partition=partition,
                    offset=offset,
                    payload=payload,
                    reason="oversize",
                )
            )
            return self._try_advance_rejections()
        if not accepted:
            self._flush_ready_partitions(force_partition=partition)
            if not self.batch.try_add(record):
                LOGGER.error("Unable to buffer event at %s[%s]@%s after flush", topic, partition, offset)
                return False
        EVENTS_BUFFERED.inc()
        self._flush_ready_partitions()
        return self._try_advance_rejections()

    def _buffer_has_earlier_offset(self, rejection: PendingRejection) -> bool:
        buffer = self.batch.buffers.get(rejection.partition)
        if buffer is None:
            return False
        return any(record.offset < rejection.offset for record in buffer.records)

    def _try_advance_rejections(self) -> bool:
        remaining: list[PendingRejection] = []
        for rejection in self.pending_rejections:
            if self._buffer_has_earlier_offset(rejection):
                remaining.append(rejection)
                continue
            if not self._publish_rejection(rejection):
                remaining.append(rejection)
                continue
            if not self._commit_single_offset(rejection.kafka_topic, rejection.partition, rejection.offset):
                remaining.append(rejection)
        self.pending_rejections = remaining
        return True

    def _publish_rejection(self, rejection: PendingRejection) -> bool:
        record = RejectionRecord(
            stage="datalake",
            origin="uns_datalake",
            reason=rejection.reason,
            captured_at=self.now(),
            topic=rejection.kafka_topic,
            original_bytes=rejection.payload[:65_536],
        )
        try:
            self.dlq.publish(
                topic=DLQ_TOPIC,
                key=rejection.kafka_topic.encode("utf-8"),
                value=encode_rejection(record),
            )
            return True
        except Exception as exc:
            DLQ_FAILURE.inc()
            LOGGER.error(
                "Failed to publish rejection for %s[%s]@%s: %s",
                rejection.kafka_topic,
                rejection.partition,
                rejection.offset,
                exc,
            )
            return False

    def _commit_single_offset(self, topic: str, partition: int, offset: int) -> bool:
        if not may_commit_kafka(ownership_active=self.ownership_active, revoked=self.revoked):
            return False
        result = self.consumer.commit(
            offsets=[TopicPartition(topic, partition, offset + 1)],
            asynchronous=False,
        )
        failures = inspect_commit_result(result)
        if failures:
            COMMIT_FAILURE.inc()
            LOGGER.error("Kafka commit failures: %s", failures)
            return False
        return True

    def _flush_ready_partitions(self, *, force_partition: int | None = None) -> None:
        while True:
            partition = force_partition if force_partition is not None else self.batch.choose_flush_partition()
            force_partition = None
            if partition is None:
                return
            buffer = self.batch.pop_partition(partition)
            if buffer.is_empty():
                continue
            self._freeze_partition(partition, tuple(buffer.records))
            return

    def _freeze_partition(self, partition: int, records: tuple[LakeRecord, ...]) -> None:
        instant = self.now()
        flush_id = new_flush_id(now=instant)
        parquet_bytes = records_to_parquet([record.envelope for record in records])
        object_path = lake_object_path(
            ingest_date=instant.date(),
            ingest_hour=instant.hour,
            partition=partition,
            flush_id=flush_id,
        )
        self.frozen_flush = FrozenPartitionFlush(
            partition=partition,
            ingest_date=instant.date(),
            ingest_hour=instant.hour,
            flush_id=flush_id,
            records=records,
            parquet_bytes=parquet_bytes,
            object_path=object_path,
        )
        self.frozen_next_offsets = next_offsets_for_records(records)
        self.upload_attempts = 0
        assigned = [TopicPartition(topic, part) for topic, part in self.owned_partitions]
        if assigned:
            self.consumer.pause(assigned)

    def _complete_frozen_flush(self) -> bool:
        assert self.frozen_flush is not None
        flush = self.frozen_flush
        with FLUSH_DURATION.time():
            try:
                self.store.put(flush.object_path, flush.parquet_bytes)
            except Exception as exc:
                PUT_FAILURE.inc()
                self.upload_attempts += 1
                if self.upload_attempts >= DatalakeConfig.upload_max_attempts:
                    LOGGER.error("Upload failed after retries for %s: %s", flush.object_path, exc)
                    return False
                self.sleep((1.0, 2.0)[min(self.upload_attempts - 1, 1)])
                return True
        LAST_PUT_TIMESTAMP.set(time.time())
        FLUSH_COUNT.inc()
        if not may_commit_kafka(ownership_active=self.ownership_active, revoked=self.revoked):
            raise OwnershipLostError("ownership lost after upload but before commit")
        partitions = build_commit_partitions(self.frozen_next_offsets)
        result = self.consumer.commit(offsets=partitions, asynchronous=False)
        failures = inspect_commit_result(result)
        if failures:
            COMMIT_FAILURE.inc()
            LOGGER.error("Commit failed after upload for %s: %s", flush.object_path, failures)
            return False
        self.frozen_flush = None
        self.frozen_next_offsets = {}
        self.upload_attempts = 0
        assigned = [TopicPartition(topic, part) for topic, part in self.owned_partitions]
        if assigned:
            self.consumer.resume(assigned)
        return self._try_advance_rejections()

    def freeze_partition_for_test(self, partition: int) -> None:
        buffer = self.batch.buffers.get(partition)
        if buffer is None or buffer.is_empty():
            raise ValueError(f"partition {partition} has no buffered records")
        popped = self.batch.pop_partition(partition)
        self._freeze_partition(partition, tuple(popped.records))


class DlqPublisher:
    def __init__(self, producer) -> None:
        self._producer = producer
        self.messages: list[tuple[str, bytes, bytes]] = []

    def publish(self, *, topic: str, key: bytes, value: bytes) -> None:
        self.messages.append((topic, key, value))
        self._producer.produce(topic, key=key, value=value)
        self._producer.flush(timeout=5.0)


def build_mapper(*, store: ObjectStore | None = None) -> DatalakeMapper:
    consumer = Consumer(DatalakeConfig.kafka_consumer_config())
    from confluent_kafka import Producer

    producer = Producer(
        {"bootstrap.servers": DatalakeConfig.kafka_consumer_config().get("bootstrap.servers", "localhost:9092")}
    )
    if store is None:
        from uns_datalake.stores import object_store_from_config

        store = object_store_from_config()
    return DatalakeMapper(consumer=consumer, store=store, dlq=DlqPublisher(producer))
