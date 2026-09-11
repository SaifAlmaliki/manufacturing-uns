"""Authenticated encryption for edge connection secrets.

Key material is loaded from files outside SQL. Encrypted backups must include the
same key files or a documented recovery path; ciphertext alone is not decryptable.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from uns_config import get_settings, resolve_conf_dir

DEFAULT_KEY_ID = "edge-secrets-v1"
REDACTED = "[redacted]"


class EdgeSecretError(ValueError):
    """Secret encryption or decryption failure with a stable reason code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    key_id: str
    nonce: bytes
    ciphertext: bytes

    def redacted(self) -> dict[str, str]:
        return {
            "key_id": self.key_id,
            "nonce": REDACTED,
            "ciphertext": REDACTED,
        }


@dataclass(frozen=True, slots=True)
class EdgeKeyMaterial:
    key_id: str
    key: bytes


class EdgeKeyRing:
    """Versioned AES-256-GCM keys loaded from operator-supplied files."""

    def __init__(self, keys: dict[str, bytes], *, active_key_id: str) -> None:
        if active_key_id not in keys:
            raise EdgeSecretError("missing_active_key", active_key_id)
        self._keys = keys
        self._active_key_id = active_key_id

    @classmethod
    def from_settings(cls) -> EdgeKeyRing:
        settings = get_settings("default")
        block = settings.get("edge_management.secrets", {}) or {}
        active_key_id = str(block.get("active_key_id", DEFAULT_KEY_ID))
        key_dir = Path(str(block.get("key_dir", resolve_conf_dir() / "edge-keys")))
        keys: dict[str, bytes] = {}
        for path in sorted(key_dir.glob("*.key")):
            raw = path.read_bytes().strip()
            if len(raw) != 32:
                raise EdgeSecretError("invalid_key_length", path.name)
            keys[path.stem] = raw
        if not keys:
            raise EdgeSecretError("missing_key_material", str(key_dir))
        return cls(keys, active_key_id=active_key_id)

    @classmethod
    def from_key_material(cls, *material: EdgeKeyMaterial, active_key_id: str) -> EdgeKeyRing:
        return cls({item.key_id: item.key for item in material}, active_key_id=active_key_id)

    def active_key(self) -> EdgeKeyMaterial:
        return EdgeKeyMaterial(self._active_key_id, self._keys[self._active_key_id])

    def key_for(self, key_id: str) -> EdgeKeyMaterial:
        if key_id not in self._keys:
            raise EdgeSecretError("unknown_key_id", key_id)
        return EdgeKeyMaterial(key_id, self._keys[key_id])


def _associated_data(*, edge_id: str, secret_id: str, version: int) -> bytes:
    return f"{edge_id}:{secret_id}:{version}".encode("utf-8")


class EdgeSecretStore:
    """Encrypt and decrypt edge-scoped secret values."""

    def __init__(self, key_ring: EdgeKeyRing) -> None:
        self._key_ring = key_ring

    def encrypt(self, *, edge_id: str, secret_id: str, version: int, plaintext: bytes) -> EncryptedSecret:
        active = self._key_ring.active_key()
        nonce = os.urandom(12)
        ciphertext = AESGCM(active.key).encrypt(
            nonce,
            plaintext,
            _associated_data(edge_id=edge_id, secret_id=secret_id, version=version),
        )
        return EncryptedSecret(active.key_id, nonce, ciphertext)

    def decrypt(
        self,
        *,
        edge_id: str,
        secret_id: str,
        version: int,
        encrypted: EncryptedSecret,
    ) -> bytes:
        key = self._key_ring.key_for(encrypted.key_id)
        try:
            return AESGCM(key.key).decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                _associated_data(edge_id=edge_id, secret_id=secret_id, version=version),
            )
        except Exception as exc:
            raise EdgeSecretError("decrypt_failed") from exc

    def serialize_backup(self, encrypted: EncryptedSecret) -> str:
        payload = {
            "key_id": encrypted.key_id,
            "nonce": base64.b64encode(encrypted.nonce).decode("ascii"),
            "ciphertext": base64.b64encode(encrypted.ciphertext).decode("ascii"),
        }
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def parse_backup(raw: str) -> EncryptedSecret:
        parsed: dict[str, Any] = json.loads(raw)
        return EncryptedSecret(
            key_id=str(parsed["key_id"]),
            nonce=base64.b64decode(str(parsed["nonce"]).encode("ascii")),
            ciphertext=base64.b64decode(str(parsed["ciphertext"]).encode("ascii")),
        )
