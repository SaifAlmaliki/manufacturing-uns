"""Immutable publication contract tests."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from uns_datalake.publication import (
    AccessDeniedError,
    FrozenObject,
    IntegrityError,
    hash_bytes,
    verify_bytes,
)
from uns_datalake.stores import RAW_V2_PREFIX, AdlsObjectStore, FakeObjectStore, S3ObjectStore


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


@pytest.fixture
def fake_store(tmp_path: Path) -> FakeObjectStore:
    return FakeObjectStore(root=tmp_path)


@pytest.fixture
def s3_store() -> tuple[S3ObjectStore, MagicMock, dict[str, bytes]]:
    client = MagicMock()
    objects: dict[str, bytes] = {}

    def put_object(**kwargs):
        key = kwargs["Key"]
        if kwargs.get("IfNoneMatch") == "*" and key in objects:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        objects[key] = kwargs["Body"]

    def get_object(**kwargs):
        key = kwargs["Key"]
        if key not in objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        body = BytesIO(objects[key])
        body.iter_chunks = lambda chunk_size=1024 * 1024: iter([objects[key]])
        return {"Body": body}

    client.put_object.side_effect = put_object
    client.get_object.side_effect = get_object
    return S3ObjectStore(bucket="lake", client=client), client, objects


@pytest.fixture
def adls_store() -> tuple[AdlsObjectStore, MagicMock, dict[str, bytes]]:
    filesystem = MagicMock()
    objects: dict[str, bytes] = {}

    def get_file_client(path: str):
        client = MagicMock()
        client.path = path

        def exists() -> bool:
            return path in objects

        def upload_data(data: bytes, overwrite: bool = False) -> None:
            if not overwrite and path in objects:
                from azure.core.exceptions import ResourceExistsError

                raise ResourceExistsError("exists")
            objects[path] = data

        def download_file():
            stream = MagicMock()
            payload = objects.get(path, b"")
            stream.chunks = lambda: iter([payload])
            return stream

        def rename_file(new_name: str) -> MagicMock:
            if new_name in objects:
                from azure.core.exceptions import ResourceExistsError

                raise ResourceExistsError("exists")
            if path not in objects:
                raise RuntimeError("missing staging object")
            objects[new_name] = objects.pop(path)
            return get_file_client(new_name)

        client.exists = exists
        client.upload_data = upload_data
        client.download_file = download_file
        client.rename_file = rename_file
        return client

    filesystem.get_file_client.side_effect = get_file_client
    return AdlsObjectStore(filesystem=filesystem, directory="lake"), filesystem, objects


@pytest.mark.parametrize(
    "store_fixture",
    ["fake_store", "s3_store", "adls_store"],
)
def test_existing_mismatch_is_not_overwritten(store_fixture: str, request: pytest.FixtureRequest):
    store = request.getfixturevalue(store_fixture)
    if isinstance(store, tuple):
        store = store[0]
    store.publish_exact("x.parquet", b"old", _digest(b"old"))
    with pytest.raises(IntegrityError):
        store.publish_exact("x.parquet", b"new", _digest(b"new"))
    store.verify_exact("x.parquet", _digest(b"old"), 3)


@pytest.mark.parametrize(
    "store_fixture",
    ["fake_store", "s3_store", "adls_store"],
)
def test_identical_retry_is_idempotent(store_fixture: str, request: pytest.FixtureRequest):
    store = request.getfixturevalue(store_fixture)
    if isinstance(store, tuple):
        store = store[0]
    data = b"same-bytes"
    digest = _digest(data)
    store.publish_exact("retry.parquet", data, digest)
    store.publish_exact("retry.parquet", data, digest)
    store.verify_exact("retry.parquet", digest, len(data))


def test_truncated_readback_fails_verification(fake_store: FakeObjectStore):
    data = b"0123456789"
    digest = _digest(data)
    fake_store.publish_exact("trunc.parquet", data, digest)
    fake_store.truncated_reads["trunc.parquet"] = 4
    with pytest.raises(IntegrityError, match="length"):
        fake_store.verify_exact("trunc.parquet", digest, len(data))


def test_truncated_s3_readback_fails_verification(s3_store):
    store, _client, objects = s3_store
    data = b"0123456789"
    digest = _digest(data)
    store.publish_exact("trunc.parquet", data, digest)
    objects["trunc.parquet"] = data[:4]
    with pytest.raises(IntegrityError, match="length"):
        store.verify_exact("trunc.parquet", digest, len(data))


def test_s3_ambiguous_timeout_retry_verifies_existing_content(s3_store):
    store, client, objects = s3_store
    data = b"maybe-written"
    digest = _digest(data)
    objects["timeout.parquet"] = data

    def timeout_put(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "RequestTimeout", "Message": "timeout"}},
            "PutObject",
        )

    client.put_object.side_effect = timeout_put
    with pytest.raises(ClientError):
        store.publish_exact("timeout.parquet", data, digest)

    client.put_object.side_effect = None
    store.publish_exact("timeout.parquet", data, digest)
    store.verify_exact("timeout.parquet", digest, len(data))


def test_s3_conditional_conflict_verifies_existing_content(s3_store):
    store, client, objects = s3_store
    data = b"frozen"
    digest = _digest(data)
    objects["conflict.parquet"] = data

    def conflict_put(**kwargs):
        raise ClientError(
            {"Error": {"Code": "ConditionalRequestConflict", "Message": "conflict"}},
            "PutObject",
        )

    client.put_object.side_effect = conflict_put
    store.publish_exact("conflict.parquet", data, digest)
    store.verify_exact("conflict.parquet", digest, len(data))


def test_s3_access_denied_is_classified(s3_store):
    store, client, _objects = s3_store

    def denied_put(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "PutObject",
        )

    client.put_object.side_effect = denied_put
    with pytest.raises(AccessDeniedError):
        store.publish_exact("denied.parquet", b"x", _digest(b"x"))


def test_adls_staging_key_is_outside_raw_v2(adls_store):
    store, filesystem, _objects = adls_store
    data = b"payload"
    digest = _digest(data)
    key = "raw/v2/application=lims/site=plant-01/schema=lab-result/version=1/ingestion_date=2026-09-11/batch1.parquet"
    store.publish_exact(key, data, digest)
    staging_paths = [
        call.args[0]
        for call in filesystem.get_file_client.call_args_list
        if call.args[0].startswith("lake/_staging/")
    ]
    assert staging_paths
    assert all(RAW_V2_PREFIX not in path.removeprefix("lake/") for path in staging_paths)


def test_adls_unsupported_finalize_fails_readiness():
    store = AdlsObjectStore(filesystem=MagicMock(), directory="lake", atomic_finalize_supported=False)
    with pytest.raises(RuntimeError, match="unsupported"):
        store.readiness_check()
    with pytest.raises(RuntimeError, match="unsupported"):
        store.publish_exact("x.parquet", b"x", _digest(b"x"))


def test_frozen_object_from_bytes():
    data = b'{"result": 4.2}'
    frozen = FrozenObject.from_bytes("raw/v2/a.parquet", data, row_count=7)
    assert frozen.key == "raw/v2/a.parquet"
    assert frozen.data == data
    assert frozen.sha256 == hash_bytes(data)
    assert frozen.row_count == 7


def test_verify_bytes_rejects_hash_mismatch():
    with pytest.raises(IntegrityError, match="hash"):
        verify_bytes(b"abc", _digest(b"xyz"), 3)
