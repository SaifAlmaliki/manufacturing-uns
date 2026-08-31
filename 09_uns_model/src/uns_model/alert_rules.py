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

Reading and writing the console's Alert Rules.

The seam for schema `console`, kept apart from `AssetModelRepository` because an
Alert Rule is not part of the Asset Model: the model says what exists, a rule says
what somebody wants to be told about. They share a database and nothing else.

Rules used to live in the browser's localStorage, which made them a property of a
laptop rather than of the plant. Here they survive a cleared cache, a different
operator and a redeployed container.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from uns_model.engine import Database
from uns_model.tables import (
    ALERT_CATEGORIES,
    ALERT_CONDITIONS,
    ALERT_SEVERITIES,
    CONSOLE_ROLES,
    AlertRule,
    AlertRuleRole,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AlertRuleSpec:
    """
    One Alert Rule as the console authors it.

    A value object rather than twenty-odd keyword arguments: the console edits a
    whole rule at a time, and a partial update of an alarm threshold is not a
    thing anybody should be able to express by accident.
    """

    id: str
    name: str
    severity: str
    category: str
    topic: str
    metric_field: str
    condition: str
    threshold_value: Any
    description: str = ""
    enabled: bool = True
    threshold_upper_value: float | None = None
    unit: str | None = None
    delay_seconds: int = 0
    escalation_role: str | None = None
    escalation_timeout_minutes: int | None = None
    auto_resolve_on_normal: bool = True
    in_app_notification: bool = True
    audio_chime: bool = True
    mqtt_publish_on_trigger: bool = False
    mqtt_alarm_topic: str | None = None
    email_webhook: bool = False
    webhook_url: str | None = None
    roles: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """
        Reject what the vocabularies do not allow, before Postgres does.

        The CHECK constraints are the real guard; this exists so that a caller
        gets 'severity must be one of ...' instead of a driver-level constraint
        violation with a generated name in it.
        """
        if not self.id:
            raise ValueError("An Alert Rule needs an id")
        if not self.name:
            raise ValueError(f"Alert Rule {self.id!r} needs a name")
        if not self.topic:
            raise ValueError(f"Alert Rule {self.id!r} needs a topic to watch")
        _require_one_of("severity", self.severity, ALERT_SEVERITIES)
        _require_one_of("category", self.category, ALERT_CATEGORIES)
        _require_one_of("condition", self.condition, ALERT_CONDITIONS)
        if self.escalation_role is not None:
            _require_one_of("escalation_role", self.escalation_role, CONSOLE_ROLES)
        for role in self.roles:
            _require_one_of("role", role, CONSOLE_ROLES)
        if self.delay_seconds < 0:
            raise ValueError(f"Alert Rule {self.id!r} has a negative delay_seconds")
        if self.escalation_timeout_minutes is not None and self.escalation_timeout_minutes < 1:
            raise ValueError(f"Alert Rule {self.id!r} needs an escalation_timeout_minutes of at least 1")
        if self.condition == "RANGE_OUTSIDE" and self.threshold_upper_value is None:
            raise ValueError(f"Alert Rule {self.id!r} is RANGE_OUTSIDE, so it needs a threshold_upper_value")

    def column_values(self) -> dict[str, Any]:
        """The spec as column values, without the roles that live in their own table."""
        return {
            column.name: getattr(self, column.name) for column in fields(self) if column.name != "roles"
        }


def _require_one_of(what: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {list(allowed)}, got {value!r}")


class AlertRuleRepository:
    """
    The console's Alert Rules.

    Callers get whole rules and never a `Session`. Every write is an upsert by id,
    so the console can save a rule it has just edited without knowing whether the
    server has seen it before.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ------------------------------------------------------------------ writes

    async def save_rule(self, spec: AlertRuleSpec) -> AlertRule:
        """
        Create or replace one Alert Rule, including which roles it notifies.

        The roles are replaced wholesale rather than merged: the console sends the
        complete list, and a role silently surviving a removal is how an operator
        ends up paged for something somebody deliberately unsubscribed them from.
        """
        spec.validate()
        values = spec.column_values()
        async with self._database.session() as session:
            statement = (
                insert(AlertRule)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[AlertRule.id],
                    set_={key: value for key, value in values.items() if key != "id"}
                    | {"updated_at": func.now()},
                )
            )
            await session.execute(statement)

            await session.execute(delete(AlertRuleRole).where(AlertRuleRole.rule_id == spec.id))
            if spec.roles:
                await session.execute(
                    insert(AlertRuleRole)
                    .values([{"rule_id": spec.id, "role": role} for role in sorted(set(spec.roles))])
                    .on_conflict_do_nothing()
                )
            return (await session.execute(select(AlertRule).where(AlertRule.id == spec.id))).scalar_one()

    async def save_rules(self, specs: Sequence[AlertRuleSpec]) -> list[AlertRule]:
        """Save several rules, e.g. when a console migrates its local rules on first load."""
        return [await self.save_rule(spec) for spec in specs]

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule and its role subscriptions. False when there was nothing to delete."""
        async with self._database.session() as session:
            result = await session.execute(delete(AlertRule).where(AlertRule.id == rule_id))
            return bool(result.rowcount)

    async def set_enabled(self, rule_id: str, *, enabled: bool) -> AlertRule | None:
        """
        Enable or disable a rule without resending it.

        Its own method because muting an alarm is the one edit that has to be
        possible in one click, and it must not be able to change a threshold.
        """
        async with self._database.session() as session:
            await session.execute(
                update(AlertRule).where(AlertRule.id == rule_id).values(enabled=enabled, updated_at=func.now())
            )
            return (await session.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()

    async def record_evaluation(self, rule_id: str, *, triggered: bool) -> AlertRule | None:
        """
        Remember that a rule was evaluated, and whether it fired.

        Timestamps come from the database rather than from the caller: the console
        runs in a browser, and a wrong laptop clock must not be able to reorder
        the alarm history.
        """
        values: dict[str, Any] = {"last_evaluated_at": func.now()}
        if triggered:
            values["last_triggered_at"] = func.now()
            values["trigger_count"] = AlertRule.trigger_count + 1
        async with self._database.session() as session:
            await session.execute(update(AlertRule).where(AlertRule.id == rule_id).values(**values))
            return (await session.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()

    # ------------------------------------------------------------------- reads

    async def list_rules(self, *, enabled_only: bool = False, topic: str | None = None) -> list[AlertRule]:
        """Every Alert Rule, newest edit last, so the console renders a stable order."""
        statement = select(AlertRule).order_by(AlertRule.created_at, AlertRule.id)
        if enabled_only:
            statement = statement.where(AlertRule.enabled.is_(True))
        if topic is not None:
            statement = statement.where(AlertRule.topic == topic)
        async with self._database.session() as session:
            return list((await session.execute(statement)).scalars())

    async def get_rule(self, rule_id: str) -> AlertRule | None:
        async with self._database.session() as session:
            return (await session.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()

    async def counts(self) -> dict[str, int]:
        """How many rules exist, and how many are armed."""
        async with self._database.session() as session:
            total = (await session.execute(select(func.count()).select_from(AlertRule))).scalar_one()
            enabled = (
                await session.execute(select(func.count()).select_from(AlertRule).where(AlertRule.enabled.is_(True)))
            ).scalar_one()
        return {"rules": total, "enabled_rules": enabled}

    async def last_changed_at(self) -> datetime | None:
        """When any rule was last edited, for a console deciding whether to refetch."""
        async with self._database.session() as session:
            return (await session.execute(select(func.max(AlertRule.updated_at)))).scalar_one_or_none()


__all__ = ["AlertRuleRepository", "AlertRuleSpec"]
