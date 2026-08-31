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

Enrichment for the realtime path: given a topic, what does the Asset Model know?

    resolver = TopicContextResolver()
    context = await resolver.resolve(topic)
    context.levels["LINE"]              # 'Line1'
    context.unit_of_measure("value")    # '°C'

Behind that sits prefix matching against the Asset Model, ancestor lookup, Metric
Definition precedence, and a TTL cache. Historic and Grafana reads do not come
through here: they join the enrichment views in Postgres instead (ADR-0003).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from uns_model.engine import Database
from uns_model.repositories import AssetModelRepository
from uns_model.topic_path import SEPARATOR, metric_key

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_SIZE = 4096
DEFAULT_TTL_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class MetricInfo:
    """What a Metric Definition says about one Metric Key."""

    metric_key: str
    display_name: str | None = None
    unit_of_measure: str | None = None
    decimals: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    deadband: float | None = None


@dataclass(frozen=True, slots=True)
class TopicContext:
    """
    Everything the Asset Model knows about one topic.

    `levels` is the useful part: `levels["LINE"]` is the line's name regardless of
    how deep the line sits in this particular branch.
    """

    topic: str
    asset_id: int
    asset_path: str
    asset_level: str
    asset_name: str
    metric_path: str
    levels: Mapping[str, str] = field(default_factory=dict)
    level_names: Mapping[str, str] = field(default_factory=dict)
    definitions: Mapping[str, MetricInfo] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    manufacturer: str | None = None
    criticality: str | None = None
    description: str | None = None

    def metric_key(self, metric_name: str) -> str:
        """The Metric Key for one scalar leaf of a payload on this topic."""
        return metric_key(self.metric_path, metric_name)

    def metric(self, metric_name: str) -> MetricInfo | None:
        """The Metric Definition for one payload leaf, if one was authored."""
        return self.definitions.get(self.metric_key(metric_name))

    def unit_of_measure(self, metric_name: str) -> str | None:
        """The physical unit of one payload leaf. Never called `unit` (see CONTEXT.md)."""
        info = self.metric(metric_name)
        return info.unit_of_measure if info else None

    def enrich(self, metric_name: str | None = None) -> dict[str, Any]:
        """
        A flat dict of Enrichment, ready to merge into an API response.

        Pass `metric_name` to include the Metric Definition for one payload leaf;
        omit it for Asset facts only.
        """
        enriched: dict[str, Any] = {
            "asset_path": self.asset_path,
            "asset_name": self.asset_name,
            "asset_level": self.asset_level,
            "enterprise": self.levels.get("ENTERPRISE"),
            "site": self.levels.get("SITE"),
            "area": self.levels.get("AREA"),
            "production_unit": self.levels.get("PRODUCTION_UNIT"),
            "line": self.levels.get("LINE"),
            "work_cell": self.levels.get("WORK_CELL"),
            "machine": self.levels.get("MACHINE"),
            "manufacturer": self.manufacturer,
            "criticality": self.criticality,
            "attributes": dict(self.attributes),
        }
        if metric_name is not None:
            info = self.metric(metric_name)
            enriched |= {
                "metric_key": self.metric_key(metric_name),
                "metric_display_name": info.display_name if info else None,
                "unit_of_measure": info.unit_of_measure if info else None,
                "decimals": info.decimals if info else None,
                "min_value": info.min_value if info else None,
                "max_value": info.max_value if info else None,
            }
        return enriched


class TopicContextResolver:
    """
    Resolve topics to Enrichment, cached in memory.

    The cache has a TTL because the Asset Model is edited by a different process
    than the one reading it: without one, a renamed line would stay wrong in the
    GraphQL server until it restarted. `refresh()` is the in-process shortcut.
    """

    def __init__(
        self,
        repository: AssetModelRepository | None = None,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._repository = repository or AssetModelRepository(Database.shared())
        self._cache_size = cache_size
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[float, TopicContext | None]] = OrderedDict()

    async def resolve(self, topic: str) -> TopicContext | None:
        """
        The Asset Model's view of a topic, or None for an Unmodelled Topic.

        Unmodelled Topics are cached too: a topic nobody has modelled is usually
        published at the same rate as one that is.
        """
        if (cached := self._get_cached(topic)) is not None:
            return cached[1]

        context = await self._load(topic)
        self._put_cached(topic, context)
        return context

    def refresh(self) -> None:
        """Forget everything cached. Call after editing the Asset Model in-process."""
        self._cache.clear()

    async def _load(self, topic: str) -> TopicContext | None:
        ancestors = await self._repository.ancestors_of(topic)
        if not ancestors:
            LOGGER.debug("Unmodelled Topic: %s", topic)
            return None

        asset = ancestors[-1]  # deepest match wins
        metric_path = topic[len(asset.path) :].lstrip(SEPARATOR)
        definitions = await self._repository.metric_definitions_for(asset.id, metric_path)

        return TopicContext(
            topic=topic,
            asset_id=asset.id,
            asset_path=asset.path,
            asset_level=asset.level,
            asset_name=asset.name,
            metric_path=metric_path,
            levels={ancestor.level: ancestor.segment for ancestor in ancestors},
            level_names={ancestor.level: ancestor.name for ancestor in ancestors},
            # Ordered Asset-specific last, so the later write wins for a shared key.
            definitions={
                definition.metric_key: MetricInfo(
                    metric_key=definition.metric_key,
                    display_name=definition.display_name,
                    unit_of_measure=definition.unit_of_measure,
                    decimals=definition.decimals,
                    min_value=definition.min_value,
                    max_value=definition.max_value,
                    deadband=definition.deadband,
                )
                for definition in definitions
            },
            attributes=dict(asset.attributes or {}),
            manufacturer=asset.manufacturer,
            criticality=asset.criticality,
            description=asset.description,
        )

    def _get_cached(self, topic: str) -> tuple[float, TopicContext | None] | None:
        entry = self._cache.get(topic)
        if entry is None:
            return None
        if time.monotonic() - entry[0] > self._ttl_seconds:
            del self._cache[topic]
            return None
        self._cache.move_to_end(topic)
        return entry

    def _put_cached(self, topic: str, context: TopicContext | None) -> None:
        self._cache[topic] = (time.monotonic(), context)
        self._cache.move_to_end(topic)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
