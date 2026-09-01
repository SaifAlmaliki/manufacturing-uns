"""Maps configured OPC UA nodes onto Unified Namespace topics."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from uns_opcua.opcua_config import Deadband, ServerConfig

PAYLOAD_LEAF = "value"
"""The payload key this connector always publishes its scalar under."""


def derive_topic(asset: str, metric_path: str) -> str:
    """
    The published topic is the Asset path followed by the topic segments below it.

    `metric_path` is deliberately the Asset Model's name for those segments, not Metric
    Key: a Metric Key also carries the dotted path inside the payload, which is one
    segment too many for a topic.
    """
    asset = asset.strip("/")
    if not asset:
        raise ValueError("A tag's asset must not be empty")
    metric_path = metric_path.strip("/")
    return f"{asset}/{metric_path}" if metric_path else asset


@dataclass(frozen=True, slots=True)
class TagBinding:
    """A resolved mapping from one OPC UA node to one UNS topic."""

    node_id: str
    topic: str
    asset: str
    metric_path: str
    unit: str | None
    deadband: Deadband | None
    equipment: str
    server_name: str

    @property
    def metric_key(self) -> str:
        """
        The Metric Key a MetricDefinition is keyed by: the topic segments below the
        Asset plus the dotted path within the payload, e.g.
        `ProcessValue/Temperature/value`.
        """
        return f"{self.metric_path}/{PAYLOAD_LEAF}" if self.metric_path else PAYLOAD_LEAF


def build_bindings(server: ServerConfig) -> tuple[TagBinding, ...]:
    """Resolve every tag of one server into a TagBinding."""
    return tuple(
        TagBinding(
            node_id=tag.node_id,
            topic=derive_topic(tag.asset, tag.metric_path),
            asset=tag.asset,
            metric_path=tag.metric_path,
            unit=tag.unit,
            deadband=tag.deadband,
            equipment=tag.asset.strip("/").rsplit("/", maxsplit=1)[-1],
            server_name=server.name,
        )
        for tag in server.tags
    )


def find_conflicts(bindings: Sequence[TagBinding]) -> list[str]:
    """
    Human-readable descriptions of mappings that cannot both be right.

    node_id is scoped per server, because the same address on two PLCs is ordinary.
    A topic is global: two tags publishing to one topic would overwrite each other.
    """
    conflicts: list[str] = []

    node_ids = Counter((binding.server_name, binding.node_id) for binding in bindings)
    for (server_name, node_id), count in sorted(node_ids.items()):
        if count > 1:
            conflicts.append(f"{server_name}: duplicate node_id {node_id!r} appears {count} times")

    topics = Counter(binding.topic for binding in bindings)
    for topic, count in sorted(topics.items()):
        if count > 1:
            conflicts.append(f"duplicate topic {topic!r} is produced by {count} tags")

    return conflicts
