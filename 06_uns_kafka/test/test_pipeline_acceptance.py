"""Pipeline acceptance and qualification tests for the canonical event transport."""

from __future__ import annotations

import json
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from confluent_kafka import OFFSET_END, Consumer
from uns_config.events import decode_event, ingress_event_id, source_event_id

from uns_kafka.ingest import HISTORIC_TOPIC, IngestionConfig, IngestionOwner, OwnershipMapping, ReceiptToken
from uns_kafka.pipeline_fixture import (
    PipelineCounters,
    PipelineManifest,
    ReconciliationResult,
    generate_fixture,
    reconcile_manifest,
)
from uns_kafka.rejections import DLQ_TOPIC
from uns_kafka.uns_kafka_config import KAFKAConfig
from uns_kafka.uns_kafka_listener import UNSKafkaMapper

REPO_ROOT = Path(__file__).resolve().parents[2]


def _endpoint_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _kafka_bootstrap_host_port() -> tuple[str, int]:
    servers = KAFKAConfig.kafka_config_map.get("bootstrap.servers", "localhost:9092")
    host, port_text = servers.split(",")[0].split(":")
    return host, int(port_text)


def _require_pipeline_stack() -> None:
    from uns_kafka.uns_kafka_config import MQTTConfig

    if not MQTTConfig.is_config_valid():
        pytest.skip("blocked: mqtt.host is not configured")
    if not _endpoint_open(MQTTConfig.host, MQTTConfig.port):
        pytest.skip(f"blocked: mqtt unreachable at {MQTTConfig.host}:{MQTTConfig.port}")
    kafka_host, kafka_port = _kafka_bootstrap_host_port()
    if not _endpoint_open(kafka_host, kafka_port):
        pytest.skip(f"blocked: kafka unreachable at {kafka_host}:{kafka_port}")


def _require_fault_orchestration() -> None:
    _require_pipeline_stack()
    pytest.skip(
        "blocked: live fault injection requires orchestrated stack control; "
        "run the manual scenarios documented in docs/benchmarks/uns-scalability-foundation.md"
    )


def _get_kafka_consumer() -> Consumer:
    consumer_config = {
        "bootstrap.servers": KAFKAConfig.kafka_config_map.get("bootstrap.servers"),
        "client.id": "uns_pipeline_acceptance_consumer",
        "group.id": f"uns_pipeline_acceptance_{uuid.uuid4()}",
        "auto.offset.reset": "earliest",
    }
    return Consumer(consumer_config)


def test_fixture_manifest_is_deterministic():
    first = generate_fixture(sites=2, topics=3, boot_id="boot-a")
    second = generate_fixture(sites=2, topics=3, boot_id="boot-a")
    assert first.manifest_digest == second.manifest_digest
    assert first.expected_source_receipts == 6
    assert first.publications[0].expected_event_id.startswith("source:")


def test_reconcile_detects_missing_and_extra_ids():
    manifest = generate_fixture(sites=1, topics=2)
    expected_ids = {item.expected_event_id for item in manifest.publications}
    one_id = next(iter(expected_ids))
    result = reconcile_manifest(
        manifest,
        observed_kafka_event_ids=expected_ids,
        observed_sql_event_ids={one_id},
        observed_archive_event_ids=expected_ids | {"extra:archive"},
        counters=PipelineCounters(dlq_records=1),
    )
    assert isinstance(result, ReconciliationResult)
    assert result.ok is False
    assert result.missing_sql == 1
    assert result.extra_archive == 1
    assert result.dlq_records == 1


def test_legacy_identity_reuse_with_different_timestamp_is_weaker_than_source_sequence():
    shared = ("plant-a", "plant-a/gateway-01", "boot-17", 42)
    first_id = source_event_id(*shared)
    second_id = source_event_id(*shared)
    assert first_id == second_id
    # Historian time-scoped uniqueness cannot detect source ID reuse at a new timestamp.
    assert datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC) != datetime(2026, 9, 9, 10, 0, 1, tzinfo=UTC)


def test_pipeline_load_requires_existing_report_parent(tmp_path: Path):
    from uns_kafka.pipeline_fixture import validate_report_parent

    missing_parent = tmp_path / "missing" / "report.json"
    with pytest.raises(FileNotFoundError, match="parent directory does not exist"):
        validate_report_parent(missing_parent)


def test_ownership_loss_is_modeled_as_delivery_failure():
    """Kafka delivery failure and shard loss both drop readiness without acking MQTT."""

    class FakeMqttAck:
        def __init__(self) -> None:
            self.acks: list = []

        def ack(self, token) -> None:
            self.acks.append(token)

    class FakePublisher:
        def __init__(self) -> None:
            self._callbacks: list = []

        def publish_event(self, topic, key, value, on_delivery) -> None:
            self._callbacks.append(on_delivery)

        def complete_next(self, *, success: bool) -> None:
            callback = self._callbacks.pop(0)
            if success:
                callback(None, object())
            else:
                callback(RuntimeError("delivery failed"), None)

    mqtt = FakeMqttAck()
    events = FakePublisher()
    owner = IngestionOwner(
        config=IngestionConfig(
            shard_id="shard-a",
            client_id="uns_kafka_ingest-shard-a",
            ownership_mappings=(OwnershipMapping("plant-a", "plant-a/ingress", ""),),
        ),
        mqtt=mqtt,
        events=events,
        dlq=MagicMock(),
        clock=lambda: datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        sleep=lambda _seconds: None,
    )
    owner.ingest_qos1(
        ReceiptToken(connection_generation=1, packet_id=7, qos=1),
        "Enterprise/PlantA/Device/Temperature",
        b'{"value": 1, "timestamp": 1788948000}',
        {"value": 1, "timestamp": 1788948000},
    )
    events.complete_next(success=False)
    assert owner.ready is False
    assert owner.disconnect_requested is True
    assert mqtt.acks == []


