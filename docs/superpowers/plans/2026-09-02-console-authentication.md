# Console authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the console's login real — Keycloak as the identity provider, OIDC Authorization Code + PKCE in the static bundle, JWT validation and role-gated mutations in `07_uns_graphql`, `assignedBy` taken from the token, and Grafana on the same realm.

**Architecture:** One Keycloak service in `docker-compose.yml`, provisioned from a committed realm export in `conf/keycloak/realm.json`, holding the five roles that `ConsoleRole` (`07_uns_graphql/src/uns_graphql/type/alert_rule.py:70`) and `UserRole` (`11_frontend/src/types/rbac.ts:5`) already declare. The GraphQL service validates bearer tokens against the realm's JWKS at the single point where its one router is mounted (`uns_graphql_app.py:122`–`:139`), puts the claims into the Strawberry context, leaves every query readable by any authenticated role, and gates all six mutations. The console replaces `AuthContext`'s fake login with a redirect to the realm, keeps tokens in memory only, and sends the access token on the one `fetch` in `services/graphql/client.ts:160` and in the one `connection_init` at `:118`. Grafana moves to OIDC and keeps working inside the console's iframes because it is proxied on the console's own origin.

**Tech Stack:** Keycloak (compose service, realm imported from `conf/`), FastAPI + Strawberry (`07_uns_graphql`), PyJWT with the JWKS client, SQLAlchemy (`09_uns_model`), React 19 + TypeScript + Vite 6 (`11_frontend`), `oidc-client-ts`, Vitest + Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-console-authentication-design.md`

**Depends on:** `docs/superpowers/plans/2026-09-02-console-foundation.md` and `docs/superpowers/plans/2026-09-02-console-surfaces.md`, in that order. Spec section 2 is explicit that the console spec ships first — *"an honest console with no authentication is a better state than a dishonest console, and a dishonest console with authentication bolted on is the worst of the three."* Three concrete couplings, not just a preference:

- The Vitest harness this plan's frontend tests run in is created by foundation-plan Task 1. There is no `vitest` in `11_frontend/package.json` today.
- Surfaces-plan Task 21 deletes `createUser`, `updateUser`, `deleteUser`, `toggleUserFeaturePermission`, `resetUserToRoleDefaults`, `auditLogs` and `restoreDefaults` from `AuthContext`, and deletes `CreateUserModal.tsx` and `EditUserModal.tsx`. This plan's Task 8 rewrites what is left. Running it first means rewriting code that is about to be deleted.
- Surfaces-plan Task 6 rewrites `GrafanaEmbed` (the component already exists; that task gives it its final shape), which is the one place Task 11 adds the `Sign in to Grafana` fallback. Without it the fallback would have to be written three times.

---

## Pre-flight: check the dependencies before Task 1

Verified on 2026-09-03, and worth re-verifying on the day work starts — the two dependency
plans existed but **neither had landed**: every checkbox in both was unticked,
`11_frontend/package.json` had no `vitest`, and `CreateUserModal.tsx`, `EditUserModal.tsx` and
the seven `AuthContext` write/audit APIs were all still present.

```bash
cd /c/Dev/manufacturing-uns
grep -c -- "- \[x\]" docs/superpowers/plans/2026-09-02-console-foundation.md \
  docs/superpowers/plans/2026-09-02-console-surfaces.md
