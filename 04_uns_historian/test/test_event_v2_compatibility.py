"""Tests for v2 envelope compatibility in the Kafka historian consumer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import DBAPIError
from uns_config.event_compatibility import as_legacy_telemetry
from uns_config.events import HistoricEventEnvelope, encode_event, source_event_id

from uns_historian.batch import ConsumedEvent, HISTORIC_KAFKA_TOPIC, IgnoredConsumedRecord
from uns_historian.historian_handler import HistorianHandler
from uns_historian.kafka_consumer import HistorianKafkaConsumer, HistorianKafkaMapper


def _telemetry_envelope(**overrides) -> HistoricEventEnvelope:
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    defaults = {
        "schema_version": 1,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": time,
        "received_at": datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC),
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"Temperature": 42.5, "timestamp": 1_788_948_000_000},
        "raw_payload_base64": None,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


def _consumed(
    envelope: HistoricEventEnvelope,
    *,
    partition: int = 0,
    offset: int = 0,
) -> ConsumedEvent:
    return ConsumedEvent(
        kafka_topic=HISTORIC_KAFKA_TOPIC,
        partition=partition,
        offset=offset,
        envelope=envelope,
        envelope_bytes=encode_event(envelope),
    )


class _FakeResult:
    def __init__(self, rows=None, scalar=None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar


class _FakeConnection:
    def __init__(self) -> None:
        self.checkpoints: dict[tuple[int, int], int] = {}
        self.raw_rows: list = []
        self.metric_rows: list = []
        self.fail_metrics = False

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        if "INSERT INTO historian.kafka_partition_checkpoint" in sql and "ON CONFLICT" in sql:
            key = (params["pipeline_epoch"], params["partition_id"])
            self.checkpoints.setdefault(key, 0)
            return _FakeResult()

        if "SELECT partition_id, next_offset" in sql and "FOR UPDATE" in sql:
            key = (params["pipeline_epoch"], params["partition_id"])
            return _FakeResult([{"partition_id": params["partition_id"], "next_offset": self.checkpoints[key]}])

        if "SELECT immutable_content_hash" in sql:
            return _FakeResult(scalar=None)

        if "INSERT INTO unifiednamespace" in sql:
            self.raw_rows.extend(params or [])
            return _FakeResult(
                [
                    {
                        "event_id": row["event_id"],
                        "event_kind": row["event_kind"],
                        "is_historical": row["is_historical"],
                        "time": row["time"],
                    }
                    for row in params or []
                ]
            )

        if "INSERT INTO uns_metrics" in sql:
            if self.fail_metrics:
                raise DBAPIError("metric insert failed", None, None)
            self.metric_rows.extend(params or [])
            return _FakeResult()

        if "UPDATE historian.kafka_partition_checkpoint" in sql:
            key = (params["pipeline_epoch"], params["partition_id"])
            self.checkpoints[key] = params["next_offset"]
            return _FakeResult()

        return _FakeResult()


class _FakeTransaction:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def begin(self):
        return _FakeTransaction(self._connection)


def _v2_business_event(**overrides) -> HistoricEventEnvelope:
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 2,
        "event_id": source_event_id("plant-01", "plant-a/lims-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/lims-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-01",
        "time": time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/LIMS/results",
        "event_kind": "business_event",
        "is_historical": False,
        "payload": {},
        "raw_payload_base64": None,
        "source_application": "lims",
        "payload_schema_id": "lab-result",
        "payload_schema_version": "1",
        "content_type": "application/json",
        "original_payload": b'{"result": 4.2}',
        "archive_eligible": True,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


def _v2_telemetry(**overrides) -> HistoricEventEnvelope:
    time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 2,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"Temperature": 42.5, "timestamp": 1_788_948_000_000},
        "raw_payload_base64": None,
        "source_application": "machine",
        "payload_schema_id": "temperature",
        "payload_schema_version": "1",
        "content_type": "application/json",
        "original_payload": b'{"Temperature": 42.5, "timestamp": 1788948000000}',
        "archive_eligible": True,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


@pytest.fixture
def v2_business_event():
    return _v2_business_event()


def test_business_event_is_not_metric_input(v2_business_event):
    assert as_legacy_telemetry(v2_business_event) is None


def test_state_snapshot_is_not_metric_input():
    assert as_legacy_telemetry(_v2_business_event(event_kind="state_snapshot")) is None


def test_v1_telemetry_is_returned_unchanged():
    envelope = _telemetry_envelope()
    assert as_legacy_telemetry(envelope) is envelope


def test_v2_telemetry_returns_v1_compatible_copy():
    envelope = _v2_telemetry()
    legacy = as_legacy_telemetry(envelope)
    assert legacy is not None
    assert legacy.schema_version == 1
    assert legacy.event_id == envelope.event_id
    assert legacy.source_id == envelope.source_id
    assert legacy.source_boot_id == envelope.source_boot_id
    assert legacy.source_sequence == envelope.source_sequence
    assert legacy.site_id == envelope.site_id
    assert legacy.time == envelope.time
    assert legacy.received_at == envelope.received_at
    assert legacy.topic == envelope.topic
    assert legacy.event_kind == "telemetry"
    assert legacy.payload["Temperature"] == envelope.payload["Temperature"]
    assert legacy.payload["timestamp"] == 1_788_948_000
    assert legacy.source_application is None
    assert legacy.original_payload is None


def test_mapper_buffers_v1_and_v2_telemetry():
    handler = AsyncMock(spec=HistorianHandler)
    mapper = HistorianKafkaMapper(handler=handler)

    v1_result = mapper.try_buffer_message(
        topic=HISTORIC_KAFKA_TOPIC,
        partition=0,
        offset=0,
        payload=encode_event(_telemetry_envelope()),
    )
    v2_result = mapper.try_buffer_message(
        topic=HISTORIC_KAFKA_TOPIC,
        partition=0,
        offset=1,
        payload=encode_event(_v2_telemetry()),
    )

    assert v1_result.consumed is not None
    assert v1_result.ignored is None
    assert v2_result.consumed is not None
    assert v2_result.ignored is None
    assert mapper.collector.events[0].envelope.schema_version == 1
    assert mapper.collector.events[1].envelope.schema_version == 1


def test_mapper_returns_ignored_for_business_event():
    handler = AsyncMock(spec=HistorianHandler)
    mapper = HistorianKafkaMapper(handler=handler)

    result = mapper.try_buffer_message(
        topic=HISTORIC_KAFKA_TOPIC,
        partition=0,
        offset=5,
        payload=encode_event(_v2_business_event()),
    )

    assert result.consumed is None
    assert result.ignored is not None
    assert result.ignored.offset == 5
    assert mapper.collector.events == []


@pytest.mark.asyncio(loop_scope="function")
async def test_checkpoint_ignored_records_advances_without_sql_insert():
    connection = _FakeConnection()
    handler = HistorianHandler(database=_FakeDatabase(connection))

    result = await handler.checkpoint_ignored_records(
        [IgnoredConsumedRecord(kafka_topic=HISTORIC_KAFKA_TOPIC, partition=0, offset=0)],
        pipeline_epoch=1,
    )

    assert result.inserted_count == 0
    assert connection.raw_rows == []
    assert connection.metric_rows == []
    assert result.next_offsets[(HISTORIC_KAFKA_TOPIC, 0)] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_interleaved_v1_business_v2_advances_checkpoint_in_order():
    connection = _FakeConnection()
    handler = HistorianHandler(database=_FakeDatabase(connection))

    telemetry = _consumed(_telemetry_envelope(), offset=0)
    await handler.persist_batch([telemetry], pipeline_epoch=1)

    ignored = await handler.checkpoint_ignored_records(
        [IgnoredConsumedRecord(kafka_topic=HISTORIC_KAFKA_TOPIC, partition=0, offset=1)],
        pipeline_epoch=1,
    )
    assert ignored.next_offsets[(HISTORIC_KAFKA_TOPIC, 0)] == 2

    v2_telemetry = _consumed(_v2_telemetry(), offset=2)
    final = await handler.persist_batch([v2_telemetry], pipeline_epoch=1)

    assert connection.raw_rows
    assert connection.metric_rows
    assert final.next_offsets[(HISTORIC_KAFKA_TOPIC, 0)] == 3


@pytest.mark.asyncio(loop_scope="function")
async def test_sql_failure_before_business_does_not_advance_past_failed_telemetry():
    connection = _FakeConnection()
    connection.fail_metrics = True
    handler = HistorianHandler(database=_FakeDatabase(connection))
    mapper = HistorianKafkaMapper(handler=handler)
    consumer = HistorianKafkaConsumer(
        loop=MagicMock(),
        consumer=MagicMock(),
        mapper=mapper,
        handler=handler,
        topic_binder=MagicMock(),
    )

    mapper.try_buffer_message(
        topic=HISTORIC_KAFKA_TOPIC,
        partition=0,
        offset=0,
        payload=encode_event(_telemetry_envelope()),
    )

    business = mapper.try_buffer_message(
        topic=HISTORIC_KAFKA_TOPIC,
        partition=0,
        offset=1,
        payload=encode_event(_v2_business_event()),
    )
    assert business.ignored is not None

    with pytest.raises(DBAPIError):
        await consumer._handle_ignored_record(business.ignored)

    assert connection.checkpoints.get((1, 0), 0) == 0
