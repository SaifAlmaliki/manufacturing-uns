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


def _latch_fault(device) -> None:
    """Pin a latched fault without a multi-hour soak at fault_p=1/3600."""
    device.fault = True
    device.running = False
    device.fault_age_s = 0.0
    device.reset_fault = False
    device.reset_age_s = 0.0


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


def test_tick_starts_in_running_with_one_duty_raw_pump():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    assert wtp.mode == "Running"
    running = [name for name in ("p101", "p102", "p103") if getattr(wtp, name).running]
    assert running == ["p101"]
    assert wtp.v101.open_fb is True
    assert wtp.p201.running is True
    assert wtp.p201.speed_sp == pytest.approx(87.5)
    assert wtp.p202.running is False
    assert wtp.p202.speed_sp == 0.0
    for _ in range(20):
        wtp.tick(1.0)
    assert wtp.dp101.running is True


def test_duty_rotates_p101_to_p102_after_900s():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    events = []
    for _ in range(901):
        events.extend(wtp.tick(1.0))
    assert wtp.p101.running is False
    assert wtp.p102.running is True
    assert "DutyP102" in events


def test_backwash_closes_filter_valves_and_returns():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    events = []
    for _ in range(1801):
        events.extend(wtp.tick(1.0))
    assert "Backwash" in events
    assert wtp.mode == "Backwash"
    assert wtp.f101.backwash is True
    assert wtp.v201.open_fb is False
    assert wtp.ft101_m3h == pytest.approx(0.0, abs=2.0)
    for _ in range(45):
        events.extend(wtp.tick(1.0))
    assert wtp.mode == "Running"
    assert "Running" in events
    assert wtp.v201.open_fb is True


def test_fault_on_duty_pump_starts_the_next():
    wtp = WTPProcess(random.Random(0), fault_p=1.0)
    wtp.tick(1.0)
    assert wtp.p101.fault is True
    assert wtp.p101.running is False
    assert wtp.p102.running is True


def test_cmd_start_stays_true_while_sequencer_wants_the_pump_even_if_faulted():
    wtp = WTPProcess(random.Random(0), fault_p=1.0)
    wtp.tick(1.0)
    assert wtp.p101.fault is True
    assert wtp.p101.running is False
    assert wtp.p101.cmd_start is True


def test_snapshot_has_spec_keys():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    snap = wtp.snapshot()
    assert snap["mode"] == "Running"
    assert snap["filter_mode"] == "InService"
    assert snap["duty_raw_pump"] == "P101"
    assert snap["lead_dist_pump"] == "P201"
    assert set(snap["tanks"]) == {"T101", "B101", "T201"}
    assert set(snap["flows_m3h"]) == {"inlet", "FT101", "FT201"}
    assert set(snap["pressures_barg"]) == {"PT101", "PT201"}


def test_fault_clears_after_120s_with_reset_pulse():
    wtp = WTPProcess(random.Random(0), fault_p=1.0)
    wtp.tick(1.0)
    assert wtp.p101.fault is True
    for _ in range(120):
        wtp.tick(1.0)
    assert wtp.p101.fault is True
    wtp.tick(1.0)
    assert wtp.p101.fault is False
    assert wtp.p101.reset_fault is True
    for _ in range(30):
        wtp.tick(1.0)
    assert wtp.p101.reset_fault is False


def test_ait101_stays_in_band():
    wtp = WTPProcess(random.Random(1), fault_p=0.0)
    values = []
    for _ in range(500):
        wtp.tick(1.0)
        values.append(wtp.ait101)
    assert min(values) >= 6.5
    assert max(values) <= 8.5


def test_flow_totalizers_start_at_zero():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    assert wtp.ft101_total_m3 == pytest.approx(0.0)
    assert wtp.ft201_total_m3 == pytest.approx(0.0)
    assert wtp.flow_reset is False


