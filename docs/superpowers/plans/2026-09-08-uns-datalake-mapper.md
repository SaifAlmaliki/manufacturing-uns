# Historic Event lake Mapper Implementation Plan

> **Planning update (2026-09-09):** For the coordinated development cutover, use
> [UNS scalability foundation](./2026-09-09-uns-scalability-foundation.md).
> The new plan replaces this plan's dotted-topic dual write, three-column event
> contract, poison-record skipping and per-MQTT-topic object layout. The original
> steps below remain historical/reference material and must not be executed as a
> competing implementation of the scalability enhancement.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kafka_mapper` also produces envelope topic `uns.historic-events`; a new Mapper writes date-partitioned Parquet to MinIO (default), AWS S3, or Azure ADLS.

**Architecture:** Keep dotted Kafka topics. Add a literal-topic produce for the envelope. `00_uns_config.datalake` owns layout, record, fake store, and envelope JSON. `14_uns_datalake` consumes the envelope, flushes Parquet, and `put`s via one backend. Default Compose always starts MinIO + `datalake_mapper`.

**Tech Stack:** confluent-kafka, pyarrow, boto3, `azure-storage-file-datalake`, prometheus-client, pytest, Docker Compose, MinIO.

**Spec:** `docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md`

**Revision:** 2026-09-09 readiness review. Preserve the six-task scope. Delivery is at-least-once **from the envelope Kafka topic to the lake**: duplicates after failures are acceptable; committing past an unpersisted valid event is not. The two MQTT-to-Kafka produces are not transactional; do not claim end-to-end exactly-once or lossless MQTT delivery.

## Global Constraints

- **Envelope Kafka topic (verbatim):** `uns.historic-events`
- **Keep 1:1 dotted topics.** `convert_mqtt_kafka_topic` stays `/` → `.`
- **Lake Mapper never imports MQTT** and never subscribes to the broker
- **One backend per plant:** `datalake.backend` is `s3` or `adls`. Never dual-write
- **Default Compose:** MinIO + `datalake_mapper` always on (no `profiles`). Azurite absent
- **Default settings:** `backend: s3`, `s3.endpoint_url: http://uns_minio:9000`, bucket `uns-historic-events`
- **Parquet columns:** `("time", "topic", "payload")` only. `payload` is JSON text of the object. No Enrichment
- **Layout:** `dt=YYYY-MM-DD/<topic_safe>-<flush_id>.parquet` with `/` → `_`
- **Flush:** 60s or 8388608 estimated serialized bytes, whichever first; group each frozen flush by `(UTC event date, MQTT topic)`. Every row must match its object's date partition.
- **Offsets:** `enable.auto.commit: false`, `enable.auto.offset.store: false`. Commit explicit per-partition next offsets synchronously only after **all** valid records in the frozen flush have been uploaded. Poison records carry offset markers but no Parquet row; defer their commits behind buffered valid records. Never call bare `consumer.commit()`.
- **Bounded failure recovery:** freeze the batch and pause consumption during uploads/retries; keep polling for group callbacks. Retry an upload at most three attempts with 1s then 2s backoff. Commit failure or ownership loss exits without advancing unsafe offsets; Kafka replays. Task 4 defines shutdown and retry state precisely.
- **Auth:** local `minio.root_user` / `minio.root_password` are separate from optional `datalake.s3.access_key` / `secret_key`. AWS defaults to its credential chain; ADLS to `DefaultAzureCredential`. Local MinIO credentials are selected only for the exact default MinIO endpoint.
- **No live AWS/Azure/MQTT in pytest.** Stub S3/ADLS clients. Fake Kafka for the Mapper
- **Module directory is `14_uns_datalake`.** `13_uns_factory_agent` already exists. Compose service remains `datalake_mapper`.
- **Cloud SDKs live in `14_uns_datalake`, not `uns_config`.** `uns_config.datalake` is types/path/fake/envelope so GraphQL does not grow boto3. The linked spec is aligned with this seam.
- **`uns_config` must not import `uns_datalake`**
- **Do not implement on `main`.** Branch `feat/uns-datalake-mapper` from current `main`
- **Offline verification:** all pytest commands below are unit checks; commands covering existing Kafka tests explicitly use `-m "not integrationtest"`. Markers alone do not skip network tests. Patch SDK constructors as well as `put` clients.
- **Commits:** the commit steps are execution checkpoints; run them only when the user explicitly authorizes commits. This document revision does not authorize implementation or commits.

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
14_uns_datalake/src/uns_datalake/checkpoint.py
14_uns_datalake/src/uns_datalake/stores.py
14_uns_datalake/src/uns_datalake/metrics.py
14_uns_datalake/src/uns_datalake/health_check.py
14_uns_datalake/src/uns_datalake/mapper.py
14_uns_datalake/src/uns_datalake/main.py
14_uns_datalake/test/test_config.py
14_uns_datalake/test/test_parquet.py
14_uns_datalake/test/test_batch.py
14_uns_datalake/test/test_checkpoint.py
14_uns_datalake/test/test_stores.py
14_uns_datalake/test/test_mapper.py
14_uns_datalake/test/test_health_check.py
14_uns_datalake/test/test_deployment.py

