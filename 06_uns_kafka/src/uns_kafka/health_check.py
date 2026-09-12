import logging
import socket
import sys

import psutil

from uns_kafka.uns_kafka_config import IngestionSettings, KAFKAConfig, MQTTConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_ingestion_ready = True
_ingestion_halted = False
_halt_reason: str | None = None


def set_ingestion_ready(ready: bool) -> None:
    global _ingestion_ready
    _ingestion_ready = ready


def set_ingestion_halted(halted: bool, reason: str | None = None) -> None:
    global _ingestion_halted, _halt_reason
    _ingestion_halted = halted
    _halt_reason = reason


def is_ingestion_ready() -> bool:
    return _ingestion_ready and not _ingestion_halted


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
    if not check_process("uns_kafka_mapper"):
        sys.exit(1)

    if not is_ingestion_ready():
        logger.error("Ingestion shard is not ready%s", f": {_halt_reason}" if _halt_reason else "")
        sys.exit(1)

    if IngestionSettings.route_control.enabled and not IngestionSettings.route_control.token:
        logger.error("Route control enabled without route_control.token configured")
        sys.exit(1)

    mqtt_host = MQTTConfig.host
    mqtt_port = MQTTConfig.port
    if not check_existing_connection(mqtt_host, mqtt_port):
        sys.exit(1)

    kafka_url: str = KAFKAConfig.kafka_config_map.get("bootstrap.servers")
    if "://" in kafka_url:
        kafka_url = kafka_url.split("://")[1]
    host_port = kafka_url.split(":")
    kafka_host: str = host_port[0]
    kafka_port: str | None = host_port[1] if len(host_port) > 1 else ""
    if not check_existing_connection(kafka_host, int(kafka_port)):
        sys.exit(1)
    logger.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
