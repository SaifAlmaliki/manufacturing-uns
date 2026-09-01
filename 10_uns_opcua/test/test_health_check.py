"""Tests for connector process detection in the health check."""

from uns_opcua.health_check import check_process


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
