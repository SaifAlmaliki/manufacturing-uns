"""Deployment contract checks for the datalake mapper package."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from uns_datalake.config import DatalakeConfig
from uns_datalake.stores import AdlsObjectStore

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = REPO_ROOT / "conf" / "settings.yaml"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
PROMETHEUS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"
PACKAGE_ROOT = REPO_ROOT / "14_uns_datalake"
MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"
CANONICAL_TOPIC = "uns.historic-events"
DATALAKE_GROUP_ID = "uns_datalake"
HISTORIAN_GROUP_ID = "uns_historian"
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


def _load_settings() -> dict:
    return yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8"))


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _kafka_group_id(service: dict) -> str:
    config = json.loads(service["environment"]["UNS_kafka__config"].removeprefix("@json "))
    return config["group.id"]


def test_kafka_remains_canonical_transport():
    settings = _load_settings()
    compose = _load_compose()

    assert settings["datalake"]["kafka"]["topic"] == CANONICAL_TOPIC
    assert settings["default"]["historian"]["historic_kafka_topic"] == CANONICAL_TOPIC
    assert (
        settings["default"]["kafka_bootstrap"]["historic_topic"]["name"]
        == CANONICAL_TOPIC
    )
    assert settings["kafka_mapper"]["kafka"]["config"]["bootstrap.servers"]
    assert "uns_kafka_broker" in compose["services"]
    assert "kafka_mapper_client" in compose["services"]
    assert "kafka_topic_init" in compose["services"]


def test_datalake_uses_independent_consumer_group():
    settings = _load_settings()
    compose = _load_compose()
    datalake = settings["datalake"]

    assert datalake["kafka"]["group_id"] == DATALAKE_GROUP_ID
    assert DATALAKE_GROUP_ID != HISTORIAN_GROUP_ID
    assert _kafka_group_id(compose["services"]["datalake_mapper"]) == DATALAKE_GROUP_ID
    assert _kafka_group_id(compose["services"]["historian_client"]) == HISTORIAN_GROUP_ID


def test_historian_is_not_lake_dependency():
    compose = _load_compose()
    depends_on = compose["services"]["datalake_mapper"]["depends_on"]
    dependency_names = set(depends_on) if isinstance(depends_on, list) else set(depends_on.keys())

    assert "historian_client" not in dependency_names
    assert "uns_timescale_db" not in dependency_names
    assert "uns_kafka_broker" in dependency_names


def test_v2_publications_enabled_in_shipped_config():
    settings = _load_settings()
    compose = _load_compose()
    ingestion = settings["kafka_mapper"]["ingestion"]

    assert "v2_publications_enabled" in ingestion
    assert ingestion["v2_publications_enabled"] is True
    assert len(ingestion["publication_routes"]) >= 4
    mapper_env = compose["services"]["kafka_mapper_client"]["environment"]
    assert "v2_publications_enabled" not in mapper_env


def test_legacy_route_map_not_in_shipped_config():
    """v2 publication_routes own live routing; legacy map is optional for v1 Kafka replay."""
    settings = _load_settings()
    assert "legacy_route_map" not in settings["datalake"]


def test_datalake_v2_routing_settings_are_present():
    settings = _load_settings()
    datalake = settings["datalake"]

    assert datalake["kafka"]["initial_position"] == "require_committed"
    assert datalake["flush"]["max_active_route_groups"] == 64
    assert datalake["flush"]["max_encoded_bytes"] == 16_777_216


def test_adls_without_atomic_finalize_cannot_report_ready():
    store = AdlsObjectStore(
        filesystem=MagicMock(),
        directory="lake",
        atomic_finalize_supported=False,
    )
    with pytest.raises(RuntimeError, match="unsupported"):
        store.readiness_check()
