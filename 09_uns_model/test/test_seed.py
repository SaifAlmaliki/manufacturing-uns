"""
Unit tests for planning a seed. No database: planning is pure, which is the point
of separating it from `apply_plan`.
"""

from __future__ import annotations

import pytest

from uns_model.seed import SIMULATOR_LEVELS, apply_plan, plan_from_simulator_config

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


class RecordingRepository:
    """Records what a seed would write, at the repository seam."""

    def __init__(self) -> None:
        self.branches: list[list[str]] = []
        self.metrics: list[str] = []
        self.rebinds = 0

    async def ensure_branch(self, specs):
        self.branches.append([spec.segment for spec in specs])
        return None

    async def define_metric(self, metric_key, **kwargs):  # noqa: ARG002
        self.metrics.append(metric_key)
        return None

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
