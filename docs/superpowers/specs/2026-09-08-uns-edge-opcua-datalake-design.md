# OPC UA on HiveMQ Edge, topic remap, and a datalake Mapper port

Date: 2026-09-08
Modules: `00_uns_config`, `07_uns_graphql`, `09_uns_model`, `10_uns_opcua`,
`11_frontend`, `conf/hivemq/`, `docker-compose.yml`
Status: Approved (pending written review)

**Lake runtime:** superseded by
[2026-09-08-uns-datalake-mapper-design.md](./2026-09-08-uns-datalake-mapper-design.md)
(envelope topic, Compose Mapper, MinIO / S3 / ADLS). Rows below that say the
lake is types-only and Kafka is unchanged are **superseded** for that Mapper.

Related:
[2026-09-07-connectivity-edge-live-apply-design.md](./2026-09-07-connectivity-edge-live-apply-design.md)
(Save → XML → Edge Management API; this spec **adds OPC UA** to that path and
drops “OPC UA never touches Edge”),
[2026-09-07-connectivity-s7-eip-edge-design.md](./2026-09-07-connectivity-s7-eip-edge-design.md)
(catalog + XML contract; “next slice = OPC UA onto Edge” is this document),
[2026-09-01-opcua-edge-connector-design.md](./2026-09-01-opcua-edge-connector-design.md)
(Browse/Test stay on `uns_opcua`; MQTT publish leaves the Compose forwarder),
[2026-09-05-condition-monitoring-design.md](./2026-09-05-condition-monitoring-design.md)
(cards query historian + live MQTT by catalog `mqttTopic`).

## 1. Problem

The Unified Namespace is the MQTT broker. Subscribed Connectivity tags must
appear there as soon as the engineer Subscribes — including OPC UA browse-path
topics such as `Server/OpcPlc/...`. Today OPC UA MQTT still comes from
`opcua_client`, while S7/EIP are moving onto HiveMQ Edge live apply. Two
publishers, two payload shapes, and a later datalake cannot assume one bus.

Engineers must also be able to remap `mqttTopic` onto an Asset path later
without emptying Condition Monitoring lookback. A future Mapper will land
Historic Events in S3 or Azure ADLS from Kafka; this slice names that port so
we do not invent a second MQTT ingest for the lake.

## 2. Decisions

| Topic | Choice |
| --- | --- |
| Who publishes plant MQTT | HiveMQ Edge for S7, EtherNet/IP, **and OPC UA** |
| Browse / Test | Unchanged: GraphQL → `uns_opcua` anonymous session. Not Edge browse |
| `opcua_client` Compose | Default **off**. Profile `legacy-opcua` for rollback only |
| Subscribe topic | **Not gated.** Browse path is valid. Data must flow once Edge has applied |
| ISA-95 remap | Optional later Save. TopicBinder may mark Unmodelled; it must not reject Subscribe |
| Remap + history | Rewrite `unifiednamespace` and `uns_metrics` in the same transaction as the catalog topic change. Failure **rolls back** the catalog change |
| Remap + Edge | Same Save then live-applies Edge. If Edge is down: history and catalog are already the new topic; lamp `pending` |
| Edge OPC UA auth | **Anonymous** URI from catalog endpoint. Catalog credentials unused by Edge this slice |
| MQTT payload | **Edge native** (`includeTimestamp` true). No rewrite to look like `uns_opcua` (`source` / `equipment`) |
| Live apply | Same as 2026-09-07: XML `after_flush` rolls back Save; Edge HTTP never rolls back Save |
| Lake this slice | **Superseded 2026-09-08 mapper spec:** running Mapper + MinIO/S3/ADLS. This document still forbids MQTT ingest and Enrichment-in-Parquet. |
| Kafka | **Superseded 2026-09-08 mapper spec:** keep 1:1 dotted topics **and** produce envelope `uns.historic-events` |
| Enrichment | Read-time. Not written into Parquet or historian JSONB |
| Southbound | Never |

Pending copy stays verbatim: `Waiting for HiveMQ Edge to apply`.

## 3. Architecture

```
Browse / Test
    GraphQL ── uns_opcua.open_client / browse     [unchanged]

Subscribe / Save / remap mqttTopic  (opc_ua | s7 | ethernet_ip)
    catalog row
        ├── config.xml (catalog-* adapters)     ← must succeed or Save rolls back
        ├── historian rewrite (remap only)      ← must succeed or topic Save rolls back
        └── Edge Management API                 ← failure keeps Save; pending

HiveMQ Edge ── polls PLC ── MQTT (catalog mqttTopic, Edge JSON)
    │
    ├── historian / graphdb / kafka mappers  (#, drop uns/platform/)
    └── future: Kafka → Parquet object store (port defined here, not run)
```

`10_uns_opcua` remains a library for Browse/Test. The Compose MQTT forwarder is
not started on a default `up`.

## 4. Language

Use `CONTEXT.md`: Unified Namespace, Historic Event, Mapper, Unmodelled Topic,
Topic Binding, Enrichment. Avoid calling Edge an “ingester.”

**Parked forwarder:** Compose service `opcua_client` behind profile
`legacy-opcua`. Not part of default plant publish.

## 5. Components

### Edge OPC UA (extends live apply)

Catalog `adapterId` remains `catalog-<server.id>`. `opc_ua` → Edge `protocolId`
`opcua`. Config is `<uri>` from `endpoint`. No username/cert in the adapter this
slice.

