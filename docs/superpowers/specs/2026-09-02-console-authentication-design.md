# Console authentication

Date: 2026-09-02
Modules: `11_frontend`, `07_uns_graphql`, `09_uns_model`, `docker-compose.yml`, `conf`,
`08_uns_observability`, new ADR
Status: Approved, not yet implemented

## 1. Problem

The console has a login screen, five roles, a permission matrix and an audit log. None of it
authenticates anybody.

`11_frontend/src/context/AuthContext.tsx:417`–`:438` resolves a login by trying the
identifier as an id, then an email, then a substring of a name, and then falling through to
`users[0]`. The password parameter is named `_password` and never read. Any string in the
username box logs in as `usr-admin-01`. An empty string does too.

The users, their roles, their permissions and the audit log are all in `localStorage`, so
they are per-browser, editable from the developer console, and gone when the profile is
cleared. `SystemHealthView.tsx:76` describes this arrangement as `ENFORCED (ZERO-TRUST)`.

Behind it, the read surface has no authorization at all. ADR-0005 states it plainly: "There is
no authorization in this service. Anyone who can reach `/graphql` can now change alarm
configuration." `07_uns_graphql/src/uns_graphql/mutations/oee.py` documents the same gap in
its own description — the `assignedBy` on a reason reassignment is "Attested by the caller,
not authenticated: this platform has no authentication anywhere." ADR-0001 records Grafana
running with anonymous access and an Admin org role as "a known security gap, deliberately
accepted", and names OIDC as "the documented target".

This spec makes the login real, gives the GraphQL service an identity to authorize against,
and puts Grafana behind the same realm.

## 2. Relationship to the operations console spec

`2026-09-02-operations-console-design.md` removes the UI that claims enforcement exists — the
`ENFORCED (ZERO-TRUST)` badge, the capability matrix, the `ISO/IEC 62443` claims — and reduces
`/users` to a read-only list labelled `browser-local, not enforced`. That spec is truthful
without this one.

This spec then makes the claim true and restores `/users` to something meaningful. Neither
blocks the other, and the console spec should ship first: an honest console with no
authentication is a better state than a dishonest console, and a dishonest console with
authentication bolted on is the worst of the three.

One coupling runs the other way and is recorded in section 10: the console spec embeds
Grafana, which works today only because Grafana is anonymous. Closing that gap changes how
the embed authenticates.

## 3. Findings that shape the design

1. **The role vocabulary already exists in the schema.**
   `07_uns_graphql/src/uns_graphql/type/alert_rule.py:70` publishes `ConsoleRole` with
   `ADMIN`, `ENGINEER`, `OPERATOR`, `AUDITOR`, `VIEWER`, and
   `11_frontend/src/types/rbac.ts:5` declares the same five as `UserRole` in lowercase.
   `lib/alarms/map-alert-rules.ts:53`–`:60` already converts between the two cases. The realm
   does not need a new role model; it needs to be the authority for the one that exists.
2. **Alert Rules already carry role references.** `AlertRuleInput` has `escalation_role` and
   `notify_roles` (`input/alert_rule.py:62`, `:64`). These are currently unenforceable
   labels. With a realm they become role names that resolve to real group membership.
3. **Every mutation is already funnelled.** `uns_graphql_app.py:68` composes exactly two
   mutation classes, `AlertRuleMutation` and `OeeMutation`, across six mutations total. The
   authorization surface to cover is small and enumerable.
4. **The service is a FastAPI app with a single GraphQL router.**
   `uns_graphql_app.py:122`–`:138` mounts one `GraphQLRouter` at `/graphql` behind
   `CORSMiddleware`. There is one place to add token validation.
5. **The console is a static bundle.** ADR-0005 records that the console "is a static bundle"
   with nowhere to keep server-side state, which is why its configuration lives in Postgres.
   The same fact dictates the OIDC flow: a static bundle has no server side to hold a client
   secret, so Authorization Code with PKCE is the only correct choice. Implicit flow is not
   an option.
