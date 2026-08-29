import asyncio
import logging
from typing import Any

from uns_simulator.config import settings
from uns_simulator.devices import HMI, PLC, SCADA
from uns_simulator.models import ISA95Hierarchy

LOGGER = logging.getLogger(__name__)


def resolve_simulation_duration(
    duration_minutes: int | float | str | None,
    simulation_config: Any,
) -> int:
    """Return configured duration in minutes. 0 means run until stopped."""
    if duration_minutes is not None:
        return int(duration_minutes)
    configured = simulation_config.get("duration")
    if configured is None:
        configured = simulation_config.get("duration_minutes", 5)
    return int(configured)


class UnifiedNamespaceSimulator:
    """Main simulator class following unifiednamespace patterns"""

    def __init__(self):
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchy = ISA95Hierarchy(**settings.hierarchy)
        self.devices: list = []
        self.tasks: list[asyncio.Task] = []

    def create_plc(self) -> list[PLC]:
        """Create PLC instances from configuration"""
        plc_list = []
        plc_count = self.simulation_config.get('plc_count', 2)

        for i in range(plc_count):
            plc_id = f"{i + 1:03d}"
            equipment_config = settings.get("equipment.mixer_tank")

            if equipment_config:
                plc = PLC(
                    plc_id=plc_id,
                    hierarchy=self.hierarchy,
                    mqtt_config=self.mqtt_config,
                    equipment_config=equipment_config
                )
                plc_list.append(plc)

        return plc_list

    def create_scada(self) -> SCADA:
        """Create SCADA instance"""
        return SCADA(hierarchy=self.hierarchy, mqtt_config=self.mqtt_config)

    def create_hmi(self, count: int = 1) -> list[HMI]:
        """Create HMI instances"""
        return [
            HMI(hmi_id=f"{i:02d}", hierarchy=self.hierarchy,
                mqtt_config=self.mqtt_config)
            for i in range(count)
        ]

    async def _run_until(self, duration: int) -> None:
        """Wait for the simulation window. duration 0 runs until cancelled."""
        if duration == 0:
            LOGGER.info("Duration: unlimited (until stopped)")
            await asyncio.Event().wait()
            return
        LOGGER.info("Duration: %s minutes", duration)
        await asyncio.sleep(duration * 60)

    async def run_simulation(self, duration_minutes: int | None = None):
        """Run the complete simulation"""
        duration = resolve_simulation_duration(
            duration_minutes, self.simulation_config)

        LOGGER.info("Starting Unified Namespace Simulator")

        # Create devices
        self.devices = (
            [*self.create_plc(), self.create_scada(), *self.create_hmi(2)]
        )

        # Start all devices
        interval = self.simulation_config.interval
        for device in self.devices:
            task = asyncio.create_task(device.start(interval))
            self.tasks.append(task)

        try:
            await self._run_until(duration)
        except KeyboardInterrupt:
            LOGGER.warning("Simulation interrupted by user")
        finally:
            await self._stop_simulation()

    async def _stop_simulation(self):
        """Cleanly stop all devices"""
        for device in self.devices:
            await device.stop()

        # Wait for tasks to complete
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
