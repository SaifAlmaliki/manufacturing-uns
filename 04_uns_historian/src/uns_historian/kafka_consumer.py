"""Kafka historian consumer loop with SQL-authoritative checkpoints."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from confluent_kafka import Consumer, KafkaError, TopicPartition
from uns_config.events import EnvelopeError, decode_event
from uns_model.engine import Database
from uns_model.notifications import AssetModelChangeListener
from uns_model.repositories import AssetModelRepository
from uns_model.topic_binder import TopicBinder

from uns_historian import health_check as historian_health
from uns_historian.aggregate_refresh import AggregateRefreshWorker
from uns_historian.batch import BatchCollector, BatchPersistResult, ConsumedEvent
from uns_historian.historian_config import HistorianConfig, KafkaConfig
from uns_historian.historian_handler import HistorianHandler
from uns_historian.prometheus_metrics import (
    BATCH_FLUSH_DURATION,
    DECODE_FAILURE,
    EVENTS_CONSUMED,
    KAFKA_COMMITS,
    start_metrics_server,
)

LOGGER = logging.getLogger(__name__)


class KafkaAheadOfSqlError(RuntimeError):
    """Kafka committed offset is ahead of the SQL checkpoint."""


class RetentionGapError(RuntimeError):
    """SQL checkpoint falls before the broker retained log."""


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    partition: int
    seek_offset: int


def reconcile_partition_offset(
    *,
    sql_checkpoint: int,
    kafka_committed: int | None,
    retained_low: int | None,
) -> int:
    if kafka_committed is not None and kafka_committed > sql_checkpoint:
        raise KafkaAheadOfSqlError(
            f"kafka committed offset {kafka_committed} is ahead of sql checkpoint {sql_checkpoint}"
        )
    if retained_low is not None and sql_checkpoint < retained_low:
        raise RetentionGapError(
            f"sql checkpoint {sql_checkpoint} is before retained low watermark {retained_low}"
        )
    return sql_checkpoint


def build_commit_partitions(next_offsets: dict[tuple[str, int], int]) -> list[TopicPartition]:
    return [
        TopicPartition(topic, partition, offset)
        for (topic, partition), offset in sorted(next_offsets.items())
    ]


def may_commit_kafka(*, ownership_active: bool, revoked: bool) -> bool:
    return ownership_active and not revoked


@dataclass(slots=True)
class HistorianKafkaMapper:
    handler: HistorianHandler
    historic_topic: str = HistorianConfig.historic_kafka_topic
    pipeline_epoch: int = HistorianConfig.pipeline_epoch
    collector: BatchCollector = field(default_factory=lambda: BatchCollector(HistorianHandler.batch_limits()))
    owned_partitions: set[tuple[str, int]] = field(default_factory=set)
    revoked: bool = False
    ownership_active: bool = False
    batch_in_flight: bool = False
    pending_kafka_commits: dict[tuple[str, int], int] = field(default_factory=dict)
    # `default_factory=time.monotonic` calls the clock at init and stores a float.
    monotonic: Callable[[], float] = field(default_factory=lambda: time.monotonic)

    def reset_collector(self) -> None:
        self.collector = BatchCollector(HistorianHandler.batch_limits())

    def on_assign(self, partitions: Sequence[TopicPartition]) -> None:
        self.revoked = False
        self.ownership_active = True
        self.owned_partitions = {(part.topic, part.partition) for part in partitions}
        historian_health.set_consumer_ready(True)

    def on_revoke(self, partitions: Sequence[TopicPartition]) -> None:
        revoked_keys = {(part.topic, part.partition) for part in partitions}
        self.owned_partitions -= revoked_keys
        if not self.owned_partitions:
            self.ownership_active = False
        self.revoked = True

    def should_pause_for_backpressure(self) -> bool:
        return self.batch_in_flight or self.collector.is_full(self.monotonic())

    def record_sql_success(self, result: BatchPersistResult, *, revoked: bool) -> dict[tuple[str, int], int]:
        if not may_commit_kafka(ownership_active=self.ownership_active, revoked=revoked):
            return {}
        commits = dict(result.next_offsets)
        self.pending_kafka_commits.update(commits)
        return commits

    async def flush_batch(self) -> tuple[BatchPersistResult, list[ConsumedEvent]] | None:
        if not self.collector.events or self.batch_in_flight:
            return None
        events = list(self.collector.events)
        self.reset_collector()
        self.batch_in_flight = True
        try:
            with BATCH_FLUSH_DURATION.time():
                result = await self.handler.persist_batch(events, self.pipeline_epoch)
            return result, events
        finally:
            self.batch_in_flight = False

    def try_buffer_message(
        self,
        *,
        topic: str,
        partition: int,
        offset: int,
        payload: bytes,
    ) -> tuple[ConsumedEvent | None, bool]:
        try:
            envelope = decode_event(payload)
        except EnvelopeError as exc:
            DECODE_FAILURE.labels(reason=exc.reason).inc()
            LOGGER.warning("Rejecting invalid envelope at %s[%s]@%s: %s", topic, partition, offset, exc)
            return None, False
        event = ConsumedEvent(
            kafka_topic=topic,
            partition=partition,
            offset=offset,
            envelope=envelope,
            envelope_bytes=payload,
        )
        if not self.collector.try_add(event, monotonic=self.monotonic()):
            return event, True
        EVENTS_CONSUMED.inc()
        return event, False


class ConsumerPort(Protocol):
    def poll(self, timeout: float) -> object | None: ...

    def commit(self, offsets: list[TopicPartition] | None = None, asynchronous: bool = False) -> None: ...

    def pause(self, partitions: list[TopicPartition]) -> None: ...

    def resume(self, partitions: list[TopicPartition]) -> None: ...

    def assign(self, partitions: list[TopicPartition]) -> None: ...

    def committed(self, partitions: list[TopicPartition], timeout: float) -> list[TopicPartition]: ...

    def get_watermark_offsets(self, partition: TopicPartition, timeout: float) -> tuple[int, int]: ...

    def subscribe(self, topics: list[str], on_assign, on_revoke) -> None: ...

    def close(self) -> None: ...


class HistorianKafkaConsumer:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        consumer: ConsumerPort,
        mapper: HistorianKafkaMapper,
        handler: HistorianHandler,
        topic_binder: TopicBinder,
        poll_timeout: float = HistorianConfig.consumer_poll_timeout,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._loop = loop
        self._consumer = consumer
        self._mapper = mapper
        self._handler = handler
        self._topic_binder = topic_binder
        self._poll_timeout = poll_timeout
        self._stop = stop_event or threading.Event()
        self._poll_thread: threading.Thread | None = None

    def _on_assign(self, _consumer, partitions) -> None:
        async def reconcile() -> None:
            checkpoints = await self._handler.read_partition_checkpoints(
                self._mapper.pipeline_epoch,
                self._mapper.historic_topic,
                [part.partition for part in partitions],
            )
            assigned: list[TopicPartition] = []
            for part in partitions:
                committed = self._consumer.committed([part], timeout=5.0)[0]
                kafka_offset = None if committed.offset < 0 else committed.offset
                low, _high = self._consumer.get_watermark_offsets(part, timeout=5.0)
                seek = reconcile_partition_offset(
                    sql_checkpoint=checkpoints.get(part.partition, 0),
                    kafka_committed=kafka_offset,
                    retained_low=low,
                )
                assigned.append(TopicPartition(part.topic, part.partition, seek))
            self._mapper.on_assign(assigned)
            self._consumer.assign(assigned)

        asyncio.run_coroutine_threadsafe(reconcile(), self._loop).result()

    def _on_revoke(self, _consumer, partitions) -> None:
        self._mapper.on_revoke(partitions)

    def start(self) -> None:
        self._consumer.subscribe(
            [self._mapper.historic_topic],
            on_assign=self._on_assign,
            on_revoke=self._on_revoke,
        )
        self._poll_thread = threading.Thread(target=self._poll_loop, name="historian-kafka-poll", daemon=True)
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            if self._mapper.should_pause_for_backpressure():
                self._pause_owned()
            message = self._consumer.poll(self._poll_timeout)
            if message is None:
                self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self._maybe_flush(force=False)))
                continue
            if hasattr(message, "error") and message.error():
                error = message.error()
                if error.code() != KafkaError._PARTITION_EOF:
                    LOGGER.error("Kafka consumer error: %s", error)
                continue
            self._loop.call_soon_threadsafe(lambda msg=message: asyncio.create_task(self._handle_message(msg)))

    def _pause_owned(self) -> None:
        assignment = [TopicPartition(topic, partition) for topic, partition in self._mapper.owned_partitions]
        if assignment:
            self._consumer.pause(assignment)

    def _resume_owned(self) -> None:
        assignment = [TopicPartition(topic, partition) for topic, partition in self._mapper.owned_partitions]
        if assignment:
            self._consumer.resume(assignment)

    async def _handle_message(self, message) -> None:
        if self._mapper.should_pause_for_backpressure():
            await self._maybe_flush(force=True)
            if self._mapper.should_pause_for_backpressure():
                return
        _event, needs_flush = self._mapper.try_buffer_message(
            topic=message.topic(),
            partition=message.partition(),
            offset=message.offset(),
            payload=message.value() or b"",
        )
        if needs_flush:
            await self._maybe_flush(force=True)
            self._mapper.try_buffer_message(
                topic=message.topic(),
                partition=message.partition(),
                offset=message.offset(),
                payload=message.value() or b"",
            )
        else:
            await self._maybe_flush(force=False)

    async def _maybe_flush(self, *, force: bool = False) -> None:
        if self._mapper.batch_in_flight:
            return
        if not force and not self._mapper.collector.is_full(self._mapper.monotonic()):
            return
        if not self._mapper.collector.events:
            return
        flushed = await self._mapper.flush_batch()
        if flushed is None:
            return
        result, events = flushed
        commits = self._mapper.record_sql_success(result, revoked=self._mapper.revoked)
        if commits:
            self._commit_kafka(commits)
        await self._observe_topics(events)
        self._resume_owned()

    def _commit_kafka(self, next_offsets: dict[tuple[str, int], int]) -> None:
        partitions = build_commit_partitions(next_offsets)
        if not partitions:
            return
        self._consumer.commit(offsets=partitions, asynchronous=False)
        KAFKA_COMMITS.inc(len(partitions))

    async def _observe_topics(self, events: Sequence[ConsumedEvent]) -> None:
        for topic in {event.envelope.topic for event in events}:
            try:
                await self._topic_binder.observe(topic)
            except Exception as exc:  # noqa: BLE001 TopicBinder is best-effort
                LOGGER.debug("Topic binding observation failed for %s: %s", topic, exc)

    async def shutdown(self) -> None:
        self._stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
        self._consumer.close()
        historian_health.set_consumer_ready(False)


@dataclass(slots=True)
class AggregateRefreshLoop:
    loop: asyncio.AbstractEventLoop
    worker: AggregateRefreshWorker
    interval_seconds: float
    stop_event: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = field(default=None, init=False)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="historian-aggregate-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                future = asyncio.run_coroutine_threadsafe(self.worker.run_once(), self.loop)
                future.result(timeout=120.0)
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("Aggregate refresh failed: %s", exc, exc_info=True)
            self.stop_event.wait(self.interval_seconds)


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    consumer = Consumer(KafkaConfig.consumer_config)
    handler = HistorianHandler()
    mapper = HistorianKafkaMapper(handler=handler, historic_topic=KafkaConfig.historic_topic)
    topic_binder = TopicBinder(AssetModelRepository(Database.shared("historian")))
    listener = AssetModelChangeListener(
        Database.shared("historian"),
        on_change=topic_binder.forget,
        module_env="historian",
    )
    kafka_consumer = HistorianKafkaConsumer(
        loop=loop,
        consumer=consumer,
        mapper=mapper,
        handler=handler,
        topic_binder=topic_binder,
    )
    refresh_worker = AggregateRefreshLoop(
        loop=loop,
        worker=AggregateRefreshWorker(),
        interval_seconds=HistorianConfig.aggregate_refresh_interval_seconds,
    )

    async def startup() -> None:
        await HistorianHandler.warm()
        await listener.start()

    loop.run_until_complete(startup())
    start_metrics_server(HistorianConfig.metrics_port)
    historian_health.set_consumer_ready(True)
    kafka_consumer.start()
    refresh_worker.start()

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        refresh_worker.stop()
        loop.run_until_complete(kafka_consumer.shutdown())
        loop.run_until_complete(HistorianHandler.close())
        loop.close()
