import asyncio
import random
import statistics

import pytest

from uns_simulator.plant import (
    EXECUTE_RATE_FLOOR,
    GRID_CO2_MAX_G_PER_KWH,
    GRID_CO2_MIN_G_PER_KWH,
    MAX_WIND_SPEED_MS,
    PACKML_STATES,
    SHIFTS,
    DeviceView,
    LineState,
    LineTiming,
    PlantClock,
    PlantContext,
    SiteState,
)


def _line(**timing_kwargs):
    return LineState("Line1", LineTiming(**timing_kwargs), nameplate_tph=12.0, rng=random.Random(7))


def test_a_line_starts_idle():
    line = _line()
    assert line.state == "IDLE"
    assert line.production_rate == 0.0
    assert line.running is False


def test_idle_leads_to_execute_through_starting():
    line = _line(starting_s=5.0)
    seen = [line.state]
    for _ in range(20):
        if (new := line.tick(1.0)) is not None:
            seen.append(new)
    assert seen[:3] == ["IDLE", "STARTING", "EXECUTE"]


def test_only_execute_counts_as_running():
    line = _line(starting_s=1.0)
    line.tick(1.0)
    assert line.state == "STARTING"
    assert line.running is False
    line.tick(1.0)
    assert line.state == "EXECUTE"
    assert line.running is True


def test_production_rate_ramps_across_starting_rather_than_stepping():
    """Spec 6.1: STARTING ramps 0 -> 0.85, and it does it over the STARTING dwell."""
    line = _line(starting_s=60.0)
    line.tick(1.0)  # IDLE dwell is starting_s too, so this does not leave IDLE yet
    while line.state == "IDLE":
        line.tick(1.0)
    assert line.state == "STARTING"
    rates = []
    while line.state == "STARTING":
        line.tick(1.0)
        rates.append(line.production_rate)
    assert rates[0] < rates[-1]
    assert rates[-1] == pytest.approx(EXECUTE_RATE_FLOOR, abs=0.02)
    assert all(b - a < 0.05 for a, b in zip(rates, rates[1:], strict=False))


def test_execute_holds_the_rate_inside_the_spec_band():
    """Spec 6.1: EXECUTE is 0.85-1.0 — a real line does not sit pinned at nameplate."""
    line = _line(starting_s=2.0, execute_s=10_000.0, hold_probability_per_hour=0.0, execute_walk_s=30.0)
    while line.state != "EXECUTE":
        line.tick(1.0)
    rates = []
    for _ in range(2000):
        line.tick(1.0)
        rates.append(line.production_rate)
    assert all(EXECUTE_RATE_FLOOR <= rate <= 1.0 for rate in rates)
    assert min(rates) < max(rates), "the rate must wander, not sit at one value"
    assert line.throughput_tph == pytest.approx(12.0 * line.production_rate, abs=0.01)


def test_production_rate_is_zero_in_the_fully_stopped_states():
    line = _line()
    for state in ("IDLE", "HELD", "SUSPENDED", "COMPLETE", "ABORTED", "STOPPED"):
        line.state = state
        line.production_rate = 0.9
        line.tick(1.0)
        assert line.production_rate == pytest.approx(0.0), state


def test_completing_ramps_the_rate_down():
    line = _line(starting_s=1.0, execute_s=20.0, completing_s=10.0, hold_probability_per_hour=0.0)
    while line.state != "COMPLETING":
        line.tick(1.0)
    first = line.production_rate
    for _ in range(4):
        line.tick(1.0)
    assert line.production_rate < first


def test_heat_load_lags_production_rate():
    """Spec 6.1: a first-order lag, so cooling responds slowly. This is the whole point."""
    line = _line(starting_s=2.0, execute_s=100_000.0, hold_probability_per_hour=0.0, heat_tau_s=600.0)
    while line.state != "EXECUTE":
        line.tick(1.0)
    for _ in range(60):
        line.tick(1.0)
    assert line.heat_load < line.production_rate / 2, "one minute in, heat has barely built"
    for _ in range(3000):
        line.tick(1.0)
    assert line.heat_load == pytest.approx(line.production_rate, abs=0.05), "and eventually it catches up"


def test_heat_load_decays_slowly_after_a_stop():
    line = _line(heat_tau_s=600.0)
    line.state = "EXECUTE"
    line.heat_load = 1.0
    line.production_rate = 1.0
    line.state = "HELD"
    line.tick(1.0)
    assert line.production_rate == pytest.approx(0.0), "production stops at once"
    assert line.heat_load > 0.99, "heat does not"


