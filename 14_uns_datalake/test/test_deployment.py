"""Deployment contract checks for the datalake mapper package."""

from pathlib import Path

import yaml

from uns_datalake.config import DatalakeConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = REPO_ROOT / "conf" / "settings.yaml"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
PROMETHEUS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"
PACKAGE_ROOT = REPO_ROOT / "14_uns_datalake"
MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"


def test_package_entrypoints_exist():
    assert (PACKAGE_ROOT / "src" / "uns_datalake" / "main.py").exists()
    assert (PACKAGE_ROOT / "Dockerfile").exists()


def test_settings_declare_canonical_stream_and_backend():
    settings = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8"))
    datalake = settings["datalake"]
    assert datalake["backend"] == "s3"
    assert datalake["kafka"]["topic"] == "uns.historic-events"
    assert datalake["kafka"]["group_id"] == "uns_datalake"
    assert datalake["s3"]["endpoint_url"] == "http://uns-minio:9000"


def test_metrics_port_matches_module_default():
    assert DatalakeConfig.metrics_port == 9096


def test_compose_runs_minio_and_mapper_without_profiles():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    for service_name in ("uns_minio", "minio_init", "datalake_mapper"):
        service = compose["services"][service_name]
        assert "profiles" not in service
    assert "ports" not in compose["services"]["uns_minio"]
    assert "ports" not in compose["services"]["datalake_mapper"]


def test_minio_services_use_pinned_image_and_healthcheck():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    minio = compose["services"]["uns_minio"]
    assert minio["image"] == MINIO_IMAGE
    health = minio["healthcheck"]["test"]
    health_command = " ".join(str(part) for part in health)
    assert "curl" in health_command
    assert "/minio/health/live" in health_command
    assert compose["services"]["minio_init"]["image"] == MINIO_IMAGE


def test_datalake_mapper_restart_and_credentials_stay_in_mounted_config():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    service = compose["services"]["datalake_mapper"]
    assert service["restart"] == "on-failure"
    environment = service["environment"]
    assert environment["UNS_datalake__s3__endpoint_url"] == "http://uns-minio:9000"
    assert "bootstrap.servers" in environment["UNS_kafka__config"]
    assert "uns_kafka_broker:29092" in environment["UNS_kafka__config"]
    assert "UNS_datalake__s3__access_key" not in environment
    assert "UNS_datalake__s3__secret_key" not in environment


def test_minio_service_exposes_hyphenated_network_alias():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    aliases = compose["services"]["uns_minio"]["networks"]["default"]["aliases"]
    assert "uns-minio" in aliases


def test_compose_does_not_reference_azurite():
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8").lower()
    assert "azurite" not in compose_text


def test_prometheus_scrapes_datalake_mapper():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    prometheus = yaml.safe_load(PROMETHEUS_FILE.read_text(encoding="utf-8"))
    jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert jobs["uns_datalake"]["static_configs"][0]["targets"] == ["datalake_mapper:9096"]
    assert "datalake_mapper" in compose["services"]["uns_prometheus"]["depends_on"]


def test_dockerfile_declares_healthcheck():
    dockerfile = (PACKAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "uns_datalake_healthcheck" in dockerfile
