"""The simulated world the signals observe.

One PlantClock ticks every second and advances this state; signals read it and never write
it. Keeping the state here rather than inside devices is what makes values correlate — every
device at a site sees the same WTPProcess.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)


class SiteState:
    """One site's water-treatment process."""

    def __init__(self, name: str, rng: random.Random) -> None:
        self.name = name
        self.rng = rng
        self.wtp = WTPProcess(rng)
        self.sim_time_s = 0.0

    def tick(self, dt: float) -> list[str]:
        self.sim_time_s += dt
        return self.wtp.tick(dt)


class PlantContext:
    """Every site's state, advanced together by one clock."""

    def __init__(self, global_seed: int) -> None:
        self.global_seed = global_seed
        self.sites: dict[str, SiteState] = {}
        self.sim_time_s = 0.0
        self.enterprise: str = "AcmeWater"

    def add_site(self, name: str) -> SiteState:
        site = SiteState(name, random.Random(f"{self.global_seed}:{name}"))  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        self.sites[name] = site
        return site

    def tick(self, dt: float) -> list[tuple[str, str, str]]:
        self.sim_time_s += dt
        out: list[tuple[str, str, str]] = []
        for site_name, site in self.sites.items():
            for event in site.wtp.tick(dt):
                out.append((site_name, "Train1", event))
        return out

    def snapshot(self) -> dict[str, Any]:
        if not self.sites:
            return {"enterprise": self.enterprise, "site": None}
        site_name = next(iter(self.sites))
        return {
            "enterprise": self.enterprise,
            "site": site_name,
            **self.sites[site_name].wtp.snapshot(),
        }


class DeviceView:
    """A device's read-only window onto the plant.

    Signals receive this and nothing else, so a signal cannot mutate the world it measures.
    """

    __slots__ = ("_context", "_site")

    def __init__(self, context: PlantContext, site: str) -> None:
        self._context = context
        self._site = site

    @property
    def site(self) -> str:
        return self._site

    @property
    def wtp(self) -> WTPProcess:
        return self._context.sites[self._site].wtp


