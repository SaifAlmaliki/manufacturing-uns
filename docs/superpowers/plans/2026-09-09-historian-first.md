# Historian-first Implementation Plan

> **Superseded planning direction (2026-09-11):** Do not execute this plan for
> UNS-to-lake delivery. The approved scope covers machine and business-system
> publications, routed by source application, site, and payload schema, with no
> historian dependency or downstream transformation work. See the
> [replacement design awaiting written review](../specs/2026-09-11-multi-system-uns-to-lake-design.md).
> Its task-by-task replacement plan follows written design approval. The original
> proposal is retained below for historical context; no runtime cutover is implied.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`
> to implement this plan task-by-task. Use `superpowers:subagent-driven-development`
> only if delegation is explicitly selected. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the default Kafka-mediated telemetry pipeline with durable MQTT
ingestion into Timescale and a recoverable database-backed Parquet archive worker.

**Architecture:** Raw events, Metrics, and archive references commit together.
The archive worker publishes immutable data plus commit manifests using durable
batch state in PostgreSQL. Operational dashboards poll authorized historian queries;
Kafka is removed from their active dependency path after a coordinated cutover.

**Tech Stack:** Python 3.14, existing Paho MQTT wrapper, SQLAlchemy Core/asyncpg,
Alembic, TimescaleDB/PostgreSQL, PyArrow, boto3/MinIO, existing ADLS adapter,
Strawberry GraphQL, React/TypeScript, pytest, Vitest, Docker Compose, Prometheus.

---

Specification: [Historian-first design](../specs/2026-09-09-historian-first-design.md).
Status: Planning artifact for later execution. No implementation has been performed.

## Execution rules

- Re-read `AGENTS.md`, relevant skills, the spec, and current diffs before starting.
  The drafting worktree already contained unrelated/uncommitted runtime changes.
- Follow repository TDD guidance for new behavior. Each task below has a failing
  test contract, implementation algorithm, and targeted verification command.
- Use existing module conventions and SQLAlchemy Core. Do not introduce an ORM
  ingestion path, a second pool, a general queue framework, or a new broker.
- Development cutover is assumed. Production consumers, inability to quiesce
  publishers, or insufficient broker buffering require revisiting the cutover first.
- Commit only when requested by the executing user. Suggested commit boundaries
  are tasks; no task authorizes deleting volumes or resetting offsets.
- All command examples run from the repository root unless a working directory is
  stated. Python tests use `uv run --package <package> pytest ... -n 0` to avoid
  parallel stateful database fixtures. An unavailable service is not a test pass.
- Refresh API documentation for installed versions before MQTT/S3/ADLS/Timescale
  integration changes. Keep service fault tests in an isolated development stack.

## File responsibilities

| Area | Existing files to modify/reuse | Proposed new files |
| --- | --- | --- |
| Pure receipt normalization | `00_uns_config/src/uns_config/events.py`, `06_uns_kafka/src/uns_kafka/ingest.py`, `06_uns_kafka/src/uns_kafka/rejections.py` | `00_uns_config/src/uns_config/receipts.py` |
| MQTT delivery controls | `02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py` | Tests added to existing MQTT test directory |
| Schema and archive work | `09_uns_model/src/uns_model/historian_pipeline.py` | `09_uns_model/migrations/versions/0010_historian_first_archive.py`, `09_uns_model/src/uns_model/archive_repository.py` |
| Batched historian | `04_uns_historian/src/uns_historian/batch.py`, `historian_handler.py`, `historian_config.py`, `health_check.py`, `prometheus_metrics.py`, `aggregate_refresh.py` | `04_uns_historian/src/uns_historian/mqtt_ingest.py`, `retention.py` |
| Lake export | `14_uns_datalake/src/uns_datalake/{main,config,parquet,stores,metrics,health_check}.py` | `14_uns_datalake/src/uns_datalake/archive_worker.py`, `publication.py`, `backfill.py` |
| Dashboard data | `07_uns_graphql/src/uns_graphql/backend/{historian,event_stream}.py`, `subscriptions/kafka.py`, `graphql_config.py` | Transport-neutral query tests as described below |
| UI refresh | `11_frontend/src/services/graphql/client.ts`, current dashboard/condition-monitoring hooks | `11_frontend/src/hooks/useHistorianRefresh.ts`, its test |
| Operations | `docker-compose.yml`, `conf/settings.yaml`, module/root `pyproject.toml`, `uv.lock`, existing SQL bootstrap and Prometheus config | `docs/operations/historian-first-cutover.md`, pipeline integration tests |

Migration number 0010 follows the observed 0009 head. If the head advances before
execution, allocate the next revision and update this plan's migration references;
never rewrite an applied migration.

## Task 1: Baseline and runnable acceptance harness

**Files**
- Read: the file map above and `docs/superpowers/specs/2026-09-09-uns-scalability-foundation-design.md`.
- Create: `14_uns_datalake/test/test_historian_first_pipeline.py`.
- Create: `docs/operations/historian-first-cutover.md`.

- [ ] Run `git status --short`, `git diff --stat`, and `git log --oneline -10`.
  Record current entry points, migration head, broker/database images, active
  retention policies, and callers of the Kafka GraphQL subscription.
- [ ] Inspect current `conftest.py` files and existing pipeline fixture code in
  `06_uns_kafka/src/uns_kafka/pipeline_fixture.py`. Reuse database/object-store
  provisioning conventions without depending on Kafka for the new fixture.
- [ ] Add an integration harness contract with deterministic source-identified
  messages, MQTT publisher, SQL inspection, and manifest-aware Parquet reading:

```python
@pytest.mark.integrationtest
async def test_committed_events_reach_lake_without_kafka(pipeline):
    expected = await pipeline.publish_source_events(count=25)
    await pipeline.wait_for_committed(expected)
    await pipeline.wait_for_archived(expected)
    assert await pipeline.raw_event_ids() == expected
    assert await pipeline.metric_event_ids() == expected
    assert await pipeline.committed_lake_event_ids() == expected
    assert not pipeline.kafka_running
