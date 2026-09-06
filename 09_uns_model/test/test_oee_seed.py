"""Tests for the conf/oee/*.yaml importer.

`plan_from_oee_config` is a pure function of a mapping, so planning tests need no
database. The shipped-conf check reads the real plant and OEE files so setup cannot
name an Asset that seed will not create.
"""

from datetime import UTC, datetime, time

import pytest
from sqlalchemy.dialects import postgresql
from uns_config import resolve_conf_dir

from uns_model.hierarchy_io import load_plant_tree
from uns_model.oee_master_data import (
    ProductSpec,
    ShiftPatternSpec,
    ShiftSlotSpec,
    deactivate_patterns_absent_from,
    deactivate_products_absent_from,
    deactivate_units_absent_from,
    delete_cycle_times_absent_from,
    delete_exceptions_absent_from,
    delete_state_rules_absent_from,
    oee_unit_upsert,
    product_upsert,
    shift_pattern_upsert,
)
from uns_model.oee_seed import apply_plan, plan_from_oee_config, read_oee_conf
from uns_model.seed import plan_from_hierarchy_tree

CONFIG = {
    "products": {"products": [{"code": "R-100-STD", "name": "Resin 100 standard"}]},
    "shifts": {
        "patterns": [
            {
                "name": "Dormagen 3-shift",
                "timezone": "Europe/Berlin",
                "asset": "CovestroAG/Dormagen/Production/Line1",
                "slots": [
                    {"days": [0, 1], "start": "06:00", "duration_minutes": 480, "label": "A"},
                    {"days": [0], "start": "22:00", "duration_minutes": 480, "label": "C"},
                ],
            }
        ],
        "exceptions": [
            {
                "starts_at": "2026-12-24T00:00:00+01:00",
                "ends_at": "2026-12-27T00:00:00+01:00",
                "kind": "HOLIDAY",
                "note": "Christmas shutdown",
            }
        ],
    },
    "units": {
        "units": [
            {
                "asset": "CovestroAG/Dormagen/Production/Line1",
                "shift_pattern": "Dormagen 3-shift",
                "state_metric_key": "Cell1/MES-01/Status/PackMlState/value",
                "good_count_metric_key": "Cell1/MES-01/ProcessValue/GoodCount/value",
                "reject_count_metric_key": "Cell1/MES-01/ProcessValue/RejectCount/value",
                "product_metric_key": "Cell1/MES-01/Status/RecipeId/value",
                "producing_states": ["EXECUTE"],
                "ideal_cycle_times": [
                    {"seconds_per_unit": 3.0},
                    {"product": "R-100-STD", "seconds_per_unit": 2.4},
                ],
            }
        ]
    },
    "reasons": {
        "reasons": [{"code": "NO_ORDER", "display_name": "No order", "is_planned": True}],
        "state_rules": [{"state": "IDLE", "reason": "NO_ORDER"}],
    },
}


def test_a_slot_is_expanded_once_per_day_it_names():
    plan = plan_from_oee_config(CONFIG)
    slots = plan.patterns[0].slots
    assert [(slot.day_of_week, slot.start_time, slot.label) for slot in slots] == [
        (0, time(6, 0), "A"),
        (1, time(6, 0), "A"),
        (0, time(22, 0), "C"),
    ]
    assert all(slot.duration_minutes == 480 for slot in slots)


def test_ideal_cycle_times_carry_the_units_asset_and_an_optional_product():
    plan = plan_from_oee_config(CONFIG)
    assert [(spec.product_code, spec.seconds_per_unit) for spec in plan.cycle_times] == [
        (None, 3.0),
        ("R-100-STD", 2.4),
    ]
    assert all(spec.asset_path == "CovestroAG/Dormagen/Production/Line1" for spec in plan.cycle_times)


def test_exception_without_an_asset_applies_to_every_asset():
    plan = plan_from_oee_config(CONFIG)
    assert plan.exceptions[0].asset_path is None
    assert plan.exceptions[0].kind == "HOLIDAY"
    assert plan.exceptions[0].starts_at.utcoffset().total_seconds() == 3600


def test_state_rule_without_an_asset_is_the_platform_default():
    plan = plan_from_oee_config(CONFIG)
    assert plan.state_reason_rules[0].asset_path is None
    assert plan.state_reason_rules[0].state_value == "IDLE"


