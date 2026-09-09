# UNS Scalability Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:subagent-driven-development only if the user requests delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-MQTT-topic Kafka production and direct MQTT historian ingestion with one bounded, replayable event pipeline through a coordinated development cutover.

**Architecture:** `kafka_mapper` produces the canonical `uns.historic-events` envelope and acknowledges delivered MQTT QoS 1 only after Kafka confirms acceptance. The historian and lake use independent consumer groups with durable-output-before-offset semantics. GraphQL dispatches authorized live events from a bounded process-level consumer; the existing Sparkplug and graph mappers move to their resilient target in Phase 2.

**Tech Stack:** Python 3.14, existing Paho MQTT wrapper, confluent-kafka/librdkafka, SQLAlchemy Core, Alembic, PostgreSQL/TimescaleDB, Strawberry GraphQL, Prometheus, pytest, Docker Compose; pyarrow and S3/ADLS SDKs for the lake slice.

**Design:** [UNS scalability foundation](../specs/2026-09-09-uns-scalability-foundation-design.md).

**Status:** Planning complete for review. No application implementation or runtime verification is claimed by this document.

---

## 1. Execution boundaries

- The user selected the best development-only route: coordinated cutover, no
  maintenance window, no temporary dual writes, no compatibility topics.
- Implement the foundation in working slices, but switch the default stack only
  after its dependent consumers pass together. Do not leave an intermediate default
  in which GraphQL still expects dotted Kafka topics or history has two writers.
- Source identity and Kafka replay identity are different guarantees. Tests must
  show the limitation for legacy sources rather than hide it behind content hashes.
- Preserve raw-plus-Metric atomicity and existing query-facing raw columns.
- Use current root uv workspace and migrations. Do not create module-local virtual
  environments, a second pool abstraction, or use `create_all()` for deployment.
- Check actual pinned client/broker APIs before implementing session, acknowledgment,
  polling and rebalance behavior. Java Kafka settings are not all librdkafka settings.
- At initial inspection, user changes included GraphQL access/subscription tests
  and a new test conftest; concurrent commits subsequently advanced HEAD. Recheck
  git status and migration head before implementation and integrate existing work.
- Commits, volume deletion, database resets and offset resets require explicit
  authorization. The plan's checkpoints are review boundaries, not commit permission.
- Keep the existing lake plan as adapter-reference material only. Its dual-write,
  three-column, poison-skip and per-topic-object requirements are replaced here.

## 2. Delivery sequence

| Milestone | Tasks | Observable result |
| --- | --- | --- |
| A. Event transport | 1-3 | Source/ingress identity, bounded canonical producer and durable rejection path |
| B. Replayable history | 4-6 | Batched SQL projection, stable deduplication, checkpoints and late refresh |
| C. Consumer cutover | 7-8 | Scoped GraphQL live fan-out and compatible lake archival |
| D. Development release | 9-10 | One default pipeline, fault tests, benchmark report and updated operational docs |

Execute A before B/C, and complete B/C before switching default Compose. Do not
parallelize edits to shared event contracts or SQL migrations. At each milestone,
review the diff and measured/tested outcomes before expanding scope.

For each behavioral increment: add the named regression, run it and verify a
behavioral failure, implement the smallest change, then run the relevant suite.
An import failure only proves a missing component, not the final failure contract.

## 3. File and responsibility map

New files are proposed; existing paths were checked during planning.

