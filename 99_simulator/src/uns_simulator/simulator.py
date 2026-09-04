import asyncio
import logging
import os
import time
from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from uns_simulator.config import settings
from uns_simulator.devices import HMI, PLC, SCADA, SignalDevice
from uns_simulator.models import ParameterType, expand_hierarchy_paths
from uns_simulator.plant import DeviceView, PlantClock
from uns_simulator.profiles import FAMILIES, LoadedProfile, filter_paths, load_profile, read_simulator_conf

LOGGER = logging.getLogger(__name__)

RUN_STATES = ("stopped", "starting", "running", "paused")


class ReconfigurationError(ValueError):
    """A runtime configuration change the simulator refuses, with the field to blame.

    Carries `field` separately so api.py can name it in a 422 without parsing the
    message, which is what spec 5.2 asks for.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _package_version() -> str:
    """The installed version of the simulator package.

    "unknown" rather than an exception when the package is not installed, because a health
    endpoint that raises is worse than one that admits ignorance.
    """
    try:
        return version("uns-simulator")
    except PackageNotFoundError:
        return "unknown"


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
    raw.update({key: value for key, value in read_simulator_conf(conf_dir).items() if value})
    return raw


class UnifiedNamespaceSimulator:
    """Main simulator class following unifiednamespace patterns"""

    def __init__(self, profile_name: str | None = None, seed: int | None = None):
        # Kept on the instance: GET /simulator/config lists the available profiles from it,
        # and apply_profile re-reads it so a profile added to conf/simulator/ while the
        # simulator is running can be switched to without a restart.
        self.raw_config = load_simulator_config(settings)
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(self.raw_config["hierarchy"])
        self.hierarchy = self.hierarchies[0]
        self.plc_templates = list(settings.get("plc") or [])
        self.equipment_fallback = settings.get("equipment.mixer_tank")
        self.devices: list = []
        self.tasks: list[asyncio.Task] = []

        requested = profile_name or self.simulation_config.get("profile", "wtp")
        configured_seed = seed if seed is not None else self.simulation_config.get("seed")
        self.profile: LoadedProfile = load_profile(self.raw_config, requested, seed=configured_seed)
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
        # Last, because it registers a listener on self.clock.
        self._init_run_state()

    def create_signal_devices(self) -> list[SignalDevice]:
        """One SignalDevice per resolved DeviceSpec, each with its own read-only view."""
        built: list[SignalDevice] = []
        for spec in self.profile.devices:
            view = DeviceView(self.profile.context, spec.path.site)
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

    def _init_run_state(self) -> None:
        """Everything the control API touches. Called from __init__ and from tests.

        A method rather than eight lines in __init__ so that test_simulator.py's `_sim()`,
        which constructs the object with __new__, has one thing to call and cannot fall
        silently behind when another attribute is added.
        """
        self.run_state = "stopped"
        # Two clocks on purpose: `created_at` is the process (GET /simulator/health) and
        # `started_at` is the current run (GET /simulator/status). Conflating them makes a
        # restarted plant look like it has been publishing for hours.
        self.created_at = time.monotonic()
        self.started_at: float | None = None
        self.overrides_active = False
        self.lock = asyncio.Lock()
        self._clock_task: asyncio.Task[None] | None = None
        self._publish_tasks: list[asyncio.Task[None]] = []
        self._transition_callbacks: list[Callable[[str, str, str], None]] = []
        self.clock.on_transition(self._notify_transition)

    def _schedule_publish_tasks(self) -> None:
        """One task per (device, tier), skipping disabled devices and zero intervals."""
        for device in self.signal_devices:
            if not device.enabled:
                continue
            for tier in sorted(device.tiers):
                # Already multiplied by the profile's tier_scale by load_profile.
                interval = self.profile.tiers.get(tier, 0.0)
                if interval <= 0.0:
                    # tier 'event' publishes on change from the tick; scheduling it would
                    # be a busy loop.
                    continue
                self._publish_tasks.append(asyncio.create_task(device.run_tier(tier, interval)))

    async def _cancel_publish_tasks(self) -> None:
        """Cancel, rather than set a flag.

        `run_tier` sleeps for its whole interval, so a cooperative flag would leave the
        5400 s meter tier publishing ninety minutes after the operator pressed pause.
        """
        tasks, self._publish_tasks = self._publish_tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self) -> None:
        """Start or resume publishing. Idempotent.

        From `paused` the clock was never stopped, so only the publishers are rebuilt and
        `started_at` is left alone: a pause is part of the same run.
        """
        if self.run_state == "running":
            return
        was_paused = self.run_state == "paused"
        self.run_state = "starting"
        if not was_paused:
            self.started_at = time.monotonic()
            self._clock_task = asyncio.create_task(self._run_clock())
        self._schedule_publish_tasks()
        self.run_state = "running"
        LOGGER.info(
            "Simulator running: profile %s, %d devices, %d publishers",
            self.profile.name,
            len(self.signal_devices),
            len(self._publish_tasks),
        )

    async def pause(self) -> None:
        """Stop publishing; keep simulating. A no-op unless currently running."""
        if self.run_state != "running":
            return
        await self._cancel_publish_tasks()
        self.run_state = "paused"
        LOGGER.info("Simulator paused; the plant clock keeps running")

    async def resume(self) -> None:
        """The inverse of pause. `start` already handles the paused branch."""
        await self.start()

    async def stop(self) -> None:
        """Stop publishing, stop the clock, disconnect. Idempotent."""
        if self.run_state == "stopped":
            return
        await self._cancel_publish_tasks()
        self.clock.stop()
        if self._clock_task is not None:
            self._clock_task.cancel()
            await asyncio.gather(self._clock_task, return_exceptions=True)
            self._clock_task = None
        for device in self.signal_devices:
            await device.stop()
        self.run_state = "stopped"
        self.started_at = None
        LOGGER.info("Simulator stopped")

    def _notify_transition(self, site: str, line: str, state: str) -> None:
        """The single plant-event listener registered on the clock.

        PlantClock calls its listeners synchronously and swallows whatever they raise, so
        one broken listener must not take the others with it — and must not disappear.
        """
        LOGGER.info("Plant %s/%s -> %s", site, line, state)
        for callback in self._transition_callbacks:
            try:
                callback(site, line, state)
            except Exception:
                LOGGER.exception("Plant transition listener failed for %s/%s", site, line)

    def on_plant_transition(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a plant-event listener (duty rotation, backwash, fault latch).

        Used by self_telemetry.py, whose callback only enqueues: the clock is on the hot
        path and an awaited publish here would slow every tick.
        """
        self._transition_callbacks.append(callback)

    def _device_by_id(self, device_id: str) -> SignalDevice:
        """The device with this id, or KeyError — which api.py turns into a 404."""
        for device in self.signal_devices:
            if device.spec.id == device_id:
                return device
        raise KeyError(device_id)

    def _rebuild_clock(self) -> None:
        """A new profile means a new PlantContext, so a new clock.

        Re-registering `_notify_transition` is the whole reason this is a method: the bug
        it prevents is a console that stops seeing plant events after the first
        profile switch, with nothing in the log to say why.
        """
        self.clock = PlantClock(self.profile.context, tick_s=self.clock.tick_s)
        self.clock.on_transition(self._notify_transition)

    async def _reschedule(self) -> None:
        """Re-apply the publish schedule.

        A no-op unless publishing is actually happening, so a change made while paused
        takes effect on resume and not before.
        """
        if self.run_state != "running":
            return
        await self._cancel_publish_tasks()
        self._schedule_publish_tasks()

    async def apply_profile(self, name: str, seed: int | None = None) -> None:
        """Switch profile, optionally reseeding. Restores the previous run state.

        Everything that can fail happens before anything is stopped, so a refused switch
        leaves a running plant running rather than stopping it and then explaining why.
        """
        raw = load_simulator_config(settings)
        available = sorted(raw.get("profiles") or {})
        if name not in available:
            known = ", ".join(available) or "none"
            raise ReconfigurationError("profile", f"unknown profile {name!r} (known: {known})")
        try:
            profile = load_profile(raw, name, seed=seed)
        except (KeyError, ValueError) as exc:
            raise ReconfigurationError("profile", str(exc)) from exc

        was_running = self.run_state in ("running", "starting")
        await self.stop()
        self.raw_config = raw
        self.profile = profile
        self._rebuild_clock()
        self.signal_devices = self.create_signal_devices()
        self.announce_device_count()
        # The running plant now matches the files on disk again.
        self.overrides_active = False
        if was_running:
            await self.start()

    async def apply_tiers(self, intervals: Mapping[str, float]) -> None:
        """Override publish intervals, in seconds. Absent tiers are left alone.

        Validated in full before anything is applied, so a body with one good tier and one
        typo changes nothing rather than half of what was asked.
        """
        for tier, interval in intervals.items():
            if tier not in self.profile.tiers:
                known = ", ".join(sorted(self.profile.tiers))
                raise ReconfigurationError(tier, f"unknown tier {tier!r} (known: {known})")
            if interval < 0.0:
                raise ReconfigurationError(tier, f"tier {tier!r} interval must not be negative")
        self.profile.tiers.update(intervals)
        self.overrides_active = True
        await self._reschedule()

    async def apply_families(self, flags: Mapping[str, bool]) -> None:
        """Enable or disable the devices a sensor family contributed.

        This cannot conjure devices for a family the profile never loaded — the YAML for it
        was not read — so enabling such a family sets the flag and changes no device count.
        Switching profile is what loads a new family. GET /simulator/config reports both
        numbers so the console can say so.
        """
        for family in flags:
            if family not in FAMILIES:
                known = ", ".join(FAMILIES)
                raise ReconfigurationError(family, f"unknown family {family!r} (known: {known})")
        self.profile.families.update(flags)
        for device in self.signal_devices:
            if device.spec.family in flags:
                device.enabled = flags[device.spec.family]
        self.overrides_active = True
        await self._reschedule()

    async def set_device_enabled(self, device_id: str, enabled: bool) -> None:
        """Silence or unsilence one device. Raises KeyError if there is no such device."""
        device = self._device_by_id(device_id)
        device.enabled = enabled
        self.overrides_active = True
        await self._reschedule()

    def health_body(self) -> dict[str, Any]:
        """Answers while the plant is stopped, which is what makes it a health check.

        `uptime_s` here is the *process*: a container up for an hour with a stopped plant
        is healthy. The *run* uptime lives in status(), and conflating the two makes a
        just-restarted plant look like it has been publishing all day.
        """
        return {
            "status": "ok",
            "uptime_s": round(time.monotonic() - self.created_at, 1),
            "git_hash": os.environ.get("GIT_HASH", "dev"),
            "version": _package_version(),
        }

    def message_rates(self) -> dict[str, float]:
        """Messages per second per tier — all zeros unless publishing is happening."""
        if self.run_state != "running":
            return dict.fromkeys(self.profile.tiers, 0.0)
        return self.profile.messages_per_second()

    def plant_snapshot(self) -> dict[str, Any]:
        """The correlated world: enterprise, site, and WTP process snapshot."""
        return self.profile.context.snapshot()

    def device_snapshots(self) -> list[dict[str, Any]]:
        """One row per device, as the console's device table renders it."""
        return [
            {
                "id": device.spec.id,
                "equipment": device.spec.equipment,
                "topic_prefix": device.spec.topic_prefix,
                "tier": device.spec.tier,
                "family": device.spec.family,
                "enabled": device.enabled,
                "connected": device.connected,
                "last_publish_ts": device.last_publish_ts,
                "publish_ok": device.publish_ok,
                "publish_fail": device.publish_fail,
                "last_error": device.last_error,
                "signal_count": len(device.spec.signals),
            }
            for device in self.signal_devices
        ]

    def signal_snapshot(self, device_id: str) -> dict[str, Any]:
        """One device's signals. Raises KeyError for an unknown id."""
        device = self._device_by_id(device_id)
        return {
            "device_id": device_id,
            # last_publish_ts is the device's, not each signal's: a device publishes a whole
            # tier in one pass, so per-signal timestamps would be one number repeated.
            #
            # The topic is built here rather than in the browser. get_parameter_topic is the
            # one definition of what a signal's topic is, and a second copy of that join in
            # TypeScript would drift the day a segment moves — silently, because a
            # subscription to a topic nothing publishes on looks exactly like a quiet signal.
            "signals": [
                {
                    **row,
                    "last_publish_ts": device.last_publish_ts,
                    "topic": device.spec.path.get_parameter_topic(
                        device.spec.equipment, ParameterType(row["param_type"]), row["name"]
                    ),
                }
                for row in device.snapshot()
            ],
        }

    def config_snapshot(self) -> dict[str, Any]:
        """What is loaded and what could be loaded. Read-only; the writes are spec 5.2."""
        paths = filter_paths(
            self.hierarchies,
            sites=self.profile.sites or None,
            max_cells_per_line=self.profile.max_cells_per_line,
        )
        return {
            "profile": self.profile.name,
            "available_profiles": sorted(self.raw_config.get("profiles") or {}),
            "seed": self.profile.seed,
            "tier_scale": self.profile.tier_scale,
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "sites": list(self.profile.sites),
            "max_cells_per_line": self.profile.max_cells_per_line,
            "hierarchy": [
                {
                    "enterprise": path.enterprise,
                    "site": path.site,
                    "area": path.area,
                    "line": path.line,
                    "cell": path.cell,
                    "kind": path.kind,
                    "nameplate_tph": path.nameplate_tph,
                }
                for path in paths
            ],
            "devices": [
                {
                    "id": device.spec.id,
                    "equipment": device.spec.equipment,
                    "family": device.spec.family,
                    "tier": device.spec.tier,
                    "enabled": device.enabled,
                    "topic_prefix": device.spec.topic_prefix,
                    "signal_count": len(device.spec.signals),
                    # The paths the YAML declared, not the ones that resolved: a `serves`
                    # entry matching nothing is precisely what an operator needs to see, and
                    # GET /simulator/diagnostics reports how many of them resolved.
                    "serves": list(device.spec.serves),
                    # `DeviceSpec` keeps the resolved path rather than the selector that
                    # matched it, so this is where the device actually lives.
                    "target": {
                        "site": device.spec.path.site,
                        "area": device.spec.path.area,
                        "line": device.spec.path.line,
                        "cell": device.spec.path.cell,
                        "kind": device.spec.path.kind,
                    },
                }
                for device in self.signal_devices
            ],
        }

    def diagnostics(self) -> dict[str, Any]:
        """Why the inventory looks the way it does, and what is going wrong right now."""
        return {
            "report": self.profile.report.as_dict(),
            "failing_devices": [
                device.health()
                for device in self.signal_devices
                if device.publish_fail or device.reconnects or device.last_error
            ],
            "sample_topics": self.sample_topics(),
        }

    def sample_topics(self, limit: int = 20) -> list[str]:
        """Real topics this profile publishes to, for pasting into an MQTT client.

        Assembled the same way ISA95Hierarchy.get_parameter_topic assembles them, so the
        console cannot show a topic that is not on the broker.
        """
        topics: list[str] = []
        for device in self.signal_devices:
            for spec in device.spec.signals:
                topics.append(f"{device.spec.topic_prefix}/{spec.param_type}/{spec.name}")
                if len(topics) >= limit:
                    return topics
        return topics

    def status(self) -> dict[str, Any]:
        """Runtime status. Every write in spec 5.2 returns this body."""
        per_tier: dict[str, int] = {}
        for device in self.signal_devices:
            for spec in device.spec.signals:
                per_tier[spec.tier] = per_tier.get(spec.tier, 0) + 1
        return {
            "run_state": self.run_state,
            "profile": self.profile.name,
            "seed": self.profile.seed,
            "device_count": len(self.signal_devices),
            "signal_count": sum(len(d.spec.signals) for d in self.signal_devices),
            "uptime_s": 0.0 if self.started_at is None else round(time.monotonic() - self.started_at, 1),
            "broker_connected": any(d.connected for d in self.signal_devices),
            "msg_per_sec": self.message_rates(),
            "published_total": sum(d.publish_ok for d in self.signal_devices),
            "failed_total": sum(d.publish_fail for d in self.signal_devices),
            "overrides_active": self.overrides_active,
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "per_tier": per_tier,
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
                    plc_id = f"{plc_cfg.get('id', 'plc')}-{path.site}-{path.line}-{path.cell}"
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
            plc_list.extend(
                PLC(
                    plc_id=f"{i + 1:03d}-{path.site}-{path.line}-{path.cell}",
                    hierarchy=path,
                    mqtt_config=self.mqtt_config,
                    equipment_config=self.equipment_fallback,
                )
                for i in range(plc_count)
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
            return [HMI(hmi_id=f"{i:02d}", hierarchy=self.hierarchy, mqtt_config=self.mqtt_config) for i in range(count)]
        seen_lines: set[tuple[str, str, str]] = set()
        hmis: list[HMI] = []
        for path in self.hierarchies:
            key = (path.site, path.area, path.line)
            if key in seen_lines:
                continue
            seen_lines.add(key)
            hmi_id = f"{path.site}-{path.line}"
            hmis.append(HMI(hmi_id=hmi_id, hierarchy=path, mqtt_config=self.mqtt_config))
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
        duration = resolve_simulation_duration(duration_minutes, self.simulation_config)

        LOGGER.info("Starting Unified Namespace Simulator")
        LOGGER.info(
            "Hierarchy cells: %s",
            ", ".join(f"{p.site}/{p.area}/{p.line}/{p.cell}" for p in self.hierarchies),
        )

        self.devices = [
            *self.signal_devices,
            *self.create_plc(),
        ]
        self.announce_device_count()

        await self.start()

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
        await self.stop()
        for device in self.devices:
            await device.stop()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
