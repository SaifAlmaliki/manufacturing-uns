# Historian-first telemetry and data lake

Date: 2026-09-09

Status: Proposed implementation specification; requested for later implementation.

Plan: [Historian-first implementation plan](../plans/2026-09-09-historian-first.md)

## 1. Decision

Use **MQTT -> batched historian ingestion -> TimescaleDB -> asynchronous Parquet
archive**. Timescale is the durable acceptance boundary for operational telemetry.
Operational and condition-monitoring dashboards read committed historian data.
MinIO stores the long-term raw archive for subsequent data engineering and analytics.

Remove Kafka from the default telemetry architecture after a coordinated cutover.
Do not buy HiveMQ Enterprise solely for this change. Keep the existing MQTT broker;
qualify its persistent-session and disk-persistence behavior before relying on it
for database-outage buffering.

This decision optimizes the number of independently operated systems. It does not
claim that a database worklist has Kafka's throughput, independent consumer replay,
or isolation from historian outages. If those become requirements, revisit the
decision using measured backlog, query latency, and recovery throughput.

### Requirements

1. Persist original Historic Events and their scalar Metrics atomically.
2. Serve live operational dashboards and condition monitoring from Timescale.
3. Eventually archive every accepted event in Parquet, including late events.
4. Survive process restarts and temporary MinIO outages without skipping data.
5. Make delivery limits, duplicate semantics, and archive completeness explicit.
6. Preserve existing development data unless an operator explicitly chooses otherwise.
7. Use existing modules, database access, MQTT delivery controls, and store adapters.

### Alternatives considered

| Approach | Assessment |
| --- | --- |
| Existing MQTT -> Kafka -> separate historian/lake consumers | Appropriate when independent log replay and ingestion isolation justify the operational cost. More infrastructure than the stated requirements need. |
| Enterprise broker -> historian and direct lake extension | Reduces custom archive code but adds licensing and independent persistence paths; MinIO and envelope compatibility need qualification. |
| Historian first, transactional archive worklist | Selected. One durable acceptance point; SQL supports operations and asynchronous archive recovery. |

## 2. Scope and precedence

This document proposes replacing the Kafka-centric Phase 1 of
[UNS scalability foundation](2026-09-09-uns-scalability-foundation-design.md)
and the Kafka source in the
[earlier lake design](2026-09-08-uns-datalake-mapper-design.md).
Those documents remain historical context until this proposal is implemented.
Retain their canonical identity, bounded batching, read-time enrichment, late
aggregate refresh, and deployment-data preservation principles.

The current Kafka decision is accepted in
[ADR-0011](../../adr/0011-canonical-historic-event-pipeline.md). This proposal does
not silently change that ADR's status. During implementation acceptance, add a
successor ADR explicitly superseding its transport/storage decisions while keeping
the canonical envelope contract.

Included: durable MQTT ingestion, complete raw envelopes, transactional archive
tracking, Parquet publication, dashboard transport migration, guarded retention,
configuration, observability, deployment cutover, and failure tests.

Excluded: a new analytics engine or BI dashboard, Iceberg/Delta, general CDC,
cross-region HA, new edge buffering products, arbitrary stream replay APIs,
Sparkplug protocol redesign, and automatic Parquet compaction. Existing graph and
Sparkplug mappers remain MQTT consumers; the telemetry path is not the entire UNS.

The prior design states that this is a development deployment. Revalidate that
assumption before execution. If production consumers now exist, stop at the
cutover planning gate and write an explicit compatibility migration.

## 3. Repository baseline

Source inspection on 2026-09-09 found:

- `04_uns_historian/pyproject.toml` runs `uns_historian.kafka_consumer:main`.
- `04_uns_historian/src/uns_historian/batch.py` and `historian_handler.py` provide
  canonical raw/Metric batches but couple their input/result to Kafka offsets.
- `04_uns_historian/src/uns_historian/uns_mqtt_historian.py` is an older direct-MQTT
  path with random client identity and per-message scheduled coroutines. Switching
  the entry point to it without redesign would regress the durability contract.
- `02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py` already provides opt-in MQTT 5
  stable sessions, manual acknowledgments, and retained-bootstrap suppression.
- `06_uns_kafka/src/uns_kafka/ingest.py` contains useful envelope construction,
  ownership mapping, bounded admission, and connection-generation concepts.
