# Factory Copilot (read-only plant colleague)

Date: 2026-09-05
Modules: `13_uns_factory_agent` (new), `11_frontend` (header drawer), `11_frontend/nginx.conf`,
`11_frontend/vite.config.ts`, `docker-compose.yml`, `conf` (settings + secrets key),
`uns_historian` schema `copilot` (conversation tables)
Status: Approved
UI skill: `frontend-design` (control-desk radio **paint**, screenshot **layout**).
Console chrome stays `console-compact-layout`.

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
- Threads live in Postgres (`copilot` schema). You only see your own. They survive a new
  browser. Replicas stay stateless.
- The bay uses the screenshot **layout** (left history, New chat, job cards, handset) and
  this console’s **dark / orange** paint. Implementation follows `frontend-design`.

## 3. Non-goals

- No writes to the plant: no ack, no Alert Rule edits, no Asset Model edits, no simulator
  control. Conversation rows are the only writes, and only for the caller’s own threads.
- No second frontend app and no new console route. Not `#/copilot`.
- No MQTT, Kafka, or Grafana tools.
- No local/Ollama model in this slice. OpenAI `gpt-4o` only (model name is config).
- No SSE / token streaming. One-shot JSON: spinner, then the full answer and citations.
- No Cypher. Live current state is GraphQL → Neo4j, not a fifth tool.
- No “how the platform is built” documentation agent.
- No sticky sessions. No new Postgres instance. No shared or admin-audited transcripts.
- No job cards for schedules, work instructions, or any store we do not have.

## 4. Architecture

```
Browser (any #/… console page)
    → FactoryCopilotDrawer  (page context + Bearer token)
    → uns_frontend nginx or vite  /agent/*
    → factory_agent replica  (13_uns_factory_agent)
         → OpenAI gpt-4o
         → query_asset_model     Postgres schema `model`   SELECT, allowlisted
         → query_historian       Timescale                 SELECT, allowlisted
         → query_live            graphql_server            caller token
         → query_alarms          graphql_server            caller token
         → copilot.conversation / copilot.message          caller subject only
```

`factory_agent` publishes no host port in Compose. The console origin is the only door,
same as the simulator control API. `npm run dev` proxies `/agent` like `/graphql`.

Config: `UNS_MODULE=13_uns_factory_agent`, `conf/settings.yaml`, OpenAI key in
`conf/.secrets.yaml` (never in the image or the browser). Model id defaults to `gpt-4o`.
A read-only database role runs plant SQL. Conversation writes use a separate role that
can only touch schema `copilot`. GraphQL tools send the caller’s Bearer token; they do
not use a service account.

The container listens on `/health`, `/chat`, `/conversations`. Nginx and vite map
`/agent/` → `/`. Compose healthchecks `GET /health` on the container network. Missing
OpenAI key or DB/GraphQL unreachability makes health degraded/red.

### 4.1 Conversation store

Tables on the existing `uns_historian` database, schema `copilot` (not a new server):

- `conversation` — `id`, `subject` (Keycloak `Identity.subject`), `title`, `created_at`,
  `updated_at`
- `message` — `id`, `conversation_id`, `role` (`user` | `assistant`), `body`,
  `citations` JSONB, `created_at`

List / get / delete filter `subject = caller`. Nobody else can open the thread, including
`admin`. **New chat** inserts a conversation. Title is the first user line, truncated.

Retention: 30 days from `conversation.updated_at`. A replica pass deletes expired rows
(and their messages). The history X deletes one thread immediately.

## 5. Him

UI title: **Factory Copilot**. He speaks first person, short sentences, plant English.
He cites Asset, topic, and time. Empty tools → he says he cannot see it. He refuses any
request to change the plant.

Job cards (empty state only, questions he can answer now):

- What is in alarm on the Asset I am looking at?
- Last-shift Historic Events / downtime for this line.
- Current Metric value versus the last eight hours.
- Which Assets on this path have published in the last hour?

No schedule, SOP, or “how do I adjust…” cards.

He is available to every signed-in Console Role. Access Groups still hide **plant** rows.
`admin` is unscoped on plant data, same as GraphQL, and still only sees **their own**
chats.

