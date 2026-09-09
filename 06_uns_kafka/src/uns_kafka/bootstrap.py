"""Idempotent Kafka topic bootstrap for the canonical historic event pipeline."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Protocol

from confluent_kafka.admin import AdminClient, ConfigResource, NewTopic, ResourceType
from uns_config import get_settings
from uns_config.kafka import sanitize_kafka_config
from uns_kafka.rejections import DLQ_TOPIC

LOGGER = logging.getLogger(__name__)

HISTORIC_TOPIC = "uns.historic-events"
SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000
THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000

settings = get_settings("default")


class TopicMismatchError(RuntimeError):
    """Existing broker topic settings do not match the required pipeline contract."""


@dataclass(frozen=True, slots=True)
class TopicSpec:
    name: str
    partitions: int
    replication_factor: int
    retention_ms: int
    cleanup_policy: str = "delete"
    min_insync_replicas: str = "1"

    def new_topic_configs(self) -> dict[str, str]:
        return {
            "cleanup.policy": self.cleanup_policy,
            "retention.ms": str(self.retention_ms),
            "min.insync.replicas": self.min_insync_replicas,
        }


class AdminPort(Protocol):
    def list_topics(self, timeout: float | None = None): ...

    def create_topics(self, new_topics, **kwargs): ...

    def describe_configs(self, resources, **kwargs): ...


def load_topic_specs() -> tuple[TopicSpec, TopicSpec]:
    bootstrap = settings.get("kafka_bootstrap", {})
    historic = bootstrap.get("historic_topic", {})
    dlq = bootstrap.get("dlq_topic", {})
    return (
        TopicSpec(
            name=historic.get("name", HISTORIC_TOPIC),
            partitions=int(historic.get("partitions", 12)),
            replication_factor=int(historic.get("replication_factor", 1)),
            retention_ms=int(historic.get("retention_ms", SEVEN_DAYS_MS)),
        ),
        TopicSpec(
            name=dlq.get("name", DLQ_TOPIC),
            partitions=int(dlq.get("partitions", 12)),
            replication_factor=int(dlq.get("replication_factor", 1)),
            retention_ms=int(dlq.get("retention_ms", THIRTY_DAYS_MS)),
        ),
    )


def bootstrap_config() -> dict:
    raw = settings.get("kafka_bootstrap.config")
    if raw is None:
        raw = {"bootstrap.servers": settings.get("kafka.bootstrap_servers", "localhost:9092")}
    return sanitize_kafka_config(raw)


def _config_value(configs: dict, key: str) -> str | None:
    entry = configs.get(key)
    if entry is None:
        return None
    return getattr(entry, "value", entry)


def verify_existing_topic(
    *,
    spec: TopicSpec,
    partition_count: int,
    configs: dict,
) -> None:
    mismatches: list[str] = []
    if partition_count != spec.partitions:
        mismatches.append(f"partitions={partition_count} expected={spec.partitions}")
    for key, expected in spec.new_topic_configs().items():
        actual = _config_value(configs, key)
        if actual is None:
            mismatches.append(f"missing config {key}")
            continue
        if str(actual) != str(expected):
            mismatches.append(f"{key}={actual} expected={expected}")
    if mismatches:
        raise TopicMismatchError(f"topic {spec.name} mismatch: " + "; ".join(mismatches))


def ensure_topic(admin: AdminPort, spec: TopicSpec, *, timeout: float = 10.0) -> None:
    metadata = admin.list_topics(timeout=timeout)
    topics = getattr(metadata, "topics", metadata)
    if spec.name not in topics:
        future_map = admin.create_topics(
            [
                NewTopic(
                    spec.name,
                    num_partitions=spec.partitions,
                    replication_factor=spec.replication_factor,
                    config=spec.new_topic_configs(),
                )
            ]
        )
        for future in future_map.values():
            future.result(timeout=timeout)
        LOGGER.info("Created Kafka topic %s", spec.name)
        return

    topic_meta = topics[spec.name]
    partition_count = len(topic_meta.partitions)
    resource = ConfigResource(ResourceType.TOPIC, spec.name)
    config_future = admin.describe_configs([resource])
    described = next(iter(config_future.values())).result(timeout=timeout)
    verify_existing_topic(spec=spec, partition_count=partition_count, configs=described)
    LOGGER.info("Verified Kafka topic %s", spec.name)


def ensure_pipeline_topics(admin: AdminPort | None = None) -> None:
    client = admin or AdminClient(bootstrap_config())
    historic, dlq = load_topic_specs()
    ensure_topic(client, historic)
    ensure_topic(client, dlq)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        ensure_pipeline_topics()
    except TopicMismatchError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc
    except Exception as exc:
        LOGGER.error("Kafka bootstrap failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