- `09_uns_model/migrations/versions/0009_historian_event_pipeline.py` adds event
  identity, Kafka checkpoints, and late-refresh tracking. Raw uniqueness is
  `(time, event_id)`; not every field of the canonical envelope is stored.
- `14_uns_datalake` implements Kafka batching, Parquet encoding, and S3/ADLS stores.
  Its current `ObjectStore.put` alone does not define recoverable publication.
- `07_uns_graphql/src/uns_graphql/backend/event_stream.py` uses Kafka; historian
  queries and condition-monitoring reads can continue using Timescale.
- `07_uns_graphql/src/uns_graphql/backend/historian.py` can rewrite stored topic
  prefixes. Archive content must not depend on these mutable query columns.

There were existing uncommitted runtime changes during drafting. The implementation
must inspect the then-current worktree and not overwrite unrelated work.

## 4. Architecture and ownership

```text
Devices / simulator / normalized Sparkplug publications
                         |
                         v
                    MQTT broker
                         |
            persistent subscriber session
                         |
                         v
              historian ingestion process
             validate -> bounded batching
                         |
                 one SQL transaction
                         |
          +--------------+-------------------+
          | Timescale/PostgreSQL             |
          | raw rows + immutable envelope    |
          | scalar Metrics                   |
          | archive worklist + late refresh  |
          +--------------+-------------------+
                         |
           +-------------+-----------------+
           |                               |
           v                               v
    GraphQL queries                  archive worker
    operational dashboards       claim -> encode -> upload
    condition monitoring                 |
                                         v
                                   MinIO / Parquet
                                   commit manifests
                                         |
                                downstream engineering
```

Reuse `04_uns_historian` for ingestion and `14_uns_datalake` for the archive worker.
The worker is a separate process so cloud latency cannot stall the MQTT network
loop or consume historian ingestion threads. It shares the existing database,
not an additional queue service. Start with one archive worker per Instance.

Timescale is the authority for accepted, not-yet-archived events. Successfully
published immutable lake objects become the long-term archive. Metrics, aggregate
tables, and dashboard state are derived data. MQTT remains the Unified Namespace,
not a historical event log.

## 5. Event fidelity and identity

Keep `00_uns_config/src/uns_config/events.py` as the canonical pure contract.
Preserve all its fields: schema version, event identity/quality, source and site,
boot/sequence, event/receive time and quality, original topic, event kind,
historical flag, payload, and nullable raw binary payload.

Add `archive_envelope JSONB` and `archive_provenance TEXT` to the raw hypertable.
For new events, write the complete canonical envelope and provenance `captured` in
the same transaction as the raw columns. JSONB preserves semantic JSON content,
not original JSON whitespace/order. Preserve original binary transport payloads
in the existing base64 field; do not infer binary bytes from a decoded object.

Limit snapshot/rejection access to the existing authorized service/admin paths;
do not expose raw payloads through health endpoints, logs, or unrestricted archive
status APIs. Existing per-topic authorization continues to apply to dashboard reads.

`archive_envelope` is immutable after initial migration backfill. Export and
duplicate-content comparison use this snapshot, never a later topic rewrite or
Asset enrichment. Existing topic remapping may continue to update query-facing
raw/Metric topic columns; it must not modify the snapshot, event identity, time,
or its immutable-content hash. Consequently archived topics are original topics;
query-facing remapped topics may differ intentionally.

Source-identified receipts deduplicate on the existing `(time, event_id)` contract
while those rows are retained. The source contract requires an immutable timestamp.
Conflicting content under that identity is durably quarantined, not overwritten.
Do not claim global event-ID uniqueness across different timestamps.

Legacy publishers remain `identity_quality=ingress`. Freeze generated identity
and receive time for all retries of one admitted receipt. MQTT redelivery after
a process crash can create a new receipt identity. Equal sensor values are not a
deduplication key. Replay after raw retention can also produce additional archive
rows; downstream consumers must understand these identity limits.

## 6. MQTT acceptance and bounded ingestion

### Admission

- One stable client ID per configured, non-overlapping topic/site shard.
- MQTT 5 persistent session; initial session expiry seven days, subject to broker
  storage capacity and supported outage qualification, not a seven-day lossless promise.
