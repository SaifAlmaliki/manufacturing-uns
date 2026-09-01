"""
Validates a tag mapping against the Asset Model.

Reports, never gates. An edge connector that cannot start without enterprise Postgres
would defeat the reason mapping by config file was chosen over an Asset-Model-driven
approach — so at startup this only logs and sets a gauge. The `uns_opcua_validate`
entry point exits non-zero instead, so CI can gate a config change.
"""

import asyncio
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from uns_model.model_config import MODEL_SCHEMA, ModelConfig
from uns_opcua import prometheus_metrics as metrics
from uns_opcua.opcua_config import OpcUaConfig
from uns_opcua.tag_map import TagBinding, build_bindings, find_conflicts

LOGGER = logging.getLogger(__name__)

_ASSET_PATHS = text(f"SELECT path FROM {MODEL_SCHEMA}.asset WHERE is_active")  # noqa: S608 - schema is a constant
_METRIC_UNITS = text(  # noqa: S608 - schema is a constant
    f"SELECT a.path, m.metric_key, m.unit_of_measure "
    f"FROM {MODEL_SCHEMA}.metric_definition m "
    f"LEFT JOIN {MODEL_SCHEMA}.asset a ON a.id = m.asset_id"
)


@dataclass(frozen=True, slots=True)
class ModelIssue:
    """One disagreement between the connector's configuration and the Asset Model."""

    kind: str
    detail: str


def check_bindings(
    bindings: Sequence[TagBinding],
    known_asset_paths: set[str],
    metric_units: Mapping[tuple[str | None, str], str | None],
) -> list[ModelIssue]:
    """
    Every issue with this mapping, in one pass.

    `metric_units` is keyed by (asset path or None, Metric Key). None means the
    MetricDefinition has `asset_id IS NULL` and so applies to every Asset; an
    Asset-specific row wins over it.
    """
    issues = [ModelIssue(kind="config_conflict", detail=detail) for detail in find_conflicts(bindings)]

    for binding in bindings:
        if binding.asset not in known_asset_paths:
            issues.append(
                ModelIssue(
                    kind="unknown_asset",
                    detail=f"{binding.node_id}: asset {binding.asset!r} is not in the Asset Model",
                )
            )

        asset_specific = (binding.asset, binding.metric_key)
        if asset_specific in metric_units:
            unit_of_measure = metric_units[asset_specific]
        elif (None, binding.metric_key) in metric_units:
            unit_of_measure = metric_units[(None, binding.metric_key)]
        else:
            issues.append(
                ModelIssue(
                    kind="missing_metric_definition",
                    detail=(
                        f"{binding.node_id}: no MetricDefinition for Metric Key "
                        f"{binding.metric_key!r} on asset {binding.asset!r}"
                    ),
                )
            )
            continue

        if binding.unit is not None and unit_of_measure is not None and binding.unit != unit_of_measure:
            issues.append(
                ModelIssue(
                    kind="unit_mismatch",
                    detail=(
                        f"{binding.node_id}: configured unit {binding.unit!r} disagrees with the "
                        f"MetricDefinition's Unit of Measure {unit_of_measure!r}"
                    ),
                )
            )

    return issues


async def load_model_facts(engine) -> tuple[set[str], dict[tuple[str | None, str], str | None]]:  # noqa: ANN001
    """Read the Asset paths and MetricDefinition units the check needs."""
    async with engine.connect() as connection:
        asset_paths = {row[0] for row in (await connection.execute(_ASSET_PATHS)).all()}
        metric_units = {
            (asset_path, metric_key): unit_of_measure
            for asset_path, metric_key, unit_of_measure in (await connection.execute(_METRIC_UNITS)).all()
        }
    return asset_paths, metric_units


def all_bindings() -> list[TagBinding]:
    """Every configured tag, across every server."""
    return [binding for server in OpcUaConfig.servers for binding in build_bindings(server)]


async def validate(bindings: Sequence[TagBinding]) -> list[ModelIssue]:
    """
    Load the model facts and check the bindings against them.

    `09_uns_model` keeps the password out of the URL and hands it over in
    `connect_args()` alongside the SSL context, so the engine is built the same way here
    rather than composing a second, divergent URL.
    """
    config = ModelConfig.from_settings("opcua")
    if not config.is_valid():
        raise RuntimeError("The Asset Model database is not configured")

    engine = create_async_engine(config.url, connect_args=config.connect_args(), pool_pre_ping=True)
    try:
        asset_paths, metric_units = await load_model_facts(engine)
    finally:
        await engine.dispose()
    return check_bindings(bindings, asset_paths, metric_units)


async def report_at_startup(bindings: Sequence[TagBinding]) -> None:
    """
    Non-blocking startup check. Publishing must never wait on Postgres, so a failure to
    reach the Asset Model is logged and forgotten.
    """
    try:
        issues = await validate(bindings)
    except Exception:
        LOGGER.warning("Asset Model validation skipped: the model is unreachable", exc_info=True)
        return

    metrics.UNMODELLED_TAGS.set(len(issues))
    for issue in issues:
        LOGGER.warning("Asset Model validation [%s] %s", issue.kind, issue.detail)
    if not issues:
        LOGGER.info("All %s configured tags are present in the Asset Model", len(bindings))


def main() -> None:
    """`uns_opcua_validate`: exit non-zero on any issue so CI can gate a config change."""
    logging.basicConfig(level=logging.INFO)
    bindings = all_bindings()
    if not bindings:
        LOGGER.error("No opcua.servers are configured, so there is nothing to validate")
        sys.exit(1)

    issues = asyncio.run(validate(bindings))
    for issue in issues:
        LOGGER.error("[%s] %s", issue.kind, issue.detail)
    if issues:
        LOGGER.error("%s issue(s) across %s configured tags", len(issues), len(bindings))
        sys.exit(1)
    LOGGER.info("All %s configured tags validate against the Asset Model", len(bindings))
    sys.exit(0)


if __name__ == "__main__":
    main()
