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

Input object for writing an Alert Rule.

A whole rule at a time, deliberately: the console edits a rule in a form and saves
it, and there is no safe meaning for "update just the threshold of an alarm whose
condition I have not read".
"""

from typing import Any

import strawberry
from strawberry.scalars import JSON
from uns_model.alert_rules import AlertRuleSpec

from uns_graphql.type.alert_rule import AlertCategory, AlertCondition, AlertSeverity, ConsoleRole


def _as_int(value: int | str | None) -> int | None:
    """
    Whole numbers arrive as strings.

    Every `int` in this schema is the Int64 scalar (GraphQL's Int is 32-bit, and epoch
    milliseconds do not fit), and Int64 parses to a string. The driver would refuse a
    string for an integer column, so the conversion happens here rather than turning
    into a stack trace on save.
    """
    return None if value is None else int(value)


@strawberry.input(description="An Alert Rule to create or replace. The id is supplied by the console.")
class AlertRuleInput:
    id: str
    name: str
    severity: AlertSeverity
    category: AlertCategory
    topic: str
    metric_field: str
    condition: AlertCondition
    threshold_value: JSON = strawberry.field(description="A JSON scalar: a number, a string or a boolean")

    description: str = ""
    enabled: bool = True
    threshold_upper_value: float | None = None
    unit: str | None = None
    delay_seconds: int = 0
    escalation_role: ConsoleRole | None = None
    escalation_timeout_minutes: int | None = None
    notify_roles: list[ConsoleRole] = strawberry.field(default_factory=list)
    auto_resolve_on_normal: bool = True
    in_app_notification: bool = True
    audio_chime: bool = True
    mqtt_publish_on_trigger: bool = False
    mqtt_alarm_topic: str | None = None
    email_webhook: bool = False
    webhook_url: str | None = None

    def to_spec(self) -> AlertRuleSpec:
        """
        Translate to the repository's value object.

        The enums carry the strings the CHECK constraints expect, so nothing here
        needs to know what a valid severity is; `AlertRuleSpec.validate()` still
        has the last word.
        """
        threshold: Any = self.threshold_value
        return AlertRuleSpec(
            id=self.id,
            name=self.name,
            severity=self.severity.value,
            category=self.category.value,
            topic=self.topic,
            metric_field=self.metric_field,
            condition=self.condition.value,
            threshold_value=threshold,
            description=self.description,
            enabled=self.enabled,
            threshold_upper_value=self.threshold_upper_value,
            unit=self.unit,
            delay_seconds=int(self.delay_seconds),
            escalation_role=self.escalation_role.value if self.escalation_role else None,
            escalation_timeout_minutes=_as_int(self.escalation_timeout_minutes),
            auto_resolve_on_normal=self.auto_resolve_on_normal,
            in_app_notification=self.in_app_notification,
            audio_chime=self.audio_chime,
            mqtt_publish_on_trigger=self.mqtt_publish_on_trigger,
            mqtt_alarm_topic=self.mqtt_alarm_topic,
            email_webhook=self.email_webhook,
            webhook_url=self.webhook_url,
            roles=[role.value for role in self.notify_roles],
        )
