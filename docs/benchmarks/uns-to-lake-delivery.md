# Multi-system UNS-to-lake Delivery — Qualification Report

> **Status:** Template for multi-system raw lake delivery evidence. A report produced
> by this template documents measured behaviour; it does not claim production
> qualification until every backend row is executed or explicitly blocked.

Design reference: [Multi-system UNS-to-lake design](../superpowers/specs/2026-09-11-multi-system-uns-to-lake-design.md).

Implementation plan: [Delivery plan](../superpowers/plans/2026-09-11-multi-system-uns-to-lake.md).

Operations runbook: [UNS-to-lake delivery](../operations/uns-to-lake-delivery.md).

## 1. Run metadata

| Field | Value |
| --- | --- |
| Date (UTC) | _fill on run_ |
| Operator | _fill on run_ |
| Git commit | _fill on run_ |
| Host CPU / RAM | _fill on run_ |
| OS / kernel | _fill on run_ |
| Docker / Compose version | _fill on run_ |
| Lake backend | `s3` (MinIO) / `s3` (AWS) / `adls` |
| v2 publications enabled | _true/false at run time_ |
| Legacy route map revision | _e.g. halabja-baseline-v1_ |

Record pinned image digests for every service in the qualification stack:

| Service | Image | Digest |
| --- | --- | --- |
| `uns_kafka_broker` | `apache/kafka:3.9.0` | _fill on run_ |
| `uns_minio` | `minio/minio:RELEASE.2025-04-22T22-12-26Z` | _fill on run_ |
| `kafka_mapper_client` | local build | _fill on run_ |
| `historian_client` | local build | _fill on run_ |
| `datalake_mapper` | local build | _fill on run_ |
| `graphql_server` | local build | _fill on run_ |

## 2. Topology and configured limits

Default development stack (`uv run uns_compose up -d --build`):

```text
MQTT (HiveMQ Edge) -> kafka_mapper -> uns.historic-events -> historian / datalake / GraphQL
                                                         -> uns.historic-events.dlq (rejections)
Parquet v2 -> object store raw/v2/application=.../site=.../schema=.../version=.../ingestion_date=.../
Parquet v1 -> object store v1/ingest_date=.../hour=.../partition=.../  (legacy dataset)
SQL -> TimescaleDB (uns_historian, independent of lake)
```

Configured limits (from `conf/settings.yaml`):

| Component | Limit |
| --- | --- |
| Ingestion pending records | 1,000 |
| Ingestion pending bytes | 16 MiB |
| Datalake flush records | 10,000 |
| Datalake flush bytes | 8 MiB |
| Datalake worker bytes | 32 MiB |
| Datalake flush age | 60 s |
| Max record size | 1 MiB |
| Max active route groups | 64 |
| Max encoded bytes (artifact) | 16 MiB |
| Canonical topic partitions | 12 |
| Historic retention | 7 days |
| DLQ retention | 30 days |

## 3. Four-domain acceptance fixture

Integration acceptance publishes four representative domains with known source
boot/sequence identity:

| Domain | Application | Schema | Wire format |
| --- | --- | --- | --- |
| Machine temperature | `machine` | `temperature/1` | `raw` |
| MES production order | `mes` | `production-order/1` | `raw` |
| LIMS lab result | `lims` | `lab-result/1` | `uns-publication-v1` |
| Logistics inventory | `logistics` | `inventory-movement/1` | `raw` |

Run the acceptance test against a live stack with v2 publications enabled:

```powershell
uv run --package uns_datalake pytest 14_uns_datalake/test/test_multi_system_pipeline.py::test_four_domains_reach_lake_with_historian_stopped -n 0 -v
```

Prerequisites: MQTT, Kafka, MinIO/S3 reachable; `ingestion.v2_publications_enabled: true`;
four publication routes registered. Missing services must appear as **blocked** skips.

Reconcile physical lake rows:

| Check | How to verify |
| --- | --- |
| Event IDs | Match `source_event_id(site, source_id, boot, sequence)` for each case |
| Body bytes | `original_payload` column equals published MQTT body |
| Route tuple | `(application, site, schema, version)` matches object path and row metadata |
| Historian independence | Historian stopped; lake rows present without SQL dependency |
| Kafka coordinates | `kafka_topic`, `kafka_partition`, `kafka_offset` populated per row |

## 4. Fault qualification matrix

Automated unit and contract tests cover safe recovery semantics. Live fault injection
requires orchestrated stack control. Record **passed**, **failed**, **blocked**, or
**not qualified** per row. Unit-only success is not durability qualification.

Offline contract suites:

```powershell
uv run pytest -n 0 -m "not integrationtest" 00_uns_config/test 06_uns_kafka/test 14_uns_datalake/test
```

