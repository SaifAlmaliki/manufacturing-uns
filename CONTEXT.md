# Unified Namespace

An ISA-95 Unified Namespace platform: plant data published to an MQTT broker is
projected into a graph of current state, a time-series history, and an event log,
then read back through a single query surface.

## Language

**Unified Namespace**:
The single MQTT topic tree that every producer publishes into and every consumer
reads from, structured as `<enterprise>/<facility>/<area>/<line>/<device>`.
_Avoid_: UNS tree, namespace, topic hierarchy

**UNS Node**:
One level of the Unified Namespace, holding the latest payload published at that
topic. Persisted in the graph, not the history.
_Avoid_: node, tag, asset

**Historic Event**:
A single immutable message as it was published, stamped with the time it
occurred. Persisted in the history, never updated.
_Avoid_: record, sample, datapoint, reading

**Mapper**:
A service that subscribes to the Unified Namespace and projects what it receives
into one downstream store. Never the source of truth for what it writes.
_Avoid_: connector, bridge, sink, ingester

**Metric**:
One scalar value extracted from a Historic Event's payload, identified by the
dotted path to it within that payload. A single event yields as many Metrics as
it has scalar leaves. Distinct from the payload itself, which stays intact.
_Avoid_: tag, signal, measurement, field, series

### Presentation

**Process Visualization**:
Presentation of the plant's own measurements — the values engineers publish, such
as temperature or flow rate. Answers "what is the plant doing?".
_Avoid_: monitoring, trending, analytics

**Platform Observability**:
Presentation of the platform's own behaviour — throughput, lag, failures, store
growth. Answers "is the platform healthy?". Distinct from Process Visualization:
they share dashboards but never share a data source, and confusing them is how a
green health indicator ends up meaning nothing.
_Avoid_: monitoring, health, telemetry

**Instance**:
One deployment of the platform, either at a single facility or centrally for the
whole enterprise. Determines which stores a dashboard can reach.
_Avoid_: environment, site, tenant, cluster