| Component | Files | Responsibility |
| --- | --- | --- |
| Event contract | `00_uns_config/src/uns_config/events.py` | Versioned envelope validation, timestamp normalization, immutable identity/key encoding |
| MQTT delivery options | `02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py` | Opt-in stable session/manual ack/retained subscription controls |
| Ingestion state machine | `06_uns_kafka/src/uns_kafka/ingest.py` | Bounded ownership of receipts and delivery completions |
| Ingestion rejection | `06_uns_kafka/src/uns_kafka/rejections.py` | Stable bounded DLQ records and delivery results |
| Kafka adapter | `06_uns_kafka/src/uns_kafka/kafka_handler.py` | Literal topic/key/bytes production, polling and completion callbacks |
| Historian batches | `04_uns_historian/src/uns_historian/batch.py` | Event/byte/Metric/time limits and partition positions |
| Historian loop | `04_uns_historian/src/uns_historian/kafka_consumer.py` | Assignment, pause/resume, SQL completion and safe Kafka commits |
| Historian writes | `04_uns_historian/src/uns_historian/historian_handler.py` | Atomic bulk raw/Metric/checkpoint writes |
| Late refresh | `04_uns_historian/src/uns_historian/aggregate_refresh.py` | Bounded retries of durable late-data work |
| SQL migration | `09_uns_model/migrations/versions/0009_historian_event_pipeline.py` | Identity/index migration, checkpoints and refresh worklist; recheck head before execution |
| GraphQL live dispatcher | `07_uns_graphql/src/uns_graphql/backend/event_stream.py` | One Kafka consumer/process and bounded client fan-out |
| GraphQL contract | `07_uns_graphql/src/uns_graphql/input/kafka.py`, `subscriptions/kafka.py`, `type/streaming_event.py` | Original MQTT topic inputs/outputs and authorization |
| Lake | `14_uns_datalake/src/uns_datalake/{config,batch,checkpoint,parquet,stores,mapper,metrics,health_check,main}.py` | Independent archival consumer with bounded partition batches |
| Deployment | `docker-compose.yml`, `docker-compose.dev.yml`, `conf/settings.yaml` | Persistent dev Kafka, canonical stream bootstrap and coordinated wiring |
| Acceptance | `06_uns_kafka/test/test_pipeline_acceptance.py`, `docs/benchmarks/uns-scalability-foundation.md` | Fault evidence, completeness and capacity results |

## Task 1: Define the canonical envelope and identity contract

**Create:** `00_uns_config/src/uns_config/events.py`, `00_uns_config/test/test_events.py`.
**Modify:** `00_uns_config/src/uns_config/uns_ingest.py` only for explicit event-kind classification.

- [ ] Define a frozen `HistoricEventEnvelope` dataclass containing every field in
  design section 4. Define `EnvelopeError` with a bounded reason code. Add pure
  `encode_event(envelope) -> bytes`, `decode_event(data) -> HistoricEventEnvelope`,
  `event_key(envelope) -> bytes`, and `immutable_content_hash(envelope) -> str`.
- [ ] Add tests for exact round-trip JSON, valid source identity, ingress fallback,
  seconds/milliseconds, timezone offsets, boolean/NaN rejection, unsupported schema,
  missing fields, 1 MiB boundary, and exclusion of platform events.
- [ ] Run: `uv run pytest -n 0 00_uns_config/test/test_events.py -v`.
  Initially expect named contract failures; after implementation expect all pass.
- [ ] Implement collision-free identity/key tuples using canonical JSON encoding:

  ```python
  import hashlib
  import json

  def tuple_digest(parts: tuple[str | int, ...]) -> str:
      wire = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
      return hashlib.sha256(wire).hexdigest()
  ```

  Source identity uses `(site_id, source_id, source_boot_id, source_sequence)`.
  Prefix the digest with `source:`. Ingress IDs use `ingress:` plus a UUID frozen
  for the receipt. Do not derive IDs from a subscriber or a value-only hash.
- [ ] Test that changing `received_at` leaves the immutable content hash unchanged,
  while changing payload/time/topic with the same source identity is detectable.
- [ ] Test two legacy MQTT receipts with equal payloads produce distinct ingress IDs,
  but encoding/retrying one envelope retains the same ID. This is intentional.
- [ ] Review the envelope with historian, GraphQL and lake usages before Task 2.

## Task 2: Add opt-in MQTT delivery and literal Kafka adapters

**Modify:** `02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py`,
`06_uns_kafka/src/uns_kafka/kafka_handler.py`,
`06_uns_kafka/src/uns_kafka/uns_kafka_config.py`.
**Create:** `02_mqtt-cluster/test/test_delivery_options.py`.
**Modify tests:** `06_uns_kafka/test/test_kafka_handler.py`.

