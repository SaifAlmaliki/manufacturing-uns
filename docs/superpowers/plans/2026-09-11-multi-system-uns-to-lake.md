# Multi-system UNS-to-lake Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`
> to implement this plan task-by-task. Use `superpowers:subagent-driven-development`
> only when the user explicitly selects delegation. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deliver machine and business-system publications from the centralized
UNS to raw lake storage by source application, site, payload schema, and version,
preserving original payloads and provenance.

**Architecture:** Extend the existing MQTT → canonical Kafka stream → independent
lake mapper. Versioned envelopes freeze routing metadata; bounded route groups
produce verified immutable Parquet objects before consumer checkpoints advance.
Delivery is at least once; the historian is an independent consumer.

**Tech Stack:** Existing Python 3.14 workspace, MQTT wrapper/Paho, confluent-kafka,
PyArrow, S3/MinIO via boto3, ADLS adapter, pytest, Docker Compose, Prometheus.

---

Specification: [Approved design](../specs/2026-09-11-multi-system-uns-to-lake-design.md).
Status: Ready for later implementation; this document does not execute a cutover.
Replaces: [Historian-first plan](2026-09-09-historian-first.md).

## Scope and execution rules

- Deliver raw data only. No transformations, schema inference, business-payload
  validation engine, curated tables, Databricks jobs, vendor connector catalog,
  business workflows, or asset/UI redesign.
- Retain Kafka and the existing canonical topic name `uns.historic-events` for
  compatibility. Do not introduce historian archive SQL tables, lake manifests,
  an exactly-once ledger, a new broker, or dashboard polling changes.
- Inspect `AGENTS.md`, current skills, current diffs, and installed dependencies
  before execution. Some repository skill paths were absent during drafting;
  resolve available guidance instead of claiming to have loaded missing files.
- Apply repository TDD guidance. Each test contract below names new behavior;
  implement the fixture/helper in the same task when introduced. Missing services
  are not a passing integration test. No production service fault injection.
- All Python commands below run from the repository root with `-n 0`. Steps are
  ordered; reader compatibility must deploy before new envelopes are enabled.
- Refresh installed-version API documentation before changing MQTT delivery,
  Kafka assignment/polling, S3 conditional writes, ADLS rename, or Arrow encoding.
  Record exact supported backend behavior in qualification evidence.
- Do not commit, reset offsets, delete objects/volumes, or cut over a running
  deployment without an explicit user request. Tasks are potential commit
  boundaries, not authorization to commit. Preserve existing user changes.

## File responsibilities

| Responsibility | Existing files | Focused new files |
| --- | --- | --- |
| Versioned envelope | `00_uns_config/src/uns_config/events.py`, `uns_ingest.py` | `event_compatibility.py` in the same package |
| Registration and publisher contract | `06_uns_kafka/src/uns_kafka/ingest.py`, `uns_kafka_config.py`, `uns_kafka_listener.py` | `00_uns_config/src/uns_config/publications.py`, `publication_routes.py` |
| Consumer compatibility | `04_uns_historian/src/uns_historian/kafka_consumer.py`, `07_uns_graphql/src/uns_graphql/backend/event_stream.py` | Focused compatibility tests in each module |
| Lake routing and legacy adaptation | `14_uns_datalake/src/uns_datalake/config.py`, `batch.py` | `14_uns_datalake/src/uns_datalake/routing.py` |
| Raw lake format | `14_uns_datalake/src/uns_datalake/parquet.py` | Tests in existing lake test directory |
| Immutable object delivery | `14_uns_datalake/src/uns_datalake/stores.py` | `14_uns_datalake/src/uns_datalake/publication.py` |
| Completion and assignment | `14_uns_datalake/src/uns_datalake/mapper.py`, `checkpoint.py` | `14_uns_datalake/src/uns_datalake/replay.py` |
| Operations | `conf/settings.yaml`, lake metrics/health/main, existing module READMEs | `docs/operations/uns-to-lake-delivery.md`, `docs/benchmarks/uns-to-lake-delivery.md` |

No file named in the new-file column exists merely because this plan names it.
Re-read existing files before applying changes; avoid line-number-dependent patches.

## Task 1: Capture baseline and four-domain acceptance fixture

**Files**
- Read: `06_uns_kafka/src/uns_kafka/pipeline_fixture.py` and `06_uns_kafka/test/test_pipeline_acceptance.py`.
- Modify: `14_uns_datalake/test/conftest.py`.
- Create: `14_uns_datalake/test/test_multi_system_pipeline.py`.
- Create: `docs/operations/uns-to-lake-delivery.md`.

- [ ] Run `git status --short`, `git diff --stat`, and `git log --oneline -10`
  independently. Record broker/backend images, topic retention/compaction settings,
  consumer group positions, current routes, and all `decode_event` callers.
- [ ] Use the graph query first, then confirm current source callers. The inspected
  active canonical readers are lake, historian, and GraphQL. Include any new
  readers found at execution before enabling v2.