pyproject.toml
docker-compose.yml
docker-compose.dev.yml
08_uns_observability/prometheus/prometheus.yml
docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md
docs/superpowers/specs/2026-09-08-uns-edge-opcua-datalake-design.md
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
    payload = {"timestamp": 1788868800000, "value": 1.2}
    env = build_envelope("Acme/Line/Temp", payload, timestamp_key="timestamp", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert env["topic"] == "Acme/Line/Temp"
    assert env["payload"] == payload
    assert env["time"] == "2026-09-08T12:00:00+00:00"


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

The fixture `1788868800000` ms is `2026-09-08T12:00:00Z`. Add the following validation tests in the same file:

```python
import pytest


@pytest.mark.parametrize("raw", [None, "", "bad-date", True, float("nan"), float("inf"), 10**100])
def test_invalid_timestamp_falls_back_to_clock(raw):
    now = datetime(2026, 9, 8, 12, tzinfo=UTC)
    assert build_envelope("t", {"timestamp": raw}, timestamp_key="timestamp", now=now)["time"] == now.isoformat()


def test_offset_timestamp_is_normalized_to_utc():
    env = build_envelope("t", {"timestamp": "2026-09-09T00:30:00+02:00"}, timestamp_key="timestamp", now=datetime.now(UTC))
    assert env["time"] == "2026-09-08T22:30:00+00:00"


@pytest.mark.parametrize("raw", [None, b"null", b"[]", b'{"time":"bad","topic":"t","payload":{}}'])
def test_tombstone_and_invalid_envelopes_are_poison(raw):
    assert parse_envelope(raw) is None
```

Timestamp contract: numbers are epoch seconds below absolute `1e11`, milliseconds otherwise; booleans, non-finite/out-of-range numbers and malformed strings fall back to the supplied clock. Naive datetimes mean UTC. Envelope timestamps are normalized to UTC; malformed envelope times are poison, not replaced on consumption. Empty topics are poison. Log invalid source timestamps without logging the payload.

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
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

ENVELOPE_TOPIC = "uns.historic-events"
HISTORIC_EVENT_COLUMNS = ("time", "topic", "payload")
LOGGER = logging.getLogger(__name__)


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
    return f"{stamp}-{uuid.uuid4().hex}"


def historic_event_object_path(*, event_time: datetime, topic: str, flush_id: str) -> str:
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    day = event_time.astimezone(UTC).date().isoformat()
    return f"dt={day}/{topic_safe(topic)}-{flush_id}.parquet"


def _to_iso8601_utc(raw: Any, *, now: datetime) -> str:
    def normalize(value: datetime) -> str:
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()

    try:
        if isinstance(raw, datetime):
            instant = raw
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("non-finite timestamp")
            instant = datetime.fromtimestamp(value / 1000 if abs(value) >= 1e11 else value, UTC)
        elif isinstance(raw, str) and raw:
            instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            if raw is not None:
                LOGGER.warning("Invalid source timestamp type; using mapper clock")
            instant = now
        return normalize(instant)
    except (ValueError, OverflowError, OSError):
        LOGGER.warning("Invalid source timestamp value; using mapper clock")
        return normalize(now)


def build_envelope(
    mqtt_topic: str,
    payload: dict[str, Any],
    *,
    timestamp_key: str,
    now: datetime,
) -> dict[str, Any]:
    raw = payload.get(timestamp_key) if isinstance(payload, dict) else None
    return {"time": _to_iso8601_utc(raw, now=now), "topic": mqtt_topic, "payload": payload}


def parse_envelope(raw: bytes | None) -> HistoricEventRecord | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    time_raw, topic, payload = data.get("time"), data.get("topic"), data.get("payload")
    if not isinstance(time_raw, str) or not isinstance(topic, str) or not topic or not isinstance(payload, dict):
        return None
    try:
        when = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        when = when.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
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

Use `produce(topic, value, key=key, callback=self.delivery_callback)` as shown in Step 3.

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
    payload = {"timestamp": 1788868800000, "value": 1.2}
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

Run: `uv run pytest ./06_uns_kafka/test/test_kafka_handler.py ./06_uns_kafka/test/test_uns_kafka_listner.py ./06_uns_kafka/test/test_kafka_config.py -m "not integrationtest" -q --tb=line`

Expected: PASS; broker integration tests are deselected by the explicit marker expression.

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

Copy `12_uns_oee/pyproject.toml` packaging structure, replacing OEE's runtime/test dependencies and sources (do not copy its historian/model dependencies). Package name `uns_datalake`. Dependencies: `uns_config`, `confluent-kafka>=2.14.0,<3`, `pyarrow>=22,<23`, `boto3>=1.35,<2`, `azure-storage-file-datalake>=12,<13`, `azure-identity>=1.19,<2`, `prometheus-client>=0.21.0,<1`, `dynaconf~=3.2`. Test dependencies: pytest, pytest-timeout, pytest-xdist, pyyaml. Local source: `uns_config = { path = "../00_uns_config", editable = true }`. Scripts come in Task 4. Resolve on Python 3.14 and verify the Linux slim image in Task 5; a missing compatible wheel is a failed build gate, not permission to silently change the range.

After creating pyproject: from repo root `uv lock` so the workspace picks it up.

- [ ] **Step 1: Write the failing tests**

`14_uns_datalake/test/test_parquet.py`:

```python
import json
from io import BytesIO

import pyarrow.parquet as pq

from uns_config.datalake import HISTORIC_EVENT_COLUMNS, HistoricEventRecord
from uns_datalake.parquet import records_to_parquet
from datetime import UTC, datetime


def test_parquet_columns_and_payload_json():
    records = [
        HistoricEventRecord(datetime(2026, 9, 8, tzinfo=UTC), "Acme/Line/Temp", {"value": 1.2}),
    ]
    data = records_to_parquet(records)
    assert isinstance(data, bytes)
    table = pq.read_table(source=BytesIO(data))
    assert tuple(table.column_names) == HISTORIC_EVENT_COLUMNS
    assert str(table.schema.field("time").type) == "timestamp[us, tz=UTC]"
    assert json.loads(table.column("payload")[0].as_py()) == {"value": 1.2}
```

`14_uns_datalake/test/test_batch.py`:

```python
from datetime import UTC, datetime

from uns_config.datalake import HistoricEventRecord
from uns_datalake.batch import HistoricEventBatch


def test_flush_on_max_bytes():
    batch = HistoricEventBatch(interval_seconds=3600, max_bytes=50, clock=lambda: 0.0)
    record = HistoricEventRecord(datetime.now(UTC), "t", {"x": "y" * 40})
    batch.add(record)
    assert batch.should_flush() is True


def test_flush_on_interval():
    start = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    now = 0.0
    batch = HistoricEventBatch(interval_seconds=60, max_bytes=10_000_000, clock=lambda: now)
    batch.add(HistoricEventRecord(start, "t", {"v": 1}))
    assert batch.should_flush() is False
    now = 61.0
    assert batch.should_flush() is True


def test_take_clears():
    batch = HistoricEventBatch(interval_seconds=1, max_bytes=10, clock=lambda: 0.0)
    batch.add(HistoricEventRecord(datetime.now(UTC), "t", {"v": 1}))
    taken = batch.take()
    assert len(taken) == 1
    assert batch.take() == []
```

Size estimate: `len(json.dumps(payload).encode("utf-8")) + len(topic.encode("utf-8")) + 64` per add, so 50-byte max_bytes with a large payload flushes. Count bytes rather than Unicode code points.

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


def test_factory_picks_backend(monkeypatch):
    boto_client = Mock()
    azure_client = Mock()
    credential = Mock()
    monkeypatch.setattr("uns_datalake.stores.boto3.client", boto_client)
    monkeypatch.setattr("uns_datalake.stores.DataLakeServiceClient", azure_client)
    monkeypatch.setattr("uns_datalake.stores.DefaultAzureCredential", credential)
    s3 = object_store_from_config(DatalakeConfig(backend="s3", s3_bucket="b", s3_region="r", s3_endpoint_url=None))
    assert isinstance(s3, S3ObjectStore)
    azure_client.assert_not_called()
    assert "aws_access_key_id" not in boto_client.call_args.kwargs
    adls = object_store_from_config(DatalakeConfig(backend="adls", adls_account="a", adls_container="c"))
    assert isinstance(adls, AdlsObjectStore)
    credential.assert_called_once()
    assert boto_client.call_count == 1
```

`14_uns_datalake/test/test_config.py`: construct `DatalakeConfig(...)` with defaults matching the spec (backend s3, topic uns.historic-events, group uns_datalake, interval 60, max_bytes 8388608, bucket uns-historic-events, endpoint http://uns_minio:9000, metrics_port 9096). A `from_settings` test can use `monkeypatch` + tmp conf like `test_compose_env`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./14_uns_datalake/test -v`

Expected: FAIL — package missing.

- [ ] **Step 3: Implement**

`DatalakeConfig`: frozen dataclass, `from_settings` via `get_settings("datalake")`. Read the block from `settings.get("datalake")`, inherited from `default.datalake`; do not confuse the Dynaconf environment with the nested block. Fields: `backend`, `kafka_topic`, `group_id`, `bootstrap_servers` (read `settings.get("kafka.config", {}).get("bootstrap.servers", "localhost:9092")`; the Kafka key contains a literal dot), `interval_seconds`, `max_bytes`, `max_records` (10000), `max_record_bytes` (1048576 raw envelope bytes), `s3_bucket`, `s3_region`, `s3_endpoint_url: str | None`, `s3_access_key: str | None`, `s3_secret_key: str | None`, `adls_account`, `adls_container`, `adls_endpoint_url: str | None`, `adls_account_key: str | None`, `metrics_port`.

Normalize empty endpoint/key strings to `None`. Reject unsupported backend, nonpositive byte/count limits, negative interval, out-of-range port, partial S3 key pairs, missing selected S3 bucket or ADLS account/container **before** constructing SDKs. Unused backend settings are ignored. Zero interval remains supported for deterministic tests.

Credential selection in `from_settings`: explicit `datalake.s3` key pair wins; otherwise use `minio.root_user` / `minio.root_password` only when the normalized endpoint is exactly `http://uns_minio:9000`; otherwise leave credentials unset. Missing MinIO keys for that endpoint fail validation. `compose_environment` only requires/exports the separate MinIO pair. Add these concrete cases to `test_config.py` using temporary settings/secrets and clearing `get_settings.cache_clear()` before/after each case:

| Endpoint / secrets | Required result |
| --- | --- |
| Default MinIO + MinIO root pair | Select root pair for local adapter |
| Empty endpoint + MinIO root pair only | Both mapper S3 keys `None` (AWS chain) |
| Empty endpoint + explicit S3 pair | Select explicit pair |
| Non-MinIO custom endpoint + only MinIO pair | Do not forward local root credentials |
| Half an explicit S3 pair | `ValueError` |
| ADLS selected + empty account | `ValueError`, no SDK constructors |
| `UNS_kafka__config` JSON with `bootstrap.servers` | Exact configured host, not localhost fallback |

`S3ObjectStore.__init__`: if `client` is None, `boto3.client("s3", region_name=..., endpoint_url=... or omit, aws_access_key_id=... and aws_secret_access_key=... only for a complete pair, config=Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}))` using `botocore.config.Config`. `put` → `put_object`. SDK retries are disabled; Task 4 owns attempt counts.

`AdlsObjectStore`: if `file_client_for` is None, build `DataLakeServiceClient` from account URL `https://{account}.dfs.core.windows.net` or `adls_endpoint_url`, credential = account key string or `DefaultAzureCredential()`, transport timeouts `connection_timeout=5`, `read_timeout=10`, `retry_total=0`. `put` → `get_file_system_client(container).get_file_client(path).upload_data(parquet_bytes, overwrite=True, max_concurrency=1)`. The container must already exist. Each retry uses the same frozen key and bytes; consumers must tolerate a partially created ADLS file until an upload succeeds. This slice does not promise atomic publication to concurrent lake readers.

`object_store_from_config`: `s3` vs `adls`; raise `ValueError` on anything else.

`records_to_parquet(records: Sequence[HistoricEventRecord]) -> bytes`: explicit schema `pa.schema([("time", pa.timestamp("us", tz="UTC")), ("topic", pa.string()), ("payload", pa.string())])`; payload is `json.dumps(record.payload)`. Write the table to `BytesIO`, return `buffer.getvalue()`. Empty records return a valid empty table with the same schema. The mapper never uploads an empty group.

`HistoricEventBatch`: constructor takes `interval_seconds`, `max_bytes`, `clock`, `max_records=10000`. First `add(record)` sets `_started_at`. `should_flush()` if records and (estimated serialized UTF-8 bytes >= max, record count >= max_records, or elapsed >= interval). `snapshot() -> tuple[HistoricEventRecord, ...]` is nondestructive. `take()` clears records, byte count and start time only after the mapper's commit succeeds. Runtime and tests use an injected monotonic clock (float seconds). Record event times remain UTC datetimes. Never retain Kafka messages in this class; `checkpoint.py` owns offset markers.

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
- Create: `14_uns_datalake/src/uns_datalake/checkpoint.py`
- Create: `14_uns_datalake/src/uns_datalake/metrics.py`
- Create: `14_uns_datalake/src/uns_datalake/health_check.py`
- Create: `14_uns_datalake/src/uns_datalake/main.py`
- Create: `14_uns_datalake/test/test_mapper.py`
- Create: `14_uns_datalake/test/test_checkpoint.py`
- Create: `14_uns_datalake/test/test_health_check.py`
- Modify: `14_uns_datalake/pyproject.toml` scripts: `uns_datalake`, `uns_datalake_health`

**Interfaces and ownership:**
- `checkpoint.py`: `Checkpoint.observe(topic, partition, offset)`, `next_offsets() -> list[TopicPartition]`, `clear()`. Track highest delivered offset + 1 per partition, not consumer positions. Offsets are safe to commit only when the mapper has persisted all buffered valid records; this class never commits by itself.
- `mapper.py`: `KafkaLakeMapper(consumer, store, config, metrics, *, clock=time.monotonic, serialize=records_to_parquet)`. Methods: `handle_message(msg)`, `flush_batch()`, `tick()`, `on_assign(consumer, partitions)`, `on_revoke(consumer, partitions)`, `on_lost(consumer, partitions)`, `close()`. `run_forever(mapper, stop)` calls `tick()` until stop, with `close()` in `finally`.
- `handle_message` validates input and records its offset; `flush_batch` freezes a batch and advances at most one upload/commit step per call. At the start of `tick`, freeze/pause if the collecting batch is due (including poison-only offsets), before another poll can deliver data. Then poll for callbacks and advance at most one upload/commit step, checking ownership again after poll. Production calls these on one thread.
- A frozen flush owns its records, grouped object keys, current upload index, retry attempt count, retry deadline, and explicit next offsets. No records enter it after freezing. Serialize one group at a time; retain its bytes only until success. Keep successful keys in that frozen flush so commit retry/recovery never invents a new key in the same process.

Health is explicit: `uns_datalake_up` measures loop liveness, `uns_datalake_ready` dependency readiness. Docker checks liveness, not readiness. `uns_datalake_ready=0` during upload failure/backoff, Kafka error, or before assignment; set 1 after assignment and when no dependency failure remains. The health CLI requires `uns_datalake_up == 1` and `0 <= now - uns_datalake_last_loop_timestamp_seconds < 60`. Do not copy OEE's metric-name-presence check. Metrics: `uns_datalake_flushes_total`, `uns_datalake_skips_total`, `uns_datalake_put_errors_total`, `uns_datalake_commit_errors_total`, `uns_datalake_last_put_timestamp_seconds`, `uns_datalake_last_loop_timestamp_seconds`. Unix time is used only for these exported timestamps; batch/retry scheduling remains monotonic. Fatal failure sets up=0 and exits nonzero; Compose `restart: on-failure` restarts the process. A healthy idle topic remains ready; no last-put freshness requirement.

- [ ] **Step 1: Write the failing tests**

`test_mapper.py` — use offset-aware fakes and an ordered side-effect log. The following helpers are part of the test file, not production abstractions:

```python
import json
from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock

import pyarrow.parquet as pq
import pytest
from confluent_kafka import TopicPartition
from uns_datalake.config import DatalakeConfig
from uns_datalake.mapper import KafkaLakeMapper


class FakeMsg:
    def __init__(self, value, offset, partition=0):
        self._value, self._offset, self._partition = value, offset, partition
    def value(self): return self._value
    def error(self): return None
    def topic(self): return "uns.historic-events"
    def partition(self): return self._partition
    def offset(self): return self._offset


def event(offset, *, partition=0, topic="Acme/Line/Temp", time="2026-09-08T12:00:00Z"):
    return FakeMsg(json.dumps({"time": time, "topic": topic, "payload": {"v": offset}}).encode(), offset, partition)


def harness(**overrides):
    log, objects, now = [], {}, [0.0]
    consumer, store, metrics = Mock(), Mock(), Mock()
    consumer.poll.return_value = None
    consumer.assignment.return_value = [TopicPartition("uns.historic-events", 0), TopicPartition("uns.historic-events", 1)]

    def put(key, data):
        log.append(("put", key))
        objects[key] = data

    def commit(*, offsets, asynchronous):
        assert asynchronous is False
        log.append(("commit", {(p.partition, p.offset) for p in offsets}))
        return offsets

    store.put.side_effect, consumer.commit.side_effect = put, commit
    config = replace(DatalakeConfig(), **overrides)
    mapper = KafkaLakeMapper(consumer, store, config, metrics, clock=lambda: now[0])
    mapper.on_assign(consumer, consumer.assignment())
    return mapper, consumer, store, metrics, log, objects, now


def finish_flush(mapper, consumer):
    before = consumer.commit.call_count
    for _ in range(20):
        mapper.flush_batch()
        if consumer.commit.call_count > before:
            return
    pytest.fail("flush did not reach commit")


def test_poison_cannot_commit_past_buffered_valid_event():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.handle_message(FakeMsg(b"bad-json", 11))
    consumer.commit.assert_not_called()
    finish_flush(mapper, consumer)
    assert [kind for kind, _ in log] == ["put", "commit"]
    assert log[-1][1] == {(0, 12)}


def test_poison_only_commits_without_object():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(FakeMsg(None, 7))
    mapper.tick()
    store.put.assert_not_called()
    assert log == [("commit", {(0, 8)})]


def test_mixed_dates_topics_and_partitions_put_before_explicit_commit():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10, time="2026-09-08T23:59:59Z"))
    mapper.handle_message(event(11, time="2026-09-09T00:00:01Z"))
    mapper.handle_message(event(40, partition=1, topic="Acme/Line/Pressure", time="2026-09-09T00:30:00+02:00"))
    finish_flush(mapper, consumer)
    assert len(objects) == 3
    assert log[-1] == ("commit", {(0, 12), (1, 41)})
    for key, data in objects.items():
        rows = pq.read_table(BytesIO(data)).to_pylist()
        assert len({row["topic"] for row in rows}) == 1
        assert all(key.startswith(f"dt={row['time'].date().isoformat()}/") for row in rows)


def test_second_object_failure_keeps_first_and_defers_all_offsets():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.handle_message(event(11, topic="z"))
    good_put = store.put.side_effect
    attempts = []

    def fail_second_once(key, data):
        attempts.append(key)
        if len(attempts) == 2:
            raise RuntimeError("store unavailable")
        good_put(key, data)

    store.put.side_effect = fail_second_once
    mapper.flush_batch()
    mapper.flush_batch()
    consumer.commit.assert_not_called()
    assert len(objects) == 1
    mapper.tick()  # still before retry deadline; must poll while paused
    assert len(attempts) == 2
    consumer.pause.assert_called()
    consumer.poll.assert_called()
    now[0] = 1.0
    finish_flush(mapper, consumer)
    assert attempts[1] == attempts[2]
    assert len(objects) == 2
    assert log[-1] == ("commit", {(0, 12)})


def test_commit_failure_exits_after_put_without_reupload():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()
    consumer.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        mapper.flush_batch()
    assert len(objects) == 1
    assert store.put.call_count == 1


def test_two_explicit_flushes_create_two_keys():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    finish_flush(mapper, consumer)
    mapper.handle_message(event(11))
    finish_flush(mapper, consumer)
    assert len(objects) == 2
    assert consumer.commit.call_count == 2
```

Add these additional failure tests before implementation; use the same harness and fake clock, never real sleeps:

```python
@pytest.mark.parametrize("callback", ["on_revoke", "on_lost"])
def test_ownership_loss_never_commits_buffered_data(callback):
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    getattr(mapper, callback)(consumer, consumer.assignment())
    with pytest.raises(RuntimeError):
        mapper.tick()
    consumer.commit.assert_not_called()


def test_retry_exhaustion_is_bounded_and_never_commits():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    store.put.side_effect = RuntimeError("store down")
    mapper.flush_batch()  # attempt 1, due at 1
    now[0] = 1.0
    mapper.tick()         # attempt 2, due at 3
    now[0] = 3.0
    with pytest.raises(RuntimeError):
        mapper.tick()     # attempt 3, fatal
    assert store.put.call_count == 3
    consumer.commit.assert_not_called()


def test_shutdown_abandons_uncommitted_batch_for_replay():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.close()
    store.put.assert_not_called()
    consumer.commit.assert_not_called()
    consumer.close.assert_called_once()


def test_idle_poll_flushes_after_interval():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.tick()
    store.put.assert_not_called()
    now[0] = 60.0
    mapper.tick()
    mapper.tick()
    assert log[-1] == ("commit", {(0, 11)})


def test_oversize_valid_envelope_exits_without_skipping():
    mapper, consumer, store, metrics, log, objects, now = harness(max_record_bytes=10)
    with pytest.raises(RuntimeError):
        mapper.handle_message(event(10))
    consumer.commit.assert_not_called()


def test_per_partition_commit_error_is_not_success():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()
    consumer.commit.side_effect = None
    consumer.commit.return_value = [Mock(error=RuntimeError("partition commit failed"))]
    with pytest.raises(RuntimeError):
        mapper.flush_batch()
    assert store.put.call_count == 1
```

`test_checkpoint.py`:

```python
import pytest
from uns_datalake.checkpoint import Checkpoint


def test_explicit_partition_next_offsets_and_clear():
    checkpoint = Checkpoint()
    checkpoint.observe("uns.historic-events", 0, 10)
    checkpoint.observe("uns.historic-events", 1, 40)
    checkpoint.observe("uns.historic-events", 0, 11)
    assert {(p.partition, p.offset) for p in checkpoint.next_offsets()} == {(0, 12), (1, 41)}
    checkpoint.clear()
    assert checkpoint.next_offsets() == []


def test_decreasing_offset_is_rejected():
    checkpoint = Checkpoint()
    checkpoint.observe("uns.historic-events", 0, 10)
    with pytest.raises(ValueError):
        checkpoint.observe("uns.historic-events", 0, 9)
```

Add to `test_mapper.py`:

```python
def test_serialization_failure_never_commits():
    mapper, consumer, store, metrics, log, objects, now = harness()
    broken = Mock(side_effect=ValueError("serialization failed"))
    mapper = KafkaLakeMapper(consumer, store, DatalakeConfig(), metrics, clock=lambda: now[0], serialize=broken)
    mapper.on_assign(consumer, consumer.assignment())
    mapper.handle_message(event(10))
    with pytest.raises(RuntimeError):
        mapper.flush_batch()
    store.put.assert_not_called()
    consumer.commit.assert_not_called()


def test_crash_after_put_replays_without_losing_event():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()  # upload, before commit
    mapper.close()
    consumer.commit.assert_not_called()
    replay = KafkaLakeMapper(consumer, store, DatalakeConfig(), metrics, clock=lambda: now[0])
    replay.on_assign(consumer, consumer.assignment())
    replay.handle_message(event(10))
    finish_flush(replay, consumer)
    assert len(objects) == 2
    rows = [row for data in objects.values() for row in pq.read_table(BytesIO(data)).to_pylist()]
    assert {json.loads(row["payload"])["v"] for row in rows} == {10}
    assert log[-1] == ("commit", {(0, 11)})


@pytest.mark.parametrize("limits", [{"max_bytes": 1}, {"max_records": 1}])
def test_size_or_count_threshold_pauses_before_more_data(limits):
    mapper, consumer, store, metrics, log, objects, now = harness(**limits)
    mapper.handle_message(event(10))
    mapper.tick()
    consumer.pause.assert_called_once()
    store.put.assert_called_once()
    mapper.tick()
    assert log[-1] == ("commit", {(0, 11)})


def test_unexpected_delivery_while_frozen_fails_closed():
    mapper, consumer, store, metrics, log, objects, now = harness()
    mapper.handle_message(event(10))
    mapper.flush_batch()
    consumer.poll.return_value = event(11)
    with pytest.raises(RuntimeError):
        mapper.tick()
    consumer.commit.assert_not_called()


def test_kafka_message_error_exits_without_commit():
    mapper, consumer, store, metrics, log, objects, now = harness()
    msg = Mock()
    msg.error.return_value.code.return_value = -1
    with pytest.raises(RuntimeError):
        mapper.handle_message(msg)
    consumer.commit.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./14_uns_datalake/test/test_mapper.py -v`

Expected: FAIL — `mapper` missing.

- [ ] **Step 3: Implement**

Implement this state machine; do not replace explicit commits with current assignment positions:

| State / event | Action / next state |
| --- | --- |
| Collecting, valid message | Reject raw values over `max_record_bytes` with fatal error before observing the offset. Otherwise parse, add valid record, observe offset. Thresholds are checked before another poll. |
| Collecting, poison/tombstone | Log topic/partition/offset and reason (no payload), increment skips, observe offset but add no row. If no valid records are buffered, next tick flushes offsets only. Otherwise wait for the existing batch's threshold. |
| Threshold or explicit flush | Snapshot records and offsets, pause the entire assignment, create one object per `(record.time.astimezone(UTC).date(), record.topic)` in sorted group order. Generate a **separate** `new_flush_id()` per group so slash/underscore filename collisions cannot overwrite another group. Freeze keys once. If there are no records or offset markers, return without pause, put, commit or resume. |
| Upload step | Serialize current group once and `store.put(key, bytes)`. Wrap serialization errors in fatal `RuntimeError` (no upload retry for them). On successful put record last-put time, advance group cursor and reset attempts for the next group; do not commit. On put failure keep current bytes/key, mark not ready, retry after 1s then 2s; third failure raises fatal runtime error. No sleep inside `flush_batch`. |
| Retry waiting | `tick` continues `poll(0.5)` for callbacks while paused, updates loop heartbeat, checks retry deadline. It never accumulates another batch. Any unexpected data message while frozen fails closed and restarts for replay. |
| All groups uploaded (or poison-only batch) | `consumer.commit(offsets=frozen_offsets, asynchronous=False)`. Inspect every returned `TopicPartition.error`; an exception or any partition error is fatal. Partial successful commits are safe because all rows were uploaded first. |
| Commit success | Clear records/checkpoint/frozen state, increment completed flushes only for a flush containing rows, restore readiness, resume current assignment. |
| Revoke/lost with pending offsets | Mark fatal/ownership invalid; subsequent tick/flush raises **before** any commit or resume. Abandon buffered data for replay. Do not flush or commit in the callback. With no pending offsets, update readiness/assignment normally. |
| Stop / SIGTERM / SIGINT | Stop consuming, set up/ready=0, abandon the uncommitted batch and close consumer. No shutdown flush or commit; replay is the recovery path. |

Set consumer configuration explicitly:

```python
consumer_config = {
    "bootstrap.servers": config.bootstrap_servers,
    "group.id": config.group_id,
    "enable.auto.commit": False,
    "enable.auto.offset.store": False,
    "auto.offset.reset": "earliest",
    "max.poll.interval.ms": 300000,
    "socket.timeout.ms": 10000,
    "queued.max.messages.kbytes": 16384,
}
```

Use classic/default group protocol and subscribe with assign/revoke/lost callbacks. Mark ownership invalid on a lost/revoked callback and check that flag both before an upload and before a commit. `_PARTITION_EOF` is benign; other message errors are fatal in this slice. Detect all-brokers-down/fatal client errors through `error_cb`, mark readiness false and exit the loop nonzero. `close()` is idempotent and runs in `finally`; auto commit remains disabled when closing.

Application buffering is bounded by `max_bytes` plus one accepted message, `max_records`, and one group's serialized Parquet bytes; reject oversized envelopes without skipping their offsets. The size is an accounting bound, not a promise about exact Python heap/RSS. Kafka client queue has a separate 16MiB target. A repeatedly oversized event intentionally requires an operator to raise the limit; no silent data loss. SDK timeouts/retry limits keep normal failed attempts below max poll interval; if assignment expires anyway, fail/replay rather than claim ownership. Do not introduce worker queues or a second consumer thread.

`main`: validate config first; create metrics registry/server, store, consumer, and mapper; register signals to set a stop event; subscribe then run. `metrics` methods used by the mapper are `record_flush()`, `record_skip()`, `record_put_error()`, `record_commit_error()`, `record_put_success()`, `set_up(bool)`, `set_ready(bool)`, and `record_loop()`.

`test_health_check.py`: use a stub opener and injected current Unix time. A body with `uns_datalake_up 1` and last-loop time 5s ago passes even when `uns_datalake_ready 0`; up=0, missing series, malformed sample, loop age >=60s, or HTTP failure fails. Assert an idle assigned consumer updates its loop heartbeat and remains ready without any upload.

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
- Create: `14_uns_datalake/Dockerfile` (`python:3.14-slim-bookworm`, not alpine — pyarrow wheels; install `librdkafka1` and `ca-certificates` from apt. Copy module manifest/lock/README/license/src into `/app` and `00_uns_config` into `/00_uns_config`, as required by the relative source dependency. Copy `conf/settings.yaml` into `/app/conf`. `uv sync --frozen --no-group test --compile-bytecode` and `uv run --frozen --no-sync --no-group test uns_datalake` like OEE. Use Debian `useradd`/`runuser`, not Alpine `adduser` flags. Health command is `uns_datalake_health`.)
- Create: `14_uns_datalake/test/test_deployment.py` (copy `12_uns_oee/test/test_deployment.py`: service `datalake_mapper`, job `uns_datalake`, port 9096 unpublished, prometheus depends_on mapper, **no** `profiles` on minio or mapper, Azurite string absent from compose)
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml` only if prometheus `depends_on` is reset there — add `datalake_mapper`, do **not** add Azurite
- Modify: `08_uns_observability/prometheus/prometheus.yml`
- Modify: `00_uns_config/src/uns_config/compose_env.py` and `00_uns_config/test/test_compose_env.py`
- Modify: `conf/.secrets_template.yaml`
- Modify: `conf/settings.yaml` (datalake block if not already added in Task 3)

**Interfaces:**
- Produces: compose services `uns_minio`, `minio_init`, `datalake_mapper`; interpolation env `UNS_minio__root_user` / `UNS_minio__root_password` from `minio.root_user` / `root_password` in secrets. Mapper reads its selected credentials from mounted config; no unconditional S3-key environment injection.

- [ ] **Step 1: Write the failing tests**

Deployment tests as above. Extend `test_compose_environment_reads_secrets_yaml` expected dict with `UNS_minio__root_user` and `UNS_minio__root_password`; add the separate `minio` pair to each valid `_write_conf` fixture. Test missing/placeholder rejection independently for both keys. No AWS keys are required by `compose_environment`.

Also assert compose `uns_minio` has no `ports:` (unpublished) and no `profiles`. Assert `"azurite" not in COMPOSE_FILE.read_text().lower()`.

Assert both MinIO services use the pinned image below, the health command invokes `curl` against `/minio/health/live`, the mapper has `restart: on-failure`, and its environment contains neither `UNS_datalake__s3__access_key` nor `UNS_datalake__s3__secret_key`. Assert the Dockerfile contains its executable health check. Static YAML tests do not substitute for the build/start gates in Step 4.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./14_uns_datalake/test/test_deployment.py ./00_uns_config/test/test_compose_env.py -v`

Expected: FAIL — services / secrets missing.

- [ ] **Step 3: Implement**

`compose_environment`: require `minio.root_user` and `minio.root_password` (same placeholder rejection). Map:

```
UNS_minio__root_user
UNS_minio__root_password
```

Add them to `COMPOSE_ENV_KEYS`. Document in the docstring: these initialize the always-on local MinIO service only. Production AWS can use its default chain even while local Compose still requires the MinIO pair. Do not export mapper S3 credentials in this helper.

`.secrets_template.yaml`:

```yaml
  minio:
    root_user: "#<local minio root user, at least 3 characters>"
    root_password: "#<local minio root password, at least 8 characters>"
  # Optional production static credentials; omit these for AWS role authentication.
  # datalake:
  #   s3:
  #     access_key: "#<AWS access key>"
  #     secret_key: "#<AWS secret key>"
```

`docker-compose.yml` (place near `kafka_mapper_client`):

```yaml
  uns_minio:
    image: minio/minio:RELEASE.2025-04-22T22-12-26Z
    command: ["server", "/data"]
    environment:
      MINIO_ROOT_USER: ${UNS_minio__root_user}
      MINIO_ROOT_PASSWORD: ${UNS_minio__root_password}
    volumes:
      - uns_minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "--fail", "--silent", "--max-time", "2", "http://127.0.0.1:9000/minio/health/live"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 10s

  minio_init:
    image: minio/minio:RELEASE.2025-04-22T22-12-26Z
    depends_on:
      uns_minio:
        condition: service_healthy
    environment:
      MINIO_ROOT_USER: ${UNS_minio__root_user}
      MINIO_ROOT_PASSWORD: ${UNS_minio__root_password}
    entrypoint:
      - /bin/sh
      - -c
      - mc alias set local http://uns_minio:9000 "$$MINIO_ROOT_USER" "$$MINIO_ROOT_PASSWORD" && mc mb --ignore-existing local/uns-historic-events
    restart: "no"

  datalake_mapper:
    restart: on-failure
    build:
      context: .
      dockerfile: ./14_uns_datalake/Dockerfile
    volumes:
      - ./conf:/app/conf
    environment:
      UNS_CONF_DIR: /app/conf
      UNS_MODULE: 14_uns_datalake
      UNS_kafka__config: '@json {"client.id": "uns_datalake", "group.id": "uns_datalake", "bootstrap.servers": "uns_kafka_broker:29092", "enable.auto.commit": false, "auto.offset.reset": "earliest"}'
    depends_on:
      uns_kafka_broker:
        condition: service_healthy
      minio_init:
        condition: service_completed_successfully
```

The pinned release's [Dockerfile.release](https://github.com/minio/minio/blob/RELEASE.2025-04-22T22-12-26Z/Dockerfile.release) copies both `curl` and `mc` into `/usr/bin`; use that same image for the initializer rather than a floating, independently versioned client. Verify the published image with the commands below. A pull/build/runtime failure blocks completion; do not substitute a speculative shell health check.

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

Expected: PASS. Generate both module and root locks deliberately (run `uv lock` with working directory `14_uns_datalake`, then `uv lock` at the root). Verify both frozen resolutions before building; Docker consumes the module lock.

- [ ] **Step 4a: Verify the actual image and mapper build**

Run from the root (these are required local deployment gates, outside pytest):

```bash
docker pull minio/minio:RELEASE.2025-04-22T22-12-26Z
docker run --rm --entrypoint curl minio/minio:RELEASE.2025-04-22T22-12-26Z --version
docker run --rm --entrypoint mc minio/minio:RELEASE.2025-04-22T22-12-26Z --version
uv run uns_compose build datalake_mapper
uv run uns_compose up -d uns_minio minio_init datalake_mapper
uv run uns_compose ps -a uns_minio minio_init datalake_mapper
```

Expected: binaries execute; frozen Python 3.14 build succeeds; MinIO and mapper become healthy; initializer exits 0. Run `uv run uns_compose exec datalake_mapper uv run --frozen --no-sync --no-group test uns_datalake_health` and expect exit 0. Credentials must be supplied in `conf/.secrets.yaml` by the operator; never copy actual secrets into tests/docs. If Docker or credentials are unavailable, record this gate as blocked rather than claiming deployment verified.

- [ ] **Step 5: Commit**

```bash
git add 14_uns_datalake docker-compose.yml docker-compose.dev.yml 08_uns_observability/prometheus/prometheus.yml 00_uns_config/src/uns_config/compose_env.py 00_uns_config/test/test_compose_env.py conf/.secrets_template.yaml conf/settings.yaml pyproject.toml uv.lock
git commit -m "chore(compose): run datalake Mapper and MinIO on the default stack."
```

---

### Task 6: Docs, contract alignment, and final verification

**Files:**
- Create: `14_uns_datalake/README.md`
- Modify: `06_uns_kafka/README.md` — after the mapping-logic section, add: Historic Events are **also** produced to `uns.historic-events` (JSON `{time,topic,payload}`, key = MQTT topic). Dotted topics remain.
- Verify: `docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md` — keep the revised offset, grouping, retry, health, and credential contracts aligned with implementation.
- Modify: `docs/superpowers/specs/2026-09-08-uns-edge-opcua-datalake-design.md` — explicitly link to this running-mapper slice as superseding the earlier types-only lake scope.
- Modify: `docs/superpowers/plans/2026-09-07-connectivity-edge-live-apply.md` — link the lake scope to this plan; do not duplicate lake implementation tasks.

- [ ] **Step 1: Write README**

`14_uns_datalake/README.md`: this is a **Mapper**. Default `uns_compose up` writes Parquet to MinIO. Explain at-least-once from Kafka, replay duplicates, UTC-date/topic grouping, deferred poison commits, bounded retries, shutdown replay, and liveness versus readiness. Condition Monitoring does not read the lake.

Include these exact production configuration examples as overlays under the existing `default:` environment:

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

The selected cloud destination must already exist and the process identity must have write access. Local Compose still starts MinIO and creates its default bucket; no dual-write occurs. Clearing the AWS endpoint while retaining only `minio.root_*` must select the AWS credential chain. If explicit `datalake.s3` keys existed previously, remove them to use the chain. Do not claim Azurite validates the ADLS Gen2 API.

- [ ] **Step 2: Verify cross-document contracts**

Confirm `14_uns_datalake` / `UNS_MODULE` and cloud adapters in the mapper package. Update the two predecessor docs listed above with links. The spec must say deferred safe poison commits, per-date/topic groups, bounded retries, replay on shutdown/ownership loss, explicit credential separation, and process liveness health checks. Do not revert these to the earlier immediate-commit or first-record-path wording.

- [ ] **Step 3: Run final offline regression checks**

Run: `uv run pytest ./14_uns_datalake/test ./00_uns_config/test ./06_uns_kafka/test -m "not integrationtest" -q --tb=line`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add 14_uns_datalake/README.md 06_uns_kafka/README.md docs/superpowers/specs/2026-09-08-uns-datalake-mapper-design.md docs/superpowers/specs/2026-09-08-uns-edge-opcua-datalake-design.md docs/superpowers/plans/2026-09-07-connectivity-edge-live-apply.md
git commit -m "docs(datalake): MinIO default and 14_ module path."
```

**Required local smoke check (outside pytest):** after Task 5's build/start gates, publish one Historic Event with a known UTC timestamp and topic through the existing MQTT tooling. Wait for the 60s flush and list the resulting date prefix using a fresh initializer container (its alias is not persisted by the earlier oneshot):

```bash
uv run uns_compose run --rm --entrypoint /bin/sh minio_init -c 'mc alias set local http://uns_minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" && mc ls --recursive local/uns-historic-events/'
```

Expect the event's UTC date and topic-safe filename. Download the resulting object with `mc cp` and inspect it with `pyarrow.parquet.read_table` to confirm `time`, `topic`, JSON payload, and the expected value. Repeat a mapper stop/start with an unflushed event and verify it appears after restart. Record object paths and results, not credentials. MinIO keys come from `minio.root_user` / `minio.root_password` in the local secrets file.

Before handoff, run `graphify update .` after implementation and review generated changes. Report offline tests, actual image/build checks, local smoke results, and any blocked gate separately; mocked tests do not establish live AWS/ADLS compatibility.

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
| Explicit safe offsets; poison cannot skip buffered valid rows | 4 |
| Mixed UTC dates/topics; partial multi-object upload failure | 4 |
| Retry bounds, pause, ownership loss, commit errors, shutdown replay | 3, 4 |
| Correct timestamp fixture and genuinely separate flushes | 1, 4 |
| Liveness/readiness and nonzero-exit restart policy | 4, 5 |
| Separate MinIO/AWS keys; AWS chain works after clearing endpoint | 3, 5, 6 |
| Pinned MinIO tools, frozen slim build, local smoke gate | 5, 6 |
| No live cloud in pytest | 1–5 |
| 14_uns_datalake; linked spec uses the same contracts | 3, 6 |
| Condition Monitoring unchanged | (not touched) |