- Subscribe at QoS 1 for this ingestion path. Publisher QoS 0 remains best effort;
  requesting QoS 1 does not upgrade it. Do not change Sparkplug's native QoS globally.
- Use manual ACK for delivered QoS 1 and suppress retained subscription bootstrap.
- Never run the legacy MQTT writer and new writer against the same shard.
- Exclude `uns/platform/` and honor event-kind rules. Excluded deliveries must be
  acknowledged/released intentionally so a broad subscription does not deadlock.
- Payload/envelope size limit: 1 MiB canonical serialized bytes. Configure and test
  MQTT packet overhead separately; broker rejection precedes application quarantine.

### Commit and acknowledgment

For each bounded batch, in a single SQL transaction:

1. Acquire the shared retention coordination lock.
2. Insert new raw rows and immutable envelopes; verify duplicate content.
3. Insert Metrics only for newly inserted telemetry events.
4. Insert archive work rows only for newly inserted raw rows.
5. Update the existing late-refresh worklist for applicable new events.
6. Persist rejection outcomes for malformed/conflicting receipts.
7. Commit, then acknowledge only current-generation QoS 1 receipt tokens.

A DB rollback or uncertain commit result never authorizes an ACK. Retry the frozen
receipt; durable deduplication makes an uncertain successful commit safe for the
same receipt identity. ACK tokens include connection generation, packet ID, and
QoS. Invalidate them immediately on disconnect so an old completion cannot ACK a
reused packet ID on the new connection.

Rejected events live in `historian.ingest_rejection` with receipt UUID, reason,
topic, receive time, original bounded payload, payload hash/length, and truncation
flag if the rejection record limit is exceeded. A rejection is a durable outcome,
not a Historic Event or silent skip. ACK it only after commit. Validation errors
must not poison unrelated valid events in the batch. DB/programming errors roll
back and retry; do not misclassify infrastructure errors as bad telemetry.

### Bounds and lifecycle

Initial values: 1,000 pending receipts, 16 MiB pending serialized bytes, MQTT
Receive Maximum 20 (existing wrapper default), SQL batch 500 events / 4 MiB /
100 ms / 20,000 total Metric rows. Flush on time even if fewer than 20 events arrive;
waiting for a 500-event batch with 20 unacknowledged deliveries would deadlock.

Use one lifecycle owner and bounded thread-to-async handoff. No unbounded task per
message. Count pending memory until terminal completion. When full or DB unavailable,
mark unready and perform an actual controlled disconnect, with bounded exponential
backoff and jitter. Continue servicing timers/completions without blocking MQTT's
network thread. QoS 0 drops under overload are counted explicitly. Shutdown stops
admission, drains for up to ten seconds, and leaves unresolved QoS 1 unacknowledged.

Broker disk/session recovery is a prerequisite for the outage claim. Publisher
PUBACK acknowledges the publisher-to-broker hop, not historian commit. Database
and broker backups/replication determine disaster recovery; this design adds no HA.

## 7. Transactional archive worklist

Use ordinary PostgreSQL metadata tables in schema `historian`, via the existing
SQLAlchemy Core engine. Do not use event-time or sequence high-watermarks.

### Tables

| Table | Fields and constraints |
| --- | --- |
| `archive_work` | `event_time timestamptz`, `event_id text`, `enqueued_at timestamptz`, `envelope_bytes integer`, nullable `batch_id uuid`; primary key `(event_time,event_id)`; nonnegative byte bound; index on unassigned work and on batch ID. |
| `archive_batch` | UUID PK; state `claimed`, `staged`, or `complete`; archive date; format version; creation/completion times; row count; content hash; exact data/manifest keys; nullable staged Parquet bytes; exact manifest bytes; error/attempt metadata. Unique object keys. |
| `archive_control` | Singleton migration/backfill completion flag and format generation. Retention requires completion. |
| `ingest_rejection` | Durable receipt outcome described in section 6, indexed by receive time. |

`archive_work` is a reference, not another copy of the payload. Assigned membership
is immutable. Keep completed work references while corresponding raw events exist;
they are evidence for retention. A duplicate receipt must not requeue an already
completed row. Batch receipts/manifests remain after raw retirement for audit.

### Claiming

