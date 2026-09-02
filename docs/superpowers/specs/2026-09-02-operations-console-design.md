# Operations console

Date: 2026-09-02
Modules: `11_frontend`, `07_uns_graphql` (one read query), `09_uns_model` (one repository
read), `docker-compose.yml`, `08_uns_observability`
Status: Approved, not yet implemented

## 1. Problem

The console is a demonstration of the platform's modules. It needs to be a tool for running
a plant. Three things stand between it and that.

**It is not truthful.** `11_frontend/src/components/layout/Sidebar.tsx:362`–`:368` prints
`MQTT: ON`, `NEO4J: OK` and `KAFKA: ON` as literal strings. The browser has no connection to
any of those three and, per the hard constraints of this platform, must never have one — so
those indicators cannot be anything but decoration. ADR-0001 was written because of exactly
this class of defect: "the React console's System Health panel derives all five component
indicators from a single boolean and no module emits any metrics at all." The panel it
describes is still there. `AppLayout.tsx:117` renders `Nodes: {allLoadedNodes.length || 28}`,
so an empty namespace reports twenty-eight nodes. `AppLayout.tsx:105`–`:107` prints
`GQL: 8000`, `VITE: 3000` and `SCHEMA: 2026.08.28-v2`: the first is a port the browser
cannot know, the second is Grafana's published port and not Vite's (`platform/settings.ts`
sets `frontendDevPort` to 5173), and the third is a version string no build step produces.
`LandingView.tsx:135` claims `99.999%` and `:593` claims `ISO/IEC 62443 Certified Cyber
Defense`, neither of which anything in this repository measures or holds.

**Real capability is unreachable.** `12_uns_oee` is implemented, running in
`docker-compose.yml:271` as `oee_client`, and its results are published through GraphQL by
`07_uns_graphql/src/uns_graphql/queries/oee.py`. ADR-0008 calls this number the pilot's
success criterion. The console references it zero times. The same is true of the Asset
Model's completeness surface: `getUnmodelledTopics` and `getAssetModelSummary` exist
(`queries/asset.py:111`, `:115`) and `CONTEXT.md` says counting Unmodelled Topics "is how you
tell an incomplete Asset Model from a complete one" — the console has no screen for either.

**It is organised around this repository, not around plant work.** The navigation reads
`Historian Explorer` with a `Timescale` badge, `Sparkplug B Decoder`, `Kafka Event Streams`,
`System Operations`. A shift operator does not know which of those holds the current value of
a reactor temperature.

This spec rebuilds the information architecture around plant jobs, wires every capability
that already exists, and removes every claim the platform cannot support.

## 2. Findings that shape the design

Established by reading the code, not assumed.

1. **The committed GraphQL schema dump is stale.** `07_uns_graphql/schema/uns_schema.graphql`
   contains no OEE surface. Building `strawberry.Schema` from
   `uns_graphql_app.py:118` and printing it yields four fields the dump does not mention:
   `oeeShiftResults`, `downtimeEvents`, `downtimePareto` and `assignDowntimeReason`. Any
   inventory taken from the dump under-reports the platform. The dump is regenerated as part
   of this work.
2. **`12_uns_oee` is implemented.** The module exists, `asset_model_setup` creates its schema
   from `conf/oee/*.yaml`, `oee_client` runs it, and `oee.py` resolves its results. The
   instruction "if `12_uns_oee` is not implemented, there is no OEE screen" is a live
   condition that evaluates false, so a Shift & OEE surface reads real computed results. It
   does not read the simulator's fabricated `Oee`/`Availability`/`Performance`/`Quality`
   signals, which the OEE engine spec section 12 retires.
3. **Exactly one Asset has OEE configured.** `conf/oee/units.yaml` declares a single unit,
   `CovestroAG/Dormagen/Production/Line1`. `Line2` and everything at `Krefeld` have no shift
   pattern, no ideal cycle times and therefore no OEE. A design that shows an OEE figure per
   line would have to invent three quarters of them.
4. **`assignDowntimeReason` cannot be driven from a UI today.** It takes a `reasonCode`
   (`mutations/oee.py`) validated against `model.downtime_reason`
   (`09_uns_model/src/uns_model/oee_results.py:284`), and no query lists that table.
   `downtimePareto` returns only codes already used, so a code authored in
   `conf/oee/reasons.yaml` but never yet triggered is unreachable. This is the one genuine
   backend gap.
5. **The frontend has no tests and no test tooling.** `11_frontend/package.json` has no
   `test` script, no Vitest, no Testing Library, and there is not one `*.test.ts(x)` file in
   the module. "Keep existing tests green" is satisfied trivially; the tooling is new work.
