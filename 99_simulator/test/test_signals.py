import statistics

import pytest

from uns_simulator.signals import (
    SIGNAL_SHAPES,
    SignalSpec,
    build_signal,
    order_signals,
    resolve_ctx_path,
    signal_dependencies,
    signal_seed,
    spec_from_config,
)


class FakeLine:
    def __init__(self, *, state="Running", production_rate=1.0, throughput_tph=10.0):
        self.state = state
        self.production_rate = production_rate
        self.throughput_tph = throughput_tph


class FakeView:
    """Minimal stand-in for DeviceView: a nested object `resolve_ctx_path` can walk."""

    def __init__(self, *, running=True, production_rate=1.0, ambient_temp_c=20.0, line=None):
        self.running = running
        self.production_rate = production_rate
        self.ambient_temp_c = ambient_temp_c
        self.line = line


def _run(signal, ticks, dt=1.0):
    return [signal.next(dt, None, {}) for _ in range(ticks)]


def test_legacy_sensor_config_still_parses_as_noise():
    spec = spec_from_config("Temperature", {"base_value": 75.0, "variation": 2.0, "unit": "°C"})
    assert spec.shape == "noise"
    assert spec.base_value == pytest.approx(75.0)
    assert spec.variation == pytest.approx(2.0)
    assert spec.unit == "°C"
    assert spec.tier == "process"
    assert spec.precision == 2


def test_seed_is_stable_for_the_same_topic():
    assert signal_seed(1234, "A/B/C") == signal_seed(1234, "A/B/C")


def test_seed_differs_by_topic_and_by_global_seed():
    assert signal_seed(1234, "A/B/C") != signal_seed(1234, "A/B/D")
    assert signal_seed(1234, "A/B/C") != signal_seed(5678, "A/B/C")


def test_seed_is_stable_across_processes():
    """A literal, not a recomputation: `hash()` would make this value vary per process."""
    assert signal_seed(0, "AcmeWater/Site1/RawWater/Train1/P101/WTP_MotorDOL/ProcessValue/Speed") == 6819111209282605787


def test_noise_stays_within_variation_band():
    signal = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7)
    for _ in range(500):
        value = signal.next(1.0, None, {})
        assert 73.0 <= value <= 77.0


def test_noise_is_reproducible_for_the_same_seed():
    first = [build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7).next(1.0, None, {})]
    second = [build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7).next(1.0, None, {})]
    assert first == second


def test_two_signals_on_different_topics_diverge():
    a = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "a/T", 7)
    b = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "b/T", 7)
    assert [a.next(1.0, None, {}) for _ in range(20)] != [b.next(1.0, None, {}) for _ in range(20)]


def test_shape_params_are_read_from_top_level_yaml_keys():
    """Spec 7.3 writes shape params flat: `expr:`, `rate:`, `initial:` are top-level."""
    spec = spec_from_config(
        "EnergyTotal",
        {"shape": "counter", "unit": "kWh", "rate": "ActivePower / 3600.0", "initial": 84000.0, "tier": "meter"},
    )
    assert spec.shape == "counter"
    assert spec.tier == "meter"
    assert spec.params == {"rate": "ActivePower / 3600.0", "initial": 84000.0}


def test_expression_constant_block_is_merged_into_params():
    """Spec 5.4 permits "keys of `params`" as expression names, so keep one flat namespace."""
    spec = spec_from_config(
        "ActivePower",
        {
            "shape": "derived",
            "unit": "kW",
            "expr": "base_load + ctx.served_production * connected_kw",
            "params": {"base_load": 220.0, "connected_kw": 1450.0},
        },
    )
    assert spec.params["expr"] == "base_load + ctx.served_production * connected_kw"
    assert spec.params["base_load"] == pytest.approx(220.0)
    assert spec.params["connected_kw"] == pytest.approx(1450.0)
    assert "params" not in spec.params


def test_constant_never_moves():
    signal = build_signal(SignalSpec(name="Sp", shape="constant", params={"value": 180.0}), "t/Sp", 7)
    assert [signal.next(1.0, None, {}) for _ in range(5)] == [180.0] * 5


