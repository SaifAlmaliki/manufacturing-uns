"""Poll loop timing, backoff, and lease behavior tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from uns_edge_agent.cloud_client import CloudClientError
from uns_edge_agent.polling import PollLoop, PollLoopConfig

from conftest import FakeClock, FakeCloud, sample_config


class CloudAdapter:
    def __init__(self, fake: FakeCloud) -> None:
        self._fake = fake

    def open_session(self, boot_id: str):
        return self._fake.open_session(boot_id)

    def get_configuration(self, lease, *, if_none_match=None):
        return self._fake.get_configuration(lease, if_none_match=if_none_match)

    def submit_report(self, lease, report):
        return self._fake.submit_report(lease, report)


def _loop(fake_cloud: FakeCloud, journal, clock: FakeClock) -> PollLoop:
    fake_cloud.configuration = sample_config()
    return PollLoop(
        cloud_client=CloudAdapter(fake_cloud),
        journal=journal,
        clock=clock,
        config=PollLoopConfig(
            poll_interval_seconds=15.0,
            poll_jitter_seconds=0.0,
            heartbeat_interval_seconds=30.0,
            max_backoff_seconds=300.0,
        ),
        rng=__import__("random").Random(0),
        edge_id_loader=lambda: "edge-test-01",
    )


def test_poll_uses_fifteen_second_interval_with_zero_jitter(journal, fake_cloud: FakeCloud) -> None:
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    delay = loop._poll_delay()
    assert abs(delay - 15.0) < 0.01


def test_heartbeat_sent_after_thirty_seconds(journal, fake_cloud: FakeCloud) -> None:
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    loop.state.boot_id = "boot-heartbeat"
    journal.set_boot_id("boot-heartbeat")

    loop.run_once()
    assert fake_cloud.reports
    assert fake_cloud.reports[-1]["phase"] == "heartbeat"
    fake_cloud.reports.clear()

    clock.advance(30.0)
    loop.run_once()
    assert fake_cloud.reports
    assert fake_cloud.reports[-1]["phase"] == "heartbeat"


def test_etag_returns_not_modified_without_reprocessing(journal, fake_cloud: FakeCloud) -> None:
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    loop.run_once()
    assert fake_cloud.config_requests == [None]
    loop.state.config_etag = fake_cloud.configuration_digest
    loop.run_once()
    assert fake_cloud.config_requests[-1] == '"digest-1"'
    assert journal.pending_apply() is None


def test_backoff_caps_at_five_minutes(journal, fake_cloud: FakeCloud) -> None:
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    fake_cloud.fail_next = 100
    for _ in range(10):
        loop.poll_configuration()
    assert loop.state.backoff_seconds == 300.0


def test_graceful_shutdown_stops_sleep_loop(journal, fake_cloud: FakeCloud) -> None:
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    loop.stop()
    loop.run_until_stopped()
    assert loop.state.running is False


def test_transient_https_outage_does_not_crash_loop(journal, fake_cloud: FakeCloud) -> None:
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    fake_cloud.fail_next = 1
    loop.run_once()
    fake_cloud.fail_next = 0
    loop.run_once()
    assert loop.state.cloud_connected is True


def test_rejects_out_of_order_reports_from_older_session(journal, fake_cloud: FakeCloud) -> None:
    journal.set_boot_id("boot-old")
    journal.finish_apply(
        {
            "edge_id": "edge-test-01",
            "boot_id": "boot-old",
            "report_sequence": 0,
            "desired_revision": 0,
            "applied_revision": 0,
            "applied_digest": "",
            "phase": "heartbeat",
            "adapter_results": [],
            "last_error_code": None,
            "versions": {},
            "capabilities": {},
        }
    )
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    loop.state.boot_id = "boot-new"
    loop.flush_pending_reports()
    assert fake_cloud.reports == []
    assert journal.pending_reports()


def test_lease_renewed_when_expiring(journal, fake_cloud: FakeCloud) -> None:
    clock = FakeClock()
    loop = _loop(fake_cloud, journal, clock)
    loop.ensure_session()
    assert loop.state.lease is not None
    loop.state.lease = replace(
        loop.state.lease,
        expires_at=datetime.now(UTC) + timedelta(seconds=10),
    )
    loop.ensure_session()
    assert len(fake_cloud.session_calls) == 2
