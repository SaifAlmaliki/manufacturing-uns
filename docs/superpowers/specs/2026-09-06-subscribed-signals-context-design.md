# Subscribed Signals context

Date: 2026-09-06
Modules: `09_uns_model` (catalog columns, Unit of Measure / label catalogs, Metric Definition upsert), `07_uns_graphql` (queries and mutations), `11_frontend` (`#/connectivity` Signals tab, Condition Monitoring cards)
Status: Approved design, awaiting implementation plan

## 1. Problem

Assets & Connectivity can subscribe OPC UA Variables and republish them. Condition Monitoring
already draws one card per subscribed catalog tag. Those cards have a display name, a topic,
and a guessed `DOUBLE` / `BOOLEAN` — no **Unit of Measure**, no **Asset**, no engineer-authored
type. Operators see `1234` with no `°C` and no “Furnace”.

There is no console surface to attach that context. Metric Definitions can store a Unit of
Measure, but nothing lists units or lets an engineer pick one per subscribed tag.

## 2. Decisions

| Topic | Choice |
| --- | --- |
| Assignment | Real Asset (any Asset Level) **and** context on the catalog tag |
| New signals | Out of scope. No `+ New Signal`. Subscribe stays in Browse data |
| Labels | Shared catalog, same “type once, reuse” rule as units |
| Type | Semantic class **and** data type |
| Topic vs Asset | Store `asset_id`. Do **not** rewrite `mqtt_topic` |
| Persistence | Extra columns on `console.connectivity_tags` + two small catalogs |
| Enrichment | When Asset **and** Unit of Measure are set, upsert a Metric Definition |
| Unit list | Seeded engineering list + **Other…** persisted in Postgres |
| Tab contents | All subscribed tags; filterable to one server |
| Condition Monitoring | Value + Unit of Measure + Asset display name; data type drives the chart |
| Editable fields | Context inline; display name, MQTT topic, unsubscribe in a side panel |
| Bulk | Multi-select apply of unit / Asset / class / data type / label. Not topic, not unsubscribe |
| Required fields | All new fields optional. Filter “missing unit” |
| Who edits | Same as connectivity: engineer and admin. Others see context on CM only |

## 3. Findings that shape the design

1. **Subscribed tags already live in `console.connectivity_tags`.** Columns today: `server_id`,
   `node_id`, `browse_path`, `display_name`, `mqtt_topic`, `subscribed`. Condition Monitoring
   already loads them via `getConnectivityServers`.
2. **Unit of Measure is a glossary term.** Bare “unit” collides with the Production Unit Asset
   Level. `conf/oee/units.yaml` names OEE Lines, not `°C`.
3. **Metric Definition** is the Asset Model’s home for Unit of Measure. Condition Monitoring
   does not join it today. Writing only Metric Definitions would leave CM blank. The catalog
   is what CM reads; the Metric Definition upsert keeps Grafana / historian Enrichment aligned.
4. **`merge_discovered` already protects `mqtt_topic`.** The new context columns must get the
   same protection. Re-browse must not clear a Unit of Measure.
5. **CM scopes by topic prefix and leaf name**, not by Asset id. After this change, an assigned
   Asset wins: the card is in scope for that Asset and its ancestors. Unassigned tags keep
   today’s topic / leaf match.
6. **Connectivity mutations are engineer/admin.** The Signals tab uses the same feature key.
   Condition Monitoring stays on `uns_tree` and only *displays* catalog context.
7. **Timescale now has volume `timescale_data`.** Catalog rows, including new units and labels,
   survive `docker compose down` without `-v`.

## 4. Language

**Signal** (console): a subscribed `ConnectivityTag` as shown on the Signals tab and on a
Condition Monitoring card. Not a new store. Not a Metric (a Metric is a scalar leaf of a
Historic Event).

**Unit of Measure catalog**: rows the Unit of Measure dropdown reads. Seeded, then grown by
**Other…**.

**Label catalog**: rows the label chip picker reads. Empty at first; first use inserts.