- [ ] Add regression tests showing the ingestion client requests a stable MQTT 5
  session with Session Expiry, Receive Maximum, manual ack, and subscription
  Retain Handling 2. Other callers retain their current default behavior.
- [ ] Run: `uv run pytest -n 0 -m "not integrationtest" 02_mqtt-cluster/test/test_delivery_options.py 06_uns_kafka/test/test_kafka_handler.py -v`.
- [ ] Introduce keyword-only options in the shared wrapper; forward manual ack
  explicitly to Paho and build proper CONNECT versus SUBSCRIBE properties. Use
  `clean_start=False` for resuming an established stable ingestion identity and
  configure session expiry to seven days for the test deployment. Verify the
  broker supports that value; do not rely on constructor `clean_session` for MQTT 5.
- [ ] Expose Kafka publication as `publish_event(topic, key, value, on_delivery)`.
  `topic` is literal, `key`/`value` are bytes, and the callback reports success or
  failure. Remove topic conversion when all Task 3 tests switch to this API.
- [ ] Test that enqueue is not reported as durable success and that a `BufferError`
  reaches the caller. Replace INFO-per-message logging with counters/debug logs.
- [ ] Configure bounded librdkafka queues, idempotence, `acks=all` and finite
  delivery timeout. Keep `poll` active so delivery callbacks run under load.
- [ ] Verify unrelated MQTT consumers still connect and subscribe with defaults.

## Task 3: Implement bounded ingestion, manual acknowledgment and DLQ

**Create:** `06_uns_kafka/src/uns_kafka/ingest.py`, `rejections.py`, `prometheus_metrics.py`.
**Modify:** `uns_kafka_listener.py`, `health_check.py` in the same package.
**Create tests:** `06_uns_kafka/test/test_ingest.py`, `test_rejections.py`.
**Modify:** `06_uns_kafka/test/test_uns_kafka_listner.py`.

- [ ] Model a receipt token as `(connection_generation, packet_id, qos)` and keep
  immutable envelope bytes plus accounted size until completion. Maintain record
  and byte budgets; expose admission and completion as separate operations.
- [ ] Write failure tests using controllable fake MQTT/Kafka adapters. Required
  behavior sequence:

  ```text
  receive QoS1 -> Kafka enqueue -> mqtt acknowledgments == []
  Kafka delivery success for current generation -> ack exactly that packet
  Kafka delivery failure -> no ack, readiness false, controlled reconnect
  reconnect then old delivery success -> no ack on new generation
  full byte/count budget -> no ack, no unbounded pending task creation
  invalid payload -> DLQ success -> ack; DLQ failure -> no ack
  delivered QoS0 -> counted as best effort; never upgraded to durable QoS1
  ```

- [ ] Run: `uv run pytest -n 0 -m "not integrationtest" 06_uns_kafka/test/test_ingest.py 06_uns_kafka/test/test_rejections.py -v`.
- [ ] Implement one lifecycle owner and explicit callbacks. Pending limits start
  at 1,000 records/16 MiB. On overflow disconnect without ack, service pending
  completions and reconnect with bounded exponential backoff/jitter. On shutdown
  drain confirmed work for at most ten seconds.
- [ ] Bind ingress source/site from configured ownership mappings, not MQTT
  subscriber identity. Validate non-overlapping shard filters and unique stable
  client IDs. Start with exact site-prefix shard assignments.
- [ ] Classify Sparkplug transport separately, preserve raw bytes, and keep
  normalized telemetry as distinct events. Lifecycle/command events do not become
  scalar process Metrics.
- [ ] Handle invalid content through `uns.historic-events.dlq`. Rejections include
  stage/origin/reason and bounded original bytes. Oversize unarchivable messages
  stop the shard visibly without ack. Never silently skip them.
- [ ] Add liveness/readiness and bounded-label counters. Redelivery after ambiguous
  success is acceptable; event loss masked by an early ack is not.
- [ ] Run the existing Kafka mapper suite; remove tests requiring dotted-topic
  production and replace them with canonical topic/key/envelope assertions.

**Milestone A review:** Event identity limitations documented, no dotted-topic
produce, no early ack, bounded queue and stale-callback tests pass.

