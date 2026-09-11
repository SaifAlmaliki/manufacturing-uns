"""Explicit Kafka replay start selection."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

InitialPosition = Literal["require_committed", "earliest", "latest"]

VALID_INITIAL_POSITIONS: frozenset[str] = frozenset({"require_committed", "earliest", "latest"})


class ReplayError(Exception):
    """Invalid or unavailable replay start position."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def choose_start(
    committed: int | None,
    low: int,
    high: int,
    initial_position: InitialPosition = "require_committed",
) -> int:
    """Select the next offset to consume for one partition assignment."""
    if initial_position not in VALID_INITIAL_POSITIONS:
        raise ValueError(f"unsupported initial_position {initial_position!r}")

    if committed is not None:
        if committed < low:
            raise ReplayError("data_gap")
        if committed > high:
            raise ReplayError("invalid_position")
        return committed

    if initial_position == "require_committed":
        raise ReplayError("initial_position_required")
    if initial_position == "earliest":
        return low
    return high


def resolve_partition_starts(
    partitions: Sequence[tuple[str, int]],
    *,
    committed_for: Callable[[str, int], int | None],
    watermarks_for: Callable[[str, int], tuple[int, int]],
    initial_position: InitialPosition = "require_committed",
) -> dict[tuple[str, int], int]:
    """Resolve replay starts for every assigned partition."""
    starts: dict[tuple[str, int], int] = {}
    for topic, partition in partitions:
        low, high = watermarks_for(topic, partition)
        starts[(topic, partition)] = choose_start(
            committed_for(topic, partition),
            low,
            high,
            initial_position,
        )
    return starts
