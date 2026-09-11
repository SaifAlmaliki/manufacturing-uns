"""Lightweight MQTT -> Kafka mapper for the qualification canonical/lake fixture."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import sys
import time
from typing import Any

import paho.mqtt.client as mqtt
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

MQTT_HOST = os.environ.get("CLOUD_MQTT_HOST", "cloud-mqtt")
MQTT_PORT = int(os.environ.get("CLOUD_MQTT_PORT", "1883"))
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "cloud-kafka:29092")
HISTORIC_TOPIC = os.environ.get("HISTORIC_TOPIC", "uns.historic-events")
SITE_ID = os.environ.get("QUALIFICATION_SITE_ID", "cloud-edge-qualification")
BOOT_ID = os.environ.get("QUALIFICATION_BOOT_ID", "cloud-edge-qualification-boot")


def _tuple_digest(parts: tuple[Any, ...]) -> str:
    wire = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


def _source_event_id(site_id: str, source_id: str, boot_id: str, sequence: int) -> str:
    return f"source:{_tuple_digest((site_id, source_id, boot_id, sequence))}"


def _historic_envelope(topic: str, payload: bytes) -> dict[str, Any]:
    try:
        publication = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        publication = {}
    if publication.get("publication_version") == 1:
        site_id = publication.get("site_id", SITE_ID)
        source_id = f"{site_id}/{publication.get('source_application', 'unknown')}-01"
        sequence = int(publication.get("source_sequence", 0))
        event_id = _source_event_id(site_id, source_id, BOOT_ID, sequence)
        original = base64.b64decode(publication.get("original_payload_base64", ""))
        return {
            "schema_version": 1,
            "event_id": event_id,
            "topic": topic,
            "site_id": site_id,
            "source_id": source_id,
            "source_sequence": sequence,
            "original_payload_base64": base64.b64encode(original).decode("ascii"),
            "occurred_at": publication.get("occurred_at"),
        }
    event_id = _source_event_id(SITE_ID, topic.replace("/", ":"), BOOT_ID, int(time.time()))
    return {
        "schema_version": 1,
        "event_id": event_id,
        "topic": topic,
        "site_id": SITE_ID,
        "original_payload_base64": base64.b64encode(payload).decode("ascii"),
    }


def _ensure_topic() -> None:
    admin = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP})
    futures = admin.create_topics([NewTopic(HISTORIC_TOPIC, num_partitions=1, replication_factor=1)])
    for future in futures.values():
        try:
            future.result(timeout=10)
        except Exception:
            pass


def main() -> None:
    _ensure_topic()
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})

    def on_message(_client, _userdata, message) -> None:  # noqa: ANN001
        envelope = _historic_envelope(message.topic, message.payload)
        producer.produce(
            HISTORIC_TOPIC,
            key=envelope["event_id"].encode("utf-8"),
            value=json.dumps(envelope, separators=(",", ":")).encode("utf-8"),
        )
        producer.poll(0)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="qualification-kafka-mapper")
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.subscribe("Enterprise/#", qos=1)
    client.loop_start()

    def shutdown(*_args: object) -> None:
        producer.flush(5)
        client.loop_stop()
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while True:
        producer.poll(0.5)


if __name__ == "__main__":
    main()
