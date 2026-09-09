# Historic Event lake Mapper (S3 or ADLS)

Date: 2026-09-08
Modules: `00_uns_config`, `06_uns_kafka`, `14_uns_datalake`,
`docker-compose.yml`, `conf/settings.yaml`, `08_uns_observability/prometheus/`
Status: Revised 2026-09-09 following implementation-readiness review; implementation not started.

Related:
[2026-09-08-uns-edge-opcua-datalake-design.md](./2026-09-08-uns-edge-opcua-datalake-design.md)
(named the object-store port, envelope topic, and “types only”; **this spec
runs** the Mapper and implements S3/ADLS),
[2026-09-07-connectivity-edge-live-apply-design.md](./2026-09-07-connectivity-edge-live-apply-design.md)
(live apply; lake work is out of scope for that plan),
[2026-09-05-condition-monitoring-design.md](./2026-09-05-condition-monitoring-design.md)
(lookback stays on the historian, not the lake).

## 1. Problem

Historic Events live on the Unified Namespace (MQTT) and in Timescale. Plants
also want an immutable object-store copy on **AWS S3** or **Azure Data Lake
Storage** for later analytics. Today `kafka_mapper` creates one Kafka topic per
MQTT topic (`/` → `.`). A lake consumer cannot subscribe to an unbounded topic
list. The 2026-09-08 Edge/datalake spec named port types and envelope topic
`uns.historic-events` but did not run a Mapper or talk to a cloud.

## 2. Decisions

| Topic | Choice |
| --- | --- |
| Who writes the lake | A **Mapper** (`datalake_mapper`). Never a second MQTT ingest |
| Kafka 1:1 topics | **Kept.** GraphQL and existing consumers unchanged |
| Envelope | `kafka_mapper` **also** produces `uns.historic-events` |
| Lake reads | **Only** `uns.historic-events` |
| Object store per plant | **One** backend: `s3` **or** `adls` (`datalake.backend`). Never dual-write |
| Default Compose | Mapper **and MinIO always on**. `backend: s3` against MinIO |
| Azurite | Out of this slice; absent from Compose. ADLS uses stubbed SDK tests and a production endpoint |
| Local auth | Separate `minio.root_user` / `minio.root_password` in `.secrets.yaml`; never injected unconditionally as AWS credentials |
| Production S3 | AWS default credential chain. Static keys only if present in secrets |
| Production ADLS | `DefaultAzureCredential`; explicit account key optional |
| Parquet layout | `dt=YYYY-MM-DD/` (UTC) + topic-safe name. Columns `time`, `topic`, `payload` |
| Enrichment | Read-time. **Not** written to Parquet |
| Flush | 60 seconds **or** 8 MiB estimated serialized bytes (`8388608`), whichever first; also cap at 10000 records |
| Objects | Completed contents are immutable. Same-process upload retries reuse a frozen key and bytes; crash/replay may create duplicate rows in another file |
| Delivery | At-least-once from Kafka envelope to lake. No commit may skip an earlier unpersisted valid record |
| Topic remap | Historian/catalog only. Lake does **not** rename old objects |
| Iceberg / Delta / query engine | Out of this slice |

Envelope topic name (verbatim): `uns.historic-events`.

## 3. Architecture

```
HiveMQ Edge ── MQTT Historic Events
                 │
                 ├── historian / graphdb  (MQTT #, drop uns/platform/)
                 └── kafka_mapper
                       ├── dotted Kafka topic (slash → dot)     [unchanged]
                       └── uns.historic-events
                             key   = MQTT topic
                             value = { time, topic, payload }
                                   │
                                   ▼
                      datalake_mapper  (14_uns_datalake)
                           batch → Parquet → ObjectStore.put
                                   │
                          datalake.backend: s3 | adls
                                   │
                     local default          production
                     MinIO (always on)      AWS S3  or  Azure ADLS
```

`14_uns_datalake` does not import MQTT. Platform Observability never reaches
the envelope: `kafka_mapper` already drops `uns/platform/` via
`is_historic_event_topic`.

## 4. Language

