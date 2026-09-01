# UNS OPC UA Edge Connector

Reads tags from one or more OPC UA servers by subscription and publishes them into the
Unified Namespace over MQTT. Read-only: it never writes setpoints, never calls methods.

## Why it exists

Every other ingest path into this platform starts at MQTT, which brownfield plant
equipment does not speak. This is the "Connect" step — the Edge-of-Node translation that
lets a real PLC, SCADA or HMI reach the namespace.

## How it works

    OPC UA subscription  ->  asyncio.Queue  ->  SQLite spool  ->  MQTT (QoS 1)

Report-by-exception is done by the *server*: each monitored item carries a
`DataChangeFilter` deadband, so the server sends a notification only when a value moves
far enough to matter. This is not polling with extra steps.

Everything goes through the spool, always. When the broker or the WAN is down the spool
grows on disk and collection continues; when the broker returns the spool drains in `id`
order, which preserves per-topic ordering. There is deliberately no direct-publish fast
path, because two paths would let a draining backlog interleave with fresh values.

Replay is safe because the historian inserts with `ON CONFLICT DO NOTHING` and writes
`uns_metrics` only for rows that were actually inserted. That safety depends on two rules
this connector must never break:

1. `timestamp` is the OPC UA `SourceTimestamp`, stamped once at collection. The spooled
   payload is republished byte-for-byte; no field is re-derived at drain time.
2. `client_id` comes from configuration and is stable across restarts.

Break either and every replayed message becomes a new row instead of a no-op.

## Payload

```json
{
  "value": 74.83,
  "unit": "°C",
  "quality": "Good",
  "timestamp": 1756704000123.0,
  "source": "uns_opcua_client",
  "equipment": "MixerTank"
}
```

There is no `status` field. `quality` is the real OPC UA `StatusCode` severity
(`Good` / `Uncertain` / `Bad`); a connector has no basis for a `Normal`/`Warning`/`Alarm`
judgement, and that belongs to an alarm engine reading the namespace. `Bad` values are
published rather than dropped — "the sensor went bad" is information.

## Configuration

See the `opcua` block in `conf/settings.yaml`. The published topic is
`asset + "/" + metric_path`. Certificate pass phrases and broker credentials belong in
`conf/.secrets.yaml` or `UNS_`-prefixed environment variables.

## Validating a mapping against the Asset Model

    uv run uns_opcua_validate

Exits non-zero when a tag names an unknown Asset, has no matching MetricDefinition, or
disagrees with its Unit of Measure — so CI can gate a config change. At runtime the same
check only logs and sets a gauge: an edge connector that cannot start without enterprise
Postgres would defeat the point of mapping by config file.