def test_limits_take_precedence_over_the_noise_heuristic():
    """Spec 5.1: hihi/lolo -> Alarm, hi/lo -> Warning, and only then the legacy heuristic."""
    spec = SignalSpec(name="Lel", unit="%", variation=1.0, limits={"hi": 10.0, "hihi": 20.0})
    signal = build_signal(spec, "t/Lel", 7)
    signal.value = 5.0
    assert signal.status() == "Normal"
    signal.value = 12.0
    assert signal.status() == "Warning"
    signal.value = 25.0
    assert signal.status() == "Alarm"


def test_lo_and_lolo_limits_fire_downwards():
    spec = SignalSpec(name="O2", unit="%", limits={"lo": 19.5, "lolo": 18.0})
    signal = build_signal(spec, "t/O2", 7)
    signal.value = 20.9
    assert signal.status() == "Normal"
    signal.value = 19.0
    assert signal.status() == "Warning"
    signal.value = 17.5
    assert signal.status() == "Alarm"


def test_status_heuristic_matches_the_pre_existing_thresholds():
    signal = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7)
    signal.value = 75.0
    assert signal.status() == "Normal"
    signal.value = 75.0 + 2.0 * 2.5
    assert signal.status() == "Warning"
    signal.value = 75.0 + 2.0 * 3.5
    assert signal.status() == "Alarm"


def test_value_range_clamps():
    signal = build_signal(SignalSpec(name="T", base_value=75.0, variation=50.0, value_range=(70.0, 80.0)), "t/T", 7)
    for _ in range(200):
        assert 70.0 <= signal.next(1.0, None, {}) <= 80.0


def test_unknown_shape_names_itself():
    with pytest.raises(ValueError, match="banana"):
        build_signal(SignalSpec(name="X", shape="banana"), "t/X", 7)


def test_registry_holds_all_ten_declared_shapes():
    assert set(SIGNAL_SHAPES) == {
        "noise",
        "constant",
        "ou_walk",
        "counter",
        "sawtooth",
        "diurnal",
        "derived",
        "window_agg",
        "stepped",
        "bernoulli_event",
    }


def test_ou_walk_is_autocorrelated_unlike_noise():
    """The point of ou_walk: consecutive samples are close, so the trace wanders."""
    walk = build_signal(
        SignalSpec(name="P", shape="ou_walk", params={"mean": 150.0, "tau": 60.0, "sigma": 5.0}),
        "t/P",
        7,
    )
    noise = build_signal(SignalSpec(name="P", base_value=150.0, variation=5.0), "t/P", 7)
    walk_values = _run(walk, 300)
    noise_values = _run(noise, 300)
    walk_steps = statistics.mean(abs(b - a) for a, b in zip(walk_values, walk_values[1:], strict=False))
    noise_steps = statistics.mean(abs(b - a) for a, b in zip(noise_values, noise_values[1:], strict=False))
    assert walk_steps < noise_steps / 2


def test_ou_walk_reverts_to_its_mean():
    signal = build_signal(
        SignalSpec(name="P", shape="ou_walk", params={"mean": 150.0, "tau": 10.0, "sigma": 3.0}),
        "t/P",
        7,
    )
    signal.value = 300.0
    signal._state = 300.0
    for _ in range(200):
        signal.next(1.0, None, {})
    assert abs(signal.value - 150.0) < 20.0


def test_ou_walk_falls_back_to_base_value_and_variation():
    """A legacy entry gains a trend line by adding `shape: ou_walk` and nothing else."""
    signal = build_signal(SignalSpec(name="P", shape="ou_walk", base_value=150.0, variation=5.0), "t/P", 7)
    assert signal._mean == pytest.approx(150.0)
    assert signal._sigma == pytest.approx(5.0)


def test_ou_walk_respects_value_range():
    signal = build_signal(
        SignalSpec(
            name="P",
            shape="ou_walk",
            value_range=(140.0, 160.0),
            params={"mean": 150.0, "tau": 5.0, "sigma": 50.0},
        ),
        "t/P",
        7,
    )
    for value in _run(signal, 500):
        assert 140.0 <= value <= 160.0


def test_diurnal_peaks_and_troughs_once_per_period():
    signal = build_signal(
        SignalSpec(
            name="Amb",
            shape="diurnal",
            precision=3,
            params={"mean": 20.0, "amplitude": 6.0, "period_s": 100.0, "phase_s": 25.0},
        ),
        "t/Amb",
        7,
    )
    values = _run(signal, 100)
    assert max(values) == pytest.approx(26.0, abs=0.05)
    assert min(values) == pytest.approx(14.0, abs=0.05)