def test_an_unknown_shift_pattern_name_is_rejected_before_the_database_sees_it():
    broken = {**CONFIG, "units": {"units": [{**CONFIG["units"]["units"][0], "shift_pattern": "Nope"}]}}
    with pytest.raises(ValueError, match="Nope"):
        plan_from_oee_config(broken)


def test_a_producing_state_must_not_also_have_a_reason_rule():
    broken = {
        **CONFIG,
        "reasons": {
            "reasons": CONFIG["reasons"]["reasons"],
            "state_rules": [{"state": "EXECUTE", "reason": "NO_ORDER"}],
        },
    }
    with pytest.raises(ValueError, match="EXECUTE"):
        plan_from_oee_config(broken)


def test_describe_lists_what_would_be_written():
    described = plan_from_oee_config(CONFIG).describe()
    assert "Dormagen 3-shift" in described
    assert "CovestroAG/Dormagen/Production/Line1" in described
    assert "NO_ORDER" in described


def test_a_full_config_records_every_oee_conf_file_as_present():
    assert plan_from_oee_config(CONFIG).present_files == {"products", "shifts", "units", "reasons"}


def test_a_shifts_only_config_records_only_the_shifts_file_as_present():
    assert plan_from_oee_config({"shifts": CONFIG["shifts"]}).present_files == {"shifts"}


def compile_pg(statement) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled).lower(), dict(compiled.params)


def test_saving_a_product_again_reactivates_it():
    sql, _params = compile_pg(product_upsert(ProductSpec(code="R-100-STD", name="Resin")))
    assert "on conflict" in sql
    assert "is_active" in sql
    assert "do update" in sql


def test_saving_a_shift_pattern_again_reactivates_it():
    spec = ShiftPatternSpec(
        name="Dormagen 3-shift",
        timezone="Europe/Berlin",
        slots=(ShiftSlotSpec(day_of_week=0, start_time=time(6, 0), duration_minutes=480, label="A"),),
    )
    sql, _params = compile_pg(shift_pattern_upsert(spec, asset_id=None))
    assert "on conflict" in sql
    assert "is_active" in sql


def test_saving_an_oee_unit_again_reactivates_it():
    values = {
        "asset_id": 1,
        "shift_pattern_id": 2,
        "state_metric_key": "state",
        "good_count_metric_key": "good",
        "reject_count_metric_key": None,
        "product_metric_key": None,
        "producing_states": ["EXECUTE"],
    }
    sql, _params = compile_pg(oee_unit_upsert(values))
    assert "on conflict" in sql
    assert "is_active" in sql


def test_products_absent_from_the_plan_are_deactivated_not_deleted():
    sql, params = compile_pg(deactivate_products_absent_from(("R-100-STD",)))
    assert sql.startswith("update")
    assert "is_active" in sql
    assert "delete from" not in sql
    assert "product" in sql
    bound = [item for value in params.values() for item in (value if isinstance(value, list) else [value])]
    assert "R-100-STD" in bound


def test_patterns_absent_from_the_plan_are_deactivated_not_deleted():
    sql, _params = compile_pg(deactivate_patterns_absent_from(("Dormagen 3-shift",)))
    assert sql.startswith("update")
    assert "shift_pattern" in sql
    assert "is_active" in sql
    assert "delete from" not in sql


def test_units_absent_from_the_plan_are_deactivated_not_deleted():
    sql, _params = compile_pg(deactivate_units_absent_from((7,)))
    assert sql.startswith("update")
    assert "oee_unit" in sql
    assert "is_active" in sql
    assert "delete from" not in sql


def test_exceptions_absent_from_the_plan_are_deleted():
    holiday = (
        None,
        datetime(2026, 12, 24, tzinfo=UTC),
        datetime(2026, 12, 27, tzinfo=UTC),
        "HOLIDAY",
    )
    keep = (holiday,)
    sql, _params = compile_pg(delete_exceptions_absent_from(keep))
    assert "delete from" in sql
    assert "shift_exception" in sql
    assert "is not" in sql  # IS NOT DISTINCT FROM, so a NULL asset_id still matches


