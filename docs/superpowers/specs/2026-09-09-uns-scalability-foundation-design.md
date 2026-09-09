# UNS scalability foundation and multi-site evolution

Date: 2026-09-09
Status: Proposed technical design for review; development cutover selected by the user; implementation not started.

Implementation plan: [Phase 1 and delivery roadmap](../plans/2026-09-09-uns-scalability-foundation.md).

## 1. Decision and scope

Use a **coordinated development cutover**, not a compatibility migration. The
platform has no production deployment. Build and test dependent changes together,
then switch the development stack to the new pipeline. Do not add temporary
dual-write switches, dotted Kafka topic aliases, or a maintenance-window process.
Existing development data is not implicitly disposable: export it if required;
any volume deletion or Kafka offset reset remains an explicit operator action.

Approaches considered:

| Approach | Benefit | Cost | Decision |
| --- | --- | --- | --- |
| Incremental dual-write migration | Preserves production consumers | Two event paths, reconciliation, temporary configuration | Unnecessary without production |
| Coordinated development cutover | One canonical contract and fewer failure paths | Dependent services must pass integration together | Selected |
| Broker-only scaling | Small initial change | Leaves historian overload, replay gaps and topic explosion intact | Rejected |

Deliver three separately testable phases:

1. **Durable ingestion foundation:** canonical Kafka stream, bounded handoff,
   replayable batched historian, updated Kafka-facing GraphQL API, and compatible
   lake consumer. A single-instance Compose environment proves behavior, not HA.
2. **Edge and state resilience:** actual HiveMQ Edge buffering, Sparkplug recovery,
   replay-safe graph projection, and signal-specific RBE contracts.
3. **Multi-site production deployment:** regional HA, identity/ACL automation,
   site bridges, capacity/failover qualification, and operating procedures.

Phase 1 is the detailed implementation scope. Phase 2 and Phase 3 have deliverables
and entry/exit gates below; their deployment-specific implementation plans follow
the Phase 1 measurements. No global throughput capacity is claimed by this design.

## 2. Repository evidence and existing decisions

- `docker-compose.yml` starts one HiveMQ Edge, one Kafka broker and one TimescaleDB.
  It explicitly declares itself unsuitable for production. Broker documentation
  also contains an older EMQX deployment path; this is not proof of a running cluster.
- `06_uns_kafka/src/uns_kafka/kafka_handler.py` derives one Kafka topic per MQTT
  topic and currently produces without an explicit record key.
- `04_uns_historian/src/uns_historian/uns_mqtt_historian.py` schedules one coroutine
  per MQTT event, with an ephemeral subscriber identity.
- `04_uns_historian/src/uns_historian/historian_handler.py` writes one raw event
  plus scalar Metrics in one transaction. Preserve their atomicity.
- The raw unique key includes subscriber identity and JSONB. It is not a stable
  identity for a source event across process restarts or worker changes.
- `07_uns_graphql/src/uns_graphql/subscriptions/kafka.py` reads client-supplied
  Kafka topics, rewinds to the beginning on assignment, and authorizes the Kafka
  topic string. Shared infrastructure topic names cannot represent asset scope.
- `05_sparkplugb/src/uns_spb_mapper/spb2unspublisher.py` holds aliases in memory.
  Arbitrary message-level distribution across mapper replicas is unsafe.
- The existing lake spec proposes `uns.historic-events` but retains dotted topics,
  a three-column envelope and topic-per-file grouping. Those choices are revised here.
- SQLAlchemy Core for ingestion and atomic raw/Metric writes remain consistent
  with ADR-0004 and ADR-0002. Use Alembic for changes; do not invent another DB pool.
- Asset enrichment remains read-time. Do not copy mutable asset descriptions into
  every event. Namespace paths remain meaningful and ISA-95-inspired.

The lake directory currently contains cached Python artifacts but no source files
returned by the source inspection. Treat the lake implementation as planned work,
not as an existing completed service.

