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

Configuration reader for mqtt server where UNS are read from and the Kafka broker to publish to
"""

import logging
from typing import Literal

from uns_config import get_settings
from uns_config.kafka import sanitize_kafka_config
from uns_mqtt.mqtt_listener import MQTTVersion

# Logger
LOGGER = logging.getLogger(__name__)

settings = get_settings("kafka_mapper")


class MQTTConfig:
    """
    Read the MQTT configurations required to connect to the MQTT broker
    """

    transport: Literal["tcp", "websockets"] = settings.get("mqtt.transport", "tcp")
    version: Literal[MQTTVersion.MQTTv5, MQTTVersion.MQTTv311, MQTTVersion.MQTTv31] = settings.get(
        "mqtt.version", MQTTVersion.MQTTv5
    )
    qos: Literal[0, 1, 2] = settings.get("mqtt.qos", 2)
    reconnect_on_failure: bool = settings.get("mqtt.reconnect_on_failure", True)
    clean_session: bool | None = settings.get("mqtt.clean_session", None)

    host: str = settings.get("mqtt.host")
    port: int = settings.get("mqtt.port", 1883)
    username: str = settings.get("mqtt.username")
    password: str = settings.get("mqtt.password")
    tls: dict | None = settings.get("mqtt.tls", None)
    topics: list[str] = settings.get("mqtt.topics", ["#"])
    if isinstance(topics, str):
        topics = [topics]
    keep_alive: int = settings.get("mqtt.keep_alive", 60)
    ignored_attributes: dict | None = settings.get("mqtt.ignored_attributes", None)
    timestamp_key: str = settings.get("mqtt.timestamp_attribute", "timestamp")
    if host is None:
        LOGGER.error(
            "MQTT Host not provided. Update key 'mqtt.host' in 'conf/settings.yaml' at the repository root",
        )

    @classmethod
    def is_config_valid(cls) -> bool:
        return cls.host is not None


class KAFKAConfig:
    """
    Read the Kafka configurations required to connect to the Kafka broker
    """

    kafka_config_map: dict = sanitize_kafka_config(settings.get("kafka.config"))
