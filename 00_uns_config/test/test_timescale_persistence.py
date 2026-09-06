"""Timescale must keep console catalogs across `docker compose down`.

Connectivity servers, subscribed OPC UA nodes, and credentials live in
`console.connectivity_*` on this database. Without a named volume those rows
die with the container; without an idempotent bootstrap the next `up` fails
because CREATE DATABASE already ran.
"""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"
_BOOTSTRAP = _REPO_ROOT / "04_uns_historian" / "sql_scripts" / "00_bootstrap.sh"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))


def test_timescale_data_survives_compose_down():
    """A named volume, not the container writable layer. `down` without -v keeps it."""
    compose = _compose()
    volumes = compose["services"]["uns_timescale_db"].get("volumes") or []
    assert "timescale_data:/var/lib/postgresql/data" in volumes
    assert "timescale_data" in compose["volumes"]


def test_tsdb_setup_reruns_against_an_existing_volume():
    """The one-shot job must not fail when the historian database already exists."""
    compose = _compose()
    setup = compose["services"]["tsdb_setup_script"]
    command = setup["command"]
    joined = " ".join(command) if isinstance(command, list) else command
    assert "/sql/00_bootstrap.sh" in joined
    assert _BOOTSTRAP.is_file()
    script = _BOOTSTRAP.read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in script
    assert "if_not_exists" in script
    assert "CREATE DATABASE" in script
