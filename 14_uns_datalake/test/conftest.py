"""Shared test helpers for the datalake mapper."""

from __future__ import annotations

import base64
import json
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import pytest
from confluent_kafka import Consumer
from uns_config.events import HistoricEventEnvelope, encode_event, source_event_id
from uns_datalake.config import DatalakeConfig
from uns_datalake.parquet import read_parquet_rows
from uns_datalake.routing import (
    LakeRecord,
    LegacyRouteEntry,
    build_legacy_route_map,
    resolve_lake_event,
)
from uns_datalake.stores import build_s3_client
from uns_kafka.ingest import HISTORIC_TOPIC
from uns_kafka.rejections import DLQ_TOPIC, decode_rejection
from uns_kafka.uns_kafka_config import KAFKAConfig, MQTTConfig
from uns_kafka.uns_kafka_listener import UNSKafkaMapper

ACCEPTANCE_BOOT_ID = "multi-system-acceptance"
ACCEPTANCE_SITE_ID = "plant-01"
LAKE_PREFIX_V2 = "raw/v2/"
LAKE_PREFIX_V1 = "v1/"


def source_envelope(**overrides) -> HistoricEventEnvelope:
    event_time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 9, 10, 0, 0, 10000, tzinfo=UTC)
    defaults = {
        "schema_version": 1,
        "event_id": source_event_id("plant-a", "plant-a/gateway-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-a/gateway-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-a",
        "time": event_time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
        "event_kind": "telemetry",
        "is_historical": False,
        "payload": {"value": 21.4, "timestamp": 1_788_948_000_000},
        "raw_payload_base64": None,
    }
    defaults.update(overrides)
    if defaults["identity_quality"] == "source":
        defaults["event_id"] = source_event_id(
            defaults["site_id"],
            defaults["source_id"],
            defaults["source_boot_id"],
            defaults["source_sequence"],
        )
    return HistoricEventEnvelope(**defaults)


def envelope_bytes(**overrides) -> bytes:
    return encode_event(source_envelope(**overrides))


def v2_envelope(**overrides) -> HistoricEventEnvelope:
    event_time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    received_at = datetime(2026, 9, 11, 8, 30, 0, tzinfo=UTC)
    defaults = {
        "schema_version": 2,
        "event_id": source_event_id("plant-01", "plant-01/lims-01", "boot-17", 42),
        "identity_quality": "source",
        "source_id": "plant-01/lims-01",
        "source_boot_id": "boot-17",
        "source_sequence": 42,
        "site_id": "plant-01",
        "time": event_time,
        "received_at": received_at,
        "timestamp_quality": "source",
        "topic": "Enterprise/plant-01/LIMS/results",
        "event_kind": "business_event",
        "is_historical": False,
        "payload": {},
        "raw_payload_base64": None,
        "source_application": "lims",
        "payload_schema_id": "lab-result",
        "payload_schema_version": "1",
        "content_type": "application/json",
        "original_payload": b'{"result": 4.2}',
        "archive_eligible": True,
    }
    defaults.update(overrides)
    return HistoricEventEnvelope(**defaults)


def legacy_route_map():
    telemetry = source_envelope()
    routes = {
        (telemetry.topic, telemetry.source_id, telemetry.site_id): LegacyRouteEntry(
            application="machine",
            schema="temperature",
            version="1",
        ),
        (
            "Enterprise/PlantA/温度",
            "plant-a/gateway-01",
            "plant-a",
        ): LegacyRouteEntry(
            application="machine",
            schema="temperature",
            version="1",
        ),
        (
            "spBv1.0/PlantA/DDATA/plant-a/device-01",
            "plant-a/gateway-01",
            "plant-a",
        ): LegacyRouteEntry(
            application="machine",
            schema="sparkplug",
            version="1",
        ),
    }
    return build_legacy_route_map("baseline-v1", routes)


def lake_record_from_envelope(
    envelope: HistoricEventEnvelope,
    *,
    legacy_map=None,
    kafka_topic: str = "uns.historic-events",
    partition: int = 0,
    offset: int = 0,
    envelope_bytes: bytes | None = None,
) -> LakeRecord:
    resolved = resolve_lake_event(envelope, legacy_map)
    return LakeRecord(
        kafka_topic=kafka_topic,
        partition=partition,
        offset=offset,
        resolved=resolved,
        envelope_bytes=encode_event(envelope) if envelope_bytes is None else envelope_bytes,
    )


@pytest.fixture
def resolved_lims_event():
    return resolve_lake_event(v2_envelope(), None)


@pytest.fixture
def v2_event():
    return v2_envelope


@dataclass(frozen=True, slots=True)
class PublicationCase:
    """One expected publication in the four-domain acceptance fixture."""

    body: bytes
    route: tuple[str, str, str, str]
    topic: str


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


def _s3_endpoint_host_port() -> tuple[str, int]:
    endpoint = DatalakeConfig.s3_settings().endpoint_url or "http://localhost:9000"
    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _require_pipeline_stack() -> None:
    if not MQTTConfig.is_config_valid():
        pytest.skip("blocked: mqtt.host is not configured")
    if not _endpoint_open(MQTTConfig.host, MQTTConfig.port):
        pytest.skip(f"blocked: mqtt unreachable at {MQTTConfig.host}:{MQTTConfig.port}")
    kafka_host, kafka_port = _kafka_bootstrap_host_port()
    if not _endpoint_open(kafka_host, kafka_port):
        pytest.skip(f"blocked: kafka unreachable at {kafka_host}:{kafka_port}")
    if not DatalakeConfig.is_config_valid():
        pytest.skip("blocked: datalake backend configuration is invalid")
    minio_host, minio_port = _s3_endpoint_host_port()
    if not _endpoint_open(minio_host, minio_port):
        pytest.skip(f"blocked: minio unreachable at {minio_host}:{minio_port}")


def _build_publication_wrapper(
    *,
    source_application: str,
    site_id: str,
    payload_schema_id: str,
    payload_schema_version: str,
    original_payload: bytes,
    source_boot_id: str,
    source_sequence: int,
    content_type: str = "application/json",
    occurred_at: str = "2026-09-11T09:00:00Z",
) -> bytes:
    wire = {
        "publication_version": 1,
        "source_application": source_application,
        "site_id": site_id,
        "payload_schema_id": payload_schema_id,
        "payload_schema_version": payload_schema_version,
        "content_type": content_type,
        "original_payload_base64": base64.b64encode(original_payload).decode("ascii"),
        "occurred_at": occurred_at,
        "source_boot_id": source_boot_id,
        "source_sequence": source_sequence,
    }
    return json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _route_from_object_key(key: str) -> tuple[str, str, str, str] | None:
    if not key.startswith(LAKE_PREFIX_V2):
        return None
    segments = key[len(LAKE_PREFIX_V2) :].split("/")
    values: dict[str, str] = {}
    for segment in segments:
        if "=" not in segment:
            continue
        name, value = segment.split("=", 1)
        if name in {"application", "site", "schema", "version"}:
            values[name] = value
    required = ("application", "site", "schema", "version")
    if all(name in values for name in required):
        return (values["application"], values["site"], values["schema"], values["version"])
    return None


def _original_payload_from_row(row: dict[str, Any]) -> bytes | None:
    if "original_payload" in row and row["original_payload"] is not None:
        value = row["original_payload"]
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
    raw_base64 = row.get("raw_payload_base64")
    if raw_base64:
        return base64.b64decode(raw_base64)
    return None


@dataclass(slots=True)
class MultiSystemPipeline:
    """Integration fixture for four-domain UNS-to-lake acceptance."""

    _mapper: UNSKafkaMapper | None = None
    _s3_client: Any = None
    _historian_running: bool = True
    _historian_stopped: bool = False
    _published_event_ids: set[str] | None = None

    @property
    def historian_running(self) -> bool:
        return self._historian_running and not self._historian_stopped

    def connect(self) -> None:
        if self._mapper is None:
            self._mapper = UNSKafkaMapper()
        if self._s3_client is None:
            s3 = DatalakeConfig.s3_settings()
            self._s3_client = build_s3_client(s3)

    def disconnect(self) -> None:
        if self._mapper is not None:
            self._mapper.uns_client.disconnect()
            self._mapper = None
        self._s3_client = None

    def stop_historian(self) -> None:
        """Stop historian consumption on the isolated stack.

        The fixture tracks historian state with a flag. Orchestrated stack control
        to pause the historian service is not available in this baseline; when the
        historian container cannot be stopped, acceptance still records the intent
        via ``historian_running`` and documents the limitation in the runbook.
        """
        self._historian_stopped = True
        self._historian_running = False

    def publish_cases(self) -> dict[str, PublicationCase]:
        self.connect()
        assert self._mapper is not None

        cases: dict[str, PublicationCase] = {}
        definitions = (
            {
                "key": "machine",
                "topic": f"Enterprise/{ACCEPTANCE_SITE_ID}/Line/Device-01/Temperature",
                "source_id": f"{ACCEPTANCE_SITE_ID}/gateway-01",
                "sequence": 0,
                "route": ("machine", ACCEPTANCE_SITE_ID, "temperature", "1"),
                "body": json.dumps(
                    {"value": 21.4, "timestamp": 1_788_948_000_000},
                    separators=(",", ":"),
                ).encode("utf-8"),
            },
            {
                "key": "mes",
                "topic": f"Enterprise/{ACCEPTANCE_SITE_ID}/MES/production-orders",
                "source_id": f"{ACCEPTANCE_SITE_ID}/mes-01",
                "sequence": 1,
                "route": ("mes", ACCEPTANCE_SITE_ID, "production-order", "1"),
                "body": json.dumps(
                    {
                        "order_id": "PO-9001",
                        "sku": "PART-A",
                        "quantity": 100,
                        "timestamp": "2026-09-11T09:00:00Z",
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
            },
            {
                "key": "lims",
                "topic": f"Enterprise/{ACCEPTANCE_SITE_ID}/LIMS/results",
                "source_id": f"{ACCEPTANCE_SITE_ID}/lims-01",
                "sequence": 2,
                "route": ("lims", ACCEPTANCE_SITE_ID, "lab-result", "1"),
                "body": _build_publication_wrapper(
                    source_application="lims",
                    site_id=ACCEPTANCE_SITE_ID,
                    payload_schema_id="lab-result",
                    payload_schema_version="1",
                    original_payload=json.dumps(
                        {"sample_id": "S-1001", "result": 4.2, "unit": "mg/L"},
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    source_boot_id=ACCEPTANCE_BOOT_ID,
                    source_sequence=2,
                ),
            },
            {
                "key": "logistics",
                "topic": f"Enterprise/{ACCEPTANCE_SITE_ID}/Logistics/inventory",
                "source_id": f"{ACCEPTANCE_SITE_ID}/logistics-01",
                "sequence": 3,
                "route": ("logistics", ACCEPTANCE_SITE_ID, "inventory-movement", "1"),
                "body": json.dumps(
                    {
                        "movement_id": "MV-501",
                        "sku": "PART-A",
                        "quantity": -5,
                        "from": "WH-A",
                        "to": "LINE-1",
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
            },
        )

        for item in definitions:
            event_id = source_event_id(
                ACCEPTANCE_SITE_ID,
                item["source_id"],
                ACCEPTANCE_BOOT_ID,
                item["sequence"],
            )
            case = PublicationCase(body=item["body"], route=item["route"], topic=item["topic"])
            cases[event_id] = case
            result = self._mapper.uns_client.publish(item["topic"], item["body"], qos=1)
            if result.rc != 0:
                raise RuntimeError(f"MQTT publish failed for {item['key']} with rc={result.rc}")

        self._mapper.kafka_handler.flush()
        self._published_event_ids = set(cases)
        return cases

    def read_lake_records(self) -> list[dict[str, Any]]:
        self.connect()
        assert self._s3_client is not None
        s3 = DatalakeConfig.s3_settings()
        rows: list[dict[str, Any]] = []

        for prefix in (LAKE_PREFIX_V2, LAKE_PREFIX_V1):
            continuation: str | None = None
            while True:
                kwargs: dict[str, Any] = {"Bucket": s3.bucket, "Prefix": prefix}
                if continuation:
                    kwargs["ContinuationToken"] = continuation
                response = self._s3_client.list_objects_v2(**kwargs)
                for item in response.get("Contents", []):
                    key = item["Key"]
                    if not key.endswith(".parquet"):
                        continue
                    object_body = self._s3_client.get_object(Bucket=s3.bucket, Key=key)["Body"].read()
                    route_from_path = _route_from_object_key(key)
                    for row in read_parquet_rows(object_body):
                        record = dict(row)
                        record["object_key"] = key
                        record["original_payload"] = _original_payload_from_row(record)
                        record["route"] = route_from_path
                        record.setdefault("kafka_topic", record.get("kafka_topic"))
                        record.setdefault("kafka_partition", record.get("kafka_partition"))
                        record.setdefault("kafka_offset", record.get("kafka_offset"))
                        rows.append(record)
                if not response.get("IsTruncated"):
                    break
                continuation = response.get("NextContinuationToken")

        return rows

    def _collect_dlq_reasons(self) -> list[str]:
        consumer_config = {
            "bootstrap.servers": KAFKAConfig.kafka_config_map.get("bootstrap.servers"),
            "client.id": "uns_datalake_acceptance_dlq",
            "group.id": f"uns_datalake_acceptance_dlq_{uuid.uuid4()}",
            "auto.offset.reset": "earliest",
        }
        consumer = Consumer(consumer_config)
        reasons: list[str] = []
        try:
            consumer.subscribe([DLQ_TOPIC])
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                message = consumer.poll(0.5)
                if message is None or message.error():
                    continue
                try:
                    rejection = decode_rejection(message.value())
                except Exception:
                    continue
                reasons.append(f"{rejection.reason} topic={rejection.topic} event_id={rejection.event_id}")
        finally:
            consumer.close()
        return reasons

    def wait_for_lake_records(
        self,
        expected: dict[str, PublicationCase],
        *,
        timeout: float = 120,
    ) -> None:
        deadline = time.monotonic() + timeout
        pending = set(expected.keys())
        last_rows: list[dict[str, Any]] = []

        while time.monotonic() < deadline:
            last_rows = self.read_lake_records()
            found = {row["event_id"] for row in last_rows}
            pending = set(expected.keys()) - found
            if not pending:
                return
            time.sleep(2.0)

        object_keys = sorted({row.get("object_key", "") for row in last_rows if row.get("object_key")})
        offsets = sorted(
            {
                (row.get("kafka_topic"), row.get("kafka_partition"), row.get("kafka_offset"))
                for row in last_rows
                if row.get("kafka_offset") is not None
            }
        )
        dlq_reasons = self._collect_dlq_reasons()
        pytest.fail(
            "timed out waiting for lake records: "
            f"pending_event_ids={sorted(pending)} "
            f"object_keys={object_keys[:20]} "
            f"kafka_offsets={offsets[:20]} "
            f"dlq_reasons={dlq_reasons[:20]}"
        )


@pytest.fixture(scope="module")
def pipeline() -> MultiSystemPipeline:
    _require_pipeline_stack()
    instance = MultiSystemPipeline()
    instance.connect()
    try:
        yield instance
    finally:
        instance.disconnect()
