# HiveMQ Edge as the UNS broker and plant ingest

Date: 2026-09-03
Modules: `docker-compose.yml`, `docker-compose.dev.yml`, `conf/hivemq/`,
`08_uns_observability/prometheus/prometheus.yml`, `README.md`
Status: Approved. Deployment topology (Site Instance, local Timescale, optional
AWS / Azure Enterprise Instance) is in
[ADR 0010](../../adr/0010-site-instance-and-enterprise-cloud-hop.md).

Supersedes the **Compose deployment** of `10_uns_opcua` from
[2026-09-01-opcua-edge-connector-design.md](./2026-09-01-opcua-edge-connector-design.md).
That module stays in the repository until a later cleanup PR. It is not started.

## 1. Problem

Brownfield PLCs speak Siemens S7, EtherNet/IP, and OPC UA, not MQTT. This stack already
has a Python OPC UA connector (`10_uns_opcua`) and no S7 or EtherNet/IP path. Adding
another Python driver per vendor protocol does not scale, and the project must stay
community / OSS (same bar as EMQX, Neo4j CE, and the mappers).

Neither MQTT **broker** — EMQX or HiveMQ — has those industrial drivers. They live on a
**gateway**:

| Product | S7 | EtherNet/IP | OPC UA northbound | License |
| --- | --- | --- | --- | --- |
| EMQX broker | No | No | No | OSS |
| HiveMQ broker (CE) | No | No | No | Apache 2.0 |
| Neuron (EMQX OSS gateway) | No | No | No | LGPLv3 (Modbus + MQTT) |
| NeuronEX | Yes | Yes | Yes | Commercial |
| HiveMQ Edge | Yes | Yes | Yes | Apache 2.0 |

HiveMQ Edge is also an MQTT 3/5 broker. Replacing `emqx/emqx` with `hivemq/hivemq-edge` as
`uns_mqtt_broker` gives one process that is both the local UNS backbone and the plant
ingest. Kafka is unchanged: the HiveMQ Kafka extension is enterprise-only;
`kafka_mapper_client` remains the OSS bridge.

Mitsubishi is deferred. Southbound (MQTT → PLC write) is out: Edge's OPC UA write path is
commercial, and this platform does not write to control systems.

## 2. Decisions that shape the design

1. **Purpose is more plant ingest, not a broker beauty contest.** S7 and EtherNet/IP first;
   OPC UA joins the same adapter path so ingest is one config.
2. **OSS is a hard gate.** NeuronEX is out. HiveMQ Edge adapters used here are northbound
   only. The Docker image may preview commercial features; checked-in XML must not enable
   them.
3. **Replace EMQX in Compose, keep the service name.** Clients already use
   `UNS_mqtt__host: uns_mqtt_broker` and port `1883`.
4. **Edge is a plant gateway, not a clustered enterprise broker.** That is acceptable for
   this local, non-production compose file. A later factory/cloud split can still MQTT-bridge
   Edge to another broker.
5. **CI mapper tests stay on `emqx/emqx`.** They need a generic MQTT 5 broker, not PLC
   adapters. Swapping CI adds no protocol coverage.
6. **Historian identity still matters.** `mqtt.timestamp_attribute` is `timestamp`.
   `ON CONFLICT DO NOTHING` makes at-least-once safe only if `timestamp` is source time
   (epoch ms) and the publisher client id is stable. Edge has **no disk spool**; a broker
   outage drops S7/EIP samples. OPC UA may hold a short server-side queue
   (`serverQueueSize`). That gap versus `10_uns_opcua` is accepted.
7. **No fabricated `status`.** Same rule as the OPC UA spec. Extra Edge fields
   (`tagName`, `statusCode`, `sourceTimestamp`) are allowed; the historian stores full JSONB.

## 3. Scope

**In scope.** Swap `uns_mqtt_broker` to HiveMQ Edge; repo-owned `conf/hivemq/config.xml`
with northbound S7, EtherNet/IP, and OPC UA adapters (empty / unroutable by default);
payload contract for historian; port remap for the Edge console; remove `opcua_client`
from Compose and Prometheus scrape; README and container-role docs.

**Out of scope.** Mitsubishi; southbound writes; HiveMQ Kafka extension; MQTT
authentication; replacing EMQX in GitHub Actions; deleting the `10_uns_opcua` tree;
K8s / helm (`02_mqtt-cluster` stays EMQX until a separate decision); Edge UI as the
source of truth for tag maps.

## 4. Architecture

```
S7 / EtherNet/IP / OPC UA  →  HiveMQ Edge adapters  →  MQTT (ISA-95 topics)
simulator / Sparkplug      →  existing publishers   →  MQTT
                         ↓
              graphdb / historian / kafka mappers → GraphQL → console
```

`uns_mqtt_broker` remains the Compose service. Image:
`hivemq/hivemq-edge` at a released tag (not `snapshot`). `:latest` is acceptable to match
the rest of this compose file.

## 5. Components

### `uns_mqtt_broker`

- Image `hivemq/hivemq-edge`.
- MQTT TCP on container `1883` (host `1883` unchanged).
- Healthcheck: Edge HTTP/API is up (not `emqx ctl`). Healthy means the MQTT listener is
  up, **not** that every PLC is connected. An empty plant must not fail `depends_on`.
- Console / API on container `8080`, published as host **18080** (`18080:8080`).
- Host `8080` is no longer MQTT-over-WebSocket. The console never talks MQTT; in-repo
  clients default to TCP `1883`. Document the break. Do not publish Keycloak on `8080`.
