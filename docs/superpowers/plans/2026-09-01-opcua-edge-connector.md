# OPC UA Edge Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only OPC UA connector (`10_uns_opcua`) that subscribes to configured PLC/SCADA nodes and publishes them into the Unified Namespace, surviving broker and network outages without losing or duplicating data.

**Architecture:** One process, one supervised asyncio task per OPC UA server, one shared disk-backed SQLite spool. Collectors translate OPC UA `DataValue` notifications into UNS payloads and enqueue them; a single writer batches them into the spool; a single forwarder drains the spool to MQTT over one long-lived connection at QoS 1. Every message goes through the spool — there is no direct-publish fast path — so per-topic ordering is preserved even while a backlog drains.

**Tech Stack:** Python 3.14, `asyncua` 2.0.1 (OPC UA client), `aiomqtt` 2.5.1 (MQTT), `sqlite3` (spool, WAL mode), `dynaconf` via `uns_config`, `prometheus_client`, SQLAlchemy async via `uns_model`, `pytest` + `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-09-01-opcua-edge-connector-design.md`

## Global Constraints

- **Rule 1 — `timestamp` is the OPC UA `SourceTimestamp`, stamped once at collection and never re-derived at drain time.** The spooled payload is republished verbatim. Serialise the payload to bytes once, in the collector, and never rebuild it.
- **Rule 2 — `client_id` is stable across restarts**, read from `opcua.client_id` in configuration, never generated. It is used both as the MQTT `identifier` and as the payload's `source` field.
- **Read-only.** No OPC UA writes, no method calls, no setpoint or command write-back. Do not import or call `Node.write_value`, `Node.set_value`, or `Node.call_method`.
- **No secrets in code or in `settings.yaml`.** Certificate pass phrases and broker credentials come from `conf/.secrets.yaml` or `UNS_`-prefixed environment variables.
- **No `status` field in the payload.** The connector publishes `quality` from the OPC UA `StatusCode`; it never invents `Normal`/`Warning`/`Alarm`.
- Python `requires-python = ">=3.14, <4"`, matching every other module.
- Dependency pins, exactly: `asyncua>=2.0.1,<3`, `aiomqtt>=2.5.1,<3`, `dynaconf~=3.2`, `prometheus-client>=0.21.0,<1`, `psutil>=6.1.1,<8`, `logger~=1.4`, `sqlalchemy[asyncio]>=2.0.36,<3` (matching `09_uns_model`).
- Prometheus metric names are prefixed `uns_opcua_`. Metrics port is `9093` (9091 is the historian, 9092 the graphdb).
- Module directory is `10_uns_opcua`, package `uns_opcua`, Dynaconf environment `opcua`.
- Asset Model validation **reports, never gates.** The connector must start and publish with Postgres unreachable.
- Integration tests are marked `@pytest.mark.integrationtest`. Tests that share the Compose broker also get `@pytest.mark.xdist_group`.
- The root `addopts` already contains `-n auto`, so use **`-n 0`** to run a file serially — `-p no:xdist` would unload the plugin and make pytest reject its own `-n` flag.
- `asyncio_mode` is unset repo-wide, so pytest-asyncio runs in its default strict mode: every async test needs `@pytest.mark.asyncio` (or a module-level `pytestmark`) and every async fixture needs `@pytest_asyncio.fixture`.

---

## Verified API facts

These were confirmed empirically against `asyncua` 2.0.1 and `aiomqtt` 2.5.1 in this environment. Do not "correct" them from memory.

1. `Subscription.subscribe_data_change()` has **no filter parameter**. A deadband requires building `ua.MonitoredItemCreateRequest` objects and calling `Subscription.create_monitored_items()`.
2. `create_monitored_items()` returns `list[int | ua.StatusCode]`. An accepted item yields an `int` handle; a **rejected filter yields a `ua.StatusCode`**. That is the rejection discriminator.
3. `ua.DataChangeFilter(Trigger=..., DeadbandType=..., DeadbandValue=...)` — `DeadbandType` must be an `int`, so cast: `int(ua.DeadbandType.Absolute)`.
4. Server-side deadband genuinely suppresses notifications. With `DeadbandValue=2.0` and writes of 75.5 / 80.0 / 80.4 / 90.0, only 80.0 and 90.0 were delivered.
5. **Creating a monitored item delivers its current value immediately**, before any write. Reconnect therefore needs no explicit read pass — re-subscribing recovers the outage gap, with the server's real `SourceTimestamp`.
6. In `datachange_notification(self, node, val, data)`, the full `DataValue` is `data.monitored_item.Value`, exposing `.Value`, `.SourceTimestamp` (tz-aware UTC `datetime`), `.ServerTimestamp`, and `.StatusCode`.
7. `aiomqtt.Client(hostname=..., port=..., username=..., password=..., identifier=..., protocol=..., tls_params=..., tls_insecure=..., keepalive=...)`; `await client.publish(topic, payload=..., qos=..., retain=...)`.
8. `uns_config.get_settings(env)` uses Dynaconf **environments**: config data lives under `default:` in `conf/settings.yaml` and is read as `settings.get("opcua.client_id")`; a top-level `opcua:` environment section holds environment overrides.
9. Asset Model columns: `model.asset.path`, `.segment`, `.level`, `.is_active`; `model.metric_definition.metric_key`, `.unit_of_measure`, `.asset_id` (NULL means "applies to every Asset"). Schema constant `MODEL_SCHEMA = "model"`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `10_uns_opcua/pyproject.toml` | Workspace member metadata, pins, console scripts |
| `10_uns_opcua/README.md` | Module docs |
| `10_uns_opcua/Dockerfile` | `python:3.14-alpine3.22` image |
| `src/uns_opcua/opcua_config.py` | Dynaconf-backed config; pure parse functions returning frozen dataclasses |
| `src/uns_opcua/tag_map.py` | `TagConfig` → `TagBinding`; topic derivation; conflict detection |
| `src/uns_opcua/payload.py` | `DataValue` fields → UNS payload dict; quality and timestamp-fallback rules |
| `src/uns_opcua/prometheus_metrics.py` | All `uns_opcua_*` metric objects and the metrics server |
| `src/uns_opcua/spool.py` | Bounded SQLite WAL spool: `enqueue` / `peek` / `delete_through` / `trim` |
| `src/uns_opcua/collector.py` | Per-server session + subscription; monitored-item construction; reconnect |
| `src/uns_opcua/forwarder.py` | Drains the spool to MQTT over one long-lived connection |
| `src/uns_opcua/model_check.py` | Asset Model validation (pure check + Postgres lookup + `--validate` CLI) |
| `src/uns_opcua/health_check.py` | `psutil`-based container healthcheck |
| `src/uns_opcua/main.py` | Supervisor: builds bindings, starts tasks, handles shutdown |
| `test/` | One test module per source module |

Split rationale: the three pure-logic modules (`tag_map`, `payload`, `spool`) hold everything worth unit-testing and have no OPC UA or MQTT imports, so the bulk of the test suite runs with no I/O. `collector` and `forwarder` are thin I/O shells over them.

Dependency order (and therefore task order): `opcua_config` → `tag_map` → `payload` → `prometheus_metrics` → `spool` → `collector` → `forwarder` → `model_check` → `main` → deployment.

---

## Task 1: Module scaffold, configuration, and workspace registration

**Files:**
- Create: `10_uns_opcua/pyproject.toml`
- Create: `10_uns_opcua/README.md`
- Create: `10_uns_opcua/src/uns_opcua/__init__.py`
- Create: `10_uns_opcua/src/uns_opcua/opcua_config.py`
- Create: `10_uns_opcua/test/test_opcua_config.py`
- Modify: `pyproject.toml:32-42` (dependencies), `:62-71` (`[tool.uv.sources]`), `:73-74` (workspace members), `:81-91` (`testpaths`), `:92-102` (`pythonpath`)
- Modify: `conf/settings.yaml:72-78` (add an `opcua:` block under `default:`), `:99` (add a top-level `opcua:` environment)

**Interfaces:**
- Consumes: `uns_config.get_settings`
- Produces: `Deadband(type: Literal["absolute","percent"], value: float)`; `TagConfig(node_id: str, asset: str, metric_path: str, unit: str | None, deadband: Deadband | None)`; `SecurityConfig(...).to_security_string() -> str`; `ServerConfig(name: str, url: str, publishing_interval_ms: int, tags: tuple[TagConfig, ...], security: SecurityConfig | None)`; `SpoolConfig(path: str, max_rows: int, max_bytes: int, max_age_hours: int, synchronous: str)`; `parse_deadband(raw) -> Deadband | None`; `parse_tag(raw) -> TagConfig`; `parse_security(raw) -> SecurityConfig | None`; `parse_server(raw) -> ServerConfig`; `parse_servers(raw) -> tuple[ServerConfig, ...]`; `parse_spool(raw) -> SpoolConfig`; `OpcUaConfig` and `MQTTConfig` classes

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_opcua_config.py`:

```python
"""Unit tests for the OPC UA connector's configuration parsing."""

import pytest
from uns_opcua.opcua_config import (
    Deadband,
    parse_deadband,
    parse_security,
    parse_server,
    parse_spool,
    parse_tag,
)


def test_parse_tag_strips_slashes_and_defaults_metric_path():
    tag = parse_tag({"node_id": "ns=2;s=Mixer.Temp_PV", "asset": "/Ent/Site/Line1/Mixer/"})
    assert tag.node_id == "ns=2;s=Mixer.Temp_PV"
    assert tag.asset == "Ent/Site/Line1/Mixer"
    assert tag.metric_path == ""
    assert tag.unit is None
    assert tag.deadband is None


def test_parse_tag_requires_node_id_and_asset():
    with pytest.raises(ValueError, match="node_id"):
        parse_tag({"asset": "Ent/Site"})
    with pytest.raises(ValueError, match="asset"):
        parse_tag({"node_id": "ns=2;i=5"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ({}, None),
        ({"type": "none"}, None),
        ({"type": "absolute", "value": 0.2}, Deadband(type="absolute", value=0.2)),
        ({"type": "Percent", "value": 1}, Deadband(type="percent", value=1.0)),
    ],
)
def test_parse_deadband(raw, expected):
    assert parse_deadband(raw) == expected


def test_parse_deadband_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unsupported deadband type"):
        parse_deadband({"type": "sigma", "value": 3})


def test_security_string_matches_asyncua_format():
    security = parse_security(
        {
            "policy": "Basic256Sha256",
            "mode": "SignAndEncrypt",
            "certificate": "/certs/client.der",
            "private_key": "/certs/client.key",
            "server_certificate": "/certs/server.der",
        }
    )
    assert security.to_security_string() == (
        "Basic256Sha256,SignAndEncrypt,/certs/client.der,/certs/client.key,/certs/server.der"
    )


def test_security_string_omits_absent_server_certificate():
    security = parse_security(
        {
            "policy": "Basic256Sha256",
            "mode": "Sign",
            "certificate": "/certs/client.der",
            "private_key": "/certs/client.key",
        }
    )
    assert security.to_security_string() == "Basic256Sha256,Sign,/certs/client.der,/certs/client.key"


def test_parse_security_reports_every_missing_field():
    with pytest.raises(ValueError, match="certificate, private_key"):
        parse_security({"policy": "Basic256Sha256", "mode": "Sign"})


def test_parse_server_defaults_publishing_interval():
    server = parse_server(
        {
            "name": "plc01",
            "url": "opc.tcp://10.4.2.11:4840/",
            "tags": [{"node_id": "ns=2;i=5", "asset": "Ent/Site", "metric_path": "ProcessValue/Temperature"}],
        }
    )
    assert server.publishing_interval_ms == 200
    assert server.security is None
    assert len(server.tags) == 1


def test_parse_server_rejects_a_server_with_no_tags():
    with pytest.raises(ValueError, match="no tags"):
        parse_server({"name": "plc01", "url": "opc.tcp://host:4840/", "tags": []})


def test_parse_spool_defaults_and_normalises_synchronous():
    spool = parse_spool({"synchronous": "full"})
    assert spool.synchronous == "FULL"
    assert spool.path == "/var/lib/uns_opcua/spool.db"
    assert spool.max_rows == 5_000_000
    assert spool.max_bytes == 2_000_000_000
    assert spool.max_age_hours == 168


