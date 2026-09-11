# Multi-system UNS-to-lake delivery

Date: 2026-09-11

Status: Written design approved by the user on 2026-09-11.
Planning only; no runtime implementation or deployment change is authorized here.

Plan: [Multi-system UNS-to-lake implementation plan](../plans/2026-09-11-multi-system-uns-to-lake.md).

## 1. Goal and boundary

Deliver accepted data from the centralized Unified Namespace to a data lake,
organized by the **publishing application, site, payload schema, and schema
version**, while preserving the source payload and provenance.

Machines are one class of publisher alongside MES/production, LIMS, ERP, WMS,
and logistics applications. Business data does not need a machine binding or
Metric representation to qualify for lake delivery.

This feature ends at reliable raw delivery. Transformations, enrichment, joins,
aggregations, curated datasets, business workflows, and processing jobs belong to
external tools such as Databricks. No Databricks integration is required here.
Building vendor connectors, introducing new ingress protocols, redesigning the
Asset Model/UI, and system-to-system writeback are also outside this feature.
Applications publish through the existing MQTT boundary, directly or through an
adapter they operate. Fixtures demonstrate the publishing contract without
claiming production connectivity to particular MES or LIMS products.

## 2. Architecture decision

Retain and extend the existing independent lake-consumer architecture:

```text
Machines / MES / LIMS / ERP / WMS / logistics publishers
                         |
                         v
                MQTT Unified Namespace
                         |
          validate delivery envelope + ownership
                         |
                         v
              durable canonical Kafka stream
                    /             \
                   v               v
          lake delivery mapper   existing consumers
                   |             (including historian)
                   v
       raw application/site/schema/version objects
```

MQTT remains the UNS; Kafka is the existing internal durable distribution log.
Lake delivery has its own consumer group and does not read from TimescaleDB.
Historian availability and Metric extraction cannot gate lake delivery.

### Alternatives

| Approach | Assessment |
| --- | --- |
| Extend existing Kafka-to-lake delivery | Selected: reuses the accepted architecture and independent replay; needs envelope compatibility and publication qualification. |
| Historian-first archive | Couples all domains to historian availability and storage semantics; does not fit this feature. |
| New direct MQTT-to-lake path | Possible, but requires a new durable buffering/recovery design already served by the existing log. |

This replaces the historian-first proposal as the planning direction for this
feature. ADR-0011 remains accepted; its transport decision is not superseded.
Any envelope changes require an additive decision record during implementation.

## 3. Inspected baseline

- `00_uns_config/src/uns_config/events.py` defines a v1 `HistoricEventEnvelope`,
  limits serialized envelopes to 1 MiB, requires a dictionary payload, and
  normalizes a top-level payload timestamp. It lacks application/schema routing.
- `00_uns_config/src/uns_config/uns_ingest.py` classifies ordinary MQTT messages
  as telemetry and excludes platform observability traffic.
- `14_uns_datalake/src/uns_datalake/mapper.py` independently consumes the canonical
  stream, batches records, publishes objects, and commits consumer offsets.
- `14_uns_datalake/src/uns_datalake/parquet.py` stores JSON payloads but omits some
  canonical provenance fields. It is not yet a full-fidelity archive contract.
- `14_uns_datalake/src/uns_datalake/stores.py` exposes only `put`; existing S3 and
  ADLS adapters do not establish verified immutable publication semantics.
- `14_uns_datalake/src/uns_datalake/config.py` provides record/byte/time bounds,
  a separate consumer group, and S3/MinIO and ADLS configuration.

These observations describe inspected code, not successful failure qualification.
The working tree contains unrelated Compose and health-test changes; execution
must re-check current diffs and preserve user work.

## 4. Publication and routing contract

Keep envelope version separate from payload schema version. The new versioned
contract adds the following metadata without interpreting business fields:

| Field | Contract |
| --- | --- |
| `source_application` | Stable ID of the publishing application, such as `lims`; not the downstream consumer or a display label. |
| `site_id` | Stable site ID associated with this publication. |
| `payload_schema_id` | Registered identifier such as `lab-result` or `production-order`. |
| `payload_schema_version` | Explicit opaque version identifier; different versions route separately. |
| `content_type` | Declared payload media type; does not imply that this service parses or transforms it. |
| Original payload | Exact source body bytes, preserved independently of any compatibility representation. |

Preserve existing event/source identity, original topic, event and receipt times,
identity/timestamp quality, source boot/sequence when present, and event category.
An envelope's own version must never be used as the payload schema partition.
Original payload bytes are authoritative; decoding JSON, changing timestamps,
flattening scalar leaves, or reserializing JSON cannot replace those bytes.