- [ ] Extend the isolated pipeline fixture with `publish_cases`,
  `wait_for_lake_records`, and `read_lake_records`. `publish_cases` returns expected
  source IDs mapped to body bytes and route tuples. Waits have a timeout and report
  pending IDs, offsets, object keys, and DLQ reasons. Reads expose physical rows,
  including duplicates, without hiding them through set conversion.
- [ ] Add this acceptance test using an explicitly selected `pipeline` integration
  fixture; the four cases are machine temperature, MES production order, LIMS lab
  result, and logistics inventory movement:

```python
@pytest.mark.integrationtest
def test_four_domains_reach_lake_with_historian_stopped(pipeline):
    pipeline.stop_historian()
    expected = pipeline.publish_cases()
    pipeline.wait_for_lake_records(expected, timeout=120)
    rows = pipeline.read_lake_records()
    for event_id, case in expected.items():
        matches = [row for row in rows if row["event_id"] == event_id]
        assert matches
        assert all(row["original_payload"] == case.body for row in matches)
        assert all(row["route"] == case.route for row in matches)
    assert not pipeline.historian_running
```

The fixture's `stop_historian` and `historian_running` operate only on its isolated
stack. Acceptance cases use the explicit publication wrapper with boot/sequence
source identity so expected IDs are known; separate raw-mode tests cover publishers
without source identity. No machine
asset is created for any business-system case. `row["route"]` is a reader helper
tuple `(application, site, schema, version)` derived from stored metadata and
checked against the object path, not an extra Parquet business column.

- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_multi_system_pipeline.py -n 0 -v`.
  Expected initial failure: missing v2/routing behavior once the fixture stack is
  available. A missing service is a reported prerequisite failure.
- [ ] Write the runbook headings for registration, raw contract, reader-first
  deployment, replay/duplicates, rollback, and backend qualification; fill each in
  its owning task. Record the existing v1 lake prefix as a separate legacy dataset.

## Task 2: Versioned, byte-preserving event envelope

**Files**
- Modify: `00_uns_config/src/uns_config/events.py`, `00_uns_config/src/uns_config/uns_ingest.py`.
- Create: `00_uns_config/test/test_events_v2.py`.
- Reuse tests: `00_uns_config/test/test_events.py`.

- [ ] Add a `v2_event` fixture constructing `HistoricEventEnvelope` with existing
  identity fields plus the fields below. Add round-trip tests for raw JSON objects,
  arrays, strings, whitespace, a string timestamp, binary bytes, and empty bytes:

```python
@pytest.mark.parametrize("body", [
    b'{ "timestamp": "2026-09-11T09:00:00Z", "result": 4.2 }',
    b'[1, {"a": true}]', b'"released"', b'\x00\xff', b'',
])
def test_v2_preserves_body_without_timestamp_normalization(v2_event, body):
    event = v2_event(original_payload=body)
    decoded = decode_event(encode_event(event))
    assert decoded.original_payload == body
    assert decoded.payload_schema_version == "1"
    assert decoded.schema_version == 2
```

- [ ] Run `uv run --package uns_config pytest 00_uns_config/test/test_events_v2.py -n 0 -v`.
  Expected: unsupported version/new field failure, before implementation.
- [ ] Extend the existing dataclass with defaulted optional v2-only fields, preserving
  old constructor compatibility; validate their presence for v2. Keep existing
  `schema_version` as envelope version, and add categories `business_event` and
  `state_snapshot` to both current event-kind definitions:

```python
# Add after the existing non-default dataclass fields.
source_application: str | None = None
payload_schema_id: str | None = None
payload_schema_version: str | None = None
content_type: str | None = None
original_payload: bytes | None = None
archive_eligible: bool | None = None
```

V2 requires all six fields; `b""` is valid and differs from `None`. V1 retains its
existing decoder, JSON normalization, wire shape, and content hash. V2 uses base64
wire field `original_payload_base64`, validates base64 strictly, and never calls
`normalize_payload_timestamps` on its body. Keep `payload` as an optional-use
dictionary compatibility representation in the existing dataclass, `{}` for
business messages; it is never the authority for the raw body. V2 ingest creates
this compatibility dictionary only for established telemetry/Sparkplug consumers.

- [ ] Branch serialization, validation, and hashing explicitly by envelope version:

```text
decode <= 1 MiB JSON object -> dispatch schema_version 1 or 2 -> validate
v1 -> existing normalization and hash, byte-for-byte wire compatibility
v2 -> decode body bytes; validate metadata; preserve body without JSON inspection
encode -> serialize once -> enforce complete 1 MiB envelope limit
hash v2 -> all immutable source/event/routing/body fields (exclude received_at)
unknown version -> EnvelopeError("unsupported_schema")
```

Retain existing identity derivation: site/source/boot/sequence yields source ID;
absence yields a fresh ingress ID. Do not deduplicate equal bodies. Retain event
partition keys; routing does not require one Kafka topic per application.

- [ ] Add failures for invalid field types, unsafe route IDs, unknown kinds, partial
  source identities, invalid base64, and complete-envelope oversize including
  base64/compatibility-payload overhead. Test unchanged v1 serialization and hashes.
- [ ] Run `uv run --package uns_config pytest 00_uns_config/test/test_events.py 00_uns_config/test/test_events_v2.py -n 0 -v`.
  Expected: both versions pass, v1 legacy timestamp behavior is unchanged.

## Task 3: Registered routes and explicit publisher wire contract

**Files**
- Create: `00_uns_config/src/uns_config/publication_routes.py`, `publications.py`.
- Create: `00_uns_config/test/test_publication_routes.py`, `test_publications.py`.
- Modify: `06_uns_kafka/src/uns_kafka/uns_kafka_config.py`, `conf/settings.yaml`.
- Modify: `docs/operations/uns-to-lake-delivery.md`.

- [ ] Define immutable `PublicationRoute` and `PublisherMessage` contracts:

```text
PublicationRoute:
  topic_filter, source_id, source_application, site_id,
  wire_format (raw | uns-publication-v1), allowed_schema_pairs,
  default_schema_pair (required for raw), content_type, event_kind,
  archive_eligible