grep -n "vitest" 11_frontend/package.json
ls 11_frontend/src/components/users/
```

The decision rule:

- **Foundation not landed (no `vitest` in `package.json`):** every frontend test step in this
  plan (`npx vitest run …` in Tasks 2, 7, 8, 9, 10, 11) fails at the command line, not at an
  assertion. Land the foundation plan first — or at minimum its Task 1, the Vitest harness —
  before touching `11_frontend`. Do not let `npx` fetch Vitest ad hoc: the harness is jsdom,
  Testing Library and the `vitest.config.ts` these tests are written against, not just the
  runner.
- **Surfaces not landed:** this plan already carries its own fallbacks, and they are the ones
  to use. Tasks 8 and 10 delete the user modals and the `AuthContext` write APIs if Task 21 has
  not; Task 8's `TAB_FEATURES` takes its labels from the current navigation, not the renamed
  one; Task 10 renders its empty states without the surfaces plan's `EmptyState` component;
  Task 11 mounts `AuthenticationPanel` on the existing `SystemHealthView`.
- **What is executable without either dependency:** Tasks 1, 3, 4, 5 and 6 are Python and
  compose work, plus the Python half of Task 2 (Steps 1–5). When the dependencies are still
  open, a sensible order is Tasks 1–6 with Task 2's frontend steps (6–9) deferred, then the
  frontend tasks once the harness exists. Task 6's schema change is deliberately free for the
  console — see its preamble — so landing the backend half first strands nothing.

---

## Global Constraints

Copied from the spec, and from the constraints in force on the console work. Every task's requirements implicitly include this section.

- **The browser talks to GraphQL (`POST /graphql`, WS `/graphql`) and to the realm's OIDC endpoints.** Nothing else. It never connects to MQTT, Neo4j, TimescaleDB, Kafka, or Keycloak's admin API directly except through the paths this plan adds.
- **The console holds no client secret.** It is a static bundle (spec finding 5), so Authorization Code with PKCE is the only correct flow. Implicit flow is not an option and must not appear anywhere in the realm export.
- **No access token in `localStorage`, `sessionStorage`, or any cookie the console sets.** Tokens live in memory. Persisting identity in `localStorage` is part of what made the current design fake (spec section 6).
- **The console never sees a password.** The `LoginView` password field is deleted, not wired up (spec section 6). Success criterion 1: *"`AuthContext` contains no password handling."*
- **Queries stay readable by any authenticated role. Only mutations are role-gated.** Six mutations, exactly the table in spec section 7. No query is gated (spec section 7, section 16).
- **`recordAlertRuleEvaluation` is open to any authenticated role,** because the browser-side evaluator calls it as a consequence of a rule firing (ADR-0005), not as a user action.
- **Do not widen the mutation surface.** ADR-0005: *"The mutation surface is deliberately narrow, and stays narrow."* This plan changes who may call the six, and removes one argument. It adds no mutation and changes what none of them do (spec section 4, out of scope).
- **Role names are the five that already exist, lowercase:** `admin`, `engineer`, `operator`, `auditor`, `viewer`. The existing `toUserRole` / `toConsoleRole` conversion in `11_frontend/src/lib/alarms/map-alert-rules.ts:53`–`:60` keeps working unchanged. An unrecognised realm role is **dropped, not guessed** — the precedent at `map-alert-rules.ts:50`–`:56`.
- **The realm is authored and committed, not clicked.** `conf/keycloak/realm.json` is a reviewable file, consistent with `conf/oee/*.yaml` and `conf/simulator/*.yaml`, and a fresh `docker compose up` must produce the same realm every time (spec section 5).
- **Secrets live in `conf/.secrets.yaml`**, reaching compose through `uns_config.compose_env`. Do not add a root `.env`; `docker-compose.yml:20`–`:26` says so.
- **English only. No i18n. No second frontend. The UI is not served from FastAPI.**
- **Keep the existing suites green.** `uv run pytest` in `00_uns_config`, `07_uns_graphql` and `09_uns_model`; `npx vitest run` and `npx tsc --noEmit` in `11_frontend`. No live broker, no live Keycloak, and no network in any test — tokens are signed with keys the test generates.
- **This does not secure the platform, and the UI says so.** Spec section 11's sentence appears in HEALTH verbatim:
  > Sign-in protects the console and the GraphQL read surface. The MQTT broker, the graph database, the historian and the Kafka broker have no authentication on this deployment.

---

## File Structure

```
conf/
  keycloak/
    realm.json                             CREATE  the whole realm: clients, roles, dev users
    README.md                              CREATE  what this is, and that it is not for production
  settings.yaml                            MODIFY  an `auth:` block: issuer, audience, jwks path, leeway
  .secrets_template.yaml                   MODIFY  keycloak.admin_password, keycloak.grafana_client_secret
docker-compose.yml                         MODIFY  uns_keycloak service; graphql_server and
                                                   uns_grafana gain auth env; anonymous Grafana out
00_uns_config/
  src/uns_config/platform.py               MODIFY  AuthConfig: the realm URLs one place reads them from
  src/uns_config/compose_env.py            MODIFY  two more interpolations from .secrets.yaml
  test/test_keycloak_realm.py              CREATE  the export is what the plan says it is
  test/test_compose_env.py                 MODIFY  the two new keys
07_uns_graphql/
  src/uns_graphql/auth/__init__.py          CREATE
  src/uns_graphql/auth/jwks.py              CREATE  fetch + cache, one refetch on unknown kid
  src/uns_graphql/auth/token.py             CREATE  decode/validate, claims -> Identity, roles dropped
  src/uns_graphql/auth/context.py           CREATE  the Strawberry context getter, HTTP and WS
  src/uns_graphql/auth/require.py           CREATE  require_roles: the one authorization decision
  src/uns_graphql/graphql_config.py         MODIFY  re-export AuthConfig beside PlatformConfig
  src/uns_graphql/uns_graphql_app.py        MODIFY  context_getter on the one router
  src/uns_graphql/mutations/alert_rule.py   MODIFY  five mutations gated
  src/uns_graphql/mutations/oee.py          MODIFY  gated; assigned_by argument deleted
  test/auth/__init__.py                     CREATE
  test/auth/keys.py                         CREATE  test-only RSA keypair + token minting
  test/auth/test_jwks.py                    CREATE  caching and the single refetch
  test/auth/test_token.py                   CREATE  signature, expiry, issuer, audience, roles
  test/auth/test_context.py                 CREATE  the context dependency, unit-tested without a server
  test/auth/test_graphql_gate.py            CREATE  every operation rejected with no token
  test/auth/test_require.py                 CREATE  one test per cell of the role table
  test/mutations/test_oee.py                MODIFY  assigned_by comes from the token now
09_uns_model/
  src/uns_model/oee_results.py              MODIFY  assign_reason requires an identity
  test/test_oee_results.py                  MODIFY  the required keyword
11_frontend/
  package.json                              MODIFY  oidc-client-ts
  src/lib/auth/oidc.ts                      CREATE  the client: PKCE, memory tokens, silent renew
  src/lib/auth/roles.ts                     CREATE  realm roles -> UserRole, unknown dropped
  src/lib/auth/oidc.test.ts                 CREATE
  src/lib/auth/roles.test.ts                CREATE
  src/context/AuthContext.tsx                MODIFY  same public shape, real identity behind it
  src/context/AuthContext.test.tsx           CREATE  no password, no localStorage, roles from token
  src/components/auth/LoginView.tsx          MODIFY  password field deleted, one Sign in button
  src/components/auth/LoginView.test.tsx     CREATE
  src/services/graphql/client.ts             MODIFY  Authorization header, connection_init payload, 401
  src/services/graphql/client-auth.test.ts   CREATE
  src/lib/auth/directory.ts                  CREATE  the realm's membership, read same-origin via /auth
  src/components/users/UserManagementView.tsx MODIFY realm membership, or it says it cannot reach it
  src/components/users/UserManagementView.test.tsx CREATE the list is realm data now
  src/components/common/GrafanaEmbed.tsx     MODIFY  the Sign in to Grafana fallback
  src/components/system/AuthenticationPanel.tsx CREATE what sign-in protects, and what it does not
  nginx.conf                                 MODIFY  /auth proxy to Keycloak, /grafana unchanged
  platform/settings.ts                       MODIFY  the realm's identity into PlatformSettings
  src/lib/platform/config.ts                 MODIFY  the same four keys, browser side
docs/adr/
  0009-oidc-authentication-for-console-and-graphql.md CREATE
  0001-grafana-for-visualization-and-observability.md MODIFY a note pointing to 0009
  0005-graphql-mutations-for-console-configuration.md MODIFY a note pointing to 0009
```

Five decisions this structure locks in.

**`auth/` is four small files, not one.** `jwks.py` does network I/O and caching; `token.py` is pure given a key; `context.py` is FastAPI and Strawberry plumbing; `require.py` is the authorization decision. Only `jwks.py` needs a network stub, so keeping it separate is what makes the other three testable without one. The role table in spec section 7 is data in `require.py`, not `if` statements spread across six resolvers — a table tested cell by cell has to exist as a table.

**The realm URLs live in `00_uns_config`, not in `07_uns_graphql`.** Three consumers need them: the GraphQL service (issuer, JWKS), the console (authority, client id — through `vite.config.ts`'s `define`, which already reads platform settings), and Grafana (through compose env). `PlatformConfig` is already the shared home for `cors_origins` and the frontend ports, so `AuthConfig` sits beside it and there is one authority for the realm's identity.

**`conf/keycloak/README.md` exists because the export contains development passwords.** `docker-compose.yml:19` already says `DO NOT USE FOR PRODUCTION DEPLOYMENT`; a file full of credentials deserves the same sentence next to it rather than three directories away.

**The console reaches Keycloak through `/auth` on its own origin,** proxied by the same nginx that already proxies `/graphql`, `/simulator` and `/grafana`. This is not cosmetic: it is what makes Grafana's session cookie same-origin (spec section 10) and it means the console's redirect URIs never change between the dev port and the compose port.

**`AuthenticationPanel` is a new HEALTH panel, not a line appended to an existing one.** What sign-in does and does not protect is a claim of its own, and the spec asks for it as its own statement (section 11). It lives in `components/system/` and Task 11 mounts it on the `SystemHealthView` that exists today; when the surfaces plan's Task 19 builds its four-panel `HealthView` (with `NotObservablePanel` — "what a browser cannot reach"), the panel moves there unchanged.

---

## Task 1: Keycloak, provisioned from a file somebody can read

The realm is the root of everything else in this plan, and it is the one piece that cannot be
partly right. If the console client allows a secret, PKCE is optional and the flow is not what
the spec chose. If the role names drift from `ConsoleRole`, `toUserRole` starts dropping every
role. So this task's test reads the committed export and asserts the four things the rest of the
plan depends on.

**Files:**
- Create: `conf/keycloak/realm.json`, `conf/keycloak/README.md`
- Modify: `conf/settings.yaml`, `conf/.secrets_template.yaml`, `docker-compose.yml`,
  `00_uns_config/src/uns_config/compose_env.py`, `00_uns_config/test/test_compose_env.py`
- Test: `00_uns_config/test/test_keycloak_realm.py` (create)

**Interfaces:**
- Consumes: `uns_config.loader.get_settings`, and the `COMPOSE_ENV_KEYS` tuple at
  `compose_env.py:18`.
- Produces: the realm at `http://localhost:8088/auth/realms/uns`, client id `uns-console`
  (public, PKCE `S256`), client id `uns-grafana` (confidential), realm roles `admin`,
  `engineer`, `operator`, `auditor`, `viewer`, and five development users
  `admin.user`, `engineer.user`, `operator.user`, `auditor.user`, `viewer.user`. Two new
  compose interpolations: `UNS_keycloak__admin_password` and
  `UNS_keycloak__grafana_client_secret`. Task 2 turns the URLs into `AuthConfig`; Tasks 3–11
  consume that.

- [ ] **Step 1: Confirm what the secrets helper does today**

```bash
cd 00_uns_config
uv run pytest test/test_compose_env.py -q
grep -n "COMPOSE_ENV_KEYS" -A 3 src/uns_config/compose_env.py
grep -n "keycloak" ../conf/settings.yaml ../conf/.secrets_template.yaml
```

Expected: the suite passes, `COMPOSE_ENV_KEYS` is the three-tuple
`("UNS_graphdb__password", "UNS_historian__password", "PGPASSWORD")`, and no `keycloak` key
exists anywhere. If `.secrets.yaml.template` is not the filename in this tree, use whatever
`ls ../conf/` shows and keep the real `conf/.secrets.yaml` untouched — it holds someone's actual
passwords and is not this plan's business.

- [ ] **Step 2: Write the failing realm test**

Create `00_uns_config/test/test_keycloak_realm.py`:

```python
"""The realm is a committed file, so its contract is testable without Keycloak running."""

import json
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REALM_FILE = _REPO_ROOT / "conf" / "keycloak" / "realm.json"
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"

# The five names in ConsoleRole (07_uns_graphql/src/uns_graphql/type/alert_rule.py:70) and in
# UserRole (11_frontend/src/types/rbac.ts:5). A drift here silently drops roles in the console.
EXPECTED_ROLES = {"admin", "engineer", "operator", "auditor", "viewer"}


@pytest.fixture(scope="module")
def realm() -> dict:
    return json.loads(_REALM_FILE.read_text(encoding="utf-8"))


def _client(realm: dict, client_id: str) -> dict:
    for client in realm["clients"]:
        if client["clientId"] == client_id:
            return client
    raise AssertionError(f"realm.json has no client {client_id!r}")


def test_realm_declares_exactly_the_five_console_roles(realm: dict):
    names = {role["name"] for role in realm["roles"]["realm"]}
    assert names == EXPECTED_ROLES


def test_console_client_is_public_and_requires_pkce(realm: dict):
    console = _client(realm, "uns-console")
    assert console["publicClient"] is True
    assert "secret" not in console
    # A static bundle cannot keep a secret, so PKCE is the whole security of the flow.
    assert console["attributes"]["pkce.code.challenge.method"] == "S256"
    assert console["standardFlowEnabled"] is True
    # Implicit puts the token in the URL fragment. Not an option (spec finding 5).
    assert console["implicitFlowEnabled"] is False
    assert console["directAccessGrantsEnabled"] is False


def test_console_client_accepts_both_console_origins(realm: dict):
    console = _client(realm, "uns-console")
    redirects = set(console["redirectUris"])
    assert "http://localhost:8088/*" in redirects
    assert "http://localhost:5173/*" in redirects


def test_grafana_client_is_confidential_and_takes_its_secret_from_the_environment(realm: dict):
    grafana = _client(realm, "uns-grafana")
    assert grafana["publicClient"] is False
    assert grafana["secret"] == "${UNS_KEYCLOAK_GRAFANA_CLIENT_SECRET}"


def test_every_development_user_holds_exactly_one_of_the_five_roles(realm: dict):
    granted = {}
    for user in realm["users"]:
        roles = set(user["realmRoles"])
        assert len(roles) == 1, f"{user['username']} holds {roles}"
        granted[user["username"]] = roles.pop()
    assert set(granted.values()) == EXPECTED_ROLES


def test_settings_yaml_points_at_this_realm():
    settings = yaml.safe_load((_REPO_ROOT / "conf" / "settings.yaml").read_text(encoding="utf-8"))
    auth = settings["default"]["auth"]
    assert auth["realm"] == "uns"
    assert auth["console_client_id"] == "uns-console"
    assert auth["issuer"].endswith("/auth/realms/uns")


def test_compose_imports_the_realm_and_does_not_publish_a_second_port():
    compose = yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))
    keycloak = compose["services"]["uns_keycloak"]
    assert "--import-realm" in keycloak["command"]
    mounted = [v for v in keycloak["volumes"] if v.startswith("./conf/keycloak")]
    assert mounted, "the realm export has to be mounted for --import-realm to see it"
    # The console proxies /auth on its own origin, which is what makes Grafana's cookie
    # same-origin (spec section 10). A published 8080 would invite a second issuer URL.
    assert "ports" not in keycloak


def test_grafana_is_no_longer_anonymous():
    compose = yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))
    env = compose["services"]["uns_grafana"]["environment"]
    # Explicit "false", not merely absent: the file states the decision, and an absent key
    # would leave Grafana's own default in charge.
    assert env.get("GF_AUTH_ANONYMOUS_ENABLED") == "false"
    assert "GF_AUTH_ANONYMOUS_ORG_ROLE" not in env
    assert env["GF_AUTH_GENERIC_OAUTH_ENABLED"] == "true"
    # Removing anonymity without keeping embedding on breaks all three console embeds.
    assert env["GF_SECURITY_ALLOW_EMBEDDING"] == "true"
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd 00_uns_config && uv run pytest test/test_keycloak_realm.py -q`

Expected: every test errors — `conf/keycloak/realm.json` does not exist, so the module-scoped
fixture raises `FileNotFoundError` and the three non-fixture tests fail on the missing `auth`
key and the missing service.

- [ ] **Step 4: Write the realm export**

Create `conf/keycloak/realm.json`:

```json
{
  "realm": "uns",
  "enabled": true,
  "displayName": "Unified Namespace",
  "sslRequired": "none",
  "registrationAllowed": false,
  "loginWithEmailAllowed": true,
  "accessTokenLifespan": 900,
  "ssoSessionIdleTimeout": 3600,
  "roles": {
    "realm": [
      { "name": "admin", "description": "Configure the platform and administer users" },
      { "name": "engineer", "description": "Author Alert Rules and correct downtime reasons" },
      { "name": "operator", "description": "Run the plant view, silence and acknowledge alarms" },
      { "name": "auditor", "description": "Read everything, change nothing" },
      { "name": "viewer", "description": "Read the plant view" }
    ]
  },
  "clients": [
    {
      "clientId": "uns-console",
      "name": "UNS operations console",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": true,
      "standardFlowEnabled": true,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
      "fullScopeAllowed": true,
      "redirectUris": [
        "http://localhost:8088/*",
        "http://127.0.0.1:8088/*",
        "http://localhost:5173/*",
        "http://127.0.0.1:5173/*"
      ],
      "webOrigins": [
        "http://localhost:8088",
        "http://127.0.0.1:8088",
        "http://localhost:5173",
        "http://127.0.0.1:5173"
      ],
      "attributes": {
        "pkce.code.challenge.method": "S256",
        "post.logout.redirect.uris": "http://localhost:8088/*##http://localhost:5173/*"
      },
      "protocolMappers": [
        {
          "name": "audience-uns-console",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-audience-mapper",
          "consentRequired": false,
          "config": {
            "included.client.audience": "uns-console",
            "access.token.claim": "true",
            "id.token.claim": "false"
          }
        }
      ]
    },
    {
      "clientId": "uns-grafana",
      "name": "Grafana",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "standardFlowEnabled": true,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "secret": "${UNS_KEYCLOAK_GRAFANA_CLIENT_SECRET}",
      "redirectUris": ["http://localhost:8088/grafana/login/generic_oauth"],
      "webOrigins": ["http://localhost:8088"],
      "protocolMappers": [
        {
          "name": "realm-roles-as-a-claim",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-usermodel-realm-role-mapper",
          "consentRequired": false,
          "config": {
            "claim.name": "roles",
            "jsonType.label": "String",
            "multivalued": "true",
            "access.token.claim": "true",
            "id.token.claim": "true",
            "userinfo.token.claim": "true"
          }
        }
      ]
    }
  ],
  "users": [
    {
      "username": "admin.user",
      "enabled": true,
      "emailVerified": true,
      "email": "admin.user@example.test",
      "firstName": "Ada",
      "lastName": "Admin",
      "credentials": [{ "type": "password", "value": "development-only", "temporary": false }],
      "realmRoles": ["admin"]
    },
    {
      "username": "engineer.user",
      "enabled": true,
      "emailVerified": true,
      "email": "engineer.user@example.test",
      "firstName": "Erin",
      "lastName": "Engineer",
      "credentials": [{ "type": "password", "value": "development-only", "temporary": false }],
      "realmRoles": ["engineer"]
    },
    {
      "username": "operator.user",
      "enabled": true,
      "emailVerified": true,
      "email": "operator.user@example.test",
      "firstName": "Omar",
      "lastName": "Operator",
      "credentials": [{ "type": "password", "value": "development-only", "temporary": false }],
      "realmRoles": ["operator"]
    },
    {
      "username": "auditor.user",
      "enabled": true,
      "emailVerified": true,
      "email": "auditor.user@example.test",
      "firstName": "Ana",
      "lastName": "Auditor",
      "credentials": [{ "type": "password", "value": "development-only", "temporary": false }],
      "realmRoles": ["auditor"]
    },
    {
      "username": "viewer.user",
      "enabled": true,
      "emailVerified": true,
      "email": "viewer.user@example.test",
      "firstName": "Vik",
      "lastName": "Viewer",
      "credentials": [{ "type": "password", "value": "development-only", "temporary": false }],
      "realmRoles": ["viewer"]
    }
  ]
}
```

Two details that are load-bearing and easy to lose. The `oidc-audience-mapper` on `uns-console`
is why Task 3 can check `aud` at all: without it Keycloak issues an access token whose audience
is `account`, and an audience check against `uns-console` would reject every real token. And
`##` in `post.logout.redirect.uris` is Keycloak's list separator for that attribute, not a typo.

The example emails use `example.test`, which RFC 6761 reserves. No real person's address goes in
a committed credential file.

- [ ] **Step 5: Say what the directory is**

Create `conf/keycloak/README.md`:

```markdown
# Keycloak realm

`realm.json` is the whole `uns` realm: two clients, the five console roles, and one
development user per role. Keycloak imports it on start (`--import-realm`), so a fresh
`docker compose up` produces the same realm every time and nobody has to click through the
admin console.

## DO NOT USE FOR PRODUCTION DEPLOYMENT

Every user in this file has the password `development-only`. The Grafana client's secret is
interpolated from `conf/.secrets.yaml`, but the user passwords are not — they are here in
plain text, on purpose, so that a checkout is runnable. A real deployment replaces this file
with a realm whose users come from the site's directory.

## Changing it

Edit this file, not the running realm. A change made in the admin console lives in Keycloak's
database and is gone the next time the volume is recreated, which is the configuration drift
this file exists to prevent. After editing:

    uv run uns_compose up -d --force-recreate uns_keycloak
    cd 00_uns_config && uv run pytest test/test_keycloak_realm.py -q

The roles are not free-form. They are the five values of `ConsoleRole`
(`07_uns_graphql/src/uns_graphql/type/alert_rule.py:70`) and of `UserRole`
(`11_frontend/src/types/rbac.ts:5`). A role added here and nowhere else is dropped by the
console, following `11_frontend/src/lib/alarms/map-alert-rules.ts:50`–`:56`.
```

- [ ] **Step 6: Put the realm's identity in `conf/settings.yaml`**

Add an `auth:` block to the `default:` section, after the `urls:` block:

```yaml
  auth:
    # The realm is reached through the console's own nginx (/auth), so the issuer is the
    # console's origin and not a second host. That is also what makes Grafana's session
    # cookie same-origin for the three embedded dashboards.
    realm: "uns"
    base_url: "http://localhost:8088/auth"
    issuer: "http://localhost:8088/auth/realms/uns"
    console_client_id: "uns-console"
    grafana_client_id: "uns-grafana"
    # The access token's `aud`, set by the audience mapper in conf/keycloak/realm.json.
    audience: "uns-console"
    # Seconds of tolerance on exp/nbf. A laptop clock is not the realm's clock.
    leeway_seconds: 30
    # Inside the compose network the GraphQL service resolves Keycloak by service name, so
    # its JWKS fetch does not depend on the frontend container being up.
    internal_base_url: "http://uns_keycloak:8080"
```

- [ ] **Step 7: Add the two secrets to the template**

In `conf/.secrets_template.yaml` (that is the real filename in this tree, not
`.secrets.yaml.template` — Step 1's fallback applied), under `default:`, following the
placeholder style already there:

```yaml
  keycloak:
    # Keycloak's own bootstrap admin, for the admin console at /auth/admin/.
    admin_password: "#<Enter the Keycloak admin password>"
    # Must match the uns-grafana client secret Keycloak imports from conf/keycloak/realm.json.
    grafana_client_secret: "#<Enter the Grafana OIDC client secret>"
```

Then extend `00_uns_config/src/uns_config/compose_env.py`. `COMPOSE_ENV_KEYS` at `:18`:

```python
COMPOSE_ENV_KEYS = (
    "UNS_graphdb__password",
    "UNS_historian__password",
    "PGPASSWORD",
    "UNS_keycloak__admin_password",
    "UNS_keycloak__grafana_client_secret",
)
```

In `compose_environment`, read and require both alongside the existing three:

```python
    keycloak_admin_password = _secret(settings, "keycloak.admin_password")
    keycloak_grafana_secret = _secret(settings, "keycloak.grafana_client_secret")
```

```python
    if keycloak_admin_password is None:
        missing.append("keycloak.admin_password")
    if keycloak_grafana_secret is None:
        missing.append("keycloak.grafana_client_secret")
```

and in the returned dict:

```python
        "UNS_keycloak__admin_password": keycloak_admin_password,
        "UNS_keycloak__grafana_client_secret": keycloak_grafana_secret,
```

Widen the `ValueError` message's second sentence so it still explains every name it lists:

```python
        raise ValueError(
            "conf/.secrets.yaml is missing " + ", ".join(missing) + ". "
            "postgres.password is the Timescale/Postgres superuser used only to "
            "initialise the volume; historian.password is uns_dbuser, which every "
            "Python service uses for tables; keycloak.grafana_client_secret must match "
            "the uns-grafana client in conf/keycloak/realm.json."
        )
```

- [ ] **Step 8: Update the compose-env test**

`00_uns_config/test/test_compose_env.py` builds its secrets dict by hand, so every case that
calls `_write_conf` needs the new keys or `compose_environment` now raises. Add to each secrets
literal:

```python
            "keycloak": {
                "admin_password": "kc-admin-secret",
                "grafana_client_secret": "kc-grafana-secret",
            },
```

and where the test asserts the returned mapping, assert the two new entries too. Read the file
before editing: if it has a test that asserts `compose_environment` raises for a *missing* key,
that test's dict must stay incomplete in exactly one key, so add the new keys there as present.

- [ ] **Step 9: Add the Keycloak service**

In `docker-compose.yml`, add `uns_keycloak` immediately before `uns_frontend` — it is a
dependency of the frontend's nginx, and compose files read better when a service appears above
the thing that proxies it:

```yaml
  uns_keycloak:
    image: "quay.io/keycloak/keycloak:26.0"
    # 8080 stays unpublished. The console proxies /auth (nginx on 8088, Vite in development),
    # so the realm has exactly one issuer URL. A second published port would mean tokens
    # minted with an issuer the GraphQL service is not expecting.
    command: ["start-dev", "--import-realm", "--http-relative-path=/auth"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${UNS_keycloak__admin_password}
      # Tokens must carry the issuer the browser used, not the container hostname, or the
      # console's OIDC library rejects its own token.
      KC_HOSTNAME: http://localhost:8088/auth
      KC_HOSTNAME_STRICT: "false"
      KC_HTTP_ENABLED: "true"
      # Without this the management interface (9000, where /health/ready lives) never
      # starts and the healthcheck below refuses every connection.
      KC_HEALTH_ENABLED: "true"
      KC_PROXY_HEADERS: xforwarded
      UNS_KEYCLOAK_GRAFANA_CLIENT_SECRET: ${UNS_keycloak__grafana_client_secret}
    volumes:
      - ./conf/keycloak:/opt/keycloak/data/import:ro
    healthcheck:
      # 26.x serves health on the management port, which start-dev exposes on 9000, and
      # --http-relative-path applies there too — hence /auth/health/ready, not /health/ready.
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/9000 && echo -e 'GET /auth/health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3 && cat <&3 | grep -q '\"status\": \"UP\"'"]
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 40s
```

`start-dev` is deliberate and matches the rest of this file: it uses the embedded H2 database,
which is exactly right for a stack whose header says `DO NOT USE FOR PRODUCTION DEPLOYMENT`, and
wrong for anything else. The ADR in Task 12 records that.

One expectation to set before it surprises anybody at Step 13: Keycloak 26's hostname v2
deprecates `KC_HOSTNAME_STRICT`, so the container logs a deprecation warning at boot. That is
expected — the setting still takes effect in 26.x, and Step 13's discovery document, not a quiet
log, is the arbiter of whether the realm advertises the right URLs.

Add it to `uns_frontend`'s `depends_on` (`docker-compose.yml:370`–`:377`), with the same shape
of comment its three siblings have:

```yaml
    depends_on:
      - graphql_server
      # nginx.conf proxies /simulator to it, and nginx will not start on an unresolvable
      # upstream hostname.
      - uns_simulator
      # nginx.conf proxies /grafana to it. Without this, System Operations shows the SPA
      # fallback instead of the dashboards.
      - uns_grafana
      # nginx.conf proxies /auth to it. Without this, every sign-in redirect lands on the
      # SPA fallback: a 200 full of HTML where the browser expected the realm.
      - uns_keycloak
```

- [ ] **Step 10: Point Grafana at the realm**

Replace the anonymous settings in `uns_grafana`'s `environment` (`docker-compose.yml:396`–`:398`).
This is the **whole** Grafana compose change — Task 11 only verifies it, because an environment
specified in two tasks is how earlier drafts of this plan ended up with two values for
`GF_AUTH_GENERIC_OAUTH_NAME`:

```yaml
      # ADR-0001 accepted anonymous access with org role Admin as a known gap and named OIDC
      # as the target. This is that target: anonymous is explicitly off — not merely absent,
      # so the file states the decision rather than relying on Grafana's default.
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_AUTH_DISABLE_LOGIN_FORM: "true"
      # The console embeds Grafana in an iframe and the operator has already signed in to the
      # same realm on the same origin, so a second visible sign-in step would be noise.
      GF_AUTH_OAUTH_AUTO_LOGIN: "true"
      GF_AUTH_GENERIC_OAUTH_ENABLED: "true"
      GF_AUTH_GENERIC_OAUTH_NAME: Keycloak
      GF_AUTH_GENERIC_OAUTH_CLIENT_ID: uns-grafana
      GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET: ${UNS_keycloak__grafana_client_secret}
      GF_AUTH_GENERIC_OAUTH_SCOPES: "openid profile email roles"
      # The browser is redirected to the auth URL, so it is the published origin. The token
      # and userinfo calls are Grafana's own, server to server, so they use the container name.
      GF_AUTH_GENERIC_OAUTH_AUTH_URL: "http://localhost:8088/auth/realms/uns/protocol/openid-connect/auth"
      GF_AUTH_GENERIC_OAUTH_TOKEN_URL: "http://uns_keycloak:8080/auth/realms/uns/protocol/openid-connect/token"
      GF_AUTH_GENERIC_OAUTH_API_URL: "http://uns_keycloak:8080/auth/realms/uns/protocol/openid-connect/userinfo"
      # admin -> Admin, engineer -> Editor, everything else Viewer (spec section 9). The
      # realm's uns-grafana client publishes a flat multivalued `roles` claim, which is what
      # this path reads. An operator gets Viewer: a plant dashboard is not something a shift
      # operator should be able to rewrite mid-shift.
      GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH: "contains(roles[*], 'admin') && 'Admin' || contains(roles[*], 'engineer') && 'Editor' || 'Viewer'"
      GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT: "false"
      # Removing anonymity without keeping embedding on breaks all three console embeds.
      GF_SECURITY_ALLOW_EMBEDDING: "true"
```

`GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT: "false"` deserves its comment. With it `true`, a
realm user who holds none of the five is refused a Grafana session entirely; with it `false` the
JMESPath's final `|| 'Viewer'` gives them a read-only one. `false` is the right choice *here*
because the console already gates the HEALTH screen on `system_ops`, so nobody reaches the
iframe without a role that the console recognises. If that gate is ever removed, this flips.

Add Keycloak to `uns_grafana`'s `depends_on`:

```yaml
      uns_keycloak:
        condition: service_healthy
```

`GF_AUTH_ANONYMOUS_ORG_ROLE` is deleted here, and anonymous is set to `"false"` in writing
rather than left to a default. Task 11 handles what the switch does to the three embeds; the
fallback if it proves unworkable is spec section 10's, and Task 12's ADR records which of the
two outcomes actually happened.

- [ ] **Step 11: Proxy `/auth`**

In `11_frontend/nginx.conf`, add a block before `location /`, matching the style of the
`/grafana/` block that is already there:

```nginx
    # Keycloak. Must come before `location /`, whose try_files would otherwise answer the
    # sign-in redirect with index.html — a 200 full of HTML where a redirect was expected.
    location /auth/ {
        proxy_pass http://uns_keycloak:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port 8088;
    }
```

`X-Forwarded-Host` and `X-Forwarded-Port` are what `KC_PROXY_HEADERS: xforwarded` reads to build
the URLs it puts in its own discovery document. Without them Keycloak advertises
`http://uns_keycloak:8080/...`, which no browser can reach.

There is no `location = /auth` redirect, unlike `/grafana`: nothing links to a bare `/auth`, and
`/auth/realms/...` is always a full path.

**Do not add an `/auth` proxy to `vite.config.ts`.** This is the one place where the realm
differs from `/graphql`, `/simulator` and `/grafana`, and it is worth being deliberate about.
Those three are proxied in development because the console addresses them by relative path.
The realm is different: OIDC discovery hands the browser absolute URLs, and Keycloak mints them
from `KC_HOSTNAME`, which Step 9 pins to `http://localhost:8088/auth`. A dev session on 5173
therefore uses the absolute authority `http://localhost:8088/auth/realms/uns`, is redirected
back to `http://localhost:5173/...` (a redirect URI the realm lists), and POSTs to the token
endpoint cross-origin — which Keycloak permits because `webOrigins` in the realm export
includes `http://localhost:5173`.

A Vite proxy would need a reachable target, and Keycloak's 8080 is deliberately unpublished, so
the proxy would have to point at `localhost:8088/auth` — through the very nginx it was meant to
avoid. The honest consequence, stated rather than papered over: **`npm run dev` needs the
`uns_frontend` container up to sign in.** That is already true of the Grafana embeds, whose
`urls.grafana_proxy_target` default of `http://localhost:3000` addresses a port this compose
file does not publish either. Note that Step 12 only runs the Python suite — nothing in this
task type-checks the console.

- [ ] **Step 12: Run the tests**

```bash
cd 00_uns_config
uv run pytest -q
```

Expected: green, including all eight cases in `test_keycloak_realm.py`. If
`test_compose_imports_the_realm_and_does_not_publish_a_second_port` fails on `command`, check
that the compose value is a YAML list and not a string — `"start-dev --import-realm"` as one
string makes `"--import-realm" in keycloak["command"]` a substring test that passes for the
wrong reason, and the list form is what the test is written against.

- [ ] **Step 13: Bring it up once, by hand**

```bash
cd /c/Dev/manufacturing-uns
uv run uns_compose up -d --build uns_keycloak uns_frontend
curl -s http://localhost:8088/auth/realms/uns/.well-known/openid-configuration | head -c 400
```

Expected: JSON whose `issuer` is exactly `http://localhost:8088/auth/realms/uns` and whose
`jwks_uri`, `authorization_endpoint` and `token_endpoint` all start with
`http://localhost:8088/auth/`. Any `uns_keycloak:8080` in that output means the forwarded
headers in Step 11 are not reaching Keycloak, and every subsequent task will fail in a way that
looks like a token problem rather than a proxy problem — fix it here.

Also confirm the roles imported:

```bash
curl -s -X POST http://localhost:8088/auth/realms/master/protocol/openid-connect/token \
  -d "grant_type=password&client_id=admin-cli&username=admin&password=$UNS_keycloak__admin_password" | head -c 120
```

Expected: an `access_token`. If it 401s, the bootstrap admin password did not reach the
container, which means `uv run uns_compose` was not the command used — plain `docker compose`
does not load `conf/.secrets.yaml`.

- [ ] **Step 14: Commit**

```bash
git add conf/keycloak conf/settings.yaml conf/.secrets.yaml.template docker-compose.yml \
        00_uns_config/src/uns_config/compose_env.py 00_uns_config/test/test_compose_env.py \
        00_uns_config/test/test_keycloak_realm.py 11_frontend/nginx.conf
git commit -m "feat(auth): add Keycloak with a realm authored in conf/

The realm is a committed export, not something clicked into a running admin
console, so a fresh compose up produces the same five roles and the same two
clients every time. The console client is public with PKCE required, because a
static bundle cannot keep a secret.

Keycloak's 8080 stays unpublished: the console proxies /auth on its own origin,
which gives the realm exactly one issuer URL and makes Grafana's session cookie
same-origin for the embedded dashboards.

Grafana moves off anonymous access onto the same realm, closing the gap ADR-0001
accepted. Embedding stays enabled."
```

**Definition of done:**
- `conf/keycloak/realm.json` is committed and imported by `--import-realm`.
- `00_uns_config/test/test_keycloak_realm.py` passes all eight cases, and `uv run pytest -q` in
  `00_uns_config` is green.
- The discovery document at `http://localhost:8088/auth/realms/uns/.well-known/openid-configuration`
  advertises the console's origin, verified by hand.
- Keycloak's 8080 is not published, and `docker-compose.yml` states
  `GF_AUTH_ANONYMOUS_ENABLED: "false"` with `GF_AUTH_ANONYMOUS_ORG_ROLE` gone.
- `conf/.secrets_template.yaml` names both new secrets, and `compose_environment` refuses to run
  without them.
- `conf/keycloak/README.md` says the passwords are development-only and that editing the running
  realm does not persist.

---

## Task 2: One authority for the realm's identity, read by three consumers

Three things need to know where the realm is: the GraphQL service (issuer and JWKS, to validate),
the console (authority and client id, to redirect), and Grafana (through compose env, already
done in Task 1). `PlatformConfig` is already the shared home for `cors_origins` and the two
frontend ports, so the realm's identity belongs beside it rather than being retyped in three
places that can drift.

**Files:**
- Modify: `00_uns_config/src/uns_config/platform.py`,
  `07_uns_graphql/src/uns_graphql/graphql_config.py`,
  `11_frontend/platform/settings.ts`, `11_frontend/src/lib/platform/config.ts`
- Test: `00_uns_config/test/test_platform_auth.py` (create),
  `11_frontend/src/lib/platform/settings-auth.test.ts` (create)

**Interfaces:**
- Consumes: the `auth:` block Task 1 added to `conf/settings.yaml`; `uns_config.loader.get_settings`.
- Produces:
  - Python: `uns_config.AuthConfig` with class attributes `realm: str`, `base_url: str`,
    `issuer: str`, `console_client_id: str`, `grafana_client_id: str`, `audience: str`,
    `leeway_seconds: int`, `internal_base_url: str`, and two classmethods
    `jwks_url() -> str` and `discovery_url() -> str`. Re-exported from
    `uns_graphql.graphql_config` beside `PlatformConfig`.
  - TypeScript: `PlatformSettings` gains `authIssuer: string`, `authClientId: string`,
    `authRealm: string`, `authBaseUrl: string`. Available in the browser as
    `platformConfig.authIssuer` etc.
  - Tasks 3–5 consume the Python side; Tasks 8–10 consume the TypeScript side.

- [x] **Step 1: Write the failing Python test**

Create `00_uns_config/test/test_platform_auth.py`:

```python
"""The realm's identity is read from conf/settings.yaml, not retyped per module."""

from uns_config import AuthConfig


def test_issuer_is_the_realm_under_the_console_origin():
    # The console proxies /auth, so the issuer is the console's origin. A token minted with
    # any other issuer is rejected by the GraphQL service, so this string is a contract.
    assert AuthConfig.issuer == "http://localhost:8088/auth/realms/uns"


def test_jwks_url_is_built_from_the_internal_base_url():
    # The service resolves Keycloak by container name: its validation must not depend on the
    # frontend container being up to serve the proxy.
    assert AuthConfig.jwks_url() == (
        "http://uns_keycloak:8080/auth/realms/uns/protocol/openid-connect/certs"
    )


def test_discovery_url_is_browser_facing():
    assert AuthConfig.discovery_url() == (
        "http://localhost:8088/auth/realms/uns/.well-known/openid-configuration"
    )


def test_the_client_ids_match_the_realm_export():
    assert AuthConfig.console_client_id == "uns-console"
    assert AuthConfig.grafana_client_id == "uns-grafana"


def test_audience_matches_the_console_client():
    # The audience mapper in conf/keycloak/realm.json puts this in the access token's `aud`.
    assert AuthConfig.audience == "uns-console"


def test_there_is_leeway_on_expiry():
    # A laptop clock is not the realm's clock, and a plant floor PC's clock is nobody's.
    assert AuthConfig.leeway_seconds > 0
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd 00_uns_config && uv run pytest test/test_platform_auth.py -q`

Expected: `ImportError: cannot import name 'AuthConfig' from 'uns_config'`.

- [x] **Step 3: Add `AuthConfig`**

In `00_uns_config/src/uns_config/platform.py`, after the `PlatformConfig` class:

```python
class AuthConfig:
    """Where the realm is, for everything that has to reach it.

    Two base URLs, and the difference matters. `base_url` is what a browser uses: the console
    proxies `/auth`, so the realm has exactly one issuer and Grafana's session cookie is
    same-origin for the embedded dashboards. `internal_base_url` is what a service inside the
    compose network uses, so that validating a token does not depend on the frontend container
    being up to serve a proxy.
    """

    realm: str = _settings.get("auth.realm", "uns")
    base_url: str = _settings.get("auth.base_url", "http://localhost:8088/auth")
    issuer: str = _settings.get("auth.issuer", "http://localhost:8088/auth/realms/uns")
    console_client_id: str = _settings.get("auth.console_client_id", "uns-console")
    grafana_client_id: str = _settings.get("auth.grafana_client_id", "uns-grafana")
    audience: str = _settings.get("auth.audience", "uns-console")
    leeway_seconds: int = int(_settings.get("auth.leeway_seconds", 30))
    internal_base_url: str = _settings.get("auth.internal_base_url", "http://uns_keycloak:8080")

    @classmethod
    def jwks_url(cls) -> str:
        return f"{cls.internal_base_url}/realms/{cls.realm}/protocol/openid-connect/certs"

    @classmethod
    def discovery_url(cls) -> str:
        return f"{cls.base_url}/realms/{cls.realm}/.well-known/openid-configuration"
```

The two builders are asymmetric on purpose and the test pins it: `internal_base_url` already
ends in the container's root and Keycloak's `--http-relative-path=/auth` puts `/auth` in front of
`/realms`, so `jwks_url` must include it. Write `internal_base_url` in `conf/settings.yaml` as
`http://uns_keycloak:8080/auth` and drop the literal from the f-string — whichever you choose,
the two tests in Step 1 are the arbiter, and the settings value Task 1 committed is
`http://uns_keycloak:8080`, so `jwks_url` supplies `/auth`:

```python
    @classmethod
    def jwks_url(cls) -> str:
        return f"{cls.internal_base_url}/auth/realms/{cls.realm}/protocol/openid-connect/certs"
```

Export it from the package. In `00_uns_config/src/uns_config/__init__.py`, add `AuthConfig` to
the import from `.platform` and to `__all__`, following exactly how `PlatformConfig` is listed
there.

- [x] **Step 4: Re-export it where the GraphQL service already looks**

In `07_uns_graphql/src/uns_graphql/graphql_config.py:29`, widen the existing import:

```python
from uns_config import AuthConfig, PlatformConfig, get_settings
```

`PlatformConfig` is imported there and re-exported by nothing but that import line —
`uns_graphql_app.py:31` reads it straight off `graphql_config`. `AuthConfig` follows the same
path so the app module keeps having one config import.

If the module has an `__all__`, add `"AuthConfig"` to it. If it does not, nothing more is needed
and a linter may flag the import as unused until Task 3 consumes it; leave it, or land Step 4
together with Task 3's first step.

- [x] **Step 5: Run the Python test**

Run: `cd 00_uns_config && uv run pytest test/test_platform_auth.py -q`

Expected: PASS, six tests.

- [x] **Step 6: Write the failing TypeScript test**

Create `11_frontend/src/lib/platform/settings-auth.test.ts`. It tests the build-time loader,
which lives outside `src/` — imported by relative path, which works because
`vitest.config.ts`'s `include` governs which files are collected as tests, not what they may
import:

```ts
import { describe, expect, it } from 'vitest'
import { platformSettingsFromConfig } from '../../../platform/settings'

describe('platformSettingsFromConfig auth values', () => {
  it('reads the realm from the auth block', () => {
    const settings = platformSettingsFromConfig({
      auth: {
        realm: 'uns',
        base_url: 'http://localhost:8088/auth',
        issuer: 'http://localhost:8088/auth/realms/uns',
        console_client_id: 'uns-console',
      },
    })

    expect(settings.authRealm).toBe('uns')
    expect(settings.authBaseUrl).toBe('http://localhost:8088/auth')
    expect(settings.authIssuer).toBe('http://localhost:8088/auth/realms/uns')
    expect(settings.authClientId).toBe('uns-console')
  })

  it('falls back to the compose origin when conf is unreadable', () => {
    // loadPlatformSettings() calls this with {} when it finds no settings.yaml. A console
    // that silently got an empty authority would redirect to nowhere and look like a
    // Keycloak outage, so the fallback has to be the real compose URL.
    const settings = platformSettingsFromConfig({})

    expect(settings.authIssuer).toBe('http://localhost:8088/auth/realms/uns')
    expect(settings.authClientId).toBe('uns-console')
  })
})
```

- [x] **Step 7: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/lib/platform/settings-auth.test.ts`

Expected: FAIL — `authRealm` and the other three are `undefined`, and TypeScript reports four
properties that do not exist on `PlatformSettings`.

- [x] **Step 8: Add the four keys to both platform config modules**

In `11_frontend/platform/settings.ts`, add to the `PlatformSettings` type after
`grafanaProxyTarget`:

```ts
  authRealm: string
  authBaseUrl: string
  authIssuer: string
  authClientId: string
```

In `platformSettingsFromConfig`, read the block beside the existing `urls` and `applications`
destructuring:

```ts
  const auth = (defaults.auth ?? {}) as Record<string, unknown>
  const authRealm = String(auth.realm ?? 'uns')
  const authBaseUrl = String(auth.base_url ?? 'http://localhost:8088/auth')
```

and add to the returned object:

```ts
    authRealm,
    authBaseUrl,
    // Absolute, not a relative path: OIDC discovery hands the browser absolute URLs and the
    // realm mints them from KC_HOSTNAME, so a dev session on 5173 uses this same authority.
    authIssuer: String(auth.issuer ?? `${authBaseUrl}/realms/${authRealm}`),
    authClientId: String(auth.console_client_id ?? 'uns-console'),
```

Mirror the four keys in `11_frontend/src/lib/platform/config.ts`'s `PlatformSettings` type. That
file declares the type a second time for the browser — the two must agree or `platformConfig`
lies about its own shape at compile time while the `define` block supplies the real object.

- [x] **Step 9: Run the frontend checks**

```bash
cd 11_frontend
npx vitest run src/lib/platform
npx tsc --noEmit
```

Expected: green. The pre-existing `src/lib/platform/config.test.ts` from foundation Task 1 also
runs here; if it asserts an exhaustive key list, extend it with the four new keys rather than
loosening the assertion — an exhaustive assertion on a config object is worth keeping.

- [ ] **Step 10: Commit**

```bash
git add 00_uns_config/src/uns_config/platform.py 00_uns_config/src/uns_config/__init__.py \
        00_uns_config/test/test_platform_auth.py \
        07_uns_graphql/src/uns_graphql/graphql_config.py \
        11_frontend/platform/settings.ts 11_frontend/src/lib/platform/config.ts \
        11_frontend/src/lib/platform/settings-auth.test.ts
git commit -m "feat(auth): read the realm's identity from conf, once

Three consumers need it — the GraphQL service to validate, the console to
redirect, Grafana through compose env — so it sits beside cors_origins in
PlatformConfig rather than being retyped per module.

Two base URLs, because a browser reaches the realm through the console's own
nginx and a service inside the network reaches it by container name. Validating
a token must not depend on the frontend container being up."
```

**Definition of done:**
- `AuthConfig` is importable from `uns_config` and from `uns_graphql.graphql_config`.
- `AuthConfig.jwks_url()` returns a URL against `uns_keycloak:8080`, and
  `AuthConfig.discovery_url()` one against `localhost:8088` — both asserted.
- `platformConfig.authIssuer`, `.authClientId`, `.authRealm` and `.authBaseUrl` exist in the
  browser, with the compose URL as the fallback when `conf/` is unreadable.
- `uv run pytest -q` in `00_uns_config` green; `npx vitest run` and `npx tsc --noEmit` in
  `11_frontend` green.

---

## Task 3: Validate a token, and cache the keys that validate it

This is the security-critical unit, and it is the one place in the plan where a permissive
default would be invisible. So it is written as a pure function over a key, with the network
isolated in a separate module behind an injectable fetch, and the tests mint their own tokens
with their own keys. No test in this task reaches Keycloak.

Spec tests 2, 3, 6 and 7 all land here.

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/auth/__init__.py`,
  `07_uns_graphql/src/uns_graphql/auth/jwks.py`,
  `07_uns_graphql/src/uns_graphql/auth/token.py`
- Modify: `07_uns_graphql/pyproject.toml`
- Test: `07_uns_graphql/test/auth/__init__.py`, `07_uns_graphql/test/auth/keys.py`,
  `07_uns_graphql/test/auth/test_jwks.py`, `07_uns_graphql/test/auth/test_token.py` (all create)

**Interfaces:**
- Consumes: `AuthConfig` from Task 2; `aiohttp`, already a dependency
  (`07_uns_graphql/pyproject.toml:38`).
- Produces:
  ```python
  # auth/jwks.py
  class UnknownSigningKeyError(Exception): ...
  class JwksCache:
      def __init__(self, url: str, *, fetch: Callable[[str], Awaitable[dict]] | None = None) -> None
      async def signing_key(self, kid: str) -> Any        # a PyJWT-usable key object
      def fetch_count(self) -> int                         # for the caching test, and only that
      async def close(self) -> None

  # auth/token.py
  CONSOLE_ROLES: frozenset[str]                            # the five, lowercase
  class AuthError(Exception): ...                          # the message reaches the client
  @dataclass(frozen=True)
  class Identity:
      subject: str
      username: str
      roles: frozenset[str]
      def has_any(self, roles: Iterable[str]) -> bool
  def bearer_from_header(value: str | None) -> str | None
  async def identity_from_token(token: str, keys: JwksCache) -> Identity
  ```
- Task 4 constructs the single `JwksCache` and calls `identity_from_token`. Task 5 calls
  `Identity.has_any`.

- [x] **Step 1: Add the one new dependency**

In `07_uns_graphql/pyproject.toml`, add to `dependencies` (after `"aiohttp~=3.14",` so the list
stays roughly grouped by purpose):

```toml
    "pyjwt[crypto]>=2.10,<3",
```

`aiohttp` does the fetching and is already there, so this is one dependency and not two.
`[crypto]` pulls `cryptography`, which is what verifies an RS256 signature; without the extra,
PyJWT silently supports only HMAC and every real token fails to verify with a confusing message.

```bash
cd 07_uns_graphql
uv sync
uv run python -c "import jwt; from jwt import PyJWK; print(jwt.__version__)"
```

Expected: a 2.10-or-later version and no import error on `PyJWK`.

- [x] **Step 2: Write the test key helper**

Create `07_uns_graphql/test/auth/__init__.py` (empty) and
`07_uns_graphql/test/auth/keys.py`:

```python
"""RSA keys and tokens minted in-process, so no test in this suite needs Keycloak.

A test that borrowed a real token would expire, and a test that skipped signature
verification would be testing nothing. So the suite is its own certificate authority.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "http://localhost:8088/auth/realms/uns"
AUDIENCE = "uns-console"


def _b64u(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class TestKey:
    """One RSA keypair, its JWK, and a mint() that signs with it."""

    kid: str
    private_pem: bytes
    jwk: dict

    def mint(
        self,
        *,
        roles: list[str] | None = None,
        username: str = "operator.user",
        subject: str = "11111111-2222-3333-4444-555555555555",
        issuer: str = ISSUER,
        audience: str | list[str] = AUDIENCE,
        expires_in: int = 900,
        issued_at: int | None = None,
    ) -> str:
        now = int(time.time()) if issued_at is None else issued_at
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "preferred_username": username,
            "iat": now,
            "exp": now + expires_in,
            # Keycloak's shape for realm roles. Client roles live under resource_access and
            # this platform does not use them.
            "realm_access": {"roles": list(roles if roles is not None else ["operator"])},
        }
        return jwt.encode(claims, self.private_pem, algorithm="RS256", headers={"kid": self.kid})


def make_key(kid: str = "test-key-1") -> TestKey:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    return TestKey(
        kid=kid,
        private_pem=private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        jwk={
            "kty": "RSA",
            "kid": kid,
            "alg": "RS256",
            "use": "sig",
            "n": _b64u(numbers.n),
            "e": _b64u(numbers.e),
        },
    )


def jwks_document(*keys: TestKey) -> dict:
    return {"keys": [key.jwk for key in keys]}
```

2048 bits, not 4096: this runs on every test that mints a token, and a 4096-bit generation adds
seconds to a suite that already has `pytest-xdist` for a reason.

- [x] **Step 3: Write the failing JWKS test**

Create `07_uns_graphql/test/auth/test_jwks.py`:

```python
"""Spec test 7: fetched once and cached; an unknown kid triggers exactly one refetch."""

import pytest

from uns_graphql.auth.jwks import JwksCache, UnknownSigningKeyError

from .keys import jwks_document, make_key

KEY_A = make_key("key-a")
KEY_B = make_key("key-b")


def _recording_fetch(*documents: dict):
    """Return a fetch that yields each document in turn, and the list of calls it recorded."""
    calls: list[str] = []
    remaining = list(documents)

    async def fetch(url: str) -> dict:
        calls.append(url)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return fetch, calls


@pytest.mark.asyncio
async def test_the_first_lookup_fetches_and_the_second_does_not():
    fetch, calls = _recording_fetch(jwks_document(KEY_A))
    cache = JwksCache("http://keys.test/certs", fetch=fetch)

    assert await cache.signing_key("key-a") is not None
    assert await cache.signing_key("key-a") is not None

    # A fetch per request would make every query wait on Keycloak, and an outage would stop
    # reads that a cached key can still validate (spec section 13).
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_an_unknown_kid_refetches_once_and_then_finds_the_rotated_key():
    fetch, calls = _recording_fetch(jwks_document(KEY_A), jwks_document(KEY_A, KEY_B))
    cache = JwksCache("http://keys.test/certs", fetch=fetch)

    await cache.signing_key("key-a")
    assert len(calls) == 1

    # Key rotation is the normal case this exists for.
    assert await cache.signing_key("key-b") is not None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_kid_that_is_still_unknown_after_the_refetch_raises_and_does_not_loop():
    fetch, calls = _recording_fetch(jwks_document(KEY_A))
    cache = JwksCache("http://keys.test/certs", fetch=fetch)

    with pytest.raises(UnknownSigningKeyError):
        await cache.signing_key("forged-kid")

    # Exactly one refetch. A token with an attacker-chosen kid must not be able to make this
    # service hammer Keycloak once per request.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_failed_refetch_leaves_the_cached_keys_usable():
    calls: list[str] = []

    async def fetch(url: str) -> dict:
        calls.append(url)
        if len(calls) == 1:
            return jwks_document(KEY_A)
        raise ConnectionError("Keycloak is down")

    cache = JwksCache("http://keys.test/certs", fetch=fetch)
    await cache.signing_key("key-a")

    with pytest.raises(UnknownSigningKeyError):
        await cache.signing_key("key-b")

    # Spec section 13: "Cached JWKS keeps validation working until a key rotates."
    assert await cache.signing_key("key-a") is not None
```

- [x] **Step 4: Write the failing token test**

Create `07_uns_graphql/test/auth/test_token.py`:

```python
"""Spec tests 2, 3 and 6, plus the claim mapping every later task depends on."""

import time

import pytest

from uns_graphql.auth.jwks import JwksCache
from uns_graphql.auth.token import AuthError, Identity, bearer_from_header, identity_from_token

from .keys import AUDIENCE, ISSUER, jwks_document, make_key

REALM_KEY = make_key("realm-key")
ATTACKER_KEY = make_key("realm-key")  # same kid, different key: the substitution attack


def _cache(*keys) -> JwksCache:
    document = jwks_document(*keys)

    async def fetch(_url: str) -> dict:
        return document

    return JwksCache("http://keys.test/certs", fetch=fetch)


@pytest.mark.asyncio
async def test_a_token_signed_by_the_realm_resolves_to_an_identity():
    token = REALM_KEY.mint(roles=["engineer"], username="erin.engineer")

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert isinstance(identity, Identity)
    assert identity.username == "erin.engineer"
    assert identity.roles == frozenset({"engineer"})


@pytest.mark.asyncio
async def test_a_token_signed_by_the_wrong_key_is_rejected():
    # Same kid, so the cache finds a key. Only signature verification catches this.
    token = ATTACKER_KEY.mint(roles=["admin"])

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_an_expired_token_is_rejected():
    token = REALM_KEY.mint(issued_at=int(time.time()) - 7200, expires_in=900)

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_from_another_issuer_is_rejected():
    token = REALM_KEY.mint(issuer="http://evil.example/realms/uns")

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_for_another_audience_is_rejected():
    # Grafana's tokens are signed by the same realm with the same key. Without an audience
    # check, a Grafana token would be accepted as a console token.
    token = REALM_KEY.mint(audience="uns-grafana")

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_naming_an_unknown_role_is_accepted_with_that_role_dropped():
    # Spec test 6, and the precedent in map-alert-rules.ts:50-56: "Anything unrecognised is
    # dropped rather than guessed."
    token = REALM_KEY.mint(roles=["engineer", "offline_access", "default-roles-uns"])

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert identity.roles == frozenset({"engineer"})


@pytest.mark.asyncio
async def test_a_token_with_no_recognised_role_is_still_an_identity():
    # Spec section 13: "A user with no recognised role can read and cannot mutate." Rejecting
    # them here would make an unrecognised role look like a broken login.
    token = REALM_KEY.mint(roles=["offline_access"])

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert identity.roles == frozenset()
    assert identity.username == "operator.user"


@pytest.mark.asyncio
async def test_a_token_with_no_realm_access_claim_is_an_identity_with_no_roles():
    token = REALM_KEY.mint(roles=[])

    identity = await identity_from_token(token, _cache(REALM_KEY))

    assert identity.roles == frozenset()


@pytest.mark.asyncio
async def test_a_token_that_is_not_a_jwt_is_rejected_without_a_key_lookup():
    with pytest.raises(AuthError):
        await identity_from_token("not.a.token", _cache(REALM_KEY))


@pytest.mark.asyncio
async def test_a_token_with_no_kid_is_rejected():
    import jwt

    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "s", "exp": int(time.time()) + 60},
        REALM_KEY.private_pem,
        algorithm="RS256",
    )

    with pytest.raises(AuthError):
        await identity_from_token(token, _cache(REALM_KEY))


def test_bearer_is_read_case_insensitively_and_nothing_else_is():
    assert bearer_from_header("Bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_from_header("bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_from_header(None) is None
    assert bearer_from_header("") is None
    assert bearer_from_header("Basic dXNlcjpwYXNz") is None
    # A bare token is not a bearer token. Accepting it would be one more shape to reason about.
    assert bearer_from_header("abc.def.ghi") is None


def test_identity_has_any():
    identity = Identity(subject="s", username="u", roles=frozenset({"operator"}))
    assert identity.has_any(["operator", "engineer"]) is True
    assert identity.has_any(["engineer", "admin"]) is False
    assert identity.has_any([]) is False
```

`ATTACKER_KEY = make_key("realm-key")` sharing a kid with `REALM_KEY` is the point of that test,
not a copy-paste slip: it proves the code verifies the signature rather than trusting that a
matching kid was found.

- [x] **Step 5: Run both and watch them fail**

Run: `cd 07_uns_graphql && uv run pytest test/auth -q`

Expected: collection errors — `uns_graphql.auth` does not exist. If instead you get
`fixture 'event_loop' not found` or an async test being skipped, check `[tool.pytest.ini_options]`
in `pyproject.toml` for `asyncio_mode`; if it is not `auto`, the `@pytest.mark.asyncio`
decorators above are already correct and nothing changes.

- [x] **Step 6: Write the JWKS cache**

Create `07_uns_graphql/src/uns_graphql/auth/__init__.py` (empty) and
`07_uns_graphql/src/uns_graphql/auth/jwks.py`:

```python
"""The realm's signing keys, fetched once and kept.

Fetching per request would put Keycloak in the path of every query, and an outage would then
stop reads that a key already in memory can validate perfectly well. So: cache by `kid`, and
refetch at most once when a `kid` is unknown, because that is what key rotation looks like.

`fetch` is injectable so the tests never open a socket.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from jwt import PyJWK

LOGGER = logging.getLogger(__name__)


class UnknownSigningKeyError(Exception):
    """No key with that `kid`, and a refetch did not produce one."""


async def _fetch_over_http(url: str) -> dict:
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        response.raise_for_status()
        return await response.json()


class JwksCache:
    """Signing keys by `kid`, with one refetch on a miss."""

    def __init__(
        self,
        url: str,
        *,
        fetch: Callable[[str], Awaitable[dict]] | None = None,
    ) -> None:
        self._url = url
        self._fetch = fetch or _fetch_over_http
        self._keys: dict[str, Any] = {}
        self._fetches = 0
        # One refetch at a time: a hundred requests arriving after a rotation must not become
        # a hundred requests to Keycloak.
        self._lock = asyncio.Lock()

    def fetch_count(self) -> int:
        """How many times the document has been fetched. Exists for the caching test."""
        return self._fetches

    async def signing_key(self, kid: str) -> Any:
        if kid in self._keys:
            return self._keys[kid]

        async with self._lock:
            # Another coroutine may have refreshed while this one waited.
            if kid in self._keys:
                return self._keys[kid]
            await self._refresh()

        if kid not in self._keys:
            raise UnknownSigningKeyError(f"The realm has no signing key {kid!r}")
        return self._keys[kid]

    async def _refresh(self) -> None:
        try:
            document = await self._fetch(self._url)
            self._fetches += 1
        except Exception:
            # Keep whatever is cached. Spec section 13: cached keys keep validation working
            # until a key rotates, and a rotation during an outage is the unlucky case.
            LOGGER.warning("Could not refresh JWKS from %s; keeping %s cached key(s)",
                           self._url, len(self._keys))
            return

        refreshed: dict[str, Any] = {}
        for jwk in document.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            try:
                refreshed[kid] = PyJWK.from_dict(jwk).key
            except Exception:
                # One unusable key in the document must not cost us the rest of them.
                LOGGER.warning("Skipping unusable JWK %s from the realm", kid)
        if refreshed:
            self._keys = refreshed

    async def close(self) -> None:
        """Nothing to close: each fetch owns its session. Here so callers can be symmetric."""
        return None
```

Two things the tests pin that are easy to get wrong. `self._fetches` increments only on a
*successful* fetch, which is why the failed-refetch test can assert one call to `fetch` and
still find the cached key. And `self._keys` is replaced only when `refreshed` is non-empty, so a
realm that briefly answers with `{"keys": []}` does not wipe a working cache.

- [x] **Step 7: Write the token validator**

Create `07_uns_graphql/src/uns_graphql/auth/token.py`:

```python
"""Turn a bearer token into an identity, or raise.

Pure given a key, so the tests mint their own tokens and no test needs Keycloak. Every
rejection raises `AuthError` with a sentence, because the message reaches the client and
"invalid token" tells an engineer nothing about which of six things went wrong.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import jwt
from uns_config import AuthConfig

from uns_graphql.auth.jwks import JwksCache, UnknownSigningKeyError

LOGGER = logging.getLogger(__name__)

# The five in ConsoleRole (type/alert_rule.py:70) and UserRole (11_frontend/src/types/rbac.ts:5).
CONSOLE_ROLES: frozenset[str] = frozenset({"admin", "engineer", "operator", "auditor", "viewer"})

_BEARER = "bearer "


class AuthError(Exception):
    """The request carried no usable identity. The message is shown to the caller."""


@dataclass(frozen=True)
class Identity:
    """Who the realm says is calling. Constructed only by `identity_from_token`."""

    subject: str
    username: str
    roles: frozenset[str]

    def has_any(self, roles: Iterable[str]) -> bool:
        return bool(self.roles & frozenset(roles))


def bearer_from_header(value: str | None) -> str | None:
    """The token out of an Authorization header, or None. Case-insensitive on the scheme only."""
    if not value:
        return None
    if not value.lower().startswith(_BEARER):
        return None
    token = value[len(_BEARER):].strip()
    return token or None


def _roles_from_claims(claims: dict) -> frozenset[str]:
    """Realm roles, filtered to the five this platform knows.

    Keycloak issues `offline_access`, `uma_authorization` and `default-roles-<realm>` to
    everybody. Dropping the unrecognised rather than guessing follows
    11_frontend/src/lib/alarms/map-alert-rules.ts:50-56.
    """
    realm_access = claims.get("realm_access") or {}
    granted = realm_access.get("roles") or []
    return frozenset(role for role in granted if role in CONSOLE_ROLES)


async def identity_from_token(token: str, keys: JwksCache) -> Identity:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as ex:
        raise AuthError("The Authorization header is not a JSON Web Token.") from ex

    kid = header.get("kid")
    if not kid:
        # Every Keycloak token has one. A token without it cannot be matched to a key, and
        # searching every key for one that happens to verify is how algorithm-confusion bugs
        # get in.
        raise AuthError("The token names no signing key (no `kid` header).")

    try:
        key = await keys.signing_key(kid)
    except UnknownSigningKeyError as ex:
        raise AuthError(
            f"The token was signed by key {kid!r}, which this realm does not publish."
        ) from ex

    try:
        claims = jwt.decode(
            token,
            key,
            # RS256 only, from the algorithm in the realm export. Never read the header's
            # `alg`: that is how a token arrives signed with `none` or with HMAC over the
            # public key.
            algorithms=["RS256"],
            issuer=AuthConfig.issuer,
            audience=AuthConfig.audience,
            leeway=AuthConfig.leeway_seconds,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as ex:
        raise AuthError("The token has expired. Sign in again.") from ex
    except jwt.InvalidIssuerError as ex:
        raise AuthError(f"The token was issued by somebody other than {AuthConfig.issuer}.") from ex
    except jwt.InvalidAudienceError as ex:
        raise AuthError(
            f"The token was issued for a different application, not {AuthConfig.audience}."
        ) from ex
    except jwt.PyJWTError as ex:
        raise AuthError("The token's signature could not be verified.") from ex

    return Identity(
        subject=str(claims["sub"]),
        # `preferred_username` and not the subject UUID: this is what gets stored on a
        # downtime reassignment, and a UUID is unreadable to the next shift lead
        # (spec section 16).
        username=str(claims.get("preferred_username") or claims["sub"]),
        roles=_roles_from_claims(claims),
    )
```

`algorithms=["RS256"]` is the single most important line in this task. PyJWT will not read the
header's `alg` when given an explicit list, which is what makes the `alg: none` and
HMAC-over-the-public-key attacks impossible rather than merely unlikely.

- [x] **Step 8: Run the tests**

```bash
cd 07_uns_graphql
uv run pytest test/auth -q
```

Expected: PASS, 15 tests. Two likely stumbles:

- `test_a_token_for_another_audience_is_rejected` failing means `AuthConfig.audience` is not
  `uns-console`, or `jwt.decode` was called without `audience=`. PyJWT ignores `aud` entirely
  unless you pass it — silently, which is why this test exists.
- `test_a_token_naming_an_unknown_role_is_accepted_with_that_role_dropped` failing with a
  *rejection* means `_roles_from_claims` was written to raise on an unknown role. It must not:
  spec section 13 says a user with no recognised role reads and cannot mutate.

- [ ] **Step 9: Run the whole module suite**

Run: `cd 07_uns_graphql && uv run pytest -q`

Expected: green, unchanged from before this task. Nothing yet calls `identity_from_token`, so no
existing behaviour moves.

- [ ] **Step 10: Commit**

```bash
cd 07_uns_graphql
git add pyproject.toml uv.lock src/uns_graphql/auth test/auth
git commit -m "feat(graphql): validate realm tokens, and cache the keys

Signature, issuer, audience and expiry, with RS256 pinned explicitly so the
header's alg is never consulted. Unrecognised realm roles are dropped rather
than guessed, following the console's own precedent, and a token with no
recognised role is still an identity — it reads and cannot mutate.

Keys are cached by kid with at most one refetch on a miss, so key rotation
works and a token with an attacker-chosen kid cannot turn every request into a
request to Keycloak. A failed refetch keeps the cached keys usable.

The tests mint their own tokens with their own keys. Nothing here reaches
Keycloak."
```

**Definition of done:**
- `uv run pytest test/auth -q` passes 15 tests, and no test in the module opens a socket.
- A token signed by a different key with the same `kid` is rejected (spec test 2).
- An expired token is rejected (spec test 3); a wrong issuer and a wrong audience are too.
- An unknown realm role is dropped and the token still resolves (spec test 6).
- The JWKS document is fetched once for repeated lookups, refetched exactly once on an unknown
  `kid`, and a failed refetch leaves the cache usable (spec test 7).
- `algorithms=["RS256"]` is explicit, and `options={"require": [...]}` demands `exp`, `iss`,
  `aud` and `sub`.

---

## Task 4: No token, no answer — the gate at the one door

Finding 4 of the spec: there is exactly one `GraphQLRouter` in this service, mounted once at
`/graphql`. So authentication is one dependency and one `on_ws_connect` override, and no
resolver has to remember to check.

Two transports, two places the token can be, because a browser cannot set a header on a
WebSocket handshake:

| Transport | Where the token is | What rejects it |
| --- | --- | --- |
| `POST /graphql` | `Authorization: Bearer …` | the context dependency, with HTTP 401 |
| `WS /graphql` | the `connection_init` payload | `on_ws_connect`, closing with 4403 |

This is spec test 1 and success criterion 2.

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/auth/context.py`
- Modify: `07_uns_graphql/src/uns_graphql/uns_graphql_app.py:27`–`:31`, `:122`–`:128`
- Test: `07_uns_graphql/test/auth/test_context.py`,
  `07_uns_graphql/test/auth/test_graphql_gate.py` (both create)

**Interfaces:**
- Consumes: `Identity`, `AuthError`, `bearer_from_header`, `identity_from_token` (Task 3);
  `JwksCache` (Task 3); `AuthConfig` (Task 2).
- Produces:
  ```python
  # auth/context.py
  CONTEXT_KEY = "identity"
  def signing_keys() -> JwksCache                  # the process-wide cache, built on first use
  def use_signing_keys(cache: JwksCache | None) -> None   # tests only
  async def graphql_context(connection: HTTPConnection) -> dict
  def identity_in(context) -> Identity | None      # tolerant of a missing or None context
  class AuthenticatedGraphQLRouter(GraphQLRouter): ...    # overrides on_ws_connect
  ```
- Task 5 calls `identity_in`. Nothing else consumes this.

- [x] **Step 1: Write the failing unit test for the dependency**

Create `07_uns_graphql/test/auth/test_context.py`:

```python
"""The context dependency, tested without a server.

The dependency takes a starlette HTTPConnection, which is the common base of Request and
WebSocket - the same annotation Strawberry's own context dependency uses
(fastapi/dependencies/utils.py:359 is what makes FastAPI inject it for both route types).
A stub with a scope and headers is therefore enough, and is faster than a TestClient.
"""

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from uns_graphql.auth.context import (
    graphql_context,
    identity_in,
    use_signing_keys,
)
from uns_graphql.auth.jwks import JwksCache
from uns_graphql.auth.token import Identity

from .keys import jwks_document, make_key

REALM_KEY = make_key("gate-key")


class FakeConnection:
    """Enough of starlette's HTTPConnection for the dependency to read."""

    def __init__(self, *, headers: dict | None = None, kind: str = "http", method: str = "POST"):
        self.scope = {"type": kind, "method": method}
        self.headers = Headers(headers or {})


@pytest.fixture(autouse=True)
def realm_keys():
    document = jwks_document(REALM_KEY)

    async def fetch(_url: str) -> dict:
        return document

    use_signing_keys(JwksCache("http://keys.test/certs", fetch=fetch))
    yield
    # Leave no cache behind: a later test getting this one's keys would pass for the wrong reason.
    use_signing_keys(None)


@pytest.mark.asyncio
async def test_a_valid_token_becomes_an_identity_in_the_context():
    token = REALM_KEY.mint(roles=["operator"], username="olga.operator")

    context = await graphql_context(FakeConnection(headers={"authorization": f"Bearer {token}"}))

    identity = identity_in(context)
    assert isinstance(identity, Identity)
    assert identity.username == "olga.operator"


@pytest.mark.asyncio
async def test_no_authorization_header_is_a_401():
    with pytest.raises(HTTPException) as raised:
        await graphql_context(FakeConnection())

    assert raised.value.status_code == 401
    # Without this header a browser's fetch cannot tell an expired session from a server
    # fault, and the console's refresh-once path (Task 9) has nothing to key on.
    assert raised.value.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_a_bad_token_is_a_401_that_says_why():
    other_realm = make_key("gate-key")  # same kid, different key
    token = other_realm.mint(roles=["admin"])

    with pytest.raises(HTTPException) as raised:
        await graphql_context(FakeConnection(headers={"authorization": f"Bearer {token}"}))

    assert raised.value.status_code == 401
    assert "signature" in str(raised.value.detail).lower()


@pytest.mark.asyncio
async def test_a_websocket_handshake_is_allowed_through_with_no_identity():
    # A browser cannot set headers on a WebSocket handshake, so the token arrives later in
    # connection_init. Rejecting here would make subscriptions impossible from a browser.
    context = await graphql_context(FakeConnection(kind="websocket"))

    assert identity_in(context) is None


@pytest.mark.asyncio
async def test_the_graphiql_page_loads_without_a_token():
    # The IDE is a static HTML page with a Headers tab. Letting the page load and requiring a
    # pasted token for the operations keeps the dev tool usable; 401ing the page reads as an
    # outage.
    context = await graphql_context(
        FakeConnection(kind="http", method="GET", headers={"accept": "text/html"})
    )

    assert identity_in(context) is None


@pytest.mark.asyncio
async def test_a_get_query_still_needs_a_token():
    # allow_queries_via_get is on by default, so GET is a real operation transport. Only the
    # html-seeking GET is the IDE.
    with pytest.raises(HTTPException):
        await graphql_context(
            FakeConnection(kind="http", method="GET", headers={"accept": "application/json"})
        )


def test_identity_in_tolerates_the_contexts_the_test_suite_uses():
    # UNSGraphql.schema.execute() with no context_value gives resolvers info.context of None,
    # and the existing suite calls it that way in a dozen files.
    assert identity_in(None) is None
    assert identity_in({}) is None
    assert identity_in({"identity": None}) is None
```

- [x] **Step 2: Write the failing end-to-end gate test**

Create `07_uns_graphql/test/auth/test_graphql_gate.py`. This one goes through the real app,
the way `test_uns_graphql_cors.py:29` already does — no database is reached, because the
dependency rejects before execution:

```python
"""Spec test 1: no bearer token, no answer - on every operation.

Enumerated rather than sampled. A gate that covers five of six mutations is not a gate, and
the missing one is always the one nobody listed.
"""

import pytest
from fastapi.testclient import TestClient

from uns_graphql.auth.jwks import JwksCache
from uns_graphql.auth.context import use_signing_keys
from uns_graphql.uns_graphql_app import UNSGraphql

from .keys import jwks_document, make_key

REALM_KEY = make_key("gate-key")

OPERATIONS = [
    # Queries. Every one of them, per success criterion 2.
    ("getUnsNodes", "{ getUnsNodes(topics: [\"a/b\"]) { topic } }"),
    ("getHistoricEvents",
     "{ getHistoricEventsByPublishers(publishers: [\"client-1\"]) { topic } }"),
    ("getAssets", "{ getAssets { path } }"),
    ("getAlertRules", "{ getAlertRules { id } }"),
    # The OEE query's datetime arguments are published as `from`/`to` (strawberry.argument
    # renames them), and the field is oeeShiftResults, not getShiftResults.
    ("oeeShiftResults",
     "{ oeeShiftResults(assetPath: \"a\", from: \"2026-01-01T00:00:00Z\", "
     "to: \"2026-01-01T08:00:00Z\") { shiftStart } }"),
    # All six mutations, per finding 3.
    ("saveAlertRule", 'mutation { saveAlertRule(rule: {id: "r", name: "n", severity: '
                      'CRITICAL, category: TEMPERATURE, topic: "a/b", metricField: "value", '
                      'condition: GREATER_THAN, thresholdValue: 1.0}) { id } }'),
    ("saveAlertRules", "mutation { saveAlertRules(rules: []) { id } }"),
    ("deleteAlertRule", 'mutation { deleteAlertRule(id: "r") }'),
    ("setAlertRuleEnabled", 'mutation { setAlertRuleEnabled(id: "r", enabled: false) { id } }'),
    ("recordAlertRuleEvaluation",
     'mutation { recordAlertRuleEvaluation(id: "r", triggered: true) { id } }'),
    ("assignDowntimeReason",
     'mutation { assignDowntimeReason(eventId: "1", reasonCode: "MECH_FAULT") { id } }'),
]


@pytest.fixture(autouse=True)
def realm_keys():
    document = jwks_document(REALM_KEY)

    async def fetch(_url: str) -> dict:
        return document

    use_signing_keys(JwksCache("http://keys.test/certs", fetch=fetch))
    yield
    use_signing_keys(None)


@pytest.mark.parametrize(("label", "document"), OPERATIONS, ids=[name for name, _ in OPERATIONS])
def test_no_token_is_rejected(label: str, document: str):  # noqa: ARG001
    client = TestClient(UNSGraphql.app)

    response = client.post("/graphql", json={"query": document})

    assert response.status_code == 401


@pytest.mark.parametrize(("label", "document"), OPERATIONS, ids=[name for name, _ in OPERATIONS])
def test_a_garbage_token_is_rejected(label: str, document: str):  # noqa: ARG001
    client = TestClient(UNSGraphql.app)

    response = client.post(
        "/graphql",
        json={"query": document},
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 401


def test_a_valid_token_gets_past_the_gate():
    """
    The gate opens. What happens next is a resolver reaching a database this test has none
    of, so the assertion is only that the answer is no longer 401 - which is precisely what
    this task is responsible for.
    """
    client = TestClient(UNSGraphql.app)
    token = REALM_KEY.mint(roles=["viewer"])

    response = client.post(
        "/graphql",
        json={"query": "{ __typename }"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"__typename": "Query"}


def test_the_preflight_permits_the_authorization_header():
    """
    allow_headers=["*"] at uns_graphql_app.py:136 already covers this. The test exists
    because if it ever stops covering it, every console request fails in the browser and
    passes in every test that does not go through CORS.
    """
    from uns_graphql.graphql_config import PlatformConfig

    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": PlatformConfig.frontend_compose_origin(),
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    allowed = (response.headers.get("access-control-allow-headers") or "").lower()
    assert "authorization" in allowed or allowed == "*"
```

The `{ __typename }` document in the last test is chosen deliberately: it is a real operation
that executes without touching a backend, so the test proves the gate opened rather than
proving a database was absent.

If any of the five query documents does not match the current schema, fix the document — do
not delete the case. `UNSGraphql.schema.as_str()` prints the schema, and a syntax-invalid
document would return HTTP 400 with the gate open, which is a passing test for the wrong
reason. Guard against that by checking that every case returns exactly 401 and never 400.

- [x] **Step 3: Run both and watch them fail**

```bash
cd 07_uns_graphql
uv run pytest test/auth/test_context.py test/auth/test_graphql_gate.py -q
```

Expected: import errors on `uns_graphql.auth.context`.

- [x] **Step 4: Write the context module**

Create `07_uns_graphql/src/uns_graphql/auth/context.py`:

```python
"""The gate, at the one door this service has.

`uns_graphql_app.py` mounts exactly one GraphQLRouter at one path, so authentication is a
dependency and a WebSocket hook rather than a check each resolver has to remember. A resolver
reading a header would be a resolver that could forget to.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from starlette.requests import HTTPConnection
from strawberry.exceptions import ConnectionRejectionError
from strawberry.fastapi import GraphQLRouter

from uns_graphql.auth.jwks import JwksCache
from uns_graphql.auth.token import AuthError, Identity, bearer_from_header, identity_from_token
from uns_graphql.graphql_config import AuthConfig

LOGGER = logging.getLogger(__name__)

CONTEXT_KEY = "identity"

_UNAUTHENTICATED = {"WWW-Authenticate": "Bearer"}

_keys: JwksCache | None = None


def signing_keys() -> JwksCache:
    """The process-wide key cache, built on first use.

    One instance, so the document is fetched once for the whole service rather than once per
    request. Built lazily rather than at import so that importing this module does not depend
    on the realm being reachable.
    """
    global _keys  # noqa: PLW0603
    if _keys is None:
        _keys = JwksCache(AuthConfig.jwks_url())
    return _keys


def use_signing_keys(cache: JwksCache | None) -> None:
    """Replace the process-wide cache. Tests only; pass None to clear it."""
    global _keys  # noqa: PLW0603
    _keys = cache


def identity_in(context: Any) -> Identity | None:
    """The identity in a Strawberry context, or None.

    Tolerant on purpose. `schema.execute()` with no `context_value` gives resolvers a context
    of None, and a dozen files in this suite call it that way.
    """
    if context is None:
        return None
    if isinstance(context, dict):
        return context.get(CONTEXT_KEY)
    return getattr(context, CONTEXT_KEY, None)


def _is_ide_page(connection: HTTPConnection) -> bool:
    """A GET asking for HTML is GraphiQL fetching its own page, not an operation.

    The IDE has a Headers tab, so letting the page load and requiring a pasted token for the
    operations keeps it usable. `allow_queries_via_get` is on, so a GET *is* an operation
    transport - only the html-seeking one is the tool.
    """
    if connection.scope.get("method") != "GET":
        return False
    return "text/html" in connection.headers.get("accept", "")


async def graphql_context(connection: HTTPConnection) -> dict:
    """Validate the bearer token and hand the identity to the resolvers.

    `HTTPConnection` and not `Request`: it is the common base of Request and WebSocket, which
    is what lets one dependency serve both the POST route and the WS route.
    """
    if connection.scope.get("type") == "websocket":
        # A browser cannot set a header on a WebSocket handshake. The token arrives in
        # connection_init, and AuthenticatedGraphQLRouter.on_ws_connect checks it there.
        return {CONTEXT_KEY: None}

    if _is_ide_page(connection):
        return {CONTEXT_KEY: None}

    token = bearer_from_header(connection.headers.get("authorization"))
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="This endpoint requires a bearer token from the UNS realm.",
            headers=_UNAUTHENTICATED,
        )

    try:
        identity = await identity_from_token(token, signing_keys())
    except AuthError as ex:
        # The message is the point: "expired" and "wrong audience" are different problems and
        # an engineer reading a log needs to know which one happened.
        LOGGER.info("Rejected a request to /graphql: %s", ex)
        raise HTTPException(status_code=401, detail=str(ex), headers=_UNAUTHENTICATED) from ex

    return {CONTEXT_KEY: identity}


class AuthenticatedGraphQLRouter(GraphQLRouter):
    """A router whose subscriptions need an identity too.

    `on_ws_connect` runs after `connection_init` has been received and after Strawberry has
    put its payload on the context, which is the first moment a WebSocket token exists.
    Rejecting here closes the socket with 4403 rather than letting a subscription stream plant
    data to an anonymous client.
    """

    async def on_ws_connect(self, context: Any) -> dict[str, object]:
        params = _connection_params(context)
        token = bearer_from_header(params.get("Authorization") or params.get("authorization"))
        if token is None:
            LOGGER.info("Rejected a subscription: connection_init carried no bearer token")
            raise ConnectionRejectionError

        try:
            identity = await identity_from_token(token, signing_keys())
        except AuthError as ex:
            LOGGER.info("Rejected a subscription: %s", ex)
            raise ConnectionRejectionError from ex

        if isinstance(context, dict):
            context[CONTEXT_KEY] = identity
        else:
            setattr(context, CONTEXT_KEY, identity)
        # Echoed in connection_ack so the console can show who it connected as without
        # decoding its own token twice.
        return {"username": identity.username}


def _connection_params(context: Any) -> dict:
    params = (
        context.get("connection_params")
        if isinstance(context, dict)
        else getattr(context, "connection_params", None)
    )
    return params if isinstance(params, dict) else {}
```

`params.get("Authorization")` first and lowercase second: `connection_init` carries a JSON
object, not HTTP headers, so its keys are case-sensitive and whichever spelling the client
sends is the spelling that arrives. Task 9 sends `Authorization`; accepting both costs one
`or` and saves an afternoon.

- [x] **Step 5: Wire it into the app**

In `07_uns_graphql/src/uns_graphql/uns_graphql_app.py`, replace the `GraphQLRouter` import at
`:27`:

```python
from strawberry.schema.config import StrawberryConfig
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL

from uns_graphql.auth.context import AuthenticatedGraphQLRouter, graphql_context
from uns_graphql.graphql_config import PlatformConfig
```

The `from strawberry.fastapi import GraphQLRouter` line goes: nothing else uses it, and
leaving it invites the next edit to construct the unauthenticated router by accident.

Then replace the router construction at `:122`–`:128`:

```python
    graphql_app = AuthenticatedGraphQLRouter(
        schema,
        # Every request to /graphql resolves an identity here or is refused with 401. This is
        # the single point that ADR-0005's "There is no authorization in this service" refers
        # to, and the reason that sentence can now be retired.
        context_getter=graphql_context,
        subscription_protocols=[
            GRAPHQL_TRANSPORT_WS_PROTOCOL,
            GRAPHQL_WS_PROTOCOL,
        ],
    )
```

Leave `app.add_middleware(CORSMiddleware, ...)` alone. `allow_headers=["*"]` at `:136` already
admits `Authorization`, and `allow_credentials=True` at `:134` is unrelated to bearer tokens —
narrowing either is out of scope here.

- [x] **Step 6: Run the new tests**

```bash
cd 07_uns_graphql
uv run pytest test/auth -q
```

Expected: PASS. Two failures worth predicting:

- If `test_a_valid_token_gets_past_the_gate` returns 401, the fixture's `use_signing_keys` ran
  after the app was imported but the app is holding its own cache — it is not; `signing_keys()`
  is called per request, which is why the setter works at all. Check instead that
  `AuthConfig.issuer` matches `test/auth/keys.py`'s `ISSUER`. Those two strings must agree, and
  `keys.py` hard-codes the value from `conf/settings.yaml` on purpose so that a settings change
  fails a test rather than silently widening what the service accepts.
- If a query case returns 400 instead of 401, its document does not match the schema. Fix the
  document.

- [ ] **Step 7: Run the whole module suite**

```bash
cd 07_uns_graphql
uv run pytest -q
```

Expected: green, and unchanged. Nothing else in the suite posts through the router —
`test_uns_graphql_cors.py` only sends preflights, which CORS answers before any dependency
runs, and every other test calls `UNSGraphql.schema.execute(...)`, which bypasses the router
entirely. That last fact is what keeps this task from touching a dozen test files, and it is
also why Task 5 has to.

- [ ] **Step 8: Check it by hand against the stack**

With the stack up (`uv run uns_compose up -d --build`):

```bash
# No token: refused.
curl -si -X POST http://localhost:8088/graphql \
  -H 'content-type: application/json' \
  -d '{"query":"{ __typename }"}' | head -5
```

Expected: `HTTP/1.1 401`, and a `WWW-Authenticate: Bearer` header.

```bash
# With a token from the realm, using the dev password from conf/keycloak/README.md.
TOKEN=$(curl -s -X POST \
  http://localhost:8088/auth/realms/uns/protocol/openid-connect/token \
  -d 'client_id=uns-console' -d 'grant_type=password' \
  -d 'username=engineer.user' -d 'password=development-only' | python -c \
  'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -s -X POST http://localhost:8088/graphql \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"query":"{ __typename }"}'
```

Expected: `{"data":{"__typename":"Query"}}`.

This needs `directAccessGrantsEnabled` on the `uns-console` client, which Task 1 deliberately
set to `false`. So either run this check against a temporarily flipped flag and flip it back,
or read the token out of the console's own session in the browser devtools. **Do not commit a
realm with direct access grants enabled** — a password grant on a public client is a
credential-stuffing target and it defeats the point of PKCE.

- [ ] **Step 9: Commit**

```bash
cd 07_uns_graphql
git add src/uns_graphql/auth/context.py src/uns_graphql/uns_graphql_app.py test/auth
git commit -m "feat(graphql): require a realm token at /graphql

One dependency and one on_ws_connect override, because this service mounts
exactly one GraphQLRouter. POST carries the token in Authorization; the
WebSocket carries it in connection_init, because a browser cannot set a header
on a handshake.

Enumerated, not sampled: every query and all six mutations are asserted to
return 401 without a token. The GraphiQL page still loads so its Headers tab
remains usable; a GET that asks for JSON does not.

Retires the first half of ADR-0005's 'Anyone who can reach /graphql can now
change alarm configuration'. The second half is the next task."
```

**Definition of done:**
- Every query and all six mutations return HTTP 401 without a bearer token, and with a
  malformed one (spec test 1, success criterion 2).
- A valid token executes `{ __typename }` and returns data.
- A WebSocket handshake reaches `on_ws_connect`, which rejects a `connection_init` with no
  token by closing 4403.
- The GraphiQL page loads unauthenticated; a GET operation asking for JSON does not.
- `uv run pytest -q` green across `07_uns_graphql`, with no existing test modified.

---

## Task 5: The role table, one test per cell

Spec test 4 asks for a test per cell "because a table like that is exactly where an off-by-one
in a role list hides". A table that is tested cell by cell has to *exist* as a table, so the
policy lives in one dict and not in six `if` statements.

Section 7's table, verbatim:

| Mutation | Required role |
| --- | --- |
| `saveAlertRule` | `engineer`, `admin` |
| `saveAlertRules` | `engineer`, `admin` |
| `deleteAlertRule` | `engineer`, `admin` |
| `setAlertRuleEnabled` | `operator`, `engineer`, `admin` |
| `recordAlertRuleEvaluation` | any authenticated role |
| `assignDowntimeReason` | `operator`, `engineer`, `admin` |

Queries are not role-gated. Task 4 already made them require authentication, and spec section
16 records why gating reads further would mean inventing an Asset-to-role model that
`model.asset` does not have.

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/auth/require.py`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/alert_rule.py`,
  `07_uns_graphql/src/uns_graphql/mutations/oee.py`
- Test: `07_uns_graphql/test/auth/test_require.py` (create),
  `07_uns_graphql/test/mutations/test_alert_rule.py` (modify),
  `07_uns_graphql/test/mutations/test_oee.py` (modify)

**Interfaces:**
- Consumes: `identity_in` (Task 4), `Identity`, `CONSOLE_ROLES` (Task 3).
- Produces:
  ```python
  # auth/require.py
  ANY_AUTHENTICATED_ROLE: frozenset[str]                    # == CONSOLE_ROLES
  MUTATION_ROLES: dict[str, frozenset[str]]                 # keyed by camelCase field name
  class NotPermittedError(Exception): ...
  def require(info, mutation: str) -> Identity              # raises NotPermittedError
  ```
- Task 6 uses `require`'s return value for `assignedBy`.

- [x] **Step 1: Write the failing table test**

Create `07_uns_graphql/test/auth/test_require.py`:

```python
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
    # Six, per finding 3 and the assertion already in test/mutations/test_oee.py:186. A
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
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd 07_uns_graphql && uv run pytest test/auth/test_require.py -q`

Expected: `ModuleNotFoundError: uns_graphql.auth.require`.

- [x] **Step 3: Write the table**

Create `07_uns_graphql/src/uns_graphql/auth/require.py`:

```python
"""Who may write what.

One table, because a policy spread across six resolvers cannot be reviewed and cannot be
tested cell by cell. Keys are the camelCase field names the schema publishes, so that a
reader of this file and a reader of the GraphQL schema are looking at the same names.

Queries are absent on purpose. Any authenticated role may read: the read surface is plant
data, and an operator who cannot read the plant cannot work. Gating reads by Asset would need
an Asset-to-role mapping that `model.asset` does not have.
"""

from __future__ import annotations

from typing import Any

from uns_graphql.auth.context import identity_in
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
```

Note what the error says about the caller as well as the requirement. "You need engineer" sends
somebody to ask for a role they may already have under a different name; "you need engineer or
admin, you hold viewer" ends the conversation in one message.

- [x] **Step 4: Run the table test**

Run: `cd 07_uns_graphql && uv run pytest test/auth/test_require.py -q`

Expected: PASS — 6 + 30 - 6 parametrised cases plus the six singles. Every cell of the table in
both directions.

- [x] **Step 5: Gate the five Alert Rule mutations**

In `07_uns_graphql/src/uns_graphql/mutations/alert_rule.py`, add the import after `:38`:

```python
from uns_graphql.auth.require import require
from uns_graphql.input.alert_rule import AlertRuleInput
from uns_graphql.type.alert_rule import AlertRuleType
```

Then take `info` and call `require` as the first line of each resolver. `save_alert_rule`
becomes:

```python
    async def save_alert_rule(self, info: strawberry.Info, rule: AlertRuleInput) -> AlertRuleType:
        require(info, "saveAlertRule")
        saved = await _repository().save_rule(rule.to_spec())
        LOGGER.info("Alert Rule %s saved for topic %s", saved.id, saved.topic)
        return AlertRuleType.from_rule(saved)
```

and the other four the same way:

```python
    async def save_alert_rules(
        self, info: strawberry.Info, rules: list[AlertRuleInput]
    ) -> list[AlertRuleType]:
        require(info, "saveAlertRules")
        ...

    async def delete_alert_rule(self, info: strawberry.Info, id: str) -> bool:  # noqa: A002
        require(info, "deleteAlertRule")
        ...

    async def set_alert_rule_enabled(
        self, info: strawberry.Info, id: str, enabled: bool  # noqa: A002
    ) -> AlertRuleType | None:
        require(info, "setAlertRuleEnabled")
        ...

    async def record_alert_rule_evaluation(
        self, info: strawberry.Info, id: str, triggered: bool  # noqa: A002
    ) -> AlertRuleType | None:
        require(info, "recordAlertRuleEvaluation")
        ...
```

`strawberry.Info` is not published as a GraphQL argument — Strawberry recognises the annotation
and injects it, so the schema is unchanged. Keep the parameter immediately after `self` in every
one, so a reader can see at a glance that all five are gated.

Also update the class docstring at `:49`, which currently reads `"""All write access to schema
`console`."""`:

```python
    """All write access to schema `console`, and who may exercise it.

    The role each field needs is in `auth/require.py`'s one table, not in these resolvers.
    """
```

- [x] **Step 6: Gate the OEE mutation**

In `07_uns_graphql/src/uns_graphql/mutations/oee.py`, add the import after `:38`:

```python
from uns_graphql.auth.require import require
from uns_graphql.type.oee import DowntimeEventType
```

and take `info` as the first parameter of `assign_downtime_reason`, calling `require` first:

```python
    async def assign_downtime_reason(
        self,
        info: strawberry.Info,
        event_id: strawberry.ID,
        reason_code: str,
        note: str | None = None,
        assigned_by: Annotated[...] = None,   # unchanged in this task; Task 6 removes it
    ) -> DowntimeEventType:
        require(info, "assignDowntimeReason")
        try:
            numeric_id = int(event_id)
        ...
```

Leave `assigned_by` exactly as it is here. Task 6 removes it, and doing both in one task would
mix a permission change with a schema change in one commit.

- [x] **Step 7: Give the existing mutation tests an identity**

Both mutation test files call `UNSGraphql.schema.execute(...)` with no `context_value`, so their
resolvers now see no identity and every one of them fails. That is the gate working. Each file
gets a context.

In `07_uns_graphql/test/mutations/test_alert_rule.py`, after the `REPOSITORY` constant at `:33`:

```python
from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity

# These tests are about what the mutations do, not about who may call them - that is
# test/auth/test_require.py, one case per cell. So they run as a role that may.
ENGINEER = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000001",
        username="erin.engineer",
        roles=frozenset({"engineer"}),
    )
}
```

Then add `context_value=ENGINEER` to every `schema.execute(...)` call in the file — the ones at
`:99`, `:121`, `:157`, `:172`, `:187`, `:209`, `:222`, `:237`, `:255` and `:277`. For example
`:209` becomes:

```python
        result = await UNSGraphql.schema.execute(
            """mutation { deleteAlertRule(id: "rule-1") }""", context_value=ENGINEER
        )
```

Leave the introspection query in `test_only_alert_rules_are_writable` at `:285` alone: it never
enters a mutation resolver, and giving it a context would suggest it needs one.

In `07_uns_graphql/test/mutations/test_oee.py`, add the same block after `REPOSITORY` at `:34`,
but as an operator — that is the role that reassigns a stop reason in a plant, and using it here
means the test exercises the row's lower bound:

```python
from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity

OPERATOR = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000002",
        username="olga.operator",
        roles=frozenset({"operator"}),
    )
}
```

and add `context_value=OPERATOR` to the executes at `:79`, `:110`, `:127`, `:143`, `:158` and
`:171`. Leave the introspection query at `:186` alone.

- [x] **Step 8: Run the mutation tests**

```bash
cd 07_uns_graphql
uv run pytest test/mutations test/auth -q
```

Expected: PASS. If a test fails with `assignDowntimeReason needs one of these roles`, an
`execute` call was missed — the message names the field, so the failure says which.

- [x] **Step 9: Add the two tests that prove the gate reaches the schema**

The table test uses a fake `info`. One test per file should go through the real schema, because
`strawberry.Info` injection is the part a fake cannot check. Append to
`07_uns_graphql/test/mutations/test_alert_rule.py`:

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_a_viewer_cannot_save_a_rule_and_is_told_which_role_they_need():
    """
    Through the real schema, not a fake info: `strawberry.Info` injection is exactly what a
    fake context cannot prove, and a resolver that stopped receiving it would silently see
    None and refuse everybody.
    """
    viewer = {
        CONTEXT_KEY: Identity(subject="s", username="val.viewer", roles=frozenset({"viewer"}))
    }
    repository = AsyncMock()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            SAVE_MUTATION, variable_values={"rule": MINIMAL_INPUT}, context_value=viewer
        )

    assert result.errors
    assert "engineer" in result.errors[0].message
    # Refused before the database, not after.
    repository.save_rule.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_an_operator_may_mute_a_rule_but_not_rewrite_it():
    """The one row of the table that differs from its neighbours, checked end to end."""
    operator = {
        CONTEXT_KEY: Identity(subject="s", username="olga.operator", roles=frozenset({"operator"}))
    }
    repository = AsyncMock()
    repository.set_enabled.return_value = _rule(enabled=False)

    with patch(REPOSITORY, return_value=repository):
        muted = await UNSGraphql.schema.execute(
            """mutation { setAlertRuleEnabled(id: "rule-1", enabled: false) { id } }""",
            context_value=operator,
        )
        rewritten = await UNSGraphql.schema.execute(
            SAVE_MUTATION, variable_values={"rule": MINIMAL_INPUT}, context_value=operator
        )

    assert muted.errors is None
    assert rewritten.errors
```

`_rule(enabled=False)` uses the helper already at `:53` of that file; check its signature
accepts `enabled` as an override before relying on it, and pass nothing if the default already
has the rule enabled — the assertion is on `errors`, not on the flag.

- [ ] **Step 10: Run everything**

```bash
cd 07_uns_graphql
uv run pytest -q
uv run ruff check src test
```

Expected: green. `ruff` may flag `A002` on the `id` parameters — those already carry `noqa`
comments; keep them on the same line after the signature is reflowed, which is easy to lose
when a parameter list becomes multi-line.

- [ ] **Step 11: Commit**

```bash
cd 07_uns_graphql
git add src/uns_graphql/auth/require.py src/uns_graphql/mutations \
        test/auth/test_require.py test/mutations
git commit -m "feat(graphql): gate the six mutations on realm roles

One table in auth/require.py, tested cell by cell in both directions, because a
role list spread across six resolvers cannot be reviewed. Queries stay open to
any authenticated role: an operator who cannot read the plant cannot work, and
gating reads by Asset would mean inventing an Asset-to-role model that
model.asset does not have.

setAlertRuleEnabled admits operator and the editors do not — muting a nuisance
alarm mid-shift is operator work, authoring the rule that produced it is not.
recordAlertRuleEvaluation is open to any role because the browser-side
evaluator calls it as a consequence of a rule firing, not as a user action.

The error names the roles required and the roles held. 'You need engineer'
sends somebody to ask for a role they may already have."
```

**Definition of done:**
- Every cell of section 7's table has a passing test in both directions — allowed roles
  permitted, every other role refused (spec test 4, success criterion 3).
- `MUTATION_ROLES` has exactly six keys, asserted.
- A refusal names both the roles needed and the roles held, and happens before the repository
  is called.
- A user with no recognised role can read and cannot mutate.
- `uv run pytest -q` green across `07_uns_graphql`.

---

## Task 6: A reassignment signed by whoever was logged in

`mutations/oee.py:63`–`:69` publishes `assignedBy` as an argument whose own description says
"Attested by the caller, not authenticated: this platform has no authentication anywhere." That
sentence stops being true in Task 4. This task makes the field mean what it says.

This is the concrete win of the whole spec: the one write this platform makes to plant data
stops being anonymous. Spec test 5 and success criterion 4.

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/mutations/oee.py:56`–`:88`,
  `09_uns_model/src/uns_model/oee_results.py:251`–`:316`
- Test: `07_uns_graphql/test/mutations/test_oee.py`, `09_uns_model/test/test_oee_results.py`

**Interfaces:**
- Consumes: `require` (Task 5), which returns the `Identity`.
- Produces: a breaking schema change — `assignDowntimeReason` no longer accepts `assignedBy`.
- `OeeResultRepository.assign_reason(event_id, reason_code, *, note=None, assigned_by)` —
  `assigned_by` becomes keyword-only and **required**.

**On the frontend, this should be a no-op — verify that rather than assume it.** The console does
not call `assignDowntimeReason` on `main`, and the console foundation plan adds the call
(`2026-09-02-console-foundation.md`, the OEE client task) but deliberately **never supplies
`assignedBy`**: it declares three variables, reads `assignedBy` in the selection set, and has a
test asserting `$assignedBy` appears nowhere in the document. That was arranged so this task's
schema change costs the console nothing.

Do not take that on trust, because of *how* it would fail if it were wrong. The mutation document
is a template string. A stale `$assignedBy: String` against a schema that no longer has the
argument is a **GraphQL validation error at runtime** — an error array from a request that
compiled cleanly. `npx tsc --noEmit` does not see it, `npm run build` does not see it, and the
foundation plan's own test does not see it either, because it mocks `fetch` and no schema ever
validates the document. Step 7 is the check, and Step 9's by-hand call with a real token is the
only thing in this plan that exercises the document against the actual schema.

- [x] **Step 1: Find the callers before changing the signature**

```bash
cd /c/Dev/manufacturing-uns
grep -rn "assignedBy\|assign_reason\|assignDowntimeReason" \
  --include="*.ts" --include="*.tsx" --include="*.py" \
  11_frontend/src 07_uns_graphql/src 09_uns_model/src
```

Write the list down. Every one of them is edited in this task or the task is not done.

Expect two Python files — `09_uns_model/src/uns_model/oee_results.py` (`:251`, `:274`, `:309`,
`:316`) and `07_uns_graphql/src/uns_graphql/mutations/oee.py`.

Under `11_frontend/src`, expect one of two states, and know which you are in:

| Frontend hits | What it means | Step 7 |
| --- | --- | --- |
| None at all | The console foundation plan has not landed | Confirmation only. Read the foundation plan's OEE client task and check it still declares three variables, because it lands *after* this and would otherwise reintroduce the argument against a schema that no longer has it. |
| `assignedBy` in a selection set, in `DowntimeEvent`, and in a test asserting it is *not* sent | The foundation plan landed as written | Confirmation only. This is the intended state. |
| `$assignedBy`, or `assignedBy:` as a field argument, or an `assignedBy` parameter | Something was added against the plan | A real edit. Step 7 says what to do. |

**And one surface definitely does need editing.** The console surfaces plan's Task 13
(`PLANT ▸ Stops`) builds a `ReassignReasonDialog` with a **`Your name` text input**, passes what
the operator typed as the fourth argument, and labels the result *"a claim, not an authenticated
identity"*. That was the honest design for a console with no identity — a fabricated
`AuthContext` user would have been worse, and that plan has a test asserting the dialog does not
import `useAuth` for exactly that reason.

It is not the honest design any more, and this task is where it changes. Step 7 covers it.

- [x] **Step 2: Write the failing GraphQL test**

In `07_uns_graphql/test/mutations/test_oee.py`, replace the `ASSIGN` document at `:39`–`:45` —
it currently declares `$assignedBy` and passes it — with one that does not:

```python
ASSIGN = """
    mutation Assign($eventId: ID!, $reasonCode: String!, $note: String) {
        assignDowntimeReason(eventId: $eventId, reasonCode: $reasonCode, note: $note) {
            id reasonCode reasonSource isPlanned assignedBy note
        }
    }
"""
```

`assignedBy` stays in the *selection set*: the field is still returned, it is just no longer
supplied. That distinction is the whole task.

Then fix the two tests that pass or assert the old argument. `:74`–`:100` becomes:

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_assign_downtime_reason_records_the_signed_in_user():
    """
    Spec success criterion 4: "a downtime reason reassignment records an identity the caller
    did not choose". The caller cannot supply a name, so the name in the row is the name in
    the token.
    """
    repository = AsyncMock()
    repository.assign_reason.return_value = _assigned(assigned_by="olga.operator")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={
                "eventId": "11",
                "reasonCode": "CHANGEOVER",
                "note": "Product change to MDI-02",
            },
            context_value=OPERATOR,
        )

    assert result.errors is None
    assert result.data["assignDowntimeReason"]["assignedBy"] == "olga.operator"
    repository.assign_reason.assert_awaited_once_with(
        11, "CHANGEOVER", note="Product change to MDI-02", assigned_by="olga.operator"
    )
```

`_assigned()`'s default at `:59` is `"a.operator"`, so pass `assigned_by="olga.operator"` to
match `OPERATOR`'s username from Task 5 — otherwise the test passes while asserting a value the
mutation did not produce.

`:117`–`:133` loses its `assigned_by: None` expectation:

```python
    assert repository.assign_reason.await_args.kwargs == {
        "note": None,
        "assigned_by": "olga.operator",
    }
```

And add the second half of spec test 5:

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_supplying_an_identity_is_a_schema_error():
    """
    Spec test 5: "a request that tries to supply assignedBy fails schema validation because
    the argument no longer exists". A caller who could name themselves could name anybody, and
    the argument's own description used to admit as much.
    """
    result = await UNSGraphql.schema.execute(
        """
        mutation {
            assignDowntimeReason(eventId: "11", reasonCode: "CHANGEOVER",
                                 assignedBy: "somebody.else") { id }
        }
        """,
        context_value=OPERATOR,
    )

    assert result.errors
    assert "assignedBy" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_the_schema_publishes_no_way_to_name_the_assigner():
    result = await UNSGraphql.schema.execute(
        """{ __type(name: "Mutation") { fields { name args { name } } } }"""
    )

    assert result.errors is None
    field = next(
        f for f in result.data["__type"]["fields"] if f["name"] == "assignDowntimeReason"
    )
    assert [arg["name"] for arg in field["args"]] == ["eventId", "reasonCode", "note"]
```

- [x] **Step 3: Run them and watch them fail**

Run: `cd 07_uns_graphql && uv run pytest test/mutations/test_oee.py -q`

Expected: `test_supplying_an_identity_is_a_schema_error` fails because the argument still
exists and the mutation succeeds; `test_the_schema_publishes_no_way_to_name_the_assigner` fails
with a fourth argument in the list.

- [x] **Step 4: Take the identity from the token**

In `07_uns_graphql/src/uns_graphql/mutations/oee.py`, delete the `assigned_by` parameter at
`:61`–`:69` entirely, along with the now-unused `Annotated` import at `:32` if nothing else in
the file uses it. The resolver becomes:

```python
    @strawberry.mutation(
        description="Attribute a stop to a reason code by hand and queue that shift for "
        "recomputation. The stored reason becomes MANUAL, which the engine never overwrites. "
        "The correction is signed by the signed-in user, who cannot choose the name recorded. "
        "Errors when there is no such event or the reason code is not authored."
    )
    async def assign_downtime_reason(
        self,
        info: strawberry.Info,
        event_id: strawberry.ID,
        reason_code: str,
        note: str | None = None,
    ) -> DowntimeEventType:
        identity = require(info, "assignDowntimeReason")

        try:
            numeric_id = int(event_id)
        except (TypeError, ValueError) as ex:
            # Rejected before the database, so a typo does not arrive as a driver error.
            raise ValueError(f"{event_id!r} is not a downtime event id") from ex

        assigned = await _repository().assign_reason(
            numeric_id, reason_code, note=note, assigned_by=identity.username
        )
        if assigned is None:
            # Non-null return type, and the right answer: an operator whose click did
            # nothing has to be told, not handed an empty object.
            raise ValueError(f"There is no downtime event {event_id}")

        LOGGER.info(
            "Downtime event %s attributed to %s by %s", event_id, reason_code, identity.username
        )
        return DowntimeEventType.from_row(assigned)
```

The `or "unknown"` in the log line at `:86` goes with it. There is no unknown assigner any
more, and leaving the fallback in would preserve a case that can no longer happen.

Update the module docstring too. `:18`–`:29` describes the mutation without mentioning who may
call it; add one line after the first paragraph:

```
The correction is signed by the signed-in user. `assignedBy` is taken from the token's
`preferred_username`, not from an argument: a caller who could name themselves could name
anybody, and this is the only write this platform makes to plant data.
```

- [x] **Step 5: Make the repository require an identity**

`09_uns_model/src/uns_model/oee_results.py:251`–`:257` currently defaults `assigned_by` to
`None`. A default of `None` is what let the GraphQL layer pass nothing for as long as it did, so
remove the default and keep it keyword-only:

```python
    async def assign_reason(
        self,
        event_id: int,
        reason_code: str,
        *,
        note: str | None = None,
        assigned_by: str,
    ) -> DowntimeEventRow | None:
```

A keyword-only parameter with no default is legal after one that has a default, so `note` may
keep its own. Then at `:309` and `:316`, delete the `or "unknown"` fallback in the log and the
`requested_by=assigned_by` line needs no change — read both lines and remove only the
defaulting, not the plumbing.

Update the docstring to say the caller is required to supply it and why:

```python
        """...

        `assigned_by` is required. The caller is the only party that knows who is asking, and
        a stored `None` would be an unattributable edit to plant data.
        """
```

- [x] **Step 6: Fix the model tests**

`09_uns_model/test/test_oee_results.py` already passes `assigned_by="a.operator"` at `:380`,
`:400`, `:422` and `:437`, so those keep working. `:147` asserts a row with `"assigned_by":
None`, which is a *stored row* from the engine's own automatic attribution and is unaffected —
read it and confirm it is fixture data rather than a call.

Add one test that pins the new requirement:

```python
@pytest.mark.asyncio
async def test_assign_reason_will_not_record_an_unattributed_correction(database):
    """
    A stored correction with no name is an edit to plant data that nobody signed. The
    signature is now required by the type, so this is a TypeError and not a validation
    message - which is the right place for it, because no caller should be able to try.
    """
    with pytest.raises(TypeError):
        await OeeResultRepository(database).assign_reason(11, "MECH_FAULT")
```

Match the fixture name and marker style of the tests already in that file — `database` above is
a placeholder for whatever the file's existing fixture is called; read `:380` and copy it.

- [x] **Step 7: Confirm the console never names an author, and fix it if it does**

```bash
cd /c/Dev/manufacturing-uns/11_frontend
grep -rn "assignDowntimeReason\|assignedBy" src/
```

Match the output against Step 1's table. In the intended state, every hit is a *read*: the field in
the selection set, the property on `DowntimeEvent`, a display in the stops table, and the
foundation plan's test asserting `$assignedBy` is absent. Nothing declares a variable and nothing
passes an argument. If that is what you see, this step is done — go to Step 8.

If a `$assignedBy` declaration, an `assignedBy:` field argument, or an `assignedBy` parameter has
appeared, fix all three places:

**`src/services/graphql/queries.ts`** — delete `$assignedBy: String` from the operation's variable
declarations and `assignedBy: $assignedBy` from the field's arguments:

```graphql
mutation AssignDowntimeReason($eventId: ID!, $reasonCode: String!, $note: String) {
  assignDowntimeReason(eventId: $eventId, reasonCode: $reasonCode, note: $note) {
    id reasonCode reasonSource isPlanned assignedBy assignedAt note
  }
}
```

**Keep `assignedBy` in the selection set.** That is the point of the whole task: the console still
shows who made a correction, and now it shows a name the server established rather than one the
browser supplied. Deleting it from the selection set would throw away the field this task made
trustworthy.

**`src/services/graphql/client.ts`** — drop the fourth parameter and the variable:

```ts
  public async assignDowntimeReason(
    eventId: string,
    reasonCode: string,
    note?: string,
  ): Promise<DowntimeEvent> {
    const res = await this.executeQuery<{ assignDowntimeReason: DowntimeEvent }>(
      ASSIGN_DOWNTIME_REASON_MUTATION,
      { eventId, reasonCode, note },
    )
```

**`src/services/graphql/client-oee.test.ts`** — the foundation plan's test calls this with
`'shift.lead'` as a fourth argument and asserts it in the variables. Drop the argument, and change
the assertion from "the caller's name was sent" to its opposite:

```ts
  it('does not send an author — the server takes it from the token', () => {
    // The whole point of removing the argument. A console that could name the author could
    // name anybody, and the field is a record of who corrected a plant number.
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.body as string).variables).not.toHaveProperty('assignedBy')
  })
```

Keep the assertion that the *returned* `assignedBy` is read and surfaced — the response still
carries it.

**`src/components/plant/ReassignReasonDialog.tsx`** (or wherever surfaces Task 13 put it) — this
is the substantive edit, and it is a deletion plus an inversion.

Delete the `Your name` field, its `attestedBy` state, and the fourth argument to
`assignDowntimeReason`. Then delete the sentence saying nothing verifies the name, and replace it
with one that says what is now true:

```tsx
        <p className="text-[11px] text-[#94A3B8]">
          This correction will be recorded against <span className="font-mono">{session?.username}</span>,
          and the shift will be recomputed. A reason's planned flag moves the interval between
          Unplanned Down and excluded time, so the OEE can change.
        </p>
```

The dialog now *does* read `useAuth`, so surfaces Task 13's test asserting it does not — the one
reading its own source with `?raw` and expecting no match for `/useAuth|AuthContext/` — has to be
inverted rather than deleted. Its reasoning is worth preserving in the new form:

```tsx
  it('does not send a name, and says whose the record will carry', async () => {
    // The old version of this test asserted the dialog never touched AuthContext, because the
    // signed-in user was fabricated in the browser and sending it would have put an
    // unattested name into plant data. Now the name comes from a validated token and the
    // console cannot choose it at all — so reading it to *display* it is correct, and sending
    // it is impossible.
    render(<ReassignReasonDialog event={EVENT} onCancel={vi.fn()} onAssigned={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText(/reason/i), 'BREAKDOWN');
    await userEvent.click(screen.getByRole('button', { name: /reassign and recompute/i }));

    await waitFor(() => expect(assignDowntimeReason).toHaveBeenCalledWith('11', 'BREAKDOWN', undefined));
    expect(screen.queryByLabelText(/your name/i)).toBeNull();
  });
```

Two more in Task 13's suite change with it: the one typing `'shift.lead'` into `/your name/i`
loses that line and its fourth expected argument, and the one asserting `/nothing verifies it/i`
now asserts the opposite. And the stops-table tooltip at Task 13's `StatusPill` — *"Attested by
… — a claim, not an authenticated identity"* — becomes:

```tsx
title={`Corrected by ${e.assignedBy ?? 'an unrecorded user'} at ${e.assignedAt ?? 'an unrecorded time'}`}
```

`?? 'an unrecorded user'` stays, and it is not dead: rows written before this change have a null
or self-attested `assigned_by`, and the history is not rewritten. Do not backfill it.

Then fix each caller `tsc` names. A call with four arguments is a type error and will be found; a
`variables` object built by hand will not be.

```bash
npx tsc --noEmit
npx vitest run
```

Expected: green. Be clear about what that does and does not prove. A stale parameter in a *method
signature* is a type error, so `tsc` catches it. A stale `assignedBy:` in a variables object
handed to a template-string document is not — it reaches the server and comes back as a GraphQL
validation error at runtime, and the mocked test suite never validates a document against a
schema. Step 9's by-hand check with a real token is the only thing in this plan that would catch
that, which is why it is not optional either.

- [ ] **Step 8: Run both module suites**

```bash
cd 07_uns_graphql && uv run pytest -q
cd ../09_uns_model && uv run pytest -q
```

Expected: green in both.

- [ ] **Step 9: Check it by hand**

There is no console screen for this yet, so the check goes through the API with a real token.
Take `$TOKEN` from a signed-in browser session's devtools (Task 4 Step 8 explains why the
password grant is not available), pick an event id out of `oee.downtime_event`, and post:

```bash
curl -s -X POST http://localhost:8088/graphql \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"query":"mutation { assignDowntimeReason(eventId: \"11\", reasonCode: \"MECH_FAULT\") { id assignedBy } }"}'
```

Then read the row back:

```sql
SELECT id, reason_code, reason_source, assigned_by, assigned_at
FROM oee.downtime_event ORDER BY assigned_at DESC NULLS LAST LIMIT 3;
```

Expected: `assigned_by` holds the `preferred_username` of whoever the token belongs to — a name
the caller never sent. Then try it again with `assignedBy: "somebody.else"` added and confirm
the server refuses the document rather than honouring it.

- [ ] **Step 10: Commit**

```bash
cd /c/Dev/manufacturing-uns
git add 07_uns_graphql/src/uns_graphql/mutations/oee.py 07_uns_graphql/test/mutations/test_oee.py \
        09_uns_model/src/uns_model/oee_results.py 09_uns_model/test/test_oee_results.py
# Add 11_frontend/src/services/graphql/ only if Step 7 found something to fix. In the intended
# state the console already never sent a name, so there is nothing to stage there.
git commit -m "feat(oee): sign a reason reassignment with the token, not an argument

assignedBy came from an argument whose own description admitted it was
'attested by the caller, not authenticated'. A caller who can name themselves
can name anybody. It now comes from the token's preferred_username and the
argument is gone from the schema, so a request that tries to supply it fails
validation.

assign_reason's assigned_by loses its None default and becomes required: that
default is what let an unattributable edit to plant data be possible for as
long as it was.

This is the one write this platform makes to plant data. It is no longer
anonymous."
```

**Definition of done:**
- `assignDowntimeReason` publishes exactly `eventId`, `reasonCode` and `note` — asserted by
  introspection.
- A request supplying `assignedBy` fails schema validation (spec test 5).
- The stored `assigned_by` is the token's `preferred_username` (success criterion 4).
- `OeeResultRepository.assign_reason` refuses to be called without an assigner.
- `grep -rn "assignedBy" 11_frontend/src` shows only selection-set reads and response-shape
  types — no `$assignedBy` declaration, no `assignedBy:` argument, no `assignedBy` parameter.
- `npx tsc --noEmit` and `npx vitest run` green in `11_frontend`.
- `uv run pytest -q` green in both `07_uns_graphql` and `09_uns_model`.

---

## Task 7: The OIDC client, in two small modules with no React in them

Everything the console needs to talk to the realm, kept out of React so it can be tested
without rendering anything: one module that owns the redirect flow and the in-memory token,
and one that turns realm roles into the console's five.

Two facts shape this task, and both come from decisions already made:

- **Tokens live in memory.** `localStorage` is where the current design's fake identity lives
  (spec section 6), and an access token in `localStorage` survives the tab and is readable by
  any script on the origin. The PKCE `code_verifier` is a different thing and does go in
  `sessionStorage` — it is single-use, useless without the matching authorization code, and it
  has to survive one full-page navigation or the flow cannot complete.
- **Silent renew works here because Task 1 put the realm on the console's own origin.**
  Keycloak's SSO cookie is therefore a first-party cookie, so the hidden-iframe renew is not
  fighting third-party cookie policy. Had Keycloak kept its own port, this would be the part
  that broke first.

**Files:**
- Create: `11_frontend/src/lib/auth/oidc.ts`, `11_frontend/src/lib/auth/roles.ts`
- Modify: `11_frontend/package.json`, `11_frontend/src/lib/alarms/map-alert-rules.ts:46`–`:56`
- Test: `11_frontend/src/lib/auth/oidc.test.ts`, `11_frontend/src/lib/auth/roles.test.ts`
  (both create)

**Interfaces:**
- Consumes: `platformConfig.authIssuer` and `.authClientId` (Task 2); `UserRole` and
  `ROLE_CONFIGS` from `src/types/rbac.ts`.
- Produces:
  ```ts
  // src/lib/auth/roles.ts
  export const CONSOLE_ROLES: readonly UserRole[]           // the five, lowercase
  export function toUserRole(role: string | null | undefined): UserRole | undefined
  export function rolesFromClaims(claims: unknown): UserRole[]   // realm_access.roles, filtered
  export function featureAllowed(roles: UserRole[], feature: FeatureKey): boolean

  // src/lib/auth/oidc.ts
  export interface Session { subject: string; username: string; email?: string;
                             displayName: string; roles: UserRole[] }
  export interface AuthClient {
    completeRedirect(): Promise<Session | null>   // returns null when this load is not a callback
    restore(): Promise<Session | null>            // silent renew against the realm SSO cookie
    signIn(): Promise<void>                       // redirects; never resolves normally
    signOut(): Promise<void>
    accessToken(): string | null
    refresh(): Promise<string | null>
    onSession(listener: (session: Session | null) => void): () => void
  }
  export function createAuthClient(overrides?: Partial<AuthSettings>): AuthClient
  export const authClient: AuthClient                        // the app's one instance
  ```
- Task 8 consumes `authClient` and `Session`. Task 9 consumes `accessToken` and `refresh`.
  Task 10 consumes `featureAllowed`.

- [x] **Step 1: Add the dependency and confirm what it exports**

```bash
cd 11_frontend
npm install oidc-client-ts@^3
node -e "const o=require('oidc-client-ts'); console.log(['UserManager','WebStorageStateStore','InMemoryWebStorage','User'].map(k=>k+'='+(k in o)).join(' '))"
```

Expected: all four `true`. `InMemoryWebStorage` is the one this task depends on and the one
worth checking rather than assuming — it is what keeps the token out of any storage the browser
persists. If it is absent in the installed version, pin the version that has it before writing
anything; do not substitute `sessionStorage` for the user store, because that defeats spec test
12's intent even though it would pass a `localStorage`-only assertion.

`oidc-client-ts` is chosen over `react-oidc-context` deliberately: the React binding would
duplicate `AuthContext`, which Task 8 keeps because a dozen components consume its shape.

- [x] **Step 2: Write the failing roles test**

Create `11_frontend/src/lib/auth/roles.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { CONSOLE_ROLES, featureAllowed, rolesFromClaims, toUserRole } from './roles';

describe('toUserRole', () => {
  it('accepts the five the platform knows', () => {
    expect(CONSOLE_ROLES.map(toUserRole)).toEqual([...CONSOLE_ROLES]);
  });

  it('is case-insensitive, because the GraphQL enum is upper case', () => {
    expect(toUserRole('ENGINEER')).toBe('engineer');
  });

  it('drops anything unrecognised rather than guessing', () => {
    // The precedent is map-alert-rules.ts: "notifying the wrong role is worse than
    // notifying nobody". The same reasoning applies to granting the wrong one.
    expect(toUserRole('offline_access')).toBeUndefined();
    expect(toUserRole('default-roles-uns')).toBeUndefined();
    expect(toUserRole('')).toBeUndefined();
    expect(toUserRole(null)).toBeUndefined();
  });
});

describe('rolesFromClaims', () => {
  it('reads Keycloak realm roles', () => {
    expect(rolesFromClaims({ realm_access: { roles: ['engineer', 'viewer'] } }))
      .toEqual(['engineer', 'viewer']);
  });

  it('drops the roles Keycloak gives everybody', () => {
    const roles = rolesFromClaims({
      realm_access: { roles: ['offline_access', 'uma_authorization', 'default-roles-uns', 'operator'] },
    });
    expect(roles).toEqual(['operator']);
  });

  it('is empty rather than throwing when the claim is missing or misshapen', () => {
    // A console that crashed on an unexpected token would be indistinguishable from an
    // outage, and this runs before anything is rendered.
    expect(rolesFromClaims({})).toEqual([]);
    expect(rolesFromClaims(null)).toEqual([]);
    expect(rolesFromClaims({ realm_access: 'engineer' })).toEqual([]);
    expect(rolesFromClaims({ realm_access: { roles: 'engineer' } })).toEqual([]);
  });

  it('deduplicates and keeps a stable order', () => {
    expect(rolesFromClaims({ realm_access: { roles: ['viewer', 'admin', 'viewer'] } }))
      .toEqual(['admin', 'viewer']);
  });
});

describe('featureAllowed', () => {
  it('reads the role profiles already in rbac.ts rather than inventing a second table', () => {
    // rbac.ts:139 and :288.
    expect(featureAllowed(['admin'], 'user_management')).toBe(true);
    expect(featureAllowed(['viewer'], 'user_management')).toBe(false);
  });

  it('grants a feature any one of the held roles grants', () => {
    // viewer.historian is false and engineer.historian is true (rbac.ts:293, :156), so this
    // fails if the implementation intersects the roles instead of unioning them.
    expect(featureAllowed(['viewer', 'engineer'], 'historian')).toBe(true);
    expect(featureAllowed(['viewer'], 'historian')).toBe(false);
  });

  it('grants nothing to a user with no recognised role', () => {
    expect(featureAllowed([], 'uns_tree')).toBe(false);
  });
});
```

`CONSOLE_ROLES.map(toUserRole)` rather than a literal list: it asserts the exported list and the
function agree, which is the pair that goes wrong.

The `featureAllowed(['viewer','engineer'], 'settings_edit')` assertion compares against
`featureAllowed(['engineer'], ...)` rather than a hard-coded `true`. Read
`types/rbac.ts:122`–`:240` and use a feature whose engineer default is genuinely `true`; if
`settings_edit` is not one, pick one that is. Asserting a value copied out of `ROLE_CONFIGS`
would just restate the table.

- [x] **Step 3: Write `roles.ts`**

Create `11_frontend/src/lib/auth/roles.ts`:

```ts
/**
 * Realm roles to console roles.
 *
 * The realm is the authority on who holds what. This module only translates, and drops what
 * it does not recognise — Keycloak issues `offline_access`, `uma_authorization` and
 * `default-roles-<realm>` to every user, and none of them mean anything here.
 */