| Scenario | Expected invariant | Unit/contract evidence | Live status | Notes |
| --- | --- | --- | --- | --- |
| Historian stopped throughout | Four domains archive without SQL/Metric dependency | `test_four_domains_reach_lake_with_historian_stopped` | _fill_ | _fill_ |
| Store stopped during second route upload | Earlier objects remain; no unsafe commit | `test_multi_route_mapper.py`, `test_mapper.py` | _fill_ | _fill_ |
| Kill after upload/before commit | Replay may duplicate rows; coordinates identify repeats | `test_duplicate_event_ids_survive_replay_in_separate_files` | _fill_ | _fill_ |
| Rebalance during delayed upload | Old generation cannot commit | `test_ownership_revoked_during_flush_does_not_commit` | _fill_ | _fill_ |
| DLQ timeout/failure | No rejection checkpointed without ACKed delivery | `test_dlq_unavailable_does_not_resolve_or_commit` | _fill_ | _fill_ |
| Existing key has different content | No overwrite; integrity readiness fails | `test_existing_mismatch_is_not_overwritten` | _fill_ | _fill_ |
| Partial ADLS staging upload | No partial final `.parquet` | `test_adls_staging_key_is_outside_raw_v2` | **not qualified** | Requires live Azure |
| Committed offset older than retained log | Explicit `data_gap` failure | `test_committed_before_retained_low_is_data_gap_even_with_earliest` | _fill_ | _fill_ |
| Two schema versions / two sites / two applications | Exact paths with original bytes | `test_routing.py`, `test_parquet_v2.py` | _fill_ | _fill_ |
| Legacy map/live registration changed | V2 frozen; v1 digest mismatch refused | `test_v2_route_ignores_changed_live_registration` | _fill_ | _fill_ |
| Many small routes / near-limit records | Bounded buffers | `test_multi_route_batch.py` | _fill_ | Record RSS separately |
| Retained bootstrap / fresh retained publication | Bootstrap not duplicated as history | `06_uns_kafka/test/test_publication_ingest.py` | _fill_ | _fill_ |

## 5. Backend qualification

Record each backend separately. Distinguish contract-test success from live-backend
durability evidence.

### 5.1 MinIO / S3-compatible (development default)

| Field | Value |
| --- | --- |
| Backend | MinIO `RELEASE.2025-04-22T22-12-26Z` |
| Conditional create API | `If-None-Match: *` |
| Test IDs executed | _e.g. test_publication.py, test_stores.py_ |
| Duration | _fill_ |
| Duplicates observed | _fill_ |
| Rejections / gaps | _fill_ |
| Artifacts | _object keys, digests_ |
| Status | _passed / failed / not qualified_ |

### 5.2 AWS S3 (production)

| Field | Value |
| --- | --- |
| Region / bucket | _fill_ |
| Conditional create API | _fill supported precondition_ |
| Test IDs executed | _fill_ |
| Duration | _fill_ |
| Status | _passed / failed / not qualified_ |

### 5.3 Azure ADLS Gen2

| Field | Value |
| --- | --- |
| Account / container | _fill_ |
| Atomic finalize supported | _true/false per installed API_ |
| Staging prefix (outside `raw/v2`) | _fill_ |
| Live partial-upload evidence | _fill or blocked_ |
| Test IDs executed | _fill_ |
| Status | _passed / failed / not qualified_ |

ADLS readiness fails when `atomic_finalize_supported` is false. Do not downgrade to
`overwrite=True`.

## 6. Capacity and latency evidence

Measure sustained ingress and catch-up throughput for the representative workload.
Catch-up must exceed live ingress for the documented workload. Unsupported capacity
is a **qualification gap**, not permission to add a processing platform.

| Metric | Target | Observed | Pass? |
| --- | --- | --- | --- |
| Sustained canonical ingress | _fill target events/s_ | _fill_ | _fill_ |
| Catch-up throughput after outage | > sustained ingress | _fill_ | _fill_ |
| p95 lake latency (received_at → verified object) | _fill target_ | _fill_ | _fill_ |
| Kafka retention headroom (hours at peak rate) | _fill_ | _fill_ | _fill_ |
| Readback-verification bandwidth | _fill_ | _fill_ | _fill_ |
| Active route groups at peak | ≤ 64 | _fill_ | _fill_ |
| Datalake mapper RSS peak | _fill_ | _fill_ | _fill_ |
| Arrow encode scratch overhead | _fill_ | _fill_ | _fill_ |
| Object-store outage recovery (max supported duration) | _fill_ | _fill_ | _fill_ |

## 7. Duplicate and replay guarantees

| Guarantee | Mechanism |
| --- | --- |
| Delivery semantics | At-least-once from Kafka through verified Parquet |
| Duplicate identification | Same `(kafka_topic, kafka_partition, kafka_offset)` |
| Business deduplication | Readers use `event_id`; coordinates for physical-row audit |
| Replay start policy | `require_committed` default; `data_gap` on retention loss |
| v1 vs v2 datasets | Separate prefixes; no implicit merge |

## 8. Release gate checklist

- [ ] Dual-version readers deployed and qualified (historian, GraphQL)
- [ ] v2 writer enabled only after reader compatibility
- [ ] Four-domain acceptance executed or blocked with reason
- [ ] Fault matrix live rows executed or blocked with reason
- [ ] MinIO/S3 backend qualified with executed test IDs
- [ ] ADLS qualified or explicitly blocked
- [ ] Capacity evidence recorded with hardware notes
- [ ] `docker compose config --quiet` passes
- [ ] Operations runbook sections complete

This closes **multi-system UNS-to-lake** development qualification, not production
HA sign-off.