**Semantic class**: `MeasuredValue`, `EnergyConsumption`, `CounterOK`, `CounterNOK`, `State`.

**Data type**: `Double`, `Boolean`, `Integer`, `String`. When unset, CM keeps inferring from
samples.

## 5. Information architecture

`#/connectivity` gains two tabs:

| Tab | Job |
| --- | --- |
| **Servers** | Today’s OPC UA server list, Add Server, Test, Browse data |
| **Signals** | Every `subscribed: true` tag across those servers, with context editors |

No new sidebar item. No change to Plant hierarchy. Subscribe still happens in Browse data.
Unsubscribe is also available from the Signals side panel (confirm).

## 6. Data model

### 6.1 `console.units_of_measure`

| Column | Notes |
| --- | --- |
| `symbol` | Primary key, unique, trimmed. e.g. `°C` |
| `name` | Optional long name, e.g. `degree Celsius` |
| `created_at` | |

Seed on migrate (insert if not exists):

`°C`, `K`, `bar`, `Pa`, `kPa`, `%`, `kWh`, `kW`, `L/min`, `m³`, `Hz`, `rpm`, `A`, `V`.

**Other…** inserts a row. Duplicate symbol (case-sensitive match after trim) returns the
existing row; it is not an error. Do not delete a symbol that any tag still references.

### 6.2 `console.signal_labels`

| Column | Notes |
| --- | --- |
| `name` | Primary key, unique, trimmed. e.g. `Cycle` |
| `created_at` | |

No seed. **Other…** / first chip insert persists the name. Same duplicate rule as units.

### 6.3 Extra columns on `console.connectivity_tags`

| Column | Type | Notes |
| --- | --- | --- |
| `asset_id` | FK `model.asset.id` ON DELETE SET NULL | Optional. Any Asset Level. Topic unchanged |
| `unit_of_measure` | text, nullable | Must be null or a `units_of_measure.symbol` |
| `semantic_class` | text, nullable | One of the five classes, or null |
| `data_type` | text, nullable | One of the four data types, or null |
| `labels` | text array, not null, default `{}` | Each element exists in `signal_labels` |

`merge_discovered` / `replace_subscribed_tags` must not overwrite these columns or
`display_name` once the engineer has set them. `display_name` from OPC may fill only when
the stored display name is still empty (first discovery).

### 6.4 Metric Definition upsert

When a tag has both `asset_id` and `unit_of_measure`, upsert a Metric Definition:

- `asset_id` = the assigned Asset
- `metric_key` = the MQTT topic suffix below `asset.path` when the topic starts with that
  path; otherwise the tag `browse_path` if set, else `display_name`
- `unit_of_measure` = the catalog symbol
- `display_name` = tag `display_name`

Clearing the Asset or the Unit of Measure does **not** delete the Metric Definition (an
engineer may still want Enrichment). Clearing `asset_id` because the Asset was deleted
leaves unit and labels on the tag.

## 7. GraphQL

New or extended types (exact names in the implementation plan):

- Query `unitsOfMeasure`: list catalog rows
- Mutation `saveUnitOfMeasure(symbol, name)`: Other…
- Query `signalLabels`: list catalog rows
- Mutation `saveSignalLabel(name)`: Other…
- Query `getSubscribedSignals`: flat list of subscribed tags with server id/name, Asset
  (id, path, display name, level), and the new fields
- Mutation `updateConnectivityTag(...)`: display name, mqtt topic, asset id, unit, class,
  data type, labels. Partial update. Empty unit/asset clears. Does not toggle `subscribed`
- Existing `unsubscribeConnectivityTag` stays the unsubscribe path
- `ConnectivityTagType` (and therefore `getConnectivityServers`) grows the new fields so
  Condition Monitoring does not need a second query

Role gates: same as today’s connectivity writes (engineer, admin). Reads of the new
catalogs: same as `getConnectivityServers` / OPC probe roles. Condition Monitoring already
calls `getConnectivityServers`; it just starts reading the extra fields.

## 8. Signals tab UI