import { FeatureKey, ROLE_CONFIGS, UserRole } from '../../types/rbac';

export const CONSOLE_ROLES: readonly UserRole[] = [
  'admin',
  'engineer',
  'operator',
  'auditor',
  'viewer',
];

const KNOWN = new Set<string>(CONSOLE_ROLES);

/**
 * The console's role names are lower case, the GraphQL enum members are not.
 * Anything unrecognised is dropped rather than guessed.
 */
export function toUserRole(role: string | null | undefined): UserRole | undefined {
  const candidate = String(role ?? '').toLowerCase();
  return KNOWN.has(candidate) ? (candidate as UserRole) : undefined;
}

/** The realm roles in an access token, filtered to the five and ordered as CONSOLE_ROLES is. */
export function rolesFromClaims(claims: unknown): UserRole[] {
  const realmAccess = (claims as { realm_access?: unknown } | null)?.realm_access;
  const granted = (realmAccess as { roles?: unknown } | undefined)?.roles;
  if (!Array.isArray(granted)) {
    // A misshapen token is not a crash. This runs before the first render.
    return [];
  }
  const held = new Set(granted.map(toUserRole).filter((r): r is UserRole => r !== undefined));
  // Ordered by CONSOLE_ROLES so that two tokens with the same roles produce the same array,
  // which is what lets React skip a re-render and a test assert without sorting.
  return CONSOLE_ROLES.filter((role) => held.has(role));
}

