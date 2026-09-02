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

COMPOSE_ENV_KEYS = ("UNS_graphdb__password", "UNS_historian__password", "PGPASSWORD")

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
    """Return the three compose interpolations from Dynaconf secrets.

    ``postgres.password`` is the Timescale image superuser (``postgres``).
    ``historian.password`` is the application role ``uns_dbuser``. They are
    different users; Python never connects as the superuser.
    """
    settings = settings or get_settings("default")
    graphdb_password = _secret(settings, "graphdb.password")
    historian_password = _secret(settings, "historian.password")
    postgres_password = _secret(settings, "postgres.password")

    missing: list[str] = []
    if graphdb_password is None:
        missing.append("graphdb.password")
    if historian_password is None:
        missing.append("historian.password")
    if postgres_password is None:
        missing.append("postgres.password")
    if missing:
        raise ValueError(
            "conf/.secrets.yaml is missing " + ", ".join(missing) + ". "
            "postgres.password is the Timescale/Postgres superuser used only to "
            "initialise the volume; historian.password is uns_dbuser, which every "
            "Python service uses for tables."
        )

    return {
        "UNS_graphdb__password": graphdb_password,
        "UNS_historian__password": historian_password,
        "PGPASSWORD": postgres_password,
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
