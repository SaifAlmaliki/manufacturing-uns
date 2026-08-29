# UNS Full Console — Implementation Prompt

Copy everything below the line into the external tool. This document is self-contained. Do not assume access to the repository.

---

You are a principal product designer and staff frontend engineer. Design and specify (and, if you generate UI, implement) a **full-fledged industrial web console** for an open-source Unified Namespace (UNS) IIoT platform.

This is **not** a marketing site, dashboard-of-KPI-cards, or generic admin admin template. It is a **dense, desktop-first, dark industrial operations console** used by plant operators, OT engineers, and integration engineers.

Do not invent backends, ports, or GraphQL fields. If a capability is not in the schema below, mark it **UI-only** or **requires new GraphQL** and do not fake live data for it.

---

## 1. Mission

Build one React SPA (`10_frontend`) that is the human interface to the Unified Namespace.

A Unified Namespace is a **centralized, event-driven repository** of OT/IT data. Devices and apps publish/subscribe on MQTT using an **ISA-95 Part 2** hierarchy instead of point-to-point integrations.

Topic shape:

```
<enterprise>/<facility>/<area>/<line>/<device>
```

Example plant (from live config):

```
CovestroAG / Dormagen | Krefeld / Production / Line1 | Line2 / Cell1 | Cell2
```

Example leaf topics published by the simulator:

```
CovestroAG/Dormagen/Production/Line1/Cell1/G1/ProcessValue/Temperature
CovestroAG/Dormagen/Production/Line1/Cell1/FillingMachine/ProcessValue/FlowRate
```

Branding (from `conf/settings.yaml`):

- Product display name: **Covestro UNS**
- Organization: **CovestroAG**
- Instance: **Instance01**

Personas (one app, three modes):

| Persona | Primary job |
| --- | --- |
| Operator | Watch the live ISA-95 tree, current payload, live MQTT traffic |
| Engineer | Search nodes, inspect JSON, query historian, trend numerics, browse Sparkplug metrics |
| Integrator | Watch Kafka stream, distinguish Sparkplug vs UNS, verify mappers are feeding the namespace |

Success: every GraphQL query and subscription in the schema below is reachable from the UI. The operator can run the console with no login on a trusted plant/VPN network.

---

## 2. Hard constraints (never violate)

1. The browser talks **only** to GraphQL.
   - HTTP: `POST /graphql`
   - WebSocket: `/graphql` (`graphql-transport-ws` and/or `graphql-ws`)
2. **Never** connect the browser to MQTT, Neo4j, TimescaleDB, Kafka, or Sparkplug protobuf.
3. Do **not** serve the UI from FastAPI. Separate static site (Vite dev / nginx prod).
4. Do **not** publish MQTT control messages (NCMD/DCMD). The Sparkplug mapper is **not** a SCADA/IIoT host.
5. Do **not** decode Sparkplug B protobuf in the browser. Live Sparkplug payloads arrive as `BytesPayload`. Decoded Sparkplug is `getSpbNodesByMetric` → `SPBNode`.
6. Tree queries **never** use MQTT `#`. Roots: `+`. Children of node `N`: `{N.namespace}/+`.
7. Sparkplug topics start with `spBv1.0/`. They appear in the live feed as a badge, **never** as JSON, and are **never** inserted into the ISA-95 tree.
8. Search **does not** replace or filter the left tree. Matches live in a list; clicking a match expands ancestors in the existing tree.
9. No authentication in this version (trusted network). Do not add fake login screens.
10. Do not invent OEE/KPI numbers. There is no OEE GraphQL field.
11. English only. Desktop-first (min ~1280px). Not mobile-first. No i18n.
12. Production build with missing `VITE_GRAPHQL_URL` shows a **blocking error**, not a blank screen.
13. Dev: GraphQL relative URL `/graphql` (Vite proxies HTTP+WS to `localhost:8000`). Prod: absolute `VITE_GRAPHQL_URL`.
14. Evolve existing app in `10_frontend`. Do not create a second frontend.

---

## 3. Architecture (how data actually flows)

```
Plant devices OR uns_simulator
    → MQTT broker EMQX
         host ports: 1883 (MQTT), 8080 (MQTT over WebSocket)
    → mapper clients (MQTT subscribers, not UI):
         graphdb_client     → Neo4j current ISA-95 tree
         historian_client   → TimescaleDB history
         spb_mapper_client  → Sparkplug protobuf → ISA-95 JSON republish
         kafka_mapper_client → MQTT → Kafka topics
    → GraphQL server (FastAPI + Strawberry)
         host: http://localhost:8000/graphql
    → Web console (this app)
         dev:  http://localhost:5173  (proxy /graphql → :8000)
         prod: http://localhost:8088  (nginx; browser calls :8000/graphql)
```

