"""Plant writes refuse Assets and topics outside the caller's Access Groups."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.require import NotPermittedError
from uns_graphql.auth.scope import AccessScope
from uns_graphql.auth.token import Identity
from uns_graphql.mutations.alert_rule import Mutation as AlertRuleMutation
from uns_graphql.mutations.oee import Mutation as OeeMutation

FILT = "AcmeWater/Site1/Filtration"
RAW = "AcmeWater/Site1/RawWater"
RAW_TOPIC = f"{RAW}/x"

ALERT_REPOSITORY = "uns_graphql.mutations.alert_rule._repository"
OEE_REPOSITORY = "uns_graphql.mutations.oee._repository"
CONTEXT_RESOLVER = "uns_graphql.queries.asset._context_resolver"


def _info(*roles: str) -> SimpleNamespace:
    return SimpleNamespace(
        context={CONTEXT_KEY: Identity("op", "omar", frozenset(roles))}
    )


def _filt_scope() -> AccessScope:
    return AccessScope(False, frozenset({FILT}))


def _rule_input(topic: str = RAW_TOPIC):
    return SimpleNamespace(topic=topic, to_spec=lambda: SimpleNamespace(topic=topic))


def _bind_topic():
    async def resolve(candidate: str):
        if candidate.startswith(FILT):
            return SimpleNamespace(asset_path=FILT)
        if candidate.startswith(RAW):
            return SimpleNamespace(asset_path=RAW)
        return None

    return SimpleNamespace(resolve=AsyncMock(side_effect=resolve))


@pytest.mark.asyncio
async def test_save_alert_rule_refuses_a_topic_outside_the_groups():
    """An engineer who may author rules still cannot aim one at another plant."""
    repository = AsyncMock()
    with (
        patch(ALERT_REPOSITORY, return_value=repository),
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=_filt_scope())),
        patch(
            CONTEXT_RESOLVER,
            return_value=_bind_topic(),
        ),
        pytest.raises(NotPermittedError, match="outside your Access Groups"),
    ):
        await AlertRuleMutation().save_alert_rule(_info("engineer"), _rule_input())

    repository.save_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_alert_rules_refuses_before_any_row_is_written():
    """A batch must not half-import: one out-of-scope topic refuses the lot."""
    repository = AsyncMock()
    rules = [_rule_input(f"{FILT}/temp"), _rule_input(RAW_TOPIC)]
    with (
        patch(ALERT_REPOSITORY, return_value=repository),
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=_filt_scope())),
        patch(
            CONTEXT_RESOLVER,
            return_value=_bind_topic(),
        ),
        pytest.raises(NotPermittedError, match=RAW_TOPIC),
    ):
        await AlertRuleMutation().save_alert_rules(_info("engineer"), rules)

    repository.save_rules.assert_not_awaited()
    repository.save_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_alert_rule_is_false_when_the_rule_is_missing():
    """Same return as today: missing is False, not a permission error."""
    repository = AsyncMock()
    repository.get_rule.return_value = None
    with patch(ALERT_REPOSITORY, return_value=repository):
        deleted = await AlertRuleMutation().delete_alert_rule(_info("engineer"), "nope")

    assert deleted is False
    repository.delete_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_alert_rule_refuses_a_topic_outside_the_groups():
    repository = AsyncMock()
    repository.get_rule.return_value = SimpleNamespace(id="rule-1", topic=RAW_TOPIC)
    with (
        patch(ALERT_REPOSITORY, return_value=repository),
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=_filt_scope())),
        patch(
            CONTEXT_RESOLVER,
            return_value=_bind_topic(),
        ),
        pytest.raises(NotPermittedError, match="outside your Access Groups"),
    ):
        await AlertRuleMutation().delete_alert_rule(_info("engineer"), "rule-1")

    repository.delete_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_alert_rule_enabled_is_null_when_the_rule_is_missing():
    repository = AsyncMock()
    repository.get_rule.return_value = None
    with patch(ALERT_REPOSITORY, return_value=repository):
        result = await AlertRuleMutation().set_alert_rule_enabled(
            _info("operator"), "nope", enabled=False
        )

    assert result is None
    repository.set_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_alert_rule_evaluation_refuses_a_topic_outside_the_groups():
    repository = AsyncMock()
    repository.get_rule.return_value = SimpleNamespace(id="rule-1", topic=RAW_TOPIC)
    with (
        patch(ALERT_REPOSITORY, return_value=repository),
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=_filt_scope())),
        patch(
            CONTEXT_RESOLVER,
            return_value=_bind_topic(),
        ),
        pytest.raises(NotPermittedError, match="outside your Access Groups"),
    ):
        await AlertRuleMutation().record_alert_rule_evaluation(
            _info("operator"), "rule-1", triggered=True
        )

    repository.record_evaluation.assert_not_awaited()


@pytest.mark.asyncio
async def test_assign_downtime_reason_refuses_an_asset_outside_the_groups():
    """Load first: an out-of-scope stop must not be attributed, then hidden."""
    repository = AsyncMock()
    repository.get_downtime_event.return_value = SimpleNamespace(asset_path=RAW)
    with (
        patch(OEE_REPOSITORY, return_value=repository),
        patch("uns_graphql.auth.require.scope_for", AsyncMock(return_value=_filt_scope())),
        pytest.raises(NotPermittedError, match="outside your Access Groups"),
    ):
        await OeeMutation().assign_downtime_reason(
            _info("operator"), event_id="11", reason_code="CHANGEOVER"
        )

    repository.assign_reason.assert_not_awaited()
