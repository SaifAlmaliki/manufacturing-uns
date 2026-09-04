"""The simulated world the signals observe.

One PlantClock ticks every second and advances this state; signals read it and never write
it. Keeping the state here rather than inside devices is what makes values correlate — a
chiller and a compressor on the same site see the same ambient temperature and the same
line production rate, so their traces move together the way real ones do.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)

# Spec 6.1: EXECUTE runs at 0.85-1.0 of nameplate, and every ramp targets the floor.
EXECUTE_RATE_FLOOR = 0.85

# The states production_rate ramps up through, ramps down through, and is flat zero in.
_RAMP_UP_STATES = frozenset({"STARTING", "UNHOLDING", "UNSUSPENDING"})
_RAMP_DOWN_STATES = frozenset({"COMPLETING", "HOLDING", "SUSPENDING", "STOPPING", "ABORTING", "CLEARING"})

PACKML_STATES = frozenset(
    {
        "IDLE",
        "STARTING",
        "EXECUTE",
        "HOLDING",
        "HELD",
        "UNHOLDING",
        "SUSPENDING",
        "SUSPENDED",
        "UNSUSPENDING",
        "COMPLETING",
        "COMPLETE",
        "RESETTING",
        "ABORTING",
        "ABORTED",
        "CLEARING",
        "STOPPING",
        "STOPPED",
    }
)


@dataclass
class LineTiming:
    """How long a line spends in each state, and how often it holds.

    All durations are seconds of simulated time. Defaults describe an hour-long batch with
    a couple of short holds per hour, which is what the profiles in conf/simulator override.

    There is deliberately no separate `ramp_s`: each ramp runs over the dwell of the state it
    happens in, so a ramp time and a dwell time can never disagree.
    """

    execute_s: float = 3600.0
    starting_s: float = 60.0
    completing_s: float = 30.0
    resetting_s: float = 20.0
    holding_s: float = 15.0
    held_s: float = 300.0
    unholding_s: float = 30.0
    hold_probability_per_hour: float = 2.0
    execute_walk_s: float = 300.0
    heat_tau_s: float = 600.0
    air_noise: float = 0.04


class LineState:
    """One production line's PackML state and the four fields spec 6.1 derives from it.

    Every utility signal in the plant ultimately keys off these four, which is why they live
    here: model the ramp, the thermal lag and the actuator jitter once, and a chiller, a
    cooling tower and an air header all inherit them instead of each faking their own.
    """

    def __init__(self, name: str, timing: LineTiming, nameplate_tph: float, rng: random.Random) -> None:
        self.name = name
        self.timing = timing
        self.nameplate_tph = nameplate_tph
        self.rng = rng
        self.state = "IDLE"
        self.previous: str | None = None
        self.time_in_state_s = 0.0
        self.production_rate = 0.0
        self.heat_load = 0.0
        self.air_demand = 0.0
        self.transition_count = 0

    @property
    def running(self) -> bool:
        return self.state == "EXECUTE"

    @property
    def throughput_tph(self) -> float:
        return round(self.nameplate_tph * self.production_rate, 3)

    def tick(self, dt: float) -> str | None:
        """Advance the machine by `dt` seconds. Returns the new state on a transition."""
        self.time_in_state_s += dt
        self._advance_production_rate(dt)
        self._advance_demands(dt)
        target = self._next_state()
        if target is None:
            return None
        self.previous = self.state
        self.state = target
        self.time_in_state_s = 0.0
        self.transition_count += 1
        return target

    def _dwell_of_current_state(self) -> float:
        timing = self.timing
        dwells = {
            "STARTING": timing.starting_s,
            "UNHOLDING": timing.unholding_s,
            "UNSUSPENDING": timing.unholding_s,
            "COMPLETING": timing.completing_s,
            "HOLDING": timing.holding_s,
            "SUSPENDING": timing.holding_s,
            "STOPPING": timing.completing_s,
            "ABORTING": timing.completing_s,
            "CLEARING": timing.resetting_s,
        }
        return max(dwells.get(self.state, 1.0), 1e-6)

    def _advance_production_rate(self, dt: float) -> None:
        if self.state in _RAMP_UP_STATES:
            # Ramp 0 -> EXECUTE_RATE_FLOOR across this state's own dwell.
            step = EXECUTE_RATE_FLOOR * dt / self._dwell_of_current_state()
            self.production_rate = min(EXECUTE_RATE_FLOOR, self.production_rate + step)
        elif self.state in _RAMP_DOWN_STATES:
            step = EXECUTE_RATE_FLOOR * dt / self._dwell_of_current_state()
            self.production_rate = max(0.0, self.production_rate - step)
        elif self.state == "EXECUTE":
            # Wander inside 0.85-1.0 rather than sitting at nameplate: a mean-reverting step
            # towards the middle of the band, then clamped back into it.
            ratio = dt / max(self.timing.execute_walk_s, 1e-6)
            midpoint = (EXECUTE_RATE_FLOOR + 1.0) / 2.0
            drift = (midpoint - self.production_rate) * ratio
            self.production_rate += drift + (1.0 - EXECUTE_RATE_FLOOR) * math.sqrt(ratio) * self.rng.gauss(0.0, 1.0)
            self.production_rate = min(1.0, max(EXECUTE_RATE_FLOOR, self.production_rate))
        else:
            # IDLE, HELD, SUSPENDED, COMPLETE, ABORTED, STOPPED, RESETTING: nothing is made.
            self.production_rate = 0.0

    def _advance_demands(self, dt: float) -> None:
        """heat_load lags production; air_demand tracks it with jitter. Spec 6.1."""
        self.heat_load += (self.production_rate - self.heat_load) * dt / max(self.timing.heat_tau_s, 1e-6)
        self.heat_load = min(1.0, max(0.0, self.heat_load))
        noisy = self.production_rate + self.rng.gauss(0.0, self.timing.air_noise)
        self.air_demand = min(1.0, max(0.0, noisy))

    def _next_state(self) -> str | None:  # ruff: ignore[complex-structure]
        elapsed = self.time_in_state_s
        timing = self.timing
        match self.state:
            case "IDLE":
                return "STARTING" if elapsed >= timing.starting_s else None
            case "STARTING":
                return "EXECUTE" if elapsed >= timing.starting_s else None
            case "EXECUTE":
                if elapsed >= timing.execute_s:
                    return "COMPLETING"
                return "HOLDING" if self.rng.random() < timing.hold_probability_per_hour / 3600.0 else None
            case "HOLDING":
                return "HELD" if elapsed >= timing.holding_s else None
            case "HELD":
                return "UNHOLDING" if elapsed >= timing.held_s else None
            case "UNHOLDING":
                return "EXECUTE" if elapsed >= timing.unholding_s else None
            case "SUSPENDING":
                return "SUSPENDED" if elapsed >= timing.holding_s else None
            case "SUSPENDED":
                return "UNSUSPENDING" if elapsed >= timing.held_s else None
            case "UNSUSPENDING":
                return "EXECUTE" if elapsed >= timing.unholding_s else None
            case "COMPLETING":
                return "COMPLETE" if elapsed >= timing.completing_s else None
            case "COMPLETE":
                return "RESETTING"
            case "RESETTING":
                return "IDLE" if elapsed >= timing.resetting_s else None
            case "ABORTING":
                return "ABORTED" if elapsed >= timing.completing_s else None
            case "ABORTED":
                return "CLEARING" if elapsed >= timing.held_s else None
            case "CLEARING":
                return "STOPPED" if elapsed >= timing.resetting_s else None
            case "STOPPING":
                return "STOPPED" if elapsed >= timing.completing_s else None
            case "STOPPED":
                return "RESETTING" if elapsed >= timing.held_s else None
            case _:  # pragma: no cover - PACKML_STATES is exhaustive above
                return None


SHIFTS: tuple[str, ...] = ("A", "B", "C")
SHIFT_LENGTH_S = 8 * 3600.0

# Spec 6.2 calls grid carbon intensity diurnal. These are the extremes of that curve, not
# the two values of a tariff switch - solar drives it down over the middle of the day.
GRID_CO2_MAX_G_PER_KWH = 420.0
GRID_CO2_MIN_G_PER_KWH = 290.0
GRID_CO2_TROUGH_HOUR = 13.0

MAX_WIND_SPEED_MS = 25.0
WIND_MEAN_MS = 4.0
WIND_TAU_S = 1800.0
WIND_SIGMA_MS = 2.5

BAROMETRIC_MEAN_MBAR = 1013.0
BAROMETRIC_TAU_S = 6.0 * 3600.0
BAROMETRIC_SIGMA_MBAR = 12.0
BAROMETRIC_MIN_MBAR = 960.0
BAROMETRIC_MAX_MBAR = 1050.0


class SiteState:
    """Conditions every device at one site shares, plus the lines that site runs.

    `lines` is keyed by the site-relative path `"<Area>/<Line>"`, not by the bare line name,
    so two areas may each contain a `Line1` without one shadowing the other.
    """

    def __init__(
        self,
        name: str,
        rng: random.Random,
        *,
        ambient_mean_c: float = 14.0,
        ambient_swing_c: float = 8.0,
        tariff_peak_hours: tuple[int, int] = (8, 20),
    ) -> None:
        self.name = name
        self.rng = rng
        self.lines: dict[str, LineState] = {}
        self.sim_time_s = 0.0
        self._ambient_mean_c = ambient_mean_c
        self._ambient_swing_c = ambient_swing_c
        self._peak_from, self._peak_to = tariff_peak_hours
        self.ambient_temp_c = ambient_mean_c
        self.ambient_rh_pct = 65.0
        self.wet_bulb_temp_c = ambient_mean_c - 3.0
        self.wind_speed_ms = WIND_MEAN_MS
        self.barometric_mbar = BAROMETRIC_MEAN_MBAR
        self.shift = SHIFTS[0]
        self.tariff = "offpeak"
        self.grid_co2_g_per_kwh = GRID_CO2_MIN_G_PER_KWH

    def tick(self, dt: float) -> list[tuple[str, str]]:
        """Advance ambient conditions, shift and tariff, then every line on this site."""
        self.sim_time_s += dt
        hour_of_day = (self.sim_time_s / 3600.0) % 24.0

        # Coldest around 05:00, warmest around 17:00 - a cosine trough at hour 5.
        angle = 2.0 * math.pi * (hour_of_day - 5.0) / 24.0
        drift = self.rng.gauss(0.0, 0.05)
        self.ambient_temp_c = round(self._ambient_mean_c - self._ambient_swing_c * math.cos(angle) + drift, 2)

        # Humidity moves opposite to temperature: warm air at fixed moisture is drier.
        self.ambient_rh_pct = round(min(100.0, max(10.0, 78.0 - 1.6 * (self.ambient_temp_c - self._ambient_mean_c))), 2)
        self.wet_bulb_temp_c = round(_wet_bulb_c(self.ambient_temp_c, self.ambient_rh_pct), 2)

        # Wind and barometric pressure are mean-reverting walks on very different time
        # constants: wind gusts over half an hour, a weather front takes most of a day.
        self.wind_speed_ms = round(
            _mean_reverting(self.wind_speed_ms, WIND_MEAN_MS, WIND_TAU_S, WIND_SIGMA_MS, dt, self.rng, 0.0, MAX_WIND_SPEED_MS),
            2,
        )
        self.barometric_mbar = round(
            _mean_reverting(
                self.barometric_mbar,
                BAROMETRIC_MEAN_MBAR,
                BAROMETRIC_TAU_S,
                BAROMETRIC_SIGMA_MBAR,
                dt,
                self.rng,
                BAROMETRIC_MIN_MBAR,
                BAROMETRIC_MAX_MBAR,
            ),
            1,
        )

        self.shift = SHIFTS[int(self.sim_time_s // SHIFT_LENGTH_S) % len(SHIFTS)]
        self.tariff = "peak" if self._peak_from <= hour_of_day < self._peak_to else "offpeak"
        # Diurnal, with its trough in the early afternoon. Deliberately *not* derived from
        # `tariff`: the cheapest hour and the cleanest hour are not the same hour, and a
        # simulator that ties them together cannot show the difference.
        co2_mean = (GRID_CO2_MAX_G_PER_KWH + GRID_CO2_MIN_G_PER_KWH) / 2.0
        co2_swing = (GRID_CO2_MAX_G_PER_KWH - GRID_CO2_MIN_G_PER_KWH) / 2.0
        co2_angle = 2.0 * math.pi * (hour_of_day - GRID_CO2_TROUGH_HOUR) / 24.0
        self.grid_co2_g_per_kwh = round(co2_mean - co2_swing * math.cos(co2_angle), 1)

        transitions: list[tuple[str, str]] = []
        for line_path, line in self.lines.items():
            if (new_state := line.tick(dt)) is not None:
                transitions.append((line_path, new_state))
        return transitions

    def snapshot(self) -> dict[str, Any]:
        return {
            "ambient_temp_c": self.ambient_temp_c,
            "ambient_rh_pct": self.ambient_rh_pct,
            "wet_bulb_temp_c": self.wet_bulb_temp_c,
            "wind_speed_ms": self.wind_speed_ms,
            "barometric_mbar": self.barometric_mbar,
            "shift": self.shift,
            "tariff": self.tariff,
            "grid_co2_g_per_kwh": self.grid_co2_g_per_kwh,
            "lines": {
                path: {
                    "state": line.state,
                    "previous": line.previous,
                    "production_rate": round(line.production_rate, 4),
                    "throughput_tph": line.throughput_tph,
                    "heat_load": round(line.heat_load, 4),
                    "air_demand": round(line.air_demand, 4),
                    "time_in_state_s": round(line.time_in_state_s, 1),
                    "transition_count": line.transition_count,
                }
                for path, line in self.lines.items()
            },
        }


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


def _wet_bulb_c(dry_bulb_c: float, rh_pct: float) -> float:
    """Stull's approximation. Good to about +/-1 K over normal plant conditions, and cheap.

    Cooling-tower and chiller signals are driven by wet bulb rather than dry bulb, because
    that is what actually limits them - so it has to be present, but it does not have to be
    a psychrometric library.
    """
    rh = max(rh_pct, 1.0)
    return (
        dry_bulb_c * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(dry_bulb_c + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


class PlantContext:
    """Every site's state, advanced together by one clock."""

    def __init__(self, global_seed: int) -> None:
        self.global_seed = global_seed
        self.sites: dict[str, SiteState] = {}
        self.sim_time_s = 0.0

    def add_site(self, name: str, **kwargs: Any) -> SiteState:
        site = SiteState(name, random.Random(f"{self.global_seed}:{name}"), **kwargs)  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        self.sites[name] = site
        return site

    def add_line(self, site: str, area: str, line: str, timing: LineTiming, nameplate_tph: float) -> LineState:
        if site not in self.sites:
            raise KeyError(f"cannot add line {area}/{line!r}: site {site!r} is not in the plant context")
        path = f"{area}/{line}"
        state = LineState(line, timing, nameplate_tph, random.Random(f"{self.global_seed}:{site}/{path}"))  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        self.sites[site].lines[path] = state
        return state

    def resolve_line(self, path: str) -> LineState:
        """Look up a fully-qualified `<Site>/<Area>/<Line>`. Raises `KeyError` if absent."""
        segments = path.split("/")
        if len(segments) != 3:
            raise KeyError(f"line path {path!r} must have exactly three segments, Site/Area/Line")
        site_name, area, line = segments
        site = self.sites.get(site_name)
        if site is None:
            raise KeyError(f"line path {path!r} names site {site_name!r}, which is not in the plant context")
        state = site.lines.get(f"{area}/{line}")
        if state is None:
            raise KeyError(f"line path {path!r} does not exist at site {site_name!r}")
        return state

    def resolve_serves(self, paths: Sequence[str]) -> tuple[LineState, ...]:
        """Resolve every `serves` path, or fail. Spec 6.3 makes an unknown path fatal."""
        return tuple(self.resolve_line(path) for path in paths)

    def tick(self, dt: float) -> list[tuple[str, str, str]]:
        self.sim_time_s += dt
        transitions: list[tuple[str, str, str]] = []
        for site_name, site in self.sites.items():
            transitions.extend((site_name, line_path, state) for line_path, state in site.tick(dt))
        return transitions

    def snapshot(self) -> dict[str, Any]:
        return {name: site.snapshot() for name, site in self.sites.items()}