```

The `pipeline` fixture must expose exactly these operations: publish returns a set
of known IDs; waits have explicit timeouts and report pending rows/manifests;
inspection methods return sets for the isolated test's IDs. It must never convert
a missing service into success. Build the fixture incrementally as tasks land.

- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_historian_first_pipeline.py -n 0 -v`.
  Expected initial failure: missing historian-first path, not a passing skip.
- [ ] Write the runbook's baseline/cutover/rollback headings with the exact procedure
  from spec section 12. Include data reconciliation and the post-new-writes rollback
  limit; do not use a reset/volume deletion shortcut.

## Task 2: Extract receipt normalization from Kafka

**Files**
- Create: `00_uns_config/src/uns_config/receipts.py`.
- Create: `00_uns_config/test/test_receipts.py`.
- Modify: `06_uns_kafka/src/uns_kafka/ingest.py`, `rejections.py` only as needed to share pure helpers.
- Reuse: `00_uns_config/src/uns_config/events.py`, `uns_ingest.py`.

- [ ] Add tests for stable source identities, frozen ingress identities, binary
  Sparkplug payloads, source/ingress timestamp quality, explicit exclusions,
  oversized payload rejection, and missing ownership mappings.

```python
def test_equal_samples_are_not_source_deduplication(receipt_factory):
    a = receipt_factory(topic="E/S/A/L/D/value", payload=b'{"value":1}')
    b = receipt_factory(topic="E/S/A/L/D/value", payload=b'{"value":1}')
    assert a.envelope.identity_quality == b.envelope.identity_quality == "ingress"
    assert a.event_id != b.event_id
```

Prove frozen-receipt reuse through a failed write and retry in Task 5; a frozen
value alone is not proof that the lifecycle retains it.

