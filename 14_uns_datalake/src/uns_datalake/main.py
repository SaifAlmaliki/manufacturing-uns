"""Entry point for the datalake mapper service."""

from __future__ import annotations

import logging
import signal
import threading

from uns_datalake.config import DatalakeConfig
from uns_datalake.mapper import build_mapper
from uns_datalake.metrics import start_metrics_server

LOGGER = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not DatalakeConfig.is_config_valid():
        raise SystemExit(1)
    start_metrics_server(DatalakeConfig.metrics_port)
    mapper = build_mapper()
    stop = threading.Event()

    def _handle_signal(*_args) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    mapper.start()
    try:
        while not stop.is_set():
            if not mapper.run_once():
                raise SystemExit(1)
    finally:
        mapper.stop()


if __name__ == "__main__":
    main()
