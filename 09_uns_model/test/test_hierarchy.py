"""Tests for the ISA-95 hierarchy tree and prefix rename validation."""

from uns_model.hierarchy import (
    HierarchyArea,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
    PrefixRename,
    all_prefixes,
    validate_renames,
    validate_tree,
)
from uns_model.topic_path import join_segments, validate_segment


def test_join_and_split_round_trip():
    assert join_segments("Acme", "Site1", "RawWater") == "Acme/Site1/RawWater"


def test_a_slash_in_a_segment_is_rejected():
    try:
        validate_segment("Site/1")
    except ValueError as exc:
        assert "Site/1" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_duplicate_sibling_cells_are_rejected():
    tree = HierarchyTree(
        enterprise="E",
        sites=(HierarchySite("S", (HierarchyArea("A", "production", (HierarchyLine("L", ("V101", "V101")),)),)),),
    )
    try:
        validate_tree(tree)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_rename_must_exist_on_the_previous_tree():
    prev = HierarchyTree("E", (HierarchySite("S1", ()),))
    new = HierarchyTree("E", (HierarchySite("S2", ()),))
    try:
        validate_renames(new, prev, (PrefixRename("E/S9", "E/S2"),))
    except ValueError:
        return
    raise AssertionError("expected ValueError")