## 6. UI (frontend-design)

**Direction: screenshot layout, control-desk radio paint.** Left history + New chat +
carousel-or-grid job cards + handset, as in the Factory Copilot pictures. Colour, type,
and chrome are this console: Oxanium, IBM Plex Mono, `#FF7A00`, theme tokens. Not a light
green island. Not Inter. Not purple.

Memorable bit: **nameplate + live lamp + stamped citations**.

### 6.1 Placement

- Header control on every protected page, left of Bookmarks, `aria-label="Factory Copilot"`.
- Right-hand bay, same mount as `BookmarksDrawer` / `StaleNodesDrawer` in `AppLayout`.
  Wide enough for a history rail: `max-w-3xl` (48rem), full height.
- Inside the bay: left rail (~11rem) for **New chat** + thread list; main column for
  greeting / thread / composer.
- No new `getPageHeading` title. No `PageToolbar`. The page behind stays as it is.
- Escape and the nameplate close control dismiss the bay. A citation jump leaves the bay
  **open** so you can come back.

### 6.2 Look

| Part | Treatment |
|---|---|
| Nameplate | `FACTORY COPILOT` in Oxanium, wide tracking. Amber lamp (`#FF7A00`) pulses while a turn is in flight; solid when idle; muted red when unavailable. |
| Page context | One stamped chip under the nameplate: route + Asset path or Metric Key or alarm topic. Mono. If nothing is selected, `Plant · no Asset selected`. |
| History rail | **New chat +**. Rows show title + local datetime (as in the screenshots). X deletes that thread. Active row uses the orange inset, not a filled SaaS chip. |
| His speech | Oxanium, left rail, no avatar circle. A thin orange tick on the left edge marks his turns. |
| Your speech | Right-aligned, quieter surface, no tick. |
| Citations | Ticket row: `Asset · topic · time · source` in IBM Plex Mono. `source` is `model`, `historian`, `live`, or `alarms`. Rectangular, inset, not pills. **Click jumps:** historian → `#/historian` (existing jump helper); alarm → `#/alerts`; Asset → `#/hierarchy` or `#/condition-monitoring` when that page already has the selection. |
| Job cards | Empty new thread only. 2×2 stamped cards (or a short carousel if four do not fit). Copy is a real, answerable question. |
| Composer | Bottom handset bar: `Message Factory Copilot…`, hardware-style send key. Enter sends; Shift+Enter newline. Disabled while the spinner is up. |
| In flight | Spinner + lamp pulse. No partial tokens. |

Light and dark both use theme tokens. The bay is `instrument-grain` / existing overlay
language, not `bg-white` leftovers.

Motion: one slide-in from the right. Lamp pulse is the only loop.

### 6.3 Files

New under `11_frontend/src/components/copilot/`:

- `FactoryCopilotDrawer.tsx` — bay, history rail, thread, composer, job cards
- `FactoryCopilotButton.tsx` — header control
- `copilotContext.ts` — page context from route + current selection
- `copilotApi.ts` — `/agent/conversations`, `/agent/chat`
- tests beside them

Reuse `consoleTokens`, overlay/panel classes, and existing historian/alarm jump helpers.
Do not clone Bookmarks markup.

Context sources (read, do not invent a parallel store): current route; Condition
Monitoring / tree selection; Alarm Management selected alarm topic; Hierarchy selected
Asset path. If a page has no selection, send route only.

## 7. Tools

He has exactly four tools. No others. Conversation SQL is not a tool he can call.

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

Schema cards are curated at boot, not a raw `information_schema` dump each turn.

**Last shift:** if an OEE shift calendar row exists, the previous completed shift window;
otherwise the last 8 hours from now. The schema card states that rule so he does not guess.

## 8. Data flow

1. Drawer opens. `GET /agent/conversations` fills the left rail (caller’s threads, not
   expired). Last opened thread, or empty + job cards if none.
2. **New chat** → `POST /agent/conversations`. Job cards show.
3. You send. `POST /agent/chat` with `{ message, context, conversationId }` and Bearer
   token.
4. Replica validates the JWT (Keycloak JWKS, same as GraphQL). No token → 401. Conversation
   must belong to `subject` or 404.
