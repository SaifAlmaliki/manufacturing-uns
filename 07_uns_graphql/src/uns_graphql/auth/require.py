"""Who may write what, and who may see which plant path.

One table, because a policy spread across resolvers cannot be reviewed and cannot be
tested cell by cell. Keys are the camelCase field names the schema publishes, so that a
reader of this file and a reader of the GraphQL schema are looking at the same names.

Queries are not open. Plant reads go through `scope_for`: an admin sees the whole tree,
everyone else sees only Assets under their Access Group roots. `require_path` is the
write-side check for a single Asset path.
"""

from __future__ import annotations

from typing import Any

from uns_graphql.auth.context import identity_in
from uns_graphql.auth.scope import scope_for
from uns_graphql.auth.token import CONSOLE_ROLES, Identity

ANY_AUTHENTICATED_ROLE: frozenset[str] = CONSOLE_ROLES

MUTATION_ROLES: dict[str, frozenset[str]] = {
    # Authoring a rule is engineering work.
    "saveAlertRule": frozenset({"engineer", "admin"}),
    "saveAlertRules": frozenset({"engineer", "admin"}),
    "deleteAlertRule": frozenset({"engineer", "admin"}),
    # Separated from the editors deliberately: silencing a nuisance alarm during a shift is
    # operator work, and authoring the rule that produced it is not.
    "setAlertRuleEnabled": frozenset({"operator", "engineer", "admin"}),
    # Open, because the browser-side evaluator calls this as a consequence of a rule firing
    # (ADR-0005), not as a user action. Gating it would make the alarm history depend on which
    # role happens to have the console open. If evaluation ever moves server-side, this
    # becomes a service-account call and closes to users entirely.
    "recordAlertRuleEvaluation": ANY_AUTHENTICATED_ROLE,
    # The one plant-data write this platform allows.
    "assignDowntimeReason": frozenset({"operator", "engineer", "admin"}),
    # Whole-tree replace of settings.yaml hierarchy plus prefix migrate. Admin only.
    "saveHierarchy": frozenset({"admin"}),
    "retryHierarchyMigrate": frozenset({"admin"}),
    # Access Groups: who may see which Asset subtree. Admin only.
    "saveAccessGroup": frozenset({"admin"}),
    "deleteAccessGroup": frozenset({"admin"}),
    "setAccessGroupMembers": frozenset({"admin"}),
    # Connectivity catalog writes (Task 5): authoring a server and curating its
    # tags is engineering work, so the five writes are engineer + admin.
    "saveConnectivityServer": frozenset({"engineer", "admin"}),
    "deleteConnectivityServer": frozenset({"engineer", "admin"}),
    "subscribeOpcUaVariables": frozenset({"engineer", "admin"}),
    "updateConnectivityTagTopic": frozenset({"engineer", "admin"}),
    "unsubscribeConnectivityTag": frozenset({"engineer", "admin"}),
}


class NotPermittedError(Exception):
    """The caller is authenticated and lacks the role. The message reaches the client."""


def require(info: Any, mutation: str) -> Identity:
    """The caller's identity, if their roles allow this mutation.

    `KeyError` on an unknown name rather than a permissive default: a typo in a field name
    must not read as "no requirement".
    """
    allowed = MUTATION_ROLES[mutation]

    identity = identity_in(getattr(info, "context", None))
    if identity is None:
        raise NotPermittedError(
            f"{mutation} needs a signed-in user. You are not signed in."
        )

    if not identity.has_any(allowed):
        needed = ", ".join(sorted(allowed))
        raise NotPermittedError(
            f"{mutation} needs one of these roles: {needed}. "
            f"You hold: {', '.join(sorted(identity.roles)) or 'no recognised role'}."
        )

    return identity


async def require_path(info: Any, path: str) -> Identity:
    """The caller's identity, if `path` sits inside their Access Groups.

    Unsigned-in and out-of-scope share one sentence: the client should not learn
    whether the path exists when they cannot see it.
    """
    identity = identity_in(getattr(info, "context", None))
    if identity is None:
        raise NotPermittedError(f"This Asset or topic is outside your Access Groups: {path}.")

    scope = await scope_for(identity)
    if not scope.covers_path(path):
        raise NotPermittedError(f"This Asset or topic is outside your Access Groups: {path}.")

    return identity


def require_role(info: Any, allowed: frozenset[str]) -> Identity:
    """The caller's identity, if their roles include one of `allowed`.

    The query-side counterpart of `require`: the mutation table names a field, a query
    or subscription gates by the role set directly, because there is no single role a
    probe "is". Used for the OPC UA probes, which open an anonymous session to a PLC and
    so are engineer + admin work, not a viewer's.
    """
    identity = identity_in(getattr(info, "context", None))
    if identity is None:
        raise NotPermittedError(
            "This query needs a signed-in user. You are not signed in."
        )

    if not identity.has_any(allowed):
        needed = ", ".join(sorted(allowed))
        raise NotPermittedError(
            f"This query needs one of these roles: {needed}. "
            f"You hold: {', '.join(sorted(identity.roles)) or 'no recognised role'}."
        )

    return identity


# OPC UA probes open an anonymous session to a PLC the caller names; a viewer must not
# be able to point the console at an arbitrary opc.tcp endpoint. Engineer + admin, like
# the connectivity writes.
OPC_PROBE_ROLES: frozenset[str] = frozenset({"engineer", "admin"})
