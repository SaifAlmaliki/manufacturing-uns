"""Unit tests for the bounded, disk-backed store-and-forward spool."""

import pytest
from uns_opcua.opcua_config import SpoolConfig
from uns_opcua.spool import Spool, SpoolRow

NOW = 1_756_728_000.0


def _config(tmp_path, **overrides) -> SpoolConfig:
    defaults = {
        "path": str(tmp_path / "spool.db"),
        "max_rows": 1000,
        "max_bytes": 100_000_000,
        "max_age_hours": 168,
        "synchronous": "NORMAL",
    }
    return SpoolConfig(**{**defaults, **overrides})


@pytest.fixture
def spool(tmp_path):
    spool = Spool(_config(tmp_path))
    spool.open()
    yield spool
    spool.close()


def _row(topic: str, value: int = 1) -> SpoolRow:
    return SpoolRow(topic=topic, payload=f'{{"value":{value}}}'.encode(), qos=1)


def test_enqueue_then_peek_returns_rows_in_fifo_order(spool):
    assert spool.enqueue([_row("a", 1), _row("b", 2), _row("c", 3)], now=NOW) == 3
    peeked = spool.peek(limit=10)
    assert [row.topic for _, row in peeked] == ["a", "b", "c"]
    assert [row_id for row_id, _ in peeked] == sorted(row_id for row_id, _ in peeked)


def test_peek_respects_its_limit(spool):
    spool.enqueue([_row("a"), _row("b"), _row("c")], now=NOW)
    assert len(spool.peek(limit=2)) == 2


def test_payload_survives_the_round_trip_byte_for_byte(spool):
    payload = '{"value":74.83,"unit":"°C"}'.encode("utf-8")
    spool.enqueue([SpoolRow(topic="t", payload=payload, qos=1)], now=NOW)
    _, row = spool.peek(limit=1)[0]
    assert row.payload == payload
    assert row.qos == 1


def test_delete_through_removes_only_acknowledged_rows(spool):
    spool.enqueue([_row("a"), _row("b"), _row("c")], now=NOW)
    peeked = spool.peek(limit=2)
    assert spool.delete_through(peeked[-1][0]) == 2
    assert [row.topic for _, row in spool.peek(limit=10)] == ["c"]


def test_row_count_and_oldest_spooled_at(spool):
    assert spool.row_count() == 0
    assert spool.oldest_spooled_at() is None
    spool.enqueue([_row("a")], now=NOW)
    spool.enqueue([_row("b")], now=NOW + 60)
    assert spool.row_count() == 2
    assert spool.oldest_spooled_at() == NOW


def test_byte_size_is_positive_once_written(spool):
    spool.enqueue([_row("a")], now=NOW)
    assert spool.byte_size() > 0


def test_trim_enforces_max_rows_by_dropping_the_oldest(tmp_path):
    spool = Spool(_config(tmp_path, max_rows=3))
    spool.open()
    try:
        spool.enqueue([_row("a"), _row("b"), _row("c"), _row("d"), _row("e")], now=NOW)
        assert spool.trim(now=NOW) == 2
        assert [row.topic for _, row in spool.peek(limit=10)] == ["c", "d", "e"]
    finally:
        spool.close()


def test_trim_enforces_max_age(tmp_path):
    spool = Spool(_config(tmp_path, max_age_hours=1))
    spool.open()
    try:
        spool.enqueue([_row("old")], now=NOW)
        spool.enqueue([_row("fresh")], now=NOW + 3600)
        # Two hours after the first row was spooled, only the fresh one is inside the bound.
        assert spool.trim(now=NOW + 7200) == 1
        assert [row.topic for _, row in spool.peek(limit=10)] == ["fresh"]
    finally:
        spool.close()


def test_trim_enforces_max_bytes(tmp_path):
    spool = Spool(_config(tmp_path, max_bytes=1))
    spool.open()
    try:
        spool.enqueue([_row("a"), _row("b")], now=NOW)
        # An absurd bound must drop rather than leave the spool over its limit forever.
        assert spool.trim(now=NOW) > 0
    finally:
        spool.close()


def test_trim_is_a_no_op_inside_every_bound(spool):
    spool.enqueue([_row("a")], now=NOW)
    assert spool.trim(now=NOW) == 0
    assert spool.row_count() == 1


def test_reopening_the_same_file_keeps_the_backlog(tmp_path):
    config = _config(tmp_path)
    first = Spool(config)
    first.open()
    first.enqueue([_row("survivor")], now=NOW)
    first.close()

    second = Spool(config)
    second.open()
    try:
        assert [row.topic for _, row in second.peek(limit=10)] == ["survivor"]
    finally:
        second.close()


def test_ids_keep_increasing_after_a_delete(spool):
    """FIFO depends on ids never being reused, so AUTOINCREMENT is required."""
    spool.enqueue([_row("a")], now=NOW)
    first_id = spool.peek(limit=1)[0][0]
    spool.delete_through(first_id)
    spool.enqueue([_row("b")], now=NOW)
    assert spool.peek(limit=1)[0][0] > first_id


def test_wal_mode_and_synchronous_are_applied(tmp_path):
    spool = Spool(_config(tmp_path, synchronous="FULL"))
    spool.open()
    try:
        assert spool.pragma("journal_mode") == "wal"
        assert spool.pragma("synchronous") == 2  # FULL
        assert spool.pragma("auto_vacuum") == 2  # INCREMENTAL, so max_bytes can be met
    finally:
        spool.close()


def test_the_spool_is_usable_from_another_thread(spool):
    """
    Every caller reaches the spool through asyncio.to_thread, which runs on a pool
    thread that did not open the connection. sqlite3 raises ProgrammingError for that
    unless check_same_thread=False.
    """
    import concurrent.futures

    def write_and_count() -> int:
        spool.enqueue([_row("from-a-thread")], now=NOW)
        return spool.row_count()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert pool.submit(write_and_count).result() == 1
        # A second, different pool thread must work too.
        assert pool.submit(write_and_count).result() == 2


def test_concurrent_writers_and_readers_do_not_corrupt_the_spool(spool):
    """The writer and forwarder tasks really do hit the spool at the same time."""
    import concurrent.futures

    def write(index: int) -> int:
        return spool.enqueue([_row(f"t{index}")], now=NOW)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        written = sum(pool.map(write, range(40)))

    assert written == 40
    assert spool.row_count() == 40
    assert len(spool.peek(limit=100)) == 40