5. Replica loads the last 20 messages of that thread from `copilot.message`, plus persona,
   schema cards, and page context. Calls OpenAI `gpt-4o` with the four tools.
6. Zero or more tool calls. SQL and GraphQL as above.
7. One JSON body: text answer plus `citations: [{ asset, topic, time, source }]`. Persist
   the user line and the assistant line. Update `conversation.updated_at` (and title if
   this was the first line).
8. Replica drops memory. The drawer replaces the spinner with the answer and tickets.

The browser never receives a database password or the OpenAI key.

## 9. Errors

| Case | Behaviour |
|---|---|
| Missing / expired token | 401. Drawer: sign in again. |
| Chat or thread that is not yours | 404 (do not leak that it exists). |
| Write request (“ack”, “change the threshold”) | Text refusal. No plant-write tool exists. |
| SQL not a single `SELECT`, or table off allowlist | Tool error. He says the lookup was rejected. No SQL in the drawer. |
| Timeout or 0 rows | He says he cannot see it in that window or Access Group. No invented numbers. |
| GraphQL 403 | He says that Asset is outside your Access Group. |
| OpenAI down or key missing | Drawer: “Factory Copilot is unavailable.” Health red. |
| Replica dies mid-turn | User resends. Thread is already on the server; a partial assistant row is not written. |
| Thread older than 30 days | Gone from the list. Treat as 404 if opened by id. |

Tool failures become a short error string for the model. Stack traces stay server-side.

## 10. Testing

No live OpenAI call in CI. Mock the model.

**Agent**

- SQL guard rejects writes, multi-statement, and unknown tables; accepts a scoped
  `SELECT` on `uns_metrics` / `model.asset`.
- Access Group wrap: non-admin history `SELECT` gains a path/topic filter; `admin` does not.
- `POST /chat` without Bearer is 401; with a token, GraphQL tools receive that token.
- “Ack this alarm” / “raise the threshold” (mocked model) produces no plant write.
- Conversation list/get/delete: only the owning `subject`. Another subject gets 404.
- Expiry: a thread with `updated_at` older than 30 days is not listed and GET is 404.

**Frontend**

- Header opens the bay on a protected route.
- History rail lists threads; New chat; X deletes.
- POST body includes page context and `conversationId`.
- Empty (job cards), spinner, citation tickets (click navigates), and unavailable states.
- Job cards do not mention schedule or work instructions.
- `npm run build` passes.

**Compose**

- `factory_agent` service, `/agent/` on nginx and vite, container healthcheck on `/health`.
- `copilot` schema created with the service (migration or startup DDL).

## 11. Decisions (locked)

| Topic | Choice |
|---|---|
| Job | Live state + alarms + Asset Model + Timescale history (last shift, downtime, Historic Events) |
| Writes | Plant: none. Conversations: caller’s own rows only |
| UI home | Header drawer on every signed-in page, not a route or a second app |
| Scale | Separate stateless container `13_uns_factory_agent` |
| Brain | OpenAI `gpt-4o`; key in `.secrets.yaml`; model id in settings |
| Query split | SQL for `model` + Timescale; GraphQL for live UNS Nodes and alarms |
| Tool style | Four named tools, not free `execute_sql` |
| Who can talk | Any signed-in Console Role; Access Groups hide plant data |
| Chat memory | Postgres `copilot` on `uns_historian`; own threads only |
| Retention | 30 days from last update; user can delete sooner |
| Answer delivery | One-shot JSON (spinner, then full answer). No SSE |
| Citations | Stamps; click jumps to historian / alerts / Asset page |
| Job cards | Only questions the four tools can answer |
| Persona | Factory Copilot, first person, cites or admits he cannot see it |
| UI craft | Screenshot layout + control-desk radio paint (`frontend-design`) |
| Live graph | GraphQL only, no Cypher |
| Shift window | OEE previous shift if present, else last 8 hours |

## 12. Out of this spec

Local models; token streaming; write tools against the plant; a `#/copilot` page; Cypher;
Kafka / MQTT / Grafana tools; teaching how the platform is built; shared or admin-audited
transcripts; schedule / SOP stores; Access Group admin UI; changing ADR-0009 token storage.
