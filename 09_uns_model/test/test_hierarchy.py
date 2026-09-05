"""Tests for the ISA-95 hierarchy tree and prefix rename validation."""

from uns_model.hierarchy import (
    HierarchyArea,
    HierarchyCell,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
    PrefixRename,
    all_prefixes,
    tree_from_mapping,
    tree_to_mapping,
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
        sites=(HierarchySite("S", (HierarchyArea("A", "production", (HierarchyLine("L", (HierarchyCell("V101"), HierarchyCell("V101"))),)),)),),
    )
    try:
        validate_tree(tree)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_cell_mapping_coerces_authored_machines():
    tree = tree_from_mapping(
        {
            "enterprise": "E",
            "sites": [
                {
                    "name": "S",
                    "areas": [
                        {
                            "name": "A",
                            "kind": "production",
                            "lines": [{"name": "L", "cells": [{"name": "V101", "machines": ["Dryer"]}]}],
                        }
                    ],
                }
            ],
        }
    )
    assert tree.sites[0].areas[0].lines[0].cells == (HierarchyCell("V101", ("Dryer",)),)


def test_string_cells_coerce_to_cells_with_no_machines():
    tree = tree_from_mapping(
        {
            "enterprise": "E",
            "sites": [
                {
                    "name": "S",
                    "areas": [
                        {
                            "name": "A",
                            "kind": "production",
                            "lines": [{"name": "L", "cells": ["V101", {"name": "P101"}]}],
                        }
                    ],
                }
            ],
        }
    )
    cells = tree.sites[0].areas[0].lines[0].cells
    assert cells == (HierarchyCell("V101"), HierarchyCell("P101"))


def test_tree_to_mapping_writes_cell_objects():
    tree = HierarchyTree(
        "E",
        (
            HierarchySite(
                "S",
                (
                    HierarchyArea(
                        "A",
                        "production",
                        (HierarchyLine("L", (HierarchyCell("V101", ("Dryer",)),)),),
                    ),
                ),
            ),
        ),
    )
    assert tree_to_mapping(tree)["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": ["Dryer"]}
    ]


def test_all_prefixes_include_machines():
    tree = HierarchyTree(
        "E",
        (
            HierarchySite(
                "S",
                (
                    HierarchyArea(
                        "A",
                        "production",
                        (HierarchyLine("L", (HierarchyCell("V101", ("Dryer",)),)),),
                    ),
                ),
            ),
        ),
    )
    assert "E/S/A/L/V101/Dryer" in all_prefixes(tree)


def test_duplicate_sibling_machines_are_rejected():
    tree = HierarchyTree(
        "E",
        (
            HierarchySite(
                "S",
                (
                    HierarchyArea(
                        "A",
                        "production",
                        (HierarchyLine("L", (HierarchyCell("V101", ("Dryer", "Dryer")),)),),
                    ),
                ),
            ),
        ),
    )
    try:
        validate_tree(tree)
    except ValueError as exc:
        assert "Dryer" in str(exc)
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
