# Module configuration moved

Platform configuration now lives at the repository root: [`../../conf/settings.yaml`](../../conf/settings.yaml).

Copy secrets from [`../../conf/.secrets_template.yaml`](../../conf/.secrets_template.yaml) to `../../conf/.secrets.yaml`.

This folder is kept for Docker volume mounts (`/app/conf`). Point `UNS_CONF_DIR` at the root `conf/` directory when running containers.
