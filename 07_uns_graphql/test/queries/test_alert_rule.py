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

Reading Alert Rules through the schema, with the repository replaced.

Executed against the real schema rather than by calling the resolvers, because the
schema is what the console talks to: a field renamed here is a broken console even
though every resolver still passes its own test. What the repository does with a
live Postgres is `09_uns_model/test/test_alert_rules.py`'s job.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uns_model.tables import AlertRule, AlertRuleRole

from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.queries.alert_rule._repository"


def _rule(rule_id: str = "rule-1", **overrides) -> AlertRule:
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
        "unit": "degC",
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
        "notify_roles": [AlertRuleRole(rule_id=rule_id, role="operator")],
    }
    values.update(overrides)
    return AlertRule(**values)


@pytest.mark.asyncio(loop_scope="function")
async def test_get_alert_rules_returns_what_the_repository_holds():
    repository = AsyncMock()
    repository.list_rules.return_value = [_rule("rule-1"), _rule("rule-2", enabled=False)]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """{ getAlertRules { id severity category condition thresholdValue notifyRoles enabled } }"""
        )

    assert result.errors is None
    assert result.data["getAlertRules"] == [
        {
            "id": "rule-1",
            "severity": "CRITICAL",
            "category": "TEMPERATURE",
            "condition": "GREATER_THAN",
            "thresholdValue": 180.0,
            "notifyRoles": ["OPERATOR"],
            "enabled": True,
        },
        {
            "id": "rule-2",
            "severity": "CRITICAL",
            "category": "TEMPERATURE",
            "condition": "GREATER_THAN",
            "thresholdValue": 180.0,
            "notifyRoles": ["OPERATOR"],
            "enabled": False,
        },
    ]
    repository.list_rules.assert_awaited_once_with(enabled_only=False, topic=None)


@pytest.mark.asyncio(loop_scope="function")
async def test_get_alert_rules_passes_the_filters_on():
    repository = AsyncMock()
    repository.list_rules.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """{ getAlertRules(enabledOnly: true, topic: "a/b/c") { id } }"""
        )

    assert result.errors is None
    assert result.data["getAlertRules"] == []
    repository.list_rules.assert_awaited_once_with(enabled_only=True, topic="a/b/c")


@pytest.mark.asyncio(loop_scope="function")
async def test_get_alert_rules_treats_an_empty_topic_as_no_filter():
    """A console clearing its filter box must not ask for the rules watching topic ''."""
    repository = AsyncMock()
    repository.list_rules.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute("""{ getAlertRules(topic: "") { id } }""")

    assert result.errors is None
    repository.list_rules.assert_awaited_once_with(enabled_only=False, topic=None)


@pytest.mark.asyncio(loop_scope="function")
async def test_get_alert_rule_by_id():
    repository = AsyncMock()
    repository.get_rule.return_value = _rule("rule-1", unit="degC")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute("""{ getAlertRule(id: "rule-1") { id unit topic } }""")

    assert result.errors is None
    assert result.data["getAlertRule"] == {
        "id": "rule-1",
        "unit": "degC",
        "topic": "enterprise/site/area/oven/temperature",
    }
    repository.get_rule.assert_awaited_once_with("rule-1")


@pytest.mark.asyncio(loop_scope="function")
async def test_get_alert_rule_is_null_for_an_unknown_id():
    """Null rather than an error: a console polling a rule somebody else deleted is normal."""
    repository = AsyncMock()
    repository.get_rule.return_value = None

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute("""{ getAlertRule(id: "nope") { id } }""")

    assert result.errors is None
    assert result.data["getAlertRule"] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_get_alert_rule_summary():
    repository = AsyncMock()
    repository.counts.return_value = {"rules": 4, "enabled_rules": 3}
    repository.last_changed_at.return_value = datetime(2026, 8, 31, 6, 30, tzinfo=UTC)

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute("""{ getAlertRuleSummary { rules enabledRules lastChangedAt } }""")

    assert result.errors is None
    assert result.data["getAlertRuleSummary"]["rules"] == 4
    assert result.data["getAlertRuleSummary"]["enabledRules"] == 3
    assert result.data["getAlertRuleSummary"]["lastChangedAt"].startswith("2026-08-31T06:30:00")


@pytest.mark.asyncio(loop_scope="function")
async def test_get_alert_rule_summary_on_an_empty_console():
    repository = AsyncMock()
    repository.counts.return_value = {"rules": 0, "enabled_rules": 0}
    repository.last_changed_at.return_value = None

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute("""{ getAlertRuleSummary { rules enabledRules lastChangedAt } }""")

    assert result.errors is None
    assert result.data["getAlertRuleSummary"] == {"rules": 0, "enabledRules": 0, "lastChangedAt": None}
