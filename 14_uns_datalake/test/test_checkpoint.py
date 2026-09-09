import pytest

from uns_datalake.checkpoint import Checkpoint


def test_explicit_partition_next_offsets_and_clear():
    checkpoint = Checkpoint()
    checkpoint.observe("uns.historic-events", 0, 10)
    checkpoint.observe("uns.historic-events", 1, 40)
    checkpoint.observe("uns.historic-events", 0, 11)
    assert {(p.partition, p.offset) for p in checkpoint.next_offsets()} == {(0, 12), (1, 41)}
    checkpoint.clear()
    assert checkpoint.next_offsets() == []


def test_decreasing_offset_is_rejected():
    checkpoint = Checkpoint()
    checkpoint.observe("uns.historic-events", 0, 10)
    with pytest.raises(ValueError):
        checkpoint.observe("uns.historic-events", 0, 9)
