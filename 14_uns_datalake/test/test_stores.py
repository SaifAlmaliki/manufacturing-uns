"""Object store adapter tests."""

from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from uns_datalake.config import AdlsSettings, DatalakeConfig, S3Settings
from uns_datalake.publication import AccessDeniedError, IntegrityError
from uns_datalake.stores import AdlsObjectStore, FakeObjectStore, S3ObjectStore, build_s3_client, object_store_from_config


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


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


def test_fake_object_store_publish_exact_writes_and_verifies(tmp_path: Path):
    store = FakeObjectStore(root=tmp_path)
    data = b"parquet-bytes"
    digest = _digest(data)
    store.publish_exact("raw/v2/a.parquet", data, digest)
    store.verify_exact("raw/v2/a.parquet", digest, len(data))
    assert (tmp_path / "raw/v2/a.parquet").read_bytes() == data


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
    filesystem.get_file_client.assert_called_with("lake/v1/partition=0/a.parquet")
    file_client.upload_data.assert_called_once_with(b"data", overwrite=True)


def test_adls_settings_validation(monkeypatch):
    monkeypatch.setattr(DatalakeConfig, "backend", "adls")
    with pytest.raises(ValueError):
        object_store_from_config()


def test_s3_publish_exact_uses_if_none_match():
    client = MagicMock()
    store = S3ObjectStore(bucket="lake", client=client)
    data = b"abc"
    store.publish_exact("a.parquet", data, _digest(data))
    client.put_object.assert_called_once_with(
        Bucket="lake",
        Key="a.parquet",
        Body=data,
        IfNoneMatch="*",
    )


def test_s3_publish_exact_verifies_on_precondition_failed():
    client = MagicMock()
    store = S3ObjectStore(bucket="lake", client=client)
    data = b"abc"
    digest = _digest(data)
    client.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
        "PutObject",
    )
    body = MagicMock()
    body.iter_chunks = lambda: iter([data])
    client.get_object.return_value = {"Body": body}
    store.publish_exact("a.parquet", data, digest)
    client.get_object.assert_called_once_with(Bucket="lake", Key="a.parquet")


def test_s3_verify_exact_rejects_mismatched_hash():
    client = MagicMock()
    store = S3ObjectStore(bucket="lake", client=client)
    body = MagicMock()
    body.iter_chunks = lambda: iter([b"xyz"])
    client.get_object.return_value = {"Body": body}
    with pytest.raises(IntegrityError, match="hash"):
        store.verify_exact("a.parquet", _digest(b"abc"), 3)


def test_s3_verify_exact_classifies_access_denied():
    client = MagicMock()
    store = S3ObjectStore(bucket="lake", client=client)
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
        "GetObject",
    )
    with pytest.raises(AccessDeniedError):
        store.verify_exact("a.parquet", _digest(b"abc"), 3)


@patch("uns_datalake.stores.build_adls_filesystem")
def test_object_store_from_config_checks_adls_readiness(mock_build_fs):
    filesystem = MagicMock()
    mock_build_fs.return_value = filesystem
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(DatalakeConfig, "backend", "adls")
    monkeypatch.setattr(
        DatalakeConfig,
        "adls_settings",
        staticmethod(
            lambda: AdlsSettings(account="acct", container="container", account_key="key")
        ),
    )
    with pytest.raises(RuntimeError, match="unsupported"):
        AdlsObjectStore(filesystem=filesystem, directory="", atomic_finalize_supported=False).readiness_check()
    monkeypatch.undo()