def test_diurnal_is_smooth():
    signal = build_signal(
        SignalSpec(name="Amb", shape="diurnal", precision=3, params={"mean": 20.0, "amplitude": 6.0, "period_s": 600.0}),
        "t/Amb",
        7,
    )
    values = _run(signal, 200)
    assert all(abs(b - a) < 0.5 for a, b in zip(values, values[1:], strict=False))


def test_sawtooth_fills_slowly_and_drains_quickly():
    """Spec 5.2: independent fill_rate and drain_rate, both in units per second."""
    signal = build_signal(
        SignalSpec(
            name="Basin",
            shape="sawtooth",
            precision=3,
            params={"low": 0.0, "high": 100.0, "fill_rate": 10.0, "drain_rate": 50.0},
        ),
        "t/Basin",
        7,
    )
    values = _run(signal, 13)
    assert values[0] == pytest.approx(10.0)
    assert values[9] == pytest.approx(100.0)
    assert values[10] == pytest.approx(50.0)
    assert values[11] == pytest.approx(0.0)
    assert values[12] == pytest.approx(10.0)


def test_sawtooth_starts_where_start_says():
    signal = build_signal(
        SignalSpec(
            name="Basin",
            shape="sawtooth",
            precision=3,
            params={"low": 20.0, "high": 80.0, "fill_rate": 1.0, "drain_rate": 1.0, "start": 79.0},
        ),
        "t/Basin",
        7,
    )
    assert signal.next(1.0, None, {}) == pytest.approx(80.0)
    assert signal.next(1.0, None, {}) == pytest.approx(79.0)


def test_sawtooth_drain_rate_defaults_to_fill_rate():
    signal = build_signal(
        SignalSpec(name="Basin", shape="sawtooth", params={"low": 0.0, "high": 5.0, "fill_rate": 5.0}),
        "t/Basin",
        7,
    )
    assert signal._drain_rate == pytest.approx(5.0)


def test_counter_integrates_a_sibling_named_by_rate():
    """`rate` naming a sibling integrates that sibling: 2 ea/s for 10 s is 20 ea."""
    signal = build_signal(
        SignalSpec(name="GoodCount", shape="counter", unit="ea", precision=0, params={"rate": "PieceRate"}),
        "t/Good",
        7,
    )
    view = FakeView()
    for _ in range(10):
        signal.next(1.0, view, {"PieceRate": 2.0})
    assert signal.value == pytest.approx(20.0)


def test_counter_integrates_a_fixed_numeric_rate():
    signal = build_signal(
        SignalSpec(name="RunHours", shape="counter", unit="h", precision=4, params={"rate": 1.0 / 3600.0}),
        "t/RH",
        7,
    )
    for _ in range(3600):
        signal.next(1.0, FakeView(), {})
    assert signal.value == pytest.approx(1.0, abs=1e-4)


def test_counter_never_decreases():
    signal = build_signal(
        SignalSpec(name="Vol", shape="counter", precision=4, params={"rate": "Flow"}),
        "t/V",
        7,
    )
    view = FakeView()
    values = [signal.next(1.0, view, {"Flow": 12.0}) for _ in range(50)]
    assert all(b >= a for a, b in zip(values, values[1:], strict=False))


def test_counter_holds_its_reading_when_the_rate_is_zero():
    """A stopped line is a zero rate, not a special case inside the counter."""
    signal = build_signal(
        SignalSpec(name="Pieces", shape="counter", precision=0, params={"rate": "PieceRate"}),
        "t/Pieces",
        7,
    )
    view = FakeView()
    for _ in range(10):
        signal.next(1.0, view, {"PieceRate": 2.0})
    frozen = signal.value
    for _ in range(10):
        signal.next(1.0, view, {"PieceRate": 0.0})
    assert signal.value == frozen


