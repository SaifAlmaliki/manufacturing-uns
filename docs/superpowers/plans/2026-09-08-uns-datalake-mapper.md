# Historic Event lake Mapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kafka_mapper` also produces envelope topic `uns.historic-events`; a new Mapper writes date-partitioned Parquet to MinIO (default), AWS S3, or Azure ADLS.

**Architecture:** Keep dotted Kafka topics. Add a literal-topic produce for the envelope. `00_uns_config.datalake` owns layout, record, fake store, and envelope JSON. `14_uns_datalake` consumes the envelope, flushes Parquet, and `put`s via one backend. Default Compose always starts MinIO + `datalake_mapper`.

**Tech Stack:** confluent-kafka, pyarrow, boto3, `azure-storage-file-datalake`, prometheus-client, pytest, Docker Compose, MinIO.

**Spec:** `docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md`

## Global Constraints

- **Envelope Kafka topic (verbatim):** `uns.historic-events`
- **Keep 1:1 dotted topics.** `convert_mqtt_kafka_topic` stays `/` → `.`
- **Lake Mapper never imports MQTT** and never subscribes to the broker
- **One backend per plant:** `datalake.backend` is `s3` or `adls`. Never dual-write
- **Default Compose:** MinIO + `datalake_mapper` always on (no `profiles`). Azurite absent
- **Default settings:** `backend: s3`, `s3.endpoint_url: http://uns_minio:9000`, bucket `uns-historic-events`
- **Parquet columns:** `("time", "topic", "payload")` only. `payload` is JSON text of the object. No Enrichment
- **Layout:** `dt=YYYY-MM-DD/<topic_safe>-<flush_id>.parquet` with `/` → `_`
- **Flush:** 60s or 8388608 bytes, whichever first
- **Offsets:** `enable.auto.commit: false`. Commit **after** successful `put`. Poison envelope: skip + commit, no `put`
- **Auth:** MinIO keys in `.secrets.yaml`. Production S3: default credential chain unless keys present. Production ADLS: `DefaultAzureCredential` unless account key present
- **No live AWS/Azure/MQTT in pytest.** Stub S3/ADLS clients. Fake Kafka for the Mapper
- **Module directory is `14_uns_datalake`.** Spec said `13_`; `13_uns_factory_agent` already exists. Compose service remains `datalake_mapper`. Patch the spec in Task 6
- **Cloud SDKs live in `14_uns_datalake`, not `uns_config`.** `uns_config.datalake` is types/path/fake/envelope so GraphQL does not grow boto3. This is the only intentional spec seam
- **`uns_config` must not import `uns_datalake`**
- **Do not implement on `main`.** Branch `feat/uns-datalake-mapper` from current `main`

---

## File Structure

```
00_uns_config/src/uns_config/datalake.py
00_uns_config/test/test_datalake.py
00_uns_config/src/uns_config/compose_env.py
00_uns_config/test/test_compose_env.py
conf/settings.yaml
conf/.secrets_template.yaml

06_uns_kafka/src/uns_kafka/kafka_handler.py
06_uns_kafka/src/uns_kafka/uns_kafka_config.py
06_uns_kafka/src/uns_kafka/uns_kafka_listener.py
06_uns_kafka/test/test_kafka_handler.py
06_uns_kafka/test/test_uns_kafka_listner.py
06_uns_kafka/README.md

14_uns_datalake/pyproject.toml
14_uns_datalake/uv.lock
14_uns_datalake/README.md
14_uns_datalake/Dockerfile
14_uns_datalake/src/uns_datalake/__init__.py
14_uns_datalake/src/uns_datalake/config.py
14_uns_datalake/src/uns_datalake/parquet.py
14_uns_datalake/src/uns_datalake/batch.py
14_uns_datalake/src/uns_datalake/stores.py
14_uns_datalake/src/uns_datalake/metrics.py
14_uns_datalake/src/uns_datalake/health_check.py
14_uns_datalake/src/uns_datalake/mapper.py
14_uns_datalake/src/uns_datalake/main.py
14_uns_datalake/test/test_config.py
14_uns_datalake/test/test_parquet.py
14_uns_datalake/test/test_batch.py
14_uns_datalake/test/test_stores.py
14_uns_datalake/test/test_mapper.py
14_uns_datalake/test/test_health_check.py
14_uns_datalake/test/test_deployment.py

pyproject.toml
docker-compose.yml
docker-compose.dev.yml
08_uns_observability/prometheus/prometheus.yml
docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md
docs/superpowers/plans/2026-09-07-connectivity-edge-live-apply.md
```

**Task order:** 1 → 2 → 3 → 4 → 5 → 6.

---

### Task 1: Layout, envelope JSON, and FakeObjectStore in `uns_config`

**Files:**
- Create: `00_uns_config/src/uns_config/datalake.py`
- Create: `00_uns_config/test/test_datalake.py`