### Design precedence

For this enhancement, this proposal replaces the earlier lake spec/plan choices
about dotted-topic retention, envelope identity, poison-event skipping and
topic-per-object grouping. The S3/ADLS adapter boundary and one selected backend
remain useful. The older documents are historical context, not an independently
executable plan once this proposal is accepted. Add an accepted ADR during
implementation approval rather than modifying existing ADRs retroactively.

## 3. Architecture and ownership

```text
Phase 1
  HiveMQ Edge / MQTT
       | ordinary namespace events + Sparkplug transport messages
       v
  kafka_mapper: validate -> bounded pending delivery -> Kafka confirmation -> MQTT ack
       |
       +--> uns.historic-events   (one canonical stream per regional deployment)
       |       +--> uns_historian consumer group -> raw + Metrics transaction
       |       +--> uns_datalake consumer group  -> immutable Parquet
       |       +--> GraphQL process-local live dispatcher -> scoped clients
       +--> uns.historic-events.dlq  (durably recorded rejected events)

  Existing Sparkplug mapper and graph mapper remain direct MQTT consumers in Phase 1.
  GraphQL's ordinary MQTT live view also remains available.

Target after Phase 2/3
  autonomous site collection + disk buffering + local MQTT
       -> selective bridge -> regional MQTT cluster -> durable Kafka handoff
       -> history / state / lake projections and enterprise integrations
```

Kafka is the replay authority for accepted events within its retention period.
Timescale raw rows are the operational Historic Event archive; Metrics and graph
state are projections. Object storage is the long-term archive once its write
completeness has been verified. MQTT remains the operational Unified Namespace,
not a historical replay store.

Phase 1 does not route control commands through the historian. Classify command
and lifecycle traffic explicitly. Archive them for audit when selected, but do
not flatten them into process Metrics. Continue excluding `uns/platform/` from
Historic Events using the existing ingestion policy.

## 4. Canonical event contract

Keep the literal Kafka topic **`uns.historic-events`**. Schema version is a field,
not a topic per device. Region isolation comes from separate deployments. Add a
small fixed set of data-class streams only when measurements justify independent
retention or traffic isolation.

Example source-identified event (illustrative identifiers):

```json
{
  "schema_version": 1,
  "event_id": "plant-a/gateway-01/boot-17/42",
  "identity_quality": "source",
  "source_id": "plant-a/gateway-01",
  "source_boot_id": "boot-17",
  "source_sequence": 42,
  "site_id": "plant-a",
  "time": "2026-09-09T10:00:00.000000Z",
  "received_at": "2026-09-09T10:00:00.010000Z",
  "timestamp_quality": "source",
  "topic": "Enterprise/PlantA/Area/Line/Device/Temperature",
  "event_kind": "telemetry",
  "is_historical": false,
  "payload": {"value": 21.4, "timestamp": 1788948000000},
  "raw_payload_base64": null
}
```

- Shared pure contract code lives in `00_uns_config/src/uns_config/events.py`.
  No Kafka, MQTT, cloud SDK or database dependency in that module.
- Required fields: schema version, event ID, identity quality, source ID, site ID,
  `time`, `received_at`, timestamp quality, original MQTT topic, event kind,
  historical flag, payload, and nullable raw payload. Boot/sequence are nullable
  only for ingress-generated identities.
- Identity encodes a validated tuple without delimiter collisions; the readable
  example is not permission to concatenate arbitrary strings. Use canonical JSON
  tuple serialization and SHA-256, prefixed by identity quality, in the implementation.
- `identity_quality=source` requires stable boot/sequence and a valid immutable
  source timestamp. Validate the identity metadata through configured trusted
  publisher/bridge mappings. Ordinary MQTT subscriptions do not expose publisher
  client identity; never call the subscriber's client ID the publisher ID.
