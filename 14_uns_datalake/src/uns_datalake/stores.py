"""Object store adapters for immutable Parquet uploads."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from uns_datalake.config import AdlsSettings, DatalakeConfig, S3Settings

LOGGER = logging.getLogger(__name__)


class ObjectStore(Protocol):
    def put(self, path: str, parquet_bytes: bytes) -> None: ...


@dataclass(slots=True)
class FakeObjectStore:
    root: Path
    objects: dict[str, bytes] = field(default_factory=dict)
    put_calls: list[tuple[str, bytes]] = field(default_factory=list)
    fail_paths: set[str] = field(default_factory=set)

    def put(self, path: str, parquet_bytes: bytes) -> None:
        if path in self.fail_paths:
            raise RuntimeError(f"simulated upload failure for {path}")
        self.put_calls.append((path, parquet_bytes))
        self.objects[path] = parquet_bytes
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(parquet_bytes)


class S3ObjectStore:
    def __init__(self, *, bucket: str, client) -> None:
        self._bucket = bucket
        self._client = client

    def put(self, path: str, parquet_bytes: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=path, Body=parquet_bytes)


class AdlsObjectStore:
    def __init__(self, *, filesystem, directory: str) -> None:
        self._filesystem = filesystem
        self._directory = directory.strip("/")

    def put(self, path: str, parquet_bytes: bytes) -> None:
        full_path = f"{self._directory}/{path}" if self._directory else path
        file_client = self._filesystem.get_file_client(full_path)
        file_client.upload_data(parquet_bytes, overwrite=True)


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
    return AdlsObjectStore(filesystem=build_adls_filesystem(adls), directory="")


def object_store_from_settings(*, backend: str, s3: S3Settings | None = None, adls: AdlsSettings | None = None) -> ObjectStore:
    if backend == "s3":
        assert s3 is not None
        return S3ObjectStore(bucket=s3.bucket, client=build_s3_client(s3))
    assert adls is not None
    return AdlsObjectStore(filesystem=build_adls_filesystem(adls), directory="")
