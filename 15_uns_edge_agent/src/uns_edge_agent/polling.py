"""Injected-clock poll loop for cloud configuration and heartbeats."""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from uns_edge_agent.cloud_client import CloudClient, CloudClientError, ConfigurationSnapshot, Lease
from uns_edge_agent.config import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_BACKOFF_SECONDS,
    POLL_INTERVAL_SECONDS,
    POLL_JITTER_SECONDS,
)
from uns_edge_agent.journal import Journal, JournalError


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass
class PollLoopConfig:
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    poll_jitter_seconds: float = POLL_JITTER_SECONDS
    heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS
    max_backoff_seconds: float = MAX_BACKOFF_SECONDS
    lease_renew_before_seconds: float = 30.0


@dataclass
class PollLoopState:
    boot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    lease: Lease | None = None
    last_poll_at: float = 0.0
    last_heartbeat_at: float = -HEARTBEAT_INTERVAL_SECONDS
    config_etag: str | None = None
    backoff_until: float = 0.0
    backoff_seconds: float = 0.0
    running: bool = True
    cloud_connected: bool = False
    lease_valid: bool = False


class PollLoop:
    """Outbound poll loop with jitter, heartbeats, ETags, and bounded backoff."""

    def __init__(
        self,
        *,
        cloud_client: CloudClient,
        journal: Journal,
        clock: Clock | None = None,
        config: PollLoopConfig | None = None,
        rng: random.Random | None = None,
        on_configuration: Callable[[ConfigurationSnapshot], None] | None = None,
        edge_id_loader: Callable[[], str] | None = None,
    ) -> None:
        self._cloud = cloud_client
        self._journal = journal
        self._clock = clock or SystemClock()
        self._config = config or PollLoopConfig()
        self._rng = rng or random.Random(0)
        self._on_configuration = on_configuration
        self._edge_id_loader = edge_id_loader
        self.state = PollLoopState()

    def stop(self) -> None:
        self.state.running = False

    def _now(self) -> float:
        return self._clock.monotonic()

    def _poll_delay(self) -> float:
        jitter = self._rng.uniform(-self._config.poll_jitter_seconds, self._config.poll_jitter_seconds)
        return max(0.0, self._config.poll_interval_seconds + jitter)

    def _register_backoff(self) -> None:
        if self.state.backoff_seconds <= 0:
            self.state.backoff_seconds = self._config.poll_interval_seconds
        else:
            self.state.backoff_seconds = min(
                self.state.backoff_seconds * 2,
                self._config.max_backoff_seconds,
            )
        self.state.backoff_until = self._now() + self.state.backoff_seconds

    def _clear_backoff(self) -> None:
        self.state.backoff_seconds = 0.0
        self.state.backoff_until = 0.0

    def _lease_expiring(self) -> bool:
        if self.state.lease is None:
            return True
        remaining = (self.state.lease.expires_at - datetime.now(self.state.lease.expires_at.tzinfo)).total_seconds()
        return remaining <= self._config.lease_renew_before_seconds

    def ensure_session(self) -> bool:
        if self.state.lease is not None and not self._lease_expiring():
            self.state.lease_valid = True
            return True
        try:
            self.state.lease = self._cloud.open_session(self.state.boot_id)
            self._journal.set_boot_id(self.state.boot_id)
            self.state.cloud_connected = True
            self.state.lease_valid = True
            self._clear_backoff()
            return True
        except CloudClientError:
            self.state.cloud_connected = False
            self.state.lease_valid = False
            self._register_backoff()
            return False

    def flush_pending_reports(self) -> None:
        if not self.ensure_session() or self.state.lease is None:
            return
        for pending in self._journal.pending_reports():
            if pending.boot_id != self.state.boot_id:
                continue
            try:
                self._cloud.submit_report(self.state.lease, pending.report)
            except CloudClientError:
                self._register_backoff()
                return
            self._journal.ack_report(pending.sequence)

    def send_heartbeat_if_due(self) -> None:
        now = self._now()
        if now - self.state.last_heartbeat_at < self._config.heartbeat_interval_seconds:
            return
        if not self.ensure_session() or self.state.lease is None:
            return
        edge_id = self._edge_id()
        report = _heartbeat_report(edge_id, self.state.boot_id)
        try:
            sequence = self._journal.finish_apply(report)
            report["report_sequence"] = sequence
            self._cloud.submit_report(self.state.lease, report)
            self._journal.ack_report(sequence)
            self.state.last_heartbeat_at = now
            self._clear_backoff()
        except CloudClientError:
            self._register_backoff()
        except JournalError:
            self._register_backoff()

    def poll_configuration(self) -> ConfigurationSnapshot | None:
        if not self.ensure_session() or self.state.lease is None:
            return None
        etag = f'"{self.state.config_etag}"' if self.state.config_etag else None
        try:
            snapshot = self._cloud.get_configuration(self.state.lease, if_none_match=etag)
        except CloudClientError:
            self._register_backoff()
            return None
        self.state.last_poll_at = self._now()
        self._clear_backoff()
        if snapshot is None:
            return None
        self.state.config_etag = snapshot.digest
        if self._on_configuration is not None:
            self._on_configuration(snapshot)
        return snapshot

    def run_once(self) -> None:
        self.flush_pending_reports()
        self.send_heartbeat_if_due()
        self.poll_configuration()

    def run_until_stopped(self) -> None:
        while self.state.running:
            now = self._now()
            if now < self.state.backoff_until:
                self._clock.sleep(min(1.0, self.state.backoff_until - now))
                continue
            self.run_once()
            if not self.state.running:
                break
            self._clock.sleep(self._poll_delay())

    def _edge_id(self) -> str:
        if self._edge_id_loader is not None:
            return self._edge_id_loader()
        pending = self._journal.pending_apply()
        if pending is not None:
            return str(pending.config.get("edge_id", "unknown"))
        return "unknown"


def _heartbeat_report(edge_id: str, boot_id: str) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "boot_id": boot_id,
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
