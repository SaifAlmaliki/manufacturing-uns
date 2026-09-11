"""Compose contract for the optional multi-system MQTT publisher."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
SIMULATOR_SCRIPT = REPO_ROOT / "conf" / "simulator" / "multi_system_publishers.py"


def test_multi_system_simulator_is_opt_in_compose_service():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    service = compose["services"]["multi_system_simulator"]

    assert service["profiles"] == ["multi-system-demo"]
    assert service["build"]["dockerfile"] == "./conf/simulator/Dockerfile.multi-system"
    assert service["depends_on"]["uns_mqtt_broker"]["condition"] == "service_healthy"
    dockerfile = (REPO_ROOT / "conf" / "simulator" / "Dockerfile.multi-system").read_text(
        encoding="utf-8"
    )
    assert "MQTT_HOST=uns_mqtt_broker" in dockerfile


def test_multi_system_simulator_builds_wrapped_and_raw_payloads():
    text = SIMULATOR_SCRIPT.read_text(encoding="utf-8")
    assert "uns-publication-v1" in text or "publication_version" in text
    assert "MES/orders" in text
    assert "LIMS/results" in text
    assert "SAP/material-documents" in text
    assert "build_publication_wrapper" in text


def test_multi_system_simulator_wrapper_round_trip():
    from uns_config.publications import decode_publication

    import importlib.util

    spec = importlib.util.spec_from_file_location("multi_system_publishers", SIMULATOR_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    body = b'{"sample_id":"S-1","result":4.2}'
    wire = module.build_publication_wrapper(
        source_application="lims",
        site_id="halabja",
        payload_schema_id="lab-result",
        payload_schema_version="1",
        original_payload=body,
        source_boot_id="boot-1",
        source_sequence=7,
    )
    message = decode_publication(wire)
    assert message.original_payload == body
    assert message.source_sequence == 7
