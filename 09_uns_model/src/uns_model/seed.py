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

Turning the configured plant description into an Asset Model.

Planning is pure: `plan_from_simulator_config` reads a mapping and returns what
should exist, so it can be printed, diffed or tested without a database.
Applying is the only part that writes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from uns_model.hierarchy import HierarchyTree, tree_to_mapping
from uns_model.repositories import AssetModelRepository, AssetSpec
from uns_model.topic_path import SEPARATOR

LOGGER = logging.getLogger(__name__)

# The levels the simulator's topic tree actually uses. PRODUCTION_UNIT is absent
# on purpose: this plant publishes Work Cells directly under a Line, which is why
# an Asset carries its own level instead of the tree having fixed depth.
SIMULATOR_LEVELS = ("ENTERPRISE", "SITE", "AREA", "LINE", "WORK_CELL")
MACHINE_LEVEL = "MACHINE"

# Payload leaves published for every sensor reading (see 99_simulator devices.py).
# Only `value` carries a Unit of Measure.
MEASURED_LEAF = "value"
PROCESS_VALUE = "ProcessValue"

# The simulator also runs one SCADA per Site and one HMI per Line, publishing under
# the first Work Cell of each (99_simulator/src/uns_simulator/simulator.py). They are
# not in the config, but modelling them keeps their topics from binding a level too
# high and showing up as Work Cell data.
SITE_MACHINE = "SCADA"
LINE_MACHINE = "HMI"


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """One Metric Definition to author."""

    metric_key: str
    unit_of_measure: str | None = None
    display_name: str | None = None
    description: str | None = None
    asset_path: str | None = None


@dataclass(slots=True)
class SeedPlan:
    """Everything a seed would write, before anything is written."""

    branches: list[list[AssetSpec]] = field(default_factory=list)
    metrics: list[MetricSpec] = field(default_factory=list)

    prune_paths: list[str] = field(default_factory=list)
    enterprise: str | None = None

    @property
    def asset_paths(self) -> list[str]:
        """Every distinct Asset path the plan would create, in tree order."""
        paths: set[str] = set()
        for branch in self.branches:
            segments: list[str] = []
            for spec in branch:
                segments.append(spec.segment)
                paths.add(SEPARATOR.join(segments))
        return sorted(paths)

    def describe(self) -> str:
        """The plan as text, for `--dry-run`."""
        lines = [f"{path}" for path in self.asset_paths]
        lines.append("")
        lines += [
            f"{spec.metric_key}"
            + (f"  [{spec.unit_of_measure}]" if spec.unit_of_measure else "")
            + (f"  on {spec.asset_path}" if spec.asset_path else "  (all Assets)")
            for spec in self.metrics
        ]
        if self.enterprise or self.prune_paths:
            lines.append("")
            scope = f" under {self.enterprise}" if self.enterprise else ""
            lines.append(f"Prune{scope}:")
            if self.prune_paths:
                lines.extend(self.prune_paths)
            else:
                lines.append("assets not listed above (this enterprise and descendants)")
        return "\n".join(lines)


def _as_mapping(node: Any) -> Mapping[str, Any]:
    if not hasattr(node, "get"):
        raise TypeError(f"Expected a mapping in the hierarchy, got {node!r}")
    return node


def _named(node: Any) -> str:
    """A hierarchy node is either a bare name or a mapping with a `name`."""
    if isinstance(node, str):
        return node
    name = _as_mapping(node).get("name")
    if not name:
        raise ValueError(f"Hierarchy node is missing 'name': {node}")
    return str(name)


