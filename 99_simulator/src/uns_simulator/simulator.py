import asyncio
import logging
from pathlib import Path
from typing import Any

from uns_simulator.config import settings
from uns_simulator.devices import HMI, PLC, SCADA, SignalDevice
from uns_simulator.models import expand_hierarchy_paths
from uns_simulator.plant import DeviceView, PlantClock
from uns_simulator.profiles import FAMILIES, PRODUCTION_KIND, LoadedProfile, load_profile, read_simulator_conf

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


def load_simulator_config(settings_obj: Any, conf_dir: Path | None = None) -> dict[str, Any]:
    """Assemble the mapping load_profile expects, files layered over Dynaconf.

    One adapter, so tests hand load_profile a plain dict and never depend on Dynaconf, and
    production has exactly one place where the two representations meet.

    `conf/simulator/*.yaml` wins over `settings.yaml` key by key, and only where the file
    supplies something. Whole-mapping replacement would be wrong in one direction and a
    deep merge wrong in the other: `simulation` only ever lives in settings.yaml, and a
    `hierarchy` half from each file would be a plant nobody authored. Per-key overlay is
    what keeps spec 12's promise that an untouched deployment with no conf/simulator/
    behaves exactly as it does today.
    """
    raw: dict[str, Any] = {
        "hierarchy": settings_obj.get("hierarchy") or {},
        "plant": settings_obj.get("plant") or {},
        "profiles": settings_obj.get("profiles") or {},
        "simulation": settings_obj.get("simulation") or {},
    }
    for family in FAMILIES:
        raw[family] = settings_obj.get(family) or {}
    for key, value in read_simulator_conf(conf_dir).items():
        if value:
            raw[key] = value
    return raw


class UnifiedNamespaceSimulator:
    """Main simulator class following unifiednamespace patterns"""

    def __init__(self, profile_name: str | None = None, seed: int | None = None):
        raw_config = load_simulator_config(settings)
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(raw_config["hierarchy"])
        self.hierarchy = self.hierarchies[0]
        self.plc_templates = list(settings.get("plc") or [])
        self.equipment_fallback = settings.get("equipment.mixer_tank")
        self.devices: list = []
        self.tasks: list[asyncio.Task] = []

        requested = profile_name or self.simulation_config.get("profile", "full")
        configured_seed = seed if seed is not None else self.simulation_config.get("seed")
        self.profile: LoadedProfile = load_profile(raw_config, requested, seed=configured_seed)
        self.clock = PlantClock(self.profile.context, tick_s=float(self.simulation_config.get("tick_s", 1.0)))
        self.signal_devices: list[SignalDevice] = self.create_signal_devices()
        LOGGER.info(
            "Loaded profile %s: %d devices, %d signals across %s",
            self.profile.name,
            self.profile.report.devices,
            self.profile.report.signals,
            ", ".join(sorted(self.profile.report.per_family)) or "no families",
        )
        for warning in self.profile.report.warnings + self.profile.report.unmatched_templates:
            LOGGER.warning("profile %s: %s", self.profile.name, warning)

    def create_signal_devices(self) -> list[SignalDevice]:
        """One SignalDevice per resolved DeviceSpec, each with its own read-only view."""
        built: list[SignalDevice] = []
        for spec in self.profile.devices:
            # Only production areas have a LineState (spec 6.1: a compressor house has no
            # batch to be IDLE between), so a utility device's view carries `line=None` and
            # reads production through `serves` instead. The line key is `<Area>/<Line>`,
            # matching how `build_plant_context` registered it.
            line = f"{spec.path.area}/{spec.path.line}" if spec.path.kind == PRODUCTION_KIND else None
            view = DeviceView(self.profile.context, spec.path.site, line, spec.serves)
            built.append(SignalDevice(spec, self.mqtt_config, view, self.profile.seed))
        return built

    def tick(self, dt: float) -> None:
        """Advance every enabled device's signals. Called once per plant tick."""
        for device in self.signal_devices:
            if device.enabled:
                device.evaluate(dt)

    def announce_device_count(self) -> None:
        """Tell every SCADA how many devices actually exist, instead of a random guess."""
        count = len(self.signal_devices)
        for device in self.devices:
            if isinstance(device, SCADA):
                device.connected_devices = count

    def status(self) -> dict[str, Any]:
        """Runtime status. Sub-project B's GET /simulator/status extends this body."""
        per_tier: dict[str, int] = {}
        for device in self.signal_devices:
            for spec in device.spec.signals:
                per_tier[spec.tier] = per_tier.get(spec.tier, 0) + 1
        return {
            "profile": self.profile.name,
            "seed": self.profile.seed,
            "device_count": len(self.signal_devices),
            "signal_count": sum(len(d.spec.signals) for d in self.signal_devices),
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "per_tier": per_tier,
            "broker_connected": any(d.connected for d in self.signal_devices),
            "published_total": sum(d.publish_ok for d in self.signal_devices),
            "failed_total": sum(d.publish_fail for d in self.signal_devices),
            "tick_count": self.clock.tick_count,
        }

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

    async def _run_clock(self) -> None:
        """Advance the plant and evaluate every signal on the same tick."""
        tick_s = self.clock.tick_s
        self.clock.running = True
        try:
            while self.clock.running:
                self.clock.advance()
                self.tick(tick_s)
                await asyncio.sleep(tick_s)
        except asyncio.CancelledError:
            LOGGER.info("Plant clock cancelled")
            raise
        finally:
            self.clock.running = False

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

        self.devices = [
            *self.signal_devices,
            *self.create_plc(),
            *self.create_scada(),
            *self.create_hmi(),
        ]
        self.announce_device_count()

        # The clock is a task of its own: it advances the world, and self.tick evaluates
        # every signal on that same advance. Publishing is scheduled separately, per tier.
        self.clock.on_transition(
            lambda site, line, state: LOGGER.info("Plant %s/%s -> %s", site, line, state)
        )
        self.tasks.append(asyncio.create_task(self._run_clock()))

        for device in self.signal_devices:
            for tier in sorted(device.tiers):
                # Already multiplied by the profile's `tier_scale` by `load_profile`, so a
                # slow profile cannot be defeated by forgetting to scale here.
                interval = self.profile.tiers.get(tier, 0.0)
                if interval <= 0.0:
                    # tier 'event' (and any tier explicitly set to 0) publishes on change
                    # from the tick itself; scheduling it would be a busy loop.
                    continue
                self.tasks.append(asyncio.create_task(device.run_tier(tier, interval)))

        # `.get`, not `.interval`: the legacy devices keep the single flat interval, and tests
        # hand this class a plain dict rather than the Dynaconf settings object.
        interval = float(self.simulation_config.get("interval", 5.0))
        for device in self.devices:
            if isinstance(device, SignalDevice):
                continue
            self.tasks.append(asyncio.create_task(device.start(interval)))

        try:
            await self._run_until(duration)
        except KeyboardInterrupt:
            LOGGER.warning("Simulation interrupted by user")
        finally:
            await self._stop_simulation()

    async def _stop_simulation(self):
        """Cleanly stop all devices"""
        self.clock.stop()
        for device in self.devices:
            await device.stop()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
