"""Local credential storage and HiveMQ-compatible MQTT keystore material."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from uns_edge_agent.config import MQTT_KEYSTORE_PASSWORD_LENGTH


class CredentialError(Exception):
    """Credential storage failure."""


@dataclass(frozen=True, slots=True)
class KeyPair:
    private_key_pem: bytes
    csr_pem: str


@dataclass(frozen=True, slots=True)
class EnrollmentMaterial:
    edge_id: str
    management_certificate_chain: tuple[str, ...]
    mqtt_certificate_chain: tuple[str, ...]
    management_serial: str
    mqtt_serial: str


def generate_key_pair(common_name: str = "edge-agent") -> KeyPair:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(private_key, hashes.SHA256())
    )
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return KeyPair(private_key_pem=private_key_pem, csr_pem=csr.public_bytes(serialization.Encoding.PEM).decode("ascii"))


def _certificate_serial_hex(pem: str) -> str:
    cert = x509.load_pem_x509_certificate(pem.encode("ascii"))
    return format(cert.serial_number, "x")


def _write_private(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    os.chmod(path, 0o600)


def _build_pkcs12_keystore(
    *,
    private_key_pem: bytes,
    leaf_pem: str,
    chain_pem: tuple[str, ...],
    password: bytes,
) -> bytes:
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    leaf = x509.load_pem_x509_certificate(leaf_pem.encode("ascii"))
    additional: list[x509.Certificate] = []
    for item in chain_pem[1:]:
        try:
            additional.append(x509.load_pem_x509_certificate(item.encode("ascii")))
        except ValueError:
            continue
    return pkcs12.serialize_key_and_certificates(
        name=b"mqtt-client",
        key=private_key,
        cert=leaf,
        cas=additional or None,
        encryption_algorithm=serialization.BestAvailableEncryption(password),
    )


class CredentialStore:
    """Filesystem-backed management and MQTT credentials."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._pending_root = root.parent / "credentials.pending"

    @property
    def root(self) -> Path:
        return self._root

    def has_credentials(self) -> bool:
        manifest = self._root / "manifest.json"
        return manifest.is_file()

    def load_manifest(self) -> dict[str, Any]:
        manifest_path = self._root / "manifest.json"
        if not manifest_path.is_file():
            raise CredentialError("credentials_missing")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def install_enrollment(
        self,
        material: EnrollmentMaterial,
        management_key: KeyPair,
        mqtt_key: KeyPair,
    ) -> None:
        if self._pending_root.exists():
            shutil.rmtree(self._pending_root)
        self._pending_root.mkdir(parents=True, exist_ok=True)

        management_leaf = material.management_certificate_chain[0]
        mqtt_leaf = material.mqtt_certificate_chain[0]
        ca_pem = material.management_certificate_chain[-1]
        keystore_password = secrets.token_urlsafe(MQTT_KEYSTORE_PASSWORD_LENGTH).encode("utf-8")

        _write_private(self._pending_root / "management.key.pem", management_key.private_key_pem)
        (self._pending_root / "management.crt.pem").write_text(management_leaf, encoding="utf-8")
        (self._pending_root / "management.chain.pem").write_text(
            "\n".join(material.management_certificate_chain),
            encoding="utf-8",
        )
        _write_private(self._pending_root / "mqtt.key.pem", mqtt_key.private_key_pem)
        (self._pending_root / "mqtt.crt.pem").write_text(mqtt_leaf, encoding="utf-8")
        (self._pending_root / "mqtt.chain.pem").write_text(
            "\n".join(material.mqtt_certificate_chain),
            encoding="utf-8",
        )
        (self._pending_root / "ca.pem").write_text(ca_pem, encoding="utf-8")
        keystore_bytes = _build_pkcs12_keystore(
            private_key_pem=mqtt_key.private_key_pem,
            leaf_pem=mqtt_leaf,
            chain_pem=material.mqtt_certificate_chain,
            password=keystore_password,
        )
        keystore_path = self._pending_root / "mqtt.keystore.p12"
        keystore_path.write_bytes(keystore_bytes)
        os.chmod(keystore_path, 0o600)
        (self._pending_root / "mqtt.keystore.pass").write_bytes(keystore_password)
        os.chmod(self._pending_root / "mqtt.keystore.pass", 0o600)

        manifest = {
            "edge_id": material.edge_id,
            "management_serial": material.management_serial,
            "mqtt_serial": material.mqtt_serial,
        }
        (self._pending_root / "manifest.json").write_text(
            json.dumps(manifest, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )

        backup: str | None = None
        if self._root.exists():
            backup = tempfile.mkdtemp(prefix="uns-edge-credentials-backup-")
            shutil.move(str(self._root), backup)
        self._root.parent.mkdir(parents=True, exist_ok=True)
        self._pending_root.rename(self._root)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)

    def management_ssl_context(self) -> ssl.SSLContext:
        manifest = self.load_manifest()
        context = ssl.create_default_context(cafile=str(self._root / "ca.pem"))
        context.load_cert_chain(
            certfile=str(self._root / "management.crt.pem"),
            keyfile=str(self._root / "management.key.pem"),
        )
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.set_alpn_protocols(["http/1.1"])
        _ = manifest  # manifest proves install completed
        return context

    def mqtt_keystore_path(self) -> Path:
        path = self._root / "mqtt.keystore.p12"
        if not path.is_file():
            raise CredentialError("mqtt_keystore_missing")
        return path

    def mqtt_keystore_password(self) -> bytes:
        path = self._root / "mqtt.keystore.pass"
        if not path.is_file():
            raise CredentialError("mqtt_keystore_password_missing")
        return path.read_bytes()

    def load_mqtt_keystore(self) -> tuple[Any, x509.Certificate, tuple[x509.Certificate, ...]]:
        """Return PKCS12 material in the same shape Edge/Java keystores expose."""
        keystore_bytes = self.mqtt_keystore_path().read_bytes()
        password = self.mqtt_keystore_password()
        private_key, certificate, additional = pkcs12.load_key_and_certificates(
            keystore_bytes,
            password,
        )
        if private_key is None or certificate is None:
            raise CredentialError("mqtt_keystore_unreadable")
        return private_key, certificate, tuple(additional or ())

    @staticmethod
    def enrollment_material_from_response(payload: dict[str, Any]) -> EnrollmentMaterial:
        return EnrollmentMaterial(
            edge_id=str(payload["edge_id"]),
            management_certificate_chain=tuple(payload["management_certificate_chain"]),
            mqtt_certificate_chain=tuple(payload["mqtt_certificate_chain"]),
            management_serial=str(payload["management_serial"]),
            mqtt_serial=str(payload["mqtt_serial"]),
        )