- Publishers lacking the identity contract remain accepted with
  `identity_quality=ingress`, a generated UUID, and a configured origin source ID.
  Freeze that ID and timestamp across Kafka producer retries for that receipt.
  A new MQTT delivery after a crash may get a new ID: semantic source deduplication
  is not promised for this class. Do not hash equal values to remove repeated samples.
- Prefer an explicit timestamp unit in the publisher contract. Legacy numeric
  values with absolute value below `1e11` are seconds, otherwise milliseconds.
  Reject boolean/nonfinite/out-of-range timestamps as source timestamps. For
  legacy receipts use the frozen receive time and mark `timestamp_quality=ingress`.
  A malformed Kafka envelope is quarantined, never silently retimed.
- `event_kind` is `telemetry`, `sparkplug_raw`, `lifecycle`, or `command`.
  Preserve existing Sparkplug transport messages as `sparkplug_raw` with original
  bytes in `raw_payload_base64` and decoded payload where available. Archive raw
  transport without flattening its protocol fields into process Metrics.
- Normalized Sparkplug telemetry is a distinct derived event on its actual UNS
  topic. Phase 1 keeps the current mapper; Phase 2 adds deterministic derived IDs
  and parent event references. Do not claim Phase 1 solves Sparkplug source identity.
- Keys: canonical JSON `[site_id, "mqtt", original_topic]` for normal events;
  `[site_id, "sparkplug", group_id, edge_node_id]` for Sparkplug transport, including
  all its Device messages. Host STATE uses a distinct host-scoped key.
  Asset renames do not retroactively change recorded keys.
- Preserve top-level event time for raw storage. Scalar leaf projection follows
  existing semantics in Phase 1. Nested per-Metric historical sample expansion is
  Phase 2 work, not an implicit guarantee of this envelope.
- Canonical envelope size limit: 1 MiB serialized, including metadata/base64.
  Configure producer, broker and consumer limits to accommodate that record plus
  Kafka batch framing; test the exact boundary. Sparkplug max Birth size is a
  separate Phase 2 qualification gate.

Create the stream with 12 partitions for development tests, seven-day time
retention and delete cleanup policy. This is a test starting point, not a measured
production partition count. Do not compact the immutable event stream. Do not
increase partitions casually: key reassignment can break processing continuity.

## 5. Durability, acknowledgment and bounded ingestion

### Selected Phase 1 mechanism

Use a persistent MQTT 5 subscriber session, stable unique client ID per assigned
ingestion shard, and **manual acknowledgment of delivered QoS 1 messages only
after Kafka's successful delivery callback**. Do not add a second ingestion disk
spool in Phase 1. Persistent broker delivery and edge spooling have distinct jobs.

| Boundary | Guarantee |
| --- | --- |
| Source -> site broker | Depends on publisher QoS, source/edge buffering and broker persistence |
| Broker -> mapper, delivered QoS 1 | Ack only after durable Kafka acceptance; broker session must survive the supported fault |
| Delivered QoS 0 | Best effort before Kafka; count separately; manual ack cannot repair it |
| Kafka -> historian/lake | At least once within retained offsets; sink commits follow durable output |
| Source-identified historian events | Deduplicated within the raw-event/replay retention contract |
| Legacy ingress-identified events | Kafka replay idempotence; MQTT redelivery can create distinct receipts |

Sparkplug's native QoS must not be globally changed to fit a generic MQTT delivery
claim. It requires its own edge/state recovery contract in Phase 2.

Implementation rules:

1. Subscribe without requesting retained snapshots. Historical ingestion must not
   reinterpret subscription bootstrap values as newly produced events. Live
   publications to retained topics still enter the stream. State bootstrapping is
   a separate projection operation.
2. Do not run multiple owners of the same stable MQTT client ID. In Phase 1 scale
   ingress by explicitly disjoint site/topic shard assignments, not ordinary `#`
   subscriptions on every replica. Validate ownership and assignments at startup.
