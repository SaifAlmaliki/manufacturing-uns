from unittest.mock import Mock

from uns_datalake.config import DatalakeConfig
from uns_datalake.stores import AdlsObjectStore, S3ObjectStore, object_store_from_config


def test_s3_put_uses_stub_client():
    client = Mock()
    store = S3ObjectStore(bucket="uns-historic-events", region="us-east-1", client=client)
    store.put("dt=2026-09-08/x.parquet", b"bytes")
    client.put_object.assert_called_once_with(Bucket="uns-historic-events", Key="dt=2026-09-08/x.parquet", Body=b"bytes")


def test_adls_put_uses_stub_file_client():
    file_client = Mock()
    store = AdlsObjectStore(account="acct", container="lake", file_client_for=lambda path: file_client)
    store.put("dt=2026-09-08/x.parquet", b"bytes")
    file_client.upload_data.assert_called_once()


def test_factory_picks_backend(monkeypatch):
    boto_client = Mock()
    azure_client = Mock()
    credential = Mock()
    monkeypatch.setattr("uns_datalake.stores.boto3.client", boto_client)
    monkeypatch.setattr("uns_datalake.stores.DataLakeServiceClient", azure_client)
    monkeypatch.setattr("uns_datalake.stores.DefaultAzureCredential", credential)
    s3 = object_store_from_config(DatalakeConfig(backend="s3", s3_bucket="b", s3_region="r", s3_endpoint_url=None))
    assert isinstance(s3, S3ObjectStore)
    azure_client.assert_not_called()
    assert "aws_access_key_id" not in boto_client.call_args.kwargs
    adls = object_store_from_config(DatalakeConfig(backend="adls", adls_account="a", adls_container="c"))
    assert isinstance(adls, AdlsObjectStore)
    credential.assert_called_once()
    assert boto_client.call_count == 1
