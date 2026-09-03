"""Compose interpolates only dotenv. Secrets live in conf/.secrets.yaml; this maps them."""

import re
from pathlib import Path

import pytest
import yaml

from uns_config.compose_env import COMPOSE_ENV_KEYS, compose_environment
from uns_config.loader import get_settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"
_SECRETS_TEMPLATE = _REPO_ROOT / "conf" / ".secrets_template.yaml"

_KEYCLOAK_SECRETS = {
    "keycloak": {
        "admin_password": "kc-admin-secret",
        "grafana_client_secret": "kc-grafana-secret",
    }
}


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
            **_KEYCLOAK_SECRETS,
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
        "UNS_keycloak__admin_password": "kc-admin-secret",
        "UNS_keycloak__grafana_client_secret": "kc-grafana-secret",
    }


def test_compose_environment_rejects_missing_postgres_password(monkeypatch, tmp_path: Path):
    """postgres.password is the Timescale superuser. historian.password is the app role."""
    conf = _write_conf(
        tmp_path,
        {
            "graphdb": {"password": "neo-secret"},
            "historian": {"password": "hist-secret"},
            **_KEYCLOAK_SECRETS,
        },
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="postgres.password"):
            compose_environment()
    finally:
        get_settings.cache_clear()


def test_compose_environment_rejects_placeholder_passwords(monkeypatch, tmp_path: Path):
    """An unfilled template value is a missing value, not a password."""
    conf = _write_conf(
        tmp_path,
        {
            "graphdb": {"password": "#<enter the password for the graph database>"},
            "historian": {"password": "hist-secret"},
            "postgres": {"password": "super-secret"},
            **_KEYCLOAK_SECRETS,
        },
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="graphdb.password"):
            compose_environment()
    finally:
        get_settings.cache_clear()


def test_compose_environment_rejects_missing_keycloak_secrets(monkeypatch, tmp_path: Path):
    """The realm import substitutes ${VAR} from the container env; a missing secret
    would silently become an empty string in a demo password."""
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
        with pytest.raises(ValueError, match="keycloak.grafana_client_secret"):
            compose_environment()
    finally:
        get_settings.cache_clear()


def test_compose_file_interpolations_match_helper():
    """Every ${VAR} in docker-compose.yml must be a name compose_environment provides.

    $${VAR} is compose's escape for container-runtime expansion (the tsdb_setup_script
    command uses it), so only a ${ not preceded by another $ counts as interpolation.
    """
    compose_text = _COMPOSE_FILE.read_text(encoding="utf-8")
    referenced = set(re.findall(r"(?<!\$)\$\{(\w+)\}", compose_text))
    provided = set(COMPOSE_ENV_KEYS)
    assert referenced <= provided, (
        "docker-compose.yml references env vars uns_compose does not provide: "
        + ", ".join(sorted(referenced - provided))
    )


def test_secrets_template_covers_every_required_key():
    """The template is the checklist a new deployment follows. If a key is required
    but absent from it, a fresh copy of the template cannot start the stack."""
    template = yaml.safe_load(_SECRETS_TEMPLATE.read_text(encoding="utf-8"))
    keycloak = template["default"]["keycloak"]
    for key in ("admin_password", "grafana_client_secret"):
        assert key in keycloak, f".secrets_template.yaml is missing keycloak.{key}"