PublisherMessage:
  source_application, site_id, payload_schema_id, payload_schema_version,
  content_type, original_payload, occurred_at?, source_boot_id?, source_sequence?
```

`resolve_route(topic, routes)` returns exactly one route or `EnvelopeError`.
`decode_publication(wire)` decodes the explicit publication wrapper below.
`validate_routes(routes)` runs before a client subscribes. These names belong to
the two new pure modules; they do not import broker/database/cloud clients.

- [ ] Add tests: duplicate/overlapping filters, valid disjoint filters, MQTT `+`
  and terminal `#`, invalid embedded wildcards, schema pair mismatch, forged
  application/site, valid shared scope, unsupported wrapper version, and literal
  business JSON that resembles an envelope but is configured as `raw`.

```python
def test_overlapping_filters_fail_startup(route):
    with pytest.raises(EnvelopeError, match="ambiguous_route"):
        validate_routes([
            route(topic_filter="E/S/+/results"),
            route(topic_filter="E/S/LIMS/#"),
        ])
```

The `route` fixture supplies a fully valid default registration; overrides replace
named fields. Overlap is determined symbolically, not only against observed topics:
walk filter segments pairwise, literals conflict only when unequal, `+` matches
one segment, terminal `#` matches the remaining suffix including zero segments.
Validate MQTT's `$` root wildcard exception. Conservatively reject all overlaps,
even equivalent ownership; no runtime priority rule is needed.

- [ ] Run `uv run --package uns_config pytest 00_uns_config/test/test_publication_routes.py 00_uns_config/test/test_publications.py -n 0 -v`.
  Expected first failure: missing pure contract modules.
- [ ] Implement route validation with ASCII `[A-Za-z0-9_-]{1,128}` for application,
  site, schema, and version; preserve case and reject invalid values rather than
  sanitizing/collapsing them. `source_id` keeps existing semantics and is not a path
  segment. Require a finite allowed schema set and a registered raw default.
- [ ] Implement the wrapper as explicit JSON metadata plus a base64 body:

```json
{
  "publication_version": 1,
  "source_application": "lims",
  "site_id": "plant-01",
  "payload_schema_id": "lab-result",
  "payload_schema_version": "1",
  "content_type": "application/json",
  "original_payload_base64": "eyJyZXN1bHQiOjQuMn0=",
  "occurred_at": "2026-09-11T09:00:00Z",
  "source_boot_id": "lims-session-1",
  "source_sequence": 42
}
```

The route selects `wire_format`; never auto-detect a wrapper from business keys.
Publisher identity claims are checked against the selected route, not trusted.
`source_id`, category, and eligibility come from registration. Validate RFC3339
time with an offset; absent time uses ingress time with ingress quality. Do not
extract timestamps from business payloads. A wrapper boot/sequence pair enables
existing source identity; both must be present together. A raw business publisher
without separately supplied identity receives ingress identity.

- [ ] Add config examples for raw machine data, wrapped LIMS, raw MES, and logistics.
  Keep v2 writing disabled until Task 4 compatibility and Task 11 deployment.
  Unknown routes enter durable rejection rather than default application/site.
- [ ] Run the Task 3 command again. Document broker ACL ownership of each filter,
  one-route-per-publication, configured enterprise/shared scope, and the distinction
  between a payload schema ID and a schema-validation engine.

## Task 4: Upgrade readers before enabling v2 writers

**Files**
- Create: `00_uns_config/src/uns_config/event_compatibility.py`.
- Modify: `04_uns_historian/src/uns_historian/kafka_consumer.py`.
- Modify: `07_uns_graphql/src/uns_graphql/backend/event_stream.py`.
- Create: `04_uns_historian/test/test_event_v2_compatibility.py`.
- Create: `07_uns_graphql/test/backend/test_event_v2_compatibility.py`.

- [ ] Add tests with interleaved v1 telemetry, v2 business event, and v2 telemetry.
  The historian must not insert business Metrics, but must persist both telemetry
  forms and advance its checkpoint only after earlier SQL work is resolved.
  Include a SQL failure before a business event: skipping it must not skip the
  failed telemetry offset. GraphQL's existing telemetry broadcast must ignore
  business records and retain existing topic authorization for telemetry.