## Task 4: Migrate historian identity, checkpoints and late-work schema

**Create:** `09_uns_model/migrations/versions/0009_historian_event_pipeline.py`,
`09_uns_model/test/test_historian_pipeline_migration.py`.
**Modify:** `04_uns_historian/sql_scripts/00_bootstrap.sh` only if ordering changes
are required; the additive schema remains owned by Alembic.

- [ ] Check current migration head before choosing the revision ID. Add raw event
  metadata and `(time, event_id)` uniqueness, Metric event IDs, immutable content
  hash and regular checkpoint/late-refresh tables as specified in design section 6.
- [ ] Write migration tests for an empty initialized historian and a database with
  legacy rows. Backfill a deterministic migration-only ID from canonical legacy
  row content. Test constraints on real TimescaleDB; SQLite does not prove them.
- [ ] Run: `uv run pytest -n 0 09_uns_model/test/test_historian_pipeline_migration.py -v` against the isolated integration database.
- [ ] Preserve query columns and existing rows. Do not drop hypertables to simplify
  index changes. Check compressed-chunk behavior for the pinned Timescale version;
  decompress/recompress affected chunks explicitly where required.
- [ ] Use checkpoint key `(pipeline_epoch, kafka_topic, partition_id)` and
  `next_offset BIGINT NOT NULL`. Worklist rows use UTC day, pending generation and
  processed generation so new late writes cannot be lost during refresh.
- [ ] Test migration twice through normal `upgrade head`, schema access grants,
  and both old-history reads and new identity constraints. Never report a skipped
  integration test as a successful migration check.

## Task 5: Implement atomic batched raw/Metric projection

**Create:** `04_uns_historian/src/uns_historian/batch.py`,
`04_uns_historian/test/test_batch.py`, `test_batch_persistence.py`.
**Modify:** `historian_handler.py`, `metric_flattener.py` and `historian_config.py`
under `04_uns_historian/src/uns_historian/`.

- [ ] Add tests for count, serialized bytes, elapsed time and Metric-expansion
  limits, including one oversized expansion and one batch spanning partitions.
  Define immutable `ConsumedEvent(topic, partition, offset, envelope)` in `batch.py`.
- [ ] Introduce `persist_batch(events, pipeline_epoch)` returning explicit committed
  next offsets and newly inserted count. Preserve the single-event method only
  where a non-ingestion caller still requires it; default runtime uses batches.
- [ ] Test atomic rollback when Metric insertion fails after raw insertion, and
  content conflict rejection for equal identity/time with different content.
  Explicitly test/document that this time-scoped key cannot detect identity reuse
  with a changed timestamp; source deduplication depends on invariant source time.
- [ ] Run: `uv run pytest -n 0 -m "not integrationtest" 04_uns_historian/test/test_batch.py 04_uns_historian/test/test_batch_persistence.py -v`.
- [ ] Implement this transaction order with SQLAlchemy Core:

  ```sql
  BEGIN;
  -- Create missing checkpoint rows, then lock them in sorted key order.
  -- Filter incoming offsets below each authoritative checkpoint.
  -- Check conflicting event identity/content before accepting a duplicate.
  -- Bulk insert raw events with ON CONFLICT (time, event_id) DO NOTHING RETURNING.
  -- Bulk insert Metrics only for returned telemetry event IDs.
  -- Upsert daily late-refresh work generations for affected historic telemetry.
  -- Advance only each fully handled contiguous partition prefix.
  COMMIT;
  ```

- [ ] Configure defaults of 500 events/4 MiB/100 ms and 20,000 Metric rows. Bound
  expansion during traversal instead of constructing an oversized list first.
- [ ] Add real-DB tests for replay after commit, competing writers, sorted locks,
  a stale batch below SQL checkpoint, and absent/null publisher timestamps.
- [ ] Verify duplicate raw events do not create duplicate Metrics. Archive
  Sparkplug transport/lifecycle/commands without flattening protocol metadata.

## Task 6: Add the Kafka historian loop and late-aggregate worker

