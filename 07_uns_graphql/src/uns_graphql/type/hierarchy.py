"""GraphQL types for the plant hierarchy and its prefix-migrate job."""

from __future__ import annotations

import strawberry
from uns_model.hierarchy import HierarchyArea, HierarchyLine, HierarchySite, HierarchyTree


@strawberry.type(description="A line and the cells (instance tags) under it.")
class HierarchyLineType:
    name: str
    cells: list[str]

    @classmethod
    def from_line(cls, line: HierarchyLine) -> HierarchyLineType:
        return cls(name=line.name, cells=list(line.cells))


@strawberry.type(description="An area in the ISA-95 tree.")
class HierarchyAreaType:
    name: str
    kind: str
    lines: list[HierarchyLineType]

    @classmethod
    def from_area(cls, area: HierarchyArea) -> HierarchyAreaType:
        return cls(
            name=area.name,
            kind=area.kind,
            lines=[HierarchyLineType.from_line(line) for line in area.lines],
        )


@strawberry.type(description="A site and the areas under it.")
class HierarchySiteType:
    name: str
    areas: list[HierarchyAreaType]

    @classmethod
    def from_site(cls, site: HierarchySite) -> HierarchySiteType:
        return cls(name=site.name, areas=[HierarchyAreaType.from_area(area) for area in site.areas])


@strawberry.type(description="The ISA-95 tree stored in plant.yaml.")
class HierarchyTreeType:
    enterprise: str
    sites: list[HierarchySiteType]

    @classmethod
    def from_tree(cls, tree: HierarchyTree) -> HierarchyTreeType:
        return cls(
            enterprise=tree.enterprise,
            sites=[HierarchySiteType.from_site(site) for site in tree.sites],
        )


@strawberry.type(description="One-at-a-time prefix migrate of historian topics and graph nodes.")
class HierarchyMigrateJob:
    status: str
    old_prefix: str | None = None
    new_prefix: str | None = None
    rewritten: int | None = None
    error: str | None = None


@strawberry.type(description="The tree as stored, plus the migrate job that save started or left idle.")
class HierarchySaveResult:
    tree: HierarchyTreeType
    job: HierarchyMigrateJob
