# ADR-0012: Multi-system UNS-to-lake raw delivery

## Status

Accepted — extends [ADR-0011](0011-canonical-historic-event-pipeline.md).

## Context

ADR-0011 established one canonical Kafka stream (`uns.historic-events`) with
independent consumers for historian, lake, and GraphQL. Machines, MES, LIMS,
logistics, and other business systems now need raw lake delivery partitioned by
publishing application, site, payload schema, and version — without coupling lake
archive to historian SQL or Metric extraction.

Business records do not require assets. The lake preserves publisher byte
fidelity and full provenance rather than normalizing business payloads at ingest.

## Decision

1. **Additive v2 envelope** — `schema_version: 2` adds routing metadata and
   `original_payload` bytes while v1 remains wire-compatible for telemetry
   (`00_uns_config.events`, `event_compatibility`).
2. **Registered publication routes** — MQTT topics resolve to exactly one
   `PublicationRoute` before payload decode (`publication_routes`,
   `publications`). Unknown routes are durable rejections, not best-effort defaults.
3. **Explicit v2 writer enablement** — `kafka_mapper.ingestion.v2_publications_enabled`
   defaults to `false`; operators opt in only after reader-first rollout.
4. **Frozen lake routing** — v2 paths derive from envelope metadata at receipt time.
   v1 paths use an immutable `legacy_route_map` revision with content digest;
   digest mismatch refuses startup.
5. **Raw v2 object layout** — `raw/v2/application=.../site=.../schema=.../version=.../ingestion_date=.../`.
   Legacy `v1/` prefix objects remain a separate dataset.
6. **At-least-once lake semantics** — verified immutable publication
   (`publish_exact` / `verify_exact`) precedes consumer offset commit. Duplicates
   are expected; readers deduplicate on Kafka coordinates and/or `event_id`.
7. **Independent lake consumer** — `uns_datalake` group with upload-before-commit;
   historian availability is not a lake dependency.

ADR-0011's Kafka transport decision is not superseded. This ADR adds envelope,
routing, and raw-fidelity decisions on top of the existing pipeline.

## Consequences

- Dual-version readers must deploy before v2 publishing is enabled.
- Rollback after v2 records exist requires keeping compatible readers until
  retained log ranges no longer need them; disabling publishing precedes reader
  downgrade.
- ADLS backends without atomic finalization cannot report ready.
- Operational rollout, replay, and rollback procedures live in
  [`docs/operations/uns-to-lake-delivery.md`](../operations/uns-to-lake-delivery.md).

## Related

- [Design](../superpowers/specs/2026-09-11-multi-system-uns-to-lake-design.md)
- [Implementation plan](../superpowers/plans/2026-09-11-multi-system-uns-to-lake.md)
- ADR-0011 (canonical historic event pipeline)
- ADR-0008 (OEE reads history, not the live stream)
