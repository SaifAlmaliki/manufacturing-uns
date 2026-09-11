"""Replay start selection tests."""

from __future__ import annotations

import pytest

from uns_datalake.replay import ReplayError, choose_start, resolve_partition_starts


@pytest.mark.parametrize(
    ("committed", "low", "high", "initial_position", "expected"),
    [
        (10, 5, 20, "require_committed", 10),
        (0, 0, 0, "require_committed", 0),
        (None, 0, 0, "earliest", 0),
        (None, 0, 0, "latest", 0),
        (None, 5, 20, "earliest", 5),
        (None, 5, 20, "latest", 20),
    ],
)
def test_choose_start_valid_positions(committed, low, high, initial_position, expected):
    assert choose_start(committed, low, high, initial_position) == expected


def test_committed_before_retained_low_is_data_gap_even_with_earliest():
    with pytest.raises(ReplayError, match="data_gap") as exc:
        choose_start(3, 5, 20, "earliest")
    assert exc.value.reason == "data_gap"


def test_committed_after_high_is_invalid_position():
    with pytest.raises(ReplayError, match="invalid_position") as exc:
        choose_start(25, 5, 20, "require_committed")
    assert exc.value.reason == "invalid_position"


def test_missing_committed_requires_explicit_initial_position():
    with pytest.raises(ReplayError, match="initial_position_required") as exc:
        choose_start(None, 5, 20, "require_committed")
    assert exc.value.reason == "initial_position_required"


def test_empty_partition_without_committed_requires_explicit_position():
    with pytest.raises(ReplayError, match="initial_position_required"):
        choose_start(None, 0, 0, "require_committed")


def test_numeric_gap_in_log_does_not_block_valid_committed_replay():
    # Offsets 11-14 may be missing while committed=10 remains readable at low=10.
    assert choose_start(10, 10, 20, "require_committed") == 10


def test_resolve_partition_starts_applies_policy_per_partition():
    starts = resolve_partition_starts(
        [("uns.historic-events", 0), ("uns.historic-events", 1)],
        committed_for=lambda topic, partition: 7 if partition == 0 else None,
        watermarks_for=lambda topic, partition: (5, 20),
        initial_position="earliest",
    )
    assert starts[("uns.historic-events", 0)] == 7
    assert starts[("uns.historic-events", 1)] == 5


def test_resolve_partition_starts_surfaces_data_gap():
    with pytest.raises(ReplayError, match="data_gap"):
        resolve_partition_starts(
            [("uns.historic-events", 0)],
            committed_for=lambda topic, partition: 3,
            watermarks_for=lambda topic, partition: (5, 20),
            initial_position="earliest",
        )