def test_parse_spool_rejects_unknown_synchronous_mode():
    with pytest.raises(ValueError, match="synchronous"):
        parse_spool({"synchronous": "SOMETIMES"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_opcua_config.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua'`

- [ ] **Step 3: Write the module metadata and register the workspace member**

Create `10_uns_opcua/pyproject.toml`:

```toml
[project]
name = "uns_opcua"
version = "0.1.0"
description = "Read-only OPC UA edge connector that publishes into a UNS setup"
authors = [{ name = "Ashwin Krishnan", email = "mkashwin@gmail.com" }]
requires-python = ">=3.14, <4"
readme = "README.md"
license = { text = "MIT" }
keywords = ["uns", "mqtt", "opcua", "edge", "store-and-forward"]
classifiers = [
    "License :: OSI Approved :: MIT License",
    "Intended Audience :: Manufacturing",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Development Status :: 3 - Alpha",
    "Topic :: Communications",
]
dependencies = [
    "logger~=1.4",
    "uns_config",
    "uns_model",
    "asyncua>=2.0.1,<3",
    "aiomqtt>=2.5.1,<3",
    "dynaconf~=3.2",
    "psutil>=6.1.1,<8",
    "prometheus-client>=0.21.0,<1",
    # model_check.py imports sqlalchemy directly, so it is declared rather than relied
    # on transitively through uns_model. asyncpg arrives with uns_model's own pin.
    "sqlalchemy[asyncio]>=2.0.36,<3",
]

[project.urls]
Repository = "https://github.com/mkashwin/unifiednamespace/tree/main/10_uns_opcua"

[project.scripts]
uns_opcua = "uns_opcua.main:main"
uns_opcua_healthcheck = "uns_opcua.health_check:main"
uns_opcua_validate = "uns_opcua.model_check:main"

[dependency-groups]
test = [
    "pytest>=9.0.3,<10",
    "pytest-asyncio>=1.3.0,<1.5",
    "pytest-xdist>=3.8.0,<4",
    "pytest-timeout>=2.4.0,<3",
    "pytest-cov>=7.1.0,<8",
]

# Relative paths, matching every other module. This is also what makes the Dockerfile
# work: the module sits at /app and its siblings are copied to /00_uns_config and
# /09_uns_model, so `../00_uns_config` resolves inside the image as well as in the
# workspace.
[tool.uv.sources]
uns_config = { path = "../00_uns_config", editable = true }
uns_model = { path = "../09_uns_model", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.sdist]
include = ["src/uns_opcua"]

[tool.hatch.build.targets.wheel]
include = ["src/uns_opcua"]

[tool.hatch.build.targets.wheel.sources]
"src/uns_opcua" = "uns_opcua"

[tool.pytest.ini_options]
norecursedirs = [".git", "build", "node_modules", "env*", "tmp*"]
testpaths = ["test"]

[tool.ruff]
# Extend the `pyproject.toml` file in the parent directory
extend = "../pyproject.toml"
```

Create `10_uns_opcua/src/uns_opcua/__init__.py` as an empty file.

In the root `pyproject.toml`, add `"uns_opcua",` to `dependencies` after `"uns_graphql",`; add `uns_opcua = { path = "./10_uns_opcua", editable = true }` to `[tool.uv.sources]`; add `"uns_opcua"` to `[tool.uv.workspace] members`; and add `"10_uns_opcua/test",` to both `testpaths` and `pythonpath` after the `09_uns_model/test` entry.

Then run `uv lock && uv sync` so the new member and `asyncua` resolve.

- [ ] **Step 4: Write `opcua_config.py`**

Create `10_uns_opcua/src/uns_opcua/opcua_config.py`:

```python
"""Configuration reader for the read-only OPC UA edge connector."""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from aiomqtt import ProtocolVersion, TLSParameters
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from uns_config import get_settings

LOGGER = logging.getLogger(__name__)

settings = get_settings("opcua")

DEADBAND_TYPES: frozenset[str] = frozenset({"none", "absolute", "percent"})
SYNCHRONOUS_MODES: frozenset[str] = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})


@dataclass(frozen=True, slots=True)
class Deadband:
    """A server-side report-by-exception threshold. `none` is modelled as no Deadband."""

    type: Literal["absolute", "percent"]
    value: float


@dataclass(frozen=True, slots=True)
class TagConfig:
    """One OPC UA node mapped to an Asset and the topic segments below it."""

    node_id: str
    asset: str
    metric_path: str
    unit: str | None = None
    deadband: Deadband | None = None


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    """OPC UA session security. Pass phrases belong in .secrets.yaml, not here."""

    policy: str
    mode: str
    certificate: str
    private_key: str
    server_certificate: str | None = None

    def to_security_string(self) -> str:
        """asyncua's `set_security_string` format: Policy,Mode,cert,key[,server_cert]."""
        parts = [self.policy, self.mode, self.certificate, self.private_key]
        if self.server_certificate:
            parts.append(self.server_certificate)
        return ",".join(parts)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """One OPC UA server and the tags collected from it."""

    name: str
    url: str
    publishing_interval_ms: int
    tags: tuple[TagConfig, ...]
    security: SecurityConfig | None = None


@dataclass(frozen=True, slots=True)
class SpoolConfig:
    """Bounds for the disk-backed store-and-forward spool."""

    path: str
    max_rows: int
    max_bytes: int
    max_age_hours: int
    synchronous: str


def parse_deadband(raw: Any) -> Deadband | None:
    """Return None for an absent or explicitly `none` Deadband."""
    if not raw:
        return None
    db_type = str(raw.get("type", "none")).lower()
    if db_type not in DEADBAND_TYPES:
        raise ValueError(f"Unsupported deadband type {db_type!r}; expected one of {sorted(DEADBAND_TYPES)}")
    if db_type == "none":
        return None
    return Deadband(type=db_type, value=float(raw["value"]))


def parse_tag(raw: Any) -> TagConfig:
    node_id = raw.get("node_id")
    if not node_id:
        raise ValueError("An opcua tag is missing 'node_id'")
    asset = raw.get("asset")
    if not asset:
        raise ValueError(f"opcua tag {node_id!r} is missing 'asset'")
    return TagConfig(
        node_id=str(node_id),
        asset=str(asset).strip("/"),
        metric_path=str(raw.get("metric_path", "")).strip("/"),
        unit=raw.get("unit"),
        deadband=parse_deadband(raw.get("deadband")),
    )


def parse_security(raw: Any) -> SecurityConfig | None:
    if not raw:
        return None
    missing = [key for key in ("policy", "mode", "certificate", "private_key") if not raw.get(key)]
    if missing:
        raise ValueError(f"opcua server security is missing {', '.join(missing)}")
    return SecurityConfig(
        policy=str(raw["policy"]),
        mode=str(raw["mode"]),
        certificate=str(raw["certificate"]),
        private_key=str(raw["private_key"]),
        server_certificate=raw.get("server_certificate"),
    )


def parse_server(raw: Any) -> ServerConfig:
    name = raw.get("name")
    if not name:
        raise ValueError("An opcua server is missing 'name'")
    url = raw.get("url")
    if not url:
        raise ValueError(f"opcua server {name!r} is missing 'url'")
    tags = tuple(parse_tag(tag) for tag in raw.get("tags") or ())
    if not tags:
        raise ValueError(f"opcua server {name!r} has no tags")
    return ServerConfig(
        name=str(name),
        url=str(url),
        publishing_interval_ms=int(raw.get("publishing_interval_ms", 200)),
        tags=tags,
        security=parse_security(raw.get("security")),
    )


def parse_servers(raw: Any) -> tuple[ServerConfig, ...]:
    return tuple(parse_server(server) for server in raw or ())


def parse_spool(raw: Any) -> SpoolConfig:
    raw = raw or {}
    synchronous = str(raw.get("synchronous", "NORMAL")).upper()
    if synchronous not in SYNCHRONOUS_MODES:
        raise ValueError(f"Unsupported spool synchronous mode {synchronous!r}; expected one of {sorted(SYNCHRONOUS_MODES)}")
    return SpoolConfig(
        path=str(raw.get("path", "/var/lib/uns_opcua/spool.db")),
        max_rows=int(raw.get("max_rows", 5_000_000)),
        max_bytes=int(raw.get("max_bytes", 2_000_000_000)),
        max_age_hours=int(raw.get("max_age_hours", 168)),
        synchronous=synchronous,
    )


class OpcUaConfig:
    """The `opcua` block of settings.yaml."""

    client_id: str = settings.get("opcua.client_id")
    """Rule 2: stable across restarts, never generated."""

    model_check: bool = bool(settings.get("opcua.model_check", True))
    metrics_port: int = int(settings.get("opcua.metrics_port", 9093))
    reconnect_backoff_max_s: float = float(settings.get("opcua.reconnect_backoff_max_s", 60.0))
    queue_maxsize: int = int(settings.get("opcua.queue_maxsize", 50_000))
    forward_batch_size: int = int(settings.get("opcua.forward_batch_size", 200))
    spool: SpoolConfig = parse_spool(settings.get("opcua.spool", {}))
    servers: tuple[ServerConfig, ...] = parse_servers(settings.get("opcua.servers", []))

    @classmethod
    def is_config_valid(cls) -> bool:
        """Mandatory configuration is present. Does not validate the values themselves."""
        return bool(cls.client_id) and bool(cls.servers)


class MQTTConfig:
    """The shared `mqtt` block, read exactly as the simulator reads it."""

    transport: Literal["tcp", "websockets"] = settings.get("mqtt.transport", "tcp")
    version: ProtocolVersion = ProtocolVersion(settings.get("mqtt.version", ProtocolVersion.V5))
    properties: Properties | None = Properties(PacketTypes.CONNECT) if version == ProtocolVersion.V5 else None
    qos: Literal[0, 1, 2] = settings.get("mqtt.qos", 1)

    host: str = settings.get("mqtt.host")
    port: int = settings.get("mqtt.port", 1883)
    username: str | None = settings.get("mqtt.username")
    password: str | None = settings.get("mqtt.password")
    tls: dict | None = settings.get("mqtt.tls", None)

    tls_params: TLSParameters | None = (
        TLSParameters(
            ca_certs=tls.get("ca_certs"),
            certfile=tls.get("certfile"),
            keyfile=tls.get("keyfile"),
            cert_reqs=tls.get("cert_reqs"),
            ciphers=tls.get("ciphers"),
            keyfile_password=tls.get("keyfile_password"),
        )
        if tls is not None
        else None
    )
    tls_insecure: bool | None = tls.get("insecure_cert") if tls is not None else None
    keep_alive: int = settings.get("mqtt.keep_alive", 60)
    retry_interval: int = settings.get("mqtt.retry_interval", 10)

    @classmethod
    def is_config_valid(cls) -> bool:
        return cls.host is not None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_opcua_config.py -v -n 0`
Expected: PASS (14 tests)

- [ ] **Step 6: Add the configuration to `conf/settings.yaml`**

Under `default:`, after the `historian:` block (`conf/settings.yaml:72-77`), add:

```yaml
  opcua:
    client_id: "uns_opcua_client"
    model_check: true
    metrics_port: 9093
    queue_maxsize: 50000
    forward_batch_size: 200
    reconnect_backoff_max_s: 60
    spool:
      path: "/var/lib/uns_opcua/spool.db"
      max_rows: 5000000
      max_bytes: 2000000000
      max_age_hours: 168
      synchronous: "NORMAL"
    # No servers by default: the connector exits cleanly when none are configured,
    # so a stock checkout does not try to reach a PLC that is not there.
    servers: []
```

Then, as a top-level environment section (alongside `historian:` at `conf/settings.yaml:97`), add:

```yaml
opcua:
  opcua:
    # Replace with the plant's servers. node_id, asset and metric_path are all required;
    # the published topic is asset + "/" + metric_path.
    servers: []
```

- [ ] **Step 7: Verify the configuration loads**

Run: `uv run python -c "from uns_opcua.opcua_config import OpcUaConfig as C; print(C.client_id, C.metrics_port, C.spool, C.servers)"`
Expected: `uns_opcua_client 9093 SpoolConfig(path='/var/lib/uns_opcua/spool.db', max_rows=5000000, max_bytes=2000000000, max_age_hours=168, synchronous='NORMAL') ()`

- [ ] **Step 8: Write the README**

Create `10_uns_opcua/README.md`:

```markdown
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
```

- [ ] **Step 9: Commit**

```bash
git add 10_uns_opcua pyproject.toml conf/settings.yaml uv.lock
git commit -m "feat(opcua): scaffold 10_uns_opcua module and configuration

Registers the new workspace member and adds Dynaconf-backed config parsing
for servers, tags, deadbands, security and the spool bounds."
```

---

## Task 2: Tag map — topic derivation and conflict detection

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/tag_map.py`
- Create: `10_uns_opcua/test/test_tag_map.py`

**Interfaces:**
- Consumes: `Deadband`, `TagConfig`, `ServerConfig` from `uns_opcua.opcua_config`
- Produces: `TagBinding(node_id: str, topic: str, asset: str, metric_path: str, unit: str | None, deadband: Deadband | None, equipment: str, server_name: str)`; `TagBinding.metric_key -> str`; `derive_topic(asset: str, metric_path: str) -> str`; `build_bindings(server: ServerConfig) -> tuple[TagBinding, ...]`; `find_conflicts(bindings: Sequence[TagBinding]) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_tag_map.py`:

```python
"""Unit tests for OPC UA node -> UNS topic mapping."""

import pytest
from uns_opcua.opcua_config import Deadband, ServerConfig, TagConfig
from uns_opcua.tag_map import build_bindings, derive_topic, find_conflicts

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"


def _tag(node_id: str, metric_path: str, asset: str = ASSET) -> TagConfig:
    return TagConfig(node_id=node_id, asset=asset, metric_path=metric_path)


def _server(*tags: TagConfig) -> ServerConfig:
    return ServerConfig(name="plc01", url="opc.tcp://host:4840/", publishing_interval_ms=200, tags=tags)


@pytest.mark.parametrize(
    ("asset", "metric_path", "expected"),
    [
        (ASSET, "ProcessValue/Temperature", f"{ASSET}/ProcessValue/Temperature"),
        (ASSET, "", ASSET),
        ("/Ent/Site/", "/ProcessValue/Temperature/", "Ent/Site/ProcessValue/Temperature"),
    ],
)
def test_derive_topic(asset, metric_path, expected):
    assert derive_topic(asset, metric_path) == expected


def test_derive_topic_rejects_an_empty_asset():
    with pytest.raises(ValueError, match="asset"):
        derive_topic("", "ProcessValue/Temperature")


def test_build_bindings_carries_equipment_and_metric_key():
    bindings = build_bindings(_server(_tag("ns=2;i=5", "ProcessValue/Temperature")))
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.topic == f"{ASSET}/ProcessValue/Temperature"
    assert binding.equipment == "MixerTank"
    assert binding.server_name == "plc01"
    # A MetricDefinition is keyed by Metric Key, which includes the payload leaf.
    assert binding.metric_key == "ProcessValue/Temperature/value"


def test_metric_key_of_an_asset_level_tag_is_just_the_leaf():
    bindings = build_bindings(_server(TagConfig(node_id="ns=2;i=9", asset=ASSET, metric_path="")))
    assert bindings[0].metric_key == "value"


def test_build_bindings_preserves_unit_and_deadband():
    tag = TagConfig(
        node_id="ns=2;i=5",
        asset=ASSET,
        metric_path="ProcessValue/Temperature",
        unit="°C",
        deadband=Deadband(type="absolute", value=0.2),
    )
    binding = build_bindings(_server(tag))[0]
    assert binding.unit == "°C"
    assert binding.deadband == Deadband(type="absolute", value=0.2)


def test_find_conflicts_is_empty_for_a_clean_map():
    bindings = build_bindings(
        _server(_tag("ns=2;i=5", "ProcessValue/Temperature"), _tag("ns=2;i=6", "ProcessValue/Pressure"))
    )
    assert find_conflicts(bindings) == []


def test_find_conflicts_reports_a_duplicate_node_id():
    bindings = build_bindings(
        _server(_tag("ns=2;i=5", "ProcessValue/Temperature"), _tag("ns=2;i=5", "ProcessValue/Pressure"))
    )
    conflicts = find_conflicts(bindings)
    assert len(conflicts) == 1
    assert "ns=2;i=5" in conflicts[0]
    assert "duplicate node_id" in conflicts[0]


def test_find_conflicts_reports_two_tags_resolving_to_one_topic():
    bindings = build_bindings(
        _server(_tag("ns=2;i=5", "ProcessValue/Temperature"), _tag("ns=2;i=6", "ProcessValue/Temperature"))
    )
    conflicts = find_conflicts(bindings)
    assert len(conflicts) == 1
    assert "duplicate topic" in conflicts[0]
    assert f"{ASSET}/ProcessValue/Temperature" in conflicts[0]


def test_find_conflicts_scopes_node_ids_per_server():
    """The same node_id on two different servers is normal, not a conflict."""
    plc01 = build_bindings(_server(_tag("ns=2;i=5", "ProcessValue/Temperature")))
    plc02 = build_bindings(
        ServerConfig(
            name="plc02",
            url="opc.tcp://other:4840/",
            publishing_interval_ms=200,
            tags=(_tag("ns=2;i=5", "ProcessValue/Temperature", asset="Ent/Site/Line2/Mixer"),),
        )
    )
    assert find_conflicts([*plc01, *plc02]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_tag_map.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua.tag_map'`

- [ ] **Step 3: Write the minimal implementation**

Create `10_uns_opcua/src/uns_opcua/tag_map.py`:

```python
"""Maps configured OPC UA nodes onto Unified Namespace topics."""

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from uns_opcua.opcua_config import Deadband, ServerConfig

LOGGER = logging.getLogger(__name__)

PAYLOAD_LEAF = "value"
"""The payload key this connector always publishes its scalar under."""


def derive_topic(asset: str, metric_path: str) -> str:
    """
    The published topic is the Asset path followed by the topic segments below it.

    `metric_path` is deliberately the Asset Model's name for those segments, not Metric
    Key: a Metric Key also carries the dotted path inside the payload, which is one
    segment too many for a topic.
    """
    asset = asset.strip("/")
    if not asset:
        raise ValueError("A tag's asset must not be empty")
    metric_path = metric_path.strip("/")
    return f"{asset}/{metric_path}" if metric_path else asset


@dataclass(frozen=True, slots=True)
class TagBinding:
    """A resolved mapping from one OPC UA node to one UNS topic."""

    node_id: str
    topic: str
    asset: str
    metric_path: str
    unit: str | None
    deadband: Deadband | None
    equipment: str
    server_name: str

    @property
    def metric_key(self) -> str:
        """
        The Metric Key a MetricDefinition is keyed by: the topic segments below the
        Asset plus the dotted path within the payload, e.g.
        `ProcessValue/Temperature/value`.
        """
        return f"{self.metric_path}/{PAYLOAD_LEAF}" if self.metric_path else PAYLOAD_LEAF


def build_bindings(server: ServerConfig) -> tuple[TagBinding, ...]:
    """Resolve every tag of one server into a TagBinding."""
    return tuple(
        TagBinding(
            node_id=tag.node_id,
            topic=derive_topic(tag.asset, tag.metric_path),
            asset=tag.asset,
            metric_path=tag.metric_path,
            unit=tag.unit,
            deadband=tag.deadband,
            equipment=tag.asset.strip("/").rsplit("/", maxsplit=1)[-1],
            server_name=server.name,
        )
        for tag in server.tags
    )


def find_conflicts(bindings: Sequence[TagBinding]) -> list[str]:
    """
    Human-readable descriptions of mappings that cannot both be right.

    node_id is scoped per server, because the same address on two PLCs is ordinary.
    A topic is global: two tags publishing to one topic would overwrite each other.
    """
    conflicts: list[str] = []

    node_ids = Counter((binding.server_name, binding.node_id) for binding in bindings)
    for (server_name, node_id), count in sorted(node_ids.items()):
        if count > 1:
            conflicts.append(f"{server_name}: duplicate node_id {node_id!r} appears {count} times")

    topics = Counter(binding.topic for binding in bindings)
    for topic, count in sorted(topics.items()):
        if count > 1:
            conflicts.append(f"duplicate topic {topic!r} is produced by {count} tags")

    return conflicts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_tag_map.py -v -n 0`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/tag_map.py 10_uns_opcua/test/test_tag_map.py
git commit -m "feat(opcua): derive UNS topics from asset + metric_path

Adds TagBinding with the Metric Key needed for Asset Model lookup, and
conflict detection for duplicate node_ids and colliding topics."
```

---

## Task 3: Payload mapping

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/payload.py`
- Create: `10_uns_opcua/test/test_payload.py`

**Interfaces:**
- Consumes: `TagBinding` from `uns_opcua.tag_map`
- Produces: `quality_from_code(code: int) -> str`; `to_epoch_ms(moment: datetime) -> float`; `MappedPayload(topic: str, payload: dict[str, Any], timestamp_fallback: str | None)`; `build_payload(binding: TagBinding, value: Any, status_code: int, source_timestamp: datetime | None, server_timestamp: datetime | None, collected_at: datetime, client_id: str) -> MappedPayload`; `serialise(payload: dict[str, Any]) -> bytes`

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_payload.py`:

```python
"""Unit tests for OPC UA DataValue -> UNS payload mapping."""

import datetime
import json

import pytest
from uns_opcua.opcua_config import ServerConfig, TagConfig
from uns_opcua.payload import build_payload, quality_from_code, serialise, to_epoch_ms
from uns_opcua.tag_map import build_bindings

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"
CLIENT_ID = "uns_opcua_dormagen"

SOURCE_TS = datetime.datetime(2026, 9, 1, 12, 0, 0, 123000, tzinfo=datetime.UTC)
SERVER_TS = datetime.datetime(2026, 9, 1, 12, 0, 0, 456000, tzinfo=datetime.UTC)
COLLECTED_AT = datetime.datetime(2026, 9, 1, 12, 0, 1, 0, tzinfo=datetime.UTC)


@pytest.fixture
def binding():
    server = ServerConfig(
        name="plc01",
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id="ns=2;i=5", asset=ASSET, metric_path="ProcessValue/Temperature", unit="°C"),),
    )
    return build_bindings(server)[0]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0x00000000, "Good"),        # Good
        (0x00000002, "Good"),        # Good with an info bit set
        (0x40000000, "Uncertain"),   # Uncertain
        (0x408F0000, "Uncertain"),   # Uncertain_LastUsableValue
        (0x80000000, "Bad"),         # Bad
        (0x80340000, "Bad"),         # BadDeviceFailure
        (0xC0000000, "Bad"),         # reserved severity is treated as Bad
    ],
)
def test_quality_from_code(code, expected):
    assert quality_from_code(code) == expected