- [ ] Define immutable `ReceiptToken(connection_generation, packet_id, qos)` and
  `NormalizedReceipt(receipt_id, token, envelope, serialized_envelope)` types.
  Represent rejection/exclusion as explicit outcomes, not empty envelopes.
- [ ] Move the existing canonical normalization/ownership/rejection logic into
  the pure module; leave transport delivery callbacks in their owning modules.
  Preserve the current 1 MiB envelope limit and source trust rules.
- [ ] Run `uv run --package uns_config pytest 00_uns_config/test/test_receipts.py 00_uns_config/test/test_events.py -n 0 -v`.
  Locate/adjust the existing event test filename if changed; new receipt tests
  must pass and existing envelope behavior must not regress.

## Task 3: Add complete snapshots and archive metadata schema

**Files**
- Create: `09_uns_model/migrations/versions/0010_historian_first_archive.py`.
- Create: `09_uns_model/test/test_historian_first_schema.py`.
- Modify: `04_uns_historian/sql_scripts/02_setup_hypertable.sql`, `04_setup_metrics_hypertable.sql` for compatible fresh initialization and retention defaults.

- [ ] Test migration on a fresh initialized Timescale DB and on a DB at revision
  0009 with existing raw rows, including compressed chunks where supported.
  Require failure if prerequisite raw tables are absent; do not silently mark
  this revision applied without the raw snapshot column.
- [ ] Add the schema from spec section 7 and nullable snapshot/provenance columns
  for the backfill period. New writers must always provide them. Add positive
  bounds/state constraints, keys, worklist indexes, and existing service-role grants.

```sql
CREATE TABLE historian.archive_work (
    event_time timestamptz NOT NULL,
    event_id text NOT NULL,
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    envelope_bytes integer NOT NULL CHECK (envelope_bytes > 0),
    batch_id uuid,
    PRIMARY KEY (event_time, event_id)
);
CREATE INDEX archive_work_pending
    ON historian.archive_work (enqueued_at, event_time, event_id)
    WHERE batch_id IS NULL;
CREATE INDEX archive_work_batch ON historian.archive_work (batch_id);
```

Create `archive_batch` before adding the work-to-batch foreign key. Use the complete
field/state list in spec section 7. Do not add a cascading raw-row foreign key that
can erase pending work. Keep the existing `(time,event_id)` hypertable uniqueness.

- [ ] Add an immutability guard allowing only the one-time NULL-to-snapshot
  backfill; reject subsequent snapshot edits. Exempt query-facing topic remapping,
  but disallow mutation of time/event identity and snapshot content hash.
- [ ] Disable unconditional retention through an additive migration that records
  removed job configuration for the runbook. Do not drop raw data or old checkpoints.
- [ ] Run `uv run --package uns_model pytest 09_uns_model/test/test_historian_first_schema.py -n 0 -v`.
  Expected: upgrade preserves row counts/identities, constraints reject bad states,
  topic remapping cannot mutate a frozen snapshot, and fresh initialization works.

## Task 4: Atomic transport-neutral historian persistence

**Files**
- Modify: `04_uns_historian/src/uns_historian/batch.py`, `historian_handler.py`.
- Create: `04_uns_historian/test/test_mqtt_batch_persistence.py`.
- Reuse: `aggregate_refresh.py`, `metric_flattener.py`.

- [ ] Add transaction-boundary tests:

```python
@pytest.mark.integrationtest
async def test_work_insert_failure_rolls_back_raw_and_metrics(writer, db, receipt):
    db.fail_next_archive_work_insert()
    with pytest.raises(Exception):
        await writer.persist_receipts([receipt])
    assert await db.raw_count() == 0
    assert await db.metric_count() == 0
    assert await db.archive_work_count() == 0

@pytest.mark.integrationtest
async def test_duplicate_does_not_requeue_completed_archive(writer, db, receipt):
    await writer.persist_receipts([receipt])
    await db.complete_archive_for(receipt.event_id)
    await writer.persist_receipts([receipt])
    assert await db.raw_count() == 1
    assert await db.archive_work_count() == 1
    assert await db.pending_archive_count() == 0
```

