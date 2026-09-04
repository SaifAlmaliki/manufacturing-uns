"""The control API's HTTP surface (spec 5).

Driven by a fake simulator on purpose. api.py is a translation layer — one call in, one
status code out — and these tests are about the translation. The read model behind it is
tested against the real simulator in test_simulator.py.
"""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from uns_simulator.api import create_app
from uns_simulator.simulator import ReconfigurationError

STATUS = {
    "run_state": "stopped",
    "profile": "wtp",
    "seed": 20260831,
    "device_count": 2,
    "signal_count": 5,
    "uptime_s": 0.0,
    "broker_connected": False,
    "msg_per_sec": {"fast": 0.0, "process": 0.0, "energy": 0.0, "status": 0.0, "meter": 0.0, "lab": 0.0, "event": 0.0},
    "published_total": 0,
    "failed_total": 0,
    "overrides_active": False,
    "tiers": {"fast": 6.0, "process": 30.0, "energy": 90.0, "status": 180.0, "meter": 5400.0, "lab": 10800.0, "event": 0.0},
    "families": {
        "wtp": True,
    },
    "per_tier": {"process": 5},
    "tick_count": 0,
}


class FakeSimulator:
    """Records what the routes asked for, and can be told to fail or to be slow."""

    def __init__(self, *, slow: bool = False) -> None:
        self.lock = asyncio.Lock()
        self.slow = slow
        self.calls: list[tuple] = []
        self.depth = 0
        self.overlaps = 0
        self.reject: ReconfigurationError | None = None
        self.unknown_device = False

    def health_body(self):
        return {"status": "ok", "uptime_s": 1.5, "git_hash": "dev", "version": "0.9.38"}

    def status(self):
        return dict(STATUS)

    def config_snapshot(self):
        return {"profile": "wtp", "available_profiles": ["wtp"], "devices": []}

    def plant_snapshot(self):
        return {
            "enterprise": "AcmeWater",
            "site": "Site1",
            "mode": "Running",
            "filter_mode": "InService",
            "duty_raw_pump": "P101",
            "lead_dist_pump": "P201",
            "tanks": {"T101": {"level_pct": 51.2, "volume_m3": 128.0, "capacity_m3": 250.0}},
            "flows_m3h": {"inlet": 80.0, "FT101": 78.4, "FT201": 69.8},
            "pressures_barg": {"PT101": 2.1, "PT201": 3.8},
        }

    def device_snapshots(self):
        return [{"id": "main-meter", "equipment": "MainMeter"}]

    def signal_snapshot(self, device_id):
        if self.unknown_device:
            raise KeyError(device_id)
        return {"device_id": device_id, "signals": [{"name": "ActivePower"}]}

    def diagnostics(self):
        return {"report": {"devices": 2}, "failing_devices": [], "sample_topics": []}

    async def _serialised(self, name, *args):
        self.calls.append((name, *args))
        self.depth += 1
        self.overlaps += max(0, self.depth - 1)
        if self.slow:
            await asyncio.sleep(0.02)
        self.depth -= 1
        if self.reject is not None:
            raise self.reject

    async def start(self):
        await self._serialised("start")

    async def stop(self):
        await self._serialised("stop")

    async def pause(self):
        await self._serialised("pause")

    async def resume(self):
        await self._serialised("resume")

    async def apply_profile(self, name, seed=None):
        if self.reject is None and name != "wtp":
            raise ReconfigurationError("profile", f"unknown profile {name!r} (known: wtp)")
        await self._serialised("apply_profile", name, seed)

    async def apply_tiers(self, intervals):
        await self._serialised("apply_tiers", dict(intervals))

    async def apply_families(self, flags):
        await self._serialised("apply_families", dict(flags))

    async def set_device_enabled(self, device_id, enabled):
        self.calls.append(("set_device_enabled", device_id, enabled))
        if self.unknown_device:
            raise KeyError(device_id)


def _client(sim=None, token=None) -> TestClient:
    return TestClient(create_app(sim if sim is not None else FakeSimulator(), token=token))


def test_health_is_served_under_the_simulator_prefix():
    """The prefix is not decoration: nginx and the Vite dev server both proxy on it,
    and an unprefixed route would be invisible from the browser."""
    response = _client().get("/simulator/health")

    assert response.status_code == 200
    assert set(response.json()) == {"status", "uptime_s", "git_hash", "version"}


def test_status_is_returned_verbatim():
    response = _client().get("/simulator/status")

    assert response.status_code == 200
    assert response.json() == STATUS


@pytest.mark.parametrize("path", ["/simulator/config", "/simulator/plant", "/simulator/diagnostics"])
def test_the_remaining_reads_answer(path):
    assert _client().get(path).status_code == 200


def test_plant_is_the_flat_wtp_body():
    body = _client().get("/simulator/plant").json()

    assert body["enterprise"] == "AcmeWater"
    assert "T101" in body["tanks"]
    assert "sites" not in body


def test_devices_are_wrapped_in_an_envelope():
    """An envelope rather than a bare array, so a field can be added later without every
    consumer's type changing shape."""
    body = _client().get("/simulator/devices").json()

    assert list(body) == ["devices"]
    assert body["devices"][0]["id"] == "main-meter"


def test_signals_are_returned_for_a_named_device():
    body = _client().get("/simulator/devices/main-meter/signals").json()

    assert body["device_id"] == "main-meter"
    assert body["signals"][0]["name"] == "ActivePower"