**Create:** `04_uns_historian/src/uns_historian/kafka_consumer.py`, `aggregate_refresh.py`,
`04_uns_historian/test/test_kafka_consumer.py`, `test_aggregate_refresh.py`.
**Modify:** `04_uns_historian/pyproject.toml`, `Dockerfile`, package `health_check.py`
and `prometheus_metrics.py`.

- [ ] Add confluent-kafka as a direct historian dependency using the workspace's
  version constraint. Point `uns_historian` entrypoint to `kafka_consumer:main`.
- [ ] Use group `uns_historian`, `enable.auto.commit=false` and
  `enable.auto.offset.store=false`. Poll on a dedicated bounded adapter thread;
  use the existing async DB engine without blocking Kafka lifecycle handling.
- [ ] Add deterministic offset/failure tests:

  ```text
  SQL failure -> no Kafka commit
  SQL success + Kafka commit failure -> replay starts from SQL checkpoint
  poison offset 11 behind pending offset 10 -> cannot commit 12 yet
  ownership lost with write pending -> no Kafka commit by old owner
  old owner DB commit before new owner lock -> new owner skips committed prefix
  Kafka committed offset ahead of SQL -> fatal consistency error
  SQL checkpoint before retained beginning -> fatal retention-gap error
  recreated stream with new epoch -> old checkpoint is never reused
  ```

- [ ] Run: `uv run pytest -n 0 -m "not integrationtest" 04_uns_historian/test/test_kafka_consumer.py 04_uns_historian/test/test_aggregate_refresh.py -v`.
- [ ] Keep one in-flight batch per process initially. Pause owned partitions while
  a batch is full/in flight, continue poll callbacks, and resume only within budgets.
  Commit explicit `TopicPartition` next offsets only after SQL success; inspect
  per-partition commit errors. Shutdown abandons uncommitted work safely.
- [ ] A DB transaction already in flight can finish after revoke. SQL checkpoint
  locking makes that replay-safe; the revoked owner still cannot commit Kafka.
  Test this interleaving rather than assuming cancellation rolls back a committed DB.
- [ ] Implement the late-refresh worker using generation claims: capture the
  requested generation, refresh both aggregates, mark only that generation done.
  Concurrent new late data increments the generation and remains pending. Failed
  refreshes retry with rate limits; no refresh executes in the ingestion transaction.
- [ ] Test seven-day-late input, refresh failure/retry, concurrent enqueue during
  refresh and UTC day boundary. Keep `avg` documented as sample mean.
- [ ] Ensure TopicBinder observation and catalog invalidation are bounded and do
  not delay SQL event commit. Capture binding failures separately.

**Milestone B review:** SQL raw/Metric/checkpoint atomicity verified on Timescale,
offset-gap tests pass, database outage does not grow memory without bound, and
seven-day replay updates aggregate results.

## Task 7: Cut GraphQL over to authorized canonical live events

**Create:** `07_uns_graphql/src/uns_graphql/backend/event_stream.py`,
`07_uns_graphql/test/backend/test_event_stream.py`.
**Modify:** `07_uns_graphql/src/uns_graphql/subscriptions/kafka.py`,
`input/kafka.py`, `type/streaming_event.py`, `graphql_config.py`, `uns_graphql_app.py`.
**Modify tests:** `07_uns_graphql/test/subscriptions/test_kafka.py`,
`07_uns_graphql/test/input/test_kafka_topic.py`.

- [ ] Replace infrastructure topic input with exact original MQTT topic input.
  Preserve the field name where practical, but update its description/validation.
  Reject arbitrary Kafka topic names and excessive input count (initially 100).
- [ ] Add a process-lifecycle-owned dispatcher and one Kafka consumer per process.
  Each process gets an independent ephemeral broadcast group, not one shared
  competing group across API replicas. First start is live-end only.
- [ ] Write tests demonstrating two browser clients receive the same permitted
  event without creating two Kafka consumers; two process dispatchers do not steal
  each other's messages; reconnect does not rewind the whole stream.
