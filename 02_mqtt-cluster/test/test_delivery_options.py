"""Regression tests for opt-in MQTT delivery session controls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import paho.mqtt.client as mqtt_client
import pytest
from paho.mqtt.properties import Properties

from uns_mqtt.mqtt_listener import (
    MQTTVersion,
    MqttDeliveryOptions,
    SEVEN_DAY_SESSION_EXPIRY_SECONDS,
    UnsMQTTClient,
)


def _connect_and_subscribe(client: UnsMQTTClient) -> None:
    with patch.object(mqtt_client.Client, "connect", autospec=True) as mock_connect:
        client.run(host="localhost", port=1883, topics=["site/#"], qos=1)
        mock_connect.assert_called_once()
        _, kwargs = mock_connect.call_args
        client.on_connect(client, None, None, 0, kwargs.get("properties"))
        return kwargs


def test_default_client_keeps_manual_ack_disabled():
    client = UnsMQTTClient(
        client_id="default-client",
        protocol=MQTTVersion.MQTTv5,
    )
    assert client._manual_ack is False


def test_default_client_uses_clean_start_on_mqtt_v5_connect():
    client = UnsMQTTClient(
        client_id="default-client",
        protocol=MQTTVersion.MQTTv5,
    )
    kwargs = _connect_and_subscribe(client)
    assert kwargs["clean_start"] is True


@pytest.mark.parametrize("protocol", [MQTTVersion.MQTTv311, MQTTVersion.MQTTv31])
@pytest.mark.parametrize("clean_session", [True, False])
@patch.object(mqtt_client.Client, "connect", autospec=True)
def test_mqtt_v3_connect_does_not_pass_v5_clean_start(mock_connect, protocol, clean_session):
    client = UnsMQTTClient(
        client_id="v3-client",
        protocol=protocol,
        clean_session=clean_session,
    )
    client.run(host="localhost", port=1883, topics=["spBv1.0"], qos=1)
    _, connect_kwargs = mock_connect.call_args
    assert connect_kwargs["clean_start"] == mqtt_client.MQTT_CLEAN_START_FIRST_ONLY
    assert connect_kwargs["properties"] is None


@patch.object(mqtt_client.Client, "subscribe", autospec=True)
@patch.object(mqtt_client.Client, "connect", autospec=True)
def test_ingestion_delivery_options_request_stable_session(mock_connect, mock_subscribe):
    client = UnsMQTTClient(
        client_id="ingestion-shard-1",
        protocol=MQTTVersion.MQTTv5,
        delivery_options=MqttDeliveryOptions.ingestion(),
    )
    assert client._manual_ack is True

    client.run(host="localhost", port=1883, topics=["site/#"], qos=1)

    _, connect_kwargs = mock_connect.call_args
    assert connect_kwargs["clean_start"] is False
    connect_properties = connect_kwargs["properties"]
    assert isinstance(connect_properties, Properties)
    assert connect_properties.SessionExpiryInterval == SEVEN_DAY_SESSION_EXPIRY_SECONDS
    assert connect_properties.ReceiveMaximum == 20

    client.on_connect(client, None, None, 0, connect_properties)
    mock_subscribe.assert_called()
    _, subscribe_kwargs = mock_subscribe.call_args
    subscribe_options = subscribe_kwargs["options"]
    assert subscribe_options is not None
    assert subscribe_options.retainHandling == 2
    assert subscribe_options.QoS == 1
    assert "qos" not in subscribe_kwargs


@patch.object(mqtt_client.Client, "connect", autospec=True)
def test_non_ingestion_callers_do_not_set_session_properties(mock_connect):
    client = UnsMQTTClient(
        client_id="historian-client",
        protocol=MQTTVersion.MQTTv5,
    )
    client.run(host="localhost", port=1883, topics=["#"], qos=2)
    _, connect_kwargs = mock_connect.call_args
    assert connect_kwargs["properties"] is not None
    assert getattr(connect_kwargs["properties"], "SessionExpiryInterval", None) is None


def test_ack_message_forwards_to_paho_ack():
    client = UnsMQTTClient(
        client_id="ingestion-shard-2",
        protocol=MQTTVersion.MQTTv5,
        delivery_options=MqttDeliveryOptions.ingestion(),
    )
    message = MagicMock()
    client.ack_message(message)
    message.ack.assert_called_once_with()
