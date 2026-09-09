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
from uns_kafka.ingest import (
    HISTORIC_TOPIC,
    IngestionConfig,
    OwnershipMapping,
    validate_ownership_mappings,
    validate_shard_client_id,
)
from uns_kafka.rejections import DLQ_TOPIC
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


def build_producer_config(raw: dict | None) -> dict:
    """Merge bounded producer defaults with sanitized deployment settings."""
    defaults = {
        "enable.idempotence": True,
        "acks": "all",
        "queue.buffering.max.messages": 1000,
        "queue.buffering.max.kbytes": 16384,
        "delivery.timeout.ms": 120_000,
    }
    return {**defaults, **sanitize_kafka_config(raw)}


class KAFKAConfig:
    """
    Read the Kafka configurations required to connect to the Kafka broker
    """

    kafka_config_map: dict = build_producer_config(settings.get("kafka.config"))


def load_ingestion_config() -> IngestionConfig:
    raw = settings.get("ingestion", {})
    ownership_raw = raw.get(
        "ownership",
        [{"site_id": "default", "source_id": "default/ingress", "topic_prefix": ""}],
    )
    mappings = tuple(
        OwnershipMapping(
            site_id=entry["site_id"],
            source_id=entry["source_id"],
            topic_prefix=entry.get("topic_prefix", ""),
        )
        for entry in ownership_raw
    )
    validate_ownership_mappings(mappings)
    client_id = raw.get("client_id") or settings.get("mqtt.client_id")
    if not client_id:
        client_id = f"uns_kafka_ingest-{raw.get('shard_id', 'default')}"
    validate_shard_client_id(client_id)
    return IngestionConfig(
        shard_id=raw.get("shard_id", "default"),
        client_id=client_id,
        historic_topic=raw.get("historic_topic", HISTORIC_TOPIC),
        dlq_topic=raw.get("dlq_topic", DLQ_TOPIC),
        ownership_mappings=mappings,
        pending_record_limit=int(raw.get("pending_record_limit", 1000)),
        pending_byte_limit=int(raw.get("pending_byte_limit", 16 * 1024 * 1024)),
        timestamp_attribute=raw.get("timestamp_attribute", MQTTConfig.timestamp_key),
    )


class IngestionSettings:
    config: IngestionConfig = load_ingestion_config()
    metrics_port: int | None = settings.get("metrics_port")