One worker holds a dedicated PostgreSQL session advisory lock for the Instance's
archive job. A second worker stays unready. Loss of that connection stops its
loop; short SQL state transitions must verify ownership. Retried in-flight object
writes are harmless because staged keys and bytes are immutable.

Resume an incomplete batch before claiming new work. In a short transaction select
unassigned `archive_work` rows ordered by `(enqueued_at,event_time,event_id)` with
`FOR UPDATE SKIP LOCKED`; stop at 10,000 rows or 16 MiB estimated envelope bytes.
Create the batch and assign selected rows atomically. Do not hold a SQL transaction
open during encoding or network upload. Claim full batches as soon as available;
flush partial work when the oldest pending work reaches 60 seconds. Poll every second.

Rows that commit later remain unassigned and are found by a subsequent selection,
even if their event time or a sequence allocation precedes already exported rows.
Missing raw references are an integrity error: halt archive readiness, preserve
work, and block retention rather than silently completing the batch.

## 8. Parquet publication and restart recovery

### Content and layout

Read only frozen envelopes of the claimed membership, sorted by `(time,event_id)`.
Retain existing Parquet columns and add source boot/sequence, timestamp quality,
immutable content hash, and archive provenance. Increment the archive format version
to 2 and use a distinct prefix; do not silently mix schemas with existing objects.

```text
historian-v2/data/archive_date=YYYY-MM-DD/<batch_uuid>.parquet
historian-v2/commits/<batch_uuid>.json
```

`archive_date` is the batch creation UTC date, not event date. This deliberately
allows late events and many topics in the same bounded file. The manifest records
minimum/maximum event time for pruning; payload columns retain site and topic.
Avoid per-topic/per-device file partitions. Start with bounded small batches for
predictable memory; tune larger files after measuring backlog and downstream scans.

### Publication protocol

1. Encode the claimed rows with the versioned Arrow schema and Snappy.
2. Persist the **exact Parquet bytes**, SHA-256, length, row count, data key and
   canonical manifest bytes in `archive_batch`; set state `staged` and commit.
   Limit staged data to 64 MiB. If exceeded, split membership into smaller claimed
   batches transactionally before staging; never upload unrecorded bytes.
3. Upload the data object at its frozen key. If already present, verify full content
   SHA-256/length or trusted equivalent; do not assume a multipart ETag is SHA-256.
   A mismatch is an integrity error, never an overwrite of different content.
4. Upload the manifest **last**, idempotently. It contains format version, batch ID,
   data key, byte checksum/length, row count, and min/max event time.
5. After confirmed manifest publication, mark the batch complete in SQL and clear
   staged data bytes. Keep the manifest and membership evidence.

Keeping one bounded staged artifact in SQL avoids a second durable filesystem and
ensures retries remain byte-identical across encoder upgrades. This is transient
write amplification, not an unbounded blob queue: finish staged work before encoding
another batch. Cap encoded buffers and measure process RSS, not just serialized bytes.

The object-store port must support idempotent publication and verification, not
only blind `put`. Use bounded timeouts and capped backoff; after a failed attempt
leave staged state retryable. ADLS needs complete-file publication (staging/rename
or equivalent verified finalize) before a manifest becomes visible. The MinIO path
is the required end-to-end acceptance target; retained ADLS support must pass its
adapter contract and remain explicitly unqualified until tested against Azure.

**Reader contract:** enumerate committed manifests and read only their referenced
data files. Do not glob every object under `data/`. This prevents partially
published/orphaned data from entering datasets. A manifest may be visible before
SQL records completion; this is safe and must not cause a second batch.

Existing Kafka-written objects are a separate legacy dataset. Do not append them
blindly to the new dataset; overlap needs explicit event-identity reconciliation.

### Failure behavior

| Failure | Required outcome |
| --- | --- |
| Crash before SQL event commit | No accepted raw/Metric/work rows; QoS 1 redelivers within session limits. |
| Crash after event commit, before ACK | Same source identity deduplicates; ingress identity limitations remain explicit. |
| Crash after claim, before staging | Resume fixed membership and encode; no uploaded object exists yet. |
| Crash after staging, before upload | Reuse stored bytes and keys. |
| Upload timeout with unknown outcome | Verify the same key and retry identical content. |
| Data upload succeeds, manifest fails | Readers ignore data until the same manifest succeeds. |
| Manifest succeeds, SQL completion fails | Retry/verify same manifest and finalize the same batch. |
| MinIO offline | Historian continues until database capacity; worklist grows; archive alerts fire. |
| Timescale offline | Dashboards report stale/unavailable; ingestion backpressures; MQTT queues within limits. |
| Disk capacity exhausted | Fail readiness, preserve unresolved work, and alert; never delete pending data to appear healthy. |

