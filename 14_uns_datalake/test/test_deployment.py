"""Deployment contract tests for datalake_mapper, MinIO, and Prometheus."""

from pathlib import Path

import pytest
import yaml

from uns_datalake.config import DatalakeConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
PROMETHEUS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"
DOCKERFILE = REPO_ROOT / "14_uns_datalake" / "Dockerfile"

SERVICE = "datalake_mapper"
JOB = "uns_datalake"
MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prometheus() -> dict:
    return yaml.safe_load(PROMETHEUS_FILE.read_text(encoding="utf-8"))


def test_scrape_target_matches_metrics_port(compose: dict, prometheus: dict):
    port = DatalakeConfig().metrics_port
    jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert JOB in jobs
    assert jobs[JOB]["static_configs"][0]["targets"] == [f"{SERVICE}:{port}"]


def test_metrics_port_not_published(compose: dict):
    assert "ports" not in compose["services"][SERVICE]


def test_minio_unpublished_and_always_on(compose: dict):
    minio = compose["services"]["uns-minio"]
    assert "ports" not in minio
    assert "profiles" not in minio
    assert minio["image"] == MINIO_IMAGE


def test_minio_init_uses_pinned_image_and_healthcheck(compose: dict):
    minio = compose["services"]["uns-minio"]
    assert "curl" in minio["healthcheck"]["test"]
    assert compose["services"]["minio_init"]["image"] == MINIO_IMAGE


def test_mapper_restart_policy_and_no_s3_env_injection(compose: dict):
    mapper = compose["services"][SERVICE]
    assert mapper["restart"] == "on-failure"
    environment = mapper["environment"]
    assert "UNS_datalake__s3__access_key" not in environment
    assert "UNS_datalake__s3__secret_key" not in environment
    assert environment["UNS_MODULE"] == "14_uns_datalake"


def test_prometheus_depends_on_mapper(compose: dict):
    assert SERVICE in compose["services"]["uns_prometheus"]["depends_on"]


def test_azurite_absent_from_compose():
    assert "azurite" not in COMPOSE_FILE.read_text(encoding="utf-8").lower()


def test_mapper_and_minio_have_no_profiles(compose: dict):
    assert "profiles" not in compose["services"][SERVICE]
    assert "profiles" not in compose["services"]["uns-minio"]


def test_dockerfile_healthcheck_uses_uns_datalake_health():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "uns_datalake_health" in dockerfile
    assert "--no-sync" in dockerfile
