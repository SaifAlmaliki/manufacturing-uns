# Site and enterprise Compose profiles (laptop mesh)

Date: 2026-09-04
Modules: `docker-compose.yml` (unchanged single-Instance path), new
`docker-compose.site.yml`, `docker-compose.enterprise.yml`, `conf/hivemq/`,
`conf/instances/`, `00_uns_config`, `README.md`
Status: Draft pending review

Extends [ADR 0010](../../adr/0010-site-instance-and-enterprise-cloud-hop.md)
and [2026-09-03-hivemq-edge-uns-broker-design.md](./2026-09-03-hivemq-edge-uns-broker-design.md).

## 1. Problem

Compose is one Instance with every service in one file. The platform goal is
three Site Instances (HiveMQ Edge + local Timescale + plant console) MQTT-bridged
to one Enterprise Instance (HiveMQ CE + central stores + Kafka) so multi-site
analysis can run in a cloud-shaped stack. That mesh is not runnable today.

AWS, Azure, and Databricks are the later analytics consumers of Kafka. They are
not this slice. HiveMQ CE cannot push to those clouds.

## 2. Decisions that shape the design

1. **Same repository, same console, same GraphQL.** No `13_enterprise`, no second
   frontend. Enterprise-specific UI (fleet home, site compare) is a later spec.
   The enterprise console on port `8388` is the current UI; the tree contains
   `AcmeWater/Site1`, `Site2`, and `Site3` because those topics arrived on CE.
2. **Two compose files, four Docker projects.** `docker-compose.site.yml` is
   started as `site1`, `site2`, `site3`. `docker-compose.enterprise.yml` is
   started as `enterprise`. Today's `docker-compose.yml` stays the single-Instance
   laptop path (`npm run stack`).
3. **Site is a full plant console.** Edge, Timescale, Neo4j, GraphQL, console,
   Grafana, Prometheus, Keycloak, simulator, Sparkplug, OEE, historian + graph
   mappers. No Kafka on a site.
4. **Enterprise is a full twin.** HiveMQ CE (`hivemq/hivemq-ce`), Timescale,
   Neo4j, Kafka + kafka mapper, GraphQL, console, Grafana, Prometheus, Keycloak,
   OEE, historian + graph mappers. No simulator, no Sparkplug mapper, no PLC
   adapters. Kafka is the analytics seam for a later Databricks / AWS / Azure spec.
5. **Three full Site Instances.** Honest and RAM-heavy. Document that. Do not
   silently thin a site to fit a laptop.
6. **Hop is HiveMQ Edge MQTT bridge**, not a new Python mapper. Forward `#` to
   CE with the same topic names. File persistence on the bridge so a WAN outage
   does not drop site publishes that already reached Edge.
7. **Grafana stays unpublished on 3000.** Open `/grafana` on that Instance's
   console. Prometheus is per Instance with distinct host ports. Site → enterprise
   `remote_write` remains later (ADR-0001).

## 3. Scope

**In scope.** Site and enterprise compose files; per-Instance HiveMQ XML and
`conf/instances/{site1,site2,site3,enterprise}/`; shared Docker network
`uns_enterprise`; `uns_compose` flags to start a named project against a file
and instance conf dir; file-contract tests; README how to run the mesh; port
table.

**Out of scope.** Enterprise console chrome; AWS / Azure / Databricks connectors;
HiveMQ Enterprise license; Prometheus `remote_write`; MQTT auth; southbound PLC
writes; replacing `docker-compose.yml`; K8s / helm; starting the four-stack mesh
in CI.

## 4. Architecture

```
site1 Edge + local stores  ──MQTT bridge──┐
site2 Edge + local stores  ──MQTT bridge──┼──► HiveMQ CE ──► enterprise Timescale / Neo4j / Kafka
site3 Edge + local stores  ──MQTT bridge──┘                      │
                                                                 ├─► GraphQL / console / Grafana (real-time)
                                                                 └─► Kafka (later cloud analytics)
```

One shared external network `uns_enterprise`. The CE service publishes the
network alias `enterprise_mqtt`. Every `siteN.xml` bridge `<host>` is
`enterprise_mqtt`.

## 5. Components

### Same codebase

`11_frontend`, `07_uns_graphql`, and the mappers are reused. Difference is which
compose file starts them, which `UNS_CONF_DIR` they mount, and which MQTT host
they use. `platform.instance_name` is `Site1` / `Site2` / `Site3` / `Enterprise`.

### `docker-compose.site.yml`

Services: `uns_mqtt_broker` (image `hivemq/hivemq-edge`), `uns_timescale_db`,
`tsdb_setup_script`, `asset_model_setup`, `uns_neo4j_db`, `graphdb_client`,
`historian_client`, `spb_mapper_client`, `uns_simulator`, `oee_client`,
`graphql_server`, `uns_keycloak`, `uns_frontend`, `uns_grafana`, `uns_prometheus`.

Must not define `uns_kafka_broker` or `kafka_mapper_client`.

Host ports come from env (`SITE_MQTT_PORT`, `SITE_CONSOLE_PORT`, …) so three
projects can run at once.

