"""Object store adapter tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from uns_datalake.config import AdlsSettings, DatalakeConfig, S3Settings
from uns_datalake.stores import AdlsObjectStore, FakeObjectStore, S3ObjectStore, build_s3_client, object_store_from_config


def test_fake_object_store_writes_immutable_bytes(tmp_path: Path):
    store = FakeObjectStore(root=tmp_path)
    store.put("v1/ingest_date=2026-09-09/hour=10/partition=0/a.parquet", b"abc")
    assert store.objects["v1/ingest_date=2026-09-09/hour=10/partition=0/a.parquet"] == b"abc"
    assert (tmp_path / "v1/ingest_date=2026-09-09/hour=10/partition=0/a.parquet").read_bytes() == b"abc"


def test_fake_object_store_can_simulate_failures(tmp_path: Path):
    store = FakeObjectStore(root=tmp_path)
    store.fail_paths.add("broken.parquet")
    with pytest.raises(RuntimeError):
        store.put("broken.parquet", b"x")


@patch("boto3.client")
def test_build_s3_client_uses_explicit_credentials(mock_client):
    s3 = S3Settings(
        bucket="bucket",
        region="us-east-1",
        endpoint_url="http://uns-minio:9000",
        access_key_id="key",
        secret_access_key="secret",
    )
    build_s3_client(s3)
    kwargs = mock_client.call_args.kwargs
    assert kwargs["endpoint_url"] == "http://uns-minio:9000"
    assert kwargs["aws_access_key_id"] == "key"


@patch("uns_datalake.stores.build_s3_client")
def test_object_store_from_config_selects_s3(mock_build):
    mock_build.return_value = MagicMock()
    store = object_store_from_config()
    assert isinstance(store, S3ObjectStore)


@patch("uns_datalake.stores.build_adls_filesystem")
def test_adls_object_store_uploads_frozen_bytes(mock_build_fs):
    filesystem = MagicMock()
    file_client = MagicMock()
    filesystem.get_file_client.return_value = file_client
    mock_build_fs.return_value = filesystem
    store = AdlsObjectStore(filesystem=filesystem, directory="lake")
    store.put("v1/partition=0/a.parquet", b"data")
    filesystem.get_file_client.assert_called_once_with("lake/v1/partition=0/a.parquet")
    file_client.upload_data.assert_called_once_with(b"data", overwrite=True)


def test_adls_settings_validation(monkeypatch):
    monkeypatch.setattr(DatalakeConfig, "backend", "adls")
    with pytest.raises(ValueError):
        object_store_from_config()
