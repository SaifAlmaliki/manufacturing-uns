"""Unit tests for edge secret encryption and key handling."""

from __future__ import annotations

import pytest

from uns_model.edge_secrets import (
    EdgeKeyMaterial,
    EdgeKeyRing,
    EdgeSecretError,
    EdgeSecretStore,
    REDACTED,
)


@pytest.fixture
def key_ring() -> EdgeKeyRing:
    return EdgeKeyRing.from_key_material(
        EdgeKeyMaterial("edge-secrets-v1", b"a" * 32),
        EdgeKeyMaterial("edge-secrets-v2", b"b" * 32),
        active_key_id="edge-secrets-v1",
    )


@pytest.fixture
def store(key_ring: EdgeKeyRing) -> EdgeSecretStore:
    return EdgeSecretStore(key_ring)


def test_encrypt_decrypt_round_trip(store: EdgeSecretStore):
    encrypted = store.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        plaintext=b"s3cret!",
    )
    assert store.decrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        encrypted=encrypted,
    ) == b"s3cret!"


def test_wrong_key_id_rejects_decryption(store: EdgeSecretStore):
    encrypted = store.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        plaintext=b"s3cret!",
    )
    tampered = type(encrypted)(
        key_id="edge-secrets-v2",
        nonce=encrypted.nonce,
        ciphertext=encrypted.ciphertext,
    )
    with pytest.raises(EdgeSecretError, match="decrypt_failed"):
        store.decrypt(
            edge_id="edge-01",
            secret_id="conn-password",
            version=1,
            encrypted=tampered,
        )


def test_wrong_edge_associated_data_rejects_decryption(store: EdgeSecretStore):
    encrypted = store.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        plaintext=b"s3cret!",
    )
    with pytest.raises(EdgeSecretError, match="decrypt_failed"):
        store.decrypt(
            edge_id="edge-02",
            secret_id="conn-password",
            version=1,
            encrypted=encrypted,
        )


def test_tampered_ciphertext_rejects_decryption(store: EdgeSecretStore):
    encrypted = store.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        plaintext=b"s3cret!",
    )
    corrupted = bytes(b ^ 0x01 for b in encrypted.ciphertext)
    tampered = type(encrypted)(encrypted.key_id, encrypted.nonce, corrupted)
    with pytest.raises(EdgeSecretError, match="decrypt_failed"):
        store.decrypt(
            edge_id="edge-01",
            secret_id="conn-password",
            version=1,
            encrypted=tampered,
        )


def test_key_rotation_encrypts_with_active_key_and_decrypts_old():
    ring_v1 = EdgeKeyRing.from_key_material(
        EdgeKeyMaterial("edge-secrets-v1", b"a" * 32),
        active_key_id="edge-secrets-v1",
    )
    store_v1 = EdgeSecretStore(ring_v1)
    encrypted_v1 = store_v1.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        plaintext=b"old-secret",
    )
    ring_v2 = EdgeKeyRing.from_key_material(
        EdgeKeyMaterial("edge-secrets-v1", b"a" * 32),
        EdgeKeyMaterial("edge-secrets-v2", b"b" * 32),
        active_key_id="edge-secrets-v2",
    )
    store_v2 = EdgeSecretStore(ring_v2)
    encrypted_v2 = store_v2.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=2,
        plaintext=b"new-secret",
    )
    assert store_v2.decrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        encrypted=encrypted_v1,
    ) == b"old-secret"
    assert store_v2.decrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=2,
        encrypted=encrypted_v2,
    ) == b"new-secret"


def test_redacted_serialization_never_exposes_material(store: EdgeSecretStore):
    encrypted = store.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        plaintext=b"s3cret!",
    )
    redacted = encrypted.redacted()
    assert redacted["key_id"] == "edge-secrets-v1"
    assert redacted["nonce"] == REDACTED
    assert redacted["ciphertext"] == REDACTED


def test_backup_round_trip_preserves_ciphertext(store: EdgeSecretStore):
    encrypted = store.encrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        plaintext=b"s3cret!",
    )
    restored = EdgeSecretStore.parse_backup(store.serialize_backup(encrypted))
    assert store.decrypt(
        edge_id="edge-01",
        secret_id="conn-password",
        version=1,
        encrypted=restored,
    ) == b"s3cret!"


def test_fresh_nonces_are_unique(store: EdgeSecretStore):
    first = store.encrypt(edge_id="edge-01", secret_id="pw", version=1, plaintext=b"1")
    second = store.encrypt(edge_id="edge-01", secret_id="pw", version=2, plaintext=b"2")
    assert first.nonce != second.nonce
