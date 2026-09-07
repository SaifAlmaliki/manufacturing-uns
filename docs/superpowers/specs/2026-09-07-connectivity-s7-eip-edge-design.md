# Catalog-driven S7 and EtherNet/IP into HiveMQ Edge

Date: 2026-09-07
Modules: `09_uns_model`, `07_uns_graphql`, `11_frontend`, `00_uns_config`,
`10_uns_opcua`, `conf/hivemq/`
Status: Draft — awaiting user review of this file

Related:
[2026-09-03-hivemq-edge-uns-broker-design.md](./2026-09-03-hivemq-edge-uns-broker-design.md)
(git XML is Edge’s runtime config; recreate is the supported apply path),
[2026-09-01-opcua-edge-connector-design.md](./2026-09-01-opcua-edge-connector-design.md)
(OPC UA catalog → `opcua_client`).

## 1. Problem

A plant will have Siemens S7, EtherNet/IP, and OPC UA at the same time. All three must
publish into the same MQTT Unified Namespace. Today that is two authoring paths:

- **OPC UA** is authored in Assets & Connectivity
  (`console.connectivity_servers` / `connectivity_tags`). `opcua_client` polls the catalog
  and publishes.
- **S7 and EtherNet/IP** are authored by hand in `conf/hivemq/config.xml`. The console
  lists those protocols as “— later.”

Engineers should not edit Edge XML. They should enter host, port, and signals in the same
Servers / Signals UI, see a status lamp like today’s OPC UA rows, and have Edge pick up
S7/EIP on broker recreate.

## 2. Decisions

| Topic | Choice |
| --- | --- |
| Authoring | One Connectivity catalog for OPC UA, S7, and EtherNet/IP |
| Apply this slice | Two backends: OPC UA → `opcua_client`; S7/EIP → generate Edge XML + operator recreate |
| Next slice (out) | Move OPC UA onto Edge so the broker is the only plant ingest |
| Live Edge Management API | Out. Status is not read from Edge’s HTTP API |
| Auto-recreate | Out. GraphQL does not use the Docker socket |
| XML ownership | Generator upserts only catalog-owned `<protocol-adapter>` blocks |
| Form | Protocol switches fields in the existing Add Server dialog |
| Signals | Manual add on the Signals tab; no S7/EIP browse |
| Test | OPC UA: existing session probe. S7/EIP: TCP connect to host:port |
| Status | `pending` after an XML write; Test may then set `connected` / `failed` |
| Southbound | Never generated |
| Other protocol tabs | Modbus, MQTT, SQL stay “— later” |

## 3. Architecture

```
Assets & Connectivity UI
        │
        ▼
console.connectivity_servers + connectivity_tags
        │
        ├── protocol = opc_ua  →  opcua_client (poll, subscribe, spool, MQTT)
        └── protocol = s7 | ethernet_ip
                    →  generator upserts <protocol-adapter> in conf/hivemq/config.xml
                    →  operator recreates uns_mqtt_broker
                    →  HiveMQ Edge polls PLC → MQTT
                              ▼
                     Unified Namespace (existing topic + payload rules)
```

`graphql_server` already mounts `./conf` at `/app/conf`. It can write
`/app/conf/hivemq/config.xml` on the host. `uns_mqtt_broker` mounts that file `:ro` and
only re-reads it on recreate.

## 4. Language

**Catalog-owned adapter**: a `<protocol-adapter>` whose `<adapterId>` is
`catalog-<server.id>`. The generator may insert, replace, or delete only these. The
`simulation` adapter, listeners, admin-api, and any hand-authored adapter are left alone.

**Pending**: `last_status` after a successful S7/EIP catalog write that changed generated
XML. Means “saved, Edge has not been recreated for this file yet” — not “PLC is up.”

**TCP test**: GraphQL opens a TCP connection to the parsed host and port. Success is
reachability, not an S7 or CIP handshake, and not proof Edge is polling.

## 5. Components

### Catalog

`CONNECTIVITY_PROTOCOLS` becomes `opc_ua`, `s7`, `ethernet_ip`. GraphQL
`ConnectivityProtocol` gains `S7` and `ETHERNET_IP`. Postgres CHECK and the frontend
`PROTOCOLS_IN_SLICE` match.

`endpoint` stays one text column:

| Protocol | Stored `endpoint` | Validation |
| --- | --- | --- |
| `opc_ua` | `opc.tcp://host:port` with optional path | Existing regex |
| `s7`, `ethernet_ip` | `host:port` (IPv4 or hostname) | Host non-empty, port 1–65535 |

IPv6 is out of this slice.

New nullable JSONB column `protocol_config` on `console.connectivity_servers`:

- S7: `{"controllerType": "S7_1500"}` — allowed values `S7_1500`, `S7_1200`, `S7_300`,
  `S7_400`. Default `S7_1500` when omitted.
- EtherNet/IP: `{}` or null.
- OPC UA: null; security stays on the existing columns.

`CONNECTIVITY_STATUSES` becomes `untested`, `pending`, `connected`, `failed`.

Signals reuse `connectivity_tags`:

| Column | S7 / EIP meaning |
| --- | --- |
| `node_id` | PLC address (`%ID103`, `Program:MainProgram.Count`) |
| `data_type` | Catalog type: `Integer`, `Double`, `Boolean`, `String` |
| `mqtt_topic` | Northbound ISA-95 topic (engineer-typed, not rewritten) |
| `subscribed` | Only `true` rows are generated into Edge |

New mutation `saveConnectivityTag`: upsert one tag by `(server_id, node_id)`, default
`subscribed: true`. Existing `updateConnectivityTag` / `unsubscribeConnectivityTag` stay.
`subscribeOpcUaVariables` stays OPC UA–only and rejects other protocols.

Duplicate `mqtt_topic` among subscribed tags (any protocol) is rejected.

### Generator

Pure functions in `00_uns_config` (`uns_config.hivemq_edge_xml`), which already owns the
HiveMQ file contract and is a GraphQL dependency.

- Input: path to `config.xml`, plus the current S7/EIP servers and their subscribed tags.
- Behaviour: parse XML; fail closed if the document is not well-formed; upsert or remove
  catalog-owned adapters so they match the catalog; write back atomically (write temp in
  the same directory, then replace).
- Never emit `<southboundMapping>`.
- `adapterId` = `catalog-` + server id (ids are already `srv_…`).
- `protocolId` = `s7` or `eip` (Edge’s spelling, not the catalog’s `ethernet_ip`).
- `<host>` / `<port>` parsed from `endpoint`. S7 also writes `<controllerType>`.
- Each subscribed tag: `<tag><name>` is a stable XML-safe id derived from `node_id`;
  `<description>` is `display_name` or the address; S7 `<tagAddress>` / EIP `<address>`
  is `node_id`; Edge data type from the map below.
- Each subscribed tag: `<northboundMapping>` with `topic` = `mqtt_topic`, `tagName` =
  that tag name, `maxQos` 1, `includeTimestamp` true.

Catalog → Edge data types:

| Catalog `data_type` | Edge XML |
| --- | --- |
| `Integer` | `DINT` |
| `Double` | `REAL` |
| `Boolean` | `BOOL` |
| `String` | `STRING` |
| unset | `DINT` |

A server with zero subscribed tags still gets an adapter block (config only, empty
mappings) so recreate attaches to the PLC before signals exist.

GraphQL runs the generator in the same transaction as the catalog write: if the XML write
fails, the catalog write rolls back.

`opcua_client` `load_servers_from_catalog` / `servers_from_catalog` includes only
`protocol == opc_ua`.

### Console

**Add / Edit Server** (existing dialog): Protocol enables OPC UA, S7, Ethernet/IP.
Modbus / MQTT / SQL remain disabled with “— later.”

| Protocol | Visible fields | Hidden |
| --- | --- | --- |
| OPC UA | Endpoint URL, Security, Authentication | — |
| S7 | Host, Port (default 102), Controller type (default S7_1500) | Security, Authentication |
| Ethernet/IP | Host, Port (default 44818) | Security, Authentication |

**Servers table**: same columns. Add a Protocol label so mixed plants are readable.
**Browse data** only for OPC UA. **Test** for all three. Empty-state copy is “No servers”
not “No OPC UA servers.”

**Signals tab**: “Add signal” for S7/EIP (address, data type, mqttTopic, display name).
OPC UA subscribe stays Browse data.

**Status lamps** (existing dots plus amber for pending):

| `last_status` | When | Lamp |
| --- | --- | --- |
| `pending` | S7/EIP save or signal change that rewrote XML | amber |
| `untested` | OPC UA save before Test; S7/EIP only if no XML change ran | grey |
| `connected` | Last Test succeeded | green |
| `failed` | Last Test failed; `lastError` is the reason | red |

After Add on S7/EIP the row appears immediately with `pending` and
`lastError` = `Recreate uns_mqtt_broker to apply Edge config`. Test may set
`connected` or `failed` even while Edge is still on the old file. A later
catalog/XML change sets `pending` and that `lastError` again.

## 6. Data flow

1. Engineer saves an S7 or EtherNet/IP server → catalog row + generator upsert →
   `last_status = pending`.
2. Engineer adds or edits subscribed tags → catalog + generator → `pending` if XML
   changed.
