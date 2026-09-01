# Grafana + Prometheus for Process Visualization and Platform Observability

See [docs/adr/0001-grafana-for-visualization-and-observability.md](../docs/adr/0001-grafana-for-visualization-and-observability.md).

## Quick start

From the repository root, with the main stack running:

```bash
docker compose up -d uns_prometheus uns_grafana
```

| Service | URL | Purpose |
| --- | --- | --- |
| Grafana | http://localhost:3000 | Dashboards (anonymous admin — dev only) |
| Prometheus | http://localhost:9090 | Scrape targets for mapper `/metrics` endpoints |

`uns_grafana` waits for `asset_model_setup` to complete so the TimescaleDB enrichment views exist before dashboards query them.

## Dashboards

### Process Visualization (`process-visualization.json`)

Plant measurements — temperature, flow rate, and so on.

- **Data source:** TimescaleDB (`timescaledb`)
- **Query target:** `public.uns_metrics_1m_enriched` (not the raw hypertable)
- **Why enriched:** Panels show line, machine, and unit of measure from the authored Asset Model joined at read time ([ADR-0003](../docs/adr/0003-postgres-asset-model-and-read-time-enrichment.md))

Template variables filter by topic and metric name substrings.

### Platform Observability (`platform-observability.json`)

Platform health — historian throughput, persist failures, mapper latency.

- **Data source:** Prometheus
- **Targets:** `historian_client:9091`, `graphdb_client:9092`, etc.

Process data and platform telemetry deliberately use different data sources so a green health panel cannot be mistaken for a healthy plant.

## Provisioning

- `grafana/provisioning/datasources/` — TimescaleDB and Prometheus connections (from template + env)
- `grafana/provisioning/dashboards/` — loads JSON dashboards from `grafana/dashboards/`

Configuration only — no Python package, not part of the `uv` workspace.
