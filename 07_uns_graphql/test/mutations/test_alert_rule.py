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

Writing Alert Rules through the schema, with the repository replaced.

These are the first mutations this service has ever exposed, so the tests also pin
down what stays read-only: an Asset or a historic event must not become writable by
accident.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uns_model.alert_rules import AlertRuleSpec
from uns_model.tables import AlertRule, AlertRuleRole

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.scope import AccessScope
from uns_graphql.auth.token import Identity
from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.mutations.alert_rule._repository"

# These tests are about what the mutations do, not about who may call them - that is
# test/auth/test_require.py, one case per cell. Admin, so Access Group checks are
# unrestricted and the repository is the only seam.
ADMIN = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000001",
        username="erin.engineer",
        roles=frozenset({"admin"}),
    )
}

MINIMAL_INPUT = {
    "id": "rule-1",
    "name": "Oven over temperature",
    "severity": "CRITICAL",
    "category": "TEMPERATURE",
    "topic": "enterprise/site/area/oven/temperature",
    "metricField": "value",
    "condition": "GREATER_THAN",
    "thresholdValue": 180.0,
}

SAVE_MUTATION = """
    mutation Save($rule: AlertRuleInput!) {
        saveAlertRule(rule: $rule) { id name severity notifyRoles thresholdValue }
    }
"""


def _rule(rule_id: str = "rule-1", roles: tuple[str, ...] = (), **overrides) -> AlertRule:
    values = {
        "id": rule_id,
        "name": "Oven over temperature",
        "description": "",
        "enabled": True,
        "severity": "CRITICAL",
        "category": "TEMPERATURE",
        "topic": "enterprise/site/area/oven/temperature",
        "metric_field": "value",
        "condition": "GREATER_THAN",
        "threshold_value": 180.0,
        "threshold_upper_value": None,
        "unit": None,
        "delay_seconds": 0,
        "escalation_role": None,
        "escalation_timeout_minutes": None,
        "auto_resolve_on_normal": True,
        "in_app_notification": True,
        "audio_chime": True,
        "mqtt_publish_on_trigger": False,
        "mqtt_alarm_topic": None,
        "email_webhook": False,
        "webhook_url": None,
        "trigger_count": 0,
        "last_triggered_at": None,
        "last_evaluated_at": None,
        "created_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "notify_roles": [AlertRuleRole(rule_id=rule_id, role=role) for role in roles],
    }
    values.update(overrides)
    return AlertRule(**values)


@pytest.mark.asyncio(loop_scope="function")
async def test_save_alert_rule_returns_the_rule_as_stored():
    """
    The stored rule, not the submitted one: the console needs the timestamps and the
    counters that only the database can fill in.
    """
    repository = AsyncMock()
    repository.save_rule.return_value = _rule(roles=("operator",))

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION, variable_values={"rule": MINIMAL_INPUT}, context_value=ADMIN
        )

    assert result.errors is None
    assert result.data["saveAlertRule"] == {
        "id": "rule-1",
        "name": "Oven over temperature",
        "severity": "CRITICAL",
        "notifyRoles": ["OPERATOR"],
        "thresholdValue": 180.0,
    }
    spec: AlertRuleSpec = repository.save_rule.await_args.args[0]
    assert spec.id == "rule-1"
    assert spec.severity == "CRITICAL"
    assert spec.roles == []


@pytest.mark.asyncio(loop_scope="function")
async def test_save_alert_rule_forwards_the_optional_settings():
    repository = AsyncMock()
    repository.save_rule.return_value = _rule()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION,
            variable_values={
                "rule": MINIMAL_INPUT
                | {
                    "enabled": False,
                    "delaySeconds": 30,
                    "escalationRole": "ENGINEER",
                    "escalationTimeoutMinutes": 15,
                    "notifyRoles": ["OPERATOR", "ADMIN"],
                    "mqttPublishOnTrigger": True,
                    "mqttAlarmTopic": "enterprise/site/alarms/oven",
                }
            },
            context_value=ADMIN,
        )

    assert result.errors is None
    spec: AlertRuleSpec = repository.save_rule.await_args.args[0]
    assert spec.enabled is False
    assert spec.delay_seconds == 30
    assert spec.escalation_role == "engineer"
    assert spec.escalation_timeout_minutes == 15
    assert spec.roles == ["operator", "admin"]
    assert spec.mqtt_publish_on_trigger is True
    assert spec.mqtt_alarm_topic == "enterprise/site/alarms/oven"


