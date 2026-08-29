import asyncio
import logging
from typing import Any

from uns_simulator.config import settings
from uns_simulator.devices import HMI, PLC, SCADA
from uns_simulator.models import expand_hierarchy_paths

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


def _plc_equipment_config(plc_cfg: Any) -> dict[str, Any]:
    return {
        "name": plc_cfg.get("equipment") or plc_cfg.get("name"),
        "sensors": plc_cfg.get("sensors") or {},
    }


class UnifiedNamespaceSimulator:
    """Main simulator class following unifiednamespace patterns"""

    def __init__(self):
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(settings.hierarchy)
        self.hierarchy = self.hierarchies[0]
        self.plc_templates = list(settings.get("plc") or [])
        self.equipment_fallback = settings.get("equipment.mixer_tank")
        self.devices: list = []
        self.tasks: list[asyncio.Task] = []

    def create_plc(self) -> list[PLC]:
        """Create one PLC per cell for each configured equipment template."""
        plc_list: list[PLC] = []

        for path in self.hierarchies:
            if self.plc_templates:
                for plc_cfg in self.plc_templates:
                    equipment_config = _plc_equipment_config(plc_cfg)
                    if not equipment_config["name"]:
                        continue
                    plc_id = (
                        f"{plc_cfg.get('id', 'plc')}-"
                        f"{path.site}-{path.line}-{path.cell}"
                    )
                    plc_list.append(
                        PLC(
                            plc_id=plc_id,
                            hierarchy=path,
                            mqtt_config=self.mqtt_config,
                            equipment_config=equipment_config,
                        )
                    )
                continue

            if not self.equipment_fallback:
                continue
            plc_count = self.simulation_config.get("plc_count", 2)
            for i in range(plc_count):
                plc_list.append(
                    PLC(
                        plc_id=f"{i + 1:03d}-{path.site}-{path.line}-{path.cell}",
                        hierarchy=path,
                        mqtt_config=self.mqtt_config,
                        equipment_config=self.equipment_fallback,
                    )
                )

        return plc_list

    def create_scada(self) -> list[SCADA]:
        """One SCADA publisher per site (first cell of that site)."""
        seen_sites: set[str] = set()
        scadas: list[SCADA] = []
        for path in self.hierarchies:
            if path.site in seen_sites:
                continue
            seen_sites.add(path.site)
            scadas.append(
                SCADA(
                    hierarchy=path,
                    mqtt_config=self.mqtt_config,
                    system_name=f"SCADA_{path.site}",
                )
            )
        return scadas

    def create_hmi(self, count: int | None = None) -> list[HMI]:
        """One HMI per line (first cell of that line)."""
        if count is not None:
            return [
                HMI(hmi_id=f"{i:02d}", hierarchy=self.hierarchy,
                    mqtt_config=self.mqtt_config)
                for i in range(count)
            ]
        seen_lines: set[tuple[str, str, str]] = set()
        hmis: list[HMI] = []
        for path in self.hierarchies:
            key = (path.site, path.area, path.line)
            if key in seen_lines:
                continue
            seen_lines.add(key)
            hmi_id = f"{path.site}-{path.line}"
            hmis.append(HMI(hmi_id=hmi_id, hierarchy=path,
                            mqtt_config=self.mqtt_config))
        return hmis

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
        LOGGER.info(
            "Hierarchy cells: %s",
            ", ".join(
                f"{p.site}/{p.area}/{p.line}/{p.cell}" for p in self.hierarchies
            ),
        )

        self.devices = (
            [*self.create_plc(), *self.create_scada(), *self.create_hmi()]
        )

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

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
