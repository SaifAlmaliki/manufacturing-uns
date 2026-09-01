"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Reading and writing the authored Asset Model.

This is the seam. Callers get these methods; they are not expected to hold a
`Session` or to know that SQLAlchemy is underneath.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from uns_model.engine import Database
from uns_model.notifications import announce_asset_model_changed
from uns_model.tables import Asset, AssetLevel, MetricDefinition, TopicBinding
from uns_model.topic_path import SEPARATOR, ancestor_paths, split_topic

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AssetSpec:
    """One level of a branch to be created or updated."""

    segment: str
    level: str
    display_name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


# Longest-prefix match of a topic against Asset paths.
#
# `starts_with` rather than `LIKE :path || '/%'` on purpose: topic segments
# routinely contain underscores (`uns_group`), and `_` is a LIKE wildcard, so LIKE
# would bind `Line_1` to an Asset named `LineX1`.
_BEST_ASSET_SQL = """
    SELECT a.id, a.path
    FROM model.asset a
    WHERE a.is_active
      AND (a.path = :topic OR starts_with(:topic, a.path || '/'))
    ORDER BY length(a.path) DESC
    LIMIT 1
"""

_BIND_TOPIC_SQL = f"""
    WITH best AS ({_BEST_ASSET_SQL})
    INSERT INTO model.topic_binding (topic, asset_id, metric_path, resolved_at)
    SELECT
        :topic,
        best.id,
        CASE
            WHEN best.path IS NULL OR best.path = :topic THEN ''
            ELSE substr(:topic, length(best.path) + 2)
        END,
        now()
    FROM (SELECT 1) AS always
    LEFT JOIN best ON TRUE
    ON CONFLICT (topic) DO UPDATE
        SET asset_id = EXCLUDED.asset_id,
            metric_path = EXCLUDED.metric_path,
            resolved_at = now()
    RETURNING asset_id, metric_path
"""

# Re-resolve every known topic after the Asset Model changed. Only rows whose
# binding actually moved are written, so this is cheap to call defensively.
_REBIND_ALL_SQL = """
    UPDATE model.topic_binding tb
    SET asset_id = resolved.asset_id,
        metric_path = resolved.metric_path,
        resolved_at = now()
    FROM (
        SELECT
            tb2.topic,
            best.id AS asset_id,
            CASE
                WHEN best.path IS NULL OR best.path = tb2.topic THEN ''
                ELSE substr(tb2.topic, length(best.path) + 2)
            END AS metric_path
        FROM model.topic_binding tb2
        LEFT JOIN LATERAL (
            SELECT a.id, a.path
            FROM model.asset a
            WHERE a.is_active
              AND (a.path = tb2.topic OR starts_with(tb2.topic, a.path || '/'))
            ORDER BY length(a.path) DESC
            LIMIT 1
        ) AS best ON TRUE
    ) AS resolved
    WHERE tb.topic = resolved.topic
      AND (tb.asset_id IS DISTINCT FROM resolved.asset_id OR tb.metric_path <> resolved.metric_path)
"""


