"""Tests for the conf/oee/*.yaml importer.

`plan_from_oee_config` is a pure function of a mapping, so these need no database and no
files - which is the point of splitting planning from applying.
"""

from datetime import time

import pytest

from uns_model.oee_seed import plan_from_oee_config

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
