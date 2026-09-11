"""Object store adapters for immutable Parquet uploads."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from botocore.exceptions import ClientError

from uns_datalake.config import AdlsSettings, DatalakeConfig, S3Settings
from uns_datalake.publication import (
    AccessDeniedError,
    IntegrityError,
    hash_stream,
    verify_bytes,
)

LOGGER = logging.getLogger(__name__)

STAGING_PREFIX = "_staging/"
RAW_V2_PREFIX = "raw/v2/"
S3_PRECONDITION_CODES = frozenset({"PreconditionFailed", "412"})
S3_CONFLICT_CODES = frozenset({"ConditionalRequestConflict", "409"})
S3_ACCESS_DENIED_CODES = frozenset({"AccessDenied", "403", "InvalidAccessKeyId", "SignatureDoesNotMatch"})


class ObjectStore(Protocol):
    def put(self, path: str, parquet_bytes: bytes) -> None: ...

    def publish_exact(self, key: str, data: bytes, sha256: str) -> None: ...

    def verify_exact(self, key: str, sha256: str, byte_length: int) -> None: ...


@dataclass(slots=True)
class FakeObjectStore:
    root: Path
    objects: dict[str, bytes] = field(default_factory=dict)
    put_calls: list[tuple[str, bytes]] = field(default_factory=list)
    fail_paths: set[str] = field(default_factory=set)
    truncated_reads: dict[str, int] = field(default_factory=dict)

    def put(self, path: str, parquet_bytes: bytes) -> None:
        if path in self.fail_paths:
            raise RuntimeError(f"simulated upload failure for {path}")
        self.put_calls.append((path, parquet_bytes))
        self.objects[path] = parquet_bytes
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(parquet_bytes)

    def publish_exact(self, key: str, data: bytes, sha256: str) -> None:
        if key in self.objects:
            self.verify_exact(key, sha256, len(data))
            return
        if key in self.fail_paths:
            raise RuntimeError(f"simulated upload failure for {key}")
        self.objects[key] = data
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def verify_exact(self, key: str, sha256: str, byte_length: int) -> None:
        if key not in self.objects:
            raise IntegrityError(f"object {key} not found")
        data = self.objects[key]
        if key in self.truncated_reads:
            data = data[: self.truncated_reads[key]]
        verify_bytes(data, sha256, byte_length)


class S3ObjectStore:
    def __init__(self, *, bucket: str, client) -> None:
        self._bucket = bucket
        self._client = client

    def put(self, path: str, parquet_bytes: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=path, Body=parquet_bytes)

    def publish_exact(self, key: str, data: bytes, sha256: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                IfNoneMatch="*",
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in S3_ACCESS_DENIED_CODES:
                raise AccessDeniedError(str(exc)) from exc
            if code in S3_PRECONDITION_CODES or code in S3_CONFLICT_CODES:
                self.verify_exact(key, sha256, len(data))
                return
            raise

    def verify_exact(self, key: str, sha256: str, byte_length: int) -> None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in S3_ACCESS_DENIED_CODES:
                raise AccessDeniedError(str(exc)) from exc
            raise IntegrityError(f"object {key} not found") from exc
        body = response["Body"]
        digest, length = hash_stream(body.iter_chunks())
        if length != byte_length:
            raise IntegrityError(
                f"object length {length} does not match expected {byte_length}"
            )
        if digest != sha256:
            raise IntegrityError(
                f"object hash {digest} does not match expected {sha256}"
            )


class AdlsObjectStore:
    def __init__(
        self,
        *,
        filesystem,
        directory: str,
        atomic_finalize_supported: bool = True,
    ) -> None:
        self._filesystem = filesystem
        self._directory = directory.strip("/")
        self._atomic_finalize_supported = atomic_finalize_supported

    @property
    def atomic_finalize_supported(self) -> bool:
        return self._atomic_finalize_supported

    def readiness_check(self) -> None:
        if not self._atomic_finalize_supported:
            raise RuntimeError("adls immutable finalization unsupported")

    def put(self, path: str, parquet_bytes: bytes) -> None:
        full_path = self._full_path(path)
        file_client = self._filesystem.get_file_client(full_path)
        file_client.upload_data(parquet_bytes, overwrite=True)

    def publish_exact(self, key: str, data: bytes, sha256: str) -> None:
        self.readiness_check()
        final_path = self._full_path(key)
        final_client = self._filesystem.get_file_client(final_path)
        if final_client.exists():
            self.verify_exact(key, sha256, len(data))
            return

        staging_name = f"{STAGING_PREFIX}{uuid.uuid4()}.upload"
        staging_path = self._full_path(staging_name)
        staging_client = self._filesystem.get_file_client(staging_path)
        staging_client.upload_data(data, overwrite=False)
        self._verify_client(staging_client, sha256, len(data))

        try:
            staging_client.rename_file(final_path)
        except Exception as exc:
            if final_client.exists():
                self.verify_exact(key, sha256, len(data))
                return
            self._raise_access_denied(exc)
            raise
        self.verify_exact(key, sha256, len(data))

    def verify_exact(self, key: str, sha256: str, byte_length: int) -> None:
        final_path = self._full_path(key)
        final_client = self._filesystem.get_file_client(final_path)
        if not final_client.exists():
            raise IntegrityError(f"object {key} not found")
        self._verify_client(final_client, sha256, byte_length)

    def _full_path(self, path: str) -> str:
        return f"{self._directory}/{path}" if self._directory else path

    def _verify_client(self, file_client, sha256: str, byte_length: int) -> None:
        try:
            stream = file_client.download_file()
            digest, length = hash_stream(stream.chunks())
        except Exception as exc:
            self._raise_access_denied(exc)
            raise
        if length != byte_length:
            raise IntegrityError(
                f"object length {length} does not match expected {byte_length}"
            )
        if digest != sha256:
            raise IntegrityError(
                f"object hash {digest} does not match expected {sha256}"
            )

    @staticmethod
    def _raise_access_denied(exc: Exception) -> None:
        from azure.core.exceptions import HttpResponseError

        if isinstance(exc, HttpResponseError) and exc.status_code in {401, 403}:
            raise AccessDeniedError(str(exc)) from exc


def build_s3_client(s3: S3Settings):
    import boto3
    from botocore.config import Config

    access_key, secret_key = DatalakeConfig.resolve_s3_credentials(s3)
    config = Config(
        connect_timeout=DatalakeConfig.upload_connect_timeout,
        read_timeout=DatalakeConfig.upload_read_timeout,
        retries={"max_attempts": 0},
    )
    kwargs: dict = {
        "service_name": "s3",
        "region_name": s3.region,
        "config": config,
    }
    if s3.endpoint_url:
        kwargs["endpoint_url"] = s3.endpoint_url
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    return boto3.client(**kwargs)


def build_adls_filesystem(adls: AdlsSettings):
    from azure.identity import DefaultAzureCredential
    from azure.storage.filedatalake import DataLakeServiceClient

    account_url = f"https://{adls.account}.dfs.core.windows.net"
    if adls.account_key:
        service = DataLakeServiceClient(account_url=account_url, credential=adls.account_key)
    else:
        service = DataLakeServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return service.get_file_system_client(adls.container)


def object_store_from_config() -> ObjectStore:
    DatalakeConfig.validate_backend()
    if DatalakeConfig.backend == "s3":
        s3 = DatalakeConfig.s3_settings()
        return S3ObjectStore(bucket=s3.bucket, client=build_s3_client(s3))
    adls = DatalakeConfig.adls_settings()
    store = AdlsObjectStore(filesystem=build_adls_filesystem(adls), directory="")
    store.readiness_check()
    return store


def object_store_from_settings(*, backend: str, s3: S3Settings | None = None, adls: AdlsSettings | None = None) -> ObjectStore:
    if backend == "s3":
        assert s3 is not None
        return S3ObjectStore(bucket=s3.bucket, client=build_s3_client(s3))
    assert adls is not None
    store = AdlsObjectStore(filesystem=build_adls_filesystem(adls), directory="")
    store.readiness_check()
    return store
