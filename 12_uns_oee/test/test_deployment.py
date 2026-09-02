"""The three files that have to agree about port 9095, and the one that has to agree about
the startup order.

None of this fails loudly when it drifts: a wrong scrape target produces an empty panel,
not an error, and a missing `depends_on` produces a container that crash-loops for a
minute and then works. Both are the kind of thing that gets found in a demo.

Reads the real deployment files, in the spirit of `99_simulator/test/test_self_telemetry.py`.
"""

from pathlib import Path

import pytest
import yaml

from uns_oee.oee_config import OeeConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
PROMETHEUS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"

SERVICE = "oee_client"
JOB = "uns_oee"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prometheus() -> dict:
    return yaml.safe_load(PROMETHEUS_FILE.read_text(encoding="utf-8"))


def test_the_scrape_target_is_the_port_the_engine_binds(compose: dict, prometheus: dict):
    """
    The one assertion that earns this file. `OeeConfig`'s default is the source of truth;
    the compose override and the scrape target both have to name it.
    """
    port = OeeConfig(mqtt_host="localhost").metrics_port

    jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert JOB in jobs, f"prometheus.yml has no {JOB} job"
    assert jobs[JOB]["static_configs"][0]["targets"] == [f"{SERVICE}:{port}"]
    assert str(compose["services"][SERVICE]["environment"]["UNS_oee__metrics_port"]) == str(port)


def test_the_metrics_port_is_not_shared_with_another_service(prometheus: dict):
    """Each scrape target is unique. Port numbers may repeat across hosts (opcua and the
    simulator both bind 9093 inside the compose network); colliding on the same host:port
    is what would empty a panel.
    """
    targets = [job["static_configs"][0]["targets"][0] for job in prometheus["scrape_configs"]]
    assert len(targets) == len(set(targets)), f"two Prometheus jobs scrape the same target: {targets}"


def test_the_metrics_port_is_not_published_to_the_host(compose: dict):
    """Prometheus scrapes from inside the network. Nothing outside needs to reach 9095."""
    assert "ports" not in compose["services"][SERVICE]


def test_the_engine_waits_for_its_tables_and_its_master_data(compose: dict):
    """
    `asset_model_setup` runs the `0003` migration and imports `conf/oee/*.yaml`. Starting
    before it means a first pass with no OeeUnit rows, which is silent by design.
    """
    depends_on = compose["services"][SERVICE]["depends_on"]
    assert depends_on["asset_model_setup"]["condition"] == "service_completed_successfully"
    assert depends_on["tsdb_setup_script"]["condition"] == "service_completed_successfully"
    assert depends_on["uns_timescale_db"]["condition"] == "service_healthy"
    assert depends_on["uns_mqtt_broker"]["condition"] == "service_healthy"


def test_the_engine_does_not_wait_for_the_historian_process(compose: dict):
    """
    It reads the `uns_metrics` table, not the mapper. A shift with no samples is a
    NO_INPUT_DATA result, so the mapper being unhealthy must not stop the engine.
    """
    assert "historian_client" not in compose["services"][SERVICE]["depends_on"]


def test_prometheus_scrapes_the_engine(compose: dict):
    """Without this, the job resolves to nothing until the engine happens to be up first."""
    assert SERVICE in compose["services"]["uns_prometheus"]["depends_on"]


def test_the_engine_gets_the_database_credentials_it_needs(compose: dict):
    """
    Reads `uns_metrics` and writes `oee.*` as the same role the historian uses. The
    password comes from the environment, never from the compose file.
    """
    environment = compose["services"][SERVICE]["environment"]
    assert environment["UNS_historian__hostname"] == "uns_timescale_db"
    assert environment["UNS_historian__metrics_table"] == "uns_metrics"
    assert environment["UNS_historian__password"] == "${UNS_historian__password}"  # ruff: ignore[hardcoded-password-string]
    assert environment["UNS_mqtt__host"] == "uns_mqtt_broker"