def _cells(hierarchy: Mapping[str, Any]) -> list[tuple[str, str, str, str, str]]:
    """
    Expand the nested hierarchy into one (enterprise, site, area, line, cell) tuple
    per Work Cell.

    Mirrors `uns_simulator.models.expand_hierarchy_paths`, which is what decides
    the topics that will actually be published. The duplication is deliberate:
    the Asset Model must not import the simulator.
    """
    enterprise = hierarchy.get("enterprise")
    if not enterprise:
        raise ValueError("simulator.hierarchy.enterprise is required")

    sites = hierarchy.get("sites")
    if not sites:
        # Legacy flat shape.
        flat = tuple(str(hierarchy.get(key) or "") for key in ("site", "area", "line", "cell"))
        if not all(flat):
            raise ValueError("simulator.hierarchy needs either 'sites' or site/area/line/cell")
        return [(str(enterprise), *flat)]  # type: ignore[return-value]

    cells: list[tuple[str, str, str, str, str]] = []
    for site in sites:
        site_name = _named(site)
        for area in _as_mapping(site).get("areas") or []:
            area_name = _named(area)
            for line in _as_mapping(area).get("lines") or []:
                line_name = _named(line)
                for cell in _as_mapping(line).get("cells") or []:
                    cells.append((str(enterprise), site_name, area_name, line_name, _named(cell)))
    if not cells:
        raise ValueError("simulator.hierarchy.sites did not produce any Work Cells")
    return cells