For legacy raw MQTT publishers, configured topic ownership supplies application,
site, and schema metadata. Contract-aware publishers provide metadata separately
from the payload body; the ingestion boundary verifies it against the same
registered ownership rules. New-envelope bodies are preserved exactly after
decoding their explicit binary/base64 transport representation.

Use configuration-based registration for this feature, not a new registry UI:
each rule declares an MQTT topic filter, source identity, application, site,
allowed schema/version pairs, and archive eligibility. Conflicting rule matches
fail configuration validation. Claimed application/site values must match the
authorized topic ownership. Broker ACLs bind publisher credentials to those
topics; a subscriber must not assume MQTT exposes a trustworthy publisher ID.

Missing/unknown routes are rejected durably with a stable reason, never silently
sent to `unknown`. Identifier segments use a bounded allowlist (letters, digits,
hyphen, underscore; 1–128 characters); slash, dot traversal, and unescaped path
separators are rejected. Application IDs are stable even when display names change.

The registry validates delivery metadata and declared schema/version membership.
It does not validate the business payload against a schema document or infer a
schema from payload contents. Schema-document management is outside this feature.

Sites need not be physical machines. Cross-site records require an explicitly
registered shared/enterprise scope ID; the delivery mapper never invents a site
or fans a single event out to multiple sites. Each accepted event has one route.

## 5. Event semantics and compatibility

Represent business events and current-state publications as such rather than
classifying all ordinary messages as telemetry. A correction is a new publication;
it does not overwrite an older lake object. The original payload carries any
business-object IDs, revisions, and relationships; this feature does not interpret
them or require a universal business-entity model.

Deploy readers that understand both v1 and the new envelope version before
enabling new writers. Existing historian and other canonical-stream consumers
must explicitly skip/checkpoint unsupported business categories while continuing
to process telemetry. They must not flatten business records into Metrics or
crash on the envelope version. New telemetry must preserve their existing query
contracts through compatibility tests.

For v1 replay, use a frozen, versioned legacy route map. Record its revision and
legacy provenance in lake rows. Preserve IDs and available metadata; do not claim
original-byte fidelity when old records contain only normalized JSON. A missing
legacy route is a reported rejection requiring an explicit mapping decision.
New accepted envelopes freeze their route metadata; later registration changes
must not reroute replayed events.

Keep existing platform-observability exclusions. Registered business events and
state updates are eligible without asset bindings. Retained bootstrap deliveries
do not become new historical events merely because a mapper reconnects; document
and test the distinction between bootstrap and fresh retained publications.

## 6. Lake format and layout

Use versioned Parquet as an envelope container, not a business-table transformation.
Every row preserves full envelope provenance and a binary original-payload column.
Add transport topic/partition/offset and publication batch identity for audit and
replay detection. Nullable legacy fields carry explicit fidelity provenance.

```text
raw/v2/
  application=lims/
    site=plant-01/
      schema=lab-result/
        version=1/
          ingestion_date=2026-09-11/
            <unique-object-id>.parquet
```

The date comes from the frozen ingress receipt time in UTC, not the upload clock
or the business event time. This keeps routing stable across late delivery/retry.
The `v2` prefix is the lake format version, independent of both schema versions.
Each object contains exactly one application/site/schema/version/date group.
No rewriting of old objects, partition compaction, or curated layer is included.

## 7. Delivery, recovery, and duplicate guarantees

The contract is **at-least-once lake delivery**, not end-to-end exactly-once.
Acceptance means the canonical event has been acknowledged by the durable log
under its qualified durability settings; MQTT publisher acknowledgment alone
does not prove lake delivery. The ingestion subscriber acknowledges QoS 1 only
after log acceptance or durable rejection, as in the existing ingest design.

Freeze a bounded partition batch, split it into route groups, encode immutable
objects, and publish each complete object. Verify stored length and content hash
before considering that object delivered. During a running attempt, retries use
the same keys and bytes; an existing key must match or halt with an integrity
error. ADLS uses staging/finalization so partial files are not visible at final
Parquet paths; S3 qualification must demonstrate its complete-object behavior.

Commit only the next offset after the fully resolved contiguous consumed prefix
for each Kafka partition. All route groups in that prefix must be verified or
durably rejected. A successful later group cannot permit committing past an
earlier failed group. Kafka offset gaps alone are not missing application events;
the prefix is defined over records actually delivered by the consumer.