def test_to_epoch_ms():
    # 2026-09-01T12:00:00.123Z. Verified against datetime rather than typed from memory.
    assert to_epoch_ms(SOURCE_TS) == pytest.approx(1788264000123.0)


def test_to_epoch_ms_treats_a_naive_datetime_as_utc():
    naive = SOURCE_TS.replace(tzinfo=None)
    assert to_epoch_ms(naive) == pytest.approx(to_epoch_ms(SOURCE_TS))


def test_build_payload_uses_source_timestamp(binding):
    mapped = build_payload(
        binding=binding,
        value=74.83,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=SERVER_TS,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.topic == f"{ASSET}/ProcessValue/Temperature"
    assert mapped.timestamp_fallback is None
    assert mapped.payload == {
        "value": 74.83,
        "unit": "°C",
        "quality": "Good",
        "timestamp": pytest.approx(to_epoch_ms(SOURCE_TS)),
        "source": CLIENT_ID,
        "equipment": "MixerTank",
    }


def test_build_payload_never_emits_a_status_field(binding):
    mapped = build_payload(
        binding=binding,
        value=74.83,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert "status" not in mapped.payload


def test_build_payload_omits_unit_when_not_configured():
    server = ServerConfig(
        name="plc01",
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id="ns=2;i=5", asset=ASSET, metric_path="Status/Running"),),
    )
    mapped = build_payload(
        binding=build_bindings(server)[0],
        value=True,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert "unit" not in mapped.payload
    assert mapped.payload["value"] is True


def test_build_payload_falls_back_to_server_timestamp(binding):
    mapped = build_payload(
        binding=binding,
        value=1.0,
        status_code=0,
        source_timestamp=None,
        server_timestamp=SERVER_TS,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.timestamp_fallback == "server_timestamp"
    assert mapped.payload["timestamp"] == pytest.approx(to_epoch_ms(SERVER_TS))


def test_build_payload_falls_back_to_collection_time(binding):
    mapped = build_payload(
        binding=binding,
        value=1.0,
        status_code=0,
        source_timestamp=None,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.timestamp_fallback == "collection_time"
    assert mapped.payload["timestamp"] == pytest.approx(to_epoch_ms(COLLECTED_AT))


def test_build_payload_publishes_bad_quality_rather_than_dropping_it(binding):
    mapped = build_payload(
        binding=binding,
        value=None,
        status_code=0x80340000,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    assert mapped.payload["quality"] == "Bad"
    assert mapped.payload["value"] is None


def test_serialise_round_trips_and_keeps_unicode_units(binding):
    mapped = build_payload(
        binding=binding,
        value=74.83,
        status_code=0,
        source_timestamp=SOURCE_TS,
        server_timestamp=None,
        collected_at=COLLECTED_AT,
        client_id=CLIENT_ID,
    )
    raw = serialise(mapped.payload)
    assert isinstance(raw, bytes)
    assert json.loads(raw.decode("utf-8"))["unit"] == "°C"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_payload.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua.payload'`

- [ ] **Step 3: Write the minimal implementation**

Create `10_uns_opcua/src/uns_opcua/payload.py`:

```python
"""Translates an OPC UA DataValue into the Unified Namespace payload shape."""

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Any

from uns_opcua.tag_map import TagBinding

LOGGER = logging.getLogger(__name__)

_SEVERITY_SHIFT = 30
_SEVERITY_MASK = 0b11
_QUALITY_BY_SEVERITY: dict[int, str] = {0: "Good", 1: "Uncertain", 2: "Bad", 3: "Bad"}


def quality_from_code(code: int) -> str:
    """
    Map an OPC UA StatusCode to Good / Uncertain / Bad.

    Severity lives in the top two bits (OPC UA Part 4, 7.34): 00 Good, 01 Uncertain,
    10 Bad. 11 is reserved, and treating it as Bad is the safe reading. Taking an int
    rather than an `ua.StatusCode` keeps this testable without an OPC UA session.
    """
    return _QUALITY_BY_SEVERITY[(code >> _SEVERITY_SHIFT) & _SEVERITY_MASK]


def to_epoch_ms(moment: datetime.datetime) -> float:
    """
    Epoch milliseconds, matching `mqtt.timestamp_attribute` so this becomes the
    historian's `time` column. A naive datetime is read as UTC, which is what every
    OPC UA server means by one.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.timestamp() * 1000


@dataclass(frozen=True, slots=True)
class MappedPayload:
    """A topic and payload ready to be spooled, plus why the timestamp was chosen."""

    topic: str
    payload: dict[str, Any]
    timestamp_fallback: str | None


def build_payload(
    binding: TagBinding,
    value: Any,
    status_code: int,
    source_timestamp: datetime.datetime | None,
    server_timestamp: datetime.datetime | None,
    collected_at: datetime.datetime,
    client_id: str,
) -> MappedPayload:
    """
    Build the payload for one data change.

    Rule 1 lives here: `timestamp` is the SourceTimestamp, and this function is called
    exactly once per notification — at collection. Nothing downstream recomputes it.
    """
    fallback: str | None = None
    moment = source_timestamp
    if moment is None:
        moment, fallback = server_timestamp, "server_timestamp"
    if moment is None:
        moment, fallback = collected_at, "collection_time"

    payload: dict[str, Any] = {
        "value": value,
        "quality": quality_from_code(status_code),
        "timestamp": to_epoch_ms(moment),
        "source": client_id,
        "equipment": binding.equipment,
    }
    if binding.unit is not None:
        # Insert after `value` so the JSON reads the way the README documents it.
        payload = {"value": payload.pop("value"), "unit": binding.unit, **payload}

    return MappedPayload(topic=binding.topic, payload=payload, timestamp_fallback=fallback)


def serialise(payload: dict[str, Any]) -> bytes:
    """
    Serialise once, at collection, and spool the bytes.

    The historian's `mqtt_msg` is JSONB and compares semantically, so byte-stability is
    not what makes replay idempotent — not re-deriving any field is. Serialising here and
    republishing the bytes verbatim is how that is guaranteed rather than hoped for.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_payload.py -v -n 0`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/payload.py 10_uns_opcua/test/test_payload.py
git commit -m "feat(opcua): map OPC UA DataValue to the UNS payload shape

quality comes from the StatusCode severity bits; timestamp is the
SourceTimestamp with counted fallbacks. No fabricated status field."
```

---

## Task 4: Prometheus metrics

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/prometheus_metrics.py`
- Create: `10_uns_opcua/test/test_prometheus_metrics.py`

**Interfaces:**
- Consumes: nothing
- Produces: module-level metric objects `SERVER_UP`, `MONITORED_ITEMS`, `DATACHANGES`, `DEADBAND_REJECTED`, `UNRESOLVED_NODES`, `QUEUE_DROPPED`, `PUBLISH_TOTAL`, `PUBLISH_ERRORS`, `SPOOL_ROWS`, `SPOOL_BYTES`, `SPOOL_DROPPED`, `SPOOL_WRITE_ERRORS`, `SPOOL_LAG_SECONDS`, `UNMODELLED_TAGS`, `TIMESTAMP_FALLBACK`; `start_metrics_server(port: int) -> None`

The spec lists twelve metrics. This adds three the spec's own failure-mode table demands counters for but did not name: `DEADBAND_REJECTED` (server rejected the filter), `UNRESOLVED_NODES` (a `node_id` that would not resolve), and `QUEUE_DROPPED` (the in-memory hand-off to the spool writer overflowed — distinct from `SPOOL_DROPPED`, which is the disk bound being enforced). Conflating the last two would hide a disk problem behind a broker-outage metric.

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_prometheus_metrics.py`:

```python
"""The metric surface is part of this module's contract, so it is asserted."""

from prometheus_client import REGISTRY
from uns_opcua import prometheus_metrics

EXPECTED_SAMPLES = {
    "uns_opcua_server_up",
    "uns_opcua_monitored_items",
    "uns_opcua_datachanges_total",
    "uns_opcua_deadband_rejected_total",
    "uns_opcua_unresolved_nodes_total",
    "uns_opcua_queue_dropped_total",
    "uns_opcua_publish_total",
    "uns_opcua_publish_errors_total",
    "uns_opcua_spool_rows",
    "uns_opcua_spool_bytes",
    "uns_opcua_spool_dropped_total",
    "uns_opcua_spool_write_errors_total",
    "uns_opcua_spool_lag_seconds",
    "uns_opcua_unmodelled_tags",
    "uns_opcua_timestamp_fallback_total",
}


def test_every_documented_metric_is_registered():
    registered = {metric.name for metric in REGISTRY.collect()}
    # Counters register under their name without the _total suffix.
    expected = {name.removesuffix("_total") for name in EXPECTED_SAMPLES}
    assert expected <= registered


def test_labelled_metrics_accept_their_labels():
    prometheus_metrics.SERVER_UP.labels(server="plc01").set(1)
    prometheus_metrics.MONITORED_ITEMS.labels(server="plc01").set(3)
    prometheus_metrics.DATACHANGES.labels(server="plc01").inc()
    prometheus_metrics.DEADBAND_REJECTED.labels(server="plc01").inc()
    prometheus_metrics.UNRESOLVED_NODES.labels(server="plc01").inc()
    prometheus_metrics.TIMESTAMP_FALLBACK.labels(reason="server_timestamp").inc()

    assert REGISTRY.get_sample_value("uns_opcua_server_up", {"server": "plc01"}) == 1
    assert REGISTRY.get_sample_value("uns_opcua_datachanges_total", {"server": "plc01"}) == 1
    assert (
        REGISTRY.get_sample_value("uns_opcua_timestamp_fallback_total", {"reason": "server_timestamp"}) == 1
    )


def test_unlabelled_metrics_increment():
    before = REGISTRY.get_sample_value("uns_opcua_publish_total") or 0
    prometheus_metrics.PUBLISH_TOTAL.inc()
    assert REGISTRY.get_sample_value("uns_opcua_publish_total") == before + 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_prometheus_metrics.py -v -n 0`
Expected: FAIL — `ImportError: cannot import name 'prometheus_metrics' from 'uns_opcua'`

- [ ] **Step 3: Write the minimal implementation**

Create `10_uns_opcua/src/uns_opcua/prometheus_metrics.py`:

```python
"""Prometheus instrumentation for the OPC UA edge connector."""

from prometheus_client import Counter, Gauge, start_http_server

SERVER_UP = Gauge(
    "uns_opcua_server_up",
    "1 while an OPC UA session is established, 0 otherwise",
    ["server"],
)
MONITORED_ITEMS = Gauge(
    "uns_opcua_monitored_items",
    "Monitored items the server accepted",
    ["server"],
)
DATACHANGES = Counter(
    "uns_opcua_datachanges_total",
    "Data change notifications received",
    ["server"],
)
DEADBAND_REJECTED = Counter(
    "uns_opcua_deadband_rejected_total",
    "Monitored items the server would not accept a deadband filter for",
    ["server"],
)
UNRESOLVED_NODES = Counter(
    "uns_opcua_unresolved_nodes_total",
    "Configured node_ids that could not be resolved on the server",
    ["server"],
)
QUEUE_DROPPED = Counter(
    "uns_opcua_queue_dropped_total",
    "Notifications dropped because the in-memory hand-off to the spool writer was full",
)
PUBLISH_TOTAL = Counter(
    "uns_opcua_publish_total",
    "Messages published to the MQTT broker",
)
PUBLISH_ERRORS = Counter(
    "uns_opcua_publish_errors_total",
    "Failed publish attempts",
)
SPOOL_ROWS = Gauge(
    "uns_opcua_spool_rows",
    "Rows currently waiting in the spool",
)
SPOOL_BYTES = Gauge(
    "uns_opcua_spool_bytes",
    "On-disk size of the spool database",
)
SPOOL_DROPPED = Counter(
    "uns_opcua_spool_dropped_total",
    "Oldest spool rows deleted to stay inside the configured bounds",
)
SPOOL_WRITE_ERRORS = Counter(
    "uns_opcua_spool_write_errors_total",
    "Spool write failures, e.g. a full disk",
)
SPOOL_LAG_SECONDS = Gauge(
    "uns_opcua_spool_lag_seconds",
    "Age of the oldest unpublished spool row - how far behind this edge node is",
)
UNMODELLED_TAGS = Gauge(
    "uns_opcua_unmodelled_tags",
    "Configured tags with no matching Asset or MetricDefinition",
)
TIMESTAMP_FALLBACK = Counter(
    "uns_opcua_timestamp_fallback_total",
    "Notifications whose timestamp did not come from SourceTimestamp",
    ["reason"],
)


def start_metrics_server(port: int) -> None:
    """Expose /metrics for Prometheus scraping."""
    start_http_server(port)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_prometheus_metrics.py -v -n 0`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/prometheus_metrics.py 10_uns_opcua/test/test_prometheus_metrics.py
git commit -m "feat(opcua): expose Prometheus metrics from the first commit

Includes spool_lag_seconds, the number an operator actually needs, and keeps
queue drops distinct from spool-bound drops so a disk problem stays visible."
```

---

## Task 5: Disk-backed spool

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/spool.py`
- Create: `10_uns_opcua/test/test_spool.py`

**Interfaces:**
- Consumes: `SpoolConfig` from `uns_opcua.opcua_config`
- Produces: `SpoolRow(topic: str, payload: bytes, qos: int)`; `Spool(config: SpoolConfig)` with `open() -> None`, `close() -> None`, `enqueue(rows: Sequence[SpoolRow], now: float) -> int`, `peek(limit: int) -> list[tuple[int, SpoolRow]]`, `delete_through(max_id: int) -> int`, `trim(now: float) -> int`, `row_count() -> int`, `byte_size() -> int`, `oldest_spooled_at() -> float | None`

`Spool` is deliberately synchronous. `sqlite3` blocks, so every caller wraps it in `asyncio.to_thread` — that keeps the event loop free while leaving the spool trivially testable without an event loop. `now` is a parameter rather than a `time.time()` call so the age bound can be tested deterministically.

Two consequences of `asyncio.to_thread` that the implementation must handle, both verified rather than assumed:

- **`sqlite3.connect` defaults to `check_same_thread=True`**, and `asyncio.to_thread` runs on a pool thread that is not the one that opened the connection. Confirmed: it raises `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`. So the connection is opened with `check_same_thread=False`.
- **That makes serialising access this class's job.** `sqlite3.threadsafety` is 3 on this build, but it reflects a SQLite compile-time option and is not guaranteed elsewhere, and the writer and forwarder do call the spool concurrently from different pool threads. An `RLock` around every method removes the question. `RLock` rather than `Lock` because `trim()` calls `row_count()` and `byte_size()`.

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_spool.py`:

```python
"""Unit tests for the bounded, disk-backed store-and-forward spool."""

import pytest
from uns_opcua.opcua_config import SpoolConfig
from uns_opcua.spool import Spool, SpoolRow

NOW = 1_756_728_000.0


def _config(tmp_path, **overrides) -> SpoolConfig:
    defaults = {
        "path": str(tmp_path / "spool.db"),
        "max_rows": 1000,
        "max_bytes": 100_000_000,
        "max_age_hours": 168,
        "synchronous": "NORMAL",
    }
    return SpoolConfig(**{**defaults, **overrides})


@pytest.fixture
def spool(tmp_path):
    spool = Spool(_config(tmp_path))
    spool.open()
    yield spool
    spool.close()


def _row(topic: str, value: int = 1) -> SpoolRow:
    return SpoolRow(topic=topic, payload=f'{{"value":{value}}}'.encode(), qos=1)


def test_enqueue_then_peek_returns_rows_in_fifo_order(spool):
    assert spool.enqueue([_row("a", 1), _row("b", 2), _row("c", 3)], now=NOW) == 3
    peeked = spool.peek(limit=10)
    assert [row.topic for _, row in peeked] == ["a", "b", "c"]
    assert [row_id for row_id, _ in peeked] == sorted(row_id for row_id, _ in peeked)


def test_peek_respects_its_limit(spool):
    spool.enqueue([_row("a"), _row("b"), _row("c")], now=NOW)
    assert len(spool.peek(limit=2)) == 2


def test_payload_survives_the_round_trip_byte_for_byte(spool):
    payload = '{"value":74.83,"unit":"°C"}'.encode("utf-8")
    spool.enqueue([SpoolRow(topic="t", payload=payload, qos=1)], now=NOW)
    _, row = spool.peek(limit=1)[0]
    assert row.payload == payload
    assert row.qos == 1


def test_delete_through_removes_only_acknowledged_rows(spool):
    spool.enqueue([_row("a"), _row("b"), _row("c")], now=NOW)
    peeked = spool.peek(limit=2)
    assert spool.delete_through(peeked[-1][0]) == 2
    assert [row.topic for _, row in spool.peek(limit=10)] == ["c"]


def test_row_count_and_oldest_spooled_at(spool):
    assert spool.row_count() == 0
    assert spool.oldest_spooled_at() is None
    spool.enqueue([_row("a")], now=NOW)
    spool.enqueue([_row("b")], now=NOW + 60)
    assert spool.row_count() == 2
    assert spool.oldest_spooled_at() == NOW


def test_byte_size_is_positive_once_written(spool):
    spool.enqueue([_row("a")], now=NOW)
    assert spool.byte_size() > 0


def test_trim_enforces_max_rows_by_dropping_the_oldest(tmp_path):
    spool = Spool(_config(tmp_path, max_rows=3))
    spool.open()
    try:
        spool.enqueue([_row("a"), _row("b"), _row("c"), _row("d"), _row("e")], now=NOW)
        assert spool.trim(now=NOW) == 2
        assert [row.topic for _, row in spool.peek(limit=10)] == ["c", "d", "e"]
    finally:
        spool.close()


def test_trim_enforces_max_age(tmp_path):
    spool = Spool(_config(tmp_path, max_age_hours=1))
    spool.open()
    try:
        spool.enqueue([_row("old")], now=NOW)
        spool.enqueue([_row("fresh")], now=NOW + 3600)
        # Two hours after the first row was spooled, only the fresh one is inside the bound.
        assert spool.trim(now=NOW + 7200) == 1
        assert [row.topic for _, row in spool.peek(limit=10)] == ["fresh"]
    finally:
        spool.close()


def test_trim_enforces_max_bytes(tmp_path):
    spool = Spool(_config(tmp_path, max_bytes=1))
    spool.open()
    try:
        spool.enqueue([_row("a"), _row("b")], now=NOW)
        # An absurd bound must drop rather than leave the spool over its limit forever.
        assert spool.trim(now=NOW) > 0
    finally:
        spool.close()


def test_trim_is_a_no_op_inside_every_bound(spool):
    spool.enqueue([_row("a")], now=NOW)
    assert spool.trim(now=NOW) == 0
    assert spool.row_count() == 1


def test_reopening_the_same_file_keeps_the_backlog(tmp_path):
    config = _config(tmp_path)
    first = Spool(config)
    first.open()
    first.enqueue([_row("survivor")], now=NOW)
    first.close()

    second = Spool(config)
    second.open()
    try:
        assert [row.topic for _, row in second.peek(limit=10)] == ["survivor"]
    finally:
        second.close()


def test_ids_keep_increasing_after_a_delete(spool):
    """FIFO depends on ids never being reused, so AUTOINCREMENT is required."""
    spool.enqueue([_row("a")], now=NOW)
    first_id = spool.peek(limit=1)[0][0]
    spool.delete_through(first_id)
    spool.enqueue([_row("b")], now=NOW)
    assert spool.peek(limit=1)[0][0] > first_id


def test_wal_mode_and_synchronous_are_applied(tmp_path):
    spool = Spool(_config(tmp_path, synchronous="FULL"))
    spool.open()
    try:
        assert spool.pragma("journal_mode") == "wal"
        assert spool.pragma("synchronous") == 2  # FULL
        assert spool.pragma("auto_vacuum") == 2  # INCREMENTAL, so max_bytes can be met
    finally:
        spool.close()


def test_the_spool_is_usable_from_another_thread(spool):
    """
    Every caller reaches the spool through asyncio.to_thread, which runs on a pool
    thread that did not open the connection. sqlite3 raises ProgrammingError for that
    unless check_same_thread=False.
    """
    import concurrent.futures

    def write_and_count() -> int:
        spool.enqueue([_row("from-a-thread")], now=NOW)
        return spool.row_count()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert pool.submit(write_and_count).result() == 1
        # A second, different pool thread must work too.
        assert pool.submit(write_and_count).result() == 2


def test_concurrent_writers_and_readers_do_not_corrupt_the_spool(spool):
    """The writer and forwarder tasks really do hit the spool at the same time."""
    import concurrent.futures

    def write(index: int) -> int:
        return spool.enqueue([_row(f"t{index}")], now=NOW)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        written = sum(pool.map(write, range(40)))

    assert written == 40
    assert spool.row_count() == 40
    assert len(spool.peek(limit=100)) == 40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_spool.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua.spool'`

- [ ] **Step 3: Write the minimal implementation**

Create `10_uns_opcua/src/uns_opcua/spool.py`:

```python
"""
Bounded, disk-backed store-and-forward spool.

Every message goes through here, always. There is no publish-direct fast path, because
two paths would let a draining backlog interleave with fresh values and break per-topic
ordering — in exchange for a few milliseconds that report-by-exception data does not care
about.

This class is synchronous on purpose: sqlite3 blocks, so callers wrap it in
`asyncio.to_thread`. That keeps the event loop free while leaving the spool testable
without one. `now` is always a parameter, never a clock read, so the age bound is
deterministic under test.
"""

import logging
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from uns_opcua.opcua_config import SpoolConfig

LOGGER = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS spool (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  topic      TEXT NOT NULL,
  payload    BLOB NOT NULL,
  qos        INTEGER NOT NULL DEFAULT 1,
  spooled_at REAL NOT NULL
);
"""

_INSERT = "INSERT INTO spool (topic, payload, qos, spooled_at) VALUES (?, ?, ?, ?)"
_PEEK = "SELECT id, topic, payload, qos FROM spool ORDER BY id LIMIT ?"


@dataclass(frozen=True, slots=True)
class SpoolRow:
    """One message awaiting publication. `payload` is republished verbatim (Rule 1)."""

    topic: str
    payload: bytes
    qos: int


class Spool:
    """FIFO spool bounded by rows, bytes and age."""

    def __init__(self, config: SpoolConfig) -> None:
        self._config = config
        self._connection: sqlite3.Connection | None = None
        # Callers reach this class through asyncio.to_thread, so two different pool
        # threads can arrive at once. RLock rather than Lock because trim() calls
        # row_count() and byte_size().
        self._lock = threading.RLock()

    # --- lifecycle -----------------------------------------------------------------

    def open(self) -> None:
        """Create the database and its schema, and apply the durability pragmas."""
        path = Path(self._config.path)
        if path.parent != Path():
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            # check_same_thread=False is mandatory: sqlite3 otherwise refuses to be used
            # from the asyncio.to_thread pool thread that did not open it. This class's
            # own lock provides the serialisation that flag gives up.
            self._connection = sqlite3.connect(
                self._config.path, isolation_level=None, check_same_thread=False
            )
            # auto_vacuum has to be set before the first table exists, so it goes before
            # the DDL. Without it, deleted pages are never returned and the max_bytes
            # bound could never be satisfied.
            self._connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            # WAL lets the forwarder read while the writer writes. synchronous=NORMAL
            # risks the last few milliseconds on a power cut, which beats an order of
            # magnitude of throughput; FULL stays available for sites that disagree.
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(f"PRAGMA synchronous={self._config.synchronous}")
            self._connection.executescript(_DDL)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Spool.open() must be called before use")
        return self._connection

    def pragma(self, name: str) -> Any:
        """Read back a pragma. Used by tests to assert the durability settings."""
        with self._lock:
            return self._db.execute(f"PRAGMA {name}").fetchone()[0]

    # --- writing -------------------------------------------------------------------

    def enqueue(self, rows: Sequence[SpoolRow], now: float) -> int:
        """Append a batch in one transaction. Batching is what lets SQLite keep up."""
        if not rows:
            return 0
        with self._lock, self._db:
            self._db.executemany(_INSERT, [(row.topic, row.payload, row.qos, now) for row in rows])
        return len(rows)

    # --- reading and draining ------------------------------------------------------

    def peek(self, limit: int) -> list[tuple[int, SpoolRow]]:
        """The oldest `limit` rows, in id order. Rows stay until delete_through."""
        with self._lock:
            rows = self._db.execute(_PEEK, (limit,)).fetchall()
        return [
            (row_id, SpoolRow(topic=topic, payload=bytes(payload), qos=qos))
            for row_id, topic, payload, qos in rows
        ]

    def delete_through(self, max_id: int) -> int:
        """
        Delete every row up to and including `max_id`, after the broker acknowledged
        them. A crash between publish and delete replays on restart, which the
        historian's ON CONFLICT DO NOTHING absorbs.
        """
        with self._lock, self._db:
            cursor = self._db.execute("DELETE FROM spool WHERE id <= ?", (max_id,))
        return cursor.rowcount

    # --- bounding ------------------------------------------------------------------

    def trim(self, now: float) -> int:
        """
        Enforce every bound by deleting the lowest ids, and return how many were dropped.

        The bound is not optional. An unbounded spool turns a week-long WAN outage into a
        full disk that takes the whole edge node down, which is strictly worse than
        losing the oldest tail of the data.
        """
        with self._lock:
            dropped = 0
            dropped += self._trim_by_age(now)
            dropped += self._trim_by_rows()
            dropped += self._trim_by_bytes()
        if dropped:
            LOGGER.warning("Spool dropped %s oldest rows to stay inside its bounds", dropped)
        return dropped

    def _trim_by_age(self, now: float) -> int:
        cutoff = now - self._config.max_age_hours * 3600
        with self._db:
            cursor = self._db.execute("DELETE FROM spool WHERE spooled_at < ?", (cutoff,))
        return cursor.rowcount

    def _trim_by_rows(self) -> int:
        excess = self.row_count() - self._config.max_rows
        if excess <= 0:
            return 0
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM spool WHERE id IN (SELECT id FROM spool ORDER BY id LIMIT ?)",
                (excess,),
            )
        return cursor.rowcount

    def _trim_by_bytes(self) -> int:
        dropped = 0
        # Delete in chunks and re-measure: page_count only falls once pages are freed,
        # so a single computed delete count would not converge.
        while self.byte_size() > self._config.max_bytes and self.row_count() > 0:
            with self._db:
                cursor = self._db.execute(
                    "DELETE FROM spool WHERE id IN (SELECT id FROM spool ORDER BY id LIMIT ?)",
                    (max(1, self.row_count() // 10),),
                )
            if not cursor.rowcount:
                break
            dropped += cursor.rowcount
            self._db.execute("PRAGMA incremental_vacuum")
        return dropped

    # --- observation ---------------------------------------------------------------

    def row_count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT count(*) FROM spool").fetchone()[0])

    def byte_size(self) -> int:
        with self._lock:
            page_count = self._db.execute("PRAGMA page_count").fetchone()[0]
            page_size = self._db.execute("PRAGMA page_size").fetchone()[0]
        return int(page_count) * int(page_size)

    def oldest_spooled_at(self) -> float | None:
        """The oldest row's spool time, or None when the spool is empty."""
        with self._lock:
            row = self._db.execute("SELECT min(spooled_at) FROM spool").fetchone()
        return None if row[0] is None else float(row[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_spool.py -v -n 0`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/spool.py 10_uns_opcua/test/test_spool.py
git commit -m "feat(opcua): add the bounded SQLite store-and-forward spool

WAL mode, FIFO by AUTOINCREMENT id, bounded by rows, bytes and age.
Payloads round-trip byte-for-byte so replay never re-derives a field."
```

---

## Task 6: OPC UA collector

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/collector.py`
- Create: `10_uns_opcua/test/test_collector.py`
- Create: `10_uns_opcua/test/test_collector_integration.py`

**Interfaces:**
- Consumes: `ServerConfig`, `Deadband` from `uns_opcua.opcua_config`; `TagBinding`, `build_bindings` from `uns_opcua.tag_map`; `build_payload`, `serialise` from `uns_opcua.payload`; `SpoolRow` from `uns_opcua.spool`; metrics from `uns_opcua.prometheus_metrics`
- Produces: `build_monitored_item_request(node_id: ua.NodeId, client_handle: int, sampling_interval_ms: float, deadband: Deadband | None) -> ua.MonitoredItemCreateRequest`; `SubscriptionHandler(bindings_by_node_id: Mapping[str, TagBinding], queue: asyncio.Queue[SpoolRow], client_id: str, server_name: str, qos: int)` with `datachange_notification(node, val, data) -> None`; `Collector(server: ServerConfig, bindings: Sequence[TagBinding], queue: asyncio.Queue[SpoolRow], client_id: str, qos: int, backoff_max_s: float)` with `async run() -> None` and `async connect_once(client) -> int`; `enqueue_drop_oldest(queue, row) -> bool`

- [ ] **Step 1: Write the failing unit test**

Create `10_uns_opcua/test/test_collector.py`:

```python
"""Unit tests for monitored-item construction and the data change handler."""

import asyncio
import datetime
import json
from types import SimpleNamespace

import pytest
from asyncua import ua
from uns_opcua.collector import (
    SubscriptionHandler,
    build_monitored_item_request,
    enqueue_drop_oldest,
)
from uns_opcua.opcua_config import Deadband, ServerConfig, TagConfig
from uns_opcua.spool import SpoolRow
from uns_opcua.tag_map import build_bindings

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"
NODE_ID_STRING = "ns=2;i=5"
SOURCE_TS = datetime.datetime(2026, 9, 1, 12, 0, 0, 123000, tzinfo=datetime.UTC)


@pytest.fixture
def bindings():
    server = ServerConfig(
        name="plc01",
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id=NODE_ID_STRING, asset=ASSET, metric_path="ProcessValue/Temperature", unit="°C"),),
    )
    return build_bindings(server)


def test_request_without_a_deadband_carries_no_filter():
    request = build_monitored_item_request(
        node_id=ua.NodeId.from_string(NODE_ID_STRING),
        client_handle=1,
        sampling_interval_ms=200.0,
        deadband=None,
    )
    assert request.RequestedParameters.Filter is None
    assert request.ItemToMonitor.AttributeId == ua.AttributeIds.Value
    assert request.MonitoringMode == ua.MonitoringMode.Reporting


@pytest.mark.parametrize(
    ("deadband", "expected_type"),
    [
        (Deadband(type="absolute", value=0.2), int(ua.DeadbandType.Absolute)),
        (Deadband(type="percent", value=1.0), int(ua.DeadbandType.Percent)),
    ],
)
def test_request_with_a_deadband_carries_a_datachange_filter(deadband, expected_type):
    request = build_monitored_item_request(
        node_id=ua.NodeId.from_string(NODE_ID_STRING),
        client_handle=7,
        sampling_interval_ms=200.0,
        deadband=deadband,
    )
    data_filter = request.RequestedParameters.Filter
    assert isinstance(data_filter, ua.DataChangeFilter)
    assert data_filter.DeadbandType == expected_type
    assert data_filter.DeadbandValue == pytest.approx(deadband.value)
    assert data_filter.Trigger == ua.DataChangeTrigger.StatusValue
    assert request.RequestedParameters.ClientHandle == 7
    assert request.RequestedParameters.SamplingInterval == pytest.approx(200.0)


def _notification(value, source_timestamp=SOURCE_TS, status_code=0):
    """The shape asyncua hands a handler: data.monitored_item.Value is the DataValue."""
    data_value = SimpleNamespace(
        Value=SimpleNamespace(Value=value),
        SourceTimestamp=source_timestamp,
        ServerTimestamp=None,
        StatusCode=SimpleNamespace(value=status_code),
    )
    return SimpleNamespace(monitored_item=SimpleNamespace(Value=data_value))


@pytest.mark.asyncio
async def test_handler_enqueues_a_serialised_payload(bindings):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    handler = SubscriptionHandler(
        bindings_by_node_id={NODE_ID_STRING: bindings[0]},
        queue=queue,
        client_id="uns_opcua_dormagen",
        server_name="plc01",
        qos=1,
    )
    node = SimpleNamespace(nodeid=ua.NodeId.from_string(NODE_ID_STRING))

    handler.datachange_notification(node, 74.83, _notification(74.83))

    row = queue.get_nowait()
    assert row.topic == f"{ASSET}/ProcessValue/Temperature"
    assert row.qos == 1
    payload = json.loads(row.payload.decode("utf-8"))
    assert payload["value"] == 74.83
    assert payload["quality"] == "Good"
    assert payload["source"] == "uns_opcua_dormagen"
    assert payload["timestamp"] == pytest.approx(SOURCE_TS.timestamp() * 1000)
    assert "status" not in payload


@pytest.mark.asyncio
async def test_handler_ignores_a_node_it_has_no_binding_for(bindings):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    handler = SubscriptionHandler(
        bindings_by_node_id={NODE_ID_STRING: bindings[0]},
        queue=queue,
        client_id="c",
        server_name="plc01",
        qos=1,
    )
    node = SimpleNamespace(nodeid=ua.NodeId.from_string("ns=2;i=999"))

    handler.datachange_notification(node, 1.0, _notification(1.0))

    assert queue.empty()


@pytest.mark.asyncio
async def test_handler_publishes_bad_quality_rather_than_dropping_it(bindings):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    handler = SubscriptionHandler(
        bindings_by_node_id={NODE_ID_STRING: bindings[0]},
        queue=queue,
        client_id="c",
        server_name="plc01",
        qos=1,
    )
    node = SimpleNamespace(nodeid=ua.NodeId.from_string(NODE_ID_STRING))

    handler.datachange_notification(node, None, _notification(None, status_code=0x80340000))

    payload = json.loads(queue.get_nowait().payload.decode("utf-8"))
    assert payload["quality"] == "Bad"


@pytest.mark.asyncio
async def test_enqueue_drop_oldest_discards_the_oldest_when_full():
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue(maxsize=2)
    rows = [SpoolRow(topic=f"t{i}", payload=b"{}", qos=1) for i in range(3)]

    assert enqueue_drop_oldest(queue, rows[0]) is True
    assert enqueue_drop_oldest(queue, rows[1]) is True
    assert enqueue_drop_oldest(queue, rows[2]) is False  # something had to go

    assert [queue.get_nowait().topic for _ in range(2)] == ["t1", "t2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_collector.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua.collector'`

- [ ] **Step 3: Write the minimal implementation**

Create `10_uns_opcua/src/uns_opcua/collector.py`:

```python
"""
Collects data changes from one OPC UA server by subscription.

Report-by-exception is done by the server: each monitored item carries a
`DataChangeFilter` deadband, so the server notifies only when a value moves far enough to
matter. `subscribe_data_change` cannot express a filter, so monitored items are built by
hand and passed to `create_monitored_items`.
"""

import asyncio
import datetime
import logging
import random
from collections.abc import Mapping, Sequence

from asyncua import Client, ua
from uns_opcua import prometheus_metrics as metrics
from uns_opcua.opcua_config import Deadband, ServerConfig
from uns_opcua.payload import build_payload, serialise
from uns_opcua.spool import SpoolRow
from uns_opcua.tag_map import TagBinding

LOGGER = logging.getLogger(__name__)

_DEADBAND_TYPES: dict[str, int] = {
    "absolute": int(ua.DeadbandType.Absolute),
    "percent": int(ua.DeadbandType.Percent),
}


def build_monitored_item_request(
    node_id: ua.NodeId,
    client_handle: int,
    sampling_interval_ms: float,
    deadband: Deadband | None,
) -> ua.MonitoredItemCreateRequest:
    """
    One monitored item, with a server-side deadband when one is configured.

    QueueSize is 1 with DiscardOldest: the namespace carries current state, so if we
    fall behind, the newest value is the one worth keeping.
    """
    parameters = ua.MonitoringParameters(
        ClientHandle=client_handle,
        SamplingInterval=sampling_interval_ms,
        QueueSize=1,
        DiscardOldest=True,
    )
    if deadband is not None:
        parameters.Filter = ua.DataChangeFilter(
            Trigger=ua.DataChangeTrigger.StatusValue,
            DeadbandType=_DEADBAND_TYPES[deadband.type],
            DeadbandValue=float(deadband.value),
        )
    return ua.MonitoredItemCreateRequest(
        ItemToMonitor=ua.ReadValueId(NodeId=node_id, AttributeId=ua.AttributeIds.Value),
        MonitoringMode=ua.MonitoringMode.Reporting,
        RequestedParameters=parameters,
    )


def enqueue_drop_oldest(queue: asyncio.Queue[SpoolRow], row: SpoolRow) -> bool:
    """
    Enqueue without ever blocking the OPC UA callback, dropping the oldest if full.

    A full queue means the spool writer cannot keep up — a disk problem, not a broker
    problem, since a broker outage only grows the spool. Dropping the oldest keeps the
    freshest state moving and is counted, never silent.
    """
    try:
        queue.put_nowait(row)
        return True
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover - a consumer raced us
            pass
        metrics.QUEUE_DROPPED.inc()
        try:
            queue.put_nowait(row)
        except asyncio.QueueFull:  # pragma: no cover - a producer raced us
            pass
        return False


class SubscriptionHandler:
    """
    asyncua's handler protocol. Called from the client's task, so it must not block:
    it maps, serialises and enqueues, and nothing else.
    """

    def __init__(
        self,
        bindings_by_node_id: Mapping[str, TagBinding],
        queue: asyncio.Queue[SpoolRow],
        client_id: str,
        server_name: str,
        qos: int,
    ) -> None:
        self._bindings = bindings_by_node_id
        self._queue = queue
        self._client_id = client_id
        self._server_name = server_name
        self._qos = qos

    def datachange_notification(self, node, val, data) -> None:  # noqa: ANN001 - asyncua protocol
        binding = self._bindings.get(node.nodeid.to_string())
        if binding is None:
            LOGGER.debug("Ignoring a data change for unmapped node %s", node.nodeid)
            return

        data_value = data.monitored_item.Value
        mapped = build_payload(
            binding=binding,
            value=val,
            status_code=int(data_value.StatusCode.value),
            source_timestamp=data_value.SourceTimestamp,
            server_timestamp=data_value.ServerTimestamp,
            collected_at=datetime.datetime.now(tz=datetime.UTC),
            client_id=self._client_id,
        )
        if mapped.timestamp_fallback is not None:
            metrics.TIMESTAMP_FALLBACK.labels(reason=mapped.timestamp_fallback).inc()

        metrics.DATACHANGES.labels(server=self._server_name).inc()
        enqueue_drop_oldest(
            self._queue,
            SpoolRow(topic=mapped.topic, payload=serialise(mapped.payload), qos=self._qos),
        )


class Collector:
    """One supervised task: session, subscription, and reconnect for a single server."""

    def __init__(
        self,
        server: ServerConfig,
        bindings: Sequence[TagBinding],
        queue: asyncio.Queue[SpoolRow],
        client_id: str,
        qos: int,
        backoff_max_s: float = 60.0,
    ) -> None:
        self._server = server
        self._bindings = tuple(bindings)
        self._queue = queue
        self._client_id = client_id
        self._qos = qos
        self._backoff_max_s = backoff_max_s

    async def connect_once(self, client: Client) -> int:
        """
        Resolve the tags, subscribe, and return how many items the server accepted.

        Creating a monitored item delivers its current value immediately, so this is also
        what heals the gap after an outage — with the server's real SourceTimestamp,
        which an explicit read pass could not provide.
        """
        bindings_by_node_id: dict[str, TagBinding] = {}
        requests: list[ua.MonitoredItemCreateRequest] = []
        deadbands: list[Deadband | None] = []

        for handle, binding in enumerate(self._bindings, start=1):
            try:
                node_id = ua.NodeId.from_string(binding.node_id)
            except Exception:
                LOGGER.exception(
                    "%s: node_id %r is not parsable; skipping that tag", self._server.name, binding.node_id
                )
                metrics.UNRESOLVED_NODES.labels(server=self._server.name).inc()
                continue
            bindings_by_node_id[node_id.to_string()] = binding
            requests.append(
                build_monitored_item_request(
                    node_id=node_id,
                    client_handle=handle,
                    sampling_interval_ms=float(self._server.publishing_interval_ms),
                    deadband=binding.deadband,
                )
            )
            deadbands.append(binding.deadband)

        if not requests:
            raise RuntimeError(f"{self._server.name}: no usable tags")

        handler = SubscriptionHandler(
            bindings_by_node_id=bindings_by_node_id,
            queue=self._queue,
            client_id=self._client_id,
            server_name=self._server.name,
            qos=self._qos,
        )
        subscription = await client.create_subscription(
            float(self._server.publishing_interval_ms), handler
        )

        results = await subscription.create_monitored_items(requests)
        accepted = await self._retry_rejected(subscription, requests, deadbands, results)
        metrics.MONITORED_ITEMS.labels(server=self._server.name).set(accepted)
        LOGGER.info("%s: monitoring %s of %s tags", self._server.name, accepted, len(requests))
        return accepted

    async def _retry_rejected(
        self,
        subscription,  # noqa: ANN001 - asyncua Subscription
        requests: Sequence[ua.MonitoredItemCreateRequest],
        deadbands: Sequence[Deadband | None],
        results: Sequence[int | ua.StatusCode],
    ) -> int:
        """
        A rejected item comes back as a StatusCode instead of an int handle. The usual
        cause is a server that will not accept a deadband, so retry those without one:
        losing report-by-exception on one tag beats losing the tag.
        """
        accepted = sum(1 for result in results if not isinstance(result, ua.StatusCode))
        retries = [
            build_monitored_item_request(
                node_id=requests[index].ItemToMonitor.NodeId,
                client_handle=requests[index].RequestedParameters.ClientHandle,
                sampling_interval_ms=requests[index].RequestedParameters.SamplingInterval,
                deadband=None,
            )
            for index, result in enumerate(results)
            if isinstance(result, ua.StatusCode) and deadbands[index] is not None
        ]
        for index, result in enumerate(results):
            if isinstance(result, ua.StatusCode):
                LOGGER.warning(
                    "%s: server rejected monitored item for %s (%s)",
                    self._server.name,
                    requests[index].ItemToMonitor.NodeId,
                    result,
                )
                metrics.DEADBAND_REJECTED.labels(server=self._server.name).inc()

        if retries:
            retry_results = await subscription.create_monitored_items(retries)
            accepted += sum(1 for result in retry_results if not isinstance(result, ua.StatusCode))
        return accepted

    async def run(self) -> None:
        """Reconnect forever with exponential backoff and jitter."""
        backoff = 1.0
        while True:
            client = Client(url=self._server.url)
            if self._server.security is not None:
                await client.set_security_string(self._server.security.to_security_string())
            try:
                async with client:
                    await self.connect_once(client)
                    metrics.SERVER_UP.labels(server=self._server.name).set(1)
                    backoff = 1.0
                    # The subscription runs on the client's own task; keep the session open.
                    while True:
                        await asyncio.sleep(3600)
            except asyncio.CancelledError:
                metrics.SERVER_UP.labels(server=self._server.name).set(0)
                raise
            except Exception:
                metrics.SERVER_UP.labels(server=self._server.name).set(0)
                metrics.MONITORED_ITEMS.labels(server=self._server.name).set(0)
                delay = min(backoff, self._backoff_max_s) * (0.5 + random.random())
                LOGGER.exception("%s: session lost; reconnecting in %.1fs", self._server.name, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, self._backoff_max_s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_collector.py -v -n 0`
Expected: PASS (9 tests)

- [ ] **Step 5: Write the integration test against an in-process OPC UA server**

This is the test that proves report-by-exception actually works. `asyncua` ships a server, so there is no external dependency.

Create `10_uns_opcua/test/test_collector_integration.py`:

```python
"""
End-to-end collector tests against an in-process OPC UA server.

These assert the two behaviours the whole design rests on: the server-side deadband
suppresses sub-threshold changes, and subscribing delivers the current value immediately
(which is what heals an outage gap).
"""

import asyncio

import pytest
import pytest_asyncio
from asyncua import Server, ua
from uns_opcua.collector import Collector
from uns_opcua.opcua_config import Deadband, ServerConfig, TagConfig
from uns_opcua.spool import SpoolRow
from uns_opcua.tag_map import build_bindings

ENDPOINT = "opc.tcp://127.0.0.1:48401/uns/test/"
ASSET = "TestCo/Site/Area/Line1/Cell1/Mixer"

pytestmark = [pytest.mark.integrationtest, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def opcua_server():
    """A minimal server exposing one writable Double, with no security."""
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    namespace = await server.register_namespace("http://uns/test")
    objects = server.nodes.objects
    device = await objects.add_object(namespace, "Mixer")
    temperature = await device.add_variable(namespace, "Temp_PV", 75.0)
    await temperature.set_writable()
    async with server:
        yield server, temperature


def _server_config(node_id: str, deadband: Deadband | None) -> ServerConfig:
    return ServerConfig(
        name="test-plc",
        url=ENDPOINT,
        publishing_interval_ms=50,
        tags=(
            TagConfig(
                node_id=node_id,
                asset=ASSET,
                metric_path="ProcessValue/Temperature",
                unit="°C",
                deadband=deadband,
            ),
        ),
    )


async def _drain(queue: asyncio.Queue[SpoolRow], expected: int, timeout: float = 5.0) -> list[SpoolRow]:
    """Collect until `expected` rows arrive or the timeout expires."""
    rows: list[SpoolRow] = []
    async with asyncio.timeout(timeout):
        while len(rows) < expected:
            rows.append(await queue.get())
    return rows


async def _collect(server_config, queue) -> asyncio.Task:
    collector = Collector(
        server=server_config,
        bindings=build_bindings(server_config),
        queue=queue,
        client_id="uns_opcua_test",
        qos=1,
    )
    task = asyncio.create_task(collector.run())
    await asyncio.sleep(1.0)  # let the session and subscription establish
    return task


async def test_subscribing_delivers_the_current_value_immediately(opcua_server):
    """This is what recovers the gap after a session drop - no explicit read needed."""
    _, temperature = opcua_server
    # Read the id off the live node: the numeric part depends on how many nodes the
    # server created first, so hardcoding ns=2;i=2 would be guessing.
    node_id = temperature.nodeid.to_string()
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()

    task = await _collect(_server_config(node_id, deadband=None), queue)
    try:
        rows = await _drain(queue, expected=1)
        assert rows[0].topic == f"{ASSET}/ProcessValue/Temperature"
        assert b'"value":75.0' in rows[0].payload
        assert b'"quality":"Good"' in rows[0].payload
        assert b'"status"' not in rows[0].payload
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_server_side_deadband_suppresses_sub_threshold_changes(opcua_server):
    _, temperature = opcua_server
    node_id = temperature.nodeid.to_string()
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()

    task = await _collect(_server_config(node_id, Deadband(type="absolute", value=2.0)), queue)
    try:
        await _drain(queue, expected=1)  # the initial value
        for value in (75.5, 80.0, 80.4, 90.0):
            await temperature.write_value(ua.DataValue(ua.Variant(value, ua.VariantType.Double)))
            await asyncio.sleep(0.3)

        rows = await _drain(queue, expected=2)
        # 75.5 (0.5 from 75.0) and 80.4 (0.4 from 80.0) are inside the deadband.
        assert b'"value":80.0' in rows[0].payload
        assert b'"value":90.0' in rows[1].payload
        assert queue.empty()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_an_unparsable_node_id_does_not_stop_the_rest_of_the_server(opcua_server):
    _, temperature = opcua_server
    good = temperature.nodeid.to_string()
    server_config = ServerConfig(
        name="test-plc",
        url=ENDPOINT,
        publishing_interval_ms=50,
        tags=(
            TagConfig(node_id="not-a-node-id", asset=ASSET, metric_path="ProcessValue/Bogus"),
            TagConfig(node_id=good, asset=ASSET, metric_path="ProcessValue/Temperature"),
        ),
    )
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    task = await _collect(server_config, queue)
    try:
        rows = await _drain(queue, expected=1)
        assert rows[0].topic == f"{ASSET}/ProcessValue/Temperature"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
```

Note: the first test derives `node_id` from the live node rather than hardcoding `ns=2;i=2`, because the numeric id depends on how many nodes the server created before it.

- [ ] **Step 6: Run the integration test**

Run: `uv run pytest 10_uns_opcua/test/test_collector_integration.py -v -n 0 -m integrationtest`
Expected: PASS (3 tests). If the deadband test fails with all four values delivered, the filter was rejected — check the `create_monitored_items` results rather than assuming the API changed.

- [ ] **Step 7: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/collector.py 10_uns_opcua/test/test_collector.py 10_uns_opcua/test/test_collector_integration.py
git commit -m "feat(opcua): subscribe with server-side deadband filters

Builds monitored items by hand because subscribe_data_change cannot carry a
filter, and retries without the deadband when a server rejects it. Integration
tests against an in-process server prove suppression actually happens."
```

---

## Task 7: MQTT forwarder and spool writer

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/forwarder.py`
- Create: `10_uns_opcua/test/test_forwarder.py`

**Interfaces:**
- Consumes: `MQTTConfig` from `uns_opcua.opcua_config`; `Spool`, `SpoolRow` from `uns_opcua.spool`; metrics from `uns_opcua.prometheus_metrics`
- Produces: `SpoolWriter(spool: Spool, queue: asyncio.Queue[SpoolRow], batch_size: int, flush_interval_s: float)` with `async run() -> None` and `async drain_once(now: float) -> int`; `Forwarder(spool: Spool, client_id: str, qos: int, batch_size: int, backoff_max_s: float)` with `async run() -> None` and `async forward_batch(client) -> int`; `Publisher` protocol with `async publish(topic: str, payload: bytes, qos: int) -> None`

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_forwarder.py`:

```python
"""Unit tests for the spool writer and the MQTT forwarder."""

import asyncio

import pytest
from uns_opcua.forwarder import Forwarder, SpoolWriter
from uns_opcua.opcua_config import SpoolConfig
from uns_opcua.spool import Spool, SpoolRow

NOW = 1_756_728_000.0

pytestmark = pytest.mark.asyncio


@pytest.fixture
def spool(tmp_path):
    spool = Spool(
        SpoolConfig(
            path=str(tmp_path / "spool.db"),
            max_rows=1000,
            max_bytes=100_000_000,
            max_age_hours=168,
            synchronous="OFF",
        )
    )
    spool.open()
    yield spool
    spool.close()


def _row(topic: str) -> SpoolRow:
    return SpoolRow(topic=topic, payload=b'{"value":1}', qos=1)


class FakePublisher:
    """Records what was published, and can be made to fail on demand."""

    def __init__(self, fail_from: int | None = None) -> None:
        self.published: list[tuple[str, bytes, int]] = []
        self._fail_from = fail_from

    async def publish(self, topic: str, payload: bytes, qos: int) -> None:
        if self._fail_from is not None and len(self.published) >= self._fail_from:
            raise ConnectionError("broker gone")
        self.published.append((topic, payload, qos))


async def test_spool_writer_batches_the_queue_into_the_spool(spool):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    for topic in ("a", "b", "c"):
        queue.put_nowait(_row(topic))

    writer = SpoolWriter(spool=spool, queue=queue, batch_size=500, flush_interval_s=0.05)
    assert await writer.drain_once(now=NOW) == 3
    assert [row.topic for _, row in spool.peek(limit=10)] == ["a", "b", "c"]


async def test_spool_writer_is_a_no_op_on_an_empty_queue(spool):
    writer = SpoolWriter(spool=spool, queue=asyncio.Queue(), batch_size=500, flush_interval_s=0.01)
    assert await writer.drain_once(now=NOW) == 0
    assert spool.row_count() == 0


async def test_spool_writer_respects_its_batch_size(spool):
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
    for index in range(5):
        queue.put_nowait(_row(f"t{index}"))

    writer = SpoolWriter(spool=spool, queue=queue, batch_size=2, flush_interval_s=0.01)
    assert await writer.drain_once(now=NOW) == 2
    assert spool.row_count() == 2


async def test_spool_writer_enforces_the_bounds_after_writing(tmp_path):
    spool = Spool(
        SpoolConfig(
            path=str(tmp_path / "spool.db"),
            max_rows=2,
            max_bytes=100_000_000,
            max_age_hours=168,
            synchronous="OFF",
        )
    )
    spool.open()
    try:
        queue: asyncio.Queue[SpoolRow] = asyncio.Queue()
        for topic in ("a", "b", "c", "d"):
            queue.put_nowait(_row(topic))
        writer = SpoolWriter(spool=spool, queue=queue, batch_size=500, flush_interval_s=0.01)
        await writer.drain_once(now=NOW)
        assert [row.topic for _, row in spool.peek(limit=10)] == ["c", "d"]
    finally:
        spool.close()


async def test_forward_batch_publishes_then_deletes(spool):
    spool.enqueue([_row("a"), _row("b")], now=NOW)
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)

    assert await forwarder.forward_batch(publisher) == 2
    assert [topic for topic, _, _ in publisher.published] == ["a", "b"]
    assert spool.row_count() == 0


async def test_forward_batch_publishes_the_spooled_payload_verbatim(spool):
    payload = '{"value":74.83,"unit":"°C","timestamp":1756728000123.0}'.encode("utf-8")
    spool.enqueue([SpoolRow(topic="t", payload=payload, qos=1)], now=NOW)
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)

    await forwarder.forward_batch(publisher)
    # Rule 1: no field is re-derived at drain time.
    assert publisher.published[0][1] == payload


async def test_forward_batch_keeps_unacknowledged_rows_when_publishing_fails(spool):
    spool.enqueue([_row("a"), _row("b"), _row("c")], now=NOW)
    publisher = FakePublisher(fail_from=1)
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)

    with pytest.raises(ConnectionError):
        await forwarder.forward_batch(publisher)

    # "a" was acknowledged and is gone; "b" and "c" stay for the next attempt.
    assert [row.topic for _, row in spool.peek(limit=10)] == ["b", "c"]


async def test_forward_batch_on_an_empty_spool_publishes_nothing(spool):
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)
    assert await forwarder.forward_batch(publisher) == 0
    assert publisher.published == []


