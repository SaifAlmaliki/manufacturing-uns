# OPC UA edge connector

Date: 2026-09-01
Modules: `10_uns_opcua` (new), `conf`, root `pyproject.toml`, `docker-compose.yml`
Status: Approved, not yet implemented

## 1. Problem

Every ingest path into the Unified Namespace starts at MQTT. `05_sparkplugb` translates
Sparkplug B, which is already MQTT-native; `99_simulator` invents data. Nothing in this
repository can read a real PLC, SCADA or HMI, so the platform can only ingest from
equipment that already speaks MQTT — which brownfield plant equipment does not.

This is the "Connect" step of the memo's approach, and the memo's own risk register names
the mitigation: "Implement tactical Edge of Node Devices to translate legacy protocols to
event-based." Without it the pilot cannot leave the simulator.

This spec adds a read-only OPC UA connector that subscribes to configured nodes on one or
more OPC UA servers and publishes them into the Unified Namespace, surviving broker and
network outages without losing data.

## 2. Findings that shape the design

Established by reading the code, not assumed:

1. **The historian is already idempotent on replay.** `historian_handler.py:42`–`:52`
   inserts with `ON CONFLICT DO NOTHING ... RETURNING`, and `:192`–`:195` writes
   `uns_metrics` only `if inserted and metric_rows` — so a duplicate raw event returns no
   row and its Metrics are not double-counted either, both inside one transaction. This is
   what makes at-least-once delivery from a spool safe rather than corrupting.
2. **The uniqueness key includes the payload.** `CONSTRAINT unique_event UNIQUE (time,
   topic, client_id, mqtt_msg)`, defined identically at `docker-compose.yml:128` and
   `.devcontainer/devcontainersetup.sh:122`. `mqtt_msg` is `JSONB`, so Postgres compares
   it semantically after parsing — key order, whitespace and `75.0` vs `75.00` are equal.
   The requirement is therefore *not* byte-stable serialisation; it is that no field be
   re-derived at drain time.
3. **The README wants that constraint narrowed** to `(time, topic, client_id)` because the
   payload column is what breaks TimescaleDB compression. Replay stays idempotent under
   the narrowed form too — one topic yields one value per `SourceTimestamp` — so this
   design does not depend on which version wins.
4. **`time` comes from the payload.** `conf/settings.yaml:51` sets
   `mqtt.timestamp_attribute: "timestamp"`, so the payload's `timestamp` field becomes the
   historian's `time` column, and therefore part of the uniqueness key.
5. **The simulator is the only existing publisher, and two of its habits must not be
   copied.** `devices.py:84` opens and tears down a broker connection inside every single
   `publish_parameter` call; `devices.py:34` builds a client id as
   `f"graphql-{time.time()}-{random.randint(0, 1000)}"`, random per process. Under replay,
   a random `client_id` duplicates every row (finding 2).
6. **The simulator stamps publish time, not source time.** `devices.py:71` sets
   `'timestamp': datetime.now().timestamp() * 1000`. A connector doing this would make
   every replayed message a new row, so the spool would silently corrupt history instead
   of repairing it.
7. **The simulator fabricates `status`.** `devices.py:186` derives `Normal`/`Warning`/
   `Alarm` from how far a value sits from its base. A connector has no basis for that
   judgement.
8. **The target topic shape is
   `<enterprise>/<site>/<area>/<line>/<cell>/<equipment>/<ParameterType>/<ParameterName>`**
   (`models.py:73`).
9. **MQTT transport security already exists.** `UnsMQTTClient.setup_tls`
   (`mqtt_listener.py:242`) handles CA certs, client certs, `cert_reqs` and ciphers, and
   the simulator's `MQTTConfig` (`99_simulator/src/uns_simulator/config.py:49`–`:72`)
   already reads `mqtt.tls`, `mqtt.username` and `mqtt.password` from settings. Only the
   OPC UA server-side session security is new work.
10. **The Asset Model already has this vocabulary.** CONTEXT.md defines Metric Key as "the
    topic segments below the Asset's path followed by the dotted path within the payload",
    and `09_uns_model/src/uns_model/tables.py` provides `Asset`, `MetricDefinition` and
    `TopicBinding`.
11. **Module conventions.** `python:3.14-alpine3.22` with `UNS_MODULE` and
    `UNS_CONF_DIR=/app/conf`; `prometheus_client` counters prefixed `uns_<module>_`;
    `health_check.py` via `psutil`; a `uv` workspace member with its own `pyproject.toml`
    that extends the root `[tool.ruff]`.
