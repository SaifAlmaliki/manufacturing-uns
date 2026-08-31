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

`AlertRuleInput.to_spec()` is the only translation between the published schema and
the repository, so a field it forgets is a setting an operator saves and never sees
again.
"""

from dataclasses import fields

import pytest
from uns_model.alert_rules import AlertRuleSpec

from uns_graphql.input.alert_rule import AlertRuleInput
from uns_graphql.type.alert_rule import AlertCategory, AlertCondition, AlertSeverity, ConsoleRole


def _input(**overrides) -> AlertRuleInput:
    values = {
        "id": "rule-1",
        "name": "Oven over temperature",
        "severity": AlertSeverity.CRITICAL,
        "category": AlertCategory.TEMPERATURE,
        "topic": "enterprise/site/area/oven/temperature",
        "metric_field": "value",
        "condition": AlertCondition.GREATER_THAN,
        "threshold_value": 180.0,
    }
    values.update(overrides)
    return AlertRuleInput(**values)


def test_to_spec_translates_enums_to_the_stored_strings():
    spec = _input(escalation_role=ConsoleRole.ENGINEER).to_spec()

    assert spec.severity == "CRITICAL"
    assert spec.category == "TEMPERATURE"
    assert spec.condition == "GREATER_THAN"
    assert spec.escalation_role == "engineer"
    spec.validate()  # the strings the CHECK constraints expect, not the enum names


def test_to_spec_carries_every_field_of_the_spec():
    """
    Guards against a field added to `AlertRuleSpec` that nothing in the schema can set.

    `roles` is the one rename: GraphQL calls it notifyRoles, because "roles" on a rule
    reads as "roles that may edit it".
    """
    graphql_names = {field.name for field in fields(AlertRuleInput)}
    spec_names = {field.name for field in fields(AlertRuleSpec)}

    assert spec_names - graphql_names == {"roles"}
    assert "notify_roles" in graphql_names


def test_to_spec_renames_notify_roles_and_keeps_them_all():
    spec = _input(notify_roles=[ConsoleRole.OPERATOR, ConsoleRole.ADMIN]).to_spec()

    assert spec.roles == ["operator", "admin"]
    spec.validate()


def test_to_spec_defaults_to_an_armed_rule_that_notifies_nobody():
    """
    Enabled by default, because a rule an engineer just wrote is one they want armed.
    Silent by default, because notifying a role nobody asked for is worse than a rule
    only the console shows.
    """
    spec = _input().to_spec()

    assert spec.enabled is True
    assert spec.roles == []
    assert spec.escalation_role is None
    assert spec.delay_seconds == 0
    assert spec.description == ""


def test_to_spec_turns_the_int64_strings_back_into_numbers():
    """
    Every `int` in this schema is the Int64 scalar, which parses to a string. Without
    the conversion the driver is handed '30' for an integer column and the save fails.
    """
    spec = _input(delay_seconds="30", escalation_timeout_minutes="15").to_spec()

    assert spec.delay_seconds == 30
    assert spec.escalation_timeout_minutes == 15
    spec.validate()


def test_to_spec_keeps_an_absent_escalation_timeout_absent():
    """0 is not 'no timeout': `validate()` rejects 0, and NULL is what 'never' means."""
    assert _input(escalation_timeout_minutes=None).to_spec().escalation_timeout_minutes is None


@pytest.mark.parametrize("threshold", [180.0, 7, "RUNNING", True])
def test_to_spec_passes_the_threshold_through_unchanged(threshold):
    assert _input(threshold_value=threshold).to_spec().threshold_value == threshold


def test_to_spec_produces_a_spec_that_can_reject_itself():
    """The schema cannot express a bad severity, but it can express a bad range."""
    spec = _input(condition=AlertCondition.RANGE_OUTSIDE).to_spec()

    with pytest.raises(ValueError, match="threshold_upper_value"):
        spec.validate()

    _input(condition=AlertCondition.RANGE_OUTSIDE, threshold_upper_value=200.0).to_spec().validate()