### `docker-compose.enterprise.yml`

Same read path as a site, plus `uns_kafka_broker` and `kafka_mapper_client`.
`uns_mqtt_broker` image is `hivemq/hivemq-ce` (Apache 2.0). No `uns_simulator`,
no `spb_mapper_client`. CE has no Control Center like Edge; do not publish a
fake Edge-console port for enterprise. MQTT host port is `1893`.

### HiveMQ XML

| File | Role |
| --- | --- |
| `conf/hivemq/config.xml` | Unchanged single-Instance Edge (no bridge). |
| `conf/hivemq/site1.xml` … `site3.xml` | Edge + `<mqtt-bridges>` to CE, filter `#`, same destination topic. Bridge persistence on. No southbound mappings. |
| `conf/hivemq/enterprise.xml` | CE listeners only. No `<protocol-adapter>`. |

### Instance conf

`conf/instances/siteN/` and `conf/instances/enterprise/` hold the Dynaconf
overlay for that project: `platform.instance_name`, simulator hierarchy
(`AcmeWater/SiteN`), mapper MQTT host, Keycloak `KC_HOSTNAME` /
`GF_SERVER_ROOT_URL` for that console origin. Secrets stay in
`conf/.secrets.yaml` unless a port-specific issuer forces a copy — prefer env
interpolation over four secret files.

### Host ports

| | MQTT | Console (+ `/grafana`) | GraphQL | Prometheus | Timescale | Neo4j browser | Kafka |
| --- | --- | --- | --- | --- | --- | --- | --- |
| site1 | 1883 | 8088 | 8000 | 9090 | 5432 | 7474 | — |
| site2 | 2883 | 8188 | 8100 | 9190 | 5532 | 7574 | — |
| site3 | 3883 | 8288 | 8200 | 9290 | 5632 | 7674 | — |
| enterprise | 1893 | 8388 | 8300 | 9390 | 5732 | 7774 | 9092 |

Edge consoles (sites only): `18080`, `18081`, `18082`.

Keycloak stays unpublished on the host. `KC_HOSTNAME` is
`http://localhost:<console>/auth` for that Instance.

## 6. Data flow

1. Site simulator (or PLC adapter) publishes `AcmeWater/SiteN/…` on that Edge.
2. Site mappers write that site's Neo4j and Timescale. Site GraphQL and Grafana
   read only that store.
3. Sparkplug, when used, is translated on the site Edge; the bridge forwards the
   ISA-95 JSON.
4. Edge bridge copies `#` to CE with unchanged topic names.
5. Enterprise mappers write enterprise Neo4j, Timescale, and Kafka.
6. Enterprise console / Grafana show all three prefixes. Nothing in this slice
   calls AWS, Azure, or Databricks.

## 7. Error handling

| Case | Behaviour |
| --- | --- |
| Enterprise down | Each site console, Timescale, and Grafana keep working. Edge persists bridged publishes and forwards when CE returns. |
| One site down | Other sites and enterprise keep running. That prefix goes quiet on CE until it returns. |
| Bridge only down | Site stays healthy. Enterprise stops receiving that plant. No PLC writes. |
| Duplicate after reconnect | Historian `ON CONFLICT DO NOTHING` on `(time, topic, client_id)`. |
| Topic collision | Forbidden: Site1 / Site2 / Site3 are different prefixes. |
| Laptop OOM | Accepted risk. README states four full stacks are for a high-RAM machine. |
| Southbound | Not configured on any XML. |

## 8. Testing

CI does not start the four-stack mesh.

**Automated.** File contracts in `00_uns_config`:

- Site compose lists the plant services and does not list Kafka.
- Enterprise compose uses `hivemq/hivemq-ce`, lists Kafka, lists no simulator
  and no Sparkplug mapper, and has no protocol-adapter in `enterprise.xml`.
- Each `siteN.xml` has an MQTT bridge whose `<host>` is `enterprise_mqtt` and
  whose filter is `#`.
- Port env defaults match the table above.
- Simulator / mapper topic prefixes are `AcmeWater/Site1|Site2|Site3` in the
  instance overlays.
- Existing `docker-compose.yml` HiveMQ Edge tests still pass.
- Mapper / GraphQL workflows keep `emqx/emqx`.

**Manual (not CI).** Start four projects. Each site console shows only its
`SiteN`. Enterprise console and `8388/grafana` show all three. `docker compose
-p enterprise down` leaves site consoles live. Bring enterprise back; new
messages land on CE, enterprise Timescale, and Kafka.

## 9. Docs in the same change

- `README.md` — how to run the mesh vs `npm run stack`; port table; RAM warning;
  Kafka is the later cloud analytics seam.
- `conf/hivemq/README.md` — site XML vs `config.xml` vs `enterprise.xml`.
- ADR 0010 — laptop mesh is specified here; AWS / Azure consumers remain later.

## 10. What this is not

This is not a second codebase. It is not an enterprise console redesign. It is
not HiveMQ Enterprise. It is not an AWS or Azure landing zone. It is not
production. It is not write-back to a PLC.
