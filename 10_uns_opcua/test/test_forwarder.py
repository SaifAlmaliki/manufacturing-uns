"""Unit tests for the spool writer and the MQTT forwarder."""

import asyncio

import pytest
from uns_opcua.forwarder import Forwarder, SpoolWriter
from uns_opcua.opcua_config import SpoolConfig
from uns_opcua.spool import Spool, SpoolRow

NOW = 1_756_728_000.0

pytestmark = pytest.mark.asyncio


@pytest.fixture
def spool(tmp_path):
    spool = Spool(
        SpoolConfig(
            path=str(tmp_path / "spool.db"),
            max_rows=1000,
            max_bytes=100_000_000,
            max_age_hours=168,
            synchronous="OFF",
        )
    )
    spool.open()
    yield spool
    spool.close()


def _row(topic: str) -> SpoolRow:
    return SpoolRow(topic=topic, payload=b'{"value":1}', qos=1)


class FakePublisher:
    """Records what was published, and can be made to fail on demand."""

    def __init__(self, fail_from: int | None = None) -> None:
        self.published: list[tuple[str, bytes, int]] = []
        self._fail_from = fail_from

    async def publish(self, topic: str, payload: bytes, qos: int) -> None:
        if self._fail_from is not None and len(self.published) >= self._fail_from:
            raise ConnectionError("broker gone")
        self.published.append((topic, payload, qos))


async def test_spool_writer_batches_the_queue_into_the_spool(spool):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    for topic in ("a", "b", "c"):
        queue.put_nowait(_row(topic))

    writer = SpoolWriter(spool=spool, queue=queue, batch_size=500, flush_interval_s=0.05)
    assert await writer.drain_once(now=NOW) == 3
    assert [row.topic for _, row in spool.peek(limit=10)] == ["a", "b", "c"]


async def test_spool_writer_is_a_no_op_on_an_empty_queue(spool):
    writer = SpoolWriter(spool=spool, queue=asyncio.Queue(), batch_size=500, flush_interval_s=0.01)
    assert await writer.drain_once(now=NOW) == 0
    assert spool.row_count() == 0


async def test_spool_writer_respects_its_batch_size(spool):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    for index in range(5):
        queue.put_nowait(_row(f"t{index}"))

    writer = SpoolWriter(spool=spool, queue=queue, batch_size=2, flush_interval_s=0.01)
    assert await writer.drain_once(now=NOW) == 2
    assert spool.row_count() == 2


async def test_spool_writer_enforces_the_bounds_after_writing(tmp_path):
    spool = Spool(
        SpoolConfig(
            path=str(tmp_path / "spool.db"),
            max_rows=2,
            max_bytes=100_000_000,
            max_age_hours=168,
            synchronous="OFF",
        )
    )
    spool.open()
    try:
        queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
        for topic in ("a", "b", "c", "d"):
            queue.put_nowait(_row(topic))
        writer = SpoolWriter(spool=spool, queue=queue, batch_size=500, flush_interval_s=0.01)
        await writer.drain_once(now=NOW)
        assert [row.topic for _, row in spool.peek(limit=10)] == ["c", "d"]
    finally:
        spool.close()


async def test_spool_writer_throttles_trim_across_rapid_drains(tmp_path):
    """Bounds still apply, but not on every 50ms write — a full-table scan at 20 Hz
    would walk a multi-GB spool on the hot path."""
    spool = Spool(
        SpoolConfig(
            path=str(tmp_path / "spool.db"),
            max_rows=2,
            max_bytes=100_000_000,
            max_age_hours=168,
            synchronous="OFF",
        )
    )
    spool.open()
    try:
        queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
        for topic in ("a", "b", "c", "d"):
            queue.put_nowait(_row(topic))
        writer = SpoolWriter(
            spool=spool,
            queue=queue,
            batch_size=500,
            flush_interval_s=0.01,
            trim_interval_s=5.0,
        )
        await writer.drain_once(now=NOW)
        assert spool.row_count() == 2

        for topic in ("e", "f"):
            queue.put_nowait(_row(topic))
        await writer.drain_once(now=NOW + 0.05)
        assert spool.row_count() == 4

        queue.put_nowait(_row("g"))
        await writer.drain_once(now=NOW + 10.0)
        assert spool.row_count() == 2
        assert [row.topic for _, row in spool.peek(limit=10)] == ["f", "g"]
    finally:
        spool.close()


async def test_forward_batch_publishes_then_deletes(spool):
    spool.enqueue([_row("a"), _row("b")], now=NOW)
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)

    assert await forwarder.forward_batch(publisher) == 2
    assert [topic for topic, _, _ in publisher.published] == ["a", "b"]
    assert spool.row_count() == 0


async def test_forward_batch_publishes_the_spooled_payload_verbatim(spool):
    payload = '{"value":74.83,"unit":"°C","timestamp":1756728000123.0}'.encode("utf-8")
    spool.enqueue([SpoolRow(topic="t", payload=payload, qos=1)], now=NOW)
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)

    await forwarder.forward_batch(publisher)
    # Rule 1: no field is re-derived at drain time.
    assert publisher.published[0][1] == payload


async def test_forward_batch_keeps_unacknowledged_rows_when_publishing_fails(spool):
    spool.enqueue([_row("a"), _row("b"), _row("c")], now=NOW)
    publisher = FakePublisher(fail_from=1)
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)

    with pytest.raises(ConnectionError):
        await forwarder.forward_batch(publisher)

    # "a" was acknowledged and is gone; "b" and "c" stay for the next attempt.
    assert [row.topic for _, row in spool.peek(limit=10)] == ["b", "c"]


async def test_forward_batch_on_an_empty_spool_publishes_nothing(spool):
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)
    assert await forwarder.forward_batch(publisher) == 0
    assert publisher.published == []


async def test_forward_batch_publishes_with_the_row_qos_including_zero(spool):
    spool.enqueue([SpoolRow(topic="t", payload=b"{}", qos=0)], now=NOW)
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)

    await forwarder.forward_batch(publisher)
    assert publisher.published[0][2] == 0


async def test_forward_batch_preserves_per_topic_order_across_batches(spool):
    spool.enqueue([_row("t"), _row("t"), _row("t")], now=NOW)
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=2)

    assert await forwarder.forward_batch(publisher) == 2
    assert await forwarder.forward_batch(publisher) == 1
    assert len(publisher.published) == 3
