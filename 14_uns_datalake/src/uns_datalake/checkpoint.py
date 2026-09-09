"""Explicit Kafka offset helpers for upload-before-commit semantics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from confluent_kafka import TopicPartition

from uns_datalake.batch import LakeRecord


def compute_next_offset(partition: int, handled_offsets: Iterable[int]) -> int:
    """Return the next contiguous commit offset after handled offsets."""
    if not handled_offsets:
        raise ValueError("handled_offsets must not be empty")
    ordered = sorted(set(handled_offsets))
    expected = ordered[0]
    for offset in ordered:
        if offset != expected:
            return expected
        expected += 1
    return expected


def next_offsets_for_records(records: Sequence[LakeRecord]) -> dict[tuple[str, int], int]:
    grouped: dict[tuple[str, int], list[int]] = {}
    for record in records:
        grouped.setdefault(record.partition_key, []).append(record.offset)
    return {
        key: compute_next_offset(key[1], offsets)
        for key, offsets in grouped.items()
    }


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
