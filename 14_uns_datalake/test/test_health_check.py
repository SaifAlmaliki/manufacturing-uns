from io import BytesIO
from unittest.mock import Mock

from uns_datalake.health_check import check_metrics_endpoint


def _body(up: int, last_loop: float) -> bytes:
    return f"uns_datalake_up {up}\nuns_datalake_ready 0\nuns_datalake_last_loop_timestamp_seconds {last_loop}\n".encode()


def test_ready_zero_still_passes_when_up_and_loop_fresh():
    now = 1_000_000.0
    response = Mock(status=200)
    response.read.return_value = _body(1, now - 5)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    assert check_metrics_endpoint(9096, now=now, opener=lambda *_a, **_k: response)


def test_up_zero_fails():
    now = 1_000_000.0
    response = Mock(status=200)
    response.read.return_value = _body(0, now - 5)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    assert not check_metrics_endpoint(9096, now=now, opener=lambda *_a, **_k: response)


def test_missing_loop_series_fails():
    response = Mock(status=200)
    response.read.return_value = b"uns_datalake_up 1\n"
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    assert not check_metrics_endpoint(9096, now=1_000_000.0, opener=lambda *_a, **_k: response)


def test_stale_loop_fails():
    now = 1_000_000.0
    response = Mock(status=200)
    response.read.return_value = _body(1, now - 120)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    assert not check_metrics_endpoint(9096, now=now, opener=lambda *_a, **_k: response)


def test_http_failure_fails():
    def opener(*_args, **_kwargs):
        raise OSError("connection refused")

    assert not check_metrics_endpoint(9096, opener=opener)
