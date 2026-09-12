"""Enrollment flow tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from uns_edge_agent.cloud_client import CloudClientError
from uns_edge_agent.credentials import CredentialStore, generate_key_pair
from uns_edge_agent.enrollment import _safe_log_record, enroll

from conftest import FakeCloud


class EnrollClient:
    def __init__(self, fake: FakeCloud) -> None:
        self._fake = fake

    def enroll(self, **payload):
        return self._fake.enroll(**payload)


def test_generates_keys_locally(agent_config, fake_cloud: FakeCloud) -> None:
    before = set(agent_config.data_dir.iterdir()) if agent_config.data_dir.exists() else set()
    edge_id = enroll(
        config=agent_config,
        enrollment_token="token-abc",
        cloud_client=EnrollClient(fake_cloud),
    )
    after = set(agent_config.data_dir.iterdir())
    assert edge_id == "edge-test-01"
    assert "credentials" in {path.name for path in after - before}


def test_enroll_does_not_log_token(agent_config, fake_cloud: FakeCloud, caplog) -> None:
    caplog.set_level(logging.INFO)
    enroll(
        config=agent_config,
        enrollment_token="super-secret-token",
        cloud_client=EnrollClient(fake_cloud),
    )
    assert "super-secret-token" not in caplog.text
    assert all(_safe_log_record(record) for record in caplog.records)


def test_atomic_credential_install(agent_config, fake_cloud: FakeCloud) -> None:
    enroll(
        config=agent_config,
        enrollment_token="token-abc",
        cloud_client=EnrollClient(fake_cloud),
    )
    store = CredentialStore(agent_config.credentials_dir)
    manifest = store.load_manifest()
    assert manifest["edge_id"] == "edge-test-01"
    assert (agent_config.credentials_dir / "management.key.pem").is_file()
    assert (agent_config.credentials_dir / "mqtt.keystore.p12").is_file()


def test_temp_enrollment_material_erased(agent_config, fake_cloud: FakeCloud) -> None:
    enroll(
        config=agent_config,
        enrollment_token="token-abc",
        cloud_client=EnrollClient(fake_cloud),
    )
    assert not agent_config.enrollment_dir.exists()


def test_enrollment_failure_erases_temp_material(agent_config, fake_cloud: FakeCloud) -> None:
    class FailingClient:
        def enroll(self, **_payload):
            raise CloudClientError("invalid_token", 401)

    agent_config.enrollment_dir.mkdir(parents=True)
    (agent_config.enrollment_dir / "stale.csr.pem").write_text("stale", encoding="utf-8")
    with pytest.raises(CloudClientError):
        enroll(config=agent_config, enrollment_token="bad", cloud_client=FailingClient())
    assert not agent_config.enrollment_dir.exists()


def test_csr_generated_before_network_call(agent_config, fake_cloud: FakeCloud) -> None:
    observed: list[str] = []

    class ObservingClient:
        def enroll(self, **payload):
            observed.append(payload["management_csr"])
            return fake_cloud.enroll(**payload)

    local = generate_key_pair("local")
    assert local.csr_pem
    enroll(config=agent_config, enrollment_token="token", cloud_client=ObservingClient())
    assert observed
    assert observed[0].startswith("-----BEGIN CERTIFICATE REQUEST-----")
