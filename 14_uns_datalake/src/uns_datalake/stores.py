"""S3 and ADLS object-store adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import boto3
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient
from botocore.config import Config

from uns_config.datalake import ObjectStore
from uns_datalake.config import DatalakeConfig


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        client: Any = None,
    ) -> None:
        self.bucket = bucket
        if client is None:
            kwargs: dict[str, Any] = {
                "region_name": region,
                "config": Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}),
            }
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            if access_key and secret_key:
                kwargs["aws_access_key_id"] = access_key
                kwargs["aws_secret_access_key"] = secret_key
            client = boto3.client("s3", **kwargs)
        self._client = client

    def put(self, path: str, parquet_bytes: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=path, Body=parquet_bytes)


class AdlsObjectStore:
    def __init__(
        self,
        *,
        account: str,
        container: str,
        endpoint_url: str | None = None,
        account_key: str | None = None,
        file_client_for: Callable[[str], Any] | None = None,
    ) -> None:
        self.container = container
        if file_client_for is None:
            account_url = endpoint_url or f"https://{account}.dfs.core.windows.net"
            credential = account_key or DefaultAzureCredential()
            service = DataLakeServiceClient(
                account_url=account_url,
                credential=credential,
                connection_timeout=5,
                read_timeout=10,
                retry_total=0,
            )
            self._file_client_for = lambda path: service.get_file_system_client(container).get_file_client(path)
        else:
            self._file_client_for = file_client_for

    def put(self, path: str, parquet_bytes: bytes) -> None:
        file_client = self._file_client_for(path)
        file_client.upload_data(parquet_bytes, overwrite=True, max_concurrency=1)


def object_store_from_config(config: DatalakeConfig) -> ObjectStore:
    if config.backend == "s3":
        return S3ObjectStore(
            bucket=config.s3_bucket,
            region=config.s3_region,
            endpoint_url=config.s3_endpoint_url,
            access_key=config.s3_access_key,
            secret_key=config.s3_secret_key,
        )
    if config.backend == "adls":
        return AdlsObjectStore(
            account=config.adls_account,
            container=config.adls_container,
            endpoint_url=config.adls_endpoint_url,
            account_key=config.adls_account_key,
        )
    raise ValueError(f"unsupported backend: {config.backend}")
