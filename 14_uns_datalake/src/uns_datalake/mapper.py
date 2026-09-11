"""Kafka-to-object-store archival loop for canonical historic events."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from confluent_kafka import Consumer, KafkaError, TopicPartition
from uns_config.events import EnvelopeError, HistoricEventEnvelope, decode_event
from uns_kafka.rejections import DLQ_TOPIC, RejectionRecord, encode_rejection

from uns_datalake import health_check as datalake_health
from uns_datalake.batch import BatchManager, FlushLimits, FrozenPartitionFlush, freeze_partition_records
from uns_datalake.checkpoint import (
    ConsumedPrefix,
    build_commit_partitions,
    inspect_commit_result,
    may_commit_kafka,
)
from uns_datalake.config import DatalakeConfig, FlushLimits as ConfigFlushLimits
from uns_datalake.metrics import (
    ACTIVE_ROUTE_GROUPS,
    ARCHIVE_ROWS,
    BUFFERED_BYTES,
    COMMIT_FAILURE,
    CONSUMER_LAG,
    DECODE_FAILURE,
    DLQ_FAILURE,
    ENCODED_BYTES,
    EVENTS_BUFFERED,
    FLUSH_COUNT,
    FLUSH_DURATION,
    INTEGRITY_FAILURE,
    LAST_LOOP_TIMESTAMP,
    LAST_PUT_TIMESTAMP,
    MAPPER_READY,
    MAPPER_UP,
    OLDEST_UNRESOLVED_AGE,
    PUT_FAILURE,
    REJECTIONS,
    REPLAY_FAILURE,
)
from uns_datalake.replay import ReplayError, choose_start
from uns_datalake.parquet import records_to_parquet
from uns_datalake.publication import FrozenObject, IntegrityError
from uns_datalake.routing import LakeRecord, LegacyRouteMap, resolve_lake_event
from uns_datalake.stores import ObjectStore

LOGGER = logging.getLogger(__name__)

PartitionKey = tuple[str, int]


class FlushPhase(str, Enum):
    ENCODE = "encode"
    PUBLISH = "publish"
    RESOLVE = "resolve"
    COMMIT = "commit"


class ConsumerPort(Protocol):
    def poll(self, timeout: float) -> object | None: ...

    def commit(self, offsets: list[TopicPartition] | None = None, asynchronous: bool = False) -> list[TopicPartition] | None: ...

    def pause(self, partitions: list[TopicPartition]) -> None: ...

    def resume(self, partitions: list[TopicPartition]) -> None: ...

    def assign(self, partitions: list[TopicPartition]) -> None: ...

    def committed(self, partitions: list[TopicPartition], timeout: float) -> list[TopicPartition]: ...

    def get_watermark_offsets(self, partition: TopicPartition, timeout: float) -> tuple[int, int]: ...

    def position(self, partitions: list[TopicPartition]) -> list[TopicPartition]: ...

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


def is_archive_eligible(envelope: HistoricEventEnvelope) -> bool:
    if envelope.schema_version == 2:
        return envelope.archive_eligible is not False
    return True


@dataclass(slots=True)
class DatalakeMapper:
    consumer: ConsumerPort
    store: ObjectStore
    dlq: DlqPublisherPort
    historic_topic: str = DatalakeConfig.historic_topic
    limits: FlushLimits = field(default_factory=lambda: ConfigFlushLimits())
    legacy_map: LegacyRouteMap | None = None
    batch: BatchManager = field(init=False)
    owned_partitions: set[PartitionKey] = field(default_factory=set)
    revoked: bool = False
    ownership_active: bool = False
    generation: int = 0
    consumed_prefixes: dict[PartitionKey, ConsumedPrefix] = field(default_factory=dict)
    frozen_flush: FrozenPartitionFlush | None = None
    frozen_generation: int = 0
    group_index: int = 0
    frozen_object: FrozenObject | None = None
    pending_commit_offset: int | None = None
    pending_rejections: list[PendingRejection] = field(default_factory=list)
    upload_attempts: int = 0
    commit_attempts: int = 0
    monotonic: Callable[[], float] = field(default=time.monotonic)
    sleep: Callable[[float], None] = field(default=time.sleep)
    now: Callable[[], datetime] = field(default_factory=lambda: (lambda: datetime.now(tz=UTC)))

    def __post_init__(self) -> None:
        self.batch = BatchManager(limits=self.limits, monotonic=self.monotonic)

    def _prefix(self, partition_key: PartitionKey) -> ConsumedPrefix:
        if partition_key not in self.consumed_prefixes:
            self.consumed_prefixes[partition_key] = ConsumedPrefix()
        return self.consumed_prefixes[partition_key]

    def _kafka_on_assign(self, _consumer, partitions: Sequence[TopicPartition]) -> None:
        self._assign_with_replay_policy(self.consumer, partitions)

    def _assign_with_replay_policy(self, consumer: ConsumerPort, partitions: Sequence[TopicPartition]) -> None:
        assigned: list[TopicPartition] = []
        timeout = DatalakeConfig.assignment_timeout_seconds
        for part in partitions:
            committed_part = consumer.committed([part], timeout=timeout)[0]
            committed = None if committed_part.offset < 0 else committed_part.offset
            low, high = consumer.get_watermark_offsets(part, timeout=timeout)
            try:
                start = choose_start(committed, low, high, DatalakeConfig.initial_position)
            except ReplayError as exc:
                REPLAY_FAILURE.labels(reason=exc.reason).inc()
                datalake_health.set_replay_failure(exc.reason)
                MAPPER_READY.set(0)
                datalake_health.set_consumer_ready(False)
                raise
            assigned.append(TopicPartition(part.topic, part.partition, start))
        datalake_health.set_replay_failure(None)
        consumer.assign(assigned)
        self.on_assign(assigned)

    def _kafka_on_revoke(self, _consumer, partitions: Sequence[TopicPartition]) -> None:
        self.on_revoke(partitions)

    def on_assign(self, partitions: Sequence[TopicPartition]) -> None:
        self.generation += 1
        self.revoked = False
        self.ownership_active = True
        self.owned_partitions = {(part.topic, part.partition) for part in partitions}
        self.consumed_prefixes = {}
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
        self._revoke_frozen_work()
        if self.batch.total_buffered_bytes() > 0 or self.pending_rejections:
            raise OwnershipLostError("ownership lost with uncommitted lake state")

    def _revoke_frozen_work(self) -> None:
        self.frozen_flush = None
        self.group_index = 0
        self.frozen_object = None
        self.pending_commit_offset = None
        self.upload_attempts = 0
        self.commit_attempts = 0
        assigned = [TopicPartition(topic, part) for topic, part in self.owned_partitions]
        if assigned:
            self.consumer.resume(assigned)

    def start(self) -> None:
        self.consumer.subscribe(
            [self.historic_topic],
            on_assign=self._kafka_on_assign,
            on_revoke=self._kafka_on_revoke,
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
            result = self._advance_frozen_flush()
            self._refresh_observability()
            return result
        self._flush_ready_partitions()
        if not self._try_advance_rejections():
            self._refresh_observability()
            return False
        if self.frozen_flush is not None:
            self._refresh_observability()
            return True
        message = self.consumer.poll(poll_timeout)
        if message is None:
            self._refresh_observability()
            return True
        if hasattr(message, "error") and message.error():
            error = message.error()
            if error.code() == KafkaError._PARTITION_EOF:
                self._refresh_observability()
                return True
            if error.code() == KafkaError._OFFSET_OUT_OF_RANGE:
                REPLAY_FAILURE.labels(reason="offset_out_of_range").inc()
                datalake_health.set_replay_failure("offset_out_of_range")
                MAPPER_READY.set(0)
                datalake_health.set_consumer_ready(False)
                LOGGER.error("Kafka offset out of range: %s", error)
                self._refresh_observability()
                return False
            LOGGER.error("Kafka consumer error: %s", error)
            self._refresh_observability()
            return False
        handled = self._handle_message(message)
        self._refresh_observability()
        return handled

    def _handle_message(self, message) -> bool:
        topic = message.topic()
        partition = message.partition()
        offset = message.offset()
        payload = message.value() or b""
        partition_key = (topic, partition)
        prefix = self._prefix(partition_key)
        prefix.observe(offset)

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

        try:
            resolved = resolve_lake_event(envelope, self.legacy_map)
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

        if not is_archive_eligible(envelope):
            prefix.resolve(offset)
            return self._try_commit_ready_prefix(partition_key)

        record = LakeRecord(
            kafka_topic=topic,
            partition=partition,
            offset=offset,
            resolved=resolved,
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
            self._flush_ready_partitions(force_partition_key=partition_key)
            if not self.batch.try_add(record):
                LOGGER.error("Unable to buffer event at %s[%s]@%s after flush", topic, partition, offset)
                return False
        EVENTS_BUFFERED.inc()
        self._flush_ready_partitions()
        return self._try_advance_rejections()

    def _rejection_blocked(self, rejection: PendingRejection) -> bool:
        partition_key = (rejection.kafka_topic, rejection.partition)
        prefix = self._prefix(partition_key)
        if prefix.has_unresolved_before(rejection.offset):
            return True
        buffer = self.batch.buffers.get(partition_key)
        if buffer is None:
            return False
        return any(record.offset < rejection.offset for record in buffer.records)

    def _try_advance_rejections(self) -> bool:
        remaining: list[PendingRejection] = []
        for rejection in self.pending_rejections:
            if self._rejection_blocked(rejection):
                remaining.append(rejection)
                continue
            if not self._publish_rejection(rejection):
                remaining.append(rejection)
                continue
            partition_key = (rejection.kafka_topic, rejection.partition)
            self._prefix(partition_key).resolve(rejection.offset)
            if not self._try_commit_ready_prefix(partition_key):
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
            REJECTIONS.labels(reason=rejection.reason).inc()
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

    def _try_commit_ready_prefix(self, partition_key: PartitionKey) -> bool:
        if self.frozen_flush is not None:
            return True
        prefix = self._prefix(partition_key)
        next_offset = prefix.next_offset()
        if next_offset is None:
            return True
        if not may_commit_kafka(ownership_active=self.ownership_active, revoked=self.revoked):
            return False
        return self._commit_partition(partition_key, next_offset)

    def _commit_partition(self, partition_key: PartitionKey, next_offset: int) -> bool:
        topic, partition = partition_key
        if not may_commit_kafka(ownership_active=self.ownership_active, revoked=self.revoked):
            return False
        result = self.consumer.commit(
            offsets=[TopicPartition(topic, partition, next_offset)],
            asynchronous=False,
        )
        failures = inspect_commit_result(result)
        if failures:
            COMMIT_FAILURE.inc()
            LOGGER.error("Kafka commit failures: %s", failures)
            return False
        self._prefix(partition_key).discard_committed(next_offset)
        return True

    def _flush_ready_partitions(self, *, force_partition_key: PartitionKey | None = None) -> None:
        while True:
            partition_key = force_partition_key if force_partition_key is not None else self.batch.choose_flush_partition()
            force_partition_key = None
            if partition_key is None:
                return
            buffer = self.batch.pop_partition(partition_key)
            if buffer.is_empty():
                continue
            self._freeze_partition(partition_key, tuple(buffer.records))
            return

    def _freeze_partition(self, partition_key: PartitionKey, records: tuple[LakeRecord, ...]) -> None:
        prefix = self._prefix(partition_key)
        eligible: list[LakeRecord] = []
        for record in records:
            if is_archive_eligible(record.envelope):
                eligible.append(record)
            else:
                prefix.resolve(record.offset)

        flush = freeze_partition_records(partition_key, eligible, now=self.now())
        self.frozen_flush = flush
        self.frozen_generation = self.generation
        self.group_index = 0
        self.frozen_object = None
        self.pending_commit_offset = None
        self.upload_attempts = 0
        self.commit_attempts = 0
        assigned = [TopicPartition(topic, part) for topic, part in self.owned_partitions]
        if assigned:
            self.consumer.pause(assigned)

        if not flush.route_groups and prefix.next_offset() is not None:
            self.pending_commit_offset = prefix.next_offset()

    def _current_group(self):
        assert self.frozen_flush is not None
        return self.frozen_flush.route_groups[self.group_index]

    def _advance_frozen_flush(self) -> bool:
        assert self.frozen_flush is not None
        if self.frozen_generation != self.generation or self.revoked:
            raise OwnershipLostError("ownership lost during frozen flush")

        flush = self.frozen_flush
        partition_key = flush.partition_key

        if self.pending_commit_offset is not None:
            return self._complete_commit(partition_key)

        if self.group_index >= len(flush.route_groups):
            next_offset = self._prefix(partition_key).next_offset()
            if next_offset is None:
                return True
            self.pending_commit_offset = next_offset
            return self._complete_commit(partition_key)

        group = self._current_group()

        if self.frozen_object is None:
            with FLUSH_DURATION.time():
                parquet_bytes = records_to_parquet(group.records, batch_id=flush.flush_id)
            self.frozen_object = FrozenObject.from_bytes(
                group.object_path,
                parquet_bytes,
                row_count=len(group.records),
            )

        with FLUSH_DURATION.time():
            try:
                self.store.publish_exact(
                    self.frozen_object.key,
                    self.frozen_object.data,
                    self.frozen_object.sha256,
                )
                self.store.verify_exact(
                    self.frozen_object.key,
                    self.frozen_object.sha256,
                    len(self.frozen_object.data),
                )
            except IntegrityError:
                INTEGRITY_FAILURE.inc()
                datalake_health.set_integrity_failure(True)
                MAPPER_READY.set(0)
                datalake_health.set_consumer_ready(False)
                LOGGER.error("Integrity failure publishing %s", self.frozen_object.key)
                return False
            except Exception as exc:
                PUT_FAILURE.inc()
                self.upload_attempts += 1
                if self.upload_attempts >= DatalakeConfig.upload_max_attempts:
                    LOGGER.error("Upload failed after retries for %s: %s", group.object_path, exc)
                    return False
                self.sleep((1.0, 2.0)[min(self.upload_attempts - 1, 1)])
                return True

        LAST_PUT_TIMESTAMP.set(time.time())
        FLUSH_COUNT.inc()
        ARCHIVE_ROWS.inc(len(group.records))
        prefix = self._prefix(partition_key)
        for record in group.records:
            prefix.resolve(record.offset)
        self.frozen_object = None
        self.upload_attempts = 0
        self.group_index += 1

        if self.group_index >= len(flush.route_groups):
            next_offset = prefix.next_offset()
            if next_offset is None:
                return True
            self.pending_commit_offset = next_offset
            return self._complete_commit(partition_key)
        return True

    def _complete_commit(self, partition_key: PartitionKey) -> bool:
        assert self.pending_commit_offset is not None
        if not may_commit_kafka(ownership_active=self.ownership_active, revoked=self.revoked):
            raise OwnershipLostError("ownership lost after upload but before commit")
        if self.frozen_generation != self.generation:
            raise OwnershipLostError("ownership generation changed before commit")

        next_offset = self.pending_commit_offset
        partitions = build_commit_partitions({partition_key: next_offset})
        result = self.consumer.commit(offsets=partitions, asynchronous=False)
        failures = inspect_commit_result(result)
        if failures:
            COMMIT_FAILURE.inc()
            self.commit_attempts += 1
            LOGGER.error("Commit failed after upload: %s", failures)
            return True

        self._prefix(partition_key).discard_committed(next_offset)
        self.frozen_flush = None
        self.group_index = 0
        self.frozen_object = None
        self.pending_commit_offset = None
        self.upload_attempts = 0
        self.commit_attempts = 0
        assigned = [TopicPartition(topic, part) for topic, part in self.owned_partitions]
        if assigned:
            self.consumer.resume(assigned)
        return self._try_advance_rejections()

    def _refresh_observability(self) -> None:
        BUFFERED_BYTES.set(self.batch.total_buffered_bytes())
        ENCODED_BYTES.set(len(self.frozen_object.data) if self.frozen_object is not None else 0)

        active_groups = sum(len(buffer.route_groups) for buffer in self.batch.buffers.values())
        if self.frozen_flush is not None:
            active_groups += len(self.frozen_flush.route_groups)
        ACTIVE_ROUTE_GROUPS.set(active_groups)

        OLDEST_UNRESOLVED_AGE.set(self._oldest_unresolved_age_seconds())
        if hasattr(self.consumer, "get_watermark_offsets") and hasattr(self.consumer, "position"):
            CONSUMER_LAG.set(self._consumer_lag())
        else:
            CONSUMER_LAG.set(0.0)

    def _oldest_unresolved_age_seconds(self) -> float:
        if not self.pending_rejections and self.batch.total_buffered_bytes() == 0 and self.frozen_flush is None:
            return 0.0

        now = self.monotonic()
        oldest: float | None = None
        for buffer in self.batch.buffers.values():
            if buffer.started_at is not None:
                oldest = buffer.started_at if oldest is None else min(oldest, buffer.started_at)
        if self.pending_rejections:
            rejection_age = now
            oldest = rejection_age if oldest is None else min(oldest, rejection_age)
        if self.frozen_flush is not None:
            frozen_age = now
            oldest = frozen_age if oldest is None else min(oldest, frozen_age)
        if oldest is None:
            return 0.0
        return max(0.0, now - oldest)

    def _consumer_lag(self) -> float:
        if not self.owned_partitions:
            return 0.0
        total_lag = 0.0
        timeout = DatalakeConfig.assignment_timeout_seconds
        for topic, partition in self.owned_partitions:
            tp = TopicPartition(topic, partition)
            try:
                _low, high = self.consumer.get_watermark_offsets(tp, timeout=timeout)
                positions = self.consumer.position([tp])
                current = positions[0].offset if positions else high
                if current < 0:
                    current = high
                total_lag += max(0, high - current)
            except Exception:
                continue
        return total_lag

    def freeze_partition_for_test(self, partition_key: PartitionKey) -> None:
        buffer = self.batch.buffers.get(partition_key)
        if buffer is None or buffer.is_empty():
            raise ValueError(f"partition {partition_key} has no buffered records")
        popped = self.batch.pop_partition(partition_key)
        self._freeze_partition(partition_key, tuple(popped.records))


class DlqPublisher:
    def __init__(self, producer) -> None:
        self._producer = producer
        self.messages: list[tuple[str, bytes, bytes]] = []

    def publish(self, *, topic: str, key: bytes, value: bytes) -> None:
        delivery_errors: list[Exception] = []

        def on_delivery(err: Exception | None, _msg: object | None) -> None:
            if err is not None:
                delivery_errors.append(err)

        self.messages.append((topic, key, value))
        self._producer.produce(topic, key=key, value=value, callback=on_delivery)
        remaining = self._producer.flush(timeout=5.0)
        if remaining > 0:
            raise TimeoutError(f"DLQ flush timeout with {remaining} messages pending")
        if delivery_errors:
            raise delivery_errors[0]


def build_mapper(*, store: ObjectStore | None = None) -> DatalakeMapper:
    consumer = Consumer(DatalakeConfig.kafka_consumer_config())
    from confluent_kafka import Producer

    producer = Producer(
        {"bootstrap.servers": DatalakeConfig.kafka_consumer_config().get("bootstrap.servers", "localhost:9092")}
    )
    if store is None:
        from uns_datalake.stores import object_store_from_config

        store = object_store_from_config()
    return DatalakeMapper(
        consumer=consumer,
        store=store,
        dlq=DlqPublisher(producer),
        legacy_map=DatalakeConfig.legacy_route_map(),
    )
