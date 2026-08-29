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
