# UNS frontend console

React console for the Unified Namespace. It talks only to the GraphQL API (`07_uns_graphql`). There is no login; run it on a trusted plant or VPN network.

## Development

1. Start GraphQL on port 8000 (for example `docker compose up graphql_server`, or uvicorn from `07_uns_graphql`).
2. From this folder:

```bash
npm install
npm run dev
```

Vite listens on port 5173 (see `conf/settings.yaml` `applications.frontend.dev_port`) and proxies `/graphql` (HTTP and WebSocket) to the GraphQL host/port from `conf/settings.yaml`.

## Build

```bash
npm run build
```

## Docker Compose

The `uns_frontend` service serves the production build at **http://localhost:8088**. The browser calls GraphQL at **http://localhost:8000/graphql** (published port, not the Docker DNS name).

## Layout

- **Home**: ISA-95 tree rooted in the authored Asset Model (Neo4j fallback when nothing is modelled), payload inspector with read-time enrichment properties, live MQTT feed (`#`).
- **Explore**: search, historian (table + trend), and property filters.
- **Sparkplug B**, **Kafka streams**, **System health**, and **Users** (RBAC demo).

The tree asks GraphQL for `getAssetChildren` and `getTopicContext` before falling back to observed Neo4j nodes. Selecting a published topic merges Asset Model enrichment (line, machine, unit of measure) into the payload inspector.

## Simulator Console (`#/simulator`)

Four sub-tabs over `99_simulator`'s control API: Status & Run Control, Configuration,
Plant & Signals, Diagnostics.

This is the one route that does not talk to `07_uns_graphql`. It calls the simulator
directly through a `/simulator` proxy path — `vite.config.ts` in development,
`nginx.conf` in the container. Both are required; a missing entry answers with
`index.html` and a 200 status, which looks like a JSON parse bug rather than a routing one.
See `docs/adr/0007-simulator-control-api-outside-graphql.md`.

**Permissions.** `simulator_ops` to see the page, `simulator_control` to change anything.
Operators and auditors get the first and not the second, so they see whether the data they
are looking at is simulated without being able to alter it. Enforcement is in the browser
only — the control API has no user identity.

**Where the numbers come from.** `useSimulator()` polls `GET /simulator/status` and
`GET /simulator/plant` every two seconds, and that is the single source for everything
rendered. The `uns/platform/simulator/#` MQTT subscription feeds only the diagnostics event
list: a retained message from a dead process looks identical to a current one, so it is not
allowed to drive a status display.

**When no simulator is running** the page shows an offline banner and keeps the last values
it read. That is a normal state — the simulator is optional and is not deployed in
production.