def _machines(simulator: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """
    Machine name to its sensor definitions.

    Every PLC template publishes under its `equipment` name in every Work Cell, so
    the same Machine name recurs across the plant; the sensors are shared, which is
    exactly why their Metric Definitions are authored plant-wide.
    """
    machines: dict[str, Mapping[str, Any]] = {}
    for template in simulator.get("plc") or []:
        template = _as_mapping(template)
        name = template.get("equipment") or template.get("name")
        if not name:
            LOGGER.warning("Skipping a simulator.plc entry with no equipment name: %s", template)
            continue
        machines[str(name)] = _as_mapping(template.get("sensors") or {})

    if not machines:
        fallback = (simulator.get("equipment") or {}).get("mixer_tank")
        if fallback:
            fallback = _as_mapping(fallback)
            machines[str(fallback.get("name") or "MixerTank")] = _as_mapping(fallback.get("sensors") or {})
    return machines


def plan_from_hierarchy_tree(tree: HierarchyTree, extra: Mapping[str, Any] | None = None) -> SeedPlan:
    """
    Build the same cell branches `plan_from_simulator_config` would from `tree`.

    `extra` may carry `plc` / `equipment` for machines. When it is omitted, no PLC
    machines are planned; SCADA/HMI still follow the existing first-cell seed rules.
    """
    payload: dict[str, Any] = dict(extra or {})
    payload["hierarchy"] = tree_to_mapping(tree)
    return plan_from_simulator_config(payload)


def plan_from_simulator_config(simulator: Mapping[str, Any]) -> SeedPlan:
    """
    Read `simulator.hierarchy` / `simulator.plc` and return the Asset Model they imply.

    Pure. Nothing here touches a database or the network.
    """
    hierarchy = simulator.get("hierarchy")
    if hierarchy is None:
        raise ValueError("simulator.hierarchy is required to seed the Asset Model")

    machines = _machines(simulator)
    enterprise = str(_as_mapping(hierarchy).get("enterprise") or "") or None
    plan = SeedPlan(enterprise=enterprise)
    sites_seen: set[str] = set()
    lines_seen: set[tuple[str, ...]] = set()

    for segments in _cells(_as_mapping(hierarchy)):
        cell_branch = [
            AssetSpec(segment=segment, level=level)
            for segment, level in zip(segments, SIMULATOR_LEVELS, strict=True)
        ]
        plan.branches.append(cell_branch)

        cell_machines = list(machines)
        if segments[1] not in sites_seen:
            sites_seen.add(segments[1])
            cell_machines.append(SITE_MACHINE)
        if segments[1:4] not in lines_seen:
            lines_seen.add(segments[1:4])
            cell_machines.append(LINE_MACHINE)

        for machine in cell_machines:
            plan.branches.append([*cell_branch, AssetSpec(segment=machine, level=MACHINE_LEVEL)])

    # One Metric Definition per sensor, not per Machine per cell: the Metric Key is
    # the part of the topic below the Asset, so `ProcessValue/Temperature/value`
    # describes that reading wherever it is published.
    for sensors in machines.values():
        for sensor, sensor_config in sensors.items():
            unit = _as_mapping(sensor_config).get("unit") if hasattr(sensor_config, "get") else None
            plan.metrics.append(
                MetricSpec(
                    metric_key=f"{PROCESS_VALUE}/{sensor}/{MEASURED_LEAF}",
                    unit_of_measure=str(unit) if unit else None,
                    display_name=str(sensor),
                )
            )
    plan.metrics = _deduplicate(plan.metrics)
    return plan


def _deduplicate(metrics: Iterable[MetricSpec]) -> list[MetricSpec]:
    """Keep the first definition per (Asset, Metric Key); two PLCs may share a sensor."""
    seen: dict[tuple[str | None, str], MetricSpec] = {}
    for spec in metrics:
        seen.setdefault((spec.asset_path, spec.metric_key), spec)
    return list(seen.values())


def _highest_paths(paths: set[str]) -> list[str]:
    """Paths that are not descendants of another path in the set, shortest first."""
    roots: list[str] = []
    for path in sorted(paths, key=lambda item: (item.count(SEPARATOR), item)):
        if any(path == root or path.startswith(root + SEPARATOR) for root in roots):
            continue
        roots.append(path)
    return roots


def _under_enterprise(path: str, enterprise: str) -> bool:
    return path == enterprise or path.startswith(enterprise + SEPARATOR)


async def _prune_removed_assets(repository: AssetModelRepository, plan: SeedPlan) -> None:
    """Delete Assets whose path is not in the plan.

    Scoped to `plan.enterprise` and its descendants when that is set, so a
    second root is never collateral damage. Skips when the model is empty:
    there is no root to delete if none exists.
    """
    existing = await repository.list_assets()
    if not existing:
        return
    keep = set(plan.asset_paths)
    extra = {
        asset.path
        for asset in existing
        if asset.path not in keep
        and (plan.enterprise is None or _under_enterprise(asset.path, plan.enterprise))
    }
    if extra:
        LOGGER.info(
            "Pruning %s Asset path(s) not in the seed plan: %s",
            len(extra),
            ", ".join(sorted(extra)),
        )
    plan.prune_paths = sorted(extra)
    for path in _highest_paths(extra):
        await repository.delete_asset(path, rebind=False)


async def apply_plan(repository: AssetModelRepository, plan: SeedPlan) -> dict[str, int]:
    """
    Write a plan to the Asset Model, then re-resolve the Topic Bindings.

    Idempotent: every Asset is upserted by path and every Metric Definition by
    (Asset, Metric Key), so re-seeding an edited config updates rather than
    duplicates. Assets no longer in the plan are deleted, including descendants.
    The `rebind_all` at the end is not optional: Topic Bindings are derived from
    the tree, so writing the tree leaves them stale (ADR-0003).
    """
    for branch in plan.branches:
        await repository.ensure_branch(branch, rebind=False)
    for spec in plan.metrics:
        await repository.define_metric(
            spec.metric_key,
            asset_path=spec.asset_path,
            unit_of_measure=spec.unit_of_measure,
            display_name=spec.display_name,
            description=spec.description,
            announce=False,
        )
    await _prune_removed_assets(repository, plan)
    rebound = await repository.rebind_all()
    from uns_model.access_repository import AccessGroupRepository

    areas = [asset for asset in await repository.list_assets(levels=["AREA"])]
    access = AccessGroupRepository(repository._database)
    groups = await access.upsert_area_groups(areas)
    await access.apply_demo_membership(groups)
    return {
        "branches": len(plan.branches),
        "assets": len(plan.asset_paths),
        "metric_definitions": len(plan.metrics),
        "rebound_topics": rebound,
    }


__all__ = [
    "MetricSpec",
    "SeedPlan",
    "apply_plan",
    "plan_from_hierarchy_tree",
    "plan_from_simulator_config",
]
