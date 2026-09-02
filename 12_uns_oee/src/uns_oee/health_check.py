"""Docker health check for the OEE engine: `uns_oee_health`.

One question - is this process up and serving its own registry - answered by scraping
127.0.0.1 on the metrics port. That strictly implies the `psutil` process check the other
modules perform, and needs no dependency beyond the standard library.

Deliberately does not probe Postgres or MQTT. Docker restarts an unhealthy container, and
restarting this one because Timescale is rebooting would fix nothing while discarding the
backfill state. Database health is `uns_oee_db_up` plus an alert, not a restart policy.
"""

import logging
import sys
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from uns_oee.oee_config import OeeConfig

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

#: The series whose presence proves the endpoint belongs to this engine. Unlabelled, so it is
#: exposed from construction onwards and a container that has not yet run a pass is healthy.
HEALTH_SERIES = "uns_oee_db_up"

#: Shorter than Docker's default 30s healthcheck timeout, so a hung endpoint is reported as
#: unhealthy rather than as a timed-out check.
DEFAULT_TIMEOUT_S = 5.0


def check_metrics_endpoint(
    port: int,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    opener: Callable[..., Any] = urlopen,
) -> bool:
    """Whether the local metrics endpoint answers with this engine's series."""
    url = f"http://127.0.0.1:{port}/metrics"
    try:
        with opener(url, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                LOGGER.error("Metrics endpoint %s answered %s", url, response.status)
                return False
            body = response.read().decode("utf-8", errors="replace")
    except Exception as ex:
        LOGGER.error("Metrics endpoint %s did not answer: %s", url, ex)
        return False
    if HEALTH_SERIES not in body:
        LOGGER.error("Metrics endpoint %s is not serving %s", url, HEALTH_SERIES)
        return False
    return True


def main() -> None:
    """Console entry point `uns_oee_health`. Exit 0 healthy, 1 not."""
    config = OeeConfig.from_settings()
    if not check_metrics_endpoint(config.metrics_port):
        sys.exit(1)
    LOGGER.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
