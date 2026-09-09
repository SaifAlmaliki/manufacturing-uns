"""Compose and settings contract checks for the coordinated pipeline cutover."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from uns_datalake.config import DatalakeConfig
from uns_kafka.uns_kafka_config import IngestionSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DEV_COMPOSE_FILE = REPO_ROOT / "docker-compose.dev.yml"
SETTINGS_FILE = REPO_ROOT / "conf" / "settings.yaml"
PROMETHEUS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"
ALERTS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "alerts.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dev_compose() -> dict:
    text = DEV_COMPOSE_FILE.read_text(encoding="utf-8").replace(": !reset\n", ":\n")
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def settings() -> dict:
    return yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prometheus() -> dict:
    return yaml.safe_load(PROMETHEUS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def alerts() -> dict:
    return yaml.safe_load(ALERTS_FILE.read_text(encoding="utf-8"))


def test_kafka_broker_disables_automatic_topic_creation(compose: dict):
    env = compose["services"]["uns_kafka_broker"]["environment"]
    assert env["KAFKA_AUTO_CREATE_TOPICS_ENABLE"] == "false"


def test_kafka_broker_uses_persistent_data_volume(compose: dict):
    broker = compose["services"]["uns_kafka_broker"]
    assert broker["environment"]["KAFKA_LOG_DIRS"] == "/var/lib/kafka/data"
    assert "kafka_data:/var/lib/kafka/data" in broker["volumes"]
    assert "kafka_data" in compose["volumes"]


def test_kafka_topic_init_runs_bootstrap_once(compose: dict):
    service = compose["services"]["kafka_topic_init"]
    assert service["entrypoint"] == ["uv", "run", "uns_kafka_bootstrap"]
    assert service["restart"] == "no"
    assert service["depends_on"]["uns_kafka_broker"]["condition"] == "service_healthy"


def test_pipeline_consumers_wait_for_topic_init(compose: dict):
    for service_name in ("historian_client", "kafka_mapper_client", "datalake_mapper", "graphql_server"):
        depends_on = compose["services"][service_name]["depends_on"]
        assert depends_on["kafka_topic_init"]["condition"] == "service_completed_successfully"


def test_historian_client_uses_kafka_not_mqtt(compose: dict):
    service = compose["services"]["historian_client"]
    environment = service["environment"]
    assert "UNS_mqtt__host" not in environment
    assert "uns_mqtt_broker" not in service["depends_on"]
    assert "uns_kafka_broker" in service["depends_on"]
    assert "uns_historian" in environment["UNS_historian__kafka__config"]
    assert "uns_kafka_broker:29092" in environment["UNS_historian__kafka__config"]


def test_settings_declare_kafka_bootstrap_contract(settings: dict):
    bootstrap = settings["default"]["kafka_bootstrap"]
    assert bootstrap["pipeline_epoch"] == 1
    assert bootstrap["historic_topic"]["name"] == "uns.historic-events"
    assert bootstrap["historic_topic"]["partitions"] == 12
    assert bootstrap["dlq_topic"]["name"] == "uns.historic-events.dlq"
    assert bootstrap["dlq_topic"]["retention_ms"] == 30 * 24 * 60 * 60 * 1000


def test_settings_keep_canonical_ingestion_and_historian_batching(settings: dict):
    kafka_mapper = settings["kafka_mapper"]
    assert kafka_mapper["mqtt"]["topics"] == ["#"]
    assert kafka_mapper["ingestion"]["shard_id"] == "dev"
    historian = settings["default"]["historian"]
    assert historian["pipeline_epoch"] == 1
    assert historian["historic_kafka_topic"] == "uns.historic-events"
    assert historian["batch"]["max_events"] == 500


def test_prometheus_scrapes_ingestion_and_lake_mappers(compose: dict, prometheus: dict):
    ingestion_port = IngestionSettings.metrics_port
    datalake_port = DatalakeConfig.metrics_port
    jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert jobs["uns_kafka_mapper"]["static_configs"][0]["targets"] == [
        f"kafka_mapper_client:{ingestion_port}"
    ]
    assert jobs["uns_datalake"]["static_configs"][0]["targets"] == [
        f"datalake_mapper:{datalake_port}"
    ]
    assert str(compose["services"]["kafka_mapper_client"]["environment"]["UNS_kafka_mapper__metrics_port"]) == str(
        ingestion_port
    )


def test_prometheus_waits_for_pipeline_mappers(compose: dict, dev_compose: dict):
    for compose_file in (compose, dev_compose):
        depends_on = compose_file["services"]["uns_prometheus"]["depends_on"]
        assert "kafka_mapper_client" in depends_on
        assert "datalake_mapper" in depends_on


def test_prometheus_alerts_cover_backpressure_and_readiness(alerts: dict):
    alert_names = {rule["alert"] for group in alerts["groups"] for rule in group["rules"]}
    assert "UnsKafkaIngestionNotReady" in alert_names
    assert "UnsKafkaIngestionBackpressure" in alert_names
    assert "UnsDatalakeNotReady" in alert_names


def test_prometheus_config_loads_alert_rules(prometheus: dict):
    assert prometheus["rule_files"] == ["/etc/prometheus/alerts.yml"]
