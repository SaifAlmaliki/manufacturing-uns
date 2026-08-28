# Unified Namespace Frontend (v1)

Date: 2026-08-28  
Status: Approved for implementation planning  
Module: `10_frontend`  
Depends on: `07_uns_graphql`

## Goal

Turn the Vite + TypeScript scaffold in `10_frontend` into a desktop-first, dark industrial console for the Unified Namespace.

Two personas share one app:

- **Operators** use Home: ISA-95 tree, current payload, live MQTT feed.
- **Engineers** use Explore: the same tree and payload inspector, plus topic/property search, historian table, and an optional numeric trend.

v1 is a React SPA that talks only to the existing GraphQL API. No login. No OEE/KPI cards. No Sparkplug decode in the browser.

## Non-goals (v1)

- Authentication, roles, or SSO
- OEE or other KPI dashboards
- Decoding Sparkplug B protobuf in the browser
- Kafka subscriptions
- Grafana or a BFF
- Serving the UI from FastAPI static files
- Changing the live subscription away from `#`
- Replacing or filtering the left tree from search
- Historian pagination
- Mobile-first layout or i18n
- Playwright / live-stack E2E

## Architecture

```
Browser (10_frontend, React + Vite)
    HTTP  →  POST /graphql     queries (tree, search, historian)
    WS    →  /graphql          subscription getMqttMessages(["#"])
                    ↓
         07_uns_graphql (FastAPI + Strawberry)
                    ↓
         Neo4j | TimescaleDB | MQTT broker
```

The browser must not connect to MQTT, Neo4j, Timescale, or Kafka directly.

### Stack

| Piece | Choice |
| --- | --- |
| App | React + TypeScript in existing Vite app |
| Styling | Tailwind CSS + shadcn/ui, dark industrial theme |
| Routing | React Router: `/` Home, `/explore` Explore |
| GraphQL client | Apollo Client + `graphql-ws` |
| Types | GraphQL Code Generator from the live schema |
| Charts | Recharts |
| Auth | None (trusted plant / VPN network) |

### How the UI reaches GraphQL

**Development**

- GraphQL server: `http://localhost:8000/graphql` (docker-compose `graphql_server` already publishes `8000`).
- Vite proxies `/graphql` (HTTP and WebSocket) to `localhost:8000`.
- Client uses a relative URL `/graphql` so the proxy is used.

**Production / docker-compose**

- Add CORS (and confirm GraphQL WebSocket) on `07_uns_graphql`.
- Frontend reads `VITE_GRAPHQL_URL` (absolute URL of the GraphQL HTTP/WS endpoint).
- Frontend is a **separate** static site / container (nginx or equivalent serving the Vite build). Do not bundle the UI into the FastAPI process.
- Add a `10_frontend` Dockerfile and a `docker-compose` service.

**Startup failure:** a production build with missing `VITE_GRAPHQL_URL` must show a clear error, not a blank screen.

### Backend changes in v1

Required:

- CORS on the GraphQL FastAPI app for the Vite origin (dev) and the compose UI origin (prod).
- GraphQL subscriptions over WebSocket on the same `/graphql` path (Strawberry `GraphQLRouter`; enable/confirm `graphql-transport-ws` or `graphql-ws` as used by Apollo).

Not in v1:

- No new GraphQL types or queries. Tree load uses existing `getUnsNodes` with MQTT `+` wildcards.

## Screens and shell

Shared chrome on both routes:

- Header: product name “Unified Namespace”, nav **Home** | **Explore**, connection chip (Live / Degraded / Down).
- Three **resizable** columns, desktop-first.

### Column 1 — ISA-95 tree (always)

- Lazy load by level. Never query `#` for the tree.
- First load: `getUnsNodes(topics: ["+"])` → enterprise roots.
- Expand node `N`: `getUnsNodes(topics: ["{N.namespace}/+"])` → children only.
- Cache children by parent namespace. Collapse does not discard cache.
- Each row: `nodeName`, `nodeType` (ENTERPRISE, FACILITY, AREA, LINE, DEVICE, …), relative `lastUpdated`.
- Dim a node if `lastUpdated` is older than 5 minutes (display only, not an alert).
- Live MQTT patches **already loaded UNS** nodes (payload, `lastUpdated`, brief highlight).
- If a **UNS** message is a **new child** under an **already expanded** parent, insert that leaf. Do not auto-expand. Do not GraphQL-fetch for that insert.
- **Never** insert Sparkplug B topics (`spBv1.0/...`) into the tree. They appear only in the live feed.
- Empty: “No nodes yet — waiting for GraphQL / UNS data.”

### Column 2 — Payload (always)

- Selected **tree** node: full namespace path, type, created, last updated, JSON inspector (`payload`). Tree nodes are UNS only.
- If the center is showing a **historical event** (engineer clicked a historian row), label it “Historical event” and show that event’s JSON; tree selection stays. A later tree click restores the node payload.
- Empty selection: prompt to pick a node.
- Empty/missing payload: “No payload.”

### Column 3 — Context (by route)

**Home `/` — live feed**

- App-wide subscription: `getMqttMessages(topics: ["#"])` while the app is open (both routes).
- Newest first. Ring buffer cap **500**. Drop oldest.
- **Pause:** do not append. Incoming messages while paused are dropped (not queued). Historian is the catch-up path.
- Autoscroll when pinned to the newest edge.
- Row: timestamp, topic, UNS JSON preview **or** Sparkplug B badge.
- Malformed UNS JSON: still show topic/time + “invalid JSON”.
- Selecting a tree node **does not** change the subscription. Matching feed rows (topic equals selected namespace, or is under it) are highlighted.
- Clicking a UNS feed row selects that node in the tree if it is already loaded (or expands to it like search). Clicking a Sparkplug row does not change the tree.