Other host ports the UI must **not** call: Neo4j 7474/7687, Timescale 5432, Kafka 9092.

Typical compose project name: `manufacturing-uns`.

Node types on UNS tree (depth labels): `ENTERPRISE`, `FACILITY`, `AREA`, `LINE`, `DEVICE`. Nested JSON objects may appear as `NESTED_ATTRIBUTE` in GraphDB but GraphQL `UNSNode.nodeType` is one of the ISA-95 labels (or similar string).

Sparkplug topic types (not in the UNS tree): `spBv1_0`, `GROUP`, `MESSAGE_TYPE`, `EDGE_NODE`, `DEVICE`.

MQTT wildcards:

- `+` = one topic level
- `#` = multi-level (this and all descendants)

Kafka subscriptions: **exact topic strings only**. No wildcards, no regex.

---

## 4. Complete GraphQL schema (wire names are camelCase)

Strawberry exposes camelCase on the wire. Use these names exactly.

### Scalars and enums

- `DateTime` (ISO-8601)
- `JSON`
- `Base64`
- `Int64` (string/number as schema defines; treat as string if needed)
- `enum BinaryOperator { OR AND NOT }`

### Inputs

```graphql
input MQTTTopicInput { topic: String! }   # wildcards + and # allowed
input KAFKATopicInput { topic: String! }   # exact topic, no wildcards
```

### Types

```graphql
type JSONPayload { data: JSON! }
type BytesPayload { data: Base64! }
union JSONPayloadBytesPayload = JSONPayload | BytesPayload

type UNSNode {
  nodeName: String!
  nodeType: String!
  namespace: String!
  payload: JSONPayload!
  created: DateTime!
  lastUpdated: DateTime!
}

type HistoricalUNSEvent {
  publisher: String!
  timestamp: DateTime!
  topic: String!
  payload: JSONPayload!
}

type MQTTMessage {
  topic: String!
  payload: JSONPayloadBytesPayload
}

type StreamingMessage {
  topic: String!
  payload: JSONPayload!
}

type SPBNode {
  topic: String!
  timestamp: DateTime!
  metrics: [SPBMetric!]!
  seq: Int64!
  uuid: ID
  body: Base64
}

type SPBMetric {
  name: String!
  alias: Int64
  timestamp: DateTime!
  datatype: String!
  isHistorical: Boolean
  isTransient: Boolean
  isNull: Boolean
  metadata: SPBMetadata
  properties: SPBPropertySet
  value: SPBPrimitiveBytesPayloadSPBDataSetSPBTemplate!
}

type SPBPrimitive { data: String! }
type BytesPayload { data: Base64! }

type SPBDataSet {
  numOfColumns: Int64!
  columns: [String!]!
  types: [String!]!
  rows: [SPBDataSetRow!]!
}
type SPBDataSetRow { elements: [SPBDataSetValue!]! }
type SPBDataSetValue { value: SPBPrimitive! }

type SPBMetadata {
  isMultiPart: Boolean
  contentType: String
  size: Int64
  seq: Int64
  fileName: String
  fileType: String
  md5: String
  description: String
}

type SPBPropertySet { keys: [String!]! values: [SPBPropertyValue!]! }
type SPBPropertySetList { propertysets: [SPBPropertySet!]! }
type SPBPropertyValue {
  isNull: Boolean
  datatype: String!
  value: SPBPrimitiveSPBPropertySetSPBPropertySetList!
}

type SPBTemplate {
  version: String
  metrics: [SPBMetric!]!
  parameters: [SPBTemplateParameter!]
  templateRef: String
  isDefinition: Boolean
}
type SPBTemplateParameter { name: String! datatype: String! value: SPBPrimitive! }

union SPBPrimitiveBytesPayloadSPBDataSetSPBTemplate =
  SPBPrimitive | BytesPayload | SPBDataSet | SPBTemplate

union SPBPrimitiveSPBPropertySetSPBPropertySetList =
  SPBPrimitive | SPBPropertySet | SPBPropertySetList
```

### Queries (all must have UI)

```graphql
type Query {
  getUnsNodes(topics: [MQTTTopicInput!]!): [UNSNode!]!

  getUnsNodesByProperty(
    propertyKeys: [String!]!
    topics: [MQTTTopicInput!]
    excludeTopics: Boolean = false
  ): [UNSNode!]!

  getHistoricEventsInTimeRange(
    topics: [MQTTTopicInput!]!
    fromDatetime: DateTime
    toDatetime: DateTime
  ): [HistoricalUNSEvent!]!

  getHistoricEventsByPublishers(
    publishers: [String!]!
    topics: [MQTTTopicInput!]
    fromDatetime: DateTime
    toDatetime: DateTime
  ): [HistoricalUNSEvent!]!

  getHistoricEventsByProperty(
    propertyKeys: [String!]!
    binaryOperator: BinaryOperator
    topics: [MQTTTopicInput!]
    fromDatetime: DateTime
    toDatetime: DateTime
  ): [HistoricalUNSEvent!]!

  getSpbNodesByMetric(metricNames: [String!]!): [SPBNode!]!
}
```

