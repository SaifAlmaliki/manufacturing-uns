"""Unit tests for Prometheus metrics server lifecycle."""

from __future__ import annotations

import errno

import pytest

from uns_kafka import prometheus_metrics


@pytest.fixture(autouse=True)
def _reset_metrics_server_state():
    started = getattr(prometheus_metrics, "_started_ports", None)
    if started is not None:
        started.clear()
    yield
    if started is not None:
        started.clear()


def test_start_metrics_server_is_idempotent_in_the_same_process(monkeypatch):
    calls: list[int] = []

    def fake_start_http_server(port: int) -> None:
        calls.append(port)

    monkeypatch.setattr(prometheus_metrics, "start_http_server", fake_start_http_server)

    prometheus_metrics.start_metrics_server(9094)
    prometheus_metrics.start_metrics_server(9094)

    assert calls == [9094]


def test_start_metrics_server_reuses_an_already_bound_port(monkeypatch):
    def fake_start_http_server(_port: int) -> None:
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(prometheus_metrics, "start_http_server", fake_start_http_server)

    prometheus_metrics.start_metrics_server(9094)


def test_start_metrics_server_still_raises_unexpected_bind_errors(monkeypatch):
    def fake_start_http_server(_port: int) -> None:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(prometheus_metrics, "start_http_server", fake_start_http_server)

    with pytest.raises(OSError, match="Permission denied"):
        prometheus_metrics.start_metrics_server(9094)
