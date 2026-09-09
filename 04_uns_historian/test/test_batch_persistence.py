"""Persistence tests for batched historian projection."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from uns_config.events import HistoricEventEnvelope, encode_event, immutable_content_hash, ingress_event_id, source_event_id
from uns_historian.batch import ConsumedEvent, HISTORIC_KAFKA_TOPIC
from uns_historian.historian_handler import HistorianHandler


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
    def __init__(self, rows: list[Mapping[str, Any]] | None = None, scalar: Any | None = None) -> None:
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
        self.existing: dict[tuple[str, str], str] = {}
        self.raw_rows: list[dict[str, Any]] = []
        self.metric_rows: list[dict[str, Any]] = []
        self.committed = False
        self.rolled_back = False
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
            existing = self.existing.get((str(params["time"]), params["event_id"]))
            return _FakeResult(scalar=existing)

        if "INSERT INTO unifiednamespace" in sql and "RETURNING event_id" in sql:
            rows = []
            for row in params if isinstance(params, list) else [params]:
                key = (str(row["time"]), row["event_id"])
                if key in self.existing:
                    continue
                self.existing[key] = row["immutable_content_hash"]
                self.raw_rows.append(row)
                rows.append(
                    {
                        "event_id": row["event_id"],
                        "event_kind": row["event_kind"],
                        "time": row["time"],
                        "is_historical": row["is_historical"],
                    }
                )
            return _FakeResult(rows)

        if "INSERT INTO uns_metrics" in sql:
            if self.fail_metrics:
                raise DBAPIError("metric insert failed", None, Exception("boom"))
            payload = params if isinstance(params, list) else [params]
            self.metric_rows.extend(payload)
            return _FakeResult()

        if "UPDATE historian.kafka_partition_checkpoint" in sql:
            key = (params["pipeline_epoch"], params["partition_id"])
            self.checkpoints[key] = params["next_offset"]
            return _FakeResult()

        if "INSERT INTO historian.late_refresh_worklist" in sql:
            return _FakeResult()

        raise AssertionError(f"unexpected SQL: {sql}")


class _FakeTransaction:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.connection.committed = True
        else:
            self.connection.rolled_back = True
            self.connection.raw_rows.clear()
            self.connection.metric_rows.clear()
            self.connection.existing.clear()


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def begin(self):
        return _FakeTransaction(self._connection)


@pytest.mark.asyncio(loop_scope="function")
async def test_persist_batch_rolls_back_when_metric_insert_fails():
    connection = _FakeConnection()
    connection.fail_metrics = True
    handler = HistorianHandler(database=_FakeDatabase(connection))

    with pytest.raises(DBAPIError):
        await handler.persist_batch([_consumed(_telemetry_envelope())], pipeline_epoch=1)

    assert connection.rolled_back is True
    assert connection.raw_rows == []
    assert connection.metric_rows == []


@pytest.mark.asyncio(loop_scope="function")
async def test_persist_batch_quarantines_content_conflicts_without_insert():
    connection = _FakeConnection()
    envelope = _telemetry_envelope()
    connection.existing[(str(envelope.time), envelope.event_id)] = "different-hash"
    handler = HistorianHandler(database=_FakeDatabase(connection))

    result = await handler.persist_batch([_consumed(envelope, offset=0)], pipeline_epoch=1)

    assert result.inserted_count == 0
    assert len(result.quarantined_conflicts) == 1
    assert result.next_offsets[(HISTORIC_KAFKA_TOPIC, 0)] == 1
    assert connection.metric_rows == []


@pytest.mark.asyncio(loop_scope="function")
async def test_duplicate_raw_event_does_not_insert_metrics():
    connection = _FakeConnection()
    envelope = _telemetry_envelope()
    connection.existing[(str(envelope.time), envelope.event_id)] = immutable_content_hash(envelope)
    handler = HistorianHandler(database=_FakeDatabase(connection))

    result = await handler.persist_batch([_consumed(envelope, offset=0)], pipeline_epoch=1)

    assert result.inserted_count == 0
    assert result.duplicate_count == 1
    assert connection.metric_rows == []


@pytest.mark.asyncio(loop_scope="function")
async def test_stale_offsets_below_checkpoint_are_filtered():
    connection = _FakeConnection()
    connection.checkpoints[(1, 0)] = 5
    handler = HistorianHandler(database=_FakeDatabase(connection))

    result = await handler.persist_batch([_consumed(_telemetry_envelope(), offset=3)], pipeline_epoch=1)

    assert result.filtered_stale_count == 1
    assert result.inserted_count == 0
    assert result.next_offsets == {}


@pytest.mark.asyncio(loop_scope="function")
async def test_changed_event_id_timestamp_is_not_detected_as_duplicate():
    """Time-scoped identity cannot catch source ID reuse with a different timestamp."""
    first = _telemetry_envelope(source_sequence=1)
    second = _telemetry_envelope(
        source_sequence=1,
        time=datetime(2026, 9, 9, 10, 0, 1, tzinfo=UTC),
        payload={"Temperature": 99.0, "timestamp": 1_788_948_001_000},
    )
    assert first.event_id == second.event_id
    assert first.time != second.time


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.xdist_group(name="uns_historian")
async def test_persist_batch_replay_is_idempotent(historian_pool):  # noqa: ARG001
    topic = "PyTestHistorianBatch/Replay/Device"
    envelope = _telemetry_envelope(
        topic=topic,
        event_id=ingress_event_id(uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")),
        identity_quality="ingress",
        source_boot_id=None,
        source_sequence=None,
        payload={"Temperature": 12.3, "timestamp": 1_788_948_000_000},
    )
    event = _consumed(envelope, offset=100)

    try:
        async with HistorianHandler() as handler:
            first = await handler.persist_batch([event], pipeline_epoch=99)
            second = await handler.persist_batch([event], pipeline_epoch=99)

        assert first.inserted_count == 1
        assert second.inserted_count == 0
        assert second.duplicate_count == 1

        async with HistorianHandler() as reader:
            metrics = await reader.execute_prepared(
                f"SELECT COUNT(*) AS count FROM uns_metrics WHERE topic = $1 AND event_id = $2",  # noqa: S608
                topic,
                envelope.event_id,
            )
        assert metrics[0]["count"] == 1
    finally:
        async with HistorianHandler() as cleaner:
            await cleaner.execute_prepared(f"DELETE FROM uns_metrics WHERE topic = $1", topic)  # noqa: S608
            await cleaner.execute_prepared(f"DELETE FROM unifiednamespace WHERE topic = $1", topic)  # noqa: S608
            await cleaner.execute_prepared(
                "DELETE FROM historian.kafka_partition_checkpoint WHERE pipeline_epoch = $1",
                99,
            )