- [ ] Add `as_legacy_telemetry(event)` in the pure compatibility module. It returns
  the original v1 event, a v1-compatible copy for supported v2 telemetry/Sparkplug/
  lifecycle/command categories, or `None` for the two new business categories:

```python
def test_business_event_is_not_metric_input(v2_business_event):
    assert as_legacy_telemetry(v2_business_event) is None
```

The copied v1 view preserves event ID, source fields, timestamps, topic, and current
telemetry payload semantics. It does not replace/mutate the canonical v2 bytes sent
to the lake. Source normalization for telemetry occurs only in this compatibility
path. Invalid supported-category payloads are explicit consumer failures, not
silently treated as successfully ignored business data.

- [ ] Run `uv run --package uns_historian pytest 04_uns_historian/test/test_event_v2_compatibility.py -n 0 -v` and
  `uv run --package uns_graphql pytest 07_uns_graphql/test/backend/test_event_v2_compatibility.py -n 0 -v` independently.
  Expected first failure: unsupported v2/incorrect category handling.
- [ ] Insert compatibility dispatch before historian `ConsumedEvent` creation and
  GraphQL `DispatchedEvent` serialization. Historian ignored records use an ordered
  consumed-record barrier: flush earlier SQL work before committing an ignored
  record's next offset; on SQL failure or ownership loss, leave both uncommitted.
  GraphQL retains its existing live-only position semantics and does not add a
  durable consumer workflow.
- [ ] Run the Task 4 tests plus `uv run --package uns_historian pytest 04_uns_historian/test/test_batch.py 04_uns_historian/test/test_batch_persistence.py -n 0 -v` and
  `uv run --package uns_graphql pytest 07_uns_graphql/test/backend/test_event_stream.py 07_uns_graphql/test/subscriptions/test_kafka.py -n 0 -v`.
  Check every additional reader discovered in Task 1 before marking compatibility ready.

## Task 5: Wire registered publications into durable ingestion

**Files**
- Modify: `06_uns_kafka/src/uns_kafka/ingest.py`, `uns_kafka_listener.py`, `prometheus_metrics.py`.
- Reuse: `06_uns_kafka/src/uns_kafka/rejections.py`.
- Create: `06_uns_kafka/test/test_publication_ingest.py`.
- Read/reuse: `02_mqtt-cluster/src/uns_mqtt/mqtt_listener.py` delivery options.

- [ ] Add controllable Kafka delivery callbacks and an MQTT ACK spy to test this
  sequence, using the existing `IngestionOwner` as the lifecycle owner:

```text
valid wrapped LIMS publication -> canonical v2 bytes queued -> ACK absent
successful Kafka delivery callback -> matching-generation MQTT token ACKed
failed callback or old connection generation -> no ACK; recovery requested
unknown route / forged metadata -> DLQ queued -> ACK only after DLQ success
raw array/string/binary business body -> accepted without get_payload_as_dict
equal bodies without source identity -> two distinct ingress event IDs
```

- [ ] Run `uv run --package uns_kafka_mapper pytest 06_uns_kafka/test/test_publication_ingest.py -n 0 -v`.
  Expected first failure: unregistered v2 ingest path or dictionary-only parsing.
- [ ] Resolve registration before payload decoding. Replace the current universal
  dictionary parser with the selected raw/wrapper branch; retain the established
  telemetry parser only for compatibility data. Build a v2 envelope from immutable
  body bytes and authorized metadata; freeze `received_at` and identity once per
  admitted receipt. Enforce final encoded size before reserving pending capacity.
- [ ] Preserve the current delivery callback/connection-generation controls. Move
  `INGEST_ACCEPTED` accounting from `on_message` admission to successful canonical
  log delivery; distinguish received/admitted/rejected/best-effort QoS 0 counts.
  Do not log original bodies in failure messages.
- [ ] For intentionally excluded observability/retained bootstrap traffic, release
  MQTT capacity without publishing a new historic event. Unknown ownership is a
  durable rejection, not the existing `_topic_allowed` silent return. Ensure ACK
  registration/cleanup cannot leak excluded packet references across reconnects.
- [ ] Test on the real broker: retained bootstrap is suppressed, a fresh publication
  with retain enabled is delivered once to an existing subscription, persistent
  QoS 1 session recovery respects generation checks, and QoS 0 loss is reported.
  Reuse existing retain-as-published/session options; verify actual broker flags.
- [ ] Run Task 5 tests and `uv run --package uns_kafka_mapper pytest 06_uns_kafka/test -n 0`.
  Keep v2 disabled in the default running deployment until Task 11.

## Task 6: Frozen lake routing, legacy provenance, and complete Parquet rows

**Files**
- Create: `14_uns_datalake/src/uns_datalake/routing.py`.
- Modify: `14_uns_datalake/src/uns_datalake/parquet.py`, `config.py`.
- Create: `14_uns_datalake/test/test_routing.py`, `test_parquet_v2.py`.
- Modify: `14_uns_datalake/test/conftest.py`.

- [ ] Define the following pure types/functions in `routing.py`:

```text
LakeRoute(application, site, schema, version, ingestion_date)  # frozen
ResolvedLakeEvent(envelope, route, original_payload, payload_fidelity,
                  legacy_route_revision)
resolve_lake_event(envelope, legacy_map) -> ResolvedLakeEvent
lake_object_path(route, object_id) -> str
```