This is at-least-once delivery with idempotent archive publication, not a blanket
end-to-end exactly-once claim.

## 9. Operational dashboard and condition-monitoring delivery

Use existing authorized historian/Metric query surfaces. Default UI refresh is
two seconds for visible operational panels and five seconds for condition-monitoring
windows. Make intervals configurable, cancel stale requests on filter changes,
avoid overlapping polls, and pause polling while a page is hidden.

Refetch the selected time window rather than appending solely by event timestamp.
This incorporates late events and refreshed aggregates. Show last successful fetch
and actual data freshness separately; a successful query with old data is not live.
Keep OEE and late aggregate refresh on their existing historian interfaces.

Remove the Kafka consumer lifecycle and Kafka-backed GraphQL subscription from
the coordinated development API. Do not silently rename it while changing stream
semantics to snapshots. Update callers/schema tests and return an explicit schema
breaking change to any unrecognized external client. Existing MQTT-specific
inspection tools may remain, clearly separate from committed telemetry dashboards.

No PostgreSQL LISTEN/NOTIFY dependency is needed in the first release. A later
post-commit notification can invalidate query caches, but must remain an optional
hint; polling/resync remains the source of completeness.

## 10. Retention, immutability, and backfill

Disable unconditional raw/Metric retention policies during cutover. Default new
retention setting is **disabled** until archive reconciliation passes. Provide a
guarded dry-run maintenance command before allowing deletion.

All raw insert/backfill and archive membership transactions take the same shared
transaction-level advisory lock. A retention transaction takes its exclusive form,
selects exact fully expired Timescale chunks, and verifies every raw row has a work
reference whose batch is complete. Missing work, noncomplete batches, or incomplete
backfill blocks that chunk. Drop only the verified chunk(s), then prune their work
references in the same transaction. Never use a broad time cutoff that can also
drop unverified chunks. Metric retention must not remove rows for pending raw events;
verify the corresponding raw coverage or restrict it to the verified retired range.

Acquire the lock before reads/writes in a consistent order. The lock serializes
the retention check/drop with late inserts; a late event arriving afterward creates
new raw/work rows and must be archived before any later cleanup. Do not rely on a
foreign key cascade to establish archive completeness. Prove behavior with the
deployed Timescale version and compressed chunks before enabling retention.

### Existing rows

With old ingestion paused and Kafka drained as described below, backfill every
retained raw row into the worklist in bounded idempotent batches. Reconstruct a
canonical envelope from known columns, preserving event IDs and timestamps. Use
provenance `reconstructed`; mark absent legacy source/site metadata with explicit
legacy values and nullable optional fields. Never claim to recover raw binary bytes
or pre-remap topics that were not stored. Report those counts in the cutover report.

Set `archive_control.backfill_complete` only after an anti-join proves every raw
row has a snapshot and a work reference. Do not use the existing lake as evidence
that a raw row is archived unless its identity/content is actually reconciled.

## 11. Configuration and observability

Reuse shared settings/secrets and `Database.shared`; no embedded credentials or
second ingestion pool. Add typed settings for historian shard/client identity,
admission/batch limits, and datalake database source, batch limits, polling, prefix,
timeouts, and disabled-by-default guarded retention. Remove Kafka settings from
the active historian, lake, and GraphQL dependency paths.

Expose:

- MQTT admitted/committed/rejected/duplicate/QoS 0 dropped counts, pending bytes,
  disconnects, reconnects, session continuity, and commit latency.
- Archive unassigned/assigned rows and bytes, oldest pending age, batch attempts,
  last completed time, published bytes/rows, integrity failures, and worker ownership.
- Database storage pressure, query latency, late-refresh age, and retention blockers.

Liveness means the process loop is progressing. Readiness means its dependencies
and ownership allow useful work. An idle, connected worker with no data is healthy.
MinIO failure makes archive readiness false, not historian readiness false.
Distinguish "last success" from "no work to do" in dashboards and alerts.