6. **`assignedBy` is a free-text string.** `mutations/oee.py` takes
   `assigned_by: str | None` and stores it (`oee_results.py`). Nothing validates it. Once a
   token exists, the argument stops being an input.
7. **The console reaches GraphQL through a proxy path.** `nginx.conf:7` proxies `/graphql`
   and `vite.config.ts:23` mirrors it. Same-origin, so a token in an `Authorization` header
   needs no CORS change; `CORSMiddleware` already allows all headers
   (`uns_graphql_app.py:136`).
8. **Grafana's embedding depends on its anonymity.** `docker-compose.yml:397`–`:399` sets
   `GF_AUTH_ANONYMOUS_ENABLED`, `GF_AUTH_ANONYMOUS_ORG_ROLE: Admin` and
   `GF_SECURITY_ALLOW_EMBEDDING`. ADR-0001 says the anonymous setting "does make iframe
   embedding in the console trivial, which is how the System Health panel stops lying."
   Removing it without replacing the session breaks three embeds.
9. **`conf/` is the established home for authored configuration.** Every service mounts
   `./conf:/app/conf` and reads `UNS_CONF_DIR`. A realm export belongs there, consistent with
   `conf/oee/*.yaml` and `conf/simulator/*.yaml`.
10. **Nothing else on the platform authenticates.** The broker publishes on 1883 unencrypted
    and unauthenticated (`docker-compose.yml:36`), Neo4j and Postgres are published to the
    host, and the simulator's control API has no user identity — `docker-compose.yml:308`
    says so explicitly, which is why its port stays unpublished. A console login does not
    secure the platform, and section 11 requires the UI to say so.

## 4. Scope

In scope:

- A Keycloak service in `docker-compose.yml` with a realm provisioned from `conf/`.
- OIDC Authorization Code + PKCE in the console, replacing `AuthContext`'s fake login.
- JWT validation against the realm's JWKS in `07_uns_graphql`, and role-based authorization
  on the six mutations.
- `assignedBy` sourced from the token subject.
- Grafana onto the same realm.
- `/users` restored to a real read-only view of realm membership.
- An ADR recording the decision and superseding the accepted gaps in ADR-0001 and ADR-0005.

Out of scope:

- MQTT, Kafka, Neo4j and Postgres authentication. Named as remaining gaps, not closed.
- The simulator control API's lack of identity. ADR-0007's territory.
- User and role administration in the console. That is Keycloak's job; see section 8.
- Any change to what the six mutations do.
- Multi-tenancy, service accounts for the mapper modules, mutual TLS.

## 5. Identity provider

Keycloak, as a compose service, with the realm exported to `conf/keycloak/realm.json` and
imported on start.

Why Keycloak rather than a hand-rolled login: the platform needs a JWKS endpoint, a token
endpoint that supports PKCE, and a role model that both a React bundle and a Python service
can read. Writing those is writing an identity provider, and the failure modes of a
hand-rolled one are exactly the failure modes this spec exists to remove.

The realm defines:

- One public client for the console, PKCE required, no client secret, with the console's
  origins as valid redirect URIs — the compose port (8088) and the dev port (5173), both from
  `platform/settings.ts`.
- One confidential client for Grafana.
- Five realm roles matching `ConsoleRole` exactly: `admin`, `engineer`, `operator`,
  `auditor`, `viewer`. The names are the lowercase form already in `rbac.ts:5`, so the
  existing `toUserRole` / `toConsoleRole` conversion keeps working unchanged.
- Development users, one per role, with passwords in the realm export. The export is marked
  clearly as a development artefact, in the same spirit as `docker-compose.yml`'s own "DO NOT
  USE FOR PRODUCTION DEPLOYMENT".

The realm export is authored and committed, not created by clicking through the admin
console, so a fresh `docker compose up` produces the same realm every time.

## 6. Console

