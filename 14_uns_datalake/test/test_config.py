"""Configuration validation tests."""

import pytest

from uns_datalake.config import (
    DEFAULT_MINIO_ENDPOINT,
    DatalakeConfig,
    S3Settings,
    validate_s3_credential_pair,
)


def test_default_kafka_topic_and_group():
    assert DatalakeConfig.historic_topic == "uns.historic-events"
    assert DatalakeConfig.group_id == "uns_datalake"


def test_kafka_consumer_config_disables_auto_commit():
    config = DatalakeConfig.kafka_consumer_config()
    assert config["enable.auto.commit"] is False
    assert config["enable.auto.offset.store"] is False


def test_flush_defaults_match_design():
    limits = DatalakeConfig.flush
    assert limits.interval_seconds == 60.0
    assert limits.max_bytes == 8_388_608
    assert limits.max_records == 10_000
    assert limits.worker_max_buffered_bytes == 32 * 1024 * 1024


def test_partial_s3_credentials_are_rejected():
    with pytest.raises(ValueError, match="together"):
        validate_s3_credential_pair("abc", None)


def test_adls_backend_requires_account_and_container(monkeypatch):
    monkeypatch.setattr(DatalakeConfig, "backend", "adls")

    def fake_get(key, default=None):
        return default

    monkeypatch.setattr("uns_datalake.config.settings.get", fake_get)
    with pytest.raises(ValueError, match="account"):
        DatalakeConfig.validate_backend()


def test_resolve_s3_credentials_uses_minio_root_for_default_endpoint():
    s3 = S3Settings(
        bucket="bucket",
        region="us-east-1",
        endpoint_url=DEFAULT_MINIO_ENDPOINT,
        access_key_id=None,
        secret_access_key=None,
    )
    access, secret = DatalakeConfig.resolve_s3_credentials(
        s3,
        minio_user="minioadmin",
        minio_password="minioadmin",
    )
    assert access == "minioadmin"
    assert secret == "minioadmin"
