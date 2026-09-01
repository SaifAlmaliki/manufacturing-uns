"""
Bounded, disk-backed store-and-forward spool.

Every message goes through here, always. There is no publish-direct fast path, because
two paths would let a draining backlog interleave with fresh values and break per-topic
ordering — in exchange for a few milliseconds that report-by-exception data does not care
about.

This class is synchronous on purpose: sqlite3 blocks, so callers wrap it in
`asyncio.to_thread`. That keeps the event loop free while leaving the spool testable
without one. `now` is always a parameter, never a clock read, so the age bound is
deterministic under test.
"""

import logging
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from uns_opcua.opcua_config import SpoolConfig

LOGGER = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS spool (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  topic      TEXT NOT NULL,
  payload    BLOB NOT NULL,
  qos        INTEGER NOT NULL DEFAULT 1,
  spooled_at REAL NOT NULL
);
"""

_INSERT = "INSERT INTO spool (topic, payload, qos, spooled_at) VALUES (?, ?, ?, ?)"
_PEEK = "SELECT id, topic, payload, qos FROM spool ORDER BY id LIMIT ?"


@dataclass(frozen=True, slots=True)
class SpoolRow:
    """One message awaiting publication. `payload` is republished verbatim (Rule 1)."""

    topic: str
    payload: bytes
    qos: int


class Spool:
    """FIFO spool bounded by rows, bytes and age."""

    def __init__(self, config: SpoolConfig) -> None:
        self._config = config
        self._connection: sqlite3.Connection | None = None
        # Callers reach this class through asyncio.to_thread, so two different pool
        # threads can arrive at once. RLock rather than Lock because trim() calls
        # row_count() and byte_size().
        self._lock = threading.RLock()

    # --- lifecycle -----------------------------------------------------------------

    def open(self) -> None:
        """Create the database and its schema, and apply the durability pragmas."""
        path = Path(self._config.path)
        if path.parent != Path():
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            # check_same_thread=False is mandatory: sqlite3 otherwise refuses to be used
            # from the asyncio.to_thread pool thread that did not open it. This class's
            # own lock provides the serialisation that flag gives up.
            self._connection = sqlite3.connect(
                self._config.path, isolation_level=None, check_same_thread=False
            )
            # auto_vacuum has to be set before the first table exists, so it goes before
            # the DDL. Without it, deleted pages are never returned and the max_bytes
            # bound could never be satisfied.
            self._connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            # WAL lets the forwarder read while the writer writes. synchronous=NORMAL
            # risks the last few milliseconds on a power cut, which beats an order of
            # magnitude of throughput; FULL stays available for sites that disagree.
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(f"PRAGMA synchronous={self._config.synchronous}")
            self._connection.executescript(_DDL)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Spool.open() must be called before use")
        return self._connection

    def pragma(self, name: str) -> Any:
        """Read back a pragma. Used by tests to assert the durability settings."""
        with self._lock:
            return self._db.execute(f"PRAGMA {name}").fetchone()[0]

    # --- writing -------------------------------------------------------------------

    def enqueue(self, rows: Sequence[SpoolRow], now: float) -> int:
        """Append a batch in one transaction. Batching is what lets SQLite keep up."""
        if not rows:
            return 0
        with self._lock, self._db:
            self._db.executemany(_INSERT, [(row.topic, row.payload, row.qos, now) for row in rows])
        return len(rows)

    # --- reading and draining ------------------------------------------------------

    def peek(self, limit: int) -> list[tuple[int, SpoolRow]]:
        """The oldest `limit` rows, in id order. Rows stay until delete_through."""
        with self._lock:
            rows = self._db.execute(_PEEK, (limit,)).fetchall()
        return [
            (row_id, SpoolRow(topic=topic, payload=bytes(payload), qos=qos))
            for row_id, topic, payload, qos in rows
        ]

    def delete_through(self, max_id: int) -> int:
        """
        Delete every row up to and including `max_id`, after the broker acknowledged
        them. A crash between publish and delete replays on restart, which the
        historian's ON CONFLICT DO NOTHING absorbs.
        """
        with self._lock, self._db:
            cursor = self._db.execute("DELETE FROM spool WHERE id <= ?", (max_id,))
        return cursor.rowcount

    # --- bounding ------------------------------------------------------------------

    def trim(self, now: float) -> int:
        """
        Enforce every bound by deleting the lowest ids, and return how many were dropped.

        The bound is not optional. An unbounded spool turns a week-long WAN outage into a
        full disk that takes the whole edge node down, which is strictly worse than
        losing the oldest tail of the data.
        """
        with self._lock:
            dropped = 0
            dropped += self._trim_by_age(now)
            dropped += self._trim_by_rows()
            dropped += self._trim_by_bytes()
        if dropped:
            LOGGER.warning("Spool dropped %s oldest rows to stay inside its bounds", dropped)
        return dropped

    def _trim_by_age(self, now: float) -> int:
        cutoff = now - self._config.max_age_hours * 3600
        with self._db:
            cursor = self._db.execute("DELETE FROM spool WHERE spooled_at < ?", (cutoff,))
        return cursor.rowcount

    def _trim_by_rows(self) -> int:
        excess = self.row_count() - self._config.max_rows
        if excess <= 0:
            return 0
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM spool WHERE id IN (SELECT id FROM spool ORDER BY id LIMIT ?)",
                (excess,),
            )
        return cursor.rowcount

    def _trim_by_bytes(self) -> int:
        dropped = 0
        # Delete in chunks and re-measure: page_count only falls once pages are freed,
        # so a single computed delete count would not converge.
        while self.byte_size() > self._config.max_bytes and self.row_count() > 0:
            with self._db:
                cursor = self._db.execute(
                    "DELETE FROM spool WHERE id IN (SELECT id FROM spool ORDER BY id LIMIT ?)",
                    (max(1, self.row_count() // 10),),
                )
            if not cursor.rowcount:
                break
            dropped += cursor.rowcount
            self._db.execute("PRAGMA incremental_vacuum")
        return dropped

    # --- observation ---------------------------------------------------------------

    def row_count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT count(*) FROM spool").fetchone()[0])

    def byte_size(self) -> int:
        with self._lock:
            page_count = self._db.execute("PRAGMA page_count").fetchone()[0]
            page_size = self._db.execute("PRAGMA page_size").fetchone()[0]
        return int(page_count) * int(page_size)

    def oldest_spooled_at(self) -> float | None:
        """The oldest row's spool time, or None when the spool is empty."""
        with self._lock:
            row = self._db.execute("SELECT min(spooled_at) FROM spool").fetchone()
        return None if row[0] is None else float(row[0])
