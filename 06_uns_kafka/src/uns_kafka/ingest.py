"""Bounded MQTT-to-Kafka ingestion lifecycle with manual QoS 1 acknowledgment."""

from __future__ import annotations

import base64
import json
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from uns_config.events import (
    MAX_ENVELOPE_BYTES,
    EnvelopeError,
    HistoricEventEnvelope,
    encode_event,
    event_key,
    ingress_event_id,
    source_event_id,
)
from uns_config.publication_routes import PublicationRoute, resolve_route
from uns_config.publications import PublisherMessage, resolve_publisher_message
from uns_config.uns_ingest import classify_event_kind, is_historic_event_topic

from uns_kafka.rejections import (
    DLQ_TOPIC,
    MAX_REJECTION_BYTES,
    RejectionError,
    RejectionRecord,
    encode_rejection,
    rejection_key,
)

HISTORIC_TOPIC = "uns.historic-events"
DEFAULT_PENDING_RECORD_LIMIT = 1000
DEFAULT_PENDING_BYTE_LIMIT = 16 * 1024 * 1024
DEFAULT_DRAIN_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ReceiptToken:
    connection_generation: int
    packet_id: int
    qos: int


@dataclass(frozen=True, slots=True)
class OwnershipMapping:
    site_id: str
    source_id: str
    topic_prefix: str = ""


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    shard_id: str
    client_id: str
    historic_topic: str = HISTORIC_TOPIC
    dlq_topic: str = DLQ_TOPIC
    ownership_mappings: tuple[OwnershipMapping, ...] = ()
    publication_routes: tuple[PublicationRoute, ...] = ()
    v2_publications_enabled: bool = False
    pending_record_limit: int = DEFAULT_PENDING_RECORD_LIMIT
    pending_byte_limit: int = DEFAULT_PENDING_BYTE_LIMIT
    timestamp_attribute: str = "timestamp"


@dataclass(slots=True)
class PendingDelivery:
    token: ReceiptToken
    byte_size: int
    target: Literal["historic", "dlq"]
    dlq_reason: str | None = None


class MqttAckPort(Protocol):
    def ack(self, token: ReceiptToken) -> None: ...


class EventPublisherPort(Protocol):
    def publish_event(
        self,
        topic: str,
        key: bytes | None,
        value: bytes,
        on_delivery: Callable[[Exception | None, object | None], None],
    ) -> None: ...


