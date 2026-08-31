# Asset Model & Enrichment (`uns_model`)

The authored side of Postgres: the **Asset Model** that describes what the plant
*is*, and the **Enrichment** that attaches those facts to observed data when it
is read.

See [`CONTEXT.md`](../CONTEXT.md) for the vocabulary, and
[ADR-0003](../docs/adr/0003-postgres-asset-model-and-read-time-enrichment.md) and
[ADR-0004](../docs/adr/0004-sqlalchemy-orm-for-the-model-core-for-ingest.md) for
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

`resolve` is cached in memory with a TTL and returns `None` for an Unmodelled
Topic. Call `refresh()` after editing the Asset Model in the same process.

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
| `04_uns_historian` | `TopicBinder.observe()` after each successful persist, so every topic gets a Topic Binding |
| `07_uns_graphql` | `getAssets`, `getAssetChildren`, `getAsset`, `getTopicContext`, `getUnmodelledTopics`, `getAssetModelSummary` |
| Grafana / SQL | `public.uns_metrics_enriched` and `public.uns_metrics_1m_enriched` |

## Commands

Alembic owns the `model` schema and the enrichment views. The legacy
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

Seeding is idempotent, and always re-resolves the Topic Bindings afterwards:
they are derived from the tree, so editing the tree leaves them stale.

## Deployment

`docker-compose.yml` runs this as `asset_model_setup`: a short-lived container that
migrates and seeds, then exits. `historian_client`, `graphql_server` and
`uns_grafana` wait on it with `service_completed_successfully`, so they never start
against a database without the `model` schema. It runs after `tsdb_setup_script`
because the enrichment views need their hypertables to already exist.

Restarting that one service (`docker compose up asset_model_setup`) is how the
Asset Model is updated after `conf/settings.yaml` changes.

## Tests

`test/test_topic_path.py`, `test/test_asset_context.py`, `test/test_seed.py` and
`test/test_topic_binder.py` are pure unit tests and need no database — the
repository seam is where the fakes go. Tests marked `integrationtest` need Postgres
from `docker-compose.yml`.
