# Live HiveMQ Edge apply from Connectivity Save

Date: 2026-09-07
Modules: `00_uns_config`, `07_uns_graphql`, `09_uns_model`, `11_frontend`,
`conf/hivemq/`, `docker-compose.yml`
Status: Approved

**Extended by** [2026-09-08-uns-edge-opcua-datalake-design.md](./2026-09-08-uns-edge-opcua-datalake-design.md):
OPC UA joins this live-apply path; MQTT publish leaves default `opcua_client`.
Rows below that say OPC UA never touches Edge are **superseded**.

Related:
[2026-09-07-connectivity-s7-eip-edge-design.md](./2026-09-07-connectivity-s7-eip-edge-design.md)
(catalog, XML generator, TCP Test — this spec replaces only that document’s
**recreate-to-apply** path),
[2026-09-03-hivemq-edge-uns-broker-design.md](./2026-09-03-hivemq-edge-uns-broker-design.md)
(`config.xml` remains the file Edge reloads after a container restart).

## 1. Problem

Engineers author S7 and EtherNet/IP in Assets & Connectivity. Save already writes
catalog-owned adapters into `conf/hivemq/config.xml`. The running broker does not
reload that file, so the console asks them to recreate `uns_mqtt_broker` before
MQTT starts. That is not how a plant engineer works: they click Save and expect
data on the topic.

HiveMQ Edge’s Management API can create and update protocol adapters, tags, and
northbound mappings without restarting the process. This slice calls that API on
every S7/EIP Save.

## 2. Decisions

| Topic | Choice |
| --- | --- |
| Engineer action | Save only. No git, no recreate, no second Apply button |
| Durable copy | Keep writing `config.xml` (catalog-owned adapters only) |
| Live apply | GraphQL calls Edge Management API after the row is stored |
| Edge down / reject | Keep the Save (catalog + file). Lamp stays `pending`. Next Save retries the API |
| XML write fails | Fail the Save; roll back the catalog row so file and catalog stay together |
| After Edge accepts | Clear pending. Lamp becomes `untested` until Test |
| Test | Unchanged: TCP reachability. Does not push to Edge |
| Retry worker | Out. Next Save is the retry |
| Docker recreate | Out of the Save path. Ops only (image upgrade). Restart loads the file |
| OPC UA | **Superseded 2026-09-08:** Edge publishes subscribed OPC UA tags. Browse/Test stay on `uns_opcua`. |
| Southbound | Never sent to Edge |
| Edge status polling | Out. Console does not read Edge’s adapter connected lamp |

Pending copy (verbatim): `Waiting for HiveMQ Edge to apply`

`EDGE_APPLY_ERROR` in `uns_model.connectivity` becomes that sentence. Frontend tests
and GraphQL tests that assert the old recreate sentence switch to it.

## 3. Architecture

```
Save server / signal / unsubscribe / delete
        │
        ▼
store catalog row
        │
        ├── write config.xml          ← must succeed or Save fails and rolls back
        └── tell HiveMQ Edge via HTTP
              PUT catalog-<id> + tags + northbound topics
              (or DELETE that adapter)
                    │
                    ├── Edge accepts  → pending cleared; polling can start
                    └── Edge down     → Save kept; pending; next Save retries
```

`graphql_server` already shares a Compose network with `uns_mqtt_broker` and already
depends on it. It calls Edge at the container admin port (`8080` inside the network,
published on the host as `18080` for humans). The browser never calls Edge.

## 4. Language

**Save:** the engineer’s click in the console. The only action they take.

**Stored:** the catalog row is in Postgres. Not a git commit.

**Live apply:** HTTP to HiveMQ Edge so the running process matches the catalog
without recreating the container.

**Pending:** `last_status` after an S7/EIP Save whose live apply has not succeeded.
Means “saved, Edge has not accepted this yet” — not “PLC is up.”

**TCP test:** GraphQL opens TCP to host:port. Reachability only.

## 5. Components

### Edge client (`00_uns_config`)

New module next to `hivemq_edge_xml.py`. Same `EdgeAdapterInput` / `EdgeTagInput`
the generator already uses. `uns_config` must not import `uns_model`.

Behaviour:

- Authenticate with Edge’s admin API (username/password from settings).
- Idempotent replace: after a call, every catalog-owned adapter (`catalog-<server.id>`)
  on Edge matches the input list (host, port, S7 `controllerType`, subscribed tags,
  northbound topics, `maxQos` 1, `includeTimestamp` true). Adapters whose
  `catalog-*` id is missing from the list are deleted.
- Do not create, update, or delete `simulation` or any non-`catalog-*` adapter.
- Do not send southbound mappings.
- Time out after 10 seconds.
- Connection errors and HTTP 4xx/5xx become a return value or a dedicated exception
  the GraphQL layer catches. They must not fail the catalog Save.
- Exact HTTP paths and JSON follow the OpenAPI of `hivemq/hivemq-edge:latest`
  (auth token, then adapter / tags / northbound-mapping resources). Lock those
  paths in client tests against a recorded fixture, not against a live broker.

### Settings