`AuthContext` keeps its public shape — `user`, `roles`, `hasPermission`, `login`, `logout` —
so the components consuming it do not all change at once. What changes is what backs it.

- Authorization Code with PKCE, per finding 5. The bundle holds no secret.
- Tokens in memory, with a refresh token in a `SameSite=Strict` cookie or, if the realm is
  configured for it, silent refresh through a hidden iframe. Access tokens are not written to
  `localStorage`: the current design's habit of persisting identity in `localStorage` is part
  of what made it fake.
- `login` becomes a redirect to the realm, not a function returning `boolean`. The
  `LoginView` password field is deleted rather than wired up — the console must never see a
  password.
- `roles` comes from the token's realm roles, mapped through the existing `toUserRole`.
  A role not in the five is dropped, following the precedent in
  `map-alert-rules.ts:50`–`:56`: "Anything unrecognised is dropped rather than guessed."
- `hasPermission` keeps its call sites but resolves against token roles. It gates UI
  affordances only. It is not security — section 7 is.
- The `localStorage` user directory, permission matrix and audit log are deleted. The audit
  log in particular is worse than nothing: a per-browser, user-editable record of who did
  what.
- Every GraphQL request carries `Authorization: Bearer <token>`, added once in
  `services/graphql/client.ts`. The WebSocket carries the token in its
  `connection_init` payload, which is where `graphql-transport-ws` puts credentials.
- A 401 triggers one silent refresh attempt, then a redirect to the realm. It does not
  silently render an empty table, which is the failure mode the console spec's section 20
  rejects.

## 7. GraphQL service

Token validation in `07_uns_graphql`, at the single point finding 4 identifies.

- A dependency that reads the bearer token, validates the signature against the realm's JWKS
  (cached, refreshed on unknown `kid`), and checks issuer, audience and expiry. The JWKS URL
  and expected issuer come from `PlatformConfig`, which is where `cors_origins` already lives
  (`uns_graphql_app.py:133`).
- The validated claims go into the Strawberry context, so resolvers read an identity rather
  than a header.
- **Queries stay readable by any authenticated role.** The read surface is plant data, and an
  operator who cannot read the plant cannot work. Anonymous access to queries ends, but no
  query is role-gated.
- **Mutations are role-gated.** All six, per finding 3:

  | Mutation | Required role |
  | --- | --- |
  | `saveAlertRule` | `engineer`, `admin` |
  | `saveAlertRules` | `engineer`, `admin` |
  | `deleteAlertRule` | `engineer`, `admin` |
  | `setAlertRuleEnabled` | `operator`, `engineer`, `admin` |
  | `recordAlertRuleEvaluation` | any authenticated role |
  | `assignDowntimeReason` | `operator`, `engineer`, `admin` |

  `setAlertRuleEnabled` is separated from the editors deliberately: silencing a nuisance
  alarm during a shift is operator work, and authoring the rule that produced it is not.
  `recordAlertRuleEvaluation` is open because the browser-side evaluator calls it as a
  consequence of a rule firing (ADR-0005), not as a user action — gating it would make
  evaluation depend on who happens to have the console open.

- **`assignedBy` stops being an argument.** It is taken from the token subject's preferred
  username. The argument is removed from the mutation, and the description that reads
  "Attested by the caller, not authenticated" is replaced with what the field then means. A
  reassignment is signed by whoever was logged in. This is the concrete win: the one plant-data
  write the platform allows stops being anonymous.
- A rejected request returns a GraphQL error naming the missing role, not a bare 403. An
  engineer who cannot save a rule should learn which role they lack.

`09_uns_model` changes only where `assign_reason`'s signature loses its caller-supplied
`assigned_by`.

## 8. Users

`/users` becomes a read-only view of realm membership: who exists, which of the five roles
they hold, and when they last signed in, read through Keycloak's admin API for callers
holding `admin`. Creating users, resetting passwords and assigning roles link out to the
Keycloak admin console.

