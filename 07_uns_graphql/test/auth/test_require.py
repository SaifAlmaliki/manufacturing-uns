"""Spec test 4: one case per cell of section 7's table.

Generated from the table rather than hand-written, so that adding a mutation without adding a
row is a failure and not an omission.
"""

import pytest

from uns_graphql.auth.require import (
    ANY_AUTHENTICATED_ROLE,
    MUTATION_ROLES,
    NotPermittedError,
    require,
)
from uns_graphql.auth.token import CONSOLE_ROLES, Identity

# Section 7 of docs/superpowers/specs/2026-09-02-console-authentication-design.md, copied.
# Deliberately a second copy: if the implementation's table and this one disagree, one of them
# is wrong and the test says so. A test that imported the table would agree with any table.
EXPECTED = {
    "saveAlertRule": {"engineer", "admin"},
    "saveAlertRules": {"engineer", "admin"},
    "deleteAlertRule": {"engineer", "admin"},
    "setAlertRuleEnabled": {"operator", "engineer", "admin"},
    "recordAlertRuleEvaluation": set(CONSOLE_ROLES),
    "assignDowntimeReason": {"operator", "engineer", "admin"},
}


class FakeInfo:
    def __init__(self, context):
        self.context = context


def _info(*roles: str) -> FakeInfo:
    return FakeInfo({"identity": Identity(subject="s", username="u", roles=frozenset(roles))})


def test_the_table_covers_exactly_the_six_mutations():
    # Six, per finding 3 and the assertion already in test/mutations/test_oee.py. A
    # seventh mutation must not be able to ship ungated.
    assert set(MUTATION_ROLES) == set(EXPECTED)


@pytest.mark.parametrize(
    ("mutation", "role"),
    [(mutation, role) for mutation, allowed in EXPECTED.items() for role in sorted(allowed)],
)
def test_an_allowed_role_is_permitted(mutation: str, role: str):
    identity = require(_info(role), mutation)

    assert identity.roles == frozenset({role})


@pytest.mark.parametrize(
    ("mutation", "role"),
    [
        (mutation, role)
        for mutation, allowed in EXPECTED.items()
        for role in sorted(CONSOLE_ROLES - allowed)
    ],
)
def test_a_role_outside_the_row_is_refused(mutation: str, role: str):
    with pytest.raises(NotPermittedError) as raised:
        require(_info(role), mutation)

    # Failure modes table: "GraphQL error naming the required role". An engineer who cannot
    # save a rule should learn which role they lack, not read "forbidden".
    message = str(raised.value)
    assert mutation in message
    for needed in sorted(EXPECTED[mutation]):
        assert needed in message


def test_holding_one_allowed_role_among_several_is_enough():
    identity = require(_info("viewer", "engineer"), "saveAlertRule")

    assert "engineer" in identity.roles


def test_no_recognised_role_can_read_but_not_mutate():
    # Failure modes table, last row. Task 3 already proved an unknown realm role is dropped;
    # this is what that user then experiences.
    with pytest.raises(NotPermittedError):
        require(_info(), "recordAlertRuleEvaluation")


def test_an_unauthenticated_context_is_refused_by_name():
    with pytest.raises(NotPermittedError) as raised:
        require(FakeInfo(None), "saveAlertRule")

    assert "not signed in" in str(raised.value).lower()


def test_an_unknown_mutation_name_is_a_programming_error_not_an_open_door():
    # A typo'd field name must not resolve to "no requirement".
    with pytest.raises(KeyError):
        require(_info("admin"), "saveAlertRulez")


def test_any_authenticated_role_is_the_five():
    assert ANY_AUTHENTICATED_ROLE == CONSOLE_ROLES