Rules:

- `getUnsNodes`: MQTT wildcards supported. Empty topics list is invalid.
- `getUnsNodesByProperty`: find nodes whose payload contains those property key names. If `topics` is set and `excludeTopics` is true, those topics are excluded; if false, topics **filter inclusion**.
- `getHistoricEventsInTimeRange`: topics required, non-empty. Time bounds optional.
- `getHistoricEventsByPublishers`: publishers required, non-empty. Topics and time optional.
- `getHistoricEventsByProperty`: propertyKeys required, non-empty. If `binaryOperator` is null, treat as **OR**. Topics / time are always ANDed with the property filter.
- There is **no pagination**. Tables must handle large result sets in the client (virtualize). Do not invent `limit`/`offset` args.

### Subscriptions (all must have UI)

```graphql
type Subscription {
  getMqttMessages(topics: [MQTTTopicInput!]!): MQTTMessage!
  getKafkaMessages(topics: [KAFKATopicInput!]!): StreamingMessage!
}
```

MQTT payload union:

- UNS (and Sparkplug STATE): `JSONPayload`
- Sparkplug B namespace (`spBv1.0/...`): `BytesPayload`

There is **no GraphQL health query**. Connection chip is inferred from HTTP query success vs WebSocket subscription status.

---

## 5. GraphQL documents the UI must implement

### Tree / search

```graphql
query GetUnsNodes($topics: [MQTTTopicInput!]!) {
  getUnsNodes(topics: $topics) {
    nodeName nodeType namespace
    payload { data }
    created lastUpdated
  }
}

query GetUnsNodesByProperty(
  $propertyKeys: [String!]!
  $topics: [MQTTTopicInput!]
  $excludeTopics: Boolean
) {
  getUnsNodesByProperty(
    propertyKeys: $propertyKeys
    topics: $topics
    excludeTopics: $excludeTopics
  ) {
    nodeName nodeType namespace
    payload { data }
    created lastUpdated
  }
}
```

### Historian (three queries)

```graphql
query GetHistoricEventsInTimeRange(
  $topics: [MQTTTopicInput!]!
  $fromDatetime: DateTime
  $toDatetime: DateTime
) {
  getHistoricEventsInTimeRange(topics: $topics, fromDatetime: $fromDatetime, toDatetime: $toDatetime) {
    publisher timestamp topic payload { data }
  }
}

query GetHistoricEventsByPublishers(
  $publishers: [String!]!
  $topics: [MQTTTopicInput!]
  $fromDatetime: DateTime
  $toDatetime: DateTime
) {
  getHistoricEventsByPublishers(
    publishers: $publishers
    topics: $topics
    fromDatetime: $fromDatetime
    toDatetime: $toDatetime
  ) {
    publisher timestamp topic payload { data }
  }
}

query GetHistoricEventsByProperty(
  $propertyKeys: [String!]!
  $binaryOperator: BinaryOperator
  $topics: [MQTTTopicInput!]
  $fromDatetime: DateTime
  $toDatetime: DateTime
) {
  getHistoricEventsByProperty(
    propertyKeys: $propertyKeys
    binaryOperator: $binaryOperator
    topics: $topics
    fromDatetime: $fromDatetime
    toDatetime: $toDatetime
  ) {
    publisher timestamp topic payload { data }
  }
}
```

### Sparkplug

```graphql
query GetSpbNodesByMetric($metricNames: [String!]!) {
  getSpbNodesByMetric(metricNames: $metricNames) {
    topic timestamp seq uuid body
    metrics {
      name alias timestamp datatype isHistorical isTransient isNull
      metadata { isMultiPart contentType size seq fileName fileType md5 description }
      value {
        __typename
        ... on SPBPrimitive { data }
        ... on BytesPayload { data }
        ... on SPBDataSet {
          numOfColumns columns types
          rows { elements { value { data } } }
        }
        ... on SPBTemplate {
          version templateRef isDefinition
          parameters { name datatype value { data } }
        }
      }
    }
  }
}
```

### Live MQTT

```graphql
subscription MqttFeed($topics: [MQTTTopicInput!]!) {
  getMqttMessages(topics: $topics) {
    topic
    payload {
      __typename
      ... on JSONPayload { data }
      ... on BytesPayload { bytesData: data }
    }
  }
}
```

