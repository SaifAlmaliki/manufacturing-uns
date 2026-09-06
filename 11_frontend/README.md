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