3. Proposed dev bounds: 1,000 pending records, 16 MiB serialized pending bytes,
   Receive Maximum 32. Charge memory until delivery finishes. Account for bounded
   Kafka producer queues and MQTT parser buffers too; serialized bytes are not RSS.
4. Maintain one serialized lifecycle owner. Kafka delivery completions carry an
   MQTT connection generation, packet ID and QoS. Never ack an old generation's
   packet ID on a reconnected session. Ambiguous successful deliveries are replayed;
   packet IDs are transport handles, not event identities.
5. A full queue or a producer enqueue failure must not ack the message. Mark
   readiness false, stop admission by controlled disconnect if needed, continue
   servicing completions, and reconnect with exponential backoff plus jitter.
   Do not block MQTT's network loop waiting indefinitely for capacity.
6. Delivery failure leaves the MQTT delivery unacknowledged. Clear ownership before
   reconnecting so stale callbacks cannot release a new delivery accidentally.
7. On shutdown stop admission, drain for at most ten seconds, acknowledge confirmed
   current-generation deliveries, then exit. Unconfirmed deliveries remain replayable
   at the broker for delivered QoS 1, within the configured session retention.
8. Kafka producer uses idempotence and `acks=all`; production uses RF=3 and
   `min.insync.replicas=2`. Single-node development uses RF=1/minISR=1 explicitly.
   Delivery timeout is bounded; never treat enqueue or `poll(0)` as acceptance.
9. Add persistent Kafka storage and explicit topic initialization to Compose.
   Preserve source data unless a reset is specifically requested.

An upstream publisher receiving PUBACK does not prove Kafka or SQL committed.
Document each boundary in observability and operational instructions.

## 6. Historian consumption and idempotence

Replace direct historian MQTT subscription with Kafka group `uns_historian`.
Keep the `historian_client` service name to minimize unrelated operational churn.
Use manual Kafka offsets and a bounded consumer loop which remains responsive to
rebalance callbacks while database work is pending.

Batch defaults: at most 500 events, 4 MiB serialized bytes, or 100 ms since the
first buffered event. Additionally bound scalar expansion to 20,000 Metric rows
per batch. One event exceeding a limit is quarantined, not partially written.
Limit concurrent database batches; start with one in-flight batch per process.
Parallelism comes from independent Kafka partitions and consumer processes.

Transaction algorithm:

```text
validate and classify envelopes
prepare raw rows and eligible Metric rows within expansion limits
BEGIN
  lock/create checkpoint rows for the affected stream partitions
  discard positions below each stored next_offset
  insert accepted raw rows, returning IDs of newly inserted events
  insert Metrics only for newly inserted telemetry events
  advance checkpoint next_offset for each fully handled contiguous partition prefix
COMMIT
commit the same explicit next offsets to Kafka
```

Do not derive checkpoint positions from `consumer.position()` or the highest
completed offset alone. Poison events and partial processing cannot cause a gap
to be skipped. A database failure does not advance Kafka offsets.

Use an Alembic migration to:

- Add `event_id`, identity quality, received time, event kind, historical flag and
  source metadata to raw rows; preserve query-facing `time`, `topic`, `mqtt_msg`.
- Replace the old JSONB/subscriber unique key with `(time, event_id)`, respecting
  the hypertable time dimension. Source-identified events have invariant `time`;
  ingress receipts freeze it across Kafka retry/replay.
- Compare an immutable content hash on `(time, event_id)` conflict. Different
  source content at that key is quarantined, not silently accepted as a duplicate.
  Exclude receive time and other delivery metadata from that comparison. This
  index does not detect a faulty producer reusing an ID with a different timestamp;
  source-level deduplication requires the immutable source-time contract. Do not
  claim a global, unbounded event-ID registry from this time-scoped constraint.
- Add `event_id` to Metric rows for traceability, without splitting raw/Metric
  atomicity. Historical development rows get deterministic migration-only IDs
  from existing row contents; no false source-ID guarantee for old data.
