"""Restricted intermediate CA for edge management and MQTT bridge certificates."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERTIFICATE_LIFETIME = timedelta(days=30)
RENEWAL_WINDOW = timedelta(days=20)
OVERLAP_DURATION = timedelta(hours=24)

EdgeCertPurpose = Literal["management", "mqtt"]


@dataclass(frozen=True, slots=True)
class IssuedCertificate:
    certificate_id: str
    purpose: EdgeCertPurpose
    pem: str
    chain_pem: tuple[str, ...]
    subject: str
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True, slots=True)
class CertificateAuthority:
    """Test-injectable intermediate CA."""

    private_key: PrivateKeyTypes
    certificate_pem: str
    subject: str


def generate_authority(common_name: str = "UNS Edge Intermediate CA") -> CertificateAuthority:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    return CertificateAuthority(
        private_key=private_key,
        certificate_pem=cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        subject=common_name,
    )


class EdgeCertificateIssuer:
    """Issue edge certificates from CSRs with server-derived subjects and EKUs."""

    def __init__(self, authority: CertificateAuthority) -> None:
        self._authority = authority
        self._authority_cert = x509.load_pem_x509_certificate(
            authority.certificate_pem.encode("ascii")
        )

    def derived_subject(self, edge_id: str, purpose: EdgeCertPurpose) -> str:
        return f"CN={edge_id}.{purpose}.uns"

    def issue_from_csr(
        self,
        csr_pem: str,
        *,
        edge_id: str,
        purpose: EdgeCertPurpose,
        now: datetime,
    ) -> IssuedCertificate:
        csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        if not csr.is_signature_valid:
            raise ValueError("invalid_csr_signature")

        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, f"{edge_id}.{purpose}.uns"),
            ]
        )
        not_before = now
        not_after = now + CERTIFICATE_LIFETIME
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self._authority_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(not_before)
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .sign(self._authority.private_key, hashes.SHA256())
        )
        leaf_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
        return IssuedCertificate(
            certificate_id=str(uuid.uuid4()),
            purpose=purpose,
            pem=leaf_pem,
            chain_pem=(leaf_pem, self._authority.certificate_pem),
            subject=self.derived_subject(edge_id, purpose),
            not_before=not_before,
            not_after=not_after,
        )

    def renewal_allowed(self, not_before: datetime, now: datetime) -> bool:
        return now >= not_before + RENEWAL_WINDOW

    def overlap_not_before(self, previous_not_after: datetime) -> datetime:
        return previous_not_after - OVERLAP_DURATION


def generate_csr(common_name: str = "agent-ignored") -> tuple[str, bytes]:
    """Build a CSR for tests; the issuer ignores the requested subject."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(private_key, hashes.SHA256())
    )
    pem = csr.public_bytes(serialization.Encoding.PEM)
    return pem.decode("ascii"), private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def certificate_serial_hex(pem: str) -> str:
    cert = x509.load_pem_x509_certificate(pem.encode("ascii"))
    return format(cert.serial_number, "x")


def new_enrollment_token() -> str:
    return secrets.token_urlsafe(32)
