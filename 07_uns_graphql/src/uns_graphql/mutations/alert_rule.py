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

The only writes this service accepts: the console's Alert Rules.

Everything else in this schema is read-only, and stays that way. UNS Nodes, historic
events and Kafka streams are observations — they are written by publishing to the
broker, not by calling an API. An Alert Rule is not an observation: it is
configuration a human authors, and the console that authors it is a static bundle
with no backend of its own (ADR-0005).

The Asset Model is deliberately *not* writable here either. It is authored in
`conf/settings.yaml` and applied by the Asset Model container, so that the plant
hierarchy is reviewable in version control.
"""

import logging

import strawberry
from uns_model.alert_rules import AlertRuleRepository
from uns_model.engine import Database

from uns_graphql.auth.require import require
from uns_graphql.input.alert_rule import AlertRuleInput
from uns_graphql.type.alert_rule import AlertRuleType

LOGGER = logging.getLogger(__name__)


def _repository() -> AlertRuleRepository:
    return AlertRuleRepository(Database.shared("graphql"))


@strawberry.type(description="Author the console's Alert Rules")
class Mutation:
    """All write access to schema `console`, and who may exercise it.

    The role each field needs is in `auth/require.py`'s one table, not in these resolvers.
    """

    @strawberry.mutation(
        description="Create or replace one Alert Rule and return it as stored. "
        "Fails with a readable message when a value is outside the allowed vocabulary."
    )
    async def save_alert_rule(self, info: strawberry.Info, rule: AlertRuleInput) -> AlertRuleType:
        require(info, "saveAlertRule")
        saved = await _repository().save_rule(rule.to_spec())
        LOGGER.info("Alert Rule %s saved for topic %s", saved.id, saved.topic)
        return AlertRuleType.from_rule(saved)

    @strawberry.mutation(
        description="Create or replace several Alert Rules at once. Used by a console importing "
        "the rules it had kept in browser storage."
    )
    async def save_alert_rules(
        self, info: strawberry.Info, rules: list[AlertRuleInput]
    ) -> list[AlertRuleType]:
        require(info, "saveAlertRules")
        saved = await _repository().save_rules([rule.to_spec() for rule in rules])
        LOGGER.info("Imported %s Alert Rule(s)", len(saved))
        return [AlertRuleType.from_rule(rule) for rule in saved]

    @strawberry.mutation(description="Delete an Alert Rule. False when there was no such rule.")
    async def delete_alert_rule(self, info: strawberry.Info, id: str) -> bool:  # noqa: A002
        require(info, "deleteAlertRule")
        deleted = await _repository().delete_rule(id)
        if deleted:
            LOGGER.info("Alert Rule %s deleted", id)
        return deleted

    @strawberry.mutation(
        description="Arm or mute an Alert Rule without resending it. Null when there is no such rule."
    )
    async def set_alert_rule_enabled(
        self, info: strawberry.Info, id: str, enabled: bool  # noqa: A002
    ) -> AlertRuleType | None:
        require(info, "setAlertRuleEnabled")
        rule = await _repository().set_enabled(id, enabled=enabled)
        return AlertRuleType.from_rule(rule) if rule else None

    @strawberry.mutation(
        description="Record that a rule was evaluated, and whether it fired. The timestamps are the "
        "database's, so a browser with a wrong clock cannot reorder the alarm history."
    )
    async def record_alert_rule_evaluation(
        self, info: strawberry.Info, id: str, triggered: bool  # noqa: A002
    ) -> AlertRuleType | None:
        require(info, "recordAlertRuleEvaluation")
        rule = await _repository().record_evaluation(id, triggered=triggered)
        return AlertRuleType.from_rule(rule) if rule else None

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the queries, which dispose it."""