- Add a small regular table for checkpoint rows keyed by pipeline epoch, Kafka
  topic and partition. Store the next offset. Lock rows in sorted order to avoid
  cross-partition deadlocks. A stale worker may not regress a checkpoint.

Checkpoint authority is the database. On assignment, reconcile Kafka committed
offset with the SQL checkpoint; SQL ahead is safe after a DB-commit/Kafka-commit
failure. Kafka ahead of SQL is a fatal consistency error. Reject a checkpoint
outside Kafka's retained range; do not silently start at `latest`.

A configured pipeline epoch changes when the Kafka stream is intentionally
recreated. Never reuse old checkpoints for a recreated topic with reused offsets.
Backfills use an explicit separate epoch and bounded time range. Raw retention is
90 days; supported routine replay is seven days. Older restoration uses a reviewed
archive backfill, not a promise of indefinite deduplication.

Retain SQLAlchemy Core batch writes initially; benchmark before adding COPY plus
staging tables. Keep TopicBinder enrichment outside the ingestion transaction,
with bounded retry/invalidation, so catalog updates do not block event durability.

## 7. Dead-letter and recovery behavior

`uns.historic-events.dlq` is a restricted, fixed Kafka topic with 30-day development
retention. A DLQ record contains origin, stage, reason code, original event ID or
Kafka coordinates, captured time, and bounded original content. Do not emit raw
payloads into logs. Consumers of the event stream do not consume their own DLQ.

- Invalid MQTT content: freeze a rejection record; ack QoS 1 only after its DLQ
  delivery succeeds. If Kafka/DLQ is unavailable, leave it unacknowledged.
- Oversized input: enforce transport admission limits where possible. If a received
  record exceeds supported DLQ capture size, halt that ingestion shard visibly
  without ack; an explicit operator decision is required. Do not silently truncate
  and call that a recoverable archive.
- Invalid Kafka envelope or identity conflict: durably write the rejection first,
  then mark that partition position handled. Never commit over prior pending events.
- DLQ write followed by crash can duplicate a rejection. Use stage plus origin
  coordinates as the rejection identity; consumers must tolerate duplicates.
- Corrected replay records carry original identity/coordinates and correction
  provenance. A changed event is assigned a new event ID; never mutate old raw rows.

## 8. GraphQL and other consumers

### Kafka-facing GraphQL cutover

Replace client-specified infrastructure Kafka topic names with original MQTT topic
filters. Keep the GraphQL field name `getKafkaMessages` where practical, but change
its input contract and update all callers together. Return the original MQTT
topic and JSON payload; optionally expose event ID/time as additive fields.

One live dispatcher per GraphQL process consumes the canonical stream using its
own ephemeral broadcast group, starting at the live end on first assignment and
resuming normally on reconnect. Separate processes need separate groups; sharing
a group across processes would distribute rather than broadcast their events.
Close/delete ephemeral group state according to broker group-retention policy.

Do not create one Kafka consumer per browser. Dispatcher fan-out uses bounded
per-client queues (100 records and 1 MiB) and a finite subscription count. Disconnect
slow clients with an explicit resubscribe/resync error, rather than accumulating
unbounded buffers or silently claiming complete event delivery.

Check `allowed_topic` against **envelope.topic** before client delivery, and honor
current Access Groups. Never authorize only `uns.historic-events`. Avoid an
unbounded per-event database lookup: use existing resolver caches with model/access
change invalidation. Restrict filters initially to exact MQTT topics to match the
current API scope; add wildcard support only with explicit tests and limits.

Live browser subscriptions are not historical replay APIs. Historical views read
the historian with bounded queries. Remove rewind-to-beginning on every assignment.

### Lake consumer integration

Implement the planned `14_uns_datalake` service against this contract. Preserve one
backend per deployment (MinIO/S3 or ADLS). Do not create a second MQTT ingestion path.

