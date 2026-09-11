# UNS-to-lake delivery operations

Operational runbook for multi-system raw lake delivery from the canonical historic
event stream.

Qualification evidence template: [benchmark report](../benchmarks/uns-to-lake-delivery.md).

## Registration

Publication routes are declared in `conf/settings.yaml` under
`kafka_mapper.ingestion.publication_routes`. Each route binds one MQTT topic
filter to immutable delivery metadata:

- `topic_filter` — MQTT filter owned by broker ACLs for the publishing credential.
- `source_id` — stable ingress source identity (not a lake path segment).
- `source_application`, `site_id` — registered application and site scope.
- `wire_format` — `raw` or `uns-publication-v1`; selects the publisher wire
  contract explicitly. Business JSON that resembles the wrapper is still treated
  as raw bytes when the route says `raw`.
- `allowed_schema_pairs` — finite schema ID/version pairs permitted on the route.
- `default_schema_pair` — required for `raw` routes; supplies schema metadata.
- `content_type`, `event_kind`, `archive_eligible` — frozen envelope metadata.

`validate_routes()` runs at mapper startup before MQTT subscribe. Overlapping or
duplicate filters fail with `ambiguous_route`. Unknown topics are durable
rejections (`unknown_route`), never defaulted to `unknown` application/site.

Operational rules:

1. **Broker ACL ownership** — credentials may publish only to their route filters.
   The mapper verifies wrapper claims against registration; MQTT does not expose
   a trustworthy publisher application ID.
2. **One route per publication** — each accepted MQTT message resolves to exactly
   one registration. Cross-site fan-out requires separate publications.
3. **Configured enterprise/shared scope** — cross-site records use an explicitly
   registered shared `site_id` (for example `shared`); the mapper never invents
   a site.
4. **Payload schema ID vs validation** — `payload_schema_id` is a routing label
   for lake partitioning, not a schema-document validation engine. Document
   validation belongs outside this service.

Shipped `conf/settings.yaml` enables v2 publishing because dual-version readers are
deployed. Set `ingestion.v2_publications_enabled: false` only when rolling back or
when upgrading an existing deployment before its readers are v2-compatible. Routes
may be present while v2 writing remains disabled.

## Raw contract

### Envelope versions

| Version | Wire shape | Body authority | Lake routing metadata |
| --- | --- | --- | --- |
| v1 | Existing telemetry envelope | `payload` JSON (normalized timestamps) | Legacy route map revision |
| v2 | `schema_version: 2` plus `original_payload_base64` | `original_payload` bytes | Frozen envelope fields |

V2 requires `source_application`, `payload_schema_id`, `payload_schema_version`,
`content_type`, `original_payload`, and `archive_eligible`. Empty bytes (`b""`)
are valid and differ from absent (`None`).

### Parquet row fidelity

Every archived row under `raw/v2/` includes:

- Canonical identity: `event_id`, source boot/sequence, timestamps, topic.
- V2 metadata: application, site, schema ID/version, content type.
- `original_payload` binary when fidelity is `original`; NULL for legacy-normalized v1.
- `payload` JSON as a labeled compatibility representation only.
- `canonical_envelope` bytes for exact accepted-envelope auditing.
- Transport coordinates: `kafka_topic`, `kafka_partition`, `kafka_offset`.
- `payload_fidelity` (`original` or `legacy_normalized`) and `legacy_route_revision`.

Object path layout (frozen at receipt time):

```text
raw/v2/application=<app>/site=<site>/schema=<schema>/version=<ver>/ingestion_date=<UTC-date>/<object_id>.parquet
```

`ingestion_date` derives from `received_at` in UTC, not event time.

### Exclusions

`archive_eligible: false` records are resolved in the consumed-prefix ledger without
writing a lake object. They cannot advance past earlier unresolved work in the same
partition flush.

## Reader-first deployment

Deploy in this order. Do not enable v2 MQTT publishing until every canonical reader
is compatible.

```text
1. Inventory all canonical readers and record current consumer group positions.
2. Capture immutable legacy route map revision and v1 object-prefix baseline.
3. Deploy dual-version readers (historian, GraphQL) with v2 writer still disabled.
4. Verify v1 telemetry and existing queries still work.
5. Deploy versioned lake writer/configuration; preserve current group positions.
6. Enable registered v2 publishing only after every reader is compatible.
7. Publish four-domain qualification cases; reconcile routes/body bytes/coordinates.
```

Reader compatibility summary:

| Consumer | Group | v2 business events | v2 telemetry |
| --- | --- | --- | --- |
| Historian | `uns_historian` | Ignored (no Metric insert) | Persisted via compatibility copy |
| GraphQL live | ephemeral | Ignored (not broadcast) | Broadcast via compatibility copy |
| Datalake mapper | `uns_datalake` | Archived when `archive_eligible` | Archived |

The historian is not a lake dependency. Lake delivery proceeds when the historian
is stopped.

Configuration gates:

- `kafka_mapper.ingestion.v2_publications_enabled` — MQTT v2 ingest (default `false`).
- `datalake.legacy_route_map.revision` — frozen v1 routing revision with content digest.
- `datalake.kafka.initial_position` — default `require_committed`.

## Replay/duplicates

Delivery is **at-least-once**. Crash, rebalance, or replay may create duplicate
Parquet objects containing the same `event_id`.

### Deduplication keys

| Use case | Key |
| --- | --- |
| Business logic | `event_id` (source boot/sequence or ingress UUID) |
| Physical row audit | `(kafka_topic, kafka_partition, kafka_offset)` |
| Object identity | `object_key` plus content SHA-256 |

Identical Kafka coordinates in multiple rows indicate repeated delivery of the same
canonical record, not a new source event.

### Replay start policy

On partition assignment the lake mapper:

1. Reads committed offset and low/high watermarks.
2. Applies `choose_start(committed, low, high, initial_position)`.
3. Assigns explicit positions; does not silently auto-reset.

| Condition | Result |
| --- | --- |
| `committed` within `[low, high]` | Resume at `committed` |
| `committed < low` | `data_gap` error (even with `earliest`) |
| `committed > high` | `invalid_position` error |
| No commit + `require_committed` | `initial_position_required` error |
| No commit + `earliest` | Start at `low` |
| No commit + `latest` | Start at `high` |

Retention-gap recovery: stop the mapper, record the gap, reconcile with source
replay/export if available, and require an explicit operator decision before
starting a replacement consumer group. No automatic offset reset.

## Rollback

### Before v2 records exist in the log

1. Disable v2 publishing (`v2_publications_enabled: false`).
2. Roll back reader deployments if needed.
3. Revert lake mapper configuration if changed.
4. Preserve consumer positions and accepted data.

### After v2 records exist in the log

1. **Disable new v2 publishing first** — stop admitting business envelopes at MQTT.
2. Keep dual-version readers until retained log ranges no longer contain v2 records
   that require compatibility handling.
3. Do not revert to v1-only reader binaries while v2 envelopes remain in the
   retained topic range.
4. Preserve accepted v2 lake objects under `raw/v2/` and current consumer positions.
5. Replay can overlap `v1/` and `raw/v2/` prefixes; treat them as separate datasets.

Reverting v1-only binaries alone is not a safe rollback once v2 canonical bytes
are in Kafka.

## Backend qualification

Immutable publication contract:

```text
publish_exact(key, data, sha256) -> creates or verifies identical content
verify_exact(key, sha256, byte_length) -> streamed readback hash check
```

Mismatching content at an existing key raises `IntegrityError` and fails readiness.
Never overwrite with different bytes.

| Backend | Create semantics | Finalization | Qualification |
| --- | --- | --- | --- |
| MinIO / S3 | `If-None-Match: *` conditional put | Immediate complete object | Development default; contract tests in CI |
| AWS S3 | Supported conditional create | Immediate complete object | Requires live-bucket evidence |
| Azure ADLS | Staging key outside `raw/v2` | Atomic rename to final `.parquet` | Blocked when API cannot guarantee no-overwrite finalize |

Record executed test IDs, versions, duration, duplicates, rejections, and artifact
keys in the [benchmark report](../benchmarks/uns-to-lake-delivery.md). Unit-only
success is not durability qualification.

Staging cleanup for abandoned ADLS uploads is manual; do not delete final `raw/v2`
objects during cleanup.

## Legacy v1 dataset

Pre-v2 lake objects remain under the legacy prefix:

```text
v1/ingest_date=<date>/hour=<hour>/partition=<n>/<flush_id>.parquet
```

Characteristics:

- Rows use `payload_fidelity=legacy_normalized`; `original_payload` is NULL.
- Routing comes from the frozen `legacy_route_map` revision, not live registration.
- Digest mismatch on the legacy map is refused at startup (`legacy_map_digest_mismatch`).
- New exports use `raw/v2/` only; no automatic backfill from v1.

Replay and analytics may read both prefixes concurrently. Deduplicate on `event_id`
and document which dataset each query targets. Do not merge v1 and v2 rows
implicitly.
