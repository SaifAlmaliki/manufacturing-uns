# Condition Monitoring

Date: 2026-09-05
Modules: `11_frontend` (route, view, cards, name-matching). No new GraphQL types.
Status: Approved, not yet implemented

## 1. Problem

Assets & Connectivity can subscribe OPC UA tags and publish them to MQTT. The operator then
has nowhere plant-shaped to watch those signals together. `#/tree` is a three-pane explorer
(Namespace Tree, Grafana payload, Live Feed). Grafana and the ticker answer "is MQTT
moving?"; they do not answer "what is P201 doing for the last hour?"

Condition Monitoring replaces `#/tree` with a page that reuses the Namespace Tree, shows one
card per **subscribed** catalog tag, draws historian lookback plus a live tail, and scopes
the grid to a zone when the operator clicks the tree.

## 2. Findings that shape the design

1. **`UnsTreeView` has no props.** It reads `UNSContext` (`selectedNode`, `selectNode`,
   expand, bookmarks). Reuse it as-is. Condition Monitoring watches `selectedNode` to set
   scope. Do not fork a second tree.
2. **Subscribed tags live in `console.connectivity_*`.** `getConnectivityServers` already
   returns `tags` with `subscribed`, `mqttTopic`, `browsePath`, `displayName`. Cards are
   that list filtered to `subscribed: true`. Subscribe/unsubscribe stays in Browse Data.
3. **Catalog topics are often browse paths.** A tag may publish
   `Server/OpcPlc/.../Distribution/P201/Fault` while the tree node is
   `AcmeWater/Site1/Distribution/Train1/P201`. Prefix match fails until someone edits the
   MQTT topic. v1 also matches on **equipment / leaf name** (`P201`).
4. **`getConnectivityServers` is an OPC probe role** (engineer and admin). The route stays
   on the existing `uns_tree` feature. If the catalog query is forbidden, show that error —
   do not render an empty subscription list as if the plant had no tags.
5. **The console has no chart library.** Simulator `SignalInspector` draws a 60×16 sparkline.
   That is not a 60-minute axis. v1 adds a small SVG chart in this feature folder. Add a
   dependency only if axes and hover cannot be tested without one.
6. **Historian and MQTT already exist.** `getHistoricEventsInTimeRange` and
   `subscribeMqttMessages` are the lookback and the tail. Do not open a second OPC session
   from the browser. Do not embed Grafana on this page.
7. **The global MQTT feed is the wrong tail.** `UNSContext` subscribes to `#` (or the
   selected node when Follow is on), caps the buffer (~500), and honors Pause. Condition
   Monitoring uses its own `subscribeMqttMessages` on the visible tags' `mqttTopic`s.

## 3. Information architecture

| Before | After |
| --- | --- |
| `#/tree` → `HomeView` (tree + Grafana + Live Feed) | `#/condition-monitoring` → Condition Monitoring |
| Sidebar **UNS Tree** | Sidebar **Condition Monitoring** (Main menu, `uns_tree`) |
| Header greeting + "Browse the ISA-95…" | Header title **Condition Monitoring** only (no subtitle) |

`#/tree` redirects to `#/condition-monitoring`. Dashboard, Historian, Alarms, and Assets &
Connectivity do not change. `PayloadInspector` and `LiveMqttFeed` stay in the repo; this
route does not mount them. Raw payload and Grafana remain on Historian. The live ticker
remains the Dashboard feed (`mqttFeed` in context).

## 4. Layout

Compact console pattern (`PageContent fullWidth`, no in-page title banner):

- **Left:** existing `UnsTreeView` (filter topics, expand, select, refresh).
- **Right:** `CompactKpiRow` → `FilterToolbar` → scrollable card grid.

`FilterToolbar` contains:

- Time range: **15m / 60m / 4h / 24h**. Default **60m**.
- Search: signal display name or MQTT topic (case-insensitive substring).
- **All signals** chip — visible only when a zone scope is active.

No Details / Comparison / Order History tabs. No pin, download, or parameter-predicate row.

## 5. Which cards exist, and which are visible

**Card set** = every catalog tag with `subscribed: true`, across all OPC UA servers returned
by `getConnectivityServers`. Tree selection never creates cards.

**Default scope** = all subscribed tags.

**Zone scope:** clicking a tree node sets scope to that node. A tag is visible if it
**matches** the selected node or any **currently loaded** descendant of that node. **All
signals** clears scope only; it does not clear `selectedNode` (the tree highlight can stay).

