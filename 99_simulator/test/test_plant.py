import random

from uns_simulator.plant import DeviceView, PlantClock, PlantContext, WTPProcess


def test_device_view_exposes_wtp():
    ctx = PlantContext(global_seed=7)
    ctx.add_site("Site1")
    ctx.tick(1.0)
    view = DeviceView(ctx, "Site1")
    assert view.wtp is ctx.sites["Site1"].wtp
    assert view.wtp.p101.running is True


def test_context_tick_emits_train_events_on_duty_rotate():
    ctx = PlantContext(global_seed=7)
    ctx.add_site("Site1")
    ctx.sites["Site1"].wtp.fault_p = 0.0
    seen = []
    for _ in range(901):
        seen.extend(ctx.tick(1.0))
    assert ("Site1", "Train1", "DutyP102") in seen


def test_clock_forwards_transitions():
    ctx = PlantContext(global_seed=7)
    ctx.add_site("Site1")
    ctx.sites["Site1"].wtp.fault_p = 0.0
    clock = PlantClock(ctx)
    seen = []
    clock.on_transition(lambda site, line, state: seen.append((site, line, state)))
    for _ in range(901):
        clock.advance()
    assert any(event[2].startswith("Duty") for event in seen)


def test_context_snapshot_matches_control_api_shape():
    ctx = PlantContext(global_seed=7)
    ctx.enterprise = "AcmeWater"
    ctx.add_site("Site1")
    ctx.tick(1.0)
    snap = ctx.snapshot()
    assert snap["enterprise"] == "AcmeWater"
    assert snap["site"] == "Site1"
    assert "tanks" in snap
    assert "sites" not in snap
