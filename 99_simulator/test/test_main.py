import asyncio
import sys

from uns_simulator.main import configure_asyncio_for_mqtt


def test_configure_asyncio_for_mqtt_sets_selector_on_windows(monkeypatch):
    set_calls = []

    class FakePolicy:
        pass

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", FakePolicy, raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", set_calls.append)

    configure_asyncio_for_mqtt()

    assert len(set_calls) == 1
    assert isinstance(set_calls[0], FakePolicy)


def test_configure_asyncio_for_mqtt_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("event loop policy should not change off Windows")

    monkeypatch.setattr(asyncio, "set_event_loop_policy", fail_if_called)
    configure_asyncio_for_mqtt()