`LakeRecord` in Task 7 carries the resolved event plus transport coordinates and
original canonical envelope bytes. V2 resolution reads frozen envelope metadata,
never current publisher registrations. V1 requires `legacy_map` with immutable
revision/content digest and topic/source/site mappings. Mount/version this map
with deployment configuration; refuse digest mismatch. No automated edits during
replay. `payload_fidelity` is `original` when proven raw bytes exist, otherwise
`legacy_normalized`; normalized legacy JSON remains in a separate compatibility
column and `original_payload` is NULL, not reconstructed bytes labeled original.

- [ ] Add tests for this deterministic path and route immutability:

```python
def test_path_uses_frozen_received_date(resolved_lims_event):
    assert lake_object_path(resolved_lims_event.route, "batch1") == (
        "raw/v2/application=lims/site=plant-01/schema=lab-result/"
        "version=1/ingestion_date=2026-09-11/batch1.parquet"
    )
```

The fixture uses `received_at` on September 11 and event time on September 9.
Add cases for UTC date rollover, changed live registration, unknown v1 route,
legacy Sparkplug original bytes, two sites, two applications, and two schema versions.

- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_routing.py 14_uns_datalake/test/test_parquet_v2.py -n 0 -v`.
  Expected first failure: missing route resolution/full-fidelity format.
- [ ] Extend the encoder to `records_to_parquet(records, *, batch_id)` where records
  are lake records, not envelopes alone. Use an explicit Arrow schema; add all
  existing canonical fields, v2 metadata, raw binary body, source boot/sequence,
  timestamp quality, legacy fidelity/revision, and Kafka topic/partition/offset.
  Keep `payload` JSON solely as the labeled compatibility representation and include
  `canonical_envelope` binary bytes for exact accepted-envelope auditing.
  Every row receives the same supplied batch ID. No business scalar columns.
  Introduce the `LakeRecord.resolved` field here as the minimum encoder input
  change; Task 7 completes batching/checkpoint integration. Keep an `envelope`
  read-only property returning `resolved.envelope` for existing caller transitions.
- [ ] Assert exact bytes for all Task 2 bodies, NULL legacy raw bodies, full source
  provenance, timezone-aware microseconds, transport coordinates, and batch ID after
  Parquet round trip. Compare bytes directly; do not validate fidelity through
  parsed-JSON equality alone. Update callers/tests to the new encoder signature.
- [ ] Run Task 6 tests plus `uv run --package uns_datalake pytest 14_uns_datalake/test/test_parquet.py -n 0 -v`.

## Task 7: Bounded route groups and ordered consumed-record checkpoints

**Files**
- Modify: `14_uns_datalake/src/uns_datalake/batch.py`, `checkpoint.py`, `config.py`.
- Modify: `14_uns_datalake/test/test_batch.py`, `test_checkpoint.py`, `test_config.py`.
- Create: `14_uns_datalake/test/test_multi_route_batch.py`.

- [ ] Replace integer-only buffer keys with `(kafka_topic, partition)`. Use the
  Task 6 `LakeRecord` carrying `resolved: ResolvedLakeEvent` while preserving
  `envelope_bytes` and its transport coordinates. Use one bounded partition flush
  at a time, split into route groups, rather than independent unbounded route workers.
- [ ] Add `ConsumedPrefix` in `checkpoint.py` with `observe(offset)`,
  `resolve(offset)`, `next_offset()`, and `discard_committed(next_offset)`:

```python
def test_numeric_gap_does_not_block_but_unresolved_record_does():
    prefix = ConsumedPrefix()
    for offset in (10, 12, 15):
        prefix.observe(offset)
    prefix.resolve(15)
    assert prefix.next_offset() is None
    prefix.resolve(10)
    assert prefix.next_offset() == 11
    prefix.resolve(12)
    assert prefix.next_offset() == 16
```

`observe` appends strictly increasing offsets for that assignment generation;
duplicate/out-of-order observation is a state error. `resolve` marks an observed
record; unknown offsets are errors. `next_offset` walks the observed order until
the first unresolved item and returns the last resolved offset plus one. It does
not fill numerical gaps. Keep entries until broker commit success. Use the same
ledger for archive-eligible records, explicit exclusions, and durable rejections.

- [ ] Add pressure tests where the next record introduces group 65, exceeds the
  global byte budget, or crosses the batch row bound. Existing defaults remain
  10,000 rows, 8 MiB batch input, 32 MiB worker input, 60-second age, 1 MiB record;
  add `max_active_route_groups=64` and `max_encoded_bytes=16 MiB`. Validate all
  limits as positive and reject inconsistent record/batch/worker limits.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_multi_route_batch.py 14_uns_datalake/test/test_checkpoint.py 14_uns_datalake/test/test_config.py -n 0 -v`.
  Expected initial failures: current numeric-contiguity helper and missing route bounds.
- [ ] Implement admission before allocation: reserve wire bytes/global group slot,
  or request pressure flush without losing the held record. At most one polled
  record may await admission and its bytes count toward a reserved record budget.
  Admission includes paused partitions and unresolved rejected records in bounds.
