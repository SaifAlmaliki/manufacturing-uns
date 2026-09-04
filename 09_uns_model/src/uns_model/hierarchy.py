"""
Pure ISA-95 hierarchy types and validators.

The hierarchy is `Enterprise > Site > Area > Line > Cell`. Each level carries a
name that must be a legal single topic segment (no `/`, non-empty), so that the
path to any node — `Enterprise/Site/Area/Line/Cell` — is a well-formed MQTT
prefix. This module is deliberately free of database and I/O concerns: it only
checks shapes and computes prefixes, so it can be tested exhaustively without
Postgres or YAML.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from uns_model.topic_path import SEPARATOR, join_segments, validate_segment

DEFAULT_AREA_KIND = "production"


@dataclass(frozen=True, slots=True)
class HierarchyLine:
    name: str
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HierarchyArea:
    name: str
    kind: str
    lines: tuple[HierarchyLine, ...]


@dataclass(frozen=True, slots=True)
class HierarchySite:
    name: str
    areas: tuple[HierarchyArea, ...]


@dataclass(frozen=True, slots=True)
class HierarchyTree:
    enterprise: str
    sites: tuple[HierarchySite, ...]


@dataclass(frozen=True, slots=True)
class PrefixRename:
    old_prefix: str
    new_prefix: str


def _site_prefix(enterprise: str, site: str) -> str:
    return join_segments(enterprise, site)


def _area_prefix(enterprise: str, site: str, area: str) -> str:
    return join_segments(enterprise, site, area)


def _line_prefix(enterprise: str, site: str, area: str, line: str) -> str:
    return join_segments(enterprise, site, area, line)


def _cell_prefix(enterprise: str, site: str, area: str, line: str, cell: str) -> str:
    return join_segments(enterprise, site, area, line, cell)


def _coerce_lines(raw: object) -> tuple[HierarchyLine, ...]:
    if isinstance(raw, Mapping):
        items = raw.items()
    else:
        items = ((entry["name"], entry) for entry in raw)  # type: ignore[union-attr]
    lines: list[HierarchyLine] = []
    for name, body in items:
        cells = tuple(body.get("cells", ())) if isinstance(body, Mapping) else tuple(getattr(body, "cells", ()))
        lines.append(HierarchyLine(name=name, cells=cells))
    return tuple(lines)


def _coerce_areas(raw: object) -> tuple[HierarchyArea, ...]:
    if isinstance(raw, Mapping):
        items = raw.items()
    else:
        items = ((entry["name"], entry) for entry in raw)  # type: ignore[union-attr]
    areas: list[HierarchyArea] = []
    for name, body in items:
        if isinstance(body, Mapping):
            kind = body.get("kind", DEFAULT_AREA_KIND)
            lines = _coerce_lines(body.get("lines", ()))
        else:
            kind = getattr(body, "kind", DEFAULT_AREA_KIND) or DEFAULT_AREA_KIND
            lines = _coerce_lines(getattr(body, "lines", ()))
        areas.append(HierarchyArea(name=name, kind=kind, lines=lines))
    return tuple(areas)


def _coerce_sites(raw: object) -> tuple[HierarchySite, ...]:
    if isinstance(raw, Mapping):
        items = raw.items()
    else:
        items = ((entry["name"], entry) for entry in raw)  # type: ignore[union-attr]
    sites: list[HierarchySite] = []
    for name, body in items:
        areas = _coerce_areas(body.get("areas", ())) if isinstance(body, Mapping) else _coerce_areas(getattr(body, "areas", ()))
        sites.append(HierarchySite(name=name, areas=areas))
    return tuple(sites)


def tree_from_mapping(raw: Mapping[str, object]) -> HierarchyTree:
    """Build a :class:`HierarchyTree` from a nested mapping.

    Accepts either dict-of-children or list-of-objects shapes; missing area
    kinds default to ``"production"``.
    """
    enterprise = raw["enterprise"]
    sites = _coerce_sites(raw.get("sites", ()))
    return HierarchyTree(enterprise=str(enterprise), sites=sites)


def tree_to_mapping(tree: HierarchyTree) -> dict[str, object]:
    """Project a tree to the list-of-objects shape plant.yaml and seed consume."""
    return {
        "enterprise": tree.enterprise,
        "sites": [
            {
                "name": site.name,
                "areas": [
                    {
                        "name": area.name,
                        "kind": area.kind or DEFAULT_AREA_KIND,
                        "lines": [{"name": line.name, "cells": list(line.cells)} for line in area.lines],
                    }
                    for area in site.areas
                ],
            }
            for site in tree.sites
        ],
    }


def _require_unique(names: Sequence[str], label: str, parent: str) -> None:
    seen: set[str] = set()
    for name in names:
        validate_segment(name)
        if name in seen:
            raise ValueError(f"duplicate {label} under {parent!r}: {name!r}")
        seen.add(name)


def validate_tree(tree: HierarchyTree) -> None:
    """Validate the structural invariants of a hierarchy tree.

    - enterprise is non-empty and a legal segment;
    - sibling names are unique at every level;
    - every name passes :func:`validate_segment`.
    """
    if not tree.enterprise:
        raise ValueError("enterprise must be non-empty")
    validate_segment(tree.enterprise)

    _require_unique([site.name for site in tree.sites], "site", tree.enterprise)
    for site in tree.sites:
        _require_unique([area.name for area in site.areas], "area", f"{tree.enterprise}/{site.name}")
        for area in site.areas:
            if not area.kind:
                raise ValueError(f"area kind must be non-empty: {area.name!r}")
            _require_unique(
                [line.name for line in area.lines],
                "line",
                f"{tree.enterprise}/{site.name}/{area.name}",
            )
            for line in area.lines:
                _require_unique(
                    line.cells,
                    "cell",
                    f"{tree.enterprise}/{site.name}/{area.name}/{line.name}",
                )


def all_prefixes(tree: HierarchyTree) -> frozenset[str]:
    """Every node path in the tree, from the enterprise down to each cell."""
    prefixes: set[str] = {tree.enterprise}
    for site in tree.sites:
        site_prefix = _site_prefix(tree.enterprise, site.name)
        prefixes.add(site_prefix)
        for area in site.areas:
            area_prefix = _area_prefix(tree.enterprise, site.name, area.name)
            prefixes.add(area_prefix)
            for line in area.lines:
                line_prefix = _line_prefix(tree.enterprise, site.name, area.name, line.name)
                prefixes.add(line_prefix)
                for cell in line.cells:
                    prefixes.add(_cell_prefix(tree.enterprise, site.name, area.name, line.name, cell))
    return frozenset(prefixes)


def _is_parent_of(parent: str, child: str) -> bool:
    """True if `parent` is a strict ancestor of `child` on whole segments."""
    return child.startswith(parent + SEPARATOR)


def validate_renames(
    tree: HierarchyTree,
    previous: HierarchyTree,
    renames: Sequence[PrefixRename],
) -> None:
    """Validate a batch of prefix renames between two trees.

    - each ``old_prefix`` exists on ``previous``;
    - each ``new_prefix`` exists on ``tree``;
    - an ``old_prefix`` is not on ``tree`` unless it equals its ``new_prefix``
      (a no-op rename leaves the prefix in place);
    - renames do not overlap: no ``old_prefix`` is a parent of another rename's
      ``old_prefix``.
    """
    previous_prefixes = all_prefixes(previous)
    tree_prefixes = all_prefixes(tree)

    for rename in renames:
        if rename.old_prefix not in previous_prefixes:
            raise ValueError(f"old_prefix not found on previous tree: {rename.old_prefix!r}")
        if rename.new_prefix not in tree_prefixes:
            raise ValueError(f"new_prefix not found on new tree: {rename.new_prefix!r}")
        if rename.old_prefix != rename.new_prefix and rename.old_prefix in tree_prefixes:
            raise ValueError(f"old_prefix still present on new tree: {rename.old_prefix!r}")

    for i, outer in enumerate(renames):
        for inner in renames[i + 1 :]:
            if _is_parent_of(outer.old_prefix, inner.old_prefix) or _is_parent_of(
                inner.old_prefix, outer.old_prefix
            ):
                raise ValueError(
                    f"overlapping rename prefixes: {outer.old_prefix!r} and {inner.old_prefix!r}"
                )