def test_an_empty_exception_plan_deletes_every_exception():
    sql, _params = compile_pg(delete_exceptions_absent_from(()))
    assert "delete from" in sql
    assert "shift_exception" in sql
    assert "where" not in sql


def test_cycle_times_absent_from_the_plan_are_deleted():
    sql, _params = compile_pg(delete_cycle_times_absent_from(((1, None),)))
    assert "delete from" in sql
    assert "ideal_cycle_time" in sql


def test_state_rules_absent_from_the_plan_are_deleted():
    sql, _params = compile_pg(delete_state_rules_absent_from(((None, "IDLE"),)))
    assert "delete from" in sql
    assert "state_reason_map" in sql


class RecordingOeeRepository:
    """Records apply_plan's writes, at the repository seam."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def save_product(self, _spec):
        self.calls.append("save_product")

    async def save_downtime_reason(self, _spec):
        self.calls.append("save_downtime_reason")

    async def save_shift_pattern(self, _spec):
        self.calls.append("save_shift_pattern")

    async def save_shift_exception(self, _spec):
        self.calls.append("save_shift_exception")

    async def save_oee_unit(self, _spec):
        self.calls.append("save_oee_unit")

    async def save_ideal_cycle_time(self, _spec):
        self.calls.append("save_ideal_cycle_time")

    async def save_state_reason_rule(self, _spec):
        self.calls.append("save_state_reason_rule")

    async def reconcile_products(self, _specs):
        self.calls.append("reconcile_products")

    async def reconcile_shift_patterns(self, _specs):
        self.calls.append("reconcile_shift_patterns")

    async def reconcile_shift_exceptions(self, _specs):
        self.calls.append("reconcile_shift_exceptions")

    async def reconcile_oee_units(self, _specs):
        self.calls.append("reconcile_oee_units")

    async def reconcile_ideal_cycle_times(self, _specs):
        self.calls.append("reconcile_ideal_cycle_times")

    async def reconcile_state_reason_rules(self, _specs):
        self.calls.append("reconcile_state_reason_rules")


@pytest.mark.asyncio
async def test_apply_plan_reconciles_rows_the_files_no_longer_declare():
    repository = RecordingOeeRepository()
    await apply_plan(repository, plan_from_oee_config(CONFIG))

    assert repository.calls.index("save_product") < repository.calls.index("reconcile_products")
    assert "reconcile_shift_exceptions" in repository.calls
    assert "reconcile_oee_units" in repository.calls
    assert "reconcile_shift_patterns" in repository.calls
    assert "reconcile_ideal_cycle_times" in repository.calls
    assert "reconcile_state_reason_rules" in repository.calls
    assert "reconcile_downtime_reasons" not in repository.calls


@pytest.mark.asyncio
async def test_a_shifts_only_plan_does_not_reconcile_units_or_products():
    repository = RecordingOeeRepository()
    await apply_plan(repository, plan_from_oee_config({"shifts": CONFIG["shifts"]}))

    assert "reconcile_shift_patterns" in repository.calls
    assert "reconcile_shift_exceptions" in repository.calls
    assert "reconcile_oee_units" not in repository.calls
    assert "reconcile_products" not in repository.calls
    assert "reconcile_ideal_cycle_times" not in repository.calls
    assert "reconcile_state_reason_rules" not in repository.calls


def test_shipped_oee_assets_exist_in_the_shipped_plant():
    """`uns_model_setup` seeds, then imports OEE. A unit that names a missing Asset
    crashes the Asset Model CI job — seed writes HalabjaWTP, leftover Covestro paths fail.
    """
    plant = plan_from_hierarchy_tree(load_plant_tree(resolve_conf_dir()))
    oee = plan_from_oee_config(read_oee_conf())
    required = {
        *(spec.asset_path for spec in oee.units),
        *(spec.asset_path for spec in oee.patterns if spec.asset_path),
        *(spec.asset_path for spec in oee.exceptions if spec.asset_path),
        *(spec.asset_path for spec in oee.cycle_times),
        *(spec.asset_path for spec in oee.state_reason_rules if spec.asset_path),
    }
    missing = sorted(path for path in required if path not in plant.asset_paths)
    assert missing == [], f"OEE YAML names Assets that seed will not create: {missing}"
