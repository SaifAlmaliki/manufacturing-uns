"""Cloud HTTPS client TLS selection tests."""

from __future__ import annotations

import ssl
from pathlib import Path

from conftest import FakeCloud

from uns_edge_agent.cloud_client import CloudClient
from uns_edge_agent.credentials import CredentialStore


def test_enrollment_verify_uses_ca_file_without_client_cert(
    tmp_path: Path, fake_cloud: FakeCloud, monkeypatch
) -> None:
    store = CredentialStore(tmp_path / "credentials")
    ca_path = tmp_path / "ca.pem"
    ca_path.write_text(fake_cloud._ca_pem, encoding="ascii")
    monkeypatch.setenv("UNS_EDGE_CA_FILE", str(ca_path))
    client = CloudClient("https://enroll.example.test", store)
    assert store.has_credentials() is False
    verify = client._verify(for_enrollment=True)
    assert isinstance(verify, ssl.SSLContext)


def test_management_verify_uses_mtls_after_credentials_exist(
    agent_config, fake_cloud: FakeCloud
) -> None:
    from uns_edge_agent.enrollment import enroll

    class EnrollClient:
        def enroll(self, **payload):
            return fake_cloud.enroll(**payload)

    issued = "fixture-enroll-1"
    enroll(config=agent_config, enrollment_token=issued, cloud_client=EnrollClient())
    store = CredentialStore(agent_config.credentials_dir)
    client = CloudClient("https://edge-mgmt.example.test", store)
    verify = client._verify(for_enrollment=False)
    assert isinstance(verify, ssl.SSLContext)
