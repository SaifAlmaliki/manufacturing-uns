"""Input objects for writing the plant hierarchy.

A whole tree at a time, deliberately: the console edits locally and saves once,
and there is no safe meaning for "rename one site without saying what the rest
of the plant now is".
"""

from __future__ import annotations

import strawberry
from uns_model.hierarchy import (
    DEFAULT_AREA_KIND,
    HierarchyArea,
    HierarchyCell,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
    PrefixRename,
)


@strawberry.input(description="A topic-prefix rename the console recorded while editing.")
class PrefixRenameInput:
    old_prefix: str
    new_prefix: str

    def to_rename(self) -> PrefixRename:
        return PrefixRename(old_prefix=self.old_prefix, new_prefix=self.new_prefix)


@strawberry.input(description="A work cell and the machines under it.")
class HierarchyCellInput:
    name: str
    machines: list[str] | None = None

    def to_cell(self) -> HierarchyCell:
        return HierarchyCell(name=self.name, machines=tuple(self.machines or ()))


@strawberry.input(description="A line and the cells (instance tags) under it.")
class HierarchyLineInput:
    name: str
    cells: list[HierarchyCellInput]


@strawberry.input(description="An area. kind defaults to production when omitted.")
class HierarchyAreaInput:
    name: str
    kind: str | None = None
    lines: list[HierarchyLineInput]


@strawberry.input(description="A site and the areas under it.")
class HierarchySiteInput:
    name: str
    areas: list[HierarchyAreaInput]


@strawberry.input(description="The ISA-95 tree to persist as plant.yaml.")
class HierarchyTreeInput:
    enterprise: str
    sites: list[HierarchySiteInput]

    def to_tree(self) -> HierarchyTree:
        return HierarchyTree(
            enterprise=self.enterprise,
            sites=tuple(
                HierarchySite(
                    name=site.name,
                    areas=tuple(
                        HierarchyArea(
                            name=area.name,
                            kind=area.kind or DEFAULT_AREA_KIND,
                            lines=tuple(
                                HierarchyLine(name=line.name, cells=tuple(cell.to_cell() for cell in line.cells))
                                for line in area.lines
                            ),
                        )
                        for area in site.areas
                    ),
                )
                for site in self.sites
            ),
        )
