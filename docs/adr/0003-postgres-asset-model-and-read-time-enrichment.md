---
status: accepted
---

# The Asset Model is authored in Postgres, and Enrichment is a read-time join

Plant structure was only ever inferred from MQTT topic strings, so nothing in the
platform knew a line's real name, a machine's manufacturer, or a Metric's Unit of
Measure — and a machine that had not yet published simply did not exist. Postgres
now holds an authored **Asset Model** (`model.asset`, `model.metric_definition`)
that engineers maintain independently of traffic, and observed data is
**Enriched** by joining to it at read time through views, never by copying model
facts onto hypertable rows.

Neo4j keeps its existing job unchanged: the latest payload per topic, discovered
from what is actually published. The two stores answer different questions —
"what should be there, and what is it called?" versus "what did we last hear?" —
so the same fact is not written twice.

## Considered Options

Mirroring discovered topics into Postgres and letting engineers fill in the
columns afterwards was rejected: it makes Postgres a second copy of the Neo4j
structure with no owner, and it can never describe equipment that has not
published yet, which is precisely the case where an Asset Model earns its keep
(commissioning, and diagnosing a silent sensor).

Moving structure out of Neo4j entirely was rejected as too large a change for the
value: it touches the graph mapper, the GraphQL graph queries, and the frontend
tree at once, and the graph is genuinely better at "show me everything under
here, with payloads".

Denormalising `line`, `machine` and `unit_of_measure` onto every `uns_metrics`
row was rejected on two counts. It puts a lookup in the hottest write path in the
platform, and it makes the model immutable in practice: renaming a line would
leave every historic row asserting the old name, so a correction becomes a
backfill over a compressed hypertable.

A per-row longest-prefix match (`topic LIKE asset.path || '/%'`) in the view was
rejected because Assets are topic *prefixes* while `uns_metrics.topic` is a full
topic, making the join non-equality and therefore unindexable across millions of
rows.

## Consequences

Prefix matching is resolved once per distinct topic into `model.topic_binding`,
not once per row, so the enrichment views join on plain equality. The historian
upserts a binding the first time it sees a topic and caches the topic in memory
afterwards, which is the only addition to the write path and is bounded by the
number of distinct topics rather than the message rate.

Because bindings are derived, they are stale the moment the Asset Model is
edited, and any write to `model.asset` must trigger a rebind. The rebind is a
single statement over a small table, but forgetting it is the obvious way to
break this design.

`public.uns_metrics_enriched` and `public.uns_metrics_1m_enriched` give Grafana
Enrichment with no Python involvement, since Grafana already queries Timescale
directly (see ADR-0001).

A topic that matches no Asset is an **Unmodelled Topic**: it still records
history exactly as before, and appears in the enriched views with null Asset
columns. Enrichment is therefore additive and cannot lose data, but a
half-populated Asset Model shows up as nulls rather than as an error.
