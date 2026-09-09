"""Docker health check for the datalake Mapper."""

from __future__ import annotations

import logging
import re
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from uns_datalake.config import DatalakeConfig

LOGGER = logging.getLogger(__name__)
LOOP_MAX_AGE_SECONDS = 60.0
DEFAULT_TIMEOUT_S = 5.0


def _parse_sample(body: str, name: str) -> float | None:
    pattern = re.compile(rf"^{name}\s+([0-9.eE+-]+)", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return None
    return float(match.group(1))


def check_metrics_endpoint(
    port: int,
    *,
    now: float | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    opener: Callable[..., Any] = urlopen,
) -> bool:
    """Whether the mapper is up and its loop heartbeat is fresh."""
    url = f"http://127.0.0.1:{port}/metrics"
    current = now if now is not None else time.time()
    try:
        with opener(url, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                LOGGER.error("Metrics endpoint %s answered %s", url, response.status)
                return False
            body = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        LOGGER.error("Metrics endpoint %s did not answer: %s", url, exc)
        return False

    up = _parse_sample(body, "uns_datalake_up")
    if up != 1.0:
        LOGGER.error("uns_datalake_up is not 1")
        return False

    last_loop = _parse_sample(body, "uns_datalake_last_loop_timestamp_seconds")
    if last_loop is None:
        LOGGER.error("missing uns_datalake_last_loop_timestamp_seconds")
        return False
    if current - last_loop >= LOOP_MAX_AGE_SECONDS:
        LOGGER.error("loop heartbeat too old")
        return False

    return True


def main() -> None:
    config = DatalakeConfig.from_settings()
    if not check_metrics_endpoint(config.metrics_port):
        sys.exit(1)
    LOGGER.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
