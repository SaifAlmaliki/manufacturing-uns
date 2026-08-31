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

GraphQL types for the console's Alert Rules, held in schema `console`.

The enums are spelled out rather than generated from `uns_model.tables`, because a
GraphQL schema is a published contract and a generated enum changes shape without
anybody reviewing it. `test/type/test_alert_rule.py` fails if the two drift.
"""

import logging
from datetime import datetime
from enum import Enum

import strawberry
from strawberry.scalars import JSON
from uns_model.tables import AlertRule

LOGGER = logging.getLogger(__name__)


@strawberry.enum(description="How badly an operator needs to care, per ISA-18.2 priority.")
class AlertSeverity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    WARNING = "WARNING"
    INFO = "INFO"


@strawberry.enum(description="What kind of condition the rule watches, used for grouping and icons.")
class AlertCategory(Enum):
    TEMPERATURE = "TEMPERATURE"
    PRESSURE = "PRESSURE"
    VIBRATION = "VIBRATION"
    FLOW_RATE = "FLOW_RATE"
    STALE_TIMEOUT = "STALE_TIMEOUT"
    NODE_OFFLINE = "NODE_OFFLINE"
    COMMUNICATION = "COMMUNICATION"
    THRESHOLD = "THRESHOLD"
    SAFETY = "SAFETY"
    CUSTOM = "CUSTOM"


@strawberry.enum(description="How the metric is compared against the threshold.")
class AlertCondition(Enum):
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    RANGE_OUTSIDE = "RANGE_OUTSIDE"
    STALE_TIMEOUT = "STALE_TIMEOUT"
    CONTAINS = "CONTAINS"


@strawberry.enum(description="A console role that can be notified when a rule fires.")
class ConsoleRole(Enum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    VIEWER = "viewer"


@strawberry.type(description="An ISA-18.2 Alert Rule as authored in the console and stored in Postgres.")
class AlertRuleType:
    """
    One Alert Rule.

    The counters and timestamps are read-only here: they are written by whoever
    evaluates the rule, through `recordAlertRuleEvaluation`, so that the alarm
    history is stamped by the database rather than by a browser clock.
    """

    id: str
    name: str
    description: str
    enabled: bool
    severity: AlertSeverity
    category: AlertCategory

    topic: str = strawberry.field(description="The topic the rule watches. May contain MQTT wildcards.")
    metric_field: str = strawberry.field(description="Which field of the payload is compared, e.g. 'value'")
    condition: AlertCondition
    threshold_value: JSON = strawberry.field(
        description="The threshold as a JSON scalar, so a rule can compare numbers, text or flags"
    )
    threshold_upper_value: float | None = strawberry.field(default=None, description="Upper bound for RANGE_OUTSIDE")
    unit: str | None = strawberry.field(
        default=None, description="Unit as typed by the engineer. Not a Metric Definition unit_of_measure."
    )

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

    trigger_count: int = 0
    last_triggered_at: datetime | None = None
    last_evaluated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_rule(cls, rule: AlertRule) -> "AlertRuleType":
        return cls(
            id=rule.id,
            name=rule.name,
            description=rule.description,
            enabled=rule.enabled,
            severity=AlertSeverity(rule.severity),
            category=AlertCategory(rule.category),
            topic=rule.topic,
            metric_field=rule.metric_field,
            condition=AlertCondition(rule.condition),
            # A JSON scalar rather than a float: a STALE_TIMEOUT counts seconds but a
            # CONTAINS matches text, and squeezing both into a number loses one of them.
            threshold_value=rule.threshold_value,
            threshold_upper_value=rule.threshold_upper_value,
            unit=rule.unit,
            delay_seconds=rule.delay_seconds,
            escalation_role=ConsoleRole(rule.escalation_role) if rule.escalation_role else None,
            escalation_timeout_minutes=rule.escalation_timeout_minutes,
            notify_roles=[ConsoleRole(role) for role in rule.roles],
            auto_resolve_on_normal=rule.auto_resolve_on_normal,
            in_app_notification=rule.in_app_notification,
            audio_chime=rule.audio_chime,
            mqtt_publish_on_trigger=rule.mqtt_publish_on_trigger,
            mqtt_alarm_topic=rule.mqtt_alarm_topic,
            email_webhook=rule.email_webhook,
            webhook_url=rule.webhook_url,
            trigger_count=rule.trigger_count,
            last_triggered_at=rule.last_triggered_at,
            last_evaluated_at=rule.last_evaluated_at,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )


@strawberry.type(description="How many Alert Rules exist and how many are armed.")
class AlertRuleSummary:
    rules: int
    enabled_rules: int
    last_changed_at: datetime | None = strawberry.field(
        default=None, description="When any rule was last edited, so a console can skip a refetch"
    )
