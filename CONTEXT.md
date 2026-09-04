# Unified Namespace

An ISA-95 Unified Namespace platform: plant data published to an MQTT broker is
projected into a graph of current state, a time-series history, and an event log,
then read back through a single query surface.

## Language

**Unified Namespace**:
The single MQTT topic tree that every producer publishes into and every consumer
reads from. Depth is not fixed: the first five levels are named
`<enterprise>/<facility>/<area>/<line>/<device>` by convention, and publishers go
deeper — the simulator publishes eight levels, ending in a parameter group and a
sensor name.
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

### Asset model

**Asset**:
A thing the plant model declares exists — a site, an area, a production unit, a
line, a work cell, a machine. Authored by engineers, and exists whether or not it
has ever published anything.
_Avoid_: node, equipment, entity, tag

**Asset Model**:
The whole authored tree of Assets, and the source of truth for plant structure
and naming. Distinct from the graph of UNS Nodes, which is discovered from
traffic and can only ever contain what has already published.
_Avoid_: hierarchy, plant model, topology, asset registry

**Asset Level**:
The name for an Asset's rank in the Asset Model — Enterprise, Site, Area,
Production Unit, Line, Work Cell, Machine. Carried by the Asset itself rather
than implied by its depth, because a branch may skip levels.
_Avoid_: depth, tier, node type

**Metric Key**:
A Metric's identity relative to its Asset: the topic segments below the Asset's
path followed by the dotted path within the payload, joined by `/` — for example
`ProcessValue/Temperature/value`.
_Avoid_: tag name, metric name, path

**Metric Definition**:
The authored description of a Metric — its Unit of Measure, display name,
precision and engineering range — keyed by Metric Key and optionally narrowed to
a single Asset. Describes a Metric; is never a Metric.
_Avoid_: tag config, metric metadata

**Unit of Measure**:
The physical unit a Metric's value is expressed in, such as `°C`, `bar` or
`L/min`. Always written in full: bare "unit" collides with the Production Unit
Asset Level.
_Avoid_: unit, UoM, engineering unit

**Enrichment**:
Attaching Asset Model and Metric Definition facts to observed data when it is
read. Never written onto the observed row, so correcting the model corrects all
history.
_Avoid_: contextualization, decoration, annotation

**Topic Binding**:
The resolved link from one observed topic to its Asset and Metric Key.
Recomputed whenever the Asset Model changes.
_Avoid_: mapping, lookup, topic resolution

**Unmodelled Topic**:
A topic that has published data but matches no Asset. Counting them is how you
tell an incomplete Asset Model from a complete one.
_Avoid_: orphan, unknown topic

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

**Alert Rule**:
A condition somebody wants to be told about, and who to tell: a topic, a field of
its payload, a comparison, a severity and the roles notified. Configuration of the
plant, not part of the Asset Model — the model says what exists, an Alert Rule says
what matters about it. Distinct from the alarm it raises, which is one occurrence of
the rule being true.
_Avoid_: alarm, alert, threshold, notification rule

### Access

**Realm**:
The Keycloak realm `uns` — the authority on who exists and what Console Roles they
hold. Served under `/auth` on the console's own origin, so its issuer and its
session cookie are first-party.
_Avoid_: auth server, IdP, identity provider

**Console Role**:
One of `admin`, `engineer`, `operator`, `auditor`, `viewer`. The GraphQL enum
spells them upper case; the console spells them lower case; they are the same five.
_Avoid_: permission, group, scope

**Identity**:
Who a validated token says the caller is: subject, username, Console Roles.
Constructed only by `identity_from_token`; nothing else gets to say who is calling.
_Avoid_: user, account, principal

**Access Group**:
A name an admin typed, plus the Asset Model roots that name covers, plus the Keycloak
subjects who belong to it. The UI word is group. Distinct from a Console Role and from
a Keycloak group.
_Avoid_: security group, zone, OS group
