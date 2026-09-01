# OEE engine

Date: 2026-09-01
Modules: `12_uns_oee` (new), `09_uns_model`, `07_uns_graphql`, `99_simulator`, `conf`,
root `pyproject.toml`, `docker-compose.yml`, `08_uns_observability`
Status: Approved, not yet implemented

## 1. Problem

The memo's pilot succeeds or fails on one number, and the platform does not have it. It has
something worse: a fabricated number wearing the name.

`conf/simulator/production.yaml` publishes `Availability`, `Performance`, `Quality` and
`Oee` on every production cell, and none of them is OEE:

- `Availability` is `100.0 * ctx.running` (`:106`). The file's own comment says
  "Instantaneous, so this is a 0-or-100 square wave and **NOT** a rolling percentage... the
  rolling view belongs in Grafana."
- `Performance` is `100.0 * ctx.production_rate` (`:114`) — the simulator's own internal
  knob. The ideal-cycle-time definition of Performance appears nowhere.
- `Oee` is `Availability * Performance * Quality / 10000.0` (`:131`), the product of three
  instantaneous values. It flickers between 0 and roughly 80; it is not a shift figure.
- `DowntimeReason` (`:136`–`:162`) is a lookup table over `ctx.state`, so a reason can only
  ever restate the state that caused it. It can never say why the material ran out.

There is no shift calendar anywhere in the repository, and without a window OEE is not a
metric at all — it is the instantaneous product above.

This is the same failure the OPC UA spec rejected in its finding 7, where the simulator
fabricates a `Normal`/`Warning`/`Alarm` `status` it has no basis to judge. The response is
the same: compute the real thing from real inputs, and stop publishing the invention.

This spec adds a service that computes Availability, Performance, Quality and OEE per
production unit per shift from historised events, attributes the lost time to reason codes,
and publishes the result back into the Unified Namespace.

## 2. Findings that shape the design

Established by reading the code, not assumed:

1. **Every input the calculation needs is already published and already historised.**
   `conf/simulator/production.yaml` emits `GoodCount` (`:68`), `RejectCount` (`:76`),
   `TotalCount` (`:84`), `CycleTime` (`:90`), `PackMlState` (`:17`), `PackMlStateCode`
   (`:25`), `RecipeId` (`:173`) and `BatchId` (`:163`). These are legitimate machine
   signals, unlike the four derived ones in section 1.
2. **`flatten_payload_to_metrics` projects every scalar leaf into `uns_metrics`**
   (`04_uns_historian/src/uns_historian/metric_flattener.py:10`), so each of those signals
   is already a queryable row keyed by `(topic, metric_name, time)`.
3. **The index for this query already exists.**
   `idx_uns_metrics_topic_metric_time ON uns_metrics (topic, metric_name, time DESC)`
   (`04_uns_historian/sql_scripts/04_setup_metrics_hypertable.sql:19`–`:20`) is exactly the
   access path a per-unit per-shift fetch needs.
4. **The volumes are trivial.** `conf/settings.yaml:173`–`:180` sets the `status` tier to
   30 s and the `meter` tier to 900 s, so one 8-hour shift is roughly 960 state samples and
   32 counter samples per unit. Fetching a shift's raw rows and computing in Python is not
   a performance concern at any plausible plant size.
5. **`param_type` defaults to `ProcessValue`** (`99_simulator/src/uns_simulator/signals.py:66`
   and `:481`), so `GoodCount` lands on `.../MES-01/ProcessValue/GoodCount` while
   `PackMlState`, which declares `param_type: Status`, lands on `.../MES-01/Status/PackMlState`.
   The engine's metric bindings must therefore be authored per signal, not derived from a
   naming rule.
6. **The topic shape is
   `<enterprise>/<site>/<area>/<line>/<cell>/<equipment>/<ParameterType>/<ParameterName>`**
   (`99_simulator/src/uns_simulator/models.py:80`), and `ParameterType` is a closed
   five-member enum — `ProcessValue`, `Setpoint`, `Status`, `Alarm`, `EVENT` (`models.py:44`–`:48`).
   None of them describes a computed shift KPI.
7. **`counters` are cumulative and restart at zero.** `GoodCount` and `RejectCount` declare
   `initial: 0.0` (`production.yaml:73`, `:81`), so a process restart mid-shift makes a
   naive `last − first` delta go negative.
8. **No dashboard depends on the fabricated signals.** Neither
   `08_uns_observability/grafana/dashboards/platform-observability.json` nor
   `process-visualization.json` mentions `Oee`, `Availability`, `Performance`, `Quality` or
   `DowntimeReason`. Retiring them is contained. `Oee` does carry `export_metric: true`
   (`production.yaml:135`), which feeds a Prometheus gauge via
   `99_simulator/src/uns_simulator/metrics.py:83`–`:88`; that goes with it.
