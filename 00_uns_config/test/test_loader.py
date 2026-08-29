"""Tests for the shared platform configuration loader."""

from pathlib import Path

from uns_config import PlatformConfig, get_settings, resolve_conf_dir

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_conf_dir_points_to_repo_root():
    conf_dir = resolve_conf_dir()
    assert conf_dir.name == "conf"
    assert (conf_dir / "settings.yaml").is_file()
    assert conf_dir == (_REPO_ROOT / "conf").resolve()


def test_resolve_conf_dir_skips_legacy_module_conf(monkeypatch):
    """CI runs pytest from the module directory, which still has leftover conf/settings.yaml."""
    monkeypatch.chdir(_REPO_ROOT / "03_uns_graphdb")
    conf_dir = resolve_conf_dir()
    assert conf_dir == (_REPO_ROOT / "conf").resolve()


def test_default_settings_include_platform_and_mqtt():
    settings = get_settings("default")
    assert settings.get("platform.instance_name")
    assert settings.get("mqtt.host")


def test_graphql_environment_merges_module_overrides():
    settings = get_settings("graphql")
    assert settings.get("mqtt.topics") == ["#"]
    kafka_config = settings.get("kafka.config")
    assert kafka_config["client.id"] == "uns_graphql_server"


def test_graphdb_environment_merges_module_overrides(monkeypatch):
    monkeypatch.chdir(_REPO_ROOT / "03_uns_graphdb")
    get_settings.cache_clear()
    settings = get_settings("graphdb")
    assert settings.get("mqtt.topics") == ["test/uns/#", "ManufacturingCo/#", "spBv1.0/uns_group/#"]
    get_settings.cache_clear()


def test_platform_config_exposes_cors_origins():
    assert PlatformConfig.cors_origins
    assert PlatformConfig.frontend_dev_origin() in PlatformConfig.cors_origins


def test_get_settings_does_not_crash_when_conf_dir_is_missing(monkeypatch, tmp_path: Path):
    """Docker smoke tests import the app with no /app/conf mount; Dynaconf must not OSError."""
    missing = tmp_path / "no-such-conf"
    assert not missing.exists()
    monkeypatch.setattr("uns_config.loader.resolve_conf_dir", lambda: missing)
    get_settings.cache_clear()
    settings = get_settings("graphdb")
    assert settings.get("mqtt.topics", ["#"]) is not None
    get_settings.cache_clear()


def test_conf_dir_override_via_env_var(monkeypatch, tmp_path: Path):
    custom_conf = tmp_path / "custom-conf"
    custom_conf.mkdir()
    (custom_conf / "settings.yaml").write_text(
        "default:\n  platform:\n    instance_name: CustomInstance\ndynaconf_merge: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(custom_conf))
    get_settings.cache_clear()

    settings = get_settings("default")
    assert settings.get("platform.instance_name") == "CustomInstance"

    get_settings.cache_clear()
    monkeypatch.delenv("UNS_CONF_DIR", raising=False)