Default subscription topics: `[{ topic: "#" }]`. User may override with custom MQTT filters (see Feed).

### Kafka

```graphql
subscription KafkaFeed($topics: [KAFKATopicInput!]!) {
  getKafkaMessages(topics: $topics) {
    topic
    payload { data }
  }
}
```

Do not subscribe to Kafka until the user submits at least one exact topic.

---

## 6. Example payloads (so UI JSON/trend behavior is correct)

Simulator publishes JSON like:

```json
{
  "timestamp": 1730000000000,
  "Temperature": 75.4,
  "unit": "°C"
}
```

or nested equipment paths. Numeric trend flattening:

- Nested keys joined with `.`
- Arrays as `[i]`
- Dropdown = union of keys whose values are finite numbers across the result set
- Skip events missing the path, non-numeric, or Sparkplug-binary

Sparkplug metric `name` may itself be an ISA-95 path plus tag:

```
Enterprise/Site/Area/Line/Cell/Tag1
```

If a metric name contains `/`, the UI should offer **“Open in UNS tree”**: take all segments except the last as namespace, expand-to that node.

---

## 7. What already exists (v1 — keep, polish, extend)

Existing stack: React + TypeScript + Vite, Tailwind CSS, shadcn-style Button/Badge, React Router, Apollo Client + graphql-ws, Recharts, react-resizable-panels, Vitest.

Routes today: `/` Home, `/explore` Explore.

Shared chrome:

- Title: `Covestro UNS` (from platform config, fallback “Unified Namespace”)
- Subtitle: `CovestroAG · Instance01`
- Nav: Home | Explore
- Connection chip: **Live** | `Degraded — GraphQL queries down` | `Degraded — live feed down` | **Down**

Layout: three **resizable** columns.

| Column | Always | Home `/` | Explore `/explore` |
| --- | --- | --- | --- |
| 1 | ISA-95 tree | same | same |
| 2 | Payload inspector | same | same |
| 3 | Context | Live MQTT feed | Search + historian + trend |

v1 already implements: lazy tree, MQTT patch/insert, feed cap 500, pause drops incoming, Sparkplug badge, search topic/property, historian time range 15m/1h/24h/custom, one numeric line chart.

**v1 gaps you must close as part of full UI:**

- `getUnsNodesByProperty` does not yet pass `excludeTopics`
- Historian only uses `getHistoricEventsInTimeRange` — missing by-publisher and by-property
- No Sparkplug explorer
- No Kafka UI
- MQTT subscription is hardcoded to `#` (full product must allow user topic filter)
- Payload is a raw `<pre>` — full product needs a collapsible JSON inspector (search, copy path, copy JSON)
- No CSV export, bookmarks, stale-node list, topic copy, node-type legend, feed kind filter

---

## 8. Information architecture (full product)

Keep the three-column shell on every operational route. Add routes:

| Route | Nav label | Persona | Purpose |
| --- | --- | --- | --- |
| `/` | Home | Operator | Tree + payload + live MQTT feed |
| `/explore` | Explore | Engineer | Search + historian (all 3 queries) + trends |
| `/sparkplug` | Sparkplug | Engineer | Decoded Sparkplug metric search (`getSpbNodesByMetric`) |
| `/streams` | Streams | Integrator | Kafka live subscription |
| `/alerts` | Alerts | Operator | Stale-node list derived from loaded tree (`lastUpdated` > 5 min) |

Header right side: connection chip. Header left: product name + org · instance.

Optional overflow menu (no new backend):

- Copy selected namespace
- Bookmark selected namespace (localStorage)
- Open GraphQL in new tab: `http://localhost:8000/graphql` (dev) — label “GraphQL IDE”
- Keyboard shortcuts cheat sheet

Do **not** add: Login, Users, Billing, OEE, Grafana embed, Settings that write `settings.yaml`, simulator start/stop (no API).

---

## 9. Visual design system

Dark industrial control-room, not a colorful SaaS landing page. Dense, high-contrast, monospace for topics/JSON, sans for UI chrome.

Tokens (already in the app — keep):

```
bg:      #0b0f14
panel:   #121821
border:  #243040
text:    #e6edf3
muted:   #8b9bb0
accent:  #3dd6c3   (live, selected, trend line)
warn:    #e3b341
danger:  #e85d5d
```

Rules:

- Full viewport height, no page scroll on the shell; panes scroll internally
- 12px–13px body, 11–12px tables/feed, 11px uppercase section labels
- Selected tree row: accent at 15% fill
- Stale node: 50% opacity (not an alarm color unless it also appears on Alerts)
- Sparkplug badge: warn/neutral, text **Sparkplug B (binary)**
- Live chip: accent. Degraded: warn. Down: danger.
- Focus rings visible for keyboard users
- Do not use purple/pink consumer-app palettes
- Charts: one accent line; optional second series in warn. No rainbow multi-series unless user picks 2–3 numeric paths
- Empty states are instructional one-liners, not illustrations

---

## 10. Feature catalog (implement all of these)

Legend: **A** = existing GraphQL, **U** = UI-only on data already in the client, **N** = needs new GraphQL — **do not fake**.

### 10.1 Shell and connection

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| S1 | Product chrome | U | Display name, organization, instance |
| S2 | Nav | U | Home, Explore, Sparkplug, Streams, Alerts. Active route accent |
| S3 | Connection chip | A | HTTP ok from queries; WS ok from MQTT (and Kafka when that tab is subscribed). Live = both ok. Degraded = one down, label which. Down = both down |
| S4 | Tree load banner | A | First tree HTTP failure: banner “Can't reach GraphQL” + Retry. Tree empty |
| S5 | Missing prod URL | U | Blocking page with the error, not a spinner |
| S6 | Resizable columns | U | Tree / payload / context. Persist sizes in localStorage |
| S7 | Shortcuts | U | `/` focus search (on Explore), `Esc` clear historic inspector, `Space` pause feed on Home |

### 10.2 ISA-95 tree (column 1, all operational routes)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| T1 | Lazy roots | A | On mount: `getUnsNodes(topics: [{ topic: "+" }])` |
| T2 | Lazy expand | A | Expand N: `getUnsNodes(topics: [{ topic: "{namespace}/+" }])`. Cache children. Collapse does not discard cache |
| T3 | Row content | A | `nodeName`, `nodeType`, relative `lastUpdated` |
| T4 | Stale dim | U | Dim if `lastUpdated` older than 5 minutes |
| T5 | Select | U | Click row → selected namespace, center shows that node’s payload, clears historic overlay |
| T6 | Live patch | A | If MQTT UNS topic equals a loaded node namespace, patch payload + lastUpdated + brief highlight |
| T7 | Live insert | A | If parent(topic) is **expanded** and child missing, insert UNS leaf. Do not auto-expand. Do not GraphQL-fetch for that insert |
| T8 | Never SPB in tree | A | Topics starting `spBv1.0/` never enter the tree |
| T9 | Expand error | A | Error on that branch only; retry on chevron |
| T10 | Empty | U | “No nodes yet — waiting for GraphQL / UNS data.” |
| T11 | Expand-to | A | From search, feed click, Sparkplug metric, bookmark, or Alerts: walk path segments; for each missing prefix query `{prefix}/+` (and `+` for first) until target is in cache; then select |
| T12 | Copy topic | U | Context / icon copies namespace to clipboard |
| T13 | Type legend | U | Small hint: ENTERPRISE → DEVICE |
| T14 | Keyboard | U | Arrow keys move selection among visible rows; Right expands; Left collapses |

### 10.3 Payload inspector (column 2)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| P1 | Node view | A | Full namespace, type, created, lastUpdated, JSON |
| P2 | Empty selection | U | “Pick a node in the tree.” |
| P3 | Empty payload | U | “No payload.” |
| P4 | Historical overlay | A | Clicking a historian row: label **Historical event**, show topic · timestamp · publisher + that event JSON. Tree selection stays. Next tree click restores node payload |
| P5 | JSON inspector | U | Collapsible tree, search keys, copy JSON, copy JSON-path (dot notation) |
| P6 | Invalid JSON | U | Live feed may be invalid; inspector says “invalid JSON” rather than crashing |

### 10.4 Live MQTT feed (Home column 3)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| F1 | Default sub | A | `getMqttMessages(topics: [{ topic: "#" }])` while app is open |
| F2 | Custom MQTT filter | A | Input for topic filters (comma-separated, wildcards allowed). Submit resubscribes. Hint: MQTT `+` and `#` |
| F3 | Follow selection | A | Toggle: when on, resubscribe to `{selected}/#` (and selected exact). Off = keep `#` or custom. Selecting a node does **not** resubscribe unless this toggle is on |
| F4 | Ring buffer | U | Newest first, cap **500**, drop oldest |
| F5 | Pause | U | Do not append. Incoming while paused are **dropped** (not queued). Historian is catch-up |
| F6 | Autoscroll | U | Pin to newest edge; disable when user scrolls away |
| F7 | Row | A | Timestamp, topic, UNS JSON preview **or** Sparkplug badge **or** “invalid JSON” |
| F8 | Highlight | U | If topic equals selected namespace or is under it, highlight row |
| F9 | Click UNS row | A | Expand-to that topic if it is a UNS path |
| F10 | Click Sparkplug row | U | Does **not** change the tree |
| F11 | Kind filter | U | Toggles: All / UNS only / Sparkplug only (client filter on buffer) |
| F12 | Empty | U | “No messages yet.” |
| F13 | WS drop | A | Chip Down/Degraded; feed stops; tree/payload stay; reconnect with backoff; **no backfill** of missed live messages |

