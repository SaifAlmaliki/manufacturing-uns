"""Map conf/.secrets.yaml into the env vars docker compose interpolates.

Compose cannot read YAML. Neo4j and Timescale official images also cannot: they
need NEO4J_AUTH and POSTGRES_PASSWORD at container create time. Python services
already load .secrets.yaml via Dynaconf; this module exists only so
`docker compose` can use the same file instead of a second root `.env`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from uns_config.loader import get_settings

COMPOSE_ENV_KEYS = (
    "UNS_graphdb__password",
    "UNS_historian__password",
    "PGPASSWORD",
    "UNS_keycloak__admin_password",
    "UNS_keycloak__grafana_client_secret",
)

_PLACEHOLDER_PREFIX = "#<"


def _secret(settings, dotted_key: str) -> str | None:
    value = settings.get(dotted_key)
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.startswith(_PLACEHOLDER_PREFIX):
        return None
    return text


def compose_environment(settings=None) -> dict[str, str]:
    """Return the compose interpolations from Dynaconf secrets.

    ``postgres.password`` is the Timescale image superuser (``postgres``).
    ``historian.password`` is the application role ``uns_dbuser``. They are
    different users; Python never connects as the superuser. The keycloak
    values feed the realm import: the Grafana client secret must match what
    Keycloak imports from conf/keycloak/realm.json.
    """
    settings = settings or get_settings("default")
    graphdb_password = _secret(settings, "graphdb.password")
    historian_password = _secret(settings, "historian.password")
    postgres_password = _secret(settings, "postgres.password")
    keycloak_admin_password = _secret(settings, "keycloak.admin_password")
    keycloak_grafana_secret = _secret(settings, "keycloak.grafana_client_secret")

    missing: list[str] = []
    if graphdb_password is None:
        missing.append("graphdb.password")
    if historian_password is None:
        missing.append("historian.password")
    if postgres_password is None:
        missing.append("postgres.password")
    if keycloak_admin_password is None:
        missing.append("keycloak.admin_password")
    if keycloak_grafana_secret is None:
        missing.append("keycloak.grafana_client_secret")
    if missing:
        raise ValueError(
            "conf/.secrets.yaml is missing " + ", ".join(missing) + ". "
            "postgres.password is the Timescale/Postgres superuser used only to "
            "initialise the volume; historian.password is uns_dbuser, which every "
            "Python service uses for tables; keycloak.grafana_client_secret must match "
            "the uns-grafana client in conf/keycloak/realm.json."
        )

    return {
        "UNS_graphdb__password": graphdb_password,
        "UNS_historian__password": historian_password,
        "PGPASSWORD": postgres_password,
        "UNS_keycloak__admin_password": keycloak_admin_password,
        "UNS_keycloak__grafana_client_secret": keycloak_grafana_secret,
    }


def main() -> None:
    """Run ``docker compose`` with secrets loaded from conf/.secrets.yaml."""
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("docker is not on PATH")

    env = {**os.environ, **compose_environment()}
    args = sys.argv[1:] or ["up", "-d"]
    completed = subprocess.run([docker, "compose", *args], env=env, check=False)
    raise SystemExit(completed.returncode)