class PlantClock:
    """Advances the whole plant on a fixed tick.

    Every signal is evaluated on this tick, whatever its publish cadence. That is what lets
    a 1 s vibration sample and a 900 s water meter reading describe the same world, and what
    lets counters integrate correctly no matter how rarely their device publishes.
    """

    def __init__(self, context: PlantContext, tick_s: float = 1.0) -> None:
        self.context = context
        self.tick_s = tick_s
        self.tick_count = 0
        self.running = False
        self._callbacks: list[Callable[[str, str, str], None]] = []

    def on_transition(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a listener for (site, line, new_state). Exceptions in it are swallowed."""
        self._callbacks.append(callback)

    def advance(self, dt: float | None = None) -> list[tuple[str, str, str]]:
        """Advance one tick synchronously and return the line transitions it produced."""
        transitions = self.context.tick(self.tick_s if dt is None else dt)
        self.tick_count += 1
        for site, line, state in transitions:
            for callback in self._callbacks:
                try:
                    callback(site, line, state)
                except Exception:
                    LOGGER.exception("plant transition callback failed for %s/%s -> %s", site, line, state)
        return transitions

    async def run(self) -> None:
        """Tick until `stop()` is called or the task is cancelled."""
        self.running = True
        try:
            while self.running:
                self.advance()
                await asyncio.sleep(self.tick_s)
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False


def _mean_reverting(
    value: float,
    mean: float,
    tau_s: float,
    sigma: float,
    dt: float,
    rng: random.Random,
    low: float,
    high: float,
) -> float:
    """One Ornstein-Uhlenbeck step, clamped. Same walk `OUWalkSignal` uses, on site state.

    `ratio` is capped at 1.0 so a coarse `dt` cannot overshoot the mean and oscillate. The
    clock always ticks at 1 s, but tests fast-forward whole hours and must stay well-behaved.
    """
    ratio = min(1.0, dt / max(tau_s, 1e-6))
    value += (mean - value) * ratio + sigma * math.sqrt(ratio) * rng.gauss(0.0, 1.0)
    return min(high, max(low, value))


# --- Water treatment plant hydraulics (WTP) ---

FLOW_TAU_S = 5.0
SPEED_TAU_S = 8.0
RAW_PUMP_M3H = 80.0
DIST_NAMEPLATE_M3H = 80.0
LL_PCT = 10.0
RESIDUAL_BARG = 0.2


def _approach(value: float, target: float, tau_s: float, dt: float) -> float:
    ratio = min(1.0, dt / max(tau_s, 1e-6))
    return value + (target - value) * ratio


class ValveState:
    def __init__(self) -> None:
        self.cmd_open = False
        self.cmd_close = True
        self.open_fb = False
        self.close_fb = True
        self.position = 0.0
        self.cycle_count = 0

    def set_open(self, open_: bool) -> None:
        changed = self.open_fb != open_
        self.cmd_open = open_
        self.cmd_close = not open_
        self.open_fb = open_
        self.close_fb = not open_
        self.position = 100.0 if open_ else 0.0
        if changed:
            self.cycle_count += 1


class MotorDOLState:
    def __init__(self) -> None:
        self.cmd_start = False
        self.cmd_stop = True
        self.reset_fault = False
        self.running = False
        self.fault = False
        self.runtime_h = 0.0
        self.start_count = 0
        self.auto = True
        self.fault_age_s = 0.0
        self.reset_age_s = 0.0


class VFDState:
    def __init__(self) -> None:
        self.run_cmd = False
        self.speed_sp = 0.0
        self.speed_pv = 0.0
        self.reset_fault = False
        self.running = False
        self.fault = False
        self.runtime_h = 0.0
        self.start_count = 0
        self.fault_age_s = 0.0
        self.reset_age_s = 0.0


class TankState:
    def __init__(self, capacity_m3: float, initial_pct: float = 50.0) -> None:
        self.capacity_m3 = capacity_m3
        self.volume_m3 = capacity_m3 * initial_pct / 100.0

    @property
    def level_pct(self) -> float:
        return 100.0 * self.volume_m3 / self.capacity_m3 if self.capacity_m3 else 0.0

    def add_m3(self, delta: float) -> None:
        self.volume_m3 = min(self.capacity_m3, max(0.0, self.volume_m3 + delta))


class BasinState(TankState):
    def __init__(self, capacity_m3: float, depth_m: float = 3.0, initial_pct: float = 50.0) -> None:
        super().__init__(capacity_m3, initial_pct)
        self.depth_m = depth_m

    @property
    def pv_m(self) -> float:
        return self.level_pct / 100.0 * self.depth_m


class FilterState:
    def __init__(self) -> None:
        self.filter_run = True
        self.backwash = False
        self.in_service = True


class WTPProcess:
    """Water-treatment hydraulics: tanks, lagged flows, and pressures."""

    DUTY_CYCLE_S = 900.0
    BACKWASH_TRIGGER_S = 1800.0
    BACKWASH_DURATION_S = 45.0
    FAULT_CLEAR_S = 120.0
    RESET_FAULT_S = 30.0
    DIST_SPEED_SP = 87.5

    def __init__(self, rng: random.Random, *, fault_p: float = 1.0 / 3600.0) -> None:
        self.rng = rng
        self.fault_p = fault_p
        self.v101 = ValveState()
        self.v201 = ValveState()
        self.v202 = ValveState()
        self.v301 = ValveState()
        self.p101 = MotorDOLState()
        self.p102 = MotorDOLState()
        self.p103 = MotorDOLState()
        self.dp101 = MotorDOLState()
        self.p201 = VFDState()
        self.p202 = VFDState()
        self.t101 = TankState(250.0)
        self.b101 = BasinState(40.0)
        self.t201 = TankState(400.0)
        self.f101 = FilterState()
        self.inlet_m3h = 0.0
        self.ft101_m3h = 0.0
        self.ft201_m3h = 0.0
        self.ft101_total_m3 = 0.0
        self.ft201_total_m3 = 0.0
        self.flow_reset = False
        self.pt101 = RESIDUAL_BARG
        self.pt201 = RESIDUAL_BARG
        self.ait101 = 7.2
        self.mode = "Running"
        self.duty_raw_pump = "P101"
        self.lead_dist_pump = "P201"
        self.running_s = 0.0
        self.duty_s = 0.0
        self.backwash_s = 0.0
        self._initialized = False

    # --- motor helpers -------------------------------------------------

    def _start_motor(self, motor: MotorDOLState) -> None:
        motor.cmd_start = True
        motor.cmd_stop = False
        was_running = motor.running
        motor.running = not motor.fault
        if motor.running and not was_running:
            motor.start_count += 1

    def _stop_motor(self, motor: MotorDOLState) -> None:
        motor.cmd_start = False
        motor.cmd_stop = True
        motor.running = False

    def _raw_pump_by_name(self, name: str) -> MotorDOLState:
        return {"P101": self.p101, "P102": self.p102, "P103": self.p103}[name]

    def _next_raw_pump(self, current: str) -> str | None:
        order = ("P101", "P102", "P103")
        start = order.index(current)
        for offset in range(1, len(order)):
            candidate = order[(start + offset) % len(order)]
            if not self._raw_pump_by_name(candidate).fault:
                return candidate
        return None

    def _start_vfd(self, pump: VFDState) -> None:
        pump.run_cmd = True
        pump.speed_sp = self.DIST_SPEED_SP
        was_running = pump.running
        pump.running = not pump.fault
        if pump.running and not was_running:
            pump.start_count += 1

    def _stop_vfd(self, pump: VFDState) -> None:
        pump.run_cmd = False
        pump.speed_sp = 0.0
        pump.running = False

    def _apply_distribution_lead(self) -> None:
        """P201 is preferred lead; P202 runs only while the lead is faulted.

        lead_dist_pump names the VFD the sequencer currently wants, not merely
        whichever machine reports fault=false. Do not start a faulted pump.
        """
        if not self.p201.fault:
            wanted = "P201"
        elif not self.p202.fault:
            wanted = "P202"
        else:
            wanted = None

        if wanted == "P201":
            self.lead_dist_pump = "P201"
            self._start_vfd(self.p201)
            self._stop_vfd(self.p202)
        elif wanted == "P202":
            self.lead_dist_pump = "P202"
            self._start_vfd(self.p202)
            self._stop_vfd(self.p201)
        else:
            self.lead_dist_pump = "P201"
            self._stop_vfd(self.p201)
            self._stop_vfd(self.p202)

    # --- sequencer -----------------------------------------------------

    def _initialize_running(self) -> None:
        self.mode = "Running"
        self.duty_raw_pump = "P101"
        self.lead_dist_pump = "P201"
        self.running_s = 0.0
        self.duty_s = 0.0
        self.backwash_s = 0.0
        for valve in (self.v101, self.v201, self.v202, self.v301):
            valve.set_open(True)
        self._start_motor(self.p101)
        self._stop_motor(self.p102)
        self._stop_motor(self.p103)
        self._apply_distribution_lead()
        self.f101.in_service = True
        self.f101.backwash = False
        self.f101.filter_run = True

    def _enter_backwash(self) -> list[str]:
        self.mode = "Backwash"
        self.backwash_s = 0.0
        self.v201.set_open(False)
        self.v202.set_open(False)
        self.f101.backwash = True
        self.f101.in_service = False
        self.f101.filter_run = False
        return ["Backwash"]

    def _exit_backwash(self) -> list[str]:
        self.mode = "Running"
        self.running_s = 0.0
        self.v201.set_open(True)
        self.v202.set_open(True)
        self.f101.backwash = False
        self.f101.in_service = True
        self.f101.filter_run = True
        return ["Running"]

    def _rotate_duty(self) -> list[str]:
        nxt = self._next_raw_pump(self.duty_raw_pump)
        if nxt is None:
            return []
        old = self.duty_raw_pump
        self._stop_motor(self._raw_pump_by_name(old))
        self.duty_raw_pump = nxt
        self._start_motor(self._raw_pump_by_name(nxt))
        self.duty_s = 0.0
        return [f"Duty{nxt}"]

    def _apply_faults(self) -> list[str]:
        events: list[str] = []
        if self.fault_p <= 0.0:
            return events
        checks = (
            ("P101", self.p101),
            ("P102", self.p102),
            ("P103", self.p103),
            ("P201", self.p201),
            ("P202", self.p202),
            ("DP101", self.dp101),
        )
        # Only motors that were already running at the start of the pass can fault
        # this tick — a failover pump that just started must survive its first tick.
        eligible = [(tag, dev) for tag, dev in checks if dev.running and not dev.fault]
        for tag, device in eligible:
            if self.rng.random() < self.fault_p:
                device.fault = True
                device.running = False
                device.fault_age_s = 0.0
                device.reset_fault = False
                device.reset_age_s = 0.0
                events.append(f"Fault{tag}")
                if tag in ("P101", "P102", "P103") and tag == self.duty_raw_pump:
                    nxt = self._next_raw_pump(tag)
                    if nxt is not None:
                        self.duty_raw_pump = nxt
                        self._start_motor(self._raw_pump_by_name(nxt))
        return events

    def _advance_fault_timers(self, dt: float) -> None:
        """Age latched faults; after FAULT_CLEAR_S clear and pulse ResetFault for RESET_FAULT_S.

        A raw pump that faulted on duty has already been failed over, so drop its
        cmd_start once the fault clears — the sequencer wants the new duty, not a
        stale resume. Distribution VFDs are restored by `_apply_distribution_lead`.
        """
        duty = self._raw_pump_by_name(self.duty_raw_pump)
        for device in (self.p101, self.p102, self.p103, self.dp101, self.p201, self.p202):
            if device.fault:
                device.fault_age_s += dt
                if device.fault_age_s > self.FAULT_CLEAR_S:
                    device.fault = False
                    device.fault_age_s = 0.0
                    device.reset_fault = True
                    device.reset_age_s = 0.0
                    if device in (self.p101, self.p102, self.p103) and device is not duty:
                        device.cmd_start = False
                        device.cmd_stop = True
            elif device.reset_fault:
                device.reset_age_s += dt
                if device.reset_age_s >= self.RESET_FAULT_S:
                    device.reset_fault = False
                    device.reset_age_s = 0.0

    def advance_sequencer(self, dt: float) -> list[str]:
        events: list[str] = []
        if not self._initialized:
            self._initialize_running()
            self._initialized = True

        self._advance_fault_timers(dt)

        if self.mode == "Backwash":
            self.backwash_s += dt
            if self.backwash_s >= self.BACKWASH_DURATION_S:
                events.extend(self._exit_backwash())
            self._apply_distribution_lead()
            return events

        # Running mode
        self.running_s += dt
        self.duty_s += dt
        if self.running_s >= self.BACKWASH_TRIGGER_S:
            # Backwash wins: duty_s is paused (not applied) until Running resumes.
            events.extend(self._enter_backwash())
            self._apply_distribution_lead()
            return events
        if self.duty_s >= self.DUTY_CYCLE_S:
            events.extend(self._rotate_duty())

        # Inlet interlock: if V101 somehow closed, stop raw pumps but keep cmd intent
        if not self.v101.open_fb:
            for pump in (self.p101, self.p102, self.p103):
                pump.running = False

        events.extend(self._apply_faults())
        self._apply_distribution_lead()
        return events

    # --- tick ----------------------------------------------------------

    def tick(self, dt: float) -> list[str]:
        events = self.advance_sequencer(dt)
        self.advance_hydraulics(dt)
        self.dp101.running = self.ft101_m3h > 1.0 and not self.dp101.fault
        self.dp101.cmd_start = self.ft101_m3h > 1.0
        self.dp101.cmd_stop = not self.dp101.cmd_start
        self.advance_quality(dt)
        return events

    def advance_quality(self, dt: float) -> None:
        mean = 7.2 if self.dp101.running else 7.6
        self.ait101 = _mean_reverting(self.ait101, mean, 600.0, 0.08, dt, self.rng, 6.5, 8.5)

    # --- snapshot ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "filter_mode": "Backwash" if self.f101.backwash else "InService",
            "duty_raw_pump": self.duty_raw_pump,
            "lead_dist_pump": self.lead_dist_pump,
            "tanks": {
                "T101": {
                    "level_pct": round(self.t101.level_pct, 2),
                    "volume_m3": round(self.t101.volume_m3, 2),
                    "capacity_m3": round(self.t101.capacity_m3, 2),
                },
                "B101": {
                    "level_pct": round(self.b101.level_pct, 2),
                    "volume_m3": round(self.b101.volume_m3, 2),
                    "capacity_m3": round(self.b101.capacity_m3, 2),
                },
                "T201": {
                    "level_pct": round(self.t201.level_pct, 2),
                    "volume_m3": round(self.t201.volume_m3, 2),
                    "capacity_m3": round(self.t201.capacity_m3, 2),
                },
            },
            "flows_m3h": {
                "inlet": round(self.inlet_m3h, 2),
                "FT101": round(self.ft101_m3h, 2),
                "FT201": round(self.ft201_m3h, 2),
            },
            "pressures_barg": {
                "PT101": round(self.pt101, 3),
                "PT201": round(self.pt201, 3),
            },
        }

    def advance_hydraulics(self, dt: float) -> None:
        raw_on = any(p.running and not p.fault for p in (self.p101, self.p102, self.p103))

        inlet_target = RAW_PUMP_M3H if self.v101.open_fb and raw_on and self.t101.level_pct < 100.0 else 0.0
        self.inlet_m3h = _approach(self.inlet_m3h, inlet_target, FLOW_TAU_S, dt)

        filter_forward = (
            self.v201.open_fb and self.v202.open_fb and self.f101.in_service and not self.f101.backwash
        )

        ft101_target = RAW_PUMP_M3H if self.t101.level_pct > LL_PCT and filter_forward else 0.0
        if ft101_target == 0.0:
            # Flow stops quickly when valves close or the filter isolates; only the
            # ramp-up is lagged. This keeps the backwash snapshot near zero immediately.
            self.ft101_m3h = 0.0
        else:
            self.ft101_m3h = _approach(self.ft101_m3h, ft101_target, FLOW_TAU_S, dt)

        b101_out = self.ft101_m3h if filter_forward else 0.0
        self.t101.add_m3((self.inlet_m3h - self.ft101_m3h) * dt / 3600.0)
        self.b101.add_m3((self.ft101_m3h - b101_out) * dt / 3600.0)

        filtrate = self.ft101_m3h if filter_forward else 0.0

        for pump in (self.p201, self.p202):
            speed_target = pump.speed_sp if pump.running else 0.0
            pump.speed_pv = _approach(pump.speed_pv, speed_target, SPEED_TAU_S, dt)

        contributions = [
            DIST_NAMEPLATE_M3H * pump.speed_pv / 100.0 if pump.running and not pump.fault else 0.0
            for pump in (self.p201, self.p202)
        ]
        ft201_target = sum(contributions) if self.v301.open_fb else 0.0
        self.ft201_m3h = _approach(self.ft201_m3h, ft201_target, FLOW_TAU_S, dt)

        self.ft101_total_m3 += self.ft101_m3h * dt / 3600.0
        self.ft201_total_m3 += self.ft201_m3h * dt / 3600.0

        self.t201.add_m3((filtrate - self.ft201_m3h) * dt / 3600.0)

        self.pt101 = RESIDUAL_BARG + 0.015 * self.t101.level_pct + (1.8 if raw_on else 0.0)
        self.pt201 = RESIDUAL_BARG + 0.015 * self.t201.level_pct + (
            2.2 * (self.ft201_m3h / DIST_NAMEPLATE_M3H)
        )

        for motor in (self.p101, self.p102, self.p103, self.dp101):
            if motor.running:
                motor.runtime_h += dt / 3600.0
        for pump in (self.p201, self.p202):
            if pump.running:
                pump.runtime_h += dt / 3600.0