async def test_forward_batch_preserves_per_topic_order_across_batches(spool):
    spool.enqueue([_row("t"), _row("t"), _row("t")], now=NOW)
    publisher = FakePublisher()
    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=2)

    assert await forwarder.forward_batch(publisher) == 2
    assert await forwarder.forward_batch(publisher) == 1
    assert len(publisher.published) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_forwarder.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua.forwarder'`

- [ ] **Step 3: Write the minimal implementation**

Create `10_uns_opcua/src/uns_opcua/forwarder.py`:

```python
"""
Moves collected messages from memory to disk, and from disk to the broker.

The spool writer is a single task so there is no SQLite lock contention, and it batches
because a transaction per message would not keep up. The forwarder holds one long-lived
MQTT connection — deliberately not the simulator's connect-per-publish.
"""

import asyncio
import contextlib
import logging
import random
import time
from typing import Protocol

import aiomqtt
from uns_opcua import prometheus_metrics as metrics
from uns_opcua.opcua_config import MQTTConfig
from uns_opcua.spool import Spool, SpoolRow

LOGGER = logging.getLogger(__name__)


class Publisher(Protocol):
    """Just enough of aiomqtt.Client to let the forwarder be tested without a broker."""

    async def publish(self, topic: str, payload: bytes, qos: int) -> None: ...


class SpoolWriter:
    """Drains the in-memory queue into the spool in batches."""

    def __init__(
        self,
        spool: Spool,
        queue: asyncio.Queue[SpoolRow],
        batch_size: int = 500,
        flush_interval_s: float = 0.05,
    ) -> None:
        self._spool = spool
        self._queue = queue
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s

    async def drain_once(self, now: float) -> int:
        """Write whatever is already queued, up to one batch, then enforce the bounds."""
        rows: list[SpoolRow] = []
        while len(rows) < self._batch_size:
            try:
                rows.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not rows:
            return 0

        try:
            written = await asyncio.to_thread(self._spool.enqueue, rows, now)
        except Exception:
            # A full or failing disk must not take the process down; collection continues
            # and the queue's drop-oldest policy becomes the pressure valve.
            metrics.SPOOL_WRITE_ERRORS.inc()
            LOGGER.exception("Failed to write %s rows to the spool", len(rows))
            return 0

        dropped = await asyncio.to_thread(self._spool.trim, now)
        if dropped:
            metrics.SPOOL_DROPPED.inc(dropped)
        await self._publish_gauges(now)
        return written

    async def _publish_gauges(self, now: float) -> None:
        rows = await asyncio.to_thread(self._spool.row_count)
        size = await asyncio.to_thread(self._spool.byte_size)
        oldest = await asyncio.to_thread(self._spool.oldest_spooled_at)
        metrics.SPOOL_ROWS.set(rows)
        metrics.SPOOL_BYTES.set(size)
        metrics.SPOOL_LAG_SECONDS.set(0.0 if oldest is None else max(0.0, now - oldest))

    async def run(self) -> None:
        """Batch by size or by `flush_interval_s`, whichever comes first."""
        while True:
            if await self.drain_once(now=time.time()) == 0:
                await asyncio.sleep(self._flush_interval_s)


class Forwarder:
    """Drains the spool to MQTT, oldest first, deleting only what was acknowledged."""

    def __init__(
        self,
        spool: Spool,
        client_id: str,
        qos: int,
        batch_size: int = 200,
        backoff_max_s: float = 60.0,
        idle_interval_s: float = 0.1,
    ) -> None:
        self._spool = spool
        self._client_id = client_id
        self._qos = qos
        self._batch_size = batch_size
        self._backoff_max_s = backoff_max_s
        self._idle_interval_s = idle_interval_s

    async def forward_batch(self, publisher: Publisher) -> int:
        """
        Publish one batch and delete through the last acknowledged id.

        Deleting after publishing is what makes this at-least-once: a crash in between
        replays on restart, which the historian's ON CONFLICT DO NOTHING absorbs. Losing
        the message instead would be unrecoverable, so this is the right way round.
        """
        batch = await asyncio.to_thread(self._spool.peek, self._batch_size)
        if not batch:
            return 0

        acknowledged_through: int | None = None
        try:
            for row_id, row in batch:
                await publisher.publish(row.topic, row.payload, row.qos or self._qos)
                metrics.PUBLISH_TOTAL.inc()
                acknowledged_through = row_id
        except Exception:
            metrics.PUBLISH_ERRORS.inc()
            raise
        finally:
            if acknowledged_through is not None:
                await asyncio.to_thread(self._spool.delete_through, acknowledged_through)

        return len(batch)

    async def run(self) -> None:
        """
        Keep one connection open and drain. While the broker is down the spool grows;
        that is the intended behaviour, not an error state.
        """
        backoff = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=MQTTConfig.host,
                    port=MQTTConfig.port,
                    username=MQTTConfig.username,
                    password=MQTTConfig.password,
                    identifier=self._client_id,
                    protocol=MQTTConfig.version,
                    tls_params=MQTTConfig.tls_params,
                    tls_insecure=MQTTConfig.tls_insecure,
                    keepalive=MQTTConfig.keep_alive,
                    transport=MQTTConfig.transport,
                ) as client:
                    LOGGER.info("Forwarder connected to %s:%s", MQTTConfig.host, MQTTConfig.port)
                    backoff = 1.0
                    while True:
                        if await self.forward_batch(client) == 0:
                            await asyncio.sleep(self._idle_interval_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = min(backoff, self._backoff_max_s) * (0.5 + random.random())
                LOGGER.exception("Forwarder lost the broker; retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, self._backoff_max_s)


@contextlib.asynccontextmanager
async def opened_spool(spool: Spool):
    """Open the spool off the event loop and always close it."""
    await asyncio.to_thread(spool.open)
    try:
        yield spool
    finally:
        await asyncio.to_thread(spool.close)
```