- [ ] Run: `uv run pytest -n 0 -m "not integrationtest" 07_uns_graphql/test/backend/test_event_stream.py 07_uns_graphql/test/subscriptions/test_kafka.py 07_uns_graphql/test/input/test_kafka_topic.py -v`.
- [ ] Decode the envelope before filtering. Authorize `envelope.topic` with current
  Access Groups, then yield `StreamingMessage` with that original topic and JSON
  payload bytes. Never authorize using the canonical Kafka topic string.
- [ ] Bound each client at 100 messages/1 MiB and close a slow subscription with a
  clear resync error. Enforce a configured maximum of 200 live stream clients per
  process initially. Poll outside the asyncio request loop.
- [ ] Test access revocation during an active stream, a restricted caller requesting
  an unauthorized exact topic, malformed envelopes and cancellation/shutdown.
- [ ] Search actual frontend/generated API callers before editing; the inspected
  frontend source search found no `getKafkaMessages` reference. Update any callers
  found at implementation time, but do not invent an unrelated UI change.

## Task 8: Integrate the lake with the new envelope and bounded file layout

**Create package:** `14_uns_datalake/pyproject.toml`, `Dockerfile`, `README.md`,
`src/uns_datalake/__init__.py` and the modules in the responsibility map.
**Create tests:** `14_uns_datalake/test/test_config.py`, `test_batch.py`,
`test_checkpoint.py`, `test_parquet.py`, `test_stores.py`, `test_mapper.py`,
`test_health_check.py`, `test_deployment.py`.
**Modify:** root `pyproject.toml` and root `uv.lock` for workspace registration.

- [ ] Reuse `events.py` for validation; do not create a competing three-field lake
  envelope. Define a local `ObjectStore` protocol with
  `put(path: str, parquet_bytes: bytes) -> None` and inject fake adapters in tests.
- [ ] Implement one selected backend: MinIO/S3 or ADLS. Retain the previous lake
  spec's exact-endpoint local credential rule and production credential chains.
  Patch SDK credential discovery in offline tests, not just upload calls.
- [ ] Implement the design's Parquet columns and UTC timestamp types. Test exact
  schema, identity preservation, Unicode topic/payload and raw Sparkplug bytes.
- [ ] Group files by ingestion date/hour and Kafka partition. Use one ordered
  batch per partition; 60 seconds/8 MiB/10,000 records and 32 MiB worker-wide budget.
  Flush oldest nonempty partition when the global budget is reached.
- [ ] Write a test with 10,000 different MQTT topics in one partition/time window:
  object count follows configured batch limits, not the number of MQTT topics.
- [ ] Run: `uv run pytest -n 0 -m "not integrationtest" 14_uns_datalake/test -v` after workspace registration.
- [ ] Freeze keys and bytes for retry, upload before explicit offset commit,
  inspect partition commit failures, and service rebalances while paused.
  Persist rejected envelopes to the restricted DLQ before advancing them.
- [ ] Test upload-then-crash duplicates carry the same event IDs; partial upload
  failure does not commit unsafe offsets; ownership loss does not commit.
  Document at-least-once files and the ADLS concurrent-reader limitation.

**Milestone C review:** No per-browser Kafka consumer, envelope-topic authorization
passes, and the lake produces bounded file counts with replay-identifiable rows.

## Task 9: Wire one coordinated development deployment

**Modify:** `docker-compose.yml`, `docker-compose.dev.yml`, `conf/settings.yaml`,
`conf/.secrets_template.yaml`, `08_uns_observability/prometheus/prometheus.yml`.
**Create:** `06_uns_kafka/src/uns_kafka/bootstrap.py`,
`06_uns_kafka/test/test_bootstrap.py`, `test_pipeline_deployment.py`.

- [ ] Add an idempotent Kafka topic-initializer entrypoint and Compose oneshot.
  Create exactly `uns.historic-events` (12 partitions/7 days) and its fixed DLQ
  (30 days); explicitly set dev RF=1/minISR=1 and delete cleanup.
  Existing mismatched topic settings cause a diagnostic failure, not destructive
  recreation. Disable automatic arbitrary topic creation for the test stack.
- [ ] Add a named Kafka data volume and a configured pipeline epoch. Pin verified
  service image versions/digests when running integration; do not choose a guessed
  release tag in this plan. Record those digests in the benchmark report.