6. **The tree already obeys the wildcard rules.** `client.ts:207` resolves roots through
   `getAssetChildren(null)` and falls back to `childrenTopic('')`; `:223` resolves children
   through the Asset Model first and `childrenTopic(parentTopic)` second. `childrenTopic`
   produces a `+` pattern. No tree path uses `#`. The `#` occurrences in the codebase are in
   the live feed's subscription (`LiveMqttFeed.tsx:108`) and the historian's exclude box
   (`ExploreView.tsx:44`), where a multi-level wildcard is correct.
7. **Sparkplug is already handled correctly.** `lib/uns/sparkplug.ts` defines
   `SPARKPLUG_PREFIX`, and no browser code decodes protobuf. Decoded Sparkplug comes from
   `getSpbNodesByMetric`; live Sparkplug is a badge on a `BytesPayload`
   (`PayloadInspector.tsx:257`). Nothing to fix here beyond where the screen lives in the
   navigation.
8. **Every GraphQL call already funnels through one client.** `services/graphql/client.ts`
   holds all seventeen methods, and every component goes through it. Adding surface means
   adding methods there, not scattering fetches.
9. **Grafana embedding is already enabled but unreachable.** `docker-compose.yml:399` sets
   `GF_SECURITY_ALLOW_EMBEDDING: "true"`. Neither `11_frontend/nginx.conf` nor
   `vite.config.ts` proxies Grafana — they proxy only `/graphql` and `/simulator` — and no
   component references a dashboard. The dashboards exist with fixed UIDs `uns-oee`,
   `uns-process-visualization` and `uns-platform-observability`.
10. **The Grafana template variables constrain deep-linking.** `oee.json` has one variable,
    `asset` (a query variable). `process-visualization.json` has two textbox variables,
    `topic` and `metric`. `platform-observability.json` has none. Deep links may set only
    `var-asset`, `var-topic` and `var-metric`; anything else would be invented.
11. **Two services publish host port 9092.** `uns_kafka_broker` (`docker-compose.yml:82`) and
    `graphdb_client`'s metrics endpoint (`:165`). Only one can bind, so on a clean `up` one
    of them fails. Prometheus reaches `graphdb_client:9092` from inside the network
    (`prometheus.yml:16`) and does not need the host publish at all.
12. **`localStorage` is the seat of the security theatre.** `AuthContext.tsx:417`–`:438`
    resolves a login by falling through to `users[0]`, which is the admin, and ignores the
    password argument entirely. This spec does not fix it — the authentication spec does —
    but it does remove the UI that claims it is fixed already.
13. **Seeded Alert Rules name equipment that does not exist.** `AlarmContext.tsx` seeds
    rules on `CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature`. Neither
    `Polyurethane` nor `Reactor_01` appears anywhere in `conf/` or `99_simulator/`. The real
    areas are `Utilities` and `Production`. `restoreDefaults()` writes these fictional rules
    into shared Postgres through `saveAlertRules`, so one operator clicking restore changes
    plant configuration for everybody.
14. **Alert Rule evaluation is browser-side by design.** ADR-0005: "alarms are only
    evaluated while somebody has the console open." `AlarmContext` already distinguishes
    `SERVER` from `BROWSER` origin honestly. This spec does not move evaluation; it surfaces
    the consequence.
15. **`text-[8px]` and `text-[9px]` appear 124 times across 28 files.** Eight-pixel type is
    not readable at control-room distance. Density has to come from layout, not from glyph
    size.

## 3. Three rules the whole design serves

1. **A surface that exists is true.** If the console cannot observe something, it does not
   draw an indicator for it. Where the platform's answer is "unknown", the UI says unknown.
   A missing number is better than a plausible one.
2. **A capability that exists is reachable.** Every query, mutation and subscription the
   live schema publishes is reachable from a screen a plant user can find, or is explicitly
   listed as deliberately unexposed with the reason.
3. **Naming follows the plant, not the repository.** Navigation, headings and labels use
   `CONTEXT.md` vocabulary. Module numbers, datastore product names and internal service
   names do not appear in the operator's path.

## 4. Scope

In scope:

- The information architecture and every screen in `11_frontend`.
- Removal of untruthful UI.
- New surfaces for Shift & OEE, downtime, the Asset Model and Unmodelled Topics.
- One new read query in `07_uns_graphql` and its repository read in `09_uns_model`.
- Regenerating `07_uns_graphql/schema/uns_schema.graphql`.
- A `/grafana` proxy in `nginx.conf` and `vite.config.ts`, and the Grafana sub-path
  environment it needs.
- Fixing the duplicate host port 9092.
- Vitest + Testing Library, with mocked GraphQL.