**Interfaces:**
- Produces: `ENVELOPE_TOPIC = "uns.historic-events"`; `HISTORIC_EVENT_COLUMNS`; `HistoricEventRecord`; `historic_event_object_path`; `topic_safe`; `new_flush_id`; `build_envelope`; `parse_envelope`; `ObjectStore` protocol; `FakeObjectStore`
- Does not import boto3/azure/pyarrow

- [ ] **Step 1: Write the failing tests**

Create `00_uns_config/test/test_datalake.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from uns_config.datalake import (
    ENVELOPE_TOPIC,
    HISTORIC_EVENT_COLUMNS,
    FakeObjectStore,
    HistoricEventRecord,
    build_envelope,
    historic_event_object_path,
    parse_envelope,
    topic_safe,
)


def test_envelope_topic_name():
    assert ENVELOPE_TOPIC == "uns.historic-events"


def test_columns_are_historic_event_only():
    assert HISTORIC_EVENT_COLUMNS == ("time", "topic", "payload")
    assert "asset" not in HISTORIC_EVENT_COLUMNS


def test_topic_safe_replaces_slash_not_dot():
    assert topic_safe("Acme/Line/Temp") == "Acme_Line_Temp"


def test_object_path_date_partition_and_unique_flush():
    when = datetime(2026, 9, 8, 15, 4, tzinfo=UTC)
    path = historic_event_object_path(event_time=when, topic="Acme/Line/Temp", flush_id="20260908T150400-abcd1234")
    assert path == "dt=2026-09-08/Acme_Line_Temp-20260908T150400-abcd1234.parquet"
    assert "Acme/Line" not in path


def test_build_envelope_uses_payload_timestamp():
    payload = {"timestamp": 1757337600000, "value": 1.2}
    env = build_envelope("Acme/Line/Temp", payload, timestamp_key="timestamp", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert env["topic"] == "Acme/Line/Temp"
    assert env["payload"] == payload
    assert env["time"].startswith("2026-09-08")


def test_build_envelope_falls_back_to_now_when_timestamp_missing():
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    env = build_envelope("t", {"value": 1}, timestamp_key="timestamp", now=now)
    assert env["time"].startswith("2026-09-08T12:00:00")


def test_parse_envelope_round_trip():
    record = parse_envelope(json.dumps({
        "time": "2026-09-08T12:00:00+00:00",
        "topic": "Acme/Line/Temp",
        "payload": {"value": 1},
    }).encode())
    assert record.topic == "Acme/Line/Temp"
    assert record.payload == {"value": 1}


def test_parse_envelope_poison_returns_none():
    assert parse_envelope(b"not-json") is None
    assert parse_envelope(b'{"topic": "t"}') is None
    assert parse_envelope(json.dumps({"time": "t", "topic": "x", "payload": "nope"}).encode()) is None


def test_fake_store_writes_bytes(tmp_path: Path):
    store = FakeObjectStore(tmp_path)
    store.put("dt=2026-09-08/x.parquet", b"PARQUET")
    assert (tmp_path / "dt=2026-09-08/x.parquet").read_bytes() == b"PARQUET"
```

For `test_build_envelope_uses_payload_timestamp`: 1757337600000 ms is 2026-09-08T12:00:00Z. If you pick another millis, update the assertion to match `datetime.fromtimestamp(ms/1000, UTC)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_datalake.py -v`

Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`datalake.py`:

```python
"""Historic Event object-store port: layout, envelope JSON, fake store.

A Mapper later puts Parquet via S3 or ADLS. That Mapper reads Kafka envelope
topic uns.historic-events (MQTT topic in the value). Do not subscribe to MQTT here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

ENVELOPE_TOPIC = "uns.historic-events"
HISTORIC_EVENT_COLUMNS = ("time", "topic", "payload")


@dataclass(frozen=True, slots=True)
class HistoricEventRecord:
    time: datetime
    topic: str
    payload: dict[str, Any]


class ObjectStore(Protocol):
    def put(self, path: str, parquet_bytes: bytes) -> None: ...


class FakeObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, path: str, parquet_bytes: bytes) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(parquet_bytes)


def topic_safe(topic: str) -> str:
    return topic.replace("/", "_")


def new_flush_id(*, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def historic_event_object_path(*, event_time: datetime, topic: str, flush_id: str) -> str:
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    day = event_time.astimezone(UTC).date().isoformat()
    return f"dt={day}/{topic_safe(topic)}-{flush_id}.parquet"


def _to_iso8601_utc(raw: Any, *, now: datetime) -> str:
    if raw is None:
        instant = now
    elif isinstance(raw, datetime):
        instant = raw
    elif isinstance(raw, (int, float)):
        seconds = raw / 1000.0 if raw > 1e11 else float(raw)
        instant = datetime.fromtimestamp(seconds, tz=UTC)
    elif isinstance(raw, str) and raw:
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        instant = now
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).isoformat()


def build_envelope(
    mqtt_topic: str,
    payload: dict[str, Any],
    *,
    timestamp_key: str,
    now: datetime,
) -> dict[str, Any]:
    raw = payload.get(timestamp_key) if isinstance(payload, dict) else None
    return {"time": _to_iso8601_utc(raw, now=now), "topic": mqtt_topic, "payload": payload}


def parse_envelope(raw: bytes) -> HistoricEventRecord | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    time_raw, topic, payload = data.get("time"), data.get("topic"), data.get("payload")
    if not isinstance(time_raw, str) or not isinstance(topic, str) or not isinstance(payload, dict):
        return None
    try:
        when = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return HistoricEventRecord(time=when, topic=topic, payload=payload)
```

