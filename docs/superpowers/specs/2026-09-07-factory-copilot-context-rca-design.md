# Factory Copilot: context pack and plant RCA

Date: 2026-09-07
Modules: `13_uns_factory_agent`, `11_frontend` copilot drawer
Status: Draft (awaiting review)
Amends: `docs/superpowers/specs/2026-09-05-factory-copilot-design.md`

Factory Copilot already talks. He still asks “which Asset?” when the drawer shows
**Plant • no Asset selected**, and starter cards say “this Asset / this metric / this
path.” This spec makes him use **default plant = Access Group roots**, a **tighter focus
when the tree or page has a selection**, a **server-side RCA playbook** on the four
existing tools, and a **curated console map**. Service-health RCA is out.

## 1. Problem

Page context is four optional strings. Empty strings plus relative job cards make the
model ask for a name instead of querying Timescale, Postgres, or GraphQL. RCA for
declining performance is only a prompt hint, so the model can skip tools. The 2026-09-05
spec forbade a “how the platform is built” agent; operators still need a short map of
pages and stores. That spec stays the source of truth for writes, auth, citations, and
Compose. This spec adds context and playbooks; it does not add stores or write tools.

## 2. Goals

- With **no tree selection**, “this plant / this path / my plant” means the caller’s
  **Access Group roots**. `admin` means the whole Asset Model (enterprise/site roots).
- With a **selection**, that Asset path, Metric key, or alarm topic **wins** as focus.
- The **current console route** is a hint (Alarms, Condition Monitoring, Hierarchy), not
  a second plant.
- RCA-shaped questions run a **fixed lookup sequence** on the four existing tools
  **before** the model writes. He cites numbers from those rows or says he cannot see
  them. He does not invent values.
- He can answer **how this console works** from a curated card (pages, which store
  answers what, Access Groups, read-only).
- Starter cards and the context chip stay usable when nothing is selected.
- A playbook miss is an answer in the thread, not “Factory Copilot is unavailable.”

## 3. Non-goals

- No platform-health RCA (why GraphQL/Copilot/Keycloak is down). Defer with one sentence.
- No new plant tools (no MQTT, Kafka, Grafana, Cypher).
- No RAG over ADRs or `CONTEXT.md`. Console map is curated text shipped with the agent.
- No writes to the plant. No SSE. No fifth data store.
- No changing Access Group rules: playbook SQL/GraphQL stay scoped like today.

## 4. Architecture

```
Browser  →  POST /agent/chat { message, conversationId, pageContext }
         →  factory_agent
              JWT → Access Group roots
              context pack (route, focus, default plant, page hint)
              classify kind
              playbook queries (code we ship, four tools)
              OpenAI (pack + results + schema cards + console map)
              optional extra tool rounds (max 3)
              submit_answer → persist
```

Tools remain `query_asset_model`, `query_historian`, `query_live`, `query_alarms`.
Playbook statements are allowlisted `SELECT`s / existing GraphQL, 5s timeout, 200-row
cap, Access Group wrap (admin unrestricted). The model never sees DB passwords or the
OpenAI key.

**GET `/agent/scope`** (Bearer required) returns `{ "roots": ["…"], "unrestricted": false }`
so the drawer chip can name the default plant without waiting for a chat turn.

## 5. Context pack

Built every chat turn on the replica.

| Field | Source |
|---|---|
| `route` | `pageContext.route` |
| `focus.assetPath` | `pageContext.assetPath` if non-empty |
| `focus.metricKey` | `pageContext.metricKey` if non-empty |
| `focus.alarmTopic` | `pageContext.alarmTopic` if non-empty |
| `defaultPlant` | Access Group root paths; `admin` → Asset Model site/enterprise paths |
| `pageHint` | From route: alarms list, CM tags, hierarchy node, or plant |

**Resolution:** if any focus field is set, playbook paths use that focus. Otherwise they
use `defaultPlant`. He must not ask for a path that is already in the pack.

Page context from the browser stays the same shape (`route`, `assetPath`, `metricKey`,
`alarmTopic`). The agent fills roots; the browser does not guess Access Groups.

## 6. Classify and playbook

Classifier is deterministic (substring / job-card id / small keyword set), not a second
model call.

