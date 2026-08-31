---
status: accepted
---

# Metrics are flattened into a narrow hypertable, dual-written by the historian

Historic Events are stored as whole JSONB payloads in `unifiednamespace`, which
no time-series query can use efficiently: the measurement is buried in JSONB,
`topic` is unindexed, and Grafana panels need `time_bucket(...) / avg(...)`. The
historian therefore also writes each payload's scalar leaves into a narrow
`uns_metrics(time, topic, metric_name, value_double, value_text)` hypertable, in
the same transaction, with continuous aggregates at 1m and 1h. Grafana queries
the aggregates, never the raw table.

## Considered Options

Querying the raw JSONB from Grafana needs no migration and works against the
simulator, but every panel becomes a full-range scan over uncompressed JSONB —
it would demo fine and fail in production, which is the same trap as the
fabricated health panel.

Reading history through the existing GraphQL API via the Infinity plugin was
rejected because Infinity cannot push down bucketing or aggregation, and
`getHistoricEventsInTimeRange` has no `LIMIT`, so a one-week panel refresh pulls
every row through the GraphQL process.

A Postgres trigger on `unifiednamespace` would keep the flattening server-side,
but puts per-row JSONB parsing in the write path of the hottest table and leaves
nowhere to count failures. A separate mapper doubles broker load and adds a
second projection that can silently drift.

Every scalar at any depth becomes a Metric, keyed by its dotted path, rather than
a configured allowlist. An allowlist is a config file someone forgets to update,
and the failure mode is a tag silently missing from history.

## Consequences

Payload data is now stored twice, deliberately. `unifiednamespace` remains the
immutable record of what was published; `uns_metrics` is a projection and may be
rebuilt from it.

Because both writes must land or neither, the historian's current
fire-and-forget insert has to become an awaited transaction. That closes the
existing silent-data-loss path as a side effect: today
`uns_mqtt_historian.on_message` schedules the coroutine and never inspects the
Future, so every insert failure is invisible.

Retention drops raw data earliest and coarse aggregates last: raw events 90 days,
`uns_metrics` 1 year, 1m aggregates 1 year, 1h aggregates 5 years, compression
after 7 days. These are engineering defaults, **not** a compliance judgement — if
regulated raw-retention applies to process data, these numbers must be revisited.