@dataclass(slots=True)
class IngestionOwner:
    config: IngestionConfig
    mqtt: MqttAckPort
    events: EventPublisherPort
    dlq: EventPublisherPort
    clock: Callable[[], datetime] = field(default_factory=lambda: (lambda: datetime.now(UTC)))
    monotonic: Callable[[], float] = field(default=time.monotonic)
    sleep: Callable[[float], None] = field(default=time.sleep)
    jitter_fn: Callable[[], float] = field(default=random.random)
    on_admitted: Callable[[], None] | None = field(default=None, repr=False)
    on_historic_delivered: Callable[[], None] | None = field(default=None, repr=False)
    on_dlq_delivered: Callable[[str], None] | None = field(default=None, repr=False)
    on_qos0_delivered: Callable[[], None] | None = field(default=None, repr=False)

    connection_generation: int = 1
    ready: bool = True
    disconnect_requested: bool = False
    qos0_delivered: int = 0
    pending_records: int = 0
    pending_bytes: int = 0
    reconnect_backoff_seconds: float = 0.0
    halted: bool = False
    halt_reason: str | None = None
    _pending: dict[str, PendingDelivery] = field(default_factory=dict, init=False)

    def on_reconnect(self) -> None:
        self.connection_generation += 1
        self.reconnect_backoff_seconds = min(
            60.0,
            max(1.0, self.reconnect_backoff_seconds * 2 or 1.0) * (0.5 + self.jitter_fn()),
        )

    def ingest_qos0(
        self,
        topic: str,
        payload_bytes: bytes,
        decoded_payload: dict[str, Any] | None,
    ) -> None:
        if not is_historic_event_topic(topic):
            return
        if not self.ready or self.halted:
            return
        try:
            envelope = self._resolve_ingress(topic, payload_bytes, decoded_payload)
        except _ExcludeWithoutPublish:
            return
        except _RejectAsDlq as rejection:
            self._publish_rejection_best_effort(rejection.record)
            return
        except _RejectUnarchivable:
            return
        self.events.publish_event(
            self.config.historic_topic,
            event_key(envelope),
            encode_event(envelope),
            lambda *_: None,
        )
        self.qos0_delivered += 1
        if self.on_qos0_delivered is not None:
            self.on_qos0_delivered()

    def ingest_qos1(
        self,
        token: ReceiptToken,
        topic: str,
        payload_bytes: bytes,
        decoded_payload: dict[str, Any] | None,
    ) -> None:
        if token.qos != 1:
            raise ValueError("ingest_qos1 requires QoS 1")
        if token.connection_generation != self.connection_generation:
            return
        if not is_historic_event_topic(topic):
            return
        if self.halted:
            return
        if not self.ready:
            self._mark_backpressure()
            return

        try:
            envelope = self._resolve_ingress(topic, payload_bytes, decoded_payload)
        except _ExcludeWithoutPublish:
            self._release_without_publish(token)
            return
        except _RejectAsDlq as rejection:
            self._begin_delivery(token, rejection.record, target="dlq")
            return
        except _RejectUnarchivable as fatal:
            self.halted = True
            self.halt_reason = fatal.reason
            self.ready = False
            self.disconnect_requested = True
            return

        self._begin_delivery(token, envelope, target="historic")

    def complete_delivery(self, delivery_id: str, *, success: bool) -> None:
        pending = self._pending.pop(delivery_id, None)
        if pending is None:
            return
        self.pending_records -= 1
        self.pending_bytes -= pending.byte_size
        if not success:
            self.ready = False
            self.disconnect_requested = True
            return
        if pending.token.connection_generation != self.connection_generation:
            return
        self.mqtt.ack(pending.token)
        if pending.target == "historic" and self.on_historic_delivered is not None:
            self.on_historic_delivered()
        elif pending.target == "dlq" and self.on_dlq_delivered is not None and pending.dlq_reason is not None:
            self.on_dlq_delivered(pending.dlq_reason)

    def shutdown(self, drain_seconds: float = DEFAULT_DRAIN_SECONDS) -> None:
        deadline = self.monotonic() + drain_seconds
        while self._pending and self.monotonic() < deadline:
            self.sleep(0.01)

    def next_backoff_seconds(self) -> float:
        return self.reconnect_backoff_seconds

    def _begin_delivery(
        self,
        token: ReceiptToken,
        payload: HistoricEventEnvelope | RejectionRecord,
        *,
        target: Literal["historic", "dlq"],
    ) -> None:
        if target == "historic":
            assert isinstance(payload, HistoricEventEnvelope)
            wire = encode_event(payload)
            topic = self.config.historic_topic
            key = event_key(payload)
        else:
            assert isinstance(payload, RejectionRecord)
            wire = encode_rejection(payload)
            topic = self.config.dlq_topic
            key = rejection_key(payload)

        if not self._reserve_pending(len(wire)):
            self._mark_backpressure()
            return

        delivery_id = str(uuid.uuid4())
        dlq_reason = payload.reason if target == "dlq" and isinstance(payload, RejectionRecord) else None
        self._pending[delivery_id] = PendingDelivery(
            token=token,
            byte_size=len(wire),
            target=target,
            dlq_reason=dlq_reason,
        )
        if target == "historic" and self.on_admitted is not None:
            self.on_admitted()

        def on_delivery(err: Exception | None, _msg: object | None) -> None:
            self.complete_delivery(delivery_id, success=err is None)

        try:
            publisher = self.events if target == "historic" else self.dlq
            publisher.publish_event(topic, key, wire, on_delivery)
        except BufferError:
            self._pending.pop(delivery_id, None)
            self.pending_records -= 1
            self.pending_bytes -= len(wire)
            self._mark_backpressure()

    def _publish_rejection_best_effort(self, record: RejectionRecord) -> None:
        try:
            wire = encode_rejection(record)
        except RejectionError:
            return
        self.dlq.publish_event(
            self.config.dlq_topic,
            rejection_key(record),
            wire,
            lambda *_: None,
        )

    def _resolve_ingress(
        self,
        topic: str,
        payload_bytes: bytes,
        decoded_payload: dict[str, Any] | None,
    ) -> HistoricEventEnvelope:
        if len(payload_bytes) > MAX_REJECTION_BYTES:
            raise _RejectUnarchivable("oversize")
        received_at = self.clock()
        receipt_uuid = uuid.uuid4()

        if self.config.v2_publications_enabled and self.config.publication_routes:
            route = self._resolve_publication_route(topic)
            if route is not None:
                return self._build_v2_envelope(
                    topic,
                    route,
                    payload_bytes,
                    received_at=received_at,
                    receipt_uuid=receipt_uuid,
                )

        ownership = resolve_ownership(topic, self.config.ownership_mappings)
        if ownership is None:
            raise _RejectAsDlq(
                self._rejection_record(
                    topic=topic,
                    payload_bytes=payload_bytes,
                    received_at=received_at,
                    reason="unknown_ownership",
                )
            )
        return self._build_v1_envelope(
            topic,
            payload_bytes,
            decoded_payload,
            received_at=received_at,
            receipt_uuid=receipt_uuid,
            ownership=ownership,
        )

    def _resolve_publication_route(self, topic: str) -> PublicationRoute | None:
        try:
            return resolve_route(topic, self.config.publication_routes)
        except EnvelopeError:
            return None

    def _build_v2_envelope(
        self,
        topic: str,
        route: PublicationRoute,
        payload_bytes: bytes,
        *,
        received_at: datetime,
        receipt_uuid: uuid.UUID,
    ) -> HistoricEventEnvelope:
        if not route.archive_eligible:
            raise _ExcludeWithoutPublish()

        try:
            message = resolve_publisher_message(payload_bytes, route)
        except EnvelopeError as exc:
            raise _RejectAsDlq(
                self._rejection_record(
                    topic=topic,
                    payload_bytes=payload_bytes,
                    received_at=received_at,
                    reason=exc.reason,
                )
            ) from exc

        if message.source_boot_id is not None and message.source_sequence is not None:
            event_id = source_event_id(
                route.site_id,
                route.source_id,
                message.source_boot_id,
                message.source_sequence,
            )
            identity_quality: Literal["source", "ingress"] = "source"
        else:
            event_id = ingress_event_id(receipt_uuid)
            identity_quality = "ingress"

        if message.occurred_at is not None:
            event_time = message.occurred_at
            timestamp_quality: Literal["source", "ingress"] = "source"
        else:
            event_time = received_at
            timestamp_quality = "ingress"

        envelope = HistoricEventEnvelope(
            schema_version=2,
            event_id=event_id,
            identity_quality=identity_quality,
            source_id=route.source_id,
            source_boot_id=message.source_boot_id,
            source_sequence=message.source_sequence,
            site_id=route.site_id,
            time=event_time,
            received_at=received_at,
            timestamp_quality=timestamp_quality,
            topic=topic,
            event_kind=route.event_kind,
            is_historical=False,
            payload=_compatibility_payload(message, route),
            raw_payload_base64=None,
            source_application=message.source_application,
            payload_schema_id=message.payload_schema_id,
            payload_schema_version=message.payload_schema_version,
            content_type=message.content_type,
            original_payload=message.original_payload,
            archive_eligible=route.archive_eligible,
        )
        return self._finalize_envelope(envelope, topic, payload_bytes, received_at)

    def _build_v1_envelope(
        self,
        topic: str,
        payload_bytes: bytes,
        decoded_payload: dict[str, Any] | None,
        *,
        received_at: datetime,
        receipt_uuid: uuid.UUID,
        ownership: OwnershipMapping,
    ) -> HistoricEventEnvelope:
        event_kind = classify_event_kind(topic)
        raw_payload_base64 = None
        payload: dict[str, Any]
        if topic.startswith("spBv1.0/"):
            raw_payload_base64 = base64.b64encode(payload_bytes).decode("ascii")
            payload = decoded_payload or {}
        else:
            if decoded_payload is None:
                raise _RejectAsDlq(
                    self._rejection_record(
                        topic=topic,
                        payload_bytes=payload_bytes,
                        received_at=received_at,
                        reason="invalid_json",
                    )
                )
            payload = decoded_payload

        timestamp_quality: Literal["source", "ingress"] = "ingress"
        event_time = received_at
        if self.config.timestamp_attribute in payload:
            try:
                from uns_config.events import normalize_legacy_timestamp_value

                seconds = normalize_legacy_timestamp_value(payload[self.config.timestamp_attribute])
                event_time = datetime.fromtimestamp(seconds, tz=UTC)
                timestamp_quality = "source"
            except EnvelopeError:
                timestamp_quality = "ingress"

        envelope = HistoricEventEnvelope(
            schema_version=1,
            event_id=ingress_event_id(receipt_uuid),
            identity_quality="ingress",
            source_id=ownership.source_id,
            source_boot_id=None,
            source_sequence=None,
            site_id=ownership.site_id,
            time=event_time,
            received_at=received_at,
            timestamp_quality=timestamp_quality,
            topic=topic,
            event_kind=event_kind,
            is_historical=False,
            payload=payload,
            raw_payload_base64=raw_payload_base64,
        )
        return self._finalize_envelope(envelope, topic, payload_bytes, received_at)

    def _finalize_envelope(
        self,
        envelope: HistoricEventEnvelope,
        topic: str,
        payload_bytes: bytes,
        received_at: datetime,
    ) -> HistoricEventEnvelope:
        try:
            encoded = encode_event(envelope)
        except EnvelopeError as exc:
            raise _RejectAsDlq(
                self._rejection_record(
                    topic=topic,
                    payload_bytes=payload_bytes,
                    received_at=received_at,
                    reason=exc.reason,
                )
            ) from exc
        if len(encoded) > MAX_ENVELOPE_BYTES:
            raise _RejectAsDlq(
                self._rejection_record(
                    topic=topic,
                    payload_bytes=payload_bytes,
                    received_at=received_at,
                    reason="oversize",
                )
            )
        return envelope

    def _rejection_record(
        self,
        *,
        topic: str,
        payload_bytes: bytes,
        received_at: datetime,
        reason: str,
    ) -> RejectionRecord:
        return RejectionRecord(
            stage="mqtt_ingress",
            origin=self.config.shard_id,
            reason=reason,
            captured_at=received_at,
            topic=topic,
            original_bytes=payload_bytes[:MAX_REJECTION_BYTES],
        )

    def _release_without_publish(self, token: ReceiptToken) -> None:
        if token.connection_generation != self.connection_generation:
            return
        self.mqtt.ack(token)

    def _reserve_pending(self, byte_size: int) -> bool:
        if self.pending_records + 1 > self.config.pending_record_limit:
            return False
        if self.pending_bytes + byte_size > self.config.pending_byte_limit:
            return False
        self.pending_records += 1
        self.pending_bytes += byte_size
        return True

    def _mark_backpressure(self) -> None:
        self.ready = False
        self.disconnect_requested = True