Use scoped integration fixtures that implement these fault/inspection helpers
against real SQL transactions; do not substitute a list-backed fake for atomicity.

- [ ] Introduce `persist_receipts(receipts)` returning committed/rejected receipt
  IDs and new/duplicate counts, with no Kafka offsets. Reuse metric conversion and
  batch bounds; enforce the 20,000 Metric cap across the entire batch.
- [ ] Implement transaction order from spec section 6. Compare duplicates using
  immutable snapshot content; preserve existing remapped query topics. Persist
  binary raw payloads and all canonical fields in the snapshot.
- [ ] Quarantine validation/content conflicts inside the batch without losing
  valid siblings. Roll back on DB failures and preserve all unresolved receipts.
- [ ] Retain topic binding and late aggregate refresh, counting only new inserts.
- [ ] Run `uv run --package uns_historian pytest 04_uns_historian/test/test_mqtt_batch_persistence.py -n 0 -v`.
  Also run existing batching, flattener, aggregate-refresh, and handler tests affected
  by the refactor; expected duplicate Metrics and archive memberships remain zero.

## Task 5: Durable direct-MQTT historian lifecycle

**Files**
- Create: `04_uns_historian/src/uns_historian/mqtt_ingest.py`.
- Create: `04_uns_historian/test/test_mqtt_ingest.py`.
- Modify: `04_uns_historian/src/uns_historian/{historian_config,health_check,prometheus_metrics}.py`.
- Modify if required: `02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py` and corresponding delivery-option tests.

- [ ] Add deterministic lifecycle tests with a controllable async writer and MQTT
  ACK spy, including failure, reconnect-generation invalidation, queue saturation,
  exclusions, rejections, shutdown, and partial batches below Receive Maximum.

```python
async def test_ack_waits_for_commit(owner, writer, mqtt, receipt):
    owner.admit(receipt)
    await owner.flush_due()
    assert mqtt.acked == []
    writer.resolve_commit()
    await owner.drain_completions()
    assert mqtt.acked == [receipt.token]

async def test_old_commit_cannot_ack_new_connection(owner, writer, mqtt, receipt):
    owner.admit(receipt)
    await owner.flush_due()
    owner.disconnected()
    owner.connected()
    writer.resolve_commit()
    await owner.drain_completions()
    assert mqtt.acked == []
```

The test owner contract is `admit`, `flush_due` (starts but does not await blocked
I/O), `drain_completions`, `disconnected`, and `connected`. Keep all lifecycle state
in one owner. Inject clocks/writer/ACK port rather than sleeping in unit tests.

- [ ] Implement bounded handoff, timed batches, same-receipt retries, actual
  disconnect/reconnect actions, stable shard identity, and ten-second shutdown drain.
- [ ] Configure subscription QoS 1 and `MqttDeliveryOptions.ingestion()`; test that
  QoS 0 remains best effort and retained bootstrap is not archived as new telemetry.
- [ ] Prove SQL rollback/uncertain completion does not ACK; retry uses the original
  envelope bytes and identity. Ensure excluded messages release MQTT capacity.
- [ ] Run `uv run --package uns_historian pytest 04_uns_historian/test/test_mqtt_ingest.py -n 0 -v`.
- [ ] Against the actual broker, test process kill after commit/before ACK and
  broker restart with persistent session data. Report loss on expired/full sessions
  separately. Do not switch the default entry point until Task 11.

## Task 6: Durable claims, staging, and SQL recovery

**Files**
- Create: `09_uns_model/src/uns_model/archive_repository.py`.
- Create: `09_uns_model/test/test_archive_repository.py`.
- Create: `14_uns_datalake/src/uns_datalake/archive_worker.py`.
- Create: `14_uns_datalake/test/test_archive_worker.py`.