/**
 * Whether any held role's profile grants this feature.
 *
 * The profiles are `ROLE_CONFIGS[role].defaultPermissions`, which already exists and is
 * already what the UI was built around. A second table would be a second thing to keep in
 * step. Note what this is not: it decides which controls the console offers, and
 * `07_uns_graphql/src/uns_graphql/auth/require.py` decides what the server accepts.
 */
export function featureAllowed(roles: UserRole[], feature: FeatureKey): boolean {
  return roles.some((role) => ROLE_CONFIGS[role]?.defaultPermissions?.[feature] === true);
}
```

- [x] **Step 4: Retire the duplicate role set in the alarms mapper**

`src/lib/alarms/map-alert-rules.ts:46` declares its own `ROLES` set and `:52`–`:56` its own
private `toUserRole`, with the comment this module's docstring now quotes. Delete both and
import instead:

```ts
import { toUserRole } from '../auth/roles'
```

Leave `toConsoleRole` at `:58` where it is — it is about the GraphQL enum's casing, not about
identity, and moving it would put an alarms concern in an auth module.

```bash
cd 11_frontend && npx vitest run src/lib/alarms && npx tsc --noEmit
```

Expected: the existing alarms tests still pass. If `map-alert-rules.ts` has no test yet, the
surfaces plan adds one; either way `tsc` catches the import.

- [x] **Step 5: Write the failing oidc test**

Create `11_frontend/src/lib/auth/oidc.test.ts`. It drives the module through a fake
`UserManager`, because the real one navigates the browser:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createAuthClient } from './oidc';

/** A minimal stand-in for oidc-client-ts's UserManager. */
function fakeManager(overrides: Record<string, unknown> = {}) {
  return {
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signinCallback: vi.fn().mockResolvedValue(null),
    signinSilent: vi.fn().mockResolvedValue(null),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    getUser: vi.fn().mockResolvedValue(null),
    removeUser: vi.fn().mockResolvedValue(undefined),
    events: { addUserLoaded: vi.fn(), addUserUnloaded: vi.fn(), addAccessTokenExpired: vi.fn() },
    ...overrides,
  };
}

const TOKEN_USER = {
  access_token: 'header.payload.signature',
  profile: {
    sub: '11111111-2222-3333-4444-555555555555',
    preferred_username: 'olga.operator',
    email: 'olga.operator@example.test',
    name: 'Olga Operator',
    realm_access: { roles: ['operator', 'offline_access'] },
  },
};

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

describe('completeRedirect', () => {
  it('does nothing when this page load is not a callback', async () => {
    const manager = fakeManager();
    const client = createAuthClient({ manager } as never);

    expect(await client.completeRedirect()).toBeNull();
    // Calling signinCallback on an ordinary load throws inside oidc-client-ts and would
    // surface as a broken app on every refresh.
    expect(manager.signinCallback).not.toHaveBeenCalled();
  });

  it('completes the flow when the realm has redirected back with a code', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);

    const session = await client.completeRedirect();

    expect(session).toMatchObject({ username: 'olga.operator', roles: ['operator'] });
    expect(client.accessToken()).toBe('header.payload.signature');
  });

  it('scrubs the code and state out of the address bar', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);

    await client.completeRedirect();

    // An authorization code left in the URL gets copied into chat messages and bookmarks.
    expect(window.location.search).toBe('');
  });

  it('keeps the hash route, because this app uses HashRouter', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz#/alarms');
    const client = createAuthClient({ manager } as never);

    await client.completeRedirect();

    expect(window.location.hash).toBe('#/alarms');
  });
});

describe('restore', () => {
  it('returns the session when the realm still has one', async () => {
    const manager = fakeManager({ signinSilent: vi.fn().mockResolvedValue(TOKEN_USER) });
    const client = createAuthClient({ manager } as never);

    expect(await client.restore()).toMatchObject({ username: 'olga.operator' });
  });

  it('returns null when the realm has no session, and does not redirect on its own', async () => {
    const manager = fakeManager({ signinSilent: vi.fn().mockRejectedValue(new Error('login_required')) });
    const client = createAuthClient({ manager } as never);

    expect(await client.restore()).toBeNull();
    // A module that redirected here would make the landing page unreachable for anybody who
    // is not signed in.
    expect(manager.signinRedirect).not.toHaveBeenCalled();
  });
});

describe('the token', () => {
  it('is never written to localStorage or sessionStorage', async () => {
    // Spec test 12. Asserted against the token string itself rather than a key name, so a
    // future change of storage key cannot make this pass while leaking.
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);

    await client.completeRedirect();

    const dump = (storage: Storage) =>
      Object.keys(storage).map((k) => storage.getItem(k) ?? '').join('|');
    expect(dump(window.localStorage)).not.toContain('header.payload.signature');
    expect(dump(window.sessionStorage)).not.toContain('header.payload.signature');
  });

  it('is null before sign-in', () => {
    expect(createAuthClient({ manager: fakeManager() } as never).accessToken()).toBeNull();
  });

  it('is refreshed by a silent renew, and refresh reports failure rather than throwing', async () => {
    const renewed = { ...TOKEN_USER, access_token: 'renewed.token.value' };
    const manager = fakeManager({ signinSilent: vi.fn().mockResolvedValue(renewed) });
    const client = createAuthClient({ manager } as never);

    expect(await client.refresh()).toBe('renewed.token.value');
    expect(client.accessToken()).toBe('renewed.token.value');

    manager.signinSilent.mockRejectedValue(new Error('login_required'));
    expect(await client.refresh()).toBeNull();
  });
});

describe('signOut', () => {
  it('drops the in-memory token before leaving for the realm', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);
    await client.completeRedirect();

    await client.signOut();

    expect(client.accessToken()).toBeNull();
    expect(manager.signoutRedirect).toHaveBeenCalled();
  });
});

describe('onSession', () => {
  it('notifies listeners and can be unsubscribed', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);
    const seen: unknown[] = [];
    const stop = client.onSession((s) => seen.push(s));

    await client.completeRedirect();
    stop();
    await client.signOut();

    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ username: 'olga.operator' });
  });
});
```

