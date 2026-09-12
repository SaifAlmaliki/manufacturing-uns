"""Manifest contracts for the reproducible DMZ edge installation bundle."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EDGE_DIR = REPO_ROOT / "deploy" / "edge"
COMPOSE_FILE = EDGE_DIR / "compose.yml"
RELEASE_FILE = EDGE_DIR / "release.json"
HIVEMQ_TEMPLATE = EDGE_DIR / "hivemq" / "config.xml.template"
AGENT_EXAMPLE = EDGE_DIR / "agent.yaml.example"
INSTALL_SCRIPT = EDGE_DIR / "install.sh"
VERIFY_SCRIPT = EDGE_DIR / "verify.sh"
UPGRADE_SCRIPT = EDGE_DIR / "upgrade.sh"
DOCS_FILE = REPO_ROOT / "docs" / "operations" / "dmz-edge-installation.md"

DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
FORBIDDEN_COMPOSE_SECRETS = (
    "UNS_EDGE_API_PASSWORD=hivemq",
    "UNS_EDGE_API_USERNAME=admin",
    "password: hivemq",
    "EDGE_API_PASSWORD=hivemq",
)


@pytest.fixture
def edge_compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def edge_release() -> dict:
    return json.loads(RELEASE_FILE.read_text(encoding="utf-8"))


def test_edge_bundle_files_exist():
    required = [
        COMPOSE_FILE,
        RELEASE_FILE,
        HIVEMQ_TEMPLATE,
        AGENT_EXAMPLE,
        INSTALL_SCRIPT,
        VERIFY_SCRIPT,
        UPGRADE_SCRIPT,
        DOCS_FILE,
    ]
    for path in required:
        assert path.is_file(), path


def test_release_json_records_digest_pinned_images(edge_release):
    assert edge_release["bundle_version"] == 1
    assert "release_id" in edge_release
    images = edge_release["images"]
    assert set(images) == {"hivemq-edge", "uns-edge-agent"}
    for name, image in images.items():
        assert DIGEST_PATTERN.fullmatch(image["digest"])
        assert image["repository"]
        assert "@" not in image["repository"]


def test_base_compose_has_exactly_two_long_running_services(edge_compose):
    services = edge_compose["services"]
    assert set(services) == {"hivemq-edge", "uns-edge-agent"}


def test_compose_images_are_digest_pinned(edge_compose, edge_release):
    for service_name, image_name in (
        ("hivemq-edge", "hivemq-edge"),
        ("uns-edge-agent", "uns-edge-agent"),
    ):
        image_ref = edge_compose["services"][service_name]["image"]
        expected_digest = edge_release["images"][image_name]["digest"]
        assert image_ref.endswith(f"@{expected_digest}")
        assert DIGEST_PATTERN.search(image_ref)


def test_compose_services_restart_unless_stopped(edge_compose):
    for service in edge_compose["services"].values():
        assert service.get("restart") == "unless-stopped"


def test_compose_does_not_publish_edge_admin_api_port(edge_compose):
    edge = edge_compose["services"]["hivemq-edge"]
    ports = edge.get("ports") or []
    published = {str(port) for port in ports}
    assert not any("8443" in port for port in published)
    assert not any("8080" in port for port in published)


def test_compose_agent_has_no_listening_port(edge_compose):
    agent = edge_compose["services"]["uns-edge-agent"]
    assert not agent.get("ports")


def test_compose_has_no_privileged_mode_or_docker_socket(edge_compose):
    for service in edge_compose["services"].values():
        assert not service.get("privileged")
        mounts = service.get("volumes") or []
        mount_text = " ".join(str(mount) for mount in mounts)
        assert "/var/run/docker.sock" not in mount_text


def test_compose_mounts_durable_edge_and_agent_volumes(edge_compose):
    edge_mounts = " ".join(str(m) for m in edge_compose["services"]["hivemq-edge"]["volumes"])
    agent_mounts = " ".join(str(m) for m in edge_compose["services"]["uns-edge-agent"]["volumes"])
    assert "edge-config:" in edge_mounts
    assert "edge-data:" in edge_mounts
    assert "edge-bridge:" in edge_mounts
    assert "agent-data:" in agent_mounts
    assert ":ro" not in edge_mounts


def test_compose_does_not_ship_default_credentials(edge_compose):
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_COMPOSE_SECRETS:
        assert forbidden not in compose_text
    for service in edge_compose["services"].values():
        env = service.get("environment") or {}
        if isinstance(env, dict):
            values = [str(value).lower() for value in env.values()]
            assert "hivemq" not in values
            assert "admin" not in values


def test_hivemq_template_uses_private_tls_admin_api():
    template = HIVEMQ_TEMPLATE.read_text(encoding="utf-8")
    assert "tls-tcp-listener" in template
    assert "<port>8443</port>" in template
    assert "admin-api" in template
    assert "<authentication>" in template or "<enabled>true</enabled>" in template
    assert "1883" not in template


def test_hivemq_template_has_no_protocol_adapters():
    template = HIVEMQ_TEMPLATE.read_text(encoding="utf-8")
    assert "protocol-adapters" not in template
    assert "protocol-adapter" not in template


def test_hivemq_template_configures_outbound_bridge_only():
    template = HIVEMQ_TEMPLATE.read_text(encoding="utf-8")
    assert "mqtt-bridges" in template
    assert "forwarded-topics" in template
    assert "remote-subscriptions" not in template
    assert "${BRIDGE_CLIENT_ID}" in template
    assert "${CLOUD_MQTT_HOST}" in template
    assert "8883" in template


def test_hivemq_template_bridge_uses_mtls_persistent_session_and_finite_buffer():
    template = HIVEMQ_TEMPLATE.read_text(encoding="utf-8")
    assert "bridge-keystore" in template
    assert "clean-start>false</clean-start>" in template
    assert "session-expiry-interval" in template
    assert "max-buffer-size" in template
    assert "persist>true</persist>" in template


def test_hivemq_template_documents_explicit_retain_rules():
    template = HIVEMQ_TEMPLATE.read_text(encoding="utf-8")
    assert "retain" in template.lower()
    assert "bootstrap-retained>false</bootstrap-retained>" in template


def test_agent_yaml_example_documents_required_settings():
    example = AGENT_EXAMPLE.read_text(encoding="utf-8")
    assert "cloud_base_url:" in example
    assert "endpoint_allowlist:" in example
    assert "edge_api_url: https://hivemq-edge:8443" in example
    assert "password:" not in example.lower() or "changeme" not in example.lower()


def test_install_script_checks_runtime_digest_and_destination():
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert "--destination" in script
    assert "release.json" in script
    assert "sha256" in script
    assert "docker compose" in script
    assert "curl" not in script
    assert "wget" not in script


def test_verify_script_checks_destination_and_services():
    script = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert "--destination" in script
    assert "compose.yml" in script
    assert "uns-edge-agent" in script
    assert "hivemq-edge" in script


def test_upgrade_script_requires_named_release_and_backup():
    script = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert "--release" in script
    assert "backup" in script.lower()
    assert "--destination" in script


def test_documentation_covers_install_sequence():
    docs = DOCS_FILE.read_text(encoding="utf-8")
    for phrase in (
        "/opt/uns-edge",
        "install.sh",
        "uns_edge_enroll",
        "verify.sh",
        "docker load",
        "edge-sim",
        "two long-running services",
    ):
        assert phrase in docs


def test_compose_config_validates_with_fixture_secrets(tmp_path: Path):
    project_dir = tmp_path / "uns-edge"
    secrets_dir = project_dir / "secrets"
    secrets_dir.mkdir(parents=True)
    (project_dir / "compose.yml").write_text(
        COMPOSE_FILE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "agent.env").write_text(
        "UNS_EDGE_CLOUD_URL=https://cloud.example.test\n"
        "UNS_EDGE_ENDPOINT_ALLOWLIST=cloud.example.test\n",
        encoding="utf-8",
    )
    (secrets_dir / "edge-api.env").write_text(
        "UNS_EDGE_API_USERNAME=fixture-user\n"
        "UNS_EDGE_API_PASSWORD=fixture-secret\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(project_dir),
            "-f",
            str(project_dir / "compose.yml"),
            "config",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
