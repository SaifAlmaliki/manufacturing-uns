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

GraphQL queries for the console's Alert Rules.

The console is a static bundle served by nginx, so this is the only way it can read
a rule that somebody else authored. Rules used to live in each browser's
localStorage, which meant an alarm existed only for whoever created it.
"""

import logging

import strawberry
from uns_model.alert_rules import AlertRuleRepository
from uns_model.engine import Database

from uns_graphql.auth.scope import AccessScope, allowed_topic, scope_from_info
from uns_graphql.queries.asset import _context_resolver
from uns_graphql.type.alert_rule import AlertRuleSummary, AlertRuleType

LOGGER = logging.getLogger(__name__)


def _repository() -> AlertRuleRepository:
    return AlertRuleRepository(Database.shared("graphql"))


async def _visible_rules(scope: AccessScope, rules: list) -> list:
    """Keep rules whose topic the caller may see. Unrestricted callers skip binding."""
    if scope.unrestricted:
        return list(rules)
    resolver = _context_resolver()
    visible = []
    for rule in rules:
        if await allowed_topic(scope, rule.topic, resolver):
            visible.append(rule)
    return visible


@strawberry.type(description="Query the Alert Rules the console has authored")
class Query:
    """All read access to schema `console`."""

    @strawberry.field(description="Every Alert Rule, oldest first. Optionally only the armed ones, or one topic's.")
    async def get_alert_rules(
        self,
        info: strawberry.Info,
        enabled_only: bool = False,
        topic: str | None = strawberry.UNSET,
    ) -> list[AlertRuleType]:
        scope = await scope_from_info(info)
        rules = await _repository().list_rules(enabled_only=enabled_only, topic=topic or None)
        return [AlertRuleType.from_rule(rule) for rule in await _visible_rules(scope, rules)]

    @strawberry.field(description="One Alert Rule by id, or null when no such rule is stored.")
    async def get_alert_rule(self, info: strawberry.Info, id: str) -> AlertRuleType | None:  # noqa: A002
        rule = await _repository().get_rule(id)
        if rule is None:
            return None
        scope = await scope_from_info(info)
        if not scope.unrestricted and not await allowed_topic(scope, rule.topic, _context_resolver()):
            return None
        return AlertRuleType.from_rule(rule)

    @strawberry.field(
        description="Counts and the last edit time, so a console can decide whether to refetch the rules."
    )
    async def get_alert_rule_summary(self, info: strawberry.Info) -> AlertRuleSummary:
        repository = _repository()
        scope = await scope_from_info(info)
        if scope.unrestricted:
            counts = await repository.counts()
            return AlertRuleSummary(
                rules=counts["rules"],
                enabled_rules=counts["enabled_rules"],
                last_changed_at=await repository.last_changed_at(),
            )
        visible = await _visible_rules(scope, await repository.list_rules())
        return AlertRuleSummary(
            rules=len(visible),
            enabled_rules=sum(1 for rule in visible if rule.enabled),
            last_changed_at=max((rule.updated_at for rule in visible), default=None),
        )

    @classmethod
    async def on_shutdown(cls):
        """
        Nothing to do: the engine is shared with the Asset Model queries, which
        dispose it. Kept so every Query mixin has the same shape.
        """
