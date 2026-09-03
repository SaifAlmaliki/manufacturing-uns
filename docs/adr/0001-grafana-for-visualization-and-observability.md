---
status: accepted
---

# Grafana serves both Process Visualization and Platform Observability

Earlier design work explicitly excluded Grafana from the architecture
(`docs/prompts/uns-full-console-ui-external-prompt.md:521,710` and
`docs/superpowers/specs/2026-08-28-uns-frontend-design.md:25`). We are reversing
that: Grafana and Prometheus join the stack as `08_uns_observability`, serving
both Process Visualization and Platform Observability. The trigger was that the
React console's System Health panel derives all five component indicators from a
single boolean and no module emits any metrics at all, so there was nothing
truthful to build a health view from.

## Considered Options

An earlier attempt at this stalled and left `99_simulator/notes:1-33` behind. Two
of the three plugin IDs it lists do not exist, which fails the container at
startup and explains the abandonment:

- `grafana-mqtt-datasource` — real, signed by Grafana Labs, stable. Adopted.
- `grafana-kafka-datasource` — no such plugin. The real slug is
  `hamedkarbasi93-kafka-datasource`, community and **unsigned**. Rejected: using
  it means disabling plugin signature verification for a live view the console
  already serves properly over `graphql-transport-ws`.
- `grafana-datasource-plugin-neo4j` — no Neo4j data source exists in the Grafana
  catalog at all. The Unified Namespace tree therefore stays in the React
  console; Grafana never becomes the place you browse the namespace.

For edge→enterprise metrics we chose Prometheus `remote_write` over federation.
Federation requires the enterprise network to initiate connections into each
facility, which is backwards from how plant networks are firewalled. `remote_write`
also keeps local retention at each facility, so a WAN outage stays debuggable.

## Consequences

Neo4j Community Edition has **no metrics export** — Prometheus, JMX, CSV and
Graphite are all Enterprise-only. There is no exporter route to graph
observability, so every Neo4j signal must come from `03_uns_graphdb`
instrumenting itself. This is why application-level `prometheus_client`
instrumentation is mandatory here rather than a nice-to-have: exporters alone
cannot see it, and they equally cannot see the historian's swallowed insert
failures.

Grafana runs with anonymous access enabled, matching the rest of the stack. This
is a **known security gap**, deliberately accepted: it makes Grafana the sixth
unauthenticated surface, and the dashboards expose plant process data. It does
make iframe embedding in the console trivial, which is how the System Health
panel stops lying. OIDC is the documented target; nothing here depends on
anonymous access remaining on.

> **Superseded in part (2026-09):** the anonymous-access gap described below is closed.
> Grafana now signs in against the platform's Keycloak realm with `generic_oauth`, and realm
> roles map to Grafana org roles. See ADR-0009. The rest of this record — why Grafana is
> proxied under `/grafana` and why port 3000 is unpublished — still stands.
