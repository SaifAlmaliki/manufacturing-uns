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

The vocabularies of an Alert Rule are written down twice: once as CHECK constraints
in `uns_model.tables` and once as GraphQL enums here. That is deliberate — a
published schema should not change shape because somebody edited a database
constraint — and these tests are what keeps the two copies honest.
"""

from datetime import UTC, datetime
from enum import Enum

import pytest
from uns_model.tables import (
    ALERT_CATEGORIES,
    ALERT_CONDITIONS,
    ALERT_SEVERITIES,
    CONSOLE_ROLES,
    AlertRule,
    AlertRuleRole,
)

from uns_graphql.type.alert_rule import (
    AlertCategory,
    AlertCondition,
    AlertRuleSummary,
    AlertRuleType,
    AlertSeverity,
    ConsoleRole,
)


@pytest.mark.parametrize(
    "graphql_enum, vocabulary",
    [
        (AlertSeverity, ALERT_SEVERITIES),
        (AlertCategory, ALERT_CATEGORIES),
        (AlertCondition, ALERT_CONDITIONS),
        (ConsoleRole, CONSOLE_ROLES),
    ],
)
def test_enums_match_the_database_vocabulary(graphql_enum: type[Enum], vocabulary: tuple[str, ...]):
    """
    A value the database accepts must be expressible in the schema, and vice versa.

    Fails both ways round on purpose: an enum member the CHECK constraint rejects is
    a mutation that always errors, and a vocabulary entry with no enum member is a
    stored rule the console cannot read back.
    """
    assert {member.value for member in graphql_enum} == set(vocabulary)


@pytest.mark.parametrize("vocabulary", [ALERT_SEVERITIES, ALERT_CATEGORIES, ALERT_CONDITIONS, CONSOLE_ROLES])
def test_vocabularies_have_no_duplicates(vocabulary: tuple[str, ...]):
    """A duplicate would make the set comparison above pass while the CHECK body repeats itself."""
    assert len(vocabulary) == len(set(vocabulary))


def _rule(**overrides) -> AlertRule:
    """A transient AlertRule, i.e. one the database has never seen."""
    values = {
        "id": "rule-1",
        "name": "Oven over temperature",
        "description": "Trips when the oven runs hot",
        "enabled": True,
        "severity": "CRITICAL",
        "category": "TEMPERATURE",
        "topic": "enterprise/site/area/oven/temperature",
        "metric_field": "value",
        "condition": "GREATER_THAN",
        "threshold_value": 180.0,
        "threshold_upper_value": None,
        "unit": "degC",
        "delay_seconds": 30,
        "escalation_role": "engineer",
        "escalation_timeout_minutes": 15,
        "auto_resolve_on_normal": True,
        "in_app_notification": True,
        "audio_chime": False,
        "mqtt_publish_on_trigger": True,
        "mqtt_alarm_topic": "enterprise/site/alarms/oven",
        "email_webhook": False,
        "webhook_url": None,
        "trigger_count": 7,
        "last_triggered_at": datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        "last_evaluated_at": datetime(2026, 8, 31, 6, 0, tzinfo=UTC),
        "created_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return AlertRule(**values)


def test_from_rule_maps_every_field():
    rule = _rule(notify_roles=[AlertRuleRole(role="operator"), AlertRuleRole(role="admin")])

    alert = AlertRuleType.from_rule(rule)

    assert alert.id == rule.id
    assert alert.name == rule.name
    assert alert.description == rule.description
    assert alert.enabled is True
    assert alert.severity is AlertSeverity.CRITICAL
    assert alert.category is AlertCategory.TEMPERATURE
    assert alert.topic == rule.topic
    assert alert.metric_field == "value"
    assert alert.condition is AlertCondition.GREATER_THAN
    assert alert.threshold_value == pytest.approx(180.0)
    assert alert.threshold_upper_value is None
    assert alert.unit == "degC"
    assert alert.delay_seconds == 30
    assert alert.escalation_role is ConsoleRole.ENGINEER
    assert alert.escalation_timeout_minutes == 15
    assert alert.auto_resolve_on_normal is True
    assert alert.in_app_notification is True
    assert alert.audio_chime is False
    assert alert.mqtt_publish_on_trigger is True
    assert alert.mqtt_alarm_topic == rule.mqtt_alarm_topic
    assert alert.email_webhook is False
    assert alert.webhook_url is None
    assert alert.trigger_count == 7
    assert alert.last_triggered_at == rule.last_triggered_at
    assert alert.last_evaluated_at == rule.last_evaluated_at
    assert alert.created_at == rule.created_at
    assert alert.updated_at == rule.updated_at


def test_from_rule_sorts_the_notified_roles():
    """The console renders the list, and a set that reorders itself reads as an edit."""
    rule = _rule(
        notify_roles=[AlertRuleRole(role="operator"), AlertRuleRole(role="admin"), AlertRuleRole(role="viewer")]
    )

    assert AlertRuleType.from_rule(rule).notify_roles == [
        ConsoleRole.ADMIN,
        ConsoleRole.OPERATOR,
        ConsoleRole.VIEWER,
    ]


def test_from_rule_without_escalation_or_roles():
    rule = _rule(escalation_role=None, escalation_timeout_minutes=None)

    alert = AlertRuleType.from_rule(rule)

    assert alert.escalation_role is None
    assert alert.escalation_timeout_minutes is None
    assert alert.notify_roles == []


@pytest.mark.parametrize("threshold", [180.0, 7, "RUNNING", True, None])
def test_threshold_value_survives_every_scalar_shape(threshold):
    """
    A STALE_TIMEOUT counts seconds, a CONTAINS matches text. The JSON scalar carries
    both unchanged; a float column would have quietly destroyed one of them.
    """
    assert AlertRuleType.from_rule(_rule(threshold_value=threshold)).threshold_value == threshold


def test_summary_defaults_to_no_last_change():
    """An empty console has no last edit, and that is not an error to report."""
    summary = AlertRuleSummary(rules=0, enabled_rules=0)

    assert (summary.rules, summary.enabled_rules, summary.last_changed_at) == (0, 0, None)