The console does not own the directory. A user CRUD screen in a static bundle would either
hold admin credentials in the browser or reimplement Keycloak's admin API behind a service
that does not exist. The console spec's reduction of `/users` to a read-only list is
therefore the permanent shape, not a temporary one — this spec only makes the data real.

## 9. Grafana

Grafana moves to OIDC against the same realm, using the confidential client from section 5.
`GF_AUTH_ANONYMOUS_ENABLED` is removed. Realm roles map to Grafana org roles: `admin` to
`Admin`, `engineer` to `Editor`, everything else to `Viewer`.

This closes the gap ADR-0001 accepted. It also breaks the three embeds the console spec adds,
unless the embed carries a session — see section 10.

## 10. The embedding dependency

The console spec's section 14 embeds `uns-process-visualization`, `uns-oee` and
`uns-platform-observability`. Those embeds work today because Grafana is anonymous
(finding 8). Removing anonymity means an iframe to `/grafana` must arrive with a Grafana
session.

Approach: because the console and Grafana are served from the same origin through the
console's nginx — `/graphql`, `/simulator` and `/grafana` are all proxy paths on one host —
Grafana's own session cookie is a same-origin cookie. The user authenticates to Grafana
through the realm once, and the browser sends that cookie on the iframe request. With
`GF_SECURITY_ALLOW_EMBEDDING` still true and `GF_SERVER_ROOT_URL` set for the sub-path, the
embed works without the console handling Grafana's tokens.

The first embed load after login may redirect through the realm inside the iframe. The
`GrafanaEmbed` component from the console spec handles this in one place: if the frame does
not signal load within a timeout, it shows a `Sign in to Grafana` action that opens the flow
in a new tab and then reloads the frame. This is stated as a known rough edge rather than
hidden, and it is the reason the console spec ships first.

If the same-origin cookie approach proves unreliable in practice, the fallback is to keep
`GF_AUTH_ANONYMOUS_ENABLED` for the embedded dashboards while Grafana's own UI requires
login, and record that as a narrowed version of ADR-0001's accepted gap rather than a closed
one. Choosing between the two requires trying the first.

## 11. What this does not secure

The UI must state this, because a login screen implies more than it delivers (finding 10).
A line in HEALTH, alongside the console spec's statement of what the browser cannot observe:

> Sign-in protects the console and the GraphQL read surface. The MQTT broker, the graph
> database, the historian and the Kafka broker have no authentication on this deployment.

The remaining gaps, named:

- MQTT on 1883 is unencrypted and unauthenticated. 1884 exists for authenticated MQTT and
  nothing in the platform uses it.
- TimescaleDB, Neo4j and Kafka are published to the host with development credentials.
- The simulator control API has no user identity. `docker-compose.yml:308` already documents
  this as the reason its port is unpublished.
- The mapper and connector modules connect to the broker with no credentials.

Anyone with network access to the broker can still publish anything into the Unified
Namespace. That is the larger problem, and this spec does not solve it.

## 12. ADR

A new ADR, `0009-oidc-authentication-for-console-and-graphql.md`, recording:

- The decision: Keycloak, Authorization Code + PKCE for the static bundle, JWKS validation in
  `07_uns_graphql`, realm roles as the authority for `ConsoleRole`.
- Why PKCE and not a client secret: finding 5.
- Why queries are open to any authenticated role and only mutations are gated: section 7.
- What it supersedes: ADR-0005's "There is no authorization in this service", and ADR-0001's
  acceptance of anonymous Grafana — the latter fully or partially depending on section 10's
  outcome.
- What it explicitly does not supersede: everything in section 11.

ADR-0001 and ADR-0005 gain a note pointing to it, following the repository's existing
convention for superseded decisions.

## 13. Failure modes