- [x] **Step 6: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/lib/auth`

Expected: `roles.test.ts` passes from Step 3; `oidc.test.ts` fails to resolve `./oidc`.

- [x] **Step 7: Write `oidc.ts`**

Create `11_frontend/src/lib/auth/oidc.ts`:

```ts
/**
 * The console's side of Authorization Code + PKCE.
 *
 * No React here on purpose: this is testable without rendering, and Task 8's AuthContext
 * becomes a thin wrapper whose own tests can stub it.
 *
 * Where things are kept, and why:
 * - The access token is in a module-local variable. It is never in localStorage or
 *   sessionStorage; persisting identity in localStorage is what made the previous design
 *   fake, and a token there is readable by any script on the origin.
 * - The PKCE `code_verifier` and the `state` do go in sessionStorage, because they must
 *   survive a full-page navigation to the realm and back. They are single-use and worthless
 *   without the matching authorization code.
 * - A page refresh therefore has no token. `restore()` gets one back through a hidden-iframe
 *   silent renew, which works because Task 1 serves the realm from the console's own origin,
 *   making Keycloak's SSO cookie a first-party cookie.
 */

import {
  InMemoryWebStorage,
  User,
  UserManager,
  WebStorageStateStore,
} from 'oidc-client-ts';

import { platformConfig } from '../platform/config';
import { rolesFromClaims } from './roles';
import type { UserRole } from '../../types/rbac';

export interface Session {
  subject: string;
  username: string;
  email?: string;
  displayName: string;
  roles: UserRole[];
}

export interface AuthClient {
  completeRedirect(): Promise<Session | null>;
  restore(): Promise<Session | null>;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
  accessToken(): string | null;
  refresh(): Promise<string | null>;
  onSession(listener: (session: Session | null) => void): () => void;
}

export interface AuthSettings {
  /** Injected by the tests. Production passes nothing and gets a real UserManager. */
  manager: UserManager;
}

function buildManager(): UserManager {
  return new UserManager({
    authority: platformConfig.authIssuer,
    client_id: platformConfig.authClientId,
    // The realm lists http://localhost:8088/* and :5173/*, so the origin is enough. A path
    // would have to be kept in step with the realm export in two repositories' worth of
    // places.
    redirect_uri: `${window.location.origin}/`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: 'code',
    scope: 'openid profile email',
    // In memory, not sessionStorage: see the module comment.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    // The code_verifier, which must survive the navigation. Not a token.
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
    // The console shows plant data that moves; an expiring token mid-shift must not surface
    // as an empty table.
    accessTokenExpiringNotificationTimeInSeconds: 60,
    monitorSession: false,
  });
}

function toSession(user: User | null | undefined): Session | null {
  if (!user?.access_token) {
    return null;
  }
  const profile = user.profile as Record<string, unknown>;
  const username = String(profile.preferred_username ?? profile.sub ?? '');
  return {
    subject: String(profile.sub ?? ''),
    username,
    email: typeof profile.email === 'string' ? profile.email : undefined,
    // What the header shows. Falls back to the username rather than to an empty chip.
    displayName: typeof profile.name === 'string' && profile.name ? profile.name : username,
    roles: rolesFromClaims(profile),
  };
}

function isRedirectCallback(): boolean {
  const params = new URLSearchParams(window.location.search);
  // Both, not either: `state` alone is an ordinary query parameter somebody might use, and
  // calling signinCallback outside a real callback throws.
  return params.has('code') && params.has('state');
}

