---
status: accepted
---

# OIDC authentication for the console and the GraphQL service

Date: 2026-09-03

## Status

Accepted

## Context

Before this change the platform had no authentication anywhere. The console kept
five invented users in `localStorage` and a login that accepted any password; the
GraphQL service had none, and `assignDowntimeReason` took the author's name as an
argument whose own description said so out loud; Grafana was anonymous with org
role `Admin`. The console is a static bundle with no backend of its own
(ADR-0005), which rules out a server-side session.

## Decision

Keycloak runs in compose, provisioned from `conf/keycloak/realm.json`, served
under `/auth` on the console's own origin. The console is a **public** client
using Authorization Code with PKCE `S256`. The GraphQL service validates RS256
tokens against the realm's JWKS. Grafana is a **confidential** client using
`generic_oauth`.

## Consequences

Each of these is a decision that looks wrong from the outside, so each is written
down with its reason.

1. **The console has no client secret, and that is correct.** A secret in a
   static bundle is published, not kept. PKCE is what replaces it.
2. **The access token lives in memory only, so a page refresh loses it.**
   `localStorage` is readable by any script on the origin, and identity in
   `localStorage` is precisely what made the previous design fake. A silent renew
   against the realm's SSO cookie restores the session, which works *because*
   Keycloak is on the console's own origin — first-party cookie. Moving Keycloak
   to its own port would break this, which is the real reason its port 8080 is
   unpublished.
3. **Authentication is one gate on the router, not a decorator on every
   resolver.** There is one `/graphql` route. A per-resolver check would be five
   queries plus six mutations of the same code, and the one that mattered would
   be the one somebody forgot on a new field.
4. **The two transports are gated differently, and that is not an
   inconsistency.** HTTP fails with 401 from a FastAPI dependency. WebSocket
   cannot: `context_getter` runs before the `connection_init` frame arrives, so
   `connection_params` do not exist yet. The socket is therefore gated in an
   `on_ws_connect` override, which closes with 4403. A browser cannot set a
   header on a WebSocket handshake, which is why the token travels in the
   `connection_init` payload.
5. **Authorization is a six-row table, not a framework.** `MUTATION_ROLES` in
   `auth/require.py` names the roles for each of the six mutations, and every
   read is open to any authenticated role. Reads are open because the alternative
   — per-topic authorization over an ISA-95 hierarchy — is a real feature with a
   real data model, and pretending to have it with a role check would be worse
   than not having it.
6. **The console's `ROLE_CONFIGS` and the service's `MUTATION_ROLES` are two
   tables and stay two tables.** The first decides which controls the console
   offers; the second decides what the server accepts. They are allowed to
   disagree, and when they do the server wins. A single shared table would imply
   the browser's copy was authoritative.
7. **What is still unauthenticated.** MQTT, Neo4j, TimescaleDB and Kafka.
   Signing in protects the console and the read surface, nothing else. The
   console states this on its HEALTH screen rather than leaving the reader to
   infer a secured platform. Closing those is a larger piece of work: broker
   ACLs, per-service credentials, and a decision about whether the simulator and
   the mappers hold their own identities.
8. **Impersonation is gone.** `switchUser` could not survive a real identity
   provider, and its removal is why `AccessRestricted` now names the required
   role instead of offering to become somebody who has it.

## Alternatives rejected

A bespoke JWT issuer in the GraphQL service: it would need a user store, a
password policy and a reset flow — all things Keycloak already has. A
reverse-proxy-enforced auth like oauth2-proxy in front of `/graphql`: the service
would still not know who the caller was, and `assignDowntimeReason` has to record
it. Keeping tokens in `localStorage` for a refresh-survivable session: the same
class of exposure the old design had.