def test_air_demand_tracks_production_with_a_fast_noisy_component():
    line = _line(starting_s=2.0, execute_s=100_000.0, hold_probability_per_hour=0.0, air_noise=0.04)
    while line.state != "EXECUTE":
        line.tick(1.0)
    demands, rates = [], []
    for _ in range(300):
        line.tick(1.0)
        demands.append(line.air_demand)
        rates.append(line.production_rate)
    assert all(0.0 <= demand <= 1.0 for demand in demands)
    assert statistics.mean(demands) == pytest.approx(statistics.mean(rates), abs=0.03)
    jitter = statistics.mean(abs(b - a) for a, b in zip(demands, demands[1:], strict=False))
    assert jitter > 0.01, "air demand is noisy tick to tick, unlike heat load"


def test_a_full_cycle_returns_to_idle():
    line = _line(starting_s=2.0, execute_s=10.0, completing_s=2.0, resetting_s=2.0, hold_probability_per_hour=0.0)
    states = []
    for _ in range(60):
        if (new := line.tick(1.0)) is not None:
            states.append(new)
        if states.count("IDLE") == 1:
            break
    assert states == ["STARTING", "EXECUTE", "COMPLETING", "COMPLETE", "RESETTING", "IDLE"]


def test_a_hold_walks_the_full_hold_branch():
    line = _line(
        starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=3600.0 * 10, holding_s=2.0, held_s=3.0, unholding_s=2.0
    )
    states = []
    for _ in range(120):
        if (new := line.tick(1.0)) is not None:
            states.append(new)
        if states.count("EXECUTE") == 2:
            break
    assert states[:5] == ["STARTING", "EXECUTE", "HOLDING", "HELD", "UNHOLDING"]
    assert states[5] == "EXECUTE"


def test_every_state_the_machine_can_reach_is_a_packml_state():
    line = _line(starting_s=1.0, execute_s=5.0, completing_s=1.0, resetting_s=1.0, hold_probability_per_hour=60.0)
    for _ in range(5000):
        line.tick(1.0)
        assert line.state in PACKML_STATES


def test_time_in_state_resets_on_transition():
    line = _line(starting_s=3.0)
    line.tick(1.0)
    line.tick(1.0)
    assert line.state == "IDLE"
    assert line.time_in_state_s == pytest.approx(2.0)
    line.tick(1.0)
    assert line.state == "STARTING"
    assert line.time_in_state_s == pytest.approx(0.0)
    line.tick(1.0)
    assert line.time_in_state_s == pytest.approx(1.0)


def test_previous_state_is_recorded():
    line = _line(starting_s=1.0)
    line.tick(1.0)
    assert line.state == "STARTING"
    assert line.previous == "IDLE"


def test_the_same_seed_gives_the_same_state_history():
    def history():
        line = LineState(
            "L", LineTiming(starting_s=2.0, execute_s=30.0, hold_probability_per_hour=120.0), 12.0, random.Random(42)
        )
        return [(line.tick(1.0), line.state, round(line.production_rate, 6)) for _ in range(500)]

    assert history() == history()


def _context():
    """Two Dormagen production lines that reach EXECUTE after one tick and never hold."""
    context = PlantContext(global_seed=7)
    context.add_site("Dormagen")
    timing = LineTiming(starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=0.0)
    context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
    context.add_line("Dormagen", "Production", "Line2", timing, 8.0)
    return context


def test_site_ambient_swings_over_a_day():
    site = SiteState("Dormagen", random.Random(7), ambient_mean_c=14.0, ambient_swing_c=8.0)
    temperatures = []
    for _ in range(0, 86_400, 60):
        site.tick(60.0)
        temperatures.append(site.ambient_temp_c)
    assert max(temperatures) > 20.0
    assert min(temperatures) < 8.0


def test_wet_bulb_is_never_above_dry_bulb():
    site = SiteState("Dormagen", random.Random(7))
    for _ in range(2000):
        site.tick(60.0)
        assert site.wet_bulb_temp_c <= site.ambient_temp_c + 1e-6


def test_humidity_stays_in_range():
    site = SiteState("Dormagen", random.Random(7))
    for _ in range(2000):
        site.tick(60.0)
        assert 10.0 <= site.ambient_rh_pct <= 100.0


def test_shift_rotates_every_eight_hours():
    site = SiteState("Dormagen", random.Random(7))
    shifts = []
    for _ in range(24):
        site.tick(3600.0)
        shifts.append(site.shift)
    assert set(shifts) == set(SHIFTS)
    assert shifts[0] == shifts[1]