**Search** applies after scope.

### Name matching

A tag **matches** a tree node when any of these is true, in order:

1. **Prefix.** `mqttTopic` equals `node.topic` or is `node.topic + '/' + rest`.
2. **Leaf name.** The last `/`-separated segment of `node.topic` equals a `/`-separated
   segment of `mqttTopic` or of `browsePath`.

Known limitation: two assets named `P201` share name-matched tags when either is selected.
Prefix match wins when topics have been edited onto the UNS path. Remapping topics is out
of scope.

## 6. Card

Each card is a `ConsoleCard`:

- Title: `displayName`. Subtitle: full `mqttTopic` (wrap).
- Latest value and a type hint (`BOOLEAN`, `DOUBLE`, …) when a sample exists.
- **Graph | Table** toggle. Default Graph.
- No Unsubscribe control. That stays in Browse Data.

**Numeric tags:** continuous line. Table = timestamp + value, newest first, **at most 200
rows**.

**Boolean tags:** value stored as 0/1. Chart is a **step** line (hold until the next
change). Table = **transitions only** (time, from → to), newest first, **at most 200
rows**. A boolean is a JSON/JS boolean, or a payload type of `BOOLEAN`.

Chart X axis is the selected time range. Hover shows time + value. Render **at most 1500**
points (min/max buckets if the historian returns more). Quality is taken from the latest
sample when the payload carries it; otherwise the card shows "—". The page does not invent
`GOOD`.

Changing the time range refetches historian points and drops samples outside the window.
The live subscription stays up if the visible topic set is unchanged.

## 7. Data flow

On entering the route:

1. `getConnectivityServers` → subscribed tags. Forbidden or transport error → banner with
   the real message; `[]` is not shown as "no tags".
2. For **visible** tags, `getHistoricEventsInTimeRange` with each tag's `mqttTopic` and the
   selected window. A topic with no rows: that card shows "No historian points in range".
3. `subscribeMqttMessages` on the visible tags' exact `mqttTopic`s. Append to the in-memory
   series and to the table. Independent of Live Feed pause / follow / buffer.

Refresh the catalog when the route is entered again (returning from Connectivity).

Historian miss is per-card. GraphQL/catalog failure is a page banner; cards already drawn
stay.

## 8. KPI row

Compact chips, counts over the **visible** (scoped + searched) tags:

| Chip | Meaning |
| --- | --- |
| In view | Visible card count |
| Live | Visible tags that received a live sample this session |
| Faults on | Visible tags whose display name or leaf is `Fault` (case-insensitive) and latest value is true/1 |
| Unacked | `AlarmContext` alarms that are unacked and whose topic matches a visible tag (prefix or leaf name, same helper) |
| Critical | Same set, severity critical |

Unacked and Critical navigate to `#/alerts`. This page does not acknowledge, silence, or
edit rules.

## 9. Empty states

| Situation | Copy |
| --- | --- |
| Zero subscribed tags (successful catalog read) | Subscribe tags in Assets & Connectivity. Link to `#/connectivity`. |
| Scope active, no visible tags | No subscribed signals in this zone. **All signals** chip. |
| Search matches nothing | No signals match this search. |
| Historian empty for one topic | Card-local empty chart; not a page error. |

## 10. Tests

- Name matching: `P201` UNS node matches `…/Distribution/P201/Fault`; `AcmeWater/…/P201`
  prefix-matches a remapped topic; `Train1` scope includes descendant `P201` tags and
  excludes `P202` if `P202` is not a descendant.
- Series: historian points then live append; samples outside the window drop on range
  change; boolean table lists transitions only.
- View: empty catalog vs catalog error; scoped empty zone; Graph | Table; `#/tree`
  redirects to `#/condition-monitoring`.

## 11. Out of scope

- Grafana or Live Feed on this page
- Pin, CSV/download, parameter predicates, Graph vs Table as a page-level control
- Rewriting MQTT topics onto the asset model
- Acknowledging or authoring alarms
- A second OPC UA client in the browser
- New GraphQL schema
- Deleting `PayloadInspector` / `LiveMqttFeed` (unmounted here, still available to move)

## 12. Error handling

- Catalog error: rose banner, real GraphQL message, no fake empty plant.
- Historian error: page banner; keep cards; empty series on failed topics.
- Live socket drop: KPI Live stops incrementing; last historian/live points remain; do not
  clear the chart.
- Session expired: existing GraphQL client message; same as other console routes.
