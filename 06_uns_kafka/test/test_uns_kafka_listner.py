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

Test cases for uns_kafka.uns_kafka_listener
"""

import json
import time
import uuid

import pytest
from confluent_kafka import Consumer
from mapper_harness import live_mapper, patch_unique_ingestion_config, wait_for_kafka_assignment, wait_until
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from uns_config.events import decode_event
from uns_mqtt.mqtt_listener import MQTTVersion

from uns_kafka.ingest import HISTORIC_TOPIC
from uns_kafka.uns_kafka_config import KAFKAConfig
from uns_kafka.uns_kafka_listener import UNSKafkaMapper


@pytest.mark.integrationtest()
def test_uns_kafka_mapper_init(monkeypatch):
    """
    Test case for UNSKafkaMapper#init()
    """
    patch_unique_ingestion_config(monkeypatch)
    uns_kafka_mapper: UNSKafkaMapper = None
    try:
        uns_kafka_mapper = UNSKafkaMapper()
        assert uns_kafka_mapper is not None, "Connection to either the MQTT Broker or Kafka broker did not happen"

        assert uns_kafka_mapper.kafka_handler.producer, "Connection to Kafka broker did not happen"
        assert uns_kafka_mapper.kafka_handler.producer.list_topics(
        ), "Connection to Kafka broker did not happen"
        assert uns_kafka_mapper.uns_client, "Connection to MQTT broker did not happen"

    except Exception as ex:
        pytest.fail(
            "Connection to either the MQTT Broker or Kafka broker did not happen" f" Exception {ex}")
    finally:
        if uns_kafka_mapper is not None:
            uns_kafka_mapper.uns_client.disconnect()


@pytest.mark.integrationtest()
@pytest.mark.parametrize(
    "mqtt_topic, mqtt_message,expected_payload",
    [
        (
            "a/b/c",
            {"timestamp": 12345678, "message": "test message1"},
            {"timestamp": 12345678, "message": "test message1"},
        ),
        (
            "abc",
            {"timestamp": 12345678, "message": "test message2"},
            {"timestamp": 12345678, "message": "test message2"},
        ),
    ],
)
def test_uns_kafka_mapper_publishing(monkeypatch, mqtt_topic: str, mqtt_message, expected_payload):
    """
    End to end: MQTT publish lands as a canonical historic envelope on uns.historic-events.
    """
    mqtt_topic = f"{mqtt_topic}/{uuid.uuid4()}"
    kafka_listener: Consumer | None = None
    try:
        with live_mapper(monkeypatch) as uns_kafka_mapper:
            publish_properties = None
            if uns_kafka_mapper.uns_client.protocol == MQTTVersion.MQTTv5:
                publish_properties = Properties(PacketTypes.PUBLISH)

            kafka_listener = get_kafka_consumer(KAFKAConfig.kafka_config_map)
            wait_for_kafka_assignment(kafka_listener, HISTORIC_TOPIC, from_end=True)
            delivered_before = uns_kafka_mapper.kafka_handler.delivered_count
            uns_kafka_mapper.uns_client.publish(
                topic=mqtt_topic,
                payload=json.dumps(mqtt_message),
                qos=1,
                retain=False,
                properties=publish_properties,
            )
            if not wait_until(
                lambda: _kafka_delivered(uns_kafka_mapper, delivered_before),
                timeout_s=10.0,
            ):
                pytest.fail("mapper did not deliver a Kafka record after MQTT publish")
            check_kafka_envelope(kafka_listener, mqtt_topic, expected_payload)
    finally:
        if kafka_listener is not None:
            kafka_listener.close()


def _kafka_delivered(mapper: UNSKafkaMapper, delivered_before: int) -> bool:
    mapper.kafka_handler.poll(0)
    return mapper.kafka_handler.delivered_count > delivered_before


def check_kafka_envelope(kafka_listener: Consumer, expected_topic: str, expected_payload: dict):
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        msg = kafka_listener.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            pytest.fail(msg.error())
        envelope = decode_event(msg.value())
        if envelope.topic != expected_topic:
            continue
        assert envelope.payload == expected_payload
        return
    pytest.fail(f"Timeout waiting for envelope on {expected_topic}")


def get_kafka_consumer(kafka_producer_config: dict) -> Consumer:
    """
    Utility method to create a consumer based on producer config
    """
    consumer_config: dict = {}
    consumer_config["bootstrap.servers"] = kafka_producer_config.get(
        "bootstrap.servers")
    consumer_config["client.id"] = "uns_kafka_mapper_test_consumer"
    consumer_config["group.id"] = f"uns_kafka_mapper_test_consumers_{uuid.uuid4()}"
    consumer_config["auto.offset.reset"] = "earliest"
    return Consumer(consumer_config)
