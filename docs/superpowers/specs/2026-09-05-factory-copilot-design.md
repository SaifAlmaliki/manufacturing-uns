# Factory Copilot (read-only plant colleague)

Date: 2026-09-05
Modules: `13_uns_factory_agent` (new), `11_frontend` (header drawer), `11_frontend/nginx.conf`,
`11_frontend/vite.config.ts`, `docker-compose.yml`, `conf` (settings + secrets key)
Status: Draft for review
UI skill: `frontend-design` (control-desk radio). Console chrome stays `console-compact-layout`.

Factory Copilot is a **person**: a read-only colleague operators and engineers talk to in
text. He looks up live plant state, alarms, the Asset Model, and Historic Events, then
answers. He never writes. The brain is a **separate container** so it can scale without
scaling the console.

## 1. Problem

The console already shows current UNS Nodes, Historic Events, Alert Rules, and the Asset
Model. An operator still has to know which page, which topic, and which time window. There
is no colleague who can take “what happened on Furnace Cold Line last shift?” and turn it
into a query.

The agent must stay modular. Putting the model loop inside GraphQL or the static console
bundle would couple scale, secrets, and UI. GraphQL remains the live/alarm query surface
(ADR-0005, ADR-0009). Timescale remains the history surface (ADR-0002). Postgres remains
the Asset Model (ADR-0003). Access Groups stay in the Asset Model (ADR-0010).

## 2. Goals

- Anyone signed into the console can open Factory Copilot from **any** protected page.
- He answers in text from **live** UNS Nodes, **active alarms / Alert Rules**, the **Asset
  Model**, and **Timescale** Historic Events / Metrics / downtime (including last shift).
- A question becomes one or more **tool calls** (generated `SELECT` or GraphQL), then a
  cited answer. He does not invent numbers.
- The agent process is `13_uns_factory_agent`, its own Compose service, stateless replicas.
- Page context (route, Asset path, Metric Key, alarm topic) goes with every turn.
- The drawer is a distinctive **control-desk radio**, not a generic chatbot panel. It still
  belongs on this console (Oxanium, IBM Plex Mono, existing tokens). Implementation of the
  drawer follows the `frontend-design` skill.

## 3. Non-goals

- No writes: no ack, no Alert Rule edits, no Asset Model edits, no simulator control.
- No second frontend app and no new console route. Not `#/copilot`.
- No MQTT, Kafka, or Grafana tools.
- No local/Ollama model in this slice. Hosted OpenAI-compatible API only.
- No server-side chat history. The browser keeps the thread. Replicas forget the turn.
- No Cypher. Live current state is GraphQL → Neo4j, not a fifth tool.
- No “how the platform is built” documentation agent.
- No sticky sessions, no agent-owned database.

## 4. Architecture

```
Browser (any #/… console page)
    → FactoryCopilotDrawer  (page context + Bearer token)
    → uns_frontend nginx or vite  /agent/*
    → factory_agent replica  (13_uns_factory_agent)
         → hosted model (OpenAI-compatible)
         → query_asset_model     Postgres schema `model`   SELECT, allowlisted
         → query_historian       Timescale                 SELECT, allowlisted
         → query_live            graphql_server            caller token
         → query_alarms          graphql_server            caller token
```

`factory_agent` publishes no host port in Compose. The console origin is the only door,
same as the simulator control API. `npm run dev` proxies `/agent` like `/graphql`.

Config follows existing modules: `UNS_MODULE=13_uns_factory_agent`, `conf/settings.yaml`,
API key in `conf/.secrets.yaml` (never in the image or the browser). A read-only database
role runs SQL. GraphQL tools send the caller’s Bearer token; they do not use a service
account.

The container listens on `/health` and `/chat`. Nginx and vite map `/agent/` → `/`, so the
browser calls `/agent/chat` and `/agent/health`. Compose healthchecks `GET /health` on the
container network. Missing model key or DB/GraphQL unreachability makes health
degraded/red.

## 5. Him

UI title: **Factory Copilot**. He speaks first person, short sentences, plant English.
He cites Asset, topic, and time. Empty tools → he says he cannot see it. He refuses any
request to change the plant. Suggested empty-state jobs:

- What is in alarm on the Asset I am looking at?
- Last-shift Historic Events / downtime for this line.
- Current Metric value versus the last eight hours.

He is available to every signed-in Console Role. Access Groups still hide rows. `admin`
is unscoped, same as GraphQL.

## 6. UI (frontend-design)

**Direction: control-desk radio.** He is a colleague on the plant radio, not a SaaS chat
bubble. The memorable thing is the **nameplate + live lamp + stamped citations**.

### 6.1 Placement

- Header control on every protected page, left of Bookmarks, `aria-label="Factory Copilot"`.
- Opens a right-hand bay, same mount as `BookmarksDrawer` / `StaleNodesDrawer` in
  `AppLayout` (overlay + panel). Wider than bookmarks: `max-w-xl` (36rem), full height.
- No new `getPageHeading` title. No `PageToolbar`. The page behind stays as it is.
- Escape and the nameplate close control dismiss the bay.

### 6.2 Look

Stay on console fonts and tokens. Do not add Inter, purple gradients, or a second type
system.

| Part | Treatment |
|---|---|
| Nameplate | `FACTORY COPILOT` in Oxanium, wide tracking, like a riveted label. A 2px amber lamp (`#FF7A00`) pulses while a turn is in flight; solid when idle; muted red when unavailable. |
| Page context | One stamped chip under the nameplate: route + Asset path or Metric Key or alarm topic. Mono. If nothing is selected, `Plant · no Asset selected`. |
| His speech | Oxanium, left rail, no avatar circle. A thin orange tick on the left edge marks his turns. |
| Your speech | Right-aligned, quieter surface, no tick. |
| Citations | Ticket row under his answer: `Asset · topic · time · source` in IBM Plex Mono. `source` is `model`, `historian`, `live`, or `alarms`. Tickets are rectangular, inset, not pills. |
| Job cards | Empty state: 2×2 stamped cards (not rounded SaaS chips). Copy is a real question, not a feature name. |
| Composer | Bottom **handset bar**: full width, `Message Factory Copilot…`, send is a hardware-style key (not a paper plane on a gradient). Enter sends; Shift+Enter newline. |
| Thread | Browser `sessionStorage` keyed by conversation id. **New conversation** clears the bay. No server transcript. |

Light and dark both use theme tokens (`background`, `surface`, `border`, `#FF7A00`). The
bay is `instrument-grain` / existing overlay language, not `bg-white` leftovers.

Motion: one slide-in from the right (existing drawer duration). Lamp pulse is the only
loop. Do not sprinkle bounce on every bubble.

### 6.3 Files

New under `11_frontend/src/components/copilot/`:

- `FactoryCopilotDrawer.tsx` — bay, thread, composer, job cards
- `FactoryCopilotButton.tsx` — header control
- `copilotContext.ts` — page context from route + current selection
- tests beside them

Reuse `consoleTokens` and the overlay/panel classes. Do not clone Bookmarks markup into a
second generic drawer.

Context sources (read, do not invent a parallel store): current route; Condition
Monitoring / tree selection; Alarm Management selected alarm topic; Hierarchy selected
Asset path. If a page has no selection, send route only.

## 7. Tools

He has exactly four tools. No others.

| Tool | Store | Allowlist / API | Answers |
|---|---|---|---|
| `query_asset_model` | Postgres `model` | `asset`, `metric_definition`, Access Group tables | What exists, names, Metric Definitions |
| `query_historian` | Timescale | `unifiednamespace`, `uns_metrics`, `oee.downtime_event` (and OEE shift views if present) | Last shift, downtime, Historic Events, Metrics |
| `query_live` | GraphQL | Current UNS Node queries the console already uses | What is publishing **now** |
| `query_alarms` | GraphQL | `getAlertRules` plus the same active-alarm projection the console uses | Active alarms, Alert Rules |

SQL tools:

- One statement. Must be a single `SELECT` (or `WITH … SELECT`).
- Reject `INSERT` / `UPDATE` / `DELETE` / `DDL` / multiple statements.
- Statement timeout 5s. Hard row cap 200.
- Before execute: load Access Group roots for `Identity.subject`. Wrap with path/topic
  filters so a non-admin cannot read outside those prefixes. Unmodelled topics stay
  admin-only (ADR-0010). `admin` skips the wrap.
- Run as a read-only DB role. The model never sees the password.

GraphQL tools forward the caller Bearer token. Access Groups are GraphQL’s job.

Schema cards are curated at boot (columns that matter per allowlisted table / query), not
a raw `information_schema` dump each turn.

**Last shift:** if an OEE shift calendar row exists, the previous completed shift window;
otherwise the last 8 hours from now. The schema card states that rule so he does not guess.

## 8. Data flow

1. Drawer opens with page context.
2. `POST /agent/chat` through `/agent` with `{ message, context, conversationId }`.
3. Replica validates the JWT against Keycloak JWKS the same way GraphQL does. No token →
   401.
4. Hosted model receives: persona, schema cards, context, user text, prior browser turns
   sent in the POST (last 20 messages).
5. Zero or more tool calls. SQL and GraphQL as above.
6. Text answer plus `citations: [{ asset, topic, time, source }]`.
7. Stream tokens when the host supports SSE; otherwise one JSON body. The drawer handles
   both.
8. Replica drops memory after the response. Browser keeps the thread.

The browser never receives a database password or the model key.

## 9. Errors

| Case | Behaviour |
|---|---|
| Missing / expired token | 401. Drawer: sign in again. |
| Write request (“ack”, “change the threshold”) | Text refusal. No write tool exists. |
| SQL not a single `SELECT`, or table off allowlist | Tool error. He says the lookup was rejected. No SQL in the drawer. |
| Timeout or 0 rows | He says he cannot see it in that window or Access Group. No invented numbers. |
| GraphQL 403 | He says that Asset is outside your Access Group. |
| Model down or key missing | Drawer: “Factory Copilot is unavailable.” Health red. |
| Replica dies mid-turn | User resends. Thread is still in the browser. |

Tool failures become a short error string for the model. Stack traces stay server-side.

## 10. Testing

No live hosted-model call in CI. Mock the model.

**Agent**

- SQL guard rejects writes, multi-statement, and unknown tables; accepts a scoped
  `SELECT` on `uns_metrics` / `model.asset`.
- Access Group wrap: non-admin history `SELECT` gains a path/topic filter; `admin` does not.
- `POST /chat` without Bearer is 401; with a token, GraphQL tools receive that token.
- “Ack this alarm” / “raise the threshold” (mocked model) produces no write and no SQL
  mutation.

**Frontend**

- Header opens the bay on a protected route.
- POST body includes page context.
- Empty (job cards), in-flight (lamp), citation tickets, and unavailable states render.
- `npm run build` passes.

**Compose**

- `factory_agent` service, `/agent/` on nginx and vite, container healthcheck on `/health`.

## 11. Decisions (locked)

| Topic | Choice |
|---|---|
| Job | Live state + alarms + Asset Model + Timescale history (last shift, downtime, Historic Events) |
| Writes | None |
| UI home | Header drawer on every signed-in page, not a route or a second app |
| Scale | Separate stateless container `13_uns_factory_agent` |
| Brain | Hosted OpenAI-compatible API; key in `.secrets.yaml` |
| Query split | SQL for `model` + Timescale; GraphQL for live UNS Nodes and alarms |
| Tool style | Four named tools, not free `execute_sql` |
| Who can talk | Any signed-in Console Role; Access Groups hide data |
| Chat memory | Browser `sessionStorage` only |
| Persona | Factory Copilot, first person, cites or admits he cannot see it |
| UI craft | `frontend-design`: control-desk radio (nameplate, lamp, stamped tickets) |
| Live graph | GraphQL only, no Cypher |
| Shift window | OEE previous shift if present, else last 8 hours |

## 12. Out of this spec

Local models; server-side transcripts; write tools; a `#/copilot` page; Cypher; Kafka /
MQTT / Grafana tools; teaching how the platform is built; Access Group admin UI; changing
ADR-0009 token storage.