Out of scope:

- Authentication and authorization. Covered by
  `2026-09-02-console-authentication-design.md`. That spec does not block this one.
- Moving Alert Rule evaluation server-side (ADR-0005 territory).
- Any second frontend, any server-rendered UI, any FastAPI-served console.
- Mobile layouts, i18n, and any change to the Grafana dashboards' own panels.
- Broker, Kafka or MQTT authentication.

## 5. Gap table

Every field in the live schema, whether a plant user can reach it today, and where it lands.
"Reachable" means a component calls it, not merely that `client.ts` can.

### 5.1 Queries

| Field | Reachable today | Destination |
| --- | --- | --- |
| `getUnsNodes` | Yes — tree and search | PLANT ▸ tree rail; NAMESPACE ▸ Topics |
| `getUnsNodesByProperty` | Yes — search | NAMESPACE ▸ Find by property |
| `getAssetChildren` | Yes — tree | PLANT ▸ tree rail; ASSETS ▸ authored tree |
| `getTopicContext` | Yes — payload inspector | PLANT ▸ Live (Enrichment) |
| `getHistoricEventsInTimeRange` | Yes — Explore | HISTORIAN ▸ Time range |
| `getHistoricEventsByPublishers` | Yes — Explore | HISTORIAN ▸ By publisher |
| `getHistoricEventsByProperty` | Yes — Explore | HISTORIAN ▸ By property |
| `getSpbNodesByMetric` | Yes — Sparkplug | SPARKPLUG ▸ Decoded |
| `getAlertRules` | Yes — Alarms | ALARMS ▸ Rules |
| `getAssets` | **No** | ASSETS ▸ authored tree (flat search) |
| `getAsset` | **No** | ASSETS ▸ Asset detail |
| `getUnmodelledTopics` | **No** | ASSETS ▸ Unmodelled Topics |
| `getAssetModelSummary` | **No** | ASSETS ▸ completeness header |
| `getAlertRule` | **No** | ALARMS ▸ rule detail (by id, deep link) |
| `getAlertRuleSummary` | **No** | ALARMS ▸ header counts; HEALTH |
| `oeeShiftResults` | **No** | SHIFT ▸ shift table; PLANT ▸ Shift & OEE |
| `downtimeEvents` | **No** | SHIFT ▸ Stops; PLANT ▸ Stops |
| `downtimePareto` | **No** | SHIFT ▸ Pareto |
| `getDowntimeReasons` | **Does not exist** | New. See section 10 |

### 5.2 Mutations

| Field | Reachable today | Destination |
| --- | --- | --- |
| `saveAlertRule` | Yes | ALARMS ▸ rule editor |
| `saveAlertRules` | Yes | ALARMS ▸ bulk import. Not `restoreDefaults` — see section 11 |
| `deleteAlertRule` | Yes | ALARMS ▸ rule editor |
| `setAlertRuleEnabled` | Yes | ALARMS ▸ rule row toggle |
| `recordAlertRuleEvaluation` | Yes | Called by the evaluator, no UI control |
| `assignDowntimeReason` | **No** | SHIFT ▸ Stops ▸ reassign |

### 5.3 Subscriptions

| Field | Reachable today | Destination |
| --- | --- | --- |
| `getMqttMessages` | Yes — live feed | PLANT ▸ Live; NAMESPACE ▸ Feed |
| `getKafkaMessages` | Yes — streams | STREAMS |

### 5.4 Deliberately not exposed

- Nothing. After this work every field above is reachable. Where a screen wants data with no
  API, it is marked **requires backend** in the code and left out of the shipping UI.

## 6. Personas and the jobs they do

The navigation is derived from this table, not from the module list.

| Persona | Job to be done | Primary surfaces |
| --- | --- | --- |
| Operator | See what the plant is doing now, and what needs attention | PLANT, ALARMS |
| Shift lead | See how the shift went and why time was lost | SHIFT |
| OT engineer | Inspect payloads with Asset and Metric context, trend, search history | PLANT, HISTORIAN, ASSETS |
| Integration engineer | Streams, Sparkplug, what is published but unmodelled, the simulator | NAMESPACE, SPARKPLUG, STREAMS, ASSETS, SIMULATOR |
| Admin | Who has access, platform health | HEALTH, USERS |

## 7. Information architecture

Eleven destinations in a single left rail, in four groups ordered by how often a plant user
needs them. Group headings are labels, not links.