@pytest.mark.asyncio(loop_scope="function")
async def test_save_alert_rule_rejects_a_value_outside_the_vocabulary_before_the_database():
    """
    An unknown severity never reaches the repository: the enum is the guard, so a
    typo is a schema error the console can show next to the field.
    """
    repository = AsyncMock()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION,
            variable_values={"rule": MINIMAL_INPUT | {"severity": "CATASTROPHIC"}},
            context_value=ADMIN,
        )

    assert result.errors
    repository.save_rule.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_save_alert_rule_surfaces_a_repository_rejection():
    """`AlertRuleSpec.validate()` has the last word, and its message is what the operator reads."""
    repository = AsyncMock()
    repository.save_rule.side_effect = ValueError("Alert Rule 'rule-1' is RANGE_OUTSIDE, so it needs a ...")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION,
            variable_values={"rule": MINIMAL_INPUT | {"condition": "RANGE_OUTSIDE"}},
            context_value=ADMIN,
        )

    assert result.errors
    assert "RANGE_OUTSIDE" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_save_alert_rules_imports_a_whole_browser_full_of_rules():
    """The migration path off localStorage: one round trip, or the console half-migrates."""
    repository = AsyncMock()
    repository.save_rules.return_value = [_rule("rule-1"), _rule("rule-2")]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation Import($rules: [AlertRuleInput!]!) {
                saveAlertRules(rules: $rules) { id }
            }
            """,
            variable_values={"rules": [MINIMAL_INPUT, MINIMAL_INPUT | {"id": "rule-2"}]},
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveAlertRules"] == [{"id": "rule-1"}, {"id": "rule-2"}]
    specs = repository.save_rules.await_args.args[0]
    assert [spec.id for spec in specs] == ["rule-1", "rule-2"]


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("deleted", [True, False])
async def test_delete_alert_rule_reports_whether_there_was_anything_to_delete(deleted: bool):
    repository = AsyncMock()
    repository.get_rule.return_value = _rule() if deleted else None
    repository.delete_rule.return_value = deleted

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """mutation { deleteAlertRule(id: "rule-1") }""", context_value=ADMIN
        )

    assert result.errors is None
    assert result.data["deleteAlertRule"] is deleted
    if deleted:
        repository.delete_rule.assert_awaited_once_with("rule-1")
    else:
        repository.delete_rule.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_set_alert_rule_enabled_mutes_without_resending_the_rule():
    repository = AsyncMock()
    repository.get_rule.return_value = _rule()
    repository.set_enabled.return_value = _rule(enabled=False)

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """mutation { setAlertRuleEnabled(id: "rule-1", enabled: false) { id enabled thresholdValue } }""",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["setAlertRuleEnabled"] == {"id": "rule-1", "enabled": False, "thresholdValue": 180.0}
    repository.set_enabled.assert_awaited_once_with("rule-1", enabled=False)


@pytest.mark.asyncio(loop_scope="function")
async def test_set_alert_rule_enabled_is_null_for_an_unknown_rule():
    repository = AsyncMock()
    repository.get_rule.return_value = None

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """mutation { setAlertRuleEnabled(id: "nope", enabled: true) { id } }""",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["setAlertRuleEnabled"] is None
    repository.set_enabled.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_record_alert_rule_evaluation_returns_the_counters():
    repository = AsyncMock()
    repository.get_rule.return_value = _rule()
    repository.record_evaluation.return_value = _rule(
        trigger_count=8,
        last_triggered_at=datetime(2026, 8, 31, 6, 30, tzinfo=UTC),
        last_evaluated_at=datetime(2026, 8, 31, 6, 30, tzinfo=UTC),
    )

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation { recordAlertRuleEvaluation(id: "rule-1", triggered: true) {
                id triggerCount lastTriggeredAt lastEvaluatedAt
            } }
            """,
            context_value=ADMIN,
        )

    assert result.errors is None
    recorded = result.data["recordAlertRuleEvaluation"]
    assert recorded["triggerCount"] == 8
    assert recorded["lastTriggeredAt"].startswith("2026-08-31T06:30:00")
    repository.record_evaluation.assert_awaited_once_with("rule-1", triggered=True)


