"""Entry point: the simulation, and the three surfaces that observe and command it.

The control API and the self-telemetry run as tasks in the simulation's own event loop
rather than in a thread or a second process. That is what lets an HTTP handler read
`simulator.status()` and get the truth — one copy of the state, one loop touching it.
"""

import asyncio
import contextlib
import logging
import sys

import uvicorn

from uns_simulator.api import create_app
from uns_simulator.config import SimulatorAPIConfig, settings
from uns_simulator.metrics import start_metrics_server
from uns_simulator.self_telemetry import SelfTelemetry
from uns_simulator.simulator import UnifiedNamespaceSimulator

LOGGER = logging.getLogger(__name__)


class _EmbeddedServer(uvicorn.Server):
    """A uvicorn server that leaves the process's signal handlers alone.

    uvicorn installs its own SIGINT handler in `serve()`. Here that would take Ctrl-C away
    from `run_simulation`'s KeyboardInterrupt path, so the plant would never shut down
    cleanly and every device would stay connected to the broker. This process is the
    simulation; the HTTP server is a guest in its event loop.
    """

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def configure_asyncio_for_mqtt() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run() -> None:
    simulator = UnifiedNamespaceSimulator()

    # A background thread of its own, from prometheus_client. Started before anything
    # publishes so a scrape during startup returns zeros rather than a refused connection.
    start_metrics_server(simulator, SimulatorAPIConfig.metrics_port)

    telemetry = SelfTelemetry(simulator, settings.get("platform.instance_name", "Instance01"))
    # Registered before the plant starts moving: the first transitions of a run are exactly
    # the ones worth seeing.
    simulator.on_plant_transition(telemetry.on_transition)

    server = _EmbeddedServer(
        uvicorn.Config(
            create_app(simulator, token=SimulatorAPIConfig.token),
            host=SimulatorAPIConfig.api_host,
            port=SimulatorAPIConfig.api_port,
            # The console polls twice a second. An access log line per poll would bury
            # every message that matters.
            access_log=False,
            log_level="warning",
        )
    )
    api_task = asyncio.create_task(server.serve())
    telemetry_task = asyncio.create_task(telemetry.run())
    LOGGER.info(
        "Simulator control API on http://%s:%d/simulator (docs at /simulator/docs)",
        SimulatorAPIConfig.api_host,
        SimulatorAPIConfig.api_port,
    )

    try:
        await simulator.run_simulation(settings.get("simulation.duration", 60))
    finally:
        await telemetry.stop()
        server.should_exit = True
        await asyncio.gather(api_task, telemetry_task, return_exceptions=True)


def main() -> None:
    configure_asyncio_for_mqtt()
    asyncio.run(run())


def run_simulator() -> None:
    main()


if __name__ == "__main__":
    main()
