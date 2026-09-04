"""Access Groups: persistence for named Asset-tree roots and their members.

Callers get `AccessGroupRecord`s and never a `Session`. Validation that does not
need the database lives in `validate_group_save` so unit tests can cover it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uns_model.access import DEMO_SUBJECTS, OPERATOR_AREA_SEGMENT, VIEWER_AREA_SEGMENT
from uns_model.engine import Database
from uns_model.tables import AccessGroup, AccessGroupMember, AccessGroupRoot, Asset


@dataclass(frozen=True, slots=True)
class AccessGroupRecord:
    id: int
    name: str
    root_asset_ids: tuple[int, ...]
    root_paths: tuple[str, ...]
    root_segments: tuple[str, ...]
    subjects: tuple[str, ...]


def area_group_name(segment: str) -> str:
    """Access Group name for a seeded Area: the segment, not a WTP label."""
    return segment


def validate_group_save(name: str, root_asset_ids: Sequence[int]) -> str:
    """Trim `name` and reject a blank name or an empty root list."""
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("The group needs a name.")
    if not root_asset_ids:
        raise ValueError("An Access Group needs at least one root Asset.")
    return trimmed


def _unique_ids(asset_ids: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    unique: list[int] = []
    for asset_id in asset_ids:
        if asset_id in seen:
            continue
        seen.add(asset_id)
        unique.append(asset_id)
    return unique


class AccessGroupRepository:
    """Named Access Groups, their Asset roots, and Keycloak member subjects."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_groups(self) -> list[AccessGroupRecord]:
        async with self._database.session() as session:
            groups = list(
                (await session.execute(select(AccessGroup).order_by(AccessGroup.name, AccessGroup.id))).scalars()
            )
            return await self._records_for(session, groups)

    async def get_group(self, group_id: int) -> AccessGroupRecord | None:
        async with self._database.session() as session:
            group = (
                await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))
            ).scalar_one_or_none()
            if group is None:
                return None
            return (await self._records_for(session, [group]))[0]

    async def save_group(
        self, group_id: int | None, name: str, root_asset_ids: Sequence[int]
    ) -> AccessGroupRecord:
        trimmed = validate_group_save(name, root_asset_ids)
        roots = _unique_ids(root_asset_ids)
        async with self._database.session() as session:
            try:
                saved_id = await self._save_group(session, group_id, trimmed, roots)
            except IntegrityError as error:
                orig = str(getattr(error, "orig", error))
                if "uq_access_group_name" in orig:
                    raise ValueError(f"An Access Group named {trimmed!r} already exists") from error
                raise
            group = (await session.execute(select(AccessGroup).where(AccessGroup.id == saved_id))).scalar_one()
            return (await self._records_for(session, [group]))[0]

    async def delete_group(self, group_id: int) -> bool:
        async with self._database.session() as session:
            result = await session.execute(delete(AccessGroup).where(AccessGroup.id == group_id))
            return bool(result.rowcount)

    async def set_members(self, group_id: int, subjects: Sequence[str]) -> AccessGroupRecord:
        cleaned = _unique_subjects(subjects)
        async with self._database.session() as session:
            group = (
                await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))
            ).scalar_one_or_none()
            if group is None:
                raise ValueError(f"Access Group {group_id} does not exist")
            await session.execute(delete(AccessGroupMember).where(AccessGroupMember.group_id == group_id))
            if cleaned:
                await session.execute(
                    insert(AccessGroupMember),
                    [{"group_id": group_id, "subject": subject} for subject in cleaned],
                )
            return (await self._records_for(session, [group]))[0]

    async def root_paths_for_subject(self, subject: str) -> frozenset[str]:
        async with self._database.session() as session:
            paths = (
                await session.execute(
                    select(Asset.path)
                    .join(AccessGroupRoot, AccessGroupRoot.asset_id == Asset.id)
                    .join(AccessGroupMember, AccessGroupMember.group_id == AccessGroupRoot.group_id)
                    .where(AccessGroupMember.subject == subject)
                )
            ).scalars()
            return frozenset(paths)

    async def upsert_area_groups(self, areas: Sequence[Asset]) -> list[AccessGroupRecord]:
        """One group per Area, named for `area.segment`, rooted at that Area.

        Upsert by name so a re-seed refreshes roots without deleting groups an
        admin created under other names.
        """
        records: list[AccessGroupRecord] = []
        async with self._database.session() as session:
            for area in areas:
                trimmed = validate_group_save(area_group_name(area.segment), [area.id])
                await self._require_assets(session, [area.id])
                group_id = (
                    await session.execute(
                        insert(AccessGroup)
                        .values(name=trimmed)
                        .on_conflict_do_update(
                            constraint="uq_access_group_name",
                            set_={"updated_at": func.now()},
                        )
                        .returning(AccessGroup.id)
                    )
                ).scalar_one()
                await self._replace_roots(session, group_id, [area.id])
                group = (await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))).scalar_one()
                records.extend(await self._records_for(session, [group]))
        return records

    async def apply_demo_membership(self, groups: Sequence[AccessGroupRecord]) -> None:
        """Add the pinned demo subjects. Idempotent; never adds admin."""
        engineer = DEMO_SUBJECTS["engineer.user"]
        auditor = DEMO_SUBJECTS["auditor.user"]
        operator = DEMO_SUBJECTS["operator.user"]
        viewer = DEMO_SUBJECTS["viewer.user"]
        rows: list[dict[str, int | str]] = []
        seen: set[tuple[int, str]] = set()
        for group in groups:
            subjects = [engineer, auditor]
            if OPERATOR_AREA_SEGMENT in group.root_segments:
                subjects.append(operator)
            if VIEWER_AREA_SEGMENT in group.root_segments:
                subjects.append(viewer)
            for subject in subjects:
                key = (group.id, subject)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"group_id": group.id, "subject": subject})
        if not rows:
            return
        async with self._database.session() as session:
            await session.execute(insert(AccessGroupMember).on_conflict_do_nothing(), rows)

    async def _save_group(
        self, session: AsyncSession, group_id: int | None, name: str, root_asset_ids: Sequence[int]
    ) -> int:
        await self._require_assets(session, root_asset_ids)
        clash = (
            await session.execute(select(AccessGroup).where(AccessGroup.name == name))
        ).scalar_one_or_none()
        if clash is not None and clash.id != group_id:
            raise ValueError(f"An Access Group named {name!r} already exists")
        if group_id is None:
            saved_id = (
                await session.execute(insert(AccessGroup).values(name=name).returning(AccessGroup.id))
            ).scalar_one()
        else:
            group = (
                await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))
            ).scalar_one_or_none()
            if group is None:
                raise ValueError(f"Access Group {group_id} does not exist")
            await session.execute(
                update(AccessGroup).where(AccessGroup.id == group_id).values(name=name, updated_at=func.now())
            )
            session.expire(group)
            saved_id = group_id
        await self._replace_roots(session, saved_id, root_asset_ids)
        return saved_id

    async def _require_assets(self, session: AsyncSession, asset_ids: Sequence[int]) -> None:
        found = set((await session.execute(select(Asset.id).where(Asset.id.in_(list(asset_ids))))).scalars().all())
        missing = [asset_id for asset_id in asset_ids if asset_id not in found]
        if missing:
            raise ValueError(f"Asset {missing[0]} does not exist")

    async def _replace_roots(self, session: AsyncSession, group_id: int, asset_ids: Sequence[int]) -> None:
        await session.execute(delete(AccessGroupRoot).where(AccessGroupRoot.group_id == group_id))
        await session.execute(
            insert(AccessGroupRoot),
            [{"group_id": group_id, "asset_id": asset_id} for asset_id in asset_ids],
        )

    async def _records_for(self, session: AsyncSession, groups: Sequence[AccessGroup]) -> list[AccessGroupRecord]:
        if not groups:
            return []
        ids = [group.id for group in groups]
        root_rows = (
            await session.execute(
                select(AccessGroupRoot.group_id, AccessGroupRoot.asset_id, Asset.path, Asset.segment)
                .join(Asset, Asset.id == AccessGroupRoot.asset_id)
                .where(AccessGroupRoot.group_id.in_(ids))
                .order_by(AccessGroupRoot.group_id, Asset.path)
            )
        ).all()
        member_rows = (
            await session.execute(
                select(AccessGroupMember.group_id, AccessGroupMember.subject)
                .where(AccessGroupMember.group_id.in_(ids))
                .order_by(AccessGroupMember.group_id, AccessGroupMember.subject)
            )
        ).all()
        roots_by_group: dict[int, list[tuple[int, str, str]]] = {group_id: [] for group_id in ids}
        for group_id, asset_id, path, segment in root_rows:
            roots_by_group[group_id].append((asset_id, path, segment))
        subjects_by_group: dict[int, list[str]] = {group_id: [] for group_id in ids}
        for group_id, subject in member_rows:
            subjects_by_group[group_id].append(subject)
        return [
            AccessGroupRecord(
                id=group.id,
                name=group.name,
                root_asset_ids=tuple(row[0] for row in roots_by_group[group.id]),
                root_paths=tuple(row[1] for row in roots_by_group[group.id]),
                root_segments=tuple(row[2] for row in roots_by_group[group.id]),
                subjects=tuple(subjects_by_group[group.id]),
            )
            for group in groups
        ]


def _unique_subjects(subjects: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for subject in subjects:
        value = subject.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


__all__ = ["AccessGroupRecord", "AccessGroupRepository", "area_group_name", "validate_group_save"]