Parquet columns: `schema_version`, `event_id`, `identity_quality`, `time`,
`received_at`, `site_id`, `source_id`, `topic`, `event_kind`, `is_historical`,
`payload`, `raw_payload_base64`. JSON values are serialized JSON text; timestamps
are UTC microseconds. Do not add mutable Asset Enrichment.

Use bounded files per **ingestion date/hour and Kafka partition**, not one file per
MQTT topic or event date. Original event time remains a row column. This avoids
millions of tiny objects and arbitrary late-event date fan-out.

```text
v1/ingest_date=2026-09-09/hour=10/partition=3/<flush_id>.parquet
```

Each partition owns an ordered batch; flush at 60 seconds, 8 MiB estimated bytes,
or 10,000 records, with a worker-wide 32 MiB buffered-byte limit. On pressure flush
the oldest nonempty partition. A frozen retry reuses identical key/bytes. Upload
before committing explicit next offsets, poll while paused, and stop unsafe work
on ownership loss. Crash/replay may produce duplicate rows across files; retain
event IDs so readers can deduplicate. No exactly-once lake claim.

ADLS partial-file visibility requires a completed-object manifest or finalization
protocol before a production query engine reads concurrently. The initial archival
slice retains the earlier limitation and verifies completed uploads only.

### Graph mapper and Sparkplug scope boundary

Their existing direct MQTT paths remain in Phase 1 and retain their known recovery
limitations. They do not block Kafka/historian throughput. Phase 2 migrates the graph
projection to replayable, event-time-aware consumption and establishes Sparkplug
ownership/state first. Do not scale the current Sparkplug mapper by adding replicas.

## 9. Aggregation, retention and replay

Keep current raw/Metric/aggregate retention initially, but record disk estimates
under the benchmark workload. Do not equate sample average with time-weighted
average under RBE.

For Phase 1, maintain a bounded late-data refresh worklist coalesced into UTC daily
ranges. Historian batches update this worklist transactionally when older telemetry
lands. A separate worker refreshes both relevant continuous aggregates in rate-limited
chunks, outside the ingestion transaction. It marks work complete only after refresh
success; crashes retry. Only schedule supported retained ranges and expose failures.
Readiness must report schema/projection failures rather than claiming fresh aggregates.

Phase 2 defines per-signal interpolation, time-weighted integration and quality
semantics before changing OEE or energy calculations. Current avg aggregates retain
their documented sample-mean semantics until then.

## 10. Observability and qualification

Metrics have bounded labels: service, reason, shard, partition, and configured
site. Never event ID, arbitrary MQTT topic or raw exception text as a metric label.

Required signals: pending count/bytes, oldest pending age, delivered QoS class,
Kafka acceptance latency/failures, consumer lag, SQL batch duration/rows, checkpoint
age, duplicate/conflicting identities, DLQ count, late-refresh lag, disk free,
and slow-client disconnects. Distinguish process liveness from dependency readiness.

Development benchmark fixture (not a production capacity promise):

| Parameter | Initial qualification workload |
| --- | --- |
| Simulated sites | 2 |
| Active topics | 10,000 total |
| Sustained rate | 10,000 events/s total, one process value per event |
| Burst | 20,000 events/s for 60 seconds |
| Payload profiles | Small JSON, multi-Metric JSON, 1 MiB envelope boundary |
| Soak | 60 minutes for initial gate; 24 hours before production qualification |
| Faults | Mapper kill, historian kill, Kafka outage 60s, DB outage 5min, rebalance |
| Routine late replay | Events 7 days old |

Record hardware, image digests, storage, network, QoS, compression and actual
serialized event sizes with every result. Sustained p99 source-to-SQL latency target
is 1 second in the healthy development fixture. If hardware cannot meet this,
publish measured saturation and bottleneck; do not relabel it as a passing run.

Acceptance invariants: no missing accepted Kafka positions except durable DLQ
records; no duplicated source-identified SQL events within retention; bounded
pending work under a stopped sink; no unauthorized browser event; no backward
checkpoint movement. Burst/recovery lag must converge after the fault clears.
Measure recovery throughput rather than assume it. Report unaccepted QoS 0 loss
separately; it is outside the durable boundary.

