"""Tests for uns_oee.health_check.

The opener is injected, so no test binds a port. What is being tested is the decision -
which answers count as healthy - not urllib.
"""

from urllib.error import URLError

import pytest

from uns_oee.health_check import HEALTH_SERIES, check_metrics_endpoint, main


class FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def opener(response):
    def _open(url, timeout=None):  # noqa: ARG001
        if isinstance(response, Exception):
            raise response
        return response

    return _open


def test_an_endpoint_serving_the_engines_registry_is_healthy():
    body = f"# HELP {HEALTH_SERIES} up\n# TYPE {HEALTH_SERIES} gauge\n{HEALTH_SERIES} 0.0\n"
    assert check_metrics_endpoint(9095, opener=opener(FakeResponse(body)))


def test_an_endpoint_serving_someone_elses_registry_is_not_healthy():
    # A port answering with the historian's series means this container is not the process
    # the health check was asked about.
    assert not check_metrics_endpoint(9095, opener=opener(FakeResponse("uns_historian_up 1.0\n")))


def test_a_non_200_answer_is_not_healthy():
    assert not check_metrics_endpoint(9095, opener=opener(FakeResponse("", status=503)))


def test_a_refused_connection_is_not_healthy():
    assert not check_metrics_endpoint(9095, opener=opener(URLError("connection refused")))


def test_main_exits_zero_when_healthy(monkeypatch):
    monkeypatch.setattr("uns_oee.health_check.check_metrics_endpoint", lambda port: True)
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0


def test_main_exits_one_when_not(monkeypatch):
    monkeypatch.setattr("uns_oee.health_check.check_metrics_endpoint", lambda port: False)
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1