```
RUN THE PLANT
  Plant          — the asset canvas: what is happening now
  Shift          — how the shift went, and where the time went
  Alarms         — what needs a person

UNDERSTAND THE DATA
  Historian      — query what was published
  Assets         — the authored Asset Model, and what is not in it
  Namespace      — what the broker is actually carrying

INTEGRATE
  Sparkplug      — decoded Sparkplug B
  Streams        — Kafka topics
  Simulator      — drive the plant model

PLATFORM
  Health         — is the platform working
  Users          — who has access
```

Route mapping from today's `App.tsx`:

| Today | Becomes |
| --- | --- |
| `/tree` | `/plant` (redirect preserved) |
| — | `/shift` (new) |
| `/alerts` | `/alarms` (redirect preserved) |
| `/historian` | `/historian` (unchanged) |
| — | `/assets` (new) |
| — | `/namespace` (new; absorbs the topic-browser half of `/tree`) |
| `/sparkplug` | `/sparkplug` (unchanged) |
| `/streams` | `/streams` (unchanged) |
| `/system` | `/health` (redirect preserved) |
| `/simulator` | `/simulator` (unchanged) |
| `/users` | `/users` (unchanged, honest — see section 11) |

`Namespace` and `Assets` stay separate destinations. `CONTEXT.md` is explicit that the graph
of UNS Nodes is discovered from traffic while the Asset Model is authored, and that a machine
which has not published yet "simply did not exist" in the former. Merging them is how a
missing Asset becomes invisible.

Badges removed: `Timescale`, `v1.0`, `Live`, `ADMIN`. A badge survives only if it changes
what an operator does — `STALE` on a tree row does, `Timescale` does not.

## 8. PLANT — the asset canvas

A persistent Asset Model tree rail on the left and a tabbed canvas on the right. One
selection, shared by every tab, so changing tabs never re-navigates the plant.

Tree rail: `getAssetChildren` lazily per expansion, with the published-traffic fallback
`client.ts:223` already implements. The selected row is marked with a left border and a
raised background, not colour alone. Stale rows are dimmed, using the existing
`isNodeStale` in `lib/uns/node-meta.ts`. Search results are a list below the tree; clicking
one expands the tree's ancestors to it. Search never filters or replaces the tree.

| Tab | Data | Notes |
| --- | --- | --- |
| Live | `getUnsNodes` under the path, `getMqttMessages` for updates, `getTopicContext` for Enrichment | Values carry the Unit of Measure, display name and decimals from the Metric Definition. A value with no Metric Definition shows raw, labelled as unenriched |
| Trend | Embedded Grafana `uns-process-visualization` | `var-topic` set from the selection. Per ADR-0002, GraphQL does not serve bucketed trends |
| Shift & OEE | `oeeShiftResults` | Section 9 |
| Stops | `downtimeEvents`, `downtimePareto`, `assignDowntimeReason` | Section 9 |
| Alarms | `getAlertRules(topic:)` | Rules watching this Asset |
| Model | The selected `AssetNode` and its `metricDefinitions` | Manufacturer, serial, criticality, engineering range |

The Shift & OEE and Stops tabs are always present. On an Asset with no configured OEE unit —
which per finding 3 is every Asset except `CovestroAG/Dormagen/Production/Line1` — they read
**"No OEE unit is configured for this Asset."** with a line naming `conf/oee/units.yaml` as
where that is authored. Hiding the tab would hide the gap; an OT engineer needs to see it.

## 9. Shift, OEE and downtime

ADR-0008 is the constraint, and the design follows it rather than working around it.

**No live gauge.** OEE is computed after a shift closes and lands roughly twenty minutes
late. The in-progress shift is shown as a row reading **"In progress — computed after the
shift closes"**, never as a partial percentage. There is no wall-display gauge, because
ADR-0008 says there is no number to put on one.

**Null is not zero.** Every ratio on `OeeShiftResult` is nullable, and
`07_uns_graphql/src/uns_graphql/type/oee.py` says why: "a shift with no Loading Time has no
Availability — it did not achieve 0%". A null ratio renders as `—`. `status` is rendered as
the sentence it means:

| `status` | Rendered |
| --- | --- |
| `OK` | the numbers |
| `NO_LOADING_TIME` | No scheduled time |
| `NO_PRODUCTION` | Scheduled, nothing produced |
| `MISSING_IDEAL_CYCLE_TIME` | No rated cycle time authored |
| `NO_INPUT_DATA` | No data historised for this shift |

**Restatement is visible.** `revision > 1` shows a `RESTATED` badge with `computedAt`.
ADR-0008 says this behaviour "needs explaining once to every plant that adopts it", so the
badge carries a tooltip: late data arrived and the shift was recomputed.

**`performanceRaw` above 1 is a warning, not a clamp artefact.** The type's own description
calls it "the only evidence" that the ideal cycle time is wrong or a stop was missed. Above
1.0 the row shows a caution marker linking to the products breakdown.

