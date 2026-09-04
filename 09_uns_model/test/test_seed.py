"""
Unit tests for planning a seed. No database: planning is pure, which is the point
of separating it from `apply_plan`. Applying is tested at the repository seam.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from uns_model.hierarchy import HierarchyArea, HierarchyLine, HierarchySite, HierarchyTree, tree_to_mapping
from uns_model.repositories import AssetSpec
from uns_model.seed import (
    SIMULATOR_LEVELS,
    apply_plan,
    plan_from_hierarchy_tree,
    plan_from_simulator_config,
)
from uns_model.topic_path import SEPARATOR

# The shape of conf/settings.yaml `simulator:`, trimmed to two cells.
SIMULATOR_CONFIG = {
    "hierarchy": {
        "enterprise": "CovestroAG",
        "sites": [
            {
                "name": "Dormagen",
                "areas": [{"name": "Production", "lines": [{"name": "Line1", "cells": ["Cell1", "Cell2"]}]}],
            },
            {
                "name": "Krefeld",
                "areas": [{"name": "Production", "lines": [{"name": "Line1", "cells": ["Cell1"]}]}],
            },
        ],
    },
    "plc": [
        {
            "id": "001",
            "equipment": "G1",
            "sensors": {
                "Temperature": {"base_value": 75.0, "variation": 2.0, "unit": "°C"},
                "Pressure": {"base_value": 150.0, "variation": 5.0, "unit": "psi"},
            },
        },
        {
            "id": "002",
            "equipment": "FillingMachine",
            "sensors": {"FlowRate": {"base_value": 450.0, "variation": 20.0, "unit": "L/min"}},
        },
    ],
    "equipment": {"mixer_tank": {"name": "MixerTank", "sensors": {}}},
}


def test_every_configured_work_cell_becomes_a_branch():
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)

    paths = plan.asset_paths

    assert "CovestroAG" in paths
    assert "CovestroAG/Dormagen/Production/Line1/Cell2" in paths
    assert "CovestroAG/Krefeld/Production/Line1/Cell1" in paths


def test_each_machine_is_created_under_every_work_cell():
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)

    paths = plan.asset_paths

    assert "CovestroAG/Dormagen/Production/Line1/Cell1/G1" in paths
    assert "CovestroAG/Dormagen/Production/Line1/Cell1/FillingMachine" in paths
    assert "CovestroAG/Krefeld/Production/Line1/Cell1/G1" in paths
    # 1 enterprise + 2 sites + 2 areas + 2 lines + 3 cells + 3 cells x 2 machines
    # + 1 SCADA per site + 1 HMI per line
    assert len(paths) == 20


def test_the_production_unit_level_is_skipped_because_the_topics_skip_it():
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)

    levels = [spec.level for spec in plan.branches[0]]

    assert levels == list(SIMULATOR_LEVELS)
    assert "PRODUCTION_UNIT" not in levels


def test_a_machine_branch_ends_at_the_machine_level():
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)

    machine_branches = [branch for branch in plan.branches if branch[-1].level == "MACHINE"]

    assert len(machine_branches) == 10
    assert {branch[-1].segment for branch in machine_branches} == {"G1", "FillingMachine", "SCADA", "HMI"}


def test_the_supervisory_devices_are_modelled_where_the_simulator_publishes_them():
    """Without these, `.../Cell1/SCADA/Status/...` would bind to the Work Cell instead."""
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)
    paths = plan.asset_paths

    # One SCADA per Site, one HMI per Line, both under that Site's/Line's first cell.
    scadas = [path for path in paths if path.endswith("/SCADA")]
    hmis = [path for path in paths if path.endswith("/HMI")]

    assert scadas == [
        "CovestroAG/Dormagen/Production/Line1/Cell1/SCADA",
        "CovestroAG/Krefeld/Production/Line1/Cell1/SCADA",
    ]
    assert hmis == [
        "CovestroAG/Dormagen/Production/Line1/Cell1/HMI",
        "CovestroAG/Krefeld/Production/Line1/Cell1/HMI",
    ]
    assert "CovestroAG/Dormagen/Production/Line1/Cell2/SCADA" not in paths


def test_units_of_measure_are_authored_once_per_sensor_not_once_per_machine():
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)

    units = {spec.metric_key: spec.unit_of_measure for spec in plan.metrics}

    assert units == {
        "ProcessValue/Temperature/value": "°C",
        "ProcessValue/Pressure/value": "psi",
        "ProcessValue/FlowRate/value": "L/min",
    }
    # Plant-wide, so one row gives every mixer's Temperature its unit.
    assert all(spec.asset_path is None for spec in plan.metrics)


def test_the_metric_key_is_the_topic_below_the_asset():
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)
    keys = {spec.metric_key for spec in plan.metrics}

    topic = "CovestroAG/Dormagen/Production/Line1/Cell1/G1/ProcessValue/Temperature"
    asset_path = "CovestroAG/Dormagen/Production/Line1/Cell1/G1"

    assert asset_path in plan.asset_paths
    assert f"{topic[len(asset_path) + 1 :]}/value" in keys


def test_a_sensor_shared_by_two_plcs_is_defined_once():
    config = {
        **SIMULATOR_CONFIG,
        "plc": [
            {"equipment": "G1", "sensors": {"Temperature": {"unit": "°C"}}},
            {"equipment": "G2", "sensors": {"Temperature": {"unit": "°C"}}},
        ],
    }

    plan = plan_from_simulator_config(config)

    assert [spec.metric_key for spec in plan.metrics] == ["ProcessValue/Temperature/value"]


def test_the_fallback_equipment_is_used_when_no_plc_is_configured():
    config = {
        "hierarchy": SIMULATOR_CONFIG["hierarchy"],
        "equipment": {"mixer_tank": {"name": "MixerTank", "sensors": {"Temperature": {"unit": "°C"}}}},
    }

    plan = plan_from_simulator_config(config)

    assert "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank" in plan.asset_paths


def test_the_legacy_flat_hierarchy_still_seeds():
    config = {
        "hierarchy": {
            "enterprise": "CovestroAG",
            "site": "Dormagen",
            "area": "Production",
            "line": "Line1",
            "cell": "Cell1",
        },
        "plc": [{"equipment": "G1", "sensors": {}}],
    }

    plan = plan_from_simulator_config(config)

    assert plan.asset_paths == [
        "CovestroAG",
        "CovestroAG/Dormagen",
        "CovestroAG/Dormagen/Production",
        "CovestroAG/Dormagen/Production/Line1",
        "CovestroAG/Dormagen/Production/Line1/Cell1",
        "CovestroAG/Dormagen/Production/Line1/Cell1/G1",
        "CovestroAG/Dormagen/Production/Line1/Cell1/HMI",
        "CovestroAG/Dormagen/Production/Line1/Cell1/SCADA",
    ]


def test_a_missing_hierarchy_is_an_error_rather_than_an_empty_model():
    with pytest.raises(ValueError, match="hierarchy"):
        plan_from_simulator_config({"plc": []})


def _two_cell_tree() -> HierarchyTree:
    return HierarchyTree(
        enterprise="E",
        sites=(
            HierarchySite(
                "S",
                (HierarchyArea("A", "production", (HierarchyLine("L", ("V101", "V102")),)),),
            ),
        ),
    )


def _one_cell_tree() -> HierarchyTree:
    return HierarchyTree(
        enterprise="E",
        sites=(
            HierarchySite(
                "S",
                (HierarchyArea("A", "production", (HierarchyLine("L", ("V101",)),)),),
            ),
        ),
    )


class RecordingRepository:
    """Records what a seed would write, at the repository seam."""

    def __init__(self) -> None:
        self.branches: list[list[str]] = []
        self.metrics: list[str] = []
        self.rebinds = 0
        self._paths: set[str] = set()

    def _path_set(self) -> set[str]:
        return set(self._paths)

    async def ensure_branch(self, specs, **kwargs):  # noqa: ARG002
        self.branches.append([spec.segment for spec in specs])
        segments: list[str] = []
        for spec in specs:
            segments.append(spec.segment)
            self._paths.add(SEPARATOR.join(segments))
        return None

    async def define_metric(self, metric_key, **kwargs):  # noqa: ARG002
        self.metrics.append(metric_key)
        return None

    async def list_assets(self, **kwargs):  # noqa: ARG002
        return [SimpleNamespace(path=path) for path in sorted(self._paths)]

    async def delete_asset(self, path: str, *, rebind: bool = True) -> int:
        prefix = path + SEPARATOR
        removed = {candidate for candidate in self._paths if candidate == path or candidate.startswith(prefix)}
        self._paths -= removed
        if rebind:
            self.rebinds += 1
        return len(removed)

    async def rebind_all(self) -> int:
        self.rebinds += 1
        return 0


@pytest.mark.asyncio
async def test_applying_a_plan_rebinds_topics_because_bindings_are_derived():
    repository = RecordingRepository()

    written = await apply_plan(repository, plan_from_simulator_config(SIMULATOR_CONFIG))

    assert repository.rebinds == 1, "not rebinding leaves every enriched row pointing at the old tree"
    assert written["metric_definitions"] == 3
    assert len(repository.branches) == len(plan_from_simulator_config(SIMULATOR_CONFIG).branches)


def test_plan_from_hierarchy_tree_builds_a_branch_for_each_cell():
    plan = plan_from_hierarchy_tree(_two_cell_tree())

    assert "E/S/A/L/V101" in plan.asset_paths
    assert "E/S/A/L/V102" in plan.asset_paths
    assert "E" in plan.asset_paths


def test_plan_from_hierarchy_tree_matches_simulator_config_from_the_same_tree():
    tree = _two_cell_tree()
    extra = {"plc": [{"equipment": "G1", "sensors": {"Temperature": {"unit": "°C"}}}]}

    from_tree = plan_from_hierarchy_tree(tree, extra)
    from_mapping = plan_from_simulator_config({"hierarchy": tree_to_mapping(tree), **extra})

    assert from_tree.asset_paths == from_mapping.asset_paths
    assert [spec.metric_key for spec in from_tree.metrics] == [spec.metric_key for spec in from_mapping.metrics]


def test_plan_from_hierarchy_tree_without_extra_has_no_plc_machines():
    plan = plan_from_hierarchy_tree(_two_cell_tree())

    assert all("/G1" not in path for path in plan.asset_paths)
    assert "E/S/A/L/V101/SCADA" in plan.asset_paths
    assert "E/S/A/L/V101/HMI" in plan.asset_paths


@pytest.mark.asyncio
async def test_applying_a_smaller_tree_prunes_the_removed_cell():
    repository = RecordingRepository()

    await apply_plan(repository, plan_from_hierarchy_tree(_two_cell_tree()))
    assert "E/S/A/L/V102" in repository._path_set()

    await apply_plan(repository, plan_from_hierarchy_tree(_one_cell_tree()))

    remaining = repository._path_set()
    assert "E/S/A/L/V101" in remaining
    assert "E/S/A/L/V102" not in remaining
    assert all(not path.startswith("E/S/A/L/V102/") for path in remaining)


def test_seed_plan_describe_includes_the_prune_scope():
    plan = plan_from_hierarchy_tree(_two_cell_tree())
    plan.prune_paths = ["E/S/A/L/V102"]

    described = plan.describe()

    assert "Prune under E" in described
    assert "E/S/A/L/V102" in described


@pytest.mark.asyncio
async def test_applying_a_smaller_tree_logs_pruned_paths(caplog: pytest.LogCaptureFixture):
    repository = RecordingRepository()
    await apply_plan(repository, plan_from_hierarchy_tree(_two_cell_tree()))

    with caplog.at_level("INFO", logger="uns_model.seed"):
        await apply_plan(repository, plan_from_hierarchy_tree(_one_cell_tree()))

    assert "E/S/A/L/V102" in caplog.text


@pytest.mark.asyncio
async def test_prune_leaves_assets_outside_the_enterprise():
    repository = RecordingRepository()
    await repository.ensure_branch([AssetSpec(segment="OtherRoot", level="ENTERPRISE")])
    await apply_plan(repository, plan_from_hierarchy_tree(_one_cell_tree()))

    remaining = repository._path_set()
    assert "OtherRoot" in remaining
    assert "E" in remaining


@pytest.mark.asyncio
async def test_delete_asset_also_removes_descendants():
    repository = RecordingRepository()
    await apply_plan(repository, plan_from_hierarchy_tree(_two_cell_tree()))

    removed = await repository.delete_asset("E/S/A/L/V101")

    remaining = repository._path_set()
    assert "E/S/A/L/V101" not in remaining
    assert "E/S/A/L/V101/SCADA" not in remaining
    assert "E/S/A/L/V102" in remaining
    assert removed >= 2


def test_seed_dry_run_loads_plant_yaml_when_present(tmp_path, monkeypatch, capsys):
    plant_dir = tmp_path / "simulator"
    plant_dir.mkdir()
    (plant_dir / "plant.yaml").write_text(
        yaml.safe_dump(tree_to_mapping(_two_cell_tree())),
        encoding="utf-8",
    )
    monkeypatch.setattr("uns_model.cli.resolve_conf_dir", lambda: tmp_path)
    monkeypatch.setattr("uns_model.cli.get_settings", lambda *_args, **_kwargs: {})

    from uns_model.cli import seed

    assert seed(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "E/S/A/L/V101" in out
    assert "E/S/A/L/V102" in out
    assert "Prune under E" in out


def test_seed_falls_back_to_settings_hierarchy_when_plant_yaml_is_absent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("uns_model.cli.resolve_conf_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "uns_model.cli.get_settings",
        lambda *_args, **_kwargs: {
            "hierarchy": {
                "enterprise": "FromSettings",
                "site": "S",
                "area": "A",
                "line": "L",
                "cell": "C",
            },
            "plc": [],
            "equipment": {},
        },
    )

    from uns_model.cli import seed

    assert seed(["--dry-run"]) == 0
    assert "FromSettings/S/A/L/C" in capsys.readouterr().out