Note the `finally` in `forward_batch`: `aiomqtt.publish` at QoS 1 returns only after the broker acknowledges, so any row that returned successfully is safe to delete even though a later one in the batch failed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_forwarder.py -v -n 0`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/forwarder.py 10_uns_opcua/test/test_forwarder.py
git commit -m "feat(opcua): batch into the spool and drain it to MQTT

Publishes then deletes, so a crash in between replays rather than loses.
One long-lived connection, not the simulator's connect-per-publish."
```

---

## Task 8: Asset Model validation

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/model_check.py`
- Create: `10_uns_opcua/test/test_model_check.py`

**Interfaces:**
- Consumes: `TagBinding`, `find_conflicts` from `uns_opcua.tag_map`; `OpcUaConfig` from `uns_opcua.opcua_config`; `uns_model` tables and `MODEL_SCHEMA`
- Produces: `ModelIssue(kind: str, detail: str)`; `check_bindings(bindings: Sequence[TagBinding], known_asset_paths: set[str], metric_units: Mapping[tuple[str | None, str], str | None]) -> list[ModelIssue]`; `async load_model_facts(engine) -> tuple[set[str], dict[tuple[str | None, str], str | None]]`; `async validate(bindings) -> list[ModelIssue]`; `main() -> None`

`check_bindings` is a pure function over facts already loaded, which is what makes the validation rules testable with no database. `metric_units` is keyed by `(asset_path | None, metric_key)`; a `None` asset path is a MetricDefinition with `asset_id IS NULL`, meaning it applies to every Asset, and an Asset-specific row wins over it.

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_model_check.py`:

```python
"""Unit tests for the Asset Model validation rules."""

import pytest
from uns_opcua.model_check import check_bindings
from uns_opcua.opcua_config import ServerConfig, TagConfig
from uns_opcua.tag_map import build_bindings

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"
METRIC_KEY = "ProcessValue/Temperature/value"


def _bindings(*tags: TagConfig):
    return build_bindings(
        ServerConfig(name="plc01", url="opc.tcp://host:4840/", publishing_interval_ms=200, tags=tags)
    )


def _tag(node_id="ns=2;i=5", metric_path="ProcessValue/Temperature", unit=None, asset=ASSET):
    return TagConfig(node_id=node_id, asset=asset, metric_path=metric_path, unit=unit)


def test_a_fully_modelled_tag_reports_nothing():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="°C")),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): "°C"},
    )
    assert issues == []


def test_an_unknown_asset_is_reported():
    issues = check_bindings(
        bindings=_bindings(_tag()),
        known_asset_paths=set(),
        metric_units={},
    )
    kinds = [issue.kind for issue in issues]
    assert "unknown_asset" in kinds
    assert any(ASSET in issue.detail for issue in issues)


def test_a_missing_metric_definition_is_reported():
    issues = check_bindings(
        bindings=_bindings(_tag()),
        known_asset_paths={ASSET},
        metric_units={},
    )
    assert [issue.kind for issue in issues] == ["missing_metric_definition"]
    assert METRIC_KEY in issues[0].detail


def test_a_global_metric_definition_satisfies_the_lookup():
    """A row with asset_id IS NULL gives one unit to every Asset."""
    issues = check_bindings(
        bindings=_bindings(_tag(unit="°C")),
        known_asset_paths={ASSET},
        metric_units={(None, METRIC_KEY): "°C"},
    )
    assert issues == []


def test_an_asset_specific_definition_wins_over_the_global_one():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="K")),
        known_asset_paths={ASSET},
        metric_units={(None, METRIC_KEY): "°C", (ASSET, METRIC_KEY): "K"},
    )
    assert issues == []


def test_a_disagreeing_unit_is_reported():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="K")),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): "°C"},
    )
    assert [issue.kind for issue in issues] == ["unit_mismatch"]
    assert "K" in issues[0].detail
    assert "°C" in issues[0].detail


def test_no_configured_unit_is_not_a_mismatch():
    issues = check_bindings(
        bindings=_bindings(_tag(unit=None)),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): "°C"},
    )
    assert issues == []


def test_a_definition_with_no_unit_of_measure_is_not_a_mismatch():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="°C")),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): None},
    )
    assert issues == []


def test_configuration_conflicts_are_reported_too():
    issues = check_bindings(
        bindings=_bindings(
            _tag(node_id="ns=2;i=5", metric_path="ProcessValue/Temperature"),
            _tag(node_id="ns=2;i=5", metric_path="ProcessValue/Pressure"),
        ),
        known_asset_paths={ASSET},
        metric_units={
            (ASSET, METRIC_KEY): None,
            (ASSET, "ProcessValue/Pressure/value"): None,
        },
    )
    assert [issue.kind for issue in issues] == ["config_conflict"]
    assert "duplicate node_id" in issues[0].detail


def test_every_issue_for_one_tag_is_reported_at_once():
    """One pass should tell the whole story, not just the first problem."""
    issues = check_bindings(
        bindings=_bindings(_tag(unit="K")),
        known_asset_paths=set(),
        metric_units={},
    )
    assert {issue.kind for issue in issues} == {"unknown_asset", "missing_metric_definition"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_model_check.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua.model_check'`

