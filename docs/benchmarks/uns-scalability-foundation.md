# UNS Scalability Foundation — Qualification Report

> **Status:** Template for Milestone D evidence. A report produced by this template
> documents measured behaviour; it does not claim production HA qualification.

Design reference: [UNS scalability foundation](../superpowers/specs/2026-09-09-uns-scalability-foundation-design.md).

Implementation plan: [Phase 1 plan](../superpowers/plans/2026-09-09-uns-scalability-foundation.md).

## 1. Run metadata

| Field | Value |
| --- | --- |
| Date (UTC) | _fill on run_ |
| Operator | _fill on run_ |
| Git commit | _fill on run_ |
| Host CPU / RAM | _fill on run_ |
| OS / kernel | _fill on run_ |
| Docker / Compose version | _fill on run_ |

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
Parquet -> MinIO bucket uns-historic-events
SQL -> TimescaleDB (uns_historian)
```

Configured limits (from `conf/settings.yaml`):

| Component | Limit |
| --- | --- |
| Ingestion pending records | 1,000 |
| Ingestion pending bytes | 16 MiB |
| Historian batch events | 500 |
| Historian batch bytes | 4 MiB |
| Historian batch age | 100 ms |
| Datalake flush records | 10,000 |
| Datalake flush bytes | 8 MiB |
| GraphQL live clients | 200 |
| Canonical topic partitions | 12 |
| Historic retention | 7 days |
| DLQ retention | 30 days |

## 3. Deterministic load fixture

Generate MQTT load with source boot/sequence IDs and a manifest digest:

```powershell
uv run python 06_uns_kafka/test/pipeline_load.py `
  --sites 2 `
  --topics 5000 `
  --rate 10000 `
  --seconds 3600 `
  --burst-rate 20000 `
  --burst-seconds 60 `
  --report docs/benchmarks/runs/2026-09-09-load.json
```

Credentials come from mounted `conf/.secrets.yaml` only. The report parent directory
must exist before writing.

The load tool counts **source receipts** separately from downstream stages. After the
run, reconcile:

| Stage | Counter | How to measure |
| --- | --- | --- |
| Source | `source_receipts` | load report |
| Kafka accepted | `kafka_accepted` | consumer lag cleared + historic topic offsets |
| DLQ | `dlq_records` | `uns.historic-events.dlq` message count |
| SQL event IDs | `sql_event_ids` | `unifiednamespace.event_id` for manifest IDs |
| Archived IDs | `archived_ids` | Parquet `event_id` values in lake objects |

Use `uns_kafka.pipeline_fixture.reconcile_manifest()` or the acceptance tests as the
reference reconciliation contract.

## 4. Target workload (development gate)

This is the **initial qualification fixture**, not evidence that production already
supports the rate:

| Parameter | Target |
| --- | --- |
| Simulated sites | 2 |
| Active topics | 10,000 total |
| Sustained rate | 10,000 events/s |
| Burst | 20,000 events/s for 60 s |
| Soak | 3,600 s for development gate |
| Healthy p99 source-to-SQL | 1 s |

If hardware cannot meet the target, record measured saturation and the limiting
component. Do not relabel a failed target as a passing run.

## 5. Measured results

| Metric | Target | Observed | Pass? |
| --- | --- | --- | --- |
| Sustained ingest rate | 10,000/s | _fill_ | _fill_ |
| Burst ingest rate | 20,000/s | _fill_ | _fill_ |
| p99 source-to-SQL latency | ≤ 1 s | _fill_ | _fill_ |
| Mapper CPU / RSS peak | _note bottleneck_ | _fill_ | _fill_ |
| Historian CPU / RSS peak | _note bottleneck_ | _fill_ | _fill_ |
| Kafka consumer lag (p99) | converges after burst | _fill_ | _fill_ |
| Pending ingestion bytes under sink outage | bounded | _fill_ | _fill_ |
| DLQ records (valid fixture) | 0 | _fill_ | _fill_ |
| Missing/extra event IDs | 0 | _fill_ | _fill_ |

## 6. Fault qualification

Automated unit and contract tests cover acknowledgment timing, bounded memory, and
authorization. Live fault injection requires orchestrated stack control.

Run offline contract suites:

```powershell
uv run pytest -n 0 -m "not integrationtest" 00_uns_config/test 02_mqtt-cluster/test 04_uns_historian/test 06_uns_kafka/test 07_uns_graphql/test 09_uns_model/test 14_uns_datalake/test
```

Run integration acceptance against a live stack:

```powershell
uv run pytest -n 0 -m integrationtest 06_uns_kafka/test/test_pipeline_acceptance.py 09_uns_model/test/test_historian_pipeline_migration.py 04_uns_historian/test/test_batch_persistence.py
```

Missing services must appear as **blocked** skips, not silent passes.

| Scenario | Expected invariant | Evidence |
| --- | --- | --- |
| Mapper crash before Kafka delivery | No MQTT ack | `06_uns_kafka/test/test_ingest.py` + manual kill |
| Mapper crash after Kafka delivery | MQTT ack only after Kafka success | `test_ingest.py` + manual kill |
| Historian crash after SQL commit | Offset not committed before SQL | `test_batch_persistence.py` |
| Kafka outage 60 s | Ingestion readiness false; no early ack | manual + Prometheus |
| Database outage 5 min | Historian readiness false; bounded pending | manual + Prometheus |
| Ownership / delivery failure | Shard not ready; no ack | `test_pipeline_acceptance.py` |
| Retention gap detection | Diagnostic failure, not silent skip | `test_bootstrap.py` |
| Legacy MQTT redelivery | Distinct ingress IDs | `test_pipeline_acceptance.py` integration |
| Slow GraphQL clients | Bounded fan-out disconnect | `07_uns_graphql/test/backend/test_event_stream.py` |
| Source-identified replay | One raw row / one metric set | `test_batch_persistence.py` integration |
| 7-day late aggregate refresh | Refresh worklist succeeds | `test_aggregate_refresh.py` |

## 7. Identity guarantees

| Guarantee | Scope |
| --- | --- |
| Source boot + sequence | Stable `event_id` across Kafka retries |
| Ingress UUID | Distinct ID per MQTT receipt without source identity |
| Legacy redelivery | Weaker: equal payloads produce distinct ingress IDs |
| Time-scoped SQL uniqueness | Does not detect source ID reuse at a new timestamp |

## 8. Release gate checklist

- [ ] One default pipeline through `uns.historic-events`
- [ ] No dotted-topic production path in default stack
- [ ] Historian consumes Kafka, not direct MQTT
- [ ] GraphQL live fan-out authorized on envelope topic
- [ ] Lake archives full envelopes with upload-before-commit
- [ ] Fault tests executed or explicitly blocked with reason
- [ ] Capacity report completed with digests and hardware notes

This closes **Phase 1** development qualification, not production HA sign-off.
