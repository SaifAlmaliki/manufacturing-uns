"""Explicit Kafka offset helpers for upload-before-commit semantics."""

from __future__ import annotations

from collections.abc import Sequence

from confluent_kafka import TopicPartition


class ConsumedPrefix:
    """Ordered consumed-record ledger for one partition assignment generation."""

    def __init__(self) -> None:
        self._observed: list[int] = []
        self._observed_set: set[int] = set()
        self._resolved: set[int] = set()
        self._committed_floor: int | None = None

    def observe(self, offset: int) -> None:
        if self._observed and offset <= self._observed[-1]:
            raise ValueError("duplicate or out-of-order observation")
        self._observed.append(offset)
        self._observed_set.add(offset)

    def resolve(self, offset: int) -> None:
        if offset not in self._observed_set:
            raise ValueError("unknown offset")
        self._resolved.add(offset)

    def next_offset(self) -> int | None:
        last_resolved: int | None = None
        for offset in self._observed:
            if offset not in self._resolved:
                if last_resolved is None:
                    return None
                return last_resolved + 1
            last_resolved = offset
        if last_resolved is None:
            return None
        return last_resolved + 1

    def has_unresolved_before(self, offset: int) -> bool:
        for observed in self._observed:
            if observed >= offset:
                return False
            if observed not in self._resolved:
                return True
        return False

    def discard_committed(self, next_offset: int) -> None:
        if next_offset <= 0:
            raise ValueError("next_offset must be positive")
        self._committed_floor = next_offset
        remaining_observed: list[int] = []
        remaining_set: set[int] = set()
        remaining_resolved: set[int] = set()
        for offset in self._observed:
            if offset >= next_offset:
                remaining_observed.append(offset)
                remaining_set.add(offset)
                if offset in self._resolved:
                    remaining_resolved.add(offset)
        self._observed = remaining_observed
        self._observed_set = remaining_set
        self._resolved = remaining_resolved


def build_commit_partitions(next_offsets: dict[tuple[str, int], int]) -> list[TopicPartition]:
    return [
        TopicPartition(topic, partition, offset)
        for (topic, partition), offset in sorted(next_offsets.items())
    ]


def inspect_commit_result(result: list[TopicPartition] | None) -> list[tuple[int, int]]:
    """Return (partition, error_code) pairs for failed commits."""
    if not result:
        return []
    failures: list[tuple[int, int]] = []
    for partition in result:
        error = partition.error
        if error is not None:
            failures.append((partition.partition, error.code()))
    return failures


def may_commit_kafka(*, ownership_active: bool, revoked: bool) -> bool:
    return ownership_active and not revoked