A crash after object publication but before offset commit may create duplicate
rows in new objects on replay. Expose transport coordinates and stable event IDs
so downstream tools can detect them. Automatic cross-object/business-event
deduplication is outside scope. Distinct receipts without source identity must
not be deduplicated merely because their payload bytes match.

On ownership revocation, stop advancement and discard unresolved in-memory state;
the new owner replays uncommitted records. Already published objects remain valid
and can overlap replay. Rejection publication failure also blocks advancement.
An integrity mismatch is a readiness failure, not an endlessly retried transient.

Reuse configurable row, byte, record-size, and flush-age bounds. Add a maximum
number of active route groups and account for encoded artifacts as well as
buffered envelopes. Pause admission/flush when bounds are reached; never spawn
unbounded per-route workers. Preserve the current 1 MiB serialized-envelope cap,
including base64 overhead, and report oversize rejection explicitly.

Replay is bounded by Kafka retention and MQTT session limits, not indefinite.
Document supported outage durations from measured load and retention capacity.
Detect a committed offset falling behind the log start and stop with a data-gap
error; do not silently reset to earliest and report success. A fresh group requires
an explicit starting-position decision. QoS 0 remains best effort. Durable
rejections are accounted for separately from successful raw-lake delivery.

## 8. Observability and operations

Expose accepted, archived, rejected, and retry counts; consumer lag; age of oldest
unresolved receipt; buffered/encoded bytes; active route groups; upload/commit
latency; integrity failures; and retention-gap failures. Keep metric labels bounded
to registered dimensions/reason codes; event IDs and arbitrary topic strings do
not belong in metric labels. Idle health is not a lag failure.

The runbook must cover registration, eligibility, envelope limits, raw format,
duplicate semantics, credentials, replay start selection, Kafka-retention limits,
route-map revisions, and recovery after partial multi-route flushes. No object
deletion, offset reset, or existing-data rewrite is implicit in deployment.

## 9. Acceptance matrix

| Scenario | Required evidence |
| --- | --- |
| Machine, production order, LIMS result, logistics movement | All reach correct routes; business messages require no machine/Metric binding. |
| Same schema across two applications/sites | Isolated destinations and unchanged source metadata. |
| Two payload schema versions | Separate destinations; envelope version never substitutes for payload version. |
| JSON arrays, strings, nested objects, binary bodies | Exact new source-body bytes round-trip; no timestamp normalization. |
| Forged/missing route metadata, conflicting registrations | Explicit validation failure or durable rejection; no cross-route writes. |
| Historian stopped | Lake delivery continues; historian-compatible telemetry behavior remains tested. |
| Interleaved routes within one Kafka partition | Failure of an earlier route blocks advancement past it; recovery loses no records. |
| Object upload or offset commit failure | Retry/replay preserves data; duplicate rows are identifiable and documented. |
| Process kill and consumer rebalance | Unresolved records replay; no offset is advanced by a revoked owner. |
| Partial ADLS upload / existing object mismatch | No partial final object; mismatch fails readiness without overwriting. |
| Unknown envelope version / DLQ unavailable | Durable rejection or blocked progress, never silent discard. |
| Log retention gap / prolonged object-store outage | Explicit gap failure or recovery within measured bounds. |
| Many routes and maximum-size records | Bounded memory and active groups; catch-up exceeds live arrival rate. |
| Mixed v1/new envelope replay | Frozen routing, preserved IDs, honest legacy fidelity, no telemetry regression. |
| Retained bootstrap and platform observability | Existing exclusions preserved without suppressing eligible live business data. |

Unit tests prove routing and contract rules. Real Kafka/object-store tests prove
upload/commit/rebalance recovery. MinIO qualification does not establish live
Azure qualification; report backend evidence separately. Missing services are
not passing integration tests.

## 10. Implementation sequence and review gate

1. Baseline actual publishers/consumers and capture contract fixtures.
2. Add versioned envelope and immutable application/site/schema routing metadata.
3. Update ingress ownership and all active canonical-stream readers for compatibility.
4. Extend Parquet fidelity and bounded multi-route batches.
5. Implement verified publication and safe partition checkpoint advancement.
6. Qualify failure/replay limits and document deployment/reader contracts.

The written design has been approved. The linked task-by-task implementation plan
maps these requirements to exact existing modules and focused new
files, with failing tests and targeted verification commands. It must not carry
forward historian-first SQL archive worklists, historian cutover, dashboard polling
changes, or transformation work.
