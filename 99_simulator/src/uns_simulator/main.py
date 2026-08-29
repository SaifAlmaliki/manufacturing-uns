#!/usr/bin/env python3
"""Main entry point for the simulator"""

import asyncio
import sys

from uns_simulator.config import settings
from uns_simulator.simulator import UnifiedNamespaceSimulator


def configure_asyncio_for_mqtt() -> None:
    """aiomqtt/paho need add_reader/add_writer, which Windows ProactorEventLoop lacks."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run() -> None:
    """Run the simulator"""
    simulator = UnifiedNamespaceSimulator()
    await simulator.run_simulation(settings.get("simulation.duration", 60))


def main() -> None:
    configure_asyncio_for_mqtt()
    asyncio.run(run())


def run_simulator() -> None:
    """Backward-compatible alias for the console script."""
    main()


if __name__ == "__main__":
    main()
