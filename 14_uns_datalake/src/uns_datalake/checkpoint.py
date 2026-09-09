"""Kafka offset checkpoint tracking for safe commits."""

from __future__ import annotations

from confluent_kafka import TopicPartition


class Checkpoint:
    """Tracks highest delivered offset + 1 per partition."""

    def __init__(self) -> None:
        self._next: dict[tuple[str, int], int] = {}

    def observe(self, topic: str, partition: int, offset: int) -> None:
        key = (topic, partition)
        next_offset = offset + 1
        if key in self._next and offset < self._next[key] - 1:
            raise ValueError(f"decreasing offset for {topic}:{partition}")
        self._next[key] = max(self._next.get(key, 0), next_offset)

    def next_offsets(self) -> list[TopicPartition]:
        return [TopicPartition(topic, partition, offset) for (topic, partition), offset in sorted(self._next.items())]

    def clear(self) -> None:
        self._next.clear()

    def has_offsets(self) -> bool:
        return bool(self._next)
