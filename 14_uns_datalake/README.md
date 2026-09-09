# Historic Event lake Mapper (`14_uns_datalake`)

This module is a **Mapper**. Default `uns_compose up` writes date-partitioned Parquet
to the always-on local MinIO bucket `uns-historic-events`. It consumes Kafka topic
`uns.historic-events` only — it never subscribes to MQTT.

## Delivery semantics

Delivery is **at-least-once from the envelope Kafka topic to the lake**. Duplicates
after failures are acceptable; committing past an unpersisted valid event is not.
Shutdown or ownership loss abandons the uncommitted batch for Kafka replay.

Poison envelopes are logged without payload, skipped for Parquet, and their offsets
commit only after any buffered valid records in the same flush are uploaded. Upload
retries are bounded (three attempts with 1s then 2s backoff) while consumption is
paused.

Each flush groups rows by UTC event date and MQTT topic:
`dt=YYYY-MM-DD/<topic_safe>-<flush_id>.parquet` with columns `time`, `topic`, and
JSON `payload` only.

## Health

- `uns_datalake_up` — process liveness (Docker healthcheck uses this plus loop age).
- `uns_datalake_ready` — dependency readiness (Kafka assignment, no active upload failure).

Condition Monitoring does not read the lake.

## Production overlays

```yaml
# AWS: keep local minio.root_* separately; omit datalake.s3 static keys.
default:
  datalake:
    backend: s3
    s3:
      endpoint_url: ""
      bucket: plant-historic-events
      region: us-east-1
```

```yaml
# ADLS: provision this filesystem/container first; omit account_key for identity auth.
default:
  datalake:
    backend: adls
    adls:
      account: plantstorage
      container: historic-events
```

The selected cloud destination must already exist and the process identity must have
write access. Local Compose still starts MinIO and creates its default bucket; no
dual-write occurs. Clearing the AWS endpoint while retaining only `minio.root_*`
selects the AWS credential chain.
