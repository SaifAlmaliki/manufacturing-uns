"""Manifest contracts for the production cloud installation bundle."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOUD_DIR = REPO_ROOT / "deploy" / "cloud"
COMPOSE_FILE = CLOUD_DIR / "compose.yml"
RELEASE_FILE = CLOUD_DIR / "release.json"
SETTINGS_EXAMPLE = CLOUD_DIR / "settings.yaml.example"
PROXY_FILE = CLOUD_DIR / "proxy" / "nginx.conf"
VALIDATE_SCRIPT = CLOUD_DIR / "validate.py"
HOSTINGER_DOC = CLOUD_DIR / "hostinger.md"
AWS_DOC = CLOUD_DIR / "aws-ec2.md"
OPS_DOC = REPO_ROOT / "docs" / "operations" / "cloud-platform.md"
BROKER_README = CLOUD_DIR / "broker" / "README.md"

DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
FORBIDDEN_COMPOSE_MARKERS = (
    "hivemq/hivemq-edge",
    "hivemq-edge",
    "start-dev",
    ":latest",
    "./conf:/app/conf",
    ".secrets.yaml",
    "oee_mqtt_simulator",
    "multi_system_simulator",
    "opcua_client",
    "opcua-simulator",
    "modbus-simulator",
    "password: hivemq",
    "KC_BOOTSTRAP_ADMIN_USERNAME: admin",
)
FORBIDDEN_HOST_PORTS = (
    "5432:5432",
    "9092:9092",
    "7474:7474",
    "7687:7687",
    "9090:9090",
    "9091:9091",
    "8000:8000",
    "8080:8080",
    "3000:3000",
    "1883:1883",
)
ALLOWED_HOST_PORTS = ("443:443", "80:80", "8883:8883")


@pytest.fixture
def cloud_compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def cloud_release() -> dict:
    return json.loads(RELEASE_FILE.read_text(encoding="utf-8"))


def test_cloud_bundle_files_exist():
    required = [
        COMPOSE_FILE,
        RELEASE_FILE,
        SETTINGS_EXAMPLE,
        PROXY_FILE,
        VALIDATE_SCRIPT,
        HOSTINGER_DOC,
        AWS_DOC,
        OPS_DOC,
        BROKER_README,
        CLOUD_DIR / "broker" / "config.xml",
    ]
    for path in required:
        assert path.is_file(), path


def test_release_json_records_digest_pinned_images(cloud_release):
    assert cloud_release["bundle_version"] == 1
    assert cloud_release.get("contract_version") == 1
    assert cloud_release.get("envelope_version") == 2
    assert cloud_release.get("single_server_failure_domain") is True
    images = cloud_release["images"]
    assert {"uns-proxy", "hivemq-broker", "uns-graphql"}.issubset(images)
    for name, image in images.items():
        assert DIGEST_PATTERN.fullmatch(image["digest"])
        assert image["repository"]
        assert "@" not in image["repository"]


def test_release_json_records_unqualified_broker_gate(cloud_release):
    broker = cloud_release["images"]["hivemq-broker"]
    assert broker["status"] == "blocked"
    assert cloud_release["qualification_status"] == "unqualified"


def test_compose_images_are_digest_pinned(cloud_compose, cloud_release):
    for service_name, service in cloud_compose["services"].items():
        image_ref = service.get("image", "")
        assert DIGEST_PATTERN.search(image_ref), service_name
        assert ":latest" not in image_ref


def test_compose_forbids_edge_simulators_and_collectors(cloud_compose):
    services = set(cloud_compose["services"])
    forbidden = {
        "hivemq-edge",
        "oee_mqtt_simulator",
        "multi_system_simulator",
        "opcua_client",
        "opcua-simulator",
        "modbus-simulator",
    }
    assert forbidden.isdisjoint(services)


def test_compose_text_forbids_development_artifacts():
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    for marker in FORBIDDEN_COMPOSE_MARKERS:
        assert marker not in compose_text


def test_compose_does_not_publish_private_dependency_ports():
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    for port_mapping in FORBIDDEN_HOST_PORTS:
        assert port_mapping not in compose_text
    for port_mapping in ALLOWED_HOST_PORTS:
        assert port_mapping in compose_text


def test_compose_mounts_only_runtime_settings_not_repository_conf(cloud_compose):
    for service in cloud_compose["services"].values():
        mounts = service.get("volumes") or []
        mount_text = " ".join(str(mount) for mount in mounts)
        assert "./conf:" not in mount_text
        assert ".secrets.yaml" not in mount_text
        assert "/app/conf" not in mount_text or "./settings.yaml:/app/conf/settings.yaml:ro" in mount_text


def test_compose_services_restart_unless_stopped(cloud_compose):
    one_shots = {"kafka_topic_init", "tsdb_setup_script", "asset_model_setup", "cloud_backup"}
    for name, service in cloud_compose["services"].items():
        if name in one_shots:
            continue
        assert service.get("restart") == "unless-stopped", name


def test_compose_uses_production_keycloak_startup(cloud_compose):
    keycloak = cloud_compose["services"]["uns_keycloak"]
    command = keycloak.get("command") or []
    assert "start" in command
    assert "start-dev" not in command


def test_compose_proxy_and_broker_are_only_public_entrypoints(cloud_compose):
    published: set[str] = set()
    for service in cloud_compose["services"].values():
        for port in service.get("ports") or []:
            published.add(str(port))
    assert published.issubset({"443:443", "80:80", "8883:8883"})


def test_settings_example_uses_https_public_origin():
    settings = yaml.safe_load(SETTINGS_EXAMPLE.read_text(encoding="utf-8"))["default"]
    origin = settings["platform"]["public_origin"]
    assert origin.startswith("https://")
    assert "localhost" not in origin
    assert settings["platform"]["edge_management"]["cloud_mode"] is True


def test_proxy_terminates_console_enrollment_and_management_separately():
    proxy = PROXY_FILE.read_text(encoding="utf-8")
    assert "server_name uns.example.com" in proxy
    assert "server_name enroll.uns.example.com" in proxy
    assert "server_name edge-mgmt.uns.example.com" in proxy
    assert "ssl_verify_client on" in proxy
    assert "X-UNS-Trusted-Proxy" in proxy
    assert "X-Edge-Id" in proxy
    assert "proxy_pass http://$graphql_upstream:8000" in proxy
    assert "mqtt" not in proxy.lower()


def test_proxy_does_not_expose_graphql_bypass_port(cloud_compose):
    graphql = cloud_compose["services"]["graphql_server"]
    assert not graphql.get("ports")


def test_documentation_covers_single_server_failure_domain():
    docs = OPS_DOC.read_text(encoding="utf-8")
    for phrase in (
        "single-server",
        "not HA",
        "source → edge → cloud",
        "validate.py",
        "hostinger.md",
        "aws-ec2.md",
        "8883",
        "enroll.",
        "edge-mgmt.",
    ):
        assert phrase in docs


def test_provider_runbooks_cover_required_operator_steps():
    for path in (HOSTINGER_DOC, AWS_DOC):
        text = path.read_text(encoding="utf-8")
        for phrase in (
            "DNS",
            "TLS",
            "docker compose",
            "settings.yaml",
            "backup",
            "rollback",
            "secrets",
            "verify",
        ):
            assert phrase in text


def test_validate_rejects_missing_tls_material(tmp_path: Path):
    bundle = _fixture_bundle(tmp_path, qualified_broker=False)
    result = _run_validate(bundle, skip_disk=True)
    assert result.returncode != 0
    assert "missing TLS" in (result.stderr or result.stdout)


def test_validate_rejects_unqualified_broker_release(tmp_path: Path):
    bundle = _fixture_bundle(tmp_path, qualified_broker=False, with_tls=True)
    result = _run_validate(bundle, skip_disk=True)
    assert result.returncode != 0
    assert "unqualified central broker" in (result.stderr or result.stdout)


def test_validate_rejects_http_public_origin(tmp_path: Path):
    bundle = _fixture_bundle(tmp_path, qualified_broker=True, with_tls=True, public_origin="http://uns.example.com")
    result = _run_validate(bundle, skip_disk=True)
    assert result.returncode != 0
    assert "HTTPS" in (result.stderr or result.stdout)


def test_validate_rejects_incompatible_contract_version(tmp_path: Path):
    bundle = _fixture_bundle(tmp_path, qualified_broker=True, with_tls=True, contract_version=99)
    result = _run_validate(bundle, skip_disk=True)
    assert result.returncode != 0
    assert "contract_version" in (result.stderr or result.stdout)


def test_validate_rejects_insufficient_disk_budget(tmp_path: Path, monkeypatch):
    bundle = _fixture_bundle(tmp_path, qualified_broker=True, with_tls=True)

    class _TinyUsage:
        total = 1
        used = 0
        free = 1

    monkeypatch.setattr("deploy.cloud.validate.shutil.disk_usage", lambda _path: _TinyUsage())
    result = _run_validate(bundle, skip_disk=False)
    assert result.returncode != 0
    assert "insufficient declared disk budget" in (result.stderr or result.stdout)


def test_validate_accepts_qualified_fixture_bundle(tmp_path: Path):
    bundle = _fixture_bundle(tmp_path, qualified_broker=True, with_tls=True)
    result = _run_validate(bundle, skip_disk=True)
    assert result.returncode == 0, result.stderr or result.stdout


def test_compose_config_validates_with_fixture_secrets(tmp_path: Path):
    bundle = _fixture_bundle(tmp_path, qualified_broker=True, with_tls=True, for_compose_config=True)
    project_dir = bundle
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


def _run_validate(bundle_dir: Path, *, skip_disk: bool) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VALIDATE_SCRIPT), "--bundle-dir", str(bundle_dir)]
    if skip_disk:
        command.append("--skip-disk-check")
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _fixture_bundle(
    tmp_path: Path,
    *,
    qualified_broker: bool,
    with_tls: bool = False,
    public_origin: str = "https://uns.example.com",
    contract_version: int = 1,
    for_compose_config: bool = False,
) -> Path:
    bundle = tmp_path / "uns-cloud"
    bundle.mkdir()
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    if for_compose_config:
        repo_root = str(REPO_ROOT).replace("\\", "/")
        compose_text = compose_text.replace("../..", repo_root)
        (bundle / "broker").mkdir()
        for name in ("config.xml",):
            source = CLOUD_DIR / "broker" / name
            (bundle / "broker" / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        (bundle / "broker" / "authorization").mkdir()
        for name in ("config.xml", "file-realm.xml", "permissions.xml"):
            source = CLOUD_DIR / "broker" / "authorization" / name
            (bundle / "broker" / "authorization" / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        (bundle / "proxy").mkdir()
        (bundle / "proxy" / "nginx.conf").write_text(PROXY_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        (bundle / "keycloak").mkdir()
    (bundle / "compose.yml").write_text(compose_text, encoding="utf-8")
    release = json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    release["contract_version"] = contract_version
    broker = release["images"]["hivemq-broker"]
    if qualified_broker:
        broker["status"] = "qualified"
        broker.pop("blocker", None)
    (bundle / "release.json").write_text(json.dumps(release), encoding="utf-8")
    settings = yaml.safe_load(SETTINGS_EXAMPLE.read_text(encoding="utf-8"))
    settings["default"]["platform"]["public_origin"] = public_origin
    (bundle / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    secrets = bundle / "secrets"
    runtime = secrets / "runtime.env"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(
        "\n".join(
            [
                "UNS_CONSOLE_ORIGIN=https://uns.example.com",
                "PGPASSWORD=fixture-postgres",
                "UNS_graphdb__password=fixture-graphdb",
                "UNS_historian__password=fixture-historian",
                "UNS_keycloak__admin_password=fixture-keycloak-admin",
                "UNS_keycloak__grafana_client_secret=fixture-grafana-secret",
                "UNS_keycloak__db_password=fixture-keycloak-db",
                "UNS_KEYCLOAK_ADMIN_USERNAME=cloud-admin",
                "UNS_KAFKA_RETENTION_MS=604800000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (secrets / "broker-tls.env").write_text("BROKER_KEYSTORE_PASSWORD=fixture\n", encoding="utf-8")
    (secrets / "backup.env").write_text("BACKUP_TARGET=s3://fixture/backups\n", encoding="utf-8")
    if with_tls:
        for relative in (
            "tls/console/fullchain.pem",
            "tls/console/privkey.pem",
            "tls/enrollment/fullchain.pem",
            "tls/enrollment/privkey.pem",
            "tls/management/fullchain.pem",
            "tls/management/privkey.pem",
            "tls/management/ca.pem",
            "broker-tls/broker-keystore.jks",
            "broker-tls/broker-truststore.jks",
        ):
            path = secrets / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
    return bundle
