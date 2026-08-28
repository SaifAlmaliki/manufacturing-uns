# Platform configuration

All UNS modules read from this folder. Configure once per deployment; every service picks up the same instance name, URLs, and connection settings.

## Setup

1. Edit [`settings.yaml`](./settings.yaml) for your environment (hosts, ports, instance name, CORS origins, MQTT topics).
2. Edit [`.secrets.yaml`](./.secrets.yaml) with your credentials (initial local-dev values are pre-filled).
3. Optionally override any key via environment variables with the `UNS_` prefix (for example `UNS_PLATFORM__INSTANCE_NAME=PlantA`).

The frontend (`10_frontend`) reads `settings.yaml` automatically for GraphQL URL, dev server port, and display name.

## Per-module overrides

[`settings.yaml`](./settings.yaml) uses [Dynaconf environments](https://www.dynaconf.com/configuration/#environment-variables). Shared values live under `default`; module-specific overrides are under `graphql`, `graphdb`, `historian`, `kafka_mapper`, `sparkplugb`, and `simulator`.

## Docker

Mount this directory at `/app/conf` and set:

```bash
export UNS_CONF_DIR=/app/conf
```