export function createAuthClient(overrides?: Partial<AuthSettings>): AuthClient {
  const manager = overrides?.manager ?? buildManager();
  let token: string | null = null;
  const listeners = new Set<(session: Session | null) => void>();

  const publish = (session: Session | null) => {
    listeners.forEach((listener) => listener(session));
  };

  const adopt = (user: User | null | undefined): Session | null => {
    const session = toSession(user);
    token = session ? (user as User).access_token : null;
    return session;
  };

  // A renew that happens on its own timer still has to update the token this module hands out.
  manager.events?.addUserLoaded?.((user: User) => {
    const session = adopt(user);
    if (session) {
      publish(session);
    }
  });

  return {
    async completeRedirect() {
      if (!isRedirectCallback()) {
        return null;
      }
      const user = await manager.signinCallback();
      const session = adopt(user as User | null);
      // An authorization code left in the address bar gets pasted into chat messages and
      // saved into bookmarks. The hash is the app's route and stays.
      window.history.replaceState({}, '', `${window.location.pathname}${window.location.hash}`);
      if (session) {
        publish(session);
      }
      return session;
    },

    async restore() {
      try {
        const user = await manager.signinSilent();
        const session = adopt(user as User | null);
        if (session) {
          publish(session);
        }
        return session;
      } catch {
        // No realm session. Not an error: this is what an anonymous visitor looks like, and
        // redirecting from here would make the landing page unreachable.
        return null;
      }
    },

    async signIn() {
      await manager.signinRedirect();
    },

    async signOut() {
      token = null;
      publish(null);
      await manager.removeUser();
      await manager.signoutRedirect();
    },

    accessToken() {
      return token;
    },

    async refresh() {
      try {
        const user = await manager.signinSilent();
        const session = adopt(user as User | null);
        if (session) {
          publish(session);
        }
        return token;
      } catch {
        return null;
      }
    },

    onSession(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** The app's one client. Task 9's GraphQL client reads its token from here. */
export const authClient: AuthClient = createAuthClient();
```

Two things the tests pin. `signOut` clears `token` and publishes *before* awaiting the redirect,
so a slow network cannot leave a signed-out console holding a usable token. And
`completeRedirect` returns `null` without calling `signinCallback` on an ordinary load —
`oidc-client-ts` throws when there is no state to match, which would otherwise break every page
refresh.

- [x] **Step 8: Run the tests**

```bash
cd 11_frontend
npx vitest run src/lib/auth
npx tsc --noEmit
```

Expected: PASS. If `createAuthClient({ manager } as never)` fails to type-check without the
cast, keep the cast in the test rather than widening `AuthSettings` — the fake is deliberately
partial and admitting that in one place is better than typing production code around a stub.

Note that `authClient` is constructed at module scope, so importing this module in a test
constructs a real `UserManager`. That is why the tests import `createAuthClient` and never
`authClient`. If `buildManager()` throws in jsdom for want of something, make the export lazy
(`let instance; export function getAuthClient()`) rather than dropping the test's isolation.

- [ ] **Step 9: Commit**

```bash
cd 11_frontend
git add package.json package-lock.json src/lib/auth src/lib/alarms/map-alert-rules.ts
git commit -m "feat(console): PKCE against the realm, with the token in memory only

Two modules with no React in them, so both are testable without rendering.
The access token lives in a module variable and is asserted absent from both
localStorage and sessionStorage by its own value, not by key name. The PKCE
code_verifier does go in sessionStorage: it must survive the navigation to the
realm, and it is worthless without the matching code.

A refresh therefore has no token, and restore() gets one back through a silent
renew — which works because the realm is served from the console's own origin,
so Keycloak's SSO cookie is first-party.

roles.ts drops any realm role outside the five, and map-alert-rules.ts now
imports that instead of keeping its own copy of the same set."
```

**Definition of done:**
- `npx vitest run src/lib/auth` green.
- The access token string appears in neither `localStorage` nor `sessionStorage` (spec test 12).
- `completeRedirect()` on an ordinary page load does nothing and does not throw.
- The authorization code is removed from the address bar and the hash route survives.
- `rolesFromClaims` drops `offline_access`, `uma_authorization` and `default-roles-uns`.
- `map-alert-rules.ts` has no second copy of the role set; `npx tsc --noEmit` green.

---

## Task 8: `AuthContext`, backed by the realm instead of `localStorage`

The provider keeps the shape its consumers use — spec section 6: *"`AuthContext` keeps its
public shape … so the components consuming it do not all change at once"* — and everything
behind it is replaced.

**Read the surfaces plan's Task 21 before starting.** It deletes `auditLogs`,
`createUser`, `updateUser`, `deleteUser`, `toggleUserFeaturePermission`,
`resetUserToRoleDefaults` and `restoreDefaults`, together with both user modals. This task
starts from that reduced file. If Task 21 has not landed (see the Pre-flight section — as of
2026-09-03 it had not), the deletion is this task's first move instead: the modals and the
seven methods go here rather than being wrapped, and the surfaces plan's Task 21 becomes a
no-op when it lands. The one ordering that is wrong is doing neither — an OIDC provider around
seven methods that are about to be deleted.

What is left after Task 21, from `AuthContext.tsx:117`–`:135`: `currentUser`, `users`,
`isAdmin`, `isAuthenticated`, `login`, `logout`, `switchUser`, `hasPermission`,
`getUserPermission`, `canAccessTab`.

Of those, exactly two cannot survive a real identity provider:

- **`switchUser`** — pretending to be somebody else is the defining feature of a fake login. Its
  one caller is `common/UserSessionMenu.tsx`. It goes, and so does the `Simulate` control in
  `UserManagementView.tsx:428`–`:434`.
- **`login`'s signature** — `(identifier, password?) => boolean` becomes `() => void`, a
  redirect. Spec section 6: *"`login` becomes a redirect to the realm, not a function returning
  `boolean`."*

**Files:**
- Modify: `11_frontend/src/context/AuthContext.tsx` (rewritten body),
  `11_frontend/src/components/auth/LoginView.tsx`,
  `11_frontend/src/components/common/UserSessionMenu.tsx`,
  `11_frontend/src/components/users/UserManagementView.tsx:428`–`:434`
- Test: `11_frontend/src/context/AuthContext.test.tsx`,
  `11_frontend/src/components/auth/LoginView.test.tsx` (both create)

**Interfaces:**
- Consumes: `authClient`, `Session` (Task 7); `featureAllowed` (Task 7).
- Produces: `useAuth()` returning
  ```ts
  {
    session: Session | null
    currentUser: UserAccount | null      // derived from the session, for the existing chrome
    isAuthenticated: boolean
    isAdmin: boolean
    isReady: boolean                     // false until the first restore() settles
    roles: UserRole[]
    login: () => void                    // redirects to the realm
    logout: () => void
    hasPermission: (feature: FeatureKey) => boolean
    canAccessTab: (tab: string) => { allowed: boolean; requiredFeature: FeatureKey; featureName: string }
  }
  ```
  `users` and `getUserPermission` move to Task 10, which sources them from the realm.
  **`currentUser` becomes nullable** — that is the one breaking change for consumers, and Step 7
  fixes every site the compiler names.
- Task 10 consumes `roles` and `hasPermission`. Task 11 consumes `isAuthenticated`.

- [ ] **Step 1: Write the failing provider test**

Create `11_frontend/src/context/AuthContext.test.tsx`:

```tsx
import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const client = {
  completeRedirect: vi.fn().mockResolvedValue(null),
  restore: vi.fn().mockResolvedValue(null),
  signIn: vi.fn().mockResolvedValue(undefined),
  signOut: vi.fn().mockResolvedValue(undefined),
  accessToken: vi.fn().mockReturnValue(null),
  refresh: vi.fn().mockResolvedValue(null),
  onSession: vi.fn().mockReturnValue(() => {}),
};

vi.mock('../lib/auth/oidc', () => ({ authClient: client }));

import { AuthProvider, useAuth } from './AuthContext';

const SESSION = {
  subject: 'sub-1',
  username: 'olga.operator',
  email: 'olga.operator@example.test',
  displayName: 'Olga Operator',
  roles: ['operator'] as const,
};

const Probe = () => {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="ready">{String(auth.isReady)}</span>
      <span data-testid="authenticated">{String(auth.isAuthenticated)}</span>
      <span data-testid="name">{auth.currentUser?.name ?? 'nobody'}</span>
      <span data-testid="roles">{auth.roles.join(',')}</span>
      <span data-testid="alarms">{String(auth.hasPermission('alarms'))}</span>
      <button onClick={auth.login}>sign in</button>
      <button onClick={auth.logout}>sign out</button>
    </div>
  );
};

const renderProbe = () => render(<AuthProvider><Probe /></AuthProvider>);

beforeEach(() => {
  vi.clearAllMocks();
  client.completeRedirect.mockResolvedValue(null);
  client.restore.mockResolvedValue(null);
  client.onSession.mockReturnValue(() => {});
  window.localStorage.clear();
});

describe('before the first restore settles', () => {
  it('is not ready and not authenticated', async () => {
    client.restore.mockReturnValue(new Promise(() => {}));   // never settles
    renderProbe();

    expect(screen.getByTestId('ready').textContent).toBe('false');
    expect(screen.getByTestId('authenticated').textContent).toBe('false');
  });

  it('does not report an unauthenticated user until it knows', async () => {
    // A router that redirected to /login on first paint would bounce a signed-in user out of
    // a deep link every time they refreshed.
    client.restore.mockReturnValue(new Promise(() => {}));
    renderProbe();

    expect(screen.getByTestId('name').textContent).toBe('nobody');
    expect(screen.getByTestId('ready').textContent).toBe('false');
  });
});

describe('a restored session', () => {
  it('becomes the current user with the realm roles', async () => {
    client.restore.mockResolvedValue(SESSION);
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('authenticated').textContent).toBe('true');
    expect(screen.getByTestId('name').textContent).toBe('Olga Operator');
    expect(screen.getByTestId('roles').textContent).toBe('operator');
  });

  it('resolves permissions from the role, not from a stored matrix', async () => {
    client.restore.mockResolvedValue({ ...SESSION, roles: ['viewer'] });
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    // rbac.ts's viewer profile, whatever it says. Read types/rbac.ts and assert its value.
    expect(screen.getByTestId('alarms').textContent).toBe('false');
  });
});

describe('the redirect back from the realm', () => {
  it('is completed before a silent restore is attempted', async () => {
    const order: string[] = [];
    client.completeRedirect.mockImplementation(async () => { order.push('callback'); return SESSION; });
    client.restore.mockImplementation(async () => { order.push('restore'); return null; });
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    // Restoring first would race the callback and could discard the session just granted.
    expect(order[0]).toBe('callback');
    expect(screen.getByTestId('authenticated').textContent).toBe('true');
  });

  it('skips the silent restore entirely when the callback produced a session', async () => {
    client.completeRedirect.mockResolvedValue(SESSION);
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(client.restore).not.toHaveBeenCalled();
  });
});

describe('login', () => {
  it('redirects to the realm and takes no password', async () => {
    // Spec test 8, and success criterion 1: "No password reaches the console."
    client.restore.mockResolvedValue(null);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => { screen.getByText('sign in').click(); });

    expect(client.signIn).toHaveBeenCalledTimes(1);
    expect(client.signIn).toHaveBeenCalledWith();      // no arguments at all
  });
});

describe('logout', () => {
  it('ends the realm session and clears the user', async () => {
    client.restore.mockResolvedValue(SESSION);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('name').textContent).toBe('Olga Operator'));

    await act(async () => { screen.getByText('sign out').click(); });

    expect(client.signOut).toHaveBeenCalledTimes(1);
  });
});

describe('what is no longer here', () => {
  it('writes nothing about identity to localStorage', async () => {
    // Success criterion 5: no users, no roles, no permissions, no audit log.
    client.restore.mockResolvedValue(SESSION);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    expect(Object.keys(window.localStorage)).toEqual([]);
  });

  it('exposes no switchUser', async () => {
    // Pretending to be somebody else was the defining feature of the fake login.
    client.restore.mockResolvedValue(SESSION);
    let auth: ReturnType<typeof useAuth> | null = null;
    const Capture = () => { auth = useAuth(); return null; };
    render(<AuthProvider><Capture /></AuthProvider>);

    await waitFor(() => expect(auth).not.toBeNull());
    expect('switchUser' in (auth as object)).toBe(false);
  });
});
```

A test asserting `expect(Object.keys(window.localStorage)).toEqual([])` will also catch the
theme provider if that writes a key — run it, and if the failure is `uns_theme` or similar,
narrow the assertion to keys matching `/user|role|perm|audit|login/i` and say so in a comment.
Do not delete the assertion.

- [ ] **Step 2: Write the failing LoginView test**

Create `11_frontend/src/components/auth/LoginView.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const login = vi.fn();
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    login,
    logout: vi.fn(),
    isAuthenticated: false,
    isReady: true,
    currentUser: null,
    roles: [],
    hasPermission: () => false,
  }),
}));

import { LoginView } from './LoginView';

const renderLogin = () => render(<MemoryRouter><LoginView /></MemoryRouter>);

describe('the sign-in screen', () => {
  it('has no password field', () => {
    // Spec section 6: "The LoginView password field is deleted rather than wired up - the
    // console must never see a password." Queried by input type, because a field renamed to
    // "PIN" would still be a password.
    const { container } = renderLogin();

    expect(container.querySelector('input[type="password"]')).toBeNull();
  });

  it('has no fields at all — signing in is one button', () => {
    const { container } = renderLogin();

    expect(container.querySelectorAll('input')).toHaveLength(0);
    expect(container.querySelectorAll('select')).toHaveLength(0);
  });

  it('sends the user to the realm', async () => {
    renderLogin();

    screen.getByTestId('sign-in').click();

    expect(login).toHaveBeenCalledTimes(1);
  });

  it('names where sign-in happens, so an unreachable realm is diagnosable', () => {
    // Failure modes table: "The console says the identity provider is unreachable and names
    // the URL." Naming it up front means the failure needs no extra screen.
    const { container } = renderLogin();

    expect(container.textContent).toContain('Keycloak');
  });

  it('offers no demo identities', () => {
    // The five seeded accounts in AuthContext are gone; a picker for them would be a picker
    // for nothing.
    const { container } = renderLogin();

    expect(container.textContent).not.toContain('Demo');
    expect(container.textContent).not.toContain('1-Click');
  });
});
```

- [ ] **Step 3: Run both and watch them fail**

```bash
cd 11_frontend
npx vitest run src/context/AuthContext.test.tsx src/components/auth/LoginView.test.tsx
```

Expected: the provider tests fail on `isReady` and `roles` not existing; the LoginView tests
fail on the password input at `:178`–`:185`, the email input at `:157`, the facility `select` at
`:196`, the remember-me checkbox at `:213`, the missing `sign-in` test id, and the `Demo` copy at
`:103`.

- [ ] **Step 4: Rewrite the provider**

Replace the body of `11_frontend/src/context/AuthContext.tsx`. Everything above the provider goes
— `STORAGE_KEYS` (`:17`–`:22`), `INITIAL_USERS` (`:25`–`:96`) and `INITIAL_AUDIT_LOGS`
(`:98`–`:115`) are all deleted, along with the four `localStorage` effects at `:186`–`:217`:

```tsx
/**
 * Who is signed in, according to the realm.
 *
 * The provider keeps the shape its consumers already use so that a dozen components do not
 * change at once. What changed is everything behind it: there is no user directory in this
 * file, no permission matrix in localStorage, and no login that accepts any password.
 *
 * `hasPermission` gates UI affordances only. What the server accepts is decided by
 * 07_uns_graphql/src/uns_graphql/auth/require.py, and a control this file enables is still
 * refused there if the role is wrong.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { authClient } from '../lib/auth/oidc';
import type { Session } from '../lib/auth/oidc';
import { featureAllowed } from '../lib/auth/roles';
import { FeatureKey, ROLE_CONFIGS, UserAccount, UserRole } from '../types/rbac';

interface AuthContextType {
  session: Session | null;
  currentUser: UserAccount | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** False until the first sign-in check settles. Nothing should route on identity before it. */
  isReady: boolean;
  roles: UserRole[];
  login: () => void;
  logout: () => void;
  hasPermission: (feature: FeatureKey) => boolean;
  canAccessTab: (tab: string) => { allowed: boolean; requiredFeature: FeatureKey; featureName: string };
}

const AuthContext = createContext<AuthContextType | null>(null);

/**
 * The realm's view of a person, in the shape the existing chrome renders.
 *
 * `department` and `plantLocation` are required by `UserAccount` (types/rbac.ts:236-244) and
 * empty here, because the realm does not hold them. Inventing 'Process Engineering' and
 * 'Dormagen' is exactly what the five seeded accounts did. Any component that renders them
 * must be checked for whether an empty string reads as missing data or as a broken layout —
 * `LoginView.tsx:133` rendered `u.department`, and that whole block is deleted in Step 5.
 *
 * `avatarColor` is deliberately omitted: it is optional on `UserAccount`, and both consumers
 * already fall back (`UserManagementView.tsx:335` and `:510` use `bg-[#FFC107]`). Note that
 * `RoleConfig` has no `avatarColor` — it has `badgeBg`, `badgeText` and `badgeBorder` — so do
 * not reach for `ROLE_CONFIGS[role].avatarColor`; it does not exist.
 */
function toAccount(session: Session): UserAccount {
  const role = session.roles[0] ?? 'viewer';
  return {
    id: session.subject,
    name: session.displayName,
    email: session.email ?? session.username,
    role,
    department: '',
    plantLocation: '',
    status: 'active',
    createdAt: '',
    lastLogin: '',
    // The role's profile, with no per-user overrides: the realm is the only authority on what
    // somebody may do, and a customPermissions map in the browser was a permission matrix
    // the server never saw.
    customPermissions: { ...ROLE_CONFIGS[role].defaultPermissions },
  };
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<Session | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const start = async () => {
      // Order matters: a redirect back from the realm carries a one-time code, and racing a
      // silent renew against it can discard the session just granted.
      const fromRedirect = await authClient.completeRedirect();
      const resolved = fromRedirect ?? (fromRedirect === null ? await authClient.restore() : null);
      if (!cancelled) {
        setSession(resolved);
        setIsReady(true);
      }
    };

    void start();
    const stop = authClient.onSession((next) => {
      if (!cancelled) {
        setSession(next);
      }
    });

    return () => {
      cancelled = true;
      stop();
    };
  }, []);

  const roles = useMemo(() => session?.roles ?? [], [session]);
  const currentUser = useMemo(() => (session ? toAccount(session) : null), [session]);

  const hasPermission = useCallback(
    (feature: FeatureKey) => featureAllowed(roles, feature),
    [roles],
  );

  const canAccessTab = useCallback(
    (tab: string) => {
      const required = TAB_FEATURES[tab] ?? TAB_FEATURES.home;
      return {
        allowed: hasPermission(required.feature),
        requiredFeature: required.feature,
        featureName: required.name,
      };
    },
    [hasPermission],
  );

  const value = useMemo<AuthContextType>(
    () => ({
      session,
      currentUser,
      isAuthenticated: session !== null,
      isAdmin: roles.includes('admin'),
      isReady,
      roles,
      login: () => { void authClient.signIn(); },
      logout: () => { void authClient.signOut(); },
      hasPermission,
      canAccessTab,
    }),
    [session, currentUser, roles, isReady, hasPermission, canAccessTab],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
};
```

`TAB_FEATURES` is the `switch` from `:376`–`:409` turned into a table beside the provider. Copy
the eight entries across verbatim — the same tab keys and the same `FeatureKey` values — and take
the *labels* from the navigation that actually shipped: the surfaces plan renames the screens
away from internal module names, and if it has not landed (as of 2026-09-03 it had not), the
labels come from the current navigation and the surfaces plan renames them later:

```tsx
const TAB_FEATURES: Record<string, { feature: FeatureKey; name: string }> = {
  home: { feature: 'uns_tree', name: 'Plant' },
  explore: { feature: 'historian', name: 'Historian' },
  sparkplug: { feature: 'sparkplug', name: 'Sparkplug' },
  streams: { feature: 'streams', name: 'Streams' },
  alarms: { feature: 'alarms', name: 'Alarms' },
  system: { feature: 'system_ops', name: 'Health' },
  simulator: { feature: 'simulator_ops', name: 'Simulator' },
  users: { feature: 'user_management', name: 'Users' },
};
```

When the surfaces plan lands, check its navigation task for the tab keys it ships and adopt
those. If it renamed a route key, this table's keys change with it; a stale key here silently
falls back to `home` and gates the wrong screen. Until then, the existing switch's keys are the
authority.

`session.roles[0]` is a lossy narrowing and it is worth being explicit about why it is
acceptable here. `UserAccount.role` is a single `UserRole`, but a realm user can hold several —
an engineer who is also an admin holds both. Because `CONSOLE_ROLES` is ordered most-privileged
first and `rolesFromClaims` preserves that order, `roles[0]` is the *highest* role held, so the
badge never under-reports. It is only ever a display value: `hasPermission` reads the whole
`roles` array, so a second role is never lost where it matters. Do not let anything gate on
`currentUser.role`; `tsc` cannot catch that and it would silently drop a privilege.

The `resolved` line reads awkwardly on purpose; write it plainly instead if you prefer, as long
as `restore()` is skipped when the callback produced a session — the second test in that block
asserts exactly that:

```tsx
const fromRedirect = await authClient.completeRedirect();
const resolved = fromRedirect ?? (await authClient.restore());
```

That simpler form is correct and passes both tests. Use it.

- [ ] **Step 5: Rewrite the sign-in screen**

`LoginView.tsx` loses its form. Delete the state at `:27`–`:33`, `handleSelectQuickUser`
(`:35`–`:40`), `handleFormSubmit` (`:42`–`:56`), `selectedUserObj`/`roleConfig` (`:58`–`:59`),
the demo identity grid (`:100`–`:139`) and the whole `<form>` (`:142`–`:239`). Keep the header,
the card, the brand block and the theme toggle.

What replaces the form:

```tsx
export const LoginView: React.FC = () => {
  const navigate = useNavigate();
  const { login, isAuthenticated, isReady } = useAuth();
  const { isDark, toggleTheme } = useTheme();

  useEffect(() => {
    if (isReady && isAuthenticated) {
      navigate('/tree');
    }
  }, [isReady, isAuthenticated, navigate]);

  // ...header and card unchanged...

          <button
            data-testid="sign-in"
            type="button"
            onClick={login}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-amber-500 hover:bg-amber-600 dark:bg-[#FFC107] dark:hover:bg-[#FFB300] text-slate-950 font-bold text-xs uppercase tracking-wider shadow-md transition-all cursor-pointer disabled:opacity-50"
          >
            <span>Sign in with Keycloak</span>
            <ChevronRight className="w-4 h-4" />
          </button>

          <p className="text-[11px] text-[#64748B] text-center">
            Sign-in happens on the plant's Keycloak realm at{' '}
            <span className="font-mono">{platformConfig.authBaseUrl}</span>. The console never
            sees your password.
          </p>
```

Naming the realm URL on the screen is what makes an unreachable identity provider diagnosable
without another screen for it: a browser that cannot reach that host shows its own error, and the
user can read where it was trying to go.

Then prune the imports. `Mail`, `Lock`, `Building2`, `AlertCircle`, `CheckCircle2` and
`ROLE_CONFIGS` all become unused; `useState` too, if the effect is the only hook left besides
`useEffect`. Add `platformConfig` from `../../lib/platform/config`. Let `tsc` and `ruff`'s
JS equivalent find them — `npx tsc --noEmit` reports unused imports only if
`noUnusedLocals` is on, so also run the linter this project uses.

The `ISO/IEC 62443` / `TLS 1.3` notice at `:242`–`:248` is the surfaces plan's Task 3. If that
has landed it is already gone; if it has not, leave it and let Task 3 remove it, so the two plans
do not conflict over the same lines.

- [ ] **Step 6: Delete the impersonation control**

In `11_frontend/src/components/common/UserSessionMenu.tsx`, remove the `switchUser` import and
whatever list of accounts it renders to call it. Replace it with the signed-in user's name, their
roles, and a `Sign out` item.

In `11_frontend/src/components/users/UserManagementView.tsx:428`–`:434`, delete the `Simulate`
button and its handler.

```bash
cd 11_frontend && grep -rn "switchUser" src/
```

Expected: no output.

- [ ] **Step 7: Fix every consumer the compiler names**

```bash
cd 11_frontend && npx tsc --noEmit
```

`currentUser` is now nullable, so every `currentUser.email` and `currentUser.name` is an error.
Every consumer, from `grep -rn "useAuth()" src/`:

| File | Reads | What changes |
| --- | --- | --- |
| `App.tsx:34` | `isAuthenticated` | gate the redirect on `isReady` too |
| `components/landing/LandingView.tsx:41` | `isAuthenticated`, `currentUser`, `login` | `login` takes no arguments now |
| `components/auth/LoginView.tsx:24` | `users`, `currentUser`, `login` | `users` is gone; Step 5 rewrote this file |
| `components/common/UserSessionMenu.tsx:21` | `currentUser`, `users`, `switchUser`, `isAdmin`, `hasPermission`, `logout` | Step 6; `users` and `switchUser` both gone |
| `components/common/AccessRestricted.tsx:17` | `currentUser`, `users`, `switchUser` | "switch to an account that can" is impossible now — say which role is required instead |
| `components/layout/Sidebar.tsx:58` | `canAccessTab`, `currentUser`, `isAdmin` | null-safe display |
| `components/layout/AppLayout.tsx:14` | `canAccessTab` | unchanged |
| `components/alarms/AlarmManagementView.tsx:58` | `currentUser`, `isAdmin` | acknowledgement uses `session?.username`, guarded |
| `components/alarms/RoleAlertMatrix.tsx:11` | `currentUser` | null-safe display |
| `context/AlarmContext.tsx:340` | `currentUser` | **the one that matters**: whatever it stamps on an alarm must not become `undefined` in stored state |
| `components/explore/HistorianTable.tsx:16` | `hasPermission` | unchanged |
| `components/simulator/SimulatorConfigPanel.tsx:17`, `SimulatorStatusPanel.tsx:58` | `hasPermission` | unchanged |
| `components/users/UserManagementView.tsx:51` | the whole surface | Task 10 |
| `components/users/CreateUserModal.tsx:12`, `EditUserModal.tsx:13` | `createUser`, `updateUser`, `deleteUser`, `resetUserToRoleDefaults` | deleted by the surfaces plan's Task 21; if they are still here, delete them now |

`AccessRestricted.tsx` deserves a sentence of its own. Today it offers to switch you into an
account that has the permission you lack, which is only possible when the accounts are fictional.
It becomes a statement of fact: which screen you asked for, which role grants it, and that a
plant administrator grants roles in Keycloak. Take the role name from
`ROLE_CONFIGS[...].label` so the wording matches the badges.

Two rules for those edits, and no third:

- Chrome that displays the user (`Sidebar`, `AppLayout`, `UserSessionMenu`) renders nothing for
  a null user rather than a placeholder name. A chip reading `Guest` or `—` invites the reader
  to think there is a session.
- Code that *acts* as the user (an `acknowledgedBy`, an export footer) uses
  `session?.username`. If there is no session it must not act; guard the call, do not substitute
  a string.

Also check `App.tsx` or wherever routes are declared: anything that redirects on
`!isAuthenticated` must now wait for `isReady` first, or a refresh on `/alarms` bounces a
signed-in user to the landing page before the silent renew finishes.

Then one grep the compiler cannot do for you:

```bash
cd 11_frontend && grep -rn "currentUser?\?\.role\b" src/
```

Every hit is a *display* of the highest role held, and that is fine. Any hit that *gates* on it
— `currentUser.role === 'admin'`, a `switch` deciding what to render — is a bug now, because a
user holding two roles has one of them dropped by `roles[0]`. Change those to `isAdmin` or
`hasPermission(...)`.

- [ ] **Step 8: Run the whole frontend suite**

```bash
cd 11_frontend
npx vitest run
npx tsc --noEmit
npm run build
```

Expected: green. `npm run build` matters here specifically — it is the check that no deleted
`localStorage` key is still referenced from a file the test suite does not import.

- [ ] **Step 9: Commit**

```bash
cd 11_frontend
git add src/context/AuthContext.tsx src/context/AuthContext.test.tsx \
        src/components/auth/LoginView.tsx src/components/auth/LoginView.test.tsx \
        src/components/common/UserSessionMenu.tsx src/components/users/UserManagementView.tsx \
        src/components
git commit -m "feat(console): sign in against the realm, and delete the password field

AuthContext keeps the shape its consumers use and replaces everything behind
it: no seeded user directory, no permission matrix in localStorage, no login
that returns true for any password. login() is a redirect and takes no
arguments, which is what the test asserts.

switchUser is gone. Pretending to be somebody else was the defining feature of
the fake login, and its one caller was a menu of five invented accounts.

currentUser is nullable now, and the chrome renders nothing rather than a
placeholder name — a chip reading 'Guest' invites the reader to believe there is
a session. isReady exists so that a refresh on a deep link does not bounce a
signed-in user to the landing page while the silent renew is still in flight."
```

**Definition of done:**
- `LoginView` contains no `input` and no `select`; `input[type="password"]` is asserted absent
  (spec test 8, success criterion 1).
- `login` is called with no arguments and redirects; no code path reads a password.
- `switchUser` does not exist anywhere in `src/`.
- Identity-related `localStorage` keys are written by nothing (success criterion 5).
- `isReady` gates every identity-based redirect.
- `npx vitest run`, `npx tsc --noEmit` and `npm run build` all green.

---

## Task 9: Every request carries the token, and a 401 is not an empty table

Spec tests 9 and 10. The console has one GraphQL client, so this is two small changes at two
known lines and one honest failure path.

Three facts from the file, verified:

1. `executeQuery` at `services/graphql/client.ts:154`–`:188` is the only place `fetch` is called,
   and its headers at `:162`–`:165` are `Content-Type` and `Accept`.
2. `initWebSocket` at `:98` sends `{"type":"connection_init"}` with no payload at `:118`.
3. **The client swallows every failure into a shape that looks like empty data.** `:171`–`:181`
   returns `{data: null}` for any non-`ok` response, and the callers turn that into `[]` — see
   `getUnsNodes` at `:190`–`:198`. A 401 today would render an empty plant tree, which is
   precisely the failure mode spec test 10 forbids.

**Files:**
- Modify: `11_frontend/src/services/graphql/client.ts:82`–`:90`, `:98`–`:152`, `:154`–`:188`
- Test: `11_frontend/src/services/graphql/client-auth.test.ts` (create)

**Interfaces:**
- Consumes: `authClient.accessToken()` and `authClient.refresh()` (Task 7).
- Produces: `UnsGraphQLClient` gains a constructor option
  ```ts
  interface AuthHooks { token(): string | null; refresh(): Promise<string | null>; onExpired(): void }
  constructor(httpUrl?: string, wsUrl?: string, auth?: AuthHooks)
  ```
  Default `auth` reads `authClient` and `onExpired` calls `authClient.signIn()`.
- Nothing consumes this further.

- [x] **Step 1: Write the failing test**

Create `11_frontend/src/services/graphql/client-auth.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UnsGraphQLClient } from './client';

/** A WebSocket that records what was sent and never opens by itself. */
class RecordingSocket {
  static instances: RecordingSocket[] = [];
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string, public protocol?: string) {
    RecordingSocket.instances.push(this);
  }
  send(data: string) { this.sent.push(data); }
  close() {}
}

const auth = {
  token: vi.fn<[], string | null>(() => 'first.access.token'),
  refresh: vi.fn<[], Promise<string | null>>(async () => 'second.access.token'),
  onExpired: vi.fn(),
};

const ok = (data: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data }) }) as unknown as Response;
const unauthorized = () =>
  ({ ok: false, status: 401, json: async () => ({}) }) as unknown as Response;

beforeEach(() => {
  vi.clearAllMocks();
  RecordingSocket.instances = [];
  auth.token.mockReturnValue('first.access.token');
  auth.refresh.mockResolvedValue('second.access.token');
  vi.stubGlobal('WebSocket', RecordingSocket);
});

const client = () => new UnsGraphQLClient('/graphql', 'ws://test/graphql', auth);

describe('the Authorization header', () => {
  it('is on every request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer first.access.token');
  });

  it('is absent rather than empty when there is no token', async () => {
    // `Authorization: Bearer ` with nothing after it is a malformed header the server logs as
    // a bad token rather than as an anonymous request.
    auth.token.mockReturnValue(null);
    const fetchMock = vi.fn().mockResolvedValue(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    const [, init] = fetchMock.mock.calls[0];
    expect('Authorization' in (init.headers as Record<string, string>)).toBe(false);
  });

  it('is read per request, so a renewed token is used immediately', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);
    const c = client();

    await c.getUnsNodes(['a/b']);
    auth.token.mockReturnValue('renewed.access.token');
    await c.getUnsNodes(['a/b']);

    const [, second] = fetchMock.mock.calls[1];
    expect((second.headers as Record<string, string>).Authorization)
      .toBe('Bearer renewed.access.token');
  });
});