Do **not** add these names to `uns_config/__init__.py`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./00_uns_config/test/test_datalake.py ./00_uns_config/test -q --tb=line`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 00_uns_config/src/uns_config/datalake.py 00_uns_config/test/test_datalake.py
git commit -m "feat(config): Historic Event lake layout and envelope JSON."
```

---

### Task 2: `kafka_mapper` also produces `uns.historic-events`

**Files:**
- Modify: `06_uns_kafka/src/uns_kafka/kafka_handler.py`
- Modify: `06_uns_kafka/src/uns_kafka/uns_kafka_config.py`
- Modify: `06_uns_kafka/src/uns_kafka/uns_kafka_listener.py`
- Modify: `06_uns_kafka/test/test_kafka_handler.py`
- Modify: `06_uns_kafka/test/test_uns_kafka_listner.py` (unit test; do not rely on the live-broker integration test for the envelope)
- Modify: `conf/settings.yaml` (`kafka_mapper.kafka.envelope_topic`)

**Interfaces:**
- Consumes: `build_envelope`, `ENVELOPE_TOPIC`, `is_historic_event_topic`
- Produces: `KafkaHandler.produce_raw(kafka_topic: str, message: str, *, key: str | None = None) -> None`; `KAFKAConfig.envelope_topic`

- [ ] **Step 1: Write the failing tests**

In `test_kafka_handler.py` (unit, mock producer — **not** `integrationtest`):

```python
from unittest.mock import Mock

from uns_config.datalake import ENVELOPE_TOPIC
from uns_kafka.kafka_handler import KafkaHandler


def test_produce_raw_does_not_convert_slashes():
    handler = KafkaHandler.__new__(KafkaHandler)
    handler.producer = Mock()
    handler.config = {}
    handler.produce_raw(ENVELOPE_TOPIC, '{"topic":"Acme/Line/Temp"}', key="Acme/Line/Temp")
    handler.producer.produce.assert_called_once()
    args, kwargs = handler.producer.produce.call_args
    assert args[0] == "uns.historic-events"
    assert kwargs.get("key") == "Acme/Line/Temp" or (len(args) > 2 and args[2] == "Acme/Line/Temp")
```

Match whatever `produce` signature you use (`topic, value, key=`).

In `test_uns_kafka_listner.py` add a **unit** test that does not start MQTT/Kafka:

```python
import json
from unittest.mock import Mock, patch
from types import SimpleNamespace

from uns_config.datalake import ENVELOPE_TOPIC
from uns_kafka.uns_kafka_listener import UNSKafkaMapper


def test_on_message_produces_dotted_topic_and_envelope():
    mapper = UNSKafkaMapper.__new__(UNSKafkaMapper)
    mapper.kafka_handler = Mock()
    mapper.uns_client = Mock()
    payload = {"timestamp": 1757337600000, "value": 1.2}
    mapper.uns_client.get_payload_as_dict.return_value = payload
    msg = SimpleNamespace(topic="Acme/Line/Temp", payload=b"{}")
    mapper.on_message(None, None, msg)
    assert mapper.kafka_handler.publish.call_count == 1
    mapper.kafka_handler.publish.assert_called_with("Acme/Line/Temp", str(payload))
    mapper.kafka_handler.produce_raw.assert_called_once()
    args, kwargs = mapper.kafka_handler.produce_raw.call_args
    assert args[0] == ENVELOPE_TOPIC
    body = json.loads(args[1])
    assert body["topic"] == "Acme/Line/Temp"
    assert body["payload"] == payload
    assert kwargs.get("key") == "Acme/Line/Temp"


def test_on_message_skips_platform_observability():
    mapper = UNSKafkaMapper.__new__(UNSKafkaMapper)
    mapper.kafka_handler = Mock()
    mapper.uns_client = Mock()
    msg = SimpleNamespace(topic="uns/platform/sim/x", payload=b"{}")
    mapper.on_message(None, None, msg)
    mapper.kafka_handler.publish.assert_not_called()
    mapper.kafka_handler.produce_raw.assert_not_called()
```

