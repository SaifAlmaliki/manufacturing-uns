# UNS datalake mapper

Archives canonical historic events from `uns.historic-events` to object storage.

Part of the Phase 1 coordinated pipeline ([ADR-0011](../docs/adr/0011-canonical-historic-event-pipeline.md)).
Multi-system raw delivery is described in
[ADR-0012](../docs/adr/0012-multi-system-uns-to-lake-delivery.md), the
[operations runbook](../docs/operations/uns-to-lake-delivery.md), and the
[qualification report](../docs/benchmarks/uns-to-lake-delivery.md).

Default development uses MinIO (`backend: s3` with `endpoint_url: http://uns-minio:9000`).
Production deployments select one backend only: AWS S3 or Azure ADLS.

## Object layout

Legacy v1 exports (pre multi-system delivery):

```text
v1/ingest_date=2026-09-09/hour=10/partition=3/<flush_id>.parquet
```

New multi-system exports (v2 envelopes and qualified v1 replay):

```text
raw/v2/application=lims/site=halabja/schema=lab-result/version=1/ingestion_date=2026-09-11/<object_id>.parquet
```

`ingestion_date` is the UTC receipt date (`received_at`), not business event time.
V1 legacy envelopes resolve routes through an optional frozen `datalake.legacy_route_map`
when replaying old Kafka records. Live routing uses `kafka_mapper.ingestion.publication_routes`.

## Consumer independence

The lake mapper uses its own Kafka consumer group (`uns_datalake` by default).
It does not read from TimescaleDB and does not depend on the historian service.
Historian availability cannot gate lake delivery.

Business records do not require assets or Metric rows. Archive eligibility is
declared per publication route, not inferred from the asset model.

## Delivery semantics

Delivery is at-least-once: crash or replay may create duplicate Parquet objects
with the same event IDs or Kafka coordinates. Readers must deduplicate on
`(kafka_topic, partition, offset)` and/or `event_id`.

Verified immutable publication (`publish_exact` then `verify_exact`) precedes
consumer offset commit. ADLS backends without supported atomic finalization fail
readiness rather than overwriting existing objects.

## Configuration highlights

| Key | Purpose |
| --- | --- |
| `datalake.kafka.group_id` | Independent consumer group (`uns_datalake`) |
| `datalake.kafka.initial_position` | New-group start policy (`require_committed` default) |
| `datalake.legacy_route_map.revision` | Frozen v1 routing revision |
| `datalake.flush.max_active_route_groups` | Bounded multi-route batching (default 64) |

V2 publishing is controlled in `kafka_mapper.ingestion.v2_publications_enabled`
(default `false`). Enable only after reader-first rollout per the runbook.

## Tests

```powershell
uv run pytest -n 0 -m "not integrationtest" test -v
```

Deployment contract checks:

```powershell
uv run pytest 14_uns_datalake/test/test_deployment.py -n 0 -v
```
