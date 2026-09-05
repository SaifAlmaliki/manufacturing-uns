"""Tests for the supervisor's wiring and shutdown behaviour."""

import asyncio

import pytest
from uns_model.connectivity import ConnectivityServerSpec, ConnectivityTagSpec
from uns_opcua.main import (
    _idle_when_no_servers,
    build_bindings_for_all,
    load_servers_from_catalog,
    resolve_servers,
    run_connector,
    run_connector_keeping_metrics_alive,
)
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


def _spool_config(tmp_path) -> SpoolConfig:
    return SpoolConfig(
        path=str(tmp_path / "spool.db"),
        max_rows=10,
        max_bytes=1_000_000,
        max_age_hours=1,
        synchronous="OFF",
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
    # A stock checkout has no servers. That must be a clean exit, not a crash loop.
    await run_connector(
        servers=(),
        spool_config=_spool_config(tmp_path),
        client_id="c",
        qos=1,
        queue_maxsize=10,
        forward_batch_size=10,
        backoff_max_s=1.0,
        model_check=False,
    )


async def test_idle_when_no_servers_keeps_running_until_cancelled():
    """Stock checkout must keep the process up so /metrics stays scrapeable."""
    task = asyncio.create_task(_idle_when_no_servers())
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_connector_keeping_metrics_alive_idles_when_no_servers(tmp_path):
    """main()'s post-run path must idle after run_connector's empty-server return."""
    task = asyncio.create_task(
        run_connector_keeping_metrics_alive(
            servers=(),
            spool_config=_spool_config(tmp_path),
            client_id="c",
            qos=1,
            queue_maxsize=10,
            forward_batch_size=10,
            backoff_max_s=1.0,
            model_check=False,
        )
    )
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


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


class _FakeCatalog:
    """A stand-in for ConnectivityRepository that returns canned specs."""

    def __init__(self, servers, tags_by_server_id, *, raise_on_read: bool = False):
        self._servers = servers
        self._tags = tags_by_server_id
        self._raise = raise_on_read

    async def list_servers(self):
        if self._raise:
            raise RuntimeError("catalog down")
        return list(self._servers)

    async def list_subscribed_tags(self, server_id):
        if self._raise:
            raise RuntimeError("catalog down")
        return list(self._tags.get(server_id, ()))


async def test_load_servers_from_catalog_returns_catalog_servers():
    servers = [ConnectivityServerSpec("s1", "opcplc", "opc_ua", "opc.tcp://host:4840/")]
    tags = {"s1": [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]}
    repository = _FakeCatalog(servers, tags)
    loaded = await load_servers_from_catalog(repository)
    assert len(loaded) == 1
    assert loaded[0].name == "opcplc"
    assert loaded[0].tags[0].mqtt_topic == "Plant/A"


async def test_load_servers_from_catalog_returns_empty_when_catalog_unreachable():
    """A console that is briefly down must not stop a YAML-only connector."""
    repository = _FakeCatalog([], {}, raise_on_read=True)
    loaded = await load_servers_from_catalog(repository)
    assert loaded == ()


async def test_resolve_servers_prefers_catalog_when_non_empty():
    catalog_server = ServerConfig(
        name="catalog-plc",
        url="opc.tcp://catalog:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id="ns=2;s=1", asset="Plant/A", metric_path=""),),
    )
    assert resolve_servers((catalog_server,)) == (catalog_server,)


async def test_resolve_servers_falls_back_to_yaml_when_catalog_empty(monkeypatch):
    yaml_server = ServerConfig(
        name="yaml-plc",
        url="opc.tcp://yaml:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id="ns=2;s=2", asset="Plant/B", metric_path=""),),
    )
    monkeypatch.setattr("uns_opcua.main.OpcUaConfig.servers", (yaml_server,))
    assert resolve_servers(()) == (yaml_server,)