If `UNSKafkaMapper.__new__` is awkward because `on_message` is bound on the instance, call `UNSKafkaMapper.on_message(mapper, None, None, msg)` the same way.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./06_uns_kafka/test/test_kafka_handler.py::test_produce_raw_does_not_convert_slashes ./06_uns_kafka/test/test_uns_kafka_listner.py::test_on_message_produces_dotted_topic_and_envelope ./06_uns_kafka/test/test_uns_kafka_listner.py::test_on_message_skips_platform_observability -v`

Expected: FAIL — `produce_raw` missing.

- [ ] **Step 3: Implement**

`kafka_handler.py` add:

```python
    def produce_raw(self, kafka_topic: str, message: str, *, key: str | None = None) -> None:
        """Produce to a Kafka topic name as given. Do not convert MQTT slashes."""
        if self.producer is None:
            self.producer = Producer(self.config)
        self.producer.produce(kafka_topic, message, key=key, callback=self.delivery_callback)
        self.producer.poll(0)
```

`uns_kafka_config.py` on `KAFKAConfig`:

```python
    envelope_topic: str = settings.get("kafka.envelope_topic", "uns.historic-events")
```

`conf/settings.yaml` under `kafka_mapper.kafka`:

```yaml
    envelope_topic: uns.historic-events
```

`uns_kafka_listener.py` `on_message` after the historic-event check:

```python
        from datetime import UTC, datetime
        import json
        from uns_config.datalake import build_envelope

        payload = self.uns_client.get_payload_as_dict(
            topic=msg.topic, payload=msg.payload, mqtt_ignored_attributes=MQTTConfig.ignored_attributes
        )
        self.kafka_handler.publish(msg.topic, str(payload))
        envelope = build_envelope(
            msg.topic, payload, timestamp_key=MQTTConfig.timestamp_key, now=datetime.now(UTC)
        )
        self.kafka_handler.produce_raw(
            KAFKAConfig.envelope_topic, json.dumps(envelope), key=msg.topic
        )
```

Keep the existing `str(payload)` for the dotted topic. Envelope value is `json.dumps`.

Move the `build_envelope` import to module top once tests pass.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./06_uns_kafka/test/test_kafka_handler.py ./06_uns_kafka/test/test_uns_kafka_listner.py ./06_uns_kafka/test/test_kafka_config.py -q --tb=line`

Expected: PASS. Integration tests that need a broker stay skipped/marked as they are today.

- [ ] **Step 5: Commit**

```bash
git add 06_uns_kafka/src/uns_kafka/kafka_handler.py 06_uns_kafka/src/uns_kafka/uns_kafka_config.py 06_uns_kafka/src/uns_kafka/uns_kafka_listener.py 06_uns_kafka/test/test_kafka_handler.py 06_uns_kafka/test/test_uns_kafka_listner.py conf/settings.yaml
git commit -m "feat(kafka): produce Historic Event envelope topic uns.historic-events."
```

---

### Task 3: Mapper package — config, Parquet, batch, S3/ADLS stores

**Files:**
- Create: `14_uns_datalake/` as listed above (no `mapper.py` / `main.py` yet)
- Modify: root `pyproject.toml` workspace members, `testpaths`, `pythonpath`, `dependencies`, `tool.uv.sources`

**Interfaces:**
- Produces: `DatalakeConfig.from_settings()`; `records_to_parquet`; `HistoricEventBatch`; `S3ObjectStore`; `AdlsObjectStore`; `object_store_from_config(config) -> ObjectStore`

Copy `12_uns_oee/pyproject.toml` structure. Package name `uns_datalake`. Dependencies: `uns_config`, `confluent-kafka>=2.14.0,<3`, `pyarrow>=21,<23` (use whatever latest major `uv add` resolves on 3.14), `boto3>=1.35,<2`, `azure-storage-file-datalake>=12,<13`, `azure-identity>=1.19,<2`, `prometheus-client>=0.21.0,<1`, `dynaconf~=3.2`. Scripts come in Task 4.

After creating pyproject: from repo root `uv lock` so the workspace picks it up.

- [ ] **Step 1: Write the failing tests**

`14_uns_datalake/test/test_parquet.py`:

```python
import json

import pyarrow.parquet as pq

from uns_config.datalake import HISTORIC_EVENT_COLUMNS, HistoricEventRecord
from uns_datalake.parquet import records_to_parquet
from datetime import UTC, datetime


def test_parquet_columns_and_payload_json():
    records = [
        HistoricEventRecord(datetime(2026, 9, 8, tzinfo=UTC), "Acme/Line/Temp", {"value": 1.2}),
    ]
    table = pq.read_table(source=records_to_parquet(records))
    assert tuple(table.column_names) == HISTORIC_EVENT_COLUMNS
    assert json.loads(table.column("payload")[0].as_py()) == {"value": 1.2}
```

