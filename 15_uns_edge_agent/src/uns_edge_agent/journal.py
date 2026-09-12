"""Durable SQLite journal for apply intent and outbound reports."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from uns_config.edge_contracts import EdgeConfig, EdgeReport


class JournalError(Exception):
    """Journal operation failure."""


class JournalLockError(JournalError):
    """Another process holds the journal lock."""


@dataclass(frozen=True, slots=True)
class PendingApply:
    revision: int
    digest: str
    config: dict[str, Any]
    recovery_snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PendingReport:
    sequence: int
    boot_id: str
    report: dict[str, Any]
    heartbeat_only: bool


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _edge_config_to_dict(config: EdgeConfig | dict[str, Any]) -> dict[str, Any]:
    if isinstance(config, dict):
        return dict(config)
    return {
        "contract_version": config.contract_version,
        "edge_id": config.edge_id,
        "revision": config.revision,
        "digest": config.digest,
        "adapters": [dict(adapter.__dict__) for adapter in config.adapters],
        "required_route_revision": config.required_route_revision,
        "secret_refs": [dict(ref) for ref in config.secret_refs],
        "deleted_adapter_ids": list(config.deleted_adapter_ids),
    }


def _edge_report_to_dict(report: EdgeReport | dict[str, Any]) -> dict[str, Any]:
    if isinstance(report, dict):
        return dict(report)
    return {
        "edge_id": report.edge_id,
        "boot_id": report.boot_id,
        "report_sequence": report.report_sequence,
        "desired_revision": report.desired_revision,
        "applied_revision": report.applied_revision,
        "applied_digest": report.applied_digest,
        "phase": report.phase,
        "adapter_results": list(report.adapter_results),
        "last_error_code": report.last_error_code,
        "versions": dict(report.versions),
        "capabilities": dict(report.capabilities),
    }


class _ProcessLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self._path, "a+b")  # noqa: SIM115
        try:
            if sys.platform == "win32":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            self._handle = None
            raise JournalLockError("journal lock held by another process") from exc

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class Journal:
    """Transactional local journal for apply intent and outbound reports."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _ProcessLock(path.with_suffix(".lock"))
        self._connection: sqlite3.Connection | None = None

    def open(self) -> None:
        self._lock.acquire()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._init_schema()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._lock.release()

    def _init_schema(self) -> None:
        assert self._connection is not None
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS journal_state (
                boot_id TEXT NOT NULL,
                next_report_sequence INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS pending_apply (
                revision INTEGER NOT NULL,
                digest TEXT NOT NULL,
                config_json TEXT NOT NULL,
                recovery_snapshot_json TEXT NOT NULL,
                started_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_reports (
                sequence INTEGER PRIMARY KEY,
                boot_id TEXT NOT NULL,
                report_json TEXT NOT NULL,
                heartbeat_only INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        row = self._connection.execute("SELECT COUNT(*) FROM journal_state").fetchone()
        if row is not None and row[0] == 0:
            self._connection.execute(
                "INSERT INTO journal_state (boot_id, next_report_sequence) VALUES (?, ?)",
                ("", 1),
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        assert self._connection is not None
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
            self._connection.execute("COMMIT")
            self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
            if hasattr(os, "sync"):
                os.sync()
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def set_boot_id(self, boot_id: str) -> None:
        with self._transaction() as conn:
            conn.execute("UPDATE journal_state SET boot_id = ?", (boot_id,))

    def boot_id(self) -> str:
        assert self._connection is not None
        row = self._connection.execute("SELECT boot_id FROM journal_state").fetchone()
        return row[0] if row else ""

    def begin_apply(self, config: EdgeConfig | dict[str, Any], recovery_snapshot: dict[str, Any]) -> None:
        payload = _edge_config_to_dict(config)
        revision = int(payload["revision"])
        digest = str(payload["digest"])
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT revision, digest FROM pending_apply LIMIT 1"
            ).fetchone()
            if existing is not None and existing[0] == revision and existing[1] == digest:
                return
            conn.execute("DELETE FROM pending_apply")
            conn.execute(
                """
                INSERT INTO pending_apply (
                    revision, digest, config_json, recovery_snapshot_json, started_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    revision,
                    digest,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    json.dumps(recovery_snapshot, separators=(",", ":"), sort_keys=True),
                    _utc_now_iso(),
                ),
            )

    def finish_apply(self, report: EdgeReport | dict[str, Any]) -> int:
        payload = _edge_report_to_dict(report)
        boot_id = str(payload["boot_id"])
        with self._transaction() as conn:
            state = conn.execute(
                "SELECT boot_id, next_report_sequence FROM journal_state"
            ).fetchone()
            if state is None:
                raise JournalError("journal state missing")
            current_boot_id, next_sequence = state
            if current_boot_id and current_boot_id != boot_id:
                raise JournalError("out_of_order_boot_id")
            requested_sequence = payload.get("report_sequence")
            if requested_sequence in (None, 0):
                assigned_sequence = next_sequence
            elif int(requested_sequence) != next_sequence:
                raise JournalError("out_of_order_report_sequence")
            else:
                assigned_sequence = next_sequence
            payload["report_sequence"] = assigned_sequence
            heartbeat_only = payload.get("phase") == "heartbeat"
            if heartbeat_only:
                conn.execute("DELETE FROM pending_reports WHERE heartbeat_only = 1")
            conn.execute("DELETE FROM pending_apply")
            conn.execute(
                """
                INSERT INTO pending_reports (
                    sequence, boot_id, report_json, heartbeat_only, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    next_sequence,
                    boot_id,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    1 if heartbeat_only else 0,
                    _utc_now_iso(),
                ),
            )
            conn.execute(
                "UPDATE journal_state SET boot_id = ?, next_report_sequence = ?",
                (boot_id, next_sequence + 1),
            )
            return next_sequence

    def pending_apply(self) -> PendingApply | None:
        assert self._connection is not None
        row = self._connection.execute(
            """
            SELECT revision, digest, config_json, recovery_snapshot_json
            FROM pending_apply
            ORDER BY started_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return PendingApply(
            revision=row[0],
            digest=row[1],
            config=json.loads(row[2]),
            recovery_snapshot=json.loads(row[3]),
        )

    def pending_reports(self) -> list[PendingReport]:
        assert self._connection is not None
        rows = self._connection.execute(
            """
            SELECT sequence, boot_id, report_json, heartbeat_only
            FROM pending_reports
            ORDER BY sequence ASC
            """
        ).fetchall()
        return [
            PendingReport(
                sequence=row[0],
                boot_id=row[1],
                report=json.loads(row[2]),
                heartbeat_only=bool(row[3]),
            )
            for row in rows
        ]

    def ack_report(self, sequence: int) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM pending_reports WHERE sequence = ?", (sequence,))