| Condition | Behaviour |
| --- | --- |
| Keycloak unreachable at login | The console says the identity provider is unreachable and names the URL. It does not fall through to a local user, which is precisely today's defect |
| Keycloak unreachable mid-session | Cached JWKS keeps validation working until a key rotates. Queries continue; refresh fails at token expiry and the user is redirected |
| Token expired | One silent refresh, then redirect. No silent empty results |
| Valid token, missing role | GraphQL error naming the required role. The UI disables the control rather than offering it and failing |
| Token with an unrecognised realm role | The role is dropped (finding 1's precedent). A user with no recognised role can read and cannot mutate |
| Clock skew between console and realm | Standard leeway on `exp`/`nbf` validation, stated in the ADR |
| Grafana session absent in an embed | Section 10's `Sign in to Grafana` action |

## 14. Testing

Backend, in `07_uns_graphql/test`:

1. A request with no bearer token is rejected on every query and mutation.
2. A token signed by the wrong key is rejected.
3. An expired token is rejected.
4. Each of the six mutations accepts every role in its row of section 7's table and rejects
   every role outside it — one test per cell, because a table like that is exactly where an
   off-by-one in a role list hides.
5. `assignDowntimeReason` stores the token subject as `assignedBy`, and a request that tries
   to supply `assignedBy` fails schema validation because the argument no longer exists.
6. A token whose realm roles include an unknown name is accepted with that role dropped.
7. JWKS is fetched once and cached; an unknown `kid` triggers exactly one refetch.

Frontend, in the Vitest suite the console spec establishes:

8. `login` redirects to the realm and never evaluates a password. A test asserts no code path
   in `AuthContext` reads a password argument.
9. Every GraphQL request carries the `Authorization` header; the WebSocket carries the token
   in `connection_init`.
10. A 401 triggers one refresh then a redirect, and does not render an empty result set.
11. `hasPermission` resolves from token roles, and a user without a mutating role sees the
    control disabled rather than absent — an operator needs to know the action exists and
    that they lack it.
12. Nothing writes an access token to `localStorage`.

## 15. Success criteria

1. No password reaches the console. `AuthContext` contains no password handling.
2. An unauthenticated request to `/graphql` is rejected.
3. Every cell of section 7's role table is covered by a passing test.
4. A downtime reason reassignment records an identity the caller did not choose.
5. `localStorage` holds no users, no roles, no permissions and no audit log.
6. `/users` shows realm membership or says it cannot reach the realm. It never shows a
   browser-local list presented as access control.
7. The three Grafana embeds load for a signed-in user, or the rough edge in section 10 is
   visible and actionable rather than a blank frame.
8. ADR-0009 exists, and ADR-0001 and ADR-0005 point to it.
9. HEALTH states what remains unauthenticated, per section 11.

## 16. Judgement calls open to revision

- **Queries open to any authenticated role.** The alternative is gating reads by Asset, which
  needs an Asset-to-role mapping that does not exist in `model.asset` and would be inventing
  a data model to enforce a policy nobody has stated. If a plant needs per-area read
  restrictions, that is a separate spec starting with the Asset Model.
- **`recordAlertRuleEvaluation` open to any role.** It is a side effect of browser-side
  evaluation, not a user action. If evaluation ever moves server-side per ADR-0005's own
  misgivings, this mutation should become a service-account call and be closed to users
  entirely.
- **Keycloak rather than a lighter provider.** It is a heavy service for a development
  compose stack. It is chosen because it provisions declaratively from a committed export,
  which is what makes the realm reproducible; a lighter provider that needs manual setup
  would reintroduce configuration drift.
- **Same-origin Grafana cookie rather than the console brokering tokens.** Section 10 states
  the fallback. This is the item in this spec most likely to need revising against a running
  stack.
- **`assignedBy` from `preferred_username` rather than the subject UUID.** A UUID in a
  downtime record is unreadable to the next shift lead; a username is not stable across a
  rename. Storing the username matches what the field was always trying to be. Storing both
  is the obvious escalation if it matters.