@dataclass(slots=True)
class _RejectAsDlq(Exception):
    record: RejectionRecord


@dataclass(slots=True)
class _RejectUnarchivable(Exception):
    reason: str


@dataclass(slots=True)
class _ExcludeWithoutPublish(Exception):
    pass


def _compatibility_payload(message: PublisherMessage, route: PublicationRoute) -> dict[str, Any]:
    if route.event_kind not in {"telemetry", "sparkplug_raw", "lifecycle", "command"}:
        return {}
    if message.content_type != "application/json":
        return {}
    try:
        parsed = json.loads(message.original_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolve_ownership(
    topic: str,
    mappings: tuple[OwnershipMapping, ...],
) -> OwnershipMapping | None:
    matches = [mapping for mapping in mappings if topic.startswith(mapping.topic_prefix)]
    if not matches:
        return None
    return max(matches, key=lambda mapping: len(mapping.topic_prefix))


def validate_ownership_mappings(mappings: tuple[OwnershipMapping, ...]) -> None:
    prefixes = [mapping.topic_prefix for mapping in mappings]
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("ownership topic_prefix values must be unique")
    empty_prefixes = sum(1 for prefix in prefixes if prefix == "")
    if empty_prefixes > 1:
        raise ValueError("only one ownership mapping may use an empty topic_prefix")


def validate_shard_client_id(client_id: str) -> None:
    if not client_id or "uns_kafka_listener-" in client_id:
        raise ValueError("ingestion requires a configured stable MQTT client_id")
