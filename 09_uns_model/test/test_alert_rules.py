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

What an Alert Rule is allowed to be, checked without a database.

The rules the CHECK constraints enforce are duplicated in `AlertRuleSpec.validate`
on purpose, so that a console gets a sentence it can show a user instead of a
driver error. These tests are what keeps the two copies in agreement.
"""

from __future__ import annotations

import pytest

from uns_model.alert_rules import AlertRuleSpec
from uns_model.tables import ALERT_CATEGORIES, ALERT_CONDITIONS, ALERT_SEVERITIES, CONSOLE_ROLES


def _spec(**overrides) -> AlertRuleSpec:
    defaults = {
        "id": "rule-1",
        "name": "Mixer over temperature",
        "severity": "HIGH",
        "category": "TEMPERATURE",
        "topic": "Enterprise/Plant1/Area1/Line1/Cell1/Mixer1/ProcessValue/Temperature",
        "metric_field": "value",
        "condition": "GREATER_THAN",
        "threshold_value": 85.0,
    }
    return AlertRuleSpec(**(defaults | overrides))


def test_a_complete_rule_is_valid():
    _spec().validate()  # must not raise


@pytest.mark.parametrize("severity", ALERT_SEVERITIES)
def test_every_severity_in_the_vocabulary_is_accepted(severity: str):
    _spec(severity=severity).validate()


@pytest.mark.parametrize("category", ALERT_CATEGORIES)
def test_every_category_in_the_vocabulary_is_accepted(category: str):
    _spec(category=category).validate()


@pytest.mark.parametrize("condition", [c for c in ALERT_CONDITIONS if c != "RANGE_OUTSIDE"])
def test_every_condition_in_the_vocabulary_is_accepted(condition: str):
    _spec(condition=condition).validate()


@pytest.mark.parametrize("role", CONSOLE_ROLES)
def test_every_console_role_may_be_notified(role: str):
    _spec(roles=[role], escalation_role=role).validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("severity", "CATASTROPHIC"),
        ("category", "SMELL"),
        ("condition", "ROUGHLY_EQUALS"),
        ("escalation_role", "ceo"),
    ],
)
def test_a_value_outside_the_vocabulary_is_named_in_the_error(field: str, value: str):
    with pytest.raises(ValueError, match=f"{field} must be one of"):
        _spec(**{field: value}).validate()


def test_an_unknown_notified_role_is_rejected():
    with pytest.raises(ValueError, match="role must be one of"):
        _spec(roles=["engineer", "night-shift"]).validate()


@pytest.mark.parametrize(("field", "value"), [("id", ""), ("name", ""), ("topic", "")])
def test_the_mandatory_fields_are_mandatory(field: str, value: str):
    with pytest.raises(ValueError):
        _spec(**{field: value}).validate()


def test_a_negative_delay_is_rejected():
    # A rule that fires 5 seconds before the reading is nonsense, not a fast alarm.
    with pytest.raises(ValueError, match="negative delay_seconds"):
        _spec(delay_seconds=-5).validate()


def test_an_escalation_timeout_below_a_minute_is_rejected():
    with pytest.raises(ValueError, match="escalation_timeout_minutes"):
        _spec(escalation_timeout_minutes=0).validate()


def test_a_range_rule_without_an_upper_bound_is_rejected():
    """RANGE_OUTSIDE with one bound would never fire, which is worse than failing loudly."""
    with pytest.raises(ValueError, match="threshold_upper_value"):
        _spec(condition="RANGE_OUTSIDE", threshold_value=10.0).validate()


def test_a_range_rule_with_both_bounds_is_valid():
    _spec(condition="RANGE_OUTSIDE", threshold_value=10.0, threshold_upper_value=90.0).validate()


def test_a_threshold_may_be_any_json_scalar():
    # STALE_TIMEOUT counts seconds, CONTAINS matches text, EQUALS may match a flag.
    for threshold in (42, "RUNNING", True, 3.5):
        _spec(threshold_value=threshold).validate()


def test_column_values_leaves_the_roles_to_their_own_table():
    values = _spec(roles=["engineer", "operator"]).column_values()

    assert "roles" not in values
    assert values["id"] == "rule-1"
    assert values["threshold_value"] == 85.0
    # Every other field is present, so a save cannot silently drop a column.
    assert values["auto_resolve_on_normal"] is True
    assert values["mqtt_alarm_topic"] is None
