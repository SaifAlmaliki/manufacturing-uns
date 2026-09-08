"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Test cases for uns_historian
"""

import asyncio
import json
import random
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from paho.mqtt.enums import MQTTErrorCode
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from uns_mqtt.mqtt_listener import MQTTVersion, UnsMQTTClient
from uns_sparkplugb.uns_spb_helper import convert_spb_bytes_payload_to_dict

from uns_historian.historian_config import HistorianConfig, MQTTConfig
from uns_historian.historian_handler import HistorianHandler
from uns_historian.uns_mqtt_historian import UnsMqttHistorian, main


@pytest.fixture(scope="function")
def mock_uns_client():
    with patch("uns_historian.uns_mqtt_historian.UnsMQTTClient", autospec=True) as mock_client:
        yield mock_client


@pytest.fixture(scope="function")
def mock_historian_handler():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with patch("uns_historian.uns_mqtt_historian.HistorianHandler", autospec=True) as mock_handler:
        mock_handler.warm = AsyncMock(return_value=MagicMock())
        mock_handler.close = AsyncMock()
        yield mock_handler
    loop.close()


@pytest.fixture(scope="function")
def mock_asset_model_deps():
    """Unit tests must not require Asset Model DB credentials or background listeners."""

    def consume_scheduled_coroutine(coro, _loop):
        if asyncio.iscoroutine(coro):
            coro.close()
        return MagicMock()

    with (
        patch("uns_historian.uns_mqtt_historian.Database.shared", return_value=MagicMock()),
        patch("uns_historian.uns_mqtt_historian.TopicBinder", return_value=MagicMock()),
        patch("uns_historian.uns_mqtt_historian.AssetModelChangeListener", return_value=MagicMock()),
        patch(
            "uns_historian.uns_mqtt_historian.asyncio.run_coroutine_threadsafe",
            side_effect=consume_scheduled_coroutine,
        ),
    ):
        yield


def test_on_message_skips_platform_observability(  # noqa: ARG001
    mock_uns_client, mock_historian_handler, mock_asset_model_deps
):
    uns_mqtt_historian = UnsMqttHistorian()
    msg = MagicMock()
    msg.topic = "uns/platform/simulator/Instance01/status"
    msg.payload = b'{"status":"ok"}'
    uns_mqtt_historian.on_message(uns_mqtt_historian.uns_client, None, msg)
    uns_mqtt_historian.uns_client.get_payload_as_dict.assert_not_called()


def test_on_message_persists_historic_topic(mock_uns_client, mock_historian_handler):  # noqa: ARG001
    """on_message must actually run persist on the historian loop, as main() does via run_forever."""
    loop = asyncio.new_event_loop()
    handler_instance = mock_historian_handler.return_value
    handler_instance.__aenter__ = AsyncMock(return_value=handler_instance)
    handler_instance.__aexit__ = AsyncMock(return_value=False)
    handler_instance.persist_mqtt_msg = AsyncMock()
    topic_binder = MagicMock()
    topic_binder.observe = AsyncMock()
    listener = MagicMock()
    listener.start = AsyncMock()
    listener.stop = AsyncMock()

    payload = {"timestamp": 1486144502122, "TestMetric1": "TestUNS"}
    started = threading.Event()

    def _run_loop() -> None:
        loop.call_soon(started.set)
        loop.run_forever()

    with (
        patch("uns_historian.uns_mqtt_historian.Database.shared", return_value=MagicMock()),
        patch("uns_historian.uns_mqtt_historian.TopicBinder", return_value=topic_binder),
        patch("uns_historian.uns_mqtt_historian.AssetModelChangeListener", return_value=listener),
    ):
        uns_mqtt_historian = UnsMqttHistorian(loop=loop)
        uns_mqtt_historian.uns_client.get_payload_as_dict.return_value = payload
        uns_mqtt_historian.uns_client._client_id = b"historian-unit"

        thread = threading.Thread(target=_run_loop, name="historian-unit-loop", daemon=True)
        thread.start()
        try:
            assert started.wait(timeout=5), "Historian unit-test loop did not start"
            msg = MagicMock()
            msg.topic = "test/uns/ar1/ln2"
            msg.payload = json.dumps(payload).encode()
            uns_mqtt_historian.on_message(uns_mqtt_historian.uns_client, None, msg)
            assert _wait_until(lambda: handler_instance.persist_mqtt_msg.await_count >= 1), (
                "persist_mqtt_msg was not awaited; on_message schedules it on the historian loop"
            )
            handler_instance.persist_mqtt_msg.assert_awaited()
            topic_binder.observe.assert_awaited_with("test/uns/ar1/ln2")
        finally:
            _stop_loop(loop, thread)


def test_uns_mqtt_disconnect_historian_close_pool(  # noqa: ARG001
    mock_uns_client, mock_historian_handler, mock_asset_model_deps
):
    uns_mqtt_historian = UnsMqttHistorian()
    # simulate the disconnection by calling the callback directly
    uns_mqtt_historian.uns_client.on_disconnect(
        client=uns_mqtt_historian.uns_client,
        userdata=None,
        flags=None,
        reason_codes=MQTTErrorCode.MQTT_ERR_SUCCESS,
        properties=None,
    )
    # verify the pool was closed
    mock_historian_handler.close.assert_not_called()


@pytest.mark.usefixtures("mock_uns_client", "mock_asset_model_deps")
def test_uns_mqtt_historian_main_positive_pool_closure(mock_historian_handler):
    # verify that the main method closed the pool in normal execution
    mock_loop = MagicMock()
    with (
        patch("asyncio.new_event_loop", return_value=mock_loop),
        patch("asyncio.set_event_loop"),
        patch("uns_historian.uns_mqtt_historian.start_metrics_server"),
    ):
        main()

        mock_loop.run_forever.assert_called_once()
        mock_historian_handler.close.assert_called_once()


@pytest.mark.usefixtures("mock_uns_client", "mock_asset_model_deps")
def test_uns_mqtt_historian_main_negative_pool_closure(mock_historian_handler):
    # verify that the main method closed the pool even if exceptions were raised
    mock_loop = MagicMock()
    mock_loop.run_forever.side_effect = RuntimeError("Mocked Loop Error")

    with (
        patch("asyncio.new_event_loop", return_value=mock_loop),
        patch("asyncio.set_event_loop"),
        patch("uns_historian.uns_mqtt_historian.start_metrics_server"),
    ):
        with pytest.raises(RuntimeError):
            main()

        mock_historian_handler.close.assert_called_once()


# test data_list :  [{topic,[messages]}]
# ensure that the topics mentioned here align with settings.yaml
test_data_list: list[dict[str, list[dict | bytes | str]]] = [
    {
        "test/uns/ar1/ln2":  # test_data[0]: test for normal messages
        [
            {
                "timestamp": 1486144502122,
                "TestMetric1": "TestUNS",
            },
            {
                "timestamp": 1586144502222,
                "TestMetric2": "TestUNS",
            },
        ],
    },
    {
        # test_data[1]: test for SparkplugB messages
        "spBv1.0/uns_group/NBIRTH/eon1": [
            (
                b"\x08\xc4\x89\x89\x83\xd30\x12\x17\n\x08Inputs/A\x10\x00\x18\xea\xf2\xf5\xa8\xa0+ "
                b"\x0bp\x00\x12\x17\n\x08Inputs/B\x10\x01\x18\xea\xf2\xf5\xa8\xa0+ \x0bp\x00\x12\x18\n\t"
                b"Outputs/E\x10\x02\x18\xea\xf2\xf5\xa8\xa0+ \x0bp\x00\x12\x18\n\tOutputs/F\x10\x03\x18\xea\xf2\xf5\xa8\xa0+ "
                b"\x0bp\x00\x12+\n\x18Properties/Hardware Make\x10\x04\x18\xea\xf2\xf5\xa8\xa0+ \x0cz\x04Sony\x12!\n\x11"
                b"Properties/Weight\x10\x05\x18\xea\xf2\xf5\xa8\xa0+ \x03P\xc8\x01\x18\x00"
            ),
        ],
    },
]


def create_publisher() -> UnsMQTTClient:
    """
    utility method to create publisher
    """
    uns_publisher = UnsMQTTClient(
        client_id=f"publisher-{time.time()}-{random.randint(0, 1000)}",  # noqa: S311
        clean_session=MQTTConfig.clean_session,
        userdata=None,
        protocol=MQTTConfig.version,
        transport=MQTTConfig.transport,
        reconnect_on_failure=MQTTConfig.reconnect_on_failure,
    )
    if MQTTConfig.username is not None:
        uns_publisher.username_pw_set(MQTTConfig.username, MQTTConfig.password)
    uns_publisher.setup_tls(MQTTConfig.tls)
    uns_publisher.topics = MQTTConfig.topics
    connect_properties = None
    if MQTTConfig.version == MQTTVersion.MQTTv5:
        connect_properties = Properties(PacketTypes.CONNECT)
    uns_publisher.connect(
        host=MQTTConfig.host, port=MQTTConfig.port, keepalive=MQTTConfig.keepalive, properties=connect_properties
    )
    return uns_publisher


def _wait_until(condition, *, timeout_s: float = 5.0, sleep_s: float = 0.1) -> bool:
    """Poll until condition() is true. The historian loop must already be running in another thread."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(sleep_s)
    return condition()


