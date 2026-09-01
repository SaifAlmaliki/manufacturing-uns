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
| `12_uns_oee/pyproject.toml` | Module packaging, workspace-relative editable deps on `00_uns_config`, `09_uns_model`, `02_mqtt-cluster`. |
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
- Produces: `OeeConfig` (frozen dataclass) with fields `metrics_port: int`, `scan_interval_seconds: float`, `settle_minutes: int`, `late_window_hours: int`, `backfill_days: int`, `mqtt_host: str | None`, `mqtt_port: int`, `mqtt_client_id: str`, `mqtt_qos: int`, `mqtt_username: str | None`, `mqtt_password: str | None`, `metrics_table: str`; classmethod `OeeConfig.from_settings(module_env: str = "oee") -> OeeConfig`; method `is_valid() -> bool`.

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
    "psutil>=6.1.0,<8",
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
Expected: PASS (3 passed).

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
