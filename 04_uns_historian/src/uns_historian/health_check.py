import logging
import socket
import sys

import psutil

from uns_historian.historian_config import HistorianConfig, KafkaConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_consumer_ready = True
_consumer_halted = False
_halt_reason: str | None = None


def set_consumer_ready(ready: bool) -> None:
    global _consumer_ready
    _consumer_ready = ready


def set_consumer_halted(halted: bool, reason: str | None = None) -> None:
    global _consumer_halted, _halt_reason
    _consumer_halted = halted
    _halt_reason = reason


def is_consumer_ready() -> bool:
    return _consumer_ready and not _consumer_halted


def check_process(name: str) -> bool:
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        cmdline = proc.info.get("cmdline", [])
        if any(name in " ".join(cmdline) for part in cmdline):
            return True
    return False


def check_existing_connection(host: str, port: int) -> bool:
    try:
        remote_ip = socket.gethostbyname(host)
        connections = psutil.net_connections("inet")
        for conn in connections:
            if conn.raddr and conn.raddr.port == port and conn.status == "ESTABLISHED":
                if remote_ip in {"127.0.0.1", "::1"}:
                    return True
                if conn.raddr.ip == remote_ip:
                    return True
        return False
    except Exception as ex:
        logger.error(ex)
        return False


def main():
    if not check_process("uns_historian"):
        sys.exit(1)

    if not is_consumer_ready():
        logger.error("Historian consumer is not ready%s", f": {_halt_reason}" if _halt_reason else "")
        sys.exit(1)

    kafka_url: str = KafkaConfig.consumer_config.get("bootstrap.servers", "")
    if "://" in kafka_url:
        kafka_url = kafka_url.split("://")[1]
    host_port = kafka_url.split(":")
    kafka_host = host_port[0]
    kafka_port = int(host_port[1]) if len(host_port) > 1 else 9092
    if not check_existing_connection(kafka_host, kafka_port):
        sys.exit(1)

    historian_host = HistorianConfig.hostname
    historian_port = int(HistorianConfig.port or 5432)
    if not check_existing_connection(historian_host, historian_port):
        sys.exit(1)

    logger.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