Use `CONTEXT.md`: Unified Namespace, Historic Event, Mapper, Enrichment.
The lake Mapper is not an “ingester.” MinIO is a local S3 stand-in, not a
second Unified Namespace.

## 5. Components

### Envelope produce (`06_uns_kafka`)

On each Historic Event, after the existing dotted `produce`:

- Kafka topic: `uns.historic-events` (from settings, default that name).
- **Key:** MQTT topic string (partition affinity per topic).
- **Value:** JSON object:
  - `time`: ISO-8601 UTC. Use the payload’s MQTT timestamp attribute when
    present (`mqtt.timestamp_attribute`, default `timestamp`); otherwise the
    mapper’s clock.
  - `topic`: MQTT topic.
  - `payload`: the same dict already published on the dotted Kafka topic.

Numeric source timestamps are epoch seconds below absolute `1e11`, milliseconds
otherwise. Invalid, non-finite, boolean or out-of-range source timestamps fall back
to the mapper clock; naive datetimes mean UTC. Valid offset timestamps normalize
to UTC. Malformed envelope timestamps on consumption are poison, not retimed.
The two Kafka produces are not transactional; this slice does not promise
lossless MQTT-to-Kafka delivery or end-to-end exactly-once semantics.

Add a handler method that produces to a **literal** Kafka topic (no `/` → `.`
on `uns.historic-events`). Dotted-topic `publish` stays as it is.

### Port (`00_uns_config.datalake`)

- `HistoricEventRecord(time, topic, payload)`
- `HISTORIC_EVENT_COLUMNS = ("time", "topic", "payload")`
- `historic_event_object_path(*, event_time, topic, flush_id) -> str`  
  `dt=YYYY-MM-DD/<topic_safe>-<flush_id>.parquet`  
  Topic-safe: `/` → `_`. `flush_id` is unique per flush (UTC compact time plus
   a random suffix). Allocate a separate ID per date/topic group, not one shared
   ID for all groups; topics that collapse to the same safe name must remain distinct.
- `ObjectStore` protocol: `put(path: str, parquet_bytes: bytes) -> None`
- `FakeObjectStore` for tests (filesystem under a temp root)
- `build_envelope` / `parse_envelope`: producer JSON and consumer validation;
  tombstones, missing/invalid fields and empty topics are poison.

### Adapters (`14_uns_datalake.stores`)

Cloud SDKs belong in the mapper package, never in `uns_config`.

- `S3ObjectStore`: boto3. `endpoint_url` set for MinIO; empty/omitted for AWS.
  Static keys from secrets when provided; otherwise default credential chain.
- `AdlsObjectStore`: Azure Data Lake File client. Explicit account key from
  secrets or `DefaultAzureCredential` when no key.
- `object_store_from_config(config)`: `datalake.backend == "s3"` → S3, `"adls"` →
  ADLS. Extra settings for the unused cloud are ignored.

Do not add these names to `uns_config/__init__.py` unless a caller outside the
Mapper needs them.

### Lake Mapper (`14_uns_datalake`)

Compose service `datalake_mapper`. confluent-kafka **consumer**, group
`uns_datalake`, `enable.auto.commit: false`, `enable.auto.offset.store: false`.
Buffer `HistoricEventRecord`s and track explicit next offsets per partition.
Flush when elapsed ≥ `flush.interval_seconds` (60) or buffered bytes ≥
`flush.max_bytes` (8388608). Write Parquet with pyarrow (those three columns
only, with `time` explicitly `timestamp[us, tz=UTC]`). Freeze a flush and group by
`(UTC event date, MQTT topic)`. Each group gets its own unique object key; never
use the first record's partition for mixed dates. Pause consumption while the
frozen flush is pending. Upload every group, then synchronously commit the frozen
next offsets. Inspect per-partition commit errors, not just raised exceptions.
Never commit the consumer's current assignment positions implicitly.

Bound records at 10000 and reject raw envelopes over 1 MiB with a fatal error
without committing them; operators can raise the configured limit. The 8 MiB
threshold is an estimate of serialized data, not exact process memory. Keep
at most one active/frozen batch and one group's encoded bytes; do not accumulate
another batch while retrying. Use a monotonic clock for interval/backoff logic.