- [ ] Test reverse commit ordering with two real SQL connections: transaction A
  inserts work but waits; B inserts/commits and is claimed; A then commits and must
  be claimed on the next pass. Add late-event and duplicate membership cases.
- [ ] Implement these focused repository operations:

```text
acquire_worker_lock() -> dedicated owned connection or ownership failure
resume_or_claim(max_rows, max_bytes, oldest_age) -> batch or no work
read_members(batch_id) -> immutable envelopes in deterministic order
stage(batch_id, parquet_bytes, manifest_bytes, checksum, keys) -> staged batch
complete(batch_id) -> complete; clear staged data only
record_failure(batch_id, reason) -> retry metadata; preserve state
```

- [ ] Implement the claim transaction explicitly:

```sql
SELECT event_time, event_id, envelope_bytes
FROM historian.archive_work
WHERE batch_id IS NULL
ORDER BY enqueued_at, event_time, event_id
LIMIT :max_rows
FOR UPDATE SKIP LOCKED;
```

Apply the cumulative byte limit before assigning membership; an individually
oversized legacy row is a reported backfill/integrity issue, not silently skipped.
Create the batch and assign selected rows in that same transaction. Do not advance
a cursor past uncommitted rows. Resume existing incomplete work first.

- [ ] Add worker session-lock loss handling, immutable membership, 64 MiB staging
  bound with transactional split before staging, and no open SQL transaction while
  uploading. A second process must not create a competing batch for the same row.
- [ ] Run `uv run --package uns_model pytest 09_uns_model/test/test_archive_repository.py -n 0 -v`.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_archive_worker.py -n 0 -v`.

## Task 7: Versioned Parquet and manifest publication

**Files**
- Modify: `14_uns_datalake/src/uns_datalake/parquet.py`, `stores.py`.
- Create: `14_uns_datalake/src/uns_datalake/publication.py`.
- Create: `14_uns_datalake/test/test_publication.py`.
- Modify: existing Parquet/store tests in `14_uns_datalake/test`.

- [ ] Add round-trip tests for every canonical field plus provenance/hash, including
  binary payload, UTC microseconds, null optional metadata, and late timestamps.
- [ ] Implement format v2 and the fixed keys in spec section 8. Manifest fields are
  `format_version`, `batch_id`, `data_key`, `sha256`, `byte_length`, `row_count`,
  `min_event_time`, and `max_event_time`. Canonicalize JSON serialization once.
- [ ] Extend the object-store contract to `publish_exact(key, bytes, sha256)` and
  `verify_exact(key, sha256, byte_length)`. Use conditional creation/finalization
  where supported; on already-existing keys verify content and reject mismatches.
  Keep the byte artifacts in SQL as the retry authority.
- [ ] Implement publication:

```text
batch = repository.resume_or_claim(...)
if batch.state == claimed:
    records = repository.read_members(batch.id)
    encode and repository.stage(exact bytes + exact manifest)
store.publish_exact(batch.data_key, batch.parquet_bytes, batch.data_sha256)
store.publish_exact(batch.manifest_key, batch.manifest_bytes, manifest_sha256)
repository.complete(batch.id)
```

- [ ] Inject a crash/failure at each arrow. Assert retries use identical keys and
  bytes and the committed reader returns one membership per event.

```python
async def test_manifest_success_sql_failure_is_idempotent(worker, repo, store):
    repo.fail_next_completion()
    await worker.run_once()
    first = dict(store.objects)
    await worker.run_once()
    assert store.objects == first
    assert repo.completed_batches == 1
```

Define `run_once` to record retryable publication/SQL-finalization failures and
return without deleting staged state; integrity violations instead halt readiness.

- [ ] Add a manifest-aware reader helper to the integration fixture; verify it
  ignores orphaned data and refuses checksum/length mismatches.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_publication.py -n 0 -v`.
  Repeat the adapter contract against MinIO. Keep ADLS support only with equivalent
  finalize/verify behavior; label its live Azure qualification separately.