@pytest.mark.asyncio(loop_scope="function")
async def test_record_alert_rule_evaluation_is_null_for_an_unknown_rule():
    """A rule deleted while an evaluator was mid-cycle is not an error worth waking anybody for."""
    repository = AsyncMock()
    repository.get_rule.return_value = None

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """mutation { recordAlertRuleEvaluation(id: "nope", triggered: false) { id } }""",
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["recordAlertRuleEvaluation"] is None
    repository.record_evaluation.assert_not_awaited()


def test_only_alert_rules_are_writable():
    """
    Process data is written by publishing to the broker. Hierarchy writes YAML then
    reseeds; downtime assignment is the one plant-data correction. Access Groups are
    admin-only plant-scope writes. Connectivity catalog writes (Task 5) are the
    engineer + admin curation of OPC UA servers and their tags. An extra mutation must
    be a decision, not an accident.
    """
    mutation = UNSGraphql.schema.get_type_by_name("Mutation")
    names = {field.name for field in mutation.fields}

    assert names == {
        "save_alert_rule",
        "save_alert_rules",
        "delete_alert_rule",
        "set_alert_rule_enabled",
        "record_alert_rule_evaluation",
        "assign_downtime_reason",
        "save_hierarchy",
        "retry_hierarchy_migrate",
        "save_access_group",
        "delete_access_group",
        "set_access_group_members",
        "save_connectivity_server",
        "delete_connectivity_server",
        "subscribe_opc_ua_variables",
        "update_connectivity_tag_topic",
        "unsubscribe_connectivity_tag",
    }


@pytest.mark.asyncio(loop_scope="function")
async def test_a_viewer_cannot_save_a_rule_and_is_told_which_role_they_need():
    """
    Through the real schema, not a fake info: `strawberry.Info` injection is exactly what a
    fake context cannot prove, and a resolver that stopped receiving it would silently see
    None and refuse everybody.
    """
    viewer = {
        CONTEXT_KEY: Identity(subject="s", username="val.viewer", roles=frozenset({"viewer"}))
    }
    repository = AsyncMock()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION, variable_values={"rule": MINIMAL_INPUT}, context_value=viewer
        )

    assert result.errors
    assert "engineer" in result.errors[0].message
    # Refused before the database, not after.
    repository.save_rule.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_an_operator_may_mute_a_rule_but_not_rewrite_it():
    """The one row of the table that differs from its neighbours, checked end to end."""
    operator = {
        CONTEXT_KEY: Identity(subject="s", username="olga.operator", roles=frozenset({"operator"}))
    }
    repository = AsyncMock()
    repository.get_rule.return_value = _rule()
    repository.set_enabled.return_value = _rule(enabled=False)
    any_plant = AccessScope(unrestricted=True, root_paths=frozenset())

    with (
        patch(REPOSITORY, return_value=repository),
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=any_plant)),
    ):
        muted = await UNSGraphql.schema.execute(
            """mutation { setAlertRuleEnabled(id: "rule-1", enabled: false) { id } }""",
            context_value=operator,
        )
        rewritten = await UNSGraphql.schema.execute(
            SAVE_MUTATION, variable_values={"rule": MINIMAL_INPUT}, context_value=operator
        )

    assert muted.errors is None
    assert rewritten.errors