### 10.5 Search (Explore)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| Q1 | Fields | A | MQTT topic (wildcards) and/or property keys (comma/whitespace separated) |
| Q2 | No query until submit | A | At least one criterion. Hint: “Enter a topic or property.” |
| Q3 | Topic only | A | `getUnsNodes(topics)` |
| Q4 | Keys only | A | `getUnsNodesByProperty(propertyKeys)` |
| Q5 | Both include | A | `getUnsNodesByProperty(propertyKeys, topics, excludeTopics: false)` — **one call**, do not merge two result sets |
| Q6 | Exclude topics | A | Checkbox “Exclude these topics”. `excludeTopics: true` with topics + keys |
| Q7 | Zero hits | U | “No nodes match.” |
| Q8 | Match list | A | namespace, type, lastUpdated. Click → expand-to, select, set historian topic |
| Q9 | HTTP error | A | “Can't reach GraphQL” |

### 10.6 Historian (Explore)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| H1 | Topic scope | A | Selected namespace with `#` so children are included, e.g. `CovestroAG/Dormagen/#`. Allow override text field |
| H2 | Time presets | U | 15m, 1h, 24h, custom. Block query if `from > to`. Copy: “From must be before to.” |
| H3 | Mode: Time range | A | `getHistoricEventsInTimeRange` |
| H4 | Mode: Publishers | A | Text field (comma-separated client ids). `getHistoricEventsByPublishers`. Topics and time still applied when set |
| H5 | Mode: Properties | A | Property keys + operator OR/AND/NOT. `getHistoricEventsByProperty`. Topics and time ANDed |
| H6 | Table | A | timestamp, topic, publisher, payload preview (truncate ~80 chars). Virtualize if large |
| H7 | Click row | U | Historical event in center inspector |
| H8 | Empty | U | “No events in this range.” Hide chart |
| H9 | HTTP error | A | Empty table message; no chart |
| H10 | CSV export | U | Download loaded rows (timestamp, topic, publisher, payload JSON) |
| H11 | No pagination API | N | Do not add fake paging controls that call non-existent args. Client virtualize only |

### 10.7 Trends (Explore)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| R1 | Numeric paths | U | Flatten JSON leaves; dropdown of numeric paths |
| R2 | Line chart | U | Recharts over the loaded time range |
| R3 | Multi-select up to 3 paths | U | Overlay up to 3 lines; skip missing/non-numeric |
| R4 | No numeric fields | U | Table only, hide chart |
| R5 | Sparkplug-binary events | U | Skip |

### 10.8 Sparkplug explorer (`/sparkplug`)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| SP1 | Search | A | Metric name(s), comma-separated. Submit → `getSpbNodesByMetric` |
| SP2 | Results | A | List of SPBNode: topic, timestamp, seq, uuid |
| SP3 | Metrics table | A | name, alias, datatype, timestamp, historical/transient/null, value (primitive string, or “binary” / dataset / template) |
| SP4 | Dataset | A | Render columns/rows if value is SPBDataSet |
| SP5 | Template | A | Show version, templateRef, parameters |
| SP6 | Body | U | If `body` present, show “binary payload” + length, not a JSON dump of protobuf |
| SP7 | Open in tree | A | If metric name looks like ISA-95 (`/` in name), expand-to parent namespace on the shared tree |
| SP8 | Empty | U | “Enter a Sparkplug metric name.” / “No Sparkplug nodes match.” |
| SP9 | Live SPB still | A | Live feed continues to show Sparkplug as badge only; this page is the decoded GraphDB view |

### 10.9 Kafka streams (`/streams`)

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| K1 | Topic input | A | Exact Kafka topic(s), comma-separated. No wildcards. Validate: reject `+` `#` `*` |
| K2 | Subscribe | A | `getKafkaMessages` only after submit |
| K3 | Feed | A | Newest first, cap 500, pause drops, JSON preview from `StreamingMessage.payload.data` |
| K4 | Inspector | U | Click row → JSON in a pane (or reuse column 2 with a “Kafka message” label, tree selection unchanged) |
| K5 | Empty | U | “Enter a Kafka topic (no wildcards).” |
| K6 | Error | A | Show subscription error; chip reflects WS |