def test_flow_totalizers_integrate_rate_times_dt():
    wtp = _wtp()
    expected_101 = 0.0
    expected_201 = 0.0
    for _ in range(30):
        wtp.advance_hydraulics(1.0)
        expected_101 += wtp.ft101_m3h / 3600.0
        expected_201 += wtp.ft201_m3h / 3600.0
    assert wtp.ft101_total_m3 == pytest.approx(expected_101)
    assert wtp.ft201_total_m3 == pytest.approx(expected_201)
    assert wtp.ft101_total_m3 > 0.0
    assert wtp.ft201_total_m3 > 0.0


def test_p201_fault_failsovers_to_p202_and_clears_lead_commands():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    _latch_fault(wtp.p201)
    wtp.tick(1.0)
    assert wtp.p201.running is False
    assert wtp.p201.run_cmd is False
    assert wtp.p201.speed_sp == 0.0
    assert wtp.p202.running is True
    assert wtp.p202.run_cmd is True
    assert wtp.p202.speed_sp == pytest.approx(87.5)
    assert wtp.lead_dist_pump == "P202"
    for _ in range(40):
        wtp.tick(1.0)
    assert wtp.ft201_m3h > 10.0
    assert wtp.lead_dist_pump == "P202"


def test_p202_fault_while_acting_lead_restores_healthy_p201():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    _latch_fault(wtp.p201)
    wtp.tick(1.0)
    assert wtp.lead_dist_pump == "P202"
    wtp.p201.fault = False
    _latch_fault(wtp.p202)
    wtp.tick(1.0)
    assert wtp.p201.fault is False
    assert wtp.p201.running is True
    assert wtp.p201.run_cmd is True
    assert wtp.p201.speed_sp == pytest.approx(87.5)
    assert wtp.p202.running is False
    assert wtp.p202.run_cmd is False
    assert wtp.p202.speed_sp == 0.0
    assert wtp.lead_dist_pump == "P201"


def test_p201_recovers_as_lead_after_fault_hold_expires():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    _latch_fault(wtp.p201)
    wtp.tick(1.0)
    assert wtp.p202.running is True
    assert wtp.lead_dist_pump == "P202"
    # Latch is already live when this tick starts, so age is 1 afterwards.
    # FAULT_CLEAR_S is 120 and the timer uses `>`, so age 120 is still latched.
    for _ in range(119):
        wtp.tick(1.0)
    assert wtp.p201.fault is True
    wtp.tick(1.0)
    assert wtp.p201.fault is False
    assert wtp.p201.running is True
    assert wtp.p201.run_cmd is True
    assert wtp.p201.speed_sp == pytest.approx(87.5)
    assert wtp.p202.running is False
    assert wtp.p202.run_cmd is False
    assert wtp.p202.speed_sp == 0.0
    assert wtp.lead_dist_pump == "P201"


def test_both_stopped_healthy_vfds_restart_preferring_p201():
    wtp = WTPProcess(random.Random(0), fault_p=0.0)
    wtp.tick(1.0)
    wtp.p201.running = False
    wtp.p201.run_cmd = False
    wtp.p201.speed_sp = 0.0
    wtp.p202.running = False
    wtp.p202.run_cmd = False
    wtp.p202.speed_sp = 0.0
    wtp.tick(1.0)
    assert wtp.p201.running is True
    assert wtp.p201.run_cmd is True
    assert wtp.p201.speed_sp == pytest.approx(87.5)
    assert wtp.p202.running is False
    assert wtp.lead_dist_pump == "P201"


def test_cleared_raw_duty_drops_cmd_start_once_it_is_no_longer_wanted():
    wtp = WTPProcess(random.Random(0), fault_p=1.0)
    wtp.tick(1.0)
    assert wtp.p101.fault is True
    assert wtp.p101.cmd_start is True
    wtp.fault_p = 0.0
    for _ in range(121):
        wtp.tick(1.0)
    assert wtp.p101.fault is False
    assert wtp.duty_raw_pump == "P102"
    assert wtp.p101.running is False
    assert wtp.p101.cmd_start is False