- [ ] Freeze membership and full UUID object IDs for route groups. Encode/publish
  one group artifact at a time; do not materialize every group's Parquet at once.
  Use a capped output sink or fail encoding at the artifact bound, split the group
  deterministically before publication, and retry smaller parts. If a single
  admissible event cannot encode within the artifact limit, durable-reject it with
  `encoded_oversize`; do not loop indefinitely. Account for Arrow scratch memory
  in the measured RSS budget; serialized-byte caps alone are not an RSS guarantee.
- [ ] Remove uses of the old numerical `compute_next_offset` from lake completion.
  Keep group membership metadata after freeing a verified artifact until the full
  partition flush is resolved; all registered exclusions/DLQ results join its ledger.
- [ ] Run the Task 7 tests plus `uv run --package uns_datalake pytest 14_uns_datalake/test/test_batch.py -n 0 -v`.

## Task 8: Verified immutable publication for each backend

**Files**
- Create: `14_uns_datalake/src/uns_datalake/publication.py`.
- Modify: `14_uns_datalake/src/uns_datalake/stores.py`.
- Create: `14_uns_datalake/test/test_publication.py`.
- Modify: `14_uns_datalake/test/test_stores.py`.

- [ ] Define `FrozenObject(key, data, sha256, row_count)` in `publication.py` and
  `IntegrityError`. Replace active `put` calls with this store contract:

```text
publish_exact(key: str, data: bytes, sha256: str) -> None
verify_exact(key: str, sha256: str, byte_length: int) -> None
```

`publish_exact` creates a complete final object or verifies an existing identical
one. It never overwrites mismatching content. `verify_exact` checks actual content
length and hash; do not mistake an ETag or self-declared metadata for content hash.
Use streamed readback hashing as the baseline portable verification mechanism.

- [ ] Add contract tests against `FakeObjectStore`, S3 mocks, and ADLS mocks:

```python
def test_existing_mismatch_is_not_overwritten(store):
    store.publish_exact("x.parquet", b"old", sha256(b"old").hexdigest())
    with pytest.raises(IntegrityError):
        store.publish_exact("x.parquet", b"new", sha256(b"new").hexdigest())
    store.verify_exact("x.parquet", sha256(b"old").hexdigest(), 3)
```

Here `sha256` is imported from `hashlib`, and `store` is parametrized by adapter.
Also test identical retries, truncated readback, ambiguous successful write followed
by timeout, conditional conflict, and permission/auth failure classification.

- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_publication.py 14_uns_datalake/test/test_stores.py -n 0 -v`.
  Expected initial failure: missing immutable publication contract.
- [ ] Implement S3 conditional create using the installed client's supported
  request precondition. On exists/uncertain result, read/verify exact content. Do
  not implement check-then-unconditional-put. Qualify behavior against actual MinIO.
- [ ] Implement ADLS upload to a unique non-Parquet staging key outside `raw/v2`,
  flush/verify complete bytes, then atomically finalize without replacing a final
  object. On destination conflict verify final content. If installed API/backend
  cannot ensure no-overwrite atomic finalization, fail ADLS readiness and record
  qualification blocked; do not downgrade silently to `overwrite=True`.
- [ ] Keep staging cleanup manual/documented; deleting abandoned staging files is
  not permission to delete final data. Final readers list only complete `.parquet`
  files under `raw/v2`; this design uses no commit manifest.
- [ ] Repeat contract tests against MinIO and, when credentials are available,
  isolated live ADLS. Record each backend separately in the benchmark report.

## Task 9: Integrate multi-route lifecycle, DLQ confirmation, and ownership fencing

**Files**
- Modify: `14_uns_datalake/src/uns_datalake/mapper.py`, `main.py`.
- Modify: `14_uns_datalake/test/test_mapper.py`.
- Create: `14_uns_datalake/test/test_multi_route_mapper.py`.

- [ ] Add controllable consumer/store/DLQ fakes with explicit ownership generations,
  delayed object completion, commit result errors, and callback-triggered revocation.
  Keep state in one mapper owner. Test the following exact order:

```text
observe offsets 10 (LIMS), 12 (MES), 15 (LIMS)
freeze partition -> route groups LIMS[10,15] and MES[12]
verify LIMS -> resolve 10,15 -> MES upload fails -> no full-flush commit
retry same MES bytes/key -> verify -> resolve 12 -> commit next offset 16
commit failure -> keep resolved ledger -> retry commit without re-encoding
ownership revoked at any stage -> no further commit from old generation
```

The implementation deliberately commits only after its whole frozen partition
flush resolves. This is a conservative use of `ConsumedPrefix`, not permission
to commit each successful route's maximum offset independently.

- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_multi_route_mapper.py -n 0 -v`.
  Expected initial failure: current single-object frozen flush.
- [ ] Implement the explicit loop states:

```text
COLLECT -> freeze bounded partition membership and pause admission
ENCODE -> prepare one immutable route artifact
PUBLISH -> publish_exact then verify_exact; retain exact bytes until verified
RESOLVE -> mark group members; release artifact; move to next group
COMMIT -> generation check; commit fully resolved consumed prefix
RELEASE -> discard committed ledger/membership and resume admission
REVOKE -> invalidate generation, cancel/discard unresolved local work, replay later
```

