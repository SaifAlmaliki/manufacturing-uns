"""Console configuration: Alert Rules move from a psql script into Alembic

Revision ID: 0002_console_alert_rules
Revises: 0001_asset_model
Create Date: 2026-08-31

`console.alert_rules` was created by 04_uns_historian/sql_scripts/03_setup_alert_rules.sql,
run by hand or by a one-off psql container. It is plain relational configuration, not
Timescale DDL, so ADR-0004 puts it here: one tool owns every non-hypertable object,
and a deployment gets it by running the Asset Model container.

The DDL is idempotent because databases that already ran the script exist, and
Alembic has no way of knowing that. `CREATE TABLE IF NOT EXISTS` with the same
constraint names the script produced makes stamping such a database safe.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_console_alert_rules"
down_revision: str | None = "0001_asset_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "console"

ALERT_RULES_TABLE = """
CREATE TABLE IF NOT EXISTS console.alert_rules (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  severity TEXT NOT NULL
    CONSTRAINT alert_rules_severity_check
    CHECK (severity IN ('CRITICAL', 'HIGH', 'WARNING', 'INFO')),
  category TEXT NOT NULL
    CONSTRAINT alert_rules_category_check
    CHECK (category IN (
      'TEMPERATURE', 'PRESSURE', 'VIBRATION', 'FLOW_RATE', 'STALE_TIMEOUT',
      'NODE_OFFLINE', 'COMMUNICATION', 'THRESHOLD', 'SAFETY', 'CUSTOM'
    )),
  topic TEXT NOT NULL,
  metric_field TEXT NOT NULL,
  condition TEXT NOT NULL
    CONSTRAINT alert_rules_condition_check
    CHECK (condition IN (
      'GREATER_THAN', 'LESS_THAN', 'EQUALS', 'NOT_EQUALS',
      'RANGE_OUTSIDE', 'STALE_TIMEOUT', 'CONTAINS'
    )),
  threshold_value JSONB NOT NULL,
  threshold_upper_value DOUBLE PRECISION,
  unit TEXT,
  delay_seconds INTEGER NOT NULL DEFAULT 0
    CONSTRAINT alert_rules_delay_seconds_check CHECK (delay_seconds >= 0),
  escalation_role TEXT
    CONSTRAINT alert_rules_escalation_role_check
    CHECK (escalation_role IS NULL OR escalation_role IN (
      'admin', 'engineer', 'operator', 'auditor', 'viewer'
    )),
  escalation_timeout_minutes INTEGER
    CONSTRAINT alert_rules_escalation_timeout_minutes_check
    CHECK (escalation_timeout_minutes IS NULL OR escalation_timeout_minutes >= 1),
  auto_resolve_on_normal BOOLEAN NOT NULL DEFAULT TRUE,
  in_app_notification BOOLEAN NOT NULL DEFAULT TRUE,
  audio_chime BOOLEAN NOT NULL DEFAULT TRUE,
  mqtt_publish_on_trigger BOOLEAN NOT NULL DEFAULT FALSE,
  mqtt_alarm_topic TEXT,
  email_webhook BOOLEAN NOT NULL DEFAULT FALSE,
  webhook_url TEXT,
  trigger_count INTEGER NOT NULL DEFAULT 0
    CONSTRAINT alert_rules_trigger_count_check CHECK (trigger_count >= 0),
  last_triggered_at TIMESTAMPTZ,
  last_evaluated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

ALERT_RULE_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS console.alert_rule_roles (
  rule_id TEXT NOT NULL
    REFERENCES console.alert_rules (id) ON DELETE CASCADE,
  role TEXT NOT NULL
    CONSTRAINT alert_rule_roles_role_check
    CHECK (role IN ('admin', 'engineer', 'operator', 'auditor', 'viewer')),
  PRIMARY KEY (rule_id, role)
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON console.alert_rules (enabled)",
    "CREATE INDEX IF NOT EXISTS idx_alert_rules_topic ON console.alert_rules (topic)",
    "CREATE INDEX IF NOT EXISTS idx_alert_rules_severity ON console.alert_rules (severity)",
    "CREATE INDEX IF NOT EXISTS idx_alert_rule_roles_role ON console.alert_rule_roles (role)",
)

# Kept even though the ORM sets updated_at itself: a rule edited with psql, or by
# a future service that does not go through AlertRuleRepository, must still be
# visible to a console that refetches on change.
UPDATED_AT_TRIGGER = """
CREATE OR REPLACE FUNCTION console.set_alert_rules_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_alert_rules_updated_at ON console.alert_rules;
CREATE TRIGGER trg_alert_rules_updated_at
  BEFORE UPDATE ON console.alert_rules
  FOR EACH ROW
  EXECUTE FUNCTION console.set_alert_rules_updated_at();
"""

COMMENTS = (
    "COMMENT ON SCHEMA console IS "
    "'Transactional UNS console configuration (Alert Rules, future RBAC). Not time-series.'",
    "COMMENT ON TABLE console.alert_rules IS "
    "'ISA-18.2 Alert Rule definitions authored in the console and persisted here rather than in a browser.'",
    "COMMENT ON TABLE console.alert_rule_roles IS 'Roles notified when an Alert Rule fires.'",
    "COMMENT ON COLUMN console.alert_rules.threshold_value IS "
    "'JSON scalar matching the console field: number, string or boolean.'",
    "COMMENT ON COLUMN console.alert_rules.unit IS "
    "'Unit as typed by the engineer. Not a Metric Definition unit_of_measure.'",
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
    op.execute(ALERT_RULES_TABLE)
    op.execute(ALERT_RULE_ROLES_TABLE)
    for index in INDEXES:
        op.execute(index)
    op.execute(UPDATED_AT_TRIGGER)
    for comment in COMMENTS:
        op.execute(comment)
    op.execute(GRANTS)


def downgrade() -> None:
    # The schema goes too, unlike `model`: nothing else lives in it, and Alembic's
    # own version table is in `model`.
    op.execute("DROP TRIGGER IF EXISTS trg_alert_rules_updated_at ON console.alert_rules")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.alert_rule_roles")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.alert_rules")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.set_alert_rules_updated_at()")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
