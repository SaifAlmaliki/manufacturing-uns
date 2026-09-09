from pathlib import Path

import pytest
import yaml

from uns_config.loader import get_settings
from uns_datalake.config import DEFAULT_MINIO_ENDPOINT, DatalakeConfig


def _write_conf(tmp_path: Path, settings: dict, secrets: dict) -> Path:
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "settings.yaml").write_text(
        yaml.safe_dump({"default": settings, "dynaconf_merge": True}),
        encoding="utf-8",
    )
    (conf / ".secrets.yaml").write_text(
        yaml.safe_dump({"default": secrets, "dynaconf_merge": True}),
        encoding="utf-8",
    )
    return conf


def test_defaults_match_spec():
    config = DatalakeConfig()
    assert config.backend == "s3"
    assert config.kafka_topic == "uns.historic-events"
    assert config.group_id == "uns_datalake"
    assert config.interval_seconds == 60
    assert config.max_bytes == 8388608
    assert config.s3_bucket == "uns-historic-events"
    assert config.s3_endpoint_url == DEFAULT_MINIO_ENDPOINT
    assert config.metrics_port == 9096


def test_default_minio_selects_root_pair(monkeypatch, tmp_path: Path):
    conf = _write_conf(
        tmp_path,
        {"datalake": {"s3": {"endpoint_url": DEFAULT_MINIO_ENDPOINT}}},
        {"minio": {"root_user": "minioadmin", "root_password": "minioadmin123"}},
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        config = DatalakeConfig.from_settings()
    finally:
        get_settings.cache_clear()
    assert config.s3_access_key == "minioadmin"
    assert config.s3_secret_key == "minioadmin123"


def test_empty_endpoint_with_only_minio_pair_leaves_keys_none(monkeypatch, tmp_path: Path):
    conf = _write_conf(
        tmp_path,
        {"datalake": {"s3": {"endpoint_url": ""}}},
        {"minio": {"root_user": "minioadmin", "root_password": "minioadmin123"}},
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        config = DatalakeConfig.from_settings()
    finally:
        get_settings.cache_clear()
    assert config.s3_access_key is None
    assert config.s3_secret_key is None


def test_empty_endpoint_with_explicit_s3_pair(monkeypatch, tmp_path: Path):
    conf = _write_conf(
        tmp_path,
        {"datalake": {"s3": {"endpoint_url": "", "access_key": "AKIA", "secret_key": "SECRET"}}},
        {},
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        config = DatalakeConfig.from_settings()
    finally:
        get_settings.cache_clear()
    assert config.s3_access_key == "AKIA"
    assert config.s3_secret_key == "SECRET"


def test_non_minio_endpoint_does_not_use_minio_root(monkeypatch, tmp_path: Path):
    conf = _write_conf(
        tmp_path,
        {"datalake": {"s3": {"endpoint_url": "http://custom:9000"}}},
        {"minio": {"root_user": "minioadmin", "root_password": "minioadmin123"}},
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        config = DatalakeConfig.from_settings()
    finally:
        get_settings.cache_clear()
    assert config.s3_access_key is None
    assert config.s3_secret_key is None


def test_half_explicit_s3_pair_raises(monkeypatch, tmp_path: Path):
    conf = _write_conf(
        tmp_path,
        {"datalake": {"s3": {"access_key": "AKIA"}}},
        {},
    )
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="access_key and secret_key"):
            DatalakeConfig.from_settings()
    finally:
        get_settings.cache_clear()


def test_adls_without_account_raises(monkeypatch, tmp_path: Path):
    conf = _write_conf(tmp_path, {"datalake": {"backend": "adls", "adls": {"account": "", "container": ""}}}, {})
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="adls"):
            DatalakeConfig.from_settings()
    finally:
        get_settings.cache_clear()


def test_kafka_bootstrap_from_env_json(monkeypatch, tmp_path: Path):
    conf = _write_conf(tmp_path, {"datalake": {}}, {})
    monkeypatch.setenv("UNS_CONF_DIR", str(conf))
    monkeypatch.setenv(
        "UNS_kafka__config",
        '@json {"bootstrap.servers": "broker.example:9092"}',
    )
    get_settings.cache_clear()
    try:
        config = DatalakeConfig.from_settings()
    finally:
        get_settings.cache_clear()
    assert config.bootstrap_servers == "broker.example:9092"