class DeviceView:
    """A device's read-only window onto the plant.

    Signals receive this and nothing else, so a signal cannot mutate the world it measures.
    `serves` names the lines a utility device feeds, as fully-qualified `<Site>/<Area>/<Line>`
    paths; the served_* properties aggregate them, which is how a chiller's load follows the
    production it is actually cooling. `line` is a site-relative `<Area>/<Line>` path, or
    `None` for a device that is not attached to a production line at all.
    """

    __slots__ = ("_context", "_line", "_served", "_serves", "_site")

    def __init__(self, context: PlantContext, site: str, line: str | None, serves: Sequence[str] = ()) -> None:
        self._context = context
        self._site = site
        self._line = line
        self._serves = tuple(serves)
        # Resolved once, here, so spec 6.3's "an unknown `serves` path is a load-time error"
        # holds: this constructor runs during the profile load. Holding the LineState objects
        # rather than their names also drops a dict lookup out of every signal evaluation.
        self._served = context.resolve_serves(self._serves)

    @property
    def site(self) -> str:
        return self._site

    @property
    def line(self) -> str | None:
        return self._line

    @property
    def serves(self) -> tuple[str, ...]:
        """The declared paths, for sub-project B's `GET /simulator/config` to echo back."""
        return self._serves

    @property
    def _site_state(self) -> SiteState:
        return self._context.sites[self._site]

    @property
    def _line_state(self) -> LineState | None:
        if self._line is None:
            return None
        return self._site_state.lines.get(self._line)

    @property
    def ambient_temp_c(self) -> float:
        return self._site_state.ambient_temp_c

    @property
    def ambient_rh_pct(self) -> float:
        return self._site_state.ambient_rh_pct

    @property
    def wet_bulb_temp_c(self) -> float:
        return self._site_state.wet_bulb_temp_c

    @property
    def wind_speed_ms(self) -> float:
        return self._site_state.wind_speed_ms

    @property
    def barometric_mbar(self) -> float:
        return self._site_state.barometric_mbar

    @property
    def shift(self) -> str:
        return self._site_state.shift

    @property
    def tariff(self) -> str:
        return self._site_state.tariff

    @property
    def grid_co2_g_per_kwh(self) -> float:
        return self._site_state.grid_co2_g_per_kwh

    @property
    def state(self) -> str:
        line = self._line_state
        return line.state if line is not None else "N/A"

    @property
    def previous(self) -> str | None:
        line = self._line_state
        return line.previous if line is not None else None

    @property
    def production_rate(self) -> float:
        line = self._line_state
        return line.production_rate if line is not None else 0.0

    @property
    def throughput_tph(self) -> float:
        line = self._line_state
        return line.throughput_tph if line is not None else 0.0

    @property
    def heat_load(self) -> float:
        line = self._line_state
        return line.heat_load if line is not None else 0.0

    @property
    def air_demand(self) -> float:
        line = self._line_state
        return line.air_demand if line is not None else 0.0

    @property
    def time_in_state_s(self) -> float:
        line = self._line_state
        return line.time_in_state_s if line is not None else 0.0

    @property
    def running(self) -> bool:
        line = self._line_state
        return line.running if line is not None else False

    @property
    def served_line_count(self) -> int:
        return len(self._served)

    @property
    def served_running_count(self) -> int:
        return sum(1 for line in self._served if line.running)

    @property
    def served_production(self) -> float:
        """Mean, not sum: a utility sized for its served lines is at half load when half run."""
        if not self._served:
            return 0.0
        return round(sum(line.production_rate for line in self._served) / len(self._served), 4)

    @property
    def served_throughput_tph(self) -> float:
        """Sum: tonnes per hour through a shared meter is the total, not the average."""
        return round(sum(line.throughput_tph for line in self._served), 3)

    @property
    def served_heat_load(self) -> float:
        """Sum: a cooling tower rejects every served line's heat, not their average."""
        return round(sum(line.heat_load for line in self._served), 4)

    @property
    def served_air_demand(self) -> float:
        """Sum: a compressor house supplies every served line's draw, not their average."""
        return round(sum(line.air_demand for line in self._served), 4)


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
        self.p201.run_cmd = True
        self.p201.speed_sp = self.DIST_SPEED_SP
        self.p201.running = not self.p201.fault
        if self.p201.running and self.p201.start_count == 0:
            self.p201.start_count += 1
        self.p202.run_cmd = False
        self.p202.speed_sp = 0.0
        self.p202.running = False
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
                events.append(f"Fault{tag}")
                if tag in ("P101", "P102", "P103") and tag == self.duty_raw_pump:
                    nxt = self._next_raw_pump(tag)
                    if nxt is not None:
                        self.duty_raw_pump = nxt
                        self._start_motor(self._raw_pump_by_name(nxt))
                elif tag == "P201":
                    self.p202.run_cmd = True
                    self.p202.speed_sp = self.DIST_SPEED_SP
                    self.p202.running = not self.p202.fault
                    if self.p202.running and self.p202.start_count == 0:
                        self.p202.start_count += 1
                    self.lead_dist_pump = "P202"
        return events

    def advance_sequencer(self, dt: float) -> list[str]:
        events: list[str] = []
        if not self._initialized:
            self._initialize_running()
            self._initialized = True

        if self.mode == "Backwash":
            self.backwash_s += dt
            if self.backwash_s >= self.BACKWASH_DURATION_S:
                events.extend(self._exit_backwash())
            return events

        # Running mode
        self.running_s += dt
        self.duty_s += dt
        if self.running_s >= self.BACKWASH_TRIGGER_S:
            events.extend(self._enter_backwash())
            return events
        if self.duty_s >= self.DUTY_CYCLE_S:
            events.extend(self._rotate_duty())

        # Lead pump reflects current health
        if self.p201.fault and not self.p202.fault:
            self.lead_dist_pump = "P202"
        else:
            self.lead_dist_pump = "P201"

        # Inlet interlock: if V101 somehow closed, stop raw pumps but keep cmd intent
        if not self.v101.open_fb:
            for pump in (self.p101, self.p102, self.p103):
                pump.running = False

        events.extend(self._apply_faults())
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
