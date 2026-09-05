"""Console configuration: OPC-UA connectivity servers and subscribed tags.

Revision ID: 0005_console_connectivity
Revises: 0004_access_groups
Create Date: 2026-09-05

The console's Connectivity catalog: which OPC-UA servers to dial, and which
nodes on them to subscribe to and republish over MQTT. Like Alert Rules, this
is relational configuration authored in the console and persisted in Postgres
so that it survives a cleared browser cache and a redeployed container
(ADR-0004). The schema is `console`, the same one Alert Rules already use.

The DDL is idempotent (`CREATE TABLE IF NOT EXISTS`) and reuses the same
constraint names a future direct psql script would produce, so stamping a
database that already has these tables is safe.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_console_connectivity"
down_revision: str | None = "0004_access_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "console"

CONNECTIVITY_SERVERS_TABLE = """
CREATE TABLE IF NOT EXISTS console.connectivity_servers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  protocol TEXT NOT NULL
    CONSTRAINT connectivity_servers_protocol_check
    CHECK (protocol = 'opc_ua'),
  endpoint TEXT NOT NULL,
  last_status TEXT NOT NULL DEFAULT 'untested'
    CONSTRAINT connectivity_servers_last_status_check
    CHECK (last_status IN ('untested', 'connected', 'failed')),
  last_error TEXT NOT NULL DEFAULT '',
  last_tested_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CONNECTIVITY_TAGS_TABLE = """
CREATE TABLE IF NOT EXISTS console.connectivity_tags (
  server_id TEXT NOT NULL
    REFERENCES console.connectivity_servers (id) ON DELETE CASCADE,
  node_id TEXT NOT NULL,
  browse_path TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  mqtt_topic TEXT NOT NULL DEFAULT '',
  subscribed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (server_id, node_id)
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_connectivity_servers_protocol ON console.connectivity_servers (protocol)",
    "CREATE INDEX IF NOT EXISTS idx_connectivity_tags_server ON console.connectivity_tags (server_id)",
    "CREATE INDEX IF NOT EXISTS idx_connectivity_tags_subscribed ON console.connectivity_tags (server_id, subscribed) "
    "WHERE subscribed",
)

# Kept even though the ORM sets updated_at itself: a row edited with psql, or by
# a future service that does not go through ConnectivityRepository, must still
# be visible to a console that refetches on change.
UPDATED_AT_FUNCTION = """
CREATE OR REPLACE FUNCTION console.set_connectivity_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$
"""

DROP_SERVERS_TRIGGER = "DROP TRIGGER IF EXISTS trg_connectivity_servers_updated_at ON console.connectivity_servers"
CREATE_SERVERS_TRIGGER = """
CREATE TRIGGER trg_connectivity_servers_updated_at
  BEFORE UPDATE ON console.connectivity_servers
  FOR EACH ROW
  EXECUTE FUNCTION console.set_connectivity_updated_at()
"""

DROP_TAGS_TRIGGER = "DROP TRIGGER IF EXISTS trg_connectivity_tags_updated_at ON console.connectivity_tags"
CREATE_TAGS_TRIGGER = """
CREATE TRIGGER trg_connectivity_tags_updated_at
  BEFORE UPDATE ON console.connectivity_tags
  FOR EACH ROW
  EXECUTE FUNCTION console.set_connectivity_updated_at()
"""

COMMENTS = (
    "COMMENT ON TABLE console.connectivity_servers IS "
    "'OPC-UA servers the console dials. Catalog shared with the OPC-UA bridge (10_uns_opcua).'",
    "COMMENT ON COLUMN console.connectivity_servers.endpoint IS "
    "'OPC-UA endpoint URL, e.g. opc.tcp://host:4840.'",
    "COMMENT ON COLUMN console.connectivity_servers.last_status IS "
    "'untested | connected | failed. Updated by record_test.'",
    "COMMENT ON TABLE console.connectivity_tags IS "
    "'OPC-UA nodes the console subscribes to. Republished to mqtt_topic when subscribed is true.'",
    "COMMENT ON COLUMN console.connectivity_tags.mqtt_topic IS "
    "'Engineer-edited MQTT topic. Discovery must not overwrite an existing value.'",
    "COMMENT ON COLUMN console.connectivity_tags.subscribed IS "
    "'True when the OPC-UA bridge should subscribe. Discovery does not unset this.'",
)

GRANTS = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
        GRANT USAGE ON SCHEMA {SCHEMA} TO uns_dbuser;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO uns_dbuser;
        ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uns_dbuser;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(CONNECTIVITY_SERVERS_TABLE)
    op.execute(CONNECTIVITY_TAGS_TABLE)
    for index in INDEXES:
        op.execute(index)
    op.execute(UPDATED_AT_FUNCTION)
    op.execute(DROP_SERVERS_TRIGGER)
    op.execute(CREATE_SERVERS_TRIGGER)
    op.execute(DROP_TAGS_TRIGGER)
    op.execute(CREATE_TAGS_TRIGGER)
    for comment in COMMENTS:
        op.execute(comment)
    op.execute(GRANTS)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_connectivity_tags_updated_at ON console.connectivity_tags")
    op.execute("DROP TRIGGER IF EXISTS trg_connectivity_servers_updated_at ON console.connectivity_servers")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.connectivity_tags")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.connectivity_servers")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.set_connectivity_updated_at()")
