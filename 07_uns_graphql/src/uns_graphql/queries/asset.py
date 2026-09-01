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

GraphQL queries against the authored Asset Model.

This is where the plant hierarchy comes from now. The graph database answers "what
has been published"; these queries answer "what exists, and what is it called",
which is the question a UNS tree or a Grafana label actually asks (ADR-0003).
"""

import logging

import strawberry
from uns_model.asset_context import TopicContextResolver
from uns_model.engine import Database
from uns_model.notifications import AssetModelChangeListener
from uns_model.repositories import AssetModelRepository

from uns_graphql.type.asset import AssetModelSummary, AssetNode, TopicContextType

LOGGER = logging.getLogger(__name__)

DEFAULT_UNMODELLED_LIMIT = 100


_resolver: TopicContextResolver | None = None
_listener: AssetModelChangeListener | None = None


def _repository() -> AssetModelRepository:
    return AssetModelRepository(Database.shared("graphql"))


def _context_resolver() -> TopicContextResolver:
    """
    One resolver per process: its cache is the reason it exists, and it has a TTL so
    that a model edited by the console is picked up without a restart.

    Built on first use rather than at import, so that importing the schema does not
    require a reachable database.
    """
    global _resolver  # noqa: PLW0603
    if _resolver is None:
        _resolver = TopicContextResolver(_repository())
    return _resolver


@strawberry.type(description="Query the authored Asset Model: the plant hierarchy and its Metric Definitions")
class Query:
    """All queries for the Asset Model stored in Postgres."""

    @strawberry.field(
        description="The Asset Model as a flat list ordered by path, which nests trivially in a client. "
        "Optionally restricted to one branch and/or a set of Asset Levels."
    )
    async def get_assets(
        self,
        under: str | None = strawberry.UNSET,
        levels: list[str] | None = strawberry.UNSET,
        include_inactive: bool = False,
    ) -> list[AssetNode]:
        assets = await _repository().list_assets(
            under=under or None,
            levels=levels or None,
            include_inactive=include_inactive,
        )
        return [AssetNode.from_asset(asset) for asset in assets]

    @strawberry.field(description="Direct children of an Asset, or the roots of the Asset Model when path is omitted.")
    async def get_asset_children(self, path: str | None = strawberry.UNSET) -> list[AssetNode]:
        children = await _repository().children_of(path or None)
        return [AssetNode.from_asset(asset) for asset in children]

    @strawberry.field(description="One Asset by its path, or null when nothing is modelled at that path.")
    async def get_asset(self, path: str) -> AssetNode | None:
        asset = await _repository().get_asset(path)
        return AssetNode.from_asset(asset) if asset else None

    @strawberry.field(
        description="Enrichment for one topic: the Asset that publishes it, its name at every Asset Level, "
        "and the Metric Definitions for its payload. Null for an Unmodelled Topic."
    )
    async def get_topic_context(self, topic: str) -> TopicContextType | None:
        resolver = _context_resolver()
        context = await resolver.resolve(topic)
        if context is None:
            LOGGER.debug("No Asset in the Asset Model matches topic %s", topic)
            return None
        asset = await _repository().get_asset(context.asset_path)
        if asset is None:
            # The Asset was deleted between resolving and reading it.
            resolver.refresh()
            return None
        return TopicContextType.from_context(context, asset)

    @strawberry.field(description="Topics that have published data but match no Asset. Empty means the model is complete.")
    async def get_unmodelled_topics(self, limit: int = DEFAULT_UNMODELLED_LIMIT) -> list[str]:
        return await _repository().unmodelled_topics(limit=limit)

    @strawberry.field(description="Counts of what the Asset Model holds, for a completeness check.")
    async def get_asset_model_summary(self) -> AssetModelSummary:
        counts = await _repository().counts()
        return AssetModelSummary(
            assets=counts["assets"],
            metric_definitions=counts["metric_definitions"],
            bound_topics=counts["bound_topics"],
            unmodelled_topics=counts["unmodelled_topics"],
        )

    @classmethod
    async def on_startup(cls) -> None:
        """Drop cached Enrichment when the Asset Model is edited elsewhere."""
        global _listener  # noqa: PLW0603
        if _listener is not None:
            return

        async def refresh() -> None:
            _context_resolver().refresh()

        _listener = AssetModelChangeListener(
            Database.shared("graphql"),
            on_change=refresh,
            module_env="graphql",
        )
        await _listener.start()

    @classmethod
    async def on_shutdown(cls):
        """Stop listening and dispose the shared engine."""
        global _listener  # noqa: PLW0603
        if _listener is not None:
            await _listener.stop()
            _listener = None
        await Database.close_shared()
