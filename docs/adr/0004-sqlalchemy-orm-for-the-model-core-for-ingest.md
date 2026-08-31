---
status: accepted
---

# SQLAlchemy ORM for the Asset Model, SQLAlchemy Core for ingest

Postgres access was two hand-rolled asyncpg pool classes — one in
`uns_historian.historian_handler`, a near-copy in
`uns_graphql.backend.historian` — issuing f-string SQL against table names read
from config. That is tolerable for two tables and untenable for the Asset Model,
which is relational, mutable, and needs migrations. A shared `uns_model` package
now owns one async engine and declarative models, with the **ORM** used for the
Asset Model and console configuration and **SQLAlchemy Core** used for the
per-message insert path.

## Considered Options

Putting the whole platform on the ORM, including per-message hypertable inserts,
was rejected. The ingest path writes one raw row plus N Metric rows per MQTT
message; routing that through a `Session` adds identity-map and flush bookkeeping
to the highest-frequency code in the platform for no benefit, since those rows are
never mutated, never re-read in the same transaction, and have no relationships to
traverse. Core gives the same `insert().on_conflict_do_nothing()` and
`executemany` behaviour with a plain connection.

Leaving asyncpg in place and using SQLAlchemy only for new tables was rejected
because it makes two permanent Postgres access styles, two pools per process, and
two places to configure SSL — and the duplicated pool classes were part of what
prompted this work.

Alembic is adopted over the existing numbered `sql_scripts/*.sql`. The scripts are
idempotent `CREATE ... IF NOT EXISTS` with no notion of having been applied, so
there is no way to alter a column, and `console.alert_rules` already demonstrates
the failure mode: it was created by script 03 and nothing has ever read it.
Timescale-specific DDL (`create_hypertable`, continuous aggregates, retention and
compression policies) stays as raw SQL inside migrations, because SQLAlchemy has
no opinion about it and pretending otherwise would hide it.

## Consequences

`uns_model` becomes a dependency of both the historian and the GraphQL server, so
a change to the shared engine can break two services. The seam is the repository
interface, not the ORM models: callers get `TopicContextResolver` and the
repositories, and are not expected to hold a `Session`.

The ORM models are the schema's single definition, but Timescale objects are not
represented in the metadata, so `create_all()` produces an incomplete database and
must not be used outside unit tests. Migrations are the only supported path.

Two dialects now reach the same database — asyncpg directly (during the
transition) and asyncpg via SQLAlchemy — which means connection-pool sizing has to
be considered per process rather than per library.
