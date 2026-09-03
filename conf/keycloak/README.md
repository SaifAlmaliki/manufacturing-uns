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