### 10.10 Alerts (`/alerts`) — UI-only

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| A1 | Stale list | U | Loaded tree nodes with `lastUpdated` > 5 minutes. Columns: namespace, type, lastUpdated, age |
| A2 | Click | A | Expand-to + select |
| A3 | Empty | U | “No stale nodes in the loaded tree.” (lazy tree: only **loaded** nodes) |
| A4 | Not a backend alarm | U | Copy: “Based on loaded nodes only. Expand the tree to include more.” |

### 10.11 Bookmarks and utilities

| ID | Feature | Type | Behavior |
| --- | --- | --- | --- |
| B1 | Bookmark | U | Star on selected node; list in a small popover; persist localStorage key `uns.bookmarks` |
| B2 | Click bookmark | A | Expand-to |
| B3 | Copy | U | Copy namespace / topic |
| B4 | Relative time | U | Tree and feed use relative time; tooltip shows ISO |

### 10.12 Explicitly out of scope (do not design screens for these)

| Item | Why |
| --- | --- |
| Login / SSO / RBAC | GraphQL pending; no API |
| OEE / KPI scorecards | No aggregation API; do not invent |
| Grafana / BFF | Not in architecture |
| Historian server-side pagination | Not in schema |
| Mobile-first / i18n | Not this version |
| Playwright against live stack | Optional later |
| Simulator start/stop from UI | No API |
| MQTT/Neo4j/Kafka admin | Use those products’ UIs |
| Write/setpoint/commands | Mapper is not a host |
| Health of MQTT/Neo4j/Timescale as green/red services | Healthcheck is a Docker script, not GraphQL. Connection chip only |

---

## 11. Data-flow rules (implement exactly)

### Tree load

1. Mount → `getUnsNodes([{ topic: "+" }])`
2. Expand `namespace` → `getUnsNodes([{ topic: "{namespace}/+" }])`
3. Expand-to `a/b/c` → ensure `+`, then `a/+`, then `a/b/+` until `a/b/c` is cached, then select

GraphQL returns a **flat** `UNSNode[]`. Client builds parent/child from `namespace` path segments and `nodeType`.

### Live MQTT → tree + feed

On each `MQTTMessage`:

1. If paused → drop entirely
2. Else append to feed buffer (drop oldest if > 500)
3. If topic starts with `spBv1.0/` → feed row as Sparkplug badge, **stop** (no tree)
4. If payload JSON parse fails → feed row “invalid JSON”; no tree
5. If topic equals a loaded node → patch that node
6. Else if `parent(topic)` is expanded and child missing → insert UNS leaf from payload

Missed messages after WS drop are **not** backfilled. Engineer uses historian.

### Search mapping

| User input | Call |
| --- | --- |
| topic only | `getUnsNodes` |
| keys only | `getUnsNodesByProperty(keys)` |
| topic + keys, exclude off | `getUnsNodesByProperty(keys, topics, false)` |
| topic + keys, exclude on | `getUnsNodesByProperty(keys, topics, true)` |

### Historian topic

Selected namespace `ns` → default topic `ns/#`. User may edit.

---

## 12. Required English copy (use verbatim)

- Product fallback: `Unified Namespace`
- Empty tree: `No nodes yet — waiting for GraphQL / UNS data.`
- Empty feed: `No messages yet.`
- Search hint: `Enter a topic or property.`
- Zero search hits: `No nodes match.`
- Empty historian: `No events in this range.`
- API down: `Can't reach GraphQL.`
- Historical inspector: `Historical event`
- Sparkplug badge: `Sparkplug B (binary)`
- Invalid JSON: `invalid JSON`
- Missing payload: `No payload.`
- Empty payload pane: `Pick a node in the tree.`
- Pause / Resume
- Kafka empty: `Enter a Kafka topic (no wildcards).`
- Sparkplug empty: `Enter a Sparkplug metric name.`
- Custom range: `From must be before to.`
- Prod missing URL: clear blocking message that `VITE_GRAPHQL_URL` is required
- Alerts empty: `No stale nodes in the loaded tree.`
- Alerts footnote: `Based on loaded nodes only. Expand the tree to include more.`

Nav: `Home` `Explore` `Sparkplug` `Streams` `Alerts`

Historian modes: `Time range` `Publishers` `Properties`

Operators: `OR` `AND` `NOT`

---

## 13. Existing frontend module layout (extend, do not replace)

