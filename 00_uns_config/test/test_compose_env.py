"""Compose interpolates only dotenv. Secrets live in conf/.secrets.yaml; this maps them."""

from pathlib import Path

import pytest
import yaml

from uns_config.compose_env import COMPOSE_ENV_KEYS, compose_environment
from uns_config.loader import get_settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"


def _write_conf(tmp_path: Path, secrets: dict) -> Path:
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "settings.yaml").write_text(
        "default:\n  mqtt:\n    host: localhost\ndynaconf_merge: true\n",
        encoding="utf-8",
    )
    (conf / ".secrets.yaml").write_text(
        yaml.safe_dump({"default": secrets, "dynaconf_merge": True}),
        encoding="utf-8",
    )
    return conf


def test_compose_environment_reads_secrets_yaml(monkeypatch, tmp_path: Path):
    conf = _write_conf(
        tmp_path,
        {
            "graphdb": {"password": "neo-secret"},
            "historian": {"password": "hist-secret"},
            "postgres": {"password": "super-secret"},
        },
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        env = compose_environment()
    finally:
        get_settings.cache_clear()

    assert env == {
        "UNS_graphdb__password": "neo-secret",
        "UNS_historian__password": "hist-secret",
        "PGPASSWORD": "super-secret",
    }


def test_compose_environment_rejects_missing_postgres_password(monkeypatch, tmp_path: Path):
    """postgres.password is the Timescale superuser. historian.password is the app role."""
    conf = _write_conf(
        tmp_path,
        {
            "graphdb": {"password": "neo-secret"},
            "historian": {"password": "hist-secret"},
        },
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="postgres.password"):
            compose_environment()
    finally:
        get_settings.cache_clear()


def test_compose_file_interpolates_only_the_mapped_secret_keys():
    """If compose gains a new ${SECRET} it must be added to compose_environment()."""
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    for key in COMPOSE_ENV_KEYS:
        assert f"${{{key}}}" in text
    assert "${UNS_graphdb__password}" in text
    assert "${UNS_historian__password}" in text
    assert "${PGPASSWORD}" in text