Prometheus metrics on port **9096** (unpublished; scrape from the compose
network). Docker health requires `uns_datalake_up=1` and a loop heartbeat younger
than 60s. `uns_datalake_ready` separately reflects assignment/dependency status;
idle topics do not fail because they have never uploaded. Expose batch flush count,
poison skips, put/commit errors, last successful put and last-loop timestamps.
Fatal errors exit nonzero; Compose uses `restart: on-failure`. Docker marking a
process unhealthy alone is not a restart mechanism.

Poison envelope (JSON missing `time`, `topic`, or `payload`): log, increment
skip metric, mark its offset handled, do not add a Parquet row. Commit it only
when earlier buffered valid records are persisted. A poison-only batch commits
without any put. This prevents poison offset N+1 from skipping buffered event N.

Uploads get three attempts total with 1s then 2s backoff, same key/bytes, SDK
retries disabled and 5s connect/10s read timeouts. Continue polling while paused
to serve rebalance callbacks. Already-uploaded groups are not repeated within a
frozen flush. Third upload failure, serialization failure, commit exception or
partition commit error exits for replay. A revoke/lost callback with pending
offsets invalidates ownership and exits without flushing/committing. A stop
signal abandons uncommitted memory and closes the consumer without auto commit.
Partial successful commits are safe because all groups have already uploaded.

ADLS upload may expose a partial file before completion; retries overwrite only
the same frozen bytes. Atomic publication to concurrent readers is outside this
slice. Production buckets/filesystems must be provisioned before startup.

### Compose and settings

Default `uns_compose up` adds:

- `uns-minio` — S3 API on the compose network (`9000`). Host ports unpublished. Service name uses a hyphen because `mc` rejects underscore hostnames.
- A oneshot that creates bucket `uns-historic-events`.
- `datalake_mapper` — depends on Kafka healthy and MinIO/bucket ready.
  `UNS_MODULE: 14_uns_datalake`.

Azurite is **not** a default service.

Default settings:

```yaml
datalake:
  backend: s3
  kafka:
    topic: uns.historic-events
    group_id: uns_datalake
  flush:
    interval_seconds: 60
    max_bytes: 8388608
    max_records: 10000
    max_record_bytes: 1048576
  s3:
    bucket: uns-historic-events
    region: us-east-1
    endpoint_url: http://uns-minio:9000
  adls:
    account: ""
    container: ""
  metrics_port: 9096
```

This block lives under the existing `default:` Dynaconf environment.
MinIO root credentials live under `default.minio.root_user` / `root_password`
in `.secrets.yaml`. Compose exports `UNS_minio__root_user` /
`UNS_minio__root_password` for MinIO services only. The mapper reads mounted
config and uses that pair only for the exact default endpoint
`http://uns_minio:9000`, unless an explicit mapper S3 pair is supplied.
Other endpoints must not inherit local root credentials. Reject partial explicit
S3 pairs and missing selected-backend fields before constructing SDK clients.

Production S3: explicitly clear the inherited MinIO `endpoint_url` with an empty
string (omitting an override leaves the local default), set `bucket` / `region`,
omit explicit `datalake.s3` keys and use the instance role. Retaining the separate
MinIO root pair for local Compose does not affect AWS credential selection.
Production ADLS: `backend: adls`, account + container,
no account key.

Prometheus: job `uns_datalake` → `datalake_mapper:9096`. Prometheus
`depends_on` may include `datalake_mapper`. It does not depend on MinIO or
Azurite.

## 6. Data flow

1. Edge publishes MQTT `Acme/Line/Temp`.
2. `kafka_mapper` produces `Acme.Line.Temp` and `uns.historic-events`.
3. `datalake_mapper` batches. On flush, `put`s  
   `dt=2026-09-08/Acme_Line_Temp-<flush_id>.parquet` to MinIO.