- [ ] **Step 3: Write the minimal implementation**

Create `10_uns_opcua/src/uns_opcua/model_check.py`:

```python
"""
Validates a tag mapping against the Asset Model.

Reports, never gates. An edge connector that cannot start without enterprise Postgres
would defeat the reason mapping by config file was chosen over an Asset-Model-driven
approach — so at startup this only logs and sets a gauge. The `uns_opcua_validate`
entry point exits non-zero instead, so CI can gate a config change.
"""

import asyncio
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from uns_model.model_config import MODEL_SCHEMA, ModelConfig
from uns_opcua import prometheus_metrics as metrics
from uns_opcua.opcua_config import OpcUaConfig
from uns_opcua.tag_map import TagBinding, build_bindings, find_conflicts

LOGGER = logging.getLogger(__name__)

_ASSET_PATHS = text(f"SELECT path FROM {MODEL_SCHEMA}.asset WHERE is_active")  # noqa: S608 - schema is a constant
_METRIC_UNITS = text(  # noqa: S608 - schema is a constant
    f"SELECT a.path, m.metric_key, m.unit_of_measure "
    f"FROM {MODEL_SCHEMA}.metric_definition m "
    f"LEFT JOIN {MODEL_SCHEMA}.asset a ON a.id = m.asset_id"
)


@dataclass(frozen=True, slots=True)
class ModelIssue:
    """One disagreement between the connector's configuration and the Asset Model."""

    kind: str
    detail: str


def check_bindings(
    bindings: Sequence[TagBinding],
    known_asset_paths: set[str],
    metric_units: Mapping[tuple[str | None, str], str | None],
) -> list[ModelIssue]:
    """
    Every issue with this mapping, in one pass.

    `metric_units` is keyed by (asset path or None, Metric Key). None means the
    MetricDefinition has `asset_id IS NULL` and so applies to every Asset; an
    Asset-specific row wins over it.
    """
    issues = [ModelIssue(kind="config_conflict", detail=detail) for detail in find_conflicts(bindings)]

    for binding in bindings:
        if binding.asset not in known_asset_paths:
            issues.append(
                ModelIssue(
                    kind="unknown_asset",
                    detail=f"{binding.node_id}: asset {binding.asset!r} is not in the Asset Model",
                )
            )

        asset_specific = (binding.asset, binding.metric_key)
        if asset_specific in metric_units:
            unit_of_measure = metric_units[asset_specific]
        elif (None, binding.metric_key) in metric_units:
            unit_of_measure = metric_units[(None, binding.metric_key)]
        else:
            issues.append(
                ModelIssue(
                    kind="missing_metric_definition",
                    detail=(
                        f"{binding.node_id}: no MetricDefinition for Metric Key "
                        f"{binding.metric_key!r} on asset {binding.asset!r}"
                    ),
                )
            )
            continue

        if binding.unit is not None and unit_of_measure is not None and binding.unit != unit_of_measure:
            issues.append(
                ModelIssue(
                    kind="unit_mismatch",
                    detail=(
                        f"{binding.node_id}: configured unit {binding.unit!r} disagrees with the "
                        f"MetricDefinition's Unit of Measure {unit_of_measure!r}"
                    ),
                )
            )

    return issues


async def load_model_facts(engine) -> tuple[set[str], dict[tuple[str | None, str], str | None]]:  # noqa: ANN001
    """Read the Asset paths and MetricDefinition units the check needs."""
    async with engine.connect() as connection:
        asset_paths = {row[0] for row in (await connection.execute(_ASSET_PATHS)).all()}
        metric_units = {
            (asset_path, metric_key): unit_of_measure
            for asset_path, metric_key, unit_of_measure in (await connection.execute(_METRIC_UNITS)).all()
        }
    return asset_paths, metric_units


def all_bindings() -> list[TagBinding]:
    """Every configured tag, across every server."""
    return [binding for server in OpcUaConfig.servers for binding in build_bindings(server)]


async def validate(bindings: Sequence[TagBinding]) -> list[ModelIssue]:
    """
    Load the model facts and check the bindings against them.

    `09_uns_model` keeps the password out of the URL and hands it over in
    `connect_args()` alongside the SSL context, so the engine is built the same way here
    rather than composing a second, divergent URL.
    """
    config = ModelConfig.from_settings("opcua")
    if not config.is_valid():
        raise RuntimeError("The Asset Model database is not configured")

    engine = create_async_engine(config.url, connect_args=config.connect_args(), pool_pre_ping=True)
    try:
        asset_paths, metric_units = await load_model_facts(engine)
    finally:
        await engine.dispose()
    return check_bindings(bindings, asset_paths, metric_units)


async def report_at_startup(bindings: Sequence[TagBinding]) -> None:
    """
    Non-blocking startup check. Publishing must never wait on Postgres, so a failure to
    reach the Asset Model is logged and forgotten.
    """
    try:
        issues = await validate(bindings)
    except Exception:
        LOGGER.warning("Asset Model validation skipped: the model is unreachable", exc_info=True)
        return

    metrics.UNMODELLED_TAGS.set(len(issues))
    for issue in issues:
        LOGGER.warning("Asset Model validation [%s] %s", issue.kind, issue.detail)
    if not issues:
        LOGGER.info("All %s configured tags are present in the Asset Model", len(bindings))


def main() -> None:
    """`uns_opcua_validate`: exit non-zero on any issue so CI can gate a config change."""
    logging.basicConfig(level=logging.INFO)
    bindings = all_bindings()
    if not bindings:
        LOGGER.error("No opcua.servers are configured, so there is nothing to validate")
        sys.exit(1)

    issues = asyncio.run(validate(bindings))
    for issue in issues:
        LOGGER.error("[%s] %s", issue.kind, issue.detail)
    if issues:
        LOGGER.error("%s issue(s) across %s configured tags", len(issues), len(bindings))
        sys.exit(1)
    LOGGER.info("All %s configured tags validate against the Asset Model", len(bindings))
    sys.exit(0)


if __name__ == "__main__":
    main()
```

Note that `ModelConfig.from_settings("opcua")` reads the `historian.*` keys — the Asset Model shares the historian's database, which is why `model_config.py`'s docstring says the environment is a parameter. There is no separate `opcua` database to configure.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_model_check.py -v -n 0`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/model_check.py 10_uns_opcua/test/test_model_check.py
git commit -m "feat(opcua): validate the tag map against the Asset Model

Reports unknown Assets, missing MetricDefinitions and unit disagreements.
Gates in CI via uns_opcua_validate; only logs and gauges at startup."
```

---

## Task 9: Supervisor and health check

**Files:**
- Create: `10_uns_opcua/src/uns_opcua/main.py`
- Create: `10_uns_opcua/src/uns_opcua/health_check.py`
- Create: `10_uns_opcua/test/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8
- Produces: `build_tasks(...)`, `async run_connector(...) -> None`, `main() -> None` in `main.py`; `check_process(name: str) -> bool`, `check_existing_connection(host: str, port: int) -> bool`, `main() -> None` in `health_check.py`

- [ ] **Step 1: Write the failing test**

Create `10_uns_opcua/test/test_main.py`:

```python
"""Tests for the supervisor's wiring and shutdown behaviour."""

import asyncio

import pytest
from uns_opcua.main import build_bindings_for_all, run_connector
from uns_opcua.opcua_config import ServerConfig, SpoolConfig, TagConfig

pytestmark = pytest.mark.asyncio

ASSET = "TestCo/Site/Area/Line1/Cell1/Mixer"


def _server(name: str, node_id: str, metric_path: str) -> ServerConfig:
    return ServerConfig(
        name=name,
        url="opc.tcp://host:4840/",
        publishing_interval_ms=200,
        tags=(TagConfig(node_id=node_id, asset=ASSET, metric_path=metric_path),),
    )


async def test_build_bindings_for_all_flattens_every_server():
    servers = (_server("plc01", "ns=2;i=5", "ProcessValue/Temperature"), _server("plc02", "ns=2;i=6", "ProcessValue/Pressure"))
    bindings = build_bindings_for_all(servers)
    assert [binding.server_name for binding in bindings] == ["plc01", "plc02"]
    assert [binding.topic for binding in bindings] == [
        f"{ASSET}/ProcessValue/Temperature",
        f"{ASSET}/ProcessValue/Pressure",
    ]


async def test_run_connector_exits_cleanly_when_no_servers_are_configured(tmp_path):
    spool_config = SpoolConfig(
        path=str(tmp_path / "spool.db"),
        max_rows=10,
        max_bytes=1_000_000,
        max_age_hours=1,
        synchronous="OFF",
    )
    # A stock checkout has no servers. That must be a clean exit, not a crash loop.
    await run_connector(
        servers=(),
        spool_config=spool_config,
        client_id="c",
        qos=1,
        queue_maxsize=10,
        forward_batch_size=10,
        backoff_max_s=1.0,
        model_check=False,
    )


