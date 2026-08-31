-- Narrow metrics hypertable projected from unifiednamespace JSONB payloads.
-- Apply as uns_dbuser against database uns_historian after 02_setup_hypertable.sql:
--   psql -U uns_dbuser -h localhost -d uns_historian -f 04_setup_metrics_hypertable.sql

CREATE TABLE IF NOT EXISTS uns_metrics (
  time TIMESTAMPTZ NOT NULL,
  topic TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  value_double DOUBLE PRECISION,
  value_text TEXT,
  CONSTRAINT uns_metrics_value_check CHECK (
    (value_double IS NOT NULL AND value_text IS NULL)
    OR (value_double IS NULL AND value_text IS NOT NULL)
  )
);

SELECT create_hypertable('uns_metrics', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_uns_metrics_topic_metric_time
  ON uns_metrics (topic, metric_name, time DESC);

-- Continuous aggregates for Grafana panels (query aggregates, never raw).
CREATE MATERIALIZED VIEW IF NOT EXISTS uns_metrics_1m
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 minute', time) AS bucket,
  topic,
  metric_name,
  avg(value_double) AS avg_value_double,
  count(*) AS sample_count
FROM uns_metrics
WHERE value_double IS NOT NULL
GROUP BY bucket, topic, metric_name
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS uns_metrics_1h
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', time) AS bucket,
  topic,
  metric_name,
  avg(value_double) AS avg_value_double,
  count(*) AS sample_count
FROM uns_metrics
WHERE value_double IS NOT NULL
GROUP BY bucket, topic, metric_name
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
  'uns_metrics_1m',
  start_offset => INTERVAL '1 day',
  end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute',
  if_not_exists => TRUE
);

SELECT add_continuous_aggregate_policy(
  'uns_metrics_1h',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour',
  if_not_exists => TRUE
);

-- Retention: raw events earliest, coarse aggregates last (engineering defaults).
SELECT add_retention_policy('unifiednamespace', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_retention_policy('uns_metrics', INTERVAL '1 year', if_not_exists => TRUE);
SELECT add_retention_policy('uns_metrics_1m', INTERVAL '1 year', if_not_exists => TRUE);
SELECT add_retention_policy('uns_metrics_1h', INTERVAL '5 years', if_not_exists => TRUE);

-- Compression after 7 days.
ALTER TABLE unifiednamespace SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'topic'
);
SELECT add_compression_policy('unifiednamespace', INTERVAL '7 days', if_not_exists => TRUE);

ALTER TABLE uns_metrics SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'topic, metric_name'
);
SELECT add_compression_policy('uns_metrics', INTERVAL '7 days', if_not_exists => TRUE);

COMMENT ON TABLE uns_metrics IS
  'Projection of scalar payload leaves keyed by dotted path. Rebuildable from unifiednamespace.';
COMMENT ON MATERIALIZED VIEW uns_metrics_1m IS
  '1-minute continuous aggregate for Grafana process visualization.';
COMMENT ON MATERIALIZED VIEW uns_metrics_1h IS
  '1-hour continuous aggregate for Grafana process visualization.';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
    GRANT SELECT, INSERT ON uns_metrics TO uns_dbuser;
    GRANT SELECT ON uns_metrics_1m TO uns_dbuser;
    GRANT SELECT ON uns_metrics_1h TO uns_dbuser;
  END IF;
END
$$;