12. **Module number 10 is free** — 00–09, 11 and 99 are taken.

## 3. Scope

**In scope.** Read-only subscription to configured OPC UA nodes on one or more servers;
translation to the Unified Namespace payload shape; disk-backed store-and-forward to MQTT;
Prometheus instrumentation; non-gating validation against the Asset Model.

**Out of scope, deliberately.** No write-back of setpoints or commands — the memo's
security case rests on OT needing no inbound connections, and writing to a PLC is a
different safety and threat-model conversation. No browse/auto-map of the address space.
No Sparkplug B encoding on egress; plain JSON, as the simulator publishes. No OPC UA
Alarms & Conditions subscription — alarming belongs to an alarm engine. No OPC UA
`HistoryRead` backfill. No GraphQL or console surface for editing mappings; that is the
Asset-Model-driven follow-up this design leaves room for.

## 4. Two rules that the whole design serves

Findings 1, 2, 5 and 6 combine into two hard rules. Everything in sections 6–8 exists to
honour them.

- **Rule 1 — `timestamp` is the OPC UA `SourceTimestamp`, stamped once at collection and
  never re-derived at drain time.** The spooled payload is republished verbatim.
- **Rule 2 — `client_id` is stable across restarts**, read from configuration, never
  generated.

Violate either and the spool stops being a repair mechanism and becomes a duplicate-row
generator.

## 5. Module layout

New workspace member `10_uns_opcua`, package `uns_opcua`:

```
10_uns_opcua/
├── Dockerfile                 # python:3.14-alpine3.22, UNS_MODULE=10_uns_opcua
├── pyproject.toml             # asyncua, aiomqtt, uns_config, dynaconf, prometheus-client, psutil
├── README.md
├── src/uns_opcua/
│   ├── opcua_config.py        # Dynaconf-backed config + validation
│   ├── tag_map.py             # config → TagBinding; topic derivation; duplicate detection
│   ├── payload.py             # OPC UA DataValue → UNS payload dict
│   ├── collector.py           # one session + subscription per server; handler → queue
│   ├── spool.py               # bounded SQLite WAL spool: enqueue / drain / trim
│   ├── forwarder.py           # drains spool → MQTT on one long-lived connection
│   ├── model_check.py         # Asset Model validation (non-gating)
│   ├── prometheus_metrics.py
│   ├── health_check.py
│   └── main.py                # supervisor: builds tasks, handles shutdown
└── test/
```

OPC UA `Basic256Sha256` requires `cryptography`, which publishes `musllinux` wheels, so
Alpine remains viable with no build toolchain in the image.

## 6. Configuration and topic derivation

Mappings name an **Asset** and a **`metric_path`** rather than a flat topic, because that is
already the project's vocabulary (finding 10): the topic is `asset + "/" + metric_path`.
This avoids restating an eight-level path per tag and makes Asset Model validation a direct
lookup rather than a string parse.

`metric_path` is deliberately the existing name from `TopicBinding.metric_path`
(`tables.py:247`, "Topic segments below the Asset"), *not* Metric Key. CONTEXT.md defines a
Metric Key as the topic segments below the Asset **followed by the dotted path within the
payload** — `ProcessValue/Temperature/value`. Topic derivation must not include that payload
leaf, so reusing "Metric Key" here would be wrong by one segment.

```yaml
opcua:
  client_id: "uns_opcua_dormagen"        # Rule 2 — stable across restarts
  spool:
    path: "/var/lib/uns_opcua/spool.db"
    max_rows: 5000000
    max_bytes: 2000000000
    max_age_hours: 168
    synchronous: "NORMAL"                # see section 8
  model_check: true                       # validate; never gate startup
  servers:
    - name: "dormagen-plc01"
      url: "opc.tcp://10.4.2.11:4840/"
      publishing_interval_ms: 200
      security:
        policy: "Basic256Sha256"
        mode: "SignAndEncrypt"
        certificate: "/certs/opcua/client.der"
        private_key: "/certs/opcua/client.key"
        server_certificate: "/certs/opcua/server.der"
      tags:
        - node_id: "ns=2;s=Mixer.Temp_PV"
          asset: "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"
          metric_path: "ProcessValue/Temperature"   # topic segments below the Asset
          unit: "°C"
          deadband: { type: "absolute", value: 0.2 }   # or { type: "percent", value: 1.0 }
```

Credentials and pass phrases come from `conf/.secrets.yaml` or environment variables, as
elsewhere in this stack. MQTT connection settings are read from the existing `mqtt` block
via `uns_config`, so TLS and broker credentials are configuration only (finding 9).