## Task 8: Idempotent backfill and archive-aware retention

**Files**
- Create: `14_uns_datalake/src/uns_datalake/backfill.py`.
- Create: `14_uns_datalake/test/test_backfill.py`.
- Create: `04_uns_historian/src/uns_historian/retention.py`.
- Create: `04_uns_historian/test/test_archive_retention.py`.
- Modify: `09_uns_model/src/uns_model/archive_repository.py`, module CLI entry points.

- [ ] Backfill tests must preserve existing IDs, represent unknown legacy metadata
  honestly, survive restarts, and never add a second work row for an existing event.
- [ ] Implement a bounded CLI backfill with writers paused, reconstructing available
  envelopes and setting provenance `reconstructed`. Persist progress for usability,
  but prove completion using raw-to-work/snapshot anti-joins, not a max timestamp.
- [ ] Add `uns_datalake_backfill` entry point with `--dry-run` and explicit apply
  mode; dry-run reports row counts, missing source metadata/binary fidelity, and
  oversized rows. Set `backfill_complete` only after zero coverage gaps.
- [ ] Implement retention with `--dry-run` as default and explicit `--apply`.
  Use shared ingestion/claim coordination versus exclusive retention coordination.
  Check exact chunk coverage and retire only verified chunks in the same transaction.
- [ ] Test these cases against Timescale:

```text
all raw rows complete -> exact expired chunk eligible
one unassigned/claimed/staged work row -> chunk blocked
one raw row without work -> chunk blocked
backfill incomplete -> all raw cleanup blocked
late insert waiting on retention -> subsequently committed row remains pending
Metric chunk overlaps pending raw event -> Metric chunk blocked
```

- [ ] Ensure raw/work cleanup is atomic, completed batch receipts remain available,
  and malformed rejection retention is a separate policy with no silent auto-delete.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_backfill.py -n 0 -v`.
- [ ] Run `uv run --package uns_historian pytest 04_uns_historian/test/test_archive_retention.py -n 0 -v`.

## Task 9: Move operational dashboards to committed historian refresh

**Files**
- Modify: `07_uns_graphql/src/uns_graphql/backend/event_stream.py`, `subscriptions/kafka.py`, `graphql_config.py`, and actual app lifespan/schema registration callers.
- Modify: `07_uns_graphql/src/uns_graphql/backend/historian.py` only for snapshot protection/query integration.
- Create: `07_uns_graphql/test/test_historian_first_api.py`.
- Create: `11_frontend/src/hooks/useHistorianRefresh.ts`, `useHistorianRefresh.test.tsx`.
- Modify: `11_frontend/src/services/graphql/client.ts` and existing operational/condition-monitoring query hooks found from its callers.

- [ ] Trace current schema registration and consumer lifecycle callers before
  editing. List external subscription users in the cutover report. Remove Kafka
  startup dependencies and the Kafka-specific subscription in this coordinated API
  change; preserve historian query signatures wherever possible.
- [ ] Add API tests: app starts without Kafka; authorized topics return committed
  data; cross-scope requests fail; uncommitted raw rows are not visible; late commits
  appear on a subsequent query of the same window. Preserve topic-remap snapshot.
- [ ] Implement refresh lifecycle with these rules:

```text
on mount/filter change -> cancel obsolete request; fetch current selected window
on completion -> schedule next refresh (2s operational / 5s condition monitoring)
on hidden page -> cancel timer; keep last data with freshness indicators
on visibility restore -> fetch immediately
on failure -> retain last data, show stale/error, bounded retry delay
on unmount -> cancel timer and in-flight request
```

- [ ] Test with fake timers: no overlapping polls, no obsolete response overriding
  new filters, hidden-page pause, retry, and late-event inclusion on full-window
  refresh. Do not introduce an event-time append cursor.
- [ ] Remove synthetic Kafka health from `11_frontend/src/services/graphql/client.ts`
  and `11_frontend/src/types/uns.ts`; update affected system/landing descriptions
  and tests to describe actual ingestion/archive health.
- [ ] Run `uv run --package uns_graphql pytest 07_uns_graphql/test/test_historian_first_api.py -n 0 -v`.
- [ ] In `11_frontend`, run `npm run test:run -- src/hooks/useHistorianRefresh.test.tsx`
  and `npm run lint`. Run affected existing condition-monitoring/dashboard tests.

## Task 10: Archive loop configuration, health, and metrics

**Files**
- Modify: `14_uns_datalake/src/uns_datalake/{main,config,health_check,metrics}.py`.
- Modify: `04_uns_historian/src/uns_historian/{historian_config,health_check,prometheus_metrics}.py`.
- Modify: `conf/settings.yaml` and existing files under `08_uns_observability/prometheus/`.
- Create: `14_uns_datalake/test/test_historian_source_config.py`.

- [ ] Test typed positive limits, database-source selection, idle health, archive
  lock contention, SQL/MinIO failure separation, and absent credentials logging.
- [ ] Wire the archive loop at one-second polling; partial flush age 60 seconds,
  10,000 rows/16 MiB envelope cap, 64 MiB staged artifact cap, bounded retries and
  timeouts. Source is the historian, not an additional source toggle supporting
  two simultaneous writers. Keep retention disabled by default.
- [ ] Expose the metrics in spec section 11 and update alert queries away from
  Kafka lag. Archive pending age must use the oldest unresolved work, not merely
  last successful upload. No-data health must not fire lag alerts.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_historian_source_config.py -n 0 -v`.
  Verify scrape configuration and health commands against the development stack.