def test_rejected_subscribe_codes_accepts_granted_qos():
    assert _rejected_subscribe_codes([0, 1, 2]) == []


def test_rejected_subscribe_codes_flags_not_authorized():
    assert _rejected_subscribe_codes([135]) == ["135"]


def _rejected_subscribe_codes(reason_codes) -> list[str]:
    codes = reason_codes if isinstance(reason_codes, list) else [reason_codes]
    rejected: list[str] = []
    for rc in codes:
        failed = bool(getattr(rc, "is_failure", False))
        if not failed:
            value = int(getattr(rc, "value", rc) or 0)
            failed = value >= 128
        if failed:
            rejected.append(str(rc))
    return rejected


def _run_on_loop(loop: asyncio.AbstractEventLoop, coro, *, timeout_s: float = 10):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout_s)


def _close_shared_database() -> None:
    """Dispose any engine bound to pytest-asyncio's loop before creating the historian loop."""

    async def _close() -> None:
        await HistorianHandler.close()

    try:
        existing = asyncio.get_event_loop()
    except RuntimeError:
        existing = None
    if existing is not None and not existing.is_closed() and not existing.is_running():
        existing.run_until_complete(_close())
        return
    tmp = asyncio.new_event_loop()
    try:
        tmp.run_until_complete(_close())
    finally:
        tmp.close()