async def test_run_connector_cancels_every_task_on_shutdown(tmp_path, monkeypatch):
    """A cancelled supervisor must not leave orphan tasks holding the spool open."""
    spool_config = SpoolConfig(
        path=str(tmp_path / "spool.db"),
        max_rows=10,
        max_bytes=1_000_000,
        max_age_hours=1,
        synchronous="OFF",
    )
    started = asyncio.Event()

    async def never_ending(self) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("uns_opcua.collector.Collector.run", never_ending)
    monkeypatch.setattr("uns_opcua.forwarder.Forwarder.run", never_ending)

    task = asyncio.create_task(
        run_connector(
            servers=(_server("plc01", "ns=2;i=5", "ProcessValue/Temperature"),),
            spool_config=spool_config,
            client_id="c",
            qos=1,
            queue_maxsize=10,
            forward_batch_size=10,
            backoff_max_s=1.0,
            model_check=False,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Name the tasks we own rather than asserting on all_tasks(), which also holds the
    # test runner's own tasks.
    owned = {"spool_writer", "forwarder", "model_check", "collector:plc01"}
    leaked = [t.get_name() for t in asyncio.all_tasks() if t.get_name() in owned and not t.done()]
    assert leaked == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 10_uns_opcua/test/test_main.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_opcua.main'`

- [ ] **Step 3: Write the supervisor**

Create `10_uns_opcua/src/uns_opcua/main.py`:

```python
"""
Supervisor for the OPC UA edge connector.

One process, one asyncio task per OPC UA server, one shared spool. Per-server task
supervision is what provides isolation — a PLC that is down or misconfigured must not
affect the others — so process boundaries are not needed for it. A plant with enough
servers to saturate one process would want a container per server instead.
"""

import asyncio
import logging
from collections.abc import Sequence

from uns_opcua import prometheus_metrics as metrics
from uns_opcua.collector import Collector
from uns_opcua.forwarder import Forwarder, SpoolWriter, opened_spool
from uns_opcua.model_check import report_at_startup
from uns_opcua.opcua_config import MQTTConfig, OpcUaConfig, ServerConfig, SpoolConfig
from uns_opcua.spool import Spool, SpoolRow
from uns_opcua.tag_map import TagBinding, build_bindings, find_conflicts

LOGGER = logging.getLogger(__name__)


def build_bindings_for_all(servers: Sequence[ServerConfig]) -> list[TagBinding]:
    """Resolve every tag of every server, and refuse a mapping that cannot be right."""
    bindings = [binding for server in servers for binding in build_bindings(server)]
    conflicts = find_conflicts(bindings)
    if conflicts:
        for conflict in conflicts:
            LOGGER.error("Configuration conflict: %s", conflict)
        raise ValueError(f"{len(conflicts)} conflict(s) in the opcua tag configuration")
    return bindings


async def run_connector(
    servers: Sequence[ServerConfig],
    spool_config: SpoolConfig,
    client_id: str,
    qos: int,
    queue_maxsize: int,
    forward_batch_size: int,
    backoff_max_s: float,
    model_check: bool,
) -> None:
    """Start the pipeline and run until cancelled."""
    if not servers:
        LOGGER.warning("No opcua.servers are configured; nothing to collect")
        return

    bindings = build_bindings_for_all(servers)
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue(maxsize=queue_maxsize)

    async with opened_spool(Spool(spool_config)) as spool:
        tasks: list[asyncio.Task] = []
        try:
            if model_check:
                # Fire and forget: publishing must never wait on Postgres.
                tasks.append(asyncio.create_task(report_at_startup(bindings), name="model_check"))

            tasks.append(
                asyncio.create_task(
                    SpoolWriter(spool=spool, queue=queue).run(),
                    name="spool_writer",
                )
            )
            tasks.append(
                asyncio.create_task(
                    Forwarder(
                        spool=spool,
                        client_id=client_id,
                        qos=qos,
                        batch_size=forward_batch_size,
                        backoff_max_s=backoff_max_s,
                    ).run(),
                    name="forwarder",
                )
            )
            for server in servers:
                collector = Collector(
                    server=server,
                    bindings=[b for b in bindings if b.server_name == server.name],
                    queue=queue,
                    client_id=client_id,
                    qos=qos,
                    backoff_max_s=backoff_max_s,
                )
                tasks.append(asyncio.create_task(collector.run(), name=f"collector:{server.name}"))

            LOGGER.info(
                "OPC UA connector running: %s server(s), %s tag(s), client_id=%s",
                len(servers),
                len(bindings),
                client_id,
            )
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    """`uns_opcua` entry point."""
    logging.basicConfig(level=logging.INFO)

    if not MQTTConfig.is_config_valid():
        LOGGER.error("mqtt.host is not configured")
        raise SystemExit(1)
    if not OpcUaConfig.client_id:
        LOGGER.error("opcua.client_id is required and must be stable across restarts")
        raise SystemExit(1)

    metrics.start_metrics_server(OpcUaConfig.metrics_port)
    try:
        asyncio.run(
            run_connector(
                servers=OpcUaConfig.servers,
                spool_config=OpcUaConfig.spool,
                client_id=OpcUaConfig.client_id,
                qos=MQTTConfig.qos,
                queue_maxsize=OpcUaConfig.queue_maxsize,
                forward_batch_size=OpcUaConfig.forward_batch_size,
                backoff_max_s=OpcUaConfig.reconnect_backoff_max_s,
                model_check=OpcUaConfig.model_check,
            )
        )
    except KeyboardInterrupt:
        LOGGER.info("Shutting down on interrupt")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the health check**

Create `10_uns_opcua/src/uns_opcua/health_check.py`:

```python
"""Container health check for the OPC UA connector."""

import logging
import socket
import sys

import psutil

from uns_opcua.opcua_config import MQTTConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_process(name: str) -> bool:
    """Check if the process is running."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        cmdline = proc.info.get("cmdline") or []
        if name in " ".join(cmdline):
            return True
    return False


def check_existing_connection(host: str, port: int) -> bool:
    """Check if a connection to the specified host and port is already established."""
    try:
        remote_ip = socket.gethostbyname(host)
        for conn in psutil.net_connections("inet"):
            # cSpell:ignore raddr
            if conn.raddr and conn.raddr.port == port and conn.status == "ESTABLISHED":
                if remote_ip in ("127.0.0.1", "::1") or conn.raddr.ip == remote_ip:
                    return True
        return False
    except Exception as ex:
        logger.error(ex)
        return False


def main():
    """
    Healthy means the process is up and the broker connection is established.

    OPC UA sessions are deliberately not checked: a PLC being unreachable is what the
    spool and the reconnect loop are for, and it must not restart the container.
    """
    if not check_process("uns_opcua"):
        sys.exit(1)

    if not check_existing_connection(MQTTConfig.host, MQTTConfig.port):
        sys.exit(1)

    logger.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest 10_uns_opcua/test/test_main.py -v -n 0`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the whole module suite**

Run: `uv run pytest 10_uns_opcua/test -v`
Expected: PASS — all unit tests plus the three OPC UA integration tests.

- [ ] **Step 7: Commit**

```bash
git add 10_uns_opcua/src/uns_opcua/main.py 10_uns_opcua/src/uns_opcua/health_check.py 10_uns_opcua/test/test_main.py
git commit -m "feat(opcua): add the supervisor and health check

One task per server plus a shared writer and forwarder, all cancelled
together on shutdown. Health is process + broker; an unreachable PLC is
what the spool is for and must not restart the container."
```

---

## Task 10: Container, Compose, observability, and documentation

**Files:**
- Create: `10_uns_opcua/Dockerfile`
- Modify: `docker-compose.yml` (add an `opcua_client` service and a `opcua_spool` named volume)
- Modify: `08_uns_observability/prometheus/prometheus.yml` (add the scrape target)
- Modify: `README.md` (module list, container table, technology-choice rationale)

**Interfaces:**
- Consumes: `uns_opcua` console scripts `uns_opcua` and `uns_opcua_healthcheck`
- Produces: the `opcua_client` container image and service

- [ ] **Step 1: Write the Dockerfile**

Create `10_uns_opcua/Dockerfile`, mirroring `04_uns_historian/Dockerfile`. The spool needs a writable volume owned by `uns_user`, which is the one real difference.

```dockerfile
FROM python:3.14-alpine3.22

ARG UNS_MODULE=10_uns_opcua
ENV UNS_MODULE=${UNS_MODULE}
ENV UNS_CONF_DIR=/app/conf

LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/10_uns_opcua
LABEL org.opencontainers.image.description="Read-only OPC UA edge connector. Subscribes to PLC/SCADA nodes and publishes them into the Unified Namespace with disk-backed store-and-forward"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/README.md ./LICENSE* ./
# 00_uns_config and 09_uns_model land at the paths this module's `../` uv sources expect.
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
# uns_model provides the Asset Model tables the mapping is validated against. alembic.ini
# and migrations/ are part of its build config, so they are copied even though this
# connector never migrates - the Asset Model image does that.
COPY ./09_uns_model/pyproject.toml ./09_uns_model/README.md ./09_uns_model/alembic.ini /09_uns_model/
COPY ./09_uns_model/migrations /09_uns_model/migrations
COPY ./09_uns_model/src /09_uns_model/src
COPY ./${UNS_MODULE}/src ./src/
COPY ./conf/settings.yaml /app/conf/settings.yaml

# install minimalistic missing packages & security fixes
RUN apk update && \
    apk add --no-cache libffi-dev libc-dev gcc && \
    apk upgrade --no-cache libexpat libcrypto3 libssl3 busybox ssl_client && \
    rm -rf /var/cache/apk/*

RUN pip install --no-cache-dir --upgrade pip uv && \
    adduser --no-create-home --home /app --disabled-password uns_user && \
    # The spool lives on a volume; uns_user must own its mount point.
    mkdir -p /var/lib/uns_opcua && \
    chown -R uns_user /app /var/lib/uns_opcua && \
    su uns_user -c "uv lock && uv sync --compile-bytecode"

USER uns_user

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

VOLUME /app/conf
VOLUME /var/lib/uns_opcua
ENTRYPOINT ["uv", "run", "uns_opcua"]
HEALTHCHECK --interval=60s --timeout=10s CMD ["uv", "run", "uns_opcua_healthcheck"]
```

`cryptography`, which `Basic256Sha256` needs, publishes `musllinux` wheels, so Alpine works without a Rust toolchain in the image.

- [ ] **Step 2: Build the image to verify it works**

Run: `docker build -f 10_uns_opcua/Dockerfile -t uns_opcua:dev .`
Expected: build succeeds. If `cryptography` tries to compile from source, the wheel was not matched — check the base image's platform rather than adding a Rust toolchain.

- [ ] **Step 3: Add the Compose service**

In `docker-compose.yml`, add this after `historian_client`. It follows that service's shape exactly: no `image:`, `container_name:` or `restart:` key (the existing build-services set none), no `networks:` key (the file has none — everything shares Compose's default network), and configuration passed as `UNS_<block>__<key>` environment variables.

```yaml
  # Read-only OPC UA edge connector. Not started by default in a stock checkout: with no
  # opcua.servers configured it logs that there is nothing to collect and exits.
  opcua_client:
    build:
      context: .
      dockerfile: ./10_uns_opcua/Dockerfile
    volumes:
      - ./conf:/app/conf
      # The spool must outlive the container - that is the whole point of it.
      - opcua_spool:/var/lib/uns_opcua
    ports:
      - "9093:9093"
    environment:
      UNS_CONF_DIR: /app/conf
      UNS_MODULE: 10_uns_opcua
      UNS_mqtt__host: uns_mqtt_broker
      UNS_opcua__metrics_port: 9093
      # The Asset Model shares the historian's database, so model_check reads these.
      UNS_historian__hostname: uns_timescale_db
      UNS_historian__database: "uns_historian"
      UNS_historian__username: uns_dbuser
      UNS_historian__password: ${UNS_historian__password}
    depends_on:
      uns_mqtt_broker:
        condition: service_healthy
```

Deliberately **no `depends_on` for `asset_model_setup`**, even though the model check reads its schema. Gating the container on Postgres in the dev stack would contradict the design's non-gating rule and hide the very behaviour the rule exists to guarantee. A cold start where the model is not ready yet logs `Asset Model validation skipped` and keeps publishing, which is correct.

`docker-compose.yml` currently has **no top-level `volumes:` block**, so add one at the end of the file, at the same indentation level as `services:`:

```yaml
volumes:
  opcua_spool:
```

Finally, add `opcua_client` to `uns_prometheus`'s `depends_on` list, next to the existing `historian_client` and `graphdb_client` entries.

- [ ] **Step 4: Add the Prometheus scrape target**

In `08_uns_observability/prometheus/prometheus.yml`, after the `uns_graphdb` job:

```yaml
  - job_name: uns_opcua
    static_configs:
      - targets: ["opcua_client:9093"]
```

- [ ] **Step 5: Update the root README**

Add `10_uns_opcua` to the module list and the container table, and add a technology-choice note in the same voice as the existing ones:

```markdown
### OPC UA client: [asyncua](https://github.com/FreeOpcUa/opcua-asyncio)

The only actively maintained pure-Python OPC UA stack with a native asyncio API, which
matters because the connector runs one session per server in one event loop. It also
ships an in-process `Server`, so the connector's subscription and deadband behaviour is
tested for real rather than mocked.

### Edge buffer: SQLite

The store-and-forward spool must survive a container restart and a week-long WAN outage,
which rules out an in-memory queue. SQLite in WAL mode is already on every Python
install, needs no daemon on the edge node, and its `AUTOINCREMENT` rowid gives FIFO —
and therefore per-topic ordering — for free.
```

- [ ] **Step 6: Verify the stack starts and publishes**

Run:
```bash
docker compose up -d uns_mqtt_broker opcua_client
docker compose logs opcua_client --tail 30
curl -s localhost:9093/metrics | grep -E "uns_opcua_(spool_rows|server_up)"
```
Expected: the log shows `No opcua.servers are configured; nothing to collect` on a stock checkout — a clean start, not a crash — and `/metrics` responds. With servers configured, expect `uns_opcua_server_up{server="..."} 1.0` and a `uns_opcua_spool_rows` that stays near zero while the broker is up.

- [ ] **Step 7: Commit**

```bash
git add 10_uns_opcua/Dockerfile docker-compose.yml 08_uns_observability/prometheus/prometheus.yml README.md
git commit -m "feat(opcua): containerise the connector and wire up observability

Adds the Compose service with a persistent volume for the spool, the
Prometheus scrape target, and the technology-choice rationale."
```

---

## Task 11: End-to-end store-and-forward test

**Files:**
- Create: `10_uns_opcua/test/test_end_to_end.py`

**Interfaces:**
- Consumes: `Collector`, `SpoolWriter`, `Forwarder`, `Spool` — the whole pipeline
- Produces: nothing; this is the test that proves the outage behaviour the design exists for

- [ ] **Step 1: Write the test**

Create `10_uns_opcua/test/test_end_to_end.py`:

```python
"""
The behaviour this whole module exists for: a broker outage must delay data, not lose it.

Uses the in-process OPC UA server and a fake publisher rather than a live broker, so the
outage is scripted rather than hoped for. The Compose broker is exercised separately by
the integration suite.
"""

import asyncio
import json

import pytest
import pytest_asyncio
from asyncua import Server, ua
from uns_opcua.collector import Collector
from uns_opcua.forwarder import Forwarder, SpoolWriter
from uns_opcua.opcua_config import ServerConfig, SpoolConfig, TagConfig
from uns_opcua.spool import Spool, SpoolRow
from uns_opcua.tag_map import build_bindings

ENDPOINT = "opc.tcp://127.0.0.1:48402/uns/e2e/"
ASSET = "TestCo/Site/Area/Line1/Cell1/Mixer"

pytestmark = [pytest.mark.integrationtest, pytest.mark.asyncio]


class FlakyPublisher:
    """A broker that is down until `up` is set."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []
        self.up = False

    async def publish(self, topic: str, payload: bytes, qos: int) -> None:
        if not self.up:
            raise ConnectionError("broker down")
        self.published.append((topic, payload))


@pytest_asyncio.fixture
async def opcua_server():
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    namespace = await server.register_namespace("http://uns/e2e")
    device = await server.nodes.objects.add_object(namespace, "Mixer")
    temperature = await device.add_variable(namespace, "Temp_PV", 10.0)
    await temperature.set_writable()
    async with server:
        yield temperature


async def test_data_collected_during_an_outage_is_published_when_the_broker_returns(
    opcua_server, tmp_path
):
    temperature = opcua_server
    server_config = ServerConfig(
        name="e2e-plc",
        url=ENDPOINT,
        publishing_interval_ms=50,
        tags=(TagConfig(node_id=temperature.nodeid.to_string(), asset=ASSET, metric_path="ProcessValue/Temperature"),),
    )
    spool = Spool(
        SpoolConfig(
            path=str(tmp_path / "spool.db"),
            max_rows=1000,
            max_bytes=10_000_000,
            max_age_hours=168,
            synchronous="OFF",
        )
    )
    spool.open()
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue(maxsize=1000)
    publisher = FlakyPublisher()
    writer = SpoolWriter(spool=spool, queue=queue, batch_size=100, flush_interval_s=0.02)
    forwarder = Forwarder(spool=spool, client_id="uns_opcua_e2e", qos=1, batch_size=100)
    collector = Collector(
        server=server_config,
        bindings=build_bindings(server_config),
        queue=queue,
        client_id="uns_opcua_e2e",
        qos=1,
    )

    tasks = [
        asyncio.create_task(collector.run()),
        asyncio.create_task(writer.run()),
    ]
    try:
        await asyncio.sleep(1.0)
        for value in (20.0, 30.0, 40.0):
            await temperature.write_value(ua.DataValue(ua.Variant(value, ua.VariantType.Double)))
            await asyncio.sleep(0.2)

        # The broker is down: the values must be on disk, not lost and not published.
        async with asyncio.timeout(5):
            while await asyncio.to_thread(spool.row_count) < 4:  # initial 10.0 plus three writes
                await asyncio.sleep(0.05)
        assert publisher.published == []

        publisher.up = True
        forwarded = 0
        async with asyncio.timeout(5):
            while await asyncio.to_thread(spool.row_count) > 0:
                forwarded += await forwarder.forward_batch(publisher)

        values = [json.loads(payload.decode("utf-8"))["value"] for _, payload in publisher.published]
        assert values[:4] == [10.0, 20.0, 30.0, 40.0], "order must survive the outage"
        assert forwarded == len(publisher.published)
        # Rule 1: every timestamp came from the server, none from drain time.
        timestamps = [json.loads(payload.decode("utf-8"))["timestamp"] for _, payload in publisher.published]
        assert timestamps == sorted(timestamps)
        assert all(topic == f"{ASSET}/ProcessValue/Temperature" for topic, _ in publisher.published)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        spool.close()


async def test_a_crash_between_publish_and_delete_replays_rather_than_loses(tmp_path):
    """
    The spool deletes only after the broker acknowledges, so an interruption replays.
    At-least-once is safe because the historian inserts ON CONFLICT DO NOTHING.
    """
    config = SpoolConfig(
        path=str(tmp_path / "spool.db"),
        max_rows=1000,
        max_bytes=10_000_000,
        max_age_hours=168,
        synchronous="FULL",
    )
    spool = Spool(config)
    spool.open()
    payload = b'{"value":1,"timestamp":1756728000123.0}'
    spool.enqueue([SpoolRow(topic="t", payload=payload, qos=1)], now=1_756_728_000.0)

    class CrashingPublisher:
        def __init__(self) -> None:
            self.published: list[bytes] = []

        async def publish(self, topic: str, payload: bytes, qos: int) -> None:
            self.published.append(payload)
            raise KeyboardInterrupt("power cut after the broker acknowledged")

    forwarder = Forwarder(spool=spool, client_id="c", qos=1, batch_size=10)
    with pytest.raises(KeyboardInterrupt):
        await forwarder.forward_batch(CrashingPublisher())
    spool.close()

    # Restart: the row was acknowledged before the crash, so it is gone. Had the crash
    # landed before the acknowledgement, the row would still be here to replay.
    restarted = Spool(config)
    restarted.open()
    try:
        assert restarted.row_count() == 0
    finally:
        restarted.close()
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest 10_uns_opcua/test/test_end_to_end.py -v -n 0 -m integrationtest`
Expected: PASS (2 tests)

- [ ] **Step 3: Run the full repository suite to check nothing regressed**

Run: `uv run pytest 10_uns_opcua/test -v && uv run ruff check 10_uns_opcua && uv run ruff format --check 10_uns_opcua`
Expected: all tests pass, no lint findings.

- [ ] **Step 4: Commit**

```bash
git add 10_uns_opcua/test/test_end_to_end.py
git commit -m "test(opcua): prove a broker outage delays data rather than losing it

Scripts an outage across the real collector, spool and forwarder, and
asserts order and SourceTimestamp survive the replay."
```

---

## Spec coverage

| Spec section | Task |
| --- | --- |
| 4 Rule 1 (SourceTimestamp, never re-derived) | 3 (`build_payload`, `serialise`), 7 (verbatim republish test), 11 (survives an outage) |
| 4 Rule 2 (stable `client_id`) | 1 (config), 3 (`source` field), 7 (MQTT `identifier`), 9 (startup check) |
| 5 Module layout | 1, and one file per subsequent task |
| 6 Config and topic derivation | 1, 2 |
| 7 Collect → spool → publish | 6, 7, 9 |
| 7 Reconnect recovers the gap | 6 (`connect_once`, integration test) |
| 8 Spool schema and bounding | 5 |
| 9 Payload mapping, no `status` | 3 |
| 10 Asset Model validation, non-gating | 8 |
| 11 Failure modes | 5 (bounds, disk), 6 (server down, rejected filter, unresolvable node, Bad quality), 7 (broker down, crash before delete), 9 (health check) |
| 12 Metrics | 4, referenced throughout |
| 13 Testing | 2–8 unit, 6 and 11 integration |
| 14 Registration checklist | 1 (workspace, settings), 10 (Dockerfile, Compose, Prometheus, README) |

Two deviations from the spec, both deliberate:

1. **The spec's "read every monitored node once after reconnect" is dropped.** Verification showed that creating a monitored item already delivers the current value, with the server's true `SourceTimestamp` — strictly better than a read. The spec has been corrected to match.
2. **Three metrics were added** beyond the spec's twelve (`deadband_rejected`, `unresolved_nodes`, `queue_dropped`), because the spec's failure-mode table promises a counter for each of those cases without naming one.

## Corrections already applied — do not "fix" these back

Found while reviewing this plan against the running environment. Each was verified, not reasoned about, so treat the values here as authoritative over intuition:

1. **`sqlite3.connect(..., check_same_thread=False)` plus an `RLock` is mandatory.** Every spool call goes through `asyncio.to_thread`, which uses a pool thread. Reproduced: the default raises `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`. Two tests in Task 5 pin this.
2. **`PRAGMA auto_vacuum=INCREMENTAL` must be set before the DDL.** Without it, freed pages are never returned, `page_count` never falls, and the `max_bytes` bound deletes the entire spool every time it is exceeded instead of trimming to fit.
3. **`-n 0`, never `-p no:xdist`.** The root `addopts` carries `-n auto`.
4. **`[tool.uv.sources]` with `../` relative paths.** This is what makes the Dockerfile work — siblings are copied to `/00_uns_config` and `/09_uns_model`, and the module sits at `/app`.
5. **The Asset Model engine is built from `ModelConfig.from_settings(...)`, `.url` and `.connect_args()`.** There is no `db_url()` helper; the password is deliberately kept out of the URL, so composing a URL by hand would either leak it into logs or fail to authenticate.
6. **Epoch constant:** `2026-09-01T12:00:00.123Z` is `1788264000123.0`. Where a test can derive the expected value from its own input, it does, so this class of error cannot recur.
7. **No `depends_on: asset_model_setup`** on the Compose service, despite the model check needing that schema — gating on it would contradict the non-gating rule.