describe('a 401', () => {
  it('is retried once with a refreshed token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    expect(auth.refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, retry] = fetchMock.mock.calls[1];
    expect((retry.headers as Record<string, string>).Authorization)
      .toBe('Bearer second.access.token');
  });

  it('is retried exactly once, never in a loop', async () => {
    const fetchMock = vi.fn().mockResolvedValue(unauthorized());
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(auth.refresh).toHaveBeenCalledTimes(1);
  });

  it('sends the user back to the realm when the refresh does not help', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()));

    await client().getUnsNodes(['a/b']);

    expect(auth.onExpired).toHaveBeenCalledTimes(1);
  });

  it('does not refresh when there was no token to begin with', async () => {
    // Not signed in yet is not an expired session, and a silent renew here would fire on
    // every request the landing page makes.
    auth.token.mockReturnValue(null);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()));

    await client().getUnsNodes(['a/b']);

    expect(auth.refresh).not.toHaveBeenCalled();
    expect(auth.onExpired).toHaveBeenCalledTimes(1);
  });

  it('never reports an expired session as no data', async () => {
    // Spec test 10, and the reason this task touches the return shape at all: today every
    // failure becomes `[]`, and an operator reads an empty plant tree as a quiet plant.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()));
    const c = client();
    const errors: string[] = [];
    c.onHealthChange?.((health) => { if (health.lastError) errors.push(health.lastError); });

    await c.getUnsNodes(['a/b']);

    expect(auth.onExpired).toHaveBeenCalled();
  });
});

describe('the subscription socket', () => {
  it('carries the token in connection_init', async () => {
    // A browser cannot set a header on a WebSocket handshake, so this is where
    // graphql-transport-ws puts credentials — and what
    // AuthenticatedGraphQLRouter.on_ws_connect reads.
    client();
    const socket = RecordingSocket.instances[0];

    socket.onopen?.();

    expect(JSON.parse(socket.sent[0])).toEqual({
      type: 'connection_init',
      payload: { Authorization: 'Bearer first.access.token' },
    });
  });

  it('sends an empty payload rather than a malformed header when there is no token', () => {
    auth.token.mockReturnValue(null);
    client();
    const socket = RecordingSocket.instances[0];

    socket.onopen?.();

    expect(JSON.parse(socket.sent[0])).toEqual({ type: 'connection_init', payload: {} });
  });
});
```

The last test in the `401` block references `c.onHealthChange` defensively with `?.` — read the
client for the real name of its health subscription (`healthListeners` at `:75` implies there is
one) and either assert on it properly or delete those three lines and keep the `onExpired`
assertion, which is the part spec test 10 actually requires.

- [x] **Step 2: Run it and watch it fail**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-auth.test.ts`

Expected: the constructor rejects a third argument; no `Authorization` header; `connection_init`
has no payload.

- [x] **Step 3: Take the auth hooks in the constructor**

In `client.ts`, above the class:

```ts
/**
 * How this client gets a token. Injected so the tests never construct a real UserManager,
 * and read per request rather than captured, so a silent renew takes effect immediately.
 */
export interface AuthHooks {
  token(): string | null
  refresh(): Promise<string | null>
  /** Called when a refreshed token is still refused. Sends the user back to the realm. */
  onExpired(): void
}

const defaultAuthHooks: AuthHooks = {
  token: () => authClient.accessToken(),
  refresh: () => authClient.refresh(),
  onExpired: () => { void authClient.signIn() },
}
```

with `import { authClient } from '../../lib/auth/oidc'` added to the imports. Then the
constructor at `:82`:

```ts
  constructor(httpUrl = '/graphql', wsUrl?: string, auth: AuthHooks = defaultAuthHooks) {
    this.auth = auth
    this.httpUrl = httpUrl
```

and a `private auth: AuthHooks` field beside the others at `:68`–`:80`. Assign `this.auth`
**before** `initWebSocket()` runs at `:89` — the socket's `onopen` reads it, and a client
constructed at module scope opens its socket during construction.

- [x] **Step 4: Put the token on the request, and stop turning 401 into nothing**

Rewrite `executeQuery` (`:154`–`:188`):

```ts
  private authHeaders(): Record<string, string> {
    const token = this.auth.token()
    // Absent rather than `Bearer `: an empty bearer is a malformed header the server logs as
    // a bad token instead of as an anonymous request.
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  private async executeQuery<T>(
    query: string,
    variables: Record<string, unknown> = {},
    retryOnUnauthorized = true,
  ): Promise<{ data: T | null; error?: string }> {
    const t0 = performance.now()
    try {
      const hadToken = this.auth.token() !== null
      const response = await fetch(this.httpUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          ...this.authHeaders(),
        },
        body: JSON.stringify({ query, variables }),
      })

      this.lastPingMs = Math.round(performance.now() - t0)

      if (response.status === 401) {
        // One refresh, then the realm. Never a loop: a 401 that survives a fresh token is a
        // permission or configuration problem, and retrying it forever hides that.
        if (retryOnUnauthorized && hadToken && (await this.auth.refresh()) !== null) {
          return this.executeQuery<T>(query, variables, false)
        }
        this.auth.onExpired()
        // An expired session is not an empty result. Every caller of this method turns
        // `{data: null}` into `[]`, and an operator reads an empty plant tree as a quiet
        // plant rather than as a session that ended.
        return { data: null, error: 'Your session has expired. Signing in again.' }
      }

      if (response.ok) {
        const json = await response.json()
        if (json.data) {
          this.isLiveBackend = true
          this.notifyHealth()
          return { data: json.data as T }
        }
        if (json.errors?.length > 0) {
          return { data: null, error: json.errors[0].message as string }
        }
      }
    } catch {
      this.isLiveBackend = false
    }

    this.notifyHealth()
    return { data: null, error: 'GraphQL endpoint unreachable' }
  }
```

`hadToken` is read before the request rather than after, because `refresh()` changes what
`token()` returns and the question being asked is "did this request carry a token" — not "is
there one now".

Note what this task does *not* change: the callers still turn `{data: null}` into `[]`. Making
each of them surface `error` is the surfaces plan's work on truthful empty states, and doing it
here would touch thirty methods in a commit about tokens. What this task guarantees is that a
401 is never silent — `onExpired()` fires, and the user is sent to the realm.

- [x] **Step 5: Put the token in `connection_init`**

At `:115`–`:120`, replace the payload-less init:

```ts
      this.ws.onopen = () => {
        this.wsConnected = true
        this.wsProtocolReady = false
        const token = this.auth.token()
        // graphql-transport-ws puts credentials here because a browser cannot set a header on
        // a handshake. AuthenticatedGraphQLRouter.on_ws_connect reads exactly this key.
        this.ws?.send(
          JSON.stringify({
            type: 'connection_init',
            payload: token ? { Authorization: `Bearer ${token}` } : {},
          }),
        )
        this.notifyHealth()
      }
```

The key is `Authorization` with a capital A, matching what Task 4's `_connection_params` reads
first. It accepts the lowercase spelling too, but there is no reason to make it.

One consequence to handle: the server now closes the socket with code 4403 when the token is
missing or bad, and `onclose` at `:144`–`:148` treats every close the same. Add the code to the
health signal so a rejected subscription is distinguishable from a stopped container:

```ts
      this.ws.onclose = (event) => {
        this.wsConnected = false
        this.wsProtocolReady = false
        if (event.code === 4403) {
          // The realm refused this socket. Not a network fault, and not something a retry
          // fixes without a new token.
          this.auth.onExpired()
        }
        this.notifyHealth()
      }
```

If `RecordingSocket` in the test does not pass an event to `onclose`, that is fine — no test
asserts this path. Add one if it is cheap; do not leave the branch untested *and* unmentioned.

- [x] **Step 6: Reconnect the socket when the session changes**

A socket opened before sign-in was rejected, and nothing currently reopens it. In
`AuthContext`'s effect, or wherever the client instance lives, call the client's existing
`setUrls(httpUrl, wsUrl)` — which at `:92`–`:96` already tears down and reopens the socket — when
a session appears. Read how the app constructs its client (`services/graphql/client.ts` exports
the class; find the singleton) and wire it to `authClient.onSession`.

If that turns out to need more than a few lines, add a `public reconnect()` that just calls
`this.initWebSocket()` and call that instead. Do not leave the socket permanently dead after a
sign-in — the plant tree's live updates come through it, and a console whose subscriptions
silently never connect is the exact class of defect this whole plan is about.

- [x] **Step 7: Run the suite**

```bash
cd 11_frontend
npx vitest run
npx tsc --noEmit
```

Expected: green.

- [ ] **Step 8: Check it by hand**

With the stack up, sign in, open the plant tree, and watch the network panel:

- Every `POST /graphql` has an `Authorization: Bearer …` request header.
- The WS frame list shows `connection_init` with an `Authorization` payload, followed by
  `connection_ack`.
- Then, in the browser console, force the failure: `localStorage.clear()` proves nothing here,
  so instead stop `uns_keycloak`, wait for the token to expire, and confirm the console
  redirects to a sign-in attempt rather than emptying the tree.

- [ ] **Step 9: Commit**

```bash
cd 11_frontend
git add src/services/graphql/client.ts src/services/graphql/client-auth.test.ts src/context
git commit -m "feat(console): send the token, and stop reporting a 401 as no data

The header goes on in executeQuery, the only place this client calls fetch, and
the token is read per request so a silent renew takes effect immediately. The
WebSocket carries it in connection_init, which is where graphql-transport-ws
puts credentials and what the server's on_ws_connect reads.

A 401 gets one refresh and then sends the user to the realm. It never loops: a
401 that survives a fresh token is a permission problem and retrying hides it.
And it no longer returns {data: null}, which every caller turns into [] — an
operator reads an empty plant tree as a quiet plant, not as an ended session.

No token means no Authorization header at all, rather than 'Bearer ' with
nothing after it, which a server logs as a bad token instead of as an
anonymous request."
```

**Definition of done:**
- Every GraphQL request carries `Authorization: Bearer <token>`, read per request (spec test 9).
- `connection_init` carries the token in its payload (spec test 9).
- A 401 triggers exactly one refresh, then `onExpired()`; it never renders as an empty result
  (spec test 10).
- No token produces no `Authorization` header rather than an empty bearer.
- A socket closed with 4403 reports an expired session rather than a network fault.
- The socket reconnects after sign-in.
- `npx vitest run` and `npx tsc --noEmit` green.

---

## Task 10: The user directory is the realm's, and it may say no

`UserManagementView` today lists five people who do not exist, lets an admin tick individual
feature boxes for them, and keeps the result in `localStorage`. All three are fictions. This task
replaces the list with the realm's membership and deletes the tick boxes, because a permission the
server never sees is not a permission.

**The honest part of this task is the failure path.** Keycloak's admin API is reached with the
console's own access token, and whether it accepts one depends on a role mapping this task adds.
Spec success criterion 6 explicitly allows the alternative: *the screen may say it cannot reach
the realm and name where to manage users instead.* Write both paths and mean both — a directory
that silently shows nothing is worse than one that says why.

**Files:**
- Modify: `conf/keycloak/realm.json` (make `admin` composite),
  `00_uns_config/test/test_keycloak_realm.py`,
  `11_frontend/src/components/users/UserManagementView.tsx`
- Create: `11_frontend/src/lib/auth/directory.ts`
- Delete: `11_frontend/src/components/users/CreateUserModal.tsx`,
  `11_frontend/src/components/users/EditUserModal.tsx` (if the surfaces plan's Task 21 has not
  already)
- Test: `11_frontend/src/lib/auth/directory.test.ts`,
  `11_frontend/src/components/users/UserManagementView.test.tsx` (both create)

**Interfaces:**
- Consumes: `authClient.accessToken()` (Task 7); `platformConfig.authBaseUrl`, `.authRealm`
  (Task 2); `rolesFromClaims`-adjacent role filtering via `toUserRole` (Task 7).
- Produces:
  ```ts
  // src/lib/auth/directory.ts
  export interface RealmMember { id: string; username: string; email?: string;
                                 displayName: string; enabled: boolean; roles: UserRole[] }
  export type DirectoryResult =
    | { kind: 'members'; members: RealmMember[] }
    | { kind: 'forbidden' }        // the realm answered 401/403: this token may not read users
    | { kind: 'unreachable'; detail: string }
  export function fetchRealmMembers(fetchImpl?: typeof fetch): Promise<DirectoryResult>
  ```
- Nothing consumes this further.

- [ ] **Step 1: Make the admin role able to read the directory**

Keycloak does not let an arbitrary realm role read `/admin/realms/{realm}/users`. The reader
needs the `view-users` *client* role of the built-in `realm-management` client, and it has to
arrive in the console's token. The way to arrange that in a realm export is to make the `admin`
realm role composite.

In `conf/keycloak/realm.json`, replace the plain `admin` entry in `roles.realm` with:

```json
{
  "name": "admin",
  "description": "Console administrator. Composite so that an admin's token can read the realm's user directory.",
  "composite": true,
  "composites": {
    "client": {
      "realm-management": ["view-users", "view-realm"]
    }
  }
}
```

`view-users` and `view-realm` only, deliberately. Not `manage-users`: this console reads the
directory and does not create people in it, and a token in a browser that could create realm
users is a much larger thing to leak than one that can list them. That is also why Step 6's
screen has no *Add user* button rather than a disabled one — the capability is absent, not
withheld.

Then extend `00_uns_config/test/test_keycloak_realm.py`:

```python
def test_the_admin_role_can_read_the_user_directory(realm: dict):
    """
    The console lists realm members with the signed-in admin's own token. Without this
    composite the directory screen can only ever show its cannot-reach-the-realm state.
    """
    admin = next(role for role in realm["roles"]["realm"] if role["name"] == "admin")
    assert admin["composite"] is True
    granted = admin["composites"]["client"]["realm-management"]
    assert "view-users" in granted


def test_no_role_in_this_realm_can_manage_users(realm: dict):
    """
    Reading the directory is the whole feature. A browser token that could create realm
    users would be a far larger thing to leak, and this console never needs it.
    """
    for role in realm["roles"]["realm"]:
        granted = role.get("composites", {}).get("client", {}).get("realm-management", [])
        assert "manage-users" not in granted, role["name"]
        assert "realm-admin" not in granted, role["name"]
```

Run: `cd 00_uns_config && uv run pytest test/test_keycloak_realm.py -q`

- [ ] **Step 2: Write the failing directory test**

Create `11_frontend/src/lib/auth/directory.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchRealmMembers } from './directory';

vi.mock('./oidc', () => ({
  authClient: { accessToken: () => 'admin.access.token' },
}));

const KEYCLOAK_USERS = [
  {
    id: 'kc-1',
    username: 'engineer.user',
    email: 'engineer.user@example.test',
    firstName: 'Erin',
    lastName: 'Engineer',
    enabled: true,
  },
  { id: 'kc-2', username: 'service-account-thing', enabled: true },
];

const json = (status: number, body: unknown) =>
  ({ ok: status < 400, status, json: async () => body }) as unknown as Response;

beforeEach(() => vi.clearAllMocks());

describe('fetchRealmMembers', () => {
  it('asks the realm, with the signed-in user token', async () => {
    const f = vi.fn()
      .mockResolvedValueOnce(json(200, KEYCLOAK_USERS))
      .mockResolvedValue(json(200, [{ name: 'engineer' }]));

    await fetchRealmMembers(f as unknown as typeof fetch);

    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain('/admin/realms/uns/users');
    expect((init.headers as Record<string, string>).Authorization)
      .toBe('Bearer admin.access.token');
  });

  it('reads each member’s realm roles and drops the ones Keycloak gives everybody', async () => {
    const f = vi.fn().mockImplementation(async (url: string) =>
      String(url).includes('/role-mappings/realm')
        ? json(200, [{ name: 'engineer' }, { name: 'default-roles-uns' }])
        : json(200, [KEYCLOAK_USERS[0]]),
    );

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toEqual({
      kind: 'members',
      members: [{
        id: 'kc-1',
        username: 'engineer.user',
        email: 'engineer.user@example.test',
        displayName: 'Erin Engineer',
        enabled: true,
        roles: ['engineer'],
      }],
    });
  });

  it('falls back to the username when the realm holds no name', async () => {
    const f = vi.fn().mockImplementation(async (url: string) =>
      String(url).includes('/role-mappings/realm') ? json(200, []) : json(200, [KEYCLOAK_USERS[1]]),
    );

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toMatchObject({
      members: [{ displayName: 'service-account-thing', roles: [] }],
    });
  });

  it('reports forbidden rather than empty when the realm refuses the token', async () => {
    // Spec success criterion 6. An empty directory would read as "this plant has no users".
    const f = vi.fn().mockResolvedValue(json(403, {}));

    expect(await fetchRealmMembers(f as unknown as typeof fetch)).toEqual({ kind: 'forbidden' });
  });

  it('reports forbidden on a 401 too', async () => {
    const f = vi.fn().mockResolvedValue(json(401, {}));

    expect(await fetchRealmMembers(f as unknown as typeof fetch)).toEqual({ kind: 'forbidden' });
  });

  it('reports unreachable when the realm is not there at all', async () => {
    const f = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toMatchObject({ kind: 'unreachable' });
    expect((result as { detail: string }).detail).toContain('Failed to fetch');
  });

  it('still lists a member whose role lookup fails, with no roles', async () => {
    // One bad row must not blank the directory.
    const f = vi.fn().mockImplementation(async (url: string) =>
      String(url).includes('/role-mappings/realm') ? json(500, {}) : json(200, [KEYCLOAK_USERS[0]]),
    );

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toMatchObject({ members: [{ username: 'engineer.user', roles: [] }] });
  });
});
```

- [ ] **Step 3: Write `directory.ts`**

Create `11_frontend/src/lib/auth/directory.ts`:

```ts
/**
 * The realm's membership, read with the signed-in admin's own token.
 *
 * There is no user directory in this console. Keycloak has one, and this reads it. Two
 * consequences the screen has to live with:
 *
 * - This is the only place the console talks to something other than /graphql and the
 *   simulator control API. It is same-origin (nginx proxies /auth), so there is no CORS
 *   negotiation, and it is a read.
 * - The realm may refuse. Reading /admin/realms/{realm}/users needs realm-management's
 *   view-users role, which conf/keycloak/realm.json grants to `admin` as a composite. If a
 *   deployment's realm was provisioned by hand without it, the answer is 403 — and that is a
 *   `forbidden` result the screen states plainly, not an empty list.
 *
 * Nothing here writes. Creating and disabling plant users happens in Keycloak.
 */

import { platformConfig } from '../platform/config';
import { authClient } from './oidc';
import { toUserRole } from './roles';
import type { UserRole } from '../../types/rbac';

export interface RealmMember {
  id: string;
  username: string;
  email?: string;
  displayName: string;
  enabled: boolean;
  roles: UserRole[];
}

export type DirectoryResult =
  | { kind: 'members'; members: RealmMember[] }
  | { kind: 'forbidden' }
  | { kind: 'unreachable'; detail: string };

/** Keycloak's admin base, e.g. http://localhost:8088/auth/admin/realms/uns */
function adminBase(): string {
  return `${platformConfig.authBaseUrl}/admin/realms/${platformConfig.authRealm}`;
}

function authHeaders(): Record<string, string> {
  const token = authClient.accessToken();
  return token ? { Authorization: `Bearer ${token}`, Accept: 'application/json' } : { Accept: 'application/json' };
}

interface KeycloakUser {
  id: string;
  username: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  enabled?: boolean;
}

function displayName(user: KeycloakUser): string {
  const full = [user.firstName, user.lastName].filter(Boolean).join(' ').trim();
  // The username, not an empty cell: a row with no name still has to be identifiable.
  return full || user.username;
}

async function rolesOf(
  fetchImpl: typeof fetch,
  userId: string,
): Promise<UserRole[]> {
  try {
    const response = await fetchImpl(`${adminBase()}/users/${userId}/role-mappings/realm`, {
      headers: authHeaders(),
    });
    if (!response.ok) {
      // One member's role lookup failing must not blank the whole directory.
      return [];
    }
    const granted = (await response.json()) as { name?: string }[];
    return granted
      .map((role) => toUserRole(role.name))
      .filter((role): role is UserRole => role !== undefined);
  } catch {
    return [];
  }
}

export async function fetchRealmMembers(fetchImpl: typeof fetch = fetch): Promise<DirectoryResult> {
  try {
    // briefRepresentation=false so firstName and lastName come back. max is Keycloak's page
    // size; a plant realm is tens of people, and a truncated list would be a lie the screen
    // could not detect.
    const response = await fetchImpl(
      `${adminBase()}/users?briefRepresentation=false&max=500`,
      { headers: authHeaders() },
    );

    if (response.status === 401 || response.status === 403) {
      return { kind: 'forbidden' };
    }
    if (!response.ok) {
      return { kind: 'unreachable', detail: `The realm answered ${response.status}.` };
    }

    const users = (await response.json()) as KeycloakUser[];
    const members = await Promise.all(
      users.map(async (user) => ({
        id: user.id,
        username: user.username,
        email: user.email,
        displayName: displayName(user),
        enabled: user.enabled !== false,
        roles: await rolesOf(fetchImpl, user.id),
      })),
    );
    return { kind: 'members', members };
  } catch (error) {
    return { kind: 'unreachable', detail: error instanceof Error ? error.message : String(error) };
  }
}
```

`max=500` is a cap, and a cap that is hit is a lie. Keycloak returns at most that many rows with
no indication there were more. If a deployment ever has more realm members than that, the screen
needs paging — note it here rather than discovering it as a missing colleague.

- [ ] **Step 4: Write the failing screen test**

Create `11_frontend/src/components/users/UserManagementView.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchRealmMembers = vi.fn();
vi.mock('../../lib/auth/directory', () => ({ fetchRealmMembers }));

const auth = { isAdmin: true, roles: ['admin'], currentUser: null, hasPermission: () => true };
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));

import { UserManagementView } from './UserManagementView';

beforeEach(() => {
  vi.clearAllMocks();
  auth.isAdmin = true;
  auth.roles = ['admin'];
});

const MEMBERS = {
  kind: 'members' as const,
  members: [
    { id: 'kc-1', username: 'erin', email: 'erin@example.test',
      displayName: 'Erin Engineer', enabled: true, roles: ['engineer' as const] },
    { id: 'kc-2', username: 'olga', displayName: 'Olga Operator', enabled: false, roles: [] },
  ],
};

describe('the user directory', () => {
  it('lists the realm’s members with the roles the realm granted', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(screen.getByText('Olga Operator')).toBeTruthy();
    expect(screen.getByText(/Plant Engineer/i)).toBeTruthy();   // ROLE_CONFIGS.engineer.label
  });

  it('shows a member with no console role as having none, not as a viewer', async () => {
    // Defaulting to viewer would tell an admin somebody has access they do not have.
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Olga Operator')).toBeTruthy());
    expect(screen.getByText(/No console role/i)).toBeTruthy();
  });

  it('says it cannot read the realm rather than showing an empty directory', async () => {
    // Spec success criterion 6.
    fetchRealmMembers.mockResolvedValue({ kind: 'forbidden' });
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText(/cannot read the realm/i)).toBeTruthy());
    expect(screen.queryByText(/no users/i)).toBeNull();
  });

  it('names where users are actually managed', async () => {
    fetchRealmMembers.mockResolvedValue({ kind: 'forbidden' });
    render(<UserManagementView />);

    // "names where to manage users instead" — an admin reading this needs the next step, not
    // just the diagnosis.
    await waitFor(() => expect(screen.getByText(/Keycloak/)).toBeTruthy());
  });

  it('reports an unreachable realm with its reason', async () => {
    fetchRealmMembers.mockResolvedValue({ kind: 'unreachable', detail: 'Failed to fetch' });
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText(/Failed to fetch/)).toBeTruthy());
  });

  it('does not ask the realm at all when the signed-in user is not an admin', async () => {
    auth.isAdmin = false;
    auth.roles = ['operator'];
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText(/administrator/i)).toBeTruthy());
    expect(fetchRealmMembers).not.toHaveBeenCalled();
  });
});

describe('what this screen can no longer do', () => {
  it('offers no way to create, edit or delete a user', async () => {
    // The realm owns the directory. A create button here would either lie or need
    // manage-users in a browser token.
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    const { container } = render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(container.textContent).not.toMatch(/add user|new user|create user|delete user/i);
  });

  it('offers no per-user permission tick boxes', async () => {
    // A permission stored in this browser is one the GraphQL service never sees. What a role
    // may do is ROLE_CONFIGS here and require.py there, and nothing in between.
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    const { container } = render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });
});
```

- [ ] **Step 5: Run both and watch them fail**

```bash
cd 11_frontend
npx vitest run src/lib/auth/directory.test.ts src/components/users
```

Expected: `directory.ts` does not resolve; the screen still destructures `auditLogs`,
`switchUser`, `toggleUserFeaturePermission` and `restoreDefaults` from `useAuth` at
`UserManagementView.tsx:43`–`:50`, none of which exist any more.

- [ ] **Step 6: Rewrite the screen**

`UserManagementView.tsx` keeps its `directory` and `roles` sub-tabs and loses `matrix` and
`audit`. The `matrix` tab was the per-user permission grid, and `audit` read `auditLogs`, which
the surfaces plan's Task 21 deleted — the realm keeps its own event log and the console is not a
second one.

The shape:

```tsx
type SubTab = 'directory' | 'roles';

export const UserManagementView: React.FC = () => {
  const { isAdmin } = useAuth();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('directory');
  const [result, setResult] = useState<DirectoryResult | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('ALL');

  useEffect(() => {
    if (!isAdmin) {
      return;
    }
    let cancelled = false;
    void fetchRealmMembers().then((next) => { if (!cancelled) setResult(next); });
    return () => { cancelled = true; };
  }, [isAdmin]);
  // ...
};
```

The four states the directory tab renders, and the exact words for the two that are not a list:

```tsx
  if (!isAdmin) {
    return <AccessRestricted feature="user_management" />;   // whatever Task 8 left it as
  }

  // result === null
  <EmptyState title="Reading the realm" body="Asking Keycloak who has access to this plant." />

  // result.kind === 'forbidden'
  <EmptyState
    title="This console cannot read the realm's user directory"
    body={`Your account is a console administrator, but the realm did not allow it to list users.
           That needs the realm-management view-users role. Users are managed in Keycloak at
           ${platformConfig.authBaseUrl}/admin/${platformConfig.authRealm}/console/.`}
  />

  // result.kind === 'unreachable'
  <EmptyState
    title="The realm did not answer"
    body={`${result.detail} Keycloak is at ${platformConfig.authBaseUrl}. Users are managed there.`}
  />
```

Use whichever `EmptyState` the surfaces plan settled on; if it takes different props, match them.
If the surfaces plan has not landed and no `EmptyState` exists in `src/` (there is none as of
2026-09-03), render the same copy in the panel style this screen already uses rather than
introducing a new component in a commit about the directory. The wording matters more than the
component: the `forbidden` copy names the missing role, because
that is the one thing an operator's administrator can act on.

Each row shows: display name, username, email, the role badge from
`ROLE_CONFIGS[member.roles[0]]` — or the words `No console role` when the array is empty — and a
`Disabled in Keycloak` marker when `enabled` is false. `member.roles[0]` is the highest role held,
for the same reason Task 8's `toAccount` uses it; if a member holds two, render both badges rather
than hiding one, since this screen exists precisely to answer "who can do what".

Delete: the `UserPlus` create button, `CreateUserModal` and `EditUserModal` and their imports,
`selectedUserForEdit`, the `Simulate` button at `:428`–`:434` (Task 8 already did this — if it is
still there, it means Task 8 was skipped, so stop and do Task 8), the `statusFilter` (the realm
has `enabled`, not three statuses), and every unused lucide import that `tsc` then names.

The `roles` sub-tab stays as it is and gets one sentence at the top:

> These are the console's five roles and what each may open. Which role a person holds is
> decided in Keycloak; what the GraphQL service accepts from that role is decided by the
> service, not by this screen.

That sentence is the whole point of keeping the tab: it is the only place in the UI that explains
the two-sided nature of the role table.

Then delete the modal files:

```bash
cd 11_frontend && rm -f src/components/users/CreateUserModal.tsx src/components/users/EditUserModal.tsx
```

- [ ] **Step 7: Run the suite**

```bash
cd 11_frontend
npx vitest run
npx tsc --noEmit
npm run build
```

Expected: green. Any surviving reference to the deleted modals or to `auditLogs` shows up here.

- [ ] **Step 8: Check it by hand**

Bring the stack up, sign in as `admin.user`, open Users.

- Expected: five people — `admin.user`, `engineer.user`, `operator.user`, `auditor.user`,
  `viewer.user` — each with the role the realm granted them.
- Then sign in as `engineer.user` and open the same screen. Expected: the access-restricted
  panel, and **no request to `/auth/admin/...` in the network panel**. The realm would refuse it
  anyway; not sending it is what stops the screen flashing a 403 at somebody who simply is not an
  administrator.

If the admin sees `forbidden`, the composite in Step 1 did not take. Check the token itself
rather than guessing — paste the access token into the browser console and look for
`resource_access['realm-management'].roles`:

```js
JSON.parse(atob(TOKEN.split('.')[1])).resource_access
```

If `view-users` is not there, the realm was imported before Step 1's edit. Keycloak does not
re-import a realm that already exists, so `docker compose down -v` for the Keycloak volume and
bring it back up. That is worth knowing generally: **every realm.json change in this plan needs
the Keycloak volume dropped to take effect.**

- [ ] **Step 9: Commit**

```bash
cd /c/Dev/manufacturing-uns
git add conf/keycloak/realm.json 00_uns_config/test/test_keycloak_realm.py \
        11_frontend/src/lib/auth/directory.ts 11_frontend/src/lib/auth/directory.test.ts \
        11_frontend/src/components/users
git commit -m "feat(console): list the realm's members, and say so when the realm refuses

The five seeded people are gone. The directory is Keycloak's, read with the
signed-in admin's own token, which works because the admin realm role is now
composite with realm-management's view-users.

view-users and view-realm only — not manage-users. A browser token that could
create realm users is a much larger thing to leak, which is also why this screen
has no Add user button rather than a disabled one.

The refusal path is written and tested, not an afterthought: a 403 says which
role is missing and where users are actually managed. An empty directory would
read as a plant with no users.

The per-user permission grid is deleted. A permission ticked in a browser is one
the GraphQL service never sees; what a role may do is ROLE_CONFIGS here and
require.py there, with nothing in between."
```

**Definition of done:**
- The directory lists realm members with realm-granted roles (spec test 11).
- A 401/403 renders a statement naming `view-users` and the Keycloak URL, never an empty list
  (success criterion 6).
- A non-admin triggers no request to the admin API at all.
- No create/edit/delete user affordance and no permission tick boxes anywhere in `src/`.
- `admin` is the only role with a `realm-management` composite, and it has neither
  `manage-users` nor `realm-admin`.
- `npx vitest run`, `npx tsc --noEmit`, `npm run build` and
  `uv run pytest test/test_keycloak_realm.py` all green.

---

## Task 11: Grafana stops being anonymous, and HEALTH says what is still open

Two things, both about telling the truth on the screen.

ADR-0001 accepted anonymous Grafana as a known gap and named OIDC as the documented target. Task 1
already created the `uns-grafana` confidential client. This task turns it on — which closes the
gap and, as a side effect, means the embedded iframe can now fail in a way the console has to
handle.

And the console now has authentication in exactly two places: itself, and the GraphQL read
surface. The broker, the graph database, the historian and Kafka still have none. A console that
showed a sign-in screen and said nothing else would imply a secured platform. HEALTH says
otherwise, in the spec's own words.

**Files:**
- Modify: `docker-compose.yml:391`–`:406` (`uns_grafana` environment),
  `11_frontend/src/components/common/GrafanaEmbed.tsx`,
  `11_frontend/src/components/system/SystemHealthView.tsx`
- Create: `11_frontend/src/components/system/AuthenticationPanel.tsx`
- Test: `11_frontend/src/components/common/GrafanaEmbed.test.tsx`,
  `11_frontend/src/components/system/AuthenticationPanel.test.tsx` (both create)

**Interfaces:**
- Consumes: `platformConfig.authBaseUrl`, `.authRealm` (Task 2); `useAuth().session` (Task 8).
- Produces: `GrafanaEmbed` gains a same-origin sign-in fallback; `AuthenticationPanel`
  is rendered by `SystemHealthView`.
- Nothing consumes this further.

- [x] **Step 1: Read what is there**

```bash
cd /c/Dev/manufacturing-uns
sed -n '391,406p' docker-compose.yml
grep -n "grafana" conf/nginx*.conf 11_frontend/nginx*.conf 11_frontend/vite.config.ts 2>/dev/null
```

Expected: `GF_AUTH_ANONYMOUS_ENABLED: "true"`, `GF_AUTH_ANONYMOUS_ORG_ROLE: Admin`,
`GF_SECURITY_ALLOW_EMBEDDING: "true"`, `GF_SERVER_SERVE_FROM_SUB_PATH: "true"`,
`GF_SERVER_ROOT_URL: "http://localhost:8088/grafana/"`, and 3000 unpublished. Note the ADR's
claim is literally true: anonymous with org role `Admin` means anyone who reaches port 8088 can
edit dashboards.

Also note the proxy path — the iframe's `src` is `/grafana/d/...`, same origin as the console.
That is what makes Step 5's fallback detectable at all.

- [x] **Step 2: Verify the compose service matches Task 1**

Task 1 Step 10 already made the whole Grafana compose change — anonymous explicitly `"false"`,
`generic_oauth` against the realm, `GF_AUTH_OAUTH_AUTO_LOGIN`, the role mapping, and the
`uns_keycloak` dependency. This task does not edit `docker-compose.yml` again; it verifies the
change survived and nothing drifted:

```bash
cd /c/Dev/manufacturing-uns
grep -n "GF_AUTH_ANONYMOUS_ENABLED\|GF_AUTH_OAUTH_AUTO_LOGIN\|GF_AUTH_GENERIC_OAUTH_NAME" docker-compose.yml
```

Expected: one match each — `"false"`, `"true"`, `Keycloak` — all in `uns_grafana`'s environment.
If anything is missing or doubled, reconcile `uns_grafana`'s environment to Task 1 Step 10's
block here, rather than editing anything else.

One value deserves re-reading rather than just grepping. `GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT: "false"`
decides what a realm user with none of the five console roles gets: with it `true` they are
refused a Grafana session entirely; with it `false` the JMESPath's final `|| 'Viewer'` gives
them a read-only one. `false` is right *here* because the console already gates the HEALTH
screen on `system_ops`, so nobody reaches the iframe without a recognised role. If that gate is
ever removed, this flips.

- [ ] **Step 3: Add the secret plumbing check**

Task 1 added `UNS_keycloak__grafana_client_secret` to the secrets helper. Confirm it actually
reaches compose, because a missing interpolation here is a Grafana that starts and then refuses
every sign-in with an opaque `invalid_client`:

```bash
cd /c/Dev/manufacturing-uns
uv run python -m uns_config.compose_env > /dev/null && docker compose config | grep -A 2 GENERIC_OAUTH_CLIENT_SECRET
```

Expected: a non-empty value. Use whatever command Task 1's step actually established for
generating the compose env — read Task 1 rather than trusting this line — and if the value comes
out empty, fix it here before going further.

- [x] **Step 4: Write the failing embed test**

Create `11_frontend/src/components/common/GrafanaEmbed.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GrafanaEmbed, grafanaKioskPath } from './GrafanaEmbed';

describe('grafanaKioskPath', () => {
  it('is same-origin, which is what makes the sign-in check possible', () => {
    expect(grafanaKioskPath('uns-oee', 'dark')).toMatch(/^\/grafana\/d\/uns-oee\?/);
  });
});

describe('GrafanaEmbed', () => {
  it('renders the dashboard', () => {
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);

    const frame = container.querySelector('iframe');
    expect(frame?.getAttribute('src')).toContain('/grafana/d/uns-oee');
  });

  it('offers a way into Grafana when the frame lands on its sign-in page', async () => {
    // Grafana is no longer anonymous. If its own OIDC round trip does not complete inside the
    // iframe, the operator sees a blank rectangle and no way forward — so say so and give
    // them a full-page link, where a redirect can actually happen.
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);
    const frame = container.querySelector('iframe') as HTMLIFrameElement;

    // Same origin, so the console can read where the frame ended up.
    Object.defineProperty(frame, 'contentWindow', {
      configurable: true,
      value: { location: { pathname: '/grafana/login' } },
    });
    frame.dispatchEvent(new Event('load'));

    await waitFor(() => expect(screen.getByText(/Sign in to Grafana/i)).toBeTruthy());
    const link = screen.getByRole('link', { name: /Sign in to Grafana/i });
    expect(link.getAttribute('href')).toContain('/grafana/');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it('shows nothing extra when the dashboard loads', async () => {
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);
    const frame = container.querySelector('iframe') as HTMLIFrameElement;
    Object.defineProperty(frame, 'contentWindow', {
      configurable: true,
      value: { location: { pathname: '/grafana/d/uns-oee' } },
    });
    frame.dispatchEvent(new Event('load'));

    await waitFor(() => expect(container.querySelector('iframe')).toBeTruthy());
    expect(screen.queryByText(/Sign in to Grafana/i)).toBeNull();
  });

  it('shows nothing extra when the frame cannot be inspected at all', async () => {
    // A cross-origin Grafana would throw on contentWindow.location. Guessing "signed out"
    // from that would put a false sign-in prompt over a working dashboard.
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);
    const frame = container.querySelector('iframe') as HTMLIFrameElement;
    Object.defineProperty(frame, 'contentWindow', {
      configurable: true,
      get() { throw new DOMException('Blocked a frame', 'SecurityError'); },
    });
    frame.dispatchEvent(new Event('load'));

    await waitFor(() => expect(container.querySelector('iframe')).toBeTruthy());
    expect(screen.queryByText(/Sign in to Grafana/i)).toBeNull();
  });
});
```

- [x] **Step 5: Add the fallback to `GrafanaEmbed`**

Keep `GRAFANA_DASHBOARDS`, `GrafanaDashboardId`, `grafanaTopicFilter`, `grafanaRangeFromPreset`
and `grafanaKioskPath` exactly as they are — `SystemHealthView.tsx:5`–`:8` imports the first
three from here, and moving them is the surfaces plan's business, not this task's.

The component gains one piece of state:

```tsx
export const GrafanaEmbed: React.FC<GrafanaEmbedProps> = ({ uid, theme, title, vars, from, to, className = '...' }) => {
  const src = grafanaKioskPath(uid, theme, { vars, from, to });
  const [signedOut, setSignedOut] = useState(false);

  /**
   * Grafana is not anonymous any more, and an iframe cannot report an HTTP status — `load`
   * fires for a sign-in page as readily as for a dashboard. What it can report is *where it
   * ended up*, because nginx serves /grafana from the console's own origin.
   *
   * A path under /login means Grafana's OIDC round trip did not complete inside the frame,
   * usually because the browser is blocking something about a redirect chain in third-party
   * context. The answer is a full-page link, where the same redirect can succeed.
   */
  const checkWhereItLanded = (event: React.SyntheticEvent<HTMLIFrameElement>) => {
    try {
      const path = event.currentTarget.contentWindow?.location?.pathname ?? '';
      setSignedOut(path.includes('/login'));
    } catch {
      // Cross-origin. Nothing can be concluded, so conclude nothing: a false sign-in prompt
      // over a working dashboard is worse than no prompt.
      setSignedOut(false);
    }
  };

  return (
    <div className="relative w-full h-full min-h-0">
      <iframe title={title} src={src} className={className} referrerPolicy="same-origin" onLoad={checkWhereItLanded} />
      {signedOut && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[#111114]/95 text-center px-6">
          <p className="text-xs font-bold text-[#F8FAFC]">Grafana needs its own sign-in</p>
          <p className="text-[11px] text-[#94A3B8] max-w-md">
            The dashboards are served by Grafana, which signs in against the same Keycloak realm
            as this console. It could not complete that inside this panel.
          </p>
          <a
            href="/grafana/"
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 rounded bg-[#FFC107] text-[#0F172A] text-[11px] font-bold uppercase tracking-wider"
          >
            Sign in to Grafana
          </a>
        </div>
      )}
    </div>
  );
};
```

Wrapping the iframe in a `div` changes the layout contract: the iframe's `h-full` now measures the
new wrapper rather than the parent. `SystemHealthView.tsx:49` puts it in a `flex-1 min-h-0`, which
the wrapper's `w-full h-full min-h-0` passes through — but check every other call site of
`GrafanaEmbed` for one that relied on the iframe being the direct child, and check the panel is
still full height in the browser rather than collapsed to nothing.

- [x] **Step 6: Write the failing authentication panel test**

Create `11_frontend/src/components/system/AuthenticationPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    session: { subject: 's', username: 'erin', displayName: 'Erin Engineer', roles: ['engineer'] },
    isAuthenticated: true,
  }),
}));

import { AuthenticationPanel } from './AuthenticationPanel';

describe('AuthenticationPanel', () => {
  it('says exactly what is protected and what is not', () => {
    // Spec section 11, verbatim. This sentence is the panel's whole reason to exist: a
    // console that shows a sign-in screen and says nothing else implies a secured platform.
    const { container } = render(<AuthenticationPanel />);
    const text = container.textContent?.replace(/\s+/g, ' ') ?? '';

    expect(text).toContain(
      'Sign-in protects the console and the GraphQL read surface. The MQTT broker, the graph ' +
      'database, the historian and the Kafka broker have no authentication on this deployment.',
    );
  });

  it('names the realm, so an integrator can find it', () => {
    const { container } = render(<AuthenticationPanel />);

    expect(container.textContent).toContain('/auth/realms/uns');
  });

  it('shows who is signed in and with which roles', () => {
    render(<AuthenticationPanel />);

    expect(screen.getByText(/Erin Engineer/)).toBeTruthy();
    expect(screen.getByText(/Plant Engineer/)).toBeTruthy();
  });
});
```

- [x] **Step 7: Write `AuthenticationPanel.tsx`**

Create `11_frontend/src/components/system/AuthenticationPanel.tsx`. Four facts, no more: who is
signed in, which roles they hold, where the realm is, and what sign-in does and does not cover.

```tsx
/**
 * What authentication on this deployment actually covers.
 *
 * This panel exists because the alternative is worse. A console with a sign-in screen and no
 * statement of scope implies a secured platform, and an integration engineer who believes
 * that will expose the broker. The sentence in here is quoted from the specification and
 * asserted verbatim by the test — if the deployment changes so that it is no longer true,
 * that test failing is the point.
 */

import React from 'react';
import { ShieldCheck } from 'lucide-react';

import { useAuth } from '../../context/AuthContext';
import { platformConfig } from '../../lib/platform/config';
import { ROLE_CONFIGS } from '../../types/rbac';

export const AuthenticationPanel: React.FC = () => {
  const { session } = useAuth();

  return (
    <section className="border border-[#1E293B] rounded bg-[#111114] p-4 space-y-3">
      <h2 className="text-[11px] font-bold uppercase tracking-wider text-[#F8FAFC] flex items-center gap-2">
        <ShieldCheck className="w-3.5 h-3.5 text-[#FFC107]" />
        <span>Authentication</span>
      </h2>

      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1.5 text-[11px]">
        <dt className="text-[#64748B]">Signed in as</dt>
        <dd className="text-[#F8FAFC]">{session?.displayName ?? 'Not signed in'}</dd>

        <dt className="text-[#64748B]">Roles</dt>
        <dd className="text-[#F8FAFC]">
          {session?.roles.length
            ? session.roles.map((role) => ROLE_CONFIGS[role].label).join(', ')
            : 'No console role'}
        </dd>

        <dt className="text-[#64748B]">Realm</dt>
        <dd className="font-mono text-[#94A3B8] break-all">
          {`${platformConfig.authBaseUrl}/realms/${platformConfig.authRealm}`}
        </dd>
      </dl>

      <p className="text-[11px] leading-relaxed text-[#94A3B8]">
        Sign-in protects the console and the GraphQL read surface. The MQTT broker, the graph
        database, the historian and the Kafka broker have no authentication on this deployment.
      </p>
    </section>
  );
};
```

The `break-all` on the realm URL is not decoration: it is a long same-line string in a dense
panel, and without it the grid column blows out and pushes the sentence off screen.

- [x] **Step 8: Put it on the HEALTH screen**

`SystemHealthView.tsx` is currently a header and a full-bleed iframe. The panel goes in a column
beside or above the embed — read the surfaces plan's HEALTH task and put it where that task says,
so the two do not fight over the layout. If the surfaces plan has not reworked this screen, the
smallest honest change is a strip under the header:

```tsx
      <div className="px-6 py-3 border-b border-[#1E293B] shrink-0">
        <AuthenticationPanel />
      </div>

      <div className="flex-1 min-h-0">
        <GrafanaEmbed uid={active.uid} theme={isDark ? 'dark' : 'light'} title={active.label} />
      </div>
```

The `shrink-0` and the embed's `flex-1 min-h-0` together are what keep the panes scrolling rather
than the shell.

- [ ] **Step 9: Check it by hand**

This is the step that finds the real problems, because Grafana's OIDC round trip cannot be
unit-tested.

```bash
cd /c/Dev/manufacturing-uns
uv run uns_compose up -d uns_keycloak uns_grafana
docker compose logs -f uns_grafana | grep -i "oauth\|invalid_client\|error"
```

(`uns_compose`, not plain `docker compose`, for the `up`: only the wrapper loads
`conf/.secrets.yaml`, and without it `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET` interpolates to empty
and every sign-in fails with an opaque `invalid_client`. Reading logs needs no secrets.)

Then in the browser:

1. Sign in to the console as `engineer.user`, open Health. The Grafana panel should render a
   dashboard with no visible sign-in step — `GF_AUTH_OAUTH_AUTO_LOGIN` plus the shared realm
   cookie.
2. Check the role mapping took: open `/grafana/` directly and look at the user's org role. An
   engineer should be `Editor`, an operator `Viewer`.
3. Confirm the gap is closed. In a private window, with no console session, open
   `http://localhost:8088/grafana/`. Expected: Keycloak's sign-in page, not a dashboard. If a
   dashboard appears, anonymous is still on and ADR-0001's gap is still open.
4. If the embedded panel shows the `Sign in to Grafana` fallback, that is the fallback working —
   but find out why before accepting it. `invalid_client` in the logs means Step 3's secret;
   a redirect-uri mismatch means Task 1's `uns-grafana` `redirectUris` does not match
   `GF_SERVER_ROOT_URL` + `/login/generic_oauth`.

- [x] **Step 10: Update ADR-0001**

ADR-0001 says anonymous Grafana is "a known security gap, deliberately accepted" with OIDC as
"the documented target". That is now false. Do not rewrite the decision — add a status note
pointing at ADR-0009, which Task 12 writes:

```markdown
> **Superseded in part (2026-09):** the anonymous-access gap described below is closed.
> Grafana now signs in against the platform's Keycloak realm with `generic_oauth`, and realm
> roles map to Grafana org roles. See ADR-0009. The rest of this record — why Grafana is
> proxied under `/grafana` and why port 3000 is unpublished — still stands.
```

- [ ] **Step 11: Commit**

```bash
cd /c/Dev/manufacturing-uns
git add docker-compose.yml docs/adr/0001-*.md \
        11_frontend/src/components/common/GrafanaEmbed.tsx \
        11_frontend/src/components/common/GrafanaEmbed.test.tsx \
        11_frontend/src/components/system
git commit -m "feat(observability): Grafana signs in against the realm, and Health says what is still open

ADR-0001 accepted anonymous Grafana with org role Admin as a known gap and named
OIDC as the target. This is that target: anonymous off, generic_oauth on, and
realm roles mapped to org roles so an operator gets Viewer rather than the
ability to rewrite a plant dashboard mid-shift.

That makes the embedded iframe able to fail, so it can now say so. An iframe
cannot report an HTTP status, but it can report where it landed — /grafana is
same-origin — and a path under /login gets a full-page sign-in link. A
cross-origin frame that cannot be inspected concludes nothing, because a false
sign-in prompt over a working dashboard is worse than none.

The Health screen now states the scope of authentication in one sentence, quoted
from the specification and asserted verbatim: the console and the GraphQL read
surface are protected, and the broker, graph database, historian and Kafka
broker are not. A console that showed a sign-in screen and said nothing else
would imply a secured platform."
```

**Definition of done:**
- Anonymous Grafana is off; an unauthenticated `/grafana/` shows Keycloak, not a dashboard.
- An engineer is `Editor` in Grafana and an operator is `Viewer`.
- The embed offers a full-page sign-in link when the frame lands on Grafana's login path, and
  offers nothing when the frame cannot be inspected — success criterion 7, taking the second
  half of it: the section 10 rough edge is honoured with a stated way forward rather than a
  blank panel.
- HEALTH carries spec section 11's sentence verbatim, asserted by a test — success criterion 9.
- ADR-0001 carries a superseded-in-part note — half of success criterion 8; Task 12 does the rest.
- `npx vitest run` and `npx tsc --noEmit` green.

---

## Task 12: The record of why this looks the way it does

Three ADRs to touch: one new, two amended. This is the last task and it is not optional — the
decisions in this plan are exactly the kind the repository keeps records of, and several of them
(a public client with no secret, a token that is deliberately lost on refresh, one gate on the
router rather than per-resolver) will look like oversights to whoever reads the code next.

**Files:**
- Create: `docs/adr/0009-oidc-authentication-for-console-and-graphql.md`
- Modify: `docs/adr/0005-*.md`, `CONTEXT.md`
- (ADR-0001 was amended in Task 11, Step 10.)

**Interfaces:** documentation only.

- [x] **Step 1: Match the house style**

```bash
cd /c/Dev/manufacturing-uns
ls docs/adr/
head -40 docs/adr/0008-*.md
```

Read one existing record before writing. Match its heading structure, its front matter if it has
any, and its length — a record three times longer than its neighbours does not get read.

- [x] **Step 2: Write ADR-0009**

Create `docs/adr/0009-oidc-authentication-for-console-and-graphql.md`, in whatever section
structure Step 1 found. The substance, which is what matters:

**Context.** Before this change the platform had no authentication anywhere. The console kept
five invented users in `localStorage` and a login that accepted any password; the GraphQL service
had none, and `assignDowntimeReason` took the author's name as an argument with a description
that said so out loud; Grafana was anonymous with org role `Admin`. The console is a static
bundle with no backend of its own (ADR-0005), which rules out a server-side session.

**Decision.** Keycloak in compose, provisioned from `conf/keycloak/realm.json`, served under
`/auth` on the console's own origin. The console is a **public** client using Authorization Code
with PKCE `S256`. The GraphQL service validates RS256 tokens against the realm's JWKS. Grafana is
a **confidential** client using `generic_oauth`.

**The consequences worth recording**, because each is a decision that looks wrong from the
outside:

1. **The console has no client secret, and that is correct.** A secret in a static bundle is
   published, not kept. PKCE is what replaces it.
2. **The access token lives in memory only, so a page refresh loses it.** `localStorage` is
   readable by any script on the origin, and identity in `localStorage` is precisely what made
   the previous design fake. A silent renew against the realm's SSO cookie restores the session,
   which works *because* Keycloak is on the console's own origin — first-party cookie. Moving
   Keycloak to its own port would break this, which is the real reason its port 8080 is
   unpublished.
3. **Authentication is one gate on the router, not a decorator on every resolver.** There is one
   `/graphql` route. A per-resolver check would be five queries plus six mutations of the same
   code, and the one that mattered would be the one somebody forgot on a new field.
4. **The two transports are gated differently, and that is not an inconsistency.** HTTP fails with
   401 from a FastAPI dependency. WebSocket cannot: `context_getter` runs before the
   `connection_init` frame arrives, so `connection_params` do not exist yet. The socket is
   therefore gated in an `on_ws_connect` override, which closes with 4403. A browser cannot set a
   header on a WebSocket handshake, which is why the token travels in the `connection_init`
   payload.
5. **Authorization is a six-row table, not a framework.** `MUTATION_ROLES` in `auth/require.py`
   names the roles for each of the six mutations, and every read is open to any authenticated
   role. Reads are open because the alternative — per-topic authorization over an ISA-95
   hierarchy — is a real feature with a real data model, and pretending to have it with a role
   check would be worse than not having it.
6. **The console's `ROLE_CONFIGS` and the service's `MUTATION_ROLES` are two tables and stay
   two tables.** The first decides which controls the console offers; the second decides what the
   server accepts. They are allowed to disagree, and when they do the server wins. A single
   shared table would imply the browser's copy was authoritative.
7. **What is still unauthenticated.** MQTT, Neo4j, TimescaleDB and Kafka. Signing in protects the
   console and the read surface, nothing else. The console states this on its HEALTH screen
   rather than leaving the reader to infer a secured platform. Closing those is a larger piece of
   work: broker ACLs, per-service credentials, and a decision about whether the simulator and the
   mappers hold their own identities.
8. **Impersonation is gone.** `switchUser` could not survive a real identity provider, and its
   removal is why `AccessRestricted` now names the required role instead of offering to become
   somebody who has it.

**Alternatives rejected**, briefly: a bespoke JWT issuer in the GraphQL service (it would need a
user store, a password policy and a reset flow — all things Keycloak already has); a
reverse-proxy-enforced auth like oauth2-proxy in front of `/graphql` (the service would still not
know who the caller was, and `assignDowntimeReason` has to record it); keeping tokens in
`localStorage` for a refresh-survivable session (the same class of exposure the old design had).

- [x] **Step 3: Amend ADR-0005**

ADR-0005 is the narrow-mutation-surface record and it contains the sentence *"There is no
authorization in this service."* That is now false, and it is the kind of false sentence somebody
copies into a new mutation. Amend it in place, keeping the original reasoning:

```markdown
> **Updated (2026-09):** this service now authenticates every request and authorizes every
> mutation against the caller's realm roles. See ADR-0009 for the design and
> `07_uns_graphql/src/uns_graphql/auth/require.py` for the table. The argument below — that the
> mutation surface stays narrow, and that a write belongs here only because the console has no
> backend of its own — is unchanged, and authentication does not widen it.
```

Find the exact sentence and leave it visible rather than deleting it; a record of a decision that
has moved on is more useful than a rewritten one that pretends it never said otherwise:

```bash
cd /c/Dev/manufacturing-uns && grep -rn "no authorization in this service" docs/ 07_uns_graphql/
```

Every hit outside `docs/adr/` is a code comment that is now wrong. Fix those too — in particular
check `mutations/alert_rule.py`'s module docstring and `mutations/oee.py`'s, since Task 6 already
rewrote the `assigned_by` description but not necessarily the surrounding prose.

- [x] **Step 4: Add the vocabulary to CONTEXT.md**

`CONTEXT.md` is the vocabulary the whole platform is described in, and this plan introduced terms
that are not in it. Add them in the file's existing style, and only these:

- **Realm** — the Keycloak realm `uns`, the authority on who exists and what roles they hold.
  Not "the auth server", not "the IdP".
- **Console role** — one of `admin`, `engineer`, `operator`, `auditor`, `viewer`. The GraphQL
  enum spells them upper case; the console spells them lower case; they are the same five.
- **Identity** — who a validated token says the caller is: subject, username, roles. The word
  used in `auth/token.py`.

Do not add "user", "permission" or "session" as defined terms. They are ordinary words here and
defining them would invite the reader to think they mean something specific.

- [x] **Step 5: Read the plan against the ADR**

The point of writing the record last is that it is a proofreading pass. Read ADR-0009 beside the
twelve tasks and check every claim it makes is one the code actually implements:

```bash
cd /c/Dev/manufacturing-uns
grep -rn "MUTATION_ROLES" 07_uns_graphql/src/ | head
grep -rn "localStorage" 11_frontend/src/lib/auth/ 11_frontend/src/context/AuthContext.tsx
grep -rn "GF_AUTH_ANONYMOUS_ENABLED" docker-compose.yml
grep -rn "no authentication anywhere" 07_uns_graphql/ 11_frontend/src/
```

Expected: `MUTATION_ROLES` has six entries; no `localStorage` in the auth modules or in
`AuthContext`; anonymous Grafana is `"false"`; and the phrase "no authentication anywhere" appears
nowhere — Task 6 removed it from `mutations/oee.py:67`, and if it survives anywhere else it is a
sentence the platform no longer means.

Any mismatch is either a defect in the code or an overstatement in the ADR. Fix whichever is
wrong. An ADR that describes a design the code does not have is worse than no ADR.

- [ ] **Step 6: Commit**

```bash
cd /c/Dev/manufacturing-uns
git add docs/adr/0009-oidc-authentication-for-console-and-graphql.md docs/adr/0005-*.md CONTEXT.md
git commit -m "docs(adr): record how authentication works and what it does not cover

ADR-0009. Several of these decisions read as oversights from outside, so each is
written down with its reason: the console has no client secret because a secret
in a static bundle is published; the token is lost on refresh because
localStorage is what made the old design fake; there is one gate on the router
rather than eleven decorators; and the two transports are gated differently
because a WebSocket's connection_params do not exist when context_getter runs.

ADR-0005 said 'There is no authorization in this service'. That sentence is left
visible and marked as moved on, because it is the kind of thing somebody copies
into a new mutation.

The record also states what is still open — MQTT, Neo4j, TimescaleDB and Kafka
have no authentication — which is the same sentence the Health screen shows. A
plan that closed the console's gap and left the reader to infer the rest would
be the more dangerous outcome."
```

**Definition of done:**
- `docs/adr/0009-oidc-authentication-for-console-and-graphql.md` exists, matches the house style,
  and records all eight consequences.
- ADR-0005's "no authorization in this service" is marked superseded, not deleted.
- ADR-0001 carries Task 11's note. With the two above, that is success criterion 8: ADR-0009
  exists and both ADR-0001 and ADR-0005 point to it.
- `CONTEXT.md` defines Realm, Console role and Identity.
- `grep -rn "no authentication anywhere"` over the repo returns nothing.
- Every claim in ADR-0009 is verified against the code by Step 5's greps.
