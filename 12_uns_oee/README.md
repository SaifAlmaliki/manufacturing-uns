# UNS OEE Engine

Computes **Overall Equipment Effectiveness** for closed shifts from data already in the
historian, and publishes each result back into the Unified Namespace.

    OEE = Availability x Performance x Quality

Definitions follow Nakajima / SEMI E79 as spelled out in
[the design](../docs/superpowers/specs/2026-09-01-oee-engine-design.md), and the reasoning
behind computing rather than streaming is [ADR-0008](../docs/adr/0008-oee-computed-from-history-not-streamed.md).

## What it does

For each Asset listed in `conf/oee/units.yaml`, once a shift has closed and settled:

| Term | From |
| --- | --- |
| Loading Time | the shift window, less planned stops and calendar exceptions |
| Run Time | the union of the intervals the Asset spent in a producing state |
| Good / Reject counts | monotonic counters, differenced with rollover and reset detection |
| Ideal Cycle Time | authored per Asset x Product in `conf/oee/products.yaml` and `units.yaml` |

The result is written to `oee.shift_result` and published once to
`<asset path>/KPI/ShiftOee`. Stops are stored individually in `oee.downtime_event` with a
reason code, so the number can always be explained.

## What it does not do

- **No live OEE.** A partial shift has no Availability, because its Loading Time is not
  known until it closes. The console shows closed shifts.
- **No write-back to any control system.** This module reads the historian and publishes
  to MQTT. It never writes to OPC UA, a PLC, or any process interface.
- **No editing of a result.** A shift result is computed. What a human can correct is
  *why* a machine stopped, through `assignDowntimeReason`; that queues a recomputation.

## Configuration

| Where | What |
| --- | --- |
| `conf/settings.yaml`, `oee:` environment | scan interval, settle time, late window, backfill days, metrics port |
| `conf/oee/shifts.yaml` | weekly shift patterns and calendar exceptions, in a named IANA timezone |
| `conf/oee/units.yaml` | which Assets OEE is reported for, and the metric keys its inputs come from |
| `conf/oee/products.yaml` | product codes and their ideal cycle times |
| `conf/oee/reasons.yaml` | the downtime reason vocabulary and the state-to-reason rules |

Override any setting with an environment variable: `UNS_oee__backfill_days=7`. The database
password comes from `conf/.secrets.yaml` or `UNS_historian__password` and must never be put
in `settings.yaml`.

After editing anything under `conf/oee/`, re-run the importer:

```bash
docker compose up asset_model_setup
```

## Running it

```bash
# In the compose stack, as the `oee_client` service
docker compose up -d oee_client

# Locally
uv run uns_oee

# Recompute a range by hand - after correcting master data, for instance
uv run uns_oee_recompute --asset "CovestroAG/Dormagen/Production/Line1" \
                         --from 2026-08-01 --to 2026-09-01
```

`uns_oee_recompute --help` lists the rest, including `--force`, which supersedes existing
revisions instead of queuing them.

## Observability

Prometheus metrics on **9095** (`uns_oee_shifts_computed`, `uns_oee_shifts_failed`,
`uns_oee_publish_failed`, `uns_oee_pass_duration_seconds`, `uns_oee_last_pass_timestamp`).
The Grafana **OEE** dashboard reads `oee.shift_result` and `oee.downtime_event` directly -
not the enriched metric views, which know nothing about shifts.

## Tests

```bash
uv run pytest ./12_uns_oee                        # everything
uv run pytest -m "not integrationtest" ./12_uns_oee   # no database needed
```

The arithmetic — the calendar, the counters, the interval algebra, the formulas — is all
pure and covered without a database. The integration tests need a Postgres with the
migrations applied.
