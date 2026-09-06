# Cloud HTTPS seam

Date: 2026-09-06
Modules: `00_uns_config` (`compose_env`, settings loader), `conf/settings.yaml`,
`docker-compose.yml`
Status: Approved, not yet implemented

## 1. Problem

The console origin is hardcoded as `http://localhost:8088` in settings, compose
(`KC_HOSTNAME`, Grafana root and OAuth URLs), and `conf/keycloak/realm.json`.
Nginx in `uns_frontend` speaks HTTP only. That is correct on a laptop.

A later cloud Instance must serve the browser on `https://` and MQTT for plant
publishers on TLS, without baking a certificate into the UI image and without
locking the repo to Kubernetes, Caddy, or one cloud load balancer.

## 2. Decision

Config names the public origin and the MQTT dial address. TLS terminates later
at whatever edge sits in front (ingress, Caddy, ALB). Nginx stays inside
`uns_frontend` and stays HTTP. Same-origin `/auth` does not change (ADR-0009).

This slice is the seam only. It does not issue certificates, open `:8883`, or
turn on HiveMQ passwords on the laptop.

## 3. Public vs private

**Public on a cloud Instance (TLS at the edge):**

- Browser origin: `/`, `/graphql`, `/grafana`, `/auth`
- MQTT for plant publishers (username/password on HiveMQ; TLS on the pipe)

**Private (unpublished on the host, in-network only):**

- Neo4j `7474` / `7687`, Postgres `5432`, Kafka `9092`, Prometheus `9090`
- GraphQL `:8000` (the browser uses `/graphql` on the origin)
- HiveMQ admin `18080`, Grafana `3000`, Keycloak `8080`

Local compose may keep today's published ports. The cloud checklist is: do not
publish the private list; put TLS in front of the public list.

## 4. Architecture

```
[ later edge: certificate + 443 / 8883 ]
        │                    │
        ▼                    ▼
  uns_frontend:80          HiveMQ :1883 (compose net)
  (nginx, HTTP)            :8883 only when an edge maps it
        │
        ├── /          SPA
        ├── /graphql   graphql_server
        ├── /grafana   uns_grafana
        └── /auth      uns_keycloak
```

The edge is not in this repository yet. The repo's job is that flipping
`platform.public_origin` to `https://uns.example.com` retargets OIDC and Grafana
without forking `nginx.conf`.

## 5. Config

| Key | Local default | Cloud Instance |
| --- | --- | --- |
| `platform.public_origin` | `http://localhost:8088` | `https://uns.example.com` |
| `mqtt.public_host` | `localhost` | hostname plant connectors dial |
| `mqtt.public_port` | `1883` | `8883` |

Override: `UNS_PLATFORM__PUBLIC_ORIGIN`. A trailing slash is stripped.

**Derived from `public_origin` (not edited by hand):**

- `auth.base_url` = `{origin}/auth`
- `auth.issuer` = `{origin}/auth/realms/uns`
- `urls.cors_origins` includes `{origin}` if it is not already listed
- Grafana browser URLs on `{origin}`

The shipped `settings.yaml` `auth.*` and CORS entries stay equal to the
localhost derivation so a reader of the file is not lied to. Runtime consumers
use one helper in `00_uns_config`; they do not re-assemble these URLs. When
`UNS_PLATFORM__PUBLIC_ORIGIN` is set, the helper wins over the file literals.

`compose_environment()` exports `UNS_CONSOLE_ORIGIN` (no trailing slash).
`docker-compose.yml` interpolates:

- `KC_HOSTNAME: ${UNS_CONSOLE_ORIGIN}/auth`
- `GF_SERVER_ROOT_URL: ${UNS_CONSOLE_ORIGIN}/grafana/`
- `GF_AUTH_GENERIC_OAUTH_AUTH_URL: ${UNS_CONSOLE_ORIGIN}/auth/realms/uns/protocol/openid-connect/auth`

Laptop defaults of that helper equal today's hardcoded strings.

**Unchanged internals:**

- `auth.internal_base_url` = `http://uns_keycloak:8080` (JWKS inside the network)
- `mqtt.host` for mappers (compose already sets `uns_mqtt_broker`)
- SPA GraphQL path stays `/graphql` on the origin — never `:8000`

**Secrets:** reuse `mqtt.username` / `mqtt.password` already in
`.secrets_template.yaml`. Placeholders are valid locally.
`compose_environment()` must not require them. A public Instance fills them in
when HiveMQ auth is turned on (later).

**`conf/keycloak/realm.json`:** keep `http://localhost:8088` redirect URIs. When
an Instance has a hostname, add that origin's redirect and web-origin entries
by hand before first sign-in. No realm templating in this slice.

## 6. Out of scope

- TLS (or HTTP→HTTPS redirect) in `11_frontend/nginx.conf`
- A separate nginx / ingress service in compose
- HiveMQ listener `:8883` in the default `conf/hivemq/config.xml`
- Enforcing MQTT user/password on local HiveMQ
- cert-manager, Caddy, ALB, or Let's Encrypt in this repo
- Mutual TLS for publishers
- HTTPS on Neo4j, Postgres, Kafka, Prometheus, or GraphQL `:8000`
- Changing `npm run stack` behaviour on a laptop

## 7. Tests

Owner: `00_uns_config` (`test_compose_env.py`, settings loader tests).

1. Shipped `settings.yaml` has `platform.public_origin: http://localhost:8088`
   and `mqtt.public_host` / `mqtt.public_port` of `localhost` / `1883`.
2. The helper maps that origin to `/auth`, `/auth/realms/uns`, `/grafana/`, and
   the Grafana browser OAuth URL — matching today's compose literals.
3. `compose_environment()` exports `UNS_CONSOLE_ORIGIN`. Compose interpolations
   stay a subset of `COMPOSE_ENV_KEYS`.
4. `UNS_PLATFORM__PUBLIC_ORIGIN=https://uns.example.com` changes
   `UNS_CONSOLE_ORIGIN`. `auth.internal_base_url` stays
   `http://uns_keycloak:8080`.
5. Placeholder `mqtt.username` / `mqtt.password` do not fail `compose_environment()`.
6. Compose still does not publish Grafana `3000` or Keycloak `8080`.

HTTP `public_origin` is valid. The loader does not reject it (that would break
the laptop). A later cloud runbook states the public Instance must be `https://`.

## 8. Later (not this slice)

1. Edge terminates TLS for the console origin and MQTT `8883`.
2. HiveMQ requires `mqtt.username` / `mqtt.password` on the public listener.
3. Operator adds the `https://` origin to `realm.json` and recreates Keycloak.
4. Private ports stay off the public internet.