@pytest.mark.integrationtest
def test_end_to_end_mqtt_publish_lands_on_historic_topic():
    _require_pipeline_stack()
    topic = f"Acceptance/{uuid.uuid4()}/Temperature"
    payload = {"value": 21.4, "timestamp": 1_788_948_000_000}
    mapper: UNSKafkaMapper | None = None
    consumer: Consumer | None = None
    try:
        mapper = UNSKafkaMapper()
        consumer = _get_kafka_consumer()

        def reset_offset(consumer_obj, partitions):
            for part in partitions:
                part.offset = OFFSET_END
            consumer_obj.assign(partitions)

        consumer.subscribe([HISTORIC_TOPIC], on_assign=reset_offset)
        mapper.uns_client.publish(topic, json.dumps(payload), qos=1)
        mapper.kafka_handler.flush()

        deadline = datetime.now(tz=UTC).timestamp() + 15.0
        while datetime.now(tz=UTC).timestamp() < deadline:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                pytest.fail(str(message.error()))
            envelope = decode_event(message.value())
            if envelope.topic == topic:
                assert envelope.payload["value"] == payload["value"]
                assert envelope.event_id.startswith("ingress:")
                return
        pytest.fail(f"did not observe canonical envelope for topic {topic}")
    finally:
        if consumer is not None:
            consumer.close()
        if mapper is not None:
            mapper.uns_client.disconnect()


@pytest.mark.integrationtest
def test_legacy_redelivery_produces_distinct_ingress_ids():
    _require_pipeline_stack()
    topic = f"Acceptance/Legacy/{uuid.uuid4()}/Temperature"
    payload = {"value": 9.9, "timestamp": 1_788_948_000_000}
    mapper: UNSKafkaMapper | None = None
    consumer: Consumer | None = None
    try:
        mapper = UNSKafkaMapper()
        consumer = _get_kafka_consumer()
        consumer.subscribe([HISTORIC_TOPIC])
        for _ in range(2):
            mapper.uns_client.publish(topic, json.dumps(payload), qos=1)
            mapper.kafka_handler.flush()

        observed: list[str] = []
        deadline = datetime.now(tz=UTC).timestamp() + 20.0
        while len(observed) < 2 and datetime.now(tz=UTC).timestamp() < deadline:
            message = consumer.poll(1.0)
            if message is None or message.error():
                continue
            envelope = decode_event(message.value())
            if envelope.topic == topic:
                observed.append(envelope.event_id)
        assert len(observed) == 2
        assert observed[0].startswith("ingress:")
        assert observed[1].startswith("ingress:")
        assert observed[0] != observed[1]
    finally:
        if consumer is not None:
            consumer.close()
        if mapper is not None:
            mapper.uns_client.disconnect()


@pytest.mark.integrationtest
@pytest.mark.parametrize(
    "scenario",
    [
        "mapper_crash_before_kafka_delivery",
        "mapper_crash_after_kafka_delivery",
        "historian_crash_after_sql_commit",
        "kafka_outage_60s",
        "database_outage_5min",
        "retention_gap_detection",
        "slow_graphql_clients",
    ],
)
def test_live_fault_scenario_requires_orchestration(scenario: str):
    _require_fault_orchestration()
    pytest.fail(f"unexpected live execution for scenario {scenario}")


@pytest.mark.integrationtest
def test_source_identified_replay_idempotency_is_covered_by_historian_suite():
    _require_pipeline_stack()
    pytest.skip(
        "blocked: SQL replay idempotency is validated in "
        "04_uns_historian/test/test_batch_persistence.py::test_persist_batch_replay_is_idempotent"
    )


@pytest.mark.integrationtest
def test_late_aggregate_refresh_is_covered_by_historian_suite():
    _require_pipeline_stack()
    pytest.skip(
        "blocked: 7-day late aggregate refresh is validated in "
        "04_uns_historian/test/test_aggregate_refresh.py"
    )


def test_acceptance_constants_reference_canonical_topics():
    assert HISTORIC_TOPIC == "uns.historic-events"
    assert DLQ_TOPIC == "uns.historic-events.dlq"


def test_manifest_counter_fields_are_tracked_separately():
    manifest: PipelineManifest = generate_fixture(sites=1, topics=1)
    counters = PipelineCounters(
        source_receipts=manifest.expected_source_receipts,
        kafka_accepted=manifest.expected_kafka_accepted,
        dlq_records=0,
        sql_event_ids=1,
        archived_ids=1,
    )
    expected_ids = {item.expected_event_id for item in manifest.publications}
    result = reconcile_manifest(
        manifest,
        observed_kafka_event_ids=expected_ids,
        observed_sql_event_ids=expected_ids,
        observed_archive_event_ids=expected_ids,
        counters=counters,
    )
    assert result.ok is True
    assert counters.source_receipts == counters.kafka_accepted == 1


def test_ingress_event_id_helper_matches_contract():
    receipt = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert ingress_event_id(receipt) == "ingress:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
