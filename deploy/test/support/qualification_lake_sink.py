"""Kafka -> MinIO lake sink for the qualification canonical/lake fixture."""

from __future__ import annotations

import io
import json
import os
import signal
import sys
import time

from confluent_kafka import Consumer, KafkaException
from minio import Minio
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "cloud-kafka:29092")
HISTORIC_TOPIC = os.environ.get("HISTORIC_TOPIC", "uns.historic-events")
LAKE_BUCKET = os.environ.get("LAKE_BUCKET", "uns-historic-events")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "cloud-minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "qualification")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "qualification-test-only")


def _client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )


def _ensure_bucket(client: Minio) -> None:
    if not client.bucket_exists(LAKE_BUCKET):
        client.make_bucket(LAKE_BUCKET)


def main() -> None:
    minio = _client()
    _ensure_bucket(minio)
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": "qualification-lake-sink",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe([HISTORIC_TOPIC])

    def shutdown(*_args: object) -> None:
        consumer.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        message = consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            raise KafkaException(message.error())
        payload = json.loads(message.value().decode("utf-8"))
        event_id = payload.get("event_id", "unknown")
        row = {
            "event_id": event_id,
            "topic": payload.get("topic"),
            "site_id": payload.get("site_id"),
            "kafka_partition": message.partition(),
            "kafka_offset": message.offset(),
            "payload": payload,
        }
        object_name = f"events/{event_id}/{message.partition()}-{message.offset()}.json"
        body = json.dumps(row, separators=(",", ":")).encode("utf-8")
        minio.put_object(
            LAKE_BUCKET,
            object_name,
            io.BytesIO(body),
            length=len(body),
            content_type="application/json",
        )
        print(
            json.dumps(
                {
                    "lake_sink": {
                        "event_id": event_id,
                        "object_name": object_name,
                        "kafka_offset": message.offset(),
                    }
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
