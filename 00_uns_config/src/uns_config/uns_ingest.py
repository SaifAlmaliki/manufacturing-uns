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

from typing import Literal

EventKind = Literal[
    "telemetry",
    "sparkplug_raw",
    "lifecycle",
    "command",
    "business_event",
    "state_snapshot",
]

SPARKPLUG_PREFIX = "spBv1.0/"
SPARKPLUG_STATE_PREFIX = "spBv1.0/STATE/"
_LIFECYCLE_MESSAGE_TYPES = frozenset({"NBIRTH", "DBIRTH", "NDEATH", "DDEATH", "STATE"})
_COMMAND_MESSAGE_TYPES = frozenset({"NCMD", "DCMD"})

UNS_WILDCARD = "#"
MAPPER_UNS_TOPICS: list[str] = [UNS_WILDCARD]
MAPPER_ENVS: tuple[str, ...] = ("graphdb", "historian", "kafka_mapper")
PLATFORM_OBSERVABILITY_PREFIX = "uns/platform/"


def is_historic_event_topic(topic: str) -> bool:
    """True when a published topic belongs in Unified Namespace history."""
    return bool(topic) and not topic.startswith(PLATFORM_OBSERVABILITY_PREFIX)


def classify_event_kind(topic: str) -> EventKind:
    """Classify MQTT traffic for the canonical historic event envelope."""
    if not topic.startswith(SPARKPLUG_PREFIX):
        return "telemetry"
    if topic.startswith(SPARKPLUG_STATE_PREFIX):
        return "lifecycle"
    parts = topic.split("/")
    if len(parts) >= 3:
        message_type = parts[2]
        if message_type in _COMMAND_MESSAGE_TYPES:
            return "command"
        if message_type in _LIFECYCLE_MESSAGE_TYPES:
            return "lifecycle"
    return "sparkplug_raw"
