"""Shared fixtures for uns_kafka tests."""

from __future__ import annotations

import socket

import pytest

from uns_kafka.bootstrap import ensure_pipeline_topics
from uns_kafka.uns_kafka_config import KAFKAConfig

_pipeline_topics_ready = False


def _kafka_reachable() -> bool:
    servers = KAFKAConfig.kafka_config_map.get("bootstrap.servers", "localhost:9092")
    host, port_text = servers.split(",")[0].split(":")
    try:
        with socket.create_connection((host, int(port_text)), timeout=2.0):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def bootstrap_pipeline_topics_for_integration(request):
    """Create uns.historic-events before integration tests subscribe to it.

    GitHub Actions Kafka has no kafka_topic_init service, and consumers do not
    auto-create topics. Compose production already runs uns_kafka_bootstrap.
    """
    global _pipeline_topics_ready
    if request.node.get_closest_marker("integrationtest") is None:
        return
    if _pipeline_topics_ready:
        return
    if not _kafka_reachable():
        return
    ensure_pipeline_topics()
    _pipeline_topics_ready = True
