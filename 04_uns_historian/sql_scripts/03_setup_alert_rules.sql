-- Transactional console config for ISA-18.2 alert rules.
-- Lives in schema `console` on the same Postgres/Timescale instance as the
-- historian hypertable. Do not store rules in `public.unifiednamespace`.
--
-- Apply as uns_dbuser against database uns_historian:
--   psql -U uns_dbuser -h localhost -d uns_historian -f 03_setup_alert_rules.sql

CREATE SCHEMA IF NOT EXISTS console;

CREATE TABLE IF NOT EXISTS console.alert_rules (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  severity TEXT NOT NULL
    CHECK (severity IN ('CRITICAL', 'HIGH', 'WARNING', 'INFO')),
  category TEXT NOT NULL
    CHECK (category IN (
      'TEMPERATURE',
      'PRESSURE',
      'VIBRATION',
      'FLOW_RATE',
      'STALE_TIMEOUT',
      'NODE_OFFLINE',
      'COMMUNICATION',
      'THRESHOLD',
      'SAFETY',
      'CUSTOM'
    )),
  topic TEXT NOT NULL,
  metric_field TEXT NOT NULL,
  condition TEXT NOT NULL
    CHECK (condition IN (
      'GREATER_THAN',
      'LESS_THAN',
      'EQUALS',
      'NOT_EQUALS',
      'RANGE_OUTSIDE',
      'STALE_TIMEOUT',
      'CONTAINS'
    )),
  threshold_value JSONB NOT NULL,
  threshold_upper_value DOUBLE PRECISION,
  unit TEXT,
  delay_seconds INTEGER NOT NULL DEFAULT 0
    CHECK (delay_seconds >= 0),
  escalation_role TEXT
    CHECK (escalation_role IS NULL OR escalation_role IN (
      'admin',
      'engineer',
      'operator',
      'auditor',
      'viewer'
    )),
  escalation_timeout_minutes INTEGER
    CHECK (escalation_timeout_minutes IS NULL OR escalation_timeout_minutes >= 1),
  auto_resolve_on_normal BOOLEAN NOT NULL DEFAULT TRUE,
  in_app_notification BOOLEAN NOT NULL DEFAULT TRUE,
  audio_chime BOOLEAN NOT NULL DEFAULT TRUE,
  mqtt_publish_on_trigger BOOLEAN NOT NULL DEFAULT FALSE,
  mqtt_alarm_topic TEXT,
  email_webhook BOOLEAN NOT NULL DEFAULT FALSE,
  webhook_url TEXT,
  trigger_count INTEGER NOT NULL DEFAULT 0
    CHECK (trigger_count >= 0),
  last_triggered_at TIMESTAMPTZ,
  last_evaluated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS console.alert_rule_roles (
  rule_id TEXT NOT NULL
    REFERENCES console.alert_rules (id) ON DELETE CASCADE,
  role TEXT NOT NULL
    CHECK (role IN ('admin', 'engineer', 'operator', 'auditor', 'viewer')),
  PRIMARY KEY (rule_id, role)
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled
  ON console.alert_rules (enabled);

CREATE INDEX IF NOT EXISTS idx_alert_rules_topic
  ON console.alert_rules (topic);

CREATE INDEX IF NOT EXISTS idx_alert_rules_severity
  ON console.alert_rules (severity);

CREATE INDEX IF NOT EXISTS idx_alert_rule_roles_role
  ON console.alert_rule_roles (role);

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

COMMENT ON SCHEMA console IS
  'Transactional UNS console configuration (alert rules, future RBAC). Not time-series.';
COMMENT ON TABLE console.alert_rules IS
  'ISA-18.2 alert rule definitions persisted from the /alerts console.';
COMMENT ON TABLE console.alert_rule_roles IS
  'Roles that receive notifications when an alert rule fires.';
COMMENT ON COLUMN console.alert_rules.threshold_value IS
  'JSON scalar matching the UI (number, string, or boolean).';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
    GRANT USAGE ON SCHEMA console TO uns_dbuser;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA console TO uns_dbuser;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA console TO uns_dbuser;
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA console TO uns_dbuser;
    ALTER DEFAULT PRIVILEGES IN SCHEMA console
      GRANT ALL ON TABLES TO uns_dbuser;
  END IF;
END
$$;