4. Explicit next offsets commit only after every group in the frozen flush uploads.
5. Condition Monitoring still reads Timescale + live MQTT.

AWS: same Mapper, empty `endpoint_url`. Azure: `backend: adls`. Remap of
`mqttTopic` changes new envelope `topic` values only.

## 7. Error handling

| Case | Behaviour |
| --- | --- |
| `uns/platform/…` | No envelope (existing `is_historic_event_topic`) |
| Poison envelope | No row; defer offset behind earlier buffered valid records |
| `put` failure | Pause, retain frozen batch/key, retry after 1s/2s; third failure exits without commit |
| Partial multi-object success | Keep successful objects; no offsets commit until all groups succeed |
| Commit failure | Exit/replay; inspect both exceptions and partition errors |
| Revoke/lost with buffered offsets | Invalidate ownership; exit without committing |
| Shutdown | Close without flushing/committing pending records; Kafka replays |
| Crash mid-batch | Kafka redelivers. A second immutable object may appear |
| Kafka down | Readiness false; fatal/all-brokers-down error exits nonzero for restart. MQTT and historian continue |
| `backend: adls` without account | Configuration validation fails before SDK construction; process exits nonzero |
| Both S3 and ADLS settings filled | Only `datalake.backend` is used |
| Topic remap | Lake unchanged. Historian spec still owns rewrite |

## 8. Testing

No live AWS, Azure, or MQTT broker in pytest.

- Port: layout, UTC timestamp normalization/fallback, columns, `FakeObjectStore`; mapper config factory and stubbed S3/ADLS
  `put` (no sockets).
- `kafka_mapper`: two produces per Historic Event; platform topics produce
  neither; existing dotted-topic tests still pass.
- Mapper: offset-aware fake Kafka + fake store; ordered upload-before-commit
  assertions, poison after buffered valid records, multiple Kafka partitions,
  UTC midnight/late events and mixed topics, partial multi-object failure,
  bounded retries while paused, commit exception/partition error, ownership
  loss, shutdown replay, oversize record rejection, time/size/count flushes,
  and two explicitly separate flushes producing distinct keys.
- Patch SDK constructors/credential providers as well as upload clients so
  offline tests cannot perform credential discovery. Select existing Kafka
  tests with `-m "not integrationtest"`.
- Health: liveness sample value and fresh heartbeat required; readiness is
  separate and idle topics remain healthy. Test local MinIO credentials are
  not forwarded when the endpoint is cleared for AWS.
- Compose: `uns-minio` and `datalake_mapper` have **no** `profiles` key.
  Default `backend` is `s3` with MinIO `endpoint_url`. Azurite absent.
  Prometheus scrapes `datalake_mapper:9096`.

Required deployment checks outside pytest: verify the pinned MinIO release's
`curl` and `mc` executables, build the frozen Python 3.14 slim mapper image,
start MinIO/initializer/mapper and verify actual health. Publish a Historic
Event, inspect its Parquet object under the correct `dt=`, and verify replay
after restart with an unflushed event. Record unavailable Docker/credentials as
blocked gates. Stub tests do not prove live AWS/ADLS compatibility.

## 9. Docs to update in the same change

- [2026-09-08-uns-edge-opcua-datalake-design.md](./2026-09-08-uns-edge-opcua-datalake-design.md)
  — “Lake this slice = types only” and “Kafka unchanged” are superseded by
  this document for the running lake.
- Live-apply plan
  `docs/superpowers/plans/2026-09-07-connectivity-edge-live-apply.md` — lake
  work is not in that plan; layout/column tests live in `00_uns_config` via
  this plan’s Task 1.
- `06_uns_kafka` README — second produce to `uns.historic-events`.
- Root or `14_uns_datalake` README — MinIO default, how to point at AWS/ADLS.

## 10. What this is not

Not MQTT ingest in the lake Mapper. Not dual-write S3+ADLS. Not Iceberg/Delta.
Not rewriting Parquet on topic remap. Not Azurite on default `up`. Not live
cloud calls in pytest. Not changing dotted Kafka topic names. Not Enrichment
in the file. Not a query UI in the console.
