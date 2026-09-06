"""Entry point: wire the engine together and run one pass every `scan_interval_seconds`.

The only module in `uns_oee` that reads a clock. Everything below takes its timestamp as an
argument (Global Constraint Rule 1), which is what makes a pass replayable and lets
`recompute_cli` reproduce a historical result exactly.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from uns_model.engine import Database
from uns_oee.master_data import MasterDataLoader
from uns_oee.oee_config import OEE_ENV, OeeConfig
from uns_oee.pipeline import ShiftPipeline
from uns_oee.prometheus_metrics import OeeMetrics, read_gauges
from uns_oee.publisher import ResultPublisher
from uns_oee.scheduler import PassSummary, ShiftScheduler
from uns_oee.sources import MetricSource
from uns_oee.store import ResultStore

LOGGER = logging.getLogger(__name__)


def utc_now() -> datetime:
    """The pass timestamp. Named so a test can replace it."""
    return datetime.now(timezone.utc)


def configure_asyncio_for_mqtt() -> None:
    """Windows needs the selector loop for the MQTT client. Harmless everywhere else."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def build_scheduler(
    config: OeeConfig, database: Database, publisher: ResultPublisher | None
) -> ShiftScheduler:
    """Assemble the engine's read, compute, store and publish layers.

    One `MetricSource` and one `MasterDataLoader` shared between the scheduler and the
    pipeline: both hold nothing but their connection source, and a thirty-day backfill would
    otherwise build sixty of them.
    """
    source = MetricSource(
        database,
        metrics_table=config.metrics_table,
        prior_lookback_hours=config.prior_lookback_hours,
    )
    master = MasterDataLoader(database)
    pipeline = ShiftPipeline(source, master, ResultStore(database), publisher)
    return ShiftScheduler(config, database, source, master, pipeline)


class OeeService:
    """The supervisor loop.

    Takes its scheduler, metrics, clock and gauge reader as arguments so the loop's behaviour -
    what it does when a pass fails, when it stops - is testable without a database or a broker.
    """

    def __init__(
        self,
        config: OeeConfig,
        database: Any,
        scheduler: Any,
        metrics: OeeMetrics,
        *,
        clock: Callable[[], datetime] = utc_now,
        gauges: Callable[[Any], Any] = read_gauges,
    ) -> None:
        self._config = config
        self._database = database
        self._scheduler = scheduler
        self._metrics = metrics
        self._clock = clock
        self._gauges = gauges
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Ask the loop to finish the current pass and return. Signal-handler safe."""
        self._stop.set()

    async def run_once(self) -> PassSummary | None:
        """One pass, then the database gauges. None means the pass failed.

        The gauges are read whether or not the pass succeeded: during an outage the recompute
        queue depth and the unpublished backlog are the two numbers worth having.
        """
        try:
            summary = await self._scheduler.run_pass(self._clock())
        except asyncio.CancelledError:
            raise
        except Exception:
            # Nothing was committed, so the next pass recomputes the same shifts. See the
            # module note: this is not counted, because `_last_shift_close_timestamp` going
            # stale is the honest alert for an engine that has stopped producing.
            LOGGER.exception("OEE pass failed; the next pass will pick up the same shifts")
            summary = None
        else:
            self._metrics.observe_pass(summary)
            LOGGER.info(
                "OEE pass over %d unit(s) computed %d shift(s) with %d failure(s)",
                summary.units,
                len(summary.outcomes),
                summary.failures,
            )
        self._metrics.apply(await self._gauges(self._database))
        return summary

    async def run_forever(self) -> None:
        """Pass, wait, repeat, until `request_stop`."""
        LOGGER.info(
            "OEE engine started; a pass every %.0fs, settling %d minutes after each shift",
            self._config.scan_interval_seconds,
            self._config.settle_minutes,
        )
        while not self._stop.is_set():
            await self.run_once()
            await self._wait_for_next_pass()
        LOGGER.info("OEE engine stopped")

    async def _wait_for_next_pass(self) -> None:
        """Sleep the scan interval, or less if asked to stop.

        `wait_for` on the stop event rather than `sleep`, so SIGTERM is acted on immediately
        instead of up to five minutes later - long enough for Docker to escalate to SIGKILL.
        """
        try:
            await asyncio.wait_for(
                self._stop.wait(), timeout=self._config.scan_interval_seconds
            )
        except TimeoutError:
            return


def _install_signal_handlers(service: OeeService) -> None:
    """Route SIGINT and SIGTERM to a clean stop where the platform allows it."""
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        handled = getattr(signal, name, None)
        if handled is None:
            continue
        try:
            loop.add_signal_handler(handled, service.request_stop)
        except NotImplementedError:
            # Windows asyncio has no add_signal_handler. `docker stop` sends SIGTERM to a
            # Linux container, which is the case that matters; on Windows the
            # KeyboardInterrupt path in `main` is the stop.
            LOGGER.debug("No asyncio handler for %s on this platform", name)


async def run(config: OeeConfig | None = None) -> None:
    """Start the metrics server, run the loop, and close the broker and the pool."""
    config = config if config is not None else OeeConfig.from_settings()
    if not config.is_valid():
        raise SystemExit("OEE engine is not configured; see conf/settings.yaml")

    database = Database.shared(OEE_ENV)
    publisher = ResultPublisher(config)
    metrics = OeeMetrics()
    # Before the first pass, so a scrape during startup returns zeros rather than a refused
    # connection - which is also what makes the container's health check pass immediately.
    metrics.serve(config.metrics_port)

    service = OeeService(config, database, build_scheduler(config, database, publisher), metrics)
    _install_signal_handlers(service)
    try:
        await service.run_forever()
    finally:
        # The publisher first: it holds a broker connection that a clean DISCONNECT closes,
        # and it needs nothing from the database to do it.
        await publisher.aclose()
        await Database.close_shared()


def main() -> None:
    """Console entry point `uns_oee`."""
    configure_asyncio_for_mqtt()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        LOGGER.info("OEE engine interrupted")


if __name__ == "__main__":
    main()