**Explore `/explore` — search + historian**

- Search fields: MQTT topic (wildcards allowed) and/or property keys.
- Do not query until the user submits at least one criterion. Hint: “Enter a topic or property.”
- Search mapping (one GraphQL call, one match list of namespace, type, last updated):
  - Topic only → `getUnsNodes(topics)`.
  - Property keys only → `getUnsNodesByProperty(propertyKeys)`.
  - Both → `getUnsNodesByProperty(propertyKeys, topics)` (topics filter the property search; do not merge two result sets).
- Zero hits: “No nodes match.”
- Click a match: expand ancestors in the **existing** tree (level-by-level `+/` queries) until the node is present, select it, load payload, set historian topic. **Do not replace or filter the left tree.**
- Historian topic: selected namespace with a multi-level wildcard so child events are included, e.g. `ent/fac/line/#`.
- Time range presets: 15m, 1h, 24h, custom. Block query if `from > to`.
- Query: `getHistoricEventsInTimeRange(topics, fromDatetime, toDatetime)`.
- Table of events (timestamp, topic, publisher, payload preview). Click a row → show that event’s JSON in the center inspector, labeled “Historical event”; do not change tree selection.
- Empty range: “No events in this range”; hide chart.
- Trend: flatten JSON payloads to numeric leaf paths; user picks a path from a dropdown; Recharts line over the time range. Skip events that lack that path or are non-numeric / Sparkplug-binary. If no numeric fields exist, table only.

## Data flow

### Tree

1. Mount → `getUnsNodes(["+"])`.
2. Expand `namespace` → `getUnsNodes(["{namespace}/+"])`.
3. Search deep-link → walk path segments; for each prefix that is not loaded, query `{prefix}/+` (and `+` for the first segment) until the target namespace is in cache; then select it.

GraphQL returns a flat list of `UNSNode` (`nodeName`, `nodeType`, `namespace`, `payload`, `created`, `lastUpdated`). The client builds the tree from `namespace` path segments and `nodeType`.

### Live MQTT → tree

On each `MQTTMessage`:

1. If paused, drop. Else append to the feed buffer (drop oldest if over 500).
2. If the topic is Sparkplug B, stop after the feed row (badge, no JSON). Do not touch the tree.
3. If `topic` equals a loaded node’s `namespace`, patch that node.
4. Else if `parent(topic)` is expanded and the child is missing, insert a UNS leaf from the message payload.

### Historian trend

Flatten each event `payload` object: nested keys joined with `.` (and `[i]` for arrays). Collect keys whose values are finite numbers. Union of keys across the result set = dropdown options.

## Error handling

| Situation | UI |
| --- | --- |
| First tree HTTP failure | Banner “Can’t reach GraphQL”, retry, empty tree |
| WebSocket drop | Chip Down; feed stops; tree/payload stay; reconnect with backoff; chip Live when `#` resumes. **No backfill** of missed live messages |
| HTTP down, WS up (or reverse) | Chip Degraded; name which half is down |
| Expand failure | Error on that branch only; retry on chevron |
| Historian HTTP error | Empty table message; no chart |
| Missing prod `VITE_GRAPHQL_URL` | Blocking startup error |

Missed live messages after a WS drop are recovered by the engineer via historian, not by the feed.

## Frontend module layout (target)

Evolve `10_frontend` (do not start a second app):

- `src/main.tsx` — React mount
- `src/App.tsx` — router + shell
- `src/lib/graphql/` — Apollo client, generated types, operations
- `src/features/tree/` — lazy tree, cache, MQTT patch/insert
- `src/features/payload/` — JSON inspector + Sparkplug badge
- `src/features/feed/` — ring buffer, pause, highlight
- `src/features/explore/` — search match list, historian table, trend
- `src/components/ui/` — shadcn primitives
- Vite `server.proxy` for `/graphql`

Remove the Vite counter demo (`counter.ts`, starter hero).

## Testing

Mock GraphQL. No real MQTT/Neo4j/Timescale in frontend tests.

**Unit**

- Flat `UNSNode[]` → child lists by parent path
- MQTT patch vs insert-under-expanded-parent rules
- Numeric leaf-path flattening
- Feed ring buffer (cap 500; pause drops incoming)

**Component**

- Feed row: UNS preview vs Sparkplug badge
- Match-list click sets selected topic / historian topic
- Historian empty and error states

Playwright against a live stack is out of v1.

## Success criteria

v1 is done when:

1. An operator can open `/`, expand the namespace level by level, see a payload, and watch `#` MQTT traffic in the right pane without logging in.
2. Selecting a node highlights matching feed rows and does not resubscribe.
3. Live messages update visible tree nodes; new children appear only under expanded parents.
4. An engineer can search by topic and/or property, click a hit, land on that node in the tree, and browse historian events for a time range, with a numeric trend when a numeric field is chosen.
5. Sparkplug B live rows never appear as JSON.
6. Dev works with Vite proxy to `:8000`; compose can serve the built UI against GraphQL with CORS.

## Implementation notes

- Strawberry field names on the wire are camelCase: `getUnsNodes`, `getUnsNodesByProperty`, `getHistoricEventsInTimeRange`, `getMqttMessages`.
- MQTT `+` is one level; `#` is multi-level. Tree uses `+` only. Feed and historian child-inclusion use `#`.
- Treat a topic as Sparkplug B if it starts with `spBv1.0/` (same prefix the GraphQL layer uses).
- Compose already exposes GraphQL on port 8000 (`graphql_server`).
- Document run steps in `10_frontend/README.md`.