`14_uns_datalake/test/test_batch.py`:

```python
from datetime import UTC, datetime, timedelta

from uns_config.datalake import HistoricEventRecord
from uns_datalake.batch import HistoricEventBatch


def test_flush_on_max_bytes():
    batch = HistoricEventBatch(interval_seconds=3600, max_bytes=50, clock=lambda: datetime.now(UTC))
    record = HistoricEventRecord(datetime.now(UTC), "t", {"x": "y" * 40})
    batch.add(record)
    assert batch.should_flush() is True


def test_flush_on_interval():
    start = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    now = start
    batch = HistoricEventBatch(interval_seconds=60, max_bytes=10_000_000, clock=lambda: now)
    batch.add(HistoricEventRecord(start, "t", {"v": 1}))
    assert batch.should_flush() is False
    now = start + timedelta(seconds=61)
    assert batch.should_flush() is True


def test_take_clears():
    batch = HistoricEventBatch(interval_seconds=1, max_bytes=10, clock=lambda: datetime.now(UTC))
    batch.add(HistoricEventRecord(datetime.now(UTC), "t", {"v": 1}))
    taken = batch.take()
    assert len(taken) == 1
    assert batch.take() == []
```

Size estimate: `len(json.dumps(payload)) + len(topic) + 64` per add, so 50-byte max_bytes with a large payload flushes.

`14_uns_datalake/test/test_stores.py`:

```python
from unittest.mock import Mock

from uns_datalake.config import DatalakeConfig
from uns_datalake.stores import AdlsObjectStore, S3ObjectStore, object_store_from_config


def test_s3_put_uses_stub_client():
    client = Mock()
    store = S3ObjectStore(bucket="uns-historic-events", region="us-east-1", client=client)
    store.put("dt=2026-09-08/x.parquet", b"bytes")
    client.put_object.assert_called_once_with(Bucket="uns-historic-events", Key="dt=2026-09-08/x.parquet", Body=b"bytes")


def test_adls_put_uses_stub_file_client():
    file_client = Mock()
    store = AdlsObjectStore(account="acct", container="lake", file_client_for=lambda path: file_client)
    store.put("dt=2026-09-08/x.parquet", b"bytes")
    file_client.upload_data.assert_called_once()


def test_factory_picks_backend():
    s3 = object_store_from_config(DatalakeConfig(backend="s3", s3_bucket="b", s3_region="r"))
    assert isinstance(s3, S3ObjectStore)
    adls = object_store_from_config(DatalakeConfig(backend="adls", adls_account="a", adls_container="c"))
    assert isinstance(adls, AdlsObjectStore)
```