- [ ] Add ingestion session/shard/queue settings and new historian batching/group
  settings. Ensure per-environment config merging does not reintroduce `#` on
  every shard or legacy dotted topics.
- [ ] Switch `historian_client` to Kafka dependencies and the new entrypoint.
  Preserve graph/Sparkplug MQTT dependencies until Phase 2. Add the MinIO initializer
  and lake mapper using the accepted default-backend convention.
- [ ] Test liveness separately from readiness. Kafka down can leave MQTT/live
  graph functioning while historian becomes stale; the UI must not imply healthy
  history solely because MQTT accepts connections.
- [ ] Add ingestion and lake Prometheus jobs, bounded labels and lag/backpressure
  alerts. Reuse existing historian metrics where semantics remain valid.
- [ ] Run: `uv run pytest -n 0 -m "not integrationtest" 06_uns_kafka/test/test_bootstrap.py 06_uns_kafka/test/test_pipeline_deployment.py 14_uns_datalake/test/test_deployment.py -v`.
- [ ] Validate Compose through the repository's `uns_compose` configuration loader;
  do not print resolved secret-bearing configuration. Start the development stack
  and verify declared volumes, topic settings, migrations and service readiness.

## Task 10: Fault qualification, capacity measurement and documentation

**Create:** `06_uns_kafka/test/test_pipeline_acceptance.py`,
`06_uns_kafka/test/pipeline_load.py`, `docs/benchmarks/uns-scalability-foundation.md`.
**Update:** module READMEs for Kafka/historian/GraphQL/lake, root README, relevant
Grafana dashboards and the previous lake design/plan cross-references.

- [ ] Implement a deterministic load fixture with source boot/sequence IDs and a
  manifest of expected publications. Count source receipts, Kafka accepted records,
  DLQ records, SQL event IDs and archived IDs separately.
- [ ] Add explicitly marked integration scenarios for mapper crash before/after
  Kafka delivery, historian crash after SQL commit, 60s Kafka outage, 5min DB outage,
  ownership loss, retention-gap detection, legacy redelivery and slow API clients.
- [ ] Run offline affected suites:

  ```powershell
  uv run pytest -n 0 -m "not integrationtest" 00_uns_config/test 02_mqtt-cluster/test 04_uns_historian/test 06_uns_kafka/test 07_uns_graphql/test 09_uns_model/test 14_uns_datalake/test
  ```

- [ ] Run integration against the isolated development stack:

  ```powershell
  uv run pytest -n 0 -m integrationtest 06_uns_kafka/test/test_pipeline_acceptance.py 09_uns_model/test/test_historian_pipeline_migration.py 04_uns_historian/test/test_batch_persistence.py
  ```

  Expected: every acceptance scenario executes and passes; missing services are
  reported as blocked, not silently counted as success.
- [ ] Implement `pipeline_load.py` arguments `--sites`, `--topics`, `--rate`,
  `--seconds`, `--burst-rate`, `--burst-seconds`, and `--report`. Use environment or
  mounted settings for credentials, never command-line secrets. The report path
  must be explicitly supplied and its parent verified before writing.
- [ ] Run the design's 10,000 events/s, 10,000-topic, two-site fixture for 3,600s
  with a 20,000 events/s 60s burst. Capture CPU/RSS/disk/queue/lag and p99 latency,
  plus serialization and Metric expansion costs. Do not use this target as evidence
  that the platform already supports it.
- [ ] Reconcile missing/extra IDs and accepted offsets. Replay source-identified
  events and verify one raw event/one set of Metrics; demonstrate the documented
  weaker legacy identity guarantee. Verify late aggregates with 7-day-old input.
- [ ] Record hardware, image digests, topology, configured limits, measured
  saturation, failure recovery times, and observed p99 against the 1s healthy target.
  A failed target remains a reported capacity gap with its limiting component.
- [ ] Run relevant lint/type checks from existing module conventions; then inspect
  `git diff --check` and the final diff. Refresh the repository graph with
  `graphify update .` and report any tooling blocker accurately.