class AssetModelRepository:
    """
    The authored Asset Model: its tree, its Metric Definitions, and the derived
    Topic Bindings that make Enrichment an equality join.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ------------------------------------------------------------------ writes

    async def ensure_branch(self, specs: Sequence[AssetSpec], *, rebind: bool = True) -> Asset:
        """
        Create or update a whole branch from the root down, returning its leaf.

        Every level is upserted by path, so re-running a seed is a no-op and a
        renamed display name is picked up. Levels must get coarser-to-finer: a
        child may skip levels but may not sit above its parent.

        Rebinds Topic Bindings by default because they are derived from the tree
        (ADR-0003). Pass `rebind=False` when writing many branches in one batch,
        then call `rebind_all()` once at the end.
        """
        if not specs:
            raise ValueError("A branch needs at least one AssetSpec")

        ranks = await self.level_ranks()
        unknown = [spec.level for spec in specs if spec.level not in ranks]
        if unknown:
            raise ValueError(f"Unknown Asset Level(s): {unknown}. Known: {sorted(ranks)}")
        for parent, child in zip(specs, specs[1:], strict=False):
            if ranks[child.level] <= ranks[parent.level]:
                raise ValueError(
                    f"Asset Level '{child.level}' cannot sit under '{parent.level}': "
                    "a branch may skip levels but not invert them"
                )

        async with self._database.session() as session:
            parent_id: int | None = None
            path_segments: list[str] = []
            for spec in specs:
                path_segments.append(spec.segment)
                path = SEPARATOR.join(path_segments)
                statement = (
                    insert(Asset)
                    .values(
                        parent_id=parent_id,
                        segment=spec.segment,
                        path=path,
                        level=spec.level,
                        display_name=spec.display_name,
                        description=spec.description,
                        attributes=spec.attributes,
                    )
                    .on_conflict_do_update(
                        index_elements=["path"],
                        set_={
                            "level": spec.level,
                            "parent_id": parent_id,
                            "display_name": spec.display_name,
                            "description": spec.description,
                            "attributes": spec.attributes,
                            "updated_at": func.now(),
                        },
                    )
                    .returning(Asset.id)
                )
                parent_id = (await session.execute(statement)).scalar_one()

            # parent_id now holds the leaf's id: the loop ran at least once.
            asset = (await session.execute(select(Asset).where(Asset.id == parent_id))).scalar_one()

        if rebind:
            await self.rebind_all()
        return asset

    async def define_metric(
        self,
        metric_key: str,
        *,
        asset_path: str | None = None,
        unit_of_measure: str | None = None,
        display_name: str | None = None,
        decimals: int | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        deadband: float | None = None,
        description: str | None = None,
        announce: bool = True,
    ) -> MetricDefinition:
        """
        Author a Metric Definition, replacing any existing one for the same key.

        Omit `asset_path` to describe the Metric Key on every Asset, which is how
        one row gives `°C` to the Temperature of every mixer.
        """
        async with self._database.session() as session:
            asset_id: int | None = None
            if asset_path is not None:
                asset_id = (await session.execute(select(Asset.id).where(Asset.path == asset_path))).scalar_one_or_none()
                if asset_id is None:
                    raise ValueError(f"No Asset at path {asset_path!r}")

            values = {
                "asset_id": asset_id,
                "metric_key": metric_key,
                "unit_of_measure": unit_of_measure,
                "display_name": display_name,
                "decimals": decimals,
                "min_value": min_value,
                "max_value": max_value,
                "deadband": deadband,
                "description": description,
            }
            statement = (
                insert(MetricDefinition)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_metric_definition_asset_key",
                    set_={key: value for key, value in values.items() if key not in {"asset_id", "metric_key"}}
                    | {"updated_at": func.now()},
                )
                .returning(MetricDefinition.id)
            )
            definition_id = (await session.execute(statement)).scalar_one()
            definition = (
                await session.execute(select(MetricDefinition).where(MetricDefinition.id == definition_id))
            ).scalar_one()

        if announce:
            await announce_asset_model_changed(self._database)
        return definition

    async def delete_asset(self, path: str, *, rebind: bool = True) -> int:
        """Delete an Asset and everything under it. Returns the number of Assets removed."""
        async with self._database.session() as session:
            result = await session.execute(delete(Asset).where(Asset.path == path))
            removed = result.rowcount or 0

        if rebind:
            await self.rebind_all()
        return removed

    # ---------------------------------------------------------------- bindings

    async def bind_topic(self, topic: str) -> TopicBinding:
        """
        Resolve one observed topic to its Asset and remember the answer.

        Called by the historian the first time it sees a topic. A topic that
        matches no Asset is still recorded, with a null Asset, so that Unmodelled
        Topics can be counted rather than silently ignored.
        """
        async with self._database.begin() as connection:
            row = (await connection.execute(text(_BIND_TOPIC_SQL), {"topic": topic})).one()
            return TopicBinding(topic=topic, asset_id=row.asset_id, metric_path=row.metric_path)

    async def rebind_all(self) -> int:
        """
        Re-resolve every known topic against the current Asset Model.

        Must be called after any write to `model.asset`: bindings are derived, so
        editing the model leaves them stale. Returns the number that moved.
        """
        async with self._database.begin() as connection:
            result = await connection.execute(text(_REBIND_ALL_SQL))
            moved = result.rowcount or 0
        if moved:
            LOGGER.info("Rebound %s topic(s) after an Asset Model change", moved)
        await announce_asset_model_changed(self._database)
        return moved

    async def unmodelled_topics(self, limit: int = 100) -> list[str]:
        """Topics that have published data but match no Asset."""
        async with self._database.session() as session:
            result = await session.execute(
                select(TopicBinding.topic)
                .where(TopicBinding.asset_id.is_(None))
                .order_by(TopicBinding.first_seen_at)
                .limit(limit)
            )
            return list(result.scalars())

    # ------------------------------------------------------------------- reads

    async def level_ranks(self) -> dict[str, int]:
        """Asset Level name to rank, coarsest first."""
        async with self._database.session() as session:
            result = await session.execute(select(AssetLevel.name, AssetLevel.rank))
            return {name: rank for name, rank in result.all()}

    async def get_asset(self, path: str) -> Asset | None:
        async with self._database.session() as session:
            return (await session.execute(select(Asset).where(Asset.path == path))).scalar_one_or_none()

    async def list_assets(
        self,
        *,
        under: str | None = None,
        levels: Collection[str] | None = None,
        include_inactive: bool = False,
    ) -> list[Asset]:
        """
        The Asset Model as a flat list ordered by path, which nests trivially.

        `under` restricts to one branch, including the Asset named by it.
        """
        statement = select(Asset).order_by(Asset.path)
        if under is not None:
            statement = statement.where((Asset.path == under) | func.starts_with(Asset.path, under + SEPARATOR))
        if levels:
            statement = statement.where(Asset.level.in_(list(levels)))
        if not include_inactive:
            statement = statement.where(Asset.is_active.is_(True))
        async with self._database.session() as session:
            return list((await session.execute(statement)).scalars())

    async def children_of(self, path: str | None) -> list[Asset]:
        """Direct children of an Asset, or the roots when `path` is None."""
        if path is None:
            statement = select(Asset).where(Asset.parent_id.is_(None))
        else:
            parent = select(Asset.id).where(Asset.path == path).scalar_subquery()
            statement = select(Asset).where(Asset.parent_id == parent)
        async with self._database.session() as session:
            return list((await session.execute(statement.order_by(Asset.segment))).scalars())

    async def ancestors_of(self, topic: str) -> list[Asset]:
        """
        Every Asset on the path to a topic, coarsest first.

        Uses the fact that an ancestor's path is a prefix of the topic, so no
        recursive query is needed: the candidate paths are computable in Python.
        """
        candidates = ancestor_paths(topic)
        if not candidates:
            return []
        async with self._database.session() as session:
            result = await session.execute(select(Asset).where(Asset.path.in_(candidates)).order_by(func.length(Asset.path)))
            return list(result.scalars())

    async def metric_definitions_for(
        self,
        asset_id: int | None,
        metric_path_prefix: str = "",
    ) -> list[MetricDefinition]:
        """
        Definitions that could apply to an Asset, Asset-specific ones last.

        Ordering matters: callers keep the last match, so a row scoped to the
        Asset overrides the plant-wide one for the same Metric Key.
        """
        applies_to_any_asset = MetricDefinition.asset_id.is_(None)
        statement = select(MetricDefinition).where(
            applies_to_any_asset if asset_id is None else (applies_to_any_asset | (MetricDefinition.asset_id == asset_id))
        )
        if metric_path_prefix:
            statement = statement.where(func.starts_with(MetricDefinition.metric_key, metric_path_prefix))
        statement = statement.order_by(MetricDefinition.asset_id.nulls_first())
        async with self._database.session() as session:
            return list((await session.execute(statement)).scalars())

    async def counts(self) -> dict[str, int]:
        """How complete is the Asset Model? Assets, definitions, bound and unmodelled topics."""
        async with self._database.session() as session:
            assets = (await session.execute(select(func.count()).select_from(Asset))).scalar_one()
            definitions = (await session.execute(select(func.count()).select_from(MetricDefinition))).scalar_one()
            bound = (
                await session.execute(
                    select(func.count()).select_from(TopicBinding).where(TopicBinding.asset_id.is_not(None))
                )
            ).scalar_one()
            unmodelled = (
                await session.execute(
                    select(func.count()).select_from(TopicBinding).where(TopicBinding.asset_id.is_(None))
                )
            ).scalar_one()
        return {
            "assets": assets,
            "metric_definitions": definitions,
            "bound_topics": bound,
            "unmodelled_topics": unmodelled,
        }


def specs_for_path(path: str, levels: Sequence[str]) -> list[AssetSpec]:
    """
    Turn a topic prefix and a level sequence into AssetSpecs.

    Convenience for seeding: `specs_for_path("A/B", ["ENTERPRISE", "SITE"])`.
    """
    segments = split_topic(path)
    if len(segments) != len(levels):
        raise ValueError(f"{len(segments)} segment(s) in {path!r} but {len(levels)} level(s) given")
    return [AssetSpec(segment=segment, level=level) for segment, level in zip(segments, levels, strict=True)]


__all__ = ["AssetModelRepository", "AssetSpec", "specs_for_path"]