```
10_frontend/src/main.tsx
10_frontend/src/App.tsx
10_frontend/src/app/UnsProvider.tsx          # app state
10_frontend/src/app/uns-reducer.ts
10_frontend/src/app/connection.ts             # Live / Degraded / Down
10_frontend/src/lib/graphql/operations.ts     # add the missing documents
10_frontend/src/lib/uns/sparkplug.ts         # spBv1.0/ detection
10_frontend/src/lib/uns/topics.ts            # parent, +, #, highlight
10_frontend/src/lib/uns/stale.ts            # 5 minute rule
10_frontend/src/features/shell/AppShell.tsx
10_frontend/src/features/shell/ConsoleHeader.tsx
10_frontend/src/features/tree/
10_frontend/src/features/payload/
10_frontend/src/features/feed/
10_frontend/src/features/explore/
```

Add feature folders: `sparkplug/`, `streams/`, `alerts/`. Keep domain logic in pure TS modules with unit tests.

---

## 14. Error handling matrix

| Situation | UI |
| --- | --- |
| First tree HTTP failure | Banner “Can't reach GraphQL”, retry, empty tree |
| WebSocket drop | Chip Down or Degraded; feed stops; reconnect backoff; no live backfill |
| HTTP down, WS up (or reverse) | Degraded; name which half |
| Expand failure | Error on that branch; retry on chevron |
| Historian HTTP error | Empty table message; no chart |
| Sparkplug query error | Message on Sparkplug page; tree unaffected |
| Kafka subscribe error | Message on Streams; do not crash Home feed |
| Missing prod `VITE_GRAPHQL_URL` | Blocking startup error |

---

## 15. Tech stack (keep)

| Piece | Choice |
| --- | --- |
| App | React + TypeScript, existing Vite app |
| Style | Tailwind + current console tokens + shadcn-style primitives |
| Routing | React Router: `/` `/explore` `/sparkplug` `/streams` `/alerts` |
| GraphQL | Apollo Client + graphql-ws |
| Charts | Recharts |
| Tables | Client virtualization for historian/feed (e.g. tanstack-virtual or equivalent already in spirit of dense lists) |
| Auth | None |
| Tests | Vitest + Testing Library; **mock GraphQL**; no real MQTT/Neo4j/Timescale |

---

## 16. Testing (required with the UI)

Mock GraphQL. No live broker in frontend tests.

Unit:

- Flat `UNSNode[]` → children by parent path
- MQTT patch vs insert-under-expanded-parent
- Sparkplug topics never enter tree
- Numeric leaf-path flattening
- Feed ring buffer cap 500; pause drops incoming
- Historian mode → which operation is called
- Kafka topic validation rejects wildcards
- Metric name → UNS namespace (drop last segment)

Component:

- Feed row: UNS preview vs Sparkplug badge vs invalid JSON
- Match-list click sets selection / historian topic
- Historian empty and error states
- Sparkplug empty/error
- Kafka empty before subscribe
- Connection chip labels

---

## 17. Definition of done

The full console is done when:

1. Operator opens `/`, expands ISA-95 level by level, sees payload, watches MQTT `#` (or a custom filter) with pause/highlight, no login.
2. Selecting a node highlights matching feed rows and does not resubscribe unless **Follow selection** is on.
3. Live messages update visible tree nodes; new children appear only under expanded parents; Sparkplug never appears in the tree.
4. Engineer searches by topic and/or property (including exclude), lands on the node in the tree, runs historian by **time**, **publisher**, and **property (OR/AND/NOT)**, exports CSV, and trends up to 3 numeric paths.
5. Sparkplug page lists decoded `SPBNode` metrics; live feed still shows Sparkplug as a badge only.
6. Integrator subscribes to exact Kafka topics and inspects JSON.
7. Alerts lists stale **loaded** nodes and can expand-to them.
8. All six Query fields and both Subscriptions are used by the UI.
9. Dev works with Vite proxy to `:8000`; prod requires `VITE_GRAPHQL_URL`.
10. Copy strings match section 12. Dark industrial tokens unchanged in spirit.

---

## 18. Deliverable from you (the external tool)

Produce, in this order:

1. **Screen designs / layouts** for Home, Explore, Sparkplug, Streams, Alerts (desktop 1440×900), including empty, live, and error states.
2. **Component inventory** (tree row, feed row, JSON inspector, historian toolbar, chips, badges).
3. **If you generate code:** implement in the spirit of `10_frontend` (React + TS + Tailwind + Apollo). Prefer a complete SPA that an engineer can drop into `10_frontend/src`.
4. **If you generate a prompt or spec only:** keep every feature ID in section 10; do not collapse Kafka/Sparkplug/historian-by-publisher into “nice to have”.

Do not omit Sparkplug, Kafka, historian-by-publisher, historian-by-property, excludeTopics, follow-selection MQTT filter, JSON inspector, CSV export, bookmarks, or alerts to “keep it simple”. Those are the full product.

Start now.