- [ ] Update the runtime documentation: old dotted topics and direct MQTT historian
  behavior are removed, delivery boundaries are explicit, and old lake requirements
  link to the new accepted design. Add an ADR after approval, preserving historical ADRs.

**Milestone D release gate:** one default pipeline, all required fault tests executed,
source/ingress identity guarantees distinguished, no silent rejection, bounded
memory under downstream outage, authorized live clients, replay-aware aggregates,
and a measured capacity report. This closes Phase 1, not production HA qualification.

## 4. Phase 2 delivery roadmap: edge and state resilience

Create a separate detailed spec/plan after Milestone D, in this order:

| Slice | Primary modules | Deliverables | Exit evidence |
| --- | --- | --- | --- |
| Edge durability | `conf/hivemq`, `10_uns_opcua`, deployment | Actual adapter-path disk buffering, bytes/time capacity, overflow policy, power-loss contract | WAN outage and gateway power-loss recovery on selected edge product |
| Sparkplug ownership | `05_sparkplugb`, shared event contracts | Node-affine ownership, fenced state, seq/bdSeq and aliases, controlled rebirth, derived event IDs | Whole-site Birth storm, mapper restart, stale Death and unknown-alias tests |
| Replayable current state | `03_uns_graphdb`, graph query consumers | Kafka-backed batched/coalesced graph state, monotonic source state, bounded hierarchy discovery | Replay cannot overwrite newer live state; cold bootstrap is qualified |
| Signal policy | edge adapters, historian, `12_uns_oee` | Deadbands against last publish, quality/max silence, late Metric timestamps, time-weighted semantics where needed | Slow drift, irregular sampling and historical sample test vectors |

The real broker edition/license and required outage duration are mandatory inputs
to the edge slice. If no duration is supplied, benchmark available capacity and
present supported duration; never silently call a small spool a 24-hour buffer.

## 5. Phase 3 delivery roadmap: production multi-site scaling

| Slice | Decision input | Deliverables | Exit evidence |
| --- | --- | --- | --- |
| Broker selection | Phase 1/2 rates, persistence and support requirements | Versioned comparison of HiveMQ Enterprise and EMQX; selected regional topology | Representative workload and N-1 results |
| Infrastructure | Provider, sites, network RTT and RPO/RTO | Regional Kafka/broker HA, DB recovery, explicit shard ownership, persistent storage | Node/storage/network fault and restore exercises |
| Identity/governance | Device capabilities and asset assignments | mTLS enrollment, trusted topic policies, rotation/revocation, quotas, configuration-as-code | Cross-site access denied; credential rotation and revocation tested |
| Federation | WAN bandwidth and required data classes | Selective bridges, loop prevention, site availability, replay priorities | WAN partition/reconnect does not create loops or stale healthy state |
| Operations | Measured demand and cost envelope | Capacity workbook, dashboards, alerts, runbooks, upgrade/rebalance procedure | Onboarding another site and draining a broker meet approved SLOs |

No provider-specific cluster manifest, broker count or outage guarantee is approved
merely by this roadmap. Select them using measured load and explicit deployment
requirements rather than the placeholder million-tag scenario.

## 6. Design coverage and completion record

| Design requirement | Implementation task |
| --- | --- |
| Coordinated cutover, no legacy dual writes | 2, 3, 7, 9 |
| Envelope, identities, keys and classification | 1, 3 |
| Manual ack, bounded work and session generations | 2, 3 |
| Rejection durability | 3, 6, 8 |
| Atomic raw/Metric/checkpoint writes | 4, 5, 6 |
| Aggregate refresh after late replay | 4, 6, 10 |
| GraphQL scope and bounded broadcast | 7 |
| Lake identity, bounded file count and offsets | 8 |
| Persistent dev deployment and observability | 9 |
| Failure/capacity evidence | 10 |
| Edge, Sparkplug and graph recovery | Phase 2 roadmap |
| HA, ACL automation and global deployment | Phase 3 roadmap |

Implementation starts with Task 1 after design/plan review. Keep all checkboxes
unchecked until their work and checks have actually completed. This planning
document does not itself establish test success or production readiness.
