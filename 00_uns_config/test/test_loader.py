"""Tests for the shared platform configuration loader."""

from pathlib import Path

from uns_config import PlatformConfig, get_settings, resolve_conf_dir


def test_resolve_conf_dir_points_to_repo_root():
    conf_dir = resolve_conf_dir()
    assert conf_dir.name == "conf"
    assert (conf_dir / "settings.yaml").is_file()


def test_default_settings_include_platform_and_mqtt():
    settings = get_settings("default")
    assert settings.get("platform.instance_name")
    assert settings.get("mqtt.host")


def test_graphql_environment_merges_module_overrides():
    settings = get_settings("graphql")
    assert settings.get("mqtt.topics") == ["#"]
    kafka_config = settings.get("kafka.config")
    assert kafka_config["client.id"] == "uns_graphql_server"


def test_platform_config_exposes_cors_origins():
    assert PlatformConfig.cors_origins
    assert PlatformConfig.frontend_dev_origin() in PlatformConfig.cors_origins


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
