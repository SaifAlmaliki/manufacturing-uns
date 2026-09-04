---
status: accepted
---

# GraphQL mutations for console configuration

The GraphQL server was read-only: queries and subscriptions over what the plant has
published, plus the authored Asset Model. It now also exposes five mutations, all of
them for the console's Alert Rules, and those rules live in Postgres schema
`console` instead of in each browser's `localStorage`.

Alert Rules were browser-local. An engineer who defined "oven over 180 °C is
critical" had defined it on their laptop: the operator on the next shift saw no
alarm, clearing site data deleted the configuration, and nothing outside that one
tab could evaluate a rule. An Alert Rule is plant configuration — it belongs to the
site, like the Asset Model does.

## Considered Options

**A backend for the console** was rejected. The console is a static bundle served by
nginx (`11_frontend`), which is what makes it deployable anywhere and swappable for
Grafana or a customer's own HMI. Giving it a private API server would make the
platform's config depend on the frontend being deployed, and would be a third
Postgres client to configure.

**Publishing rules to MQTT and letting the historian persist them** was rejected.
It reuses the existing write path, but a rule is not an observation: a topic that
carries both process data and the configuration describing that data is a topic
nobody can subscribe to safely, retained-message semantics become the config's
consistency model, and there is no way to answer "is this rule stored" except to
wait.

**Writes on the GraphQL server** was chosen. It already holds the shared
`uns_model` engine that the Asset Model queries use, it is already the console's
only backend, and a mutation returns the stored row — so the console can show the
database's timestamps rather than trusting its own clock.

The mutation surface is deliberately narrow, and stays narrow. Process data is
written by publishing to the broker. The Asset Model is authored in
`conf/settings.yaml` and applied by the `asset_model_setup` container, so the plant
hierarchy is reviewable in version control rather than editable in a form. What is
left is configuration that has nowhere else to live.

Whole rules are written, never fields: `saveAlertRule` replaces a rule and its
notified roles together. "Update just the threshold of an alarm whose condition I
have not read" has no safe meaning, and a role surviving a removal is how somebody
gets paged for an alarm they unsubscribed from.

The four vocabularies (severity, category, condition, role) are written twice: as
CHECK constraints in `uns_model.tables` and as GraphQL enums in
`uns_graphql.type.alert_rule`. Generating the enums from the constraints was
rejected because a published schema should not change shape because somebody edited
a database constraint. `test/type/test_alert_rule.py` fails if the two drift.

## Consequences

The GraphQL server needs write access to schema `console`, so its database role is
no longer read-only and its integration tests need the Alembic migrations applied.

Anyone who can reach `/graphql` can now change alarm configuration. There is no
authorization in this service — the `notifyRoles` on a rule say who gets told, not
who may edit — so the deployment has to keep the endpoint off untrusted networks
until authentication exists.

> **Updated (2026-09):** this service now authenticates every request and
> authorizes every mutation against the caller's realm roles. See ADR-0009 for
> the design and `07_uns_graphql/src/uns_graphql/auth/require.py` for the table.
> The argument above — that the mutation surface stays narrow, and that a write
> belongs here only because the console has no backend of its own — is unchanged,
> and authentication does not widen it. The paragraph it amends is left visible:
> a record of a decision that has moved on is more useful than one that pretends
> it never said otherwise.

Rules authored before this change are in browser storage, which the server cannot
see. `saveAlertRules` exists so a console can hand over everything it has in one
round trip on first load; a browser that is never opened again keeps its rules to
itself.

Evaluation is still the console's job: it reads the rules and reports back through
`recordAlertRuleEvaluation`. So alarms are only evaluated while somebody has the
console open. Moving evaluation into a service is now possible — the rules are
readable by anything with a database connection — but it is not done here.

## Addendum (2026-09-04)

The plant hierarchy is still YAML (`conf/simulator/plant.yaml`) and remains
reviewable in version control, but `saveHierarchy` may now write it through
GraphQL, so the mutation surface is no longer alert-rules-only.

A graph prefix rename is not durable while anything still publishes the old
prefix. The mapper `MERGE`s a node per topic segment, so live traffic on the
old path recreates the old branch beside the renamed one. The rename sticks
only after the publisher is retargeted. This slice does not retarget the
simulator; the console banner on the hierarchy page says so.
