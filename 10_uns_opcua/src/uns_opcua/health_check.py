"""Container health check for the OPC UA connector."""

import logging
import socket
import sys

import psutil

from uns_opcua.opcua_config import MQTTConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_process(name: str) -> bool:
    """Check if the process is running."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        cmdline = proc.info.get("cmdline") or []
        if name in " ".join(cmdline):
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
