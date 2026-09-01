"""Container health check for the OPC UA connector."""

import logging
import os
import socket
import sys
from collections.abc import Iterable, Sequence

import psutil

from uns_opcua.opcua_config import MQTTConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ProcessSnapshot = tuple[int, Sequence[str]]


def _cmdline_has_connector(cmdline: Sequence[str], name: str) -> bool:
    """True when a cmdline token is the connector entry point, not a sibling script."""
    for token in cmdline:
        base = token.replace("\\", "/").rsplit("/", 1)[-1]
        if base == name or base == f"{name}.exe":
            return True
    return False


def check_process(
    name: str,
    *,
    processes: Iterable[ProcessSnapshot] | None = None,
    current_pid: int | None = None,
) -> bool:
    """Check if the connector process is running.

    Excludes ``current_pid`` (defaults to this process) so the healthcheck never
    matches itself. Matching is token-based: a cmdline entry that is exactly
    ``name``, ``name.exe``, or ends with ``/name`` / ``\\name`` — not sibling
    scripts such as ``uns_opcua_healthcheck`` or ``uns_opcua_validate``.
    """
    if current_pid is None:
        current_pid = os.getpid()
    if processes is None:
        processes = (
            (proc.info["pid"], proc.info.get("cmdline") or [])
            for proc in psutil.process_iter(["pid", "name", "cmdline"])
        )
    for pid, cmdline in processes:
        if pid == current_pid:
            continue
        if _cmdline_has_connector(cmdline, name):
            return True
    return False


def check_existing_connection(host: str, port: int) -> bool:
    """Check if a connection to the specified host and port is already established."""
    try:
        remote_ip = socket.gethostbyname(host)
        for conn in psutil.net_connections("inet"):
            # cSpell:ignore raddr
            if conn.raddr and conn.raddr.port == port and conn.status == "ESTABLISHED":
                if remote_ip in ("127.0.0.1", "::1") or conn.raddr.ip == remote_ip:
                    return True
        return False
    except Exception as ex:
        logger.error(ex)
        return False


def main():
    """
    Healthy means the process is up and the broker connection is established.

    OPC UA sessions are deliberately not checked: a PLC being unreachable is what the
    spool and the reconnect loop are for, and it must not restart the container.
    """
    if not check_process("uns_opcua"):
        sys.exit(1)

    if not check_existing_connection(MQTTConfig.host, MQTTConfig.port):
        sys.exit(1)

    logger.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