Offload bounded object I/O to one worker so the consumer-owner thread continues
polling while partitions are paused. Only the owner polls/commits Kafka. Completion
messages include generation and object ID; late completions cannot advance offsets.
Freeze all referenced bytes until worker completion or cancellation is known.
Set client internal queue bounds as well as application bounds; no unbounded
`poll` delivery backlog while uploads run. Backoff uses deadlines, not owner sleeps.

- [ ] Fix `DlqPublisher.publish` to wait for the actual delivery callback and check
  both callback error and flush timeout/remaining count. Calling `produce` or
  `flush` alone is not durable rejection. Resolve a rejection offset only on
  confirmed delivery; bound pending rejections and stop admission on saturation.
- [ ] Add tests for unknown envelope version, missing legacy route, DLQ unavailable,
  later exclusion behind earlier failed upload, retry exhaustion/restart, mixed
  topics with equal partition IDs, and shutdown while an upload completes late.
  On retry exhaustion stop readiness/process without committing unresolved data;
  recover by replay. An integrity mismatch halts immediately.
- [ ] Run Task 9 tests plus `uv run --package uns_datalake pytest 14_uns_datalake/test/test_mapper.py -n 0 -v`.
  Include `archive_eligible=False`: resolve it as an explicit exclusion without
  writing a raw object, and prove it cannot advance past earlier unresolved work.

## Task 10: Explicit replay starts, retention-gap detection, and delivery health

**Files**
- Create: `14_uns_datalake/src/uns_datalake/replay.py`.
- Modify: `14_uns_datalake/src/uns_datalake/config.py`, `mapper.py`, `metrics.py`, `health_check.py`.
- Create: `14_uns_datalake/test/test_replay.py`.
- Modify: `14_uns_datalake/test/test_config.py`, `test_health_check.py`.

- [ ] Define `choose_start(committed, low, high, initial_position)` where offsets
  are concrete integers, missing committed is `None`, and `initial_position` is
  `require_committed` (default), `earliest`, or `latest`. Use the exact rules:

```text
committed exists and low <= committed <= high -> use committed
committed < low -> data_gap error even when earliest is configured
committed > high -> invalid_position error
missing + require_committed -> initial_position_required error
missing + earliest -> low; missing + latest -> high
```

- [ ] Add tests for every branch plus empty partitions and numeric offset gaps in
  otherwise valid consumption. Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_replay.py -n 0 -v`;
  expected first failure is missing position policy.
- [ ] On assignment query committed offsets and low/high watermarks, validate, then
  explicitly assign positions. Disable silent auto reset (`auto.offset.reset=error`
  for the installed client if supported). Treat runtime out-of-range/reset events
  as readiness failures too; assignment-only checks miss retention overtaking a
  slow active consumer. Recheck policy after every rebalance.
- [ ] Export bounded metrics for verified archive rows, durable rejections,
  upload/commit failures and latency, consumer lag, oldest unresolved receipt age,
  application buffered bytes, encoded bytes, active groups, integrity/gap failures.
  Archive counts reflect physical verified rows, not globally unique business events.
  Oldest unresolved time includes frozen/retry/DLQ state; publish zero/no backlog
  when idle, not time since the last event. Separate liveness and readiness.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_replay.py 14_uns_datalake/test/test_config.py 14_uns_datalake/test/test_health_check.py -n 0 -v`.
- [ ] Document new-group starting-position selection and retention-gap recovery:
  stop, record the gap, reconcile with a source replay/export if available, and
  require an explicit operator decision before starting a replacement group.
  No automatic offset reset or claim that expired events can be recovered.

## Task 11: Reader-first rollout and operational documentation

**Files**
- Modify: `conf/settings.yaml`, `docker-compose.yml` only where deployment tests require wiring.
- Modify: `14_uns_datalake/test/test_deployment.py`, `14_uns_datalake/README.md`, `06_uns_kafka/README.md`.
- Update: `docs/operations/uns-to-lake-delivery.md`.
- Create: `docs/adr/0012-multi-system-uns-to-lake-delivery.md` (use the next free number if occupied).

- [ ] Add deployment tests asserting Kafka remains, the lake uses its own group,
  historian is not a lake dependency, v2 writer enablement is explicit, the frozen
  legacy route revision is supplied, and ADLS cannot report ready without supported
  finalization. Do not overwrite concurrent Compose/health-test work.
- [ ] Run `uv run --package uns_datalake pytest 14_uns_datalake/test/test_deployment.py -n 0 -v`.
  Expected initial failure: absent v2 routing/configuration contracts.
- [ ] Document and exercise this rollout in the isolated fixture stack:

```text
inventory all canonical readers and record current group positions
capture immutable legacy map revision and object-prefix baseline
deploy dual-version readers with v2 writer disabled
verify v1 telemetry and existing queries still work
deploy versioned lake writer/configuration; preserve current group position
enable registered v2 publishing only after every reader is compatible
publish four-domain qualification cases; reconcile routes/body bytes/coordinates
```

