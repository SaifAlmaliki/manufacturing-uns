---
status: accepted
---

# The simulator's control API sits outside GraphQL

Date: 2026-09-01

## Status

Accepted

## Context

The simulator console needs to read live simulator state and write to it: start and stop
the run, switch profiles, change publish intervals, disable a device.

Every other mutation in `11_frontend` goes through `07_uns_graphql`. Doing the same here
would mean the GraphQL server importing `99_simulator`, or reaching it over a network call
it would then wrap. Both make the platform's read API depend on a component that is not
part of the platform: the simulator is a development tool, it is not deployed in
production, and `99_simulator/Dockerfile:41` says so.

There is also a state problem. The values the console needs — run state, per-tier publish
rates, the PackML state of each line — exist only inside the running simulator process, in
memory, changing every tick. A GraphQL resolver would have to ask the simulator for them
anyway. The question is not whether to add a hop, but whether to add two.

## Decision

The simulator serves its own FastAPI control API on port 8099 under `/simulator`, in the
simulation's own event loop. `11_frontend` calls it directly through a proxy path that Vite
serves in development and nginx serves in the container.

The GraphQL schema does not mention the simulator.

Three consequences follow from running the API in the simulation's loop rather than in a
thread or a sidecar process:

- A request handler reads live in-process state. There is one copy of it and one loop
  touching it, so `GET /simulator/status` cannot be stale.
- All writes serialise behind a single `asyncio.Lock`, which is what makes "switch the
  profile" and "change the tier intervals" safe to issue concurrently.
- uvicorn must not install its own signal handlers, or it takes Ctrl-C away from the
  simulation's shutdown path. `main._EmbeddedServer` overrides `capture_signals` to a no-op.

Runtime changes are never written back to `conf/simulator/*.yaml`. `overrides_active` in
the status body says when the running plant has diverged from the files, and a restart
returns to them.

Observability follows the same separation. Prometheus metrics are on 9093, beside the
historian's 9091 and the graph database's 9092. MQTT self-telemetry publishes under
`uns/platform/simulator/<instance>/`, which no mapper subscribes to — enforced by
`99_simulator/test/test_self_telemetry.py`, which reads the real topic lists from
`conf/settings.yaml` and matches them against the telemetry topics with an MQTT wildcard
matcher.

## Consequences

**Good.** `07_uns_graphql` stays free of a development-only dependency. The console's
numbers come from the process that owns them. The simulator can be removed from a
deployment and the console degrades to an "offline" banner instead of a broken schema.

**Bad.** `11_frontend` now talks to two backends, so both `vite.config.ts` and `nginx.conf`
need a proxy entry, and a missing one produces `index.html` with a 200 status rather than a
clear failure. Authentication is a shared bearer token
(`simulator.api.token`, optional and unset by default) rather than the console's RBAC —
the API has no user identity, so `simulator_control` is enforced in the browser only.
Anyone who can reach port 8099 can command the simulator, which is why neither 8099 nor 9093
is published to the host in `docker-compose.yml` — the mapping is present but commented out,
to be uncommented deliberately on a development machine.

**Neutral.** A future production-grade control plane would move this behind GraphQL with
real authorization. Nothing here prevents that: the console talks to one client module
(`src/services/simulator/client.ts`), so the transport is replaceable in one file.