Each **subscribed** tag: Edge `<tag>` name stable per `nodeId`; `<definition>`
`<node>` is the OPC UA NodeId. Northbound mapping: `topic` = `mqttTopic`,
`tagName` matches, `maxQos` 1, `includeTimestamp` true. Zero subscribed tags:
adapter config only (same as S7/EIP). Unsubscribe omits the tag on the next
replace.

Idempotent replace of all catalog-owned adapters still includes S7, EIP, **and**
OPC UA in one Edge call. Do not touch `simulation` or non-`catalog-*`.

OPC UA mutations that already sync XML **now call live apply** (Save server,
save/update/unsubscribe tag, update topic, delete server).

Test: OPC UA stays a session probe; S7/EIP stay TCP. Test does not push Edge.
If `pending`, a successful Test keeps `EDGE_APPLY_ERROR`.

### Compose

- `opcua_client` has `profiles: [legacy-opcua]`.
- Default prometheus must **not** `depends_on` `opcua_client` (the service is absent).
- Default `up`: Edge is the only OPC UA MQTT publisher.

### Topic remap

`updateConnectivityTagTopic` (and any bulk path that changes `mqttTopic`):

1. Reject duplicate `mqttTopic` (unchanged).
2. In one DB transaction: update the catalog row **and**
   `HistorianRepository.rewrite_topic_prefix` (old topic → new topic) on
   `unifiednamespace` and `uns_metrics`.
3. If rewrite fails, roll back the catalog change (same spirit as XML
   `after_flush`).
4. After commit: XML + Edge live apply for that server.
5. Condition Monitoring already queries and subscribes to catalog `mqttTopic`;
   lookback remains continuous after rewrite. Live tail waits on Edge if pending.

Unmodelled browse-path topics are allowed. Connectivity may show Unmodelled;
Subscribe must still succeed.

### Datalake Mapper port (`00_uns_config`)

**Runtime Mapper:** [2026-09-08-uns-datalake-mapper-design.md](./2026-09-08-uns-datalake-mapper-design.md).
This section only named the port. Layout (`dt=YYYY-MM-DD/`), Historic Event
columns (`time`, `topic`, `payload`), no Enrichment in Parquet, and no MQTT
ingest still apply. Envelope topic, Compose, and real S3/ADLS `put` live in
that spec.

## 6. Data flow

1. Engineer Browses OPC UA (GraphQL/`uns_opcua`). Subscribes with whatever
   `mqttTopic` is in the row (often the browse path).
2. Catalog stored → XML written → Edge replace includes the OPC UA adapter and
   mappings → Edge polls → MQTT on that topic → historian stores Historic
   Events → Condition Monitoring lookback + live work.
3. Later the engineer sets `mqttTopic` to an Asset path. Catalog + historian
   rewrite commit together. Edge is told the new mapping. CM keeps the line.
4. Lake objects: [2026-09-08-uns-datalake-mapper-design.md](./2026-09-08-uns-datalake-mapper-design.md).

## 7. Error handling

| Case | Behaviour |
| --- | --- |
| Invalid form | Reject before store. No XML, no rewrite, no Edge |
| Cannot write `config.xml` | Save fails; catalog rolled back |
| Historian rewrite fails on remap | Topic Save fails; catalog `mqttTopic` unchanged |
| Edge down / 4xx / 5xx | Save (and rewrite, if any) kept; `pending` + waiting sentence |
| Unmodelled `mqttTopic` | Allowed. Optional Unmodelled mark. Not a GraphQL error |
| Duplicate subscribed topic | Reject (unchanged) |
| Secured OPC UA (needs credentials) | Out of this slice. Anonymous only. Browse/Test remain anonymous |
| `legacy-opcua` profile and Edge both publishing | Operator error. Default compose must not start the forwarder |

## 8. Testing

- Flip live-apply tests: OPC UA Save/subscribe **does** call the Edge client.
  Remove `test_save_opc_ua_does_not_call_live_apply`.
- XML/API fixtures: `opcua` adapter with `uri`, tags, northbound topics;
  `simulation` untouched; no southbound.
- Remap: rewrite called; Timescale failure rolls back catalog topic (mocked
  historian).
- Compose: `opcua_client` only under `legacy-opcua`.
- Lake layout/columns: still tested in `00_uns_config`; the running Mapper is
  [2026-09-08-uns-datalake-mapper-design.md](./2026-09-08-uns-datalake-mapper-design.md).
- No live broker in pytest (mock HTTP). No live S3/ADLS in the Edge slice.

## 9. Docs to update in the same change

- `2026-09-07-connectivity-edge-live-apply-design.md` — OPC UA now on the live
  apply path; “not moving OPC UA” is superseded by this spec.
- `2026-09-07-connectivity-s7-eip-edge-design.md` — “next slice” is this spec;
  apply path remains live apply.
- `conf/hivemq/README.md` — OPC UA catalog adapters; `legacy-opcua` profile.
- Implementation plan
  `docs/superpowers/plans/2026-09-07-connectivity-edge-live-apply.md` — after
  this spec is reviewed, extend tasks for OPC UA, remap/rewrite, compose
  profile, lake port.

## 10. What this is not

Not Edge browse. Not deleting `10_uns_opcua`. Not Edge OPC UA credentials.
Not Iceberg/Delta. Not southbound. Not requiring ISA-95 before Subscribe. Not
rolling back Save when Edge is down. Not a background rewrite/retry worker.
A running lake Mapper is
[2026-09-08-uns-datalake-mapper-design.md](./2026-09-08-uns-datalake-mapper-design.md).