**Products are shown, not just totals.** `OeeShiftProduct` exists because "a mixed shift's
number cannot be re-derived from the totals once the product mix is gone". The shift detail
lists each product's counts and rated cycle time.

**Stops.** `downtimeEvents` is a table: start, end, duration, the published `stateValue`,
the reason with its category, whether it was planned, and whether the reason was `AUTO` or
`MANUAL`. `downtimePareto` is a horizontal bar list ordered by share, planned and unplanned
visually distinguished. Reassigning a reason opens a picker fed by `getDowntimeReasons`
(section 10) plus a free-text note, and calls `assignDowntimeReason`.

**The reassignment is honest about what it records.** The mutation's own description says the
value is "Attested by the caller, not authenticated: this platform has no authentication
anywhere." Until the authentication spec lands, the reassign dialog states that the name
recorded is self-declared. It does not silently send the fake `AuthContext` user as though it
were an identity.

**`publishedAt` null means not yet on the broker.** Shown as a small `NOT PUBLISHED` marker,
because a downstream consumer reading `<asset path>/KPI/ShiftOee` will not have it yet.

The `/shift` destination is the same data without the tree rail: a shift table for the
configured unit, its Pareto, and its stop list. It exists so a shift lead does not have to
navigate a plant tree to find the one line that has OEE.

## 10. The one backend addition

`getDowntimeReasons: [DowntimeReason!]!` — every authored downtime reason code.

- Type: a new `DowntimeReasonType` published as `DowntimeReason`, with `code`,
  `displayName`, `category` and `isPlanned`. These are exactly the columns on
  `model.downtime_reason` (`09_uns_model/src/uns_model/oee_tables.py:305`) and exactly the
  four fields `DowntimeParetoBucket` already publishes, so no new vocabulary enters the
  schema.
- Resolver: `oee.Query`, alongside the three that exist.
- Repository: a `downtime_reasons()` read on `OeeResultRepository`. That class already
  imports `DowntimeReason` and joins to it (`oee_results.py:46`, `:232`), and already
  validates a code against it (`:284`), so this is the table it is already responsible for.
- Read-only. ADR-0005's mutation surface is deliberately narrow and stays as it is.

Why this and not a hardcoded list in the console: the codes are authored in
`conf/oee/reasons.yaml` and imported by `asset_model_setup`. A plant that edits that file
and gets a console picker showing someone else's codes has been lied to by the UI, which is
the defect this whole spec is about.

`07_uns_graphql/schema/uns_schema.graphql` is regenerated in the same change, so the dump
stops being the stale artefact finding 1 describes.

## 11. Removing untruthful UI

Each item is a deletion or a binding to a real source. Nothing here is replaced by a
better-looking invention.

| Location | Untruth | Resolution |
| --- | --- | --- |
| `Sidebar.tsx:356` | `GQL 8000` | Removed. The browser reaches GraphQL through a proxy path and does not know a port |
| `Sidebar.tsx:362`–`:368` | `MQTT: ON`, `NEO4J: OK`, `KAFKA: ON` | Deleted. The browser cannot observe any of them |
| `AppLayout.tsx:105` | `GQL: 8000` | Replaced by the resolved GraphQL URL from `platform/settings.ts` |
| `AppLayout.tsx:106` | `VITE: 3000` | Deleted. 3000 is Grafana's port; Vite's default is 5173 |
| `AppLayout.tsx:107` | `SCHEMA: 2026.08.28-v2` | Deleted. No build step produces it |
| `AppLayout.tsx:114` | Static `Connected to UNS Backend` with a green pulse | Replaced by the connection chip in section 12 |
| `AppLayout.tsx:117` | `Nodes: {allLoadedNodes.length \|\| 28}` | `\|\| 28` removed; zero renders as zero |
| `SystemHealthView.tsx:76` | `ENFORCED (ZERO-TRUST)` | Deleted. Finding 12 |
| `SystemHealthView.tsx:92`, `:108`, `:124` | Three `SCHEMA PENDING` panels | Deleted. Replaced per section 13 |
| `SystemHealthView.tsx:165`, `:175`, `:185` | Capability matrix rows reading `OPERATIONAL` | Deleted with the matrix |
| `SystemHealthView.tsx:197`, `:209` | `BLOCKED (SCHEMA PENDING)` | Deleted with the matrix |
| `LandingView.tsx:135` | `99.999%` | Deleted |
| `LandingView.tsx:153`, `:267`, `:593`, `:72` | `ISO/IEC 62443`, `ISO/IEC 62443 Certified Cyber Defense` | Deleted. Nothing in this repository holds that certification |
| `LoginView.tsx:245` | `ISO/IEC 62443 Security Auditing Enabled` | Deleted |
| `AlarmContext.tsx` | `INITIAL_RULES` on `Polyurethane/Reactor_01` | Deleted. Finding 13 |
| `AlarmContext.tsx` `restoreDefaults()` | Writes fictional rules to shared Postgres | Removed. There is no defensible default set, and one user's click must not rewrite plant configuration |
| `/users` | RBAC presented as enforced | Reduced to a read-only view of the local user list, labelled `browser-local, not enforced`, until the authentication spec lands |