def test_counter_holds_its_reading_when_the_named_rate_sibling_is_absent():
    signal = build_signal(
        SignalSpec(name="Pieces", shape="counter", precision=0, params={"rate": "Missing", "initial": 5.0}),
        "t/Pieces",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(5.0)


def test_counter_starts_from_initial():
    signal = build_signal(
        SignalSpec(name="RunHours", shape="counter", precision=2, params={"rate": 1.0, "initial": 12345.0}),
        "t/RH",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(12346.0)


def test_counter_wraps_at_rollover():
    """A real 6-digit register wraps; a consumer computing deltas must cope with it."""
    signal = build_signal(
        SignalSpec(name="Energy", shape="counter", precision=1, params={"rate": 10.0, "initial": 95.0, "rollover": 100.0}),
        "t/E",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(5.0)
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(15.0)


def test_window_agg_reports_the_max_over_its_window():
    signal = build_signal(
        SignalSpec(name="PeakDemand", shape="window_agg", params={"source": "ActivePower", "window_s": 5.0, "agg": "max"}),
        "t/Peak",
        7,
    )
    view = FakeView()
    for power in (100.0, 300.0, 200.0, 150.0, 120.0):
        signal.next(1.0, view, {"ActivePower": power})
    assert signal.value == pytest.approx(300.0)
    for power in (100.0, 100.0, 100.0, 100.0, 100.0):
        signal.next(1.0, view, {"ActivePower": power})
    assert signal.value == pytest.approx(100.0), "the 300 kW sample must age out of the window"


def test_window_agg_mean():
    signal = build_signal(
        SignalSpec(name="AvgT", shape="window_agg", params={"source": "T", "window_s": 4.0, "agg": "mean"}),
        "t/AvgT",
        7,
    )
    for value in (10.0, 20.0, 30.0, 40.0):
        signal.next(1.0, FakeView(), {"T": value})
    assert signal.value == pytest.approx(25.0)


def test_window_agg_missing_source_is_none_not_a_crash():
    signal = build_signal(
        SignalSpec(name="AvgT", shape="window_agg", params={"source": "absent", "agg": "mean"}),
        "t/AvgT",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) is None


def test_window_agg_rejects_an_unknown_aggregate_at_construction():
    with pytest.raises(ValueError, match="medain"):
        build_signal(
            SignalSpec(name="AvgT", shape="window_agg", params={"source": "T", "agg": "medain"}),
            "t/AvgT",
            7,
        )


def test_stepped_holds_its_value_for_the_dwell_time():
    signal = build_signal(
        SignalSpec(name="Mode", shape="stepped", params={"choices": ["Auto", "Manual", "Local"], "dwell_s": 10.0}),
        "t/Mode",
        7,
    )
    values = [signal.next(1.0, None, {}) for _ in range(10)]
    assert len(set(values)) == 1, "must not change within one dwell period"


def test_stepped_only_ever_emits_declared_choices():
    signal = build_signal(
        SignalSpec(name="Mode", shape="stepped", params={"choices": ["Auto", "Manual"], "dwell_s": 1.0}),
        "t/Mode",
        7,
    )
    assert {signal.next(1.0, None, {}) for _ in range(200)} <= {"Auto", "Manual"}


def test_stepped_respects_weights():
    signal = build_signal(
        SignalSpec(
            name="Mode",
            shape="stepped",
            params={"choices": ["Auto", "Manual"], "weights": [99.0, 1.0], "dwell_s": 1.0},
        ),
        "t/Mode",
        7,
    )
    values = [signal.next(1.0, None, {}) for _ in range(1000)]
    assert values.count("Auto") > values.count("Manual") * 10


def test_stepped_reads_a_ctx_source_path():
    """A `stepped` signal with `source` mirrors the plant rather than inventing a state.

    The nested `line.state` here is a deliberately arbitrary path, proving `resolve_ctx_path`
    walks whatever depth it is given. DeviceView is flat (`ctx.wtp.*`); this fixture is not.
    """
    signal = build_signal(
        SignalSpec(name="Mode", shape="stepped", params={"source": "line.state"}),
        "t/State",
        7,
    )
    view = FakeView(line=FakeLine(state="Running"))
    assert signal.next(1.0, view, {}) == "Running"
    view.line.state = "Backwash"
    assert signal.next(1.0, view, {}) == "Backwash", "a sourced stepped signal follows immediately"


def test_stepped_translates_through_map():
    signal = build_signal(
        SignalSpec(
            name="ModeCode",
            shape="stepped",
            params={"source": "ctx.line.state", "map": {"Idle": 1, "Running": 6}},
        ),
        "t/Code",
        7,
    )
    assert signal.next(1.0, FakeView(line=FakeLine(state="Running")), {}) == 6
    assert signal.next(1.0, FakeView(line=FakeLine(state="Idle")), {}) == 1


def test_stepped_passes_an_unmapped_value_through_unchanged():
    signal = build_signal(
        SignalSpec(name="Code", shape="stepped", params={"source": "line.state", "map": {"Idle": 1}}),
        "t/Code",
        7,
    )
    assert signal.next(1.0, FakeView(line=FakeLine(state="Faulted")), {}) == "Faulted"


def test_stepped_without_source_or_choices_names_the_signal():
    with pytest.raises(ValueError, match="TapPosition"):
        build_signal(SignalSpec(name="TapPosition", shape="stepped"), "t/Tap", 7)


def test_resolve_ctx_path_tolerates_a_missing_hop():
    assert resolve_ctx_path(FakeView(line=FakeLine(state="Idle")), "line.state") == "Idle"
    assert resolve_ctx_path(FakeView(line=None), "line.state") is None
    assert resolve_ctx_path(None, "line.state") is None
    assert resolve_ctx_path(FakeView(), "no_such_field") is None


def test_bernoulli_event_fires_at_roughly_the_declared_rate():
    """`p` is per tick, and the PlantClock ticks every second: 1/3600 is once an hour."""
    signal = build_signal(
        SignalSpec(name="DetectorFault", shape="bernoulli_event", params={"p": 1.0 / 3600.0, "choices": ["Fault"]}),
        "t/DF",
        7,
    )
    fires = sum(1 for _ in range(360_000) if signal.next(1.0, None, {}) == "Fault")
    assert 70 <= fires <= 130, f"expected ~100 fires in 100 simulated hours, got {fires}"


def test_bernoulli_event_publishes_nothing_on_a_quiet_tick():
    signal = build_signal(
        SignalSpec(name="Door", shape="bernoulli_event", params={"p": 0.0001, "choices": ["Opened", "Closed"]}),
        "t/Door",
        7,
    )
    values = [signal.next(1.0, None, {}) for _ in range(1000)]
    assert values.count(None) > 990
    assert set(values) <= {None, "Opened", "Closed"}


def test_bernoulli_event_status_marks_the_tick_it_fires():
    signal = build_signal(
        SignalSpec(name="Trip", shape="bernoulli_event", params={"p": 1.0, "choices": ["Tripped"]}),
        "t/Trip",
        7,
    )
    assert signal.next(1.0, None, {}) == "Tripped"
    assert signal.status() == "Alarm"


def test_stepped_reports_normal_status():
    signal = build_signal(SignalSpec(name="Mode", shape="stepped", params={"choices": ["Auto"]}), "t/Mode", 7)
    signal.next(1.0, None, {})
    assert signal.status() == "Normal"


def test_derived_reads_siblings():
    signal = build_signal(
        SignalSpec(name="ApparentPower", shape="derived", precision=1, params={"expr": "ActivePower / PowerFactor"}),
        "t/S",
        7,
    )
    assert signal.next(1.0, None, {"ActivePower": 450.0, "PowerFactor": 0.9}) == pytest.approx(500.0)


def test_derived_reads_plant_context_through_ctx():
    signal = build_signal(
        SignalSpec(name="ChillerLoad", shape="derived", precision=2, params={"expr": "ctx.ambient_temp_c * 3.0"}),
        "t/CL",
        7,
    )
    assert signal.next(1.0, FakeView(ambient_temp_c=30.0), {}) == pytest.approx(90.0)


def test_derived_params_supply_constants():
    signal = build_signal(
        SignalSpec(name="Power", shape="derived", precision=2, params={"expr": "flow * head * k", "k": 0.0027}),
        "t/P",
        7,
    )
    assert signal.next(1.0, None, {"flow": 100.0, "head": 40.0}) == pytest.approx(10.8)


def test_derived_siblings_override_params():
    signal = build_signal(
        SignalSpec(name="X", shape="derived", precision=2, params={"expr": "a", "a": 1.0}),
        "t/X",
        7,
    )
    assert signal.next(1.0, None, {"a": 9.0}) == pytest.approx(9.0)


def test_derived_without_expr_names_the_signal():
    with pytest.raises(ValueError, match="ChillerLoad"):
        build_signal(SignalSpec(name="ChillerLoad", shape="derived"), "t/CL", 7)


def test_derived_missing_sibling_yields_none_not_a_crash():
    signal = build_signal(SignalSpec(name="X", shape="derived", params={"expr": "absent * 2"}), "t/X", 7)
    assert signal.next(1.0, None, {}) is None


def test_counter_rate_accepts_an_expression():
    """Spec 7.3's EnergyTotal, verbatim: 450 kW integrated for an hour is 450 kWh."""
    signal = build_signal(
        SignalSpec(
            name="EnergyTotal",
            shape="counter",
            unit="kWh",
            precision=3,
            params={"rate": "ActivePower / 3600.0", "initial": 84000.0},
        ),
        "t/E",
        7,
    )
    for _ in range(3600):
        signal.next(1.0, FakeView(), {"ActivePower": 450.0})
    assert signal.value == pytest.approx(84450.0, abs=0.01)


def test_counter_rate_expression_can_read_ctx_and_params():
    signal = build_signal(
        SignalSpec(
            name="GoodCount",
            shape="counter",
            precision=0,
            params={"rate": "ctx.line.production_rate * per_second", "per_second": 3.0},
        ),
        "t/Good",
        7,
    )
    view = FakeView(line=FakeLine(production_rate=0.5))
    for _ in range(10):
        signal.next(1.0, view, {})
    assert signal.value == pytest.approx(15.0)
    view.line.production_rate = 0.0
    for _ in range(10):
        signal.next(1.0, view, {})
    assert signal.value == pytest.approx(15.0), "a held line must not advance the register"


def test_dependencies_are_found_for_every_shape_that_reads_siblings():
    assert signal_dependencies(SignalSpec(name="a", shape="derived", params={"expr": "b + c"})) == frozenset({"b", "c"})
    assert signal_dependencies(SignalSpec(name="a", shape="counter", params={"rate": "Power"})) == frozenset({"Power"})
    assert signal_dependencies(SignalSpec(name="a", shape="counter", params={"rate": "Power / 3600.0"})) == frozenset(
        {"Power"}
    )
    assert signal_dependencies(SignalSpec(name="a", shape="counter", params={"rate": 2.0})) == frozenset()
    assert signal_dependencies(SignalSpec(name="a", shape="window_agg", params={"source": "T"})) == frozenset({"T"})
    assert signal_dependencies(SignalSpec(name="a")) == frozenset()


def test_a_stepped_ctx_source_is_not_a_sibling_dependency():
    """`line.state` is a ctx path, so ordering must not look for a sibling called `line`."""
    assert signal_dependencies(SignalSpec(name="a", shape="stepped", params={"source": "line.state"})) == frozenset()


def test_ctx_and_dt_are_not_dependencies():
    deps = signal_dependencies(SignalSpec(name="a", shape="derived", params={"expr": "ctx.shift + dt + b"}))
    assert deps == frozenset({"b"})


def test_order_signals_puts_inputs_first():
    specs = [
        SignalSpec(name="Energy", shape="counter", params={"rate": "ApparentPower / 3600.0"}),
        SignalSpec(name="ApparentPower", shape="derived", params={"expr": "ActivePower / pf", "pf": 0.9}),
        SignalSpec(name="ActivePower", shape="ou_walk", params={"mean": 400.0}),
    ]
    assert [spec.name for spec in order_signals(specs)] == ["ActivePower", "ApparentPower", "Energy"]


def test_order_signals_is_stable_for_independent_signals():
    specs = [SignalSpec(name=name) for name in ("c", "a", "b")]
    assert [spec.name for spec in order_signals(specs)] == ["c", "a", "b"]


def test_order_signals_rejects_a_cycle_and_names_it():
    specs = [
        SignalSpec(name="a", shape="derived", params={"expr": "b + 1"}),
        SignalSpec(name="b", shape="derived", params={"expr": "a + 1"}),
    ]
    with pytest.raises(ValueError, match="cycle") as exc:
        order_signals(specs)
    assert "a" in str(exc.value) and "b" in str(exc.value)


def test_order_signals_rejects_self_reference():
    with pytest.raises(ValueError, match="cycle"):
        order_signals([SignalSpec(name="a", shape="derived", params={"expr": "a + 1"})])


def test_order_signals_ignores_references_to_signals_on_other_devices():
    """An unresolved name is not a dependency here; it fails at evaluation with None."""
    specs = [SignalSpec(name="a", shape="derived", params={"expr": "elsewhere * 2"})]
    assert [spec.name for spec in order_signals(specs)] == ["a"]