## 7. The collect → spool → publish pipeline

Three stages in one process, decoupled by an `asyncio.Queue` and by the spool.

**Collector — one supervised task per server.** Opens an `asyncua.Client` session, applies
security, resolves each `node_id`, and creates **one subscription per server** whose
monitored items carry a server-side `DataChangeFilter` deadband. Server-side is the point:
the deadband is what makes this report-by-exception (the memo's Key Principle 2) rather
than polling in disguise. If a server rejects the filter the collector retries without one,
logs once, counts it, and optionally applies a client-side deadband.

Reconnect is the subtle part, and verification simplified it. An OPC UA subscription
reports changes only *while subscribed*, so a tag that changes during an outage would
otherwise never be reported. But **creating a monitored item delivers its current value
immediately** as the first notification — confirmed empirically against `asyncua` 2.0.1,
where subscribing produced a `datachange_notification` before any write occurred. So
**reconnect → re-resolve → re-subscribe is sufficient**; no explicit read pass is needed.

This is better than an explicit read, because the initial notification carries the server's
real `SourceTimestamp` — the moment the value actually changed — rather than the time we
happened to read it. Rule 1 is preserved. And if the value did *not* change during the
outage, the re-delivered notification is byte-identical in its significant fields, so the
historian's dedupe (finding 1) absorbs it. The gap heals either way.

**Spool writer — one task.** Drains the queue in batches (≤500 rows or 50 ms, whichever
comes first) into one transaction. Batching is what lets SQLite keep up; a single writer
means no lock contention. If the queue is full — a disk problem, not a broker problem — the
collector drops oldest and counts it.

**Forwarder — one task.** `SELECT id, topic, payload FROM spool ORDER BY id LIMIT n`, then
publish each at QoS 1 awaiting broker acknowledgement, then `DELETE FROM spool WHERE
id <= :max_id`, over one long-lived `aiomqtt` connection — explicitly not the simulator's
connect-per-publish (finding 5). A crash between publish and delete replays on restart,
which the historian absorbs (finding 1). When the broker is down the forwarder backs off
and the spool grows; that is the intended behaviour, not an error state.

**Everything goes through the spool, always.** There is no "publish direct, spool on
failure" fast path. Two paths allow a spooled backlog to interleave with fresh publishes
and break per-topic ordering, in exchange for a few milliseconds of latency that
report-by-exception data does not care about.

## 8. Spool schema and bounding

```sql
CREATE TABLE IF NOT EXISTS spool (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  topic      TEXT NOT NULL,
  payload    BLOB NOT NULL,   -- UTF-8 JSON, republished verbatim (Rule 1)
  qos        INTEGER NOT NULL DEFAULT 1,
  spooled_at REAL NOT NULL    -- retention only; deliberately NOT in the payload
);
```

`PRAGMA journal_mode=WAL`. `synchronous=NORMAL` by default: a power cut can lose the last
few milliseconds of writes, which is a better trade than the order-of-magnitude throughput
cost of `FULL`, and `FULL` remains available as a config knob for sites that disagree.

The monotonic `id` gives FIFO and therefore per-topic ordering. `spooled_at` stays outside
the payload precisely because it would differ between original and replay, which would
violate Rule 1.

Bounds are enforced after each write batch — `max_rows`, `max_bytes` (via
`page_count × page_size`), `max_age_hours` — deleting lowest ids and incrementing a
counter. The bound is not optional: an unbounded spool converts a week-long WAN outage into
a full disk that takes the whole edge node down, which is strictly worse than losing the
oldest tail of the data.

## 9. Payload mapping

```json
{
  "value": 74.83,
  "unit": "°C",
  "quality": "Good",
  "timestamp": 1756704000123.0,
  "source": "uns_opcua_dormagen",
  "equipment": "MixerTank"
}
```

- `value` ← `DataValue.Value.Value`. Arrays and structures serialise as nested JSON; the
  historian's `flatten_payload_to_metrics` already projects nesting into dotted Metric
  paths.
- `timestamp` ← `SourceTimestamp` as epoch milliseconds, matching finding 4. Falls back to
  `ServerTimestamp`, then to collection time — each fallback counted by reason, never
  silent. This is Rule 1.
- `quality` ← `StatusCode`, mapped to `Good` / `Uncertain` / `Bad`. A real quality signal
  from the source rather than an invention. `Bad` values are still published: "the sensor
  went bad" is information the platform should carry, not discard.
- `unit` ← configuration.
- `source` ← the configured `client_id`. This is Rule 2.
- `equipment` ← the last segment of the `asset` path.

**No `status` field**, diverging from the simulator (finding 7). A connector cannot
justify a `Normal`/`Warning`/`Alarm` judgement, and that judgement belongs to an alarm
engine reading the namespace. Consumers that read `status` from simulator payloads must
tolerate its absence.

## 10. Asset Model validation — reporting, never gating

`model_check.py` runs both as a `--validate` CLI mode and as a non-blocking startup check
when `model_check: true`. It reports:

- `asset` values absent from `model.asset`
- `metric_path` values with no matching `MetricDefinition`. Because a `MetricDefinition` is
  keyed by Metric Key, and this connector's payload always carries its scalar under `value`,
  the key to look up is `<metric_path>/value` — for example `ProcessValue/Temperature` is
  checked against `ProcessValue/Temperature/value`.
- a configured `unit` disagreeing with the MetricDefinition's Unit of Measure
- duplicate `node_id`s, and two tags resolving to the same topic

`--validate` exits non-zero so CI can gate a config change. At startup it only logs and
sets the `uns_opcua_unmodelled_tags` gauge. It never blocks publishing: an edge connector
that cannot start without enterprise Postgres defeats the reason the config-file approach
was chosen over an Asset-Model-driven one.

## 11. Failure modes

| Failure | Behaviour |
| --- | --- |
| OPC UA server down at start | Task retries with backoff + jitter; other servers unaffected; `server_up` = 0 |
| Session drops | Reconnect → re-resolve → re-subscribe; the monitored item's initial notification recovers the gap |
| Server rejects deadband filter | Retry without filter, log once, count; optional client-side deadband |
| `node_id` unresolvable | Log once, skip that tag, count; the rest of that server keeps running |
| Broker down | Forwarder backs off; spool grows; collection continues |
| Spool at bound | Drop oldest, increment `spool_dropped_total` |
| Disk full | Writer catches, increments `spool_write_errors_total`; process stays up |
| Crash between publish and delete | Replays on restart; historian absorbs it (finding 1) |
| `Bad` / `Uncertain` StatusCode | Published with `quality` set — never dropped |

## 12. Metrics

Instrumented from the first commit, so this module does not join the "only 2 of 5 services
expose metrics" gap the README records.

`uns_opcua_server_up{server}`, `_monitored_items{server}`, `_datachanges_total{server}`,
`_publish_total`, `_publish_errors_total`, `_spool_rows`, `_spool_bytes`,
`_spool_dropped_total`, `_spool_write_errors_total`, `_spool_lag_seconds`,
`_unmodelled_tags`, `_timestamp_fallback_total{reason}`.

`_spool_lag_seconds` — now minus the oldest `spooled_at` — is the number an operator
actually needs: how far behind is this edge node.

## 13. Testing

- **Unit.** Payload mapping including StatusCode and timestamp fallbacks; tag-map parsing,
  topic derivation and duplicate detection; spool bounding by rows, bytes and age; FIFO
  ordering.
- **Spool integration.** Temp-file SQLite; kill between publish and delete; assert replay
  occurs and that the historian's dedupe absorbs it.
- **OPC UA integration** (`@pytest.mark.integrationtest`). `asyncua` ships an in-process
  `Server`, so tests start one, expose nodes, and assert subscription, deadband, and
  reconnect behaviour. No external dependency for this half.
- **End to end** (`@pytest.mark.integrationtest`, `xdist_group`). asyncua server →
  connector → Compose broker → assert topics and payloads.

## 14. Registration checklist

- Root `pyproject.toml`: `dependencies`, `[tool.uv.sources]`, `[tool.uv.workspace] members`,
  and pytest `testpaths` + `pythonpath`
- `conf/settings.yaml`: `opcua:` environment
- `docker-compose.yml`: `uns_opcua_client` service with a named volume for the spool
- `08_uns_observability`: Prometheus scrape target
- Root `README.md`: module list, container table, and the technology-choice rationale

## 15. Judgement calls open to revision

1. **Dropping `status`** (section 9) diverges from the simulator's payload shape; any
   frontend code reading `status` must tolerate its absence.
2. **`synchronous=NORMAL`** (section 8) trades a few milliseconds of data on power loss for
   roughly an order of magnitude of spool throughput.
3. **One process for all servers.** Per-server asyncio task supervision provides the
   isolation, not process boundaries. A plant with enough servers to saturate one process
   would want the container-per-server variant instead.
