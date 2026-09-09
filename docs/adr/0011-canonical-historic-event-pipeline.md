# ADR-0011: Canonical historic event pipeline and coordinated development cutover

## Status

Accepted — Phase 1 development stack.

## Context

The platform originally mapped each MQTT topic to a dotted Kafka topic and wrote history
directly from MQTT. That model does not scale to bounded replay, independent consumer
groups, or explicit delivery boundaries between MQTT QoS 1 and durable storage.

Phase 1 replaces the default development path with one canonical stream:

```text
MQTT -> kafka_mapper -> uns.historic-events -> historian / datalake / GraphQL
```

Rejections durably land on `uns.historic-events.dlq`. GraphQL live subscriptions read
the same envelope topic with authorization on `envelope.topic`, not per-browser Kafka
consumers on derived topic names.

## Decision

1. **One canonical envelope** on `uns.historic-events` with explicit source and ingress
   identity fields (`00_uns_config.events`).
2. **Manual MQTT acknowledgment** only after Kafka (or DLQ) delivery succeeds
   (`06_uns_kafka.ingest`).
3. **Historian Kafka consumer** with SQL-before-offset commit semantics
   (`04_uns_historian.kafka_consumer`).
4. **Independent lake consumer** with upload-before-commit (`14_uns_datalake`).
5. **Coordinated Compose cutover** — no dual writes, no compatibility dotted topics in
   the default stack (`docker-compose.yml`, `kafka_topic_init`).
6. **Graph and Sparkplug MQTT clients remain** until Phase 2 moves them to the
   resilient target.

## Consequences

- Dotted Kafka topics and direct MQTT historian ingestion are removed from the default
  development stack.
- Legacy MQTT payloads without source boot/sequence receive ingress IDs; redelivery
  creates distinct IDs by design.
- Production HA, multi-site federation, and edge durability are Phase 2/3 work tracked
  separately.
- Qualification evidence lives in
  [`docs/benchmarks/uns-scalability-foundation.md`](../benchmarks/uns-scalability-foundation.md).

## Supersedes

- Per-topic dotted Kafka production as the default UNS export path.
- Direct MQTT historian ingestion in the default Compose stack.
- Dual-write and three-column lake requirements from the earlier datalake design — see
  [UNS datalake mapper design](../superpowers/specs/2026-09-08-uns-datalake-mapper-design.md)
  header for the explicit supersession note.

## Related

- [Design](../superpowers/specs/2026-09-09-uns-scalability-foundation-design.md)
- [Implementation plan](../superpowers/plans/2026-09-09-uns-scalability-foundation.md)
- ADR-0008 (OEE reads history, not the live stream)
