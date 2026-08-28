# Platform configuration

All UNS modules read from this folder. Configure once per deployment; every service picks up the same instance name, URLs, and connection settings.

## Setup

1. Edit [`settings.yaml`](./settings.yaml) for your environment (hosts, ports, instance name, CORS origins, MQTT topics).
2. Copy [`.secrets_template.yaml`](./.secrets_template.yaml) to `.secrets.yaml` and fill in credentials.
3. Optionally override any key via environment variables with the `UNS_` prefix (for example `UNS_PLATFORM__INSTANCE_NAME=PlantA`).

## Per-module overrides

[`settings.yaml`](./settings.yaml) uses [Dynaconf environments](https://www.dynaconf.com/configuration/#environment-variables). Shared values live under `default`; module-specific overrides are under `graphql`, `graphdb`, `historian`, `kafka_mapper`, `sparkplugb`, and `simulator`.

## Docker

Mount this directory at `/app/conf` and set:

```bash
export UNS_CONF_DIR=/app/conf
```
