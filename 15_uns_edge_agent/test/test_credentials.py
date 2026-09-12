"""Credential storage and MQTT keystore tests."""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.serialization import pkcs12

from uns_edge_agent.credentials import CredentialStore, EnrollmentMaterial, generate_key_pair

from conftest import FakeCloud


def _install(store: CredentialStore, fake_cloud: FakeCloud) -> None:
    management_key = generate_key_pair("management")
    mqtt_key = generate_key_pair("mqtt")
    payload = fake_cloud.enroll(
        enrollment_token="ignored",
        management_csr=management_key.csr_pem,
        mqtt_csr=mqtt_key.csr_pem,
    )
    material = CredentialStore.enrollment_material_from_response(payload)
    store.install_enrollment(material, management_key, mqtt_key)


def test_mqtt_keystore_pkcs12_format(agent_config, fake_cloud: FakeCloud) -> None:
    store = CredentialStore(agent_config.credentials_dir)
    _install(store, fake_cloud)
    keystore = store.mqtt_keystore_path()
    assert keystore.suffix == ".p12"
    assert keystore.read_bytes().startswith(b"\x30")


def test_keystore_readable_by_edge_format(agent_config, fake_cloud: FakeCloud) -> None:
    store = CredentialStore(agent_config.credentials_dir)
    _install(store, fake_cloud)
    private_key, certificate, chain = store.load_mqtt_keystore()
    assert private_key is not None
    assert certificate is not None
    raw = store.mqtt_keystore_path().read_bytes()
    password = store.mqtt_keystore_password()
    reloaded_key, reloaded_cert, reloaded_chain = pkcs12.load_key_and_certificates(raw, password)
    assert reloaded_key is not None
    assert reloaded_cert is not None
    assert reloaded_cert.serial_number == certificate.serial_number
    assert tuple(reloaded_chain or ()) == chain


def test_management_mtls_context(agent_config, fake_cloud: FakeCloud) -> None:
    store = CredentialStore(agent_config.credentials_dir)
    _install(store, fake_cloud)
    context = store.management_ssl_context()
    assert context.verify_mode.name == "CERT_REQUIRED"