## Task 11: Packaging and coordinated default-stack cutover

**Files**
- Modify: `04_uns_historian/pyproject.toml`, `14_uns_datalake/pyproject.toml`, `07_uns_graphql/pyproject.toml`, root `pyproject.toml`, `uv.lock`.
- Modify: `docker-compose.yml`, actual module Docker startup scripts, and relevant READMEs.
- Create: `14_uns_datalake/test/test_historian_first_deployment.py`.
- Modify: existing deployment tests in `06_uns_kafka/test/test_pipeline_deployment.py` only where they assert default-stack behavior.
- Update: `docs/operations/historian-first-cutover.md`.

- [ ] Add deployment contract tests: default historian command uses `mqtt_ingest`,
  datalake depends on SQL/MinIO, GraphQL can start without Kafka, persistent MQTT
  broker volume/session config exists, and no unconditional retention job returns.
- [ ] Point `uns_historian` to the new MQTT entry point. Ensure `uns_mqtt` is an
  actual runtime dependency. Point `uns_datalake` to the new archive loop and add
  `uns_model`; remove its `uns_kafka_mapper` and `confluent-kafka` runtime dependencies.
- [ ] Remove Kafka imports/dependencies from active historian/GraphQL paths; remove
  Kafka services from default Compose. Keep the old stack instructions/code for
  explicit rollback during qualification, without enabling parallel writers.
- [ ] Regenerate the lockfile using existing uv workflow. Verify a clean module
  install does not depend on transitive imports from an accidentally installed
  Kafka mapper. Inspect service images, environment mounts, health and startup order.
