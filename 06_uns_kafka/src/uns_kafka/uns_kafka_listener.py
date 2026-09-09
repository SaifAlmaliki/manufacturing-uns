"""MQTT listener that publishes canonical historic events to Kafka."""

from __future__ import annotations

import logging

from uns_config.uns_ingest import is_historic_event_topic
from uns_mqtt.mqtt_listener import MqttDeliveryOptions, UnsMQTTClient

from uns_kafka.health_check import set_ingestion_halted, set_ingestion_ready
from uns_kafka.ingest import IngestionOwner, ReceiptToken
from uns_kafka.kafka_handler import KafkaHandler
from uns_kafka.prometheus_metrics import (
    INGEST_ACCEPTED,
    INGEST_BACKPRESSURE,
    INGEST_READY,
    INGEST_RECEIVED,
    start_metrics_server,
)
from uns_kafka.uns_kafka_config import IngestionSettings, KAFKAConfig, MQTTConfig

LOGGER = logging.getLogger(__name__)


class _MqttAckAdapter:
    def __init__(self, client: UnsMQTTClient) -> None:
        self._client = client
        self._messages: dict[tuple[int, int], object] = {}

    def register(self, token: ReceiptToken, message) -> None:
        self._messages[(token.connection_generation, token.packet_id)] = message

    def ack(self, token: ReceiptToken) -> None:
        message = self._messages.pop((token.connection_generation, token.packet_id), None)
        if message is not None:
            self._client.ack_message(message)


class _KafkaPublisherAdapter:
    def __init__(self, handler: KafkaHandler) -> None:
        self._handler = handler

    def publish_event(self, topic, key, value, on_delivery) -> None:
        self._handler.publish_event(topic, key, value, on_delivery)


class UNSKafkaMapper:
    """MQTT ingestion shard that publishes canonical historic events to Kafka."""

    def __init__(self):
        self.ingestion_config = IngestionSettings.config
        self.kafka_handler = KafkaHandler(KAFKAConfig.kafka_config_map)
        publisher = _KafkaPublisherAdapter(self.kafka_handler)
        self.mqtt_ack = _MqttAckAdapter(None)  # placeholder until client exists
        self.owner = IngestionOwner(
            config=self.ingestion_config,
            mqtt=self.mqtt_ack,
            events=publisher,
            dlq=publisher,
        )
        self.uns_client = UnsMQTTClient(
            client_id=self.ingestion_config.client_id,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            reconnect_on_failure=MQTTConfig.reconnect_on_failure,
            delivery_options=MqttDeliveryOptions.ingestion(),
        )
        self.mqtt_ack._client = self.uns_client
        self.uns_client.on_message = self.on_message
        self.uns_client.on_disconnect = self.on_disconnect
        previous_on_connect = self.uns_client.on_connect
        self._connected_once = False

        def on_connect(client, userdata, flags, reason_code, properties=None):
            if reason_code == 0 and self._connected_once:
                self.owner.on_reconnect()
            if reason_code == 0:
                self._connected_once = True
            if previous_on_connect is not None:
                previous_on_connect(client, userdata, flags, reason_code, properties)

        self.uns_client.on_connect = on_connect
        INGEST_READY.labels(shard=self.ingestion_config.shard_id).set(1)
        set_ingestion_ready(True)
        if IngestionSettings.metrics_port:
            start_metrics_server(int(IngestionSettings.metrics_port))
        self.uns_client.run(
            host=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            tls=MQTTConfig.tls,
            keepalive=MQTTConfig.keep_alive,
            topics=MQTTConfig.topics,
            qos=MQTTConfig.qos,
        )

    def on_message(self, client, userdata, msg):  # noqa: ARG002
        if not is_historic_event_topic(msg.topic):
            return
        INGEST_RECEIVED.labels(shard=self.ingestion_config.shard_id, qos=str(msg.qos)).inc()
        decoded_payload = None
        if not msg.topic.startswith("spBv1.0/"):
            try:
                decoded_payload = self.uns_client.get_payload_as_dict(
                    topic=msg.topic,
                    payload=msg.payload,
                    mqtt_ignored_attributes=MQTTConfig.ignored_attributes,
                )
            except Exception:
                decoded_payload = None
        else:
            try:
                decoded_payload = self.uns_client.get_payload_as_dict(
                    topic=msg.topic,
                    payload=msg.payload,
                    mqtt_ignored_attributes=MQTTConfig.ignored_attributes,
                )
            except Exception:
                decoded_payload = {}

        token = ReceiptToken(self.owner.connection_generation, msg.mid, msg.qos)
        if msg.qos == 0:
            self.owner.ingest_qos0(msg.topic, msg.payload, decoded_payload)
        elif msg.qos == 1:
            self.mqtt_ack.register(token, msg)
            self.owner.ingest_qos1(token, msg.topic, msg.payload, decoded_payload)
            INGEST_ACCEPTED.labels(shard=self.ingestion_config.shard_id).inc()
        self._sync_readiness()
        self.kafka_handler.poll(0)

    def on_disconnect(
        self,
        client,  # noqa: ARG002
        userdata,  # noqa: ARG002
        flags,  # noqa: ARG002
        reason_codes,
        properties=None,  # noqa: ARG002
    ):
        LOGGER.debug("MQTT ingestion shard disconnected: %s", reason_codes)
        self._sync_readiness()
        self.kafka_handler.flush(1)

    def _sync_readiness(self) -> None:
        ready = self.owner.ready and not self.owner.halted
        INGEST_READY.labels(shard=self.ingestion_config.shard_id).set(1 if ready else 0)
        set_ingestion_ready(ready)
        if self.owner.halted:
            set_ingestion_halted(True, self.owner.halt_reason or "halted")
        if not ready:
            INGEST_BACKPRESSURE.labels(
                shard=self.ingestion_config.shard_id,
                reason=self.owner.halt_reason or "backpressure",
            ).inc()
        if self.owner.disconnect_requested:
            LOGGER.warning(
                "Ingestion shard %s requested controlled disconnect; backoff=%ss",
                self.ingestion_config.shard_id,
                self.owner.next_backoff_seconds(),
            )


def main():
    mapper = None
    try:
        mapper = UNSKafkaMapper()
        mapper.uns_client.loop_forever(retry_first_connection=True)
    finally:
        if mapper is not None:
            mapper.owner.shutdown()
            mapper.kafka_handler.flush(10)
            mapper.uns_client.disconnect()


if __name__ == "__main__":
    main()
