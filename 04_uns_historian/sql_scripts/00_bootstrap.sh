#!/bin/bash
# Idempotent Timescale bootstrap. Safe to re-run against a volume that already
# holds historian hypertables and console catalogs (connectivity servers survive
# `docker compose down` without `-v`).
set -euo pipefail

: "${UNS_historian__hostname:?}"
: "${UNS_historian__database:?}"
: "${UNS_historian__username:?}"
: "${UNS_historian__password:?}"
: "${UNS_historian__table:?}"
: "${PGPASSWORD:?}"

export PGPASSWORD

psql_super() {
  psql -h "$UNS_historian__hostname" -U postgres -p 5432 -v ON_ERROR_STOP=1 "$@"
}

psql_app() {
  PGPASSWORD="$UNS_historian__password" psql \
    -h "$UNS_historian__hostname" \
    -U "$UNS_historian__username" \
    -d "$UNS_historian__database" \
    -p 5432 \
    -v ON_ERROR_STOP=1 \
    "$@"
}

# CREATE DATABASE cannot run inside a transaction; \gexec issues it alone.
psql_super <<SQL
SELECT format('CREATE DATABASE %I', '${UNS_historian__database}')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${UNS_historian__database}')\gexec
SQL

psql_super -d "$UNS_historian__database" -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

psql_super <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${UNS_historian__username}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${UNS_historian__username}', '${UNS_historian__password}');
  ELSE
    EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', '${UNS_historian__username}', '${UNS_historian__password}');
  END IF;
END
\$\$;
SELECT format('ALTER DATABASE %I OWNER TO %I', '${UNS_historian__database}', '${UNS_historian__username}')\gexec
SQL

psql_app <<SQL
CREATE TABLE IF NOT EXISTS ${UNS_historian__table} (
  time TIMESTAMPTZ NOT NULL,
  topic TEXT NOT NULL,
  client_id TEXT,
  mqtt_msg JSONB,
  CONSTRAINT unique_event UNIQUE (time, topic, client_id, mqtt_msg)
);
SELECT create_hypertable('${UNS_historian__table}', 'time', if_not_exists => TRUE);
SQL

psql_app -f /sql/04_setup_metrics_hypertable.sql

echo "Successfully created & configured timescaledb for the UNS"
