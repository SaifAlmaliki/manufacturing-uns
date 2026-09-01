"""The simulator's own ports. Read at import time, exactly as MQTTConfig does."""

from uns_simulator.config import SimulatorAPIConfig


def test_the_control_api_port_comes_from_settings():
    assert SimulatorAPIConfig.api_port == 8099


def test_the_metrics_port_comes_from_settings():
    assert SimulatorAPIConfig.metrics_port == 9093


def test_the_metrics_port_does_not_collide_with_another_client():
    """9090 is Prometheus, 9091 the historian, 9092 the graph database (spec 2, finding 8).

    A collision does not fail loudly: whichever container starts second logs an address-in-use
    error and keeps running with no metrics at all.
    """
    assert SimulatorAPIConfig.metrics_port not in (9090, 9091, 9092)


def test_the_api_binds_all_interfaces_so_the_container_is_reachable():
    assert SimulatorAPIConfig.api_host == "0.0.0.0"  # noqa: S104


def test_a_token_is_only_required_when_one_is_configured(monkeypatch):
    """Spec 10: no token in the secrets file means an open API, which is the default."""
    monkeypatch.setattr(SimulatorAPIConfig, "token", None)
    assert SimulatorAPIConfig.is_token_required() is False
    monkeypatch.setattr(SimulatorAPIConfig, "token", "s3cret")
    assert SimulatorAPIConfig.is_token_required() is True