Keep existing v1 objects readable under their old prefix; all newly exported rows
use `raw/v2`. Replay can overlap both prefixes; the runbook names the datasets and
deduplication keys rather than merging them implicitly. No backfill is automatic.

- [ ] Document rollback: disable new publishing before rolling readers back. Once
  v2 records exist in the log, keep dual-version readers until those records and
  retained replay ranges no longer require them; reverting v1-only binaries is
  not a safe rollback. Preserve accepted v2 data and consumer positions.
- [ ] Add the ADR as an extension to ADR-0011, describing envelope/routing/raw
  fidelity and at-least-once lake semantics without superseding its Kafka decision.
  Keep domain glossary/asset terminology changes outside this feature; module
  documentation explicitly states that business records do not require assets.
- [ ] Run the deployment test again and `docker compose config --quiet`.
  Record configuration validity separately from a running-stack qualification.

## Task 12: Failure qualification, capacity evidence, and handoff

**Files**
- Complete: `14_uns_datalake/test/test_multi_system_pipeline.py`.
- Create: `docs/benchmarks/uns-to-lake-delivery.md`.
- Complete: `docs/operations/uns-to-lake-delivery.md` and relevant module READMEs.

- [ ] Execute the spec's full acceptance matrix. In addition to Task 1, include
  these isolated-stack fault points and capture physical lake rows and offsets:

| Fault/condition | Required evidence |
| --- | --- |
| Historian stopped throughout | Four domains archive without SQL/Metric dependency. |
| Store stopped during second route upload | Earlier objects remain; no unsafe commit; recovery includes every expected coordinate. |
| Kill after upload/before commit | Replay may duplicate rows; identical Kafka coordinates identify repeated delivery. |
| Rebalance during delayed upload | Old generation cannot commit; new owner completes unresolved work. |
| DLQ timeout/failure | No rejection is checkpointed without acknowledged delivery. |
| Existing key has different content | No overwrite; integrity readiness fails. |
| Partial ADLS staging upload | No partial final `.parquet` object; separate live-Azure evidence. |
| Committed offset older than retained log | Explicit data-gap failure rather than auto-reset success. |
| Two schema versions / two sites / two applications | Exact intended paths with original body bytes and full provenance. |
| Legacy map/live registration changed | V2 routing unchanged; v1 map digest change refused unless explicit new replay decision. |
| Many small routes / near-limit records | Application and encoded buffers remain bounded; record RSS/scratch overhead. |
| Retained bootstrap / fresh retained publication | Bootstrap not duplicated as history; live eligible publication delivered. |

- [ ] For each backend, list actual executed test IDs, versions, duration, observed
  duplicates/rejections/gaps, and artifacts. Distinguish passed, failed, and not
  qualified; unit-only success is not durability qualification.
- [ ] Measure sustained ingress and catch-up throughput, p95 lake latency, log
  retention headroom, readback-verification bandwidth, group-cardinality effects,
  process RSS, and supported object-store outage duration. Catch-up must exceed
  live ingress for the documented representative workload. Unsupported capacity
  is a qualification gap, not an invitation to add a processing platform.
- [ ] Run focused regression suites independently after task tests pass:

```powershell
uv run --package uns_config pytest 00_uns_config/test -n 0
uv run --package uns_kafka_mapper pytest 06_uns_kafka/test -n 0
uv run --package uns_datalake pytest 14_uns_datalake/test -n 0
uv run --package uns_historian pytest 04_uns_historian/test -n 0
uv run --package uns_graphql pytest 07_uns_graphql/test -n 0
```

Run existing OEE historian-facing tests if compatibility changes reach their query
contracts; record the actual discovered test paths. No frontend redesign or test
suite is required merely because the lake layout changed.

- [ ] Review diffs for scope, credentials, fixture isolation, raw fidelity, and
  reader-first deployment. Run `git diff --check` and `graphify update .`.
  Report semantic document indexing separately if the CLI updates code only.
- [ ] Report implementation changes, verification evidence, duplicate/replay
  guarantees, backend gaps, and deployment status. Commit only if requested.

## Spec-to-plan coverage

| Design section | Tasks |
| --- | --- |
| 1–3: scope, existing architecture and baseline | 1, 4, 11 |
| 4: publication envelope, ownership, safe route IDs | 2, 3, 5 |
| 5: business semantics, old readers, legacy fidelity, exclusions | 2, 4, 5, 6, 11 |
| 6: lake format, immutable routing, UTC receipt date | 6, 7 |
| 7: durable acceptance, publication, consumed prefix, replay limits | 5, 7, 8, 9, 10 |
| 8: bounded observability and operations | 7, 10, 11, 12 |
| 9: acceptance and real backend evidence | 1, 4–10, 12 |
| 10: ordered delivery sequence | 1–12 |

## Completion definition

The feature is complete when all registered representative domains reach their
correct raw lake routes with proven new-payload byte fidelity, existing telemetry
consumers remain compatible, failure tests demonstrate safe at-least-once recovery,
and measured retention/backend limits are documented. External transformations,
vendor connectivity, and Databricks processing are not completion prerequisites.
