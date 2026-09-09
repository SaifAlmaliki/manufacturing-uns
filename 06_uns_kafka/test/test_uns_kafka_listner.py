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
import uuid

import pytest
from confluent_kafka import OFFSET_END, Consumer
from confluent_kafka.admin import AdminClient
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from uns_config.events import decode_event
from uns_mqtt.mqtt_listener import MQTTVersion

from uns_kafka.ingest import HISTORIC_TOPIC
from uns_kafka.uns_kafka_config import KAFKAConfig
from uns_kafka.uns_kafka_listener import UNSKafkaMapper


@pytest.mark.integrationtest()
def test_uns_kafka_mapper_init():
    """
    Test case for UNSKafkaMapper#init()
    """
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
def test_uns_kafka_mapper_publishing(mqtt_topic: str, mqtt_message, expected_payload):
    """
    End to end: MQTT publish lands as a canonical historic envelope on uns.historic-events.
    """
    uns_kafka_mapper: UNSKafkaMapper = None
    admin_client = None
    mqtt_topic = f"{mqtt_topic}/{uuid.uuid4()}"

    try:
        uns_kafka_mapper = UNSKafkaMapper()
        admin_client = AdminClient(KAFKAConfig.kafka_config_map)

        publish_properties = None
        if uns_kafka_mapper.uns_client.protocol == MQTTVersion.MQTTv5:
            publish_properties = Properties(PacketTypes.PUBLISH)

        payload = json.dumps(mqtt_message)

        def on_message_decorator(client, userdata, msg):
            old_on_message(client, userdata, msg)
            uns_kafka_mapper.kafka_handler.flush()
            kafka_listener: Consumer = get_kafka_consumer(KAFKAConfig.kafka_config_map)

            def reset_offset(consumer, partitions):
                for part in partitions:
                    part.offset = OFFSET_END
                consumer.assign(partitions)

            kafka_listener.subscribe([HISTORIC_TOPIC], on_assign=reset_offset)
            check_kafka_envelope(kafka_listener, mqtt_topic, expected_payload)

        old_on_message = uns_kafka_mapper.uns_client.on_message
        uns_kafka_mapper.uns_client.on_message = on_message_decorator

        uns_kafka_mapper.uns_client.publish(
            topic=mqtt_topic,
            payload=payload,
            qos=1,
            retain=False,
            properties=publish_properties,
        )

    except Exception as ex:
        pytest.fail(
            f"Connection to either the MQTT Broker or Kafka broker did not happen: Exception {ex}")
    finally:
        if uns_kafka_mapper is not None:
            uns_kafka_mapper.uns_client.disconnect()


def check_kafka_envelope(kafka_listener: Consumer, expected_topic: str, expected_payload: dict):
    try:
        while True:
            msg = kafka_listener.poll(1.0)
            if msg is None:
                print("Waiting...")  # noqa: T201
            elif msg.error():
                pytest.fail(msg.error())
            else:
                envelope = decode_event(msg.value())
                assert envelope.topic == expected_topic
                assert envelope.payload == expected_payload
                break
    finally:
        kafka_listener.close()


def get_kafka_consumer(kafka_producer_config: dict) -> Consumer:
    """
    Utility method to create a consumer based on producer config
    """
    consumer_config: dict = {}
    consumer_config["bootstrap.servers"] = kafka_producer_config.get(
        "bootstrap.servers")
    consumer_config["client.id"] = "uns_kafka_mapper_test_consumer"
    consumer_config["group.id"] = "uns_kafka_mapper_test_consumers"
    consumer_config["auto.offset.reset"] = "earliest"
    return Consumer(consumer_config)
