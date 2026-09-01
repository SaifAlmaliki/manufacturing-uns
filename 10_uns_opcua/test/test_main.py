"""Tests for the supervisor's wiring and shutdown behaviour."""

import asyncio

import pytest
from uns_opcua.main import build_bindings_for_all, run_connector
from uns_opcua.opcua_config import ServerConfig, SpoolConfig, TagConfig

pytestmark = pytest.mark.asyncio

ASSET = "TestCo/Site/Area/Line1/Cell1/Mixer"


def _server(name: str, node_id: str, metric_path: str) -> ServerConfig:
    return ServerConfig(
        name=name,
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id=node_id, asset=ASSET, metric_path=metric_path),),
    )


async def test_build_bindings_for_all_flattens_every_server():
    servers = (_server("plc01", "ns=2;i=5", "ProcessValue/Temperature"), _server("plc02", "ns=2;i=6", "ProcessValue/Pressure"))
    bindings = build_bindings_for_all(servers)
    assert [binding.server_name for binding in bindings] == ["plc01", "plc02"]
    assert [binding.topic for binding in bindings] == [
        f"{ASSET}/ProcessValue/Temperature",
        f"{ASSET}/ProcessValue/Pressure",
    ]


async def test_run_connector_exits_cleanly_when_no_servers_are_configured(tmp_path):
    spool_config = SpoolConfig(
        path=str(tmp_path / "spool.db"),
        max_rows=10,
        max_bytes=1_000_000,
        max_age_hours=1,
        synchronous="OFF",
    )
    # A stock checkout has no servers. That must be a clean exit, not a crash loop.
    await run_connector(
        servers=(),
        spool_config=spool_config,
        client_id="c",
        qos=1,
        queue_maxsize=10,
        forward_batch_size=10,
        backoff_max_s=1.0,
        model_check=False,
    )


async def test_run_connector_cancels_every_task_on_shutdown(tmp_path, monkeypatch):
    """A cancelled supervisor must not leave orphan tasks holding the spool open."""
    spool_config = SpoolConfig(
        path=str(tmp_path / "spool.db"),
        max_rows=10,
        max_bytes=1_000_000,
        max_age_hours=1,
        synchronous="OFF",
    )
    started = asyncio.Event()

    async def never_ending(self) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("uns_opcua.collector.Collector.run", never_ending)
    monkeypatch.setattr("uns_opcua.forwarder.Forwarder.run", never_ending)

    task = asyncio.create_task(
        run_connector(
            servers=(_server("plc01", "ns=2;i=5", "ProcessValue/Temperature"),),
            spool_config=spool_config,
            client_id="c",
            qos=1,
            queue_maxsize=10,
            forward_batch_size=10,
            backoff_max_s=1.0,
            model_check=False,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Name the tasks we own rather than asserting on all_tasks(), which also holds the
    # test runner's own tasks.
    owned = {"spool_writer", "forwarder", "model_check", "collector:plc01"}
    leaked = [t.get_name() for t in asyncio.all_tasks() if t.get_name() in owned and not t.done()]
    assert leaked == []
