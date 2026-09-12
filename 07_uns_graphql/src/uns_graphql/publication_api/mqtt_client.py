"""MQTT publisher used by the publication outbox worker."""

from __future__ import annotations

import asyncio
import logging
import time

from aiomqtt import Client, MqttError

from uns_graphql.graphql_config import MQTTConfig

LOGGER = logging.getLogger(__name__)


class AiomqttPublicationClient:
    async def publish_qos1(self, topic: str, payload: bytes) -> None:
        if not MQTTConfig.is_config_valid():
            raise RuntimeError("mqtt_not_configured")
        client_id = f"uns-publication-outbox-{time.time_ns()}"
        try:
            async with Client(
                identifier=client_id,
                protocol=MQTTConfig.version,
                transport=MQTTConfig.transport,
                hostname=MQTTConfig.host,
                port=MQTTConfig.port,
                username=MQTTConfig.username,
                password=MQTTConfig.password,
                keepalive=MQTTConfig.keep_alive,
                tls_params=MQTTConfig.tls_params,
                tls_insecure=MQTTConfig.tls_insecure,
            ) as client:
                await client.publish(topic, payload, qos=MQTTConfig.qos)
                await asyncio.sleep(0)
        except MqttError as exc:
            LOGGER.warning("mqtt publish failed topic=%s error=%s", topic, exc)
            raise
