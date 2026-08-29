# Platform configuration

All UNS modules read from this folder. Configure once per deployment; every service picks up the same instance name, URLs, and connection settings.

Do not add per-module `conf/settings.yaml` copies. Module-specific values (MQTT topics, Kafka client IDs, simulator payloads) belong under Dynaconf environments in this file.

## Setup

1. Edit [`settings.yaml`](./settings.yaml) for your environment (hosts, ports, instance name, CORS origins, MQTT topics).
2. Copy [`.secrets_template.yaml`](./.secrets_template.yaml) to [`.secrets.yaml`](./.secrets.yaml) and fill in credentials.
3. Optionally override any key via environment variables with the `UNS_` prefix (for example `UNS_PLATFORM__INSTANCE_NAME=PlantA`).

The frontend (`11_frontend`) reads `settings.yaml` automatically for GraphQL URL, dev server port, and display name.

## Per-module overrides

[`settings.yaml`](./settings.yaml) uses [Dynaconf environments](https://www.dynaconf.com/configuration/#environment-variables). Shared values live under `default`; module-specific overrides are under `graphql`, `graphdb`, `historian`, `kafka_mapper`, `sparkplugb`, and `simulator`.

## Docker

Images copy `settings.yaml` into `/app/conf` at build time and set `UNS_CONF_DIR=/app/conf`. For a live mount, use **this** directory (the repository-root `conf/`), not a per-module folder:

```bash
docker run --name uns_mqtt_graphdb -d \
  -v /path/to/manufacturing-uns/conf:/app/conf \
  -e UNS_CONF_DIR=/app/conf \
  uns/graphdb:latest
```

`docker-compose.yml` mounts `./conf:/app/conf` for every UNS service.
