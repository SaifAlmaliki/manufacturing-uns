# Asset Model & Enrichment (`uns_model`)

The authored side of Postgres: the **Asset Model** that describes what the plant
*is*, the **Enrichment** that attaches those facts to observed data when it is
read, and the **Alert Rules** the console authors.

Two schemas, one engine. `model` holds the Asset Model, `console` holds the Alert
Rules; they share a database and nothing else, which is why
`AlertRuleRepository` is a separate seam from `AssetModelRepository`.

See [`CONTEXT.md`](../CONTEXT.md) for the vocabulary, and
[ADR-0003](../docs/adr/0003-postgres-asset-model-and-read-time-enrichment.md),
[ADR-0004](../docs/adr/0004-sqlalchemy-orm-for-the-model-core-for-ingest.md) and
[ADR-0005](../docs/adr/0005-graphql-mutations-for-console-configuration.md) for
why it is shaped this way.

## What this is not

It is **not** the Neo4j graph. The graph holds UNS Nodes — the latest payload per
topic, discovered from traffic. This package holds Assets — what an engineer says
exists, whether or not it has ever published. A machine being commissioned exists
here and not there; a topic somebody published by mistake exists there and not
here (an **Unmodelled Topic**).

It is also not the historian. Nothing in this package writes time-series data.

## The shape

```
Asset Model (authored)              Observed data (projected from MQTT)
model.asset ─────────┐              public.unifiednamespace
model.metric_definition             public.uns_metrics
        │            │                      │
        └── model.topic_binding ────────────┘
                     │
        public.uns_metrics_enriched, public.uns_metrics_1m_enriched
```

An Asset's path is a topic *prefix*. The simulator publishes

```
ManufacturingCo/PlantA/Production/Line1/Cell1/MixerTank/ProcessValue/Temperature
└────────────────── Asset: the MACHINE ──────────────┘ └─ Metric Key ──┘
```

so `PRODUCTION_UNIT` is simply skipped in that branch — which is why an Asset
carries its own **Asset Level** instead of having one inferred from its depth.

Matching a full topic to its Asset is a longest-prefix search, which is not an
indexable join. It is therefore resolved **once per distinct topic** into
`model.topic_binding`, and the enrichment views join on plain equality.

## Using it

```python
from uns_model import TopicContextResolver

resolver = TopicContextResolver()
context = await resolver.resolve("ManufacturingCo/PlantA/Production/Line1/Cell1/MixerTank/ProcessValue/Temperature")

context.levels["LINE"]            # 'Line1'
context.levels["MACHINE"]         # 'MixerTank'
context.level_names["LINE"]       # 'Polyol Line 1' — the authored display name
context.asset_name                # 'Mixer Tank 1'
context.metric_path               # 'ProcessValue/Temperature'
context.unit_of_measure("value")  # '°C'
context.enrich("value")           # flat dict: site, line, machine, unit_of_measure, …
```

`resolve` is cached in memory with a TTL and returns `None` for an Unmodelled Topic.
Long-running services (GraphQL, historian) also **listen for `NOTIFY asset_model_changed`**
and drop their caches when the model is edited elsewhere — for example after
`docker compose up asset_model_setup`. Call `refresh()` for an in-process edit.

Every write to the Asset tree triggers `rebind_all()` automatically (`ensure_branch`,
`delete_asset`). Batch seeding passes `rebind=False` per branch and calls `rebind_all()` once
at the end of `apply_plan()`.

Alert Rules go through their own repository. Every write is an upsert by id, so the
console saves a rule it has just edited without knowing whether the server has seen
it before, and the notified roles are replaced wholesale rather than merged:

```python
from uns_model import AlertRuleRepository, AlertRuleSpec

rules = AlertRuleRepository(Database.shared("graphql"))
await rules.save_rule(AlertRuleSpec(
    id="oven-overtemp", name="Oven over temperature",
    severity="CRITICAL", category="TEMPERATURE",
    topic="ManufacturingCo/PlantA/Production/Line1/Cell1/Oven/ProcessValue/Temperature",
    metric_field="value", condition="GREATER_THAN", threshold_value=180.0,
    roles=["operator", "engineer"],
))
```

`AlertRuleSpec.validate()` rejects a value outside the allowed vocabulary before
Postgres does, so a caller gets `severity must be one of [...]` instead of a
constraint violation with a generated name in it. The CHECK constraints are still
the real guard.

On the ingest side, the historian calls a `TopicBinder` instead, which resolves
each *distinct* topic once and never raises — Enrichment is not worth a lost
measurement:

```python
from uns_model import AssetModelRepository, Database, TopicBinder

binder = TopicBinder(AssetModelRepository(Database.shared("historian")))
await binder.observe(topic)   # a no-op for a topic already bound
```

## Who uses it

| Caller | What it does |
| --- | --- |
| `04_uns_historian` | SQLAlchemy Core persist to hypertables; `TopicBinder.observe()` after each successful write; `LISTEN` to invalidate binder cache |
| `07_uns_graphql` | Asset Model queries, Alert Rule queries/mutations; `TopicContextResolver` with `LISTEN` cache invalidation; historic reads via Core |
| Grafana / SQL | `public.uns_metrics_enriched` and `public.uns_metrics_1m_enriched` (see [08_uns_observability](../08_uns_observability/README.md)) |

## Commands

Alembic owns the `model` and `console` schemas and the enrichment views. The legacy
`04_uns_historian/sql_scripts/*.sql` still bootstrap the hypertables; see ADR-0004
for why Timescale DDL stays as raw SQL inside migrations. The enrichment views are
created only if their hypertable already exists, so `upgrade` works on a fresh
database — re-run it after applying `sql_scripts` to pick them up.

```sh
uv run uns_model_setup                          # migrate, then seed: what the container does
uv run uns_model_setup --skip-seed              # schema only
uv run uns_model_migrate                        # or: uv run alembic upgrade head
uv run uns_model_migrate --sql                  # print the DDL instead of running it
uv run uns_model_seed --from-simulator-config   # import conf/settings.yaml hierarchy
uv run uns_model_seed --dry-run                 # print what a seed would write
```

Seeding is idempotent: every Asset is upserted by path, every Metric Definition by
(Asset, Metric Key), and `apply_plan()` finishes with a single `rebind_all()` plus
`NOTIFY asset_model_changed` so bindings and downstream caches catch up.

## Deployment

`docker-compose.yml` runs this as `asset_model_setup`: a short-lived container that
migrates and seeds, then exits. `historian_client`, `graphql_server` and
`uns_grafana` wait on it with `service_completed_successfully`, so they never start
against a database without the `model` schema. It runs after `tsdb_setup_script`
because the enrichment views need their hypertables to already exist.

Restarting that one service (`docker compose up asset_model_setup`) is how the
Asset Model is updated after `conf/settings.yaml` changes.

## Tests

`test/test_topic_path.py`, `test/test_asset_context.py`, `test/test_seed.py`,
`test/test_topic_binder.py` and `test/test_alert_rules.py` are pure unit tests and
need no database — the repository seam is where the fakes go. Tests marked
`integrationtest` need Postgres from `docker-compose.yml`; the
[`uns_model-app` workflow](../.github/workflows/uns_model-app.yml) runs them in CI
against a Timescale service container with hypertables and migrations applied.
