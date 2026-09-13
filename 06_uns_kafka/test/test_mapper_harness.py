"""Unit tests for live MQTT mapper test helpers."""

from __future__ import annotations

from mapper_harness import patch_unique_ingestion_config, wait_until

from uns_kafka.uns_kafka_config import IngestionSettings


def test_patch_unique_ingestion_config_does_not_reuse_settings_client_id(monkeypatch):
    original = IngestionSettings.config.client_id
    client_id = patch_unique_ingestion_config(monkeypatch)
    assert client_id != original
    assert client_id.startswith("uns_kafka_ingest-test-")
    assert IngestionSettings.config.client_id == client_id
    assert IngestionSettings.config.shard_id.startswith("test-")


def test_wait_until_returns_false_when_condition_never_holds():
    assert wait_until(lambda: False, timeout_s=0.05, sleep_s=0.01) is False


def test_wait_until_returns_true_when_condition_holds():
    assert wait_until(lambda: True, timeout_s=0.05) is True
