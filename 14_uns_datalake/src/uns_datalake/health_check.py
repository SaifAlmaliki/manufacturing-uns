"""Health checks for the datalake mapper."""

from __future__ import annotations

import logging
import sys
import time

import psutil

from uns_datalake.config import DatalakeConfig

LOGGER = logging.getLogger(__name__)

_consumer_ready = False
_replay_failure: str | None = None
_integrity_failure = False
_last_heartbeat = 0.0
HEARTBEAT_MAX_AGE_SECONDS = 60.0


def set_consumer_ready(ready: bool) -> None:
    global _consumer_ready
    _consumer_ready = ready


def set_replay_failure(reason: str | None) -> None:
    global _replay_failure
    _replay_failure = reason


def set_integrity_failure(failed: bool) -> None:
    global _integrity_failure
    _integrity_failure = failed


def touch_heartbeat(now: float | None = None) -> None:
    global _last_heartbeat
    _last_heartbeat = time.time() if now is None else now


def is_consumer_ready() -> bool:
    return _consumer_ready


def replay_failure_reason() -> str | None:
    return _replay_failure


def integrity_failure_active() -> bool:
    return _integrity_failure


def heartbeat_is_fresh(now: float | None = None) -> bool:
    instant = time.time() if now is None else now
    return instant - _last_heartbeat <= HEARTBEAT_MAX_AGE_SECONDS


def is_live(now: float | None = None) -> bool:
    return heartbeat_is_fresh(now)


def is_ready(now: float | None = None) -> bool:
    return (
        is_consumer_ready()
        and replay_failure_reason() is None
        and not integrity_failure_active()
        and heartbeat_is_fresh(now)
    )


def check_process(name: str) -> bool:
    for proc in psutil.process_iter(["cmdline"]):
        cmdline = proc.info.get("cmdline") or []
        if any(name in part for part in cmdline):
            return True
    return False


def main() -> None:
    if not check_process("uns_datalake"):
        sys.exit(1)
    if not is_live():
        LOGGER.error("Datalake mapper heartbeat is stale")
        sys.exit(1)
    if not is_ready():
        LOGGER.error(
            "Datalake mapper is not ready: consumer_ready=%s replay_failure=%s integrity_failure=%s",
            is_consumer_ready(),
            replay_failure_reason(),
            integrity_failure_active(),
        )
        sys.exit(1)
    bootstrap = DatalakeConfig.kafka_consumer_config().get("bootstrap.servers", "")
    if not bootstrap:
        LOGGER.error("Kafka bootstrap servers are not configured")
        sys.exit(1)
    LOGGER.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