Compact console page (no extra title banner). **frontend-design:** dense plant table in this
console’s type, spacing, and orange accent — Factory Intelligence “Devices and Signals”
density, not a generic admin grid.

**Toolbar:** search (name, topic, node id); server filter; Asset filter; “missing unit”
chip; semantic class; label. Multi-select checkbox column.

**Columns:** select, display name, server, Asset, Unit of Measure, semantic class, data
type, labels, subscribed.

**Inline (immediate save):** Asset picker (Plant hierarchy, any level, clearable);
Unit of Measure `<select>` ending in **Other…**; semantic class; data type; label chips
with **Other…**.

**Other…** opens a short field for symbol (units) or name (labels). On confirm, persist
then select it on the current row (and on bulk apply if that is what launched it).

**Side panel** (click display name): display name, MQTT topic, the same context fields,
Save, Unsubscribe with confirm. Topic validation stays `non-empty` (existing topic rules
if any). Unsubscribe removes the row from this tab and from CM.

**Bulk bar** (one or more selected): Apply Unit of Measure / Asset / class / data type /
add label. Does not change display name, topic, or subscribed.

**Empty state:** “Subscribe variables from Browse data on a server — then attach units
here.”

**Load error:** same red banner pattern as the Servers tab (`GraphQL endpoint unreachable`
is a load error, not an empty plant).

## 9. Condition Monitoring changes

On each card:

- Latest value, then Unit of Measure when set (`1234 °C`)
- Asset display name when `asset_id` is set (subtitle, not a second title)
- Chart: authored `data_type` when set (`Boolean` → step; numeric → line). Else today’s
  sample inference

**Scope:** Condition Monitoring’s tree is still UNS Nodes (topics), not the Asset Model.
If the tag has `asset_id`, it is in scope when `asset.path` equals `selectedNode.topic`,
either is a prefix of the other, or the Asset segment equals the node’s leaf name.
Also keep today’s topic / leaf match on `mqtt_topic` so mixed plants work. Unassigned
tags: today’s match only.

Semantic class and labels are **not** drawn on the card in this slice.

Viewers and operators who cannot open `#/connectivity` still see unit and Asset on cards.

## 10. Errors and edge cases

| Case | Behaviour |
| --- | --- |
| GraphQL down | Banner, no fake empty catalog |
| Duplicate Other… symbol | Return existing row |
| Unit still referenced | Refuse delete (v1 has no delete UI) |
| Asset deleted | `asset_id` SET NULL; unit and labels remain |
| Empty data type | CM infers from samples |
| Unsubscribe | Confirm; row leaves Signals and CM |
| Discovery / re-subscribe | Context columns and edited display name survive |
| Viewer hits Signals | Existing AccessRestricted for connectivity |

## 11. Tests

- Seeded units appear; Other… inserts and the next dropdown includes it
- Other… duplicate symbol is the same row
- Saving unit + Asset on a tag upserts a Metric Definition
- `merge_discovered` does not clear unit, Asset, labels, class, data type
- `getConnectivityServers` / `getSubscribedSignals` return the new fields
- Signals tab: missing-unit filter; server filter; bulk apply unit does not change topic
- Side panel unsubscribe requires confirm and drops the row
- Viewer cannot mutate; CM card still renders `°C` and Asset name from the catalog
- CM card without unit looks like today (value only)
- Assigned Asset scopes the card under that Asset and its parents

## 12. Out of scope

- Creating a signal that was not subscribed from Browse data
- Rewriting MQTT topic when assigning an Asset
- Health / Unhealthy column from the Factory Intelligence reference
- Drawing semantic class or labels on Condition Monitoring cards
- Bulk unsubscribe or bulk topic edit
- Authoring a Unit of Measure admin page beyond Other…
- Deleting units or labels from the catalogs
- Changing who may open Assets & Connectivity

## 13. Success

An engineer subscribes Variables on Browse data, opens **Signals**, attaches `°C` and a
Machine (or any Asset) — including a custom unit typed once — and Condition Monitoring
shows `1234 °C` under that Asset after a refresh. `docker compose down` (no `-v`) keeps
the catalogs.