`14_uns_datalake/test/test_config.py`: construct `DatalakeConfig(...)` with defaults matching the spec (backend s3, topic uns.historic-events, group uns_datalake, interval 60, max_bytes 8388608, bucket uns-historic-events, endpoint http://uns_minio:9000, metrics_port 9096). A `from_settings` test can use `monkeypatch` + tmp conf like `test_compose_env`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./14_uns_datalake/test -v`

Expected: FAIL — package missing.

- [ ] **Step 3: Implement**

`DatalakeConfig`: frozen dataclass, `from_settings` via `get_settings("datalake")`. Fields: `backend`, `kafka_topic`, `group_id`, `bootstrap_servers` (from `kafka.config.bootstrap.servers` with a default `localhost:9092`), `interval_seconds`, `max_bytes`, `s3_bucket`, `s3_region`, `s3_endpoint_url: str | None`, `s3_access_key: str | None`, `s3_secret_key: str | None`, `adls_account`, `adls_container`, `adls_endpoint_url: str | None`, `adls_account_key: str | None`, `metrics_port`.

`S3ObjectStore.__init__`: if `client` is None, `boto3.client("s3", region_name=..., endpoint_url=... or omit, aws_access_key_id=... only if access_key)`. `put` → `put_object`.

`AdlsObjectStore`: if `file_client_for` is None, build `DataLakeServiceClient` from account URL `https://{account}.dfs.core.windows.net` or `adls_endpoint_url`, credential = account key string or `DefaultAzureCredential()`. `put` → `get_file_system_client(container).get_file_client(path).upload_data(parquet_bytes, overwrite=True)`.

`object_store_from_config`: `s3` vs `adls`; raise `ValueError` on anything else.

`records_to_parquet`: pyarrow table with `time` as timestamp tz UTC, `topic` string, `payload` string (`json.dumps`). Return `BytesIO` bytes.

`HistoricEventBatch`: first `add` sets `_started_at`. `should_flush` if records and (bytes >= max or clock() - started >= interval). Empty batch never flushes.

Add `settings.yaml` `datalake:` block from the spec (Task 5 will also set Compose env). Adding settings here unblocks `from_settings` tests.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./14_uns_datalake/test ./00_uns_config/test/test_datalake.py -q --tb=line`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 14_uns_datalake pyproject.toml uv.lock conf/settings.yaml
git commit -m "feat(datalake): Parquet batch and S3/ADLS object-store adapters."
```

---

### Task 4: Consumer loop, metrics, health

**Files:**
- Create: `14_uns_datalake/src/uns_datalake/mapper.py`
- Create: `14_uns_datalake/src/uns_datalake/metrics.py`
- Create: `14_uns_datalake/src/uns_datalake/health_check.py`
- Create: `14_uns_datalake/src/uns_datalake/main.py`
- Create: `14_uns_datalake/test/test_mapper.py`
- Create: `14_uns_datalake/test/test_health_check.py`
- Modify: `14_uns_datalake/pyproject.toml` scripts: `uns_datalake`, `uns_datalake_health`

**Interfaces:**
- Consumes: `parse_envelope`, `historic_event_object_path`, `new_flush_id`, `records_to_parquet`, `HistoricEventBatch`, `ObjectStore`
- Produces: `flush_batch(batch, store, consumer, metrics) -> None`; `handle_message(msg, batch, store, consumer, metrics)`; `run_forever(...)` used by `main`

Copy health check from `12_uns_oee/src/uns_oee/health_check.py` with `HEALTH_SERIES = "uns_datalake_up"`. Metrics: Counter flushes, skips, put_errors; Gauge `uns_datalake_up` = 1; Gauge last put unix time. `start_http_server(metrics_port)`.

- [ ] **Step 1: Write the failing tests**

`test_mapper.py` — fake Kafka message objects:

```python
from unittest.mock import Mock
from uns_config.datalake import FakeObjectStore
from uns_datalake.batch import HistoricEventBatch
from uns_datalake.mapper import handle_message, flush_batch
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


class FakeMsg:
    def __init__(self, value, error=None):
        self._value = value
        self._error = error
    def value(self):
        return self._value
    def error(self):
        return self._error


def test_valid_envelope_put_then_commit(tmp_path: Path):
    store = FakeObjectStore(tmp_path)
    consumer = Mock()
    metrics = Mock()
    batch = HistoricEventBatch(interval_seconds=0, max_bytes=10_000_000, clock=lambda: datetime.now(UTC))
    body = json.dumps({"time": "2026-09-08T12:00:00+00:00", "topic": "Acme/Line/Temp", "payload": {"v": 1}})
    handle_message(FakeMsg(body.encode()), batch, store, consumer, metrics)
    # interval 0 → should_flush after add
    assert any(tmp_path.rglob("*.parquet"))
    consumer.commit.assert_called()
    metrics.record_flush.assert_called()


def test_put_failure_does_not_commit(tmp_path: Path):
    store = Mock()
    store.put.side_effect = RuntimeError("minio down")
    consumer = Mock()
    metrics = Mock()
    batch = HistoricEventBatch(interval_seconds=0, max_bytes=1, clock=lambda: datetime.now(UTC))
    body = json.dumps({"time": "2026-09-08T12:00:00+00:00", "topic": "t", "payload": {"v": 1}})
    handle_message(FakeMsg(body.encode()), batch, store, consumer, metrics)
    consumer.commit.assert_not_called()
    metrics.record_put_error.assert_called()
    assert len(batch.take()) == 1


def test_poison_commits_without_put(tmp_path: Path):
    store = Mock()
    consumer = Mock()
    metrics = Mock()
    batch = HistoricEventBatch(interval_seconds=3600, max_bytes=10_000_000, clock=lambda: datetime.now(UTC))
    handle_message(FakeMsg(b"nope"), batch, store, consumer, metrics)
    store.put.assert_not_called()
    consumer.commit.assert_called()
    metrics.record_skip.assert_called()


def test_two_flushes_two_object_keys(tmp_path: Path):
    store = FakeObjectStore(tmp_path)
    consumer = Mock()
    metrics = Mock()
    t0 = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    now = t0
    batch = HistoricEventBatch(interval_seconds=60, max_bytes=10_000_000, clock=lambda: now)
    body = json.dumps({"time": "2026-09-08T12:00:00+00:00", "topic": "Acme/Line/Temp", "payload": {"v": 1}})
    handle_message(FakeMsg(body.encode()), batch, store, consumer, metrics)
    now = t0 + timedelta(seconds=61)
    handle_message(FakeMsg(body.encode()), batch, store, consumer, metrics)
    paths = list(tmp_path.rglob("*.parquet"))
    assert len(paths) >= 2
    assert len({p.name for p in paths}) >= 2
```

If `interval_seconds=0` is too sharp, flush explicitly in the first test via `flush_batch` after `add` instead of inside `handle_message`. Then `handle_message` only adds / poison-commits; `run_forever` decides flush. That is cleaner:

- `handle_message`: poison → skip+commit; else `batch.add(record, kafka_msg=msg)` then if `should_flush`: `flush_batch`
- `flush_batch`: parquet, `put`, on success `consumer.commit()` (sync, the stored messages) and `batch.take()`; on failure leave batch, `record_put_error`

Keep kafka messages on the batch (`add` stores `(record, msg)`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./14_uns_datalake/test/test_mapper.py -v`

Expected: FAIL — `mapper` missing.

- [ ] **Step 3: Implement**

`flush_batch`: if no records, return. `flush_id = new_flush_id()`. Path from **first** record’s `time` and first record’s `topic` (one file per flush; 60s batches almost never span topics — still use first topic in the filename even if mixed; rows inside keep their own topic column). `put` then commit each stored kafka msg (or `consumer.commit(asynchronous=False)` if the API commits the current assignment — prefer committing the specific messages you flushed). Clear batch only after success.

`run_forever`: `poll(0.5)`; None → maybe time-based `flush_batch`; else `handle_message`. Loop until `stop` event for tests.

`main`: `DatalakeConfig.from_settings()`, metrics server, `object_store_from_config`, `Consumer({bootstrap.servers, group.id, enable.auto.commit: False, auto.offset.reset: earliest})`, subscribe `[config.kafka_topic]`, `run_forever`.

Do **not** import `uns_mqtt`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./14_uns_datalake/test -q --tb=line`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 14_uns_datalake
git commit -m "feat(datalake): consume uns.historic-events and put Parquet after flush."
```

---

### Task 5: Compose MinIO, secrets, Prometheus, Dockerfile

**Files:**
- Create: `14_uns_datalake/Dockerfile` (python **slim**, not alpine — pyarrow wheels; install `librdkafka1` from apt. Copy only `00_uns_config` + `14_uns_datalake`. `uv sync --frozen --no-group test --compile-bytecode` and `uv run --frozen --no-sync` like OEE)
- Create: `14_uns_datalake/test/test_deployment.py` (copy `12_uns_oee/test/test_deployment.py`: service `datalake_mapper`, job `uns_datalake`, port 9096 unpublished, prometheus depends_on mapper, **no** `profiles` on minio or mapper, Azurite string absent from compose)
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml` only if prometheus `depends_on` is reset there — add `datalake_mapper`, do **not** add Azurite
- Modify: `08_uns_observability/prometheus/prometheus.yml`
- Modify: `00_uns_config/src/uns_config/compose_env.py` and `00_uns_config/test/test_compose_env.py`
- Modify: `conf/.secrets_template.yaml`
- Modify: `conf/settings.yaml` (datalake block if not already added in Task 3)

**Interfaces:**
- Produces: compose services `uns_minio`, `minio_init`, `datalake_mapper`; env `UNS_datalake__s3__access_key` / `UNS_datalake__s3__secret_key` from `datalake.s3.access_key` / `secret_key` in secrets

- [ ] **Step 1: Write the failing tests**

Deployment tests as above. Extend `test_compose_environment_reads_secrets_yaml` expected dict with the two MinIO keys; add those keys to every `_write_conf` secrets fixture in that file or tests that currently pass will fail when keys become required.

Also assert compose `uns_minio` has no `ports:` (unpublished) and no `profiles`. Assert `"azurite" not in COMPOSE_FILE.read_text().lower()`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./14_uns_datalake/test/test_deployment.py ./00_uns_config/test/test_compose_env.py -v`

Expected: FAIL — services / secrets missing.

- [ ] **Step 3: Implement**

`compose_environment`: require `datalake.s3.access_key` and `datalake.s3.secret_key` (same placeholder rejection). Map:

```
UNS_datalake__s3__access_key
UNS_datalake__s3__secret_key
```

Add them to `COMPOSE_ENV_KEYS`. Document in the docstring: MinIO root user. Production AWS does not need these when using instance role (local Compose still does).

`.secrets_template.yaml`:

```yaml
  datalake:
    s3:
      access_key: "#<minio root user / AWS access key>"
      secret_key: "#<minio root password / AWS secret key>"
```

`docker-compose.yml` (place near `kafka_mapper_client`):

```yaml
  uns_minio:
    image: minio/minio:latest
    command: ["server", "/data"]
    environment:
      MINIO_ROOT_USER: ${UNS_datalake__s3__access_key}
      MINIO_ROOT_PASSWORD: ${UNS_datalake__s3__secret_key}
    volumes:
      - uns_minio_data:/data
    healthcheck:
      test: ["CMD-SHELL", "timeout 2 bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/9000' || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 10s

  minio_init:
    image: minio/mc:latest
    depends_on:
      uns_minio:
        condition: service_healthy
    environment:
      MINIO_ROOT_USER: ${UNS_datalake__s3__access_key}
      MINIO_ROOT_PASSWORD: ${UNS_datalake__s3__secret_key}
    entrypoint:
      - /bin/sh
      - -c
      - mc alias set local http://uns_minio:9000 "$$MINIO_ROOT_USER" "$$MINIO_ROOT_PASSWORD" && mc mb --ignore-existing local/uns-historic-events
    restart: "no"

  datalake_mapper:
    build:
      context: .
      dockerfile: ./14_uns_datalake/Dockerfile
    volumes:
      - ./conf:/app/conf
    environment:
      UNS_CONF_DIR: /app/conf
      UNS_MODULE: 14_uns_datalake
      UNS_kafka__config: '@json {"client.id": "uns_datalake", "group.id": "uns_datalake", "bootstrap.servers": "uns_kafka_broker:29092", "enable.auto.commit": false, "auto.offset.reset": "earliest"}'
      UNS_datalake__s3__access_key: ${UNS_datalake__s3__access_key}
      UNS_datalake__s3__secret_key: ${UNS_datalake__s3__secret_key}
    depends_on:
      uns_kafka_broker:
        condition: service_healthy
      minio_init:
        condition: service_completed_successfully
```

If MinIO's image has no bash, switch the healthcheck to whatever binary it ships (`mc ready` after a local alias, or the image's documented `health/live` curl). The deployment test only asserts a `healthcheck` key exists.

Add volume `uns_minio_data` next to the other named volumes.

Prometheus job:

```yaml
  - job_name: uns_datalake
    static_configs:
      - targets: ["datalake_mapper:9096"]
```

Add `datalake_mapper` to `uns_prometheus.depends_on`. If `docker-compose.dev.yml` resets that list, add it there too (and still omit `opcua_client` if the live-apply profile work already removed it).

`datalake_mapper` does not `depends_on` `kafka_mapper_client` (envelope can be empty).

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./14_uns_datalake/test ./00_uns_config/test/test_compose_env.py ./00_uns_config/test/test_hivemq_edge_stack.py -q --tb=line`

Expected: PASS. `uv lock` in `14_uns_datalake` and repo root if Docker `--frozen` needs it.

- [ ] **Step 5: Commit**

```bash
git add 14_uns_datalake docker-compose.yml docker-compose.dev.yml 08_uns_observability/prometheus/prometheus.yml 00_uns_config/src/uns_config/compose_env.py 00_uns_config/test/test_compose_env.py conf/.secrets_template.yaml conf/settings.yaml pyproject.toml uv.lock
git commit -m "chore(compose): run datalake Mapper and MinIO on the default stack."
```

---

### Task 6: Docs and spec path number

**Files:**
- Create: `14_uns_datalake/README.md`
- Modify: `06_uns_kafka/README.md` — after the mapping-logic section, add: Historic Events are **also** produced to `uns.historic-events` (JSON `{time,topic,payload}`, key = MQTT topic). Dotted topics remain.
- Modify: `docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md` — replace `13_uns_datalake` with `14_uns_datalake`

- [ ] **Step 1: Write README**

`14_uns_datalake/README.md`: this is a **Mapper**. Default `uns_compose up` writes Parquet to MinIO. Point at AWS by clearing `datalake.s3.endpoint_url` and using instance role. Point at ADLS with `datalake.backend: adls`. Condition Monitoring does not read the lake. Manual check: publish one MQTT Historic Event, `docker exec` MinIO/`mc ls local/uns-historic-events/dt=`.

- [ ] **Step 2: Spec module number**

Replace `13_uns_datalake` with `14_uns_datalake` in the mapper spec (and `UNS_MODULE`).

- [ ] **Step 3: Run a quick grep**

Run: `uv run pytest ./14_uns_datalake/test ./00_uns_config/test/test_datalake.py ./06_uns_kafka/test/test_kafka_handler.py::test_produce_raw_does_not_convert_slashes -q --tb=line`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add 14_uns_datalake/README.md 06_uns_kafka/README.md docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md
git commit -m "docs(datalake): MinIO default and 14_ module path."
```

**Manual check (not a pytest gate):** `uv run uns_compose up -d --build`, publish one Historic Event to MQTT, list `dt=` in MinIO. Fill `conf/.secrets.yaml` datalake keys from the template first or Compose interpolation fails.

---

## Self-review

| Spec requirement | Task |
| --- | --- |
| Envelope `uns.historic-events` + keep dotted topics | 2 |
| Mapper Kafka-only, no MQTT | 4 |
| One backend s3 \| adls | 3 |
| MinIO + mapper always on; Azurite absent | 5 |
| Keys local; AWS chain / DefaultAzureCredential prod | 3, 5 |
| `dt=YYYY-MM-DD/` columns time, topic, payload | 1, 3 |
| Flush 60s / 8MiB | 3, 4 |
| Commit after put; poison skip+commit | 4 |
| No live cloud in pytest | 1–5 |
| 13_ taken → 14_uns_datalake | 3, 6 |
| Condition Monitoring unchanged | (not touched) |
