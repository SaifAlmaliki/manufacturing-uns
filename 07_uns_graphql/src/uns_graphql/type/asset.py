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

GraphQL types for the authored Asset Model held in Postgres.

Distinct from `isa95_node.UNSNode` on purpose: a UNSNode is what was observed on
the broker, an Asset is what an engineer declared exists. Only the Asset Model
carries names, units and equipment facts (ADR-0003).
"""

import logging

import strawberry
from uns_model.asset_context import MetricInfo, TopicContext
from uns_model.tables import Asset

from uns_graphql.type.basetype import JSONPayload

LOGGER = logging.getLogger(__name__)


@strawberry.type(description="A declared thing in the plant: a Site, a Line, a Machine.")
class AssetNode:
    """One Asset from the authored Asset Model."""

    path: str = strawberry.field(description="Topic prefix this Asset publishes under, e.g. 'Ent/Site/Area/Line1/Cell1/G1'")
    segment: str = strawberry.field(description="The single topic segment naming this Asset, e.g. 'G1'")
    level: str = strawberry.field(description="Asset Level, e.g. SITE, LINE, WORK_CELL, MACHINE. Levels may be skipped.")
    name: str = strawberry.field(description="Display name if one was authored, otherwise the segment")
    description: str | None = None
    manufacturer: str | None = None
    model_number: str | None = None
    serial_number: str | None = None
    criticality: str | None = None
    is_active: bool = True
    attributes: JSONPayload | None = strawberry.field(
        default=None, description="Site-specific facts that do not deserve a column"
    )

    @classmethod
    def from_asset(cls, asset: Asset) -> "AssetNode":
        return cls(
            path=asset.path,
            segment=asset.segment,
            level=asset.level,
            name=asset.name,
            description=asset.description,
            manufacturer=asset.manufacturer,
            model_number=asset.model_number,
            serial_number=asset.serial_number,
            criticality=asset.criticality,
            is_active=asset.is_active,
            attributes=JSONPayload(dict(asset.attributes or {})),
        )


@strawberry.type(description="What the Asset Model says about one Metric Key.")
class MetricDefinitionType:
    metric_key: str = strawberry.field(description="Topic below the Asset plus the payload leaf, e.g. 'ProcessValue/Temperature/value'")
    display_name: str | None = None
    unit_of_measure: str | None = strawberry.field(default=None, description="The physical unit, e.g. '°C'")
    decimals: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    deadband: float | None = None

    @classmethod
    def from_metric_info(cls, info: MetricInfo) -> "MetricDefinitionType":
        return cls(
            metric_key=info.metric_key,
            display_name=info.display_name,
            unit_of_measure=info.unit_of_measure,
            decimals=info.decimals,
            min_value=info.min_value,
            max_value=info.max_value,
            deadband=info.deadband,
        )


@strawberry.type(
    description="Enrichment for one topic: which Asset publishes it, what it is named at every "
    "Asset Level, and the Metric Definitions that apply to its payload."
)
class TopicContextType:
    topic: str
    asset: AssetNode
    metric_path: str = strawberry.field(description="Topic segments below the Asset, e.g. 'ProcessValue/Temperature'")

    enterprise: str | None = None
    site: str | None = None
    area: str | None = None
    production_unit: str | None = strawberry.field(
        default=None, description="The ISA-95 Production Unit, not a unit of measure"
    )
    line: str | None = None
    work_cell: str | None = None
    machine: str | None = None

    level_names: JSONPayload | None = strawberry.field(
        default=None, description="Asset Level to display name, for levels this branch actually uses"
    )
    metric_definitions: list[MetricDefinitionType] = strawberry.field(default_factory=list)

    @classmethod
    def from_context(cls, context: TopicContext, asset: Asset) -> "TopicContextType":
        return cls(
            topic=context.topic,
            asset=AssetNode.from_asset(asset),
            metric_path=context.metric_path,
            enterprise=context.levels.get("ENTERPRISE"),
            site=context.levels.get("SITE"),
            area=context.levels.get("AREA"),
            production_unit=context.levels.get("PRODUCTION_UNIT"),
            line=context.levels.get("LINE"),
            work_cell=context.levels.get("WORK_CELL"),
            machine=context.levels.get("MACHINE"),
            level_names=JSONPayload(dict(context.level_names)),
            metric_definitions=[MetricDefinitionType.from_metric_info(info) for info in context.definitions.values()],
        )


@strawberry.type(description="How complete the Asset Model is.")
class AssetModelSummary:
    assets: int
    metric_definitions: int
    bound_topics: int
    unmodelled_topics: int = strawberry.field(
        description="Topics that have published data but match no Asset. Non-zero means the model is incomplete."
    )