- [ ] Follow spec section 12: backup, quiesce, drain recorded offsets, stop old
  writers, migrate/backfill, establish new subscription, resume, reconcile. If
  current environment is not authorized for cutover, provide the tested runbook
  and run the same procedure in the isolated fixture stack.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_historian_first_deployment.py -n 0 -v`.
  Run `docker compose config --quiet`; expected success with no missing dependencies.

## Task 12: End-to-end failure qualification and documentation

**Files**
- Complete: `14_uns_datalake/test/test_historian_first_pipeline.py`.
- Update: `docs/operations/historian-first-cutover.md`, module READMEs, `CONTEXT.md` only where the storage authority wording needs correction.
- Create: `docs/adr/0012-historian-first-telemetry-and-archive.md` (advance the
  number if occupied), explicitly superseding the Kafka transport/storage decisions
  in `docs/adr/0011-canonical-historic-event-pipeline.md` while preserving the envelope.
- Mark superseded sections in the older lake/scalability specs and plans, linking this design.

- [ ] Execute the acceptance matrix; record actual results, not just test names:

| Scenario | Required evidence |
| --- | --- |
| Known IDs through pipeline | Raw IDs, Metrics, work membership, manifest counts, Parquet IDs/content agree. |
| SQL rollback and uncertain commit | No early ACK; frozen retry produces one source-identified event. |
| Reverse transaction commits and late event | Neither work item is skipped. |
| Kill after claim/stage/data/manifest | Same batch/keys/bytes recover; no duplicate committed membership. |
| MinIO stopped and restarted | Dashboards remain queryable; pending age grows and then drains. |
| SQL stopped and restarted | MQTT backpressure occurs; QoS 1 recovery matches session contract. |
| Broker killed/restarted | Persisted-session recovery measured; QoS 0 limitations reported. |
| Retention raced with ingestion | Pending raw and corresponding Metrics survive. |
| Topic remap after acceptance | Query-facing topic changes; archive snapshot/content stays original. |
| Kafka unavailable for entire run | Operational/condition-monitoring API and archive continue. |

- [ ] Run targeted module suites after all task tests pass:

```powershell
uv run --package uns_historian pytest 04_uns_historian/test -n 0
uv run --package uns_datalake pytest 14_uns_datalake/test -n 0
uv run --package uns_model pytest 09_uns_model/test -n 0
uv run --package uns_graphql pytest 07_uns_graphql/test -n 0
```

Run each independently and inspect failures. From `11_frontend`, run
`npm run test:run` and `npm run build` after affected UI tests pass. Run the existing
OEE historian-facing tests to verify that changing transport did not change their
query/aggregate contracts. Do not claim integration success from unit-only tests.

- [ ] Measure throughput, Metric fanout, commit p95, dashboard freshness, exporter
  catch-up rate, DB/WAL/worklist growth, and process RSS at the representative load.
  Record supported database/MinIO outage durations. If catch-up cannot exceed live
  traffic or dashboard queries regress, tune batching/indexes before cutover approval.
- [ ] Document rollback before/after new accepted writes, manifest-only reader
  contract, legacy dataset overlap, legacy snapshot fidelity, retained-data
  deduplication scope, and disabled-until-qualified retention.
- [ ] Review the final diff, run `graphify update .` as required by repository
  instructions, and report changes, evidence, and any qualification gaps.

## Spec-to-plan coverage

| Specification | Tasks |
| --- | --- |
| Decision, scope, baseline, ownership | 1, 11, 12 |
| Event fidelity and source identity | 2, 3, 4, 7, 8 |
| MQTT acceptance and bounded lifecycle | 2, 4, 5 |
| Transactional worklist and reverse commits | 3, 4, 6 |
| Parquet staging/manifests and recovery | 6, 7, 12 |
| Dashboard/condition-monitoring migration | 9, 11, 12 |
| Retention, backfill, remap invariants | 3, 4, 8, 9 |
| Configuration and observability | 5, 10, 11 |
| Cutover, rollback, acceptance | 1, 11, 12 |

## Completion definition

Implementation is complete when the default deployment, with Kafka unavailable,
passes all applicable spec acceptance criteria; the failure/capacity report states
measured limits; existing data is accounted for; and operators have a tested
backfill, archive-reader, retention, and rollback procedure. Passing static tests
alone is not sufficient to establish MQTT outage durability or archive completeness.
