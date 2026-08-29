# uns_config

Loads the platform-wide configuration from the repository root `conf/` directory.

All UNS Python modules depend on this package. Do not add per-module `conf/settings.yaml` copies; use Dynaconf environments in the root file instead.

See [`../conf/README.md`](../conf/README.md) for setup instructions.