The `/users` reduction matters. The current screen edits `localStorage` and presents the
result as access control. Leaving it looking authoritative while `AuthContext.tsx:417`
accepts any password is the single most misleading surface in the console.

Alert Rule evaluation stays browser-side, and ALARMS says so: a line in the rules header
reads that rules are evaluated in this browser and are not checked while the console is
closed. ADR-0005 accepted that limitation; the console should not conceal it.

## 12. Connection state

One chip in the shell, driven by the two things the browser genuinely observes: the GraphQL
HTTP endpoint and the GraphQL WebSocket.

| State | Condition | Text |
| --- | --- | --- |
| Live | HTTP reachable, WS connected | `Live` |
| Degraded | HTTP reachable, WS down | `Degraded — live updates offline` |
| Degraded | HTTP failing, WS connected | `Degraded — queries failing` |
| Down | Neither | `Down — no connection to GraphQL` |

Naming which half failed is the point. An operator whose WebSocket dropped is looking at
values that stopped updating while every query still works, and a single green dot cannot
tell them that. This replaces `UNSContext`'s health being flattened into one indicator.

Nothing else in the console draws a health colour for a backing store. Store health is
Platform Observability, and per ADR-0001 that is Grafana's job.

## 13. HEALTH — Platform Observability

`CONTEXT.md` separates Process Visualization from Platform Observability and warns that
confusing them "is how a green health indicator ends up meaning nothing". The two never
share a data source. HEALTH is Platform Observability only.

Contents:

1. The connection chip from section 12, expanded: endpoint URLs, last successful query, last
   WebSocket event.
2. An embedded `uns-platform-observability` dashboard. Per ADR-0001 this is the source for
   module health, because Prometheus is where the modules emit and the browser is not.
3. Asset Model completeness from `getAssetModelSummary`, and Alert Rule counts from
   `getAlertRuleSummary` — both real counts from the read surface.
4. A plain statement of what the console cannot see: the broker, the graph database, the
   historian and Kafka are not reachable from a browser, and their state is in the embedded
   dashboard. ADR-0001 notes Neo4j Community exports no metrics at all, so that is said
   rather than papered over.

## 14. Grafana embedding

Three dashboards, embedded in three places: `uns-process-visualization` in PLANT ▸ Trend,
`uns-oee` in SHIFT, `uns-platform-observability` in HEALTH.

Required changes:

- `11_frontend/nginx.conf`: a `location /grafana` proxying to `uns_grafana:3000`, placed
  before `location /`. ADR-0007 records that a missing proxy entry returns `index.html` with
  a 200 rather than a clear failure, which is why this must be added deliberately.
- `11_frontend/vite.config.ts`: the same path in the dev proxy, so `npm run dev` behaves
  like the composed stack.
- `docker-compose.yml`: `GF_SERVER_ROOT_URL` and `GF_SERVER_SERVE_FROM_SUB_PATH` on
  `uns_grafana`, so Grafana generates correct asset URLs under `/grafana`.

Deep links set only the variables that exist (finding 10): `var-asset` on `uns-oee`,
`var-topic` and `var-metric` on `uns-process-visualization`, none on
`uns-platform-observability`. Embeds use kiosk mode and pass the console's theme.

Grafana currently runs anonymous with an Admin org role (`docker-compose.yml:397`–`:398`).
ADR-0001 accepted that deliberately and named OIDC as the target. This spec does not change
it; embedding works because of it. The authentication spec closes it, and closing it will
require the embed to carry a session — that dependency is recorded there, not here.

## 15. Visual system

Desktop-first, minimum 1280px. The shell occupies exactly the viewport height and does not
scroll; panes scroll independently. Dark, high-contrast, with visible focus rings on every
interactive element.

Type scale, replacing the 124 uses of 8px and 9px type:

| Use | Size |
| --- | --- |
| Body, controls, tab labels | 13px |
| Dense tables, feeds, tree rows | 12px |
| Column headers, unit suffixes, badges | 11px |

Nothing below 11px. Density comes from tighter row heights, fewer borders and less padding,
not from smaller glyphs.

