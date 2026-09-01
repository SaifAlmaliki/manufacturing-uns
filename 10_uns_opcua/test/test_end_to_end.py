"""
The behaviour this whole module exists for: a broker outage must delay data, not lose it.

Uses the in-process OPC UA server and a fake publisher rather than a live broker, so the
outage is scripted rather than hoped for. The Compose broker is exercised separately by
the integration suite.
"""

import asyncio
import json

import pytest
import pytest_asyncio
from asyncua import Server, ua

from uns_opcua.collector import Collector
from uns_opcua.forwarder import Forwarder, SpoolWriter
from uns_opcua.opcua_config import ServerConfig, SpoolConfig, TagConfig
from uns_opcua.spool import Spool, SpoolRow
from uns_opcua.tag_map import build_bindings

ENDPOINT = "opc.tcp://127.0.0.1:48402/uns/e2e/"
ASSET = "TestCo/Site/Area/Line1/Cell1/Mixer"

pytestmark = [pytest.mark.integrationtest, pytest.mark.asyncio]


class FlakyPublisher:
    """A broker that is down until `up` is set."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []
        self.up = False

    async def publish(self, topic: str, payload: bytes, qos: int) -> None:
        if not self.up:
            raise ConnectionError("broker down")
        self.published.append((topic, payload))
        _ = qos


@pytest_asyncio.fixture
async def opcua_server():
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    namespace = await server.register_namespace("http://uns/e2e")
    device = await server.nodes.objects.add_object(namespace, "Mixer")
    temperature = await device.add_variable(namespace, "Temp_PV", 10.0)
    await temperature.set_writable()
    async with server:
        yield temperature


async def test_data_collected_during_an_outage_is_published_when_the_broker_returns(opcua_server, tmp_path):
    temperature = opcua_server
    server_config = ServerConfig(
        name="e2e-plc",
        url=ENDPOINT,
        publishing_interval_ms=50,
        tags=(TagConfig(node_id=temperature.nodeid.to_string(), asset=ASSET, metric_path="ProcessValue/Temperature"),),
    )
    spool = Spool(
        SpoolConfig(
            path=str(tmp_path / "spool.db"),
            max_rows=1000,
            max_bytes=10_000_000,
            max_age_hours=168,
            synchronous="OFF",
        )
    )
    spool.open()
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue(maxsize=1000)
    publisher = FlakyPublisher()
    writer = SpoolWriter(spool=spool, queue=queue, batch_size=100, flush_interval_s=0.02)
    forwarder = Forwarder(spool=spool, client_id="uns_opcua_e2e", qos=1, batch_size=100)
    collector = Collector(
        server=server_config,
        bindings=build_bindings(server_config),
        queue=queue,
        client_id="uns_opcua_e2e",
        qos=1,
    )

    tasks = [
        asyncio.create_task(collector.run()),
        asyncio.create_task(writer.run()),
    ]
    try:
        await asyncio.sleep(1.0)
        for value in (20.0, 30.0, 40.0):
            await temperature.write_value(ua.DataValue(ua.Variant(value, ua.VariantType.Double)))
            await asyncio.sleep(0.2)

        # The broker is down: the values must be on disk, not lost and not published.
        async with asyncio.timeout(5):
            while await asyncio.to_thread(spool.row_count) < 4:  # initial 10.0 plus three writes
                await asyncio.sleep(0.05)
        assert publisher.published == []

        publisher.up = True
        forwarded = 0
        async with asyncio.timeout(5):
            while await asyncio.to_thread(spool.row_count) > 0:
                forwarded += await forwarder.forward_batch(publisher)

        values = [json.loads(payload.decode("utf-8"))["value"] for _, payload in publisher.published]
        assert values[:4] == [10.0, 20.0, 30.0, 40.0], "order must survive the outage"
        assert forwarded == len(publisher.published)
        # Rule 2: client_id is stamped at collection from config, never generated at drain.
        assert all(json.loads(payload.decode("utf-8"))["source"] == "uns_opcua_e2e" for _, payload in publisher.published)
        # Rule 1: every timestamp came from the server, none from drain time.
        timestamps = [json.loads(payload.decode("utf-8"))["timestamp"] for _, payload in publisher.published]
        assert timestamps == sorted(timestamps)
        assert all(topic == f"{ASSET}/ProcessValue/Temperature" for topic, _ in publisher.published)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        spool.close()


async def test_a_crash_during_publish_leaves_the_row_to_replay(tmp_path):
    """
    The spool deletes only after the broker acknowledges, so an interruption replays.
    At-least-once is safe because the historian inserts ON CONFLICT DO NOTHING.
    """
    config = SpoolConfig(
        path=str(tmp_path / "spool.db"),
        max_rows=1000,
        max_bytes=10_000_000,
        max_age_hours=168,
        synchronous="FULL",
    )
    spool = Spool(config)
    spool.open()
    payload = b'{"value":1,"timestamp":1756728000123.0}'
    spool.enqueue([SpoolRow(topic="t", payload=payload, qos=1)], now=1_756_728_000.0)

    class CrashingPublisher:
        def __init__(self) -> None:
            self.published: list[bytes] = []

        async def publish(self, topic: str, payload: bytes, qos: int) -> None:
            self.published.append(payload)
            _ = topic, qos
            raise KeyboardInterrupt("power cut after the broker acknowledged")

    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)
    with pytest.raises(KeyboardInterrupt):
        await forwarder.forward_batch(CrashingPublisher())
    spool.close()

    # Restart: publish raised before returning, so the row was never marked
    # acknowledged and is still here to replay. Had publish returned, finally
    # would have deleted it.
    restarted = Spool(config)
    restarted.open()
    try:
        assert restarted.row_count() == 1
    finally:
        restarted.close()
