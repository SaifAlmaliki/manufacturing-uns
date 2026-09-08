# Historic Event lake Mapper (S3 or ADLS)

Date: 2026-09-08
Modules: `00_uns_config`, `06_uns_kafka`, `13_uns_datalake`,
`docker-compose.yml`, `conf/settings.yaml`, `08_uns_observability/prometheus/`
Status: Approved (pending written review)

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
| Azurite | **Not** in default `up`. Used when settings say `adls` |
| Local auth | MinIO (and Azurite) access key + secret in `.secrets.yaml` |
| Production S3 | AWS default credential chain. Static keys only if present in secrets |
| Production ADLS | `DefaultAzureCredential`. Account key only for Azurite |
| Parquet layout | `dt=YYYY-MM-DD/` (UTC) + topic-safe name. Columns `time`, `topic`, `payload` |
| Enrichment | Read-time. **Not** written to Parquet |
| Flush | 60 seconds **or** 8 MiB (`8388608` bytes), whichever first |
| Objects | Immutable. A retry may write a second file with the same rows |
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
                      datalake_mapper  (13_uns_datalake)
                           batch → Parquet → ObjectStore.put
                                   │
                          datalake.backend: s3 | adls
                                   │
                     local default          production
                     MinIO (always on)      AWS S3  or  Azure ADLS
```

`13_uns_datalake` does not import MQTT. Platform Observability never reaches
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

Add a handler method that produces to a **literal** Kafka topic (no `/` → `.`
on `uns.historic-events`). Dotted-topic `publish` stays as it is.

### Port (`00_uns_config.datalake`)

- `HistoricEventRecord(time, topic, payload)`
- `HISTORIC_EVENT_COLUMNS = ("time", "topic", "payload")`
- `historic_event_object_path(*, event_time, topic, flush_id) -> str`  
  `dt=YYYY-MM-DD/<topic_safe>-<flush_id>.parquet`  
  Topic-safe: `/` → `_`. `flush_id` is unique per flush (UTC compact time plus
  a short random suffix) so two flushes the same day never overwrite.
- `ObjectStore` protocol: `put(path: str, parquet_bytes: bytes) -> None`
- `FakeObjectStore` for tests (filesystem under a temp root)
- `S3ObjectStore`: boto3. `endpoint_url` set for MinIO; empty/omitted for AWS.
  Static keys from secrets when provided; otherwise default credential chain.
- `AdlsObjectStore`: Azure Data Lake File client. Account key from secrets for
  Azurite; `DefaultAzureCredential` when no key.
- `object_store_from_settings()`: `datalake.backend == "s3"` → S3, `"adls"` →
  ADLS. Extra settings for the unused cloud are ignored.

Do not add these names to `uns_config/__init__.py` unless a caller outside the
Mapper needs them.

### Lake Mapper (`13_uns_datalake`)

Compose service `datalake_mapper`. confluent-kafka **consumer**, group
`uns_datalake`, `enable.auto.commit: false`. Buffer `HistoricEventRecord`s.
Flush when elapsed ≥ `flush.interval_seconds` (60) or buffered bytes ≥
`flush.max_bytes` (8388608). Write Parquet with pyarrow (those three columns
only). `put`, then commit offsets for the flushed messages.

Prometheus metrics on port **9096** (unpublished; scrape from the compose
network). Health check is the metrics endpoint, same idea as OEE (`12_uns_oee`).
Suggested series: batch flush count, skip count (poison), `put` errors, last
successful `put` timestamp.

Poison envelope (JSON missing `time`, `topic`, or `payload`): log, increment
skip metric, **commit** that offset, do not `put`.

### Compose and settings

Default `uns_compose up` adds:

- `uns_minio` — S3 API on the compose network (`9000`). Host ports unpublished.
- A oneshot that creates bucket `uns-historic-events`.
- `datalake_mapper` — depends on Kafka healthy and MinIO/bucket ready.
  `UNS_MODULE: 13_uns_datalake`.

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
  s3:
    bucket: uns-historic-events
    region: us-east-1
    endpoint_url: http://uns_minio:9000
  adls:
    account: ""
    container: ""
  metrics_port: 9096
```

MinIO root user/password live in `.secrets.yaml` (same pattern as Postgres).
`datalake_mapper` receives them as S3 access key/secret when `endpoint_url` is
set.

Production S3: omit `endpoint_url` (or empty string), set `bucket` / `region`,
use the instance role. Production ADLS: `backend: adls`, account + container,
no account key.

Prometheus: job `uns_datalake` → `datalake_mapper:9096`. Prometheus
`depends_on` may include `datalake_mapper`. It does not depend on MinIO or
Azurite.

## 6. Data flow

1. Edge publishes MQTT `Acme/Line/Temp`.
2. `kafka_mapper` produces `Acme.Line.Temp` and `uns.historic-events`.
3. `datalake_mapper` batches. On flush, `put`s  
   `dt=2026-09-08/Acme_Line_Temp-<flush_id>.parquet` to MinIO.
4. Offsets commit after a successful `put`.
5. Condition Monitoring still reads Timescale + live MQTT.

AWS: same Mapper, empty `endpoint_url`. Azure: `backend: adls`. Remap of
`mqttTopic` changes new envelope `topic` values only.

## 7. Error handling

| Case | Behaviour |
| --- | --- |
| `uns/platform/…` | No envelope (existing `is_historic_event_topic`) |
| Poison envelope | Skip, commit offset, no `put` |
| `put` failure | Do not commit. Retry with backoff. Keep batch |
| Crash mid-batch | Kafka redelivers. A second immutable object may appear |
| Kafka down | Mapper unhealthy / restart. MQTT and historian continue |
| `backend: adls` without account | Mapper health fails. Default stack uses MinIO |
| Both S3 and ADLS settings filled | Only `datalake.backend` is used |
| Topic remap | Lake unchanged. Historian spec still owns rewrite |

## 8. Testing

No live AWS, Azure, or MQTT broker in pytest.

- Port: layout, columns, `FakeObjectStore`, settings factory, stubbed S3/ADLS
  `put` (no sockets).
- `kafka_mapper`: two produces per Historic Event; platform topics produce
  neither; existing dotted-topic tests still pass.
- Mapper: fake Kafka + fake store; commit after `put`; `put` failure does not
  commit; poison skip; time and size flush; two flushes → two object keys.
- Compose: `uns_minio` and `datalake_mapper` have **no** `profiles` key.
  Default `backend` is `s3` with MinIO `endpoint_url`. Azurite absent.
  Prometheus scrapes `datalake_mapper:9096`.

Manual (not pytest): `uns_compose up`, publish one Historic Event, list an
object under `dt=` in MinIO.

## 9. Docs to update in the same change

- [2026-09-08-uns-edge-opcua-datalake-design.md](./2026-09-08-uns-edge-opcua-datalake-design.md)
  — “Lake this slice = types only” and “Kafka unchanged” are superseded by
  this document for the running lake.
- Live-apply plan
  `docs/superpowers/plans/2026-09-07-connectivity-edge-live-apply.md` — lake
  work is not in that plan; layout/column tests live in `00_uns_config` via
  this plan’s Task 1.
- `06_uns_kafka` README — second produce to `uns.historic-events`.
- Root or `13_uns_datalake` README — MinIO default, how to point at AWS/ADLS.

## 10. What this is not

Not MQTT ingest in the lake Mapper. Not dual-write S3+ADLS. Not Iceberg/Delta.
Not rewriting Parquet on topic remap. Not Azurite on default `up`. Not live
cloud calls in pytest. Not changing dotted Kafka topic names. Not Enrichment
in the file. Not a query UI in the console.
