"""Health checks for the datalake mapper."""

from __future__ import annotations

import logging
import sys
import time

import psutil

from uns_datalake.config import DatalakeConfig

LOGGER = logging.getLogger(__name__)

_consumer_ready = False
_last_heartbeat = 0.0
HEARTBEAT_MAX_AGE_SECONDS = 60.0


def set_consumer_ready(ready: bool) -> None:
    global _consumer_ready
    _consumer_ready = ready


def touch_heartbeat(now: float | None = None) -> None:
    global _last_heartbeat
    _last_heartbeat = time.time() if now is None else now


def is_consumer_ready() -> bool:
    return _consumer_ready


def heartbeat_is_fresh(now: float | None = None) -> bool:
    instant = time.time() if now is None else now
    return instant - _last_heartbeat <= HEARTBEAT_MAX_AGE_SECONDS


def check_process(name: str) -> bool:
    for proc in psutil.process_iter(["cmdline"]):
        cmdline = proc.info.get("cmdline") or []
        if any(name in part for part in cmdline):
            return True
    return False


def main() -> None:
    if not check_process("uns_datalake"):
        sys.exit(1)
    if not is_consumer_ready() or not heartbeat_is_fresh():
        LOGGER.error("Datalake mapper is not ready or heartbeat is stale")
        sys.exit(1)
    bootstrap = DatalakeConfig.kafka_consumer_config().get("bootstrap.servers", "")
    if not bootstrap:
        LOGGER.error("Kafka bootstrap servers are not configured")
        sys.exit(1)
    LOGGER.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
