"""Behavioral tests for edge-scoped MQTT publisher configuration."""

from __future__ import annotations

import importlib.util
import json
import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch

import paho.mqtt.client as mqtt
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISHER_SCRIPT = REPO_ROOT / "conf" / "simulator" / "multi_system_publishers.py"
OEE_SCRIPT = REPO_ROOT / "HiveMQ-Simulator.sh"


def _load_publisher_module():
    import sys

    spec = importlib.util.spec_from_file_location("multi_system_publishers", PUBLISHER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_shell_script_supports_tls_and_acceptance_env_vars():
    text = OEE_SCRIPT.read_text(encoding="utf-8")
    for name in (
        "MQTT_TLS",
        "MQTT_CA_FILE",
        "CLIENT_ID_PREFIX",
        "ACCEPTANCE_MODE",
        "RUN_ID",
        "SEED",
        "CASE_COUNT",
        "MQTT_CREDENTIALS_FILE",
        "IDENTITY_FILE",
    ):
        assert name in text


def test_shell_script_uses_per_edge_client_id_prefix():
    text = OEE_SCRIPT.read_text(encoding="utf-8")
    assert "CLIENT_ID_PREFIX" in text
    assert "BOOT_ID" in text
    assert "IDENTITY_FILE" in text


@patch("paho.mqtt.client.Client.connect")
def test_publisher_waits_for_puback_before_success(_connect):
    module = _load_publisher_module()
    publisher = module.MultiSystemPublisher(
        host="localhost",
        port=1883,
        enterprise="EdgeSimulation",
        site="EdgeSimulation",
        site_id="edge-simulation",
        boot_id="boot-test",
        interval_seconds=1.0,
        topic_prefix="EdgeSimulation/EdgeSimulation",
        tls=False,
        ca_file=None,
        cert_file=None,
        key_file=None,
        tls_verify=True,
        username=None,
        password=None,
        acceptance_mode=False,
        run_id=None,
        seed=None,
        case_count=0,
        malformed_mode=False,
        identity_file=Path("/tmp/test_identity.json"),
        client_id_prefix="test_multi",
    )
    info = MagicMock()
    info.rc = mqtt.MQTT_ERR_SUCCESS
    info.is_published.return_value = True
    publisher._client.publish = MagicMock(return_value=info)
    result = publisher.publish_with_ack("Enterprise/test", b"{}")
    assert result.admitted is True
    assert result.acknowledged is True
    info.wait_for_publish.assert_called_once()


@patch("paho.mqtt.client.Client.connect")
def test_publisher_distinguishes_admission_from_ack(_connect):
    module = _load_publisher_module()
    publisher = module.MultiSystemPublisher(
        host="localhost",
        port=1883,
        enterprise="EdgeSimulation",
        site="EdgeSimulation",
        site_id="edge-simulation",
        boot_id="boot-test",
        interval_seconds=1.0,
        topic_prefix="EdgeSimulation/EdgeSimulation",
        tls=False,
        ca_file=None,
        cert_file=None,
        key_file=None,
        tls_verify=True,
        username=None,
        password=None,
        acceptance_mode=False,
        run_id=None,
        seed=None,
        case_count=0,
        malformed_mode=False,
        identity_file=Path("/tmp/test_identity_ack.json"),
        client_id_prefix="test_multi",
    )
    info = MagicMock()
    info.rc = mqtt.MQTT_ERR_SUCCESS
    info.is_published.return_value = False
    publisher._client.publish = MagicMock(return_value=info)
    result = publisher.publish_with_ack("Enterprise/test", b"{}")
    assert result.admitted is True
    assert result.acknowledged is False


@patch("paho.mqtt.client.Client.connect", side_effect=ssl.SSLError("verification failed"))
def test_tls_verification_failure_raises(_connect, tmp_path: Path):
    module = _load_publisher_module()
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("not-a-ca", encoding="utf-8")
    with pytest.raises(ssl.SSLError):
        module.MultiSystemPublisher(
            host="localhost",
            port=8883,
            enterprise="EdgeSimulation",
            site="EdgeSimulation",
            site_id="edge-simulation",
            boot_id="boot-test",
            interval_seconds=1.0,
            topic_prefix="EdgeSimulation/EdgeSimulation",
            tls=True,
            ca_file=str(ca_file),
            cert_file=None,
            key_file=None,
            tls_verify=True,
            username=None,
            password=None,
            acceptance_mode=False,
            run_id=None,
            seed=None,
            case_count=0,
            malformed_mode=False,
            identity_file=tmp_path / "identity.json",
            client_id_prefix="test_multi",
        )


def test_restart_identity_persists_sequence(tmp_path: Path):
    module = _load_publisher_module()
    identity_file = tmp_path / "identity.json"
    module._save_identity(identity_file, "boot-abc", 4)
    boot_id, sequence = module._load_identity(identity_file, None)
    assert boot_id == "boot-abc"
    assert sequence == 4


@patch("paho.mqtt.client.Client.connect")
def test_acceptance_mode_is_bounded_and_reproducible(_connect, tmp_path: Path):
    module = _load_publisher_module()
    identity_file = tmp_path / "identity_accept.json"

    def _make_publisher(seed: int):
        publisher = module.MultiSystemPublisher(
            host="localhost",
            port=1883,
            enterprise="EdgeSimulation",
            site="EdgeSimulation",
            site_id="edge-simulation",
            boot_id="boot-accept",
            interval_seconds=0.01,
            topic_prefix="EdgeSimulation/EdgeSimulation",
            tls=False,
            ca_file=None,
            cert_file=None,
            key_file=None,
            tls_verify=True,
            username=None,
            password=None,
            acceptance_mode=True,
            run_id="run-1",
            seed=seed,
            case_count=2,
            malformed_mode=False,
            identity_file=identity_file,
            client_id_prefix="test_multi",
        )
        publisher._client.loop = MagicMock()
        publisher._client.disconnect = MagicMock()
        publisher._client.publish = MagicMock(
            return_value=MagicMock(
                rc=mqtt.MQTT_ERR_SUCCESS,
                is_published=MagicMock(return_value=True),
                wait_for_publish=MagicMock(),
            )
        )
        return publisher

    first = _make_publisher(42)
    first.run()
    second = _make_publisher(42)
    second.run()
    assert len(first._manifest) == 2
    assert len(second._manifest) == 2
    assert first._manifest[0]["topics"] == second._manifest[0]["topics"]
