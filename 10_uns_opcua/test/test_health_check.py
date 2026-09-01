"""Tests for connector process detection in the health check."""

import pytest

from uns_opcua.health_check import check_process, main


def test_check_process_does_not_count_healthcheck_script_as_connector():
    # A cmdline that contains the substring "uns_opcua" but is the healthcheck
    # itself must not be treated as the connector process.
    processes = (
        (100, ["python", "uns_opcua_healthcheck"]),
    )
    assert check_process("uns_opcua", processes=processes, current_pid=1) is False


def test_check_process_counts_connector_script():
    processes = (
        (200, ["python", "/opt/venv/bin/uns_opcua"]),
    )
    assert check_process("uns_opcua", processes=processes, current_pid=1) is True


def test_main_passes_without_mqtt_when_no_servers_configured(monkeypatch):
    # Idle stock checkout never opens MQTT; process-up alone is healthy.
    monkeypatch.setattr("uns_opcua.health_check.check_process", lambda *a, **k: True)
    with pytest.raises(SystemExit) as exc:
        main(servers=(), check_connection=lambda _host, _port: False)
    assert exc.value.code == 0


def test_main_requires_mqtt_when_servers_are_configured(monkeypatch):
    monkeypatch.setattr("uns_opcua.health_check.check_process", lambda *a, **k: True)
    with pytest.raises(SystemExit) as exc:
        main(servers=(object(),), check_connection=lambda _host, _port: False)
    assert exc.value.code == 1
