import random

import pytest

from uns_simulator.plant import LL_PCT, RAW_PUMP_M3H, WTPProcess


def _wtp() -> WTPProcess:
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.v101.set_open(True)
    wtp.v201.set_open(True)
    wtp.v202.set_open(True)
    wtp.v301.set_open(True)
    wtp.p101.running = True
    wtp.p101.cmd_start = True
    wtp.f101.in_service = True
    wtp.p201.running = True
    wtp.p201.run_cmd = True
    wtp.p201.speed_sp = 87.5
    wtp.p201.speed_pv = 87.5
    return wtp


def test_tanks_start_half_full():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    assert wtp.t101.level_pct == pytest.approx(50.0)
    assert wtp.t101.volume_m3 == pytest.approx(125.0)
    assert wtp.b101.level_pct == pytest.approx(50.0)
    assert wtp.t201.level_pct == pytest.approx(50.0)
    assert wtp.b101.pv_m == pytest.approx(1.5)


def test_closed_v101_stops_inlet_and_t101_does_not_fill():
    wtp = _wtp()
    wtp.v101.set_open(False)
    before = wtp.t101.volume_m3
    for _ in range(30):
        wtp.advance_hydraulics(1.0)
    assert wtp.inlet_m3h == pytest.approx(0.0, abs=0.5)
    assert wtp.t101.volume_m3 <= before + 0.01


def test_open_inlet_and_running_raw_pump_fill_t101_when_outlet_is_blocked():
    wtp = _wtp()
    wtp.v201.set_open(False)
    wtp.v202.set_open(False)
    before = wtp.t101.volume_m3
    for _ in range(20):
        wtp.advance_hydraulics(1.0)
    assert wtp.inlet_m3h == pytest.approx(RAW_PUMP_M3H, abs=5.0)
    assert wtp.t101.volume_m3 > before


def test_both_distribution_pumps_stopped_drops_ft201_and_pt201():
    wtp = _wtp()
    for _ in range(20):
        wtp.advance_hydraulics(1.0)
    flowing = wtp.ft201_m3h
    pressured = wtp.pt201
    wtp.p201.running = False
    wtp.p202.running = False
    wtp.p201.speed_pv = 0.0
    wtp.p202.speed_pv = 0.0
    for _ in range(40):
        wtp.advance_hydraulics(1.0)
    assert flowing > 10.0
    assert wtp.ft201_m3h < flowing * 0.2
    assert wtp.pt201 < pressured
    assert wtp.pt201 == pytest.approx(0.2 + 0.015 * wtp.t201.level_pct, abs=0.3)


def test_v301_closed_stops_distribution_flow():
    wtp = _wtp()
    for _ in range(15):
        wtp.advance_hydraulics(1.0)
    wtp.v301.set_open(False)
    for _ in range(40):
        wtp.advance_hydraulics(1.0)
    assert wtp.ft201_m3h == pytest.approx(0.0, abs=1.0)


def test_backwash_isolates_filter_and_stops_ft101():
    wtp = _wtp()
    wtp.f101.in_service = False
    wtp.f101.backwash = True
    wtp.v201.set_open(False)
    wtp.v202.set_open(False)
    for _ in range(20):
        wtp.advance_hydraulics(1.0)
    assert wtp.ft101_m3h == pytest.approx(0.0, abs=1.0)


def test_level_interlock_stops_outlet_at_ll():
    wtp = _wtp()
    wtp.t101.volume_m3 = wtp.t101.capacity_m3 * (LL_PCT / 100.0) * 0.5
    for _ in range(10):
        wtp.advance_hydraulics(1.0)
    assert wtp.ft101_m3h == pytest.approx(0.0, abs=1.0)


def test_valve_set_open_counts_a_cycle():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.v101.set_open(True)
    wtp.v101.set_open(False)
    assert wtp.v101.cycle_count == 2
    assert wtp.v101.position == 0.0
    assert wtp.v101.close_fb is True