9. **The Asset Model is the right home for master data, and says so.**
   `09_uns_model/src/uns_model/tables.py:18`–`:25` states these tables are "low-volume,
   relational and human-edited, which is what the ORM is for", per ADR-0004. Shift
   patterns, products and ideal cycle times are precisely that.
10. **`MetricDefinition` already establishes the "null means every Asset" idiom**
    (`tables.py:172`–`:174`: a null `asset_id` "means 'every Asset', which is how one row
    gives `°C` to the Temperature of all forty mixers"), enforced with
    `postgresql_nulls_not_distinct=True` (`:184`). Ideal cycle time and reason mapping reuse
    it rather than inventing a second convention.
11. **Migrations are sequential and `0003` is next** — `09_uns_model/migrations/versions/`
    holds `0001_asset_model.py` and `0002_console_alert_rules.py`.
12. **`asset_model_setup` already imports file-authored master data into `model`.** The
    Compose service creates the schemas and "imports the configured plant hierarchy as
    Assets", which is the mechanism OEE master data reuses.
13. **The uniqueness key on the raw hypertable includes the payload.**
    `CONSTRAINT unique_event UNIQUE (time, topic, client_id, mqtt_msg)`
    (`docker-compose.yml:128`), and the README wants it narrowed to
    `(time, topic, client_id)`. A republished revision of the same shift therefore inserts
    under the current form and collides under the proposed one, so the publisher must not
    depend on which wins.
14. **Module and port numbers.** `10_` is reserved by the OPC UA edge connector spec and
    `11_frontend` exists, so this is `12_uns_oee`. `conf/settings.yaml` assigns metrics port
    9091 to the historian (`:83`), 9092 to the graph database (`:76`) and **9093 to the
    simulator** (`:87`); with 9094 going to the OPC UA connector, this module takes **9095**.
15. **`ModelConfig` already provides the database handle.**
    `09_uns_model/src/uns_model/model_config.py` exposes
    `ModelConfig.from_settings(module_env)`, `.is_valid()`, `.url` and `.connect_args()`,
    reading the same `historian.*` keys because the Asset Model shares the historian's
    database. No new connection code is needed.

## 3. Three rules the whole design serves

- **Rule 1 — the calculation is a pure function of historised input.** No state is carried
  between runs. Recomputing a shift from the same input rows must yield the same result,
  bit for bit. Every requirement in this spec — correcting a reason code, absorbing late
  data from an OPC UA spool replay, fixing a wrong ideal cycle time — is served by
  re-running, and only Rule 1 makes re-running trustworthy.
- **Rule 2 — Performance uses Total Count; Quality uses Good over Total.** Scrap is a
  quality loss. Using Good Count in both factors penalises it twice, reads several points
  low, and is nearly impossible to detect after the fact.
- **Rule 3 — a manual reason code is never overwritten by auto-classification.** Enforced
  in the writer, not by convention. An operator's attribution outranks a state-transition
  guess permanently.

## 4. Scope

**In scope.** A shift calendar with timezone and exception handling; per-unit metric
bindings; counter delta with reset detection; stop-interval extraction; the four factors
per shift with per-product Performance; auto-classified downtime events; an immutable
revisioned shift record; late-data revision; a GraphQL mutation to reassign a reason and
queries to read results; publication back into the Unified Namespace; Prometheus
instrumentation; retirement of the simulator's fabricated signals; a Grafana OEE dashboard.

**Out of scope, deliberately.** No live or rolling OEE — closed-shift only, which is what
removes the need for streaming state. No operator-facing frontend view for attributing
downtime; this spec delivers the events, the vocabulary and the mutation, and the console
surface is its own spec. No batch or order genealogy — `model.product` is its groundwork,
not its delivery. No OEE targets, alerting or escalation; `console.alert_rules` already
exists and can watch the published topic. No six-big-losses or TEEP decomposition. No
write-back to any control system.

## 5. Module layout

New workspace member `12_uns_oee`, package `uns_oee`:

```
12_uns_oee/
├── Dockerfile                 # python:3.14-alpine3.22, UNS_MODULE=12_uns_oee
├── pyproject.toml
├── README.md
├── src/uns_oee/
│   ├── oee_config.py          # Dynaconf-backed config + validation
│   ├── master_data.py         # load model.* master data into frozen dataclasses
│   ├── shift_calendar.py      # pattern + exceptions → concrete UTC shift windows
│   ├── sources.py             # fetch state / counter / product samples for a window
│   ├── counters.py            # monotonic counter delta with reset detection
│   ├── states.py              # sample series → stop intervals and producing duration
│   ├── oee_calc.py            # the pure calculator: inputs → ShiftMetrics
│   ├── classifier.py          # stop interval → reason code
│   ├── store.py               # idempotent write, revision bump, input fingerprint
│   ├── publisher.py           # one long-lived aiomqtt connection
│   ├── scheduler.py           # boundary wake, late re-check, recompute queue drain
│   ├── recompute_cli.py       # --recompute <asset-path> <from> <to>
│   ├── prometheus_metrics.py
│   ├── health_check.py
│   └── main.py                # supervisor
└── test/
```

`oee_calc.py`, `counters.py`, `states.py`, `classifier.py` and `shift_calendar.py` take plain
dataclasses and return plain dataclasses — no database, no clock, no MQTT. That is what makes
the arithmetic in section 8 testable to the decimal, and it is where most of the risk in this
module lives.

The pipeline order within one shift is fixed, for the reason given in section 8:

```
shift_calendar → sources → counters + states → classifier → oee_calc → store → publisher
```

`classifier` runs *before* `oee_calc` because a reason's `is_planned` flag is an input to
Loading Time.

## 6. Where the computation lives: Python, not SQL

SQL fetches rows; Python computes. Findings 3 and 4 make the fetch cheap and the volume
small, so the only real question is where the logic is most likely to be correct — and these
are the parts that would be both hardest to express and impossible to test properly in SQL:

- **The state at shift start is the last sample *before* the boundary, not the first one
  inside it.** Get this wrong and every shift's first stop is truncated by up to one sample
  interval. This is the classic OEE implementation bug.
- **Counter reset detection** (finding 7).
- **Per-product segmentation with time weighting**, which the per-Asset × Product decision
  requires.
- **Partial overlap between a planned exception window and a stop interval.**

A third approach was considered and rejected: Timescale continuous aggregates exposing a
`shift_oee` view, with no service at all. It cannot publish back into the namespace, cannot
hold a corrected reason code, cannot hold an immutable revisioned record, and cannot express
time-weighted per-product Performance.

## 7. Data model

### 7.1 Master data — schema `model`, migration `0003_oee_model.py`

Authored, human-editable, relational: finding 9's criteria exactly.

| Table | Columns of note |
| --- | --- |
| `model.product` | `code` UNIQUE, `display_name`, `description`. The genealogy groundwork. |
| `model.shift_pattern` | `name`, `timezone` (IANA name), `asset_id` (the Site or Line it applies to). |
| `model.shift_pattern_slot` | `shift_pattern_id`, `day_of_week` (0–6), `start_time` (local wall-clock `TIME`), `duration_minutes`, `label`. |
| `model.shift_exception` | `asset_id`, `starts_at`, `ends_at`, `kind` ∈ {`PLANNED_DOWN`, `NON_PRODUCING`, `HOLIDAY`}, `description`. Subtracted from Loading Time. |
| `model.oee_unit` | `asset_id` UNIQUE, `shift_pattern_id`, `state_metric_key`, `good_count_metric_key`, `reject_count_metric_key`, `product_metric_key` (nullable), `producing_states` (`TEXT[]`, default `{EXECUTE}`), `is_active`. |

**The OEE unit is the Asset you report at — normally the `LINE`** (`tables.py:57`–`:65`,
rank 4) — **and its metric bindings are paths relative to that Asset**, naming the descendant
machine the signal actually comes from:

```yaml
asset: "CovestroAG/Dormagen/Production/Line1"
state_metric_key:        "Cell1/MES-01/Status/PackMlState/value"
good_count_metric_key:   "Cell1/MES-01/ProcessValue/GoodCount/value"
reject_count_metric_key: "Cell1/MES-01/ProcessValue/RejectCount/value"
product_metric_key:      "Cell1/MES-01/Status/RecipeId/value"
```

This needs no `source_asset_id` column, because it is exactly `TopicBinding.metric_path`'s
existing meaning — "topic segments below the Asset" (`tables.py:247`–`:248`) — and the topic
to query is `asset.path || '/' || metric_key` with the trailing `/value` stripped to give
`uns_metrics.metric_name`.

The alternative, keying the unit to the machine that publishes the counts, yields three OEE
figures for a three-cell line and no line figure, which is the one the pilot reports. Binding
at the line makes OEE a property of the production unit, with the machine merely being where
the signal originates.
| `model.ideal_cycle_time` | `asset_id`, `product_id` (nullable), `seconds_per_unit`. UNIQUE `(asset_id, product_id)` with `postgresql_nulls_not_distinct=True`. |
| `model.downtime_reason` | `code` PK, `display_name`, `category`, `is_planned`. |
| `model.state_reason_map` | `oee_unit_id` (nullable = all units), `state_value`, `reason_code` → `model.downtime_reason`. UNIQUE `(oee_unit_id, state_value)`, nulls not distinct. |

A null `product_id` on `ideal_cycle_time` is that Asset's default, and a null `oee_unit_id`
on `state_reason_map` applies to every unit — reusing finding 10's established idiom rather
than inventing a second one. A row with a value wins over a null row, as `MetricDefinition`
already does.

`producing_states` defaults to `{EXECUTE}` because in PackML that is the only state in which
the machine is making product. Every other state is a stop; `production.yaml:32`–`:48` lists
all seventeen.

### 7.2 Results — new schema `oee`

Derived, never authored. A separate schema so that which rows a human may edit is obvious
from the name, rather than being a rule someone has to remember.

| Table | Columns of note |
| --- | --- |
| `oee.shift_result` | `oee_unit_id`, `shift_start`, `shift_end`, `shift_label`, `loading_time_s`, `run_time_s`, `planned_down_s`, `unplanned_down_s`, `good_count`, `reject_count`, `total_count`, `availability`, `performance`, `performance_raw`, `quality`, `oee`, `status`, `revision`, `input_fingerprint`, `computed_at`. UNIQUE `(oee_unit_id, shift_start)`. |
| `oee.shift_result_product` | `shift_result_id`, `product_id` (nullable), `run_time_s`, `total_count`, `good_count`, `ideal_cycle_time_s`. |
| `oee.shift_result_revision` | The full prior contents of a `shift_result` row before a revision bump, plus `superseded_at`. |
| `oee.downtime_event` | `oee_unit_id`, `started_at`, `ended_at`, `duration_s`, `state_value`, `reason_code`, `reason_source` ∈ {`auto`, `manual`}, `assigned_by`, `assigned_at`, `note`. UNIQUE `(oee_unit_id, started_at)`. |
| `oee.recompute_request` | `oee_unit_id`, `shift_start`, `requested_at`, `requested_by`, `reason`, `claimed_at`, `completed_at`. |

`status` is an explicit vocabulary — `OK`, `NO_LOADING_TIME`, `NO_PRODUCTION`,
`MISSING_IDEAL_CYCLE_TIME`, `NO_INPUT_DATA` — so a shift that could not be computed is
distinguishable from one that computed badly. See section 8.

### 7.3 How master data is authored

File-authored, relationally stored. `conf/oee/shifts.yaml`, `conf/oee/units.yaml`,
`conf/oee/products.yaml` and `conf/oee/reasons.yaml` are imported into the section 7.1 tables
by the existing `asset_model_setup` container (finding 12), exactly as it already imports the
plant hierarchy as Assets. The import is idempotent and declarative: the file is the source
of truth, and a removed row is removed.

This is deliberately both: git-tracked and reviewable with no UI to build today, and
relational so that ADR-0005's GraphQL-mutation console can take over authoring later without
a data migration. `model.oee_unit`'s four metric-binding columns are the OEE analogue of the
OPC UA connector's tag map, and the reason they are columns rather than a naming convention
is finding 5.

## 8. The arithmetic

Stated explicitly because this is where OEE implementations quietly disagree.

```
Planned Down   = | (planned exception windows ∪ planned-reason stops) ∩ shift |
Loading Time   = (shift_end − shift_start) − Planned Down
Unplanned Down = | (unplanned-reason stops) ∩ Loading Time |
Run Time       = Loading Time − Unplanned Down

Availability = Run Time / Loading Time
Performance  = Σ_p (ideal_cycle_time_s(p) × total_count(p)) / Run Time
Quality      = Good Count / Total Count
OEE          = Availability × Performance × Quality
```

A stop interval is any maximal run of time in which the unit's state is not in
`producing_states`. The state in force at `shift_start` is the value of the last sample at or
before `shift_start`; the state in force at `shift_end` extends to `shift_end`.

**Planned time has two sources, not one:** a `model.shift_exception` window, and a stop
whose resolved reason code has `is_planned` — a changeover or a scheduled clean is planned
downtime whether or not anyone put it in the calendar. Both are subtracted from Loading Time.

Two consequences that constrain the implementation:

- **Reason classification is an input to the arithmetic, not a report on it.** The pipeline
  order is fixed: extract stops → classify each → compute. A design that computed the
  factors first and labelled the stops afterwards could not honour `is_planned` at all, and
  section 10's reassignment would have nothing to change.
- **Durations are measured over the *union* of intervals, never by summing them.** A planned
  exception window that overlaps a planned-reason stop must be counted once. Summing is the
  natural implementation and it silently inflates Planned Down, which inflates Availability —
  an error in the flattering direction, which is the kind nobody reports.

`oee.shift_result.planned_down_s` is that union. The split between its two sources is
recoverable from `model.shift_exception` and the shift's `oee.downtime_event` rows, so it does
not need its own column.

`Performance` uses **Total Count**, per Rule 2.

`total_count(p)` and `good_count(p)` are the counter deltas attributed to the interval during
which `product_metric_key` reported product `p`. Counter deltas are apportioned by interval,
not by time weighting: a counter is cumulative, so the delta across a product segment is
exactly that segment's production, which is more accurate than pro-rating and needs no
assumption about rate.

When `product_metric_key` is null, or a shift's product cannot be resolved, the whole shift
becomes one segment with `product_id` null and the Asset's default ideal cycle time.

### 8.1 Cases that must not become a division

| Case | Behaviour |
| --- | --- |
| `Loading Time == 0` — a fully planned-down shift | Write the row with null factors, `status = 'NO_LOADING_TIME'`. A shift nobody was scheduled to run is not a 0% shift; recording it as one poisons every average it enters. |
| `Total Count == 0` — scheduled but produced nothing | Null `performance` and `quality`, real `availability`, `status = 'NO_PRODUCTION'`. |
| `Run Time == 0` but `Total Count > 0` | Null `performance`, `status = 'NO_PRODUCTION'`; the inputs disagree and inventing a number would hide it. |
| No input rows at all in the window | `status = 'NO_INPUT_DATA'`, all factors null. Distinguishes "the unit was silent" from "the unit was idle". |
| No `ideal_cycle_time` row for the resolved product and no Asset default | Null `performance`, `status = 'MISSING_IDEAL_CYCLE_TIME'`, and `uns_oee_missing_ideal_cycle_time_total` increments. Master data gaps must be visible, not silently averaged over. |
| `Performance > 1.0` | Store the true value in `performance_raw`, store `1.0` in `performance`, use the clamped value in the OEE product, and increment `uns_oee_performance_over_unity_total`. It always means the authored ideal cycle time is wrong; clamping silently would hide bad master data, and not clamping would produce an OEE above 100%. |

### 8.2 Counter resets

Samples are walked in time order. A sample lower than its predecessor is a reset: the delta
contributed is the new sample's value, taken from zero, and
`uns_oee_counter_resets_total` increments. This is standard counter-rollover handling and it
is required by finding 7, not defensive programming.

### 8.3 Timezones and DST

Shift slots are local wall-clock times in `model.shift_pattern.timezone`, resolved against
that zone to produce concrete UTC windows. Loading Time is derived from the **actual UTC
duration** of the window, never from `duration_minutes`.

The consequence is intended: on a spring-forward day a three-shift schedule covers 23 hours
and one shift is genuinely 7 hours long; on autumn's fall-back it covers 25 and one is 9. A
design that assumes 8 hours is wrong twice a year, in a direction that flatters or damns one
shift crew, and nobody notices until an auditor does.

Ambiguous and non-existent local times — 02:30 on a fall-back or spring-forward day — resolve
to the earlier and the following instant respectively, and the choice is asserted by test
rather than inherited from a library default.

## 9. Late data and revisions

The OPC UA connector's spool exists in order to deliver values hours after they were
produced. A shift result computed minutes after the boundary can therefore be wrong through
no fault of the calculation.

`input_fingerprint` is the row count and `max(time)` over the input window. Two phases:

1. At `shift_end + settle_minutes` (default 15) — compute and write `revision = 1`.
2. Until `shift_end + late_window_hours` (default 48) — periodically recompute the
   fingerprint only. If it differs from the stored one, recompute the shift, copy the prior
   row into `oee.shift_result_revision`, bump `revision`, and republish.

Recomputing the fingerprint is one indexed aggregate per open shift, which is why the
re-check can run often and the full recompute cannot.

A revision supersedes, it does not erase: prior factors remain in
`oee.shift_result_revision` with `superseded_at`. An OEE figure that changed silently after
somebody reported it is worse than one that changed visibly, and the revision counter is what
makes the change answerable.

Rule 1 is what makes all of this sound. Because the calculation carries no state between
runs, revision *n* is not a patch applied to revision *n−1*; it is the same function over a
larger input set.

### 9.1 Backfill on first run

`uns_metrics` retains one year and the raw hypertable ninety days
(`04_setup_metrics_hypertable.sql:66`–`:69`), so on the day this engine is deployed there is
already real history to compute from. Leaving it uncomputed would show an empty trend for a
week — the pilot's headline chart, blank, for exactly as long as anyone is paying attention.

On start, the engine computes every shift from `now − backfill_days` (default 30) forward,
oldest first, for which no `oee.shift_result` row exists. This is the same code path as a
closed-shift computation — Rule 1 again — so backfill needs no separate implementation, only a
bounded enumeration of shift windows.

Two guards, both of which exist to stop backfill producing noise instead of history:

- **A shift whose window ends before the unit's earliest input row is skipped entirely, not
  written as `NO_INPUT_DATA`.** A shift that predates the deployment is not a data gap, and
  writing it as one would fill the section 15 worklist with hundreds of rows an engineer can
  do nothing about — which is how a worklist gets ignored.
- **`backfill_days` is clamped to the `uns_metrics` retention window.** Configuring 400 days
  against a one-year retention cannot silently produce a year of skipped shifts and a log
  nobody reads; the clamp is logged once at startup with both numbers.

Backfilled rows are indistinguishable from live ones by design, and they are published to MQTT
like any other result. Their `timestamp` is the historical `shift_end`, so they land in the
historian at the time they describe rather than at the time they were computed — the same
property Rule 1 gives revisions.

`recompute_cli.py` remains available for ranges beyond `backfill_days` or for a deliberate
recomputation after master data changes.

## 10. Reason codes

The engine writes one `oee.downtime_event` per stop interval, with the reason resolved from
`model.state_reason_map` — unit-specific row first, then the null-unit row — and
`reason_source = 'auto'`.

An unmapped state gets reason `UNCLASSIFIED`, never null. A downtime Pareto must always sum
to total downtime; a null bucket that quietly holds a third of the lost time is how downtime
analysis loses its credibility.

Correction is a GraphQL mutation in `07_uns_graphql`, per ADR-0005:

```graphql
assignDowntimeReason(eventId: ID!, reasonCode: String!, note: String): DowntimeEvent!
```

It sets `reason_code`, `reason_source = 'manual'`, `assigned_by`, `assigned_at`, and inserts
into `oee.recompute_request`. Per Rule 3, the engine's writer never overwrites a row whose
`reason_source` is `manual`.

Reassignment can change OEE, because a reason's `is_planned` flag moves that interval between
Unplanned Down and excluded time, which changes Loading Time and Run Time. That is correct
behaviour, and it is the reason the mutation enqueues a recompute rather than merely editing
a label.

Reads, also in `07_uns_graphql`:

```graphql
oeeShiftResults(assetPath: String!, from: DateTime!, to: DateTime!): [OeeShiftResult!]!
downtimeEvents(assetPath: String!, from: DateTime!, to: DateTime!): [DowntimeEvent!]!
downtimePareto(assetPath: String!, from: DateTime!, to: DateTime!): [DowntimeParetoBucket!]!
```

## 11. Publishing back into the namespace

One message per unit per shift, published on the unit's Asset path over one long-lived
`aiomqtt` connection at QoS 1:

```
CovestroAG/Dormagen/Production/Line1/KPI/ShiftOee
```

```json
{
  "value": 71.4,
  "unit": "%",
  "quality": 95.2,
  "timestamp": 1788307200000.0,
  "source": "uns_oee",
  "equipment": "Line1",
  "availability": 89.2,
  "performance": 84.1,
  "good_count": 12840,
  "reject_count": 182,
  "total_count": 13022,
  "shift_label": "A",
  "shift_start": 1788278400000.0,
  "status": "OK",
  "revision": 1
}
```

- `value` is OEE as a percentage, so the topic's headline number is the one its name promises.
- `equipment` is the OEE unit Asset's own segment — `Line1`, since section 7.1 binds at the
  line. The name is imprecise at line level, but it is the platform's existing convention
  ("the last segment of the Asset path", as the OPC UA spec also defines it), and inventing a
  second field name for the same idea would be worse than a slightly loose word.
- `timestamp` is `shift_end` as epoch milliseconds. Per `conf/settings.yaml:57`
  (`timestamp_attribute: "timestamp"`) this becomes the historian's `time` column, which
  places the shift's result at the shift's end — where a trend line needs it.
- `quality` here is the Quality factor as a percentage. It is deliberately **not** the OPC UA
  connector's `quality`, which is a `StatusCode` severity; the two never appear on the same
  topic, and renaming either to avoid the collision would misname it on its own topic.
- `status` carries section 7.2's vocabulary, so a consumer can tell a real 0% from a shift
  that was never scheduled.

**`KPI` is a new `ParameterType`**, added to `models.py`'s enum alongside `ProcessValue`,
`Setpoint`, `Status`, `Alarm` and `EVENT`. A computed shift KPI is none of those five, and
publishing it as `ProcessValue` would make it indistinguishable from a sensor reading —
including to the alert engine and the graph database, both of which type topics by that
segment.

Finding 2 means every field becomes its own `uns_metrics` row, so
`KPI/ShiftOee/availability` is independently queryable with no extra work.

Finding 13 means a republished revision carries the same `(time, topic, client_id)` with a
different payload: a new row under the current constraint, a conflict under the narrowed one.
The publisher therefore does not depend on which version is deployed — it publishes, and the
historian's own upsert path decides. The `revision` field is what makes the two rows
distinguishable in either case.

## 12. Retiring the simulator's fabricated OEE

Deleted from `conf/simulator/production.yaml`: `Availability`, `Performance`, `Quality`,
`Oee` (including its `export_metric: true`) and `DowntimeReason`.

Two publishers on one concept, one of them fabricated, is worse than having no OEE: it makes
the pilot's headline number unfalsifiable. Finding 8 confirms nothing consumes them.

Kept, because they are honest machine signals the engine now consumes: `GoodCount`,
`RejectCount`, `TotalCount`, `CycleTime`, `PackMlState`, `PackMlStateCode`, `RecipeId`,
`BatchId`.

No simulator behaviour needs adding. `ctx.state` already cycles through PackML, so stops
occur; `RecipeId` already has `dwell_s: 7200` (`production.yaml:178`), so a product change
occurs within a long shift and the per-product path is exercised by the shipped
configuration. For tests that need a shift's worth of history in seconds rather than hours,
the fixtures seed `uns_metrics` directly rather than waiting on the simulator.

## 13. Failure modes

| Failure | Behaviour |
| --- | --- |
| Database unreachable at startup | Retry with backoff; `uns_oee_db_up` = 0; no shift is skipped, because the boundary is recomputed from the calendar on recovery |
| Broker unreachable | The shift result is already durable in `oee.shift_result`; publication retries, and `uns_oee_unpublished_results` reports the backlog |
| A unit's inputs are silent for the whole shift | `status = 'NO_INPUT_DATA'`, factors null, one row still written — an absent row and a silent unit must not look the same |
| Master data missing for a unit | That unit is skipped with a counted, once-per-shift log; other units compute |
| Engine down across several shift boundaries | Section 9.1's backfill covers it: every shift with no result inside `backfill_days` is computed in boundary order on start. A gap longer than that needs the `--recompute` CLI and is logged rather than silently skipped |
| `backfill_days` exceeds `uns_metrics` retention | Clamped to retention, logged once with both numbers (section 9.1) |
| Backfill spans shifts that predate any data | Skipped, not written as `NO_INPUT_DATA`, and counted in `_backfill_shifts_skipped_total` (section 9.1) |
| Two engine instances running | `UNIQUE (oee_unit_id, shift_start)` plus `claimed_at` on `oee.recompute_request` make the second a no-op rather than a duplicate |
| Recompute requested for a shift with no result | Computed as if at its boundary; `revision` starts at 1 |
| Counter reset mid-shift | Handled per section 8.2 and counted |
| `Performance > 1.0` | Clamped, raw value retained, counted (section 8.1) |
| Reason reassigned to a planned code | Loading Time shrinks, Availability changes, revision bumps — correct, not an error |

## 14. Metrics

Port 9095 (finding 14), prefix `uns_oee_`:

`_shifts_computed_total{unit,status}`, `_shift_compute_seconds`, `_revisions_total{unit}`,
`_late_data_detected_total{unit}`, `_input_rows{unit}`, `_shift_oee{unit}`,
`_availability{unit}`, `_performance{unit}`, `_quality{unit}`,
`_performance_over_unity_total{unit}`, `_counter_resets_total{unit}`,
`_missing_ideal_cycle_time_total{unit}`, `_unclassified_downtime_seconds_total{unit}`,
`_recompute_queue_depth`, `_unpublished_results`, `_publish_total`, `_publish_errors_total`,
`_last_shift_close_timestamp{unit}`, `_db_up`, `_backfill_shifts_total{unit}`,
`_backfill_shifts_skipped_total{unit,reason}`.

`_last_shift_close_timestamp` is the operator's real question — is this engine still closing
shifts — and `_unclassified_downtime_seconds_total` is the master-data quality signal that
tells an engineer their `state_reason_map` has a hole.

## 15. Grafana

One new dashboard, `08_uns_observability/grafana/dashboards/oee.json`:

- OEE trend by shift, per unit, with the three factors as separate series
- A waterfall from Loading Time through Availability, Performance and Quality losses
- Downtime Pareto by reason code for the selected range
- A table of shifts with `status <> 'OK'` — the master-data and data-gap worklist

Panels query `oee.shift_result` and `oee.downtime_event` joined to `model.asset` and
`model.downtime_reason` — **not** `public.uns_metrics_enriched`. The published metric rows
exist for consumers of the namespace; the results tables are the authoritative record, and
they are the only place carrying `status`, `revision` and the per-product breakdown. A trend
built on the metric rows would silently omit any shift whose publication failed.

This does not conflict with ADR-0002's "Grafana queries the aggregates, never the raw table"
(`docs/adr/0002-uns-metrics-hypertable.md:12`–`:13`). That rule exists because the raw table
is unindexed JSONB requiring `time_bucket`/`avg` at query time; `oee.shift_result` is a small
indexed relational table holding one pre-aggregated row per unit per shift, which is what the
rule is asking for rather than an exception to it.

## 16. Registration checklist

- Root `pyproject.toml`: `dependencies`, `[tool.uv.sources]`, `[tool.uv.workspace] members`,
  pytest `testpaths` and `pythonpath`
- `12_uns_oee/pyproject.toml`: `[tool.uv.sources]` with `../`-relative editable paths to
  `00_uns_config`, `09_uns_model` and `02_mqtt-cluster`, matching `04_uns_historian`
- `conf/settings.yaml`: `oee:` environment plus `applications.oee`, `oee.metrics_port: 9095`,
  `oee.settle_minutes: 15`, `oee.late_window_hours: 48`, `oee.backfill_days: 30`,
  `oee.mqtt.client_id: "uns_oee_client"`
- `conf/oee/`: `shifts.yaml`, `units.yaml`, `products.yaml`, `reasons.yaml`
- `09_uns_model`: migration `0003_oee_model.py`, ORM tables, and the `conf/oee/` importer
  invoked by `asset_model_setup`
- `07_uns_graphql`: the three queries and the one mutation of section 10
- `99_simulator`: the deletions of section 12, and `KPI` added to `ParameterType`
- `docker-compose.yml`: an `oee_client` service depending on `asset_model_setup`
  (`service_completed_successfully`) and `uns_mqtt_broker`
- `08_uns_observability`: Prometheus scrape target and `oee.json`
- Root `README.md`: module list, container table, and the OEE section
- `docs/adr/0008-oee-computed-from-history-not-streamed.md`

Unlike the OPC UA connector, this service **may** depend on `asset_model_setup`: its master
data lives in Postgres, so without the Asset Model it has nothing to compute. That is a
genuine dependency, not a startup-order convenience.

## 17. Testing

- **Unit, no I/O.** Section 8's arithmetic against hand-computed fixtures, including every
  row of 8.1; counter resets and multiple resets in one shift; stop intervals with the
  state-before-boundary case, a stop spanning the whole shift, and a stop crossing both
  boundaries; partial overlap between an exception window and a planned-reason stop, asserting
  the union is counted once rather than summed; a planned-reason stop reducing Loading Time;
  per-product segmentation with two and three products; DST in both directions plus the
  ambiguous and non-existent local times of section 8.3.
- **Integration** (`@pytest.mark.integrationtest`). A real Timescale: seed `uns_metrics` with
  a synthetic shift and assert the stored row; assert re-running at an unchanged fingerprint
  writes nothing; assert a changed fingerprint bumps the revision and preserves the prior one
  in `oee.shift_result_revision`; assert reassigning a reason to a planned code changes
  Availability; assert `reason_source = 'manual'` survives a recompute (Rule 3); assert two
  concurrent engines produce one row; assert backfill computes only shifts with no existing
  result, skips shifts predating the earliest input row rather than writing `NO_INPUT_DATA`,
  and clamps `backfill_days` to retention.
- **End to end** (`@pytest.mark.integrationtest`, `xdist_group`). Simulator → historian →
  engine → broker, asserting the `KPI/ShiftOee` payload shape and that every field of
  section 11 is present.

## 18. Judgement calls open to revision

1. **`KPI` as a sixth `ParameterType`** (section 11). The alternative — publishing under
   `ProcessValue` — avoids touching an enum the graph database and alert engine both read,
   at the cost of making a computed KPI look like a sensor.
2. **Performance uses Total Count** (Rule 2). Some plants define it on Good Count. Changing
   it is a one-line change in `oee_calc.py`, but it makes this platform's OEE
   incomparable with the standard definition, so it is a rule rather than a setting.
3. **`settle_minutes` = 15 and `late_window_hours` = 48** (section 9). Both are
   configuration; the defaults suit a site whose worst expected spool replay is under two
   days.
4. **Clamping `Performance` at 1.0** (section 8.1). Publishing an OEE above 100% would be
   more honest about the input error and less usable in every downstream average.
5. **Deleting the simulator's derived signals** (section 12) rather than renaming them to
   `SimulatedOee`. Renaming would keep a demo-friendly live number at the cost of two OEE
   vocabularies in one namespace.