- Monospace for topics, metric keys, payloads and JSON. Sans for chrome, labels and prose.
- Tabular numerals for every numeric value, so a column of readings aligns.
- Charts carry few series with readable axes and no rainbow palette. Planned and unplanned
  downtime are distinguished by fill, not hue alone.
- Empty states say what to do next and name the file or screen where the thing is authored.
  No illustrations. "No Unmodelled Topics — every published topic matches an Asset" is a
  result; "Nothing here" is not.
- English only. No i18n scaffolding.

## 16. Seconds to answer

The design is judged against these paths, and each is a test in section 18.

**Operator, current value:** open PLANT → the tree is already expanded to the last selection
→ click the equipment row → the Live tab shows the value with its unit. Two clicks from a
cold load.

**Operator, why an alarm fired:** ALARMS → click the active alarm → it names the topic and
the rule's condition and threshold → `Open in Plant` jumps to that Asset's Live tab with the
rule's metric highlighted.

**Shift lead, where the time went:** SHIFT → the last closed shift is the default row → the
Pareto beside it is that shift's → click the largest bar → the stop list filters to that
reason.

**OT engineer, is this value trending wrong:** PLANT → select the metric → Trend → the
embedded dashboard opens on that topic.

**Integration engineer, what is not modelled:** ASSETS → the completeness header shows the
Unmodelled Topic count → click it → the worklist.

## 17. Frontend module layout

Follows the existing `components/<area>/` convention.

```
src/components/
  plant/        PlantView, AssetTreeRail, tabs/{Live,Trend,ShiftOee,Stops,Alarms,Model}
  shift/        ShiftView, ShiftResultTable, DowntimePareto, StopList, ReassignReasonDialog
  assets/       AssetsView, AuthoredAssetTree, AssetDetail, UnmodelledTopicsList, ModelSummaryHeader
  namespace/    NamespaceView, TopicBrowser, LiveFeed, FindByProperty   (from home/)
  historian/    HistorianView, TimeRangeQuery, ByPublisherQuery, ByPropertyQuery   (from explore/)
  health/       HealthView, ConnectionDetail   (from system/)
  alarms/       (unchanged)
  sparkplug/    (unchanged)
  streams/      (unchanged)
  simulator/    (unchanged)
  users/        reduced per section 11
  layout/       AppLayout, Sidebar, ConnectionChip
  common/       GrafanaEmbed, EmptyState, DataTable, ValueWithUnit, StatusPill
  ui/           (unchanged)
src/services/graphql/
  client.ts     + getAssets, getAsset, getUnmodelledTopics, getAssetModelSummary,
                  getAlertRule, getAlertRuleSummary, getOeeShiftResults,
                  getDowntimeEvents, getDowntimePareto, getDowntimeReasons,
                  assignDowntimeReason
  queries.ts    + the matching documents
src/lib/oee/    status labels, ratio formatting (null-safe), revision helpers
```

`GrafanaEmbed` is one component used three times, so the sub-path, kiosk and theme
parameters are decided once.

`src/lib/oee/` exists so that "null renders as `—`, never 0%" is one tested function rather
than a convention repeated in four components.

## 18. Testing

Vitest + Testing Library + `@testing-library/jest-dom`, added to `11_frontend` as new
tooling per finding 5. A `test` script and a `vitest.config.ts` reusing the Vite aliases. No
live broker, no live GraphQL: every test mocks the transport at the `client.ts` boundary or
mocks `fetch`.

Tests that must exist:

1. **Null ratios never render as zero.** An `OeeShiftResult` with `availability: null` and
   `status: NO_LOADING_TIME` renders `—` and `No scheduled time`, and the string `0%` appears
   nowhere in the output. This is the single most important test in the suite.
2. **In-progress shift shows no percentage.** A window whose latest shift has not closed
   renders the in-progress row and no OEE figure.
3. **`revision > 1` renders the restated badge** with `computedAt`.
4. **`performanceRaw > 1` renders the caution marker.**
5. **An Asset with no OEE unit** renders the "No OEE unit is configured" empty state on both
   Shift & OEE and Stops, and does not call `oeeShiftResults`.
6. **Reason reassignment** lists codes from `getDowntimeReasons` — including a code absent
   from the Pareto — and calls `assignDowntimeReason` with the chosen code and note.
7. **Connection chip** renders each of the four states in section 12, and the Degraded text
   names which half failed.
8. **No hardcoded health.** A test asserts the rendered shell contains none of `MQTT: ON`,
   `NEO4J: OK`, `KAFKA: ON`, `VITE:`, `SCHEMA: 2026`, and that with zero nodes the count
   reads `0`.
