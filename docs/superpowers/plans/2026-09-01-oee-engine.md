# OEE Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute Availability × Performance × Quality for every closed shift from data already in the historian, store the result with its downtime breakdown, and publish it back into the Unified Namespace.

**Architecture:** A new module `12_uns_oee` runs a scheduler that wakes periodically, asks the shift calendar which shift windows have closed, reads that window's state and counter samples out of `uns_metrics`, computes the KPIs as a pure function of those samples, writes a revisioned result row, and publishes one MQTT payload per shift. Master data (shift patterns, ideal cycle times, reason codes, unit bindings) lives in the existing `model` schema and is authored from `conf/oee/*.yaml`; results live in a new `oee` schema. Nothing subscribes to MQTT and nothing holds state between runs, so any shift can be recomputed at any time and must produce the identical number.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x async (asyncpg), Alembic, TimescaleDB/PostgreSQL, aiomqtt, Strawberry GraphQL, prometheus_client, Dynaconf, pytest + pytest-asyncio, uv workspace, Docker Compose, Grafana.

**Spec:** `docs/superpowers/specs/2026-09-01-oee-engine-design.md`

## Global Constraints

- **Rule 1 — the calculation is a pure function of historised input.** No state is carried between runs. Recomputing a shift from the same input rows must produce bit-identical numbers. Never read the clock inside a calculation function; pass time in.
- **Rule 2 — Performance uses Total Count; Quality uses Good over Total.** Using Good Count in the Performance numerator penalises scrap twice.
- **Rule 3 — a manual reason code is never overwritten by auto-classification.** Recomputation re-reads manual assignments and preserves them.
- **No write-back to any control system.** This module reads the historian and publishes to MQTT. It never writes to OPC UA, PLCs, or any process interface.
- Durations are measured over the **union** of intervals, never by summing interval lengths.
- The state at `shift_start` is the last sample **at or before** the boundary, not the first sample inside the window.
- Python version floor: 3.14. Line length 127. Ruff `max-complexity = 15`.
- Metrics port for this module: **9095** (9091 historian, 9092 graphdb, 9093 simulator, 9094 reserved for the OPC UA connector).
- New sixth `ParameterType` in the topic hierarchy: `KPI`.
- Secrets come from `conf/.secrets.yaml` or `UNS_`-prefixed environment variables. Never hardcode a password and never put one in `settings.yaml`.
- Test commands use `-n 0` to disable xdist for a single test. **Never `-p no:xdist`** — the root `addopts` carries `-n auto --dist loadgroup`, and disabling the plugin makes those options unrecognised.
- Alembic migration `0003` follows the `op.create_table` + `sa.Column` idiom of `0001_asset_model.py`, not the raw-DDL-string idiom of `0002`.
- Every new SQLAlchemy model file imports `Base` from `uns_model.tables`. There is one `Base` in the project.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `12_uns_oee/pyproject.toml` | Module packaging, workspace-relative editable deps on `00_uns_config` and `09_uns_model`. Not on `02_mqtt-cluster`: this module publishes with `aiomqtt` directly and never subscribes, so it needs none of the listener machinery. |
| `12_uns_oee/Dockerfile` | Runtime image, non-root `uns_user`, `UNS_MODULE="12_uns_oee"`. |
| `12_uns_oee/src/uns_oee/oee_config.py` | Frozen `OeeConfig` read from the `oee` Dynaconf environment. No other file reads settings. |
| `12_uns_oee/src/uns_oee/shift_calendar.py` | Pure: pattern + UTC range → list of `ShiftWindow`. Owns all timezone/DST arithmetic. |
| `12_uns_oee/src/uns_oee/counters.py` | Pure: monotonic counter samples → delta, with rollover/reset detection. |
| `12_uns_oee/src/uns_oee/states.py` | Pure: state samples → intervals; interval union/intersect/subtract and duration. |
| `12_uns_oee/src/uns_oee/classifier.py` | Pure: stop intervals + reason rules + manual overrides → classified stops. |
| `12_uns_oee/src/uns_oee/oee_calc.py` | Pure: `ShiftInputs` → `ShiftMetrics`. The only place the OEE formulas appear. |
| `12_uns_oee/src/uns_oee/master_data.py` | Loads `OeeUnit` rows and their metric bindings into `UnitMasterData`. |
| `12_uns_oee/src/uns_oee/sources.py` | Reads `uns_metrics` sample series and input fingerprints. The only reader of the historian. |
| `12_uns_oee/src/uns_oee/store.py` | Writes `oee.*` result rows. The only writer of results. |
| `12_uns_oee/src/uns_oee/publisher.py` | Builds the KPI topic + payload and publishes over one long-lived aiomqtt connection. |
| `12_uns_oee/src/uns_oee/pipeline.py` | Orchestrates one shift: sources → counters/states → classifier → calc → store → publish. |
| `12_uns_oee/src/uns_oee/scheduler.py` | Decides which shifts are due, drains the recompute queue, runs the backfill once. |
| `12_uns_oee/src/uns_oee/prometheus_metrics.py` | Custom collector on port 9095. |
| `12_uns_oee/src/uns_oee/health_check.py` | Docker healthcheck: process alive + metrics port bound. |
| `12_uns_oee/src/uns_oee/main.py` | Entry point: config → engine → scheduler → graceful shutdown. |
| `12_uns_oee/src/uns_oee/recompute_cli.py` | `uns_oee_recompute` — enqueue or force a recompute of a date range. |
| `09_uns_model/src/uns_model/oee_tables.py` | The 13 ORM tables (8 in `model`, 5 in `oee`) plus the vocabulary tuples. |
| `09_uns_model/src/uns_model/oee_master_data.py` | `OeeMasterDataRepository` + the dataclass specs it writes. |
| `09_uns_model/src/uns_model/oee_seed.py` | Pure `plan_from_oee_config` + idempotent `apply_plan`. |
| `09_uns_model/src/uns_model/oee_results.py` | `OeeResultRepository` — result/event reads for GraphQL and the reason-assignment write. |
| `09_uns_model/migrations/versions/0003_oee_model.py` | Creates the `oee` schema and all 13 tables; seeds the default reason codes. |
| `07_uns_graphql/src/uns_graphql/type/oee.py` | GraphQL types + hand-written enums. |
| `07_uns_graphql/src/uns_graphql/queries/oee.py` | `oeeShiftResults`, `downtimeEvents`, `downtimePareto`. |
| `07_uns_graphql/src/uns_graphql/mutations/oee.py` | `assignDowntimeReason`. |
| `conf/oee/{shifts,units,products,reasons}.yaml` | Human-authored master data. |
| `08_uns_observability/grafana/dashboards/oee.json` | The OEE trend and downtime Pareto. |
| `docs/adr/0008-oee-computed-from-history-not-streamed.md` | Records why the engine reads history instead of subscribing. |

---

### Task 1: Module scaffold and configuration

**Files:**
- Create: `12_uns_oee/pyproject.toml`
- Create: `12_uns_oee/src/uns_oee/__init__.py`
- Create: `12_uns_oee/src/uns_oee/oee_config.py`
- Create: `12_uns_oee/test/__init__.py`
- Create: `12_uns_oee/test/test_oee_config.py`
- Modify: `pyproject.toml` (root — `dependencies`, `[tool.uv.sources]`, `[tool.uv.workspace] members`, `testpaths`, `pythonpath`)
- Modify: `conf/settings.yaml` (add the `oee:` environment block)

**Interfaces:**
- Consumes: `uns_config.get_settings`, `uns_model.model_config.ModelConfig`.
- Produces: `OeeConfig` (frozen dataclass) with fields `metrics_port: int`, `scan_interval_seconds: float`, `settle_minutes: int`, `late_window_hours: int`, `backfill_days: int`, `mqtt_host: str | None`, `mqtt_port: int`, `mqtt_client_id: str`, `mqtt_qos: int`, `mqtt_username: str | None`, `mqtt_password: str | None`, `mqtt_keep_alive: int`, `mqtt_version: int`, `mqtt_transport: str`, `metrics_table: str`; classmethod `OeeConfig.from_settings(module_env: str = "oee") -> OeeConfig`; method `is_valid() -> bool`.

- [ ] **Step 1: Create the module package files**

`12_uns_oee/pyproject.toml`:

```toml
[project]
name = "uns_oee"
version = "0.9.38"
description = "Shift OEE engine: computes Availability x Performance x Quality from historised UNS data"
authors = [{ name = "Ashwin Krishnan", email = "mkashwin@gmail.com" }]
requires-python = ">=3.14, <4"
readme = "README.md"
license = { text = "MIT" }
maintainers = [
    { name = "Himanshu Dhami", email = "himanshudhami@gmail.com" },
    { name = "Johan Jeppson", email = "logic4human@gmail.com" },
]
keywords = ["uns", "isa-95", "oee", "shift", "downtime", "timescaledb", "mqtt"]
classifiers = [
    "License :: OSI Approved :: MIT License",
    "Intended Audience :: Manufacturing",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Development Status :: 4 - Beta",
    "Topic :: Communications",
]
dependencies = [
    "logger~=1.4",
    "uns_config",
    "uns_model",
    "sqlalchemy[asyncio]>=2.0.36,<3",
    "asyncpg>=0.31.0,<0.32",
    "aiomqtt>=2.4.0,<3",
    "prometheus-client>=0.21.0,<1",
    "dynaconf~=3.2",
]

[project.urls]
Repository = "https://github.com/mkashwin/unifiednamespace/tree/main/12_uns_oee"

[project.scripts]
uns_oee = "uns_oee.main:main"
uns_oee_recompute = "uns_oee.recompute_cli:main"
uns_oee_health = "uns_oee.health_check:main"

[dependency-groups]
test = [
    "pytest>=9.0.3,<10",
    "pytest-xdist>=3.8.0,<4",
    "pytest-timeout>=2.4.0,<3",
    "pytest-asyncio>=1.3.0,<1.5",
    "pytest-cov>=6.0.0,<8",
    "safety>=3.4.0,<4",
]

[tool.uv]
default-groups = ["test"]

[tool.uv.sources]
uns_config = { path = "../00_uns_config", editable = true }
uns_model = { path = "../09_uns_model", editable = true }

[tool.hatch.build.targets.sdist]
include = ["src/uns_oee"]

[tool.hatch.build.targets.wheel]
include = ["src/uns_oee"]

[tool.hatch.build.targets.wheel.sources]
"src/uns_oee" = "uns_oee"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
norecursedirs = [".git", "build", "node_modules", "env*", "tmp*"]
testpaths = ["test"]
markers = ["integrationtest: mark a test as an integration test"]
addopts = "--timeout=300"
asyncio_default_fixture_loop_scope = "session"

[tool.ruff]
extend = "../pyproject.toml"
```

`12_uns_oee/src/uns_oee/__init__.py` and `12_uns_oee/test/__init__.py` are both empty files.

- [ ] **Step 2: Register the module in the root workspace**

In the root `pyproject.toml`, append `"uns_oee"` to `[project] dependencies`, add to `[tool.uv.sources]`:

```toml
uns_oee = { path = "./12_uns_oee", editable = true }
```

append `"uns_oee"` to `[tool.uv.workspace] members`, and append `"12_uns_oee/test"` to **both** `testpaths` and `pythonpath`.

- [ ] **Step 3: Add the `oee:` environment to `conf/settings.yaml`**

Insert after the `simulator:` block, before `dynaconf_merge: true`:

```yaml
oee:
  mqtt:
    client_id: "uns_oee_client"
  oee:
    # Prometheus scrapes this. 9091 historian, 9092 graph database, 9093 simulator,
    # 9094 reserved for the OPC UA edge connector.
    metrics_port: 9095
    # Seconds between scheduler passes. A shift boundary is only ever seen on a pass,
    # so this bounds how late the first revision of a result can be.
    scan_interval_seconds: 300
    # Wait this long after shift_end before computing revision 1, so that in-flight
    # messages have landed in the historian.
    settle_minutes: 15
    # Keep re-checking a shift's input fingerprint for this long after shift_end. Data
    # arriving later than this does not trigger a new revision.
    late_window_hours: 48
    # On an empty results table, walk back this many days. Shifts that end before a
    # unit's earliest historised sample are skipped, not computed as zero.
    backfill_days: 30
```

The nested `oee.oee.*` shape is deliberate: `oee:` is the Dynaconf *environment* name, and the inner `oee:` is the settings block, exactly as `historian:` is both for `04_uns_historian`. Environment overrides are therefore `UNS_oee__metrics_port`.

- [ ] **Step 4: Write the failing test**

`12_uns_oee/test/test_oee_config.py`:

```python
"""Tests for the OEE module's configuration reader."""

from uns_oee.oee_config import OeeConfig


def test_defaults_match_the_documented_platform_ports():
    config = OeeConfig(mqtt_host="localhost")
    assert config.metrics_port == 9095
    assert config.settle_minutes == 15
    assert config.late_window_hours == 48
    assert config.backfill_days == 30
    assert config.mqtt_client_id == "uns_oee_client"
    assert config.metrics_table == "uns_metrics"


def test_is_valid_requires_an_mqtt_host():
    assert OeeConfig(mqtt_host="localhost").is_valid()
    assert not OeeConfig(mqtt_host=None).is_valid()


def test_from_settings_reads_the_oee_environment():
    config = OeeConfig.from_settings("oee")
    assert config.metrics_port == 9095
    assert config.mqtt_client_id == "uns_oee_client"
    assert config.scan_interval_seconds == 300


def test_from_settings_reuses_the_platforms_shared_broker_settings():
    config = OeeConfig.from_settings("oee")
    assert config.mqtt_host == "localhost"
    assert config.mqtt_port == 1883
    assert config.mqtt_keep_alive == 60
    assert config.mqtt_version == 5
    assert config.mqtt_transport == "tcp"
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_oee_config.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee'`.

- [ ] **Step 6: Write the implementation**

`12_uns_oee/src/uns_oee/oee_config.py`:

```python
"""Configuration for the OEE engine.

The only module that reads `conf/`. Everything downstream takes an `OeeConfig`, so a
test can construct one directly instead of writing a settings file. Mirrors
`uns_model.model_config.ModelConfig`: a frozen dataclass with a `from_settings`
classmethod, not module-level class attributes evaluated at import time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from uns_config import get_settings

LOGGER = logging.getLogger(__name__)

#: Dynaconf environment this module reads.
OEE_ENV = "oee"


@dataclass(frozen=True, slots=True)
class OeeConfig:
    """Everything the engine needs that is not master data."""

    mqtt_host: str | None
    mqtt_port: int = 1883
    mqtt_client_id: str = "uns_oee_client"
    mqtt_qos: int = 1
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_keep_alive: int = 60
    mqtt_version: int = 5
    mqtt_transport: str = "tcp"
    metrics_port: int = 9095
    scan_interval_seconds: float = 300.0
    settle_minutes: int = 15
    late_window_hours: int = 48
    backfill_days: int = 30
    metrics_table: str = "uns_metrics"

    @classmethod
    def from_settings(cls, module_env: str = OEE_ENV) -> OeeConfig:
        """Read the OEE settings from the platform `conf/` directory."""
        settings = get_settings(module_env)
        config = cls(
            mqtt_host=settings.get("mqtt.host"),
            mqtt_port=settings.get("mqtt.port", 1883),
            mqtt_client_id=settings.get("mqtt.client_id", "uns_oee_client"),
            # QoS 1 not 2: a duplicate KPI payload is harmless because the topic carries
            # the shift's final value, and a lost one is not.
            mqtt_qos=settings.get("mqtt.qos", 1),
            mqtt_username=settings.get("mqtt.username", None),
            mqtt_password=settings.get("mqtt.password", None),
            # The platform's shared `mqtt:` block already sets these three
            # (`conf/settings.yaml:53`-`:56`); read them rather than hardcode a second answer.
            mqtt_keep_alive=settings.get("mqtt.keep_alive", 60),
            mqtt_version=settings.get("mqtt.version", 5),
            mqtt_transport=settings.get("mqtt.transport", "tcp"),
            metrics_port=settings.get("oee.metrics_port", 9095),
            scan_interval_seconds=settings.get("oee.scan_interval_seconds", 300.0),
            settle_minutes=settings.get("oee.settle_minutes", 15),
            late_window_hours=settings.get("oee.late_window_hours", 48),
            backfill_days=settings.get("oee.backfill_days", 30),
            metrics_table=settings.get("historian.metrics_table", "uns_metrics"),
        )
        if not config.is_valid():
            LOGGER.error(
                "MQTT host not provided. Update key 'mqtt.host' in 'conf/settings.yaml' at the repository root"
            )
        return config

    def is_valid(self) -> bool:
        """Mandatory settings are present. Does not check that they are correct."""
        return self.mqtt_host is not None
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv sync && uv run pytest 12_uns_oee/test/test_oee_config.py -v -n 0`
Expected: PASS (4 passed).

- [ ] **Step 8: Commit**

```bash
git add 12_uns_oee pyproject.toml conf/settings.yaml
git commit -m "feat(oee): scaffold 12_uns_oee module and its configuration"
```

---

### Task 2: ORM tables and the `0003` migration

**Files:**
- Create: `09_uns_model/src/uns_model/oee_tables.py`
- Create: `09_uns_model/migrations/versions/0003_oee_model.py`
- Create: `09_uns_model/test/test_oee_tables.py`
- Modify: `09_uns_model/src/uns_model/model_config.py` (add `OEE_SCHEMA = "oee"`)

**Interfaces:**
- Consumes: `uns_model.tables.Base`, `uns_model.model_config.MODEL_SCHEMA`.
- Produces: `OEE_SCHEMA`; ORM classes `Product`, `ShiftPattern`, `ShiftPatternSlot`, `ShiftException`, `OeeUnit`, `IdealCycleTime`, `DowntimeReason`, `StateReasonMap`, `ShiftResult`, `ShiftResultProduct`, `ShiftResultRevision`, `DowntimeEvent`, `RecomputeRequest`; vocabulary tuples `SHIFT_EXCEPTION_KINDS`, `OEE_STATUSES`, `REASON_SOURCES`, `DEFAULT_PRODUCING_STATES`, `DEFAULT_DOWNTIME_REASONS`; constant `UNCLASSIFIED_REASON_CODE = "UNCLASSIFIED"`.

Why a new file rather than appending to `tables.py`: that file is already 405 lines covering the Asset Model and the console. Thirteen more tables would take it past 800 and mix two subsystems that are reviewed separately. `oee_tables.py` imports the one `Base` so `create_all()` still sees every table.

**These classes declare no `relationship()`, unlike `tables.py`.** Every consumer is async, and under asyncio a lazy load raises `MissingGreenlet` at the attribute access rather than at the query that forgot to eager-load — a long way from the cause. Task 9 and Task 14 therefore join explicitly and select the columns they need. Foreign keys are still declared; only the ORM navigation is left out. Do not add relationships "for convenience".

- [ ] **Step 1: Add the schema constant**

In `09_uns_model/src/uns_model/model_config.py`, beside the existing constants:

```python
MODEL_SCHEMA = "model"
CONSOLE_SCHEMA = "console"
OEE_SCHEMA = "oee"
```

- [ ] **Step 2: Write the failing test**

`09_uns_model/test/test_oee_tables.py`:

```python
"""Structural tests for the OEE tables.

These assert the contract other modules rely on - schema placement, the
nulls-not-distinct uniqueness that makes 'null means every Asset' work, and the
closed vocabularies - without needing a database.
"""

import pytest
from sqlalchemy import UniqueConstraint

from uns_model.model_config import MODEL_SCHEMA, OEE_SCHEMA
from uns_model.oee_tables import (
    DEFAULT_DOWNTIME_REASONS,
    DEFAULT_PRODUCING_STATES,
    OEE_STATUSES,
    REASON_SOURCES,
    SHIFT_EXCEPTION_KINDS,
    UNCLASSIFIED_REASON_CODE,
    DowntimeEvent,
    IdealCycleTime,
    OeeUnit,
    RecomputeRequest,
    ShiftResult,
    ShiftResultProduct,
    ShiftResultRevision,
    StateReasonMap,
)


def test_master_data_lives_in_model_and_results_live_in_oee():
    assert OeeUnit.__table__.schema == MODEL_SCHEMA
    assert IdealCycleTime.__table__.schema == MODEL_SCHEMA
    for table in (ShiftResult, ShiftResultProduct, ShiftResultRevision, DowntimeEvent, RecomputeRequest):
        assert table.__table__.schema == OEE_SCHEMA


@pytest.mark.parametrize(
    ("model", "columns"),
    [
        (IdealCycleTime, {"asset_id", "product_id"}),
        (StateReasonMap, {"oee_unit_id", "state_value"}),
    ],
)
def test_nullable_scope_keys_are_unique_with_nulls_not_distinct(model, columns):
    """A NULL scope key means 'every Asset', so two NULLs must collide."""
    constraints = [c for c in model.__table__.constraints if isinstance(c, UniqueConstraint)]
    matching = [c for c in constraints if {col.name for col in c.columns} == columns]
    assert matching, f"{model.__name__} has no unique constraint over {columns}"
    assert matching[0].dialect_kwargs["postgresql_nulls_not_distinct"] is True


def test_one_result_row_per_unit_and_shift_start():
    constraints = [c for c in ShiftResult.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert any({col.name for col in c.columns} == {"oee_unit_id", "shift_start"} for c in constraints)


def test_vocabularies_are_closed_and_include_the_documented_values():
    assert SHIFT_EXCEPTION_KINDS == ("PLANNED_DOWN", "NON_PRODUCING", "HOLIDAY")
    assert REASON_SOURCES == ("auto", "manual")
    assert OEE_STATUSES == (
        "OK",
        "NO_LOADING_TIME",
        "NO_PRODUCTION",
        "MISSING_IDEAL_CYCLE_TIME",
        "NO_INPUT_DATA",
    )
    assert DEFAULT_PRODUCING_STATES == ("EXECUTE",)


def test_unclassified_is_a_seeded_unplanned_reason():
    seeded = {code: is_planned for code, _name, _category, is_planned in DEFAULT_DOWNTIME_REASONS}
    assert UNCLASSIFIED_REASON_CODE == "UNCLASSIFIED"
    assert seeded[UNCLASSIFIED_REASON_CODE] is False
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_oee_tables.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_model.oee_tables'`.

- [ ] **Step 4: Write the ORM tables — module header, vocabularies, and master data**

`09_uns_model/src/uns_model/oee_tables.py`:

```python
"""Declarative models for shift OEE: master data in schema `model`, results in `oee`.

Two schemas because the two halves have different lifecycles. Master data is authored
by a person from `conf/oee/*.yaml` and changes rarely; results are derived, disposable
and recomputable from the historian at any time. Putting the derived half in its own
schema means it can be truncated and rebuilt without touching anything a human wrote.

Nothing here is a hypertable. Result volume is one row per unit per shift - a few
thousand rows a year - so a plain table with a b-tree index is the right shape, and
`uns_metrics` remains the only time-series table in the platform (ADR-0002).
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from uns_model.model_config import MODEL_SCHEMA, OEE_SCHEMA
from uns_model.tables import Base

#: What a calendar exception does to a shift window. PLANNED_DOWN subtracts from Loading
#: Time; NON_PRODUCING and HOLIDAY do too, and are kept distinct only so a report can say
#: which it was.
SHIFT_EXCEPTION_KINDS: tuple[str, ...] = ("PLANNED_DOWN", "NON_PRODUCING", "HOLIDAY")

#: Who put the reason code on a downtime event. `manual` is never overwritten.
REASON_SOURCES: tuple[str, ...] = ("auto", "manual")

#: Why a shift result reads the way it does. Precedence when several could apply is
#: NO_INPUT_DATA, NO_LOADING_TIME, NO_PRODUCTION, MISSING_IDEAL_CYCLE_TIME, OK.
OEE_STATUSES: tuple[str, ...] = (
    "OK",
    "NO_LOADING_TIME",
    "NO_PRODUCTION",
    "MISSING_IDEAL_CYCLE_TIME",
    "NO_INPUT_DATA",
)

#: PackML/OMAC states that count as producing. EXECUTE is the only one that makes parts.
DEFAULT_PRODUCING_STATES: tuple[str, ...] = ("EXECUTE",)

#: The reason assigned when no rule matches. Never null, so a Pareto always adds up.
UNCLASSIFIED_REASON_CODE = "UNCLASSIFIED"

#: (code, display_name, category, is_planned) seeded by migration 0003. A deployment adds
#: to these from conf/oee/reasons.yaml; they exist so a fresh install can classify at all.
DEFAULT_DOWNTIME_REASONS: tuple[tuple[str, str, str, bool], ...] = (
    ("UNCLASSIFIED", "Unclassified", "Unknown", False),
    ("PLANNED_MAINTENANCE", "Planned maintenance", "Maintenance", True),
    ("CHANGEOVER", "Product changeover", "Setup", True),
    ("PLANNED_BREAK", "Planned break", "Organisational", True),
    ("BREAKDOWN", "Equipment breakdown", "Technical", False),
    ("MINOR_STOP", "Minor stop", "Technical", False),
    ("MATERIAL_SHORTAGE", "Material shortage", "Supply", False),
    ("OPERATOR_ABSENT", "No operator", "Organisational", False),
    ("QUALITY_HOLD", "Quality hold", "Quality", False),
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """A CHECK body constraining `column` to `values`."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


# --------------------------------------------------------------------------------------
# Master data - schema `model`
# --------------------------------------------------------------------------------------


class Product(Base):
    """Something the plant makes. Ideal cycle time is per Asset and per Product."""

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("code", name="uq_product_code"),
        CheckConstraint("code <> ''", name="ck_product_code_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    """The value that appears on the product/recipe topic, e.g. 'RECIPE-A'."""

    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"Product(code={self.code!r})"


class ShiftPattern(Base):
    """A named weekly shift schedule, in one timezone."""

    __tablename__ = "shift_pattern"
    __table_args__ = (
        UniqueConstraint("name", name="uq_shift_pattern_name"),
        CheckConstraint("timezone <> ''", name="ck_shift_pattern_timezone_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    """IANA zone name, e.g. 'Europe/Berlin'. Shift slots are local wall-clock times, so
    the zone is what makes a 06:00 start mean 06:00 to the operator across a DST change."""

    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=True,
    )
    """The Asset this pattern was authored for, for display and scoping only. NULL means
    site-wide. Which pattern a unit uses is decided by `oee_unit.shift_pattern_id`."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"ShiftPattern(name={self.name!r}, timezone={self.timezone!r})"


class ShiftPatternSlot(Base):
    """One shift within a weekly pattern.

    Stored as (day, local start time, duration) rather than (start, end) so a shift that
    crosses midnight needs no second row and no end-before-start special case.
    """

    __tablename__ = "shift_pattern_slot"
    __table_args__ = (
        UniqueConstraint(
            "shift_pattern_id", "day_of_week", "start_time", name="uq_shift_slot_pattern_day_start"
        ),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_shift_slot_day_of_week"),
        CheckConstraint(
            "duration_minutes > 0 AND duration_minutes <= 1440", name="ck_shift_slot_duration"
        ),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shift_pattern_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.shift_pattern.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    """0 = Monday, matching `datetime.date.weekday()`."""

    start_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    """Local wall-clock start, resolved through the pattern's timezone at read time."""

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """What the operators call it, e.g. 'A'. Published on the KPI payload."""

    def __repr__(self) -> str:
        return f"ShiftPatternSlot(day={self.day_of_week}, start={self.start_time}, label={self.label!r})"


class ShiftException(Base):
    """A window that is not available for production, overriding the weekly pattern."""

    __tablename__ = "shift_exception"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_shift_exception_range"),
        CheckConstraint(_in_list("kind", SHIFT_EXCEPTION_KINDS), name="ck_shift_exception_kind"),
        Index("idx_shift_exception_window", "starts_at", "ends_at"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=True,
    )
    """NULL means every Asset - a plant holiday is one row, not one per line."""

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="PLANNED_DOWN")
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"ShiftException(kind={self.kind!r}, starts_at={self.starts_at})"


class OeeUnit(Base):
    """An Asset that OEE is reported for, and where its inputs come from.

    The subject is the Line, because that is the number a plant manages. The metric
    bindings are paths relative to the Line's topic prefix, so they can name a descendant
    machine - `Cell1/MES-01/Status/PackMlState/value` - without a second Asset row and
    without a column that duplicates the tree.
    """

    __tablename__ = "oee_unit"
    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_oee_unit_asset"),
        CheckConstraint("state_metric_key <> ''", name="ck_oee_unit_state_metric_key"),
        CheckConstraint(
            "array_length(producing_states, 1) >= 1", name="ck_oee_unit_producing_states"
        ),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_pattern_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.shift_pattern.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state_metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    good_count_metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    reject_count_metric_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    """NULL when the line publishes no reject counter. Quality is then 1.0."""

    product_metric_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    """NULL when the line makes one product. Ideal cycle time then falls back to the
    Asset-wide row, which is what the NULL `product_id` in `ideal_cycle_time` is for."""

    producing_states: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{EXECUTE}'::text[]")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"OeeUnit(asset_id={self.asset_id}, state_metric_key={self.state_metric_key!r})"


class IdealCycleTime(Base):
    """Seconds per unit at the designed rate, per Asset and optionally per Product."""

    __tablename__ = "ideal_cycle_time"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "product_id",
            name="uq_ideal_cycle_time_asset_product",
            # A NULL product_id means 'any product on this Asset'. Without this, two such
            # rows would both be accepted and the lookup would be ambiguous.
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("seconds_per_unit > 0", name="ck_ideal_cycle_time_positive"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.product.id", ondelete="CASCADE"),
        nullable=True,
    )
    seconds_per_unit: Mapped[float] = mapped_column(Double, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"IdealCycleTime(asset_id={self.asset_id}, product_id={self.product_id})"


class DowntimeReason(Base):
    """A downtime reason code and whether it counts as planned.

    `is_planned` is an input to the calculation, not a label: a planned stop leaves
    Loading Time, an unplanned one leaves Run Time. That is why classification runs
    before the calculator.
    """

    __tablename__ = "downtime_reason"
    __table_args__ = (
        CheckConstraint("code <> ''", name="ck_downtime_reason_code_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_planned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    def __repr__(self) -> str:
        return f"DowntimeReason(code={self.code!r}, is_planned={self.is_planned})"


class StateReasonMap(Base):
    """Maps a published state value to a reason code, for auto-classification."""

    __tablename__ = "state_reason_map"
    __table_args__ = (
        UniqueConstraint(
            "oee_unit_id",
            "state_value",
            name="uq_state_reason_map_unit_state",
            # NULL oee_unit_id is the default rule for every unit; two defaults for one
            # state value would make classification depend on row order.
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("state_value <> ''", name="ck_state_reason_map_state_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=True,
    )
    """NULL is the platform default rule. A unit-specific row wins over it."""

    state_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{MODEL_SCHEMA}.downtime_reason.code", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"StateReasonMap(unit={self.oee_unit_id}, state={self.state_value!r})"
```

- [ ] **Step 5: Write the result tables into the same file**

Append to `09_uns_model/src/uns_model/oee_tables.py`:

```python
# --------------------------------------------------------------------------------------
# Results - schema `oee`
# --------------------------------------------------------------------------------------


class ShiftResult(Base):
    """The current OEE result for one unit and one shift.

    One row per (unit, shift_start), overwritten in place when a revision supersedes it.
    The superseded numbers move to `shift_result_revision`, so a dashboard reads one row
    and an audit can still see what the number was yesterday.
    """

    __tablename__ = "shift_result"
    __table_args__ = (
        UniqueConstraint("oee_unit_id", "shift_start", name="uq_shift_result_unit_start"),
        CheckConstraint("shift_end > shift_start", name="ck_shift_result_range"),
        CheckConstraint(_in_list("status", OEE_STATUSES), name="ck_shift_result_status"),
        CheckConstraint("revision >= 1", name="ck_shift_result_revision"),
        CheckConstraint(
            "good_count >= 0 AND reject_count >= 0 AND total_count >= 0",
            name="ck_shift_result_counts_non_negative",
        ),
        Index("idx_shift_result_shift_start", "shift_start"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    loading_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    run_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    planned_down_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    unplanned_down_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")

    good_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    reject_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    total_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")

    availability: Mapped[float | None] = mapped_column(Double, nullable=True)
    performance: Mapped[float | None] = mapped_column(Double, nullable=True)
    performance_raw: Mapped[float | None] = mapped_column(Double, nullable=True)
    """Performance before the clamp at 1.0. A value above 1 means the ideal cycle time is
    wrong or a stop was missed, and the unclamped number is the only evidence of that."""

    quality: Mapped[float | None] = mapped_column(Double, nullable=True)
    oee: Mapped[float | None] = mapped_column(Double, nullable=True)
    """Ratios are NULL, never zero, when they are undefined. A shift with no Loading Time
    did not achieve 0% Availability - it has no Availability, and averaging a fabricated
    zero drags every rollup down."""

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="OK")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """Row count and max(time) over the input window. Equal fingerprint means equal input,
    so a re-check can skip the whole computation."""

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """NULL means the result exists but has not reached MQTT. The engine retries these."""

    def __repr__(self) -> str:
        return f"ShiftResult(unit={self.oee_unit_id}, shift_start={self.shift_start}, oee={self.oee})"


class ShiftResultProduct(Base):
    """Per-product counts and ideal time within one shift result.

    Performance is a sum over products, so the terms have to be stored: a mixed shift's
    number cannot be re-derived from the totals once the product mix is gone.
    """

    __tablename__ = "shift_result_product"
    __table_args__ = (
        UniqueConstraint("shift_result_id", "product_code", name="uq_shift_result_product"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shift_result_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{OEE_SCHEMA}.shift_result.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """The raw published value, not a FK: an unknown recipe must still be recorded."""

    good_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    reject_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    total_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    ideal_cycle_time_s: Mapped[float | None] = mapped_column(Double, nullable=True)
    """NULL when no ideal cycle time was configured, which sets status
    MISSING_IDEAL_CYCLE_TIME on the parent row."""

    def __repr__(self) -> str:
        return f"ShiftResultProduct(product={self.product_code!r}, total={self.total_count})"


class ShiftResultRevision(Base):
    """A superseded result, kept verbatim so a changed number can be explained."""

    __tablename__ = "shift_result_revision"
    __table_args__ = (
        UniqueConstraint("oee_unit_id", "shift_start", "revision", name="uq_shift_result_revision"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    loading_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    run_time_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    good_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    reject_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    total_count: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    availability: Mapped[float | None] = mapped_column(Double, nullable=True)
    performance: Mapped[float | None] = mapped_column(Double, nullable=True)
    quality: Mapped[float | None] = mapped_column(Double, nullable=True)
    oee: Mapped[float | None] = mapped_column(Double, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="OK")
    input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"ShiftResultRevision(unit={self.oee_unit_id}, revision={self.revision})"


class DowntimeEvent(Base):
    """One stop, with the reason it is attributed to.

    Keyed on (unit, started_at) rather than on the shift result, because a manual reason
    assignment must survive recomputation - and recomputation replaces the result row.
    """

    __tablename__ = "downtime_event"
    __table_args__ = (
        UniqueConstraint("oee_unit_id", "started_at", name="uq_downtime_event_unit_start"),
        CheckConstraint("ended_at > started_at", name="ck_downtime_event_range"),
        CheckConstraint(
            _in_list("reason_source", REASON_SOURCES), name="ck_downtime_event_reason_source"
        ),
        Index("idx_downtime_event_shift", "oee_unit_id", "shift_start"),
        Index("idx_downtime_event_reason", "reason_code"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    state_value: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """The published state that held for the whole stop, e.g. 'ABORTED'."""

    reason_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{MODEL_SCHEMA}.downtime_reason.code", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
        server_default=UNCLASSIFIED_REASON_CODE,
    )
    reason_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="auto")
    assigned_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"DowntimeEvent(unit={self.oee_unit_id}, started_at={self.started_at})"


class RecomputeRequest(Base):
    """A queued request to recompute a range, from the CLI or a reason reassignment.

    A queue rather than a direct call: a reason change arrives on the GraphQL process, and
    the engine is the only writer of results. `claimed_at` is how a single worker takes a
    request without a lock table.
    """

    __tablename__ = "recompute_request"
    __table_args__ = (
        CheckConstraint("range_end > range_start", name="ck_recompute_request_range"),
        Index("idx_recompute_request_pending", "claimed_at", "requested_at"),
        {"schema": OEE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    oee_unit_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.oee_unit.id", ondelete="CASCADE"),
        nullable=True,
    )
    """NULL means every active unit."""

    range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"RecomputeRequest(unit={self.oee_unit_id}, range_start={self.range_start})"


__all__ = [
    "DEFAULT_DOWNTIME_REASONS",
    "DEFAULT_PRODUCING_STATES",
    "OEE_STATUSES",
    "REASON_SOURCES",
    "SHIFT_EXCEPTION_KINDS",
    "UNCLASSIFIED_REASON_CODE",
    "DowntimeEvent",
    "DowntimeReason",
    "IdealCycleTime",
    "OeeUnit",
    "Product",
    "RecomputeRequest",
    "ShiftException",
    "ShiftPattern",
    "ShiftPatternSlot",
    "ShiftResult",
    "ShiftResultProduct",
    "ShiftResultRevision",
    "StateReasonMap",
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest 09_uns_model/test/test_oee_tables.py -v -n 0`
Expected: PASS (7 passed — the parametrised test counts twice).

- [ ] **Step 7: Write the migration — header and master-data tables**

The current Alembic head is `0002_console_alert_rules`, so that is `down_revision`.

`09_uns_model/migrations/versions/0003_oee_model.py`:

```python
"""OEE master data in schema `model` and shift results in schema `oee`.

Revision ID: 0003_oee_model
Revises: 0002_console_alert_rules
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_oee_model"
down_revision: str | None = "0002_console_alert_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_SCHEMA = "model"
OEE_SCHEMA = "oee"

# Duplicated from uns_model.oee_tables on purpose: a migration is a historical record and
# must keep applying even after the application constant changes.
DEFAULT_DOWNTIME_REASONS = (
    ("UNCLASSIFIED", "Unclassified", "Unknown", False),
    ("PLANNED_MAINTENANCE", "Planned maintenance", "Maintenance", True),
    ("CHANGEOVER", "Product changeover", "Setup", True),
    ("PLANNED_BREAK", "Planned break", "Organisational", True),
    ("BREAKDOWN", "Equipment breakdown", "Technical", False),
    ("MINOR_STOP", "Minor stop", "Technical", False),
    ("MATERIAL_SHORTAGE", "Material shortage", "Supply", False),
    ("OPERATOR_ABSENT", "No operator", "Organisational", False),
    ("QUALITY_HOLD", "Quality hold", "Quality", False),
)


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(OEE_SCHEMA, if_not_exists=True))
    op.execute(
        f"COMMENT ON SCHEMA {OEE_SCHEMA} IS "
        f"'Derived shift OEE results. Rebuildable from the historian at any time.'"
    )
    _create_master_data()
    _create_results()
    _seed_reasons()
    _grant()


def _create_master_data() -> None:
    op.create_table(
        "product",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_product_code"),
        sa.CheckConstraint("code <> ''", name="ck_product_code_not_empty"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "shift_pattern",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), server_default="UTC", nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("name", name="uq_shift_pattern_name"),
        sa.CheckConstraint("timezone <> ''", name="ck_shift_pattern_timezone_not_empty"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "shift_pattern_slot",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("shift_pattern_id", sa.BigInteger(), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(timezone=False), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["shift_pattern_id"], [f"{MODEL_SCHEMA}.shift_pattern.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "shift_pattern_id", "day_of_week", "start_time", name="uq_shift_slot_pattern_day_start"
        ),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_shift_slot_day_of_week"),
        sa.CheckConstraint(
            "duration_minutes > 0 AND duration_minutes <= 1440", name="ck_shift_slot_duration"
        ),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "shift_exception",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), server_default="PLANNED_DOWN", nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_shift_exception_range"),
        sa.CheckConstraint(
            "kind IN ('PLANNED_DOWN', 'NON_PRODUCING', 'HOLIDAY')", name="ck_shift_exception_kind"
        ),
        schema=MODEL_SCHEMA,
    )
    op.create_index(
        "idx_shift_exception_window", "shift_exception", ["starts_at", "ends_at"], schema=MODEL_SCHEMA
    )

    op.create_table(
        "downtime_reason",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), server_default="", nullable=False),
        sa.Column("is_planned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("code"),
        sa.CheckConstraint("code <> ''", name="ck_downtime_reason_code_not_empty"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "oee_unit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_pattern_id", sa.BigInteger(), nullable=False),
        sa.Column("state_metric_key", sa.Text(), nullable=False),
        sa.Column("good_count_metric_key", sa.Text(), nullable=False),
        sa.Column("reject_count_metric_key", sa.Text(), nullable=True),
        sa.Column("product_metric_key", sa.Text(), nullable=True),
        sa.Column(
            "producing_states",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{EXECUTE}'::text[]"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shift_pattern_id"], [f"{MODEL_SCHEMA}.shift_pattern.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("asset_id", name="uq_oee_unit_asset"),
        sa.CheckConstraint("state_metric_key <> ''", name="ck_oee_unit_state_metric_key"),
        sa.CheckConstraint(
            "array_length(producing_states, 1) >= 1", name="ck_oee_unit_producing_states"
        ),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "ideal_cycle_time",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("seconds_per_unit", sa.Double(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["asset_id"], [f"{MODEL_SCHEMA}.asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], [f"{MODEL_SCHEMA}.product.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "asset_id",
            "product_id",
            name="uq_ideal_cycle_time_asset_product",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("seconds_per_unit > 0", name="ck_ideal_cycle_time_positive"),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "state_reason_map",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=True),
        sa.Column("state_value", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reason_code"],
            [f"{MODEL_SCHEMA}.downtime_reason.code"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "oee_unit_id",
            "state_value",
            name="uq_state_reason_map_unit_state",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("state_value <> ''", name="ck_state_reason_map_state_not_empty"),
        schema=MODEL_SCHEMA,
    )
```

- [ ] **Step 8: Add the result tables, the seed and the grants to the migration**

Append to `09_uns_model/migrations/versions/0003_oee_model.py`:

```python
def _create_results() -> None:
    op.create_table(
        "shift_result",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shift_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shift_label", sa.Text(), server_default="", nullable=False),
        sa.Column("loading_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("run_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("planned_down_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("unplanned_down_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("good_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("reject_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("availability", sa.Double(), nullable=True),
        sa.Column("performance", sa.Double(), nullable=True),
        sa.Column("performance_raw", sa.Double(), nullable=True),
        sa.Column("quality", sa.Double(), nullable=True),
        sa.Column("oee", sa.Double(), nullable=True),
        sa.Column("status", sa.Text(), server_default="OK", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_fingerprint", sa.Text(), server_default="", nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("oee_unit_id", "shift_start", name="uq_shift_result_unit_start"),
        sa.CheckConstraint("shift_end > shift_start", name="ck_shift_result_range"),
        sa.CheckConstraint(
            "status IN ('OK', 'NO_LOADING_TIME', 'NO_PRODUCTION', 'MISSING_IDEAL_CYCLE_TIME', "
            "'NO_INPUT_DATA')",
            name="ck_shift_result_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_shift_result_revision"),
        sa.CheckConstraint(
            "good_count >= 0 AND reject_count >= 0 AND total_count >= 0",
            name="ck_shift_result_counts_non_negative",
        ),
        schema=OEE_SCHEMA,
    )
    op.create_index("idx_shift_result_shift_start", "shift_result", ["shift_start"], schema=OEE_SCHEMA)

    op.create_table(
        "shift_result_product",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("shift_result_id", sa.BigInteger(), nullable=False),
        sa.Column("product_code", sa.Text(), server_default="", nullable=False),
        sa.Column("good_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("reject_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("ideal_cycle_time_s", sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["shift_result_id"], [f"{OEE_SCHEMA}.shift_result.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("shift_result_id", "product_code", name="uq_shift_result_product"),
        schema=OEE_SCHEMA,
    )

    op.create_table(
        "shift_result_revision",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("loading_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("run_time_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("good_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("reject_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Double(), server_default="0", nullable=False),
        sa.Column("availability", sa.Double(), nullable=True),
        sa.Column("performance", sa.Double(), nullable=True),
        sa.Column("quality", sa.Double(), nullable=True),
        sa.Column("oee", sa.Double(), nullable=True),
        sa.Column("status", sa.Text(), server_default="OK", nullable=False),
        sa.Column("input_fingerprint", sa.Text(), server_default="", nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("oee_unit_id", "shift_start", "revision", name="uq_shift_result_revision"),
        schema=OEE_SCHEMA,
    )

    op.create_table(
        "downtime_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("state_value", sa.Text(), server_default="", nullable=False),
        sa.Column("reason_code", sa.Text(), server_default="UNCLASSIFIED", nullable=False),
        sa.Column("reason_source", sa.Text(), server_default="auto", nullable=False),
        sa.Column("assigned_by", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reason_code"],
            [f"{MODEL_SCHEMA}.downtime_reason.code"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("oee_unit_id", "started_at", name="uq_downtime_event_unit_start"),
        sa.CheckConstraint("ended_at > started_at", name="ck_downtime_event_range"),
        sa.CheckConstraint(
            "reason_source IN ('auto', 'manual')", name="ck_downtime_event_reason_source"
        ),
        schema=OEE_SCHEMA,
    )
    op.create_index(
        "idx_downtime_event_shift", "downtime_event", ["oee_unit_id", "shift_start"], schema=OEE_SCHEMA
    )
    op.create_index("idx_downtime_event_reason", "downtime_event", ["reason_code"], schema=OEE_SCHEMA)

    op.create_table(
        "recompute_request",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("oee_unit_id", sa.BigInteger(), nullable=True),
        sa.Column("range_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["oee_unit_id"], [f"{MODEL_SCHEMA}.oee_unit.id"], ondelete="CASCADE"),
        sa.CheckConstraint("range_end > range_start", name="ck_recompute_request_range"),
        schema=OEE_SCHEMA,
    )
    op.create_index(
        "idx_recompute_request_pending",
        "recompute_request",
        ["claimed_at", "requested_at"],
        schema=OEE_SCHEMA,
    )


def _seed_reasons() -> None:
    op.bulk_insert(
        sa.table(
            "downtime_reason",
            sa.column("code", sa.Text),
            sa.column("display_name", sa.Text),
            sa.column("category", sa.Text),
            sa.column("is_planned", sa.Boolean),
            schema=MODEL_SCHEMA,
        ),
        [
            {"code": code, "display_name": display, "category": category, "is_planned": is_planned}
            for code, display, category, is_planned in DEFAULT_DOWNTIME_REASONS
        ],
    )


def _grant() -> None:
    # Guarded: the role is created interactively, so it may not exist yet.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
                GRANT USAGE ON SCHEMA {OEE_SCHEMA} TO uns_dbuser;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {OEE_SCHEMA} TO uns_dbuser;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {MODEL_SCHEMA} TO uns_dbuser;
                ALTER DEFAULT PRIVILEGES IN SCHEMA {OEE_SCHEMA}
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uns_dbuser;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    for table in (
        "recompute_request",
        "downtime_event",
        "shift_result_revision",
        "shift_result_product",
        "shift_result",
    ):
        op.drop_table(table, schema=OEE_SCHEMA)
    op.execute(sa.schema.DropSchema(OEE_SCHEMA, if_exists=True))
    for table in (
        "state_reason_map",
        "ideal_cycle_time",
        "oee_unit",
        "downtime_reason",
        "shift_exception",
        "shift_pattern_slot",
        "shift_pattern",
        "product",
    ):
        op.drop_table(table, schema=MODEL_SCHEMA)
```

- [ ] **Step 9: Verify the migration applies and reverses**

With a database running (`docker compose up -d uns_timescale_db`):

Run: `cd 09_uns_model && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: three clean runs, no error. If no database is available in this environment, say so — Task 16's integration test covers it.

- [ ] **Step 10: Commit**

```bash
git add 09_uns_model/src/uns_model/oee_tables.py 09_uns_model/src/uns_model/model_config.py \
        09_uns_model/migrations/versions/0003_oee_model.py 09_uns_model/test/test_oee_tables.py
git commit -m "feat(oee): add OEE master-data and result tables with migration 0003"
```

---

### Task 3: Authored master data — `conf/oee/*.yaml` and the importer

**Files:**
- Create: `conf/oee/shifts.yaml`
- Create: `conf/oee/units.yaml`
- Create: `conf/oee/products.yaml`
- Create: `conf/oee/reasons.yaml`
- Create: `09_uns_model/src/uns_model/oee_master_data.py`
- Create: `09_uns_model/src/uns_model/oee_seed.py`
- Create: `09_uns_model/test/test_oee_seed.py`
- Modify: `09_uns_model/src/uns_model/cli.py` (add `oee_import`, chain it from `main`)
- Modify: `09_uns_model/pyproject.toml` (add `pyyaml` and the `uns_model_oee_import` script)

**Interfaces:**
- Consumes: `uns_config.resolve_conf_dir`, `uns_model.engine.Database`, `uns_model.oee_tables.*`.
- Produces:
  - Specs in `oee_master_data.py`: `ProductSpec(code, name="")`, `ShiftSlotSpec(day_of_week, start_time, duration_minutes, label="")`, `ShiftPatternSpec(name, timezone, asset_path=None, slots=())`, `ShiftExceptionSpec(starts_at, ends_at, kind="PLANNED_DOWN", asset_path=None, note="")`, `DowntimeReasonSpec(code, display_name, category="", is_planned=False)`, `OeeUnitSpec(asset_path, shift_pattern_name, state_metric_key, good_count_metric_key, reject_count_metric_key=None, product_metric_key=None, producing_states=("EXECUTE",))`, `IdealCycleTimeSpec(asset_path, seconds_per_unit, product_code=None)`, `StateReasonRuleSpec(state_value, reason_code, asset_path=None)`. Every spec has `validate() -> None`.
  - `OeeMasterDataRepository(database)` with `async save_product`, `save_shift_pattern`, `save_shift_exception`, `save_downtime_reason`, `save_oee_unit`, `save_ideal_cycle_time`, `save_state_reason_rule`, `counts`.
  - In `oee_seed.py`: `OeeSeedPlan` with `.describe()`, `read_oee_conf(conf_dir=None) -> dict`, `plan_from_oee_config(mapping) -> OeeSeedPlan`, `async apply_plan(repository, plan) -> dict[str, int]`.

- [ ] **Step 1: Write the four configuration files**

`conf/oee/products.yaml` — the recipe codes the simulator actually publishes on `Status/RecipeId`:

```yaml
# conf/oee/products.yaml
# What the plant makes. `code` must equal the value published on the unit's
# product_metric_key topic, because that is how a shift's counts are split by product.

products:
  - code: "R-100-STD"
    name: "Resin 100 standard"
  - code: "R-100-HIGH"
    name: "Resin 100 high-flow"
  - code: "R-220-STD"
    name: "Resin 220 standard"
  - code: "R-330-LOW"
    name: "Resin 330 low-viscosity"
```

`conf/oee/shifts.yaml`:

```yaml
# conf/oee/shifts.yaml
# Weekly shift patterns. `start` is local wall-clock time in `timezone`, so 06:00 stays
# 06:00 to the operator across a daylight-saving change - which means the shift containing
# the spring-forward gap really is 7 hours long, and the autumn one 9.
#
# `duration_minutes` rather than an end time: a shift crossing midnight then needs no
# second row and no end-before-start special case.

patterns:
  - name: "Dormagen 3-shift"
    timezone: "Europe/Berlin"
    asset: "CovestroAG/Dormagen/Production/Line1"
    slots:
      # Monday (0) to Friday (4), three eight-hour shifts.
      - {days: [0, 1, 2, 3, 4], start: "06:00", duration_minutes: 480, label: "A"}
      - {days: [0, 1, 2, 3, 4], start: "14:00", duration_minutes: 480, label: "B"}
      - {days: [0, 1, 2, 3, 4], start: "22:00", duration_minutes: 480, label: "C"}

exceptions:
  # No `asset` means every Asset: a plant holiday is one row, not one per line.
  - starts_at: "2026-12-24T00:00:00+01:00"
    ends_at: "2026-12-27T00:00:00+01:00"
    kind: "HOLIDAY"
    note: "Christmas shutdown"
  - asset: "CovestroAG/Dormagen/Production/Line1"
    starts_at: "2026-09-14T06:00:00+02:00"
    ends_at: "2026-09-14T14:00:00+02:00"
    kind: "PLANNED_DOWN"
    note: "Annual overhaul, Line 1"
```

`conf/oee/units.yaml`:

```yaml
# conf/oee/units.yaml
# Which Assets OEE is reported for, and where their inputs come from.
#
# The subject is the Line, because that is the number a plant manages. The metric keys are
# paths relative to the Line's topic prefix, so they can name a descendant machine without
# a second Asset row: state_metric_key below resolves to the historian metric
# 'CovestroAG/Dormagen/Production/Line1/Cell1/MES-01/Status/PackMlState'.

units:
  - asset: "CovestroAG/Dormagen/Production/Line1"
    shift_pattern: "Dormagen 3-shift"
    state_metric_key: "Cell1/MES-01/Status/PackMlState/value"
    good_count_metric_key: "Cell1/MES-01/ProcessValue/GoodCount/value"
    reject_count_metric_key: "Cell1/MES-01/ProcessValue/RejectCount/value"
    product_metric_key: "Cell1/MES-01/Status/RecipeId/value"
    # EXECUTE is the only PackML state that makes parts. Everything else is a stop.
    producing_states: ["EXECUTE"]
    ideal_cycle_times:
      # No `product` is the fallback used when the published recipe has no row of its own.
      - seconds_per_unit: 3.0
      - {product: "R-100-STD", seconds_per_unit: 3.0}
      - {product: "R-100-HIGH", seconds_per_unit: 2.4}
      - {product: "R-220-STD", seconds_per_unit: 4.5}
      - {product: "R-330-LOW", seconds_per_unit: 6.0}
```

`conf/oee/reasons.yaml`:

```yaml
# conf/oee/reasons.yaml
# Downtime reason codes, and the rules that attribute a published state to one.
#
# `is_planned` is an input to the calculation, not a label: a planned stop is subtracted
# from Loading Time, an unplanned one from Run Time. Getting it wrong moves the OEE number.
#
# Migration 0003 already seeded UNCLASSIFIED, PLANNED_MAINTENANCE, CHANGEOVER,
# PLANNED_BREAK, BREAKDOWN, MINOR_STOP, MATERIAL_SHORTAGE, OPERATOR_ABSENT and
# QUALITY_HOLD. These are the additions this plant needs for the PackML state set.

reasons:
  - {code: "NO_ORDER", display_name: "No order", category: "Organisational", is_planned: true}
  - {code: "ORDER_FINISHING", display_name: "Order finishing", category: "Organisational", is_planned: true}
  - {code: "STARTUP", display_name: "Startup / ramp-up", category: "Setup", is_planned: false}
  - {code: "PROCESS_HOLD", display_name: "Process hold", category: "Technical", is_planned: false}
  - {code: "UPSTREAM_BLOCKED", display_name: "Blocked or starved", category: "Supply", is_planned: false}
  - {code: "OPERATOR_STOP", display_name: "Operator stop", category: "Organisational", is_planned: false}

# No `asset` means the rule is the platform default for every unit. A rule naming an asset
# wins over the default for that unit. EXECUTE is deliberately absent: it is a producing
# state, so it never becomes a stop and never needs a reason.
state_rules:
  - {state: "IDLE", reason: "NO_ORDER"}
  - {state: "STARTING", reason: "STARTUP"}
  - {state: "HOLDING", reason: "PROCESS_HOLD"}
  - {state: "HELD", reason: "MATERIAL_SHORTAGE"}
  - {state: "UNHOLDING", reason: "STARTUP"}
  - {state: "SUSPENDING", reason: "UPSTREAM_BLOCKED"}
  - {state: "SUSPENDED", reason: "UPSTREAM_BLOCKED"}
  - {state: "UNSUSPENDING", reason: "STARTUP"}
  - {state: "COMPLETING", reason: "ORDER_FINISHING"}
  - {state: "COMPLETE", reason: "NO_ORDER"}
  - {state: "RESETTING", reason: "CHANGEOVER"}
  - {state: "ABORTING", reason: "BREAKDOWN"}
  - {state: "ABORTED", reason: "BREAKDOWN"}
  - {state: "CLEARING", reason: "BREAKDOWN"}
  - {state: "STOPPING", reason: "OPERATOR_STOP"}
  - {state: "STOPPED", reason: "OPERATOR_STOP"}
```

- [ ] **Step 2: Write the failing test**

`09_uns_model/test/test_oee_seed.py`:

```python
"""Tests for the conf/oee/*.yaml importer.

`plan_from_oee_config` is a pure function of a mapping, so these need no database and no
files - which is the point of splitting planning from applying.
"""

from datetime import time

import pytest

from uns_model.oee_seed import plan_from_oee_config


CONFIG = {
    "products": {"products": [{"code": "R-100-STD", "name": "Resin 100 standard"}]},
    "shifts": {
        "patterns": [
            {
                "name": "Dormagen 3-shift",
                "timezone": "Europe/Berlin",
                "asset": "CovestroAG/Dormagen/Production/Line1",
                "slots": [
                    {"days": [0, 1], "start": "06:00", "duration_minutes": 480, "label": "A"},
                    {"days": [0], "start": "22:00", "duration_minutes": 480, "label": "C"},
                ],
            }
        ],
        "exceptions": [
            {
                "starts_at": "2026-12-24T00:00:00+01:00",
                "ends_at": "2026-12-27T00:00:00+01:00",
                "kind": "HOLIDAY",
                "note": "Christmas shutdown",
            }
        ],
    },
    "units": {
        "units": [
            {
                "asset": "CovestroAG/Dormagen/Production/Line1",
                "shift_pattern": "Dormagen 3-shift",
                "state_metric_key": "Cell1/MES-01/Status/PackMlState/value",
                "good_count_metric_key": "Cell1/MES-01/ProcessValue/GoodCount/value",
                "reject_count_metric_key": "Cell1/MES-01/ProcessValue/RejectCount/value",
                "product_metric_key": "Cell1/MES-01/Status/RecipeId/value",
                "producing_states": ["EXECUTE"],
                "ideal_cycle_times": [
                    {"seconds_per_unit": 3.0},
                    {"product": "R-100-STD", "seconds_per_unit": 2.4},
                ],
            }
        ]
    },
    "reasons": {
        "reasons": [{"code": "NO_ORDER", "display_name": "No order", "is_planned": True}],
        "state_rules": [{"state": "IDLE", "reason": "NO_ORDER"}],
    },
}


def test_a_slot_is_expanded_once_per_day_it_names():
    plan = plan_from_oee_config(CONFIG)
    slots = plan.patterns[0].slots
    assert [(slot.day_of_week, slot.start_time, slot.label) for slot in slots] == [
        (0, time(6, 0), "A"),
        (1, time(6, 0), "A"),
        (0, time(22, 0), "C"),
    ]
    assert all(slot.duration_minutes == 480 for slot in slots)


def test_ideal_cycle_times_carry_the_units_asset_and_an_optional_product():
    plan = plan_from_oee_config(CONFIG)
    assert [(spec.product_code, spec.seconds_per_unit) for spec in plan.cycle_times] == [
        (None, 3.0),
        ("R-100-STD", 2.4),
    ]
    assert all(
        spec.asset_path == "CovestroAG/Dormagen/Production/Line1" for spec in plan.cycle_times
    )


def test_exception_without_an_asset_applies_to_every_asset():
    plan = plan_from_oee_config(CONFIG)
    assert plan.exceptions[0].asset_path is None
    assert plan.exceptions[0].kind == "HOLIDAY"
    assert plan.exceptions[0].starts_at.utcoffset().total_seconds() == 3600


def test_state_rule_without_an_asset_is_the_platform_default():
    plan = plan_from_oee_config(CONFIG)
    assert plan.state_reason_rules[0].asset_path is None
    assert plan.state_reason_rules[0].state_value == "IDLE"


def test_an_unknown_shift_pattern_name_is_rejected_before_the_database_sees_it():
    broken = {**CONFIG, "units": {"units": [{**CONFIG["units"]["units"][0], "shift_pattern": "Nope"}]}}
    with pytest.raises(ValueError, match="Nope"):
        plan_from_oee_config(broken)


def test_a_producing_state_must_not_also_have_a_reason_rule():
    broken = {
        **CONFIG,
        "reasons": {
            "reasons": CONFIG["reasons"]["reasons"],
            "state_rules": [{"state": "EXECUTE", "reason": "NO_ORDER"}],
        },
    }
    with pytest.raises(ValueError, match="EXECUTE"):
        plan_from_oee_config(broken)


def test_describe_lists_what_would_be_written():
    described = plan_from_oee_config(CONFIG).describe()
    assert "Dormagen 3-shift" in described
    assert "CovestroAG/Dormagen/Production/Line1" in described
    assert "NO_ORDER" in described
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_oee_seed.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_model.oee_seed'`.

- [ ] **Step 4: Write the specs**

`09_uns_model/src/uns_model/oee_master_data.py`, first half:

```python
"""Authoring access to the OEE master data in schema `model`.

Follows `alert_rules.py`: a frozen dataclass spec per table with a `validate()` that
produces a readable error before Postgres gets a chance to produce an unreadable one, and
one repository that owns every write. Reads used by the engine live in the second half of
this file, added in Task 8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from uns_model.engine import Database
from uns_model.oee_tables import (
    DEFAULT_PRODUCING_STATES,
    SHIFT_EXCEPTION_KINDS,
    DowntimeReason,
    IdealCycleTime,
    OeeUnit,
    Product,
    ShiftException,
    ShiftPattern,
    ShiftPatternSlot,
    StateReasonMap,
)
from uns_model.tables import Asset


def _require_one_of(what: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {', '.join(allowed)}, got {value!r}")


def _require_non_empty(what: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{what} must not be empty")


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """Something the plant makes."""

    code: str
    name: str = ""

    def validate(self) -> None:
        _require_non_empty("product code", self.code)


@dataclass(frozen=True, slots=True)
class ShiftSlotSpec:
    """One shift on one weekday, as local wall-clock start plus duration."""

    day_of_week: int
    start_time: time
    duration_minutes: int
    label: str = ""

    def validate(self) -> None:
        if not 0 <= self.day_of_week <= 6:
            raise ValueError(f"day_of_week must be 0 (Monday) to 6 (Sunday), got {self.day_of_week}")
        if not 0 < self.duration_minutes <= 1440:
            raise ValueError(f"duration_minutes must be 1 to 1440, got {self.duration_minutes}")


@dataclass(frozen=True, slots=True)
class ShiftPatternSpec:
    """A named weekly schedule in one timezone."""

    name: str
    timezone: str
    asset_path: str | None = None
    slots: tuple[ShiftSlotSpec, ...] = ()

    def validate(self) -> None:
        _require_non_empty("shift pattern name", self.name)
        _require_non_empty("shift pattern timezone", self.timezone)
        if not self.slots:
            raise ValueError(f"shift pattern {self.name!r} declares no slots, so no shift ever closes")
        for slot in self.slots:
            slot.validate()


@dataclass(frozen=True, slots=True)
class ShiftExceptionSpec:
    """A window that is not available for production."""

    starts_at: datetime
    ends_at: datetime
    kind: str = "PLANNED_DOWN"
    asset_path: str | None = None
    note: str = ""

    def validate(self) -> None:
        _require_one_of("shift exception kind", self.kind, SHIFT_EXCEPTION_KINDS)
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("shift exception timestamps must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError(f"shift exception ends_at {self.ends_at} is not after starts_at {self.starts_at}")


@dataclass(frozen=True, slots=True)
class DowntimeReasonSpec:
    """A reason code and whether it counts as planned."""

    code: str
    display_name: str
    category: str = ""
    is_planned: bool = False

    def validate(self) -> None:
        _require_non_empty("downtime reason code", self.code)
        _require_non_empty("downtime reason display_name", self.display_name)


@dataclass(frozen=True, slots=True)
class OeeUnitSpec:
    """An Asset OEE is reported for, and where its inputs come from."""

    asset_path: str
    shift_pattern_name: str
    state_metric_key: str
    good_count_metric_key: str
    reject_count_metric_key: str | None = None
    product_metric_key: str | None = None
    producing_states: tuple[str, ...] = DEFAULT_PRODUCING_STATES

    def validate(self) -> None:
        _require_non_empty("unit asset path", self.asset_path)
        _require_non_empty("unit shift_pattern", self.shift_pattern_name)
        _require_non_empty("unit state_metric_key", self.state_metric_key)
        _require_non_empty("unit good_count_metric_key", self.good_count_metric_key)
        if not self.producing_states:
            raise ValueError(
                f"unit {self.asset_path!r} declares no producing states, so Run Time would always be zero"
            )


@dataclass(frozen=True, slots=True)
class IdealCycleTimeSpec:
    """Seconds per unit at the designed rate. `product_code` None is the fallback."""

    asset_path: str
    seconds_per_unit: float
    product_code: str | None = None

    def validate(self) -> None:
        _require_non_empty("ideal cycle time asset path", self.asset_path)
        if self.seconds_per_unit <= 0:
            raise ValueError(
                f"ideal cycle time for {self.asset_path!r} must be greater than zero, "
                f"got {self.seconds_per_unit}"
            )


@dataclass(frozen=True, slots=True)
class StateReasonRuleSpec:
    """Attributes a published state value to a reason code. None asset is the default."""

    state_value: str
    reason_code: str
    asset_path: str | None = None

    def validate(self) -> None:
        _require_non_empty("state rule state", self.state_value)
        _require_non_empty("state rule reason", self.reason_code)
```

- [ ] **Step 5: Write the repository into the same file**

Append to `09_uns_model/src/uns_model/oee_master_data.py`:

```python
class OeeMasterDataRepository:
    """Every write to the OEE master data.

    Idempotent by natural key throughout - product code, pattern name, (asset, product),
    (unit, state) - so re-importing an edited `conf/oee/` updates rather than duplicates.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ---- writes -------------------------------------------------------------------

    async def save_product(self, spec: ProductSpec) -> int:
        spec.validate()
        statement = (
            insert(Product)
            .values(code=spec.code, name=spec.name)
            .on_conflict_do_update(index_elements=[Product.code], set_={"name": spec.name})
            .returning(Product.id)
        )
        async with self._database.session() as session:
            return (await session.execute(statement)).scalar_one()

    async def save_downtime_reason(self, spec: DowntimeReasonSpec) -> str:
        spec.validate()
        statement = (
            insert(DowntimeReason)
            .values(
                code=spec.code,
                display_name=spec.display_name,
                category=spec.category,
                is_planned=spec.is_planned,
            )
            .on_conflict_do_update(
                index_elements=[DowntimeReason.code],
                set_={
                    "display_name": spec.display_name,
                    "category": spec.category,
                    "is_planned": spec.is_planned,
                },
            )
            .returning(DowntimeReason.code)
        )
        async with self._database.session() as session:
            return (await session.execute(statement)).scalar_one()

    async def save_shift_pattern(self, spec: ShiftPatternSpec) -> int:
        """Upsert the pattern, then replace its slots wholesale.

        Replace rather than merge: the pattern is authored as one document, so a slot
        deleted from the YAML has to disappear from the database too.
        """
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._asset_id(session, spec.asset_path)
            pattern_id = (
                await session.execute(
                    insert(ShiftPattern)
                    .values(name=spec.name, timezone=spec.timezone, asset_id=asset_id)
                    .on_conflict_do_update(
                        index_elements=[ShiftPattern.name],
                        set_={"timezone": spec.timezone, "asset_id": asset_id},
                    )
                    .returning(ShiftPattern.id)
                )
            ).scalar_one()
            await session.execute(
                delete(ShiftPatternSlot).where(ShiftPatternSlot.shift_pattern_id == pattern_id)
            )
            if spec.slots:
                await session.execute(
                    insert(ShiftPatternSlot),
                    [
                        {
                            "shift_pattern_id": pattern_id,
                            "day_of_week": slot.day_of_week,
                            "start_time": slot.start_time,
                            "duration_minutes": slot.duration_minutes,
                            "label": slot.label,
                        }
                        for slot in spec.slots
                    ],
                )
            return pattern_id

    async def save_shift_exception(self, spec: ShiftExceptionSpec) -> int:
        """Insert an exception, skipping an identical one.

        Keyed on the whole window rather than a surrogate id, so re-importing the same
        holiday does not add a second row - and two genuinely different overlapping
        exceptions are still both kept, because union arithmetic makes that harmless.
        """
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._asset_id(session, spec.asset_path)
            existing = (
                await session.execute(
                    select(ShiftException.id).where(
                        ShiftException.asset_id.is_not_distinct_from(asset_id),
                        ShiftException.starts_at == spec.starts_at,
                        ShiftException.ends_at == spec.ends_at,
                        ShiftException.kind == spec.kind,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
            return (
                await session.execute(
                    insert(ShiftException)
                    .values(
                        asset_id=asset_id,
                        starts_at=spec.starts_at,
                        ends_at=spec.ends_at,
                        kind=spec.kind,
                        note=spec.note,
                    )
                    .returning(ShiftException.id)
                )
            ).scalar_one()

    async def save_oee_unit(self, spec: OeeUnitSpec) -> int:
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._require_asset_id(session, spec.asset_path)
            pattern_id = (
                await session.execute(
                    select(ShiftPattern.id).where(ShiftPattern.name == spec.shift_pattern_name)
                )
            ).scalar_one_or_none()
            if pattern_id is None:
                raise ValueError(
                    f"unit {spec.asset_path!r} names shift pattern {spec.shift_pattern_name!r}, "
                    f"which does not exist"
                )
            values = {
                "asset_id": asset_id,
                "shift_pattern_id": pattern_id,
                "state_metric_key": spec.state_metric_key,
                "good_count_metric_key": spec.good_count_metric_key,
                "reject_count_metric_key": spec.reject_count_metric_key,
                "product_metric_key": spec.product_metric_key,
                "producing_states": list(spec.producing_states),
            }
            statement = (
                insert(OeeUnit)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[OeeUnit.asset_id],
                    set_={**values, "updated_at": func.now()},
                )
                .returning(OeeUnit.id)
            )
            return (await session.execute(statement)).scalar_one()

    async def save_ideal_cycle_time(self, spec: IdealCycleTimeSpec) -> int:
        spec.validate()
        async with self._database.session() as session:
            asset_id = await self._require_asset_id(session, spec.asset_path)
            product_id = None
            if spec.product_code is not None:
                product_id = (
                    await session.execute(select(Product.id).where(Product.code == spec.product_code))
                ).scalar_one_or_none()
                if product_id is None:
                    raise ValueError(
                        f"ideal cycle time on {spec.asset_path!r} names product "
                        f"{spec.product_code!r}, which does not exist"
                    )
            statement = (
                insert(IdealCycleTime)
                .values(asset_id=asset_id, product_id=product_id, seconds_per_unit=spec.seconds_per_unit)
                .on_conflict_do_update(
                    constraint="uq_ideal_cycle_time_asset_product",
                    set_={"seconds_per_unit": spec.seconds_per_unit, "updated_at": func.now()},
                )
                .returning(IdealCycleTime.id)
            )
            return (await session.execute(statement)).scalar_one()

    async def save_state_reason_rule(self, spec: StateReasonRuleSpec) -> int:
        spec.validate()
        async with self._database.session() as session:
            unit_id = None
            if spec.asset_path is not None:
                asset_id = await self._require_asset_id(session, spec.asset_path)
                unit_id = (
                    await session.execute(select(OeeUnit.id).where(OeeUnit.asset_id == asset_id))
                ).scalar_one_or_none()
                if unit_id is None:
                    raise ValueError(
                        f"state rule names asset {spec.asset_path!r}, which is not an OEE unit"
                    )
            statement = (
                insert(StateReasonMap)
                .values(oee_unit_id=unit_id, state_value=spec.state_value, reason_code=spec.reason_code)
                .on_conflict_do_update(
                    constraint="uq_state_reason_map_unit_state",
                    set_={"reason_code": spec.reason_code},
                )
                .returning(StateReasonMap.id)
            )
            return (await session.execute(statement)).scalar_one()

    # ---- reads --------------------------------------------------------------------

    async def counts(self) -> dict[str, int]:
        """Row counts, for the importer's closing log line."""
        tables = {
            "products": Product,
            "shift_patterns": ShiftPattern,
            "shift_pattern_slots": ShiftPatternSlot,
            "shift_exceptions": ShiftException,
            "downtime_reasons": DowntimeReason,
            "oee_units": OeeUnit,
            "ideal_cycle_times": IdealCycleTime,
            "state_reason_rules": StateReasonMap,
        }
        async with self._database.session() as session:
            return {
                name: (await session.execute(select(func.count()).select_from(model))).scalar_one()
                for name, model in tables.items()
            }

    # ---- helpers ------------------------------------------------------------------

    async def _asset_id(self, session: Any, asset_path: str | None) -> int | None:
        """None path means every Asset, which is stored as a NULL asset_id."""
        if asset_path is None:
            return None
        return await self._require_asset_id(session, asset_path)

    async def _require_asset_id(self, session: Any, asset_path: str) -> int:
        asset_id = (
            await session.execute(select(Asset.id).where(Asset.path == asset_path))
        ).scalar_one_or_none()
        if asset_id is None:
            raise ValueError(
                f"Asset {asset_path!r} is not in the Asset Model. Run `uns_model_seed` first."
            )
        return asset_id


__all__ = [
    "DowntimeReasonSpec",
    "IdealCycleTimeSpec",
    "OeeMasterDataRepository",
    "OeeUnitSpec",
    "ProductSpec",
    "ShiftExceptionSpec",
    "ShiftPatternSpec",
    "ShiftSlotSpec",
    "StateReasonRuleSpec",
]
```

- [ ] **Step 6: Write the importer**

`09_uns_model/src/uns_model/oee_seed.py`:

```python
"""Read `conf/oee/*.yaml` into a plan, then apply the plan.

Split for the same reason as `seed.py`: planning is a pure function of a mapping, so every
validation error is reachable from a unit test with no database and no files, and
`--dry-run` prints exactly what the write would do.

Not routed through `uns_config.get_settings()`: that hardcodes
`settings_files=["settings.yaml", ".secrets.yaml"]` for all modules, so widening it for the
OEE module's benefit would change config loading platform-wide.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any

import yaml
from uns_config import resolve_conf_dir

from uns_model.oee_master_data import (
    DowntimeReasonSpec,
    IdealCycleTimeSpec,
    OeeMasterDataRepository,
    OeeUnitSpec,
    ProductSpec,
    ShiftExceptionSpec,
    ShiftPatternSpec,
    ShiftSlotSpec,
    StateReasonRuleSpec,
)
from uns_model.oee_tables import DEFAULT_PRODUCING_STATES

LOGGER = logging.getLogger(__name__)

OEE_CONF_SUBDIR = "oee"
OEE_CONF_FILES = ("products", "shifts", "units", "reasons")


@dataclass(slots=True)
class OeeSeedPlan:
    """Everything an import would write, before anything is written."""

    products: list[ProductSpec] = field(default_factory=list)
    reasons: list[DowntimeReasonSpec] = field(default_factory=list)
    patterns: list[ShiftPatternSpec] = field(default_factory=list)
    exceptions: list[ShiftExceptionSpec] = field(default_factory=list)
    units: list[OeeUnitSpec] = field(default_factory=list)
    cycle_times: list[IdealCycleTimeSpec] = field(default_factory=list)
    state_reason_rules: list[StateReasonRuleSpec] = field(default_factory=list)

    def describe(self) -> str:
        """The plan as text, for `--dry-run`."""
        lines: list[str] = ["Products:"]
        lines += [f"  {spec.code}  {spec.name}" for spec in self.products]
        lines.append("Downtime reasons:")
        lines += [
            f"  {spec.code}  {'planned' if spec.is_planned else 'unplanned'}  {spec.display_name}"
            for spec in self.reasons
        ]
        lines.append("Shift patterns:")
        for spec in self.patterns:
            lines.append(f"  {spec.name}  [{spec.timezone}]  {len(spec.slots)} slot(s)")
            lines += [
                f"    day {slot.day_of_week} {slot.start_time} +{slot.duration_minutes}m  {slot.label}"
                for slot in spec.slots
            ]
        lines.append("Shift exceptions:")
        lines += [
            f"  {spec.kind}  {spec.starts_at} .. {spec.ends_at}  "
            f"{spec.asset_path or '(all Assets)'}  {spec.note}"
            for spec in self.exceptions
        ]
        lines.append("OEE units:")
        for spec in self.units:
            lines.append(f"  {spec.asset_path}  pattern={spec.shift_pattern_name}")
            lines.append(f"    state      {spec.state_metric_key}")
            lines.append(f"    good       {spec.good_count_metric_key}")
            lines.append(f"    reject     {spec.reject_count_metric_key or '(none)'}")
            lines.append(f"    product    {spec.product_metric_key or '(single product)'}")
            lines.append(f"    producing  {', '.join(spec.producing_states)}")
        lines.append("Ideal cycle times:")
        lines += [
            f"  {spec.asset_path}  {spec.product_code or '(any product)'}  {spec.seconds_per_unit}s/unit"
            for spec in self.cycle_times
        ]
        lines.append("State reason rules:")
        lines += [
            f"  {spec.state_value} -> {spec.reason_code}  {spec.asset_path or '(all units)'}"
            for spec in self.state_reason_rules
        ]
        return "\n".join(lines)


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{path.name}: expected a YAML mapping at the top level, got {type(loaded).__name__}")
    return dict(loaded)


def read_oee_conf(conf_dir: Path | None = None) -> dict[str, Any]:
    """Read `conf/oee/*.yaml` into the mapping `plan_from_oee_config` consumes.

    Absent files are skipped rather than defaulted, so a deployment can land shifts before
    it has decided its reason codes.
    """
    directory = (conf_dir if conf_dir is not None else resolve_conf_dir()) / OEE_CONF_SUBDIR
    raw: dict[str, Any] = {}
    for name in OEE_CONF_FILES:
        if (document := _read_yaml_mapping(directory / f"{name}.yaml")) is not None:
            raw[name] = document
    LOGGER.info("Read OEE configuration from %s: %s", directory, ", ".join(sorted(raw)) or "nothing")
    return raw


def _section(config: Mapping[str, Any], file: str, key: str) -> list[Mapping[str, Any]]:
    document = config.get(file) or {}
    entries = document.get(key) or []
    if not isinstance(entries, Sequence) or isinstance(entries, str):
        raise ValueError(f"{file}.yaml: '{key}' must be a list, got {type(entries).__name__}")
    return [dict(entry) for entry in entries]


def _parse_time(raw: Any, where: str) -> time:
    """Accept both a YAML time and a 'HH:MM' string.

    PyYAML turns an unquoted 06:00 into the integer 360 (sexagesimal), so a bare number is
    an authoring mistake worth naming rather than silently accepting.
    """
    if isinstance(raw, time):
        return raw
    if isinstance(raw, str):
        return time.fromisoformat(raw)
    raise ValueError(f"{where}: 'start' must be a quoted 'HH:MM' string, got {raw!r}")


def _parse_datetime(raw: Any, where: str) -> datetime:
    value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if value.tzinfo is None:
        raise ValueError(f"{where}: timestamp {raw!r} has no timezone offset")
    return value


def plan_from_oee_config(config: Mapping[str, Any]) -> OeeSeedPlan:
    """Turn the `conf/oee/` mapping into a plan, validating every cross-reference."""
    plan = OeeSeedPlan()

    for entry in _section(config, "products", "products"):
        plan.products.append(ProductSpec(code=str(entry["code"]), name=str(entry.get("name", ""))))

    for entry in _section(config, "reasons", "reasons"):
        plan.reasons.append(
            DowntimeReasonSpec(
                code=str(entry["code"]),
                display_name=str(entry.get("display_name", entry["code"])),
                category=str(entry.get("category", "")),
                is_planned=bool(entry.get("is_planned", False)),
            )
        )

    for entry in _section(config, "shifts", "patterns"):
        name = str(entry["name"])
        slots: list[ShiftSlotSpec] = []
        for raw_slot in entry.get("slots") or []:
            start = _parse_time(raw_slot.get("start"), f"shifts.yaml pattern {name!r}")
            for day in raw_slot.get("days") or []:
                slots.append(
                    ShiftSlotSpec(
                        day_of_week=int(day),
                        start_time=start,
                        duration_minutes=int(raw_slot["duration_minutes"]),
                        label=str(raw_slot.get("label", "")),
                    )
                )
        plan.patterns.append(
            ShiftPatternSpec(
                name=name,
                timezone=str(entry.get("timezone", "UTC")),
                asset_path=entry.get("asset"),
                slots=tuple(slots),
            )
        )

    for entry in _section(config, "shifts", "exceptions"):
        plan.exceptions.append(
            ShiftExceptionSpec(
                starts_at=_parse_datetime(entry["starts_at"], "shifts.yaml exception"),
                ends_at=_parse_datetime(entry["ends_at"], "shifts.yaml exception"),
                kind=str(entry.get("kind", "PLANNED_DOWN")),
                asset_path=entry.get("asset"),
                note=str(entry.get("note", "")),
            )
        )

    pattern_names = {spec.name for spec in plan.patterns}
    product_codes = {spec.code for spec in plan.products}
    producing_states: set[str] = set()

    for entry in _section(config, "units", "units"):
        asset_path = str(entry["asset"])
        pattern_name = str(entry["shift_pattern"])
        if pattern_name not in pattern_names:
            raise ValueError(
                f"units.yaml: unit {asset_path!r} names shift pattern {pattern_name!r}, "
                f"which shifts.yaml does not define"
            )
        states = tuple(str(state) for state in entry.get("producing_states") or DEFAULT_PRODUCING_STATES)
        producing_states.update(states)
        plan.units.append(
            OeeUnitSpec(
                asset_path=asset_path,
                shift_pattern_name=pattern_name,
                state_metric_key=str(entry["state_metric_key"]),
                good_count_metric_key=str(entry["good_count_metric_key"]),
                reject_count_metric_key=entry.get("reject_count_metric_key"),
                product_metric_key=entry.get("product_metric_key"),
                producing_states=states,
            )
        )
        for raw_cycle in entry.get("ideal_cycle_times") or []:
            product_code = raw_cycle.get("product")
            if product_code is not None and str(product_code) not in product_codes:
                raise ValueError(
                    f"units.yaml: ideal cycle time on {asset_path!r} names product "
                    f"{product_code!r}, which products.yaml does not define"
                )
            plan.cycle_times.append(
                IdealCycleTimeSpec(
                    asset_path=asset_path,
                    seconds_per_unit=float(raw_cycle["seconds_per_unit"]),
                    product_code=None if product_code is None else str(product_code),
                )
            )

    reason_codes = {spec.code for spec in plan.reasons}
    for entry in _section(config, "reasons", "state_rules"):
        state_value = str(entry["state"])
        if state_value in producing_states:
            raise ValueError(
                f"reasons.yaml: {state_value!r} is a producing state, so it can never be a stop "
                f"and must not have a reason rule"
            )
        plan.state_reason_rules.append(
            StateReasonRuleSpec(
                state_value=state_value,
                reason_code=str(entry["reason"]),
                asset_path=entry.get("asset"),
            )
        )
        LOGGER.debug("state rule %s -> %s", state_value, entry["reason"])

    for spec in (
        *plan.products,
        *plan.reasons,
        *plan.patterns,
        *plan.exceptions,
        *plan.units,
        *plan.cycle_times,
        *plan.state_reason_rules,
    ):
        spec.validate()

    # Reason codes not declared here may still be seeded by migration 0003, so an unknown
    # code is a warning at plan time and a foreign-key error at write time - which names
    # the offending code either way.
    for rule in plan.state_reason_rules:
        if rule.reason_code not in reason_codes:
            LOGGER.info(
                "state rule %s -> %s relies on a reason code seeded by migration 0003",
                rule.state_value,
                rule.reason_code,
            )
    return plan


async def apply_plan(repository: OeeMasterDataRepository, plan: OeeSeedPlan) -> dict[str, int]:
    """Write a plan to the OEE master data.

    Order matters: products before their cycle times, patterns before the units that name
    them, units before the unit-scoped reason rules, reasons before the rules that
    reference them.
    """
    for product in plan.products:
        await repository.save_product(product)
    for reason in plan.reasons:
        await repository.save_downtime_reason(reason)
    for pattern in plan.patterns:
        await repository.save_shift_pattern(pattern)
    for exception in plan.exceptions:
        await repository.save_shift_exception(exception)
    for unit in plan.units:
        await repository.save_oee_unit(unit)
    for cycle_time in plan.cycle_times:
        await repository.save_ideal_cycle_time(cycle_time)
    for rule in plan.state_reason_rules:
        await repository.save_state_reason_rule(rule)
    return {
        "products": len(plan.products),
        "downtime_reasons": len(plan.reasons),
        "shift_patterns": len(plan.patterns),
        "shift_exceptions": len(plan.exceptions),
        "oee_units": len(plan.units),
        "ideal_cycle_times": len(plan.cycle_times),
        "state_reason_rules": len(plan.state_reason_rules),
    }


__all__ = ["OeeSeedPlan", "apply_plan", "plan_from_oee_config", "read_oee_conf"]
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest 09_uns_model/test/test_oee_seed.py -v -n 0`
Expected: PASS (7 passed).

- [ ] **Step 8: Add the CLI entry point**

In `09_uns_model/pyproject.toml`, add `"pyyaml>=6.0.2,<7"` to `dependencies` and this to `[project.scripts]`:

```toml
uns_model_oee_import = "uns_model.cli:oee_import"
```

In `09_uns_model/src/uns_model/cli.py`, import the importer beside the existing seed imports:

```python
from uns_model.oee_master_data import OeeMasterDataRepository
from uns_model.oee_seed import OeeSeedPlan, apply_plan as apply_oee_plan, plan_from_oee_config, read_oee_conf
```

and add, after `seed`:

```python
def oee_import(argv: list[str] | None = None) -> int:
    """Import conf/oee/*.yaml into the OEE master data."""
    parser = argparse.ArgumentParser(
        prog="uns_model_oee_import",
        description="Import conf/oee/*.yaml (shift patterns, units, products, reason codes).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    plan = plan_from_oee_config(read_oee_conf())
    if args.dry_run:
        sys.stdout.write(plan.describe() + "\n")
        return 0
    return asyncio.run(_oee_import(plan))


async def _oee_import(plan: OeeSeedPlan) -> int:
    database = Database.from_config(ModelConfig.from_settings())
    try:
        repository = OeeMasterDataRepository(database)
        written = await apply_oee_plan(repository, plan)
        LOGGER.info(
            "Imported %s OEE unit(s), %s shift pattern(s), %s ideal cycle time(s), %s reason rule(s)",
            written["oee_units"],
            written["shift_patterns"],
            written["ideal_cycle_times"],
            written["state_reason_rules"],
        )
        for name, count in sorted((await repository.counts()).items()):
            LOGGER.info("OEE master data now holds %s %s", count, name)
    finally:
        await database.dispose()
    return 0
```

In `main()`, after the seed step and guarded the same way, add an OEE import step so the
`asset_model_setup` container lands master data in one run. Add the flag beside
`--skip-seed`:

```python
    parser.add_argument(
        "--skip-oee-import",
        action="store_true",
        help="Do not import conf/oee/*.yaml after seeding",
    )
```

and after the seed call:

```python
    if not args.skip_oee_import:
        # Absent conf/oee/ is not an error: a deployment that does not report OEE has
        # nothing to import, and the tables stay empty rather than half-populated.
        if read_oee_conf():
            if (code := oee_import(forwarded)) != 0:
                return code
        else:
            LOGGER.info("No conf/oee/ directory, skipping the OEE master-data import")
```

where `forwarded` is the same `["-v"]`-or-`[]` list already built for the seed call.

- [ ] **Step 9: Verify the CLI parses and dry-runs**

Run: `uv run uns_model_oee_import --dry-run -v`
Expected: the plan printed — 4 products, 6 reasons, 1 pattern with 15 slots, 2 exceptions, 1 unit, 5 ideal cycle times, 16 state rules — and exit 0 without touching a database.

- [ ] **Step 10: Commit**

```bash
git add conf/oee 09_uns_model/src/uns_model/oee_master_data.py 09_uns_model/src/uns_model/oee_seed.py \
        09_uns_model/src/uns_model/cli.py 09_uns_model/pyproject.toml 09_uns_model/test/test_oee_seed.py
git commit -m "feat(oee): author OEE master data from conf/oee and import it"
```

---

### Task 4: The shift calendar

**Files:**
- Create: `12_uns_oee/src/uns_oee/shift_calendar.py`
- Create: `12_uns_oee/test/test_shift_calendar.py`
- Modify: `12_uns_oee/pyproject.toml` (add `tzdata`)

**Interfaces:**
- Consumes: nothing from earlier tasks. Pure standard library.
- Produces: `ShiftSlot(day_of_week: int, start_time: time, duration_minutes: int, label: str = "")`; `ShiftSchedule(name: str, timezone: str, slots: tuple[ShiftSlot, ...])` with `.zone -> ZoneInfo`; `ShiftWindow(start: datetime, end: datetime, label: str)` with `.duration_s -> float` and `.is_closed_at(at: datetime, settle_minutes: int) -> bool`; `resolve_local(zone: ZoneInfo, day: date, at: time) -> datetime`; `shift_windows(schedule: ShiftSchedule, from_utc: datetime, to_utc: datetime) -> list[ShiftWindow]`.

Named `ShiftSchedule`, not `ShiftPatternSpec`: `uns_model.oee_master_data.ShiftPatternSpec` already owns that name for the authoring side, and two dataclasses with one name in one pipeline is how the wrong one gets imported.

`tzdata` is a hard dependency, not a nicety. Windows ships no IANA database, so `ZoneInfo("Europe/Berlin")` raises `ZoneInfoNotFoundError` on a developer machine without it — verified in this repository's interpreter. The Alpine image needs it too.

- [ ] **Step 1: Write the failing test**

`12_uns_oee/test/test_shift_calendar.py`:

```python
"""Tests for shift-window generation.

The DST cases are the point of this module. A shift is authored as a local wall-clock start
plus a duration in minutes, and the operator's 22:00-to-06:00 shift really is seven hours
long on the spring-forward night and nine on the autumn one. Getting this wrong moves
Loading Time by an hour twice a year, in opposite directions, which is exactly the kind of
error that shows up as an unexplained OEE step and never as a bug report.
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot, resolve_local, shift_windows

BERLIN = ZoneInfo("Europe/Berlin")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


NIGHTS = ShiftSchedule(
    name="every night",
    timezone="Europe/Berlin",
    slots=tuple(ShiftSlot(day, time(22, 0), 480, "C") for day in range(7)),
)

WEEKDAY_MORNINGS = ShiftSchedule(
    name="weekday mornings",
    timezone="Europe/Berlin",
    slots=tuple(ShiftSlot(day, time(6, 0), 480, "A") for day in range(5)),
)


def test_a_plain_shift_is_its_nominal_length():
    windows = shift_windows(WEEKDAY_MORNINGS, utc(2026, 9, 7), utc(2026, 9, 8))
    assert len(windows) == 1
    assert windows[0].start == utc(2026, 9, 7, 4, 0)
    assert windows[0].end == utc(2026, 9, 7, 12, 0)
    assert windows[0].duration_s == 8 * 3600
    assert windows[0].label == "A"


def test_the_spring_forward_night_shift_is_seven_hours():
    windows = shift_windows(NIGHTS, utc(2026, 3, 28, 12), utc(2026, 3, 29, 12))
    starts = [window.start for window in windows]
    assert utc(2026, 3, 28, 21, 0) in starts
    window = next(w for w in windows if w.start == utc(2026, 3, 28, 21, 0))
    assert window.end == utc(2026, 3, 29, 4, 0)
    assert window.duration_s == 7 * 3600


def test_the_fall_back_night_shift_is_nine_hours():
    windows = shift_windows(NIGHTS, utc(2026, 10, 24, 12), utc(2026, 10, 25, 12))
    window = next(w for w in windows if w.start == utc(2026, 10, 24, 20, 0))
    assert window.end == utc(2026, 10, 25, 5, 0)
    assert window.duration_s == 9 * 3600


@pytest.mark.parametrize(
    ("day", "at", "expected"),
    [
        # Ambiguous: 02:30 happens twice on the fall-back night. fold=0 takes the first.
        (date(2026, 10, 25), time(2, 30), utc(2026, 10, 25, 0, 30)),
        # Non-existent: 02:30 is skipped on the spring-forward night. fold=0 interprets it
        # with the offset in force before the transition, landing on a real later instant.
        (date(2026, 3, 29), time(2, 30), utc(2026, 3, 29, 1, 30)),
    ],
)
def test_resolve_local_never_raises_on_a_dst_boundary(day, at, expected):
    assert resolve_local(BERLIN, day, at) == expected


def test_windows_are_sorted_and_bounded_by_start():
    windows = shift_windows(WEEKDAY_MORNINGS, utc(2026, 9, 7), utc(2026, 9, 12))
    assert windows == sorted(windows, key=lambda window: window.start)
    assert len(windows) == 5
    assert all(utc(2026, 9, 7) <= window.start < utc(2026, 9, 12) for window in windows)


def test_a_shift_is_closed_only_after_the_settle_window():
    window = shift_windows(WEEKDAY_MORNINGS, utc(2026, 9, 7), utc(2026, 9, 8))[0]
    assert not window.is_closed_at(utc(2026, 9, 7, 12, 10), settle_minutes=15)
    assert window.is_closed_at(utc(2026, 9, 7, 12, 15), settle_minutes=15)


def test_an_unknown_timezone_is_named_in_the_error():
    schedule = ShiftSchedule(name="broken", timezone="Mars/Olympus", slots=NIGHTS.slots)
    with pytest.raises(ValueError, match="Mars/Olympus"):
        shift_windows(schedule, utc(2026, 9, 7), utc(2026, 9, 8))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_shift_calendar.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.shift_calendar'`.

- [ ] **Step 3: Add the `tzdata` dependency**

In `12_uns_oee/pyproject.toml`, add to `dependencies`:

```toml
    "tzdata>=2025.2",
```

- [ ] **Step 4: Write the implementation**

`12_uns_oee/src/uns_oee/shift_calendar.py`:

```python
"""Which UTC windows a shift pattern produces.

Pure: a schedule and a UTC range in, a list of windows out. No clock read, no database, no
configuration - which is what makes every DST case reachable from a unit test.

A shift is authored as (weekday, local wall-clock start, duration in minutes) because that
is how a plant describes it. The duration is wall-clock, not elapsed: an eight-hour night
shift is eight hours on the operator's clock, so on the spring-forward night it occupies
seven real hours and on the fall-back night nine. Loading Time has to agree with the clock
on the wall, because that is the clock the shift was staffed against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: Widened by a day at each end when walking local dates, so a shift that starts the day
#: before `from_utc` in local time - or the day after `to_utc` - is still considered.
_EDGE_DAYS = 1


@dataclass(frozen=True, slots=True)
class ShiftSlot:
    """One shift on one weekday. `day_of_week` is 0 = Monday, as `date.weekday()`."""

    day_of_week: int
    start_time: time
    duration_minutes: int
    label: str = ""


@dataclass(frozen=True, slots=True)
class ShiftSchedule:
    """A named weekly pattern in one IANA timezone.

    Distinct from `uns_model.oee_master_data.ShiftPatternSpec`, which is the authoring
    shape. This is the calculation shape: it carries a resolved zone and nothing else.
    """

    name: str
    timezone: str
    slots: tuple[ShiftSlot, ...] = ()

    @property
    def zone(self) -> ZoneInfo:
        """The pattern's zone.

        Raises `ValueError` naming the zone, because `ZoneInfoNotFoundError` alone does not
        say which pattern is misconfigured - and on a host with no IANA database (Windows
        without `tzdata`) every zone fails, which is worth stating plainly.
        """
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                f"shift pattern {self.name!r} names timezone {self.timezone!r}, which this host "
                f"cannot resolve. Install the `tzdata` package or correct the zone name."
            ) from error


@dataclass(frozen=True, slots=True, order=True)
class ShiftWindow:
    """One closed-ended UTC interval a shift occupies. `end` is exclusive."""

    start: datetime
    end: datetime
    label: str = ""

    @property
    def duration_s(self) -> float:
        """Real elapsed seconds, which is not the nominal length across a DST change."""
        return (self.end - self.start).total_seconds()

    def is_closed_at(self, at: datetime, settle_minutes: int) -> bool:
        """True once enough time has passed after `end` for in-flight data to have landed.

        Computing at `end` exactly would read a window the historian has not finished
        receiving, and produce a first revision that is wrong for a knowable reason.
        """
        return at >= self.end + timedelta(minutes=settle_minutes)


def resolve_local(zone: ZoneInfo, day: date, at: time) -> datetime:
    """The instant a local wall-clock time names, as an aware datetime.

    `fold=0` throughout, which is one rule covering both awkward cases: for a local time
    that happens twice it takes the earlier instant, and for one that never happens it
    applies the offset in force before the transition, landing on a real instant. Either
    way it never raises, and two runs over the same shift agree - which Rule 1 requires.
    """
    return datetime.combine(day, at).replace(tzinfo=zone, fold=0)


def shift_windows(schedule: ShiftSchedule, from_utc: datetime, to_utc: datetime) -> list[ShiftWindow]:
    """Every window of `schedule` whose start lies in `[from_utc, to_utc)`, earliest first.

    Bounded by start, not by overlap: a shift belongs to the instant it began, so a caller
    asking for a day gets that day's shifts and not the tail of the previous night's.
    """
    if to_utc <= from_utc:
        return []
    zone = schedule.zone
    windows: list[ShiftWindow] = []
    first_day = (from_utc.astimezone(zone) - timedelta(days=_EDGE_DAYS)).date()
    last_day = (to_utc.astimezone(zone) + timedelta(days=_EDGE_DAYS)).date()

    for slot in schedule.slots:
        day = first_day
        while day <= last_day:
            if day.weekday() == slot.day_of_week:
                windows.append(_window(zone, day, slot))
            day += timedelta(days=1)

    return sorted(
        window for window in windows if from_utc <= window.start < to_utc
    )


def _window(zone: ZoneInfo, day: date, slot: ShiftSlot) -> ShiftWindow:
    """One window, with both ends resolved as local wall-clock times.

    The end is the local start plus the duration, re-resolved through the zone - not the
    start instant plus the duration. Adding to the instant would keep the shift eight real
    hours long and slide its wall-clock end by an hour across a DST change, which is the
    opposite of what the roster says.
    """
    naive_start = datetime.combine(day, slot.start_time)
    naive_end = naive_start + timedelta(minutes=slot.duration_minutes)
    start = resolve_local(zone, naive_start.date(), naive_start.time())
    end = resolve_local(zone, naive_end.date(), naive_end.time())
    return ShiftWindow(
        start=start.astimezone(timezone.utc),
        end=end.astimezone(timezone.utc),
        label=slot.label,
    )


__all__ = ["ShiftSchedule", "ShiftSlot", "ShiftWindow", "resolve_local", "shift_windows"]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv sync && uv run pytest 12_uns_oee/test/test_shift_calendar.py -v -n 0`
Expected: PASS (8 passed — the parametrised test counts twice).

- [ ] **Step 6: Commit**

```bash
git add 12_uns_oee/src/uns_oee/shift_calendar.py 12_uns_oee/test/test_shift_calendar.py \
        12_uns_oee/pyproject.toml
git commit -m "feat(oee): resolve shift patterns into DST-correct UTC windows"
```

---

### Task 5: Counter arithmetic and interval arithmetic

**Files:**
- Create: `12_uns_oee/src/uns_oee/counters.py`
- Create: `12_uns_oee/src/uns_oee/states.py`
- Create: `12_uns_oee/test/test_counters.py`
- Create: `12_uns_oee/test/test_states.py`

**Interfaces:**
- Consumes: nothing. Both modules are standard library only.
- Produces:
  - `counters.Sample(at: datetime, value: float)`; `counters.CounterDelta(total: float, resets: int, samples: int)`; `counters.counter_delta(samples: Sequence[Sample]) -> CounterDelta`; `counters.counter_delta_in(samples: Sequence[Sample], start: datetime, end: datetime) -> CounterDelta`
  - `states.Interval(start: datetime, end: datetime)` with `.duration_s -> float` and `.clipped_to(other: Interval) -> Interval | None`; `states.StateSample(at: datetime, state: str)`; `states.StateSegment(state: str, interval: Interval)`; `states.StopInterval(state: str, interval: Interval)`; `states.state_segments(samples, window) -> list[StateSegment]`; `states.stop_intervals(segments, producing_states) -> list[StopInterval]`; `states.union_duration_s(intervals) -> float`; `states.merge(intervals) -> list[Interval]`; `states.intersect(left, right) -> list[Interval]`; `states.subtract(left, right) -> list[Interval]`

These two modules carry all of the OEE numerator and denominator arithmetic, and nothing else in the module is allowed to reimplement any of it. Every later stage — Loading Time, Run Time, per-product apportioning, the downtime Pareto — is a call into `states`, and every count is a call into `counters`. That is the whole reason they are pure, standard-library-only, and tested first.

- [ ] **Step 1: Write the failing counter test**

`12_uns_oee/test/test_counters.py`:

```python
"""Tests for monotonic counter differencing.

A PLC production counter is not a measurement, it is an odometer. It only ever climbs, and
then one day the operator power-cycles the panel or the tag wraps at 32767 and it starts
again from zero. Differencing naively gives a large negative number, which silently drags a
shift's Good Count below zero and makes Quality nonsense. Every case below is one of those
days.
"""

from datetime import datetime, timedelta, timezone

from uns_oee.counters import Sample, counter_delta, counter_delta_in

T0 = datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def samples(*pairs: tuple[float, float]) -> list[Sample]:
    return [Sample(at=at(minutes), value=value) for minutes, value in pairs]


def test_a_rising_counter_is_last_minus_first():
    delta = counter_delta(samples((0, 100.0), (5, 140.0), (10, 175.0)))
    assert delta.total == 75.0
    assert delta.resets == 0
    assert delta.samples == 3


def test_a_reset_contributes_the_value_after_the_reset():
    # 100 -> 140, then a restart that has already climbed back to 12 by the time we see it.
    delta = counter_delta(samples((0, 100.0), (5, 140.0), (10, 12.0), (15, 30.0)))
    assert delta.total == 40.0 + 12.0 + 18.0
    assert delta.resets == 1


def test_two_resets_are_both_counted():
    delta = counter_delta(samples((0, 50.0), (5, 5.0), (10, 3.0)))
    assert delta.resets == 2
    assert delta.total == 5.0 + 3.0


def test_a_flat_counter_produces_zero_not_none():
    delta = counter_delta(samples((0, 88.0), (5, 88.0)))
    assert delta.total == 0.0
    assert delta.resets == 0


def test_one_sample_cannot_produce_a_delta():
    delta = counter_delta(samples((0, 88.0)))
    assert delta.total == 0.0
    assert delta.samples == 1


def test_no_samples_is_zero_and_not_an_error():
    delta = counter_delta([])
    assert delta.total == 0.0
    assert delta.samples == 0


def test_samples_are_sorted_before_differencing():
    delta = counter_delta(samples((10, 175.0), (0, 100.0), (5, 140.0)))
    assert delta.total == 75.0
    assert delta.resets == 0


def test_a_window_anchors_on_the_sample_at_or_before_the_start():
    # The shift starts at minute 5. The counter read 140 at minute 5 exactly and 200 at the
    # end, so the shift made 60 - the pre-shift climb from 100 must not be included.
    window = counter_delta_in(samples((0, 100.0), (5, 140.0), (30, 200.0)), at(5), at(30))
    assert window.total == 60.0


def test_a_window_uses_the_last_prior_sample_when_none_lands_on_the_boundary():
    # Nothing arrived exactly at minute 10, so minute 8's reading is the baseline. This
    # attributes the two minutes before the shift to the shift, bounded by one sample
    # interval - the alternative loses everything made before the first in-shift sample,
    # which is a larger and less predictable error.
    window = counter_delta_in(samples((8, 140.0), (12, 150.0), (30, 200.0)), at(10), at(30))
    assert window.total == 60.0


def test_a_window_with_no_prior_sample_starts_at_the_first_sample_inside_it():
    window = counter_delta_in(samples((12, 150.0), (30, 200.0)), at(10), at(30))
    assert window.total == 50.0


def test_a_window_excludes_samples_after_its_end():
    window = counter_delta_in(samples((0, 100.0), (30, 200.0), (40, 260.0)), at(0), at(30))
    assert window.total == 100.0


def test_a_window_end_is_inclusive_so_the_closing_sample_counts():
    window = counter_delta_in(samples((0, 100.0), (30, 200.0)), at(0), at(30))
    assert window.total == 100.0


def test_an_empty_window_is_zero():
    window = counter_delta_in(samples((0, 100.0), (30, 200.0)), at(50), at(60))
    assert window.total == 0.0
    assert window.samples == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_counters.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.counters'`.

- [ ] **Step 3: Write `counters.py`**

`12_uns_oee/src/uns_oee/counters.py`:

```python
"""Turning odometer readings into production counts.

A PLC production counter climbs and then, on a power cycle or a tag wrap, restarts. So the
count a shift produced is the sum of the positive steps between consecutive readings, not
last minus first - and a step that goes backwards is read as a restart whose new value is
itself production since the restart.

Pure and stateless: same samples in, same numbers out, on any run. That is Rule 1, and it
is what makes a recomputation of last Tuesday agree with what was stored last Tuesday.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, order=True)
class Sample:
    """One counter reading. `at` is UTC-aware; `value` is the raw tag value."""

    at: datetime
    value: float


@dataclass(frozen=True, slots=True)
class CounterDelta:
    """How much a counter advanced, and how much of that was inferred across a restart.

    `resets` is carried so a suspicious shift is identifiable: one reset in a shift is a
    power cycle, twelve is a misconfigured binding pointed at a value that is not a counter.
    """

    total: float = 0.0
    resets: int = 0
    samples: int = 0


def counter_delta(samples: Sequence[Sample]) -> CounterDelta:
    """The production represented by `samples`, restart-safe.

    Sorted first, because the historian is queried by time but a caller may have merged two
    result sets, and one out-of-order pair would read as a reset and inflate the total.
    """
    ordered = sorted(samples)
    total = 0.0
    resets = 0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        step = current.value - previous.value
        if step >= 0:
            total += step
        else:
            # The counter restarted somewhere in between. Everything it has climbed to
            # since is production; what it lost between `previous` and the restart is not
            # recoverable from the samples and is not invented here.
            resets += 1
            total += max(current.value, 0.0)
    return CounterDelta(total=total, resets=resets, samples=len(ordered))


def counter_delta_in(samples: Sequence[Sample], start: datetime, end: datetime) -> CounterDelta:
    """The production between `start` and `end`, both bounds inclusive.

    When no sample lands on `start` exactly, the last sample before it is pulled in as the
    baseline so the climb up to the first in-shift reading is not lost. That attributes up
    to one sample interval of pre-shift production to the shift; the alternative - starting
    at the first sample inside the window - loses an unbounded amount, because a counter on
    the fifteen-minute meter tier may have no in-shift sample until minute fourteen. A
    sample sitting exactly on the boundary already is the baseline, so nothing is pulled in.
    """
    ordered = sorted(samples)
    inside = [sample for sample in ordered if start <= sample.at <= end]
    prior = [sample for sample in ordered if sample.at < start]
    if inside and prior and inside[0].at > start:
        inside.insert(0, prior[-1])
    return counter_delta(inside)


__all__ = ["CounterDelta", "Sample", "counter_delta", "counter_delta_in"]
```

- [ ] **Step 4: Run the counter test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_counters.py -v -n 0`
Expected: PASS (13 passed).

- [ ] **Step 5: Write the failing state test**

`12_uns_oee/test/test_states.py`:

```python
"""Tests for state segmentation and interval arithmetic.

Two rules are being pinned here. First: the state a machine is in when a shift begins is
whatever it was last reported to be, even if that report predates the shift - a machine
stopped at 05:40 is still stopped at 06:00, and a segmenter that starts at the first
in-shift sample would credit the stop to nobody. Second: durations come from a union, never
from a sum. Overlapping stops double-count under addition, and a double-counted stop can
push Run Time negative.
"""

from datetime import datetime, timedelta, timezone

from uns_oee.states import (
    Interval,
    StateSample,
    StateSegment,
    intersect,
    merge,
    state_segments,
    stop_intervals,
    subtract,
    union_duration_s,
)

PRODUCING = ("EXECUTE",)


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


SHIFT = Interval(t(6), t(14))


def test_the_state_before_the_shift_carries_into_it():
    segments = state_segments(
        [StateSample(t(5, 50), "HELD"), StateSample(t(7), "EXECUTE")], SHIFT
    )
    assert [(segment.state, segment.interval) for segment in segments] == [
        ("HELD", Interval(t(6), t(7))),
        ("EXECUTE", Interval(t(7), t(14))),
    ]


def test_a_sample_on_the_shift_start_is_the_opening_state_and_is_not_duplicated():
    segments = state_segments(
        [StateSample(t(6), "IDLE"), StateSample(t(10), "EXECUTE")], SHIFT
    )
    assert [segment.state for segment in segments] == ["IDLE", "EXECUTE"]
    assert segments[0].interval == Interval(t(6), t(10))


def test_a_sample_on_the_shift_end_belongs_to_the_next_shift():
    segments = state_segments(
        [StateSample(t(6), "EXECUTE"), StateSample(t(14), "HELD")], SHIFT
    )
    assert segments == [StateSegment(state="EXECUTE", interval=Interval(t(6), t(14)))]


def test_repeated_identical_states_become_one_segment():
    segments = state_segments(
        [
            StateSample(t(5, 50), "EXECUTE"),
            StateSample(t(8), "EXECUTE"),
            StateSample(t(11), "EXECUTE"),
        ],
        SHIFT,
    )
    assert len(segments) == 1
    assert segments[0].interval == SHIFT


def test_with_no_prior_sample_the_first_segment_starts_where_the_data_does():
    segments = state_segments([StateSample(t(7), "HELD")], SHIFT)
    assert segments[0].interval == Interval(t(7), t(14))


def test_no_samples_in_or_before_the_window_yields_nothing():
    assert state_segments([StateSample(t(15), "EXECUTE")], SHIFT) == []
    assert state_segments([], SHIFT) == []


def test_stops_are_every_segment_not_in_a_producing_state():
    segments = state_segments(
        [
            StateSample(t(6), "EXECUTE"),
            StateSample(t(9), "HELD"),
            StateSample(t(9, 30), "EXECUTE"),
            StateSample(t(12), "SUSPENDED"),
        ],
        SHIFT,
    )
    stops = stop_intervals(segments, PRODUCING)
    assert [(stop.state, stop.interval.duration_s) for stop in stops] == [
        ("HELD", 1800.0),
        ("SUSPENDED", 7200.0),
    ]
    assert union_duration_s([stop.interval for stop in stops]) == 9000.0


def test_two_producing_states_can_be_declared():
    segments = state_segments(
        [StateSample(t(6), "EXECUTE"), StateSample(t(10), "COMPLETING")], SHIFT
    )
    assert stop_intervals(segments, ("EXECUTE", "COMPLETING")) == []


def test_merge_coalesces_overlapping_and_touching_intervals():
    assert merge(
        [Interval(t(6), t(8)), Interval(t(7), t(9)), Interval(t(9), t(10)), Interval(t(12), t(13))]
    ) == [Interval(t(6), t(10)), Interval(t(12), t(13))]


def test_union_never_double_counts():
    overlapping = [Interval(t(6), t(9)), Interval(t(7), t(10))]
    assert sum(interval.duration_s for interval in overlapping) == 6 * 3600
    assert union_duration_s(overlapping) == 4 * 3600


def test_intersect_keeps_only_common_time():
    assert intersect([Interval(t(6), t(10))], [Interval(t(8), t(12))]) == [Interval(t(8), t(10))]
    assert intersect([Interval(t(6), t(7))], [Interval(t(8), t(9))]) == []


def test_subtract_can_split_an_interval_in_two():
    assert subtract([Interval(t(6), t(14))], [Interval(t(9), t(10))]) == [
        Interval(t(6), t(9)),
        Interval(t(10), t(14)),
    ]


def test_subtract_removes_a_fully_covered_interval():
    assert subtract([Interval(t(9), t(10))], [Interval(t(6), t(14))]) == []


def test_subtract_with_nothing_to_remove_returns_the_merged_input():
    assert subtract([Interval(t(6), t(8)), Interval(t(7), t(9))], []) == [Interval(t(6), t(9))]


def test_a_zero_length_interval_has_no_duration_and_survives_no_operation():
    assert Interval(t(6), t(6)).duration_s == 0.0
    assert merge([Interval(t(6), t(6))]) == []


def test_an_inverted_interval_reads_as_empty_rather_than_negative():
    # Defensive: a caller that mixed up its bounds must not create negative Run Time.
    assert Interval(t(10), t(6)).duration_s == 0.0


def test_clipped_to_is_none_when_there_is_no_overlap():
    assert Interval(t(6), t(7)).clipped_to(Interval(t(8), t(9))) is None
    assert Interval(t(6), t(9)).clipped_to(SHIFT) == Interval(t(6), t(9))


def test_intervals_sort_by_start_then_end():
    unsorted = [Interval(t(8), t(9)), Interval(t(6), t(12)), Interval(t(6), t(7))]
    assert sorted(unsorted) == [Interval(t(6), t(7)), Interval(t(6), t(12)), Interval(t(8), t(9))]


def test_a_stop_that_spans_the_whole_shift_is_the_whole_shift():
    segments = state_segments([StateSample(t(4), "ABORTED")], SHIFT)
    stops = stop_intervals(segments, PRODUCING)
    assert union_duration_s([stop.interval for stop in stops]) == timedelta(hours=8).total_seconds()
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_states.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.states'`.

- [ ] **Step 7: Write `states.py`**

`12_uns_oee/src/uns_oee/states.py`:

```python
"""Machine-state segments and the interval algebra the OEE numbers are built from.

Loading Time is a shift window with planned-down periods subtracted. Run Time is Loading
Time with stops subtracted. A product's share of Run Time is Run Time intersected with the
periods that product was running. All three are the same three operations - merge, subtract,
intersect - so they live here once, and every duration comes out of `union_duration_s`.

Never sum durations. Two stops that overlap sum to more than the time that elapsed, and a
Run Time computed by subtracting a sum can go negative, which surfaces as an OEE above one
or below zero and is not traceable back to the arithmetic that caused it.

Intervals are half-open: `[start, end)`. A sample landing exactly on a shift end therefore
opens the next shift rather than closing this one, and no instant is counted twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, order=True)
class Interval:
    """A half-open UTC interval. Inverted or empty bounds read as zero, never negative."""

    start: datetime
    end: datetime

    @property
    def duration_s(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)

    @property
    def is_empty(self) -> bool:
        return self.end <= self.start

    def clipped_to(self, other: Interval) -> Interval | None:
        """The overlap with `other`, or `None` when they do not overlap."""
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return None if end <= start else Interval(start, end)


@dataclass(frozen=True, slots=True, order=True)
class StateSample:
    """One machine-state report. `state` is the raw published value, e.g. `"EXECUTE"`."""

    at: datetime
    state: str


@dataclass(frozen=True, slots=True)
class StateSegment:
    """A period the machine spent continuously in one state, clipped to the shift."""

    state: str
    interval: Interval


@dataclass(frozen=True, slots=True)
class StopInterval:
    """A segment in a non-producing state - a candidate for a downtime reason code."""

    state: str
    interval: Interval


def state_segments(samples: Sequence[StateSample], window: Interval) -> list[StateSegment]:
    """Segment `window` by machine state.

    The last sample at or before `window.start` sets the opening state, because state is a
    level and not an event: a machine that went down at 05:40 and published nothing since is
    still down at 06:00. With no such sample the first segment starts where the data starts -
    the state before the first report is unknown and is not guessed.

    Consecutive samples reporting the same state are coalesced, so a status tier republishing
    `EXECUTE` every thirty seconds produces one segment and not nine hundred and sixty.
    """
    ordered = sorted(samples)
    prior = [sample for sample in ordered if sample.at <= window.start]
    points = [StateSample(at=window.start, state=prior[-1].state)] if prior else []
    points.extend(sample for sample in ordered if window.start < sample.at < window.end)

    segments: list[StateSegment] = []
    for index, point in enumerate(points):
        end = points[index + 1].at if index + 1 < len(points) else window.end
        if end <= point.at:
            continue
        if segments and segments[-1].state == point.state:
            merged = Interval(segments[-1].interval.start, end)
            segments[-1] = StateSegment(state=point.state, interval=merged)
            continue
        segments.append(StateSegment(state=point.state, interval=Interval(point.at, end)))
    return segments


def stop_intervals(
    segments: Sequence[StateSegment], producing_states: Sequence[str]
) -> list[StopInterval]:
    """Every segment whose state is not one the unit declares as producing.

    Kept as separate stops rather than a merged blanket, because each one gets its own reason
    code: a thirty-minute changeover and a two-hour breakdown are one number in Availability
    and two very different lines in the Pareto.
    """
    producing = set(producing_states)
    return [
        StopInterval(state=segment.state, interval=segment.interval)
        for segment in segments
        if segment.state not in producing
    ]


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    """The input as a minimal set of non-overlapping intervals, earliest first.

    Touching intervals are joined: `[06:00, 08:00)` and `[08:00, 09:00)` describe two hours
    of continuous time and splitting them would only invite a later off-by-one.
    """
    ordered = sorted(interval for interval in intervals if not interval.is_empty)
    merged: list[Interval] = []
    for interval in ordered:
        if merged and interval.start <= merged[-1].end:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return merged


def union_duration_s(intervals: Iterable[Interval]) -> float:
    """Seconds covered by at least one interval. The only sanctioned way to total time."""
    return sum(interval.duration_s for interval in merge(intervals))


def intersect(left: Iterable[Interval], right: Iterable[Interval]) -> list[Interval]:
    """Time covered by both sides."""
    overlaps = [
        clipped
        for one in merge(left)
        for other in merge(right)
        if (clipped := one.clipped_to(other)) is not None
    ]
    return merge(overlaps)


def subtract(left: Iterable[Interval], right: Iterable[Interval]) -> list[Interval]:
    """Time covered by `left` and not by `right`."""
    remaining = merge(left)
    for cut in merge(right):
        next_remaining: list[Interval] = []
        for interval in remaining:
            if cut.end <= interval.start or cut.start >= interval.end:
                next_remaining.append(interval)
                continue
            if interval.start < cut.start:
                next_remaining.append(Interval(interval.start, cut.start))
            if cut.end < interval.end:
                next_remaining.append(Interval(cut.end, interval.end))
        remaining = next_remaining
    return remaining


__all__ = [
    "Interval",
    "StateSample",
    "StateSegment",
    "StopInterval",
    "intersect",
    "merge",
    "state_segments",
    "stop_intervals",
    "subtract",
    "union_duration_s",
]
```

- [ ] **Step 8: Run the state test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_states.py -v -n 0`
Expected: PASS (18 passed).

- [ ] **Step 9: Commit**

```bash
git add 12_uns_oee/src/uns_oee/counters.py 12_uns_oee/src/uns_oee/states.py \
        12_uns_oee/test/test_counters.py 12_uns_oee/test/test_states.py
git commit -m "feat(oee): add restart-safe counter deltas and interval algebra"
```

---

### Task 6: Downtime reason classification

**Files:**
- Create: `12_uns_oee/src/uns_oee/classifier.py`
- Create: `12_uns_oee/test/test_classifier.py`

**Interfaces:**
- Consumes: `uns_oee.states.Interval`, `uns_oee.states.StopInterval` (Task 5); `uns_model.oee_tables.UNCLASSIFIED_REASON_CODE` (Task 2).
- Produces: `ReasonSpec(code: str, display_name: str, category: str, is_planned: bool)`; `ManualReason(reason_code: str, note: str | None = None, assigned_by: str | None = None)`; `ReasonResolver(reasons: Mapping[str, ReasonSpec], unit_rules: Mapping[str, str], default_rules: Mapping[str, str])` with `.resolve(state_value: str) -> ReasonSpec`; `ClassifiedStop(interval: Interval, state_value: str, reason_code: str, is_planned: bool, source: str, note: str | None, assigned_by: str | None)`; `classify(stops, resolver, manual=None) -> list[ClassifiedStop]`; `planned_intervals(classified) -> list[Interval]`; `unplanned_intervals(classified) -> list[Interval]`.

Classification is an input to the arithmetic, not a report on it (spec §8): `is_planned` decides whether an interval leaves Loading Time or reduces Run Time, so this task has to be finished before `oee_calc` can be written.

- [ ] **Step 1: Write the failing test**

`12_uns_oee/test/test_classifier.py`:

```python
"""Tests for resolving a machine state into a downtime reason code.

Three behaviours matter here and each has a failure mode that is invisible in the numbers.
A unit-specific rule must beat the plant-wide one, or a line with its own vocabulary silently
reports someone else's reasons. An unmapped state must land in UNCLASSIFIED and never in
null, or the Pareto stops summing to total downtime. And a manual assignment must survive
recomputation - Rule 3 - or the operator who corrected a reason watches the engine undo it
the next time late data arrives.
"""

from datetime import datetime, timezone

import pytest

from uns_oee.classifier import (
    ManualReason,
    ReasonResolver,
    ReasonSpec,
    classify,
    planned_intervals,
    unplanned_intervals,
)
from uns_oee.states import Interval, StopInterval


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


REASONS = {
    "UNCLASSIFIED": ReasonSpec("UNCLASSIFIED", "Unclassified", "UNKNOWN", is_planned=False),
    "CHANGEOVER": ReasonSpec("CHANGEOVER", "Changeover", "PLANNED", is_planned=True),
    "PLANNED_BREAK": ReasonSpec("PLANNED_BREAK", "Planned break", "PLANNED", is_planned=True),
    "BREAKDOWN": ReasonSpec("BREAKDOWN", "Breakdown", "UNPLANNED", is_planned=False),
    "MINOR_STOP": ReasonSpec("MINOR_STOP", "Minor stop", "UNPLANNED", is_planned=False),
}


def resolver(unit_rules: dict[str, str] | None = None) -> ReasonResolver:
    return ReasonResolver(
        reasons=REASONS,
        unit_rules=unit_rules or {},
        default_rules={"HELD": "MINOR_STOP", "ABORTED": "BREAKDOWN", "SUSPENDED": "CHANGEOVER"},
    )


def stop(from_hour: int, to_hour: int, state: str) -> StopInterval:
    return StopInterval(state=state, interval=Interval(t(from_hour), t(to_hour)))


def test_a_plant_wide_rule_resolves_a_state():
    assert resolver().resolve("HELD").code == "MINOR_STOP"


def test_a_unit_rule_beats_the_plant_wide_rule():
    assert resolver({"HELD": "PLANNED_BREAK"}).resolve("HELD").code == "PLANNED_BREAK"


def test_an_unmapped_state_is_unclassified_and_never_null():
    resolved = resolver().resolve("STOPPING")
    assert resolved.code == "UNCLASSIFIED"
    assert resolved.is_planned is False


def test_a_rule_naming_a_reason_the_resolver_does_not_know_is_a_loud_error():
    # The FK makes this impossible from the database. It is reachable from a hand-edited
    # conf file, and mislabelling every stop on a line is worse than failing one shift.
    broken = ReasonResolver(reasons=REASONS, unit_rules={}, default_rules={"HELD": "NOPE"})
    with pytest.raises(ValueError, match="NOPE"):
        broken.resolve("HELD")


def test_a_resolver_without_the_unclassified_reason_is_rejected_on_construction():
    with pytest.raises(ValueError, match="UNCLASSIFIED"):
        ReasonResolver(reasons={"BREAKDOWN": REASONS["BREAKDOWN"]}, unit_rules={}, default_rules={})


def test_every_stop_is_classified_as_auto_by_default():
    classified = classify([stop(9, 10, "HELD"), stop(11, 12, "ABORTED")], resolver())
    assert [(item.reason_code, item.source) for item in classified] == [
        ("MINOR_STOP", "auto"),
        ("BREAKDOWN", "auto"),
    ]


def test_a_manual_reason_wins_and_is_marked_manual():
    manual = {t(9): ManualReason(reason_code="PLANNED_BREAK", note="canteen", assigned_by="operator1")}
    classified = classify([stop(9, 10, "HELD")], resolver(), manual)
    assert classified[0].reason_code == "PLANNED_BREAK"
    assert classified[0].source == "manual"
    assert classified[0].is_planned is True
    assert classified[0].note == "canteen"
    assert classified[0].assigned_by == "operator1"


def test_a_manual_reason_for_a_different_stop_does_not_leak():
    manual = {t(20): ManualReason(reason_code="PLANNED_BREAK")}
    classified = classify([stop(9, 10, "HELD")], resolver(), manual)
    assert classified[0].source == "auto"
    assert classified[0].reason_code == "MINOR_STOP"


def test_a_manual_reason_naming_an_unknown_code_is_a_loud_error():
    manual = {t(9): ManualReason(reason_code="GONE")}
    with pytest.raises(ValueError, match="GONE"):
        classify([stop(9, 10, "HELD")], resolver(), manual)


def test_planned_and_unplanned_intervals_partition_the_stops():
    classified = classify(
        [stop(9, 10, "HELD"), stop(11, 12, "SUSPENDED"), stop(13, 14, "ABORTED")], resolver()
    )
    assert planned_intervals(classified) == [Interval(t(11), t(12))]
    assert unplanned_intervals(classified) == [Interval(t(9), t(10)), Interval(t(13), t(14))]


def test_no_stops_classifies_to_nothing():
    assert classify([], resolver()) == []
    assert planned_intervals([]) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_classifier.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.classifier'`.

- [ ] **Step 3: Write the implementation**

`12_uns_oee/src/uns_oee/classifier.py`:

```python
"""From a machine state to a downtime reason code.

Two lookups and a floor. A rule declared for this unit wins; failing that the plant-wide
rule for the state; failing that `UNCLASSIFIED`. Never null - a downtime Pareto has to sum
to total downtime, and a null bucket holding a third of the lost time is how downtime
analysis loses its credibility.

The reason carries `is_planned`, which is why this runs before the calculator: a planned
reason moves its interval out of Loading Time entirely, while an unplanned one reduces Run
Time inside it. Same seconds, different factor.

Pure: no database. The resolver is handed the rows it needs, so every precedence case is one
dictionary literal in a test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from uns_model.oee_tables import UNCLASSIFIED_REASON_CODE

from uns_oee.states import Interval, StopInterval

AUTO = "auto"
MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ReasonSpec:
    """One `model.downtime_reason` row, as the calculator needs it."""

    code: str
    display_name: str
    category: str
    is_planned: bool = False


@dataclass(frozen=True, slots=True)
class ManualReason:
    """An operator's attribution, read back from an existing `oee.downtime_event` row."""

    reason_code: str
    note: str | None = None
    assigned_by: str | None = None


@dataclass(frozen=True, slots=True)
class ClassifiedStop:
    """A stop with its reason resolved, ready to be written and to be arithmetic."""

    interval: Interval
    state_value: str
    reason_code: str
    is_planned: bool
    source: str = AUTO
    note: str | None = None
    assigned_by: str | None = None


class ReasonResolver:
    """The precedence chain for one OEE unit.

    Constructed per unit and per run from `model.state_reason_map` and
    `model.downtime_reason`; holding no connection is what lets the pipeline classify a
    hundred backfilled shifts without re-querying.
    """

    def __init__(
        self,
        reasons: Mapping[str, ReasonSpec],
        unit_rules: Mapping[str, str],
        default_rules: Mapping[str, str],
    ) -> None:
        if UNCLASSIFIED_REASON_CODE not in reasons:
            raise ValueError(
                f"reason vocabulary is missing {UNCLASSIFIED_REASON_CODE!r}, which is the floor "
                f"every unmapped state falls back to. Migration 0003 seeds it."
            )
        self._reasons = dict(reasons)
        self._unit_rules = dict(unit_rules)
        self._default_rules = dict(default_rules)

    def resolve(self, state_value: str) -> ReasonSpec:
        """The reason for `state_value`: unit rule, then plant-wide rule, then unclassified."""
        code = self._unit_rules.get(state_value) or self._default_rules.get(state_value)
        if code is None:
            return self._reasons[UNCLASSIFIED_REASON_CODE]
        return self.spec(code)

    def spec(self, code: str) -> ReasonSpec:
        """The reason with this code.

        Raises rather than falling back, because a code with no row means the vocabulary was
        loaded incompletely. Labelling every stop on a line as unclassified would hide that.
        """
        try:
            return self._reasons[code]
        except KeyError as error:
            raise ValueError(f"reason code {code!r} is not in the loaded reason vocabulary") from error


def classify(
    stops: Sequence[StopInterval],
    resolver: ReasonResolver,
    manual: Mapping[object, ManualReason] | None = None,
) -> list[ClassifiedStop]:
    """Attach a reason to every stop, honouring Rule 3.

    `manual` is keyed by the stop's start instant, matching `oee.downtime_event`'s
    `(oee_unit_id, started_at)` key. A stop whose start is in that mapping keeps the
    operator's code permanently: auto-classification proposes, it never overrules.
    """
    assigned = manual or {}
    classified: list[ClassifiedStop] = []
    for stop in stops:
        override = assigned.get(stop.interval.start)
        spec = resolver.spec(override.reason_code) if override else resolver.resolve(stop.state)
        classified.append(
            ClassifiedStop(
                interval=stop.interval,
                state_value=stop.state,
                reason_code=spec.code,
                is_planned=spec.is_planned,
                source=MANUAL if override else AUTO,
                note=override.note if override else None,
                assigned_by=override.assigned_by if override else None,
            )
        )
    return classified


def planned_intervals(classified: Sequence[ClassifiedStop]) -> list[Interval]:
    """The intervals that leave Loading Time."""
    return [item.interval for item in classified if item.is_planned]


def unplanned_intervals(classified: Sequence[ClassifiedStop]) -> list[Interval]:
    """The intervals that reduce Run Time within Loading Time."""
    return [item.interval for item in classified if not item.is_planned]


__all__ = [
    "AUTO",
    "MANUAL",
    "ClassifiedStop",
    "ManualReason",
    "ReasonResolver",
    "ReasonSpec",
    "classify",
    "planned_intervals",
    "unplanned_intervals",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_classifier.py -v -n 0`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/classifier.py 12_uns_oee/test/test_classifier.py
git commit -m "feat(oee): resolve machine states into downtime reason codes"
```

---

### Task 7: The calculator

**Files:**
- Create: `12_uns_oee/src/uns_oee/oee_calc.py`
- Create: `12_uns_oee/test/test_oee_calc.py`

**Interfaces:**
- Consumes: `uns_oee.states.{Interval, intersect, merge, subtract, union_duration_s}` (Task 5); `uns_oee.classifier.{ClassifiedStop, planned_intervals, unplanned_intervals}` (Task 6); `uns_model.oee_tables.OEE_STATUSES` (Task 2).
- Produces: `ProductSegment(product_code: str | None, intervals: tuple[Interval, ...], ideal_cycle_time_s: float | None, good_count: float, reject_count: float)` with `.total_count -> float`; `ShiftInputs(window: Interval, exception_intervals: tuple[Interval, ...], classified_stops: tuple[ClassifiedStop, ...], products: tuple[ProductSegment, ...], has_input_data: bool)`; `ProductMetrics(product_code, run_time_s, good_count, reject_count, total_count, ideal_cycle_time_s)`; `ShiftMetrics` with fields `loading_time_s, run_time_s, planned_down_s, unplanned_down_s, good_count, reject_count, total_count, availability, performance, performance_raw, quality, oee, status, products, missing_ideal_cycle_time, performance_over_unity`; `compute(inputs: ShiftInputs) -> ShiftMetrics`; status constants `STATUS_OK`, `STATUS_NO_LOADING_TIME`, `STATUS_NO_PRODUCTION`, `STATUS_MISSING_IDEAL_CYCLE_TIME`, `STATUS_NO_INPUT_DATA`.

This is spec §8 transcribed into one function, and §8.1 is its test list. Every row of that table is a case where the obvious implementation divides by zero or, worse, returns a plausible number.

The shift's counts are defined as the sum over product segments rather than as an independent whole-window counter delta. When a unit has no `product_metric_key` the pipeline passes one segment spanning the shift, so the two definitions coincide there — and where they would not, summing keeps `Σ products == shift`, so a per-product panel always reconciles with the headline row.

- [ ] **Step 1: Write the failing test**

`12_uns_oee/test/test_oee_calc.py`:

```python
"""Tests for the OEE arithmetic.

Spec section 8.1 is a table of six cases in which the obvious implementation either raises
ZeroDivisionError or - much worse - returns a believable number. Each has a test here. The
believable-number cases are the reason `status` exists: a shift nobody staffed is not a 0%
shift, and recording it as one poisons every average it enters for the rest of the year.
"""

from datetime import datetime, timezone

from uns_model.oee_tables import OEE_STATUSES

from uns_oee.classifier import ClassifiedStop
from uns_oee.oee_calc import (
    STATUS_MISSING_IDEAL_CYCLE_TIME,
    STATUS_NO_INPUT_DATA,
    STATUS_NO_LOADING_TIME,
    STATUS_NO_PRODUCTION,
    STATUS_OK,
    ProductSegment,
    ShiftInputs,
    compute,
)
from uns_oee.states import Interval


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


SHIFT = Interval(t(6), t(14))  # eight hours = 28800 s


def stop(from_h: int, to_h: int, *, planned: bool, state: str = "HELD") -> ClassifiedStop:
    return ClassifiedStop(
        interval=Interval(t(from_h), t(to_h)),
        state_value=state,
        reason_code="CHANGEOVER" if planned else "BREAKDOWN",
        is_planned=planned,
        source="auto",
        note=None,
        assigned_by=None,
    )


def segment(
    *,
    code: str | None = "R-100-STD",
    intervals: tuple[Interval, ...] = (SHIFT,),
    ideal: float | None = 2.0,
    good: float = 0.0,
    reject: float = 0.0,
) -> ProductSegment:
    return ProductSegment(
        product_code=code,
        intervals=intervals,
        ideal_cycle_time_s=ideal,
        good_count=good,
        reject_count=reject,
    )


def test_a_clean_shift_multiplies_out():
    # Loading 28800 s, one hour unplanned stop -> Run Time 25200 s.
    # 12000 units at an ideal 2.0 s/unit = 24000 s of work in 25200 s of run time.
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            classified_stops=(stop(9, 10, planned=False),),
            products=(segment(good=11760, reject=240),),
        )
    )
    assert metrics.loading_time_s == 28800.0
    assert metrics.planned_down_s == 0.0
    assert metrics.unplanned_down_s == 3600.0
    assert metrics.run_time_s == 25200.0
    assert metrics.total_count == 12000.0
    assert metrics.availability == 25200.0 / 28800.0
    assert metrics.performance == (2.0 * 12000.0) / 25200.0
    assert metrics.quality == 11760.0 / 12000.0
    assert metrics.oee == metrics.availability * metrics.performance * metrics.quality
    assert metrics.status == STATUS_OK


def test_a_planned_reason_stop_leaves_loading_time():
    # Availability is not punished for a changeover: the hour comes out of the denominator.
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(9, 10, planned=True),), products=(segment(good=100),))
    )
    assert metrics.planned_down_s == 3600.0
    assert metrics.loading_time_s == 25200.0
    assert metrics.unplanned_down_s == 0.0
    assert metrics.run_time_s == 25200.0
    assert metrics.availability == 1.0


def test_a_calendar_exception_also_leaves_loading_time():
    metrics = compute(
        ShiftInputs(window=SHIFT, exception_intervals=(Interval(t(6), t(8)),), products=(segment(good=100),))
    )
    assert metrics.planned_down_s == 7200.0
    assert metrics.loading_time_s == 21600.0


def test_an_exception_overlapping_a_planned_stop_is_counted_once():
    # Summing would give 7200 + 3600 = 10800 and inflate Availability. The union is 7200.
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            exception_intervals=(Interval(t(6), t(8)),),
            classified_stops=(stop(7, 8, planned=True),),
            products=(segment(good=100),),
        )
    )
    assert metrics.planned_down_s == 7200.0
    assert metrics.loading_time_s == 21600.0


def test_an_unplanned_stop_inside_planned_time_does_not_reduce_run_time_twice():
    # The breakdown happened during a window nobody was scheduled to run. It is already out
    # of Loading Time, so it must not also come out of Run Time.
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            exception_intervals=(Interval(t(6), t(8)),),
            classified_stops=(stop(6, 7, planned=False),),
            products=(segment(good=100),),
        )
    )
    assert metrics.loading_time_s == 21600.0
    assert metrics.unplanned_down_s == 0.0
    assert metrics.run_time_s == 21600.0


def test_an_unplanned_stop_straddling_the_planned_boundary_counts_only_its_loaded_part():
    metrics = compute(
        ShiftInputs(
            window=SHIFT,
            exception_intervals=(Interval(t(6), t(8)),),
            classified_stops=(stop(7, 9, planned=False),),
            products=(segment(good=100),),
        )
    )
    assert metrics.unplanned_down_s == 3600.0
    assert metrics.run_time_s == 18000.0


def test_overlapping_unplanned_stops_are_unioned():
    stops = (stop(9, 11, planned=False), stop(10, 12, planned=False))
    metrics = compute(ShiftInputs(window=SHIFT, classified_stops=stops, products=(segment(good=100),)))
    assert metrics.unplanned_down_s == 3 * 3600.0


def test_a_fully_planned_down_shift_has_no_factors():
    metrics = compute(
        ShiftInputs(window=SHIFT, exception_intervals=(SHIFT,), products=(segment(good=0),))
    )
    assert metrics.loading_time_s == 0.0
    assert metrics.status == STATUS_NO_LOADING_TIME
    assert metrics.availability is None
    assert metrics.performance is None
    assert metrics.quality is None
    assert metrics.oee is None


def test_a_scheduled_shift_that_produced_nothing_keeps_availability():
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(6, 10, planned=False),), products=(segment(),))
    )
    assert metrics.availability == (28800.0 - 14400.0) / 28800.0
    assert metrics.performance is None
    assert metrics.quality is None
    assert metrics.oee is None
    assert metrics.status == STATUS_NO_PRODUCTION


def test_counts_with_no_run_time_null_performance_but_keep_quality():
    # The inputs disagree: the unit was stopped all shift yet the counter moved. Inventing a
    # Performance would hide that; Quality is still a fact about the units that exist.
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(6, 14, planned=False),), products=(segment(good=90, reject=10),))
    )
    assert metrics.run_time_s == 0.0
    assert metrics.availability == 0.0
    assert metrics.performance is None
    assert metrics.quality == 0.9
    assert metrics.oee is None
    assert metrics.status == STATUS_NO_PRODUCTION


def test_a_silent_unit_is_distinguished_from_an_idle_one():
    metrics = compute(ShiftInputs(window=SHIFT, has_input_data=False))
    assert metrics.status == STATUS_NO_INPUT_DATA
    assert metrics.availability is None
    assert metrics.loading_time_s == 0.0
    assert metrics.run_time_s == 0.0
    assert metrics.total_count == 0.0


def test_a_missing_ideal_cycle_time_nulls_performance_and_says_so():
    metrics = compute(ShiftInputs(window=SHIFT, products=(segment(ideal=None, good=100),)))
    assert metrics.performance is None
    assert metrics.performance_raw is None
    assert metrics.quality == 1.0
    assert metrics.oee is None
    assert metrics.status == STATUS_MISSING_IDEAL_CYCLE_TIME
    assert metrics.missing_ideal_cycle_time is True


def test_a_segment_that_produced_nothing_needs_no_ideal_cycle_time():
    products = (
        segment(code="R-100-STD", intervals=(Interval(t(6), t(10)),), ideal=2.0, good=1000),
        segment(code="R-330-LOW", intervals=(Interval(t(10), t(14)),), ideal=None),
    )
    metrics = compute(ShiftInputs(window=SHIFT, products=products))
    assert metrics.status == STATUS_OK
    assert metrics.missing_ideal_cycle_time is False


def test_performance_above_one_is_clamped_and_flagged():
    # 20000 units at 2.0 s each is 40000 s of work claimed inside 28800 s of run time. The
    # authored ideal cycle time is wrong; the true value is kept so it can be seen.
    metrics = compute(ShiftInputs(window=SHIFT, products=(segment(good=20000),)))
    assert metrics.performance_raw == 40000.0 / 28800.0
    assert metrics.performance == 1.0
    assert metrics.performance_over_unity is True
    assert metrics.oee == metrics.availability * 1.0 * metrics.quality
    assert metrics.status == STATUS_OK


def test_performance_is_time_weighted_across_products():
    products = (
        segment(code="R-100-STD", intervals=(Interval(t(6), t(10)),), ideal=2.0, good=6000),
        segment(code="R-220-STD", intervals=(Interval(t(10), t(14)),), ideal=4.0, good=3000),
    )
    metrics = compute(ShiftInputs(window=SHIFT, products=products))
    assert metrics.total_count == 9000.0
    assert metrics.performance == (2.0 * 6000.0 + 4.0 * 3000.0) / 28800.0
    assert [item.run_time_s for item in metrics.products] == [14400.0, 14400.0]


def test_a_products_run_time_excludes_downtime_inside_its_own_segment():
    products = (
        segment(code="R-100-STD", intervals=(Interval(t(6), t(10)),), ideal=2.0, good=6000),
        segment(code="R-220-STD", intervals=(Interval(t(10), t(14)),), ideal=4.0, good=3000),
    )
    metrics = compute(
        ShiftInputs(window=SHIFT, classified_stops=(stop(8, 9, planned=False),), products=products)
    )
    assert [item.run_time_s for item in metrics.products] == [10800.0, 14400.0]
    assert sum(item.run_time_s for item in metrics.products) == metrics.run_time_s


def test_quality_uses_good_over_total_and_reject_is_reported():
    metrics = compute(ShiftInputs(window=SHIFT, products=(segment(good=900, reject=100),)))
    assert metrics.good_count == 900.0
    assert metrics.reject_count == 100.0
    assert metrics.total_count == 1000.0
    assert metrics.quality == 0.9


def test_every_status_the_calculator_returns_is_a_declared_status():
    assert {
        STATUS_OK,
        STATUS_NO_LOADING_TIME,
        STATUS_NO_PRODUCTION,
        STATUS_MISSING_IDEAL_CYCLE_TIME,
        STATUS_NO_INPUT_DATA,
    } <= set(OEE_STATUSES)


def test_no_products_at_all_is_no_production_not_a_crash():
    metrics = compute(ShiftInputs(window=SHIFT))
    assert metrics.status == STATUS_NO_PRODUCTION
    assert metrics.availability == 1.0
    assert metrics.products == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_oee_calc.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.oee_calc'`.

- [ ] **Step 3: Write the implementation**

`12_uns_oee/src/uns_oee/oee_calc.py`:

```python
"""The OEE arithmetic, and nothing else.

Spec section 8:

    Planned Down   = | (planned exception windows u planned-reason stops) n shift |
    Loading Time   = (shift_end - shift_start) - Planned Down
    Unplanned Down = | (unplanned-reason stops) n Loading Time |
    Run Time       = Loading Time - Unplanned Down

    Availability = Run Time / Loading Time
    Performance  = sum_p (ideal_cycle_time_s(p) x total_count(p)) / Run Time
    Quality      = Good Count / Total Count
    OEE          = Availability x Performance x Quality

Planned time has two sources: a calendar exception, and a stop whose reason is planned. Both
leave Loading Time, and they are unioned - an exception window overlapping a changeover is
one period of planned time, and summing it twice inflates Availability. In the flattering
direction, which is the kind of error nobody reports.

Unplanned stops are intersected with Loading Time before they reduce Run Time, so a breakdown
during a planned shutdown is not subtracted twice.

No factor is ever invented. Where a denominator is zero the factor is `None` and `status`
says which case it was, because a shift that nobody staffed is not a 0% shift.

Pure, and no clock: `compute` reads only what it is given.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from uns_oee.classifier import ClassifiedStop, planned_intervals, unplanned_intervals
from uns_oee.states import Interval, intersect, subtract, union_duration_s

STATUS_OK = "OK"
STATUS_NO_LOADING_TIME = "NO_LOADING_TIME"
STATUS_NO_PRODUCTION = "NO_PRODUCTION"
STATUS_MISSING_IDEAL_CYCLE_TIME = "MISSING_IDEAL_CYCLE_TIME"
STATUS_NO_INPUT_DATA = "NO_INPUT_DATA"

#: Performance above this means the authored ideal cycle time is wrong. Clamped, never hidden.
_PERFORMANCE_CEILING = 1.0


@dataclass(frozen=True, slots=True)
class ProductSegment:
    """What one product ran during, and what it produced.

    Counts are counter deltas taken over `intervals`, not pro-rated from a shift total: a
    counter is cumulative, so its delta across a segment already is that segment's output and
    needs no assumption about rate. `product_code` is `None` when the unit declares no product
    binding, in which case the pipeline passes a single segment spanning the whole shift.
    """

    product_code: str | None = None
    intervals: tuple[Interval, ...] = ()
    ideal_cycle_time_s: float | None = None
    good_count: float = 0.0
    reject_count: float = 0.0

    @property
    def total_count(self) -> float:
        return self.good_count + self.reject_count


@dataclass(frozen=True, slots=True)
class ShiftInputs:
    """Everything one shift's numbers are computed from.

    `has_input_data` is separate from `products` being empty: a unit that published nothing
    all shift is a different fact from a unit that was scheduled, ran, and made nothing.
    """

    window: Interval
    exception_intervals: tuple[Interval, ...] = ()
    classified_stops: tuple[ClassifiedStop, ...] = ()
    products: tuple[ProductSegment, ...] = ()
    has_input_data: bool = True


@dataclass(frozen=True, slots=True)
class ProductMetrics:
    """One product's share of the shift, as stored in `oee.shift_result_product`."""

    product_code: str | None
    run_time_s: float
    good_count: float
    reject_count: float
    total_count: float
    ideal_cycle_time_s: float | None


@dataclass(frozen=True, slots=True)
class ShiftMetrics:
    """One shift's result. A `None` factor is a fact, not a missing value - see `status`."""

    loading_time_s: float = 0.0
    run_time_s: float = 0.0
    planned_down_s: float = 0.0
    unplanned_down_s: float = 0.0
    good_count: float = 0.0
    reject_count: float = 0.0
    total_count: float = 0.0
    availability: float | None = None
    performance: float | None = None
    performance_raw: float | None = None
    quality: float | None = None
    oee: float | None = None
    status: str = STATUS_NO_INPUT_DATA
    products: tuple[ProductMetrics, ...] = field(default_factory=tuple)
    missing_ideal_cycle_time: bool = False
    performance_over_unity: bool = False


def compute(inputs: ShiftInputs) -> ShiftMetrics:
    """The four factors for one shift, or the reason there are none."""
    if not inputs.has_input_data:
        return ShiftMetrics(status=STATUS_NO_INPUT_DATA)

    planned = list(inputs.exception_intervals) + planned_intervals(inputs.classified_stops)
    planned_in_shift = intersect(planned, [inputs.window])
    planned_down_s = union_duration_s(planned_in_shift)
    loading = subtract([inputs.window], planned_in_shift)
    loading_time_s = union_duration_s(loading)

    unplanned_in_loading = intersect(unplanned_intervals(inputs.classified_stops), loading)
    unplanned_down_s = union_duration_s(unplanned_in_loading)
    run = subtract(loading, unplanned_in_loading)
    run_time_s = union_duration_s(run)

    products = _product_metrics(inputs.products, run)
    good_count = sum(item.good_count for item in products)
    reject_count = sum(item.reject_count for item in products)
    total_count = good_count + reject_count

    if loading_time_s <= 0.0:
        return ShiftMetrics(
            planned_down_s=planned_down_s,
            good_count=good_count,
            reject_count=reject_count,
            total_count=total_count,
            status=STATUS_NO_LOADING_TIME,
            products=products,
        )

    availability = run_time_s / loading_time_s
    quality = good_count / total_count if total_count > 0.0 else None
    performance_raw, missing_ideal = _performance_raw(products, run_time_s, total_count)
    performance = None if performance_raw is None else min(performance_raw, _PERFORMANCE_CEILING)
    oee = None if performance is None or quality is None else availability * performance * quality

    return ShiftMetrics(
        loading_time_s=loading_time_s,
        run_time_s=run_time_s,
        planned_down_s=planned_down_s,
        unplanned_down_s=unplanned_down_s,
        good_count=good_count,
        reject_count=reject_count,
        total_count=total_count,
        availability=availability,
        performance=performance,
        performance_raw=performance_raw,
        quality=quality,
        oee=oee,
        status=_status(performance, quality, missing_ideal),
        products=products,
        missing_ideal_cycle_time=missing_ideal,
        performance_over_unity=performance_raw is not None and performance_raw > _PERFORMANCE_CEILING,
    )


def _product_metrics(
    segments: Sequence[ProductSegment], run: Sequence[Interval]
) -> tuple[ProductMetrics, ...]:
    """Each segment's counts, with its run time clipped to the shift's actual Run Time.

    Clipping means the per-product run times sum to the shift's Run Time rather than to the
    segments' wall-clock length, so a per-product panel reconciles with the headline row.
    """
    return tuple(
        ProductMetrics(
            product_code=segment.product_code,
            run_time_s=union_duration_s(intersect(segment.intervals, run)),
            good_count=segment.good_count,
            reject_count=segment.reject_count,
            total_count=segment.total_count,
            ideal_cycle_time_s=segment.ideal_cycle_time_s,
        )
        for segment in segments
    )


def _performance_raw(
    products: Sequence[ProductMetrics], run_time_s: float, total_count: float
) -> tuple[float | None, bool]:
    """The unclamped Performance, and whether an ideal cycle time was missing.

    All-or-nothing on the master data: if any product that actually produced has no authored
    ideal cycle time, Performance is null rather than computed from the products that do. A
    partial numerator over the full Run Time understates Performance by an amount that looks
    like a real loss.
    """
    if run_time_s <= 0.0 or total_count <= 0.0:
        return None, False
    producing = [item for item in products if item.total_count > 0.0]
    if any(item.ideal_cycle_time_s is None for item in producing):
        return None, True
    ideal_seconds = sum(
        (item.ideal_cycle_time_s or 0.0) * item.total_count for item in producing
    )
    return ideal_seconds / run_time_s, False


def _status(performance: float | None, quality: float | None, missing_ideal: bool) -> str:
    """Which of the section 8.1 cases this shift landed in.

    Order matters: a shift with no ideal cycle time and no production is reported as
    NO_PRODUCTION, because fixing the master data would not give it a Performance.
    """
    if quality is None or (performance is None and not missing_ideal):
        return STATUS_NO_PRODUCTION
    if missing_ideal:
        return STATUS_MISSING_IDEAL_CYCLE_TIME
    return STATUS_OK


__all__ = [
    "STATUS_MISSING_IDEAL_CYCLE_TIME",
    "STATUS_NO_INPUT_DATA",
    "STATUS_NO_LOADING_TIME",
    "STATUS_NO_PRODUCTION",
    "STATUS_OK",
    "ProductMetrics",
    "ProductSegment",
    "ShiftInputs",
    "ShiftMetrics",
    "compute",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_oee_calc.py -v -n 0`
Expected: PASS (19 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/oee_calc.py 12_uns_oee/test/test_oee_calc.py
git commit -m "feat(oee): compute availability, performance and quality per shift"
```

---

### Task 8: Reading samples out of `uns_metrics`

**Files:**
- Create: `12_uns_oee/src/uns_oee/sources.py`
- Create: `12_uns_oee/test/test_sources.py`

**Interfaces:**
- Consumes: `uns_model.engine.Database` (existing); `uns_oee.counters.Sample` (Task 5); `uns_oee.states.StateSample` (Task 5).
- Produces: `MetricRef(topic: str, metric_name: str)`; `split_metric_key(asset_path: str, metric_key: str) -> MetricRef`; `Fingerprint(row_count: int, max_time: datetime | None, manual_digest: str = "-")` with `.as_text() -> str`, `.is_empty -> bool` and `.with_manual(digest: str) -> Fingerprint`; `MetricSource(database, metrics_table="uns_metrics", prior_lookback_hours=24)` with `async numeric_samples(ref, start, end, *, include_prior=True) -> list[Sample]`, `async text_samples(ref, start, end, *, include_prior=True) -> list[StateSample]`, `async fingerprint(refs, start, end) -> Fingerprint`, `async earliest_sample_at(refs) -> datetime | None`; module functions `window_sql`, `prior_sql`, `fingerprint_sql`, `earliest_sql`, `pair_params`.

The access path is already there: `idx_uns_metrics_topic_metric_time ON uns_metrics (topic, metric_name, time DESC)` (`04_uns_historian/sql_scripts/04_setup_metrics_hypertable.sql:19`–`:20`). Every query in this module is written to use it, and none of them touch `unifiednamespace` or the JSONB payloads.

Two design points that the tests pin:

**`include_prior` has a bounded lookback.** The state at a shift start is the last sample at or before the boundary, so a second query reaching backwards is unavoidable. Without a lower bound, a unit that stopped publishing a year ago makes Timescale walk every chunk in the hypertable backwards. `prior_lookback_hours` (default 24) caps it; a unit silent for longer than that has no state to carry in, which the calculator reports as `NO_INPUT_DATA` rather than guessing.

**A binding maps to `(topic, metric_name)` by splitting at the last `/`.** `asset.path` is `CovestroAG/Dormagen/Production/Line1` and the binding is `Cell1/MES-01/Status/PackMlState/value`; the simulator publishes to `.../Cell1/MES-01/Status/PackMlState` with a payload of `{"value": ..., "unit": ..., "status": ..., "quality": ...}`, and `flatten_payload_to_metrics` (`04_uns_historian/src/uns_historian/metric_flattener.py:10`) turns each leaf into a row with `metric_name = "value"`. So the last segment of the binding is the metric name and everything before it is the topic. That also means a nested payload is addressable — `.../Status/Detail/value.inner` — without a second convention.

- [ ] **Step 1: Write the failing test**

`12_uns_oee/test/test_sources.py`:

```python
"""Tests for the historian read path.

The SQL is exercised for real in the end-to-end integration test. What is worth pinning
without a database is everything around it: that a metric binding resolves to the right
(topic, metric_name) pair, that the prior-sample query is bounded so it cannot walk a whole
hypertable backwards, that a text metric and a numeric metric read different columns, and
that the fingerprint is a stable string - a fingerprint that formats differently between two
runs would make every shift look like it had late data.
"""

from datetime import datetime, timedelta, timezone

import pytest

from uns_oee.sources import (
    Fingerprint,
    MetricRef,
    MetricSource,
    earliest_sql,
    fingerprint_sql,
    pair_params,
    prior_sql,
    split_metric_key,
    window_sql,
)

ASSET = "CovestroAG/Dormagen/Production/Line1"
STATE_KEY = "Cell1/MES-01/Status/PackMlState/value"
T0 = datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, results):
        self._results = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        return self._results.pop(0) if self._results else FakeResult([])


class FakeDatabase:
    """Stands in for `uns_model.engine.Database`; only `begin()` is used by MetricSource."""

    def __init__(self, *results):
        self.connection = FakeConnection(results)

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


def test_a_binding_splits_into_topic_and_metric_name():
    assert split_metric_key(ASSET, STATE_KEY) == MetricRef(
        topic=f"{ASSET}/Cell1/MES-01/Status/PackMlState", metric_name="value"
    )


def test_a_nested_payload_leaf_is_addressable():
    assert split_metric_key(ASSET, "Cell1/MES-01/Status/Detail/value.inner").metric_name == "value.inner"


def test_surrounding_slashes_do_not_produce_an_empty_segment():
    assert split_metric_key(f"{ASSET}/", f"/{STATE_KEY}") == split_metric_key(ASSET, STATE_KEY)


def test_a_binding_with_no_slash_is_rejected():
    with pytest.raises(ValueError, match="value"):
        split_metric_key(ASSET, "value")


def test_a_fingerprint_formats_the_same_way_twice():
    fingerprint = Fingerprint(row_count=1440, max_time=T0)
    assert fingerprint.as_text() == "1440:2026-09-07T06:00:00+00:00:-"
    assert fingerprint.as_text() == Fingerprint(row_count=1440, max_time=T0).as_text()
    assert fingerprint.is_empty is False


def test_an_empty_fingerprint_is_recognisable_and_still_formats():
    empty = Fingerprint()
    assert empty.is_empty is True
    assert empty.as_text() == "0:-:-"


def test_an_operator_reassignment_moves_the_fingerprint_without_moving_a_sample():
    fingerprint = Fingerprint(row_count=1440, max_time=T0)
    reassigned = fingerprint.with_manual("9f2c1a")
    assert reassigned.as_text() != fingerprint.as_text()
    # Same historian rows: the recompute is driven by the operator, not by late data.
    assert (reassigned.row_count, reassigned.max_time) == (1440, T0)
    assert reassigned.is_empty is False


def test_the_historian_half_of_a_stored_fingerprint_is_recoverable():
    fingerprint = Fingerprint(row_count=1440, max_time=T0)
    # A reassignment leaves the historian half identical; late data changes it.
    assert Fingerprint.source_part(fingerprint.with_manual("9f2c1a").as_text()) == (
        Fingerprint.source_part(fingerprint.as_text())
    )
    later = Fingerprint(row_count=1441, max_time=T0)
    assert Fingerprint.source_part(later.as_text()) != Fingerprint.source_part(fingerprint.as_text())
    assert Fingerprint.source_part(Fingerprint().as_text()) == "0:-"


def test_a_table_name_that_is_not_an_identifier_is_refused():
    with pytest.raises(ValueError, match="metrics table"):
        MetricSource(FakeDatabase(), metrics_table="uns_metrics; DROP TABLE model.asset")


def test_the_window_query_reads_the_column_the_caller_asked_for():
    numeric = window_sql("uns_metrics", "value_double")
    text = window_sql("uns_metrics", "value_text")
    assert "value_double IS NOT NULL" in numeric
    assert "value_text IS NOT NULL" in text
    for statement in (numeric, text):
        assert "topic = :topic" in statement
        assert "metric_name = :metric_name" in statement
        assert "ORDER BY time" in statement


def test_the_prior_query_is_bounded_at_both_ends_and_takes_one_row():
    statement = prior_sql("uns_metrics", "value_double")
    assert "time < :start" in statement
    assert "time >= :lookback_from" in statement
    assert "ORDER BY time DESC" in statement
    assert "LIMIT 1" in statement


def test_the_pair_predicate_binds_one_placeholder_per_pair():
    refs = [MetricRef("a", "value"), MetricRef("b", "value")]
    statement = fingerprint_sql("uns_metrics", len(refs))
    assert "(topic, metric_name) IN ((:topic_0, :metric_0), (:topic_1, :metric_1))" in statement
    assert "count(*)" in statement
    assert "max(time)" in statement
    assert pair_params(refs) == {
        "topic_0": "a",
        "metric_0": "value",
        "topic_1": "b",
        "metric_1": "value",
    }


def test_a_fingerprint_over_no_bindings_is_empty_without_a_query():
    statement = fingerprint_sql("uns_metrics", 0)
    assert statement == ""


def test_the_earliest_query_is_a_min_over_the_same_pairs():
    statement = earliest_sql("uns_metrics", 1)
    assert "min(time)" in statement
    assert "(:topic_0, :metric_0)" in statement


@pytest.mark.asyncio
async def test_numeric_samples_prepend_the_prior_reading():
    database = FakeDatabase(
        FakeResult([(T0 - timedelta(minutes=2), 140.0)]),
        FakeResult([(T0 + timedelta(minutes=5), 150.0), (T0 + timedelta(minutes=10), 160.0)]),
    )
    source = MetricSource(database)
    samples = await source.numeric_samples(
        MetricRef("topic", "value"), T0, T0 + timedelta(hours=8)
    )
    assert [sample.value for sample in samples] == [140.0, 150.0, 160.0]
    assert samples == sorted(samples)


@pytest.mark.asyncio
async def test_include_prior_false_issues_one_query_only():
    database = FakeDatabase(FakeResult([(T0, 150.0)]))
    source = MetricSource(database)
    await source.numeric_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=8), include_prior=False)
    assert len(database.connection.calls) == 1


@pytest.mark.asyncio
async def test_the_prior_query_passes_the_bounded_lookback():
    database = FakeDatabase(FakeResult([]), FakeResult([]))
    source = MetricSource(database, prior_lookback_hours=6)
    await source.numeric_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=8))
    _statement, parameters = database.connection.calls[0]
    assert parameters["lookback_from"] == T0 - timedelta(hours=6)


@pytest.mark.asyncio
async def test_text_samples_become_state_samples():
    database = FakeDatabase(
        FakeResult([(T0 - timedelta(minutes=1), "HELD")]),
        FakeResult([(T0 + timedelta(hours=1), "EXECUTE")]),
    )
    source = MetricSource(database)
    samples = await source.text_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=8))
    assert [sample.state for sample in samples] == ["HELD", "EXECUTE"]


@pytest.mark.asyncio
async def test_a_null_value_row_is_skipped_rather_than_becoming_a_zero():
    # The CHECK constraint makes one of the two value columns null on every row, so a caller
    # that queried the wrong column would otherwise read a column of zeros.
    database = FakeDatabase(FakeResult([]), FakeResult([(T0, None), (T0 + timedelta(minutes=1), 12.0)]))
    source = MetricSource(database)
    samples = await source.numeric_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=1))
    assert [sample.value for sample in samples] == [12.0]


@pytest.mark.asyncio
async def test_a_fingerprint_with_no_bindings_never_touches_the_database():
    database = FakeDatabase()
    source = MetricSource(database)
    assert await source.fingerprint([], T0, T0 + timedelta(hours=8)) == Fingerprint()
    assert database.connection.calls == []


@pytest.mark.asyncio
async def test_a_fingerprint_reads_the_count_and_the_latest_time():
    database = FakeDatabase(FakeResult([(1440, T0)]))
    source = MetricSource(database)
    fingerprint = await source.fingerprint([MetricRef("topic", "value")], T0, T0 + timedelta(hours=8))
    assert fingerprint == Fingerprint(row_count=1440, max_time=T0)


@pytest.mark.asyncio
async def test_earliest_sample_at_is_none_when_the_unit_has_never_published():
    database = FakeDatabase(FakeResult([(None,)]))
    source = MetricSource(database)
    assert await source.earliest_sample_at([MetricRef("topic", "value")]) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_sources.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.sources'`.

- [ ] **Step 3: Write the implementation**

`12_uns_oee/src/uns_oee/sources.py`:

```python
"""Reading machine samples out of the historian's narrow metrics table.

Every statement here is written to hit `idx_uns_metrics_topic_metric_time (topic,
metric_name, time DESC)`, which already exists. Nothing in this module reads the JSONB
`unifiednamespace` table or the continuous aggregates: the aggregates average, and an OEE
counter delta cannot be taken from an average.

A metric binding is `<segments below the Asset>/<payload leaf>` - the same meaning
`TopicBinding.metric_path` already carries. Splitting at the last slash gives the MQTT topic
and the flattened leaf name, which is `value` for every signal the simulator publishes.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import text
from uns_model.engine import Database

from uns_oee.counters import Sample
from uns_oee.states import StateSample

LOGGER = logging.getLogger(__name__)

#: The metrics table comes from configuration, not from a request, but it is interpolated
#: into SQL - so it is checked against this rather than trusted.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: How far before a shift start the "last known value" query is allowed to reach. Bounded so
#: a unit that stopped publishing months ago cannot make Timescale walk every chunk backwards.
DEFAULT_PRIOR_LOOKBACK_HOURS = 24


@dataclass(frozen=True, slots=True)
class MetricRef:
    """One addressable series: an MQTT topic and a flattened payload leaf name."""

    topic: str
    metric_name: str


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """What the input window looked like, cheaply enough to re-read often.

    Row count and latest sample time. Late-arriving data changes one or both, which is the
    signal to recompute the shift and supersede the stored revision.

    `manual_digest` is the third input and does not come from the historian: an operator
    reassigning a downtime reason changes the arithmetic without changing a single sample.
    Left at "-" here and filled in by the pipeline, which is where the reasons are read.
    """

    row_count: int = 0
    max_time: datetime | None = None
    manual_digest: str = "-"

    @property
    def is_empty(self) -> bool:
        """Whether the historian had anything to say. Manual reasons do not make a shift
        non-empty: a reason attached to a stop that no longer has samples behind it is not
        input data."""
        return self.row_count == 0

    def as_text(self) -> str:
        """The stored form. Stable across runs - two formats would look like late data."""
        return (
            f"{self.row_count}:"
            f"{self.max_time.isoformat() if self.max_time else '-'}:"
            f"{self.manual_digest}"
        )

    def with_manual(self, digest: str) -> Fingerprint:
        """This fingerprint plus the operator's contribution to the inputs."""
        return replace(self, manual_digest=digest)

    @staticmethod
    def source_part(stored: str) -> str:
        """The historian half of a stored fingerprint, without the operator's digest.

        The parser lives beside the formatter so the two cannot drift. It exists because
        "the data changed" and "someone reassigned a reason" are different events, and
        `uns_oee_late_data_detected_total` must only count the first.
        """
        return stored.rpartition(":")[0]


def split_metric_key(asset_path: str, metric_key: str) -> MetricRef:
    """Resolve an Asset path plus a binding into a topic and a metric name."""
    combined = f"{asset_path.strip('/')}/{metric_key.strip('/')}"
    topic, _, metric_name = combined.rpartition("/")
    if not topic or not metric_name:
        raise ValueError(
            f"metric binding {metric_key!r} must be at least one topic segment followed by a "
            f"payload leaf, e.g. 'Cell1/MES-01/Status/PackMlState/value'"
        )
    return MetricRef(topic=topic, metric_name=metric_name)


def window_sql(table: str, value_column: str) -> str:
    """Every sample of one series inside a closed window, oldest first."""
    return (
        f"SELECT time, {value_column} FROM {table} "
        f"WHERE topic = :topic AND metric_name = :metric_name "
        f"AND time >= :start AND time <= :end AND {value_column} IS NOT NULL "
        f"ORDER BY time"
    )


def prior_sql(table: str, value_column: str) -> str:
    """The last sample of one series before a window, within a bounded lookback."""
    return (
        f"SELECT time, {value_column} FROM {table} "
        f"WHERE topic = :topic AND metric_name = :metric_name "
        f"AND time < :start AND time >= :lookback_from AND {value_column} IS NOT NULL "
        f"ORDER BY time DESC LIMIT 1"
    )


def fingerprint_sql(table: str, pair_count: int) -> str:
    """Row count and latest sample time across several series. Empty string for no series."""
    if pair_count <= 0:
        return ""
    return (
        f"SELECT count(*), max(time) FROM {table} "
        f"WHERE {_pair_predicate(pair_count)} AND time >= :start AND time <= :end"
    )


def earliest_sql(table: str, pair_count: int) -> str:
    """The first sample time across several series. Used once, to bound the backfill."""
    if pair_count <= 0:
        return ""
    return f"SELECT min(time) FROM {table} WHERE {_pair_predicate(pair_count)}"


def pair_params(refs: Sequence[MetricRef]) -> dict[str, str]:
    """Bound parameters for `_pair_predicate`, in the same order."""
    parameters: dict[str, str] = {}
    for index, ref in enumerate(refs):
        parameters[f"topic_{index}"] = ref.topic
        parameters[f"metric_{index}"] = ref.metric_name
    return parameters


def _pair_predicate(pair_count: int) -> str:
    """`(topic, metric_name) IN ((:topic_0, :metric_0), ...)`.

    A row constructor rather than two `= ANY(...)` clauses, which would match the cross
    product - four topics and two metric names would silently include four pairs nobody asked
    for, and the fingerprint would move for reasons unrelated to the shift.
    """
    pairs = ", ".join(f"(:topic_{index}, :metric_{index})" for index in range(pair_count))
    return f"(topic, metric_name) IN ({pairs})"


class MetricSource:
    """The historian read path for one OEE run.

    Holds no state beyond its connection source, so the pipeline can reuse one instance for a
    thirty-day backfill.
    """

    def __init__(
        self,
        database: Database,
        metrics_table: str = "uns_metrics",
        prior_lookback_hours: int = DEFAULT_PRIOR_LOOKBACK_HOURS,
    ) -> None:
        if not _IDENTIFIER.match(metrics_table):
            raise ValueError(f"metrics table {metrics_table!r} is not a plain SQL identifier")
        self._database = database
        self._table = metrics_table
        self._prior_lookback = timedelta(hours=prior_lookback_hours)

    async def numeric_samples(
        self, ref: MetricRef, start: datetime, end: datetime, *, include_prior: bool = True
    ) -> list[Sample]:
        """Counter readings for one series, with the pre-window baseline unless refused."""
        rows = await self._rows(ref, start, end, "value_double", include_prior)
        return sorted(Sample(at=at, value=float(value)) for at, value in rows if value is not None)

    async def text_samples(
        self, ref: MetricRef, start: datetime, end: datetime, *, include_prior: bool = True
    ) -> list[StateSample]:
        """State or product readings for one series, with the value in force at `start`."""
        rows = await self._rows(ref, start, end, "value_text", include_prior)
        return sorted(StateSample(at=at, state=str(value)) for at, value in rows if value is not None)

    async def fingerprint(
        self, refs: Sequence[MetricRef], start: datetime, end: datetime
    ) -> Fingerprint:
        """One indexed aggregate over every series a unit reads. Cheap enough to re-run often."""
        statement = fingerprint_sql(self._table, len(refs))
        if not statement:
            return Fingerprint()
        parameters = pair_params(refs) | {"start": start, "end": end}
        async with self._database.begin() as connection:
            row = (await connection.execute(text(statement), parameters)).first()
        if row is None:
            return Fingerprint()
        return Fingerprint(row_count=int(row[0] or 0), max_time=row[1])

    async def earliest_sample_at(self, refs: Sequence[MetricRef]) -> datetime | None:
        """The first sample a unit ever published, or `None`. Bounds the startup backfill."""
        statement = earliest_sql(self._table, len(refs))
        if not statement:
            return None
        async with self._database.begin() as connection:
            row = (await connection.execute(text(statement), pair_params(refs))).first()
        return None if row is None else row[0]

    async def _rows(
        self, ref: MetricRef, start: datetime, end: datetime, value_column: str, include_prior: bool
    ) -> list[tuple[datetime, object]]:
        """The window's rows, preceded by the baseline row when one is wanted and exists."""
        base = {"topic": ref.topic, "metric_name": ref.metric_name, "start": start, "end": end}
        rows: list[tuple[datetime, object]] = []
        async with self._database.begin() as connection:
            if include_prior:
                prior = await connection.execute(
                    text(prior_sql(self._table, value_column)),
                    base | {"lookback_from": start - self._prior_lookback},
                )
                rows.extend(prior.fetchall())
            window = await connection.execute(text(window_sql(self._table, value_column)), base)
            rows.extend(window.fetchall())
        return rows


__all__ = [
    "DEFAULT_PRIOR_LOOKBACK_HOURS",
    "Fingerprint",
    "MetricRef",
    "MetricSource",
    "earliest_sql",
    "fingerprint_sql",
    "pair_params",
    "prior_sql",
    "split_metric_key",
    "window_sql",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_sources.py -v -n 0`
Expected: PASS (22 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/sources.py 12_uns_oee/test/test_sources.py
git commit -m "feat(oee): read state and counter samples from uns_metrics"
```

---

### Task 9: Loading master data

**Files:**
- Create: `12_uns_oee/src/uns_oee/master_data.py`
- Create: `12_uns_oee/test/test_master_data.py`

**Interfaces:**
- Consumes: `uns_model.engine.Database`; `uns_model.tables.Asset`; `uns_model.oee_tables.{OeeUnit, ShiftPattern, ShiftPatternSlot, ShiftException, IdealCycleTime, DowntimeReason, StateReasonMap, Product, DEFAULT_PRODUCING_STATES}` (Task 2); `uns_oee.shift_calendar.{ShiftSchedule, ShiftSlot}` (Task 4); `uns_oee.sources.{MetricRef, split_metric_key}` (Task 8); `uns_oee.classifier.{ReasonResolver, ReasonSpec}` (Task 6); `uns_oee.states.{Interval, merge}` (Task 5).
- Produces: `UnitMasterData` (frozen) with fields `unit_id: int, asset_id: int, asset_path: str, schedule: ShiftSchedule, producing_states: tuple[str, ...], state_ref: MetricRef, good_ref: MetricRef, reject_ref: MetricRef | None, product_ref: MetricRef | None, ideal_cycle_times: Mapping[str | None, float], resolver: ReasonResolver`, property `.refs -> tuple[MetricRef, ...]`, method `.ideal_cycle_time_for(product_code: str | None) -> float | None`; `ExceptionWindow(interval: Interval, kind: str, asset_path: str | None)`; `MasterDataLoader(database)` with `async active_units() -> list[UnitMasterData]` and `async exception_windows(unit, window) -> list[ExceptionWindow]`; module functions `applies_to(exception_asset_path: str | None, unit_asset_path: str) -> bool`, `exception_intervals(windows: Sequence[ExceptionWindow]) -> list[Interval]`.

There is no product-id lookup, because `oee.shift_result_product.product_code` stores the value the machine published rather than a foreign key (Task 2). `model.product` is still read — it is what gives an `ideal_cycle_time` row its product code.

`reject_count_metric_key` is nullable in Task 2's schema, so `reject_ref` is optional. A unit with no reject binding reports `reject_count = 0` and therefore `quality = 1.0` — which is what the plant's instrumentation actually says, and is visible in the stored row rather than hidden in an assumption.

Every query joins explicitly instead of declaring ORM relationships. Under asyncio a lazy load raises `MissingGreenlet` at the point of attribute access, a long way from the query that failed to eager-load it; an explicit `select(OeeUnit, Asset.path, ...)` cannot fail that way. Task 2's OEE tables therefore declare no `relationship()`, unlike `tables.py`.

**An assumption the spec left open, stated explicitly:** `model.shift_exception.asset_id` is described as "the Site or Line it applies to", and `conf/oee/exceptions` authors a plant-wide Christmas holiday with no Asset at all. This task resolves an exception against a unit when the exception's Asset is null (every unit), is the unit's own Asset, or is an **ancestor** of it — so a site-wide shutdown authored on `CovestroAG/Dormagen` applies to `CovestroAG/Dormagen/Production/Line1`. A descendant never matches upward: a cell-level exception does not stop the line. All three `kind` values subtract from Loading Time identically (spec §7.1); `kind` is carried for reporting only.

Ancestor matching is done in Python rather than in SQL. A thirty-day window contains a handful of exception rows, and `literal(path).like(asset.path || '/%')` is both harder to read and harder to test than a prefix check.

- [ ] **Step 1: Write the failing test**

`12_uns_oee/test/test_master_data.py`:

```python
"""Tests for the pure half of master-data loading.

The queries themselves are exercised against a real database in the end-to-end integration
test. What is worth pinning here is the resolution logic, because each rule has a quiet
failure mode: an ideal cycle time that falls back to the wrong default reads as a Performance
change nobody made, and an exception that resolves to the wrong Asset silently rewrites
Loading Time for a line that was running.
"""

from dataclasses import replace
from datetime import datetime, time, timezone

from uns_oee.classifier import ReasonResolver, ReasonSpec
from uns_oee.master_data import (
    ExceptionWindow,
    UnitMasterData,
    applies_to,
    exception_intervals,
)
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot
from uns_oee.sources import MetricRef
from uns_oee.states import Interval

LINE = "CovestroAG/Dormagen/Production/Line1"


def t(hour: int) -> datetime:
    return datetime(2026, 9, 7, hour, tzinfo=timezone.utc)


def unit(ideal: dict[str | None, float] | None = None) -> UnitMasterData:
    return UnitMasterData(
        unit_id=1,
        asset_id=42,
        asset_path=LINE,
        schedule=ShiftSchedule(
            name="Dormagen 3-shift",
            timezone="Europe/Berlin",
            slots=(ShiftSlot(0, time(6, 0), 480, "A"),),
        ),
        producing_states=("EXECUTE",),
        state_ref=MetricRef(f"{LINE}/Cell1/MES-01/Status/PackMlState", "value"),
        good_ref=MetricRef(f"{LINE}/Cell1/MES-01/ProcessValue/GoodCount", "value"),
        reject_ref=MetricRef(f"{LINE}/Cell1/MES-01/ProcessValue/RejectCount", "value"),
        product_ref=MetricRef(f"{LINE}/Cell1/MES-01/Status/RecipeId", "value"),
        ideal_cycle_times=ideal if ideal is not None else {None: 3.0, "R-100-STD": 2.0},
        resolver=ReasonResolver(
            reasons={"UNCLASSIFIED": ReasonSpec("UNCLASSIFIED", "Unclassified", "UNKNOWN", False)},
            unit_rules={},
            default_rules={},
        ),
    )


def test_an_exact_product_wins_over_the_asset_default():
    assert unit().ideal_cycle_time_for("R-100-STD") == 2.0


def test_an_unknown_product_falls_back_to_the_asset_default():
    assert unit().ideal_cycle_time_for("R-999-NEW") == 3.0


def test_no_product_uses_the_asset_default():
    assert unit().ideal_cycle_time_for(None) == 3.0


def test_with_no_default_an_unknown_product_has_no_ideal_cycle_time():
    assert unit({"R-100-STD": 2.0}).ideal_cycle_time_for("R-999-NEW") is None


def test_refs_lists_every_series_the_unit_reads():
    assert len(unit().refs) == 4
    assert unit().refs[0] == unit().state_ref


def test_a_unit_with_no_product_binding_reads_three_series():
    assert len(replace(unit(), product_ref=None).refs) == 3


def test_a_unit_with_no_reject_binding_reads_three_series():
    # A machine with no reject counter is a real configuration. It reports quality 1.0, and
    # the missing binding is visible in the unit row rather than assumed away.
    assert len(replace(unit(), reject_ref=None).refs) == 3


def test_a_unit_with_neither_optional_binding_reads_two_series():
    assert len(replace(unit(), reject_ref=None, product_ref=None).refs) == 2


def test_an_exception_with_no_asset_applies_everywhere():
    assert applies_to(None, LINE) is True


def test_an_exception_on_the_unit_itself_applies():
    assert applies_to(LINE, LINE) is True


def test_an_exception_on_an_ancestor_applies():
    assert applies_to("CovestroAG/Dormagen", LINE) is True
    assert applies_to("CovestroAG", LINE) is True


def test_an_exception_on_a_descendant_does_not_apply():
    assert applies_to(f"{LINE}/Cell1", LINE) is False


def test_an_exception_on_a_sibling_does_not_apply():
    assert applies_to("CovestroAG/Dormagen/Production/Line2", LINE) is False


def test_a_prefix_that_is_not_a_path_boundary_does_not_apply():
    # "Line1" must not match "Line10". The separator is part of the comparison.
    assert applies_to("CovestroAG/Dormagen/Production/Line10", LINE) is False
    assert applies_to("CovestroAG/Dormagen/Production/Line1", f"{LINE}0") is False


def test_exception_intervals_are_extracted_in_order():
    windows = [
        ExceptionWindow(interval=Interval(t(10), t(11)), kind="PLANNED_DOWN", asset_path=LINE),
        ExceptionWindow(interval=Interval(t(6), t(7)), kind="HOLIDAY", asset_path=None),
    ]
    assert exception_intervals(windows) == [Interval(t(6), t(7)), Interval(t(10), t(11))]


def test_overlapping_exceptions_are_coalesced_so_they_cannot_be_double_counted():
    windows = [
        ExceptionWindow(interval=Interval(t(6), t(9)), kind="PLANNED_DOWN", asset_path=LINE),
        ExceptionWindow(interval=Interval(t(8), t(11)), kind="HOLIDAY", asset_path=None),
    ]
    assert exception_intervals(windows) == [Interval(t(6), t(11))]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_master_data.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.master_data'`.

- [ ] **Step 3: Write the implementation**

`12_uns_oee/src/uns_oee/master_data.py`:

```python
"""Loading the authored master data one OEE run needs.

Read once per scan and handed to the pure modules as frozen dataclasses, so a thirty-day
backfill re-queries nothing. Everything that resolves - an ideal cycle time falling back to
the Asset default, an exception applying to a descendant Asset - resolves here, in one place,
where it is testable without a database.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from uns_model.engine import Database
from uns_model.oee_tables import (
    DEFAULT_PRODUCING_STATES,
    DowntimeReason,
    IdealCycleTime,
    OeeUnit,
    Product,
    ShiftException,
    ShiftPattern,
    ShiftPatternSlot,
    StateReasonMap,
)
from uns_model.tables import Asset

from uns_oee.classifier import ReasonResolver, ReasonSpec
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot
from uns_oee.sources import MetricRef, split_metric_key
from uns_oee.states import Interval, merge

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UnitMasterData:
    """One `model.oee_unit` row with everything it points at already resolved."""

    unit_id: int
    asset_id: int
    asset_path: str
    schedule: ShiftSchedule
    producing_states: tuple[str, ...]
    state_ref: MetricRef
    good_ref: MetricRef
    reject_ref: MetricRef | None
    product_ref: MetricRef | None
    ideal_cycle_times: Mapping[str | None, float]
    resolver: ReasonResolver

    @property
    def refs(self) -> tuple[MetricRef, ...]:
        """Every series this unit reads. The fingerprint is taken over exactly these.

        Exactly these, so a unit with no reject counter is not fingerprinted over a series
        that will never have rows - which would leave `max(time)` permanently behind and make
        every shift look like it was still waiting for data.
        """
        optional = (self.reject_ref, self.product_ref)
        return (self.state_ref, self.good_ref, *(ref for ref in optional if ref is not None))

    def ideal_cycle_time_for(self, product_code: str | None) -> float | None:
        """This product's authored cycle time, else the Asset default, else nothing.

        A value row winning over a null row is the same precedence `MetricDefinition` and
        `state_reason_map` already use. Returning `None` rather than a guess is what makes the
        calculator report MISSING_IDEAL_CYCLE_TIME instead of averaging over a master data gap.
        """
        if product_code is not None and product_code in self.ideal_cycle_times:
            return self.ideal_cycle_times[product_code]
        return self.ideal_cycle_times.get(None)


@dataclass(frozen=True, slots=True)
class ExceptionWindow:
    """A `model.shift_exception` row that applies to a unit, clipped to the shift."""

    interval: Interval
    kind: str
    asset_path: str | None


def applies_to(exception_asset_path: str | None, unit_asset_path: str) -> bool:
    """Whether an exception authored on one Asset covers a unit.

    Null covers every unit; the unit's own Asset covers it; an ancestor covers it, so a
    site-wide shutdown does not have to be repeated on every line. A descendant does not: one
    cell stopping is not the line stopping, which is the whole point of reporting at the line.
    """
    if exception_asset_path is None:
        return True
    if exception_asset_path == unit_asset_path:
        return True
    return unit_asset_path.startswith(f"{exception_asset_path}/")


def exception_intervals(windows: Sequence[ExceptionWindow]) -> list[Interval]:
    """The windows as a minimal set of non-overlapping intervals.

    Coalesced here rather than at the call site so two overlapping exceptions cannot be
    subtracted from Loading Time twice.
    """
    return merge(window.interval for window in windows)


class MasterDataLoader:
    """Every read of the authored tables the engine performs."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def active_units(self) -> list[UnitMasterData]:
        """Every active OEE unit, fully resolved. One call per scan.

        Five small selects rather than one join with five left outer joins: the authored tables
        hold tens of rows, and the shared lookups - reasons, rules, slots - are the same for
        every unit, so fetching them once each is both fewer rows and easier to read.
        """
        async with self._database.session() as session:
            reasons = {
                row.code: ReasonSpec(
                    code=row.code,
                    display_name=row.display_name,
                    category=row.category,
                    is_planned=row.is_planned,
                )
                for row in (await session.scalars(select(DowntimeReason))).all()
            }
            rules = (await session.scalars(select(StateReasonMap))).all()
            slots = (await session.scalars(select(ShiftPatternSlot))).all()
            cycle_times = (
                await session.execute(
                    select(
                        IdealCycleTime.asset_id,
                        Product.code,
                        IdealCycleTime.seconds_per_unit,
                    ).outerjoin(Product, IdealCycleTime.product_id == Product.id)
                )
            ).all()
            units = (
                await session.execute(
                    select(OeeUnit, Asset.path, ShiftPattern.name, ShiftPattern.timezone)
                    .join(Asset, OeeUnit.asset_id == Asset.id)
                    .join(ShiftPattern, OeeUnit.shift_pattern_id == ShiftPattern.id)
                    .where(OeeUnit.is_active.is_(True))
                    .order_by(Asset.path)
                )
            ).all()

        return [
            self._resolve(
                unit=unit,
                asset_path=asset_path,
                schedule=_schedule(pattern_name, pattern_timezone, unit.shift_pattern_id, slots),
                reasons=reasons,
                rules=rules,
                cycle_times=cycle_times,
            )
            for unit, asset_path, pattern_name, pattern_timezone in units
        ]

    async def exception_windows(
        self, unit: UnitMasterData, window: Interval
    ) -> list[ExceptionWindow]:
        """The exceptions overlapping `window` that apply to `unit`, clipped to it.

        Fetched by time range only; whether an exception's Asset covers the unit is decided in
        Python by `applies_to`, because the rows in one window are few and a prefix check is
        easier to be sure of than the SQL equivalent.
        """
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(ShiftException, Asset.path)
                    .outerjoin(Asset, ShiftException.asset_id == Asset.id)
                    .where(
                        ShiftException.starts_at < window.end,
                        ShiftException.ends_at > window.start,
                    )
                )
            ).all()

        found: list[ExceptionWindow] = []
        for exception, asset_path in rows:
            if not applies_to(asset_path, unit.asset_path):
                continue
            clipped = Interval(exception.starts_at, exception.ends_at).clipped_to(window)
            if clipped is not None:
                found.append(
                    ExceptionWindow(interval=clipped, kind=exception.kind, asset_path=asset_path)
                )
        return found

    def _resolve(
        self,
        unit: OeeUnit,
        asset_path: str,
        schedule: ShiftSchedule,
        reasons: Mapping[str, ReasonSpec],
        rules: Sequence[StateReasonMap],
        cycle_times: Sequence[tuple[int, str | None, float]],
    ) -> UnitMasterData:
        """One ORM unit and the shared lookups, as a frozen record the pure modules accept."""
        producing = tuple(unit.producing_states or ())
        if not producing:
            LOGGER.warning(
                "OEE unit %s declares no producing states; falling back to %s. Every state "
                "would otherwise be a stop and Availability would read zero.",
                asset_path,
                DEFAULT_PRODUCING_STATES,
            )
            producing = tuple(DEFAULT_PRODUCING_STATES)

        return UnitMasterData(
            unit_id=unit.id,
            asset_id=unit.asset_id,
            asset_path=asset_path,
            schedule=schedule,
            producing_states=producing,
            state_ref=split_metric_key(asset_path, unit.state_metric_key),
            good_ref=split_metric_key(asset_path, unit.good_count_metric_key),
            reject_ref=_optional_ref(asset_path, unit.reject_count_metric_key),
            product_ref=_optional_ref(asset_path, unit.product_metric_key),
            ideal_cycle_times={
                product_code: float(seconds)
                for asset_id, product_code, seconds in cycle_times
                if asset_id == unit.asset_id
            },
            resolver=ReasonResolver(
                reasons=reasons,
                unit_rules={
                    rule.state_value: rule.reason_code
                    for rule in rules
                    if rule.oee_unit_id == unit.id
                },
                default_rules={
                    rule.state_value: rule.reason_code
                    for rule in rules
                    if rule.oee_unit_id is None
                },
            ),
        )


def _optional_ref(asset_path: str, metric_key: str | None) -> MetricRef | None:
    """A binding that the unit may legitimately not have. Blank counts as absent."""
    return split_metric_key(asset_path, metric_key) if metric_key else None


def _schedule(
    name: str, timezone_name: str, pattern_id: int, slots: Sequence[ShiftPatternSlot]
) -> ShiftSchedule:
    """The ORM shift pattern as the calendar's calculation shape.

    Sorted, so two runs build the same schedule and the windows come out in the same order -
    `shift_windows` sorts its output anyway, but a stable schedule is easier to compare in a log.
    """
    return ShiftSchedule(
        name=name,
        timezone=timezone_name,
        slots=tuple(
            ShiftSlot(
                day_of_week=slot.day_of_week,
                start_time=slot.start_time,
                duration_minutes=slot.duration_minutes,
                label=slot.label or "",
            )
            for slot in sorted(
                (slot for slot in slots if slot.shift_pattern_id == pattern_id),
                key=lambda slot: (slot.day_of_week, slot.start_time),
            )
        ),
    )


__all__ = [
    "ExceptionWindow",
    "MasterDataLoader",
    "UnitMasterData",
    "applies_to",
    "exception_intervals",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_master_data.py -v -n 0`
Expected: PASS (16 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/master_data.py 12_uns_oee/test/test_master_data.py
git commit -m "feat(oee): load shift patterns, bindings and reason rules per unit"
```

---

### Task 10: Storing a result idempotently

**Files:**
- Create: `12_uns_oee/src/uns_oee/store.py`
- Create: `12_uns_oee/test/test_store.py`

**Interfaces:**
- Consumes: `Database` from `uns_model.engine`; `DowntimeEvent`, `ShiftResult`, `ShiftResultProduct`, `ShiftResultRevision` from `uns_model.oee_tables` (Task 2); `ShiftWindow` (Task 4); `Interval` (Task 5); `AUTO`, `MANUAL`, `ClassifiedStop`, `ManualReason` (Task 6); `ProductMetrics`, `ShiftMetrics` (Task 7); `Fingerprint` (Task 8).
- Produces: module constants `GEOMETRY_COLUMNS: tuple[str, ...]`, `REASON_COLUMNS: tuple[str, ...]`; `StoredResult(result_id: int, revision: int, input_fingerprint: str, published_at: datetime | None)`; pure functions `result_values(unit_id: int, window: ShiftWindow, metrics: ShiftMetrics, fingerprint: Fingerprint, computed_at: datetime) -> dict[str, object]`, `revision_values(stored: ShiftResult) -> dict[str, object]`, `product_values(result_id: int, metrics: ShiftMetrics) -> list[dict[str, object]]`, `event_values(unit_id: int, shift_start: datetime, stops: Sequence[ClassifiedStop]) -> list[dict[str, object]]`, `downtime_upsert(rows: Sequence[Mapping[str, object]]) -> PostgresInsert`; `ResultStore(database)` with `async existing(unit_id, shift_start) -> StoredResult | None`, `async manual_reasons(unit_id, window) -> dict[datetime, ManualReason]`, `async save(unit_id, window, metrics, stops, fingerprint, computed_at) -> StoredResult`, `async mark_published(result_id, published_at) -> None`.

Recomputation is the normal case, not the exception, so this module is where idempotence is enforced. Three separate mechanisms carry it:

**The keys are stable.** A result is keyed `(oee_unit_id, shift_start)` and a stop `(oee_unit_id, started_at)`. Neither key involves anything the engine derives, so recomputing a shift finds its own previous work instead of duplicating it.

**The old numbers are kept.** A revision copies the row that is about to be replaced into `oee.shift_result_revision` and bumps `revision`. A number that changes with no record of what it was is worse than no number: the first question a plant manager asks about a corrected OEE is what it used to be.

**A manual reason is refused twice.** Task 6 already honours a stored manual reason when it classifies. This module refuses the overwrite a second time, in the `ON CONFLICT` clause, so a stop a person has explained keeps that explanation even if `manual_reasons` failed to match it — which it will whenever recomputation moves a stop's `started_at` by a sample. That second refusal is the difference between an operator's work being durable and it being probabilistic.

The pure mappers are separated from the two `async` methods for the same reason as Task 8: the column mapping and the conflict clause are what can be wrong, and they can be tested without a database. Task 17 exercises the round trip against a real Postgres.

- [ ] **Step 1: Write the failing test**

Create `12_uns_oee/test/test_store.py`:

```python
"""Tests for uns_oee.store - the column mappings and the conflict clause.

Compiled against the PostgreSQL dialect rather than executed, because what can be wrong
here is which columns a recomputation touches, and that is visible in the statement. The
round trip - two saves of the same shift leaving one row, a manual reason surviving the
second - is Task 17's integration test, which needs a real database to be worth anything.
"""

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from uns_model.oee_tables import ShiftResult
from uns_oee.classifier import AUTO, MANUAL, ClassifiedStop
from uns_oee.oee_calc import ProductMetrics, ShiftMetrics
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import Fingerprint
from uns_oee.states import Interval
from uns_oee.store import (
    GEOMETRY_COLUMNS,
    REASON_COLUMNS,
    downtime_upsert,
    event_values,
    product_values,
    result_values,
    revision_values,
)

UNIT = 7
FINGERPRINT = Fingerprint(row_count=2880, max_time=datetime(2026, 9, 7, 12, tzinfo=timezone.utc))
COMPUTED_AT = datetime(2026, 9, 7, 12, 5, tzinfo=timezone.utc)


def t(hour: int) -> datetime:
    return datetime(2026, 9, 7, hour, tzinfo=timezone.utc)


WINDOW = ShiftWindow(start=t(4), end=t(12), label="A")


def metrics() -> ShiftMetrics:
    return ShiftMetrics(
        loading_time_s=27000.0,
        run_time_s=24300.0,
        planned_down_s=1800.0,
        unplanned_down_s=2700.0,
        good_count=11760.0,
        reject_count=240.0,
        total_count=12000.0,
        availability=0.9,
        performance=0.95,
        performance_raw=0.95,
        quality=0.98,
        oee=0.8379,
        status="OK",
        products=(
            ProductMetrics(
                product_code="R-100-STD",
                run_time_s=24300.0,
                good_count=11760.0,
                reject_count=240.0,
                total_count=12000.0,
                ideal_cycle_time_s=2.0,
            ),
        ),
    )


def stop(
    from_hour: int,
    to_hour: int,
    *,
    reason: str = "MECH_FAILURE",
    source: str = AUTO,
    note: str = "",
    assigned_by: str | None = None,
) -> ClassifiedStop:
    return ClassifiedStop(
        interval=Interval(t(from_hour), t(to_hour)),
        state_value="ABORTED",
        reason_code=reason,
        is_planned=False,
        source=source,
        note=note,
        assigned_by=assigned_by,
    )


def compile_pg(statement) -> tuple[str, dict[str, object]]:
    """The statement as lower-cased SQL plus its bind parameters.

    Without `literal_binds`, so nothing depends on how a given SQLAlchemy version renders a
    timezone-aware datetime as a literal. Values are asserted through `params`.
    """
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled).lower(), dict(compiled.params)


def test_result_values_carry_the_window_and_its_label():
    values = result_values(UNIT, WINDOW, metrics(), FINGERPRINT, COMPUTED_AT)
    assert values["oee_unit_id"] == UNIT
    assert values["shift_start"] == t(4)
    assert values["shift_end"] == t(12)
    assert values["shift_label"] == "A"


def test_result_values_carry_every_factor_and_its_fingerprint():
    values = result_values(UNIT, WINDOW, metrics(), FINGERPRINT, COMPUTED_AT)
    assert values["availability"] == 0.9
    assert values["performance"] == 0.95
    assert values["performance_raw"] == 0.95
    assert values["quality"] == 0.98
    assert values["oee"] == 0.8379
    assert values["status"] == "OK"
    assert values["input_fingerprint"] == FINGERPRINT.as_text()
    assert values["computed_at"] == COMPUTED_AT


def test_an_undefined_factor_is_stored_as_null_not_zero():
    blank = replace(metrics(), availability=None, performance=None, quality=None, oee=None)
    values = result_values(UNIT, WINDOW, blank, FINGERPRINT, COMPUTED_AT)
    assert values["availability"] is None
    assert values["oee"] is None


def test_a_saved_result_is_always_unpublished():
    assert result_values(UNIT, WINDOW, metrics(), FINGERPRINT, COMPUTED_AT)["published_at"] is None


def test_revision_values_copy_the_stored_row_verbatim():
    stored = ShiftResult(
        id=99,
        oee_unit_id=UNIT,
        shift_start=t(4),
        revision=2,
        loading_time_s=27000.0,
        run_time_s=24300.0,
        good_count=11760.0,
        reject_count=240.0,
        total_count=12000.0,
        availability=0.9,
        performance=0.95,
        quality=0.98,
        oee=0.8379,
        status="OK",
        input_fingerprint="2880:2026-09-07T12:00:00+00:00",
        computed_at=COMPUTED_AT,
    )
    values = revision_values(stored)
    assert values["revision"] == 2
    assert values["oee"] == 0.8379
    assert values["input_fingerprint"] == "2880:2026-09-07T12:00:00+00:00"
    assert values["computed_at"] == COMPUTED_AT
    assert "superseded_at" not in values


def test_one_product_row_per_segment():
    rows = product_values(99, metrics())
    assert len(rows) == 1
    assert rows[0] == {
        "shift_result_id": 99,
        "product_code": "R-100-STD",
        "good_count": 11760.0,
        "reject_count": 240.0,
        "total_count": 12000.0,
        "ideal_cycle_time_s": 2.0,
    }


def test_a_segment_with_no_product_code_stores_the_empty_string():
    unbound = replace(metrics().products[0], product_code=None)
    rows = product_values(99, replace(metrics(), products=(unbound,)))
    assert rows[0]["product_code"] == ""


def test_a_segment_with_no_ideal_cycle_time_stores_null():
    gap = replace(metrics().products[0], ideal_cycle_time_s=None)
    rows = product_values(99, replace(metrics(), products=(gap,)))
    assert rows[0]["ideal_cycle_time_s"] is None


def test_no_segments_is_no_product_rows():
    assert product_values(99, replace(metrics(), products=())) == []


def test_one_event_row_per_stop_with_its_duration():
    rows = event_values(UNIT, t(4), (stop(6, 7), stop(9, 10)))
    assert [row["started_at"] for row in rows] == [t(6), t(9)]
    assert [row["duration_s"] for row in rows] == [3600.0, 3600.0]
    assert {row["shift_start"] for row in rows} == {t(4)}


def test_an_event_carries_the_classification():
    row = event_values(UNIT, t(4), (stop(6, 7),))[0]
    assert row["oee_unit_id"] == UNIT
    assert row["state_value"] == "ABORTED"
    assert row["reason_code"] == "MECH_FAILURE"
    assert row["reason_source"] == AUTO
    assert row["assigned_by"] is None
    assert row["assigned_at"] is None
    assert row["note"] == ""


def test_a_manual_classification_carries_its_assigner_and_note():
    manual = stop(6, 7, reason="TOOL_CHANGE", source=MANUAL, note="die swap", assigned_by="operator1")
    row = event_values(UNIT, t(4), (manual,))[0]
    assert row["reason_code"] == "TOOL_CHANGE"
    assert row["reason_source"] == MANUAL
    assert row["assigned_by"] == "operator1"
    assert row["note"] == "die swap"


def test_no_stops_is_no_event_rows():
    assert event_values(UNIT, t(4), ()) == []


def test_the_upsert_conflicts_on_unit_and_started_at():
    sql, _ = compile_pg(downtime_upsert(event_values(UNIT, t(4), (stop(6, 7),))))
    assert "on conflict (oee_unit_id, started_at) do update" in sql


def test_the_upsert_always_refreshes_the_stops_geometry():
    sql, _ = compile_pg(downtime_upsert(event_values(UNIT, t(4), (stop(6, 7),))))
    for column in GEOMETRY_COLUMNS:
        assert f"excluded.{column}" in sql
        assert f"downtime_event.{column}" not in sql


def test_the_upsert_never_overwrites_a_manual_reason():
    sql, params = compile_pg(downtime_upsert(event_values(UNIT, t(4), (stop(6, 7),))))
    assert "case when" in sql
    for column in REASON_COLUMNS:
        assert f"downtime_event.{column}" in sql
        assert f"excluded.{column}" in sql
    assert MANUAL in params.values()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_store.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.store'`.

- [ ] **Step 3: Write the implementation**

Create `12_uns_oee/src/uns_oee/store.py`:

```python
"""Writing one shift's numbers, so that writing them twice changes nothing.

Recomputation is normal here: a late sample, a corrected shift exception or an operator
assigning a downtime reason all make yesterday's shift worth computing again. Every write is
therefore keyed on something the engine did not derive - a result on (unit, shift_start), a
stop on (unit, started_at) - and the numbers a revision replaces move to
`oee.shift_result_revision` rather than disappearing.

The one thing a recomputation must never do is overwrite a person. `classifier.classify`
already honours a stored manual reason; the `ON CONFLICT` clause here refuses the overwrite a
second time, because the match by `started_at` fails whenever recomputation moves a stop's
first sample, and an operator's work must not depend on that.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, delete, insert, select, update
from sqlalchemy.dialects.postgresql import Insert as PostgresInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from uns_model.engine import Database
from uns_model.oee_tables import (
    DowntimeEvent,
    ShiftResult,
    ShiftResultProduct,
    ShiftResultRevision,
)
from uns_oee.classifier import MANUAL, ClassifiedStop, ManualReason
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import Fingerprint

LOGGER = logging.getLogger(__name__)

#: Derived from the samples on every run, so always refreshed. None of these is ever authored.
GEOMETRY_COLUMNS = ("shift_start", "ended_at", "duration_s", "state_value")

#: Kept as they are once `reason_source` is 'manual'. This tuple is the enforcement of Rule 3.
REASON_COLUMNS = ("reason_code", "reason_source", "assigned_by", "assigned_at", "note")


@dataclass(frozen=True, slots=True)
class StoredResult:
    """What is already on record for one shift.

    `input_fingerprint` is the reason this type exists: comparing it against a fresh
    fingerprint is how the pipeline decides a shift needs no work, which is what makes a
    30-day backfill cheap on its second run.
    """

    result_id: int
    revision: int
    input_fingerprint: str
    published_at: datetime | None


def result_values(
    unit_id: int,
    window: ShiftWindow,
    metrics: ShiftMetrics,
    fingerprint: Fingerprint,
    computed_at: datetime,
) -> dict[str, object]:
    """The `oee.shift_result` column values for one computed shift.

    `published_at` is always None, including on a revision. A corrected number has not been
    published even though the number it replaces was, and keeping the old timestamp would make
    the publisher skip the correction and leave MQTT disagreeing with the database for good.
    """
    return {
        "oee_unit_id": unit_id,
        "shift_start": window.start,
        "shift_end": window.end,
        "shift_label": window.label,
        "loading_time_s": metrics.loading_time_s,
        "run_time_s": metrics.run_time_s,
        "planned_down_s": metrics.planned_down_s,
        "unplanned_down_s": metrics.unplanned_down_s,
        "good_count": metrics.good_count,
        "reject_count": metrics.reject_count,
        "total_count": metrics.total_count,
        "availability": metrics.availability,
        "performance": metrics.performance,
        "performance_raw": metrics.performance_raw,
        "quality": metrics.quality,
        "oee": metrics.oee,
        "status": metrics.status,
        "input_fingerprint": fingerprint.as_text(),
        "computed_at": computed_at,
        "published_at": None,
    }


def revision_values(stored: ShiftResult) -> dict[str, object]:
    """The row about to be replaced, as an `oee.shift_result_revision` insert.

    The old `revision` and the old `computed_at` are copied, not restamped: this row's whole
    purpose is to say what the number was and when it was worked out. `superseded_at` is left
    to the column default so the database, not the engine, records when it stopped being true.
    """
    return {
        "oee_unit_id": stored.oee_unit_id,
        "shift_start": stored.shift_start,
        "revision": stored.revision,
        "loading_time_s": stored.loading_time_s,
        "run_time_s": stored.run_time_s,
        "good_count": stored.good_count,
        "reject_count": stored.reject_count,
        "total_count": stored.total_count,
        "availability": stored.availability,
        "performance": stored.performance,
        "quality": stored.quality,
        "oee": stored.oee,
        "status": stored.status,
        "input_fingerprint": stored.input_fingerprint,
        "computed_at": stored.computed_at,
    }


def product_values(result_id: int, metrics: ShiftMetrics) -> list[dict[str, object]]:
    """One `oee.shift_result_product` row per product segment.

    A segment with no product code stores the empty string rather than NULL, because
    `product_code` is part of a unique constraint and NULLs there would let the same unbound
    segment be inserted twice.
    """
    return [
        {
            "shift_result_id": result_id,
            "product_code": item.product_code or "",
            "good_count": item.good_count,
            "reject_count": item.reject_count,
            "total_count": item.total_count,
            "ideal_cycle_time_s": item.ideal_cycle_time_s,
        }
        for item in metrics.products
    ]


def event_values(
    unit_id: int, shift_start: datetime, stops: Sequence[ClassifiedStop]
) -> list[dict[str, object]]:
    """One `oee.downtime_event` row per classified stop.

    `assigned_at` is always None. A stop can only be manual because a stored row already was,
    and the conflict clause keeps that row's timestamp - so a value here would either be
    ignored or, worse, restamp a human decision with the time the engine last ran.
    """
    return [
        {
            "oee_unit_id": unit_id,
            "shift_start": shift_start,
            "started_at": stop.interval.start,
            "ended_at": stop.interval.end,
            "duration_s": stop.interval.duration_s,
            "state_value": stop.state_value,
            "reason_code": stop.reason_code,
            "reason_source": stop.source,
            "assigned_by": stop.assigned_by,
            "assigned_at": None,
            "note": stop.note,
        }
        for stop in stops
    ]


def downtime_upsert(rows: Sequence[Mapping[str, object]]) -> PostgresInsert:
    """Insert these stops, refreshing what is derived and preserving what a person set.

    In `ON CONFLICT DO UPDATE`, an unqualified reference to the target table is the row already
    stored and `excluded` is the row being inserted. So each reason column becomes: keep the
    stored value where the stored `reason_source` is 'manual', otherwise take the new one. The
    geometry columns take the new value unconditionally, because a stop that recomputed to a
    different length is a better fact than the one on record.
    """
    statement = pg_insert(DowntimeEvent)
    stored = DowntimeEvent.__table__.c
    is_manual = stored.reason_source == MANUAL
    refreshed: dict[str, object] = {
        column: statement.excluded[column] for column in GEOMETRY_COLUMNS
    }
    preserved: dict[str, object] = {
        column: case((is_manual, stored[column]), else_=statement.excluded[column])
        for column in REASON_COLUMNS
    }
    return statement.values(list(rows)).on_conflict_do_update(
        index_elements=["oee_unit_id", "started_at"],
        set_=refreshed | preserved,
    )


class ResultStore:
    """Every write the engine makes to the `oee` schema."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def existing(self, unit_id: int, shift_start: datetime) -> StoredResult | None:
        """What is on record for this shift, or None if it has never been computed."""
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(
                        ShiftResult.id,
                        ShiftResult.revision,
                        ShiftResult.input_fingerprint,
                        ShiftResult.published_at,
                    ).where(
                        ShiftResult.oee_unit_id == unit_id,
                        ShiftResult.shift_start == shift_start,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        return StoredResult(
            result_id=row.id,
            revision=row.revision,
            input_fingerprint=row.input_fingerprint,
            published_at=row.published_at,
        )

    async def manual_reasons(
        self, unit_id: int, window: ShiftWindow
    ) -> dict[datetime, ManualReason]:
        """The human-assigned reasons inside this shift, keyed by the stop's start instant.

        Keyed by `started_at` because that is what `classifier.classify` matches on, and what
        the unique constraint keys on. A stop whose start moved between runs will not match,
        which is why `downtime_upsert` refuses the overwrite as well.
        """
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(
                        DowntimeEvent.started_at,
                        DowntimeEvent.reason_code,
                        DowntimeEvent.note,
                        DowntimeEvent.assigned_by,
                    ).where(
                        DowntimeEvent.oee_unit_id == unit_id,
                        DowntimeEvent.reason_source == MANUAL,
                        DowntimeEvent.started_at >= window.start,
                        DowntimeEvent.started_at < window.end,
                    )
                )
            ).all()
        return {
            row.started_at: ManualReason(
                reason_code=row.reason_code, note=row.note, assigned_by=row.assigned_by
            )
            for row in rows
        }

    async def save(
        self,
        unit_id: int,
        window: ShiftWindow,
        metrics: ShiftMetrics,
        stops: Sequence[ClassifiedStop],
        fingerprint: Fingerprint,
        computed_at: datetime,
    ) -> StoredResult:
        """Write this shift's numbers, superseding whatever was there. One transaction.

        The existing row is selected `FOR UPDATE` so two engine processes cannot both decide
        they are writing revision 3. On the insert path there is no row to lock, and the unique
        constraint on (oee_unit_id, shift_start) is what stops the duplicate instead.
        """
        values = result_values(unit_id, window, metrics, fingerprint, computed_at)
        async with self._database.session() as session:
            stored = (
                await session.scalars(
                    select(ShiftResult)
                    .where(
                        ShiftResult.oee_unit_id == unit_id,
                        ShiftResult.shift_start == window.start,
                    )
                    .with_for_update()
                )
            ).one_or_none()

            if stored is None:
                revision = 1
                result_id = (
                    await session.execute(
                        insert(ShiftResult)
                        .values(**values, revision=revision)
                        .returning(ShiftResult.id)
                    )
                ).scalar_one()
            else:
                revision = stored.revision + 1
                result_id = stored.id
                session.add(ShiftResultRevision(**revision_values(stored)))
                await session.execute(
                    update(ShiftResult)
                    .where(ShiftResult.id == result_id)
                    .values(**values, revision=revision)
                )
                await session.execute(
                    delete(ShiftResultProduct).where(
                        ShiftResultProduct.shift_result_id == result_id
                    )
                )
                LOGGER.info(
                    "OEE unit %d shift %s recomputed as revision %d",
                    unit_id,
                    window.start.isoformat(),
                    revision,
                )

            products = product_values(result_id, metrics)
            if products:
                await session.execute(insert(ShiftResultProduct), products)

            events = event_values(unit_id, window.start, stops)
            if events:
                await session.execute(downtime_upsert(events))

        return StoredResult(
            result_id=result_id,
            revision=revision,
            input_fingerprint=str(values["input_fingerprint"]),
            published_at=None,
        )

    async def mark_published(self, result_id: int, published_at: datetime) -> None:
        """Record that this result reached MQTT.

        Separate from `save` and written after the publish returns, so a broker outage leaves
        `published_at` NULL and the next scan retries rather than silently losing the message.
        """
        async with self._database.session() as session:
            await session.execute(
                update(ShiftResult)
                .where(ShiftResult.id == result_id)
                .values(published_at=published_at)
            )


__all__ = [
    "GEOMETRY_COLUMNS",
    "REASON_COLUMNS",
    "ResultStore",
    "StoredResult",
    "downtime_upsert",
    "event_values",
    "product_values",
    "result_values",
    "revision_values",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_store.py -v -n 0`
Expected: PASS (15 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/store.py 12_uns_oee/test/test_store.py
git commit -m "feat(oee): store shift results idempotently, preserving manual reasons"
```

---

### Task 11: Publishing the result back into the namespace

**Files:**
- Create: `12_uns_oee/src/uns_oee/publisher.py`
- Create: `12_uns_oee/test/test_publisher.py`

**Interfaces:**
- Consumes: `OeeConfig` (Task 1); `ShiftWindow` (Task 4); `ShiftMetrics` (Task 7).
- Produces: constants `KPI_PARAMETER_TYPE = "KPI"`, `KPI_PARAMETER_NAME = "ShiftOee"`, `PAYLOAD_SOURCE = "uns_oee"`, `PAYLOAD_FIELDS: frozenset[str]`; pure functions `shift_oee_topic(asset_path: str) -> str`, `equipment_of(asset_path: str) -> str`, `epoch_millis(at: datetime) -> float`, `as_percent(ratio: float | None) -> float | None`, `shift_oee_payload(asset_path: str, window: ShiftWindow, metrics: ShiftMetrics, revision: int) -> dict[str, Any]`; `ResultPublisher(config, client_factory=None)` with `async publish(asset_path, window, metrics, revision) -> bool`, `async aclose() -> None`, property `connected: bool`, counters `published: int`, `failed: int`.

Spec §11 fixes the topic and the payload; this task transcribes them and adds one long-lived connection.

Two decisions the spec implies but does not spell out:

**A null factor stays null in the payload.** `_scalar_to_metric` returns `None` for a `None` value (`04_uns_historian/src/uns_historian/metric_flattener.py:52`–`:53`), so a null leaf produces no `uns_metrics` row at all. That is exactly the behaviour spec §7.2 wants — an undefined Availability has no row rather than a fabricated zero — and it means the publisher can emit the nulls verbatim instead of inventing a sentinel.

**`publish` returns a bool; it does not raise.** The caller uses the answer to decide whether to call `ResultStore.mark_published`. A broker outage therefore leaves `published_at` NULL and the next scan retries, which is the whole retry mechanism — there is no queue and no backoff loop in this module.

Counts stay floats even though spec §11's example shows integers: a counter delta need not be discrete, because a kilogram counter is a counter, and the historian stores both as `value_double` regardless.

Nothing is published with `retain=True`. A shift result is a historical fact stamped at its own `shift_end`; retained, it would be re-delivered to every new subscriber as though it were the current shift. The trend comes from the historian, which is the point of the whole design.

TLS is not wired up, because `conf/settings.yaml:47`–`:58` defines no TLS keys for any module's broker connection, and OEE would be the only place one existed. Credentials, if set, come from `conf/.secrets.yaml` or `UNS_`-prefixed environment variables as everywhere else.

- [ ] **Step 1: Write the failing test**

Create `12_uns_oee/test/test_publisher.py`:

```python
"""Tests for uns_oee.publisher - the topic, the payload, and one connection.

The payload numbers here are spec section 11's worked example, so a change to the rounding
or to a field name fails against the document rather than against a copy of it.
"""

import json
from datetime import datetime, timezone

import pytest

from uns_oee.oee_config import OeeConfig
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.publisher import (
    PAYLOAD_FIELDS,
    PAYLOAD_SOURCE,
    ResultPublisher,
    epoch_millis,
    equipment_of,
    shift_oee_payload,
    shift_oee_topic,
)
from uns_oee.shift_calendar import ShiftWindow

LINE = "CovestroAG/Dormagen/Production/Line1"
WINDOW = ShiftWindow(
    start=datetime(2026, 9, 7, 4, tzinfo=timezone.utc),
    end=datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
    label="A",
)
CONFIG = OeeConfig(mqtt_host="localhost")


def metrics() -> ShiftMetrics:
    return ShiftMetrics(
        loading_time_s=27000.0,
        run_time_s=24084.0,
        planned_down_s=1800.0,
        unplanned_down_s=2916.0,
        good_count=12840.0,
        reject_count=182.0,
        total_count=13022.0,
        availability=0.892,
        performance=0.841,
        performance_raw=0.841,
        quality=0.952,
        oee=0.714,
        status="OK",
    )


class FakeClient:
    """An aiomqtt.Client stand-in: an async context manager with a publish."""

    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[tuple[str, str, int, bool]] = []
        self.fail = fail
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> "FakeClient":
        self.entered += 1
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        self.exited += 1
        return False

    async def publish(self, topic, payload, qos=0, retain=False) -> None:
        if self.fail:
            raise RuntimeError("broker unreachable")
        self.messages.append((topic, payload, qos, retain))


def test_the_topic_is_the_asset_path_plus_the_kpi_parameter():
    assert shift_oee_topic(LINE) == f"{LINE}/KPI/ShiftOee"


def test_equipment_is_the_last_segment_of_the_asset_path():
    assert equipment_of(LINE) == "Line1"
    assert equipment_of("Line1") == "Line1"


def test_the_headline_value_is_oee_as_a_percentage():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=1)
    assert payload["value"] == 71.4
    assert payload["unit"] == "%"


def test_every_factor_is_a_percentage_and_no_count_is():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=1)
    assert payload["availability"] == 89.2
    assert payload["performance"] == 84.1
    assert payload["quality"] == 95.2
    assert payload["good_count"] == 12840.0
    assert payload["reject_count"] == 182.0
    assert payload["total_count"] == 13022.0


def test_the_timestamp_is_shift_end_in_epoch_milliseconds():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=1)
    assert payload["timestamp"] == epoch_millis(WINDOW.end)
    assert payload["shift_start"] == epoch_millis(WINDOW.start)
    assert payload["timestamp"] > payload["shift_start"]


def test_an_undefined_factor_stays_null_so_the_historian_writes_no_row():
    blank = ShiftMetrics(status="NO_LOADING_TIME")
    payload = shift_oee_payload(LINE, WINDOW, blank, revision=1)
    assert payload["value"] is None
    assert payload["availability"] is None
    assert payload["quality"] is None
    assert payload["status"] == "NO_LOADING_TIME"


def test_the_shift_label_source_and_revision_travel_with_the_payload():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=3)
    assert payload["shift_label"] == "A"
    assert payload["source"] == PAYLOAD_SOURCE
    assert payload["equipment"] == "Line1"
    assert payload["revision"] == 3


def test_the_payload_has_exactly_the_documented_field_set():
    assert set(shift_oee_payload(LINE, WINDOW, metrics(), revision=1)) == PAYLOAD_FIELDS


@pytest.mark.asyncio
async def test_publishing_sends_one_json_message_at_the_configured_qos():
    client = FakeClient()
    publisher = ResultPublisher(CONFIG, client_factory=lambda: client)

    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is True

    topic, body, qos, retain = client.messages[0]
    assert topic == f"{LINE}/KPI/ShiftOee"
    assert json.loads(body)["value"] == 71.4
    assert qos == CONFIG.mqtt_qos
    assert retain is False
    assert publisher.published == 1
    await publisher.aclose()


@pytest.mark.asyncio
async def test_a_second_publish_reuses_the_one_connection():
    client = FakeClient()
    publisher = ResultPublisher(CONFIG, client_factory=lambda: client)

    await publisher.publish(LINE, WINDOW, metrics(), revision=1)
    await publisher.publish(LINE, WINDOW, metrics(), revision=2)

    assert client.entered == 1
    assert len(client.messages) == 2
    await publisher.aclose()


@pytest.mark.asyncio
async def test_a_broker_failure_is_reported_not_raised():
    publisher = ResultPublisher(CONFIG, client_factory=lambda: FakeClient(fail=True))

    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is False
    assert publisher.failed == 1
    assert publisher.published == 0
    assert not publisher.connected


@pytest.mark.asyncio
async def test_a_failure_drops_the_connection_so_the_next_call_reconnects():
    clients = [FakeClient(fail=True), FakeClient()]
    publisher = ResultPublisher(CONFIG, client_factory=lambda: clients.pop(0))

    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is False
    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is True
    assert publisher.failed == 1
    assert publisher.published == 1
    await publisher.aclose()


@pytest.mark.asyncio
async def test_closing_an_unconnected_publisher_is_not_an_error():
    publisher = ResultPublisher(CONFIG, client_factory=FakeClient)
    await publisher.aclose()
    assert not publisher.connected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_publisher.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.publisher'`.

- [ ] **Step 3: Write the implementation**

Create `12_uns_oee/src/uns_oee/publisher.py`:

```python
"""Publishing a closed shift's OEE back onto the unit's own Asset path.

The engine reads history and writes a result, and this module is the only part of it that
touches MQTT. One message per unit per shift on `<asset path>/KPI/ShiftOee`, over one
long-lived connection - the scheduler wakes every few minutes, and a connect-publish-
disconnect per result would spend more time in handshakes than in work.

`publish` returns False rather than raising. Whether the message reached the broker decides
whether `ResultStore.mark_published` is called, and a NULL `published_at` is what makes the
next scan try again. That is the entire retry mechanism: no queue, no backoff, nothing to
drain on shutdown, and nothing that can silently lose a result because a process died.
"""

import contextlib
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import aiomqtt

from uns_oee.oee_config import OeeConfig
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.shift_calendar import ShiftWindow

LOGGER = logging.getLogger(__name__)

#: The sixth ParameterType, added to the simulator's enum in Task 17. A computed shift KPI is
#: not a ProcessValue, and the graph database and alert engine both type topics by this segment.
KPI_PARAMETER_TYPE = "KPI"
KPI_PARAMETER_NAME = "ShiftOee"

#: `source` on every payload, so a consumer can tell a computed number from a measured one.
PAYLOAD_SOURCE = "uns_oee"

#: Percentages are published to this many decimals. One is what a shift report shows.
_PERCENT_DECIMALS = 1

#: Spec section 11's field set, asserted against rather than described.
PAYLOAD_FIELDS = frozenset(
    {
        "value",
        "unit",
        "quality",
        "timestamp",
        "source",
        "equipment",
        "availability",
        "performance",
        "good_count",
        "reject_count",
        "total_count",
        "shift_label",
        "shift_start",
        "status",
        "revision",
    }
)


def shift_oee_topic(asset_path: str) -> str:
    """The unit's own Asset path plus the KPI parameter. No new topic namespace."""
    return f"{asset_path}/{KPI_PARAMETER_TYPE}/{KPI_PARAMETER_NAME}"


def equipment_of(asset_path: str) -> str:
    """The last segment of the Asset path, which is the platform's `equipment` convention.

    Imprecise at line level - `Line1` is not a piece of equipment - but it is the existing
    convention, and a second field name for the same idea would be worse than a loose word.
    """
    return asset_path.rsplit("/", 1)[-1]


def epoch_millis(at: datetime) -> float:
    """A timezone-aware instant as epoch milliseconds.

    Milliseconds because `conf/settings.yaml:57` makes `timestamp` the historian's `time`
    column, and every other publisher on this platform already uses that unit.
    """
    return at.timestamp() * 1000.0


def as_percent(ratio: float | None) -> float | None:
    """A 0-1 factor as a percentage, or None if it is undefined.

    None survives as None: `flatten_payload_to_metrics` skips a null leaf entirely
    (`metric_flattener.py:52`), so an undefined factor produces no `uns_metrics` row instead
    of a zero that would drag every rollup down.
    """
    return None if ratio is None else round(ratio * 100.0, _PERCENT_DECIMALS)


def shift_oee_payload(
    asset_path: str, window: ShiftWindow, metrics: ShiftMetrics, revision: int
) -> dict[str, Any]:
    """Spec section 11's payload for one closed shift.

    `timestamp` is `shift_end`, so the historian stamps the result at the moment the shift
    finished - which is where a trend line needs it, not where the engine happened to run.
    Counts stay floats: a counter delta need not be discrete, and `value_double` holds both.
    """
    return {
        "value": as_percent(metrics.oee),
        "unit": "%",
        "quality": as_percent(metrics.quality),
        "timestamp": epoch_millis(window.end),
        "source": PAYLOAD_SOURCE,
        "equipment": equipment_of(asset_path),
        "availability": as_percent(metrics.availability),
        "performance": as_percent(metrics.performance),
        "good_count": metrics.good_count,
        "reject_count": metrics.reject_count,
        "total_count": metrics.total_count,
        "shift_label": window.label,
        "shift_start": epoch_millis(window.start),
        "status": metrics.status,
        "revision": revision,
    }


class ResultPublisher:
    """One MQTT connection, opened on the first publish and kept.

    `client_factory` exists so a test can hand in a stand-in; production leaves it unset and
    gets a client built from `OeeConfig`.
    """

    def __init__(
        self, config: OeeConfig, client_factory: Callable[[], Any] | None = None
    ) -> None:
        self._config = config
        self._client_factory = client_factory or self._build_client
        self._stack: contextlib.AsyncExitStack | None = None
        self._client: Any | None = None
        self.published = 0
        self.failed = 0

    @property
    def connected(self) -> bool:
        return self._client is not None

    def _build_client(self) -> aiomqtt.Client:
        """A client from the platform's shared `mqtt:` settings.

        `clean_session` is deliberately left unset: aiomqtt rejects it under MQTT 5, and the
        platform's `mqtt.version` is 5. No Last Will either - the engine has no online state
        worth announcing, unlike the simulator's heartbeat.
        """
        return aiomqtt.Client(
            identifier=self._config.mqtt_client_id,
            hostname=self._config.mqtt_host,
            port=self._config.mqtt_port,
            username=self._config.mqtt_username,
            password=self._config.mqtt_password,
            keepalive=self._config.mqtt_keep_alive,
            protocol=aiomqtt.ProtocolVersion(self._config.mqtt_version),
            transport=self._config.mqtt_transport,
        )

    async def _connect(self) -> Any:
        """The live client, connecting first if there is not one."""
        if self._client is None:
            stack = contextlib.AsyncExitStack()
            self._client = await stack.enter_async_context(self._client_factory())
            self._stack = stack
            LOGGER.info(
                "OEE publisher connected to %s:%s as %s",
                self._config.mqtt_host,
                self._config.mqtt_port,
                self._config.mqtt_client_id,
            )
        return self._client

    async def _drop(self) -> None:
        """Forget the connection, so the next publish makes a new one.

        Errors while closing are suppressed: this is called because publishing already failed,
        and a second exception from the same broken socket says nothing new.
        """
        stack = self._stack
        self._stack = None
        self._client = None
        if stack is not None:
            with contextlib.suppress(Exception):
                await stack.aclose()

    async def publish(
        self, asset_path: str, window: ShiftWindow, metrics: ShiftMetrics, revision: int
    ) -> bool:
        """Send one shift result. True if the broker took it.

        Not retained: a shift result is a historical fact stamped at its own `shift_end`, and
        retaining it would hand every new subscriber the last closed shift as though it were
        the current one.
        """
        topic = shift_oee_topic(asset_path)
        body = json.dumps(shift_oee_payload(asset_path, window, metrics, revision))
        try:
            client = await self._connect()
            await client.publish(topic, body, qos=self._config.mqtt_qos, retain=False)
        except Exception:
            self.failed += 1
            LOGGER.exception("OEE publish to %s failed; leaving it unpublished for retry", topic)
            await self._drop()
            return False
        self.published += 1
        LOGGER.debug("Published %s revision %d", topic, revision)
        return True

    async def aclose(self) -> None:
        """Close the connection if there is one. Safe to call when there is not."""
        await self._drop()


__all__ = [
    "KPI_PARAMETER_NAME",
    "KPI_PARAMETER_TYPE",
    "PAYLOAD_FIELDS",
    "PAYLOAD_SOURCE",
    "ResultPublisher",
    "as_percent",
    "epoch_millis",
    "equipment_of",
    "shift_oee_payload",
    "shift_oee_topic",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_publisher.py -v -n 0`
Expected: PASS (13 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/publisher.py 12_uns_oee/test/test_publisher.py
git commit -m "feat(oee): publish shift results on the unit's KPI/ShiftOee topic"
```

---

### Task 12: One shift, end to end

**Files:**
- Create: `12_uns_oee/src/uns_oee/pipeline.py`
- Create: `12_uns_oee/test/test_pipeline.py`

**Interfaces:**
- Consumes: `UNCLASSIFIED_REASON_CODE` from `uns_model.oee_tables` (Task 2); `ShiftWindow` (Task 4); `Sample`, `counter_delta`, `counter_delta_in` (Task 5); `Interval`, `StateSample`, `merge`, `state_segments`, `stop_intervals`, `union_duration_s` (Task 5); `ClassifiedStop`, `ManualReason`, `classify` (Task 6); `ProductSegment`, `ShiftInputs`, `ShiftMetrics`, `compute` (Task 7); `Fingerprint`, `MetricSource` (Task 8); `MasterDataLoader`, `UnitMasterData`, `exception_intervals` (Task 9); `ResultStore`, `StoredResult` (Task 10); `ResultPublisher` (Task 11).
- Produces: action constants `ACTION_COMPUTED = "COMPUTED"`, `ACTION_REVISED = "REVISED"`, `ACTION_REPUBLISHED = "REPUBLISHED"`, `ACTION_UNCHANGED = "UNCHANGED"`; `ShiftSamples(state, good, reject, product)` with `.counter_resets -> int`; `ShiftOutcome(unit_id, asset_path, window, action, metrics, revision, published, input_rows, counter_resets, unclassified_seconds, late_data, compute_seconds)`; pure functions `as_interval(window: ShiftWindow) -> Interval`, `product_segments(unit, window, samples) -> tuple[ProductSegment, ...]`, `shift_inputs(unit, window, samples, exceptions, manual, *, has_input_data=True) -> ShiftInputs`, `unclassified_seconds(stops: Sequence[ClassifiedStop]) -> float`, `manual_digest(manual: Mapping[datetime, ManualReason]) -> str`; `ShiftPipeline(source, master, store, publisher)` with `async run_shift(unit, window, computed_at) -> ShiftOutcome`.

Spec §5 fixes the order: `shift_calendar → sources → counters + states → classifier → oee_calc → store → publisher`. Everything before `store` is a pure function here, and only `run_shift` performs IO — which is why the interesting behaviour is tested without a database and only the five-branch action decision needs fakes.

**Why a product code series is a state series.** `state_segments` turns `(instant, string)` samples into contiguous segments of equal value. That is exactly what segmenting a shift by `RecipeId` is, so per-product segmentation reuses it rather than reimplementing coalescing. Per-segment counts then come from `counter_delta_in` over each interval, and because that function includes the sample sitting exactly on `end`, the increment across a product changeover is credited to the outgoing product and the incoming one starts from the changeover value. Σ per-product therefore equals the whole-window delta, which is what makes `oee.shift_result_product` reconcile with `oee.shift_result`.

**Why an unpublished shift is recomputed rather than read back.** When the fingerprint matches the stored one but `published_at` is NULL, the numbers on record are already right and only the MQTT message is missing. Recomputing them costs one shift's arithmetic and lets the publisher be handed a `ShiftMetrics` without a second read path out of `oee.shift_result`. Rule 1 is what makes this sound — the same inputs give the same output — so the recomputed metrics are published under the **stored** revision and nothing is written. Bumping the revision because a broker was down would make `revision` count outages instead of corrections.

- [ ] **Step 1: Write the failing test**

Create `12_uns_oee/test/test_pipeline.py`:

```python
"""Tests for uns_oee.pipeline - the shift's assembly line.

Two halves. The pure functions get real sample series, because the bugs that matter here are
arithmetic: a product changeover counted twice, a stop truncated at the shift boundary, a
manual reason lost. The five-branch action decision gets fakes, because what matters there is
which writes happen - and a revision bump for a broker outage is a bug no arithmetic test
would catch.
"""

from datetime import datetime, time, timezone

import pytest

from uns_model.oee_tables import UNCLASSIFIED_REASON_CODE
from uns_oee.classifier import AUTO, MANUAL, ManualReason, ReasonResolver, ReasonSpec
from uns_oee.counters import Sample
from uns_oee.master_data import ExceptionWindow, UnitMasterData
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.pipeline import (
    ACTION_COMPUTED,
    ACTION_REPUBLISHED,
    ACTION_REVISED,
    ACTION_UNCHANGED,
    ShiftPipeline,
    ShiftSamples,
    manual_digest,
    product_segments,
    shift_inputs,
    unclassified_seconds,
)
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot, ShiftWindow
from uns_oee.sources import Fingerprint, MetricRef
from uns_oee.states import Interval, StateSample
from uns_oee.store import StoredResult

LINE = "CovestroAG/Dormagen/Production/Line1"
MES = f"{LINE}/Cell1/MES-01"


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


WINDOW = ShiftWindow(start=t(6), end=t(14), label="A")
COMPUTED_AT = datetime(2026, 9, 7, 14, 15, tzinfo=timezone.utc)

REASONS = {
    UNCLASSIFIED_REASON_CODE: ReasonSpec(UNCLASSIFIED_REASON_CODE, "Unclassified", "UNKNOWN", False),
    "MECH_FAILURE": ReasonSpec("MECH_FAILURE", "Mechanical failure", "EQUIPMENT", False),
    "TOOL_CHANGE": ReasonSpec("TOOL_CHANGE", "Tool change", "PLANNED", True),
}


def unit(*, product_bound: bool = True) -> UnitMasterData:
    return UnitMasterData(
        unit_id=1,
        asset_id=42,
        asset_path=LINE,
        schedule=ShiftSchedule(
            name="Dormagen 3-shift",
            timezone="Europe/Berlin",
            slots=(ShiftSlot(0, time(6, 0), 480, "A"),),
        ),
        producing_states=("EXECUTE",),
        state_ref=MetricRef(f"{MES}/Status/PackMlState", "value"),
        good_ref=MetricRef(f"{MES}/ProcessValue/GoodCount", "value"),
        reject_ref=MetricRef(f"{MES}/ProcessValue/RejectCount", "value"),
        product_ref=MetricRef(f"{MES}/Status/RecipeId", "value") if product_bound else None,
        ideal_cycle_times={None: 3.0, "R-100-STD": 2.0},
        resolver=ReasonResolver(
            reasons=REASONS,
            unit_rules={},
            default_rules={"ABORTED": "MECH_FAILURE", "SUSPENDED": "TOOL_CHANGE"},
        ),
    )


def samples(
    *,
    state: tuple[StateSample, ...] = (),
    good: tuple[Sample, ...] = (),
    reject: tuple[Sample, ...] = (),
    product: tuple[StateSample, ...] = (),
) -> ShiftSamples:
    return ShiftSamples(state=state, good=good, reject=reject, product=product)


#: EXECUTE from before the boundary, ABORTED 09:00-10:00, EXECUTE to the end.
RUN_WITH_ONE_STOP = (
    StateSample(t(5, 58), "EXECUTE"),
    StateSample(t(9), "ABORTED"),
    StateSample(t(10), "EXECUTE"),
)
GOOD_CLIMB = (Sample(t(6), 0.0), Sample(t(10), 2500.0), Sample(t(14), 6000.0))
REJECT_CLIMB = (Sample(t(6), 0.0), Sample(t(14), 100.0))
TWO_PRODUCTS = (StateSample(t(6), "R-100-STD"), StateSample(t(10), "R-200-FAST"))


# --- the pure half -------------------------------------------------------------------


def test_a_unit_with_no_product_binding_gets_one_segment_spanning_the_shift():
    segments = product_segments(
        unit(product_bound=False), WINDOW, samples(good=GOOD_CLIMB, reject=REJECT_CLIMB)
    )
    assert len(segments) == 1
    assert segments[0].product_code is None
    assert segments[0].intervals == (Interval(t(6), t(14)),)
    assert segments[0].good_count == 6000.0
    assert segments[0].reject_count == 100.0
    assert segments[0].ideal_cycle_time_s == 3.0


def test_a_product_series_splits_the_shift_into_one_segment_per_code():
    segments = product_segments(
        unit(), WINDOW, samples(good=GOOD_CLIMB, reject=REJECT_CLIMB, product=TWO_PRODUCTS)
    )
    assert {segment.product_code for segment in segments} == {"R-100-STD", "R-200-FAST"}


def test_per_product_counts_sum_to_the_whole_window_delta():
    segments = product_segments(
        unit(), WINDOW, samples(good=GOOD_CLIMB, reject=REJECT_CLIMB, product=TWO_PRODUCTS)
    )
    by_code = {segment.product_code: segment for segment in segments}
    assert by_code["R-100-STD"].good_count == 2500.0
    assert by_code["R-200-FAST"].good_count == 3500.0
    assert sum(segment.good_count for segment in segments) == 6000.0


def test_each_segment_carries_the_ideal_cycle_time_for_its_own_code():
    segments = product_segments(unit(), WINDOW, samples(good=GOOD_CLIMB, product=TWO_PRODUCTS))
    by_code = {segment.product_code: segment for segment in segments}
    assert by_code["R-100-STD"].ideal_cycle_time_s == 2.0
    assert by_code["R-200-FAST"].ideal_cycle_time_s == 3.0


def test_a_product_that_ran_twice_keeps_both_of_its_intervals():
    interrupted = (
        StateSample(t(6), "R-100-STD"),
        StateSample(t(8), "R-200-FAST"),
        StateSample(t(10), "R-100-STD"),
    )
    segments = product_segments(unit(), WINDOW, samples(good=GOOD_CLIMB, product=interrupted))
    by_code = {segment.product_code: segment for segment in segments}
    assert by_code["R-100-STD"].intervals == (Interval(t(6), t(8)), Interval(t(10), t(14)))


def test_a_counter_reset_inside_the_shift_is_counted():
    restarted = (Sample(t(6), 0.0), Sample(t(10), 2500.0), Sample(t(11), 0.0), Sample(t(14), 900.0))
    assert samples(good=restarted).counter_resets == 1
    assert samples(good=GOOD_CLIMB, reject=REJECT_CLIMB).counter_resets == 0


def test_the_state_held_at_the_shift_start_is_carried_in():
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), {})
    # One stop only. If the 05:58 EXECUTE sample were dropped, the shift would open with an
    # unknown state and 06:00-09:00 would become a second, fabricated stop.
    assert len(inputs.classified_stops) == 1
    assert inputs.classified_stops[0].interval == Interval(t(9), t(10))


def test_a_stop_is_classified_before_the_inputs_are_built():
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), {})
    stop = inputs.classified_stops[0]
    assert stop.reason_code == "MECH_FAILURE"
    assert stop.source == AUTO
    assert stop.is_planned is False


def test_a_planned_reason_marks_the_stop_planned():
    suspended = (StateSample(t(5, 58), "EXECUTE"), StateSample(t(9), "SUSPENDED"), StateSample(t(10), "EXECUTE"))
    inputs = shift_inputs(unit(), WINDOW, samples(state=suspended), (), {})
    assert inputs.classified_stops[0].reason_code == "TOOL_CHANGE"
    assert inputs.classified_stops[0].is_planned is True


def test_a_manual_reason_wins_over_the_rule():
    manual = {t(9): ManualReason(reason_code="TOOL_CHANGE", note="die swap", assigned_by="operator1")}
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), manual)
    stop = inputs.classified_stops[0]
    assert stop.reason_code == "TOOL_CHANGE"
    assert stop.source == MANUAL
    assert stop.assigned_by == "operator1"


def test_exception_windows_become_exception_intervals():
    windows = (
        ExceptionWindow(interval=Interval(t(6), t(7)), kind="PLANNED_DOWN", asset_path=LINE),
        ExceptionWindow(interval=Interval(t(7), t(8)), kind="NON_PRODUCING", asset_path=None),
    )
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), windows, {})
    # Merged, so two adjacent exceptions cannot subtract from Loading Time twice.
    assert inputs.exception_intervals == (Interval(t(6), t(8)),)


def test_no_input_rows_makes_the_shift_report_no_input_data():
    inputs = shift_inputs(unit(), WINDOW, samples(), (), {}, has_input_data=False)
    assert inputs.has_input_data is False


def test_unclassified_seconds_totals_only_the_unclassified_stops():
    unknown = (StateSample(t(5, 58), "EXECUTE"), StateSample(t(9), "HELD"), StateSample(t(10), "EXECUTE"))
    inputs = shift_inputs(unit(), WINDOW, samples(state=unknown), (), {})
    assert inputs.classified_stops[0].reason_code == UNCLASSIFIED_REASON_CODE
    assert unclassified_seconds(inputs.classified_stops) == 3600.0


def test_unclassified_seconds_is_zero_when_every_stop_has_a_reason():
    inputs = shift_inputs(unit(), WINDOW, samples(state=RUN_WITH_ONE_STOP), (), {})
    assert unclassified_seconds(inputs.classified_stops) == 0.0


def test_no_manual_reasons_digests_to_a_stable_placeholder():
    assert manual_digest({}) == "-"


def test_a_reassigned_code_changes_the_digest():
    before = {t(9): ManualReason(reason_code="TOOL_CHANGE", assigned_by="operator1")}
    after = {t(9): ManualReason(reason_code="MECH_FAILURE", assigned_by="operator1")}
    assert manual_digest(before) != manual_digest(after)
    # The note and the author are not inputs to the arithmetic, so they are not in the digest.
    assert manual_digest(before) == manual_digest(
        {t(9): ManualReason(reason_code="TOOL_CHANGE", note="die swap", assigned_by="operator2")}
    )


def test_a_reason_moved_to_another_stop_changes_the_digest():
    here = {t(9): ManualReason(reason_code="TOOL_CHANGE")}
    there = {t(11): ManualReason(reason_code="TOOL_CHANGE")}
    assert manual_digest(here) != manual_digest(there)


# --- the IO half ---------------------------------------------------------------------


class FakeSource:
    def __init__(self, series: ShiftSamples, fingerprint: Fingerprint) -> None:
        self.series = series
        self._fingerprint = fingerprint

    async def fingerprint(self, refs, start, end) -> Fingerprint:
        return self._fingerprint

    async def text_samples(self, ref, start, end, *, include_prior=True):
        return list(self.series.product if ref.topic.endswith("RecipeId") else self.series.state)

    async def numeric_samples(self, ref, start, end, *, include_prior=True):
        return list(self.series.reject if ref.topic.endswith("RejectCount") else self.series.good)


class FakeMaster:
    def __init__(self, windows=()) -> None:
        self.windows = list(windows)

    async def exception_windows(self, unit, window):
        return list(self.windows)


class FakeStore:
    def __init__(self, stored: StoredResult | None = None) -> None:
        self.stored = stored
        self.manual: dict[datetime, ManualReason] = {}
        self.saves: list[int] = []
        self.marked: list[tuple[int, datetime]] = []

    async def existing(self, unit_id, shift_start):
        return self.stored

    async def manual_reasons(self, unit_id, window):
        return dict(self.manual)

    async def save(self, unit_id, window, metrics, stops, fingerprint, computed_at):
        revision = 1 if self.stored is None else self.stored.revision + 1
        self.saves.append(revision)
        return StoredResult(
            result_id=11,
            revision=revision,
            input_fingerprint=fingerprint.as_text(),
            published_at=None,
        )

    async def mark_published(self, result_id, published_at):
        self.marked.append((result_id, published_at))


class FakePublisher:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, int]] = []

    async def publish(self, asset_path, window, metrics, revision) -> bool:
        self.sent.append((asset_path, revision))
        return self.ok


FULL_SHIFT = ShiftSamples(
    state=RUN_WITH_ONE_STOP, good=GOOD_CLIMB, reject=REJECT_CLIMB, product=TWO_PRODUCTS
)
FINGERPRINT = Fingerprint(row_count=2880, max_time=t(14))


def pipeline(store: FakeStore, publisher: FakePublisher, fingerprint=FINGERPRINT) -> ShiftPipeline:
    return ShiftPipeline(
        source=FakeSource(FULL_SHIFT, fingerprint),
        master=FakeMaster(),
        store=store,
        publisher=publisher,
    )


@pytest.mark.asyncio
async def test_a_shift_with_no_stored_result_is_computed_at_revision_one():
    store, publisher = FakeStore(), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.revision == 1
    assert outcome.published is True
    assert outcome.input_rows == 2880
    assert outcome.metrics is not None
    assert outcome.metrics.status == "OK"
    assert store.saves == [1]
    assert store.marked == [(11, COMPUTED_AT)]
    assert publisher.sent == [(LINE, 1)]


@pytest.mark.asyncio
async def test_a_changed_fingerprint_is_a_revision():
    stored = StoredResult(result_id=11, revision=1, input_fingerprint="1440:-", published_at=t(14))
    store, publisher = FakeStore(stored), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_REVISED
    assert outcome.revision == 2
    assert outcome.late_data is True
    assert store.saves == [2]
    assert publisher.sent == [(LINE, 2)]


@pytest.mark.asyncio
async def test_an_unchanged_published_shift_does_no_work_at_all():
    stored = StoredResult(
        result_id=11, revision=1, input_fingerprint=FINGERPRINT.as_text(), published_at=t(14)
    )
    store, publisher = FakeStore(stored), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_UNCHANGED
    assert outcome.metrics is None
    assert store.saves == []
    assert publisher.sent == []


@pytest.mark.asyncio
async def test_an_unchanged_unpublished_shift_is_republished_at_the_same_revision():
    stored = StoredResult(
        result_id=11, revision=2, input_fingerprint=FINGERPRINT.as_text(), published_at=None
    )
    store, publisher = FakeStore(stored), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_REPUBLISHED
    assert outcome.revision == 2
    # Nothing written but the publication timestamp: a broker outage is not a correction.
    assert store.saves == []
    assert store.marked == [(11, COMPUTED_AT)]
    assert publisher.sent == [(LINE, 2)]


@pytest.mark.asyncio
async def test_a_reassigned_reason_is_a_revision_even_though_no_sample_moved():
    stored = StoredResult(
        result_id=11, revision=1, input_fingerprint=FINGERPRINT.as_text(), published_at=t(14)
    )
    store, publisher = FakeStore(stored), FakePublisher()
    store.manual = {t(9): ManualReason(reason_code="TOOL_CHANGE", assigned_by="operator1")}
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    # Spec section 13: Loading Time shrinks, Availability changes, revision bumps.
    assert outcome.action == ACTION_REVISED
    assert outcome.revision == 2
    # Not late data: no sample moved, so `uns_oee_late_data_detected_total` must not move.
    assert outcome.late_data is False
    assert store.saves == [2]


@pytest.mark.asyncio
async def test_a_failed_publish_leaves_the_result_unmarked_for_the_next_pass():
    store, publisher = FakeStore(), FakePublisher(ok=False)
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.published is False
    assert store.saves == [1]
    assert store.marked == []


@pytest.mark.asyncio
async def test_a_silent_unit_still_gets_a_row_with_no_input_data():
    store, publisher = FakeStore(), FakePublisher()
    empty = Fingerprint(row_count=0, max_time=None)
    outcome = await pipeline(store, publisher, empty).run_shift(unit(), WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.metrics is not None
    assert outcome.metrics.status == "NO_INPUT_DATA"
    assert store.saves == [1]


@pytest.mark.asyncio
async def test_the_outcome_reports_the_shifts_unclassified_downtime():
    store, publisher = FakeStore(), FakePublisher()
    outcome = await pipeline(store, publisher).run_shift(unit(), WINDOW, COMPUTED_AT)
    assert outcome.unclassified_seconds == 0.0
    assert outcome.counter_resets == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_pipeline.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.pipeline'`.

- [ ] **Step 3: Write the implementation**

Create `12_uns_oee/src/uns_oee/pipeline.py`:

```python
"""Computing one shift for one unit, in the order spec section 5 fixes.

    shift_calendar -> sources -> counters + states -> classifier -> oee_calc -> store -> publisher

`classifier` runs before `oee_calc` because a reason's `is_planned` flag decides whether its
stop leaves Loading Time, so classification is an arithmetic input and not a presentation
detail.

Everything up to `store` is a pure function in this module: `product_segments` and
`shift_inputs` take sample lists and return dataclasses. Only `ShiftPipeline.run_shift`
performs IO, and it reads no clock - `computed_at` is passed in by the scheduler, which is
what lets a whole shift be recomputed deterministically from the same rows.
"""

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from uns_model.oee_tables import UNCLASSIFIED_REASON_CODE
from uns_oee.classifier import ClassifiedStop, ManualReason, classify
from uns_oee.counters import Sample, counter_delta, counter_delta_in
from uns_oee.master_data import ExceptionWindow, MasterDataLoader, UnitMasterData, exception_intervals
from uns_oee.oee_calc import ProductSegment, ShiftInputs, ShiftMetrics, compute
from uns_oee.publisher import ResultPublisher
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import Fingerprint, MetricSource
from uns_oee.states import Interval, StateSample, merge, state_segments, stop_intervals, union_duration_s
from uns_oee.store import ResultStore

LOGGER = logging.getLogger(__name__)

#: A shift computed for the first time. `revision` is 1.
ACTION_COMPUTED = "COMPUTED"

#: A shift recomputed because its input fingerprint moved. `revision` was bumped.
ACTION_REVISED = "REVISED"

#: The stored numbers were already right; only the MQTT message was missing.
ACTION_REPUBLISHED = "REPUBLISHED"

#: Same inputs, already published. Nothing was read past the fingerprint.
ACTION_UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class ShiftSamples:
    """Every series one shift needs, already fetched.

    Separated from the fetching so the arithmetic can be tested against a hand-written series.
    An empty tuple is a legitimate value: a unit with no reject binding has no reject samples,
    and a counter delta over nothing is zero rather than an error.
    """

    state: tuple[StateSample, ...] = ()
    good: tuple[Sample, ...] = ()
    reject: tuple[Sample, ...] = ()
    product: tuple[StateSample, ...] = ()

    @property
    def counter_resets(self) -> int:
        """Resets seen across both counters. Reported, never silently absorbed."""
        return counter_delta(self.good).resets + counter_delta(self.reject).resets


@dataclass(frozen=True, slots=True)
class ShiftOutcome:
    """What `run_shift` did, in the terms the scheduler and the metrics need."""

    unit_id: int
    asset_path: str
    window: ShiftWindow
    action: str
    metrics: ShiftMetrics | None
    revision: int
    published: bool
    input_rows: int = 0
    counter_resets: int = 0
    unclassified_seconds: float = 0.0

    #: Whether the historian's half of the fingerprint moved, as opposed to an operator having
    #: reassigned a reason. Both cause a revision; only this one is late-arriving data.
    late_data: bool = False

    #: Wall time this shift took, stamped by the scheduler from `time.monotonic()`. Left at
    #: zero here: the pipeline reads no clock, and this number is never stored - it exists
    #: only to fill `uns_oee_shift_compute_seconds`.
    compute_seconds: float = 0.0


def as_interval(window: ShiftWindow) -> Interval:
    """The shift window as the half-open interval the arithmetic works in."""
    return Interval(window.start, window.end)


def product_segments(
    unit: UnitMasterData, window: ShiftWindow, samples: ShiftSamples
) -> tuple[ProductSegment, ...]:
    """The shift split by what was running, with each part's counts.

    A product code series is a state series - contiguous runs of one string - so this reuses
    `state_segments` rather than reimplementing coalescing. With no product binding, or no
    product samples to segment by, the whole shift is one unnamed segment; the calculator
    handles that identically, and the counts then equal the whole-window delta.
    """
    whole = as_interval(window)
    if unit.product_ref is None or not samples.product:
        return (_segment(unit, None, (whole,), samples),)

    grouped: dict[str, list[Interval]] = {}
    for segment in state_segments(samples.product, whole):
        grouped.setdefault(segment.state, []).append(segment.interval)
    return tuple(
        _segment(unit, code, tuple(merge(intervals)), samples)
        for code, intervals in grouped.items()
    )


def _segment(
    unit: UnitMasterData,
    product_code: str | None,
    intervals: tuple[Interval, ...],
    samples: ShiftSamples,
) -> ProductSegment:
    """One product's counts, taken per interval rather than pro-rated.

    `counter_delta_in` includes the sample sitting exactly on the interval's end, so the
    increment across a changeover is credited to the outgoing product and the incoming one
    starts from the changeover value. The per-product totals therefore sum to the shift's.
    """
    return ProductSegment(
        product_code=product_code,
        intervals=intervals,
        ideal_cycle_time_s=unit.ideal_cycle_time_for(product_code),
        good_count=sum(counter_delta_in(samples.good, i.start, i.end).total for i in intervals),
        reject_count=sum(counter_delta_in(samples.reject, i.start, i.end).total for i in intervals),
    )


def shift_inputs(
    unit: UnitMasterData,
    window: ShiftWindow,
    samples: ShiftSamples,
    exceptions: Sequence[ExceptionWindow],
    manual: Mapping[datetime, ManualReason],
    *,
    has_input_data: bool = True,
) -> ShiftInputs:
    """Everything the calculator needs, assembled from one shift's rows.

    All three shift-exception kinds subtract from Loading Time (`SHIFT_EXCEPTION_KINDS` is
    PLANNED_DOWN, NON_PRODUCING, HOLIDAY, kept distinct only so a report can name which), so
    no filtering by kind happens here.
    """
    whole = as_interval(window)
    segments = state_segments(samples.state, whole)
    stops = stop_intervals(segments, unit.producing_states)
    return ShiftInputs(
        window=whole,
        exception_intervals=tuple(exception_intervals(exceptions)),
        classified_stops=tuple(classify(stops, unit.resolver, manual=manual)),
        products=product_segments(unit, window, samples),
        has_input_data=has_input_data,
    )


def unclassified_seconds(stops: Sequence[ClassifiedStop]) -> float:
    """Downtime with no reason rule behind it - the master data quality signal.

    Totalled by union, like every other duration in this module, so two stops that somehow
    overlap cannot inflate the number an engineer is being asked to act on.
    """
    return union_duration_s(
        [stop.interval for stop in stops if stop.reason_code == UNCLASSIFIED_REASON_CODE]
    )


def manual_digest(manual: Mapping[datetime, ManualReason]) -> str:
    """A short, stable summary of the operator's attributions for one shift.

    Hashed rather than stored verbatim so `input_fingerprint` stays a short key on a shift
    with fifty reassigned stops. Both the stop instants and the codes go in, sorted, because
    a reason moved from one stop to another is as much a change as a code edited in place.
    """
    if not manual:
        return "-"
    joined = "|".join(
        f"{at.isoformat()}={reason.reason_code}" for at, reason in sorted(manual.items())
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


class ShiftPipeline:
    """One shift for one unit: fetch, compute, store, publish."""

    def __init__(
        self,
        source: MetricSource,
        master: MasterDataLoader,
        store: ResultStore,
        publisher: ResultPublisher,
    ) -> None:
        self._source = source
        self._master = master
        self._store = store
        self._publisher = publisher

    async def run_shift(
        self, unit: UnitMasterData, window: ShiftWindow, computed_at: datetime
    ) -> ShiftOutcome:
        """Compute and publish one closed shift, doing as little as the inputs allow.

        The fingerprint is checked first because it is three indexed reads, which is what makes
        re-checking every open shift on every pass affordable while a full recompute is not.
        Four outcomes follow from it and from whether the stored row reached MQTT.

        The manual reasons are read before the decision, not after it. A reassignment changes
        no sample, so a fingerprint made only of historian rows would call the shift unchanged
        and never write the corrected Availability - which is exactly the case spec section 13
        says must bump the revision.
        """
        counted = await self._source.fingerprint(unit.refs, window.start, window.end)
        manual = await self._store.manual_reasons(unit.unit_id, window)
        fingerprint = counted.with_manual(manual_digest(manual))
        stored = await self._store.existing(unit.unit_id, window.start)
        unchanged = stored is not None and stored.input_fingerprint == fingerprint.as_text()

        if unchanged and stored.published_at is not None:
            return ShiftOutcome(
                unit_id=unit.unit_id,
                asset_path=unit.asset_path,
                window=window,
                action=ACTION_UNCHANGED,
                metrics=None,
                revision=stored.revision,
                published=True,
                input_rows=fingerprint.row_count,
            )

        samples = await self._fetch(unit, window)
        exceptions = await self._master.exception_windows(unit, as_interval(window))
        inputs = shift_inputs(
            unit,
            window,
            samples,
            exceptions,
            manual,
            has_input_data=not fingerprint.is_empty,
        )
        metrics = compute(inputs)

        if unchanged:
            # Rule 1: same inputs, same output. So the numbers on record are these numbers,
            # and publishing them under the stored revision is exact. Writing a new revision
            # here would make `revision` count broker outages instead of corrections.
            action = ACTION_REPUBLISHED
            result_id, revision = stored.result_id, stored.revision
        else:
            saved = await self._store.save(
                unit.unit_id,
                window,
                metrics,
                inputs.classified_stops,
                fingerprint,
                computed_at,
            )
            result_id, revision = saved.result_id, saved.revision
            action = ACTION_COMPUTED if revision == 1 else ACTION_REVISED

        # A revision has two causes and the operator needs to tell them apart. Comparing only
        # the historian half isolates late-arriving data from a reason reassignment.
        late_data = stored is not None and Fingerprint.source_part(
            stored.input_fingerprint
        ) != Fingerprint.source_part(fingerprint.as_text())

        published = await self._publisher.publish(unit.asset_path, window, metrics, revision)
        if published:
            await self._store.mark_published(result_id, computed_at)

        LOGGER.info(
            "OEE %s %s shift %s: %s revision %d, status %s",
            unit.asset_path,
            window.label,
            window.start.isoformat(),
            action,
            revision,
            metrics.status,
        )
        return ShiftOutcome(
            unit_id=unit.unit_id,
            asset_path=unit.asset_path,
            window=window,
            action=action,
            metrics=metrics,
            revision=revision,
            published=published,
            input_rows=fingerprint.row_count,
            counter_resets=samples.counter_resets,
            unclassified_seconds=unclassified_seconds(inputs.classified_stops),
            late_data=late_data,
        )

    async def _fetch(self, unit: UnitMasterData, window: ShiftWindow) -> ShiftSamples:
        """Every series this unit binds, for this window.

        `include_prior` is left at its default for all four: the state at the boundary decides
        whether the shift opens in a stop, and a counter's pre-boundary value is what makes the
        first in-shift delta correct rather than a jump from zero.
        """
        state = await self._source.text_samples(unit.state_ref, window.start, window.end)
        good = await self._source.numeric_samples(unit.good_ref, window.start, window.end)
        reject = (
            await self._source.numeric_samples(unit.reject_ref, window.start, window.end)
            if unit.reject_ref is not None
            else []
        )
        product = (
            await self._source.text_samples(unit.product_ref, window.start, window.end)
            if unit.product_ref is not None
            else []
        )
        return ShiftSamples(
            state=tuple(state), good=tuple(good), reject=tuple(reject), product=tuple(product)
        )


__all__ = [
    "ACTION_COMPUTED",
    "ACTION_REPUBLISHED",
    "ACTION_REVISED",
    "ACTION_UNCHANGED",
    "ShiftOutcome",
    "ShiftPipeline",
    "ShiftSamples",
    "as_interval",
    "manual_digest",
    "product_segments",
    "shift_inputs",
    "unclassified_seconds",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_pipeline.py -v -n 0`
Expected: PASS (25 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/pipeline.py 12_uns_oee/test/test_pipeline.py
git commit -m "feat(oee): compute, store and publish one shift end to end"
```

---

### Task 13: Deciding which shifts are due

**Files:**
- Create: `12_uns_oee/src/uns_oee/scheduler.py`
- Create: `12_uns_oee/test/test_scheduler.py`

**Interfaces:**
- Consumes: `uns_model.engine.Database`; `uns_model.oee_tables.RecomputeRequest` (Task 2); `OeeConfig` (Task 1); `ShiftWindow`, `shift_windows` (Task 4); `MetricSource` (Task 8); `MasterDataLoader`, `UnitMasterData` (Task 9); `ShiftOutcome`, `ShiftPipeline` (Task 12).
- Produces: `REQUEST_CLAIM_LIMIT = 200`; `SKIP_NO_HISTORY = "NO_HISTORY"`, `SKIP_PREDATES_DATA = "PREDATES_DATA"`; `ClaimedRange(request_id: int, unit_id: int | None, start: datetime, end: datetime)`; `BackfillPlan(windows, skipped_no_history, skipped_predates_data)`; `BackfillTally(unit_id, asset_path, computed, skipped_no_history, skipped_predates_data)`; `PassSummary(outcomes, units, windows, failures, backfilled, backfill)`; pure functions `clamp_backfill_days(configured: int, retention: float | None) -> int`, `recheck_windows(unit, now, *, settle_minutes, late_window_hours) -> list[ShiftWindow]`, `backfill_windows(unit, now, *, settle_minutes, backfill_days, earliest_input_at) -> BackfillPlan`, `request_windows(unit, ranges, now, *, settle_minutes) -> list[ShiftWindow]`, `ranges_for(unit_id, claimed) -> tuple[tuple[datetime, datetime], ...]`, `ordered_unique(windows) -> list[ShiftWindow]`; `async retention_days(database, table) -> float | None`; `async claim_requests(database, at, *, limit=REQUEST_CLAIM_LIMIT) -> list[ClaimedRange]`; `async complete_requests(database, request_ids, at, *, error=None) -> None`; `ShiftScheduler(config, database, source, master, pipeline, *, claim=..., retention=..., complete=...)` with `async run_pass(now: datetime) -> PassSummary`.

Spec §9 gives the engine two phases and this module is both of them. A shift becomes due at `shift_end + settle_minutes` — the settle window is what stops a shift being computed from a historian that is still catching up. After that it is re-checked on every pass until `shift_end + late_window_hours`, and then it is left alone. §9.1 adds a third source of work, the bounded backfill, and a fourth arrives through `oee.recompute_request` when an operator reassigns a reason.

**Why the late window closes at all.** Re-checking a shift costs two indexed queries (the fingerprint and the stored row), so re-checking everything forever would grow linearly with the plant's history and eventually consume a whole scan interval doing nothing. The late window is the statement that a machine does not amend last month's data on its own. A human still can, and that path is the recompute request, which has no window.

**Why `backfill_days` is clamped.** `uns_metrics` carries a one-year retention policy (`04_uns_historian/sql_scripts/04_setup_metrics_hypertable.sql:67`). Asking for a 400-day backfill would enumerate 1200 shifts whose rows were dropped months ago and write 1200 `NO_INPUT_DATA` results that look like an outage. The clamp reads the policy from `timescaledb_information.jobs` and logs both numbers once, so the operator learns the request was reduced rather than discovering it in the data.

**Why `now` is a parameter.** `run_pass(now)` is the only place the pass's timestamp enters, and `main.py` is the only caller that reads a clock. Everything below — the window enumeration, the fingerprint comparison, `computed_at` on the stored row — derives from that one value, which is what makes a pass replayable.

**Why two coroutine functions are injectable.** `claim_requests` and `retention_days` are the scheduler's only SQL, and they are three statements against tables the store does not own. Passing them in as defaults keeps `ShiftScheduler`'s decision logic testable without a database, and keeps the SQL out of `ResultStore`, whose job is one shift's results.

- [ ] **Step 1: Write the failing test**

Create `12_uns_oee/test/test_scheduler.py`:

```python
"""Tests for uns_oee.scheduler - which shifts a pass computes, and why.

The window arithmetic is pure and gets real schedules: the bugs that matter are a shift
computed before the historian caught up, a shift re-checked forever, and a backfill that
invents thirty days of NO_INPUT_DATA out of dropped chunks. The pass itself gets fakes,
because what matters there is that one broken unit does not stop the plant's other lines.
"""

from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from uns_oee.oee_config import OeeConfig
from uns_oee.pipeline import ACTION_COMPUTED, ShiftOutcome
from uns_oee.scheduler import (
    ClaimedRange,
    ShiftScheduler,
    backfill_windows,
    claim_requests,
    clamp_backfill_days,
    ordered_unique,
    ranges_for,
    recheck_windows,
    request_windows,
    retention_days,
)
from uns_oee.shift_calendar import ShiftSchedule, ShiftSlot, ShiftWindow

NOW = datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc)
SETTLE = 15
LATE = 48

#: One eight-hour morning shift every day, in UTC so the arithmetic in this file is readable.
#: Task 4's tests are where the timezone and DST behaviour is pinned.
DAILY = ShiftSchedule(
    name="daily mornings",
    timezone="UTC",
    slots=tuple(ShiftSlot(day, time(6, 0), 480, "A") for day in range(7)),
)


class FakeUnit:
    """Only the three attributes the scheduler reads off a UnitMasterData."""

    def __init__(self, unit_id: int = 1, schedule: ShiftSchedule = DAILY) -> None:
        self.unit_id = unit_id
        self.asset_path = f"CovestroAG/Dormagen/Production/Line{unit_id}"
        self.schedule = schedule
        self.refs = ()


def days(windows) -> list[int]:
    return [window.start.day for window in windows]


# --- the window arithmetic -----------------------------------------------------------


def test_a_settled_shift_inside_the_late_window_is_rechecked():
    windows = recheck_windows(FakeUnit(), NOW, settle_minutes=SETTLE, late_window_hours=LATE)
    # Sept 9 ended an hour ago, Sept 8 twenty-five hours ago. Sept 7 ended 49h ago.
    assert days(windows) == [8, 9]


def test_a_shift_that_has_not_settled_is_not_rechecked():
    just_ended = datetime(2026, 9, 9, 14, 10, tzinfo=timezone.utc)
    windows = recheck_windows(FakeUnit(), just_ended, settle_minutes=SETTLE, late_window_hours=LATE)
    assert 9 not in days(windows)


def test_a_shift_older_than_the_late_window_is_not_rechecked():
    windows = recheck_windows(FakeUnit(), NOW, settle_minutes=SETTLE, late_window_hours=LATE)
    assert 7 not in days(windows)
    assert 6 not in days(windows)


def test_the_lookback_covers_a_shift_longer_than_a_day():
    marathon = ShiftSchedule(
        name="weekly",
        timezone="UTC",
        slots=(ShiftSlot(0, time(6, 0), 60 * 30, "LONG"),),
    )
    # Started Mon Sept 7 06:00, ended Tue Sept 8 12:00 - 27h before NOW, so inside the late
    # window. A fixed one-day lookback would have missed its start.
    windows = recheck_windows(
        FakeUnit(schedule=marathon), NOW, settle_minutes=SETTLE, late_window_hours=LATE
    )
    assert days(windows) == [7]


def test_backfill_enumerates_from_now_minus_backfill_days_oldest_first():
    plan = backfill_windows(
        FakeUnit(),
        NOW,
        settle_minutes=SETTLE,
        backfill_days=3,
        earliest_input_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert days(plan.windows) == [7, 8, 9]
    assert plan.skipped_predates_data == 0


def test_a_backfill_shift_ending_before_the_first_input_row_is_skipped():
    plan = backfill_windows(
        FakeUnit(),
        NOW,
        settle_minutes=SETTLE,
        backfill_days=30,
        earliest_input_at=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
    )
    # Sept 7's shift ends at 14:00, after the first row, so it is computed. Everything before
    # it predates the data entirely and is skipped rather than written as NO_INPUT_DATA.
    assert days(plan.windows) == [7, 8, 9]
    # Aug 11 through Sept 6 inclusive: counted, so the choice is visible in Prometheus.
    assert plan.skipped_predates_data == 27


def test_a_unit_that_never_published_anything_gets_no_backfill():
    plan = backfill_windows(
        FakeUnit(), NOW, settle_minutes=SETTLE, backfill_days=30, earliest_input_at=None
    )
    assert plan.windows == ()
    assert plan.skipped_no_history == 30
    assert plan.skipped_predates_data == 0


def test_a_recompute_range_becomes_the_shift_windows_inside_it():
    ranges = ((datetime(2026, 9, 7, tzinfo=timezone.utc), datetime(2026, 9, 9, tzinfo=timezone.utc)),)
    windows = request_windows(FakeUnit(), ranges, NOW, settle_minutes=SETTLE)
    # Requested ranges ignore the late window entirely: a human asked.
    assert days(windows) == [7, 8]


def test_an_unsettled_shift_inside_a_requested_range_is_not_returned():
    ranges = ((datetime(2026, 9, 9, tzinfo=timezone.utc), datetime(2026, 9, 10, tzinfo=timezone.utc)),)
    just_ended = datetime(2026, 9, 9, 14, 10, tzinfo=timezone.utc)
    assert request_windows(FakeUnit(), ranges, just_ended, settle_minutes=SETTLE) == []


def test_a_range_with_no_unit_applies_to_every_unit():
    claimed = [ClaimedRange(request_id=1, unit_id=None, start=NOW, end=NOW + timedelta(hours=1))]
    assert len(ranges_for(1, claimed)) == 1
    assert len(ranges_for(99, claimed)) == 1


def test_a_range_with_a_unit_applies_only_to_that_unit():
    claimed = [ClaimedRange(request_id=1, unit_id=1, start=NOW, end=NOW + timedelta(hours=1))]
    assert len(ranges_for(1, claimed)) == 1
    assert ranges_for(2, claimed) == ()


def test_windows_from_two_sources_collapse_to_one_ordered_list():
    first = ShiftWindow(start=NOW - timedelta(days=1), end=NOW - timedelta(hours=16), label="A")
    second = ShiftWindow(start=NOW - timedelta(hours=9), end=NOW - timedelta(hours=1), label="A")
    assert ordered_unique([second, first, second]) == [first, second]


def test_backfill_days_is_clamped_to_the_retention_policy():
    assert clamp_backfill_days(400, 365.25) == 365


def test_a_backfill_inside_retention_is_left_alone():
    assert clamp_backfill_days(30, 365.25) == 30


def test_no_retention_policy_leaves_the_backfill_alone():
    assert clamp_backfill_days(400, None) == 400


# --- the three statements ------------------------------------------------------------


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, results):
        self._results = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, parameters=None):
        # Compiled against PostgreSQL because SKIP LOCKED does not exist in the default
        # dialect, and it is the whole point of the claim query.
        compiled = statement.compile(dialect=postgresql.dialect())
        self.calls.append((str(compiled).lower(), dict(parameters or {})))
        return self._results.pop(0) if self._results else FakeResult([])


class FakeDatabase:
    """Stands in for `uns_model.engine.Database`; only `begin()` is used here."""

    def __init__(self, *results):
        self.connection = FakeConnection(results)

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_the_retention_query_asks_timescale_for_the_metrics_table():
    database = FakeDatabase(FakeResult([(365.25,)]))
    assert await retention_days(database, "uns_metrics") == 365.25
    sql, params = database.connection.calls[0]
    assert "timescaledb_information.jobs" in sql
    assert "policy_retention" in sql
    assert params == {"table": "uns_metrics"}


@pytest.mark.asyncio
async def test_no_retention_row_reads_as_no_policy():
    assert await retention_days(FakeDatabase(FakeResult([])), "uns_metrics") is None
    assert await retention_days(FakeDatabase(FakeResult([(None,)])), "uns_metrics") is None


@pytest.mark.asyncio
async def test_claiming_skips_rows_another_worker_holds():
    rows = [(7, 1, NOW - timedelta(days=1), NOW)]
    database = FakeDatabase(FakeResult(rows))
    claimed = await claim_requests(database, NOW)

    assert claimed == [ClaimedRange(request_id=7, unit_id=1, start=NOW - timedelta(days=1), end=NOW)]
    sql, _ = database.connection.calls[0]
    # SKIP LOCKED is what makes a second engine instance a no-op instead of a duplicate.
    assert "skip locked" in sql
    assert "claimed_at is null" in sql


# --- one pass ------------------------------------------------------------------------


class FakeSource:
    def __init__(self, earliest=None):
        self.earliest = earliest
        self.asked = 0

    async def earliest_sample_at(self, refs):
        self.asked += 1
        return self.earliest


class FakeMaster:
    def __init__(self, units):
        self.units = list(units)

    async def active_units(self):
        return list(self.units)


class FakePipeline:
    def __init__(self, *, failing_units=()):
        self.failing_units = set(failing_units)
        self.calls: list[tuple[int, datetime, datetime]] = []

    async def run_shift(self, unit, window, computed_at):
        if unit.unit_id in self.failing_units:
            raise RuntimeError("historian went away")
        self.calls.append((unit.unit_id, window.start, computed_at))
        return ShiftOutcome(
            unit_id=unit.unit_id,
            asset_path=unit.asset_path,
            window=window,
            action=ACTION_COMPUTED,
            metrics=None,
            revision=1,
            published=True,
        )


def scheduler(master, pipeline, source=None, *, claimed=(), backfill_days=30):
    config = OeeConfig(
        settle_minutes=SETTLE, late_window_hours=LATE, backfill_days=backfill_days
    )
    completed: list[tuple[tuple[int, ...], datetime]] = []

    async def fake_claim(database, at, *, limit=200):
        return list(claimed)

    async def fake_retention(database, table):
        return None

    async def fake_complete(database, request_ids, at, *, error=None):
        completed.append((tuple(request_ids), at))

    instance = ShiftScheduler(
        config=config,
        database=FakeDatabase(),
        source=source or FakeSource(),
        master=master,
        pipeline=pipeline,
        claim=fake_claim,
        retention=fake_retention,
        complete=fake_complete,
    )
    instance.completed = completed
    return instance


@pytest.mark.asyncio
async def test_a_pass_computes_every_settled_window_for_every_active_unit():
    pipeline = FakePipeline()
    master = FakeMaster([FakeUnit(1), FakeUnit(2)])
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    summary = await scheduler(master, pipeline, source).run_pass(NOW)

    assert summary.units == 2
    assert summary.failures == 0
    assert summary.backfilled is True
    # Sept 8 and Sept 9 for each unit: the backfill's windows are the same two, deduped.
    assert [(unit_id, start.day) for unit_id, start, _ in pipeline.calls] == [
        (1, 8), (1, 9), (2, 8), (2, 9),
    ]
    assert len(summary.outcomes) == 4


@pytest.mark.asyncio
async def test_the_backfill_only_runs_on_the_first_pass():
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    instance = scheduler(FakeMaster([FakeUnit(1)]), FakePipeline(), source)

    await instance.run_pass(NOW)
    assert source.asked == 1
    second = await instance.run_pass(NOW + timedelta(minutes=5))
    assert source.asked == 1
    assert second.backfilled is False


@pytest.mark.asyncio
async def test_a_failing_unit_does_not_stop_the_pass():
    pipeline = FakePipeline(failing_units={1})
    master = FakeMaster([FakeUnit(1), FakeUnit(2)])
    summary = await scheduler(master, pipeline).run_pass(NOW)

    assert summary.failures == 2  # unit 1's two windows
    assert {unit_id for unit_id, _, _ in pipeline.calls} == {2}


@pytest.mark.asyncio
async def test_a_pass_with_a_failure_retries_the_backfill():
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    instance = scheduler(FakeMaster([FakeUnit(1)]), FakePipeline(failing_units={1}), source)

    await instance.run_pass(NOW)
    await instance.run_pass(NOW + timedelta(minutes=5))
    # A backfill that half failed is not a backfill. Two enumerations, not one.
    assert source.asked == 2


@pytest.mark.asyncio
async def test_a_claimed_request_is_computed_and_completed():
    pipeline = FakePipeline()
    request = ClaimedRange(
        request_id=7,
        unit_id=1,
        start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    instance = scheduler(FakeMaster([FakeUnit(1)]), pipeline, claimed=[request])
    await instance.run_pass(NOW)

    computed = sorted({start.day for _, start, _ in pipeline.calls})
    # Sept 1 and 2 from the request, plus the two the late window already covered.
    assert computed == [1, 2, 8, 9]
    assert instance.completed == [((7,), NOW)]


@pytest.mark.asyncio
async def test_the_pipeline_is_given_the_passs_timestamp():
    pipeline = FakePipeline()
    await scheduler(FakeMaster([FakeUnit(1)]), pipeline).run_pass(NOW)
    assert {computed_at for _, _, computed_at in pipeline.calls} == {NOW}


@pytest.mark.asyncio
async def test_every_outcome_is_stamped_with_how_long_it_took():
    summary = await scheduler(FakeMaster([FakeUnit(1)]), FakePipeline()).run_pass(NOW)
    # Monotonic, so never negative even if the host clock steps mid-pass.
    assert all(outcome.compute_seconds >= 0.0 for outcome in summary.outcomes)


@pytest.mark.asyncio
async def test_the_pass_reports_what_the_backfill_declined():
    source = FakeSource(earliest=datetime(2026, 9, 8, tzinfo=timezone.utc))
    summary = await scheduler(FakeMaster([FakeUnit(1)]), FakePipeline(), source).run_pass(NOW)
    tally = summary.backfill[0]
    assert tally.asset_path.endswith("Line1")
    assert (tally.computed, tally.skipped_predates_data, tally.skipped_no_history) == (2, 28, 0)


@pytest.mark.asyncio
async def test_a_later_pass_reports_no_backfill_at_all():
    instance = scheduler(FakeMaster([FakeUnit(1)]), FakePipeline())
    await instance.run_pass(NOW)
    assert (await instance.run_pass(NOW + timedelta(minutes=5))).backfill == ()


@pytest.mark.asyncio
async def test_a_silent_unit_still_gets_its_steady_state_windows():
    pipeline = FakePipeline()
    # earliest_sample_at is None, so the unit has never published. The backfill skips it, but
    # the late window does not: spec section 13 wants one NO_INPUT_DATA row per silent shift.
    await scheduler(FakeMaster([FakeUnit(1)]), pipeline, FakeSource(earliest=None)).run_pass(NOW)
    assert sorted(start.day for _, start, _ in pipeline.calls) == [8, 9]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_scheduler.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.scheduler'`.

- [ ] **Step 3: Write the implementation**

Create `12_uns_oee/src/uns_oee/scheduler.py`:

```python
"""Which shifts a pass computes (spec sections 9 and 9.1).

Four sources of work, in one ordered list per unit:

  recheck   every settled shift still inside `late_window_hours`
  request   every settled shift inside a claimed `oee.recompute_request` range
  backfill  on the first pass only, back to `backfill_days` clamped to retention
  (nothing)  a shift older than the late window with no request against it

`run_pass(now)` takes the pass's timestamp as an argument and passes it down as `computed_at`.
Nothing in this module or below it reads a clock, which is what makes a pass replayable and
`recompute_cli` able to reproduce a historical result exactly.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import select, text, update

from uns_model.engine import Database
from uns_model.oee_tables import RecomputeRequest
from uns_oee.master_data import MasterDataLoader, UnitMasterData
from uns_oee.oee_config import OeeConfig
from uns_oee.pipeline import ShiftOutcome, ShiftPipeline
from uns_oee.shift_calendar import ShiftWindow, shift_windows
from uns_oee.sources import MetricSource

LOGGER = logging.getLogger(__name__)

#: Requests claimed per pass. A ceiling rather than a page size: a reason reassignment queues
#: one row, so reaching 200 means something is generating requests in a loop, and draining
#: them all in one pass would starve the shifts that are actually due.
REQUEST_CLAIM_LIMIT = 200

#: Label values for `uns_oee_backfill_shifts_skipped_total{unit,reason}`. Two distinct facts:
#: a unit that has never published anything, and a shift older than the data it would need.
SKIP_NO_HISTORY = "NO_HISTORY"
SKIP_PREDATES_DATA = "PREDATES_DATA"

#: Postgres parses the policy's interval and converts it to days; see `retention_days`.
_RETENTION_SQL = """
SELECT EXTRACT(EPOCH FROM (config->>'drop_after')::interval) / 86400.0
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_retention' AND hypertable_name = :table
"""


@dataclass(frozen=True, slots=True)
class ClaimedRange:
    """One recompute request this instance has taken. `unit_id` None means every unit."""

    request_id: int
    unit_id: int | None
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    """The backfill's windows plus what it declined, so the skips can be counted.

    A skip is reported rather than silently dropped: spec section 13 requires
    `_backfill_shifts_skipped_total`, because "no result for last March" and "we chose not to
    compute last March" are different answers to the same operator question.
    """

    windows: tuple[ShiftWindow, ...] = ()
    skipped_no_history: int = 0
    skipped_predates_data: int = 0


@dataclass(frozen=True, slots=True)
class BackfillTally:
    """One unit's backfill, as the metrics module needs it labelled."""

    unit_id: int
    asset_path: str
    computed: int
    skipped_no_history: int
    skipped_predates_data: int


@dataclass(frozen=True, slots=True)
class PassSummary:
    """What one pass did. Consumed by prometheus_metrics, which owns no state of its own."""

    outcomes: tuple[ShiftOutcome, ...] = ()
    units: int = 0
    windows: int = 0
    failures: int = 0
    backfilled: bool = False
    backfill: tuple[BackfillTally, ...] = ()


def clamp_backfill_days(configured: int, retention: float | None) -> int:
    """`backfill_days`, reduced to what the retention policy can still answer.

    Without the clamp, a 400-day request against a one-year hypertable would write months of
    NO_INPUT_DATA results for chunks that were dropped on schedule - an outage in the data
    that never happened in the plant.
    """
    if retention is None:
        return configured
    return min(configured, int(retention))


def _lookback(unit: UnitMasterData, late_window_hours: int) -> timedelta:
    """How far back to enumerate so no shift inside the late window is missed.

    `shift_windows` bounds by start, so the range has to open one full shift earlier than the
    late window itself. Derived from the schedule's longest slot rather than a fixed margin,
    because a 30-hour campaign shift is a legitimate roster.
    """
    longest = max(
        (timedelta(minutes=slot.duration_minutes) for slot in unit.schedule.slots),
        default=timedelta(),
    )
    return timedelta(hours=late_window_hours) + longest


def recheck_windows(
    unit: UnitMasterData, now: datetime, *, settle_minutes: int, late_window_hours: int
) -> list[ShiftWindow]:
    """Settled shifts still inside their late window - the steady-state work of a pass.

    No earliest-input guard here, deliberately. A unit that has gone silent must still get one
    row per shift with `status = 'NO_INPUT_DATA'` (spec section 13), because that row is the
    only evidence in the system that a line stopped reporting.
    """
    limit = timedelta(hours=late_window_hours)
    return [
        window
        for window in shift_windows(unit.schedule, now - _lookback(unit, late_window_hours), now)
        if window.is_closed_at(now, settle_minutes) and now - window.end <= limit
    ]


def backfill_windows(
    unit: UnitMasterData,
    now: datetime,
    *,
    settle_minutes: int,
    backfill_days: int,
    earliest_input_at: datetime | None,
) -> BackfillPlan:
    """Settled shifts back to `now - backfill_days` that the unit has data for.

    A shift ending at or before the unit's first sample is skipped entirely rather than stored
    as NO_INPUT_DATA: the line was not silent then, it did not exist in this system yet, and a
    Grafana panel cannot tell those two apart. A unit with no samples at all gets nothing, and
    both kinds of skip are counted so the decision is visible.
    """
    settled = [
        window
        for window in shift_windows(unit.schedule, now - timedelta(days=backfill_days), now)
        if window.is_closed_at(now, settle_minutes)
    ]
    if earliest_input_at is None:
        return BackfillPlan(skipped_no_history=len(settled))
    kept = tuple(window for window in settled if window.end > earliest_input_at)
    return BackfillPlan(windows=kept, skipped_predates_data=len(settled) - len(kept))


def request_windows(
    unit: UnitMasterData,
    ranges: Sequence[tuple[datetime, datetime]],
    now: datetime,
    *,
    settle_minutes: int,
) -> list[ShiftWindow]:
    """Settled shifts inside the requested ranges, with no late window applied.

    The late window exists because a machine does not amend last month's data by itself. A
    human reassigning a reason code is exactly the case it was never meant to block.
    """
    windows: list[ShiftWindow] = []
    for start, end in ranges:
        windows.extend(
            window
            for window in shift_windows(unit.schedule, start, end)
            if window.is_closed_at(now, settle_minutes)
        )
    return windows


def ranges_for(
    unit_id: int, claimed: Sequence[ClaimedRange]
) -> tuple[tuple[datetime, datetime], ...]:
    """The claimed ranges that apply to one unit, including the unit-less ones."""
    return tuple(
        (item.start, item.end) for item in claimed if item.unit_id in (None, unit_id)
    )


def ordered_unique(windows: Sequence[ShiftWindow]) -> list[ShiftWindow]:
    """One window per shift start, earliest first.

    Keyed on `start` because that is what `uq_shift_result_unit_start` is keyed on: two
    sources offering the same shift are the same row, and computing it twice in one pass would
    write a revision whose only change is the revision number.
    """
    seen: set[datetime] = set()
    unique: list[ShiftWindow] = []
    for window in sorted(windows, key=lambda item: item.start):
        if window.start in seen:
            continue
        seen.add(window.start)
        unique.append(window)
    return unique


async def retention_days(database: Database, table: str) -> float | None:
    """The hypertable's retention policy in days, or None if it has none.

    The interval is parsed by Postgres rather than by this module: `1 year` and `365 days` are
    both legitimate policy values and only the server knows what the first one means.
    """
    async with database.begin() as connection:
        row = (await connection.execute(text(_RETENTION_SQL), {"table": table})).first()
    if row is None or row[0] is None:
        return None
    return float(row[0])


async def claim_requests(
    database: Database, at: datetime, *, limit: int = REQUEST_CLAIM_LIMIT
) -> list[ClaimedRange]:
    """Take up to `limit` unclaimed requests, stamping `claimed_at`.

    `FOR UPDATE SKIP LOCKED` inside the subquery is what makes a second engine instance a
    no-op rather than a duplicate writer: it takes the rows the first instance did not, and
    `claimed_at` keeps them taken across restarts.
    """
    pending = (
        select(RecomputeRequest.id)
        .where(RecomputeRequest.claimed_at.is_(None))
        .order_by(RecomputeRequest.requested_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    statement = (
        update(RecomputeRequest)
        .where(RecomputeRequest.id.in_(pending))
        .values(claimed_at=at)
        .returning(
            RecomputeRequest.id,
            RecomputeRequest.oee_unit_id,
            RecomputeRequest.range_start,
            RecomputeRequest.range_end,
        )
    )
    async with database.begin() as connection:
        rows = (await connection.execute(statement)).fetchall()
    return [
        ClaimedRange(request_id=row[0], unit_id=row[1], start=row[2], end=row[3]) for row in rows
    ]


async def complete_requests(
    database: Database,
    request_ids: Sequence[int],
    at: datetime,
    *,
    error: str | None = None,
) -> None:
    """Close the claimed requests. Coarse by design: one verdict for the whole pass.

    A request names a range, and a range spans shifts across units, so attributing one
    window's failure to one request would be a guess. `error` records that the pass which
    drained these requests was not clean, and the operator re-runs it from `recompute_cli`.
    """
    if not request_ids:
        return
    statement = (
        update(RecomputeRequest)
        .where(RecomputeRequest.id.in_(list(request_ids)))
        .values(completed_at=at, error=error)
    )
    async with database.begin() as connection:
        await connection.execute(statement)


class ShiftScheduler:
    """One pass over every active unit, computing what is due.

    `claim`, `retention` and `complete` are injected with real defaults. They are this
    module's only SQL, against tables `ResultStore` does not own, and keeping them behind
    parameters is what lets the scheduling decisions be tested without a database.
    """

    def __init__(
        self,
        config: OeeConfig,
        database: Database,
        source: MetricSource,
        master: MasterDataLoader,
        pipeline: ShiftPipeline,
        *,
        claim: Callable = claim_requests,
        retention: Callable = retention_days,
        complete: Callable = complete_requests,
    ) -> None:
        self._config = config
        self._database = database
        self._source = source
        self._master = master
        self._pipeline = pipeline
        self._claim = claim
        self._retention = retention
        self._complete = complete
        self._backfill_days: int | None = None
        self._backfilled = False

    async def run_pass(self, now: datetime) -> PassSummary:
        """Compute every due shift for every active unit. Never raises for one unit's sake.

        A failure is counted and logged, and the pass continues: one line's historian gap must
        not cost the other lines their shift reports. The failure count is what makes the
        outage visible on `uns_oee_compute_failures_total`.
        """
        await self._bound_backfill()
        units = await self._master.active_units()
        claimed = await self._claim(self._database, now, limit=REQUEST_CLAIM_LIMIT)
        backfilling = not self._backfilled

        outcomes: list[ShiftOutcome] = []
        tallies: list[BackfillTally] = []
        windows_seen = 0
        failures = 0
        for unit in units:
            windows, tally = await self._windows_for(unit, now, claimed, backfilling)
            if tally is not None:
                tallies.append(tally)
            windows_seen += len(windows)
            for window in windows:
                try:
                    # Monotonic, so an NTP step during a pass cannot produce a negative
                    # histogram sample. Never stored - `computed_at` is the recorded time.
                    started = time.monotonic()
                    outcome = await self._pipeline.run_shift(unit, window, now)
                    outcomes.append(
                        replace(outcome, compute_seconds=time.monotonic() - started)
                    )
                except Exception:
                    failures += 1
                    LOGGER.exception(
                        "OEE compute failed for %s shift starting %s",
                        unit.asset_path,
                        window.start.isoformat(),
                    )

        if claimed:
            summary = None if failures == 0 else f"{failures} window(s) failed in this pass"
            await self._complete(
                self._database, [item.request_id for item in claimed], now, error=summary
            )

        # A backfill that half failed is not a backfill, so the next pass enumerates it again.
        # The re-enumeration is cheap - an unchanged shift costs two indexed queries - and the
        # alternative is losing history silently to a transient outage.
        if backfilling and failures == 0:
            self._backfilled = True

        return PassSummary(
            outcomes=tuple(outcomes),
            units=len(units),
            windows=windows_seen,
            failures=failures,
            backfilled=backfilling,
            backfill=tuple(tallies),
        )

    async def _bound_backfill(self) -> None:
        """Resolve `backfill_days` against the retention policy, once, and say so."""
        if self._backfill_days is not None:
            return
        retention = await self._retention(self._database, self._config.metrics_table)
        self._backfill_days = clamp_backfill_days(self._config.backfill_days, retention)
        if self._backfill_days != self._config.backfill_days:
            LOGGER.warning(
                "OEE backfill of %d days reduced to %d days: %s retains %s days",
                self._config.backfill_days,
                self._backfill_days,
                self._config.metrics_table,
                f"{retention:.0f}" if retention is not None else "unknown",
            )
        else:
            LOGGER.info(
                "OEE backfill bounded to %d days; %s retains %s days",
                self._backfill_days,
                self._config.metrics_table,
                f"{retention:.0f}" if retention is not None else "no policy",
            )

    async def _windows_for(
        self,
        unit: UnitMasterData,
        now: datetime,
        claimed: Sequence[ClaimedRange],
        backfilling: bool,
    ) -> tuple[list[ShiftWindow], BackfillTally | None]:
        """This unit's due shifts from all sources, deduped and ordered oldest first.

        Oldest first because a revision supersedes the row before it: computing September 9
        before September 1 would still be correct, but the revision history would read
        backwards to anyone auditing it.

        The tally is None on every pass but the first: there is no backfill to report.
        """
        windows = recheck_windows(
            unit,
            now,
            settle_minutes=self._config.settle_minutes,
            late_window_hours=self._config.late_window_hours,
        )
        windows.extend(
            request_windows(
                unit,
                ranges_for(unit.unit_id, claimed),
                now,
                settle_minutes=self._config.settle_minutes,
            )
        )
        if not backfilling:
            return ordered_unique(windows), None

        earliest = await self._source.earliest_sample_at(unit.refs)
        plan = backfill_windows(
            unit,
            now,
            settle_minutes=self._config.settle_minutes,
            backfill_days=self._backfill_days or 0,
            earliest_input_at=earliest,
        )
        windows.extend(plan.windows)
        tally = BackfillTally(
            unit_id=unit.unit_id,
            asset_path=unit.asset_path,
            computed=len(plan.windows),
            skipped_no_history=plan.skipped_no_history,
            skipped_predates_data=plan.skipped_predates_data,
        )
        return ordered_unique(windows), tally


__all__ = [
    "REQUEST_CLAIM_LIMIT",
    "SKIP_NO_HISTORY",
    "SKIP_PREDATES_DATA",
    "BackfillPlan",
    "BackfillTally",
    "ClaimedRange",
    "PassSummary",
    "ShiftScheduler",
    "backfill_windows",
    "claim_requests",
    "clamp_backfill_days",
    "complete_requests",
    "ordered_unique",
    "ranges_for",
    "recheck_windows",
    "request_windows",
    "retention_days",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_scheduler.py -v -n 0`
Expected: PASS (28 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/scheduler.py 12_uns_oee/test/test_scheduler.py
git commit -m "feat(oee): schedule settled shifts, late re-checks and a bounded backfill"
```

---

### Task 14: Metrics on port 9095

**Files:**
- Create: `12_uns_oee/src/uns_oee/prometheus_metrics.py`
- Create: `12_uns_oee/test/test_prometheus_metrics.py`

**Interfaces:**
- Consumes: `uns_model.engine.Database`; `uns_model.oee_tables.{RecomputeRequest, ShiftResult}` (Task 2); `ACTION_REVISED`, `ACTION_UNCHANGED`, `ShiftOutcome` (Task 12); `PassSummary`, `SKIP_NO_HISTORY`, `SKIP_PREDATES_DATA` (Task 13).
- Produces: `METRIC_PREFIX = "uns_oee"`; `COMPUTE_BUCKETS`; `Readings(recompute_queue_depth, unpublished_results, database_up)`; `async read_gauges(database) -> Readings`; `OeeMetrics(registry=None)` with attributes for all 22 series and methods `observe_pass(summary: PassSummary) -> None`, `apply(readings: Readings) -> None`, `serve(port: int) -> None`.

Spec §14 names 21 series on port 9095 with the prefix `uns_oee_`. This module exposes those 21 plus one addition, `uns_oee_compute_failures_total`, which the spec's list omits: §13 requires a unit whose master data is missing to be "skipped with a counted log", and `PassSummary.failures` is that count. It is unlabelled because a failure is caught around one `run_shift` call and the pass records only how many there were.

**Why its own registry.** The default registry also carries the Python process and GC collectors. Port 9095 exists to answer one question — is this engine still closing shifts — and the simulator made the same call for the same reason (`99_simulator/src/uns_simulator/metrics.py:36`–`:43`).

**Why instance attributes instead of module-level Counters.** The historian declares its metrics at module scope (`04_uns_historian/src/uns_historian/prometheus_metrics.py:5`), which works for a process that has exactly one of each. Here the tests build several `OeeMetrics` in one session, and module-level objects on a shared registry would raise `Duplicated timeseries in CollectorRegistry` on the second import. An instance holding its own registry has no such problem, and the test can assert the exposed text.

**Why an UNCHANGED shift records nothing.** Nothing was computed, so `shifts_computed_total` must not move — otherwise the counter measures how often Prometheus was scraped rather than how many shifts were closed. `_last_shift_close_timestamp` is likewise already at the right value from the pass that computed it.

- [ ] **Step 1: Write the failing test**

Create `12_uns_oee/test/test_prometheus_metrics.py`:

```python
"""Tests for uns_oee.prometheus_metrics.

The exposed text is what is asserted, not the Python attributes. Spec section 14 is a promise
about metric names, and prometheus_client renames things - a Counter declared as `x` is
exposed as `x_total`. Only `generate_latest` can tell whether the promise was kept.
"""

from datetime import datetime, timedelta, timezone

import pytest
from prometheus_client import generate_latest

from uns_oee.oee_calc import ShiftMetrics
from uns_oee.pipeline import (
    ACTION_COMPUTED,
    ACTION_REVISED,
    ACTION_UNCHANGED,
    ShiftOutcome,
)
from uns_oee.prometheus_metrics import OeeMetrics, Readings, read_gauges
from uns_oee.scheduler import BackfillTally, PassSummary
from uns_oee.shift_calendar import ShiftWindow

LINE = "CovestroAG/Dormagen/Production/Line1"
WINDOW = ShiftWindow(
    start=datetime(2026, 9, 7, 6, tzinfo=timezone.utc),
    end=datetime(2026, 9, 7, 14, tzinfo=timezone.utc),
    label="A",
)

#: Every series spec section 14 promises, as the names Prometheus actually scrapes.
EXPECTED_SERIES = (
    "uns_oee_shifts_computed_total",
    "uns_oee_shift_compute_seconds_bucket",
    "uns_oee_revisions_total",
    "uns_oee_late_data_detected_total",
    "uns_oee_input_rows",
    "uns_oee_shift_oee",
    "uns_oee_availability",
    "uns_oee_performance",
    "uns_oee_quality",
    "uns_oee_performance_over_unity_total",
    "uns_oee_counter_resets_total",
    "uns_oee_missing_ideal_cycle_time_total",
    "uns_oee_unclassified_downtime_seconds_total",
    "uns_oee_recompute_queue_depth",
    "uns_oee_unpublished_results",
    "uns_oee_publish_total",
    "uns_oee_publish_errors_total",
    "uns_oee_last_shift_close_timestamp",
    "uns_oee_db_up",
    "uns_oee_backfill_shifts_total",
    "uns_oee_backfill_shifts_skipped_total",
    "uns_oee_compute_failures_total",
)


def good_metrics(**overrides) -> ShiftMetrics:
    values = {
        "loading_time_s": 27000.0,
        "run_time_s": 24084.0,
        "good_count": 12840.0,
        "reject_count": 182.0,
        "total_count": 13022.0,
        "availability": 0.892,
        "performance": 0.841,
        "quality": 0.952,
        "oee": 0.714,
        "status": "OK",
    }
    values.update(overrides)
    return ShiftMetrics(**values)


def outcome(**overrides) -> ShiftOutcome:
    values = {
        "unit_id": 1,
        "asset_path": LINE,
        "window": WINDOW,
        "action": ACTION_COMPUTED,
        "metrics": good_metrics(),
        "revision": 1,
        "published": True,
        "input_rows": 2880,
        "counter_resets": 0,
        "unclassified_seconds": 0.0,
        "compute_seconds": 0.4,
    }
    values.update(overrides)
    return ShiftOutcome(**values)


def exposed(metrics: OeeMetrics) -> str:
    return generate_latest(metrics.registry).decode("utf-8")


def series(text: str, name: str, labels: str = "") -> float | None:
    """The value of one sample line, or None if the series is absent."""
    needle = f"{name}{labels} "
    for line in text.splitlines():
        if line.startswith(needle):
            return float(line.rsplit(" ", 1)[1])
    return None


# --- the promise ---------------------------------------------------------------------


def test_every_series_the_spec_names_is_exposed():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(
            outcomes=(outcome(),),
            units=1,
            windows=1,
            failures=1,
            backfilled=True,
            backfill=(
                BackfillTally(
                    unit_id=1,
                    asset_path=LINE,
                    computed=2,
                    skipped_no_history=0,
                    skipped_predates_data=28,
                ),
            ),
        )
    )
    metrics.apply(Readings(recompute_queue_depth=3, unpublished_results=1, database_up=True))
    text = exposed(metrics)
    missing = [name for name in EXPECTED_SERIES if name not in text]
    assert missing == []


def test_the_registry_carries_nothing_but_this_engines_series():
    text = exposed(OeeMetrics())
    # Not the default registry: no process or GC collectors on this port.
    assert "python_gc_objects_collected_total" not in text
    assert "process_virtual_memory_bytes" not in text


def test_two_instances_do_not_collide_on_one_registry():
    # Module-level Counters would raise "Duplicated timeseries" here.
    first, second = OeeMetrics(), OeeMetrics()
    assert first.registry is not second.registry


# --- what one shift records ----------------------------------------------------------


def test_a_computed_shift_records_its_factors_and_its_close_time():
    metrics = OeeMetrics()
    metrics.observe_pass(PassSummary(outcomes=(outcome(),)))
    text = exposed(metrics)

    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_shift_oee", label) == 0.714
    assert series(text, "uns_oee_availability", label) == 0.892
    assert series(text, "uns_oee_performance", label) == 0.841
    assert series(text, "uns_oee_quality", label) == 0.952
    assert series(text, "uns_oee_input_rows", label) == 2880.0
    assert series(text, "uns_oee_last_shift_close_timestamp", label) == WINDOW.end.timestamp()
    assert series(text, "uns_oee_shifts_computed_total", f'{{status="OK",unit="{LINE}"}}') == 1.0


def test_a_null_factor_is_not_exposed_as_zero():
    metrics = OeeMetrics()
    silent = good_metrics(
        availability=None, performance=None, quality=None, oee=None, status="NO_INPUT_DATA"
    )
    metrics.observe_pass(PassSummary(outcomes=(outcome(metrics=silent),)))
    text = exposed(metrics)

    label = f'{{unit="{LINE}"}}'
    # A zero OEE and an undefined OEE are different facts, and a trend that plots the second
    # as the first invents a catastrophic shift. Absent is the only honest rendering.
    assert series(text, "uns_oee_shift_oee", label) is None
    assert series(text, "uns_oee_availability", label) is None
    # The shift is still counted, with the status that says why there are no factors.
    assert series(text, "uns_oee_shifts_computed_total", f'{{status="NO_INPUT_DATA",unit="{LINE}"}}') == 1.0


def test_an_unchanged_shift_records_nothing():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(outcomes=(outcome(action=ACTION_UNCHANGED, metrics=None),))
    )
    text = exposed(metrics)
    assert series(text, "uns_oee_shifts_computed_total", f'{{status="OK",unit="{LINE}"}}') is None
    assert series(text, "uns_oee_shift_compute_seconds_count") == 0.0


def test_a_revision_counts_as_a_revision_and_as_late_data():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(outcomes=(outcome(action=ACTION_REVISED, revision=2, late_data=True),))
    )
    text = exposed(metrics)
    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_revisions_total", label) == 1.0
    assert series(text, "uns_oee_late_data_detected_total", label) == 1.0


def test_a_reassignment_is_a_revision_but_not_late_data():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(outcomes=(outcome(action=ACTION_REVISED, revision=2, late_data=False),))
    )
    text = exposed(metrics)
    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_revisions_total", label) == 1.0
    assert series(text, "uns_oee_late_data_detected_total", label) == 0.0


def test_the_data_quality_signals_are_counted():
    metrics = OeeMetrics()
    flawed = good_metrics(missing_ideal_cycle_time=True, performance_over_unity=True)
    metrics.observe_pass(
        PassSummary(
            outcomes=(outcome(metrics=flawed, counter_resets=2, unclassified_seconds=3600.0),)
        )
    )
    text = exposed(metrics)
    label = f'{{unit="{LINE}"}}'
    assert series(text, "uns_oee_missing_ideal_cycle_time_total", label) == 1.0
    assert series(text, "uns_oee_performance_over_unity_total", label) == 1.0
    assert series(text, "uns_oee_counter_resets_total", label) == 2.0
    assert series(text, "uns_oee_unclassified_downtime_seconds_total", label) == 3600.0


def test_a_failed_publish_is_an_error_not_a_publish():
    metrics = OeeMetrics()
    metrics.observe_pass(PassSummary(outcomes=(outcome(published=False),)))
    text = exposed(metrics)
    assert series(text, "uns_oee_publish_total") == 0.0
    assert series(text, "uns_oee_publish_errors_total") == 1.0


def test_the_two_kinds_of_skipped_backfill_are_labelled_apart():
    metrics = OeeMetrics()
    metrics.observe_pass(
        PassSummary(
            backfill=(
                BackfillTally(1, LINE, computed=2, skipped_no_history=0, skipped_predates_data=28),
                BackfillTally(2, "Line2", computed=0, skipped_no_history=30, skipped_predates_data=0),
            )
        )
    )
    text = exposed(metrics)
    assert series(text, "uns_oee_backfill_shifts_total", f'{{unit="{LINE}"}}') == 2.0
    assert (
        series(
            text,
            "uns_oee_backfill_shifts_skipped_total",
            f'{{reason="PREDATES_DATA",unit="{LINE}"}}',
        )
        == 28.0
    )
    assert (
        series(
            text, "uns_oee_backfill_shifts_skipped_total", '{reason="NO_HISTORY",unit="Line2"}'
        )
        == 30.0
    )


def test_a_pass_failure_is_counted():
    metrics = OeeMetrics()
    metrics.observe_pass(PassSummary(failures=3))
    assert series(exposed(metrics), "uns_oee_compute_failures_total") == 3.0


def test_the_readings_land_on_their_gauges():
    metrics = OeeMetrics()
    metrics.apply(Readings(recompute_queue_depth=4, unpublished_results=7, database_up=True))
    text = exposed(metrics)
    assert series(text, "uns_oee_recompute_queue_depth") == 4.0
    assert series(text, "uns_oee_unpublished_results") == 7.0
    assert series(text, "uns_oee_db_up") == 1.0


def test_a_database_that_is_down_reads_as_zero():
    metrics = OeeMetrics()
    metrics.apply(Readings(database_up=False))
    assert series(exposed(metrics), "uns_oee_db_up") == 0.0


# --- the two counts that come from the database --------------------------------------


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeConnection:
    def __init__(self, results, raises=False):
        self._results = list(results)
        self._raises = raises
        self.calls: list[str] = []

    async def execute(self, statement, parameters=None):
        if self._raises:
            raise RuntimeError("could not connect to server")
        self.calls.append(str(statement).lower())
        return self._results.pop(0)


class FakeDatabase:
    def __init__(self, *results, raises=False):
        self.connection = FakeConnection(results, raises=raises)

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_the_queue_depth_and_the_backlog_are_read_together():
    database = FakeDatabase(FakeResult(3), FakeResult(11))
    readings = await read_gauges(database)

    assert readings == Readings(recompute_queue_depth=3, unpublished_results=11, database_up=True)
    queue_sql, backlog_sql = database.connection.calls
    assert "recompute_request" in queue_sql and "claimed_at is null" in queue_sql
    assert "shift_result" in backlog_sql and "published_at is null" in backlog_sql


@pytest.mark.asyncio
async def test_a_database_that_refuses_the_query_reads_as_down():
    readings = await read_gauges(FakeDatabase(raises=True))
    # Nothing invented: the counts stay at zero and `database_up` is what the alert fires on.
    assert readings == Readings(recompute_queue_depth=0, unpublished_results=0, database_up=False)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_prometheus_metrics.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.prometheus_metrics'`.

- [ ] **Step 3: Write the implementation**

Create `12_uns_oee/src/uns_oee/prometheus_metrics.py`:

```python
"""Platform Observability for the OEE engine: spec section 14's series on port 9095.

Twenty-two series, twenty-one of them named in the spec and one - `_compute_failures_total` -
added because section 13 asks for a counted skip and `PassSummary.failures` is that count.

Everything here is fed from a `PassSummary` and a `Readings`, never read from the database by
the collector itself. A scrape must not be able to start a query: Prometheus scrapes on its
own HTTP thread, and a gauge that lazily queried Timescale would put an unbounded, unpooled
database call on a path whose only failure mode should be a stale number.
"""

import logging
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
from sqlalchemy import func, select

from uns_model.engine import Database
from uns_model.oee_tables import RecomputeRequest, ShiftResult
from uns_oee.pipeline import ACTION_REVISED, ShiftOutcome
from uns_oee.scheduler import SKIP_NO_HISTORY, SKIP_PREDATES_DATA, PassSummary

LOGGER = logging.getLogger(__name__)

#: prometheus_client appends `_total` to every Counter, so the names declared below are one
#: suffix short of the names spec section 14 promises. The test asserts the exposed text.
METRIC_PREFIX = "uns_oee"

#: A shift is a handful of indexed queries plus arithmetic over one shift's samples. Anything
#: past ten seconds means the historian is struggling, which is worth its own bucket.
COMPUTE_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

_UNIT = "unit"
_STATUS = "status"
_REASON = "reason"


@dataclass(frozen=True, slots=True)
class Readings:
    """The three numbers that come from the database rather than from a pass.

    `database_up` defaults to False so a failed read cannot be mistaken for a healthy one by
    omission - the caller has to have succeeded to set it.
    """

    recompute_queue_depth: int = 0
    unpublished_results: int = 0
    database_up: bool = False


async def read_gauges(database: Database) -> Readings:
    """The queue depth and the publication backlog, in one transaction.

    Both are `count(*)` over an indexed partial predicate, so they are cheap enough to read
    once per pass. Any failure returns `database_up=False` with the counts left at zero: a
    stale non-zero backlog would be worse than an obvious outage.
    """
    queued = (
        select(func.count())
        .select_from(RecomputeRequest)
        .where(RecomputeRequest.claimed_at.is_(None))
    )
    unpublished = (
        select(func.count()).select_from(ShiftResult).where(ShiftResult.published_at.is_(None))
    )
    try:
        async with database.begin() as connection:
            depth = (await connection.execute(queued)).scalar_one()
            backlog = (await connection.execute(unpublished)).scalar_one()
    except Exception:
        LOGGER.exception("OEE could not read its observability counts")
        return Readings(database_up=False)
    return Readings(
        recompute_queue_depth=int(depth or 0),
        unpublished_results=int(backlog or 0),
        database_up=True,
    )


class OeeMetrics:
    """The engine's series, on their own registry.

    Instance attributes rather than module-level objects: several of these are built in one
    test session, and module-level Counters sharing a registry raise on the second import.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        registry_ = self.registry

        self.shifts_computed = Counter(
            f"{METRIC_PREFIX}_shifts_computed",
            "Shifts whose result was computed, by unit and result status.",
            [_UNIT, _STATUS],
            registry=registry_,
        )
        self.compute_seconds = Histogram(
            f"{METRIC_PREFIX}_shift_compute_seconds",
            "Wall time to compute, store and publish one shift.",
            buckets=COMPUTE_BUCKETS,
            registry=registry_,
        )
        self.revisions = Counter(
            f"{METRIC_PREFIX}_revisions",
            "Stored results superseded by a recomputation, from any cause.",
            [_UNIT],
            registry=registry_,
        )
        self.late_data = Counter(
            f"{METRIC_PREFIX}_late_data_detected",
            "Revisions caused by historian rows arriving after the shift settled.",
            [_UNIT],
            registry=registry_,
        )
        self.input_rows = Gauge(
            f"{METRIC_PREFIX}_input_rows",
            "Historian rows behind the most recently computed shift.",
            [_UNIT],
            registry=registry_,
        )
        self.shift_oee = Gauge(
            f"{METRIC_PREFIX}_shift_oee",
            "OEE of the most recently computed shift, 0 to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.availability = Gauge(
            f"{METRIC_PREFIX}_availability",
            "Availability of the most recently computed shift, 0 to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.performance = Gauge(
            f"{METRIC_PREFIX}_performance",
            "Performance of the most recently computed shift, clamped to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.quality = Gauge(
            f"{METRIC_PREFIX}_quality",
            "Quality of the most recently computed shift, 0 to 1.",
            [_UNIT],
            registry=registry_,
        )
        self.performance_over_unity = Counter(
            f"{METRIC_PREFIX}_performance_over_unity",
            "Shifts whose raw Performance exceeded 1.0 and was clamped.",
            [_UNIT],
            registry=registry_,
        )
        self.counter_resets = Counter(
            f"{METRIC_PREFIX}_counter_resets",
            "Production counter resets or rollovers detected inside a shift.",
            [_UNIT],
            registry=registry_,
        )
        self.missing_ideal_cycle_time = Counter(
            f"{METRIC_PREFIX}_missing_ideal_cycle_time",
            "Shifts with a product segment that had no ideal cycle time authored.",
            [_UNIT],
            registry=registry_,
        )
        self.unclassified_downtime_seconds = Counter(
            f"{METRIC_PREFIX}_unclassified_downtime_seconds",
            "Downtime with no state_reason_map rule behind it. A master-data hole.",
            [_UNIT],
            registry=registry_,
        )
        self.compute_failures = Counter(
            f"{METRIC_PREFIX}_compute_failures",
            "Shift computations that raised and were skipped so the pass could continue.",
            registry=registry_,
        )
        self.backfill_shifts = Counter(
            f"{METRIC_PREFIX}_backfill_shifts",
            "Shifts the first pass enumerated for the bounded backfill.",
            [_UNIT],
            registry=registry_,
        )
        self.backfill_shifts_skipped = Counter(
            f"{METRIC_PREFIX}_backfill_shifts_skipped",
            "Backfill shifts declined, by reason.",
            [_UNIT, _REASON],
            registry=registry_,
        )
        self.publishes = Counter(
            f"{METRIC_PREFIX}_publish",
            "Shift results published to the namespace.",
            registry=registry_,
        )
        self.publish_errors = Counter(
            f"{METRIC_PREFIX}_publish_errors",
            "Publish attempts that failed, leaving published_at NULL for the next pass.",
            registry=registry_,
        )
        self.last_shift_close = Gauge(
            f"{METRIC_PREFIX}_last_shift_close_timestamp",
            "Unix time of the end of the last shift closed for this unit.",
            [_UNIT],
            registry=registry_,
        )
        self.recompute_queue_depth = Gauge(
            f"{METRIC_PREFIX}_recompute_queue_depth",
            "Unclaimed rows in oee.recompute_request.",
            registry=registry_,
        )
        self.unpublished_results = Gauge(
            f"{METRIC_PREFIX}_unpublished_results",
            "Stored results whose published_at is still NULL. The broker backlog.",
            registry=registry_,
        )
        self.db_up = Gauge(
            f"{METRIC_PREFIX}_db_up",
            "1 when the engine's last database read succeeded, 0 otherwise.",
            registry=registry_,
        )

    def observe_pass(self, summary: PassSummary) -> None:
        """Record everything one pass produced."""
        self.compute_failures.inc(summary.failures)
        for tally in summary.backfill:
            # `.inc(0)` on purpose: the series exists at zero, so a Grafana panel shows a
            # backfill that skipped nothing rather than a gap that could mean anything.
            self.backfill_shifts.labels(tally.asset_path).inc(tally.computed)
            self.backfill_shifts_skipped.labels(tally.asset_path, SKIP_NO_HISTORY).inc(
                tally.skipped_no_history
            )
            self.backfill_shifts_skipped.labels(tally.asset_path, SKIP_PREDATES_DATA).inc(
                tally.skipped_predates_data
            )
        for outcome in summary.outcomes:
            self._observe_shift(outcome)

    def apply(self, readings: Readings) -> None:
        """Set the three gauges that come from the database."""
        self.recompute_queue_depth.set(readings.recompute_queue_depth)
        self.unpublished_results.set(readings.unpublished_results)
        self.db_up.set(1.0 if readings.database_up else 0.0)

    def serve(self, port: int) -> None:
        """Expose the registry on `port` in a background thread."""
        start_http_server(port, registry=self.registry)
        LOGGER.info("OEE metrics available on port %d", port)

    def _observe_shift(self, outcome: ShiftOutcome) -> None:
        """One shift's contribution. An UNCHANGED shift contributes nothing.

        `metrics is None` is the test rather than the action name, because it is the honest
        one: without a `ShiftMetrics` there is no status to label and no factor to set.
        """
        if outcome.metrics is None:
            return
        metrics = outcome.metrics
        unit = outcome.asset_path

        self.compute_seconds.observe(outcome.compute_seconds)
        self.shifts_computed.labels(unit, metrics.status).inc()
        self.input_rows.labels(unit).set(outcome.input_rows)
        self.last_shift_close.labels(unit).set(outcome.window.end.timestamp())
        self.counter_resets.labels(unit).inc(outcome.counter_resets)
        self.unclassified_downtime_seconds.labels(unit).inc(outcome.unclassified_seconds)

        if outcome.action == ACTION_REVISED:
            self.revisions.labels(unit).inc()
            # Zeroed rather than skipped, so the series exists for every unit that has ever
            # been revised and a rate() over it is not a gap.
            self.late_data.labels(unit).inc(1 if outcome.late_data else 0)
        if metrics.performance_over_unity:
            self.performance_over_unity.labels(unit).inc()
        if metrics.missing_ideal_cycle_time:
            self.missing_ideal_cycle_time.labels(unit).inc()
        if outcome.published:
            self.publishes.inc()
        else:
            self.publish_errors.inc()

        # A null factor is left unset. `_scalar_to_metric` makes the same choice on the MQTT
        # side (04_uns_historian/src/uns_historian/metric_flattener.py): an undefined
        # Availability rendered as 0.0 would read as a catastrophic shift instead of no shift.
        self._set_if_known(self.shift_oee, unit, metrics.oee)
        self._set_if_known(self.availability, unit, metrics.availability)
        self._set_if_known(self.performance, unit, metrics.performance)
        self._set_if_known(self.quality, unit, metrics.quality)

    @staticmethod
    def _set_if_known(gauge: Gauge, unit: str, value: float | None) -> None:
        if value is not None:
            gauge.labels(unit).set(value)


__all__ = ["COMPUTE_BUCKETS", "METRIC_PREFIX", "OeeMetrics", "Readings", "read_gauges"]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_prometheus_metrics.py -v -n 0`
Expected: PASS (16 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/prometheus_metrics.py 12_uns_oee/test/test_prometheus_metrics.py
git commit -m "feat(oee): expose the engine's 22 series on port 9095"
```

---

### Task 15: The supervisor loop and the container's health check

**Files:**
- Create: `12_uns_oee/src/uns_oee/main.py`
- Create: `12_uns_oee/src/uns_oee/health_check.py`
- Create: `12_uns_oee/test/test_main.py`
- Create: `12_uns_oee/test/test_health_check.py`

**Interfaces:**
- Consumes: `uns_model.engine.Database`; `OeeConfig`, `OEE_ENV` (Task 1); `MetricSource` (Task 8); `MasterDataLoader` (Task 9); `ResultStore` (Task 10); `ResultPublisher` (Task 11); `ShiftPipeline` (Task 12); `ShiftScheduler`, `PassSummary` (Task 13); `OeeMetrics`, `read_gauges` (Task 14).
- Produces: `utc_now() -> datetime`; `build_scheduler(config, database, publisher) -> ShiftScheduler`; `OeeService(config, database, scheduler, metrics, *, clock=utc_now, gauges=read_gauges)` with `run_once()`, `run_forever()`, `request_stop()`; `run(config=None)`; `main()`. In `health_check.py`: `HEALTH_SERIES`, `check_metrics_endpoint(port, *, timeout=..., opener=urlopen) -> bool`, `main()`.

**This module is the only clock reader in the engine.** Global Constraint Rule 1 makes every layer below take its timestamp as an argument, which is what lets `recompute_cli` reproduce a historical result exactly. `utc_now` exists so the one remaining `datetime.now` in the module has a name a test can replace.

**Why the loop catches everything.** `run_pass` already isolates one unit's failure from the others, but the work it does *before* the units — bounding the backfill, loading master data, claiming requests — is against the database, and a restarting Postgres must not kill the engine. A pass that raises is logged, the gauges are read anyway, and the next pass computes the same shifts: nothing was committed, so nothing was lost.

**Why a failed pass does not increment a counter.** `uns_oee_compute_failures_total` means "a shift raised and the pass carried on", and reusing it for a whole-pass failure would make the two indistinguishable. The signals that catch a stalled engine already exist: `uns_oee_db_up` goes to 0 for the common cause, and `uns_oee_last_shift_close_timestamp` stops advancing for every other cause. Alert on the second — `time() - uns_oee_last_shift_close_timestamp{unit=...}` exceeding two shift lengths — because it is true regardless of *why* the engine stopped producing.

**Why the health check is an HTTP scrape and not a database probe.** Docker restarts an unhealthy container. A container whose only problem is that Timescale is restarting would be restarted repeatedly, which fixes nothing and loses the in-memory backfill flag each time. So liveness here means "the process is up and serving its own registry", which the metrics endpoint answers and which strictly implies the process check the other modules do with `psutil`. Readiness of the database belongs to `uns_oee_db_up` and an alert, not to a restart policy.

- [ ] **Step 1: Write the failing test for the supervisor loop**

Create `12_uns_oee/test/test_main.py`:

```python
"""Tests for uns_oee.main.

The service is constructed with its scheduler, its metrics and its clock passed in, so every
test here runs without a database, a broker or a wall clock. Only the two waits use real time,
and both are milliseconds.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from uns_oee.main import OeeService, build_scheduler, utc_now
from uns_oee.oee_config import OeeConfig
from uns_oee.prometheus_metrics import OeeMetrics, Readings
from uns_oee.scheduler import PassSummary

NOW = datetime(2026, 9, 9, 15, tzinfo=timezone.utc)


def config(**overrides) -> OeeConfig:
    values = {"mqtt_host": "localhost", "scan_interval_seconds": 0.01}
    values.update(overrides)
    return OeeConfig(**values)


class FakeScheduler:
    """Records the timestamps it was passed and can be told to fail."""

    def __init__(self, *, failures: int = 0, on_pass=None) -> None:
        self.calls: list[datetime] = []
        self._failures = failures
        self._on_pass = on_pass

    async def run_pass(self, now: datetime) -> PassSummary:
        self.calls.append(now)
        if self._on_pass is not None:
            self._on_pass()
        if self._failures > 0:
            self._failures -= 1
            raise RuntimeError("connection refused")
        return PassSummary(units=2, windows=3)


async def fake_gauges(_database) -> Readings:
    return Readings(recompute_queue_depth=5, unpublished_results=0, database_up=True)


def service(scheduler, *, metrics=None, gauges=fake_gauges, **config_overrides) -> OeeService:
    return OeeService(
        config(**config_overrides),
        database=object(),
        scheduler=scheduler,
        metrics=metrics if metrics is not None else OeeMetrics(),
        clock=lambda: NOW,
        gauges=gauges,
    )


# --- one pass ------------------------------------------------------------------------


def test_utc_now_is_timezone_aware():
    # A naive timestamp would silently become "UTC" three layers down, where the shift
    # calendar is doing DST arithmetic with it.
    assert utc_now().tzinfo is not None


@pytest.mark.asyncio
async def test_a_pass_stamps_the_clock_the_service_was_given():
    scheduler = FakeScheduler()
    summary = await service(scheduler).run_once()
    assert scheduler.calls == [NOW]
    assert summary == PassSummary(units=2, windows=3)


@pytest.mark.asyncio
async def test_a_pass_reads_the_database_gauges_afterwards():
    metrics = OeeMetrics()
    await service(FakeScheduler(), metrics=metrics).run_once()
    from prometheus_client import generate_latest

    text = generate_latest(metrics.registry).decode("utf-8")
    assert "uns_oee_recompute_queue_depth 5.0" in text
    assert "uns_oee_db_up 1.0" in text


@pytest.mark.asyncio
async def test_a_pass_that_raises_still_reads_the_gauges():
    metrics = OeeMetrics()
    # The pass failed, so there is no summary - but the queue depth is exactly the number an
    # operator wants during an outage, so it is read either way.
    assert await service(FakeScheduler(failures=1), metrics=metrics).run_once() is None
    from prometheus_client import generate_latest

    assert "uns_oee_recompute_queue_depth 5.0" in generate_latest(metrics.registry).decode("utf-8")


# --- the loop ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stop_before_the_first_pass_runs_nothing():
    scheduler = FakeScheduler()
    engine = service(scheduler, scan_interval_seconds=30.0)
    engine.request_stop()
    await asyncio.wait_for(engine.run_forever(), timeout=1.0)
    assert scheduler.calls == []


@pytest.mark.asyncio
async def test_a_stop_during_a_pass_ends_the_loop_without_serving_out_the_interval():
    holder: dict[str, OeeService] = {}
    scheduler = FakeScheduler(on_pass=lambda: holder["engine"].request_stop())
    holder["engine"] = service(scheduler, scan_interval_seconds=30.0)
    # A 30 second interval and a one second timeout: if the stop only took effect after the
    # sleep, `docker stop` would kill the container instead of it exiting.
    await asyncio.wait_for(holder["engine"].run_forever(), timeout=1.0)
    assert scheduler.calls == [NOW]


@pytest.mark.asyncio
async def test_the_loop_keeps_going_after_a_failed_pass():
    calls = 0

    def stop_after_two():
        nonlocal calls
        calls += 1
        if calls == 2:
            holder["engine"].request_stop()

    holder: dict[str, OeeService] = {}
    scheduler = FakeScheduler(failures=1, on_pass=stop_after_two)
    holder["engine"] = service(scheduler)
    await asyncio.wait_for(holder["engine"].run_forever(), timeout=2.0)
    # Two passes: the first raised, and the loop did not treat that as a reason to stop.
    assert len(scheduler.calls) == 2


# --- wiring --------------------------------------------------------------------------


def test_build_scheduler_rejects_a_metrics_table_that_is_not_an_identifier():
    # The table name reaches SQL by interpolation, so the guard in MetricSource must fire at
    # startup rather than on the first query of the first shift.
    with pytest.raises(ValueError, match="not a plain SQL identifier"):
        build_scheduler(config(metrics_table="uns_metrics; DROP TABLE oee.shift_result"), object(), None)


def test_build_scheduler_returns_a_scheduler_for_a_sane_configuration():
    from uns_oee.scheduler import ShiftScheduler

    assert isinstance(build_scheduler(config(), object(), None), ShiftScheduler)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_main.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.main'`.

- [ ] **Step 3: Write the supervisor loop**

Create `12_uns_oee/src/uns_oee/main.py`:

```python
"""Entry point: wire the engine together and run one pass every `scan_interval_seconds`.

The only module in `uns_oee` that reads a clock. Everything below takes its timestamp as an
argument (Global Constraint Rule 1), which is what makes a pass replayable and lets
`recompute_cli` reproduce a historical result exactly.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from uns_model.engine import Database
from uns_oee.master_data import MasterDataLoader
from uns_oee.oee_config import OEE_ENV, OeeConfig
from uns_oee.pipeline import ShiftPipeline
from uns_oee.prometheus_metrics import OeeMetrics, read_gauges
from uns_oee.publisher import ResultPublisher
from uns_oee.scheduler import PassSummary, ShiftScheduler
from uns_oee.sources import MetricSource
from uns_oee.store import ResultStore

LOGGER = logging.getLogger(__name__)


def utc_now() -> datetime:
    """The pass timestamp. Named so a test can replace it."""
    return datetime.now(timezone.utc)


def configure_asyncio_for_mqtt() -> None:
    """Windows needs the selector loop for the MQTT client, exactly as the simulator does
    (`99_simulator/src/uns_simulator/main.py`). Harmless everywhere else."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def build_scheduler(
    config: OeeConfig, database: Database, publisher: ResultPublisher | None
) -> ShiftScheduler:
    """Assemble the engine's read, compute, store and publish layers.

    One `MetricSource` and one `MasterDataLoader` shared between the scheduler and the
    pipeline: both hold nothing but their connection source, and a thirty-day backfill would
    otherwise build sixty of them.
    """
    source = MetricSource(database, metrics_table=config.metrics_table)
    master = MasterDataLoader(database)
    pipeline = ShiftPipeline(source, master, ResultStore(database), publisher)
    return ShiftScheduler(config, database, source, master, pipeline)


class OeeService:
    """The supervisor loop.

    Takes its scheduler, metrics, clock and gauge reader as arguments so the loop's behaviour -
    what it does when a pass fails, when it stops - is testable without a database or a broker.
    """

    def __init__(
        self,
        config: OeeConfig,
        database: Any,
        scheduler: Any,
        metrics: OeeMetrics,
        *,
        clock: Callable[[], datetime] = utc_now,
        gauges: Callable[[Any], Any] = read_gauges,
    ) -> None:
        self._config = config
        self._database = database
        self._scheduler = scheduler
        self._metrics = metrics
        self._clock = clock
        self._gauges = gauges
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Ask the loop to finish the current pass and return. Signal-handler safe."""
        self._stop.set()

    async def run_once(self) -> PassSummary | None:
        """One pass, then the database gauges. None means the pass failed.

        The gauges are read whether or not the pass succeeded: during an outage the recompute
        queue depth and the unpublished backlog are the two numbers worth having.
        """
        try:
            summary = await self._scheduler.run_pass(self._clock())
        except asyncio.CancelledError:
            raise
        except Exception:
            # Nothing was committed, so the next pass recomputes the same shifts. See the
            # module note: this is not counted, because `_last_shift_close_timestamp` going
            # stale is the honest alert for an engine that has stopped producing.
            LOGGER.exception("OEE pass failed; the next pass will pick up the same shifts")
            summary = None
        else:
            self._metrics.observe_pass(summary)
            LOGGER.info(
                "OEE pass over %d unit(s) computed %d shift(s) with %d failure(s)",
                summary.units,
                len(summary.outcomes),
                summary.failures,
            )
        self._metrics.apply(await self._gauges(self._database))
        return summary

    async def run_forever(self) -> None:
        """Pass, wait, repeat, until `request_stop`."""
        LOGGER.info(
            "OEE engine started; a pass every %.0fs, settling %d minutes after each shift",
            self._config.scan_interval_seconds,
            self._config.settle_minutes,
        )
        while not self._stop.is_set():
            await self.run_once()
            await self._wait_for_next_pass()
        LOGGER.info("OEE engine stopped")

    async def _wait_for_next_pass(self) -> None:
        """Sleep the scan interval, or less if asked to stop.

        `wait_for` on the stop event rather than `sleep`, so SIGTERM is acted on immediately
        instead of up to five minutes later - long enough for Docker to escalate to SIGKILL.
        """
        try:
            await asyncio.wait_for(
                self._stop.wait(), timeout=self._config.scan_interval_seconds
            )
        except TimeoutError:
            return


def _install_signal_handlers(service: OeeService) -> None:
    """Route SIGINT and SIGTERM to a clean stop where the platform allows it."""
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        handled = getattr(signal, name, None)
        if handled is None:
            continue
        try:
            loop.add_signal_handler(handled, service.request_stop)
        except NotImplementedError:
            # Windows asyncio has no add_signal_handler. `docker stop` sends SIGTERM to a
            # Linux container, which is the case that matters; on Windows the
            # KeyboardInterrupt path in `main` is the stop.
            LOGGER.debug("No asyncio handler for %s on this platform", name)


async def run(config: OeeConfig | None = None) -> None:
    """Start the metrics server, run the loop, and close the broker and the pool."""
    config = config if config is not None else OeeConfig.from_settings()
    if not config.is_valid():
        raise SystemExit("OEE engine is not configured; see conf/settings.yaml")

    database = Database.shared(OEE_ENV)
    publisher = ResultPublisher(config)
    metrics = OeeMetrics()
    # Before the first pass, so a scrape during startup returns zeros rather than a refused
    # connection - which is also what makes the container's health check pass immediately.
    metrics.serve(config.metrics_port)

    service = OeeService(config, database, build_scheduler(config, database, publisher), metrics)
    _install_signal_handlers(service)
    try:
        await service.run_forever()
    finally:
        # The publisher first: it holds a broker connection that a clean DISCONNECT closes,
        # and it needs nothing from the database to do it.
        await publisher.aclose()
        await Database.close_shared()


def main() -> None:
    """Console entry point `uns_oee`."""
    configure_asyncio_for_mqtt()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        LOGGER.info("OEE engine interrupted")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_main.py -v -n 0`
Expected: PASS (9 passed).

- [ ] **Step 5: Write the failing test for the health check**

Create `12_uns_oee/test/test_health_check.py`:

```python
"""Tests for uns_oee.health_check.

The opener is injected, so no test binds a port. What is being tested is the decision -
which answers count as healthy - not urllib.
"""

from urllib.error import URLError

import pytest

from uns_oee.health_check import HEALTH_SERIES, check_metrics_endpoint, main


class FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def opener(response):
    def _open(url, timeout=None):  # noqa: ARG001
        if isinstance(response, Exception):
            raise response
        return response

    return _open


def test_an_endpoint_serving_the_engines_registry_is_healthy():
    body = f"# HELP {HEALTH_SERIES} up\n# TYPE {HEALTH_SERIES} gauge\n{HEALTH_SERIES} 0.0\n"
    assert check_metrics_endpoint(9095, opener=opener(FakeResponse(body)))


def test_an_endpoint_serving_someone_elses_registry_is_not_healthy():
    # A port answering with the historian's series means this container is not the process
    # the health check was asked about.
    assert not check_metrics_endpoint(9095, opener=opener(FakeResponse("uns_historian_up 1.0\n")))


def test_a_non_200_answer_is_not_healthy():
    assert not check_metrics_endpoint(9095, opener=opener(FakeResponse("", status=503)))


def test_a_refused_connection_is_not_healthy():
    assert not check_metrics_endpoint(9095, opener=opener(URLError("connection refused")))


def test_main_exits_zero_when_healthy(monkeypatch):
    monkeypatch.setattr("uns_oee.health_check.check_metrics_endpoint", lambda port: True)
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0


def test_main_exits_one_when_not(monkeypatch):
    monkeypatch.setattr("uns_oee.health_check.check_metrics_endpoint", lambda port: False)
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_health_check.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.health_check'`.

- [ ] **Step 7: Write the health check**

Create `12_uns_oee/src/uns_oee/health_check.py`:

```python
"""Docker health check for the OEE engine: `uns_oee_health`.

One question - is this process up and serving its own registry - answered by scraping
127.0.0.1 on the metrics port. That strictly implies the `psutil` process check the other
modules perform, and needs no dependency beyond the standard library.

Deliberately does not probe Postgres or MQTT. Docker restarts an unhealthy container, and
restarting this one because Timescale is rebooting would fix nothing while discarding the
backfill state. Database health is `uns_oee_db_up` plus an alert, not a restart policy.
"""

import logging
import sys
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from uns_oee.oee_config import OeeConfig

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

#: The series whose presence proves the endpoint belongs to this engine. Unlabelled, so it is
#: exposed from construction onwards and a container that has not yet run a pass is healthy.
HEALTH_SERIES = "uns_oee_db_up"

#: Shorter than Docker's default 30s healthcheck timeout, so a hung endpoint is reported as
#: unhealthy rather than as a timed-out check.
DEFAULT_TIMEOUT_S = 5.0


def check_metrics_endpoint(
    port: int,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    opener: Callable[..., Any] = urlopen,
) -> bool:
    """Whether the local metrics endpoint answers with this engine's series."""
    url = f"http://127.0.0.1:{port}/metrics"
    try:
        with opener(url, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                LOGGER.error("Metrics endpoint %s answered %s", url, response.status)
                return False
            body = response.read().decode("utf-8", errors="replace")
    except Exception as ex:
        LOGGER.error("Metrics endpoint %s did not answer: %s", url, ex)
        return False
    if HEALTH_SERIES not in body:
        LOGGER.error("Metrics endpoint %s is not serving %s", url, HEALTH_SERIES)
        return False
    return True


def main() -> None:
    """Console entry point `uns_oee_health`. Exit 0 healthy, 1 not."""
    config = OeeConfig.from_settings()
    if not check_metrics_endpoint(config.metrics_port):
        sys.exit(1)
    LOGGER.info("Health check passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_health_check.py -v -n 0`
Expected: PASS (6 passed).

- [ ] **Step 9: Run the whole module's tests**

Run: `uv run pytest 12_uns_oee/test -q`
Expected: PASS. Every unit test in `12_uns_oee` passes; nothing here needs a database or a broker.

- [ ] **Step 10: Commit**

```bash
git add 12_uns_oee/src/uns_oee/main.py 12_uns_oee/src/uns_oee/health_check.py \
        12_uns_oee/test/test_main.py 12_uns_oee/test/test_health_check.py \
        12_uns_oee/pyproject.toml
git commit -m "feat(oee): run the engine as a supervised loop with a health check"
```

---

### Task 16: The recompute CLI

**Files:**
- Create: `12_uns_oee/src/uns_oee/recompute_cli.py`
- Create: `12_uns_oee/test/test_recompute_cli.py`

**Interfaces:**
- Consumes: `uns_model.engine.Database`; `uns_model.oee_tables.RecomputeRequest` (Task 2); `OeeConfig`, `OEE_ENV` (Task 1); `MasterDataLoader` (Task 9); `ResultPublisher` (Task 11); `build_scheduler`, `utc_now`, `configure_asyncio_for_mqtt` (Task 15).
- Produces: `as_utc(text) -> datetime`; `build_parser() -> ArgumentParser`; `parse_args(argv) -> Namespace`; `async resolve_unit_id(master, asset_path) -> int`; `async enqueue(database, unit_id, start, end, *, reason, requested_by) -> int`; `async run(argv) -> int`; `main()`.

Spec §9.1 keeps this CLI for two jobs the backfill cannot do: a range older than `backfill_days`, and a deliberate recomputation after master data changed — a corrected ideal cycle time moves Performance for every shift that ran that product, and no fingerprint of historian rows will ever notice.

**Why it writes to the queue instead of computing.** The engine is the only writer of results (§10), and two writers would race on `UNIQUE (oee_unit_id, shift_start)`. Enqueuing means the CLI works identically whether the engine is running or not, and an operator who runs it twice queues two rows that the second `claim_requests` finds already claimed.

**Why `--now` enqueues first and then runs a pass.** The alternative — a second code path that computes an arbitrary range in-process — would be the one path never exercised in production, and it is the path that writes to the database. So `--now` inserts the same row and then runs one ordinary pass, which claims it through `claim_requests` like any other. There is no second way to compute a shift in this codebase.

**What `--now` also does.** A pass is a pass: it re-checks every shift still inside `late_window_hours` and, on a fresh results table, runs the bounded backfill. That is logged before it starts. It is not a side effect worth suppressing — those shifts either have an unchanged fingerprint and cost two indexed queries each, or they needed computing anyway.

- [ ] **Step 1: Write the failing test**

Create `12_uns_oee/test/test_recompute_cli.py`:

```python
"""Tests for uns_oee.recompute_cli.

Argument handling is pure and gets tested directly. The one database call, `enqueue`, is
tested against a fake connection that records the compiled statement - what matters is that
the row lands pending, with the range the operator asked for.
"""

from datetime import datetime, timedelta, timezone

import pytest

from uns_oee.recompute_cli import as_utc, enqueue, parse_args, resolve_unit_id, run

FROM = "2026-08-01T00:00:00+00:00"
TO = "2026-09-01T00:00:00+00:00"
LINE = "CovestroAG/Dormagen/Production/Line1"


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeConnection:
    def __init__(self, results):
        self._results = list(results)
        self.statements: list = []

    async def execute(self, statement, parameters=None):
        self.statements.append(statement)
        return self._results.pop(0)


class FakeDatabase:
    def __init__(self, *results):
        self.connection = FakeConnection(results)

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


class FakeUnit:
    def __init__(self, unit_id: int, asset_path: str) -> None:
        self.unit_id = unit_id
        self.asset_path = asset_path


class FakeMaster:
    def __init__(self, units) -> None:
        self._units = units

    async def active_units(self):
        return self._units


# --- timestamps ----------------------------------------------------------------------


def test_a_naive_timestamp_is_read_as_utc():
    # A bare date is what an operator types. It is a range filter, not a shift boundary -
    # the shift calendar resolves local boundaries from the pattern's own timezone - so
    # reading it as UTC cannot shift a shift into the wrong day.
    assert as_utc("2026-08-01") == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_an_offset_is_honoured_rather_than_overwritten():
    parsed = as_utc("2026-08-01T02:00:00+02:00")
    assert parsed == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert parsed.tzinfo is not None


def test_an_unparsable_timestamp_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--asset-path", LINE, "--from", "last tuesday", "--to", TO])
    assert exit_info.value.code == 2


# --- arguments -----------------------------------------------------------------------


def test_a_unit_and_a_range_are_enough():
    args = parse_args(["--asset-path", LINE, "--from", FROM, "--to", TO])
    assert args.asset_path == LINE
    assert args.all_units is False
    assert args.now is False
    assert args.range_start == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_a_target_is_required():
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--from", FROM, "--to", TO])
    assert exit_info.value.code == 2


def test_a_unit_and_all_units_cannot_both_be_asked_for():
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--asset-path", LINE, "--all-units", "--from", FROM, "--to", TO])
    assert exit_info.value.code == 2


def test_a_backwards_range_is_refused_before_anything_is_written():
    # The table's CHECK would refuse it too, but as an IntegrityError traceback rather than
    # a usage message.
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--all-units", "--from", TO, "--to", FROM])
    assert exit_info.value.code == 2


# --- the unit -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_asset_path_resolves_to_its_unit_id():
    master = FakeMaster([FakeUnit(1, LINE), FakeUnit(2, "Other/Line2")])
    assert await resolve_unit_id(master, LINE) == 1


@pytest.mark.asyncio
async def test_an_unknown_asset_path_names_the_paths_that_do_exist():
    master = FakeMaster([FakeUnit(1, LINE)])
    with pytest.raises(SystemExit) as exit_info:
        await resolve_unit_id(master, "Typo/Line9")
    # The message, not just the exit code: an operator with a typo needs the list.
    assert LINE in str(exit_info.value)


# --- the row --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_writes_one_pending_request_and_returns_its_id():
    database = FakeDatabase(FakeResult(42))
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    request_id = await enqueue(
        database, 1, start, start + timedelta(days=31), reason="cycle time fixed", requested_by="ops"
    )
    assert request_id == 42
    sql = str(database.connection.statements[0]).lower()
    assert "insert into oee.recompute_request" in sql
    # claimed_at and completed_at are left NULL: pending is the whole point of the row.
    assert "claimed_at" not in sql
    assert "returning" in sql


@pytest.mark.asyncio
async def test_all_units_enqueues_one_row_with_no_unit():
    database = FakeDatabase(FakeResult(7))
    exit_code = await run(["--all-units", "--from", FROM, "--to", TO], database=database, master=FakeMaster([]))
    assert exit_code == 0
    parameters = database.connection.statements[0].compile().params
    assert parameters["oee_unit_id"] is None


@pytest.mark.asyncio
async def test_a_queued_request_does_not_run_a_pass():
    database = FakeDatabase(FakeResult(7))
    ran = []
    await run(
        ["--asset-path", LINE, "--from", FROM, "--to", TO],
        database=database,
        master=FakeMaster([FakeUnit(1, LINE)]),
        pass_runner=lambda: ran.append(True),
    )
    # Without --now the CLI's job is done when the row is committed; the engine's next pass
    # picks it up. Running a pass here would make the CLI a second writer of results.
    assert ran == []


@pytest.mark.asyncio
async def test_now_runs_one_pass_after_enqueuing():
    database = FakeDatabase(FakeResult(7))
    ran = []

    async def pass_runner():
        ran.append(True)

    exit_code = await run(
        ["--asset-path", LINE, "--from", FROM, "--to", TO, "--now"],
        database=database,
        master=FakeMaster([FakeUnit(1, LINE)]),
        pass_runner=pass_runner,
    )
    assert exit_code == 0
    assert ran == [True]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_recompute_cli.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_oee.recompute_cli'`.

- [ ] **Step 3: Write the implementation**

Create `12_uns_oee/src/uns_oee/recompute_cli.py`:

```python
"""`uns_oee_recompute` - queue a range for recomputation (spec sections 9.1 and 10).

Two jobs the automatic backfill cannot do: a range older than `backfill_days`, and a
deliberate recomputation after master data changed. A corrected ideal cycle time moves
Performance for every shift that ran that product, and no fingerprint of historian rows will
ever notice, because not one sample changed.

Writes a row to `oee.recompute_request` and stops there. The engine is the only writer of
results, so this process never computes one: `--now` enqueues the same row and then runs one
ordinary pass, which claims it through `claim_requests` like any other request.

    uns_oee_recompute --asset-path Enterprise/Site/Area/Line1 --from 2026-08-01 --to 2026-09-01
    uns_oee_recompute --all-units --from 2026-08-01 --to 2026-09-01 --now --reason "cycle times"
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert

from uns_model.engine import Database
from uns_model.oee_tables import RecomputeRequest
from uns_oee.main import build_scheduler, configure_asyncio_for_mqtt, utc_now
from uns_oee.master_data import MasterDataLoader
from uns_oee.oee_config import OEE_ENV, OeeConfig
from uns_oee.publisher import ResultPublisher

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def as_utc(text: str) -> datetime:
    """An ISO-8601 timestamp as an aware UTC datetime.

    A naive value is read as UTC rather than refused. The range is a filter over shift
    boundaries, not a boundary itself - the shift calendar resolves those from each pattern's
    own timezone - so `2026-08-01` cannot move a shift into the wrong day.
    """
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(f"{text!r} is not an ISO-8601 timestamp") from ex
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    """The command line. One target, one range, two optional flags."""
    parser = argparse.ArgumentParser(
        prog="uns_oee_recompute",
        description="Queue a shift range for recomputation by the OEE engine.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--asset-path", help="ISA-95 path of the OEE unit, e.g. Enterprise/Site/Area/Line1")
    target.add_argument(
        "--all-units",
        action="store_true",
        help="Every active unit. Written as a single request with no unit, which is how the table spells it.",
    )
    parser.add_argument("--from", dest="range_start", required=True, type=as_utc, help="Start of the range")
    parser.add_argument("--to", dest="range_end", required=True, type=as_utc, help="End of the range, exclusive")
    parser.add_argument("--reason", default="", help="Why. Stored on the request and read by the next engineer.")
    parser.add_argument("--requested-by", default=None, help="Defaults to the invoking OS user.")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run one engine pass in this process after enqueuing, instead of waiting for the engine's next scan.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parsed arguments, with the range validated. Exits 2 on a usage error."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.range_end <= args.range_start:
        # The table's CHECK would refuse this too, as an IntegrityError traceback. A usage
        # message is the better answer to a transposed pair of dates.
        parser.error("--to must be after --from")
    if args.requested_by is None:
        args.requested_by = _invoking_user()
    return args


def _invoking_user() -> str:
    """Who to record. `getuser` raises in a container with no passwd entry."""
    try:
        return getpass.getuser()
    except Exception:
        return "cli"


async def resolve_unit_id(master: Any, asset_path: str) -> int:
    """The `oee_unit.id` for an asset path. Exits 1 with the valid paths if there is none."""
    units = await master.active_units()
    for unit in units:
        if unit.asset_path == asset_path:
            return unit.unit_id
    known = ", ".join(sorted(unit.asset_path for unit in units)) or "none configured"
    raise SystemExit(f"No active OEE unit at {asset_path!r}. Active units: {known}")


async def enqueue(
    database: Any,
    unit_id: int | None,
    start: datetime,
    end: datetime,
    *,
    reason: str,
    requested_by: str,
) -> int:
    """Insert one pending request and return its id.

    `claimed_at`, `completed_at` and `error` are left unset: a pending row is the entire
    message, and `requested_at` comes from the server's `now()` so the queue is ordered by one
    clock rather than by whichever machine ran the CLI.
    """
    statement = (
        insert(RecomputeRequest)
        .values(
            oee_unit_id=unit_id,
            range_start=start,
            range_end=end,
            reason=reason,
            requested_by=requested_by,
        )
        .returning(RecomputeRequest.id)
    )
    async with database.begin() as connection:
        return (await connection.execute(statement)).scalar_one()


async def run(
    argv: Sequence[str] | None = None,
    *,
    database: Any | None = None,
    master: Any | None = None,
    pass_runner: Callable[[], Any] | None = None,
) -> int:
    """Enqueue the request, and run one pass if asked. Returns the process exit code.

    `database`, `master` and `pass_runner` are injected so the argument and SQL behaviour can
    be tested without a database; production leaves all three unset.
    """
    args = parse_args(argv)
    config = OeeConfig.from_settings()
    owned = database is None
    database = database if database is not None else Database.shared(OEE_ENV)
    master = master if master is not None else MasterDataLoader(database)

    try:
        unit_id = None if args.all_units else await resolve_unit_id(master, args.asset_path)
        request_id = await enqueue(
            database,
            unit_id,
            args.range_start,
            args.range_end,
            reason=args.reason,
            requested_by=args.requested_by,
        )
        LOGGER.info(
            "Queued recompute request %d for %s from %s to %s",
            request_id,
            args.asset_path if unit_id is not None else "every active unit",
            args.range_start.isoformat(),
            args.range_end.isoformat(),
        )
        if args.now:
            await _run_one_pass(config, database, pass_runner)
        else:
            LOGGER.info("The engine will claim it within %.0fs", config.scan_interval_seconds)
        return 0
    finally:
        if owned:
            await Database.close_shared()


async def _run_one_pass(config: OeeConfig, database: Any, pass_runner: Callable[[], Any] | None) -> None:
    """One ordinary engine pass in this process.

    Ordinary means ordinary: it also re-checks every shift still inside `late_window_hours`
    and, against an empty results table, runs the bounded backfill. Said out loud rather than
    suppressed - an unchanged shift costs two indexed queries, and the rest needed computing.
    """
    LOGGER.info("Running one pass here. It will also re-check recent shifts and, on an empty table, backfill.")
    if pass_runner is not None:
        await pass_runner()
        return
    publisher = ResultPublisher(config)
    try:
        summary = await build_scheduler(config, database, publisher).run_pass(utc_now())
        LOGGER.info(
            "Pass computed %d shift(s) with %d failure(s)", len(summary.outcomes), summary.failures
        )
    finally:
        await publisher.aclose()


def main() -> None:
    """Console entry point `uns_oee_recompute`."""
    configure_asyncio_for_mqtt()
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_recompute_cli.py -v -n 0`
Expected: PASS (13 passed).

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/src/uns_oee/recompute_cli.py 12_uns_oee/test/test_recompute_cli.py
git commit -m "feat(oee): add uns_oee_recompute to queue a range for recomputation"
```

---

### Task 17: Retire the simulator's fabricated OEE

**Files:**
- Modify: `conf/simulator/production.yaml` — delete five signals from the `MES-01` template
- Modify: `99_simulator/src/uns_simulator/models.py:41`–`:48` — add `KPI` to `ParameterType`
- Modify: `99_simulator/test/test_conf_files.py:46`, `:290`–`:292` — the signal count and the map assertions

**Interfaces:**
- Consumes: nothing from the engine. This task is deletion plus one enum member.
- Produces: `ParameterType.KPI` with value `"KPI"`, matching `KPI_PARAMETER_TYPE` in `uns_oee.publisher` (Task 11).

Spec §12. The simulator publishes `Availability`, `Performance`, `Quality`, `Oee` and `DowntimeReason` as instantaneous derived expressions. Two publishers on one concept, one of them fabricated, is worse than having no OEE at all: it makes the pilot's headline number unfalsifiable. Nothing consumes them — no dashboard, no alert rule, no test outside the conf-file tables.

**What stays, and why the engine needs no new simulator behaviour.** `GoodCount`, `RejectCount`, `TotalCount`, `CycleTime`, `PackMlState`, `PackMlStateCode`, `RecipeId` and `BatchId` are honest machine signals and are exactly the engine's inputs. `ctx.state` already cycles through PackML, so stops occur; `RecipeId` already carries `dwell_s: 7200`, so a product change happens inside a long shift and the per-product path is exercised by the shipped configuration.

**Why `KPI` is added to an enum this module no longer emits.** `ParameterType` in `models.py` is the only place in the repository where the topic hierarchy's sixth segment is enumerated, so it is where the vocabulary is declared and reviewed. `uns_oee.publisher` deliberately does not import it — a runtime dependency from the engine onto the simulator would be backwards — and Step 4 pins the two spellings together with a test instead.

- [ ] **Step 1: Write the failing tests**

In `99_simulator/test/test_conf_files.py`, add `ParameterType` to the imports:

```python
from uns_simulator.models import ParameterType
from uns_simulator.plant import PACKML_STATES
from uns_simulator.profiles import load_profile, read_simulator_conf
```

Add the two vocabularies below `CONF_DIR`:

```python
# Spec 12. Deleted because `12_uns_oee` computes these from historised samples, and a
# fabricated second answer to the same question makes the real one unfalsifiable.
RETIRED_MES_SIGNALS = ("Availability", "Performance", "Quality", "Oee", "DowntimeReason")

# Kept, because these are honest machine signals and they are the engine's inputs. Asserted
# rather than assumed: deleting one of these would leave the OEE engine computing
# NO_INPUT_DATA for every shift, with nothing in the simulator's own suite to say why.
CONSUMED_MES_SIGNALS = (
    "GoodCount",
    "RejectCount",
    "TotalCount",
    "CycleTime",
    "PackMlState",
    "PackMlStateCode",
    "RecipeId",
    "BatchId",
)
```

Change the production signal count on line 46 from 15 to 10:

```python
    "production": {"MES-01": 10, "QA-01": 6, "LAB-01": 6, "001": 2, "002": 1},
```

Replace `test_packml_state_code_maps_every_state` and append the three new tests:

```python
def _mes_signals(raw) -> dict:
    return next(item for item in raw["production"]["devices"] if item["id"] == "MES-01")["signals"]


def test_packml_state_code_maps_every_state(raw):
    """A state missing from the map publishes its own name where an integer is expected.

    SteppedSignal._translate falls through to the raw value on a miss, so an incomplete map
    fails as a type surprise on a consumer rather than at load time. Only this test catches it.
    """
    assert set(_mes_signals(raw)["PackMlStateCode"]["map"]) == set(PACKML_STATES)


def test_the_simulator_publishes_no_fabricated_oee(raw):
    """Spec 12. The OEE engine is the only publisher of these numbers."""
    signals = _mes_signals(raw)
    assert [name for name in RETIRED_MES_SIGNALS if name in signals] == []


def test_the_signals_the_oee_engine_reads_are_still_published(raw):
    signals = _mes_signals(raw)
    assert [name for name in CONSUMED_MES_SIGNALS if name not in signals] == []


def test_kpi_is_a_parameter_type_no_simulated_device_claims(raw):
    """The sixth ParameterType exists, and nothing here publishes under it.

    A simulated device claiming `KPI` would put a fabricated number back on the topic the
    engine writes to, which is the whole thing spec 12 removes.
    """
    assert ParameterType("KPI") is ParameterType.KPI
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            for name, signal in template["signals"].items():
                claimed = (signal or {}).get("param_type")
                assert claimed != "KPI", f"{family}.yaml {template['id']}/{name} claims KPI"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest 99_simulator/test/test_conf_files.py -v -n 0`
Expected: FAIL — `test_kpi_is_a_parameter_type_no_simulated_device_claims` raises `ValueError: 'KPI' is not a valid ParameterType`, `test_the_simulator_publishes_no_fabricated_oee` reports all five names, and the parametrised `MES-01` count fails with 15 != 10.

- [ ] **Step 3: Add the enum member**

In `99_simulator/src/uns_simulator/models.py`, extend `ParameterType`:

```python
class ParameterType(Enum):
    """Types of industrial parameters following ISA-95 standards"""

    PROCESS_VALUE = "ProcessValue"  # Measured values from sensors
    SETPOINT = "Setpoint"  # Target values for control
    STATUS = "Status"  # Equipment status information
    ALARM = "Alarm"  # Alarm and warning conditions
    EVENT = "EVENT"  # EVENT STATUS
    KPI = "KPI"  # Computed over a closed period, not measured at an instant
```

The comment earns its place: `KPI` differs from the other five in *when* it is true. A `ProcessValue` is a reading at a timestamp; a KPI is an assertion about a window that has ended, which is why the OEE engine publishes one per shift rather than continuously.

- [ ] **Step 4: Delete the five signals**

In `conf/simulator/production.yaml`, remove these five blocks from the `MES-01` template, leaving everything else — including the comment header and the other ten signals — untouched:

- `Availability` (the `100.0 * ctx.running` square wave)
- `Performance` (`100.0 * ctx.production_rate`, with its `limits`)
- `Quality` (the counter ratio, with its `limits`)
- `Oee` (the product of the three, with its `limits` **and its `export_metric: true`**)
- `DowntimeReason` (the 17-entry PackML-to-reason map)

`MES-01` should be left with exactly these ten, in this order: `PackMlState`, `PackMlStateCode`, `ProductionRate`, `ThroughputTph`, `GoodCount`, `RejectCount`, `TotalCount`, `CycleTime`, `BatchId`, `RecipeId`.

Add a note to the file's header comment, after the `NOTE the ctx path` paragraph, so the next reader does not re-add them:

```yaml
# OEE is NOT published here. Availability, Performance, Quality, Oee and DowntimeReason were
# removed per the OEE engine design section 12: `12_uns_oee` computes them from historised
# samples over a closed shift, and an instantaneous square wave named "Availability" competing
# with a real one is worse than no number at all. The signals that engine reads - the two
# counters, TotalCount, CycleTime, both PackML signals, RecipeId and BatchId - stay.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest 99_simulator/test/test_conf_files.py -v -n 0`
Expected: PASS.

- [ ] **Step 6: Run the simulator's whole suite**

Run: `uv run pytest 99_simulator/test -q`
Expected: PASS. `test_metrics.py` builds its own `SignalSpec` objects rather than reading `production.yaml`, so losing `Oee`'s `export_metric: true` changes no expectation there; `test_conf_files.py` is the only suite that reads the shipped files.

- [ ] **Step 7: Commit**

```bash
git add conf/simulator/production.yaml 99_simulator/src/uns_simulator/models.py \
        99_simulator/test/test_conf_files.py
git commit -m "refactor(simulator): retire fabricated OEE signals and declare the KPI parameter type"
```

---

### Task 18: `OeeResultRepository` — the reads GraphQL needs, and the one write

**Files:**
- Create: `09_uns_model/src/uns_model/oee_results.py`
- Test: `09_uns_model/test/test_oee_results.py`

**Interfaces:**
- Consumes: `uns_model.oee_tables` from Task 2 — `DowntimeEvent`, `DowntimeReason`, `OeeUnit`, `RecomputeRequest`, `REASON_SOURCES`, `ShiftResult`, `ShiftResultProduct`; `uns_model.tables.Asset`; `Database` from `uns_model.engine`.
- Produces:
  - `MANUAL_REASON_SOURCE: str`, `SINGLE_SHIFT_MARGIN: timedelta`
  - `ParetoBucket(reason_code: str, display_name: str, category: str, is_planned: bool, event_count: int, total_seconds: float, share: float)`
  - `ShiftResultRow(result: ShiftResult, asset_path: str, products: tuple[ShiftResultProduct, ...])`
  - `DowntimeEventRow(event: DowntimeEvent, asset_path: str, display_name: str, category: str, is_planned: bool)`
  - `pareto_from_rows(rows: Sequence[tuple[str, str, str, bool, int, float]]) -> list[ParetoBucket]`
  - `OeeResultRepository(database: Database)` with
    `shift_results(asset_path: str, range_start: datetime, range_end: datetime) -> list[ShiftResultRow]`,
    `downtime_events(asset_path: str, range_start: datetime, range_end: datetime) -> list[DowntimeEventRow]`,
    `downtime_pareto(asset_path: str, range_start: datetime, range_end: datetime) -> list[ParetoBucket]`,
    `assign_reason(event_id: int, reason_code: str, *, note: str | None = None, assigned_by: str | None = None) -> DowntimeEventRow | None`

**Why this lives in `09_uns_model` and not in `12_uns_oee`.** The GraphQL service must not depend on the engine's package: `07_uns_graphql` already depends on `09_uns_model`, and importing `uns_oee` would put an aiomqtt publisher and a scheduler into the API container for the sake of three SELECTs. `09_uns_model` is the shared seam both processes already have — which is where `AlertRuleRepository` sits, for the same reason.

**Why it is a separate file from `oee_master_data.py`.** Master data is authored in `conf/oee/*.yaml` and applied by a container; a downtime reason is corrected by an operator looking at last night's shift. They share a database and nothing else — the same split `uns_model/alert_rules.py` already makes against `AssetModelRepository`.

**Why every join is spelled out.** `uns_model` declares no `relationship()` anywhere. Under asyncio a lazy load on an unloaded attribute raises `MissingGreenlet`, and the failure then surfaces in the resolver rather than in the query — so the joins are written explicitly and the rows are grouped in Python.

**Why the ranges are half-open on the start column.** `shift_windows` in Task 4 already bounds by `[from, to)` on the shift's start. A console asking for two adjacent days must neither drop a shift nor count one twice, and matching the calendar's own convention is what guarantees it. `downtime_events` and `downtime_pareto` filter on the same column with the same predicate — `started_at` — so an events table and a Pareto chart on one dashboard can never disagree about which stops are in the window.

- [ ] **Step 1: Write the failing test**

Create `09_uns_model/test/test_oee_results.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

What the OEE result reads return, and what a reason assignment writes.

The Pareto arithmetic is tested as a pure function, because that is the one piece of
this file that decides a number rather than a row. The repository methods are tested
against a scripted session: what matters here is that the right statements are built in
the right order and that their rows land on the right dataclass fields. Whether the SQL
is valid against a real TimescaleDB is `test_integration.py`'s job.
"""

from __future__ import annotations

from collections import namedtuple
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from uns_model.oee_results import (
    MANUAL_REASON_SOURCE,
    SINGLE_SHIFT_MARGIN,
    DowntimeEventRow,
    OeeResultRepository,
    ParetoBucket,
    pareto_from_rows,
)
from uns_model.oee_tables import REASON_SOURCES, DowntimeEvent, ShiftResult, ShiftResultProduct

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def row(**fields):
    """A stand-in for a SQLAlchemy `Row`: attribute access and tuple unpacking both work."""
    return namedtuple("Row", fields)(**fields)


class FakeResult:
    """One scripted result. `all`, `first` and `one_or_none` read the same rows."""

    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        if len(self._rows) > 1:
            raise AssertionError("one_or_none over more than one row")
        return self._rows[0] if self._rows else None


class FakeSession:
    """Hands back scripted results in order and keeps every statement it was given."""

    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    async def scalars(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


class FakeDatabase:
    def __init__(self, results=()):
        self.session_obj = FakeSession(results)

    @asynccontextmanager
    async def session(self):
        yield self.session_obj


def sql(statement) -> str:
    return str(statement)


def bound(statement) -> dict:
    """The literal values a statement carries, so an INSERT can be asserted on."""
    return statement.compile().params


def _result(result_id: int = 1, **overrides) -> ShiftResult:
    values = {
        "id": result_id,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "shift_end": SHIFT_END,
        "shift_label": "Morning",
        "loading_time_s": 27000.0,
        "run_time_s": 24300.0,
        "planned_down_s": 1800.0,
        "unplanned_down_s": 2700.0,
        "good_count": 4800.0,
        "reject_count": 200.0,
        "total_count": 5000.0,
        "availability": 0.9,
        "performance": 0.85,
        "performance_raw": 0.85,
        "quality": 0.96,
        "oee": 0.7344,
        "status": "OK",
        "revision": 1,
        "input_fingerprint": "1200:2026-08-31T14:00:00+00:00",
        "computed_at": datetime(2026, 8, 31, 14, 20, tzinfo=UTC),
        "published_at": datetime(2026, 8, 31, 14, 20, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return ShiftResult(**values)


def _event(event_id: int = 11, **overrides) -> DowntimeEvent:
    values = {
        "id": event_id,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "UNCLASSIFIED",
        "reason_source": "auto",
        "assigned_by": None,
        "assigned_at": None,
        "note": "",
    }
    values.update(overrides)
    return DowntimeEvent(**values)


# --------------------------------------------------------------------- the Pareto


def test_manual_reason_source_is_in_the_database_vocabulary():
    """A constant the CHECK constraint rejects would fail on every assignment, at runtime."""
    assert MANUAL_REASON_SOURCE in REASON_SOURCES


def test_pareto_orders_by_lost_time_descending():
    """A Pareto chart *is* the ordering. Unsorted buckets are just a table."""
    buckets = pareto_from_rows(
        [
            ("CHANGEOVER", "Changeover", "PLANNED", True, 2, 1800.0),
            ("MECH_FAULT", "Mechanical fault", "FAILURE", False, 5, 5400.0),
            ("NO_FEED", "No feedstock", "SUPPLY", False, 1, 3600.0),
        ]
    )

    assert [bucket.reason_code for bucket in buckets] == ["MECH_FAULT", "NO_FEED", "CHANGEOVER"]
    assert buckets[0].event_count == 5
    assert buckets[0].total_seconds == pytest.approx(5400.0)


def test_pareto_breaks_ties_on_the_reason_code():
    """Two reasons with the same lost time must not swap places between refreshes."""
    buckets = pareto_from_rows(
        [
            ("NO_FEED", "No feedstock", "SUPPLY", False, 1, 600.0),
            ("CHANGEOVER", "Changeover", "PLANNED", True, 1, 600.0),
        ]
    )

    assert [bucket.reason_code for bucket in buckets] == ["CHANGEOVER", "NO_FEED"]


def test_pareto_shares_sum_to_one():
    """Spec section 10: a Pareto must always account for all of the downtime."""
    buckets = pareto_from_rows(
        [
            ("MECH_FAULT", "Mechanical fault", "FAILURE", False, 3, 3000.0),
            ("NO_FEED", "No feedstock", "SUPPLY", False, 2, 1000.0),
        ]
    )

    assert buckets[0].share == pytest.approx(0.75)
    assert buckets[1].share == pytest.approx(0.25)
    assert sum(bucket.share for bucket in buckets) == pytest.approx(1.0)


def test_pareto_of_zero_total_downtime_reports_zero_shares():
    """Stops of no measurable length are not a division by zero."""
    buckets = pareto_from_rows([("CHANGEOVER", "Changeover", "PLANNED", True, 1, 0.0)])

    assert buckets[0].share == 0.0


def test_pareto_of_an_empty_window_is_empty():
    assert pareto_from_rows([]) == []


def test_pareto_falls_back_to_the_code_when_a_reason_has_no_display_name():
    """`display_name` defaults to '' in the table, and a nameless bar is unreadable."""
    buckets = pareto_from_rows([("MECH_FAULT", "", "FAILURE", False, 1, 60.0)])

    assert buckets[0].display_name == "MECH_FAULT"


def test_pareto_buckets_compare_by_value():
    """A frozen dataclass, so a test can assert on a whole bucket."""
    bucket = ParetoBucket(
        reason_code="NO_FEED",
        display_name="No feedstock",
        category="SUPPLY",
        is_planned=False,
        event_count=1,
        total_seconds=60.0,
        share=1.0,
    )

    assert bucket == ParetoBucket("NO_FEED", "No feedstock", "SUPPLY", False, 1, 60.0, 1.0)


# ---------------------------------------------------------------------- the reads


@pytest.mark.asyncio
async def test_shift_results_maps_rows_and_groups_products():
    database = FakeDatabase(
        [
            FakeResult(
                [
                    row(ShiftResult=_result(1), path=LINE),
                    row(ShiftResult=_result(2, shift_start=SHIFT_END), path=LINE),
                ]
            ),
            FakeResult(
                [
                    ShiftResultProduct(id=1, shift_result_id=1, product_code="MDI-01", total_count=3000.0),
                    ShiftResultProduct(id=2, shift_result_id=1, product_code="MDI-02", total_count=2000.0),
                    ShiftResultProduct(id=3, shift_result_id=2, product_code="MDI-01", total_count=1000.0),
                ]
            ),
        ]
    )

    rows = await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END + timedelta(hours=8))

    assert [item.result.id for item in rows] == [1, 2]
    assert [item.asset_path for item in rows] == [LINE, LINE]
    assert [product.product_code for product in rows[0].products] == ["MDI-01", "MDI-02"]
    assert [product.product_code for product in rows[1].products] == ["MDI-01"]


@pytest.mark.asyncio
async def test_a_shift_result_with_no_products_gets_an_empty_tuple():
    """A single-product line publishes no recipe, so `shift_result_product` stays empty."""
    database = FakeDatabase([FakeResult([row(ShiftResult=_result(1), path=LINE)]), FakeResult([])])

    rows = await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END)

    assert rows[0].products == ()


@pytest.mark.asyncio
async def test_shift_results_filters_on_a_half_open_range():
    database = FakeDatabase([FakeResult([]), FakeResult([])])

    await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END)

    statement = sql(database.session_obj.statements[0])
    assert "shift_result.shift_start >= " in statement
    assert "shift_result.shift_start < " in statement
    assert "asset.path = " in statement


@pytest.mark.asyncio
async def test_shift_results_does_not_query_products_when_there_are_no_results():
    """One round trip, not two, for the common case of a line with no shifts in range."""
    database = FakeDatabase([FakeResult([])])

    rows = await OeeResultRepository(database).shift_results(LINE, SHIFT_START, SHIFT_END)

    assert rows == []
    assert len(database.session_obj.statements) == 1


@pytest.mark.asyncio
async def test_downtime_events_carry_the_joined_reason():
    """The console needs `isPlanned` to explain why a reassignment moved the OEE."""
    database = FakeDatabase(
        [
            FakeResult(
                [
                    row(
                        DowntimeEvent=_event(11),
                        path=LINE,
                        display_name="Mechanical fault",
                        category="FAILURE",
                        is_planned=False,
                    )
                ]
            )
        ]
    )

    rows = await OeeResultRepository(database).downtime_events(LINE, SHIFT_START, SHIFT_END)

    assert len(rows) == 1
    assert rows[0] == DowntimeEventRow(
        event=rows[0].event,
        asset_path=LINE,
        display_name="Mechanical fault",
        category="FAILURE",
        is_planned=False,
    )
    assert rows[0].event.id == 11
    assert "downtime_event.started_at >= " in sql(database.session_obj.statements[0])


@pytest.mark.asyncio
async def test_downtime_pareto_aggregates_in_the_database():
    """Grouped in SQL: a year of stops is thousands of rows and the console wants nine."""
    database = FakeDatabase(
        [
            FakeResult(
                [
                    row(
                        reason_code="NO_FEED",
                        display_name="No feedstock",
                        category="SUPPLY",
                        is_planned=False,
                        event_count=2,
                        total_seconds=1200.0,
                    )
                ]
            )
        ]
    )

    buckets = await OeeResultRepository(database).downtime_pareto(LINE, SHIFT_START, SHIFT_END)

    assert buckets == [ParetoBucket("NO_FEED", "No feedstock", "SUPPLY", False, 2, 1200.0, 1.0)]
    statement = sql(database.session_obj.statements[0]).upper()
    assert "GROUP BY" in statement
    assert "COUNT(" in statement
    assert "SUM(" in statement


# ---------------------------------------------------------------------- the write


def _assignment_database(existing_note: str = "") -> FakeDatabase:
    """The four results `assign_reason` consumes: reason check, update, insert, re-read."""
    return FakeDatabase(
        [
            FakeResult(["MECH_FAULT"]),
            FakeResult([row(oee_unit_id=7, shift_start=SHIFT_START)]),
            FakeResult([]),
            FakeResult(
                [
                    row(
                        DowntimeEvent=_event(
                            11,
                            reason_code="MECH_FAULT",
                            reason_source="manual",
                            assigned_by="a.operator",
                            assigned_at=datetime(2026, 8, 31, 15, 0, tzinfo=UTC),
                            note=existing_note,
                        ),
                        path=LINE,
                        display_name="Mechanical fault",
                        category="FAILURE",
                        is_planned=False,
                    )
                ]
            ),
        ]
    )


@pytest.mark.asyncio
async def test_assign_reason_marks_the_row_manual():
    database = _assignment_database()

    assigned = await OeeResultRepository(database).assign_reason(
        11, "MECH_FAULT", note="Gearbox seized", assigned_by="a.operator"
    )

    assert assigned is not None
    assert assigned.event.reason_source == MANUAL_REASON_SOURCE
    assert assigned.display_name == "Mechanical fault"
    changed = bound(database.session_obj.statements[1])
    assert changed["reason_code"] == "MECH_FAULT"
    assert changed["reason_source"] == MANUAL_REASON_SOURCE
    assert changed["assigned_by"] == "a.operator"
    assert changed["note"] == "Gearbox seized"


@pytest.mark.asyncio
async def test_assign_reason_enqueues_a_recompute_for_that_one_shift():
    """
    Spec section 10: a reason's `is_planned` flag moves the interval between Unplanned Down
    and excluded time, so the number changes. The range is one second wide because
    `shift_windows` selects on `[from, to)` over the shift's *start*.
    """
    database = _assignment_database()

    await OeeResultRepository(database).assign_reason(11, "MECH_FAULT", assigned_by="a.operator")

    enqueued = bound(database.session_obj.statements[2])
    assert enqueued["oee_unit_id"] == 7
    assert enqueued["range_start"] == SHIFT_START
    assert enqueued["range_end"] == SHIFT_START + SINGLE_SHIFT_MARGIN
    assert enqueued["requested_by"] == "a.operator"
    assert "11" in enqueued["reason"]


@pytest.mark.asyncio
async def test_assign_reason_without_a_note_leaves_the_stored_note_alone():
    """An operator correcting only the code must not erase what somebody else typed."""
    database = _assignment_database(existing_note="Called maintenance at 09:05")

    assigned = await OeeResultRepository(database).assign_reason(11, "MECH_FAULT", assigned_by="a.operator")

    assert "note" not in bound(database.session_obj.statements[1])
    assert assigned.event.note == "Called maintenance at 09:05"


@pytest.mark.asyncio
async def test_assign_reason_is_null_for_an_unknown_event():
    """Null, not an error: acting on a list a recomputation has since replaced is normal."""
    database = FakeDatabase([FakeResult(["MECH_FAULT"]), FakeResult([])])

    assert await OeeResultRepository(database).assign_reason(999, "MECH_FAULT") is None
    assert len(database.session_obj.statements) == 2


@pytest.mark.asyncio
async def test_assign_reason_rejects_a_reason_code_nobody_authored():
    """
    A readable sentence instead of a driver-level foreign key violation naming a generated
    constraint - the same reason `AlertRuleSpec.validate` duplicates its CHECK constraints.
    """
    database = FakeDatabase([FakeResult([])])

    with pytest.raises(ValueError, match="NOT_A_REASON"):
        await OeeResultRepository(database).assign_reason(11, "NOT_A_REASON")

    assert len(database.session_obj.statements) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_oee_results.py -v -n 0`
Expected: FAIL — collection error, `ModuleNotFoundError: No module named 'uns_model.oee_results'`.

- [ ] **Step 3: Write the implementation**

Create `09_uns_model/src/uns_model/oee_results.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Reading OEE results, and the one write a human is allowed to make to them.

The seam for schema `oee`, kept apart from `OeeMasterDataRepository` because a shift
result is not master data: the model says how the line is rostered and rated, a result
says what actually happened. They share a database and nothing else.

It lives here rather than in `12_uns_oee` so the GraphQL service can read results
without depending on the engine's package. `07_uns_graphql` already depends on
`09_uns_model`; importing `uns_oee` would put an aiomqtt publisher and a scheduler into
the API container for the sake of three SELECTs.

Every join is spelled out and every grouping happens in Python. There is no
`relationship()` anywhere in `uns_model`, because under asyncio a lazy load on an
unloaded attribute raises `MissingGreenlet` in the resolver rather than in the query.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select, update

from uns_model.engine import Database
from uns_model.oee_tables import (
    DowntimeEvent,
    DowntimeReason,
    OeeUnit,
    RecomputeRequest,
    ShiftResult,
    ShiftResultProduct,
)
from uns_model.tables import Asset

LOGGER = logging.getLogger(__name__)

MANUAL_REASON_SOURCE = "manual"
"""One of `REASON_SOURCES`. `test_oee_results.py` fails if it stops being."""

SINGLE_SHIFT_MARGIN = timedelta(seconds=1)
"""How wide a recompute range has to be to name exactly one shift.

`shift_windows` selects windows whose *start* lies in `[range_start, range_end)`, so a
range of one second beginning at a shift's start picks out that shift and no other -
including the one that begins the moment it ends.
"""


@dataclass(frozen=True, slots=True)
class ParetoBucket:
    """One reason code's share of the downtime in a window."""

    reason_code: str
    display_name: str
    category: str
    is_planned: bool
    event_count: int
    total_seconds: float
    share: float


@dataclass(frozen=True, slots=True)
class ShiftResultRow:
    """One `oee.shift_result` with its Asset path and its per-product terms."""

    result: ShiftResult
    asset_path: str
    products: tuple[ShiftResultProduct, ...] = ()


@dataclass(frozen=True, slots=True)
class DowntimeEventRow:
    """One `oee.downtime_event` with the reason it is attributed to already resolved.

    `is_planned` travels with the event because it is what explains a changed OEE: it is
    the flag that moves an interval between Unplanned Down and excluded time.
    """

    event: DowntimeEvent
    asset_path: str
    display_name: str
    category: str
    is_planned: bool


def pareto_from_rows(rows: Sequence[tuple[str, str, str, bool, int, float]]) -> list[ParetoBucket]:
    """Grouped rows, ordered as a Pareto and given their share of the total.

    A pure function, so the one piece of this file that decides a number can be tested
    without a database. `share` is 0.0 rather than None when nothing was lost: a Pareto of
    zero downtime has no bars, and a null would make the console's percentage formatter the
    place that decides what to draw.

    Ties break on the reason code, so two reasons with the same lost time do not swap
    places between two refreshes of the same dashboard.
    """
    total = sum(float(seconds) for *_, seconds in rows)
    buckets = [
        ParetoBucket(
            reason_code=code,
            # The column defaults to '', and a nameless bar is unreadable.
            display_name=display_name or code,
            category=category,
            is_planned=bool(is_planned),
            event_count=int(event_count),
            total_seconds=float(seconds),
            share=float(seconds) / total if total > 0 else 0.0,
        )
        for code, display_name, category, is_planned, event_count, seconds in rows
    ]
    buckets.sort(key=lambda bucket: (-bucket.total_seconds, bucket.reason_code))
    return buckets


class OeeResultRepository:
    """Everything the GraphQL service does with schema `oee`.

    Callers get whole rows and never a `Session`. The engine remains the only writer of
    results: the one write here corrects a reason code and *queues* a recomputation, which
    is why `assign_reason` touches `oee.recompute_request` and never `oee.shift_result`.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ------------------------------------------------------------------- reads

    async def shift_results(
        self, asset_path: str, range_start: datetime, range_end: datetime
    ) -> list[ShiftResultRow]:
        """The results for one Asset whose shift began in `[range_start, range_end)`.

        Two statements rather than one outer join: a shift with four products would repeat
        the result's twenty-odd columns four times, and the products would still have to be
        grouped in Python afterwards either way.
        """
        statement = (
            select(ShiftResult, Asset.path)
            .join(OeeUnit, ShiftResult.oee_unit_id == OeeUnit.id)
            .join(Asset, OeeUnit.asset_id == Asset.id)
            .where(
                Asset.path == asset_path,
                ShiftResult.shift_start >= range_start,
                ShiftResult.shift_start < range_end,
            )
            .order_by(ShiftResult.shift_start)
        )
        async with self._database.session() as session:
            found = (await session.execute(statement)).all()
            if not found:
                return []
            products = (
                await session.scalars(
                    select(ShiftResultProduct)
                    .where(ShiftResultProduct.shift_result_id.in_([result.id for result, _ in found]))
                    .order_by(ShiftResultProduct.shift_result_id, ShiftResultProduct.product_code)
                )
            ).all()

        by_result: dict[int, list[ShiftResultProduct]] = {}
        for product in products:
            by_result.setdefault(product.shift_result_id, []).append(product)
        return [
            ShiftResultRow(result=result, asset_path=path, products=tuple(by_result.get(result.id, ())))
            for result, path in found
        ]

    async def downtime_events(
        self, asset_path: str, range_start: datetime, range_end: datetime
    ) -> list[DowntimeEventRow]:
        """The stops for one Asset that began in `[range_start, range_end)`, oldest first.

        Filtered on `started_at` and not on `shift_start` - the same column and the same
        predicate `downtime_pareto` uses - so an events table and a Pareto chart on one
        dashboard can never disagree about which stops are in the window.

        An inner join to `downtime_reason` is safe: `reason_code` is NOT NULL behind a
        RESTRICT foreign key, so an event with no reason cannot exist.
        """
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    _event_projection().where(
                        Asset.path == asset_path,
                        DowntimeEvent.started_at >= range_start,
                        DowntimeEvent.started_at < range_end,
                    )
                    .order_by(DowntimeEvent.started_at)
                )
            ).all()
        return _event_rows(rows)

    async def downtime_pareto(
        self, asset_path: str, range_start: datetime, range_end: datetime
    ) -> list[ParetoBucket]:
        """Lost time per reason code over a window, largest first.

        Aggregated in the database rather than by summing `downtime_events` in Python: a
        year of stops on a busy line is tens of thousands of rows, and the console wants the
        nine reason codes.
        """
        statement = (
            select(
                DowntimeEvent.reason_code,
                DowntimeReason.display_name,
                DowntimeReason.category,
                DowntimeReason.is_planned,
                func.count().label("event_count"),
                func.coalesce(func.sum(DowntimeEvent.duration_s), 0.0).label("total_seconds"),
            )
            .join(OeeUnit, DowntimeEvent.oee_unit_id == OeeUnit.id)
            .join(Asset, OeeUnit.asset_id == Asset.id)
            .join(DowntimeReason, DowntimeEvent.reason_code == DowntimeReason.code)
            .where(
                Asset.path == asset_path,
                DowntimeEvent.started_at >= range_start,
                DowntimeEvent.started_at < range_end,
            )
            .group_by(
                DowntimeEvent.reason_code,
                DowntimeReason.display_name,
                DowntimeReason.category,
                DowntimeReason.is_planned,
            )
        )
        async with self._database.session() as session:
            rows = (await session.execute(statement)).all()
        return pareto_from_rows([tuple(row) for row in rows])

    # ------------------------------------------------------------------- write

    async def assign_reason(
        self,
        event_id: int,
        reason_code: str,
        *,
        note: str | None = None,
        assigned_by: str | None = None,
    ) -> DowntimeEventRow | None:
        """Attribute a stop to a reason by hand, and queue that shift for recomputation.

        One transaction for both, because a corrected reason that never reached the queue
        would leave a downtime breakdown disagreeing with the OEE above it until somebody
        noticed and ran the CLI.

        `assigned_at` is `func.now()` and not a caller's timestamp: the console runs in a
        browser, and a wrong laptop clock must not be able to reorder who corrected what.

        Returns None when there is no such event. A console acting on a list of stops that a
        recomputation has since replaced is normal, not an error.
        """
        values: dict = {
            "reason_code": reason_code,
            "reason_source": MANUAL_REASON_SOURCE,
            "assigned_by": assigned_by,
            "assigned_at": func.now(),
        }
        if note is not None:
            # Omitted rather than defaulted to '': an operator correcting only the code must
            # not erase a note somebody else typed.
            values["note"] = note

        async with self._database.session() as session:
            known = (
                await session.scalars(select(DowntimeReason.code).where(DowntimeReason.code == reason_code))
            ).first()
            if known is None:
                # Checked here so the caller gets a sentence rather than a foreign key
                # violation naming a generated constraint.
                raise ValueError(f"{reason_code!r} is not an authored downtime reason code")

            changed = (
                await session.execute(
                    update(DowntimeEvent)
                    .where(DowntimeEvent.id == event_id)
                    .values(**values)
                    .returning(DowntimeEvent.oee_unit_id, DowntimeEvent.shift_start)
                )
            ).one_or_none()
            if changed is None:
                LOGGER.warning("No downtime event %s to assign reason %s to", event_id, reason_code)
                return None

            await session.execute(
                insert(RecomputeRequest).values(
                    oee_unit_id=changed.oee_unit_id,
                    range_start=changed.shift_start,
                    range_end=changed.shift_start + SINGLE_SHIFT_MARGIN,
                    reason=f"reason {reason_code} assigned to downtime event {event_id}",
                    requested_by=assigned_by,
                )
            )
            LOGGER.info(
                "Downtime event %s reassigned to %s by %s; shift %s queued for recompute",
                event_id,
                reason_code,
                assigned_by or "unknown",
                changed.shift_start.isoformat(),
            )
            rows = _event_rows(
                (await session.execute(_event_projection().where(DowntimeEvent.id == event_id))).all()
            )
        return rows[0] if rows else None


def _event_projection():
    """The five-column event select, shared by the read and the write-then-read.

    One definition, so the row the mutation returns has exactly the shape the query
    returns - a console must not get a different object depending on how it got there.
    """
    return (
        select(
            DowntimeEvent,
            Asset.path,
            DowntimeReason.display_name,
            DowntimeReason.category,
            DowntimeReason.is_planned,
        )
        .join(OeeUnit, DowntimeEvent.oee_unit_id == OeeUnit.id)
        .join(Asset, OeeUnit.asset_id == Asset.id)
        .join(DowntimeReason, DowntimeEvent.reason_code == DowntimeReason.code)
    )


def _event_rows(rows: Sequence) -> list[DowntimeEventRow]:
    """The five-column event projection as dataclasses. One shape, one mapping."""
    return [
        DowntimeEventRow(
            event=event,
            asset_path=asset_path,
            display_name=display_name or event.reason_code,
            category=category,
            is_planned=bool(is_planned),
        )
        for event, asset_path, display_name, category, is_planned in rows
    ]


__all__ = [
    "MANUAL_REASON_SOURCE",
    "SINGLE_SHIFT_MARGIN",
    "DowntimeEventRow",
    "OeeResultRepository",
    "ParetoBucket",
    "ShiftResultRow",
    "pareto_from_rows",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 09_uns_model/test/test_oee_results.py -v -n 0`
Expected: PASS (18 passed).

- [ ] **Step 5: Run the whole model suite and the linter**

Run: `uv run pytest 09_uns_model/test -q -m "not integrationtest"`
Expected: PASS. Nothing else imports `oee_results` yet, so this is a check that the new module does not break collection.

Run: `uv run ruff check 09_uns_model/src/uns_model/oee_results.py 09_uns_model/test/test_oee_results.py`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add 09_uns_model/src/uns_model/oee_results.py 09_uns_model/test/test_oee_results.py
git commit -m "feat(model): read OEE results and assign downtime reasons by hand"
```

---

### Task 19: The GraphQL surface — three reads and `assignDowntimeReason`

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/type/oee.py`
- Create: `07_uns_graphql/src/uns_graphql/queries/oee.py`
- Create: `07_uns_graphql/src/uns_graphql/mutations/oee.py`
- Modify: `07_uns_graphql/src/uns_graphql/uns_graphql_app.py:32-33`, `:42`, `:53-62`, `:66`, `:76-81`
- Test: `07_uns_graphql/test/type/test_oee.py`
- Test: `07_uns_graphql/test/queries/test_oee.py`
- Test: `07_uns_graphql/test/mutations/test_oee.py`

**Interfaces:**
- Consumes: `OeeResultRepository`, `ShiftResultRow`, `DowntimeEventRow`, `ParetoBucket` from Task 18; `OEE_STATUSES`, `REASON_SOURCES`, `ShiftResultProduct` from Task 2; `Database.shared("graphql")`.
- Produces: the schema this feature publishes —
  ```graphql
  oeeShiftResults(assetPath: String!, from: DateTime!, to: DateTime!): [OeeShiftResult!]!
  downtimeEvents(assetPath: String!, from: DateTime!, to: DateTime!): [DowntimeEvent!]!
  downtimePareto(assetPath: String!, from: DateTime!, to: DateTime!): [DowntimeParetoBucket!]!
  assignDowntimeReason(eventId: ID!, reasonCode: String!, note: String, assignedBy: String): DowntimeEvent!
  ```

**Why the enums are written out by hand.** `type/alert_rule.py` already establishes this: a GraphQL schema is a published contract, and an enum generated from `uns_model` would change shape because somebody edited a CHECK constraint. `test/type/test_oee.py` compares each enum against its vocabulary tuple in both directions, so the two copies cannot drift.

**Why the Python class is `DowntimeEventType` but the GraphQL type is `DowntimeEvent`.** Spec §10 names the return type `DowntimeEvent!`, and `uns_model.oee_tables.DowntimeEvent` is the ORM class the same module has to import. `@strawberry.type(name="DowntimeEvent")` publishes the spec's name from a Python class that does not collide — the same problem `AlertRule`/`AlertRuleType` already has, solved the same way except that here the published name is pinned.

**How `from` and `to` are spelled.** `from` is a Python keyword, so the resolver parameters are `range_start` and `range_end` and each carries `Annotated[datetime, strawberry.argument(name="from")]`. The existing historian queries dodged this by calling theirs `fromDatetime`/`toDatetime`; that is not done here, because spec §10 writes the signature down and a published argument name is not a detail to improvise. `test_the_range_arguments_are_named_from_and_to` asserts it through introspection rather than against printed SDL, so a Strawberry upgrade that reformats the schema cannot break it.

**One deliberate addition to the spec's signature: `assignedBy: String`.** Spec §10 gives the signature as three arguments but also requires the mutation to set `assigned_by`. Those cannot both hold: this platform has no authentication anywhere, so there is no request identity to read. The argument is added as an optional fourth, which leaves the spec's three-argument call valid, and its description says plainly that the value is attested by the caller and not authenticated. Recording an unverified name is still worth more than recording nothing — "who says they changed this" is what an auditor asks first.

**Why an unknown event is an error here and `None` in the repository.** The return type is `DowntimeEvent!`, so null is not expressible. It is also the right answer: an operator who has just clicked a reason onto a stop must be told the click did nothing, whereas a repository has callers that legitimately treat a missing row as an empty result.

- [ ] **Step 1: Write the failing type test**

Create `07_uns_graphql/test/type/test_oee.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

The OEE vocabularies are written down twice: once as CHECK constraints in
`uns_model.oee_tables` and once as GraphQL enums. That is deliberate - a published
schema should not change shape because somebody edited a database constraint - and
these tests are what keeps the two copies honest.
"""

from datetime import UTC, datetime
from enum import Enum

import pytest
from uns_model.oee_results import DowntimeEventRow, ParetoBucket, ShiftResultRow
from uns_model.oee_tables import (
    OEE_STATUSES,
    REASON_SOURCES,
    DowntimeEvent,
    ShiftResult,
    ShiftResultProduct,
)

from uns_graphql.type.oee import (
    DowntimeEventType,
    DowntimeParetoBucket,
    OeeShiftResult,
    OeeStatus,
    ReasonSource,
)

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "graphql_enum, vocabulary",
    [
        (OeeStatus, OEE_STATUSES),
        (ReasonSource, REASON_SOURCES),
    ],
)
def test_enums_match_the_database_vocabulary(graphql_enum: type[Enum], vocabulary: tuple[str, ...]):
    """
    A value the database accepts must be expressible in the schema, and vice versa.

    Fails both ways round on purpose: an enum member the CHECK constraint rejects is a
    query that can never match, and a stored status with no enum member is a shift
    result the console cannot read back at all.
    """
    assert {member.value for member in graphql_enum} == set(vocabulary)


@pytest.mark.parametrize("vocabulary", [OEE_STATUSES, REASON_SOURCES])
def test_vocabularies_have_no_duplicates(vocabulary: tuple[str, ...]):
    """A duplicate would make the set comparison above pass while the CHECK body repeats itself."""
    assert len(vocabulary) == len(set(vocabulary))


def _result(**overrides) -> ShiftResult:
    values = {
        "id": 1,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "shift_end": SHIFT_END,
        "shift_label": "Morning",
        "loading_time_s": 27000.0,
        "run_time_s": 24300.0,
        "planned_down_s": 1800.0,
        "unplanned_down_s": 2700.0,
        "good_count": 4800.0,
        "reject_count": 200.0,
        "total_count": 5000.0,
        "availability": 0.9,
        "performance": 0.85,
        "performance_raw": 1.04,
        "quality": 0.96,
        "oee": 0.7344,
        "status": "OK",
        "revision": 2,
        "input_fingerprint": "1200:2026-08-31T14:00:00+00:00",
        "computed_at": datetime(2026, 8, 31, 14, 20, tzinfo=UTC),
        "published_at": datetime(2026, 8, 31, 14, 20, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return ShiftResult(**values)


def _event(**overrides) -> DowntimeEvent:
    values = {
        "id": 11,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "MECH_FAULT",
        "reason_source": "manual",
        "assigned_by": "a.operator",
        "assigned_at": datetime(2026, 8, 31, 15, 0, tzinfo=UTC),
        "note": "Gearbox seized",
    }
    values.update(overrides)
    return DowntimeEvent(**values)


def test_from_row_maps_every_shift_result_field():
    row = ShiftResultRow(result=_result(), asset_path=LINE, products=())

    result = OeeShiftResult.from_row(row)

    assert result.asset_path == LINE
    assert result.shift_start == SHIFT_START
    assert result.shift_end == SHIFT_END
    assert result.shift_label == "Morning"
    assert result.loading_time_s == pytest.approx(27000.0)
    assert result.run_time_s == pytest.approx(24300.0)
    assert result.planned_down_s == pytest.approx(1800.0)
    assert result.unplanned_down_s == pytest.approx(2700.0)
    assert result.good_count == pytest.approx(4800.0)
    assert result.reject_count == pytest.approx(200.0)
    assert result.total_count == pytest.approx(5000.0)
    assert result.availability == pytest.approx(0.9)
    assert result.performance == pytest.approx(0.85)
    assert result.performance_raw == pytest.approx(1.04)
    assert result.quality == pytest.approx(0.96)
    assert result.oee == pytest.approx(0.7344)
    assert result.status is OeeStatus.OK
    assert result.revision == 2
    assert result.computed_at == row.result.computed_at
    assert result.published_at == row.result.published_at


def test_a_null_factor_stays_null():
    """
    Spec section 8.1: a shift with no Loading Time has no Availability. Rendering it as
    0.0 would put a catastrophic shift on the trend that never happened.
    """
    row = ShiftResultRow(
        result=_result(status="NO_LOADING_TIME", availability=None, performance=None, quality=None, oee=None),
        asset_path=LINE,
    )

    result = OeeShiftResult.from_row(row)

    assert (result.availability, result.performance, result.quality, result.oee) == (None, None, None, None)
    assert result.status is OeeStatus.NO_LOADING_TIME


def test_the_per_product_terms_are_carried_through():
    """Performance is a sum over products, so a mixed shift's terms have to be readable."""
    row = ShiftResultRow(
        result=_result(),
        asset_path=LINE,
        products=(
            ShiftResultProduct(
                id=1,
                shift_result_id=1,
                product_code="MDI-01",
                good_count=2900.0,
                reject_count=100.0,
                total_count=3000.0,
                ideal_cycle_time_s=4.0,
            ),
            ShiftResultProduct(
                id=2,
                shift_result_id=1,
                product_code="MDI-02",
                good_count=1900.0,
                reject_count=100.0,
                total_count=2000.0,
                ideal_cycle_time_s=None,
            ),
        ),
    )

    products = OeeShiftResult.from_row(row).products

    assert [product.product_code for product in products] == ["MDI-01", "MDI-02"]
    assert products[0].ideal_cycle_time_s == pytest.approx(4.0)
    assert products[1].ideal_cycle_time_s is None


def test_a_single_product_line_has_an_empty_product_list():
    """Not null: the console iterates it, and a null list is an extra branch for no reason."""
    assert OeeShiftResult.from_row(ShiftResultRow(result=_result(), asset_path=LINE)).products == []


def test_downtime_event_from_row_carries_the_resolved_reason():
    row = DowntimeEventRow(
        event=_event(),
        asset_path=LINE,
        display_name="Mechanical fault",
        category="FAILURE",
        is_planned=False,
    )

    event = DowntimeEventType.from_row(row)

    assert event.id == "11"
    assert event.asset_path == LINE
    assert event.shift_start == SHIFT_START
    assert event.started_at == row.event.started_at
    assert event.ended_at == row.event.ended_at
    assert event.duration_s == pytest.approx(2700.0)
    assert event.state_value == "ABORTED"
    assert event.reason_code == "MECH_FAULT"
    assert event.reason_display_name == "Mechanical fault"
    assert event.reason_category == "FAILURE"
    assert event.is_planned is False
    assert event.reason_source is ReasonSource.MANUAL
    assert event.assigned_by == "a.operator"
    assert event.assigned_at == row.event.assigned_at
    assert event.note == "Gearbox seized"


def test_an_auto_classified_event_has_no_assignee():
    row = DowntimeEventRow(
        event=_event(reason_code="UNCLASSIFIED", reason_source="auto", assigned_by=None, assigned_at=None, note=""),
        asset_path=LINE,
        display_name="Unclassified",
        category="",
        is_planned=False,
    )

    event = DowntimeEventType.from_row(row)

    assert event.reason_source is ReasonSource.AUTO
    assert event.assigned_by is None
    assert event.assigned_at is None


def test_pareto_bucket_from_bucket():
    bucket = ParetoBucket("MECH_FAULT", "Mechanical fault", "FAILURE", False, 5, 5400.0, 0.6)

    published = DowntimeParetoBucket.from_bucket(bucket)

    assert published.reason_code == "MECH_FAULT"
    assert published.display_name == "Mechanical fault"
    assert published.category == "FAILURE"
    assert published.is_planned is False
    assert published.event_count == 5
    assert published.total_seconds == pytest.approx(5400.0)
    assert published.share == pytest.approx(0.6)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 07_uns_graphql/test/type/test_oee.py -v -n 0`
Expected: FAIL — collection error, `ModuleNotFoundError: No module named 'uns_graphql.type.oee'`.

- [ ] **Step 3: Write the types**

Create `07_uns_graphql/src/uns_graphql/type/oee.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

GraphQL types for computed OEE, held in schema `oee`.

The enums are spelled out rather than generated from `uns_model.oee_tables`, because a
GraphQL schema is a published contract and a generated enum changes shape without
anybody reviewing it. `test/type/test_oee.py` fails if the two drift.

Every ratio is nullable. Spec section 8.1: a shift with no Loading Time has no
Availability - it did not achieve 0% - and a schema that could not say so would force
the console to invent a number.
"""

import logging
from datetime import datetime
from enum import Enum

import strawberry
from uns_model.oee_results import DowntimeEventRow, ParetoBucket, ShiftResultRow
from uns_model.oee_tables import ShiftResultProduct

LOGGER = logging.getLogger(__name__)


@strawberry.enum(description="Whether the shift's numbers are usable, and why not when they are not.")
class OeeStatus(Enum):
    OK = "OK"
    NO_LOADING_TIME = "NO_LOADING_TIME"
    NO_PRODUCTION = "NO_PRODUCTION"
    MISSING_IDEAL_CYCLE_TIME = "MISSING_IDEAL_CYCLE_TIME"
    NO_INPUT_DATA = "NO_INPUT_DATA"


@strawberry.enum(description="Whether a stop was classified by the engine or corrected by a person.")
class ReasonSource(Enum):
    AUTO = "auto"
    MANUAL = "manual"


@strawberry.type(description="One product's counts and rated cycle time within a shift.")
class OeeShiftProduct:
    """
    Stored per product because Performance is a sum over products.

    A mixed shift's number cannot be re-derived from the totals once the product mix is
    gone, so the terms are published rather than only the result.
    """

    product_code: str = strawberry.field(description="The value the line published, e.g. a recipe id.")
    good_count: float
    reject_count: float
    total_count: float
    ideal_cycle_time_s: float | None = strawberry.field(
        description="Seconds per unit at the designed rate. Null when none was authored, "
        "which sets MISSING_IDEAL_CYCLE_TIME on the shift."
    )

    @classmethod
    def from_row(cls, product: ShiftResultProduct) -> "OeeShiftProduct":
        return cls(
            product_code=product.product_code,
            good_count=product.good_count,
            reject_count=product.reject_count,
            total_count=product.total_count,
            ideal_cycle_time_s=product.ideal_cycle_time_s,
        )


@strawberry.type(description="Availability x Performance x Quality for one closed shift on one Asset.")
class OeeShiftResult:
    """
    The current result for a shift. Superseded numbers are kept in
    `oee.shift_result_revision` and are deliberately not published: a dashboard reads
    one row per shift, and `revision` is what tells it the number has been restated.
    """

    asset_path: str = strawberry.field(description="The Line the number is reported for.")
    shift_start: datetime
    shift_end: datetime
    shift_label: str

    loading_time_s: float = strawberry.field(description="Scheduled time less planned stops and exceptions.")
    run_time_s: float = strawberry.field(description="Time in a producing state, measured over the interval union.")
    planned_down_s: float
    unplanned_down_s: float

    good_count: float
    reject_count: float
    total_count: float

    availability: float | None = strawberry.field(description="Run Time / Loading Time. Null when undefined.")
    performance: float | None = strawberry.field(description="Clamped at 1.0. Null when undefined.")
    performance_raw: float | None = strawberry.field(
        description="Performance before the clamp. Above 1 means the ideal cycle time is wrong "
        "or a stop was missed, and this is the only evidence of that."
    )
    quality: float | None = strawberry.field(description="Good Count / Total Count. Null when undefined.")
    oee: float | None

    status: OeeStatus
    revision: int = strawberry.field(description="Increments when late data restated the shift.")
    computed_at: datetime | None = None
    published_at: datetime | None = strawberry.field(
        default=None, description="When the result reached MQTT. Null means it has not yet."
    )
    products: list[OeeShiftProduct] = strawberry.field(
        default_factory=list, description="Empty on a line that publishes no recipe."
    )

    @classmethod
    def from_row(cls, row: ShiftResultRow) -> "OeeShiftResult":
        result = row.result
        return cls(
            asset_path=row.asset_path,
            shift_start=result.shift_start,
            shift_end=result.shift_end,
            shift_label=result.shift_label,
            loading_time_s=result.loading_time_s,
            run_time_s=result.run_time_s,
            planned_down_s=result.planned_down_s,
            unplanned_down_s=result.unplanned_down_s,
            good_count=result.good_count,
            reject_count=result.reject_count,
            total_count=result.total_count,
            # Passed straight through, never coalesced: see the module docstring.
            availability=result.availability,
            performance=result.performance,
            performance_raw=result.performance_raw,
            quality=result.quality,
            oee=result.oee,
            status=OeeStatus(result.status),
            revision=result.revision,
            computed_at=result.computed_at,
            published_at=result.published_at,
            products=[OeeShiftProduct.from_row(product) for product in row.products],
        )


@strawberry.type(name="DowntimeEvent", description="One stop, with the reason it is attributed to.")
class DowntimeEventType:
    """
    Published as `DowntimeEvent` (spec section 10) from a Python class that does not
    collide with the ORM class of the same name, which this module's dependencies import.

    `isPlanned` travels with the event because it is what explains a changed OEE: it is
    the flag that moves the interval between Unplanned Down and excluded time.
    """

    id: strawberry.ID
    asset_path: str
    shift_start: datetime = strawberry.field(description="The shift this stop is counted against.")
    started_at: datetime
    ended_at: datetime
    duration_s: float
    state_value: str = strawberry.field(description="The published state that held for the whole stop, e.g. 'ABORTED'.")

    reason_code: str
    reason_display_name: str
    reason_category: str
    is_planned: bool
    reason_source: ReasonSource
    assigned_by: str | None = None
    assigned_at: datetime | None = None
    note: str = ""

    @classmethod
    def from_row(cls, row: DowntimeEventRow) -> "DowntimeEventType":
        event = row.event
        return cls(
            id=strawberry.ID(str(event.id)),
            asset_path=row.asset_path,
            shift_start=event.shift_start,
            started_at=event.started_at,
            ended_at=event.ended_at,
            duration_s=event.duration_s,
            state_value=event.state_value,
            reason_code=event.reason_code,
            reason_display_name=row.display_name,
            reason_category=row.category,
            is_planned=row.is_planned,
            reason_source=ReasonSource(event.reason_source),
            assigned_by=event.assigned_by,
            assigned_at=event.assigned_at,
            note=event.note,
        )


@strawberry.type(description="One reason code's share of the downtime in a window, largest first.")
class DowntimeParetoBucket:
    reason_code: str
    display_name: str
    category: str
    is_planned: bool
    event_count: int
    total_seconds: float
    share: float = strawberry.field(
        description="Fraction of the window's total downtime, 0..1. Zero when nothing was lost."
    )

    @classmethod
    def from_bucket(cls, bucket: ParetoBucket) -> "DowntimeParetoBucket":
        return cls(
            reason_code=bucket.reason_code,
            display_name=bucket.display_name,
            category=bucket.category,
            is_planned=bucket.is_planned,
            event_count=bucket.event_count,
            total_seconds=bucket.total_seconds,
            share=bucket.share,
        )
```

- [ ] **Step 4: Run the type test to verify it passes**

Run: `uv run pytest 07_uns_graphql/test/type/test_oee.py -v -n 0`
Expected: PASS (11 passed).

- [ ] **Step 5: Write the failing query test**

Create `07_uns_graphql/test/queries/test_oee.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Reading OEE results through the schema, with the repository replaced.

Executed against the real schema rather than by calling the resolvers, because the
schema is what a dashboard talks to: an argument renamed here is a broken dashboard
even though every resolver still passes its own test. What the repository does with a
live Postgres is `09_uns_model`'s integration test's job.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uns_model.oee_results import DowntimeEventRow, ParetoBucket, ShiftResultRow
from uns_model.oee_tables import DowntimeEvent, ShiftResult

from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.queries.oee._repository"

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def _result_row(**overrides) -> ShiftResultRow:
    values = {
        "id": 1,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "shift_end": SHIFT_END,
        "shift_label": "Morning",
        "loading_time_s": 27000.0,
        "run_time_s": 24300.0,
        "planned_down_s": 1800.0,
        "unplanned_down_s": 2700.0,
        "good_count": 4800.0,
        "reject_count": 200.0,
        "total_count": 5000.0,
        "availability": 0.9,
        "performance": 0.85,
        "performance_raw": 0.85,
        "quality": 0.96,
        "oee": 0.7344,
        "status": "OK",
        "revision": 1,
        "input_fingerprint": "",
        "computed_at": datetime(2026, 8, 31, 14, 20, tzinfo=UTC),
        "published_at": None,
    }
    values.update(overrides)
    return ShiftResultRow(result=ShiftResult(**values), asset_path=LINE)


def _event_row(**overrides) -> DowntimeEventRow:
    values = {
        "id": 11,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "MECH_FAULT",
        "reason_source": "auto",
        "assigned_by": None,
        "assigned_at": None,
        "note": "",
    }
    values.update(overrides)
    return DowntimeEventRow(
        event=DowntimeEvent(**values),
        asset_path=LINE,
        display_name="Mechanical fault",
        category="FAILURE",
        is_planned=False,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_the_range_arguments_are_named_from_and_to():
    """
    Spec section 10 writes the signature down. Asserted by introspection rather than
    against printed SDL, so a Strawberry upgrade that reformats the schema cannot
    break a test that is about the contract.
    """
    result = await UNSGraphql.schema.execute("""{ __type(name: "Query") { fields { name args { name } } } }""")

    assert result.errors is None
    arguments = {field["name"]: [arg["name"] for arg in field["args"]] for field in result.data["__type"]["fields"]}
    assert arguments["oeeShiftResults"] == ["assetPath", "from", "to"]
    assert arguments["downtimeEvents"] == ["assetPath", "from", "to"]
    assert arguments["downtimePareto"] == ["assetPath", "from", "to"]


@pytest.mark.asyncio(loop_scope="function")
async def test_oee_shift_results_returns_what_the_repository_holds():
    repository = AsyncMock()
    repository.shift_results.return_value = [_result_row()]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                assetPath shiftLabel availability performance quality oee status revision publishedAt
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert result.data["oeeShiftResults"] == [
        {
            "assetPath": LINE,
            "shiftLabel": "Morning",
            "availability": pytest.approx(0.9),
            "performance": pytest.approx(0.85),
            "quality": pytest.approx(0.96),
            "oee": pytest.approx(0.7344),
            "status": "OK",
            "revision": 1,
            "publishedAt": None,
        }
    ]


@pytest.mark.asyncio(loop_scope="function")
async def test_oee_shift_results_passes_the_parsed_range_through():
    repository = AsyncMock()
    repository.shift_results.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                shiftLabel
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    repository.shift_results.assert_awaited_once_with(
        LINE, SHIFT_START, datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_a_null_factor_is_null_in_the_response():
    """A shift with no Loading Time must not arrive at the dashboard as 0%."""
    repository = AsyncMock()
    repository.shift_results.return_value = [
        _result_row(status="NO_LOADING_TIME", availability=None, performance=None, quality=None, oee=None)
    ]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                status availability oee
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert result.data["oeeShiftResults"][0] == {
        "status": "NO_LOADING_TIME",
        "availability": None,
        "oee": None,
    }


@pytest.mark.asyncio(loop_scope="function")
async def test_an_asset_with_no_results_is_an_empty_list():
    """Not an error: a line whose first shift has not closed yet is normal."""
    repository = AsyncMock()
    repository.shift_results.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              oeeShiftResults(assetPath: "nope", from: "2026-08-31T06:00:00+00:00", to: "2026-09-01T06:00:00+00:00") {
                oee
              }
            }
            """
        )

    assert result.errors is None
    assert result.data["oeeShiftResults"] == []


@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_events_expose_the_resolved_reason():
    repository = AsyncMock()
    repository.downtime_events.return_value = [_event_row()]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              downtimeEvents(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-08-31T14:00:00+00:00") {
                id durationS stateValue reasonCode reasonDisplayName reasonCategory isPlanned reasonSource note
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert result.data["downtimeEvents"] == [
        {
            "id": "11",
            "durationS": pytest.approx(2700.0),
            "stateValue": "ABORTED",
            "reasonCode": "MECH_FAULT",
            "reasonDisplayName": "Mechanical fault",
            "reasonCategory": "FAILURE",
            "isPlanned": False,
            "reasonSource": "AUTO",
            "note": "",
        }
    ]
    repository.downtime_events.assert_awaited_once_with(LINE, SHIFT_START, SHIFT_END)


@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_pareto_returns_the_buckets_in_order():
    repository = AsyncMock()
    repository.downtime_pareto.return_value = [
        ParetoBucket("MECH_FAULT", "Mechanical fault", "FAILURE", False, 5, 5400.0, 0.6),
        ParetoBucket("CHANGEOVER", "Changeover", "PLANNED", True, 2, 3600.0, 0.4),
    ]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            {
              downtimePareto(assetPath: "%s", from: "2026-08-31T06:00:00+00:00", to: "2026-08-31T14:00:00+00:00") {
                reasonCode displayName isPlanned eventCount totalSeconds share
              }
            }
            """
            % LINE
        )

    assert result.errors is None
    assert [bucket["reasonCode"] for bucket in result.data["downtimePareto"]] == ["MECH_FAULT", "CHANGEOVER"]
    assert result.data["downtimePareto"][0]["eventCount"] == 5
    assert result.data["downtimePareto"][0]["share"] == pytest.approx(0.6)
    assert result.data["downtimePareto"][1]["isPlanned"] is True
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest 07_uns_graphql/test/queries/test_oee.py -v -n 0`
Expected: FAIL — collection error, `ModuleNotFoundError: No module named 'uns_graphql.queries.oee'`.

- [ ] **Step 7: Write the queries**

Create `07_uns_graphql/src/uns_graphql/queries/oee.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

GraphQL queries for computed OEE (spec section 10).

Read from `oee.shift_result` and `oee.downtime_event`, never from `uns_metrics`. The
engine has already resolved the shift calendar, the interval union, the counter resets
and the product mix; a dashboard that recomputed any of that from raw samples would be
a second implementation of the arithmetic, free to disagree with the first.

The publishing side is `12_uns_oee`, which puts the same numbers on
`<line>/KPI/ShiftOee`. This is the query path for a range of shifts, which MQTT cannot
answer.
"""

import logging
from datetime import datetime
from typing import Annotated

import strawberry
from uns_model.engine import Database
from uns_model.oee_results import OeeResultRepository

from uns_graphql.type.oee import DowntimeEventType, DowntimeParetoBucket, OeeShiftResult

LOGGER = logging.getLogger(__name__)

# `from` is a Python keyword, so the resolver parameters are named for what they are and
# the published argument names are set explicitly. Spec section 10 fixes them as
# `from`/`to`; test/queries/test_oee.py pins them by introspection.
FromArgument = Annotated[datetime, strawberry.argument(name="from")]
ToArgument = Annotated[datetime, strawberry.argument(name="to")]


def _repository() -> OeeResultRepository:
    return OeeResultRepository(Database.shared("graphql"))


@strawberry.type(description="Query computed OEE results and their downtime breakdown")
class Query:
    """All read access to schema `oee`."""

    @strawberry.field(
        description="Shift results for one Asset whose shift began in [from, to), oldest first. "
        "Ratios are null when undefined - a shift with no Loading Time has no Availability."
    )
    async def oee_shift_results(
        self, asset_path: str, range_start: FromArgument, range_end: ToArgument
    ) -> list[OeeShiftResult]:
        rows = await _repository().shift_results(asset_path, range_start, range_end)
        return [OeeShiftResult.from_row(row) for row in rows]

    @strawberry.field(
        description="Stops for one Asset that began in [from, to), oldest first, each with its "
        "reason code resolved. Bounded the same way downtimePareto is, so the two agree."
    )
    async def downtime_events(
        self, asset_path: str, range_start: FromArgument, range_end: ToArgument
    ) -> list[DowntimeEventType]:
        rows = await _repository().downtime_events(asset_path, range_start, range_end)
        return [DowntimeEventType.from_row(row) for row in rows]

    @strawberry.field(
        description="Lost time per reason code over [from, to), largest first. Always sums to the "
        "window's total downtime: an unmapped state is UNCLASSIFIED, never null."
    )
    async def downtime_pareto(
        self, asset_path: str, range_start: FromArgument, range_end: ToArgument
    ) -> list[DowntimeParetoBucket]:
        buckets = await _repository().downtime_pareto(asset_path, range_start, range_end)
        return [DowntimeParetoBucket.from_bucket(bucket) for bucket in buckets]

    @classmethod
    async def on_shutdown(cls):
        """
        Nothing to do: the engine is shared with the Asset Model queries, which dispose
        it. Kept so every Query mixin has the same shape.
        """
```

- [ ] **Step 8: Wire the queries into the schema**

In `07_uns_graphql/src/uns_graphql/uns_graphql_app.py`, change the import at line 33 from

```python
from uns_graphql.queries import alert_rule, asset, graph, historian
```

to

```python
from uns_graphql.queries import alert_rule, asset, graph, historian, oee
```

Change the `Query` declaration at line 42 from

```python
class Query(historian.Query, graph.Query, asset.Query, alert_rule.Query):
```

to

```python
class Query(historian.Query, graph.Query, asset.Query, alert_rule.Query, oee.Query):
```

and add the OEE shutdown call inside the existing `finally`, so the block reads:

```python
    @classmethod
    async def on_shutdown(cls):
        """
        Clean up connections, db pools etc.
        """
        try:
            await historian.Query.on_shutdown()
        finally:
            try:
                await graph.Query.on_shutdown()
            finally:
                # Last: this disposes the engine that the Asset Model, the Alert Rules
                # and the OEE results share.
                await alert_rule.Query.on_shutdown()
                await oee.Query.on_shutdown()
                await asset.Query.on_shutdown()
```

- [ ] **Step 9: Run the query test to verify it passes**

Run: `uv run pytest 07_uns_graphql/test/queries/test_oee.py -v -n 0`
Expected: PASS (7 passed).

- [ ] **Step 10: Write the failing mutation test**

Create `07_uns_graphql/test/mutations/test_oee.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Correcting a downtime reason through the schema, with the repository replaced.

This is the second write this service has ever exposed, and the only one that touches
plant data. The tests pin down what it is allowed to be: it corrects an attribution and
queues a recomputation. It must never become a way to edit an OEE number directly.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uns_model.oee_results import DowntimeEventRow
from uns_model.oee_tables import DowntimeEvent

from uns_graphql.uns_graphql_app import UNSGraphql

REPOSITORY = "uns_graphql.mutations.oee._repository"

LINE = "CovestroAG/Dormagen/Production/Line1"
SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)

ASSIGN = """
    mutation Assign($eventId: ID!, $reasonCode: String!, $note: String, $assignedBy: String) {
        assignDowntimeReason(eventId: $eventId, reasonCode: $reasonCode, note: $note, assignedBy: $assignedBy) {
            id reasonCode reasonSource isPlanned assignedBy note
        }
    }
"""


def _assigned(**overrides) -> DowntimeEventRow:
    values = {
        "id": 11,
        "oee_unit_id": 7,
        "shift_start": SHIFT_START,
        "started_at": datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 31, 9, 45, tzinfo=UTC),
        "duration_s": 2700.0,
        "state_value": "ABORTED",
        "reason_code": "CHANGEOVER",
        "reason_source": "manual",
        "assigned_by": "a.operator",
        "assigned_at": datetime(2026, 8, 31, 15, 0, tzinfo=UTC),
        "note": "Product change to MDI-02",
    }
    values.update(overrides)
    return DowntimeEventRow(
        event=DowntimeEvent(**values),
        asset_path=LINE,
        display_name="Changeover",
        category="PLANNED",
        is_planned=True,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_assign_downtime_reason_returns_the_event_as_stored():
    repository = AsyncMock()
    repository.assign_reason.return_value = _assigned()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN,
            variable_values={
                "eventId": "11",
                "reasonCode": "CHANGEOVER",
                "note": "Product change to MDI-02",
                "assignedBy": "a.operator",
            },
        )

    assert result.errors is None
    assert result.data["assignDowntimeReason"] == {
        "id": "11",
        "reasonCode": "CHANGEOVER",
        "reasonSource": "MANUAL",
        "isPlanned": True,
        "assignedBy": "a.operator",
        "note": "Product change to MDI-02",
    }
    repository.assign_reason.assert_awaited_once_with(
        11, "CHANGEOVER", note="Product change to MDI-02", assigned_by="a.operator"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_the_event_id_reaches_the_repository_as_a_number():
    """The schema publishes ID, which is a string. The primary key is a BIGINT."""
    repository = AsyncMock()
    repository.assign_reason.return_value = _assigned()

    with patch(REPOSITORY, return_value=repository):
        await UNSGraphql.schema.execute(
            ASSIGN, variable_values={"eventId": "11", "reasonCode": "CHANGEOVER"}
        )

    assert repository.assign_reason.await_args.args == (11, "CHANGEOVER")


@pytest.mark.asyncio(loop_scope="function")
async def test_omitting_the_note_leaves_the_stored_note_alone():
    """
    None rather than '': the repository omits the column entirely when the note is
    None, so an operator correcting only the code cannot erase somebody else's note.
    """
    repository = AsyncMock()
    repository.assign_reason.return_value = _assigned(note="Called maintenance at 09:05")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN, variable_values={"eventId": "11", "reasonCode": "CHANGEOVER"}
        )

    assert result.errors is None
    assert repository.assign_reason.await_args.kwargs == {"note": None, "assigned_by": None}
    assert result.data["assignDowntimeReason"]["note"] == "Called maintenance at 09:05"


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unknown_event_is_an_error_and_not_a_null():
    """The return type is non-null, and an operator whose click did nothing must be told."""
    repository = AsyncMock()
    repository.assign_reason.return_value = None

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN, variable_values={"eventId": "999", "reasonCode": "CHANGEOVER"}
        )

    assert result.errors
    assert "999" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unauthored_reason_code_reaches_the_caller_as_a_message():
    """The repository's ValueError, not a driver-level foreign key violation."""
    repository = AsyncMock()
    repository.assign_reason.side_effect = ValueError("'NOT_A_REASON' is not an authored downtime reason code")

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN, variable_values={"eventId": "11", "reasonCode": "NOT_A_REASON"}
        )

    assert result.errors
    assert "NOT_A_REASON" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_an_event_id_that_is_not_a_number_is_rejected_before_the_database():
    repository = AsyncMock()

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            ASSIGN, variable_values={"eventId": "eleven", "reasonCode": "CHANGEOVER"}
        )

    assert result.errors
    assert "eleven" in result.errors[0].message
    repository.assign_reason.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_the_schema_exposes_no_other_way_to_write_to_the_oee_schema():
    """
    A shift result is computed, never edited. If a second OEE mutation ever appears,
    this test is the place that argues about it.
    """
    result = await UNSGraphql.schema.execute("""{ __type(name: "Mutation") { fields { name } } }""")

    assert result.errors is None
    names = [field["name"] for field in result.data["__type"]["fields"]]
    assert [name for name in names if "owntime" in name or "Oee" in name or "oee" in name] == [
        "assignDowntimeReason"
    ]
```

- [ ] **Step 11: Run it to verify it fails**

Run: `uv run pytest 07_uns_graphql/test/mutations/test_oee.py -v -n 0`
Expected: FAIL — collection error, `ModuleNotFoundError: No module named 'uns_graphql.mutations.oee'`.

- [ ] **Step 12: Write the mutation**

Create `07_uns_graphql/src/uns_graphql/mutations/oee.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

The one write this service makes to plant data: which reason a stop is attributed to.

An OEE number is computed, never edited. What a human legitimately knows better than
the engine is *why* a machine stopped - the engine only ever saw a state code. So this
mutation corrects the attribution and queues a recomputation, and the engine remains
the only writer of `oee.shift_result` (ADR-0005 for why the write lives in GraphQL at
all: the console is a static bundle with no backend of its own).

Reassignment can change the OEE, because a reason's `is_planned` flag moves the
interval between Unplanned Down and excluded time. That is correct behaviour, and it is
why this enqueues rather than merely editing a label.
"""

import logging
from typing import Annotated

import strawberry
from uns_model.engine import Database
from uns_model.oee_results import OeeResultRepository

from uns_graphql.type.oee import DowntimeEventType

LOGGER = logging.getLogger(__name__)


def _repository() -> OeeResultRepository:
    return OeeResultRepository(Database.shared("graphql"))


@strawberry.type(description="Correct which reason a stop is attributed to")
class Mutation:
    """All write access to schema `oee`. One field, deliberately."""

    @strawberry.mutation(
        description="Attribute a stop to a reason code by hand and queue that shift for "
        "recomputation. The stored reason becomes MANUAL, which the engine never overwrites. "
        "Errors when there is no such event or the reason code is not authored."
    )
    async def assign_downtime_reason(
        self,
        event_id: strawberry.ID,
        reason_code: str,
        note: str | None = None,
        # `strawberry.argument`, not `strawberry.field`: this is a resolver argument, and
        # `field` as a default value would be published as a String with a broken default.
        assigned_by: Annotated[
            str | None,
            strawberry.argument(
                description="Who says they made the correction. Attested by the caller, not "
                "authenticated: this platform has no authentication anywhere."
            ),
        ] = None,
    ) -> DowntimeEventType:
        try:
            numeric_id = int(event_id)
        except (TypeError, ValueError) as ex:
            # Rejected before the database, so a typo does not arrive as a driver error.
            raise ValueError(f"{event_id!r} is not a downtime event id") from ex

        assigned = await _repository().assign_reason(
            numeric_id, reason_code, note=note, assigned_by=assigned_by
        )
        if assigned is None:
            # Non-null return type, and the right answer: an operator whose click did
            # nothing has to be told, not handed an empty object.
            raise ValueError(f"There is no downtime event {event_id}")

        LOGGER.info(
            "Downtime event %s attributed to %s by %s", event_id, reason_code, assigned_by or "unknown"
        )
        return DowntimeEventType.from_row(assigned)

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the queries, which dispose it."""
```

- [ ] **Step 13: Wire the mutation into the schema**

In `07_uns_graphql/src/uns_graphql/uns_graphql_app.py`, add the import after line 32:

```python
from uns_graphql.mutations.alert_rule import Mutation as AlertRuleMutation
from uns_graphql.mutations.oee import Mutation as OeeMutation
```

and change the `Mutation` class so it reads:

```python
@strawberry.type(description="Write configuration to the UNS platform")
class Mutation(AlertRuleMutation, OeeMutation):
    """
    The only mutations this service exposes.

    Deliberately narrow: process data is written by publishing to the broker, and the
    Asset Model is authored in `conf/settings.yaml`. What is left is the console's own
    configuration, which has nowhere else to live because the console is a static
    bundle (ADR-0005), and one correction to plant data that no machine can make - which
    reason a stop is attributed to.
    """

    @classmethod
    async def on_shutdown(cls):
        """
        Clean up connections, db pools etc.
        """
        await AlertRuleMutation.on_shutdown()
        await OeeMutation.on_shutdown()
```

- [ ] **Step 14: Run the mutation test to verify it passes**

Run: `uv run pytest 07_uns_graphql/test/mutations/test_oee.py -v -n 0`
Expected: PASS (7 passed).

- [ ] **Step 15: Run the whole GraphQL suite and the linter**

Run: `uv run pytest 07_uns_graphql/test -q -m "not integrationtest"`
Expected: PASS. `test_uns_graphql_app.py::test_uns_graphql_app_db_pool_cleanup` still asserts `Database.close_shared` is awaited exactly once — `oee.Query.on_shutdown` is a no-op for the same reason `alert_rule.Query.on_shutdown` is, so that count does not change.

Run: `uv run ruff check 07_uns_graphql/src/uns_graphql/type/oee.py 07_uns_graphql/src/uns_graphql/queries/oee.py 07_uns_graphql/src/uns_graphql/mutations/oee.py 07_uns_graphql/test/type/test_oee.py 07_uns_graphql/test/queries/test_oee.py 07_uns_graphql/test/mutations/test_oee.py 07_uns_graphql/src/uns_graphql/uns_graphql_app.py`
Expected: no findings.

- [ ] **Step 16: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/type/oee.py \
        07_uns_graphql/src/uns_graphql/queries/oee.py \
        07_uns_graphql/src/uns_graphql/mutations/oee.py \
        07_uns_graphql/src/uns_graphql/uns_graphql_app.py \
        07_uns_graphql/test/type/test_oee.py \
        07_uns_graphql/test/queries/test_oee.py \
        07_uns_graphql/test/mutations/test_oee.py
git commit -m "feat(graphql): expose OEE results, downtime events and the reason-assignment mutation"
```

---

### Task 20: Packaging, deployment and the ADR

**Files:**
- Create: `12_uns_oee/Dockerfile`
- Create: `12_uns_oee/README.md`
- Create: `12_uns_oee/test/test_deployment.py`
- Create: `docs/adr/0008-oee-computed-from-history-not-streamed.md`
- Modify: `12_uns_oee/pyproject.toml` (add `pyyaml` to the `test` group)
- Modify: `09_uns_model/Dockerfile:49` (copy `conf/oee/`)
- Modify: `docker-compose.yml:317-327` (add `oee_client`, add it to `uns_prometheus`'s `depends_on`)
- Modify: `08_uns_observability/prometheus/prometheus.yml:18-21` (fifth scrape job)
- Modify: `README.md:117`, `:269`, `:339`, `:386`, `:398`

**Interfaces:**
- Consumes: `uns_oee.oee_config.OeeConfig` (Task 1) for the port the test asserts against; the `uns_oee` and `uns_oee_health` entry points (Tasks 15, 1).
- Produces: the `oee_client` compose service and the `uns_oee` Prometheus job. Task 21's Grafana dashboard and Task 22's integration test both assume the compose stack described here.

**Why this task has real tests and not only `docker compose config`.** Three numbers have to agree that live in three files nobody edits together: `OeeConfig.metrics_port`, `UNS_oee__metrics_port` in `docker-compose.yml`, and the target in `prometheus.yml`. When they disagree nothing fails — the container starts, the engine computes, and the dashboard's platform-health row is simply empty, which reads as "no OEE has run" rather than "the scrape target is wrong". `99_simulator/test/test_self_telemetry.py` already sets the precedent of a unit test that reads the real deployment files; this follows it.

**Why the container waits on `asset_model_setup` and not on `historian_client`.** The engine needs its tables and its authored master data, which `asset_model_setup` creates (Task 3 chains `oee_import` into `uns_model_setup`). It does not need the historian *process*: it reads the `uns_metrics` table, and a shift with no samples in it is a `NO_INPUT_DATA` result, not an error. Depending on `historian_client` would only mean the engine cannot start while the mapper is unhealthy, for no benefit.

**Why 9095 is not published to the host.** Same reason 9091, 9092 and 9093 are not: Prometheus scrapes it from inside the compose network. The engine has no HTTP surface a person needs.

- [ ] **Step 1: Write the failing deployment test**

Create `12_uns_oee/test/test_deployment.py`:

```python
"""The three files that have to agree about port 9095, and the one that has to agree about
the startup order.

None of this fails loudly when it drifts: a wrong scrape target produces an empty panel,
not an error, and a missing `depends_on` produces a container that crash-loops for a
minute and then works. Both are the kind of thing that gets found in a demo.

Reads the real deployment files, in the spirit of `99_simulator/test/test_self_telemetry.py`.
"""

from pathlib import Path

import pytest
import yaml
from uns_oee.oee_config import OeeConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
PROMETHEUS_FILE = REPO_ROOT / "08_uns_observability" / "prometheus" / "prometheus.yml"

SERVICE = "oee_client"
JOB = "uns_oee"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prometheus() -> dict:
    return yaml.safe_load(PROMETHEUS_FILE.read_text(encoding="utf-8"))


def test_the_scrape_target_is_the_port_the_engine_binds(compose: dict, prometheus: dict):
    """
    The one assertion that earns this file. `OeeConfig`'s default is the source of truth;
    the compose override and the scrape target both have to name it.
    """
    port = OeeConfig(mqtt_host="localhost").metrics_port

    jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert JOB in jobs, f"prometheus.yml has no {JOB} job"
    assert jobs[JOB]["static_configs"][0]["targets"] == [f"{SERVICE}:{port}"]
    assert str(compose["services"][SERVICE]["environment"]["UNS_oee__metrics_port"]) == str(port)


def test_the_metrics_port_is_not_shared_with_another_service(prometheus: dict):
    """9091 historian, 9092 graph database, 9093 simulator, 9094 the OPC UA connector."""
    targets = [job["static_configs"][0]["targets"][0] for job in prometheus["scrape_configs"]]
    ports = [target.rsplit(":", 1)[1] for target in targets]
    assert len(ports) == len(set(ports)), f"two Prometheus jobs scrape the same port: {ports}"


def test_the_metrics_port_is_not_published_to_the_host(compose: dict):
    """Prometheus scrapes from inside the network. Nothing outside needs to reach 9095."""
    assert "ports" not in compose["services"][SERVICE]


def test_the_engine_waits_for_its_tables_and_its_master_data(compose: dict):
    """
    `asset_model_setup` runs the `0003` migration and imports `conf/oee/*.yaml`. Starting
    before it means a first pass with no OeeUnit rows, which is silent by design.
    """
    depends_on = compose["services"][SERVICE]["depends_on"]
    assert depends_on["asset_model_setup"]["condition"] == "service_completed_successfully"
    assert depends_on["tsdb_setup_script"]["condition"] == "service_completed_successfully"
    assert depends_on["uns_timescale_db"]["condition"] == "service_healthy"
    assert depends_on["uns_mqtt_broker"]["condition"] == "service_healthy"


def test_the_engine_does_not_wait_for_the_historian_process(compose: dict):
    """
    It reads the `uns_metrics` table, not the mapper. A shift with no samples is a
    NO_INPUT_DATA result, so the mapper being unhealthy must not stop the engine.
    """
    assert "historian_client" not in compose["services"][SERVICE]["depends_on"]


def test_prometheus_scrapes_the_engine(compose: dict):
    """Without this, the job resolves to nothing until the engine happens to be up first."""
    assert SERVICE in compose["services"]["uns_prometheus"]["depends_on"]


def test_the_engine_gets_the_database_credentials_it_needs(compose: dict):
    """
    Reads `uns_metrics` and writes `oee.*` as the same role the historian uses. The
    password comes from the environment, never from the compose file.
    """
    environment = compose["services"][SERVICE]["environment"]
    assert environment["UNS_historian__hostname"] == "uns_timescale_db"
    assert environment["UNS_historian__metrics_table"] == "uns_metrics"
    assert environment["UNS_historian__password"] == "${UNS_historian__password}"
    assert environment["UNS_mqtt__host"] == "uns_mqtt_broker"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_deployment.py -v -n 0`
Expected: FAIL — `ModuleNotFoundError: No module named 'yaml'` on collection, or once that is installed, `KeyError: 'oee_client'`.

- [ ] **Step 3: Add `pyyaml` to the test group**

In `12_uns_oee/pyproject.toml`, `[dependency-groups] test`, add:

```toml
    "pyyaml>=6.0.2,<7",
```

The test group, not `dependencies`: the engine reads no YAML of its own — `conf/oee/*.yaml` is `09_uns_model`'s importer's business — and only this test needs a parser.

- [ ] **Step 4: Add the Prometheus job**

`08_uns_observability/prometheus/prometheus.yml`, after the `uns_simulator` job:

```yaml
  - job_name: uns_oee
    static_configs:
      - targets: ["oee_client:9095"]
```

- [ ] **Step 5: Add the compose service**

In `docker-compose.yml`, insert before `uns_prometheus`:

```yaml
  # Computes OEE for closed shifts and publishes each result to `<line>/KPI/ShiftOee`.
  # Reads the `uns_metrics` hypertable and writes the `oee` schema; it never publishes
  # process data and never writes to a control system (ADR-0008).
  oee_client:
    build:
      context: .
      dockerfile: ./12_uns_oee/Dockerfile
    volumes:
      - ./conf:/app/conf
    # 9095 stays unpublished: Prometheus scrapes it from inside the network, exactly as it
    # does the historian's 9091, the graph database's 9092 and the simulator's 9093.
    environment:
      UNS_CONF_DIR: /app/conf
      UNS_MODULE: 12_uns_oee
      UNS_mqtt__host: uns_mqtt_broker
      UNS_historian__hostname: uns_timescale_db
      UNS_historian__database: "uns_historian"
      UNS_historian__metrics_table: "uns_metrics"
      UNS_historian__username: uns_dbuser
      UNS_historian__password: ${UNS_historian__password}
      UNS_oee__metrics_port: 9095
    depends_on:
      uns_mqtt_broker:
        condition: service_healthy
      uns_timescale_db:
        condition: service_healthy
      tsdb_setup_script:
        condition: service_completed_successfully
      # Creates the `oee` schema and imports conf/oee/*.yaml. Without it the first pass
      # finds no OeeUnit rows and does nothing, which is silent.
      asset_model_setup:
        condition: service_completed_successfully
```

and add `oee_client` to `uns_prometheus`:

```yaml
  uns_prometheus:
    image: "prom/prometheus:latest"
    ports:
      - "9090:9090"
    volumes:
      - ./08_uns_observability/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    depends_on:
      - historian_client
      - graphdb_client
      - uns_simulator
      - oee_client
```

- [ ] **Step 6: Write the Dockerfile**

Create `12_uns_oee/Dockerfile`:

```dockerfile
###############################################################################
# Copyright (c) 2021 Ashwin Krishnan
#
# All rights reserved. This program and the accompanying materials
# are made available under the terms of MIT and  is provided "as is",
# without warranty of any kind, express or implied, including but
# not limited to the warranties of merchantability, fitness for a
# particular purpose and noninfringement. In no event shall the
# authors, contributors or copyright holders be liable for any claim,
# damages or other liability, whether in an action of contract,
# tort or otherwise, arising from, out of or in connection with the software
# or the use or other dealings in the software.
#
# Contributors:
#    -
###############################################################################

# The command for building this image is
#       docker build -t uns/oee:<version> --build-arg GIT_HASH=<git hash or local> -f ./Dockerfile ..
#       e.g.
#       docker build -t uns/oee:0.9.38 --build-arg GIT_HASH=local -f ./Dockerfile ..
# Run the build command from the repository root (context is `..` from 12_uns_oee)
# Mount the repository-root conf/ folder at /app/conf.
#       e.g.
#       docker run --name uns_oee -v <repo-root>/conf:/app/conf --network=host uns/oee:0.9.38

# Use the official Python image
FROM python:3.14-alpine3.22

# Set the environment variable for the entrypoint command
# spell-checker:disable
ENV UNS_MODULE="12_uns_oee"\
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UNS_CONF_DIR="/app/conf"
# spell-checker:enable
LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/12_uns_oee
LABEL org.opencontainers.image.description="Computes shift OEE from historised UNS data and publishes it back to MQTT"
LABEL org.opencontainers.image.licenses=MIT

# Set the working directory in the container to /
WORKDIR /app

# Copy the contents of the project into the container
COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/uv.lock ./${UNS_MODULE}/README.md ./LICENSE* ./
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
# The Asset Model: this module's ORM tables, its engine and its result repository all live
# there. alembic.ini and migrations/ are part of its build config, so they are copied even
# though the engine never migrates - the Asset Model image does that.
COPY ./09_uns_model/pyproject.toml ./09_uns_model/uv.lock ./09_uns_model/README.md ./09_uns_model/alembic.ini /09_uns_model/
COPY ./09_uns_model/migrations /09_uns_model/migrations
COPY ./09_uns_model/src /09_uns_model/src
COPY ./${UNS_MODULE}/src ./src/
COPY ./conf/settings.yaml /app/conf/settings.yaml

# install minimalistic missing packages & security fixes
RUN apk update && \
    apk add --no-cache libffi-dev libc-dev gcc && \
    apk upgrade --no-cache libexpat libcrypto3 libssl3 busybox ssl_client && \
    rm -rf /var/cache/apk/*

# Install pip & uv
RUN  pip install  --no-cache-dir --upgrade pip uv && \
    # create application user
    adduser --no-create-home --home /app --disabled-password uns_user && \
    chown -R uns_user /app && \
    # Install the required dependencies for the project using uv as that user
    su uns_user -c "uv lock && uv sync --group main --compile-bytecode"

USER uns_user

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

# Mount the volume /conf
VOLUME /app/conf
# Set the Entrypoint script to run the uns_oee module
ENTRYPOINT ["uv", "run", "uns_oee"]
HEALTHCHECK --interval=60s --timeout=10s CMD ["uv", "run", "uns_oee_health"]
```

Note what is *not* in it: no `02_mqtt-cluster`. The engine publishes with `aiomqtt` directly and never subscribes, so the listener base class would be dead weight. `tzdata` is not installed by `apk` either — it comes in as a Python dependency (Task 4), which is what makes the same wheel work on Windows and Alpine.

- [ ] **Step 7: Ship `conf/oee/` in the Asset Model image**

In `09_uns_model/Dockerfile`, after the `COPY ./conf/settings.yaml` line, add:

```dockerfile
# The authored OEE master data, imported by `uns_model_oee_import`. Compose mounts the
# whole conf/ over this, so it only matters when the image is run without a mount - which
# is exactly the case where a missing shift pattern would be hardest to diagnose.
COPY ./conf/oee /app/conf/oee
```

- [ ] **Step 8: Run the deployment test to verify it passes**

Run: `uv sync && uv run pytest 12_uns_oee/test/test_deployment.py -v -n 0`
Expected: PASS (7 passed).

Run: `docker compose config > /dev/null`
Expected: no output and exit status 0. This is what catches a YAML indentation slip in Step 5, which the Python test cannot see because `yaml.safe_load` would have failed first — if the test errored on parsing, fix the indentation before reading further.

- [ ] **Step 9: Write the module README**

Create `12_uns_oee/README.md`:

```markdown
# UNS OEE Engine

Computes **Overall Equipment Effectiveness** for closed shifts from data already in the
historian, and publishes each result back into the Unified Namespace.

    OEE = Availability x Performance x Quality

Definitions follow Nakajima / SEMI E79 as spelled out in
[the design](../docs/superpowers/specs/2026-09-01-oee-engine-design.md), and the reasoning
behind computing rather than streaming is [ADR-0008](../docs/adr/0008-oee-computed-from-history-not-streamed.md).

## What it does

For each Asset listed in `conf/oee/units.yaml`, once a shift has closed and settled:

| Term | From |
| --- | --- |
| Loading Time | the shift window, less planned stops and calendar exceptions |
| Run Time | the union of the intervals the Asset spent in a producing state |
| Good / Reject counts | monotonic counters, differenced with rollover and reset detection |
| Ideal Cycle Time | authored per Asset x Product in `conf/oee/products.yaml` and `units.yaml` |

The result is written to `oee.shift_result` and published once to
`<asset path>/KPI/ShiftOee`. Stops are stored individually in `oee.downtime_event` with a
reason code, so the number can always be explained.

## What it does not do

- **No live OEE.** A partial shift has no Availability, because its Loading Time is not
  known until it closes. The console shows closed shifts.
- **No write-back to any control system.** This module reads the historian and publishes
  to MQTT. It never writes to OPC UA, a PLC, or any process interface.
- **No editing of a result.** A shift result is computed. What a human can correct is
  *why* a machine stopped, through `assignDowntimeReason`; that queues a recomputation.

## Configuration

| Where | What |
| --- | --- |
| `conf/settings.yaml`, `oee:` environment | scan interval, settle time, late window, backfill days, metrics port |
| `conf/oee/shifts.yaml` | weekly shift patterns and calendar exceptions, in a named IANA timezone |
| `conf/oee/units.yaml` | which Assets OEE is reported for, and the metric keys its inputs come from |
| `conf/oee/products.yaml` | product codes and their ideal cycle times |
| `conf/oee/reasons.yaml` | the downtime reason vocabulary and the state-to-reason rules |

Override any setting with an environment variable: `UNS_oee__backfill_days=7`. The database
password comes from `conf/.secrets.yaml` or `UNS_historian__password` and must never be put
in `settings.yaml`.

After editing anything under `conf/oee/`, re-run the importer:

```bash
docker compose up asset_model_setup
```

## Running it

```bash
# In the compose stack, as the `oee_client` service
docker compose up -d oee_client

# Locally
uv run uns_oee

# Recompute a range by hand - after correcting master data, for instance
uv run uns_oee_recompute --asset "CovestroAG/Dormagen/Production/Line1" \
                         --from 2026-08-01 --to 2026-09-01
```

`uns_oee_recompute --help` lists the rest, including `--force`, which supersedes existing
revisions instead of queuing them.

## Observability

Prometheus metrics on **9095** (`uns_oee_shifts_computed`, `uns_oee_shifts_failed`,
`uns_oee_publish_failed`, `uns_oee_pass_duration_seconds`, `uns_oee_last_pass_timestamp`).
The Grafana **OEE** dashboard reads `oee.shift_result` and `oee.downtime_event` directly -
not the enriched metric views, which know nothing about shifts.

## Tests

```bash
uv run pytest ./12_uns_oee                        # everything
uv run pytest -m "not integrationtest" ./12_uns_oee   # no database needed
```

The arithmetic — the calendar, the counters, the interval algebra, the formulas — is all
pure and covered without a database. The integration tests need a Postgres with the
migrations applied.
```

- [ ] **Step 10: Write the ADR**

Create `docs/adr/0008-oee-computed-from-history-not-streamed.md`:

```markdown
---
status: accepted
---

# OEE is computed from shift history, not streamed

Date: 2026-09-01

## Status

Accepted

## Context

The platform needed the memo's pilot success criterion: an OEE number per line that
production can act on.

The obvious shape is a stream processor. Machine state and counters already arrive on MQTT;
a subscriber could keep a running Availability, Performance and Quality per line and
publish them continuously, and the console would show a live gauge.

Three things make that the wrong shape here.

**Availability has no live value.** It is Run Time over *Loading Time*, and Loading Time is
the shift's scheduled time less its planned stops. Mid-shift, the denominator is not known:
a changeover scheduled for the last hour has not happened yet. A live gauge would either
divide by elapsed time — a different quantity that drifts toward the real one and looks
wrong all shift — or by planned time, and read 40% at 08:00 on every shift ever run.

**A stopped machine has to be asked why.** Auto-classification from a state code gets some
of the way, and the rest is a person saying "that was the gearbox". That answer arrives
minutes or hours after the stop, and `is_planned` on the reason moves the interval between
Unplanned Down and excluded time — so it changes Availability. A number that is final the
instant the shift ends is a number that cannot absorb the correction.

**Late data is normal.** An edge connector reconnects and flushes an hour of buffered
samples. Stream state has already moved past them.

## Decision

OEE is computed **after** a shift closes, from the historised `uns_metrics` rows, by a
scheduler that runs a pass every few minutes.

- A shift becomes eligible `settle_minutes` after its end, so in-flight messages have
  landed.
- Each computation records an **input fingerprint** (a row count and a max timestamp) over
  its window. For `late_window_hours` after the shift ends, a pass that finds a changed
  fingerprint recomputes and writes a new **revision**; the previous numbers move to
  `oee.shift_result_revision`. Identical fingerprint, no write.
- Correcting a downtime reason enqueues that shift in `oee.recompute_request`, which the
  same pass drains.
- A manually assigned reason (`reason_source = 'manual'`) is never overwritten by the
  engine. Recomputation reads the corrected reason and produces a different, better number.
- Results are published once per revision to `<asset path>/KPI/ShiftOee`, which is a KPI
  topic and not a measurement. Nothing subscribes to it in order to compute anything else.

Every formula lives in one pure module (`oee_calc.py`) that takes a `ShiftInputs` and
returns a `ShiftMetrics`. Nothing else does arithmetic. The dashboard reads
`oee.shift_result`; it does not re-derive OEE from samples, because a second implementation
of the formula is free to disagree with the first.

Undefined is represented as null, never zero. A shift with no Loading Time did not achieve
0% — `status` says `NO_LOADING_TIME` and the ratios are null, so a plant holiday does not
appear on the trend as a catastrophe.

## Consequences

**Good.** The number is explainable: every result has its stops, its per-product counts and
its ideal cycle times stored beside it. Recomputation is safe by construction — the same
inputs produce the same fingerprint and therefore no write — so the CLI, the queue and the
scheduler can all ask for the same range without racing. Corrections are first-class rather
than an audit-trail afterthought. The engine is a batch reader, so it can be stopped for an
hour and catch up.

**Bad.** OEE is late by `settle_minutes` plus up to one scan interval — around twenty
minutes with the defaults — and there is no live gauge to put on a wall display. A shift's
number can change after an operator sees it, which needs explaining once to every plant that
adopts it; `revision` and `oee.shift_result_revision` are what make that explanation
possible. Backfill on an empty results table walks back `backfill_days`, which on a large
history is the slowest thing the module ever does, so it is bounded and logged.

**Neutral.** Nothing here prevents adding a live *rate* signal later — units per hour is
well defined mid-shift and needs no Loading Time. That would be a new topic beside
`KPI/ShiftOee`, not a change to it.
```

- [ ] **Step 11: Update the root README**

Add to the container table after the `uns_simulator` row (`README.md:117`):

```markdown
| `oee_client` | Computes shift OEE from the historised `uns_metrics` rows and publishes each result to `<line>/KPI/ShiftOee`. Reads the historian, writes the `oee` schema, never writes to a control system (ADR-0008). Metrics on `9095`, unpublished. |
```

Add to the module bullet list after the Asset Model line (`README.md:269`):

```markdown
- The shift OEE engine, which turns that history into Availability x Performance x Quality per line [12_uns_oee](./12_uns_oee/README.md)
```

Add to the numbered module list after `09_uns_model` (`README.md:339`):

```markdown
1. [12_uns_oee](./12_uns_oee/README.md): Python project that computes OEE for closed shifts from historised UNS data, stores the result and its downtime breakdown in the `oee` schema, and publishes it back to MQTT
```

Add to both test-command blocks (`README.md:386` and `:398`):

```bash
uv run pytest  ./12_uns_oee
```

```bash
uv run pytest -m "not integrationtest" ./12_uns_oee
```

Add a section after **Observability & Visualization** and before **Setting up the development environment** (`README.md:324`):

```markdown
### **OEE**

**Overall Equipment Effectiveness** — Availability x Performance x Quality — is computed per
closed shift by **[12_uns_oee](./12_uns_oee/README.md)** from data already in the historian,
and published back into the namespace on `<line>/KPI/ShiftOee`.

It is deliberately not a live gauge. Availability is Run Time over *Loading Time*, and
Loading Time is not known until the shift closes — mid-shift, a changeover scheduled for the
last hour has not happened yet. A live number would either divide by elapsed time, which is a
different quantity, or read 40% at 08:00 on every shift ever run.

Two consequences are worth knowing before you rely on it:

- **A shift's number can change.** Late-arriving data and corrected downtime reasons both
  trigger a recomputation within `late_window_hours`. Each restatement bumps `revision` and
  moves the previous numbers to `oee.shift_result_revision`, so the change is visible rather
  than silent.
- **Undefined is null, never zero.** A shift with no Loading Time has `status`
  `NO_LOADING_TIME` and null ratios. A plant holiday therefore leaves a gap on the trend
  instead of a catastrophe.

The reasoning is recorded in
[ADR 0008](./docs/adr/0008-oee-computed-from-history-not-streamed.md).
```

- [ ] **Step 12: Verify the image builds and the stack starts**

```bash
docker build -t uns/oee:local --build-arg GIT_HASH=local -f ./12_uns_oee/Dockerfile .
```

Expected: a successful build. If `uv lock` fails inside the image, the cause is almost always a dependency in `12_uns_oee/pyproject.toml` whose source path is not copied — compare the `COPY` lines against `[tool.uv.sources]`.

```bash
UNS_graphdb__password=password1 UNS_historian__password=password2 PGPASSWORD=password3 \
  docker compose up -d oee_client
docker compose logs oee_client
```

Expected: `Simulator`-style startup lines from `main.py` — the metrics server bound to 9095, the config summary, and a first scheduler pass. On a fresh stack with the simulator running for less than a shift, the pass finds nothing due and says so; that is correct, not a failure.

```bash
docker compose exec uns_prometheus wget -qO- http://oee_client:9095/metrics | head -20
```

Expected: the `uns_oee_*` families, at zero.

- [ ] **Step 13: Run the module's tests and the linter**

Run: `uv run pytest 12_uns_oee/test -q -m "not integrationtest"`
Expected: PASS.

Run: `uv run ruff check 12_uns_oee/test/test_deployment.py`
Expected: no findings.

- [ ] **Step 14: Commit**

```bash
git add 12_uns_oee/Dockerfile 12_uns_oee/README.md 12_uns_oee/test/test_deployment.py \
        12_uns_oee/pyproject.toml 09_uns_model/Dockerfile docker-compose.yml \
        08_uns_observability/prometheus/prometheus.yml README.md \
        docs/adr/0008-oee-computed-from-history-not-streamed.md
git commit -m "feat(oee): package the engine as a container and document the design decision"
```

---

### Task 21: The Grafana OEE dashboard

**Files:**
- Create: `08_uns_observability/grafana/dashboards/oee.json`
- Create: `12_uns_oee/test/test_dashboard.py`
- Modify: `08_uns_observability/grafana/provisioning/datasources/datasources.yaml.template:4-22` (declare the `uid`s)
- Modify: `docker-compose.yml` (`uns_grafana` waits on `oee_client`)
- Modify: `README.md:121` (the `uns_grafana` row mentions the OEE dashboard)

**Interfaces:**
- Consumes: `oee.shift_result`, `oee.shift_result_product`, `oee.downtime_event` (Task 2); `model.oee_unit`, `model.asset`, `model.downtime_reason` (Tasks 2, 3). No new Python interfaces.
- Produces: dashboard `uid: uns-oee`, provisioned into the `UNS` folder by the existing file provider. Nothing depends on it.

**Why the datasource `uid`s are added here.** Both existing dashboards already reference `"uid": "timescaledb"` and `"uid": "prometheus"`, and `datasources.yaml.template` declares neither — Grafana generates a random uid per provisioning run, so those panels resolve to "Datasource not found". This is a pre-existing bug, and it is fixed in this task rather than left alone because the OEE dashboard would otherwise be born broken in exactly the same way and the cause would be attributed to the new code. `test_dashboard.py` asserts every uid a dashboard names is declared, so it cannot recur.

**Why the dashboard reads `oee.shift_result` and not `uns_metrics_1m_enriched`.** The enriched views know about topics and Assets; they know nothing about shifts, producing states, counter resets or product mix. A panel that recomputed OEE from samples would be a second implementation of the formulas in `oee_calc.py`, free to disagree with the number the engine published to MQTT. `test_no_panel_recomputes_oee_from_raw_samples` makes that a test failure rather than a code review.

**Why `shift_start` is the time column and not `computed_at`.** A restated shift must move on the trend where the shift *was*, not where the recomputation happened. Plotting `computed_at` would put a corrected August shift into September.

**Why `WHERE revision = ...` appears nowhere.** `oee.shift_result` holds exactly one row per (unit, shift) — superseded numbers live in `oee.shift_result_revision`. The current result is the only result, which is what makes every panel a plain select.

- [ ] **Step 1: Write the failing dashboard test**

Create `12_uns_oee/test/test_dashboard.py`:

```python
"""What the OEE dashboard is not allowed to do.

Grafana fails quietly. A panel naming a datasource uid that provisioning never declared
renders "Datasource not found" in one panel and nothing anywhere else; a panel missing
`$__timeFilter` works perfectly until the table has a year in it. Both are found by a
person looking at a screen, which is the worst place to find them.
"""

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAFANA = REPO_ROOT / "08_uns_observability" / "grafana"
DASHBOARD_DIR = GRAFANA / "dashboards"
OEE_DASHBOARD = DASHBOARD_DIR / "oee.json"
DATASOURCES = GRAFANA / "provisioning" / "datasources" / "datasources.yaml.template"


def _panels(dashboard: dict) -> list[dict]:
    """Flattened, because a collapsed row nests its panels inside itself."""
    panels = []
    for panel in dashboard.get("panels", []):
        panels.append(panel)
        panels.extend(panel.get("panels", []))
    return panels


def _queries(panel: dict) -> list[str]:
    return [target["rawSql"] for target in panel.get("targets", []) if "rawSql" in target]


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(OEE_DASHBOARD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def declared_uids() -> set[str]:
    template = yaml.safe_load(DATASOURCES.read_text(encoding="utf-8"))
    return {source["uid"] for source in template["datasources"] if "uid" in source}


@pytest.mark.parametrize("path", sorted(DASHBOARD_DIR.glob("*.json")), ids=lambda path: path.name)
def test_every_dashboard_names_a_declared_datasource(path: Path, declared_uids: set[str]):
    """
    Applies to all three dashboards, not only the new one: two of them referenced uids
    that provisioning never declared, which is why the datasource template changed here.
    """
    body = json.loads(path.read_text(encoding="utf-8"))
    named = {
        panel["datasource"]["uid"]
        for panel in _panels(body)
        if isinstance(panel.get("datasource"), dict) and "uid" in panel["datasource"]
    }
    assert named <= declared_uids, f"{path.name} names undeclared datasource uid(s): {named - declared_uids}"


def test_no_panel_recomputes_oee_from_raw_samples(dashboard: dict):
    """
    The engine's numbers or nothing. A panel doing its own arithmetic over `uns_metrics`
    would be a second implementation of the formulas, free to disagree with the value
    already published to `<line>/KPI/ShiftOee`.
    """
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "uns_metrics" not in query, f"panel {panel.get('title')!r} reads uns_metrics"


def test_every_query_is_bounded_by_the_dashboard_time_range(dashboard: dict):
    """Without $__timeFilter a panel scans every shift ever computed."""
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "$__timeFilter" in query, f"panel {panel.get('title')!r} has an unbounded query"


def test_the_trend_is_plotted_against_shift_start(dashboard: dict):
    """
    Not `computed_at`: a restated August shift has to move where the shift was, not where
    the recomputation happened.
    """
    trend = next(panel for panel in _panels(dashboard) if panel["type"] == "timeseries")
    query = _queries(trend)[0]
    assert "$__timeFilter(shift_start)" in query
    assert "computed_at" not in query


def test_every_query_is_filtered_to_the_selected_asset(dashboard: dict):
    """A dashboard showing two lines' OEE on one axis is a dashboard showing neither."""
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "$asset" in query, f"panel {panel.get('title')!r} ignores the asset variable"


def test_the_asset_variable_lists_only_assets_oee_is_computed_for(dashboard: dict):
    variable = next(item for item in dashboard["templating"]["list"] if item["name"] == "asset")
    assert variable["type"] == "query"
    assert "model.oee_unit" in variable["query"]
    assert "is_active" in variable["query"]


def test_panel_ids_are_unique(dashboard: dict):
    """Duplicated ids make Grafana silently drop a panel on import."""
    ids = [panel["id"] for panel in _panels(dashboard)]
    assert len(ids) == len(set(ids))


def test_the_dashboard_is_identified_and_tagged(dashboard: dict):
    assert dashboard["uid"] == "uns-oee"
    assert dashboard["title"] == "OEE"
    assert "oee" in dashboard["tags"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 12_uns_oee/test/test_dashboard.py -v -n 0`
Expected: FAIL — `FileNotFoundError` for `oee.json` on the module-scoped fixture, and `test_every_dashboard_names_a_declared_datasource` failing for `platform-observability.json` and `process-visualization.json` with `{'prometheus'}` and `{'timescaledb'}`. Both failures are the point: the second one is the pre-existing bug.

- [ ] **Step 3: Declare the datasource `uid`s**

In `08_uns_observability/grafana/provisioning/datasources/datasources.yaml.template`, add a `uid` to each datasource. Without it Grafana generates one per provisioning run and every dashboard's `"uid": "timescaledb"` resolves to nothing:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    # Fixed uid, because the dashboard JSON files reference datasources by uid. Grafana
    # generates a random one when this is omitted, which is why panels rendered
    # "Datasource not found" before this line existed.
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://uns_prometheus:9090
    isDefault: true
    editable: false

  - name: TimescaleDB
    uid: timescaledb
    type: grafana-postgresql-datasource
    access: proxy
    url: uns_timescale_db:5432
    user: uns_dbuser
    database: uns_historian
    jsonData:
      sslmode: disable
      postgresVersion: 1600
      timescaledb: true
    secureJsonData:
      password: ${UNS_HISTORIAN_PASSWORD}

  - name: MQTT
    uid: mqtt
    type: grafana-mqtt-datasource
    access: proxy
    url: tcp://uns_mqtt_broker:1883
    jsonData:
      tlsAuth: false
      tlsAuthWithCACert: false
    editable: false
```

- [ ] **Step 4: Write the dashboard**

Create `08_uns_observability/grafana/dashboards/oee.json`:

```json
{
  "annotations": { "list": [] },
  "description": "Availability x Performance x Quality per closed shift, computed by 12_uns_oee (ADR-0008). Shows closed shifts only: a partial shift has no Loading Time and therefore no Availability.",
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 1,
  "id": null,
  "links": [],
  "panels": [
    {
      "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
      "description": "Most recent closed shift in the selected range. Blank means no shift has closed yet.",
      "fieldConfig": {
        "defaults": {
          "decimals": 1,
          "mappings": [],
          "max": 1,
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "orange", "value": 0.5 },
              { "color": "green", "value": 0.75 }
            ]
          },
          "unit": "percentunit"
        },
        "overrides": []
      },
      "gridPos": { "h": 5, "w": 6, "x": 0, "y": 0 },
      "id": 1,
      "options": {
        "colorMode": "value",
        "graphMode": "none",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "textMode": "auto"
      },
      "targets": [
        {
          "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
          "format": "table",
          "rawSql": "SELECT r.oee FROM oee.shift_result r JOIN model.oee_unit u ON u.id = r.oee_unit_id JOIN model.asset a ON a.id = u.asset_id WHERE a.path = '$asset' AND $__timeFilter(r.shift_start) ORDER BY r.shift_start DESC LIMIT 1",
          "refId": "A"
        }
      ],
      "title": "Latest shift OEE",
      "type": "stat"
    },
    {
      "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
      "description": "Mean over the closed shifts in range. Shifts with an undefined factor are excluded rather than counted as zero.",
      "fieldConfig": {
        "defaults": {
          "decimals": 1,
          "max": 1,
          "min": 0,
          "unit": "percentunit"
        },
        "overrides": []
      },
      "gridPos": { "h": 5, "w": 12, "x": 6, "y": 0 },
      "id": 2,
      "options": {
        "colorMode": "value",
        "graphMode": "none",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "textMode": "value_and_name"
      },
      "targets": [
        {
          "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
          "format": "table",
          "rawSql": "SELECT avg(r.availability) AS \"Availability\", avg(r.performance) AS \"Performance\", avg(r.quality) AS \"Quality\", avg(r.oee) AS \"OEE\" FROM oee.shift_result r JOIN model.oee_unit u ON u.id = r.oee_unit_id JOIN model.asset a ON a.id = u.asset_id WHERE a.path = '$asset' AND $__timeFilter(r.shift_start)",
          "refId": "A"
        }
      ],
      "title": "Average over range",
      "type": "stat"
    },
    {
      "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
      "description": "Shifts whose numbers are not usable, and why. An empty panel is the healthy case.",
      "fieldConfig": { "defaults": {}, "overrides": [] },
      "gridPos": { "h": 5, "w": 6, "x": 18, "y": 0 },
      "id": 3,
      "options": { "showHeader": true },
      "targets": [
        {
          "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
          "format": "table",
          "rawSql": "SELECT r.status AS \"Status\", count(*) AS \"Shifts\" FROM oee.shift_result r JOIN model.oee_unit u ON u.id = r.oee_unit_id JOIN model.asset a ON a.id = u.asset_id WHERE a.path = '$asset' AND r.status <> 'OK' AND $__timeFilter(r.shift_start) GROUP BY r.status ORDER BY 2 DESC",
          "refId": "A"
        }
      ],
      "title": "Unusable shifts",
      "type": "table"
    },
    {
      "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
      "description": "One point per closed shift, plotted at the shift's start. A gap is a shift that was not scheduled; a null is a shift whose factor is undefined.",
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": {
            "drawStyle": "line",
            "lineWidth": 2,
            "pointSize": 6,
            "showPoints": "always",
            "spanNulls": false
          },
          "max": 1,
          "min": 0,
          "unit": "percentunit"
        },
        "overrides": [
          {
            "matcher": { "id": "byName", "options": "OEE" },
            "properties": [{ "id": "custom.lineWidth", "value": 3 }]
          }
        ]
      },
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 5 },
      "id": 4,
      "options": {
        "legend": { "displayMode": "list", "placement": "bottom" },
        "tooltip": { "mode": "multi", "sort": "none" }
      },
      "targets": [
        {
          "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
          "format": "time_series",
          "rawSql": "SELECT r.shift_start AS time, r.oee AS \"OEE\", r.availability AS \"Availability\", r.performance AS \"Performance\", r.quality AS \"Quality\" FROM oee.shift_result r JOIN model.oee_unit u ON u.id = r.oee_unit_id JOIN model.asset a ON a.id = u.asset_id WHERE a.path = '$asset' AND $__timeFilter(r.shift_start) ORDER BY 1",
          "refId": "A"
        }
      ],
      "title": "OEE and its factors, by shift",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
      "description": "Lost time per reason code, largest first. Sums to the window's total downtime: an unmapped state is UNCLASSIFIED, never dropped.",
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": { "axisPlacement": "auto", "fillOpacity": 80 },
          "unit": "s"
        },
        "overrides": []
      },
      "gridPos": { "h": 10, "w": 12, "x": 0, "y": 15 },
      "id": 5,
      "options": {
        "barWidth": 0.7,
        "legend": { "displayMode": "hidden", "placement": "bottom" },
        "orientation": "horizontal",
        "showValue": "auto",
        "xTickLabelRotation": 0
      },
      "targets": [
        {
          "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
          "format": "table",
          "rawSql": "SELECT COALESCE(NULLIF(dr.display_name, ''), e.reason_code) AS \"Reason\", sum(e.duration_s) AS \"Lost seconds\" FROM oee.downtime_event e JOIN model.oee_unit u ON u.id = e.oee_unit_id JOIN model.asset a ON a.id = u.asset_id LEFT JOIN model.downtime_reason dr ON dr.code = e.reason_code WHERE a.path = '$asset' AND $__timeFilter(e.started_at) GROUP BY 1 ORDER BY 2 DESC LIMIT 12",
          "refId": "A"
        }
      ],
      "title": "Downtime Pareto",
      "type": "barchart"
    },
    {
      "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
      "description": "The stops behind the numbers above. `Source` is `auto` when the engine classified the stop from its state code and `manual` when a person corrected it; the engine never overwrites a manual reason.",
      "fieldConfig": {
        "defaults": {},
        "overrides": [
          {
            "matcher": { "id": "byName", "options": "Duration" },
            "properties": [{ "id": "unit", "value": "s" }]
          }
        ]
      },
      "gridPos": { "h": 10, "w": 12, "x": 12, "y": 15 },
      "id": 6,
      "options": { "showHeader": true, "sortBy": [{ "desc": true, "displayName": "Duration" }] },
      "targets": [
        {
          "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
          "format": "table",
          "rawSql": "SELECT e.started_at AS \"Started\", e.duration_s AS \"Duration\", e.state_value AS \"State\", COALESCE(NULLIF(dr.display_name, ''), e.reason_code) AS \"Reason\", dr.is_planned AS \"Planned\", e.reason_source AS \"Source\", e.assigned_by AS \"By\", e.note AS \"Note\" FROM oee.downtime_event e JOIN model.oee_unit u ON u.id = e.oee_unit_id JOIN model.asset a ON a.id = u.asset_id LEFT JOIN model.downtime_reason dr ON dr.code = e.reason_code WHERE a.path = '$asset' AND $__timeFilter(e.started_at) ORDER BY e.duration_s DESC LIMIT 200",
          "refId": "A"
        }
      ],
      "title": "Longest stops",
      "type": "table"
    },
    {
      "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
      "description": "Good and reject counts per product, with the ideal cycle time each shift's Performance was computed against. A null cycle time is what sets MISSING_IDEAL_CYCLE_TIME.",
      "fieldConfig": { "defaults": {}, "overrides": [] },
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 25 },
      "id": 7,
      "options": { "showHeader": true },
      "targets": [
        {
          "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
          "format": "table",
          "rawSql": "SELECT p.product_code AS \"Product\", sum(p.good_count) AS \"Good\", sum(p.reject_count) AS \"Reject\", max(p.ideal_cycle_time_s) AS \"Ideal cycle (s)\" FROM oee.shift_result_product p JOIN oee.shift_result r ON r.id = p.shift_result_id JOIN model.oee_unit u ON u.id = r.oee_unit_id JOIN model.asset a ON a.id = u.asset_id WHERE a.path = '$asset' AND $__timeFilter(r.shift_start) GROUP BY 1 ORDER BY 2 DESC",
          "refId": "A"
        }
      ],
      "title": "Production by product",
      "type": "table"
    }
  ],
  "refresh": "5m",
  "schemaVersion": 39,
  "tags": ["oee", "process-visualization"],
  "templating": {
    "list": [
      {
        "datasource": { "type": "grafana-postgresql-datasource", "uid": "timescaledb" },
        "definition": "Assets that OEE is computed for",
        "hide": 0,
        "includeAll": false,
        "label": "Asset",
        "multi": false,
        "name": "asset",
        "options": [],
        "query": "SELECT a.path FROM model.oee_unit u JOIN model.asset a ON a.id = u.asset_id WHERE u.is_active ORDER BY 1",
        "refresh": 1,
        "regex": "",
        "sort": 1,
        "type": "query"
      }
    ]
  },
  "time": { "from": "now-7d", "to": "now" },
  "timezone": "browser",
  "title": "OEE",
  "uid": "uns-oee",
  "version": 1
}
```

`refresh: 5m`, not `30s`: the underlying data changes once a shift, and the engine's own pass runs every five minutes. A 30-second refresh would issue 600 pointless queries an hour against the same rows.

- [ ] **Step 5: Run the dashboard test to verify it passes**

Run: `uv run pytest 12_uns_oee/test/test_dashboard.py -v -n 0`
Expected: PASS (9 passed — the parametrised datasource test contributes one per dashboard file).

- [ ] **Step 6: Make Grafana wait for the engine**

In `docker-compose.yml`, add to `uns_grafana`'s `depends_on`:

```yaml
      # The OEE dashboard's panels read the `oee` schema. `asset_model_setup` creates it,
      # so this is not about the tables existing - it is so that a stack brought up for a
      # demo has the engine running before anybody opens the dashboard.
      oee_client:
        condition: service_started
```

- [ ] **Step 7: Update the README's Grafana row**

Change `README.md:121` so the dashboard list is current:

```markdown
| `uns_grafana` | Dashboards for Process Visualization (plant measurements from `uns_metrics_1m_enriched`), OEE (shift results and downtime from the `oee` schema), and Platform Observability (platform health). Host port: **`3000`** (`http://localhost:3000`). Anonymous access is enabled — see [Known Limitations](#known-limitations--workarounds). |
```

- [ ] **Step 8: Look at it**

```bash
UNS_graphdb__password=password1 UNS_historian__password=password2 PGPASSWORD=password3 \
  docker compose up -d uns_grafana
```

Open `http://localhost:3000`, folder **UNS**, dashboard **OEE**.

Expected, on a stack that has not yet run a full shift: the **Asset** dropdown lists the lines from `conf/oee/units.yaml`, and every panel is empty. Empty is the correct result — it means the queries resolved and found no closed shifts.

Expected failure mode worth recognising: "Datasource timescaledb was not found" means Step 3's `uid` did not take. Grafana only re-reads provisioning on start, so `docker compose restart uns_grafana` after editing the template.

To see it populated without waiting a shift, backfill against whatever history the simulator has produced:

```bash
docker compose exec oee_client uv run uns_oee_recompute \
  --asset "CovestroAG/Dormagen/Production/Line1" --from 2026-08-25 --to 2026-09-01 --force
```

- [ ] **Step 9: Run the module's tests and the linter**

Run: `uv run pytest 12_uns_oee/test -q -m "not integrationtest"`
Expected: PASS.

Run: `uv run ruff check 12_uns_oee/test/test_dashboard.py`
Expected: no findings.

- [ ] **Step 10: Commit**

```bash
git add 08_uns_observability/grafana/dashboards/oee.json \
        08_uns_observability/grafana/provisioning/datasources/datasources.yaml.template \
        12_uns_oee/test/test_dashboard.py docker-compose.yml README.md
git commit -m "feat(observability): add the OEE dashboard and pin the datasource uids"
```

---

### Task 22: Integration tests against a real Postgres

**Files:**
- Create: `12_uns_oee/test/test_integration.py`

**Interfaces:**
- Consumes: everything with SQL in it — `MetricSource` (Task 8), `MasterDataLoader` (Task 9), `ResultStore` (Task 10), `ShiftPipeline` (Task 12), `claim_requests` / `complete_requests` / `retention_days` (Task 13), `OeeResultRepository` (Task 18), `OeeMasterDataRepository` (Task 3), and the existing `AssetModelRepository`.
- Produces: nothing. This is the last task that can fail before the feature is trustworthy.

**What this task is for.** Every unit test up to here replaced the database with a scripted `FakeSession`, which pins statement order and predicates but says nothing about whether the SQL is valid, whether the joins find rows, or whether `on_conflict_do_update` actually collapses two writers into one row. `09_uns_model/test/test_integration.py` draws the same line and this file follows its shape: session-scoped engine, a test-only Asset branch, and a `_clean` that runs before and after so the file is safe against a database that already holds a seeded model.

**Why the shift pattern's timezone is `UTC`.** The DST cases — spring-forward, fall-back, ambiguous and non-existent local times — are pure arithmetic and are covered exhaustively in Task 4 without a database. Repeating them here would make a slow test slower and would obscure what this file is actually checking. A `UTC` pattern makes every expected number readable in the assertion.

**Why `ShiftScheduler.run_pass` is not called.** `run_pass` iterates `active_units()`, which on any real database includes the units seeded from `conf/oee/units.yaml`. Calling it would compute and publish results for the actual plant hierarchy as a side effect of running the test suite. What `run_pass` adds over the pure scheduling functions is exactly three pieces of SQL — `claim_requests`, `complete_requests`, `retention_days` — and those are tested directly.

**The shift the whole file is built on.** One eight-hour window, chosen so every expected value is exact rather than a `pytest.approx` with six digits:

| | |
| --- | --- |
| Window | `2026-08-31T06:00Z` → `14:00Z`, 28800 s |
| One stop | `ABORTED`, `10:00Z` → `10:30Z`, 1800 s, unplanned |
| Run Time | 27000 s |
| Good / Reject | 4800 / 200, so Total 5000 |
| Ideal cycle time | 5.0 s/unit |
| Availability | 27000 / 28800 = **15/16** |
| Performance | 25000 / 27000 = **25/27** |
| Quality | 4800 / 5000 = **24/25** |
| OEE | **5/6**, exactly |

Reassigning that stop to a planned reason moves 1800 s out of Loading Time, so Availability becomes 1.0 and OEE becomes 8/9 — which is what makes "a corrected reason changes the number" visible in an assertion instead of a paragraph.

- [ ] **Step 1: Write the integration test**

Create `12_uns_oee/test/test_integration.py`:

```python
"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Integration tests for the OEE engine against a real Postgres/TimescaleDB.

The unit tests cover the decisions; these cover the SQL, which is where the interesting
mistakes are: the master-data joins, the sample window with its prior sample, the
fingerprint, the idempotent upsert, the revision hand-off, and the queue claim. They need a
migrated database reachable with the `historian.*` settings - `uv run uns_model_setup`, or
the compose stack.

Everything is written under TEST_ROOT and removed again, so the tests are safe to run
against a database that already holds a seeded Asset Model and real OEE master data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from uns_model.engine import Database
from uns_model.model_config import ModelConfig
from uns_model.oee_master_data import (
    DowntimeReasonSpec,
    IdealCycleTimeSpec,
    OeeMasterDataRepository,
    OeeUnitSpec,
    ProductSpec,
    ShiftPatternSpec,
    ShiftSlotSpec,
    StateReasonRuleSpec,
)
from uns_model.oee_results import OeeResultRepository
from uns_model.repositories import AssetModelRepository, AssetSpec

from uns_oee.master_data import MasterDataLoader
from uns_oee.oee_config import OeeConfig
from uns_oee.pipeline import ACTION_COMPUTED, ACTION_REVISED, ACTION_UNCHANGED, ShiftPipeline
from uns_oee.scheduler import claim_requests, complete_requests, retention_days
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import MetricSource, split_metric_key
from uns_oee.store import ResultStore

pytestmark = [
    pytest.mark.integrationtest,
    pytest.mark.asyncio(loop_scope="session"),
    # Serialised: every test in the file writes the same test Asset branch.
    pytest.mark.xdist_group(name="oee_database"),
]

# Nothing outside this Enterprise is touched, which is what makes these tests runnable
# against a database that already holds the real plant hierarchy.
TEST_ROOT = "PyTestOEE"
LINE_PATH = f"{TEST_ROOT}/Plant1/Area1/Line1"
PATTERN_NAME = "PyTest OEE 1-shift"
PRODUCT_CODE = "PYTEST-P1"
UNPLANNED_REASON = "PYTEST_MECH_FAULT"
PLANNED_REASON = "PYTEST_CHANGEOVER"
REASON_CODES = (UNPLANNED_REASON, PLANNED_REASON)

STATE_KEY = "Cell1/MES-01/Status/PackMlState"
GOOD_KEY = "Cell1/MES-01/Production/GoodCount"
REJECT_KEY = "Cell1/MES-01/Production/RejectCount"

SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
WINDOW = ShiftWindow(start=SHIFT_START, end=SHIFT_END, label="A")
COMPUTED_AT = SHIFT_END + timedelta(minutes=20)

STOP_START = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
STOP_END = datetime(2026, 8, 31, 10, 30, tzinfo=UTC)

# See the task's table: every one of these is exact, not approximate.
EXPECTED_AVAILABILITY = 27000 / 28800
EXPECTED_PERFORMANCE = 25000 / 27000
EXPECTED_QUALITY = 4800 / 5000
EXPECTED_OEE = 5 / 6

BRANCH = [
    AssetSpec(segment=TEST_ROOT, level="ENTERPRISE"),
    AssetSpec(segment="Plant1", level="SITE"),
    AssetSpec(segment="Area1", level="AREA"),
    AssetSpec(segment="Line1", level="LINE"),
]


class _RecordingPublisher:
    """Stands in for `ResultPublisher`. Real MQTT is Task 23's business."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ShiftWindow, object, int]] = []
        self.published = 0
        self.failed = 0
        self.connected = True

    async def publish(self, asset_path, window, metrics, revision) -> bool:
        self.calls.append((asset_path, window, metrics, revision))
        self.published += 1
        return True

    async def aclose(self) -> None:
        return None


# ---- fixtures


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def database():
    """One engine for the whole session: asyncpg connections belong to a loop."""
    config = ModelConfig.from_settings()
    assert config.is_valid(), "historian.* settings are needed for the OEE integration tests"
    database = Database.from_config(config)
    yield database
    await database.dispose()


async def _clean(database: Database) -> None:
    """Remove everything these tests could have written, in FK-safe order."""
    async with database.begin() as connection:
        unit_ids = "SELECT u.id FROM model.oee_unit u JOIN model.asset a ON a.id = u.asset_id WHERE starts_with(a.path, :root)"
        await connection.execute(text(f"DELETE FROM oee.recompute_request WHERE oee_unit_id IN ({unit_ids})"), {"root": TEST_ROOT})
        await connection.execute(text(f"DELETE FROM oee.downtime_event WHERE oee_unit_id IN ({unit_ids})"), {"root": TEST_ROOT})
        # shift_result_product and shift_result_revision cascade from shift_result.
        await connection.execute(text(f"DELETE FROM oee.shift_result WHERE oee_unit_id IN ({unit_ids})"), {"root": TEST_ROOT})
        await connection.execute(text("DELETE FROM uns_metrics WHERE starts_with(topic, :root)"), {"root": TEST_ROOT})
        await connection.execute(text("DELETE FROM model.shift_exception WHERE asset_id IN (SELECT id FROM model.asset WHERE starts_with(path, :root))"), {"root": TEST_ROOT})
        # Cascades to model.oee_unit and model.ideal_cycle_time.
        await connection.execute(text("DELETE FROM model.asset WHERE path = :root"), {"root": TEST_ROOT})
        await connection.execute(text("DELETE FROM model.shift_pattern WHERE name = :name"), {"name": PATTERN_NAME})
        await connection.execute(
            text("DELETE FROM model.state_reason_map WHERE reason_code = ANY(:codes)"), {"codes": list(REASON_CODES)}
        )
        await connection.execute(text("DELETE FROM model.downtime_reason WHERE code = ANY(:codes)"), {"codes": list(REASON_CODES)})
        await connection.execute(text("DELETE FROM model.product WHERE code = :code"), {"code": PRODUCT_CODE})


async def _seed_master_data(database: Database) -> None:
    """The authored side, written through the real repository so its SQL is exercised too."""
    await AssetModelRepository(database).ensure_branch(BRANCH)
    repository = OeeMasterDataRepository(database)
    await repository.save_product(ProductSpec(code=PRODUCT_CODE, name="PyTest product"))
    await repository.save_shift_pattern(
        ShiftPatternSpec(
            name=PATTERN_NAME,
            # UTC on purpose: DST is Task 4's exhaustive unit tests, and a UTC pattern
            # keeps every expected number in this file readable.
            timezone="UTC",
            asset_path=LINE_PATH,
            # All seven days, so the test does not depend on what weekday 2026-08-31 is.
            slots=tuple(
                ShiftSlotSpec(day_of_week=day, start_time=time(6, 0), duration_minutes=480, label="A")
                for day in range(7)
            ),
        )
    )
    await repository.save_downtime_reason(
        DowntimeReasonSpec(code=UNPLANNED_REASON, display_name="PyTest mechanical fault", category="FAILURE", is_planned=False)
    )
    await repository.save_downtime_reason(
        DowntimeReasonSpec(code=PLANNED_REASON, display_name="PyTest changeover", category="PLANNED", is_planned=True)
    )
    await repository.save_state_reason_rule(
        StateReasonRuleSpec(state_value="ABORTED", reason_code=UNPLANNED_REASON, asset_path=LINE_PATH)
    )
    await repository.save_oee_unit(
        OeeUnitSpec(
            asset_path=LINE_PATH,
            shift_pattern_name=PATTERN_NAME,
            state_metric_key=STATE_KEY,
            good_count_metric_key=GOOD_KEY,
            reject_count_metric_key=REJECT_KEY,
            producing_states=("EXECUTE",),
        )
    )
    await repository.save_ideal_cycle_time(IdealCycleTimeSpec(asset_path=LINE_PATH, seconds_per_unit=5.0))


async def _insert_samples(database: Database, rows: list[tuple[datetime, str, str, float | None, str | None]]) -> None:
    async with database.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO uns_metrics (time, topic, metric_name, value_double, value_text) "
                "VALUES (:time, :topic, :metric_name, :value_double, :value_text)"
            ),
            [
                {"time": at, "topic": topic, "metric_name": name, "value_double": number, "value_text": word}
                for at, topic, name, number, word in rows
            ],
        )


def _state(at: datetime, value: str):
    ref = split_metric_key(LINE_PATH, STATE_KEY)
    return (at, ref.topic, ref.metric_name, None, value)


def _counter(at: datetime, key: str, value: float):
    ref = split_metric_key(LINE_PATH, key)
    return (at, ref.topic, ref.metric_name, value, None)


async def _seed_shift_samples(database: Database) -> None:
    """One producing shift with a single 30-minute ABORTED stop in the middle."""
    await _insert_samples(
        database,
        [
            _state(SHIFT_START, "EXECUTE"),
            _state(STOP_START, "ABORTED"),
            _state(STOP_END, "EXECUTE"),
            # Counters are read as deltas, so the first sample is the baseline.
            _counter(SHIFT_START, GOOD_KEY, 1000.0),
            _counter(SHIFT_END - timedelta(minutes=1), GOOD_KEY, 5800.0),
            _counter(SHIFT_START, REJECT_KEY, 0.0),
            _counter(SHIFT_END - timedelta(minutes=1), REJECT_KEY, 200.0),
        ],
    )


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(database: Database):
    """Master data and one shift's samples, with nothing left behind either side."""
    await _clean(database)
    await _seed_master_data(database)
    await _seed_shift_samples(database)
    yield database
    await _clean(database)


@pytest_asyncio.fixture(loop_scope="session")
async def unit(seeded: Database):
    """The one `UnitMasterData` these tests compute, loaded through the real joins."""
    units = [item for item in await MasterDataLoader(seeded).active_units() if item.asset_path == LINE_PATH]
    assert len(units) == 1, "the test unit was not loaded; is the 0003 migration applied?"
    return units[0]


@pytest_asyncio.fixture(loop_scope="session")
async def pipeline(seeded: Database):
    """A pipeline whose only stub is the broker."""
    publisher = _RecordingPublisher()
    config = OeeConfig(mqtt_host="localhost")
    yield ShiftPipeline(
        MetricSource(seeded, metrics_table=config.metrics_table),
        MasterDataLoader(seeded),
        ResultStore(seeded),
        publisher,
    ), publisher


async def _stored(database: Database, unit_id: int) -> dict:
    async with database.begin() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT revision, status, loading_time_s, run_time_s, planned_down_s, unplanned_down_s, "
                    "good_count, reject_count, total_count, availability, performance, quality, oee, published_at "
                    "FROM oee.shift_result WHERE oee_unit_id = :unit AND shift_start = :start"
                ),
                {"unit": unit_id, "start": SHIFT_START},
            )
        ).mappings().one()
    return dict(row)


# ---- the authored side and the reads


async def test_master_data_loader_resolves_every_binding(unit):
    """
    The joins in `master_data.py`, which no unit test can validate: four tables, two of
    them optional, plus an array column and a mapping keyed by a nullable product code.
    """
    assert unit.asset_path == LINE_PATH
    assert unit.schedule.timezone == "UTC"
    assert len(unit.schedule.slots) == 7
    assert unit.producing_states == ("EXECUTE",)
    assert unit.state_ref == split_metric_key(LINE_PATH, STATE_KEY)
    assert unit.good_ref == split_metric_key(LINE_PATH, GOOD_KEY)
    assert unit.reject_ref == split_metric_key(LINE_PATH, REJECT_KEY)
    assert unit.product_ref is None
    # The Asset-wide row: keyed by None, which is what makes a single-product line work.
    assert unit.ideal_cycle_time_for(None) == pytest.approx(5.0)
    assert unit.resolver.resolve("ABORTED").code == UNPLANNED_REASON


async def test_metric_source_reads_the_window_and_its_prior_sample(seeded: Database, unit):
    """
    `include_prior` is the difference between a shift that starts mid-stop being counted
    as running and being counted as stopped. It needs a real query to prove.
    """
    source = MetricSource(seeded)

    states = await source.text_samples(unit.state_ref, SHIFT_START, SHIFT_END)
    assert [sample.value for sample in states] == ["EXECUTE", "ABORTED", "EXECUTE"]

    # A window starting inside the stop must still learn the machine was ABORTED.
    later = await source.text_samples(unit.state_ref, STOP_START + timedelta(minutes=5), SHIFT_END)
    assert later[0].value == "ABORTED"
    assert later[0].at <= STOP_START

    counts = await source.numeric_samples(unit.good_ref, SHIFT_START, SHIFT_END)
    assert [sample.value for sample in counts] == [1000.0, 5800.0]


async def test_the_fingerprint_and_the_earliest_sample_come_from_sql(seeded: Database, unit):
    source = MetricSource(seeded)

    fingerprint = await source.fingerprint(unit.refs, SHIFT_START, SHIFT_END)

    assert fingerprint.row_count == 7
    assert fingerprint.max_time == SHIFT_END - timedelta(minutes=1)
    assert not fingerprint.is_empty
    # What bounds backfill: shifts ending before this are skipped, not written as zero.
    assert await source.earliest_sample_at(unit.refs) == SHIFT_START


# ---- computing, storing, and not storing


async def test_one_shift_stores_the_result_its_products_and_its_stop(seeded: Database, unit, pipeline):
    engine, publisher = pipeline

    outcome = await engine.run_shift(unit, WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.revision == 1
    assert outcome.published is True
    assert publisher.published == 1

    stored = await _stored(seeded, unit.unit_id)
    assert stored["status"] == "OK"
    assert stored["loading_time_s"] == pytest.approx(28800.0)
    assert stored["run_time_s"] == pytest.approx(27000.0)
    assert stored["planned_down_s"] == pytest.approx(0.0)
    assert stored["unplanned_down_s"] == pytest.approx(1800.0)
    assert stored["good_count"] == pytest.approx(4800.0)
    assert stored["reject_count"] == pytest.approx(200.0)
    assert stored["total_count"] == pytest.approx(5000.0)
    assert stored["availability"] == pytest.approx(EXPECTED_AVAILABILITY)
    assert stored["performance"] == pytest.approx(EXPECTED_PERFORMANCE)
    assert stored["quality"] == pytest.approx(EXPECTED_QUALITY)
    assert stored["oee"] == pytest.approx(EXPECTED_OEE)
    # Set by `mark_published`, which is a second statement: an unset value here means the
    # engine would republish the same revision on the next pass.
    assert stored["published_at"] is not None

    async with seeded.begin() as connection:
        stop = (
            await connection.execute(
                text(
                    "SELECT started_at, ended_at, duration_s, state_value, reason_code, reason_source "
                    "FROM oee.downtime_event WHERE oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).mappings().one()
    assert stop["started_at"] == STOP_START
    assert stop["ended_at"] == STOP_END
    assert stop["duration_s"] == pytest.approx(1800.0)
    assert stop["state_value"] == "ABORTED"
    assert stop["reason_code"] == UNPLANNED_REASON
    assert stop["reason_source"] == "auto"


async def test_an_unchanged_fingerprint_writes_nothing(seeded: Database, unit, pipeline):
    """
    The whole recomputation design rests on this: the CLI, the queue and the scheduler can
    all ask for the same range and only the first one writes.
    """
    engine, publisher = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    first = await _stored(seeded, unit.unit_id)

    again = await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(minutes=10))

    assert again.action == ACTION_UNCHANGED
    assert again.revision == 1
    assert publisher.published == 1, "an unchanged shift must not be republished"
    assert await _stored(seeded, unit.unit_id) == first
    async with seeded.begin() as connection:
        revisions = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM oee.shift_result_revision v "
                    "JOIN oee.shift_result r ON r.id = v.shift_result_id WHERE r.oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).scalar()
    assert revisions == 0


async def test_late_data_bumps_the_revision_and_preserves_the_previous(seeded: Database, unit, pipeline):
    engine, publisher = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)

    # An edge connector reconnecting and flushing a buffered sample inside the window.
    await _insert_samples(seeded, [_counter(SHIFT_END - timedelta(seconds=30), GOOD_KEY, 5900.0)])
    revised = await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(hours=1))

    assert revised.action == ACTION_REVISED
    assert revised.revision == 2
    assert publisher.published == 2, "a restated shift is published again"

    stored = await _stored(seeded, unit.unit_id)
    assert stored["revision"] == 2
    assert stored["good_count"] == pytest.approx(4900.0)

    async with seeded.begin() as connection:
        previous = (
            await connection.execute(
                text(
                    "SELECT v.revision, v.good_count, v.oee FROM oee.shift_result_revision v "
                    "JOIN oee.shift_result r ON r.id = v.shift_result_id WHERE r.oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).mappings().all()
    # The superseded number is kept, which is what makes a restatement explainable.
    assert [row["revision"] for row in previous] == [1]
    assert previous[0]["good_count"] == pytest.approx(4800.0)
    assert previous[0]["oee"] == pytest.approx(EXPECTED_OEE)


async def test_two_pipelines_computing_the_same_shift_produce_one_row(seeded: Database, unit):
    """
    Two engines, or an engine and the CLI. `ResultStore.save` upserts on
    (oee_unit_id, shift_start); without that this is two rows and the dashboard shows the
    shift twice.
    """
    stores = [
        ShiftPipeline(MetricSource(seeded), MasterDataLoader(seeded), ResultStore(seeded), _RecordingPublisher())
        for _ in range(2)
    ]

    outcomes = await asyncio.gather(*(engine.run_shift(unit, WINDOW, COMPUTED_AT) for engine in stores))

    async with seeded.begin() as connection:
        rows = (
            await connection.execute(
                text("SELECT count(*) FROM oee.shift_result WHERE oee_unit_id = :unit"), {"unit": unit.unit_id}
            )
        ).scalar()
    assert rows == 1
    assert {outcome.revision for outcome in outcomes} <= {1, 2}


# ---- corrections


async def _assign_planned_reason(database: Database, unit) -> int:
    """Reassign the shift's one stop to a planned reason, as the mutation would."""
    repository = OeeResultRepository(database)
    events = await repository.downtime_events(LINE_PATH, SHIFT_START, SHIFT_END)
    assert len(events) == 1
    assigned = await repository.assign_reason(
        int(events[0].event.id), PLANNED_REASON, note="pytest", assigned_by="pytest"
    )
    assert assigned is not None
    return int(events[0].event.id)


async def test_a_manual_reason_survives_a_recompute(seeded: Database, unit, pipeline):
    """
    Rule 3. Without it, the next pass would silently overwrite the correction with the
    state-code default and the number would flip back an hour after somebody fixed it.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    event_id = await _assign_planned_reason(seeded, unit)

    await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(hours=1))

    async with seeded.begin() as connection:
        stop = (
            await connection.execute(
                text("SELECT reason_code, reason_source, assigned_by, note FROM oee.downtime_event WHERE id = :id"),
                {"id": event_id},
            )
        ).mappings().one()
    assert stop["reason_code"] == PLANNED_REASON
    assert stop["reason_source"] == "manual"
    assert stop["assigned_by"] == "pytest"
    assert stop["note"] == "pytest"


async def test_reassigning_to_a_planned_reason_raises_availability(seeded: Database, unit, pipeline):
    """
    The reason this is a recomputation and not a relabelling: `is_planned` moves the 1800
    seconds out of Loading Time, so Availability goes from 15/16 to 1.0 and OEE to 8/9.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    await _assign_planned_reason(seeded, unit)

    revised = await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(hours=1))

    assert revised.action == ACTION_REVISED
    stored = await _stored(seeded, unit.unit_id)
    assert stored["loading_time_s"] == pytest.approx(27000.0)
    assert stored["planned_down_s"] == pytest.approx(1800.0)
    assert stored["unplanned_down_s"] == pytest.approx(0.0)
    assert stored["availability"] == pytest.approx(1.0)
    assert stored["oee"] == pytest.approx(8 / 9)


async def test_assigning_a_reason_queues_exactly_that_shift(seeded: Database, unit, pipeline):
    """
    `SINGLE_SHIFT_MARGIN` is one second, and `shift_windows` selects by start. The queued
    range must therefore name this shift and not the one that begins when it ends.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    await _assign_planned_reason(seeded, unit)

    async with seeded.begin() as connection:
        queued = (
            await connection.execute(
                text(
                    "SELECT range_start, range_end, requested_by, completed_at FROM oee.recompute_request "
                    "WHERE oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).mappings().all()
    assert len(queued) == 1
    assert queued[0]["range_start"] == SHIFT_START
    assert queued[0]["range_end"] == SHIFT_START + timedelta(seconds=1)
    assert queued[0]["requested_by"] == "pytest"
    assert queued[0]["completed_at"] is None


# ---- what the console reads back


async def test_the_result_repository_reads_what_the_engine_wrote(seeded: Database, unit, pipeline):
    """
    The four selects in `oee_results.py`, whose unit tests only pin statement order. The
    Pareto's shares must sum to 1 and its seconds to the stored downtime, or the events
    table and the Pareto chart on one dashboard disagree.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    repository = OeeResultRepository(seeded)

    results = await repository.shift_results(LINE_PATH, SHIFT_START, SHIFT_END + timedelta(days=1))
    assert len(results) == 1
    assert results[0].asset_path == LINE_PATH
    assert results[0].result.oee == pytest.approx(EXPECTED_OEE)
    # One product segment, from the Asset-wide ideal cycle time.
    assert [product.ideal_cycle_time_s for product in results[0].products] == [pytest.approx(5.0)]

    events = await repository.downtime_events(LINE_PATH, SHIFT_START, SHIFT_END)
    assert [event.event.reason_code for event in events] == [UNPLANNED_REASON]
    assert events[0].display_name == "PyTest mechanical fault"
    assert events[0].is_planned is False

    pareto = await repository.downtime_pareto(LINE_PATH, SHIFT_START, SHIFT_END)
    assert [bucket.reason_code for bucket in pareto] == [UNPLANNED_REASON]
    assert pareto[0].event_count == 1
    assert pareto[0].total_seconds == pytest.approx(1800.0)
    assert pareto[0].share == pytest.approx(1.0)


async def test_an_asset_with_no_results_reads_back_empty(seeded: Database):
    """One round trip and an empty list, not an error: a line whose first shift is open."""
    repository = OeeResultRepository(seeded)

    assert await repository.shift_results("No/Such/Asset", SHIFT_START, SHIFT_END) == []
    assert await repository.downtime_events("No/Such/Asset", SHIFT_START, SHIFT_END) == []
    assert await repository.downtime_pareto("No/Such/Asset", SHIFT_START, SHIFT_END) == []


async def test_assigning_an_unauthored_reason_is_refused_before_the_foreign_key(seeded: Database, unit, pipeline):
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    repository = OeeResultRepository(seeded)
    events = await repository.downtime_events(LINE_PATH, SHIFT_START, SHIFT_END)

    with pytest.raises(ValueError, match="not an authored downtime reason code"):
        await repository.assign_reason(int(events[0].event.id), "PYTEST_NOT_A_REASON")


# ---- the scheduler's three pieces of SQL


async def test_claim_requests_hands_each_row_to_one_claimer(seeded: Database, unit):
    """
    `FOR UPDATE SKIP LOCKED` in a `RETURNING` update. Two claimers must partition the
    queue, not both take it: a doubly-claimed range is a shift computed twice concurrently.
    """
    async with seeded.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO oee.recompute_request (oee_unit_id, range_start, range_end, reason) "
                "SELECT :unit, :start + (n || ' days')::interval, :end + (n || ' days')::interval, 'pytest' "
                "FROM generate_series(0, 3) AS n"
            ),
            {"unit": unit.unit_id, "start": SHIFT_START, "end": SHIFT_END},
        )

    first, second = await asyncio.gather(
        claim_requests(seeded, COMPUTED_AT, limit=2), claim_requests(seeded, COMPUTED_AT, limit=2)
    )

    mine = [claim for claim in first + second if claim.unit_id == unit.unit_id]
    assert len(mine) == 4
    assert len({claim.request_id for claim in mine}) == 4, "a request was claimed twice"

    await complete_requests(seeded, [claim.request_id for claim in mine], COMPUTED_AT)
    async with seeded.begin() as connection:
        outstanding = (
            await connection.execute(
                text("SELECT count(*) FROM oee.recompute_request WHERE oee_unit_id = :unit AND completed_at IS NULL"),
                {"unit": unit.unit_id},
            )
        ).scalar()
    assert outstanding == 0
    # Claimed rows must not come back on the next pass.
    assert [claim for claim in await claim_requests(seeded, COMPUTED_AT) if claim.unit_id == unit.unit_id] == []


async def test_retention_days_reads_the_timescale_job_table(seeded: Database):
    """
    Queries `timescaledb_information.jobs`, whose shape changes between Timescale versions.
    `None` is a valid answer - a database with no retention policy - so what is asserted is
    that the query runs and returns something usable rather than raising.
    """
    days = await retention_days(seeded, "uns_metrics")

    assert days is None or days > 0
```

- [ ] **Step 2: Run it against a real database**

Bring the stack up if it is not already:

```bash
UNS_graphdb__password=password1 UNS_historian__password=password2 PGPASSWORD=password3 \
  docker compose up -d uns_timescale_db tsdb_setup_script asset_model_setup
```

Run: `uv run pytest 12_uns_oee/test/test_integration.py -v -n 0 -m integrationtest`
Expected: PASS (14 passed).

Failures worth recognising, because each has one cause:
- `AssertionError: the test unit was not loaded; is the 0003 migration applied?` — `asset_model_setup` has not run against this database, or ran before Task 2 existed. Re-run it.
- `UndefinedTableError: relation "oee.shift_result" does not exist` — same cause, seen one layer lower.
- `relation "uns_metrics" does not exist` — `tsdb_setup_script` has not applied `04_setup_metrics_hypertable.sql`.
- `MissingGreenlet` — something added a `relationship()` to `oee_tables.py`, or a test touched an attribute outside a session. Task 2 says why the relationships are absent; do not add them to make this pass.

- [ ] **Step 3: Verify the suite still passes without a database**

Run: `uv run pytest 12_uns_oee/test -q -m "not integrationtest"`
Expected: PASS, with the integration file deselected entirely. If it errors at *collection* rather than being deselected, an import at module scope is reaching the database — move it into a fixture.

- [ ] **Step 4: Run the linter**

Run: `uv run ruff check 12_uns_oee/test/test_integration.py`
Expected: no findings.

- [ ] **Step 5: Commit**

```bash
git add 12_uns_oee/test/test_integration.py
git commit -m "test(oee): integration tests for the engine's SQL against a real Postgres"
```

---
