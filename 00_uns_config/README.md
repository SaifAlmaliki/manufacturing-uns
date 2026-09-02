# uns_config

Loads the platform-wide configuration from the repository root `conf/` directory.

All UNS Python modules depend on this package. Do not add per-module `conf/settings.yaml` copies; use Dynaconf environments in the root file instead.

See [`../conf/README.md`](../conf/README.md) for setup instructions.

`uv run uns_compose` loads `conf/.secrets.yaml` and runs `docker compose` with the
passwords official images need (`NEO4J_AUTH`, `POSTGRES_PASSWORD`). Python services
read the same file directly; they do not use a root `.env`.
