"""Prometheus metrics for the datalake Mapper."""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import Counter, Gauge, start_http_server


class DatalakeMetrics:
    def __init__(self, port: int) -> None:
        self._port = port
        self._flushes = Counter("uns_datalake_flushes_total", "Completed flushes with rows")
        self._skips = Counter("uns_datalake_skips_total", "Poison or skipped envelopes")
        self._put_errors = Counter("uns_datalake_put_errors_total", "Object store put failures")
        self._commit_errors = Counter("uns_datalake_commit_errors_total", "Kafka commit failures")
        self._last_put = Gauge("uns_datalake_last_put_timestamp_seconds", "Unix time of last successful put")
        self._last_loop = Gauge("uns_datalake_last_loop_timestamp_seconds", "Unix time of last mapper loop tick")
        self._up = Gauge("uns_datalake_up", "Mapper process liveness")
        self._ready = Gauge("uns_datalake_ready", "Mapper dependency readiness")
        self._up.set(1)
        self._ready.set(0)

    def start(self) -> None:
        start_http_server(self._port)

    def record_flush(self) -> None:
        self._flushes.inc()

    def record_skip(self) -> None:
        self._skips.inc()

    def record_put_error(self) -> None:
        self._put_errors.inc()

    def record_commit_error(self) -> None:
        self._commit_errors.inc()

    def record_put_success(self) -> None:
        self._last_put.set(time.time())

    def record_loop(self) -> None:
        self._last_loop.set(time.time())

    def set_up(self, value: bool) -> None:
        self._up.set(1 if value else 0)

    def set_ready(self, value: bool) -> None:
        self._ready.set(1 if value else 0)