9. **Tree wildcards.** Expanding a node requests a `+` pattern and never a `#`, and
   `spBv1.0/` topics never enter the ISA-95 tree.
10. **Search does not filter the tree.** Searching leaves the tree's rendered rows
    unchanged; clicking a result expands the ancestors of the match.
11. **Unmodelled Topics** renders the count from `getAssetModelSummary` and the list from
    `getUnmodelledTopics`, and renders the "model is complete" state on an empty list.
12. **Enrichment.** A metric with a Metric Definition renders its Unit of Measure and
    display name; one without renders raw and is labelled unenriched.
13. **Historian by property** sends the OR/AND/NOT combination the form expresses, and CSV
    export contains exactly the loaded rows.
14. **No Sparkplug decoding in the browser.** Live Sparkplug renders as a badge over
    `BytesPayload`; decoded values come only from `getSpbNodesByMetric`.

Backend tests for section 10: `getDowntimeReasons` returns every authored code including one
never used by an event, and the repository read is covered alongside the existing
`OeeResultRepository` tests.

## 19. Compose fix

`graphdb_client`'s `ports: - "9092:9092"` (`docker-compose.yml:165`) is removed. It collides
with `uns_kafka_broker` (`:82`), and Prometheus scrapes `graphdb_client:9092` from inside the
network (`prometheus.yml:16`), so nothing needs the host publish. This matches how
`oee_client`'s 9095 and `uns_simulator`'s 9093 are already handled — both are commented as
deliberately unpublished for exactly this reason.

## 20. Failure modes

| Condition | Behaviour |
| --- | --- |
| GraphQL HTTP unreachable | Connection chip `Down`. Panes show a retry, not an empty table that looks like no data |
| WebSocket down, HTTP up | Chip `Degraded — live updates offline`. Live values show their last-received timestamp and are dimmed |
| `oeeShiftResults` returns empty | "No closed shifts in this window", with the window stated |
| Asset has no OEE unit | Section 8's empty state naming `conf/oee/units.yaml` |
| Grafana unreachable | The embed slot shows that the dashboard could not be loaded and the URL tried. It does not silently render an empty frame, which is what a missing proxy entry produces (ADR-0007) |
| `assignDowntimeReason` rejects a code | The repository raises a sentence (`oee_results.py:284`); it is shown verbatim rather than replaced with "an error occurred" |
| Asset Model empty | The tree falls back to published traffic, as `client.ts:223` already does, and says the structure shown is discovered rather than authored |

## 21. Success criteria

1. The gap table in section 5 has no **No** left in the "Reachable" column.
2. Every item in section 11 is gone from the built bundle, verified by the test in 18.8.
3. An operator reaches a current value in two clicks and an alarm's cause in two, per
   section 16.
4. No OEE number is displayed for an Asset that has no configured OEE unit, and no null
   ratio renders as a zero.
5. The console draws no health indicator for MQTT, Neo4j, TimescaleDB or Kafka.
6. `npm run lint` and `npm test` pass; `tsc --noEmit` is clean.
7. `07_uns_graphql/schema/uns_schema.graphql` matches the built schema.
8. `docker compose up` binds every published port without collision.

## 22. Judgement calls open to revision

- **Eleven destinations, not the seven labels first proposed** (Plant, Historian, Alarms,
  Assets, Sparkplug, Streams, Health). SHIFT is added because `12_uns_oee` is implemented and
  its results have no home. NAMESPACE is added because `CONTEXT.md` treats the authored Asset
  Model and the graph discovered from traffic as different things, and one destination cannot
  be honest about both. SIMULATOR and USERS are kept because they already exist as routes and
  deleting a working screen is not this spec's job. If the rail feels long in use, NAMESPACE
  is the candidate to fold into ASSETS as a tab — not the reverse, because the authored model
  is the source of truth.
- **`/shift` duplicates PLANT ▸ Shift & OEE.** Deliberate: a shift lead should not navigate a
  plant tree to reach the one configured line. If a second and third line get OEE units, the
  standalone view becomes a line picker and the duplication stops being duplication.
- **Grafana for trending rather than a native chart.** ADR-0002 rejected GraphQL-for-trending
  on a concrete ground — `getHistoricEventsInTimeRange` has no `LIMIT`. If a bounded,
  bucketed read is ever added to the schema, PLANT ▸ Trend is the first place a native chart
  should replace an iframe.
- **`restoreDefaults` removed rather than rewritten.** There is no set of default Alert Rules
  that is correct for an unknown plant, and the mutation writes to shared storage. A future
  version could seed from the Asset Model's criticality field, which would at least be
  derived from something real.
