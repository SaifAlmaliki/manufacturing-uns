"""Archives canonical historic events from `uns.historic-events` to object storage.

Part of the Phase 1 coordinated pipeline ([ADR-0011](../docs/adr/0011-canonical-historic-event-pipeline.md)).
Qualification procedure: [benchmark report](../docs/benchmarks/uns-scalability-foundation.md).

Default development uses MinIO (`backend: s3` with `endpoint_url: http://uns_minio:9000`).
Production deployments select one backend only: AWS S3 or Azure ADLS.

Files are bounded by ingestion date/hour and Kafka partition:

```text
v1/ingest_date=2026-09-09/hour=10/partition=3/<flush_id>.parquet
```

Delivery is at-least-once: crash/replay may create duplicate Parquet objects with the
same event IDs. Readers must deduplicate on `event_id`.

Run unit tests:

```powershell
uv run pytest -n 0 -m "not integrationtest" test -v
```