| Kind | Triggers | Lookups in order |
|---|---|---|
| `alarms_on_focus` | “in alarm”, job card 1 | `query_alarms` (enabled + firing) then Asset Model names for topics under focus/default plant |
| `metric_vs_window` | “last eight hours”, “this metric” | Resolve Metric (selection, else Metric Definitions on focus Assets) → historian last 8h (last shift if OEE calendar exists) → `query_live` |
| `publishers_on_path` | “published in the last hour”, “on this path” | Historian last 1h under focus/default paths → live for those topics |
| `performance_rca` | “lost performance”, “why is X down”, “P101” + weeks | Asset + Metric Definitions → historian 3 weeks + last shift → `oee.downtime_event` on that line → alarms on that Asset → live |
| `plant_overview` | “hi”, “what’s going on?”, greetings | Alarm firing under default plant → publishers last hour → one-line Asset Model map of roots |
| `platform_map` | “how does historian work”, “Access Group”, “what is this console” | Console map card only. No SQL/GraphQL. |
| `other` | everything else | No forced playbook. Model may call tools with the pack in the system prompt. |

After the playbook, OpenAI writes the cited answer. Extra tool rounds remain max 3 for
follow-up only. Writes (ack, edit rules, setpoints) stay a text refusal with no plant
tool.

**Empty results:** “I cannot see … in that window / Access Group / store.” Name the
store. Do not ask for a path already in the pack. Do not invent numbers.

**Citations:** `{ asset, topic, time, source }` as today.

## 7. Console map (curated)

Short card, shipped in `13_uns_factory_agent`, not fetched from git at runtime:

- Console pages: Hierarchy, Condition Monitoring, Alarms, historian jumps.
- Stores: Postgres `model` = what exists; Timescale `uns_metrics` / `oee.downtime_event`
  = history; GraphQL = live UNS Nodes and Alert Rules.
- Access Groups hide plant rows; chats are per caller.
- He is read-only. Service health is out of this slice.

## 8. UI

Context chip (`data-testid="copilot-context"`):

- Focus set → that path / Metric / alarm topic.
- Else one root → `Plant · {root}`.
- Else several roots → `Plant · {n} Access Groups`.
- Never `Plant · no Asset selected` once `/agent/scope` succeeds.

Starter cards (empty thread). When **no** focus, copy is plant-scoped:

1. What is in alarm in my plant right now?
2. Has Pump P101 lost performance over the last three weeks?
3. How does the selected metric (or this line’s main metrics) compare to the last eight hours?
4. Which Assets on my plant path published in the last hour?

When **focus is set**, the same four kinds may say “this Asset / this metric / this
path.” Cards still must not mention schedule, SOP, or work instructions.

Greeting unchanged. Composer enabled when health is ok. Playbook-empty answers stay in
the thread. Citations still jump; drawer stays open. No `#/copilot` route.

## 9. Errors

| Case | Behaviour |
|---|---|
| No tree selection | Default plant. Do not ask for a path. |
| Empty playbook rows | “I cannot see …” in the thread. Lamp not `down`. |
| Outside Access Group | Asset outside your group (same meaning as GraphQL 403). |
| Write request | Text refusal. |
| Missing/expired token | 401. Sign in again. |
| OpenAI / JWKS / proxy down | Unavailable, as today. |
| “Why is GraphQL down?” | One sentence: not in this slice. |

## 10. Testing

No live OpenAI in CI. Mock the model.

**Agent**

- Each starter line and “hi” classify to the expected kind.
- Empty focus: playbook SQL/GraphQL filters use Access Group roots.
- Focus `…/P101`: historian/alarms scoped to that path, not all roots.
- Empty historian mock: answer admits cannot see; no numeric invention.
- `platform_map` does not call SQL or GraphQL.
- `GET /agent/scope` without Bearer is 401; with token returns roots.
- Existing SQL guard, Access Group wrap, conversation isolation, JWKS skip-enc-key tests stay green.

**Frontend**

- Chip without selection is not `no Asset selected` when scope returns roots.
- POST `/agent/chat` still sends page context + `conversationId`.
- Job cards: four plant-focused prompts; no schedule/SOP language.
- Unavailable only on health/auth/proxy failure, not on empty plant data.

## 11. Decisions (locked)

| Topic | Choice |
|---|---|
| Default plant | Access Group roots; admin = whole model |
| Focus | Page/tree selection wins when set |
| RCA | Server playbook on the four existing tools |
| `hi` | `plant_overview`, not small-talk only |
| Console how-it-works | Curated card, not RAG |
| Platform-health RCA | Out |
| Chip | From `GET /agent/scope`, never “no Asset selected” after a good scope |
| Tools | Still exactly four plant tools |

## 12. Out of this spec

Local models; streaming; plant writes; Cypher; MQTT/Kafka/Grafana tools; ingesting ADRs;
service-health RCA; shared transcripts; changing ADR-0009 token storage.