| Key | Compose (`graphql_server`) | Local default |
| --- | --- | --- |
| `hivemq_edge.base_url` | `http://uns_mqtt_broker:8080` | `http://127.0.0.1:18080` |
| `hivemq_edge.username` | `admin` | `admin` |
| `hivemq_edge.password` | from secrets, default `hivemq` | `hivemq` |

Environment overrides: `UNS_hivemq_edge__base_url`, `UNS_hivemq_edge__username`,
`UNS_hivemq_edge__password`. Password lives in `conf/.secrets.yaml` next to the
other service passwords. The console never sees these.

### GraphQL

Existing `_sync_edge` keeps the XML write inside `after_flush` (Save rolls back if
the file write fails).

After the repository method returns (the row is stored), GraphQL calls the Edge
client with the same adapter list. Then it updates that server’s status:

| Live apply | `last_status` | `last_error` |
| --- | --- | --- |
| accepted | `untested` | null |
| failed or unreachable | `pending` | `Waiting for HiveMQ Edge to apply` |

HTTP details are logged server-side, not shown in `last_error`.

This runs for the same mutations as today’s XML sync: `saveConnectivityServer`,
`deleteConnectivityServer`, `saveConnectivityTag`, `updateConnectivityTag`,
`updateConnectivityTagTopic`, `unsubscribeConnectivityTag`. **OPC UA is included**
(see 2026-09-08 spec).

`testConnectivityServer` stays a TCP probe. If the server is still `pending`, a
successful Test keeps `last_error` as `Waiting for HiveMQ Edge to apply` (same
rule as today, new sentence). Test does not retry live apply.

### Console

Pending lamp stays amber. Replace the recreate sentence with
`Waiting for HiveMQ Edge to apply`. No new button.

### README

`conf/hivemq/README.md`: Save applies live. Recreate is for broker image upgrades
and disaster recovery. Do not hand-edit catalog-owned adapters.

## 6. Data flow

1. Engineer clicks Save on an S7/EIP server or signal.
2. Catalog row is stored.
3. Generator upserts `config.xml`.
4. Edge client pushes the same catalog adapters to the running broker.
5. Edge accepts → pending cleared (`untested`). Edge polls. MQTT can start on
   `mqtt_topic` when the PLC answers.
6. Edge is down or rejects → Save already succeeded. Lamp pending. Next Save
   retries step 4.
7. Unsubscribe: that tag is omitted from the next replace; Edge stops publishing it.
8. Delete server: row gone, `catalog-*` block removed from the file, Edge DELETE
   that adapter. If Edge is down, the file is already without the adapter; a later
   broker restart drops it. A later successful Save of any other catalog Edge
   protocol also deletes leftover `catalog-*` ids not in the list.
9. Browse / Test still never call Edge. OPC UA **Save / Subscribe / topic edit**
   do (2026-09-08 spec).

A server with zero subscribed tags still has an adapter (config only), same as the
XML contract. Edge attaches to the PLC; nothing publishes until a subscribed tag
exists.

## 7. Error handling

| Case | Behaviour |
| --- | --- |
| Invalid form or spec | Reject before store. No file touch, no Edge call |
| Cannot write `config.xml` | Save fails; catalog rolled back |
| Edge down, timeout, 4xx, 5xx | Save succeeds; `pending` + waiting sentence; next Save retries |
| Edge accepts, PLC unreachable | Save succeeds; `untested` (or `failed` after Test). Adapter is live; no MQTT until the PLC answers |
| Tag not subscribed / no topic | Not sent to Edge |
| Delete while Edge is down | Catalog and file updated. Edge may keep the old adapter until the next successful live apply or a broker restart (restart loads the file) |
| Two catalog servers, same host:port | Allowed (unchanged) |
| Duplicate subscribed `mqtt_topic` | Reject (unchanged) |
| Southbound | Never sent |

## 8. Testing

- **Edge client (no broker).** Mock HTTP. Create adapter, replace tags and topics,
  delete a removed `catalog-*` id, leave `simulation` untouched, send no southbound.
  Connection refused and 4xx/5xx are errors the caller can swallow.
- **Save path.** Existing XML tests stay. New: Edge accepted → pending/waiting text
  cleared, status `untested`; Edge down → Save succeeds, status `pending`, next
  Save calls the client again. XML failure
  still rolls back and does not call Edge. OPC UA Save **does** call the client
  (2026-09-08 spec).
- **Console.** Pending sentence is `Waiting for HiveMQ Edge to apply`.
- **Manual on this stack.** Add one S7 or EIP signal. Do not recreate the broker.
  Subscribe to that MQTT topic. If the PLC or sim is up, a value arrives.

## 9. Docs to update in the same change

- `conf/hivemq/README.md` — live apply on Save; recreate is ops-only.
- `docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md` — one line
  at the top: apply path superseded by this spec; catalog and XML contract unchanged.

## 10. What this is not

Not a background retry loop. Not GraphQL using the Docker socket. Not Modbus, MQTT, or SQL catalog apply. Not southbound writes. Not
reading Edge’s live connection state into the lamp. Not changing MQTT payload
shape (`timestamp` + `value`, QoS 1). OPC UA MQTT on Edge is
[2026-09-08-uns-edge-opcua-datalake-design.md](./2026-09-08-uns-edge-opcua-datalake-design.md).