def test_tariff_is_peak_during_the_day():
    site = SiteState("Dormagen", random.Random(7), tariff_peak_hours=(8, 20))
    site.tick(10.0 * 3600.0)
    assert site.tariff == "peak"
    site.tick(13.0 * 3600.0)
    assert site.tariff == "offpeak"


def test_wind_speed_stays_in_range():
    site = SiteState("Dormagen", random.Random(7))
    speeds = []
    for _ in range(5000):
        site.tick(60.0)
        assert 0.0 <= site.wind_speed_ms <= MAX_WIND_SPEED_MS
        speeds.append(site.wind_speed_ms)
    # It has to actually move, or the stack's plume-direction signals are constant.
    assert max(speeds) - min(speeds) > 1.0


def test_barometric_pressure_stays_near_standard():
    site = SiteState("Dormagen", random.Random(7))
    readings = []
    for _ in range(5000):
        site.tick(60.0)
        readings.append(site.barometric_mbar)
    assert min(readings) > 950.0
    assert max(readings) < 1060.0
    assert max(readings) - min(readings) > 1.0


def test_grid_carbon_intensity_is_diurnal_with_a_midday_trough():
    """Spec 6.2 calls grid_co2_g_per_kwh diurnal, not a function of the tariff clock.

    Solar pushes it down over the middle of the day, so a plant that shifts load into
    the afternoon shows a lower CarbonRate even at the same kW.
    """
    site = SiteState("Dormagen", random.Random(7))
    by_hour: dict[int, float] = {}
    for _ in range(24):
        site.tick(3600.0)
        by_hour[int((site.sim_time_s / 3600.0) % 24.0)] = site.grid_co2_g_per_kwh
    assert min(by_hour, key=by_hour.__getitem__) in {12, 13, 14}
    assert max(by_hour.values()) - min(by_hour.values()) > 100.0
    assert all(GRID_CO2_MIN_G_PER_KWH <= value <= GRID_CO2_MAX_G_PER_KWH for value in by_hour.values())


def test_context_tick_reports_line_transitions_with_their_site_and_path():
    context = _context()
    transitions = []
    for _ in range(10):
        transitions.extend(context.tick(1.0))
    assert ("Dormagen", "Production/Line1", "STARTING") in transitions
    assert ("Dormagen", "Production/Line2", "STARTING") in transitions


def test_context_snapshot_shape():
    context = _context()
    context.tick(1.0)
    snapshot = context.snapshot()
    site = snapshot["Dormagen"]
    assert set(site) >= {
        "ambient_temp_c",
        "ambient_rh_pct",
        "wet_bulb_temp_c",
        "wind_speed_ms",
        "barometric_mbar",
        "shift",
        "tariff",
        "grid_co2_g_per_kwh",
        "lines",
    }
    line = site["lines"]["Production/Line1"]
    assert set(line) >= {
        "state",
        "previous",
        "production_rate",
        "throughput_tph",
        "heat_load",
        "air_demand",
        "time_in_state_s",
    }


def test_device_view_reads_its_own_line():
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    view = DeviceView(context, "Dormagen", "Production/Line1")
    assert view.state == "EXECUTE"
    assert view.running is True
    assert view.production_rate == pytest.approx(0.9, abs=0.1)
    assert view.throughput_tph == pytest.approx(view.production_rate * 12.0, abs=0.05)


def test_device_view_without_a_line_still_reads_the_site():
    context = _context()
    context.tick(60.0)
    view = DeviceView(context, "Dormagen", None)
    assert view.line is None
    assert view.state == "N/A"
    assert view.production_rate == 0.0
    assert view.heat_load == 0.0
    assert view.air_demand == 0.0
    assert view.running is False
    assert isinstance(view.ambient_temp_c, float)


def test_serves_aggregates_the_lines_a_utility_feeds():
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    lines = context.sites["Dormagen"].lines
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/Line2"])
    assert view.served_line_count == 2
    assert view.served_running_count == 2
    assert view.served_production == pytest.approx(0.9, abs=0.1)
    expected_tph = lines["Production/Line1"].throughput_tph + lines["Production/Line2"].throughput_tph
    assert view.served_throughput_tph == pytest.approx(expected_tph, abs=0.01)
    # Each line runs its own seeded walk, so the sum is not the mean times the total nameplate.
    assert 17.0 < view.served_throughput_tph <= 20.0


def test_served_heat_load_and_air_demand_are_sums():
    """Spec 6.3: production is a mean, the two demand aggregates are sums."""
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    lines = context.sites["Dormagen"].lines
    lines["Production/Line1"].heat_load = 0.4
    lines["Production/Line2"].heat_load = 0.3
    lines["Production/Line1"].air_demand = 0.6
    lines["Production/Line2"].air_demand = 0.2
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/Line2"])
    assert view.served_heat_load == pytest.approx(0.7)
    assert view.served_air_demand == pytest.approx(0.8)


