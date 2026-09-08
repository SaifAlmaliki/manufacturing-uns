"""Mapper ingest policy for the Unified Namespace.

The MQTT broker is the Unified Namespace: every producer publishes into it and
every Mapper reads from it. Historian, GraphDB, and Kafka therefore subscribe to
`MAPPER_UNS_TOPICS` (`#`) so a browse-path topic such as `Server/OpcPlc/...` is
stored the same way as an ISA-95 path.

Platform Observability (`uns/platform/...`) is not a Historic Event. Mappers
still receive those messages under `#`; `is_historic_event_topic` drops them
before persist so simulator self-telemetry never lands in Timescale or Neo4j
(ADR-0007). MQTT `#` does not match `$SYS`.
"""

from __future__ import annotations

UNS_WILDCARD = "#"
MAPPER_UNS_TOPICS: list[str] = [UNS_WILDCARD]
MAPPER_ENVS: tuple[str, ...] = ("graphdb", "historian", "kafka_mapper")
PLATFORM_OBSERVABILITY_PREFIX = "uns/platform/"


def is_historic_event_topic(topic: str) -> bool:
    """True when a published topic belongs in Unified Namespace history."""
    return bool(topic) and not topic.startswith(PLATFORM_OBSERVABILITY_PREFIX)
