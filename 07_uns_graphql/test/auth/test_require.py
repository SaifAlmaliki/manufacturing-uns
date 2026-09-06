"""Spec test 4: one case per cell of section 7's table.

Generated from the table rather than hand-written, so that adding a mutation without adding a
row is a failure and not an omission.
"""

from unittest.mock import AsyncMock, patch

import pytest

from uns_graphql.auth.require import (
    ANY_AUTHENTICATED_ROLE,
    MUTATION_ROLES,
    NotPermittedError,
    OPC_PROBE_ROLES,
    require,
    require_path,
    require_role,
)
from uns_graphql.auth.scope import AccessScope
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
    "saveHierarchy": {"admin"},
    "retryHierarchyMigrate": {"admin"},
    "saveAccessGroup": {"admin"},
    "deleteAccessGroup": {"admin"},
    "setAccessGroupMembers": {"admin"},
    # Connectivity catalog writes: authoring a server and curating its tags is
    # engineering work, so the five writes are engineer + admin (Task 5 brief).
    "saveConnectivityServer": {"engineer", "admin"},
    "deleteConnectivityServer": {"engineer", "admin"},
    "subscribeOpcUaVariables": {"engineer", "admin"},
    "updateConnectivityTagTopic": {"engineer", "admin"},
    "unsubscribeConnectivityTag": {"engineer", "admin"},
    "saveUnitOfMeasure": {"engineer", "admin"},
    "saveSignalLabel": {"engineer", "admin"},
    "updateConnectivityTag": {"engineer", "admin"},
}


class FakeInfo:
    def __init__(self, context):
        self.context = context


def _info(*roles: str) -> FakeInfo:
    return FakeInfo({"identity": Identity(subject="s", username="u", roles=frozenset(roles))})


def test_the_table_covers_exactly_the_six_mutations():
    # Every published mutation must have a row. The name is historical (there were
    # six); the assertion counts all keys so a new mutation cannot ship ungated.
    assert set(MUTATION_ROLES) == set(EXPECTED)
    assert len(MUTATION_ROLES) == len(EXPECTED)


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


@pytest.mark.asyncio
async def test_require_path_refuses_unsigned_in():
    with pytest.raises(NotPermittedError) as raised:
        await require_path(FakeInfo(None), "AcmeWater/Site1/Filtration")

    assert str(raised.value) == (
        "This Asset or topic is outside your Access Groups: AcmeWater/Site1/Filtration."
    )


@pytest.mark.asyncio
async def test_require_path_allows_admin_for_any_path():
    identity = await require_path(_info("admin"), "AcmeWater/Site1/RawWater")

    assert "admin" in identity.roles


@pytest.mark.asyncio
async def test_require_path_refuses_a_path_outside_the_scope():
    filt = AccessScope(unrestricted=False, root_paths=frozenset({"AcmeWater/Site1/Filtration"}))
    with (
        patch("uns_graphql.auth.require.scope_for", AsyncMock(return_value=filt)),
        pytest.raises(NotPermittedError) as raised,
    ):
        await require_path(_info("operator"), "AcmeWater/Site1/RawWater")

    assert str(raised.value) == (
        "This Asset or topic is outside your Access Groups: AcmeWater/Site1/RawWater."
    )


@pytest.mark.asyncio
async def test_require_path_allows_a_path_inside_the_scope():
    filt = AccessScope(unrestricted=False, root_paths=frozenset({"AcmeWater/Site1/Filtration"}))
    with patch("uns_graphql.auth.require.scope_for", AsyncMock(return_value=filt)):
        identity = await require_path(_info("operator"), "AcmeWater/Site1/Filtration/Train1")

    assert "operator" in identity.roles


# --------------------------------------------------------------- require_role (queries)


def test_opc_probe_roles_are_engineer_and_admin():
    assert OPC_PROBE_ROLES == frozenset({"engineer", "admin"})


@pytest.mark.parametrize("role", sorted(OPC_PROBE_ROLES))
def test_require_role_permits_an_allowed_role(role: str):
    identity = require_role(_info(role), OPC_PROBE_ROLES)

    assert role in identity.roles


@pytest.mark.parametrize("role", sorted(CONSOLE_ROLES - OPC_PROBE_ROLES))
def test_require_role_refuses_a_role_outside_the_set(role: str):
    with pytest.raises(NotPermittedError) as raised:
        require_role(_info(role), OPC_PROBE_ROLES)

    message = str(raised.value)
    for needed in sorted(OPC_PROBE_ROLES):
        assert needed in message


def test_require_role_refuses_an_unauthenticated_context():
    with pytest.raises(NotPermittedError) as raised:
        require_role(FakeInfo(None), OPC_PROBE_ROLES)

    assert "not signed in" in str(raised.value).lower()


def test_require_role_admits_when_one_of_several_roles_matches():
    identity = require_role(_info("viewer", "admin"), OPC_PROBE_ROLES)

    assert "admin" in identity.roles
