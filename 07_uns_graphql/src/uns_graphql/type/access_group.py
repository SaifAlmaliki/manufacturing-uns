"""GraphQL types for Access Groups: named Asset-tree roots and their members."""

from __future__ import annotations

import strawberry
from uns_model.access_repository import AccessGroupRecord


@strawberry.type(description="One Asset root of an Access Group.")
class AccessGroupRootType:
    asset_id: int
    path: str
    segment: str
    level: str


@strawberry.type(description="A named Access Group: who may see which Asset subtree.")
class AccessGroupType:
    id: int
    name: str
    roots: list[AccessGroupRootType]
    subjects: list[str]

    @classmethod
    def from_record(cls, record: AccessGroupRecord) -> AccessGroupType:
        roots = [
            AccessGroupRootType(
                asset_id=asset_id,
                path=path,
                segment=segment,
                level=level,
            )
            for asset_id, path, segment, level in zip(
                record.root_asset_ids,
                record.root_paths,
                record.root_segments,
                record.root_levels,
                strict=True,
            )
        ]
        return cls(id=record.id, name=record.name, roots=roots, subjects=list(record.subjects))
