# uns_edge_agent

Standalone DMZ edge management agent. Polls the cloud management API over outbound
HTTPS, maintains a durable local journal, and installs enrollment credentials
without depending on the cloud model or GraphQL runtime.

## Console scripts

- `uns_edge_agent` — main poll loop
- `uns_edge_enroll` — one-shot enrollment
- `uns_edge_healthcheck` — process and dependency health probe

## Tests

```bash
uv run --package uns_edge_agent pytest 15_uns_edge_agent/test -n 0 -v
```