def test_served_production_is_a_mean_not_a_sum():
    """A utility sized for two lines is at half load when one runs, not at 100%."""
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    lines = context.sites["Dormagen"].lines
    lines["Production/Line1"].production_rate = 1.0
    lines["Production/Line2"].production_rate = 0.0
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/Line2"])
    assert view.served_production == pytest.approx(0.5)


def test_serving_a_path_that_does_not_exist_is_a_load_time_error():
    """Spec 6.3. A typo in `serves` must fail the profile load, not silently halve a chiller's load."""
    context = _context()
    with pytest.raises(KeyError, match="Dormagen/Production/LineNine"):
        DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/LineNine"])


def test_serving_a_line_at_another_site_is_allowed():
    """A central utility can feed lines at more than one site, so `serves` is site-qualified."""
    context = _context()
    context.add_site("Krefeld")
    context.add_line("Krefeld", "Production", "Line1", LineTiming(starting_s=1.0, hold_probability_per_hour=0.0), 5.0)
    for _ in range(20):
        context.tick(1.0)
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Krefeld/Production/Line1"])
    assert view.served_line_count == 2
    assert view.served_throughput_tph > 0.0


def test_serves_nothing_yields_zeroes():
    view = DeviceView(_context(), "Dormagen", None)
    assert view.serves == ()
    assert view.served_line_count == 0
    assert view.served_production == 0.0
    assert view.served_throughput_tph == 0.0
    assert view.served_heat_load == 0.0
    assert view.served_air_demand == 0.0


def test_device_view_exposes_no_setter_for_plant_state():
    view = DeviceView(_context(), "Dormagen", "Production/Line1")
    with pytest.raises(AttributeError):
        view.production_rate = 0.5


def test_resolve_line_names_the_path_it_could_not_find():
    context = _context()
    with pytest.raises(KeyError, match="Dormagen/Utilities/Nope"):
        context.resolve_line("Dormagen/Utilities/Nope")


def test_resolve_line_rejects_a_path_that_is_not_three_segments():
    context = _context()
    with pytest.raises(KeyError, match="Site/Area/Line"):
        context.resolve_line("Dormagen/Line1")


def test_adding_a_line_to_an_unknown_site_names_the_site():
    with pytest.raises(KeyError, match="Nowhere"):
        PlantContext(global_seed=7).add_line("Nowhere", "Production", "Line1", LineTiming(), 1.0)


def test_advance_moves_the_context_by_one_tick():
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    clock.advance()
    assert context.sim_time_s == pytest.approx(1.0)
    assert clock.tick_count == 1


def test_advance_accepts_an_explicit_dt():
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    clock.advance(60.0)
    assert context.sim_time_s == pytest.approx(60.0)


def test_advance_returns_transitions_and_notifies_callbacks():
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    seen: list[tuple[str, str, str]] = []
    clock.on_transition(lambda site, line, state: seen.append((site, line, state)))
    transitions: list[tuple[str, str, str]] = []
    for _ in range(5):
        transitions.extend(clock.advance())
    assert transitions
    assert seen == transitions


def test_a_failing_callback_does_not_stop_the_clock():
    """Self-telemetry publishing must never be able to freeze the simulated world."""
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    calls: list[str] = []

    def explode(site, line, state):
        calls.append("boom")
        raise RuntimeError("broker down")

    clock.on_transition(explode)
    for _ in range(5):
        clock.advance()
    assert calls
    assert clock.tick_count == 5


@pytest.mark.asyncio
async def test_run_ticks_until_stopped():
    context = _context()
    clock = PlantClock(context, tick_s=0.01)
    task = asyncio.create_task(clock.run())
    await asyncio.sleep(0.15)
    clock.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert clock.tick_count >= 5
    assert clock.running is False


@pytest.mark.asyncio
async def test_run_can_be_cancelled():
    clock = PlantClock(_context(), tick_s=0.01)
    task = asyncio.create_task(clock.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_same_seed_gives_the_same_plant_history():
    def history():
        context = PlantContext(global_seed=99)
        context.add_site("Dormagen")
        timing = LineTiming(starting_s=2.0, execute_s=30.0, hold_probability_per_hour=120.0)
        context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
        clock = PlantClock(context, tick_s=1.0)
        line = context.sites["Dormagen"].lines["Production/Line1"]
        return [(line.state, clock.advance() and None) for _ in range(400)]

    assert history() == history()
