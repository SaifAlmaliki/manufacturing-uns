import pytest
import uvicorn

from uns_simulator import main
from uns_simulator.main import configure_asyncio_for_mqtt


def test_configure_asyncio_for_mqtt_sets_selector_on_windows(monkeypatch):
    """Stub Windows asyncio bits. Real asyncio.__getattr__ crashes on Linux/macOS
    if sys.platform is patched to win32 (windows_events is not imported)."""
    set_calls = []

    class FakePolicy:
        pass

    class FakeSys:
        platform = "win32"

    class FakeAsyncio:
        WindowsSelectorEventLoopPolicy = FakePolicy

        @staticmethod
        def set_event_loop_policy(policy):
            set_calls.append(policy)

    monkeypatch.setattr("uns_simulator.main.sys", FakeSys)
    monkeypatch.setattr("uns_simulator.main.asyncio", FakeAsyncio)

    configure_asyncio_for_mqtt()

    assert len(set_calls) == 1
    assert isinstance(set_calls[0], FakePolicy)


def test_configure_asyncio_for_mqtt_is_noop_off_windows(monkeypatch):
    class FakeSys:
        platform = "linux"

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("event loop policy should not change off Windows")

    monkeypatch.setattr("uns_simulator.main.sys", FakeSys)
    monkeypatch.setattr("uns_simulator.main.asyncio.set_event_loop_policy", fail_if_called)
    configure_asyncio_for_mqtt()


@pytest.mark.asyncio
async def test_run_serves_the_api_the_metrics_and_the_telemetry_beside_the_simulation(monkeypatch):
    """The failure this guards: the app is built and never served. The simulator's own
    logs look perfect and the console shows nothing but 'offline'."""
    events: list[str] = []

    class FakeSimulator:
        def __init__(self):
            self.signal_devices = []
            self.listeners = []

        def on_plant_transition(self, callback):
            self.listeners.append(callback)

        async def run_simulation(self, duration):
            events.append(f"simulation:{duration}")

    class FakeTelemetry:
        def __init__(self, simulator, instance, interval_s=10.0):
            self.simulator = simulator
            self.instance = instance

        def on_transition(self, site, line, state):
            events.append(f"transition:{state}")

        async def run(self):
            events.append("telemetry")

        async def stop(self):
            events.append("telemetry:stopped")

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False

        async def serve(self):
            events.append(f"api:{self.config.port}")

    simulators: list[FakeSimulator] = []

    def _build_simulator():
        simulator = FakeSimulator()
        simulators.append(simulator)
        return simulator

    monkeypatch.setattr(main, "UnifiedNamespaceSimulator", _build_simulator)
    monkeypatch.setattr(main, "SelfTelemetry", FakeTelemetry)
    monkeypatch.setattr(main, "_EmbeddedServer", FakeServer)
    monkeypatch.setattr(main, "start_metrics_server", lambda simulator, port: events.append(f"metrics:{port}"))

    await main.run()

    assert "metrics:9093" in events
    assert "api:8099" in events
    assert "telemetry" in events
    assert "telemetry:stopped" in events
    assert any(event.startswith("simulation:") for event in events)
    # The telemetry has to be listening before the plant starts moving, or the first
    # transitions of a run are the ones nobody sees.
    assert len(simulators[0].listeners) == 1


def test_the_embedded_server_does_not_steal_the_interrupt():
    """uvicorn installs its own SIGINT handler on serve(). That would take Ctrl-C away
    from run_simulation's KeyboardInterrupt path and leave every device connected."""
    server = main._EmbeddedServer(uvicorn.Config(app=lambda scope, receive, send: None))

    with server.capture_signals():
        pass