def _stop_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    if loop.is_closed():
        return
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(HistorianHandler.close())
    loop.close()


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def clean_up_database():
    """
    Clean database from test data from the historian after execution of the tests
    """
    yield
    delete_sql_cmd = f""" DELETE FROM {HistorianConfig.table} WHERE
                               topic = $1 AND
                               mqtt_msg = $2;"""  # noqa: S608
    for test_data in test_data_list:
        for topic, messages in test_data.items():
            for message in messages:
                if type(message) is bytes:
                    message = convert_spb_bytes_payload_to_dict(message)
                async with HistorianHandler() as historian:
                    await historian.execute_prepared(delete_sql_cmd, *[topic, json.dumps(message)])


@pytest.mark.integrationtest
@pytest.mark.xdist_group(name="mqtt_historian")
@pytest.mark.xdist_group(name="uns_mqtt_historian")
@pytest.mark.parametrize(  # convert test data dict into tuples for pytest parameterize
    "topic, messages", [(topic, messages) for dictionary in test_data_list for topic, messages in dictionary.items()]
)
def test_uns_mqtt_historian(clean_up_database, topic: str, messages: list):  # noqa: ARG001
    uns_mqtt_historian = None
    uns_publisher = None
    publish_properties = None
    loop: asyncio.AbstractEventLoop | None = None
    loop_thread: threading.Thread | None = None
    try:
        # main() runs this loop forever so MQTT-thread persist tasks execute.
        # pytest-asyncio's session loop is not running during this sync test.
        _close_shared_database()
        loop = asyncio.new_event_loop()
        uns_mqtt_historian = UnsMqttHistorian(loop=loop)

        subscribed = threading.Event()
        subscribe_rejected: list[str] = []
        persist_errors: list[BaseException] = []
        received_count = 0
        old_on_subscribe = uns_mqtt_historian.uns_client.on_subscribe
        old_on_message = uns_mqtt_historian.on_message

        def on_subscribe(client, userdata, mid, reason_codes, properties=None):
            old_on_subscribe(client, userdata, mid, reason_codes, properties)
            subscribe_rejected.extend(_rejected_subscribe_codes(reason_codes))
            subscribed.set()

        def on_message(client, userdata, msg):
            nonlocal received_count
            received_count += 1
            old_on_message(client, userdata, msg)

        def on_persist_done(future: asyncio.Future) -> None:
            try:
                future.result()
            except Exception as ex:  # noqa: BLE001 - surface persist failures in the assertion
                persist_errors.append(ex)
            UnsMqttHistorian._on_persist_done(future)

        uns_mqtt_historian.uns_client.on_subscribe = on_subscribe
        uns_mqtt_historian.uns_client.on_message = on_message
        uns_mqtt_historian._on_persist_done = on_persist_done

        started = threading.Event()

        def _run_loop() -> None:
            loop.call_soon(started.set)
            loop.run_forever()

        loop_thread = threading.Thread(target=_run_loop, name="uns-mqtt-historian-loop", daemon=True)
        loop_thread.start()
        assert started.wait(timeout=5), "Historian asyncio loop did not start"

        uns_mqtt_historian.uns_client.loop_start()
        assert _wait_until(lambda: uns_mqtt_historian.uns_client.is_connected() and subscribed.is_set()), (
            "Historian MQTT client did not connect and subscribe before publish"
        )
        assert not subscribe_rejected, (
            f"MQTT subscribe was rejected: {subscribe_rejected}. "
            "HiveMQ Edge must allow the historian topic filter before publish."
        )

        uns_publisher = create_publisher()
        uns_publisher.loop_start()
        assert _wait_until(uns_publisher.is_connected), "Publisher MQTT client did not connect before publish"

        if MQTTConfig.version == MQTTVersion.MQTTv5:
            publish_properties = Properties(PacketTypes.PUBLISH)
        for message in messages:
            payload = json.dumps(message) if type(message) is dict or type(message) is str else message
            uns_publisher.publish(topic=topic, payload=payload, qos=2, retain=True, properties=publish_properties)

        select_query = f""" SELECT * FROM {HistorianConfig.table} WHERE
                               topic = $1 AND
                               mqtt_msg = $2 AND
                               client_id = $3;"""  # noqa: S608

        async def execute_prepared_async(select_query, topic, message, client_id):
            async with HistorianHandler() as historian:
                return await historian.execute_prepared(select_query, *[topic, json.dumps(message), client_id])

        normalized_messages = [
            convert_spb_bytes_payload_to_dict(message) if type(message) is bytes else message for message in messages
        ]

        persisted: dict[str, list] = {}

        def _all_persisted() -> bool:
            for message in normalized_messages:
                key = json.dumps(message)
                if key in persisted:
                    continue
                result = _run_on_loop(
                    loop, execute_prepared_async(select_query, topic, message, uns_mqtt_historian.client_id)
                )
                if result:
                    persisted[key] = result
            return len(persisted) == len(normalized_messages)

        assert _wait_until(_all_persisted, timeout_s=15.0), (
            f"Historian did not persist {len(normalized_messages)} message(s) for topic {topic}; "
            f"mqtt_received={received_count}, persist_errors={persist_errors!r}"
        )

        uns_mqtt_historian.uns_client.disconnect()
        uns_mqtt_historian.uns_client.loop_stop()

        for message in normalized_messages:
            result = persisted[json.dumps(message)]
            assert result is not None, "Should have gotten a result"
            assert len(result) == 1, "Should have gotten only one record because we inserted only one record"

    finally:
        if uns_publisher is not None:
            uns_publisher.publish(topic=topic, payload=b"", qos=2, retain=True, properties=publish_properties)
            uns_publisher.disconnect()
            uns_publisher.loop_stop()
        if uns_mqtt_historian is not None:
            uns_mqtt_historian.uns_client.disconnect()
            uns_mqtt_historian.uns_client.loop_stop()
        if loop is not None and loop_thread is not None:
            _stop_loop(loop, loop_thread)
        elif loop is not None and not loop.is_closed():
            loop.close()