def test_an_unknown_device_is_a_404_not_an_empty_list():
    sim = FakeSimulator()
    sim.unknown_device = True

    response = _client(sim).get("/simulator/devices/nope/signals")

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_the_openapi_document_is_served():
    assert _client().get("/simulator/openapi.json").status_code == 200


def test_without_a_configured_token_every_route_is_open():
    assert _client().get("/simulator/status").status_code == 200


def test_a_configured_token_is_required_on_every_route():
    """Including /health. The simulator has no Docker healthcheck to exempt, and one
    exempt route is how a shared secret becomes decorative."""
    client = _client(token="s3cret")

    assert client.get("/simulator/status").status_code == 401
    assert client.get("/simulator/health").status_code == 401
    assert client.get("/simulator/status", headers={"X-Simulator-Token": "s3cret"}).status_code == 200


def test_a_wrong_token_is_a_401():
    client = _client(token="s3cret")
    assert client.get("/simulator/status", headers={"X-Simulator-Token": "wrong"}).status_code == 401


@pytest.mark.asyncio
async def test_the_app_can_be_driven_without_a_server():
    """The transport Task 7's concurrency test needs; proven here on a read."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(FakeSimulator())), base_url="http://sim"
    ) as client:
        response = await client.get("/simulator/status")

    assert response.status_code == 200


@pytest.mark.parametrize("action", ["start", "stop", "pause", "resume"])
def test_each_run_action_reaches_the_simulator_and_returns_the_new_status(action):
    sim = FakeSimulator()
    response = _client(sim).post("/simulator/run", json={"action": action})

    assert response.status_code == 200
    assert response.json() == STATUS
    assert sim.calls == [(action,)]


def test_an_unknown_run_action_is_rejected_before_anything_happens():
    sim = FakeSimulator()
    response = _client(sim).post("/simulator/run", json={"action": "explode"})

    assert response.status_code == 422
    assert sim.calls == []


def test_a_profile_switch_passes_the_optional_seed_through():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/profile", json={"profile": "wtp", "seed": 42})

    assert response.status_code == 200
    assert sim.calls == [("apply_profile", "wtp", 42)]


def test_a_profile_switch_says_that_the_counters_were_reset():
    """Spec 5.2. Without it a console keeps subtracting from a total that just went to
    zero and renders negative throughput."""
    body = _client().put("/simulator/profile", json={"profile": "wtp"}).json()

    assert body["counters_reset"] is True


def test_unknown_profile_is_422_profile():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/profile", json={"profile": "small"})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "profile"


def test_a_refused_profile_switch_is_a_422_naming_the_field():
    sim = FakeSimulator()
    sim.reject = ReconfigurationError("profile", "unknown profile 'huge' (known: wtp)")

    response = _client(sim).put("/simulator/profile", json={"profile": "huge"})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "profile"
    assert "huge" in response.json()["detail"]["message"]


def test_an_unexpected_body_key_is_refused():
    """extra="forbid": a misspelled key that is silently dropped is a control that
    appears to work and does nothing."""
    response = _client().put("/simulator/profile", json={"profile": "wtp", "sedd": 42})

    assert response.status_code == 422


def test_tiers_accepts_a_partial_body_and_forwards_only_what_was_sent():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"process": 12.5})

    assert response.status_code == 200
    assert sim.calls == [("apply_tiers", {"process": 12.5})]


def test_tiers_accepts_the_event_tier_too():
    """Spec 5.2's body names six tiers; plan A's TIER_DEFAULTS has seven. Excluding
    `event` would leave one tier permanently unreachable."""
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"event": 0.0})

    assert response.status_code == 200
    assert sim.calls == [("apply_tiers", {"event": 0.0})]


def test_an_unknown_tier_is_a_422_that_names_it():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"turbo": 1.0})

    assert response.status_code == 422
    assert any("turbo" in str(item["loc"]) for item in response.json()["detail"])
    assert sim.calls == []


def test_a_negative_tier_interval_is_a_422():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/tiers", json={"fast": -1.0})

    assert response.status_code == 422
    assert sim.calls == []


def test_families_forwards_only_the_flags_that_were_sent():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/families", json={"wtp": False})

    assert response.status_code == 200
    assert sim.calls == [("apply_families", {"wtp": False})]


def test_an_unknown_family_is_a_422():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/families", json={"nonsense": True})

    assert response.status_code == 422
    assert sim.calls == []


def test_one_device_can_be_disabled_over_http():
    sim = FakeSimulator()
    response = _client(sim).put("/simulator/devices/main-meter", json={"enabled": False})

    assert response.status_code == 200
    assert sim.calls == [("set_device_enabled", "main-meter", False)]


def test_disabling_an_unknown_device_is_a_404():
    sim = FakeSimulator()
    sim.unknown_device = True

    response = _client(sim).put("/simulator/devices/nope", json={"enabled": False})

    assert response.status_code == 404


def test_a_write_with_no_body_is_a_422_rather_than_a_crash():
    assert _client().put("/simulator/devices/main-meter", json={}).status_code == 422


@pytest.mark.asyncio
async def test_concurrent_writes_are_serialised():
    """Two profile switches arriving together must not rebuild the device list from two
    directions at once. The lock is the only thing preventing it."""
    sim = FakeSimulator(slow=True)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(sim)), base_url="http://sim") as client:
        responses = await asyncio.gather(
            client.put("/simulator/profile", json={"profile": "wtp"}),
            client.put("/simulator/profile", json={"profile": "wtp", "seed": 1}),
        )

    assert [r.status_code for r in responses] == [200, 200]
    assert len(sim.calls) == 2
    assert sim.overlaps == 0