3. Engineer clicks Test → TCP to host:port (3s timeout) → `record_test` →
   `connected` / `failed`. If `last_status` was `pending`, Test success keeps the
   recreate sentence in `lastError` (green lamp, apply still outstanding). Test
   failure sets `lastError` to the TCP error.
4. Operator runs
   `uv run uns_compose up -d --force-recreate uns_mqtt_broker`.
   Edge loads the new file and polls. Console does not detect recreate automatically.
5. Edge publishes one MQTT message per tag, QoS 1, payload `timestamp` (epoch ms) and
   `value`, onto `mqtt_topic`. Mappers and the console consume it as any other UNS
   publish.
6. OPC UA save / Test / Browse / subscribe is unchanged and does not touch XML.
7. Delete S7/EIP server: cascade tags, remove that `adapterId` block, other adapters
   untouched. Edge drops the connection only after recreate.

Recreate reminder: the pending `lastError` sentence after every S7/EIP XML write is
enough. Do not add a “mark applied” button and do not try to detect broker recreate.

## 7. Error handling

| Case | Behaviour |
| --- | --- |
| Invalid form or spec | Reject before write. No catalog row, no XML touch |
| Invalid signal | Reject that tag write. Other tags and XML stay |
| XML write fails after catalog write started | Fail the mutation; roll back the catalog write |
| `config.xml` not well-formed | Fail; do not write |
| Hand-edited / `simulation` adapters | Left alone |
| Two servers, same host:port | Allowed |
| Duplicate subscribed `mqtt_topic` | Reject |
| PLC down at Test | `failed` + TCP error text. XML unchanged |
| PLC down after recreate | Broker stays healthy; that adapter retries; console status does not auto-flip |
| Broker not recreated | Console may be `pending` or Test-connected with recreate in `lastError`. Edge keeps old adapters |
| `opcua_client` given an S7/EIP row | Ignored. A filter miss that dials `host:port` as OPC UA is a failing test |
| Browse / `subscribeOpcUaVariables` / `testOpcUaConnection` on S7/EIP | API rejects; UI hides Browse |
| Southbound | Never generated |

## 8. Testing

- **Catalog / spec.** Protocol-specific endpoint validation; S7 `controllerType` allow-list;
  `pending` in `CONNECTIVITY_STATUSES`; `saveConnectivityTag` upsert and duplicate topic
  rejection.
- **Generator (temp XML, no Docker).** Start from a copy of `config.xml` that includes the
  `simulation` adapter. Add S7, add EIP, replace the same `adapterId`, delete one server,
  assert listeners / admin-api / `simulation` unchanged, no southbound, `includeTimestamp`
  true, `maxQos` 1, `protocolId` `eip` for `ethernet_ip`, host/port/controllerType match,
  data-type map as in §5. Refuse to write on broken XML.
- **GraphQL.** Save S7/EIP persists and updates a temp config path (inject path in tests).
  XML failure rolls back. `subscribeOpcUaVariables` on S7 raises. TCP test uses a mocked
  socket: open → `connected`, refused → `failed`.
- **`opcua_client`.** Catalog fixtures with mixed protocols produce collectors only for
  `opc_ua`.
- **Frontend.** Protocol dropdown enables S7 and Ethernet/IP; form swaps fields and
  defaults ports; Servers table shows mixed rows, hides Browse for S7/EIP, renders
  pending as amber; Add-signal path exists for non-OPC UA; validation rejects blank host
  and `opc.tcp://` on S7.
- **File contract.** `adapters-unroutable.xml` stays a parse fixture at `192.0.2.1`.
  Checked-in `config.xml` may keep `simulation`; it must not gain checked-in catalog
  adapters. README: S7/EIP are authored in the console; do not hand-edit those adapter
  blocks.
- **Manual / optional.** Point a catalog S7 row at a real PLC or the unroutable fixture,
  recreate, confirm the broker stays healthy and (if the PLC is real) a message lands on
  `mqtt_topic`.

## 9. Docs to update in the same change

- `conf/hivemq/README.md` — S7/EIP come from Assets & Connectivity; XML remains the Edge
  runtime file; recreate still applies; OPC UA stays on `opcua_client`.
- Empty-state and dialog copy in the connectivity console (no “OPC UA only” wording for
  the page as a whole).

## 10. What this is not

Not live apply via the Edge Management API. Not automatic broker recreate. Not OPC UA as
an Edge adapter. Not Modbus, MQTT, or SQL. Not southbound writes. Not Mitsubishi. Not
site-mesh compose XML (`docs/superpowers/specs/2026-09-04-site-enterprise-compose-profiles-design.md`
stays listener + bridge). Not a replacement for the simulation adapter.