## 11. Phase 2 and Phase 3 design constraints

### Phase 2: edge, Sparkplug and state

- Verify HiveMQ Edge bridge persistence, licensing, mounted storage and power-loss
  behavior on the actual adapter path. The legacy OPC UA SQLite spool is not proof.
- Compute buffer capacity from stored bytes/s * maximum outage * reserve. Require
  recovery throughput above live throughput; give live alarms priority over backfill.
- Partition Sparkplug processing by site/group/edge node. Maintain Birth/Death,
  aliases, seq/bdSeq, quality and host/site reachability as explicit state.
- Use fenced ownership and a durable checkpoint/state strategy; a new owner either
  restores valid state or requests controlled rebirth before accepting alias data.
- Birth/data ordering cannot rely on message-level shared subscriptions. Rate-limit
  rebirth requests and test a whole-site reconnect, unknown aliases and stale Death.
- Prevent historical replay from overwriting newer graph state; use source ordering
  where available and mark uncertainty when legacy clocks cannot establish order.
- Topic Binding and graph hierarchy discovery must not require per-measurement
  structural writes. Batch/coalesce current-state updates with explicit freshness.
- Define per-signal sampling, deadband against last published value, hysteresis,
  maximum silence, quality changes and alarm handling. Validate slow drift and RBE
  aggregation mathematically.

Entry: Phase 1 event contract and recovery tests pass. Exit: a selected real edge
adapter survives the documented outage/power-loss model, Sparkplug restart and
rebirth tests pass, and graph state remains correct after replay.

### Phase 3: regional production deployment

- Keep sites autonomous. Use regional MQTT clusters and selective bridges; do not
  span a low-latency broker cluster across global factory WANs.
- Choose HiveMQ Enterprise or EMQX edition/version after comparing required
  durability, bridge/state semantics, operational support and measured workload.
  Retain HiveMQ Edge for collection unless testing supplies a reason to change.
- Regional Kafka target: at least three brokers across failure domains, RF=3,
  minISR=2, acks=all, persistent storage and a supported controller quorum.
- Provision non-overlapping ingress shards and stable identities through configuration
  management. Autoscaling must account for partition/shard ownership, not just CPU.
- Use broker-side mTLS and authenticated attribute-derived topic policies. Publisher
  metadata alone cannot grant permissions. Enforce default deny and client quotas.
- Bind Console Access Groups to broker policy through an explicit mapping; they are
  not automatically the same authorization mechanism. Test revocation/cache expiry.
- Automate certificate rotation, bridge templates, site onboarding and pinned images.
- Prove N-1 capacity, storage failover, reconnect storms, planned node removal and
  database recovery; publish SLO/RPO/RTO and costs per site/data class.

Entry: measured workloads and actual deployment/provider constraints are available.
Exit: chosen topology passes the agreed production workload and failure gates.

## 12. References and verification status

- [Paho manual acknowledgment](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)
- [HiveMQ Edge bridging and offline buffering](https://docs.hivemq.com/hivemq-edge/mqtt-bridging.html)
- [HiveMQ Enterprise clustering](https://docs.hivemq.com/hivemq/latest/user-guide/cluster.html)
- [EMQX cluster architecture](https://docs.emqx.com/en/emqx/latest/deploy/cluster/mria-introduction.html)
- [Kafka producer durability](https://kafka.apache.org/41/configuration/producer-configs/)
- [Sparkplug 3.0 specification](https://sparkplug.eclipse.org/specification/version/3.0/documents/sparkplug-specification-3.0.0.pdf)

Repository paths were inspected; runtime behavior and capacity have not been
verified. Context7 authentication was unavailable; Paho manual-ack behavior was
checked against its primary documentation. Exact pinned client/broker versions
must pass the acceptance tests before any reliability claim is promoted to fact.
