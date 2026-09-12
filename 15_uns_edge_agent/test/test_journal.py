"""Journal durability and locking tests."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from uns_edge_agent.journal import Journal, JournalLockError

from conftest import sample_config, sample_report


def test_begin_apply_survives_restart(data_dir: Path) -> None:
    journal_path = data_dir / "journal.db"
    config = sample_config()
    recovery = {"adapters": []}

    journal = Journal(journal_path)
    journal.open()
    journal.begin_apply(config, recovery)
    journal.close()

    restarted = Journal(journal_path)
    restarted.open()
    pending = restarted.pending_apply()
    restarted.close()

    assert pending is not None
    assert pending.revision == 1
    assert pending.digest == "digest-1"
    assert pending.config["edge_id"] == "edge-test-01"
    assert pending.recovery_snapshot == recovery


def test_report_retries_keep_same_boot_id_sequence_and_content(data_dir: Path) -> None:
    journal_path = data_dir / "journal.db"
    journal = Journal(journal_path)
    journal.open()
    journal.set_boot_id("boot-42")
    report = sample_report(boot_id="boot-42")
    sequence = journal.finish_apply(report)
    pending = journal.pending_reports()
    journal.close()

    reopened = Journal(journal_path)
    reopened.open()
    retried = reopened.pending_reports()
    reopened.close()

    assert sequence == 1
    assert len(retried) == 1
    assert retried[0].boot_id == "boot-42"
    assert retried[0].sequence == 1
    assert retried[0].report["phase"] == "applied"
    assert pending[0].report == retried[0].report


def test_same_revision_digest_begin_apply_is_safe(data_dir: Path) -> None:
    journal = Journal(data_dir / "journal.db")
    journal.open()
    config = sample_config()
    journal.begin_apply(config, {"first": True})
    journal.begin_apply(config, {"second": True})
    pending = journal.pending_apply()
    journal.close()

    assert pending is not None
    assert pending.recovery_snapshot == {"first": True}


def test_ack_report_removes_pending(data_dir: Path) -> None:
    journal = Journal(data_dir / "journal.db")
    journal.open()
    journal.set_boot_id("boot-1")
    sequence = journal.finish_apply(sample_report())
    assert journal.pending_reports()
    journal.ack_report(sequence)
    assert journal.pending_reports() == []
    journal.close()


def _hold_lock(path: Path, ready: multiprocessing.Queue, release: multiprocessing.Queue) -> None:
    journal = Journal(path)
    journal.open()
    ready.put("locked")
    release.get()
    journal.close()


def test_second_process_cannot_acquire_journal_lock(data_dir: Path) -> None:
    journal_path = data_dir / "journal.db"
    ready: multiprocessing.Queue = multiprocessing.Queue()
    release: multiprocessing.Queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_hold_lock,
        args=(journal_path, ready, release),
    )
    process.start()
    assert ready.get(timeout=5) == "locked"

    second = Journal(journal_path)
    with pytest.raises(JournalLockError):
        second.open()

    release.put("go")
    process.join(timeout=5)
    assert process.exitcode == 0

    third = Journal(journal_path)
    third.open()
    third.close()


def test_finish_apply_rejects_older_boot_id(data_dir: Path) -> None:
    journal = Journal(data_dir / "journal.db")
    journal.open()
    journal.set_boot_id("boot-new")
    with pytest.raises(Exception, match="out_of_order_boot_id"):
        journal.finish_apply(sample_report(boot_id="boot-old"))
    journal.close()


def test_heartbeat_reports_coalesce(data_dir: Path) -> None:
    journal = Journal(data_dir / "journal.db")
    journal.open()
    journal.set_boot_id("boot-1")
    first = journal.finish_apply(sample_report(phase="heartbeat", report_sequence=0))
    second = journal.finish_apply(sample_report(phase="heartbeat", report_sequence=0))
    pending = journal.pending_reports()
    journal.close()

    assert first == 1
    assert second == 2
    assert len(pending) == 1
    assert pending[0].heartbeat_only is True
    assert pending[0].sequence == 2