Initial development objectives (to be measured, not advertised as capacity):
SQL commit p95 <= 500 ms at the test load; operational panel freshness <= 3 seconds;
partial archive batches published within 90 seconds while dependencies are healthy.
Record peak events/s, payload distribution, Metric fanout, RSS, WAL/storage growth,
and query latency before/after export. Required outage storage is measured bytes/s
times outage duration plus headroom; recovery throughput must exceed live arrival rate.

## 12. Cutover and rollback

1. Record versions, current worktree changes, dependency clients, and raw counts;
   take a tested database backup and preserve Kafka/MinIO volumes.
2. Quiesce producers/bridges, let the old MQTT-to-Kafka mapper finish accepted
   deliveries, and drain historian and old lake consumer groups to recorded end
   offsets. Resolve/reconcile old rejection records. Keep the old session/volumes.
3. Stop old writers and Kafka-backed live dispatch. Apply additive migrations and
   backfill existing raw rows while all writers remain stopped. Reconcile row
   counts, snapshot/work coverage, and legacy provenance.
4. Start the new persistent historian subscription and confirm SUBACK/readiness
   before resuming producers. Start archive worker and new dashboard clients.
5. Publish known IDs, reconcile SQL -> manifests -> Parquet, then run fault tests.
6. Remove Kafka services from default Compose only after acceptance. Preserve old
   code/data for explicit rollback until the new path has passed the agreed trial.
   Mark earlier docs superseded during implementation; create a new ADR then.

If producers cannot be quiesced, this cutover is not sufficient: design a bridge
or overlap reconciliation procedure before proceeding. MQTT does not provide
arbitrary pre-subscription event history.

Rollback before new writes: restore old entry points/deployment against preserved
Kafka checkpoints and volumes. After new writes: pause producers, stop new writers,
retain additive schema/worklist and all SQL data, then resume old ingestion from its
recorded boundary. Events accepted only by the new path do not magically exist in
Kafka; keep their SQL archive worker draining, or explicitly reconcile/replay them
before returning archive authority to Kafka. No destructive downgrade, volume reset,
or simultaneous overlapping writers is an automatic rollback step.

## 13. Acceptance criteria

1. Default stack starts and both dashboards operate with Kafka stopped.
2. New raw/Metric/work records commit atomically; ACK occurs afterward.
3. Rejected/excluded messages cannot block all valid ingestion indefinitely.
4. The same source event creates one raw row, Metric set, and archive membership
   within the documented identity/retention scope.
5. Two concurrent SQL transactions that commit in reverse start order both archive.
6. Late, duplicate, binary, and historical events retain the defined envelope fields.
7. Process kills at every publication boundary recover to the same object keys/bytes.
8. A MinIO outage leaves dashboards usable; restoration drains backlog without gaps.
9. A DB/broker outage test proves the supported persistent-session recovery window;
   QoS 0 behavior and expired/full-session behavior are reported separately.
10. Dashboard authorization remains scoped and refresh includes late arrivals.
11. Retention cannot remove pending/missing-work rows, including a concurrent late insert.
12. Existing development data and old object prefixes remain intact through cutover.
13. A fresh database and an upgraded database both pass migrations and backfill.

## 14. Implementation references

Local contract references: `CONTEXT.md`, ADR-0002/0004, canonical event helpers,
current MQTT delivery wrapper, and the linked implementation plan. Recheck these
against the worktree when implementation starts; older design status text is not
evidence of which code has since shipped.

Primary references for the implementer:

- [PostgreSQL SELECT / locking clauses](https://www.postgresql.org/docs/current/sql-select.html):
  queue-style `FOR UPDATE SKIP LOCKED`, not a historical completeness cursor.
- [PostgreSQL explicit/advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html).
- [Paho Python client](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html):
  validate manual acknowledgment and session options against the installed version.
- [Timescale drop_chunks](https://docs.tigerdata.com/api/latest/hypertable/drop_chunks/):
  validate exact chunk-selection and transactional behavior against the deployed version.

Context7 authentication was unavailable during drafting. PostgreSQL SELECT behavior
was checked directly against its official documentation; SDK-specific publication
and Timescale retention operations still require version-pinned verification in
the implementation tasks, rather than assumed API syntax.
