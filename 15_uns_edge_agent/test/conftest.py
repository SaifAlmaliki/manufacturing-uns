"""Shared fixtures for edge agent tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from uns_edge_agent.cloud_client import CloudClient, ConfigurationSnapshot, Lease
from uns_edge_agent.config import AgentConfig
from uns_edge_agent.credentials import CredentialStore, EnrollmentMaterial, generate_key_pair
from uns_edge_agent.journal import Journal


@dataclass
class FakeClock:
    now: float = 0.0
    slept: list[float] | None = None

    def __post_init__(self) -> None:
        if self.slept is None:
            self.slept = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeCloud:
    def __init__(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        self.enroll_calls: list[dict[str, Any]] = []
        self.session_calls: list[str] = []
        self.config_requests: list[str | None] = []
        self.reports: list[dict[str, Any]] = []
        self.fail_next = 0
        self.configuration: dict[str, Any] | None = None
        self.configuration_revision = 1
        self.configuration_digest = "digest-1"
        self.edge_id = "edge-test-01"
        self._ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
        self._ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_subject)
            .issuer_name(ca_subject)
            .public_key(self._ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC))
            .not_valid_after(datetime.now(UTC) + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(self._ca_key, hashes.SHA256())
        )
        from cryptography.hazmat.primitives import serialization

        self._ca_pem = self._ca_cert.public_bytes(serialization.Encoding.PEM).decode("ascii")

    def _issue_from_csr(self, csr_pem: str, common_name: str) -> tuple[str, str]:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID

        csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
            .issuer_name(self._ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC))
            .not_valid_after(datetime.now(UTC) + timedelta(days=30))
            .sign(self._ca_key, hashes.SHA256())
        )
        pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        return pem, format(cert.serial_number, "x")

    def enroll(self, **payload: Any) -> dict[str, Any]:
        self.enroll_calls.append(payload)
        management_pem, management_serial = self._issue_from_csr(
            payload["management_csr"],
            f"{self.edge_id}.management.uns",
        )
        mqtt_pem, mqtt_serial = self._issue_from_csr(
            payload["mqtt_csr"],
            f"{self.edge_id}.mqtt.uns",
        )
        return {
            "edge_id": self.edge_id,
            "management_certificate_chain": [management_pem, self._ca_pem],
            "mqtt_certificate_chain": [mqtt_pem, self._ca_pem],
            "management_serial": management_serial,
            "mqtt_serial": mqtt_serial,
        }

    def open_session(self, boot_id: str) -> Lease:
        if self.fail_next:
            self.fail_next -= 1
            from uns_edge_agent.cloud_client import CloudClientError

            raise CloudClientError("cloud_down", 503)
        self.session_calls.append(boot_id)
        return Lease(
            edge_id=self.edge_id,
            boot_id=boot_id,
            generation=len(self.session_calls),
            lease_token=f"lease-{len(self.session_calls)}",
            expires_at=datetime.now(UTC) + timedelta(seconds=120),
        )

    def get_configuration(self, lease: Lease, *, if_none_match: str | None = None) -> ConfigurationSnapshot | None:
        self.config_requests.append(if_none_match)
        if self.configuration is None:
            from uns_edge_agent.cloud_client import CloudClientError

            raise CloudClientError("no_configuration", 404)
        quoted = f'"{self.configuration_digest}"'
        if if_none_match in {quoted, self.configuration_digest}:
            return None
        return ConfigurationSnapshot(
            revision=self.configuration_revision,
            digest=self.configuration_digest,
            document=self.configuration,
            etag=self.configuration_digest,
        )

    def submit_report(self, lease: Lease, report: dict[str, Any]) -> dict[str, Any]:
        self.reports.append(report)
        return {
            "edge_id": lease.edge_id,
            "boot_id": lease.boot_id,
            "report_sequence": report["report_sequence"],
            "received_at": datetime.now(UTC).isoformat(),
        }


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "agent-data"


@pytest.fixture
def agent_config(data_dir: Path) -> AgentConfig:
    return AgentConfig(
        cloud_base_url="https://cloud.test",
        data_dir=data_dir,
        edge_api_url="http://edge-api.test/health",
    )


@pytest.fixture
def journal(data_dir: Path) -> Journal:
    journal = Journal(data_dir / "journal.db")
    journal.open()
    yield journal
    journal.close()


@pytest.fixture
def fake_cloud() -> FakeCloud:
    return FakeCloud()


@pytest.fixture
def enrolled_store(agent_config: AgentConfig, fake_cloud: FakeCloud) -> CredentialStore:
    from uns_edge_agent.enrollment import enroll

    enroll(
        config=agent_config,
        enrollment_token="enroll-token-123",
        cloud_client=type(
            "Client",
            (),
            {
                "enroll": lambda self, **payload: fake_cloud.enroll(**payload),
            },
        )(),
    )
    return CredentialStore(agent_config.credentials_dir)


def sample_config(edge_id: str = "edge-test-01", revision: int = 1, digest: str = "digest-1") -> dict[str, Any]:
    return {
        "contract_version": 1,
        "edge_id": edge_id,
        "revision": revision,
        "digest": digest,
        "adapters": [],
        "required_route_revision": 0,
        "secret_refs": [],
        "deleted_adapter_ids": [],
    }


def sample_report(
    *,
    edge_id: str = "edge-test-01",
    boot_id: str = "boot-1",
    report_sequence: int = 1,
    phase: str = "applied",
) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "boot_id": boot_id,
        "report_sequence": report_sequence,
        "desired_revision": 1,
        "applied_revision": 1,
        "applied_digest": "digest-1",
        "phase": phase,
        "adapter_results": [],
        "last_error_code": None,
        "versions": {},
        "capabilities": {},
    }