- Authenticated EMQX ports `1884` / `8090` are dropped unless a cheap Edge equivalent
  exists. Not required for this cut.
- No southbound mappings in the checked-in config.

### `conf/hivemq/`

Repo-owned `config.xml`: listeners, adapter instances, tags, northbound topic maps.
Mounted read-only into the container. Tag → ISA-95 topic is authored here (asset path +
metric path, same vocabulary as today’s OPC UA `nodes[]`).

Default checked-in `config.xml`: MQTT listener only, **no** adapter instances. A **test
fixture** (not the Compose default) may add one S7, one EtherNet/IP, and one OPC UA
adapter aimed at unroutable hosts to prove parse-and-start. The stack must boot with no
plant.

Changing a tag map is a git edit and a broker recreate. Edge can hot-reload XML; this
stack treats recreate as the supported path so Compose matches git.

### Payload contract

Every adapter publish is **one MQTT message per tag**, QoS 1, on the mapped ISA-95 topic.

Required JSON fields:

- `timestamp` — number, epoch milliseconds, **source** time. For OPC UA this is
  `SourceTimestamp` (Edge also emits ISO-8601 `sourceTimestamp` in metadata; the field the
  historian reads is still `timestamp`). For polled S7 / EtherNet/IP, Edge
  `includeTimestamp` is the generation time of that sample.
- `value` — the scalar (or nested JSON). Historian flattening already turns nesting into
  dotted Metric paths.

Optional: `quality` / `statusCode`, `tagName`, `unit`. No fabricated `status`.

All Edge publishes share **one stable MQTT client id** (never generated at runtime).
Implementation must confirm that identity is the same after a container recreate. If it
is not stable, stop: do not ship a publisher that will duplicate historian rows.

Historian keeps `mqtt.timestamp_attribute: timestamp`.

### Unchanged

Simulator, Sparkplug mapper, graphdb / historian / kafka mappers, GraphQL, console, Kafka,
Neo4j, Timescale, OEE, Keycloak, Grafana.

### Removed from Compose

`opcua_client` service, `opcua_spool` volume, host `9093`, Prometheus target
`opcua_client:9093`, and `uns_prometheus` / `docker-compose.dev.yml` `depends_on` entries
for `opcua_client`.

`10_uns_opcua/` remains in git until a cleanup PR. `conf/settings.yaml` `opcua:` keys may
stay; nothing reads them in Compose after the service is gone.

## 6. Data flow

1. An adapter polls (S7 / EtherNet/IP) or subscribes (OPC UA) and publishes onto the
   mapped topic.
2. That message is a normal UNS publish. `graphdb_client` updates the current tree;
   `historian_client` inserts the Historic Event and Metrics using payload `timestamp`;
   `kafka_mapper_client` copies it to Kafka.
3. GraphQL and the console see PLC tags the same way they see simulator tags. No new
   query surface.
4. No PLC configured: adapters idle; simulator and Sparkplug still feed the namespace.

## 7. Error handling

| Case | Behaviour |
| --- | --- |
| PLC unreachable at start or later | That adapter retries (`maxPollingErrorsBeforeRemoval` / OPC UA reconnect). Other adapters and MQTT clients stay up. Broker stays healthy. |
| Broker down | S7 / EIP samples in that window are not spooled. OPC UA may keep a short server-side queue; overflow is lost. After MQTT returns, new samples publish. Historian `ON CONFLICT DO NOTHING` drops true duplicates. |
| Bad tag / wrong address | Edge logs the failed poll. No fake value. One bad tag does not stop the adapter. |
| Payload missing `timestamp` | Historian uses its existing fallback. Treated as a config bug: northbound mappings always set `includeTimestamp`. |
| Southbound / write | Not configured. A UI click that adds a write mapping is unsupported. |
| Compose health | MQTT listener up. Empty plant must not fail `depends_on`. |

## 8. Testing

- **Compose smoke.** `uns_mqtt_broker` becomes healthy; simulator still publishes;
  GraphQL / console still see live MQTT. No PLC required.
- **Port contract.** Host `1883` accepts MQTT 5 publish + subscribe. Host `18080` serves
  the Edge console. Host `8080` is not MQTT-WS. Keycloak remains unpublished on the host.
- **Adapter config parse.** A fixture `config.xml` with one S7, one EtherNet/IP, and one
  OPC UA adapter (unroutable hosts) starts the broker without crashing and without failing
  the healthcheck.
- **Northbound contract (optional / manual).** Against a simulator or stand-in: message
  lands on the mapped topic with numeric epoch-ms `timestamp` and `value`. Historian
  insert uses that `timestamp`. No Python OPC UA suite in CI for this cut.
- **Regression.** Existing mapper / GraphQL integration workflows keep `emqx/emqx`.
- **Removal check.** `opcua_client` is absent from `docker compose ps`; host `:9093` is
  unpublished; Prometheus has no `opcua_client` scrape target.

## 9. Docs to update in the same change

- `README.md` — Local Compose container table, Docker images list (`emqx/emqx` →
  `hivemq/hivemq-edge`; drop built `opcua_client` image), ports (`18080` console,
  `8080` no longer MQTT-WS).
- `08_uns_observability` comments that name `opcua_client:9093`.
- Do **not** rewrite `02_mqtt-cluster` helm/EMQX guides in this cut.

## 10. What this is not

This is not a replacement for Kafka. It is not NeuronEX. It is not a production
enterprise MQTT cluster. It is not write-back to a PLC.
