# ISA-95 Asset Authoring — Model Core & Write API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Asset Model writable — single-Asset CRUD, rename/move/duplicate, Metric Definition CRUD, adopting Unmodelled Topics, and Asset Templates that instantiate N times and propagate live — exposed as GraphQL mutations so the console has an API to build against.

**Architecture:** Postgres stays the single authored source of truth (ADR-0003). Every structural write happens in **one** transaction that also rebinds `model.topic_binding` and issues `NOTIFY asset_model_changed`, so a failed write cannot leave stale bindings behind. Asset Templates are a second authored tree (`model.asset_template_node`) that Assets point back to; editing a template *projects* onto its instances immediately, skipping any field an engineer has overridden locally. The seed stops reconciling and becomes bootstrap-only, which removes the second writer.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async ORM + Core, Alembic, asyncpg, Postgres/TimescaleDB, Strawberry GraphQL, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-03-isa95-asset-authoring-design.md`

## Global Constraints

- **The four rules the design serves** (spec §3), which every task is judged against:
  1. The Asset Model is authored in Postgres and nowhere else. YAML bootstraps an empty database; after that the console is the only writer.
  2. A derived fact is never authored. `model.topic_binding` is rebuilt, never edited.
  3. A template edit may not silently discard an engineer's work. An overridden field wins.
  4. Every write to the Asset tree rebinds topics **in the same transaction as the write**, and announces the change.
- **`starts_with(path, prefix)`, never `LIKE prefix || '%'`.** Segments contain underscores and `_` is a LIKE wildcard (`repositories.py:47`).
- **Deactivate, never delete, when propagating.** `oee_unit`, `shift_pattern`, `shift_exception` and `ideal_cycle_time` all hold `ON DELETE CASCADE` FKs to `model.asset`, so deleting an Asset silently destroys its OEE configuration.
- **New template FKs are `ON DELETE SET NULL`.** Dropping a template must never delete the Assets it created.
- **New Python modules carry a plain docstring, no copyright block** — follow `oee_master_data.py`, not `tables.py`.
- **Migrations duplicate constants from application code on purpose** — follow `0004`'s predecessor `migrations/versions/0003_oee_model.py`; a migration must not import from `uns_model`.
- **Vocabulary is fixed** (spec §5): Asset Template, Template Node, Instance Override, Plant Scope, Metric Definition, Unit of Measure (never `unit`), Unmodelled Topic.
- **Tests:** unit tests use fakes at the repository seam and need no database; anything needing Postgres is marked `@pytest.mark.integrationtest` and `@pytest.mark.asyncio(loop_scope="session")`, and writes only under `TEST_ROOT = "PyTestUNS"`.
- Run commands from the **repository root** with the single root `.venv`: `uv run pytest 09_uns_model/test/... -v`.

---

### Task 1: Enlist the rebind and the announcement in the caller's transaction

Today a structural write is three transactions: `session()` commits, then `rebind_all()` opens its own `begin()`, then `announce_asset_model_changed()` opens a third (`repositories.py:274`, `notifications.py:24`). A crash between them leaves committed structure with stale bindings. Both functions gain an optional `connection`; omitting it keeps today's behaviour exactly, so no existing caller or test moves.

**Files:**
- Modify: `09_uns_model/src/uns_model/notifications.py`
- Modify: `09_uns_model/src/uns_model/repositories.py` (`rebind_all`, around line 268)
- Test: `09_uns_model/test/test_asset_writes.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `async def announce_asset_model_changed(database: Database, *, connection: AsyncConnection | None = None) -> None`
  - `AssetModelRepository.rebind_all(self, *, connection: AsyncConnection | None = None) -> int`

- [ ] **Step 1: Write the failing test**

Create `09_uns_model/test/test_asset_writes.py`:

```python
"""
Unit tests for the Asset Model write primitives. No database: the fakes sit at the
`Database` seam, which is where the interesting decision lives — whether a write
opens a transaction of its own or joins the caller's.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from uns_model.notifications import announce_asset_model_changed
from uns_model.repositories import AssetModelRepository


class _Result:
    """Just enough of a SQLAlchemy Result for code that only reads rowcount."""

    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _RecordingConnection:
    """Records the SQL it is handed, so a test can assert what ran and in what order."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: Any, parameters: Any = None) -> _Result:
        self.statements.append(str(statement))
        return _Result(rowcount=0)


class _NoConnectionDatabase:
    """A Database that fails the test if anything opens a transaction of its own."""

    @asynccontextmanager
    async def begin(self):
        raise AssertionError("opened its own transaction instead of using the caller's connection")
        yield  # pragma: no cover - unreachable, present so this is a generator

    @asynccontextmanager
    async def session(self):
        raise AssertionError("opened its own session instead of using the caller's connection")
        yield  # pragma: no cover


@pytest.mark.asyncio
async def test_rebind_all_uses_the_supplied_connection():
    connection = _RecordingConnection()
    repository = AssetModelRepository(_NoConnectionDatabase())

    await repository.rebind_all(connection=connection)

    assert len(connection.statements) == 1


@pytest.mark.asyncio
async def test_announcing_a_change_uses_the_supplied_connection():
    connection = _RecordingConnection()

    await announce_asset_model_changed(_NoConnectionDatabase(), connection=connection)

    assert any("NOTIFY" in statement for statement in connection.statements)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest 09_uns_model/test/test_asset_writes.py -v`
Expected: FAIL — both tests raise `AssertionError: opened its own transaction ...`, because neither function accepts `connection` yet (`TypeError: unexpected keyword argument 'connection'` is the likely first error).

- [ ] **Step 3: Add the parameter to `announce_asset_model_changed`**

In `09_uns_model/src/uns_model/notifications.py`, replace the function body:

```python
async def announce_asset_model_changed(
    database: Database,
    *,
    connection: AsyncConnection | None = None,
) -> None:
    """
    Tell every listener that bindings or authored facts may have changed.

    Pass `connection` to enlist in the caller's transaction. NOTIFY is queued and
    delivered only when that transaction commits, so a rolled-back write never
    announces itself — which is why enlisting is strictly better than a second
    transaction of our own. Omitting it keeps the standalone behaviour.
    """
    statement = text(f"NOTIFY {ASSET_MODEL_CHANGED_CHANNEL}, ''")
    if connection is not None:
        await connection.execute(statement)
        return
    async with database.begin() as own_connection:
        await own_connection.execute(statement)
```

Add the import at the top of the file:

```python
from sqlalchemy.ext.asyncio import AsyncConnection
```

- [ ] **Step 4: Add the parameter to `rebind_all`**

In `09_uns_model/src/uns_model/repositories.py`, replace `rebind_all`:

```python
    async def rebind_all(self, *, connection: AsyncConnection | None = None) -> int:
        """
        Re-resolve every Topic Binding, and announce that the model changed.

        Pass `connection` to run inside the caller's transaction: a structural
        write and the rebind it invalidates must commit or roll back together
        (rule 4). Omitting it keeps the standalone behaviour the seed relies on.
        """
        if connection is not None:
            result = await connection.execute(text(_REBIND_ALL_SQL))
            moved = result.rowcount or 0
            await announce_asset_model_changed(self._database, connection=connection)
        else:
            async with self._database.begin() as own_connection:
                result = await own_connection.execute(text(_REBIND_ALL_SQL))
                moved = result.rowcount or 0
            await announce_asset_model_changed(self._database)
        if moved:
            LOGGER.info("Rebound %s topic(s) after an Asset Model change", moved)
        return moved
```

Add `AsyncConnection` to the imports if it is not already there:

```python
from sqlalchemy.ext.asyncio import AsyncConnection
```

- [ ] **Step 5: Run the tests to verify they pass, and that nothing else broke**

Run: `uv run pytest 09_uns_model/test/test_asset_writes.py -v`
Expected: PASS (2 passed)

Run: `uv run pytest 09_uns_model/test -v -m "not integrationtest"`
Expected: PASS — no existing test calls either function with `connection`, so all of them take the unchanged branch.

- [ ] **Step 6: Commit**

```bash
git add 09_uns_model/src/uns_model/notifications.py 09_uns_model/src/uns_model/repositories.py 09_uns_model/test/test_asset_writes.py
git commit -m "feat(model): let a rebind and its announcement join the caller's transaction"
```

---

### Task 2: Migration 0004 and the ORM for Asset Templates

Three new tables plus five new columns on existing ones. The migration is the schema of record; the ORM classes must match it exactly, because `create_all()` is what the unit tests build from.

**Files:**
- Create: `09_uns_model/migrations/versions/0004_asset_templates.py`
- Modify: `09_uns_model/src/uns_model/tables.py`
- Test: `09_uns_model/test/test_asset_templates.py` (create)

**Interfaces:**
- Consumes: `MODEL_SCHEMA` from `uns_model.model_config`, `Base`/`Asset`/`MetricDefinition` from `uns_model.tables`.
- Produces: ORM classes `AssetTemplate`, `AssetTemplateNode`, `AssetTemplateMetric`; new columns `Asset.template_id`, `Asset.template_node_id`, `Asset.overridden_fields`, `MetricDefinition.template_metric_id`, `MetricDefinition.is_overridden`. Alembic revision `0004_asset_templates` with `down_revision = "0003_oee_model"`.

- [ ] **Step 1: Write the failing test**

Create `09_uns_model/test/test_asset_templates.py`:

```python
"""
Unit tests for Asset Templates. The table shape is asserted against a SQLite-free
in-memory metadata check rather than a database: what matters here is that the ORM
declares the constraints the design depends on, and that a template FK cannot take
an Asset with it when the template is dropped.
"""

from __future__ import annotations

from uns_model.tables import Asset, AssetTemplate, AssetTemplateMetric, AssetTemplateNode, MetricDefinition


def test_a_template_node_is_unique_by_relative_path_within_its_template():
    names = {constraint.name for constraint in AssetTemplateNode.__table__.constraints}

    assert "uq_asset_template_node_relative_path" in names


def test_a_template_node_is_unique_by_segment_among_its_siblings():
    names = {constraint.name for constraint in AssetTemplateNode.__table__.constraints}

    assert "uq_asset_template_node_sibling_segment" in names


def test_dropping_a_template_does_not_delete_the_assets_it_made():
    # ON DELETE SET NULL, never CASCADE: an Asset outlives the template that made it,
    # and its OEE configuration hangs off it by CASCADE.
    for column_name in ("template_id", "template_node_id"):
        foreign_keys = list(Asset.__table__.c[column_name].foreign_keys)
        assert [key.ondelete for key in foreign_keys] == ["SET NULL"], column_name


def test_dropping_a_template_metric_does_not_delete_the_metric_definition():
    foreign_keys = list(MetricDefinition.__table__.c["template_metric_id"].foreign_keys)

    assert [key.ondelete for key in foreign_keys] == ["SET NULL"]


def test_a_template_metric_is_unique_by_key_within_its_node():
    names = {constraint.name for constraint in AssetTemplateMetric.__table__.constraints}

    assert "uq_asset_template_metric_key" in names


def test_a_template_name_is_unique():
    names = {constraint.name for constraint in AssetTemplate.__table__.constraints}

    assert "uq_asset_template_name" in names


def test_an_asset_records_which_of_its_fields_were_overridden_locally():
    assert Asset.__table__.c["overridden_fields"].nullable is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_asset_templates.py -v`
Expected: FAIL — `ImportError: cannot import name 'AssetTemplate' from 'uns_model.tables'`

- [ ] **Step 3: Add the ORM classes and columns**

In `09_uns_model/src/uns_model/tables.py`, add to the `Asset` class body, after `commissioned_on`:

```python
    template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset_template.id", ondelete="SET NULL"),
        nullable=True,
    )
    """Set on the instance root only: the Asset an `instantiate` call created."""

    template_node_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset_template_node.id", ondelete="SET NULL"),
        nullable=True,
    )
    """Set on every Asset the template made, including the instance root."""

    overridden_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    """Fields an engineer edited locally. Propagation leaves every one of them alone."""
```

Add to the `MetricDefinition` class body, after `description`:

```python
    template_metric_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset_template_metric.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The Template Metric this row was projected from, if any."""

    is_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    """True once an engineer edited this row by hand. Propagation skips it."""
```

Add `ARRAY` to the `sqlalchemy.dialects.postgresql` import:

```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
```

Then add the three new classes after `TopicBinding`:

```python
class AssetTemplate(Base):
    """
    A reusable Asset shape — ISA-95's Equipment Class, made concrete.

    A template is authored once and instantiated N times; the instances stay linked
    to it, so correcting the template corrects every line that uses it. It holds no
    path of its own: a template describes a subtree relative to wherever it lands.
    """

    __tablename__ = "asset_template"
    __table_args__ = (
        UniqueConstraint("name", name="uq_asset_template_name"),
        CheckConstraint("name <> ''", name="ck_asset_template_name_not_empty"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    root_level: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{MODEL_SCHEMA}.asset_level.name", onupdate="CASCADE"),
        nullable=False,
    )
    """The Asset Level the template's own root sits at, e.g. 'LINE'."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    nodes: Mapped[list[AssetTemplateNode]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"AssetTemplate(name={self.name!r}, root_level={self.root_level!r})"


class AssetTemplateNode(Base):
    """
    One Asset in a template's subtree, positioned by `relative_path`.

    `relative_path` is the path below the instance root and is empty for the root
    node itself, which is what makes a template placeable anywhere: instantiating
    at `Plant/Area` gives `Plant/Area/<segment>/<relative_path>`.
    """

    __tablename__ = "asset_template_node"
    __table_args__ = (
        UniqueConstraint("template_id", "relative_path", name="uq_asset_template_node_relative_path"),
        UniqueConstraint("parent_id", "segment", name="uq_asset_template_node_sibling_segment"),
        CheckConstraint("segment <> ''", name="ck_asset_template_node_segment_not_empty"),
        CheckConstraint("id <> parent_id", name="ck_asset_template_node_not_its_own_parent"),
        Index("idx_asset_template_node_template", "template_id"),
        Index("idx_asset_template_node_parent", "parent_id"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset_template.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset_template_node.id", ondelete="CASCADE"),
        nullable=True,
    )
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """'' for the root node, else e.g. 'Cell1/Mixer'."""

    level: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{MODEL_SCHEMA}.asset_level.name", onupdate="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    template: Mapped[AssetTemplate] = relationship(back_populates="nodes")
    metrics: Mapped[list[AssetTemplateMetric]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"AssetTemplateNode(relative_path={self.relative_path!r}, level={self.level!r})"


class AssetTemplateMetric(Base):
    """A Metric Definition a template projects onto every instance of one node."""

    __tablename__ = "asset_template_metric"
    __table_args__ = (
        UniqueConstraint("template_node_id", "metric_key", name="uq_asset_template_metric_key"),
        CheckConstraint("metric_key <> ''", name="ck_asset_template_metric_key_not_empty"),
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_asset_template_metric_range",
        ),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    template_node_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset_template_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(Text, nullable=True)
    decimals: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    min_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    deadband: Mapped[float | None] = mapped_column(Double, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    node: Mapped[AssetTemplateNode] = relationship(back_populates="metrics")

    def __repr__(self) -> str:
        return f"AssetTemplateMetric(metric_key={self.metric_key!r})"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 09_uns_model/test/test_asset_templates.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Write the migration**

Create `09_uns_model/migrations/versions/0004_asset_templates.py`:

```python
"""Asset Templates, and the columns that link an Asset back to the template that made it.

Revision ID: 0004_asset_templates
Revises: 0003_oee_model

The constants below are duplicated from `uns_model.tables` on purpose: a migration
describes the database as it was at this revision, so it must not import code that
will keep changing underneath it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_asset_templates"
down_revision = "0003_oee_model"
branch_labels = None
depends_on = None

MODEL_SCHEMA = "model"


def upgrade() -> None:
    op.create_table(
        "asset_template",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("root_level", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_asset_template_name"),
        sa.CheckConstraint("name <> ''", name="ck_asset_template_name_not_empty"),
        sa.ForeignKeyConstraint(
            ["root_level"], [f"{MODEL_SCHEMA}.asset_level.name"], onupdate="CASCADE"
        ),
        schema=MODEL_SCHEMA,
    )

    op.create_table(
        "asset_template_node",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("segment", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["template_id"], [f"{MODEL_SCHEMA}.asset_template.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], [f"{MODEL_SCHEMA}.asset_template_node.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["level"], [f"{MODEL_SCHEMA}.asset_level.name"], onupdate="CASCADE"),
        sa.UniqueConstraint("template_id", "relative_path", name="uq_asset_template_node_relative_path"),
        sa.UniqueConstraint("parent_id", "segment", name="uq_asset_template_node_sibling_segment"),
        sa.CheckConstraint("segment <> ''", name="ck_asset_template_node_segment_not_empty"),
        sa.CheckConstraint("id <> parent_id", name="ck_asset_template_node_not_its_own_parent"),
        schema=MODEL_SCHEMA,
    )
    op.create_index("idx_asset_template_node_template", "asset_template_node", ["template_id"], schema=MODEL_SCHEMA)
    op.create_index("idx_asset_template_node_parent", "asset_template_node", ["parent_id"], schema=MODEL_SCHEMA)

    op.create_table(
        "asset_template_metric",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("template_node_id", sa.BigInteger(), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("unit_of_measure", sa.Text(), nullable=True),
        sa.Column("decimals", sa.SmallInteger(), nullable=True),
        sa.Column("min_value", sa.Double(), nullable=True),
        sa.Column("max_value", sa.Double(), nullable=True),
        sa.Column("deadband", sa.Double(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["template_node_id"], [f"{MODEL_SCHEMA}.asset_template_node.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("template_node_id", "metric_key", name="uq_asset_template_metric_key"),
        sa.CheckConstraint("metric_key <> ''", name="ck_asset_template_metric_key_not_empty"),
        sa.CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_asset_template_metric_range",
        ),
        schema=MODEL_SCHEMA,
    )

    # SET NULL, not CASCADE: an Asset must outlive the template that made it, because
    # its OEE configuration hangs off the Asset by CASCADE.
    op.add_column("asset", sa.Column("template_id", sa.BigInteger(), nullable=True), schema=MODEL_SCHEMA)
    op.add_column("asset", sa.Column("template_node_id", sa.BigInteger(), nullable=True), schema=MODEL_SCHEMA)
    op.add_column(
        "asset",
        sa.Column(
            "overridden_fields",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        schema=MODEL_SCHEMA,
    )
    op.create_foreign_key(
        "fk_asset_template",
        "asset",
        "asset_template",
        ["template_id"],
        ["id"],
        source_schema=MODEL_SCHEMA,
        referent_schema=MODEL_SCHEMA,
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_asset_template_node",
        "asset",
        "asset_template_node",
        ["template_node_id"],
        ["id"],
        source_schema=MODEL_SCHEMA,
        referent_schema=MODEL_SCHEMA,
        ondelete="SET NULL",
    )
    op.create_index("idx_asset_template", "asset", ["template_id"], schema=MODEL_SCHEMA)
    op.create_index("idx_asset_template_node_id", "asset", ["template_node_id"], schema=MODEL_SCHEMA)

    op.add_column(
        "metric_definition", sa.Column("template_metric_id", sa.BigInteger(), nullable=True), schema=MODEL_SCHEMA
    )
    op.add_column(
        "metric_definition",
        sa.Column("is_overridden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=MODEL_SCHEMA,
    )
    op.create_foreign_key(
        "fk_metric_definition_template_metric",
        "metric_definition",
        "asset_template_metric",
        ["template_metric_id"],
        ["id"],
        source_schema=MODEL_SCHEMA,
        referent_schema=MODEL_SCHEMA,
        ondelete="SET NULL",
    )

    _grant()


def _grant() -> None:
    """Give the application role the same access it has on the older tables."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uns_dbuser') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON
                    {MODEL_SCHEMA}.asset_template,
                    {MODEL_SCHEMA}.asset_template_node,
                    {MODEL_SCHEMA}.asset_template_metric
                TO uns_dbuser;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_metric_definition_template_metric", "metric_definition", schema=MODEL_SCHEMA)
    op.drop_column("metric_definition", "is_overridden", schema=MODEL_SCHEMA)
    op.drop_column("metric_definition", "template_metric_id", schema=MODEL_SCHEMA)

    op.drop_index("idx_asset_template_node_id", "asset", schema=MODEL_SCHEMA)
    op.drop_index("idx_asset_template", "asset", schema=MODEL_SCHEMA)
    op.drop_constraint("fk_asset_template_node", "asset", schema=MODEL_SCHEMA)
    op.drop_constraint("fk_asset_template", "asset", schema=MODEL_SCHEMA)
    op.drop_column("asset", "overridden_fields", schema=MODEL_SCHEMA)
    op.drop_column("asset", "template_node_id", schema=MODEL_SCHEMA)
    op.drop_column("asset", "template_id", schema=MODEL_SCHEMA)

    op.drop_table("asset_template_metric", schema=MODEL_SCHEMA)
    op.drop_index("idx_asset_template_node_parent", "asset_template_node", schema=MODEL_SCHEMA)
    op.drop_index("idx_asset_template_node_template", "asset_template_node", schema=MODEL_SCHEMA)
    op.drop_table("asset_template_node", schema=MODEL_SCHEMA)
    op.drop_table("asset_template", schema=MODEL_SCHEMA)
```

- [ ] **Step 6: Check the migration produces valid SQL and matches the ORM**

Run: `uv run uns_model_migrate --sql`
Expected: the DDL for all three tables and the five columns prints without error.

Run: `uv run pytest 09_uns_model/test/test_migrations_asyncpg.py -v`
Expected: PASS. If this suite compares Alembic's head against `Base.metadata`, any mismatch between Step 3 and Step 5 shows up here — fix the migration to match the ORM, not the other way round.

- [ ] **Step 7: Commit**

```bash
git add 09_uns_model/migrations/versions/0004_asset_templates.py 09_uns_model/src/uns_model/tables.py 09_uns_model/test/test_asset_templates.py
git commit -m "feat(model): add Asset Template tables and the Asset columns that link to them"
```

---

### Task 3: `AssetWriteSpec` and `save_asset` / `set_active`

The console saves **one** Asset with every authored column, which `AssetSpec` cannot express — and must not learn to. `AssetSpec` is the *seed's* branch spec, and `ensure_branch`'s upsert sets only the columns the seed knows about; teaching it `manufacturer` would blank an engineer's entry on every re-seed. So a second, separate spec.

**Files:**
- Modify: `09_uns_model/src/uns_model/repositories.py`
- Modify: `09_uns_model/src/uns_model/__init__.py` (export `AssetWriteSpec`)
- Test: `09_uns_model/test/test_asset_writes.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `rebind_all(connection=...)` from Task 1; `Asset.overridden_fields`, `AssetTemplateNode` from Task 2.
- Produces:
  - `AssetWriteSpec(path, level, display_name=None, description=None, manufacturer=None, model_number=None, serial_number=None, criticality=None, commissioned_on=None, attributes={}, is_active=True)` with `.segment`, `.parent_path`, `.validate()`
  - `AssetModelRepository.save_asset(self, spec: AssetWriteSpec) -> Asset`
  - `AssetModelRepository.set_active(self, path: str, *, is_active: bool) -> int` — returns the number of Assets changed, the subtree included.

- [ ] **Step 1: Write the failing unit tests for the spec**

Append to `09_uns_model/test/test_asset_writes.py`:

```python
from uns_model.repositories import AssetWriteSpec


def test_a_spec_knows_its_own_segment_and_parent():
    spec = AssetWriteSpec(path="Co/PlantA/Area1/Line1", level="LINE")

    assert spec.segment == "Line1"
    assert spec.parent_path == "Co/PlantA/Area1"


def test_a_root_spec_has_no_parent():
    spec = AssetWriteSpec(path="Co", level="ENTERPRISE")

    assert spec.parent_path is None


def test_a_path_with_an_empty_segment_is_rejected():
    with pytest.raises(ValueError, match="empty segment"):
        AssetWriteSpec(path="Co//Line1", level="LINE").validate()


def test_a_path_with_leading_or_trailing_separators_is_rejected():
    with pytest.raises(ValueError, match="empty segment"):
        AssetWriteSpec(path="/Co", level="ENTERPRISE").validate()


def test_a_blank_path_is_rejected():
    with pytest.raises(ValueError, match="path is required"):
        AssetWriteSpec(path="   ", level="ENTERPRISE").validate()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest 09_uns_model/test/test_asset_writes.py -v -k spec or parent or path`
Expected: FAIL — `ImportError: cannot import name 'AssetWriteSpec'`

- [ ] **Step 3: Add the spec**

In `09_uns_model/src/uns_model/repositories.py`, after the existing `AssetSpec` declaration:

```python
@dataclass(frozen=True, slots=True)
class AssetWriteSpec:
    """
    One Asset as the console authors it, addressed by full path.

    Deliberately *not* an extension of `AssetSpec`. `AssetSpec` is the seed's
    branch spec and its upsert touches only the columns a seed knows about; if it
    grew a `manufacturer`, every re-seed would blank the one an engineer typed.
    """

    path: str
    level: str
    display_name: str | None = None
    description: str | None = None
    manufacturer: str | None = None
    model_number: str | None = None
    serial_number: str | None = None
    criticality: str | None = None
    commissioned_on: date | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    is_active: bool = True

    # The columns propagation and override-tracking both reason about, in the order
    # a form shows them. `path`, `level` and `is_active` are structural, not authored
    # detail, so they are not overridable fields.
    AUTHORED_FIELDS: ClassVar[tuple[str, ...]] = (
        "display_name",
        "description",
        "manufacturer",
        "model_number",
        "serial_number",
        "criticality",
        "commissioned_on",
        "attributes",
    )

    @property
    def segment(self) -> str:
        """The last path segment: the Asset's own name."""
        return self.path.rsplit(SEPARATOR, 1)[-1]

    @property
    def parent_path(self) -> str | None:
        """The parent's path, or None for an Enterprise at the root."""
        if SEPARATOR not in self.path:
            return None
        return self.path.rsplit(SEPARATOR, 1)[0]

    def validate(self) -> None:
        """Reject what Postgres would reject, with a message a human can act on."""
        if not self.path.strip():
            raise ValueError("An Asset path is required")
        if any(not segment for segment in self.path.split(SEPARATOR)):
            raise ValueError(f"Asset path {self.path!r} has an empty segment")
        if not self.level:
            raise ValueError("An Asset Level is required")
```

Add to the imports at the top of the file whatever is missing:

```python
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar
from collections.abc import Mapping
```

- [ ] **Step 4: Run the spec tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_asset_writes.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing integration tests for `save_asset` and `set_active`**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_saving_an_asset_writes_every_authored_column(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    saved = await repository.save_asset(
        AssetWriteSpec(
            path=MIXER_PATH,
            level="MACHINE",
            display_name="Mixer Tank One",
            manufacturer="Bühler",
            model_number="MT-400",
            serial_number="SN-0001",
            criticality="HIGH",
            attributes={"volume_litres": 400},
        )
    )

    assert saved.display_name == "Mixer Tank One"
    assert saved.manufacturer == "Bühler"
    assert saved.attributes == {"volume_litres": 400}


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_saving_an_asset_under_a_missing_parent_is_refused(repository: AssetModelRepository):
    with pytest.raises(ValueError, match="No Asset at"):
        await repository.save_asset(
            AssetWriteSpec(path=f"{TEST_ROOT}/Nowhere/Line9", level="LINE")
        )


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_asset_may_not_sit_above_its_parent(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    with pytest.raises(ValueError, match="cannot sit under"):
        await repository.save_asset(AssetWriteSpec(path=f"{CELL_PATH}/Site9", level="SITE"))


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deactivating_an_asset_deactivates_its_subtree(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    changed = await repository.set_active(CELL_PATH, is_active=False)

    assert changed >= 2  # the Work Cell and the Mixer under it
    assert (await repository.get_asset(MIXER_PATH)).is_active is False

    await repository.set_active(CELL_PATH, is_active=True)
    assert (await repository.get_asset(MIXER_PATH)).is_active is True
```

Add `AssetWriteSpec` to the existing `from uns_model.repositories import ...` line in that file.

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "save_asset or set_active or sit_above or missing_parent"`
Expected: FAIL — `AttributeError: 'AssetModelRepository' object has no attribute 'save_asset'`

- [ ] **Step 7: Implement `save_asset` and `set_active`**

In `09_uns_model/src/uns_model/repositories.py`, add to `AssetModelRepository`:

```python
    async def save_asset(self, spec: AssetWriteSpec) -> Asset:
        """
        Create or update one Asset, addressed by path.

        Everything happens in a single transaction — the row, the rebind and the
        announcement — because Topic Bindings are derived from this row and must
        not survive a rolled-back write (rule 4).

        A field the caller changes on a template-linked Asset becomes an **Instance
        Override**: propagation will leave it alone from now on. Setting it back to
        the template's value drops the override again, so an override is a fact
        about divergence rather than a sticky flag.
        """
        spec.validate()
        ranks = await self.level_ranks()
        if spec.level not in ranks:
            raise ValueError(f"Unknown Asset Level: {spec.level!r}. Known: {sorted(ranks)}")

        async with self._database.session() as session:
            parent_id: int | None = None
            if spec.parent_path is not None:
                parent = (
                    await session.execute(select(Asset).where(Asset.path == spec.parent_path))
                ).scalar_one_or_none()
                if parent is None:
                    raise ValueError(f"No Asset at {spec.parent_path!r} to hang {spec.path!r} under")
                if ranks[spec.level] <= ranks[parent.level]:
                    raise ValueError(
                        f"Asset Level {spec.level!r} cannot sit under {parent.level!r}: "
                        "a branch may skip levels but not invert them"
                    )
                parent_id = parent.id

            existing = (await session.execute(select(Asset).where(Asset.path == spec.path))).scalar_one_or_none()
            if existing is None:
                asset = Asset(
                    parent_id=parent_id,
                    segment=spec.segment,
                    path=spec.path,
                    level=spec.level,
                    display_name=spec.display_name,
                    description=spec.description,
                    manufacturer=spec.manufacturer,
                    model_number=spec.model_number,
                    serial_number=spec.serial_number,
                    criticality=spec.criticality,
                    commissioned_on=spec.commissioned_on,
                    attributes=dict(spec.attributes),
                    is_active=spec.is_active,
                )
                session.add(asset)
            else:
                asset = existing
                asset.level = spec.level
                asset.parent_id = parent_id
                for name in AssetWriteSpec.AUTHORED_FIELDS:
                    value = getattr(spec, name)
                    setattr(asset, name, dict(value) if name == "attributes" else value)
                asset.is_active = spec.is_active
                asset.overridden_fields = await self._overrides_after_edit(session, asset, spec)

            await session.flush()
            connection = await session.connection()
            await self.rebind_all(connection=connection)
            await session.refresh(asset)
            return asset

    async def _overrides_after_edit(
        self, session: AsyncSession, asset: Asset, spec: AssetWriteSpec
    ) -> list[str]:
        """
        Which authored fields now differ from the template that made this Asset.

        An Asset with no template has no overrides to track. Comparing against the
        Template Node rather than against the previous value means an engineer who
        types the template's own value back in stops being overridden.
        """
        if asset.template_node_id is None:
            return list(asset.overridden_fields or ())
        node = (
            await session.execute(
                select(AssetTemplateNode).where(AssetTemplateNode.id == asset.template_node_id)
            )
        ).scalar_one_or_none()
        if node is None:
            return list(asset.overridden_fields or ())
        overridden = []
        for name in AssetWriteSpec.AUTHORED_FIELDS:
            if not hasattr(node, name):
                continue
            if getattr(spec, name) != getattr(node, name):
                overridden.append(name)
        return overridden

    async def set_active(self, path: str, *, is_active: bool) -> int:
        """
        Activate or deactivate an Asset and everything under it.

        Deactivation is how the model retires equipment: the row stays, so its
        history, its Topic Bindings and its OEE configuration all survive — which
        deleting it would not allow (`oee_unit.asset_id` cascades).
        """
        async with self._database.session() as session:
            connection = await session.connection()
            result = await connection.execute(
                text(
                    """
                    UPDATE model.asset
                       SET is_active = :is_active, updated_at = now()
                     WHERE (path = :path OR starts_with(path, :path || '/'))
                       AND is_active <> :is_active
                    """
                ),
                {"path": path, "is_active": is_active},
            )
            changed = result.rowcount or 0
            if changed:
                await self.rebind_all(connection=connection)
            return changed
```

Add the imports this needs:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from uns_model.tables import AssetTemplateNode
```

(`AssetTemplateNode` joins whatever `uns_model.tables` names the module already imports.)

- [ ] **Step 8: Run the integration tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "save_asset or set_active or sit_above or missing_parent"`
Expected: PASS

Run: `uv run pytest 09_uns_model/test -v`
Expected: PASS — nothing existing changes.

- [ ] **Step 9: Export the spec**

In `09_uns_model/src/uns_model/__init__.py`, add `AssetWriteSpec` to the `from uns_model.repositories import ...` line and to `__all__`, keeping both alphabetical.

- [ ] **Step 10: Commit**

```bash
git add 09_uns_model/src/uns_model/repositories.py 09_uns_model/src/uns_model/__init__.py 09_uns_model/test/test_asset_writes.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): save a single Asset with every authored column, and retire one by deactivating it"
```

---

### Task 4: `dependents_of` and a `delete_asset` that refuses to destroy OEE config

`model.asset` is the parent of four `ON DELETE CASCADE` FKs in the `oee` schema. Deleting an Asset therefore deletes its OEE Unit, its Shift Patterns, its Shift Exceptions and its Ideal Cycle Times without warning. Deletion stays available, but the caller has to ask for it knowing what goes.

**Files:**
- Modify: `09_uns_model/src/uns_model/repositories.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `rebind_all(connection=...)` from Task 1.
- Produces:
  - `AssetDependents(oee_units: int, shift_patterns: int, shift_exceptions: int, ideal_cycle_times: int, descendants: int, alert_rules: tuple[str, ...])` with `.total` and `.describe()`
  - `AssetModelRepository.dependents_of(self, path: str) -> AssetDependents`
  - `AssetModelRepository.delete_asset(self, path: str, *, force: bool = False) -> bool` — the existing signature gains `force`; deleting an Asset with dependents and `force=False` raises `ValueError`.

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_dependents_of_counts_the_subtree_and_the_oee_config(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    dependents = await repository.dependents_of(CELL_PATH)

    assert dependents.descendants >= 1  # the Mixer
    assert dependents.total >= 1


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deleting_an_asset_with_dependents_is_refused_without_force(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    with pytest.raises(ValueError, match="force"):
        await repository.delete_asset(CELL_PATH)

    assert await repository.get_asset(MIXER_PATH) is not None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_leaf_with_no_dependents_still_deletes_without_force(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    assert await repository.delete_asset(MIXER_PATH) is True
    assert await repository.get_asset(MIXER_PATH) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "dependents or delete"`
Expected: FAIL — `AttributeError: ... has no attribute 'dependents_of'`, and the refusal test fails because today's `delete_asset` deletes the subtree silently.

- [ ] **Step 3: Implement both**

In `09_uns_model/src/uns_model/repositories.py`, add the dataclass beside `AssetWriteSpec`:

```python
@dataclass(frozen=True, slots=True)
class AssetDependents:
    """What a delete would take with it. Descendants cascade; so does OEE config."""

    descendants: int = 0
    oee_units: int = 0
    shift_patterns: int = 0
    shift_exceptions: int = 0
    ideal_cycle_times: int = 0
    alert_rules: tuple[str, ...] = ()
    """Alert Rules whose topic sits under this Asset. Text, so nothing cascades — a
    delete leaves them pointing at a path that no longer exists."""

    @property
    def total(self) -> int:
        """How many rows a cascading delete would remove. Alert Rules are not among them."""
        return (
            self.descendants
            + self.oee_units
            + self.shift_patterns
            + self.shift_exceptions
            + self.ideal_cycle_times
        )

    def describe(self) -> str:
        """A one-line summary for an error message or a confirmation dialog."""
        parts = [
            f"{self.descendants} descendant Asset(s)",
            f"{self.oee_units} OEE Unit(s)",
            f"{self.shift_patterns} Shift Pattern(s)",
            f"{self.shift_exceptions} Shift Exception(s)",
            f"{self.ideal_cycle_times} Ideal Cycle Time(s)",
        ]
        if self.alert_rules:
            parts.append(f"{len(self.alert_rules)} Alert Rule(s) would be left dangling")
        return ", ".join(parts)
```

Add the counting SQL beside the other module-level statements:

```python
_DEPENDENTS_SQL = """
WITH subtree AS (
    SELECT id FROM model.asset
     WHERE path = :path OR starts_with(path, :path || '/')
)
SELECT (SELECT count(*) FROM subtree) - 1                                        AS descendants,
       (SELECT count(*) FROM oee.oee_unit         WHERE asset_id IN (SELECT id FROM subtree)) AS oee_units,
       (SELECT count(*) FROM oee.shift_pattern    WHERE asset_id IN (SELECT id FROM subtree)) AS shift_patterns,
       (SELECT count(*) FROM oee.shift_exception  WHERE asset_id IN (SELECT id FROM subtree)) AS shift_exceptions,
       (SELECT count(*) FROM oee.ideal_cycle_time WHERE asset_id IN (SELECT id FROM subtree)) AS ideal_cycle_times
"""

# console.alert_rules.topic is free text and may be an MQTT pattern, so nothing
# cascades and nothing can be rewritten reliably. Reporting the rules is all a
# delete or a rename can honestly do.
_DEPENDENT_ALERT_RULES_SQL = """
SELECT id FROM console.alert_rules
 WHERE topic = :path OR starts_with(topic, :path || '/')
 ORDER BY id
"""
```

Then the two methods:

```python
    async def dependents_of(self, path: str) -> AssetDependents:
        """Everything a cascading delete of this Asset would remove or orphan."""
        async with self._database.begin() as connection:
            row = (await connection.execute(text(_DEPENDENTS_SQL), {"path": path})).mappings().one()
            rules = (await connection.execute(text(_DEPENDENT_ALERT_RULES_SQL), {"path": path})).scalars().all()
        return AssetDependents(
            descendants=max(row["descendants"], 0),
            oee_units=row["oee_units"],
            shift_patterns=row["shift_patterns"],
            shift_exceptions=row["shift_exceptions"],
            ideal_cycle_times=row["ideal_cycle_times"],
            alert_rules=tuple(rules),
        )
```

Replace the body of the existing `delete_asset` so it guards first, keeping whatever it already does to remove the row and rebind:

```python
    async def delete_asset(self, path: str, *, force: bool = False) -> bool:
        """
        Remove an Asset and, by CASCADE, its subtree and its OEE configuration.

        Refuses when there is anything to cascade onto unless `force=True`: the FKs
        from `oee.oee_unit`, `oee.shift_pattern`, `oee.shift_exception` and
        `oee.ideal_cycle_time` are all ON DELETE CASCADE, so an unguarded delete
        throws away shift calendars nobody asked it to touch. Prefer `set_active`.
        """
        if not force:
            dependents = await self.dependents_of(path)
            if dependents.total:
                raise ValueError(
                    f"Deleting {path!r} would also remove {dependents.describe()}. "
                    "Pass force=True to proceed, or deactivate it instead."
                )
        async with self._database.session() as session:
            connection = await session.connection()
            result = await connection.execute(
                text("DELETE FROM model.asset WHERE path = :path"), {"path": path}
            )
            removed = bool(result.rowcount)
            if removed:
                await self.rebind_all(connection=connection)
            return removed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "dependents or delete"`
Expected: PASS

Run: `uv run pytest 09_uns_model/test -v`
Expected: PASS. If an existing test calls `delete_asset` on a branch root, it now needs `force=True` — that is the intended behaviour change; update the call and say so in the commit message.

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/repositories.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): refuse to delete an Asset that would take OEE config with it"
```

---

### Task 5: `rename_asset` and `move_asset`

`path` is denormalised, so renaming an Asset has to rewrite every descendant's path. The per-row CHECK `path = segment OR right(path, length(segment) + 1) = '/' || segment` constrains only the row it is on, which is exactly why nothing today stops a rename from leaving descendants behind — and why the two statements must run in this order.

**Files:**
- Modify: `09_uns_model/src/uns_model/repositories.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `rebind_all(connection=...)`, `dependents_of` (for the Alert Rule warning).
- Produces:
  - `RenameResult(path: str, assets_updated: int, alert_rules: tuple[str, ...])`
  - `AssetModelRepository.rename_asset(self, path: str, *, segment: str) -> RenameResult`
  - `AssetModelRepository.move_asset(self, path: str, *, new_parent_path: str) -> RenameResult`

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_renaming_an_asset_rewrites_every_descendant_path(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    result = await repository.rename_asset(CELL_PATH, segment="CellOne")

    assert result.path == f"{TEST_ROOT}/Plant1/Area1/Line1/CellOne"
    assert result.assets_updated == 2  # the Work Cell and the Mixer
    assert await repository.get_asset(MIXER_PATH) is None
    assert await repository.get_asset(f"{result.path}/Mixer1") is not None

    await repository.rename_asset(result.path, segment="Cell1")


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_renaming_onto_an_existing_sibling_is_refused(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.ensure_branch(
        _branch(
            (TEST_ROOT, "ENTERPRISE"),
            ("Plant1", "SITE"),
            ("Area1", "AREA"),
            ("Line1", "LINE"),
            ("Cell2", "WORK_CELL"),
        )
    )

    with pytest.raises(ValueError, match="already"):
        await repository.rename_asset(CELL_PATH, segment="Cell2")


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_moving_an_asset_reparents_its_whole_subtree(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.ensure_branch(
        _branch((TEST_ROOT, "ENTERPRISE"), ("Plant1", "SITE"), ("Area1", "AREA"), ("Line2", "LINE"))
    )

    result = await repository.move_asset(CELL_PATH, new_parent_path=f"{TEST_ROOT}/Plant1/Area1/Line2")

    assert result.path == f"{TEST_ROOT}/Plant1/Area1/Line2/Cell1"
    assert await repository.get_asset(f"{result.path}/Mixer1") is not None

    await repository.move_asset(result.path, new_parent_path=f"{TEST_ROOT}/Plant1/Area1/Line1")


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_moving_an_asset_under_itself_is_refused(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    with pytest.raises(ValueError, match="under itself"):
        await repository.move_asset(CELL_PATH, new_parent_path=MIXER_PATH)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "renaming or moving"`
Expected: FAIL — `AttributeError: ... has no attribute 'rename_asset'`

- [ ] **Step 3: Implement the shared prefix rewrite**

In `09_uns_model/src/uns_model/repositories.py`, add the result type and the statements:

```python
@dataclass(frozen=True, slots=True)
class RenameResult:
    """Where the Asset ended up, and what a caller should be told about."""

    path: str
    assets_updated: int
    alert_rules: tuple[str, ...] = ()
    """Alert Rules that still name the old path. They are free text, so nothing
    rewrote them; the console shows them as a warning."""


# Two statements, in this order. The row itself carries the per-row CHECK tying
# `path` to `segment`, so it must be updated as one write; descendants only need
# their prefix swapped, and `substr` keeps the part below the old prefix intact.
_RENAME_SELF_SQL = """
UPDATE model.asset
   SET segment = :new_segment, path = :new_path, updated_at = now()
 WHERE path = :old_path
"""

_REPREFIX_DESCENDANTS_SQL = """
UPDATE model.asset
   SET path = :new_path || substr(path, length(:old_path) + 1),
       updated_at = now()
 WHERE starts_with(path, :old_path || '/')
"""
```

Then the two methods:

```python
    async def rename_asset(self, path: str, *, segment: str) -> RenameResult:
        """
        Rename an Asset, rewriting its own path and every descendant's.

        `path` is denormalised on purpose (ADR-0003), so a rename is a subtree
        rewrite rather than one column. The CHECK on `asset` constrains each row
        alone and would not have caught a half-done rename, which is the whole
        reason this lives here rather than in a trigger.
        """
        if not segment or SEPARATOR in segment:
            raise ValueError(f"A segment must be one non-empty path segment, got {segment!r}")
        parent_path = path.rsplit(SEPARATOR, 1)[0] if SEPARATOR in path else None
        new_path = f"{parent_path}{SEPARATOR}{segment}" if parent_path else segment
        return await self._reprefix(path, new_path, segment)

    async def move_asset(self, path: str, *, new_parent_path: str) -> RenameResult:
        """
        Re-parent an Asset, keeping its own segment and taking its subtree with it.

        Refuses a move into its own subtree, which would detach that subtree from
        the root while leaving every FK intact — a cycle the `id <> parent_id`
        CHECK does not catch because it only sees one hop.
        """
        segment = path.rsplit(SEPARATOR, 1)[-1]
        if new_parent_path == path or new_parent_path.startswith(f"{path}{SEPARATOR}"):
            raise ValueError(f"Cannot move {path!r} under itself")

        ranks = await self.level_ranks()
        async with self._database.session() as session:
            moving = (await session.execute(select(Asset).where(Asset.path == path))).scalar_one_or_none()
            if moving is None:
                raise ValueError(f"No Asset at {path!r}")
            parent = (
                await session.execute(select(Asset).where(Asset.path == new_parent_path))
            ).scalar_one_or_none()
            if parent is None:
                raise ValueError(f"No Asset at {new_parent_path!r} to move {path!r} under")
            if ranks[moving.level] <= ranks[parent.level]:
                raise ValueError(
                    f"Asset Level {moving.level!r} cannot sit under {parent.level!r}: "
                    "a branch may skip levels but not invert them"
                )
            parent_id = parent.id

        result = await self._reprefix(path, f"{new_parent_path}{SEPARATOR}{segment}", segment)
        async with self._database.session() as session:
            await session.execute(
                update(Asset).where(Asset.path == result.path).values(parent_id=parent_id)
            )
        return result

    async def _reprefix(self, old_path: str, new_path: str, new_segment: str) -> RenameResult:
        """The path rewrite both a rename and a move need, in one transaction."""
        if old_path == new_path:
            return RenameResult(path=new_path, assets_updated=0)
        rules = (await self.dependents_of(old_path)).alert_rules
        async with self._database.session() as session:
            connection = await session.connection()
            try:
                own = await connection.execute(
                    text(_RENAME_SELF_SQL),
                    {"old_path": old_path, "new_path": new_path, "new_segment": new_segment},
                )
                if not own.rowcount:
                    raise ValueError(f"No Asset at {old_path!r}")
                descendants = await connection.execute(
                    text(_REPREFIX_DESCENDANTS_SQL), {"old_path": old_path, "new_path": new_path}
                )
            except IntegrityError as error:
                # uq_asset_path / uq_asset_sibling_segment: a generated constraint name
                # is no use to an engineer looking at a form.
                raise ValueError(f"An Asset already exists at {new_path!r}") from error
            updated = (own.rowcount or 0) + (descendants.rowcount or 0)
            await self.rebind_all(connection=connection)
        return RenameResult(path=new_path, assets_updated=updated, alert_rules=rules)
```

Add the imports this needs:

```python
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "renaming or moving"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/repositories.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): rename and move an Asset, rewriting every descendant path"
```

---

### Task 6: `expand_pattern` and `duplicate_subtree`

The user's actual ask — "easily duplicate them". A one-off copy of an existing subtree, N times, with names generated from a pattern. Distinct from templates: a duplicate is independent from the moment it exists.

**Files:**
- Create: `09_uns_model/src/uns_model/naming.py`
- Modify: `09_uns_model/src/uns_model/repositories.py`
- Modify: `09_uns_model/src/uns_model/__init__.py`
- Test: `09_uns_model/test/test_naming.py` (create)
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `rebind_all(connection=...)`, `level_ranks()`.
- Produces:
  - `expand_pattern(pattern: str, count: int, *, start: int = 1) -> list[str]`
  - `AssetModelRepository.duplicate_subtree(self, source_path: str, *, target_parent_path: str, segments: Sequence[str]) -> list[Asset]`

- [ ] **Step 1: Write the failing unit test**

Create `09_uns_model/test/test_naming.py`:

```python
"""
Unit tests for generated Asset names. Pure string work, kept out of the repository
so the console and the seed can agree on what `Line{n}` means without a database.
"""

from __future__ import annotations

import pytest

from uns_model.naming import expand_pattern


def test_a_bare_placeholder_counts_from_one():
    assert expand_pattern("Line{n}", 3) == ["Line1", "Line2", "Line3"]


def test_a_zero_padded_placeholder_keeps_its_width():
    assert expand_pattern("Cell{n:02d}", 3) == ["Cell01", "Cell02", "Cell03"]


def test_a_placeholder_may_sit_anywhere_in_the_name():
    assert expand_pattern("Mixer{n}Tank", 2) == ["Mixer1Tank", "Mixer2Tank"]


def test_counting_may_start_anywhere():
    assert expand_pattern("Line{n}", 2, start=7) == ["Line7", "Line8"]


def test_a_pattern_without_a_placeholder_is_rejected():
    # Silently producing three Assets with the same name would collide on
    # uq_asset_sibling_segment anyway; saying so up front is more useful.
    with pytest.raises(ValueError, match=r"\{n\}"):
        expand_pattern("Line", 3)


def test_a_pattern_with_no_placeholder_is_allowed_for_a_single_copy():
    assert expand_pattern("Line9", 1) == ["Line9"]


def test_a_count_below_one_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        expand_pattern("Line{n}", 0)


def test_a_pattern_that_would_contain_a_separator_is_rejected():
    with pytest.raises(ValueError, match="segment"):
        expand_pattern("Line/{n}", 2)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_model.naming'`

- [ ] **Step 3: Write `naming.py`**

Create `09_uns_model/src/uns_model/naming.py`:

```python
"""
Generated Asset names.

Duplicating a subtree forty times means generating forty segments, and the console
and the repository have to agree on what `Cell{n:02d}` expands to. Keeping it here
— pure, no database — is what lets both sides be tested without one.
"""

from __future__ import annotations

import re

from uns_model.topic_path import SEPARATOR

_PLACEHOLDER = re.compile(r"\{n(?::0(\d+)d)?\}")
"""`{n}` or `{n:0Nd}`. Deliberately narrow: this is a naming convention, not a
format-string evaluator, and accepting arbitrary format specs would let a pattern
produce a segment containing a separator."""


def expand_pattern(pattern: str, count: int, *, start: int = 1) -> list[str]:
    """
    Expand a naming pattern into `count` Asset segments.

    `Line{n}` gives Line1, Line2, …; `Cell{n:02d}` gives Cell01, Cell02, …. A
    pattern with no placeholder is only legal for a single copy, because forty
    Assets called `Line` would collide on `uq_asset_sibling_segment` and the error
    would name a constraint rather than the mistake.
    """
    if count < 1:
        raise ValueError("A duplicate count must be at least 1")
    if SEPARATOR in pattern:
        raise ValueError(f"A naming pattern must be one path segment, got {pattern!r}")

    match = _PLACEHOLDER.search(pattern)
    if match is None:
        if count == 1:
            return [pattern]
        raise ValueError(f"Pattern {pattern!r} needs a {{n}} placeholder to produce {count} names")

    width = int(match.group(1)) if match.group(1) else 0
    return [
        pattern[: match.start()] + str(number).rjust(width, "0") + pattern[match.end() :]
        for number in range(start, start + count)
    ]


__all__ = ["expand_pattern"]
```

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `uv run pytest 09_uns_model/test/test_naming.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Write the failing integration test for `duplicate_subtree`**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_duplicating_a_subtree_copies_its_descendants_and_metrics(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.define_metric(
        f"{TEST_METRIC_PREFIX}Temperature/value", asset_path=MIXER_PATH, unit_of_measure="°C"
    )

    copies = await repository.duplicate_subtree(
        CELL_PATH,
        target_parent_path=f"{TEST_ROOT}/Plant1/Area1/Line1",
        segments=expand_pattern("Cell{n}", 2, start=8),
    )

    assert [asset.path for asset in copies] == [
        f"{TEST_ROOT}/Plant1/Area1/Line1/Cell8",
        f"{TEST_ROOT}/Plant1/Area1/Line1/Cell9",
    ]
    copied_mixer = await repository.get_asset(f"{TEST_ROOT}/Plant1/Area1/Line1/Cell8/Mixer1")
    assert copied_mixer is not None
    assert copied_mixer.display_name == "Mixer Tank 1"
    keys = {metric.metric_key for metric in await repository.metric_definitions_for(copied_mixer.id)}
    assert f"{TEST_METRIC_PREFIX}Temperature/value" in keys


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_duplicate_is_not_linked_to_the_asset_it_came_from(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    copies = await repository.duplicate_subtree(
        CELL_PATH, target_parent_path=f"{TEST_ROOT}/Plant1/Area1/Line1", segments=["Cell7"]
    )

    # A duplicate is a one-off copy: no template link, so editing the original later
    # does nothing to it. That is the difference from `instantiate`.
    assert copies[0].template_id is None
    assert copies[0].template_node_id is None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_duplicating_onto_an_existing_name_is_refused(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    with pytest.raises(ValueError, match="Cell1"):
        await repository.duplicate_subtree(
            CELL_PATH, target_parent_path=f"{TEST_ROOT}/Plant1/Area1/Line1", segments=["Cell1"]
        )


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_batch_with_one_taken_name_writes_none_of_the_others(
    repository: AssetModelRepository,
):
    """A partial batch leaves the engineer to work out which of five landed."""
    await repository.ensure_branch(MIXER_BRANCH)
    line_path = f"{TEST_ROOT}/Plant1/Area1/Line1"

    with pytest.raises(ValueError, match="Cell1"):
        await repository.duplicate_subtree(
            CELL_PATH, target_parent_path=line_path, segments=["CellX", "Cell1", "CellY"]
        )

    assert await repository.get_asset(f"{line_path}/CellX") is None
    assert await repository.get_asset(f"{line_path}/CellY") is None
```

The template-link carry from spec section 9 is asserted in Task 10, once there is a template to instantiate.

Add `from uns_model.naming import expand_pattern` to that file's imports.

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k duplicat`
Expected: FAIL — `AttributeError: ... has no attribute 'duplicate_subtree'`

- [ ] **Step 7: Implement `duplicate_subtree`**

In `09_uns_model/src/uns_model/repositories.py`, add to `AssetModelRepository`:

```python
    async def duplicate_subtree(
        self,
        source_path: str,
        *,
        target_parent_path: str,
        segments: Sequence[str],
    ) -> list[Asset]:
        """
        Copy an Asset and everything under it, once per name in `segments`.

        The copy inherits whatever template link the source had: duplicating a Line
        that came from an Asset Template yields **another instance of that template**,
        not a detached orphan, so a later template edit reaches it. Duplicating a
        hand-built subtree yields a hand-built subtree. `overridden_fields` is *not*
        carried — a fresh copy has overridden nothing yet.

        Metric Definitions come along, because a Work Cell without its tags is not a
        useful copy. Topic Bindings do not: they are derived, and the rebind at the
        end of the transaction resolves them.
        """
        if not segments:
            raise ValueError("Duplicating needs at least one target segment")
        if len(set(segments)) != len(segments):
            raise ValueError(f"Duplicate target segments are not unique: {list(segments)}")

        ranks = await self.level_ranks()
        async with self._database.session() as session:
            source = (await session.execute(select(Asset).where(Asset.path == source_path))).scalar_one_or_none()
            if source is None:
                raise ValueError(f"No Asset at {source_path!r} to duplicate")
            target_parent = (
                await session.execute(select(Asset).where(Asset.path == target_parent_path))
            ).scalar_one_or_none()
            if target_parent is None:
                raise ValueError(f"No Asset at {target_parent_path!r} to duplicate into")
            if ranks[source.level] <= ranks[target_parent.level]:
                raise ValueError(
                    f"Asset Level {source.level!r} cannot sit under {target_parent.level!r}: "
                    "a branch may skip levels but not invert them"
                )

            # Every name is checked before any row is written. Five copies where the
            # third name is taken must create nothing and must say *which* name — a
            # constraint violation with a generated name in it is not a name the
            # engineer can fix.
            taken = set(
                (
                    await session.execute(
                        select(Asset.segment).where(Asset.parent_id == target_parent.id)
                    )
                )
                .scalars()
                .all()
            )
            collisions = [segment for segment in segments if segment in taken]
            if collisions:
                raise ValueError(
                    f"An Asset already exists under {target_parent_path!r} named "
                    f"{collisions[0]!r}; nothing was duplicated"
                )

            subtree = (
                (
                    await session.execute(
                        select(Asset)
                        .where(or_(Asset.path == source_path, Asset.path.op("^@")(f"{source_path}/")))
                        .order_by(Asset.path)
                    )
                )
                .scalars()
                .all()
            )
            metrics_by_asset: dict[int, list[MetricDefinition]] = {}
            for metric in (
                (
                    await session.execute(
                        select(MetricDefinition).where(
                            MetricDefinition.asset_id.in_([asset.id for asset in subtree])
                        )
                    )
                )
                .scalars()
                .all()
            ):
                metrics_by_asset.setdefault(metric.asset_id, []).append(metric)

            created: list[Asset] = []
            try:
                for segment in segments:
                    new_root_path = f"{target_parent_path}{SEPARATOR}{segment}"
                    by_new_path: dict[str, Asset] = {}
                    for original in subtree:
                        suffix = original.path[len(source_path) :]
                        new_path = f"{new_root_path}{suffix}"
                        new_segment = new_path.rsplit(SEPARATOR, 1)[-1]
                        parent_path = new_path.rsplit(SEPARATOR, 1)[0]
                        copy = Asset(
                            parent_id=(
                                target_parent.id
                                if original.path == source_path
                                else by_new_path[parent_path].id
                            ),
                            segment=new_segment,
                            path=new_path,
                            level=original.level,
                            display_name=original.display_name,
                            description=original.description,
                            manufacturer=original.manufacturer,
                            model_number=original.model_number,
                            serial_number=original.serial_number,
                            criticality=original.criticality,
                            commissioned_on=original.commissioned_on,
                            attributes=dict(original.attributes or {}),
                            is_active=original.is_active,
                            # `template_id` marks an instance *root*, so it only
                            # belongs on the copy of the source itself.
                            template_id=(original.template_id if original.path == source_path else None),
                            template_node_id=original.template_node_id,
                            # Deliberately not `original.overridden_fields`.
                            overridden_fields=[],
                        )
                        session.add(copy)
                        await session.flush()
                        by_new_path[new_path] = copy
                        for metric in metrics_by_asset.get(original.id, ()):
                            session.add(
                                MetricDefinition(
                                    asset_id=copy.id,
                                    metric_key=metric.metric_key,
                                    display_name=metric.display_name,
                                    unit_of_measure=metric.unit_of_measure,
                                    decimals=metric.decimals,
                                    min_value=metric.min_value,
                                    max_value=metric.max_value,
                                    deadband=metric.deadband,
                                    description=metric.description,
                                    template_metric_id=metric.template_metric_id,
                                    # The copy has not been edited, whatever the source's
                                    # state — so the template still owns this row.
                                    is_overridden=False,
                                )
                            )
                    created.append(by_new_path[new_root_path])
                await session.flush()
            except IntegrityError as error:
                # The pre-check above catches the common case with a usable message.
                # This is the concurrent-writer case, and still writes nothing.
                raise ValueError(
                    f"An Asset already exists under {target_parent_path!r} with one of "
                    f"{list(segments)}"
                ) from error

            connection = await session.connection()
            await self.rebind_all(connection=connection)
            return created
```

Add whatever is missing from the imports:

```python
from collections.abc import Sequence
from sqlalchemy import or_
```

Note on `Asset.path.op("^@")(...)`: `^@` is Postgres's operator form of `starts_with`, which keeps the ORM query consistent with the raw SQL elsewhere and avoids `LIKE`'s underscore trap.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k duplicat`
Expected: PASS

- [ ] **Step 9: Export `expand_pattern`**

Add `from uns_model.naming import expand_pattern` to `09_uns_model/src/uns_model/__init__.py` and `"expand_pattern"` to `__all__`.

- [ ] **Step 10: Commit**

```bash
git add 09_uns_model/src/uns_model/naming.py 09_uns_model/src/uns_model/repositories.py 09_uns_model/src/uns_model/__init__.py 09_uns_model/test/test_naming.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): duplicate an Asset subtree N times from a naming pattern"
```

---

### Task 7: `delete_metric`, and Unmodelled Topics an engineer can adopt

The Tag screen needs to remove a Metric Definition, and it needs the list of topics that arrived but match no Asset — scoped to a subtree, because a central cloud instance serves many plants and the whole list is useless.

**Files:**
- Modify: `09_uns_model/src/uns_model/repositories.py` (`define_metric`, `unmodelled_topics`)
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `announce_asset_model_changed(connection=...)` from Task 1.
- Produces:
  - `AssetModelRepository.delete_metric(self, metric_key: str, *, asset_path: str | None = None) -> bool`
  - `AssetModelRepository.unmodelled_topics(self, *, limit: int = 100, under: str | None = None) -> list[str]` — the existing method gains `under` and keeps `limit`'s current default.
  - `AssetModelRepository.metrics_for_path(self, asset_path: str | None) -> list[MetricDefinition]`
  - `define_metric(..., is_overridden: bool = False)` — the console passes `True`, so propagation leaves the row alone.

The existing `metric_definitions_for` takes an **`asset_id`** and returns every definition that *could* apply to an Asset, plant-wide rows included, ordered so the last match wins — the shape Enrichment needs. A tag table needs the opposite: the rows actually authored *at* one path, addressed the way every other write in this plan is addressed. Hence a second method rather than a changed one.

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deleting_a_metric_definition_removes_only_that_one(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.define_metric(f"{TEST_METRIC_PREFIX}Doomed/value", asset_path=MIXER_PATH)
    await repository.define_metric(f"{TEST_METRIC_PREFIX}Kept/value", asset_path=MIXER_PATH)

    assert await repository.delete_metric(f"{TEST_METRIC_PREFIX}Doomed/value", asset_path=MIXER_PATH) is True

    keys = {metric.metric_key for metric in await repository.metrics_for_path(MIXER_PATH)}
    assert f"{TEST_METRIC_PREFIX}Doomed/value" not in keys
    assert f"{TEST_METRIC_PREFIX}Kept/value" in keys


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deleting_a_metric_definition_that_is_not_there_reports_it(repository: AssetModelRepository):
    assert await repository.delete_metric(f"{TEST_METRIC_PREFIX}Absent/value", asset_path=MIXER_PATH) is False


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_metric_the_console_edits_is_marked_overridden(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)

    await repository.define_metric(
        f"{TEST_METRIC_PREFIX}Edited/value", asset_path=MIXER_PATH, unit_of_measure="bar", is_overridden=True
    )

    edited = next(
        metric
        for metric in await repository.metrics_for_path(MIXER_PATH)
        if metric.metric_key == f"{TEST_METRIC_PREFIX}Edited/value"
    )
    assert edited.is_overridden is True


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_unmodelled_topics_can_be_scoped_to_one_plant(
    repository: AssetModelRepository, database: Database
):
    await repository.bind_topic(f"{TEST_ROOT}/PlantX/Stray/Temperature")
    await repository.bind_topic(f"{TEST_ROOT}/PlantY/Stray/Temperature")

    scoped = await repository.unmodelled_topics(under=f"{TEST_ROOT}/PlantX")

    assert f"{TEST_ROOT}/PlantX/Stray/Temperature" in scoped
    assert f"{TEST_ROOT}/PlantY/Stray/Temperature" not in scoped
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "metric_definition or overridden or unmodelled_topics_can"`
Expected: FAIL — `AttributeError: ... has no attribute 'delete_metric'`, and `unmodelled_topics() got an unexpected keyword argument 'under'`.

- [ ] **Step 3: Implement all three changes**

In `09_uns_model/src/uns_model/repositories.py`:

Add `is_overridden` to `define_metric`'s signature (after `deadband`) and to both the `values(...)` and the `on_conflict_do_update(set_={...})` of its upsert:

```python
        is_overridden: bool = False,
```

```python
            "is_overridden": is_overridden,
```

with this line in its docstring:

```
        `is_overridden=True` marks the row as an Instance Override: template
        propagation will not touch it again until it is reverted (rule 3).
```

Add `delete_metric`:

```python
    async def delete_metric(self, metric_key: str, *, asset_path: str | None = None) -> bool:
        """
        Remove one Metric Definition, returning whether there was one to remove.

        `asset_path=None` addresses the Asset-independent default — the single row
        that gives every mixer's Temperature its `°C`. No rebind: Metric Definitions
        are read through `topic_binding`, they do not change it.
        """
        async with self._database.session() as session:
            statement = delete(MetricDefinition).where(MetricDefinition.metric_key == metric_key)
            if asset_path is None:
                statement = statement.where(MetricDefinition.asset_id.is_(None))
            else:
                asset_id = (
                    await session.execute(select(Asset.id).where(Asset.path == asset_path))
                ).scalar_one_or_none()
                if asset_id is None:
                    return False
                statement = statement.where(MetricDefinition.asset_id == asset_id)
            removed = bool((await session.execute(statement)).rowcount)
            if removed:
                connection = await session.connection()
                await announce_asset_model_changed(self._database, connection=connection)
            return removed
```

Add `metrics_for_path` beside it:

```python
    async def metrics_for_path(self, asset_path: str | None) -> list[MetricDefinition]:
        """
        The Metric Definitions authored *at* one Asset — the Tag list for a machine.

        Distinct from `metric_definitions_for`, which takes an `asset_id` and answers
        the Enrichment question "everything that could apply here, plant-wide rows
        included". This answers the editing question: which rows does this Asset own,
        so that deleting one from the table deletes the row the engineer pointed at.

        `asset_path=None` returns the Asset-independent defaults.
        """
        async with self._database.session() as session:
            asset_id = None
            if asset_path is not None:
                asset_id = (
                    await session.execute(select(Asset.id).where(Asset.path == asset_path))
                ).scalar_one_or_none()
                if asset_id is None:
                    return []
            statement = (
                select(MetricDefinition)
                .where(
                    MetricDefinition.asset_id.is_(None)
                    if asset_id is None
                    else MetricDefinition.asset_id == asset_id
                )
                .order_by(MetricDefinition.metric_key)
            )
            return list((await session.execute(statement)).scalars().all())
```

Add `under` to `unmodelled_topics`, keeping its existing body and adding the filter:

```python
    async def unmodelled_topics(self, *, limit: int = 100, under: str | None = None) -> list[str]:
        """
        Topics that arrived but match no Asset — the candidates for adoption.

        `under` scopes the answer to one subtree. A central cloud instance carries
        every plant's traffic, so an unscoped list is long enough to be useless on
        a screen that asks "what is missing from *this* plant?".
        """
```

and in the SQL, add the clause only when `under` is given, so the unscoped query is untouched:

```python
        clauses = ["asset_id IS NULL"]
        parameters: dict[str, Any] = {"limit": limit}
        if under is not None:
            clauses.append("starts_with(topic, :under || '/')")
            parameters["under"] = under
        statement = text(
            f"SELECT topic FROM model.topic_binding WHERE {' AND '.join(clauses)} "
            "ORDER BY first_seen_at DESC LIMIT :limit"
        )
```

Add `delete` to the `sqlalchemy` import list.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "metric_definition or overridden or unmodelled"`
Expected: PASS — including the pre-existing unscoped `unmodelled_topics` test.

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/repositories.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): delete a Metric Definition, mark one overridden, and scope Unmodelled Topics to a subtree"
```

---

### Task 8: The Asset Template specs, and the validation that keeps a template well-formed

Every spec in this codebase validates itself before Postgres does (`AlertRuleSpec`, `OeeUnitSpec`), so a caller gets a sentence instead of a constraint name. A template has more invariants than most: a single root, every parent present, and `segment` agreeing with `relative_path`.

**Files:**
- Create: `09_uns_model/src/uns_model/asset_templates.py`
- Test: `09_uns_model/test/test_asset_templates.py`

**Interfaces:**
- Consumes: `SEPARATOR` from `uns_model.topic_path`.
- Produces:
  - `TemplateMetricSpec(metric_key, display_name=None, unit_of_measure=None, decimals=None, min_value=None, max_value=None, deadband=None, description=None)` with `.validate()`
  - `TemplateNodeSpec(relative_path, segment, level, display_name=None, description=None, attributes={}, metrics=())` with `.parent_relative_path`, `.depth`, `.validate()`
  - `AssetTemplateSpec(name, root_level, description=None, nodes=(), id=None)` with `.root`, `.ordered()`, `.validate()`
  - `TemplateProjection(assets_created=0, assets_updated=0, assets_deactivated=0, metrics_written=0, metrics_deleted=0, overrides_skipped=())`
  - `InstanceDrift(asset_path, overridden_fields=(), missing_nodes=(), extra_nodes=(), overridden_metrics=())`

- [ ] **Step 1: Write the failing unit tests**

Append to `09_uns_model/test/test_asset_templates.py`:

```python
import pytest

from uns_model.asset_templates import (
    AssetTemplateSpec,
    TemplateMetricSpec,
    TemplateNodeSpec,
    TemplateProjection,
)


def _line_template(nodes: list[TemplateNodeSpec] | None = None) -> AssetTemplateSpec:
    """A two-node template: a LINE root with one WORK_CELL under it."""
    return AssetTemplateSpec(
        name="Polyol Line",
        root_level="LINE",
        nodes=nodes
        if nodes is not None
        else [
            TemplateNodeSpec(relative_path="", segment="Line", level="LINE"),
            TemplateNodeSpec(
                relative_path="Cell1",
                segment="Cell1",
                level="WORK_CELL",
                metrics=[TemplateMetricSpec(metric_key="ProcessValue/Temperature/value", unit_of_measure="°C")],
            ),
        ],
    )


def test_a_well_formed_template_validates():
    _line_template().validate()  # does not raise


def test_the_root_node_is_the_one_with_an_empty_relative_path():
    assert _line_template().root.level == "LINE"


def test_nodes_come_back_shallowest_first():
    spec = _line_template(
        [
            TemplateNodeSpec(relative_path="Cell1/Mixer", segment="Mixer", level="MACHINE"),
            TemplateNodeSpec(relative_path="", segment="Line", level="LINE"),
            TemplateNodeSpec(relative_path="Cell1", segment="Cell1", level="WORK_CELL"),
        ]
    )

    # Creating an Asset needs its parent to exist already, so order is not cosmetic.
    assert [node.relative_path for node in spec.ordered()] == ["", "Cell1", "Cell1/Mixer"]


def test_a_template_without_a_root_node_is_rejected():
    with pytest.raises(ValueError, match="exactly one root"):
        _line_template([TemplateNodeSpec(relative_path="Cell1", segment="Cell1", level="WORK_CELL")]).validate()


def test_a_template_with_two_root_nodes_is_rejected():
    with pytest.raises(ValueError, match="exactly one root"):
        _line_template(
            [
                TemplateNodeSpec(relative_path="", segment="Line", level="LINE"),
                TemplateNodeSpec(relative_path="", segment="Other", level="LINE"),
            ]
        ).validate()


def test_a_root_node_whose_level_disagrees_with_the_template_is_rejected():
    with pytest.raises(ValueError, match="root_level"):
        _line_template(
            [TemplateNodeSpec(relative_path="", segment="Line", level="AREA")]
        ).validate()


def test_an_orphan_node_is_rejected():
    with pytest.raises(ValueError, match="no parent"):
        _line_template(
            [
                TemplateNodeSpec(relative_path="", segment="Line", level="LINE"),
                TemplateNodeSpec(relative_path="Cell1/Mixer", segment="Mixer", level="MACHINE"),
            ]
        ).validate()


def test_a_segment_that_disagrees_with_its_relative_path_is_rejected():
    with pytest.raises(ValueError, match="last segment"):
        _line_template(
            [
                TemplateNodeSpec(relative_path="", segment="Line", level="LINE"),
                TemplateNodeSpec(relative_path="Cell1", segment="CellOne", level="WORK_CELL"),
            ]
        ).validate()


def test_two_nodes_at_the_same_relative_path_are_rejected():
    with pytest.raises(ValueError, match="more than once"):
        _line_template(
            [
                TemplateNodeSpec(relative_path="", segment="Line", level="LINE"),
                TemplateNodeSpec(relative_path="Cell1", segment="Cell1", level="WORK_CELL"),
                TemplateNodeSpec(relative_path="Cell1", segment="Cell1", level="WORK_CELL"),
            ]
        ).validate()


def test_a_blank_template_name_is_rejected():
    with pytest.raises(ValueError, match="name is required"):
        AssetTemplateSpec(name="  ", root_level="LINE", nodes=[]).validate()


def test_a_metric_range_the_wrong_way_round_is_rejected():
    with pytest.raises(ValueError, match="min_value"):
        TemplateMetricSpec(metric_key="a/value", min_value=10.0, max_value=1.0).validate()


def test_a_blank_metric_key_is_rejected():
    with pytest.raises(ValueError, match="Metric Key"):
        TemplateMetricSpec(metric_key="").validate()


def test_a_projection_starts_empty():
    projection = TemplateProjection()

    assert projection.assets_created == 0
    assert projection.overrides_skipped == ()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest 09_uns_model/test/test_asset_templates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_model.asset_templates'`

- [ ] **Step 3: Write the specs**

Create `09_uns_model/src/uns_model/asset_templates.py`:

```python
"""
Asset Templates: a reusable Asset shape, instantiated many times, kept in step.

ISA-95's Equipment Class made concrete. A template describes a subtree *relative*
to wherever it is placed, which is why nothing here holds a path — placing it is
`instantiate`'s job, and the same template serves every plant.

Editing a template projects onto its instances immediately. An **Instance
Override** — a field an engineer edited locally — is never overwritten, because a
propagation that silently discarded local work would make templates too dangerous
to use (rule 3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from uns_model.topic_path import SEPARATOR


@dataclass(frozen=True, slots=True)
class TemplateMetricSpec:
    """A Metric Definition a template projects onto every instance of one node."""

    metric_key: str
    display_name: str | None = None
    unit_of_measure: str | None = None
    decimals: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    deadband: float | None = None
    description: str | None = None

    def validate(self) -> None:
        if not self.metric_key.strip():
            raise ValueError("A Metric Key is required")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError(
                f"Metric {self.metric_key!r}: min_value {self.min_value} is above max_value {self.max_value}"
            )


@dataclass(frozen=True, slots=True)
class TemplateNodeSpec:
    """
    One Asset in a template's subtree.

    `relative_path` is the path below the instance root — '' for the root node
    itself. `segment` is its last path segment, kept as a column because the root
    node has no `relative_path` to derive it from.
    """

    relative_path: str
    segment: str
    level: str
    display_name: str | None = None
    description: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    metrics: Sequence[TemplateMetricSpec] = ()

    @property
    def is_root(self) -> bool:
        return self.relative_path == ""

    @property
    def parent_relative_path(self) -> str | None:
        """The parent's `relative_path`, or None for the root node."""
        if self.is_root:
            return None
        if SEPARATOR not in self.relative_path:
            return ""
        return self.relative_path.rsplit(SEPARATOR, 1)[0]

    @property
    def depth(self) -> int:
        """How far below the instance root this node sits. The root is 0."""
        return 0 if self.is_root else self.relative_path.count(SEPARATOR) + 1

    def validate(self) -> None:
        if not self.segment or SEPARATOR in self.segment:
            raise ValueError(f"A Template Node segment must be one path segment, got {self.segment!r}")
        if not self.level:
            raise ValueError(f"Template Node {self.relative_path!r} needs an Asset Level")
        if not self.is_root and self.relative_path.rsplit(SEPARATOR, 1)[-1] != self.segment:
            raise ValueError(
                f"Template Node {self.relative_path!r} must have {self.segment!r} as its last segment"
            )
        if any(not part for part in self.relative_path.split(SEPARATOR)) and not self.is_root:
            raise ValueError(f"Template Node path {self.relative_path!r} has an empty segment")
        for metric in self.metrics:
            metric.validate()


@dataclass(frozen=True, slots=True)
class AssetTemplateSpec:
    """A whole template as the console saves it: the header plus every node."""

    name: str
    root_level: str
    description: str | None = None
    nodes: Sequence[TemplateNodeSpec] = ()
    id: int | None = None
    """None for a new template; set when updating an existing one."""

    @property
    def root(self) -> TemplateNodeSpec:
        """The node the instance root is made from."""
        return next(node for node in self.nodes if node.is_root)

    def ordered(self) -> list[TemplateNodeSpec]:
        """Shallowest first, so a node's parent always exists before it is written."""
        return sorted(self.nodes, key=lambda node: (node.depth, node.relative_path))

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("An Asset Template name is required")
        if not self.root_level:
            raise ValueError("An Asset Template needs a root_level")

        roots = [node for node in self.nodes if node.is_root]
        if len(roots) != 1:
            raise ValueError(f"An Asset Template needs exactly one root node, found {len(roots)}")
        if roots[0].level != self.root_level:
            raise ValueError(
                f"The root node's level {roots[0].level!r} disagrees with root_level {self.root_level!r}"
            )

        seen: set[str] = set()
        for node in self.nodes:
            node.validate()
            if node.relative_path in seen:
                raise ValueError(f"Template Node {node.relative_path!r} appears more than once")
            seen.add(node.relative_path)
        for node in self.nodes:
            parent = node.parent_relative_path
            if parent is not None and parent not in seen:
                raise ValueError(f"Template Node {node.relative_path!r} has no parent node {parent!r}")


@dataclass(frozen=True, slots=True)
class TemplateProjection:
    """
    What a propagation actually did — reported, never guessed at.

    `overrides_skipped` is the honest part: (asset_path, field) for every field a
    template edit did not apply because an engineer owns it.
    """

    assets_created: int = 0
    assets_updated: int = 0
    assets_deactivated: int = 0
    metrics_written: int = 0
    metrics_deleted: int = 0
    overrides_skipped: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class InstanceDrift:
    """How far one instance has diverged from the template that made it."""

    asset_path: str
    overridden_fields: tuple[str, ...] = ()
    missing_nodes: tuple[str, ...] = ()
    """Template Nodes with no Asset — a node added after this instance was deactivated."""
    extra_nodes: tuple[str, ...] = ()
    """Assets under the instance root that no Template Node accounts for."""
    overridden_metrics: tuple[str, ...] = ()

    @property
    def has_drifted(self) -> bool:
        return bool(self.overridden_fields or self.missing_nodes or self.extra_nodes or self.overridden_metrics)


__all__ = [
    "AssetTemplateSpec",
    "InstanceDrift",
    "TemplateMetricSpec",
    "TemplateNodeSpec",
    "TemplateProjection",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_asset_templates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/asset_templates.py 09_uns_model/test/test_asset_templates.py
git commit -m "feat(model): add Asset Template specs that validate their own tree shape"
```

---

### Task 9: `AssetTemplateRepository` — save, list, get, delete

A separate repository, for the same reason `AlertRuleRepository` is separate: a different seam, a different set of tables, and unit tests that can fake one without the other. Saving replaces the node set wholesale — a template *is* its nodes, and merging by hand is where a half-applied save would come from.

**Files:**
- Create: `09_uns_model/src/uns_model/template_repository.py`
- Modify: `09_uns_model/src/uns_model/__init__.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `AssetTemplateSpec`, `TemplateNodeSpec`, `TemplateMetricSpec`, `TemplateProjection` from Task 8; `AssetTemplate`, `AssetTemplateNode`, `AssetTemplateMetric` from Task 2; `Database` from `uns_model.engine`.
- Produces:
  - `AssetTemplateRepository(database: Database)`
  - `async def save_template(self, spec: AssetTemplateSpec, *, expected_updated_at: datetime | None = None) -> TemplateProjection`
  - `async def list_templates(self) -> list[AssetTemplate]`
  - `async def get_template(self, template_id: int) -> AssetTemplate | None` — nodes and metrics eagerly loaded
  - `async def delete_template(self, template_id: int) -> bool`

Note: `save_template` returns a `TemplateProjection` because Task 11 makes it propagate; until then the projection counts are zero for everything but the template's own rows.

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
LINE_TEMPLATE = AssetTemplateSpec(
    name="PyTest Polyol Line",
    root_level="LINE",
    description="Two cells, one mixer each",
    nodes=[
        TemplateNodeSpec(relative_path="", segment="Line", level="LINE", display_name="Polyol Line"),
        TemplateNodeSpec(relative_path="Cell1", segment="Cell1", level="WORK_CELL"),
        TemplateNodeSpec(
            relative_path="Cell1/Mixer",
            segment="Mixer",
            level="MACHINE",
            display_name="Mixer Tank",
            metrics=[
                TemplateMetricSpec(
                    metric_key=f"{TEST_METRIC_PREFIX}Temperature/value", unit_of_measure="°C", decimals=1
                )
            ],
        ),
    ],
)


@pytest_asyncio.fixture(loop_scope="session")
async def templates(database: Database):
    repository = AssetTemplateRepository(database)
    yield repository
    for template in await repository.list_templates():
        if template.name.startswith("PyTest "):
            await repository.delete_template(template.id)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_saving_a_template_stores_its_nodes_and_metrics(templates: AssetTemplateRepository):
    await templates.save_template(LINE_TEMPLATE)

    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    loaded = await templates.get_template(stored.id)
    assert {node.relative_path for node in loaded.nodes} == {"", "Cell1", "Cell1/Mixer"}
    mixer = next(node for node in loaded.nodes if node.relative_path == "Cell1/Mixer")
    assert [metric.unit_of_measure for metric in mixer.metrics] == ["°C"]


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_saving_a_template_twice_replaces_its_nodes_rather_than_duplicating(
    templates: AssetTemplateRepository,
):
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)

    trimmed = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[node for node in LINE_TEMPLATE.nodes if node.relative_path != "Cell1/Mixer"],
    )
    await templates.save_template(trimmed)

    loaded = await templates.get_template(stored.id)
    assert {node.relative_path for node in loaded.nodes} == {"", "Cell1"}


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_concurrent_edit_is_refused_rather_than_silently_winning(
    templates: AssetTemplateRepository,
):
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    stale = datetime(2000, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="changed since"):
        await templates.save_template(replace(LINE_TEMPLATE, id=stored.id), expected_updated_at=stale)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_two_templates_may_not_share_a_name(templates: AssetTemplateRepository):
    await templates.save_template(LINE_TEMPLATE)

    with pytest.raises(ValueError, match="already"):
        await templates.save_template(replace(LINE_TEMPLATE, id=None))


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deleting_a_template_reports_whether_there_was_one(templates: AssetTemplateRepository):
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)

    assert await templates.delete_template(stored.id) is True
    assert await templates.delete_template(stored.id) is False
```

Add these imports to `09_uns_model/test/test_integration.py`:

```python
from dataclasses import replace
from datetime import UTC, datetime

from uns_model.asset_templates import AssetTemplateSpec, TemplateMetricSpec, TemplateNodeSpec
from uns_model.template_repository import AssetTemplateRepository
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k template`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_model.template_repository'`

- [ ] **Step 3: Write the repository**

Create `09_uns_model/src/uns_model/template_repository.py`:

```python
"""
The write seam for Asset Templates.

Separate from `AssetModelRepository` for the same reason `AlertRuleRepository` is:
different tables, a different caller, and unit tests that can fake one without
dragging the other in. Propagation onto instances lives here too, because a
template edit and the Assets it changes have to commit together.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from uns_model.asset_templates import AssetTemplateSpec, TemplateProjection
from uns_model.engine import Database
from uns_model.tables import AssetTemplate, AssetTemplateMetric, AssetTemplateNode

LOGGER = logging.getLogger(__name__)


class AssetTemplateRepository:
    """Reads and writes Asset Templates, and projects them onto their instances."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_templates(self) -> list[AssetTemplate]:
        """Every template, by name. The library screen's query."""
        async with self._database.session() as session:
            result = await session.execute(select(AssetTemplate).order_by(AssetTemplate.name))
            return list(result.scalars().all())

    async def get_template(self, template_id: int) -> AssetTemplate | None:
        """One template with its nodes and their metrics loaded."""
        async with self._database.session() as session:
            result = await session.execute(
                select(AssetTemplate)
                .where(AssetTemplate.id == template_id)
                .options(selectinload(AssetTemplate.nodes).selectinload(AssetTemplateNode.metrics))
            )
            return result.scalar_one_or_none()

    async def save_template(
        self,
        spec: AssetTemplateSpec,
        *,
        expected_updated_at: datetime | None = None,
    ) -> TemplateProjection:
        """
        Create or update a template, replacing its node set wholesale.

        Replacing rather than merging: a template *is* its nodes, and a merge would
        need a stable node identity the console has no way to supply for a node the
        engineer just dragged into place. Because `asset.template_node_id` is
        ON DELETE SET NULL, a replaced node releases its Assets instead of deleting
        them, and the projection in Task 11 re-adopts them by path.

        `expected_updated_at` is optimistic locking: pass what the console loaded and
        a save that would overwrite somebody else's is refused rather than winning.
        """
        spec.validate()
        async with self._database.session() as session:
            template = await self._upsert_header(session, spec, expected_updated_at)
            await session.flush()
            await self._replace_nodes(session, template.id, spec)
            await session.flush()
            return TemplateProjection()

    async def _upsert_header(
        self,
        session,
        spec: AssetTemplateSpec,
        expected_updated_at: datetime | None,
    ) -> AssetTemplate:
        """Insert or update the `asset_template` row, checking the caller is current."""
        template: AssetTemplate | None = None
        if spec.id is not None:
            template = (
                await session.execute(select(AssetTemplate).where(AssetTemplate.id == spec.id))
            ).scalar_one_or_none()
            if template is None:
                raise ValueError(f"No Asset Template with id {spec.id}")
            if expected_updated_at is not None and template.updated_at != expected_updated_at:
                raise ValueError(
                    f"Asset Template {template.name!r} changed since it was loaded "
                    f"({template.updated_at.isoformat()}); reload before saving"
                )
            template.name = spec.name
            template.description = spec.description
            template.root_level = spec.root_level
        else:
            template = AssetTemplate(
                name=spec.name, description=spec.description, root_level=spec.root_level
            )
            session.add(template)
        try:
            await session.flush()
        except IntegrityError as error:
            raise ValueError(f"An Asset Template named {spec.name!r} already exists") from error
        return template

    async def _replace_nodes(self, session, template_id: int, spec: AssetTemplateSpec) -> None:
        """Drop every node and write the spec's, shallowest first so parents exist."""
        await session.execute(
            delete(AssetTemplateNode).where(AssetTemplateNode.template_id == template_id)
        )
        await session.flush()

        by_relative_path: dict[str, AssetTemplateNode] = {}
        for node_spec in spec.ordered():
            parent = node_spec.parent_relative_path
            node = AssetTemplateNode(
                template_id=template_id,
                parent_id=None if parent is None else by_relative_path[parent].id,
                segment=node_spec.segment,
                relative_path=node_spec.relative_path,
                level=node_spec.level,
                display_name=node_spec.display_name,
                description=node_spec.description,
                attributes=dict(node_spec.attributes),
            )
            session.add(node)
            await session.flush()
            by_relative_path[node_spec.relative_path] = node
            for metric_spec in node_spec.metrics:
                session.add(
                    AssetTemplateMetric(
                        template_node_id=node.id,
                        metric_key=metric_spec.metric_key,
                        display_name=metric_spec.display_name,
                        unit_of_measure=metric_spec.unit_of_measure,
                        decimals=metric_spec.decimals,
                        min_value=metric_spec.min_value,
                        max_value=metric_spec.max_value,
                        deadband=metric_spec.deadband,
                        description=metric_spec.description,
                    )
                )
        await session.flush()

    async def delete_template(self, template_id: int) -> bool:
        """
        Remove a template, releasing its instances rather than deleting them.

        `asset.template_id` and `asset.template_node_id` are ON DELETE SET NULL, so
        the Assets stay and simply stop being linked — which is the only safe answer,
        because `oee.oee_unit` cascades off `asset`.
        """
        async with self._database.session() as session:
            result = await session.execute(delete(AssetTemplate).where(AssetTemplate.id == template_id))
            return bool(result.rowcount)


__all__ = ["AssetTemplateRepository"]
```

Note: `text` and `TemplateProjection` are imported now because Tasks 10–13 add methods to this class that use them; if the linter objects at this point, add them in the task that first needs them instead.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k template`
Expected: PASS

- [ ] **Step 5: Export the repository**

In `09_uns_model/src/uns_model/__init__.py`, add:

```python
from uns_model.asset_templates import (
    AssetTemplateSpec,
    InstanceDrift,
    TemplateMetricSpec,
    TemplateNodeSpec,
    TemplateProjection,
)
from uns_model.template_repository import AssetTemplateRepository
```

and add all six names to `__all__`, keeping it alphabetical.

- [ ] **Step 6: Commit**

```bash
git add 09_uns_model/src/uns_model/template_repository.py 09_uns_model/src/uns_model/__init__.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): add AssetTemplateRepository with wholesale node replacement and optimistic locking"
```

---

### Task 10: `instantiate` and `instantiate_many`

The leverage the user asked for: define a line once, stamp it out forty times, and have the copies stay linked so a correction reaches all forty.

**Files:**
- Modify: `09_uns_model/src/uns_model/template_repository.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `get_template` from Task 9; `AssetModelRepository.rebind_all(connection=...)` and `level_ranks()`; `expand_pattern` from Task 6.
- Produces:
  - `AssetTemplateRepository(database, *, assets: AssetModelRepository | None = None)` — the constructor gains an injectable Asset repository.
  - `async def instantiate(self, template_id: int, *, parent_path: str, segment: str) -> Asset`
  - `async def instantiate_many(self, template_id: int, *, parent_path: str, count: int, naming_pattern: str, start: int = 1) -> list[Asset]`

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_instantiating_a_template_creates_its_whole_subtree(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)

    root = await templates.instantiate(
        stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line5"
    )

    assert root.path == f"{TEST_ROOT}/Plant1/Area1/Line5"
    assert root.display_name == "Polyol Line"
    assert root.template_id == stored.id
    mixer = await repository.get_asset(f"{root.path}/Cell1/Mixer")
    assert mixer is not None
    assert mixer.template_node_id is not None
    assert mixer.template_id is None  # only the instance root records the template
    units = {
        metric.metric_key: metric.unit_of_measure
        for metric in await repository.metrics_for_path(mixer.path)
    }
    assert units[f"{TEST_METRIC_PREFIX}Temperature/value"] == "°C"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_instantiating_many_uses_the_naming_pattern(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)

    roots = await templates.instantiate_many(
        stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", count=3, naming_pattern="Line{n:02d}", start=10
    )

    assert [root.segment for root in roots] == ["Line10", "Line11", "Line12"]


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_instantiating_below_a_finer_level_is_refused(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)

    # A LINE template cannot be placed under a MACHINE.
    with pytest.raises(ValueError, match="cannot sit under"):
        await templates.instantiate(stored.id, parent_path=MIXER_PATH, segment="Line6")


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_instantiating_onto_an_existing_name_is_refused(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)

    with pytest.raises(ValueError, match="already"):
        await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line1")


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_duplicating_an_instance_yields_another_instance_of_the_same_template(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    """Spec section 9: a duplicate of an instantiated Line is not a detached orphan."""
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    area_path = f"{TEST_ROOT}/Plant1/Area1"
    source = await templates.instantiate(stored.id, parent_path=area_path, segment="Line7")
    await repository.save_asset(
        AssetWriteSpec(path=source.path, level="LINE", display_name="Locally renamed")
    )

    copies = await repository.duplicate_subtree(
        source.path, target_parent_path=area_path, segments=["Line8"]
    )

    assert copies[0].template_id == stored.id
    assert copies[0].template_node_id is not None
    # The source's Instance Override does not travel: the copy has overridden nothing.
    assert list(copies[0].overridden_fields) == []
    copied_mixer = await repository.get_asset(f"{copies[0].path}/Cell1/Mixer")
    assert copied_mixer.template_node_id is not None
    assert copied_mixer.template_id is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "instantiat or duplicating_an_instance"`
Expected: FAIL — `AttributeError: 'AssetTemplateRepository' object has no attribute 'instantiate'`

- [ ] **Step 3: Give the repository an Asset repository**

In `09_uns_model/src/uns_model/template_repository.py`, replace `__init__`:

```python
    def __init__(self, database: Database, *, assets: AssetModelRepository | None = None) -> None:
        self._database = database
        self._assets = assets or AssetModelRepository(database)
        """Injected so a unit test can fake the rebind, and so both repositories
        share one engine rather than opening a second pool."""
```

and add the imports:

```python
from uns_model.naming import expand_pattern
from uns_model.repositories import SEPARATOR, AssetModelRepository, AssetWriteSpec
from uns_model.tables import Asset, MetricDefinition
```

(If `SEPARATOR` is re-exported from `uns_model.topic_path` rather than `repositories`, import it from there — match whatever `repositories.py` itself does.)

- [ ] **Step 4: Implement `instantiate` and `instantiate_many`**

Add to `AssetTemplateRepository`:

```python
    async def instantiate(self, template_id: int, *, parent_path: str, segment: str) -> Asset:
        """Place one copy of a template under `parent_path`, named `segment`."""
        created = await self._instantiate(template_id, parent_path=parent_path, segments=[segment])
        return created[0]

    async def instantiate_many(
        self,
        template_id: int,
        *,
        parent_path: str,
        count: int,
        naming_pattern: str,
        start: int = 1,
    ) -> list[Asset]:
        """
        Place `count` copies at once, named from `naming_pattern`.

        One transaction for the whole batch: forty lines that half-exist because the
        thirty-first name collided is worse than none, and the rebind at the end has
        to see the finished tree.
        """
        segments = expand_pattern(naming_pattern, count, start=start)
        return await self._instantiate(template_id, parent_path=parent_path, segments=segments)

    async def _instantiate(
        self, template_id: int, *, parent_path: str, segments: list[str]
    ) -> list[Asset]:
        """Create every Asset and Metric Definition each segment's subtree needs."""
        template = await self.get_template(template_id)
        if template is None:
            raise ValueError(f"No Asset Template with id {template_id}")
        if len(set(segments)) != len(segments):
            raise ValueError(f"Instance segments are not unique: {segments}")

        ranks = await self._assets.level_ranks()
        spec = _spec_from(template)

        async with self._database.session() as session:
            parent = (
                await session.execute(select(Asset).where(Asset.path == parent_path))
            ).scalar_one_or_none()
            if parent is None:
                raise ValueError(f"No Asset at {parent_path!r} to instantiate under")
            if ranks[template.root_level] <= ranks[parent.level]:
                raise ValueError(
                    f"Asset Level {template.root_level!r} cannot sit under {parent.level!r}: "
                    "a branch may skip levels but not invert them"
                )

            nodes_by_relative_path = {node.relative_path: node for node in template.nodes}
            roots: list[Asset] = []
            try:
                for segment in segments:
                    instance_root_path = f"{parent_path}{SEPARATOR}{segment}"
                    by_path: dict[str, Asset] = {}
                    for node_spec in spec.ordered():
                        node = nodes_by_relative_path[node_spec.relative_path]
                        path = (
                            instance_root_path
                            if node_spec.is_root
                            else f"{instance_root_path}{SEPARATOR}{node_spec.relative_path}"
                        )
                        parent_id = (
                            parent.id
                            if node_spec.is_root
                            else by_path[path.rsplit(SEPARATOR, 1)[0]].id
                        )
                        asset = Asset(
                            parent_id=parent_id,
                            # The instance root takes the caller's name, not the
                            # template's: the template's root segment is only a default.
                            segment=segment if node_spec.is_root else node_spec.segment,
                            path=path,
                            level=node_spec.level,
                            display_name=node_spec.display_name,
                            description=node_spec.description,
                            attributes=dict(node_spec.attributes),
                            template_id=template.id if node_spec.is_root else None,
                            template_node_id=node.id,
                        )
                        session.add(asset)
                        await session.flush()
                        by_path[path] = asset
                        for metric in node.metrics:
                            session.add(
                                MetricDefinition(
                                    asset_id=asset.id,
                                    metric_key=metric.metric_key,
                                    display_name=metric.display_name,
                                    unit_of_measure=metric.unit_of_measure,
                                    decimals=metric.decimals,
                                    min_value=metric.min_value,
                                    max_value=metric.max_value,
                                    deadband=metric.deadband,
                                    description=metric.description,
                                    template_metric_id=metric.id,
                                )
                            )
                    roots.append(by_path[instance_root_path])
                await session.flush()
            except IntegrityError as error:
                raise ValueError(
                    f"An Asset already exists under {parent_path!r} with one of {segments}"
                ) from error

            connection = await session.connection()
            await self._assets.rebind_all(connection=connection)
            for root in roots:
                await session.refresh(root)
            return roots
```

Add the module-level helper that turns stored rows back into a spec, so ordering logic exists once:

```python
def _spec_from(template: AssetTemplate) -> AssetTemplateSpec:
    """
    A spec view of a stored template, so `ordered()` is the only place tree order lives.

    Metrics are deliberately not carried across: callers that need them read
    `AssetTemplateNode.metrics` directly, which keeps the template's own ids — and
    `MetricDefinition.template_metric_id` needs those ids.
    """
    return AssetTemplateSpec(
        id=template.id,
        name=template.name,
        description=template.description,
        root_level=template.root_level,
        nodes=[
            TemplateNodeSpec(
                relative_path=node.relative_path,
                segment=node.segment,
                level=node.level,
                display_name=node.display_name,
                description=node.description,
                attributes=dict(node.attributes or {}),
            )
            for node in template.nodes
        ],
    )
```

and add `TemplateNodeSpec` to the `uns_model.asset_templates` import.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "instantiat or template"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add 09_uns_model/src/uns_model/template_repository.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): instantiate a template once or N times, linking every Asset it makes"
```

---

### Task 11: `project_to_instances` — create, adopt, and update structure

Live propagation, half of it. A template edit walks every instance and makes the structure match: create the nodes that are missing, adopt an Asset that already sits at the right path, and update the fields no engineer has claimed.

**Files:**
- Modify: `09_uns_model/src/uns_model/template_repository.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `_spec_from`, `get_template`, `AssetWriteSpec.AUTHORED_FIELDS`, `Asset.overridden_fields`.
- Produces: `async def project_to_instances(self, template_id: int) -> TemplateProjection` — structure only at this point; Task 12 adds metrics and deactivation.

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_adding_a_template_node_reaches_every_instance(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    await templates.instantiate_many(
        stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", count=2, naming_pattern="Line2{n}"
    )

    grown = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[*LINE_TEMPLATE.nodes, TemplateNodeSpec(relative_path="Cell2", segment="Cell2", level="WORK_CELL")],
    )
    await templates.save_template(grown)
    projection = await templates.project_to_instances(stored.id)

    assert projection.assets_created == 2
    assert await repository.get_asset(f"{TEST_ROOT}/Plant1/Area1/Line21/Cell2") is not None
    assert await repository.get_asset(f"{TEST_ROOT}/Plant1/Area1/Line22/Cell2") is not None


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_template_edit_updates_a_field_nobody_has_claimed(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line31")

    renamed = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[
            replace(node, display_name="Mixer Tank Mk2") if node.relative_path == "Cell1/Mixer" else node
            for node in LINE_TEMPLATE.nodes
        ],
    )
    await templates.save_template(renamed)
    await templates.project_to_instances(stored.id)

    mixer = await repository.get_asset(f"{TEST_ROOT}/Plant1/Area1/Line31/Cell1/Mixer")
    assert mixer.display_name == "Mixer Tank Mk2"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_template_edit_leaves_an_overridden_field_alone_and_says_so(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line41")
    mixer_path = f"{TEST_ROOT}/Plant1/Area1/Line41/Cell1/Mixer"
    await repository.save_asset(
        AssetWriteSpec(path=mixer_path, level="MACHINE", display_name="Old Bertha")
    )

    renamed = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[
            replace(node, display_name="Mixer Tank Mk3") if node.relative_path == "Cell1/Mixer" else node
            for node in LINE_TEMPLATE.nodes
        ],
    )
    await templates.save_template(renamed)
    projection = await templates.project_to_instances(stored.id)

    assert (await repository.get_asset(mixer_path)).display_name == "Old Bertha"
    assert (mixer_path, "display_name") in projection.overrides_skipped


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_asset_already_at_the_right_path_is_adopted_rather_than_duplicated(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line51")
    # An engineer builds Cell2 by hand, then it is added to the template.
    await repository.save_asset(AssetWriteSpec(path=f"{root.path}/Cell2", level="WORK_CELL"))

    grown = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[*LINE_TEMPLATE.nodes, TemplateNodeSpec(relative_path="Cell2", segment="Cell2", level="WORK_CELL")],
    )
    await templates.save_template(grown)
    projection = await templates.project_to_instances(stored.id)

    adopted = await repository.get_asset(f"{root.path}/Cell2")
    assert adopted.template_node_id is not None
    assert projection.assets_created == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "project or adopted or overridden_field"`
Expected: FAIL — `AttributeError: ... has no attribute 'project_to_instances'`

- [ ] **Step 3: Implement the structural half**

Add to `AssetTemplateRepository` in `09_uns_model/src/uns_model/template_repository.py`:

```python
    async def project_to_instances(self, template_id: int) -> TemplateProjection:
        """
        Make every instance match the template again.

        Live propagation (ADR-0009): a template edit reaches its instances in the
        same transaction rather than waiting for someone to press sync. Three things
        can happen to an Asset at a Template Node's path — it is created, it is
        adopted because it already exists, or it is updated field by field — and a
        field listed in `overridden_fields` is never among the updates.

        Adoption is what makes the wholesale node replacement in `save_template`
        safe: the replaced nodes released their Assets by SET NULL, and this walk
        re-links them by path.
        """
        template = await self.get_template(template_id)
        if template is None:
            raise ValueError(f"No Asset Template with id {template_id}")
        spec = _spec_from(template)
        nodes_by_relative_path = {node.relative_path: node for node in template.nodes}

        created = updated = 0
        skipped: list[tuple[str, str]] = []

        async with self._database.session() as session:
            roots = (
                (await session.execute(select(Asset).where(Asset.template_id == template_id)))
                .scalars()
                .all()
            )
            for root in roots:
                existing = {
                    asset.path: asset
                    for asset in (
                        await session.execute(
                            select(Asset).where(
                                or_(Asset.path == root.path, Asset.path.op("^@")(f"{root.path}/"))
                            )
                        )
                    )
                    .scalars()
                    .all()
                }
                for node_spec in spec.ordered():
                    node = nodes_by_relative_path[node_spec.relative_path]
                    path = (
                        root.path
                        if node_spec.is_root
                        else f"{root.path}{SEPARATOR}{node_spec.relative_path}"
                    )
                    asset = existing.get(path)
                    if asset is None:
                        parent_path = path.rsplit(SEPARATOR, 1)[0]
                        parent = existing.get(parent_path)
                        if parent is None:
                            # The parent node was itself just created, so it is in
                            # `existing` — unless the tree is malformed, which
                            # AssetTemplateSpec.validate() already ruled out.
                            raise ValueError(f"No Asset at {parent_path!r} to hang {path!r} under")
                        asset = Asset(
                            parent_id=parent.id,
                            segment=path.rsplit(SEPARATOR, 1)[-1],
                            path=path,
                            level=node_spec.level,
                            display_name=node_spec.display_name,
                            description=node_spec.description,
                            attributes=dict(node_spec.attributes),
                            template_node_id=node.id,
                        )
                        session.add(asset)
                        await session.flush()
                        existing[path] = asset
                        created += 1
                        continue

                    # Adopt: an Asset already here belongs to this node from now on.
                    asset.template_node_id = node.id
                    if node_spec.is_root:
                        asset.template_id = template_id
                    asset.level = node_spec.level
                    overridden = set(asset.overridden_fields or ())
                    changed = False
                    for name in AssetWriteSpec.AUTHORED_FIELDS:
                        if not hasattr(node_spec, name):
                            continue
                        if name in overridden:
                            skipped.append((path, name))
                            continue
                        value = getattr(node_spec, name)
                        new_value = dict(value) if name == "attributes" else value
                        if getattr(asset, name) != new_value:
                            setattr(asset, name, new_value)
                            changed = True
                    if changed:
                        updated += 1
                await session.flush()

            connection = await session.connection()
            await self._assets.rebind_all(connection=connection)
            return TemplateProjection(
                assets_created=created,
                assets_updated=updated,
                overrides_skipped=tuple(skipped),
            )
```

Add `or_` to the `sqlalchemy` import in this module.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "project or adopted or overridden_field or template or instantiat"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/template_repository.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): project a template's structure onto its instances, skipping overrides"
```

---

### Task 12: `project_to_instances` — metrics, retirement, and the automatic propagation

The other half. A node removed from the template deactivates the Assets it made (never deletes — OEE config cascades off them). Metric Definitions the template owns are rewritten unless overridden, and ones it no longer declares are removed. Then `save_template` starts calling this, which is what makes propagation *live*.

**Files:**
- Modify: `09_uns_model/src/uns_model/template_repository.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: everything from Task 11.
- Produces: `project_to_instances` now fills `assets_deactivated`, `metrics_written` and `metrics_deleted`; `save_template` returns the real projection instead of an empty one.

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_removing_a_template_node_deactivates_rather_than_deletes(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line61")

    trimmed = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[node for node in LINE_TEMPLATE.nodes if node.relative_path != "Cell1/Mixer"],
    )
    projection = await templates.save_template(trimmed)

    mixer = await repository.get_asset(f"{root.path}/Cell1/Mixer")
    # Deleting it would cascade to oee.oee_unit and take the shift calendar with it.
    assert mixer is not None
    assert mixer.is_active is False
    assert projection.assets_deactivated == 1


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_asset_an_engineer_added_by_hand_is_never_deactivated(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line71")
    await repository.save_asset(AssetWriteSpec(path=f"{root.path}/LocalCell", level="WORK_CELL"))

    await templates.project_to_instances(stored.id)

    # template_node_id IS NULL means the template never made it, so it is not the
    # template's business to retire it.
    local = await repository.get_asset(f"{root.path}/LocalCell")
    assert local.is_active is True


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_template_metric_edit_reaches_every_instance(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line81")

    rescaled = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[
            replace(node, metrics=[replace(node.metrics[0], unit_of_measure="K", decimals=2)])
            if node.relative_path == "Cell1/Mixer"
            else node
            for node in LINE_TEMPLATE.nodes
        ],
    )
    projection = await templates.save_template(rescaled)

    metric = next(
        m
        for m in await repository.metrics_for_path(f"{root.path}/Cell1/Mixer")
        if m.metric_key == f"{TEST_METRIC_PREFIX}Temperature/value"
    )
    assert metric.unit_of_measure == "K"
    assert projection.metrics_written >= 1


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_overridden_metric_survives_a_template_metric_edit(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="Line91")
    mixer_path = f"{root.path}/Cell1/Mixer"
    await repository.define_metric(
        f"{TEST_METRIC_PREFIX}Temperature/value",
        asset_path=mixer_path,
        unit_of_measure="°F",
        is_overridden=True,
    )

    rescaled = replace(
        LINE_TEMPLATE,
        id=stored.id,
        nodes=[
            replace(node, metrics=[replace(node.metrics[0], unit_of_measure="K")])
            if node.relative_path == "Cell1/Mixer"
            else node
            for node in LINE_TEMPLATE.nodes
        ],
    )
    await templates.save_template(rescaled)

    metric = next(
        m
        for m in await repository.metrics_for_path(mixer_path)
        if m.metric_key == f"{TEST_METRIC_PREFIX}Temperature/value"
    )
    assert metric.unit_of_measure == "°F"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "deactivates_rather or by_hand or metric_edit or overridden_metric"`
Expected: FAIL — `assert projection.assets_deactivated == 1` is `0`, and the metric unit is still `°C`, because `project_to_instances` does neither yet and `save_template` does not call it.

- [ ] **Step 3: Add retirement and metric projection**

In `project_to_instances`, inside the `for root in roots:` loop, after the `for node_spec in spec.ordered():` loop and before `await session.flush()`, add:

```python
                # Retire what the template no longer declares. Deactivate, never
                # delete: oee.oee_unit, oee.shift_pattern, oee.shift_exception and
                # oee.ideal_cycle_time all cascade off asset.id.
                live_node_ids = {node.id for node in template.nodes}
                for asset in existing.values():
                    if asset.template_node_id is None:
                        continue  # an engineer added it; not the template's to retire
                    if asset.template_node_id in live_node_ids:
                        continue
                    if asset.is_active:
                        asset.is_active = False
                        deactivated += 1
```

and after the field-update block for an adopted or created Asset, project its metrics. Extract that as a method so the loop stays readable:

```python
    async def _project_metrics(
        self, session, asset: Asset, node: AssetTemplateNode
    ) -> tuple[int, int, list[tuple[str, str]]]:
        """
        Rewrite the Metric Definitions this Template Node owns on one Asset.

        Owned means `template_metric_id` is set. A row an engineer edited carries
        `is_overridden` and is left exactly as it is; a row the template no longer
        declares is deleted, because a stale Unit of Measure is worse than none.
        """
        written = 0
        skipped: list[tuple[str, str]] = []
        wanted = {metric.metric_key: metric for metric in node.metrics}

        owned = (
            (
                await session.execute(
                    select(MetricDefinition).where(
                        MetricDefinition.asset_id == asset.id,
                        MetricDefinition.template_metric_id.isnot(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_key = {row.metric_key: row for row in owned}

        deleted = 0
        for key, row in by_key.items():
            if key in wanted:
                continue
            if row.is_overridden:
                skipped.append((asset.path, f"metric:{key}"))
                continue
            await session.delete(row)
            deleted += 1

        for key, metric in wanted.items():
            row = by_key.get(key)
            if row is None:
                # An Asset-specific row may already exist without a template link —
                # adopt it rather than colliding on uq_metric_definition_asset_key.
                row = (
                    await session.execute(
                        select(MetricDefinition).where(
                            MetricDefinition.asset_id == asset.id,
                            MetricDefinition.metric_key == key,
                        )
                    )
                ).scalar_one_or_none()
            if row is None:
                session.add(
                    MetricDefinition(
                        asset_id=asset.id,
                        metric_key=key,
                        display_name=metric.display_name,
                        unit_of_measure=metric.unit_of_measure,
                        decimals=metric.decimals,
                        min_value=metric.min_value,
                        max_value=metric.max_value,
                        deadband=metric.deadband,
                        description=metric.description,
                        template_metric_id=metric.id,
                    )
                )
                written += 1
                continue
            row.template_metric_id = metric.id
            if row.is_overridden:
                skipped.append((asset.path, f"metric:{key}"))
                continue
            row.display_name = metric.display_name
            row.unit_of_measure = metric.unit_of_measure
            row.decimals = metric.decimals
            row.min_value = metric.min_value
            row.max_value = metric.max_value
            row.deadband = metric.deadband
            row.description = metric.description
            written += 1

        return written, deleted, skipped
```

Call it once per node inside the `for node_spec in spec.ordered():` loop — for the created branch just before `continue`, and for the adopted branch after the field updates:

```python
                    metrics_written, metrics_deleted, metric_skips = await self._project_metrics(
                        session, asset, node
                    )
                    written += metrics_written
                    deleted_metrics += metrics_deleted
                    skipped.extend(metric_skips)
```

Initialise the new counters beside `created = updated = 0`:

```python
        created = updated = deactivated = written = deleted_metrics = 0
```

and return them:

```python
            return TemplateProjection(
                assets_created=created,
                assets_updated=updated,
                assets_deactivated=deactivated,
                metrics_written=written,
                metrics_deleted=deleted_metrics,
                overrides_skipped=tuple(skipped),
            )
```

Add `AssetTemplateNode` to the `uns_model.tables` import if it is not already there.

- [ ] **Step 4: Make `save_template` propagate**

Replace the tail of `save_template`:

```python
        spec.validate()
        async with self._database.session() as session:
            template = await self._upsert_header(session, spec, expected_updated_at)
            await session.flush()
            await self._replace_nodes(session, template.id, spec)
            await session.flush()
            template_id = template.id
        # A second transaction on purpose: the node set must be committed before the
        # projection reads it back, and a projection that fails leaves a saved
        # template rather than losing the engineer's edit. The projection is itself
        # atomic, so instances are never half-updated.
        return await self.project_to_instances(template_id)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "template or instantiat or project"`
Expected: PASS — including Task 9's `test_saving_a_template_twice_replaces_its_nodes_rather_than_duplicating`, which now also propagates.

- [ ] **Step 6: Commit**

```bash
git add 09_uns_model/src/uns_model/template_repository.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): propagate template metrics and retire removed nodes on every save"
```

---

### Task 13: `drift` and `revert_to_template`

Overrides are invisible without a report, and an override with no way back is a trap. `drift` answers "how far has this line diverged?"; `revert_to_template` drops an instance's overrides and re-projects.

**Files:**
- Modify: `09_uns_model/src/uns_model/template_repository.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `InstanceDrift` from Task 8; `project_to_instances` from Tasks 11–12.
- Produces:
  - `async def drift(self, template_id: int) -> list[InstanceDrift]`
  - `async def revert_to_template(self, asset_path: str) -> TemplateProjection`

- [ ] **Step 1: Write the failing integration test**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_drift_names_the_overridden_fields_and_the_extra_assets(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="LineD1")
    await repository.save_asset(
        AssetWriteSpec(path=f"{root.path}/Cell1/Mixer", level="MACHINE", display_name="Bertha")
    )
    await repository.save_asset(AssetWriteSpec(path=f"{root.path}/LocalCell", level="WORK_CELL"))

    report = next(entry for entry in await templates.drift(stored.id) if entry.asset_path == root.path)

    assert "display_name" in report.overridden_fields
    assert f"{root.path}/LocalCell" in report.extra_nodes
    assert report.has_drifted is True


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_an_untouched_instance_has_not_drifted(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="LineD2")

    report = next(entry for entry in await templates.drift(stored.id) if entry.asset_path == root.path)

    assert report.has_drifted is False


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_reverting_an_instance_drops_its_overrides_and_re_applies_the_template(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="LineD3")
    mixer_path = f"{root.path}/Cell1/Mixer"
    await repository.save_asset(
        AssetWriteSpec(path=mixer_path, level="MACHINE", display_name="Bertha")
    )

    await templates.revert_to_template(root.path)

    mixer = await repository.get_asset(mixer_path)
    assert mixer.display_name == "Mixer Tank"
    assert list(mixer.overridden_fields) == []


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_reverting_something_no_template_made_is_refused(
    templates: AssetTemplateRepository, repository: AssetModelRepository
):
    await repository.ensure_branch(MIXER_BRANCH)

    with pytest.raises(ValueError, match="no Asset Template"):
        await templates.revert_to_template(CELL_PATH)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "drift or revert"`
Expected: FAIL — `AttributeError: ... has no attribute 'drift'`

- [ ] **Step 3: Implement both**

Add to `AssetTemplateRepository`:

```python
    async def drift(self, template_id: int) -> list[InstanceDrift]:
        """
        How far each instance has diverged from its template.

        Overrides are the point of the design and also its main hazard: without a
        report, "why is line 12 different?" has no answer. Read-only — reporting
        drift must never be the thing that changes it.
        """
        template = await self.get_template(template_id)
        if template is None:
            raise ValueError(f"No Asset Template with id {template_id}")
        wanted_relative_paths = {node.relative_path for node in template.nodes}
        live_node_ids = {node.id for node in template.nodes}

        reports: list[InstanceDrift] = []
        async with self._database.session() as session:
            roots = (
                (await session.execute(select(Asset).where(Asset.template_id == template_id)))
                .scalars()
                .all()
            )
            for root in roots:
                subtree = (
                    (
                        await session.execute(
                            select(Asset).where(
                                or_(Asset.path == root.path, Asset.path.op("^@")(f"{root.path}/"))
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                overridden: set[str] = set()
                extra: list[str] = []
                present: set[str] = set()
                for asset in subtree:
                    overridden.update(asset.overridden_fields or ())
                    if asset.template_node_id in live_node_ids:
                        relative = asset.path[len(root.path) :].lstrip(SEPARATOR)
                        present.add(relative)
                    else:
                        extra.append(asset.path)
                overridden_metrics = (
                    (
                        await session.execute(
                            select(MetricDefinition.metric_key)
                            .join(Asset, Asset.id == MetricDefinition.asset_id)
                            .where(
                                or_(Asset.path == root.path, Asset.path.op("^@")(f"{root.path}/")),
                                MetricDefinition.is_overridden.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                reports.append(
                    InstanceDrift(
                        asset_path=root.path,
                        overridden_fields=tuple(sorted(overridden)),
                        missing_nodes=tuple(sorted(wanted_relative_paths - present)),
                        extra_nodes=tuple(sorted(extra)),
                        overridden_metrics=tuple(sorted(set(overridden_metrics))),
                    )
                )
        return reports

    async def revert_to_template(self, asset_path: str) -> TemplateProjection:
        """
        Drop one instance's Instance Overrides, then re-apply its template.

        The way out of an override. Clearing the flags first is what makes the
        re-projection do anything: propagation is defined to skip them.
        """
        async with self._database.session() as session:
            root = (
                await session.execute(select(Asset).where(Asset.path == asset_path))
            ).scalar_one_or_none()
            if root is None or root.template_id is None:
                raise ValueError(f"{asset_path!r} was made by no Asset Template, so there is nothing to revert to")
            template_id = root.template_id
            connection = await session.connection()
            await connection.execute(
                text(
                    """
                    UPDATE model.asset
                       SET overridden_fields = '{}'::text[], updated_at = now()
                     WHERE path = :path OR starts_with(path, :path || '/')
                    """
                ),
                {"path": asset_path},
            )
            await connection.execute(
                text(
                    """
                    UPDATE model.metric_definition md
                       SET is_overridden = false, updated_at = now()
                      FROM model.asset a
                     WHERE md.asset_id = a.id
                       AND (a.path = :path OR starts_with(a.path, :path || '/'))
                    """
                ),
                {"path": asset_path},
            )
        return await self.project_to_instances(template_id)
```

Add `InstanceDrift` to the `uns_model.asset_templates` import.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "drift or revert"`
Expected: PASS

Run: `uv run pytest 09_uns_model/test -v`
Expected: PASS — the whole model suite, unit and integration.

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/template_repository.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): report instance drift and let an instance be reverted to its template"
```

---

### Task 14: Demote the seed to a bootstrap

Rule 1. Two writers with equal authority is the failure mode this whole design exists to avoid: today `docker compose up asset_model_setup` re-runs `ensure_branch`, whose upsert sets `display_name`, `description` and `attributes` from YAML — so every restart silently reverts what an engineer typed in the console. After this task the seed fills an empty database and otherwise leaves authored text alone, unless someone explicitly asks it to reconcile.

**Files:**
- Modify: `09_uns_model/src/uns_model/repositories.py` (`ensure_branch`, `define_metric`)
- Modify: `09_uns_model/src/uns_model/seed.py` (`apply_plan`)
- Modify: `09_uns_model/src/uns_model/oee_seed.py:286-318` (`apply_plan`)
- Modify: `09_uns_model/src/uns_model/cli.py` (`seed`, `oee_import`)
- Modify: `09_uns_model/README.md`
- Test: `09_uns_model/test/test_seed.py`
- Test: `09_uns_model/test/test_oee_seed.py:283`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `ensure_branch(self, specs, *, rebind: bool = True, update_existing: bool = True) -> Asset`
  - `define_metric(..., update_existing: bool = True)`
  - `apply_plan(repository, plan, *, reconcile: bool = False) -> dict[str, int]`
  - `uns_model_seed --reconcile`

- [ ] **Step 1: Write the failing tests**

Append to `09_uns_model/test/test_seed.py`:

```python
class _RecordingRepository:
    """Captures how `apply_plan` calls the repository, which is the decision here."""

    def __init__(self) -> None:
        self.branch_calls: list[dict] = []
        self.metric_calls: list[dict] = []

    async def ensure_branch(self, specs, *, rebind=True, update_existing=True):
        self.branch_calls.append({"rebind": rebind, "update_existing": update_existing})
        return None

    async def define_metric(self, metric_key, **kwargs):
        self.metric_calls.append({"metric_key": metric_key, **kwargs})
        return None

    async def rebind_all(self):
        return 0


@pytest.mark.asyncio
async def test_a_seed_does_not_overwrite_what_the_console_authored():
    repository = _RecordingRepository()
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)

    await apply_plan(repository, plan)

    # Bootstrap-only: the console is the authority on display names once a row exists.
    assert all(call["update_existing"] is False for call in repository.branch_calls)
    assert all(call["update_existing"] is False for call in repository.metric_calls)


@pytest.mark.asyncio
async def test_reconciling_is_available_but_has_to_be_asked_for():
    repository = _RecordingRepository()
    plan = plan_from_simulator_config(SIMULATOR_CONFIG)

    await apply_plan(repository, plan, reconcile=True)

    assert all(call["update_existing"] is True for call in repository.branch_calls)
```

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_bootstrap_seed_leaves_a_console_edited_display_name_alone(
    repository: AssetModelRepository,
):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.save_asset(
        AssetWriteSpec(path=MIXER_PATH, level="MACHINE", display_name="Renamed In The Console")
    )

    await repository.ensure_branch(MIXER_BRANCH, update_existing=False)

    assert (await repository.get_asset(MIXER_PATH)).display_name == "Renamed In The Console"


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_reconciling_seed_still_puts_the_yaml_value_back(repository: AssetModelRepository):
    await repository.ensure_branch(MIXER_BRANCH)
    await repository.save_asset(
        AssetWriteSpec(path=MIXER_PATH, level="MACHINE", display_name="Renamed In The Console")
    )

    await repository.ensure_branch(MIXER_BRANCH, update_existing=True)

    assert (await repository.get_asset(MIXER_PATH)).display_name == "Mixer Tank 1"
```

Add `import pytest` and `pytest_asyncio` usage to `test_seed.py` only if they are not already imported — `pytest` is; the async marker needs no extra import beyond the plugin already configured for the repo.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest 09_uns_model/test/test_seed.py -v -k "overwrite or reconciling"`
Expected: FAIL — `apply_plan` passes no `update_existing`, so `_RecordingRepository` records the default `True`.

Run: `uv run pytest 09_uns_model/test/test_integration.py -v -m integrationtest -k "bootstrap_seed or reconciling_seed"`
Expected: FAIL — `ensure_branch() got an unexpected keyword argument 'update_existing'`

- [ ] **Step 3: Make the upserts optional**

In `09_uns_model/src/uns_model/repositories.py`, change `ensure_branch`'s signature and its `on_conflict_do_update`:

```python
    async def ensure_branch(
        self, specs: Sequence[AssetSpec], *, rebind: bool = True, update_existing: bool = True
    ) -> Asset:
```

Add to its docstring:

```
        `update_existing=False` makes this a bootstrap: existing rows keep whatever
        the console authored, and only `parent_id` — structure, not authored text —
        is corrected. That is what stops a container restart from reverting an
        engineer's display names (rule 1).
```

and replace the `set_={...}` with:

```python
                    .on_conflict_do_update(
                        index_elements=["path"],
                        # parent_id is structure and must stay right even in a
                        # bootstrap; everything else below it is authored text.
                        set_=(
                            {
                                "level": spec.level,
                                "parent_id": parent_id,
                                "display_name": spec.display_name,
                                "description": spec.description,
                                "attributes": spec.attributes,
                                "updated_at": func.now(),
                            }
                            if update_existing
                            else {"parent_id": parent_id}
                        ),
                    )
```

Do the same for `define_metric`: add `update_existing: bool = True` to the signature, and make its `on_conflict_do_update`'s `set_` collapse to `{"metric_key": metric_key}` when it is `False` — a no-op update that still returns the row, so the caller does not need a second query.

- [ ] **Step 4: Make `apply_plan` bootstrap by default**

In `09_uns_model/src/uns_model/seed.py`, change `apply_plan`:

```python
async def apply_plan(
    repository: AssetModelRepository, plan: SeedPlan, *, reconcile: bool = False
) -> dict[str, int]:
    """
    Write a plan to the Asset Model, then re-resolve the Topic Bindings.

    **Bootstrap, not reconcile.** Postgres is the authored source of truth and the
    console is its only writer (ADR-0003, ADR-0009), so a seed fills in what is
    missing and leaves every existing row's authored text alone. Without that, a
    `docker compose up asset_model_setup` would revert display names an engineer had
    corrected — two writers with equal authority, which is exactly the hazard the
    design removes.

    `reconcile=True` restores the old behaviour for the one case that wants it:
    re-importing a hierarchy that YAML is still the authority for.
    """
    for branch in plan.branches:
        await repository.ensure_branch(branch, rebind=False, update_existing=reconcile)
    for spec in plan.metrics:
        await repository.define_metric(
            spec.metric_key,
            asset_path=spec.asset_path,
            unit_of_measure=spec.unit_of_measure,
            display_name=spec.display_name,
            description=spec.description,
            announce=False,
            update_existing=reconcile,
        )
    rebound = await repository.rebind_all()
    return {
        "branches": len(plan.branches),
        "assets": len(plan.asset_paths),
        "metric_definitions": len(plan.metrics),
        "rebound_topics": rebound,
        "reconciled": int(reconcile),
    }
```

- [ ] **Step 5: Add the CLI flag**

In `09_uns_model/src/uns_model/cli.py`, in `seed()`, add the argument beside `--dry-run`:

```python
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Overwrite display names, descriptions and attributes from YAML. "
        "Off by default: the console is the authority once a row exists.",
    )
```

and forward it at the `apply_plan` call site (`cli.py:148`):

```python
        written = await apply_plan(repository, plan, reconcile=args.reconcile)
```

`_seed` currently takes only the plan (`cli.py:143`), so widen it to `async def _seed(plan: SeedPlan, *, reconcile: bool = False) -> int` and call it as `asyncio.run(_seed(plan, reconcile=args.reconcile))`.

- [ ] **Step 5b: Say which store is authoritative**

Still in `seed()`, immediately after `_configure_logging(args.verbose)`:

```python
    LOGGER.info(
        "Postgres is the authoritative store for the Asset Model. This seed is a bootstrap: "
        "it fills in what is missing and leaves existing rows alone. Anything authored in the "
        "console is not represented in conf/settings.yaml and will not appear here."
    )
    if args.reconcile:
        LOGGER.warning(
            "--reconcile will overwrite console-authored display names, descriptions and "
            "attributes with the values in conf/settings.yaml"
        )
```

An engineer who has spent an afternoon in the console needs to read this before wondering why `settings.yaml` does not mention their work — and the warning is the only notice they get before `--reconcile` discards it.

- [ ] **Step 5c: Stop the OEE import pruning by default**

`oee_seed.apply_plan` prunes too (`oee_seed.py:308`–`:318`), and the same argument applies: an OEE Unit added in the console must not vanish because `conf/oee/units.yaml` does not list it.

First, update the existing test in `09_uns_model/test/test_oee_seed.py:283` and add its counterpart:

```python
@pytest.mark.asyncio
async def test_apply_plan_reconciles_rows_the_files_no_longer_declare():
    repository = RecordingOeeRepository()
    await apply_plan(repository, plan_from_oee_config(CONFIG), reconcile=True)

    assert repository.calls.index("save_product") < repository.calls.index("reconcile_products")
    assert "reconcile_shift_exceptions" in repository.calls
    assert "reconcile_oee_units" in repository.calls
    assert "reconcile_shift_patterns" in repository.calls
    assert "reconcile_ideal_cycle_times" in repository.calls
    assert "reconcile_state_reason_rules" in repository.calls
    assert "reconcile_downtime_reasons" not in repository.calls


@pytest.mark.asyncio
async def test_apply_plan_prunes_nothing_by_default():
    """An OEE Unit authored in the console must survive the next container start."""
    repository = RecordingOeeRepository()
    await apply_plan(repository, plan_from_oee_config(CONFIG))

    assert "save_product" in repository.calls
    assert not [call for call in repository.calls if call.startswith("reconcile_")]
```

Then in `09_uns_model/src/uns_model/oee_seed.py`, change the signature and gate the block:

```python
async def apply_plan(
    repository: OeeMasterDataRepository, plan: OeeSeedPlan, *, reconcile: bool = False
) -> dict[str, int]:
    """Write a plan to the OEE master data.

    Order matters: products before their cycle times, patterns before the units that name
    them, units before the unit-scoped reason rules, reasons before the rules that
    reference them.

    `reconcile` deactivates and deletes rows the YAML no longer declares, and is off by
    default: Postgres is authoritative (ADR-0009), so a row the console added is not a
    row the files forgot. When on, it still runs only for files in `plan.present_files`,
    so a missing YAML file leaves that collection alone.
    """
```

and wrap the reconcile block:

```python
    present = plan.present_files if reconcile else frozenset()
```

leaving the six `if ... in present:` branches exactly as they are — one line, and the rest of the function is untouched.

Add the flag to `oee_import()` in `cli.py`, beside its `--dry-run`:

```python
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Deactivate and delete OEE rows that conf/oee/*.yaml no longer declares. "
        "Off by default: the console is the authority once a row exists.",
    )
```

and thread it: `async def _oee_import(plan: OeeSeedPlan, *, reconcile: bool = False)` → `await apply_oee_plan(repository, plan, reconcile=reconcile)`, called as `asyncio.run(_oee_import(plan, reconcile=args.reconcile))`.

Leave `main()` alone. It forwards only `-v`, so the container entrypoint bootstraps and never prunes — which is the whole point of this task.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest 09_uns_model/test/test_seed.py 09_uns_model/test/test_oee_seed.py -v`
Expected: PASS

Run: `uv run pytest 09_uns_model/test -v`
Expected: PASS

Run: `uv run uns_model_seed --dry-run` and `uv run uns_model_seed --reconcile --dry-run`
Expected: both print a plan; the first logs that Postgres is authoritative, the second also warns that it will overwrite console-authored text.

Run: `uv run uns_model_oee_import --help`
Expected: `--reconcile` is listed.

- [ ] **Step 7: Correct the README**

In `09_uns_model/README.md`, replace the two claims that are now wrong.

Replace the "Every write to the Asset tree triggers `rebind_all()`" paragraph (lines 75–77) with:

```markdown
Every write to the Asset tree triggers a rebind **in the same transaction** —
`ensure_branch`, `save_asset`, `rename_asset`, `move_asset`, `duplicate_subtree`,
`set_active`, `delete_asset`, and every template projection. `NOTIFY` is queued on
that transaction, so a rolled-back write never announces itself. Batch seeding
passes `rebind=False` per branch and calls `rebind_all()` once at the end of
`apply_plan()`.
```

Replace the "Seeding is idempotent" paragraph (lines 140–141) with:

```markdown
Seeding **bootstraps**; it does not reconcile. Postgres is the authored source of
truth and the console is its only writer, so a seed inserts what is missing and
leaves every existing row's display name, description and attributes alone. Pass
`--reconcile` to put the YAML values back — the one case where YAML is still the
authority.
```

Replace the "Restarting that one service" paragraph (lines 151–152) with:

```markdown
Restarting that one service (`docker compose up asset_model_setup`) bootstraps any
Assets `conf/settings.yaml` has gained. It will **not** revert console edits; use
`uv run uns_model_seed --reconcile` if that is what you want.
```

Add `--reconcile` to the command list:

```sh
uv run uns_model_seed --reconcile              # overwrite authored text from YAML
```

- [ ] **Step 8: Commit**

```bash
git add 09_uns_model/src/uns_model/repositories.py 09_uns_model/src/uns_model/seed.py 09_uns_model/src/uns_model/oee_seed.py 09_uns_model/src/uns_model/cli.py 09_uns_model/README.md 09_uns_model/test/test_seed.py 09_uns_model/test/test_oee_seed.py 09_uns_model/test/test_integration.py
git commit -m "feat(model): demote the seed to a bootstrap so the console stays the only writer"
```

---

### Task 15: GraphQL inputs and types

The translation layer. Inputs carry `to_spec()`, matching `AlertRuleInput`; types carry `from_*` classmethods, matching `AssetNode`.

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/input/asset.py`
- Modify: `07_uns_graphql/src/uns_graphql/type/asset.py`
- Test: `07_uns_graphql/test/input/test_asset.py` (create)

**Interfaces:**
- Consumes: `AssetWriteSpec`, `AssetTemplateSpec`, `TemplateNodeSpec`, `TemplateMetricSpec`, `AssetDependents`, `RenameResult`, `TemplateProjection`, `InstanceDrift` from Tasks 3–13.
- Produces:
  - `AssetInput` → `.to_spec() -> AssetWriteSpec`
  - `MetricDefinitionInput(metric_key, asset_path=None, display_name=None, unit_of_measure=None, decimals=None, min_value=None, max_value=None, deadband=None, description=None)`
  - `AdoptTopicInput(topic, asset_path, level, metric_key=None, unit_of_measure=None)`
  - `AssetTemplateInput` → `.to_spec() -> AssetTemplateSpec`; `TemplateNodeInput` → `.to_spec()`; `TemplateMetricInput` → `.to_spec()`
  - `DeleteAssetResult(removed: bool, refused: bool, dependents: AssetDependentsType | None)`
  - `AssetDependentsType`, `RenameResultType`, `TemplateProjectionType`, `InstanceDriftType`, `AssetTemplateType`, `TemplateNodeType`, `TemplateMetricType`
  - `AssetNode` gains `commissioned_on`, `template_id`, `template_name`, `overridden_fields`, `has_template`, and a keyword-only `template_name` on `from_asset`
  - `MetricDefinitionType` gains `is_overridden`, `is_plant_wide` and `from_metric_definition(row: MetricDefinition)`

- [ ] **Step 1: Write the failing test**

Create `07_uns_graphql/test/input/test_asset.py`:

```python
"""
Unit tests for the Asset authoring inputs. No database and no schema: what matters
is that `to_spec()` hands the repository exactly what the caller typed, because that
is the only place a GraphQL field name and a repository field name have to agree.
"""

from __future__ import annotations

import pytest

from uns_graphql.input.asset import AssetInput, AssetTemplateInput, TemplateMetricInput, TemplateNodeInput


def test_an_asset_input_becomes_an_asset_write_spec():
    spec = AssetInput(
        path="Co/PlantA/Area1/Line1",
        level="LINE",
        display_name="Polyol Line 1",
        manufacturer="Bühler",
        attributes='{"bay": "north"}',
    ).to_spec()

    assert spec.path == "Co/PlantA/Area1/Line1"
    assert spec.display_name == "Polyol Line 1"
    assert spec.manufacturer == "Bühler"
    assert spec.attributes == {"bay": "north"}


def test_omitted_attributes_become_an_empty_mapping_not_none():
    # `attributes` is NOT NULL in Postgres, so a null here has to be resolved before
    # the write rather than by the constraint.
    assert AssetInput(path="Co", level="ENTERPRISE").to_spec().attributes == {}


def test_attributes_that_are_not_a_json_object_are_rejected():
    with pytest.raises(ValueError, match="JSON object"):
        AssetInput(path="Co", level="ENTERPRISE", attributes="[1, 2]").to_spec()


def test_a_template_input_becomes_a_validated_template_spec():
    spec = AssetTemplateInput(
        name="Polyol Line",
        root_level="LINE",
        nodes=[
            TemplateNodeInput(relative_path="", segment="Line", level="LINE"),
            TemplateNodeInput(
                relative_path="Cell1",
                segment="Cell1",
                level="WORK_CELL",
                metrics=[TemplateMetricInput(metric_key="ProcessValue/Temperature/value", unit_of_measure="°C")],
            ),
        ],
    ).to_spec()

    spec.validate()  # does not raise
    assert [node.relative_path for node in spec.ordered()] == ["", "Cell1"]
    assert spec.nodes[1].metrics[0].unit_of_measure == "°C"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 07_uns_graphql/test/input/test_asset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_graphql.input.asset'`

- [ ] **Step 3: Write the inputs**

Create `07_uns_graphql/src/uns_graphql/input/asset.py`:

```python
"""
The console's Asset Model writes, as GraphQL inputs.

Each input's only job is `to_spec()`: turn what a form sent into the frozen
dataclass the repository validates. Keeping the translation here means a GraphQL
field rename cannot quietly change a database column.

`attributes` arrives as a JSON string rather than a scalar map, matching how the
schema already handles `threshold_value` on an Alert Rule: Strawberry has no
built-in JSON object input, and inventing one for two fields is not worth it.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import strawberry
from uns_model.asset_templates import AssetTemplateSpec, TemplateMetricSpec, TemplateNodeSpec
from uns_model.repositories import AssetWriteSpec


def _as_attributes(raw: str | None) -> dict[str, Any]:
    """Parse an attributes JSON string, rejecting anything that is not an object."""
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"attributes must be a JSON object, got {type(parsed).__name__}")
    return parsed


@strawberry.input(description="One Asset as the console authors it, addressed by full path")
class AssetInput:
    path: str
    level: str
    display_name: str | None = None
    description: str | None = None
    manufacturer: str | None = None
    model_number: str | None = None
    serial_number: str | None = None
    criticality: str | None = None
    commissioned_on: date | None = None
    attributes: str | None = strawberry.field(default=None, description="A JSON object, or null")
    is_active: bool = True

    def to_spec(self) -> AssetWriteSpec:
        return AssetWriteSpec(
            path=self.path,
            level=self.level,
            display_name=self.display_name,
            description=self.description,
            manufacturer=self.manufacturer,
            model_number=self.model_number,
            serial_number=self.serial_number,
            criticality=self.criticality,
            commissioned_on=self.commissioned_on,
            attributes=_as_attributes(self.attributes),
            is_active=self.is_active,
        )


@strawberry.input(description="An authored Metric Definition. A null assetPath means every Asset.")
class MetricDefinitionInput:
    metric_key: str
    asset_path: str | None = None
    display_name: str | None = None
    unit_of_measure: str | None = None
    decimals: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    deadband: float | None = None
    description: str | None = None


@strawberry.input(
    description="Turn one Unmodelled Topic into an Asset, and optionally a Metric Definition"
)
class AdoptTopicInput:
    topic: str
    asset_path: str = strawberry.field(
        description="The prefix of `topic` that is the Asset. Everything below it is the Metric Key."
    )
    level: str
    display_name: str | None = None
    metric_key: str | None = strawberry.field(
        default=None, description="Defaults to the part of `topic` below `assetPath`"
    )
    unit_of_measure: str | None = None


@strawberry.input(description="A Metric Definition a template projects onto every instance")
class TemplateMetricInput:
    metric_key: str
    display_name: str | None = None
    unit_of_measure: str | None = None
    decimals: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    deadband: float | None = None
    description: str | None = None

    def to_spec(self) -> TemplateMetricSpec:
        return TemplateMetricSpec(
            metric_key=self.metric_key,
            display_name=self.display_name,
            unit_of_measure=self.unit_of_measure,
            decimals=self.decimals,
            min_value=self.min_value,
            max_value=self.max_value,
            deadband=self.deadband,
            description=self.description,
        )


@strawberry.input(description="One Asset in a template's subtree. relativePath is '' for the root.")
class TemplateNodeInput:
    relative_path: str
    segment: str
    level: str
    display_name: str | None = None
    description: str | None = None
    attributes: str | None = None
    metrics: list[TemplateMetricInput] = strawberry.field(default_factory=list)

    def to_spec(self) -> TemplateNodeSpec:
        return TemplateNodeSpec(
            relative_path=self.relative_path,
            segment=self.segment,
            level=self.level,
            display_name=self.display_name,
            description=self.description,
            attributes=_as_attributes(self.attributes),
            metrics=[metric.to_spec() for metric in self.metrics],
        )


@strawberry.input(description="A whole Asset Template: the header plus every node")
class AssetTemplateInput:
    name: str
    root_level: str
    description: str | None = None
    id: int | None = strawberry.field(default=None, description="Null to create, set to update")  # noqa: A003
    nodes: list[TemplateNodeInput] = strawberry.field(default_factory=list)

    def to_spec(self) -> AssetTemplateSpec:
        return AssetTemplateSpec(
            id=self.id,
            name=self.name,
            root_level=self.root_level,
            description=self.description,
            nodes=[node.to_spec() for node in self.nodes],
        )


__all__ = [
    "AdoptTopicInput",
    "AssetInput",
    "AssetTemplateInput",
    "MetricDefinitionInput",
    "TemplateMetricInput",
    "TemplateNodeInput",
]
```

- [ ] **Step 4: Run the input test to verify it passes**

Run: `uv run pytest 07_uns_graphql/test/input/test_asset.py -v`
Expected: PASS

- [ ] **Step 5: Add the output types**

In `07_uns_graphql/src/uns_graphql/type/asset.py`, add these five fields to `AssetNode` and set them in `from_asset()`:

```python
    commissioned_on: date | None = strawberry.field(
        default=None, description="When this Asset went into service"
    )
    template_id: int | None = strawberry.field(
        default=None, description="The Asset Template this instance root was made from"
    )
    template_name: str | None = None
    overridden_fields: list[str] = strawberry.field(
        default_factory=list,
        description="Fields edited locally. A template edit will not overwrite them.",
    )

    @strawberry.field(description="Whether an Asset Template is keeping this Asset in step")
    def has_template(self) -> bool:
        return self.template_id is not None
```

Change `from_asset()`'s signature to take the name as an argument, and add the three fields:

```python
    @classmethod
    def from_asset(cls, asset: Asset, *, template_name: str | None = None) -> "AssetNode":
        """
        `template_name` is passed in rather than read from `asset.template`. Task 2
        adds no `template` relationship on purpose: touching one here would lazy-load
        after the session has closed, which raises `MissingGreenlet` at runtime and
        passes every unit test. A caller that has the name supplies it; the console
        looks the template up once by id for the whole tree anyway.
        """
```

and inside the existing `cls(...)` call:

```python
            commissioned_on=asset.commissioned_on,
            template_id=asset.template_id,
            template_name=template_name,
            overridden_fields=list(asset.overridden_fields or ()),
```

Add `from datetime import date` to the imports.

`commissioned_on` is on the table and accepted by `AssetInput`, but until now no query returned it — so an editor that loads an Asset, shows a form and saves it would send `commissioned_on=None` and silently erase a commissioning date it was never shown. A write API needs every writable column to be readable; that is what makes the round trip safe.

Every existing `AssetNode.from_asset(asset)` call site keeps working, because the new parameter is keyword-only with a default.

Add `is_overridden` and `is_plant_wide` to `MetricDefinitionType` and give it a constructor for an ORM row:

```python
    is_overridden: bool = strawberry.field(
        default=False,
        description="Edited locally, so an Asset Template will not overwrite it",
    )
    is_plant_wide: bool = strawberry.field(
        default=False,
        description="Applies to every Asset. Editing it changes all of them.",
    )

    @classmethod
    def from_metric_definition(cls, row: MetricDefinition) -> "MetricDefinitionType":
        """
        From an authored `model.metric_definition` row, which carries
        `is_overridden`. `from_metric_info` stays for the Enrichment path, whose
        `MetricInfo` has no such column — a resolved unit is not an authored one.

        `is_plant_wide` is derived from `asset_id`, not from an asset path: the row
        has no path column, and reading `row.asset.path` would lazy-load after the
        session closed. A caller editing one Asset already knows the path; what it
        cannot otherwise tell is whether this row belongs to that Asset or to every
        Asset, and editing an inherited row by mistake would change all of them.
        """
        return cls(
            metric_key=row.metric_key,
            display_name=row.display_name,
            unit_of_measure=row.unit_of_measure,
            decimals=row.decimals,
            min_value=row.min_value,
            max_value=row.max_value,
            deadband=row.deadband,
            is_overridden=row.is_overridden,
            is_plant_wide=row.asset_id is None,
        )
```

Add `MetricDefinition` to the `from uns_model.tables import ...` line in that module.

Then append the result types to the same module:

```python
@strawberry.type(description="What deleting an Asset would remove or leave dangling")
class AssetDependentsType:
    descendants: int
    oee_units: int
    shift_patterns: int
    shift_exceptions: int
    ideal_cycle_times: int
    alert_rules: list[str]
    total: int

    @classmethod
    def from_dependents(cls, dependents) -> AssetDependentsType:
        return cls(
            descendants=dependents.descendants,
            oee_units=dependents.oee_units,
            shift_patterns=dependents.shift_patterns,
            shift_exceptions=dependents.shift_exceptions,
            ideal_cycle_times=dependents.ideal_cycle_times,
            alert_rules=list(dependents.alert_rules),
            total=dependents.total,
        )


@strawberry.type(
    description="The outcome of a delete. `refused` means there were dependents and force was not set."
)
class DeleteAssetResult:
    removed: bool
    refused: bool
    dependents: AssetDependentsType | None = None


@strawberry.type(description="Where a renamed or moved Asset ended up")
class RenameResultType:
    path: str
    assets_updated: int
    alert_rules: list[str] = strawberry.field(
        default_factory=list,
        description="Alert Rules still naming the old path. Their topic is free text, so nothing rewrote them.",
    )

    @classmethod
    def from_result(cls, result) -> RenameResultType:
        return cls(
            path=result.path,
            assets_updated=result.assets_updated,
            alert_rules=list(result.alert_rules),
        )


@strawberry.type(description="A field a template edit did not apply because it is overridden locally")
class SkippedOverrideType:
    asset_path: str
    field_name: str


@strawberry.type(description="What a template save or propagation actually did")
class TemplateProjectionType:
    assets_created: int
    assets_updated: int
    assets_deactivated: int
    metrics_written: int
    metrics_deleted: int
    overrides_skipped: list[SkippedOverrideType]

    @classmethod
    def from_projection(cls, projection) -> TemplateProjectionType:
        return cls(
            assets_created=projection.assets_created,
            assets_updated=projection.assets_updated,
            assets_deactivated=projection.assets_deactivated,
            metrics_written=projection.metrics_written,
            metrics_deleted=projection.metrics_deleted,
            overrides_skipped=[
                SkippedOverrideType(asset_path=path, field_name=name)
                for path, name in projection.overrides_skipped
            ],
        )


@strawberry.type(description="How far one instance has diverged from its Asset Template")
class InstanceDriftType:
    asset_path: str
    overridden_fields: list[str]
    missing_nodes: list[str]
    extra_nodes: list[str]
    overridden_metrics: list[str]
    has_drifted: bool

    @classmethod
    def from_drift(cls, drift) -> InstanceDriftType:
        return cls(
            asset_path=drift.asset_path,
            overridden_fields=list(drift.overridden_fields),
            missing_nodes=list(drift.missing_nodes),
            extra_nodes=list(drift.extra_nodes),
            overridden_metrics=list(drift.overridden_metrics),
            has_drifted=drift.has_drifted,
        )


@strawberry.type(description="A Metric Definition a template projects")
class TemplateMetricType:
    id: int  # noqa: A003
    metric_key: str
    display_name: str | None
    unit_of_measure: str | None
    decimals: int | None
    min_value: float | None
    max_value: float | None
    deadband: float | None
    description: str | None

    @classmethod
    def from_metric(cls, metric) -> TemplateMetricType:
        return cls(
            id=metric.id,
            metric_key=metric.metric_key,
            display_name=metric.display_name,
            unit_of_measure=metric.unit_of_measure,
            decimals=metric.decimals,
            min_value=metric.min_value,
            max_value=metric.max_value,
            deadband=metric.deadband,
            description=metric.description,
        )


@strawberry.type(description="One Asset in a template's subtree")
class TemplateNodeType:
    id: int  # noqa: A003
    relative_path: str
    segment: str
    level: str
    display_name: str | None
    description: str | None
    attributes: str
    metrics: list[TemplateMetricType]

    @classmethod
    def from_node(cls, node) -> TemplateNodeType:
        return cls(
            id=node.id,
            relative_path=node.relative_path,
            segment=node.segment,
            level=node.level,
            display_name=node.display_name,
            description=node.description,
            attributes=json.dumps(node.attributes or {}),
            metrics=[TemplateMetricType.from_metric(metric) for metric in node.metrics],
        )


@strawberry.type(description="A reusable Asset shape — ISA-95's Equipment Class")
class AssetTemplateType:
    id: int  # noqa: A003
    name: str
    description: str | None
    root_level: str
    updated_at: datetime
    nodes: list[TemplateNodeType]

    @classmethod
    def from_template(cls, template, *, include_nodes: bool = True) -> AssetTemplateType:
        return cls(
            id=template.id,
            name=template.name,
            description=template.description,
            root_level=template.root_level,
            updated_at=template.updated_at,
            nodes=[TemplateNodeType.from_node(node) for node in template.nodes] if include_nodes else [],
        )
```

Add `import json` and `from datetime import datetime` to that module if they are not already there. `include_nodes=False` exists for `getAssetTemplates`, whose rows are loaded without their nodes.

- [ ] **Step 6: Check the schema still builds**

Run: `uv run python -c "from uns_graphql.uns_graphql_app import UNSGraphql; print(len(str(UNSGraphql.schema)))"`
Expected: prints a number. A Strawberry type error shows up here rather than at request time.

Run: `uv run pytest 07_uns_graphql/test -v -k asset`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/input/asset.py 07_uns_graphql/src/uns_graphql/type/asset.py 07_uns_graphql/test/input/test_asset.py
git commit -m "feat(graphql): add Asset and Asset Template inputs and result types"
```

---

### Task 16: Asset mutations

The write surface for the tree and its tags. Every one is a thin call onto Task 3–7's repository methods; the only logic here is the delete's refusal-versus-error decision and splitting an adopted topic into an Asset path and a Metric Key.

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/mutations/asset.py`
- Test: `07_uns_graphql/test/mutations/test_asset.py` (create)

**Interfaces:**
- Consumes: `AssetInput`, `MetricDefinitionInput`, `AdoptTopicInput` (Task 15); `AssetModelRepository.save_asset` / `rename_asset` / `move_asset` / `set_active` / `delete_asset` / `dependents_of` / `duplicate_subtree` / `define_metric` / `delete_metric` (Tasks 3–7); `expand_pattern` (Task 6).
- Produces: `class Mutation` with `save_asset`, `rename_asset`, `move_asset`, `set_asset_active`, `delete_asset`, `duplicate_asset`, `save_metric_definition`, `delete_metric_definition`, `adopt_unmodelled_topics`, and `on_shutdown`.

- [ ] **Step 1: Write the failing test**

Create `07_uns_graphql/test/mutations/test_asset.py`:

```python
"""
Unit tests for the Asset mutations. The repository is faked, so these cover the
decisions the resolver makes rather than the SQL: what a refused delete returns, and
how an adopted topic is split into an Asset path and a Metric Key.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from uns_graphql.input.asset import AdoptTopicInput, AssetInput
from uns_graphql.mutations import asset as asset_mutations


class _FakeRepository:
    def __init__(self, *, dependents_total: int = 0) -> None:
        self.saved: list = []
        self.defined: list = []
        self.deleted: list[str] = []
        self._dependents_total = dependents_total

    async def save_asset(self, spec):
        self.saved.append(spec)
        return SimpleNamespace(
            path=spec.path,
            segment=spec.path.rsplit("/", 1)[-1],
            level=spec.level,
            display_name=spec.display_name,
            description=spec.description,
            manufacturer=spec.manufacturer,
            model_number=spec.model_number,
            serial_number=spec.serial_number,
            criticality=spec.criticality,
            commissioned_on=spec.commissioned_on,
            attributes=dict(spec.attributes),
            is_active=spec.is_active,
            template_id=None,
            template_node_id=None,
            overridden_fields=[],
        )

    async def dependents_of(self, path):
        return SimpleNamespace(
            descendants=self._dependents_total,
            oee_units=0,
            shift_patterns=0,
            shift_exceptions=0,
            ideal_cycle_times=0,
            alert_rules=(),
            total=self._dependents_total,
        )

    async def delete_asset(self, path, *, force=False):
        self.deleted.append(path)
        return True

    async def define_metric(self, metric_key, **kwargs):
        self.defined.append((metric_key, kwargs))
        return SimpleNamespace(metric_key=metric_key, **kwargs)


@pytest.fixture
def fake(monkeypatch):
    repository = _FakeRepository()
    monkeypatch.setattr(asset_mutations, "_repository", lambda: repository)
    return repository


@pytest.mark.asyncio
async def test_saving_an_asset_passes_the_spec_through(fake):
    await asset_mutations.Mutation().save_asset(
        AssetInput(path="Co/PlantA", level="SITE", display_name="Plant A")
    )

    assert fake.saved[0].path == "Co/PlantA"
    assert fake.saved[0].display_name == "Plant A"


@pytest.mark.asyncio
async def test_a_delete_with_dependents_is_refused_rather_than_raising(monkeypatch):
    repository = _FakeRepository(dependents_total=3)
    monkeypatch.setattr(asset_mutations, "_repository", lambda: repository)

    result = await asset_mutations.Mutation().delete_asset(path="Co/PlantA", force=False)

    # A refusal is data, not an error: the console has to show what would be lost.
    assert result.refused is True
    assert result.removed is False
    assert result.dependents.total == 3
    assert repository.deleted == []


@pytest.mark.asyncio
async def test_a_forced_delete_goes_through(monkeypatch):
    repository = _FakeRepository(dependents_total=3)
    monkeypatch.setattr(asset_mutations, "_repository", lambda: repository)

    result = await asset_mutations.Mutation().delete_asset(path="Co/PlantA", force=True)

    assert result.removed is True
    assert result.refused is False


@pytest.mark.asyncio
async def test_adopting_a_topic_derives_the_metric_key_from_the_asset_path(fake):
    await asset_mutations.Mutation().adopt_unmodelled_topics(
        topics=[
            AdoptTopicInput(
                topic="Co/PlantA/Area1/Line1/Cell1/Mixer/ProcessValue/Temperature",
                asset_path="Co/PlantA/Area1/Line1/Cell1/Mixer",
                level="MACHINE",
                unit_of_measure="°C",
            )
        ]
    )

    assert fake.saved[0].path == "Co/PlantA/Area1/Line1/Cell1/Mixer"
    assert fake.defined[0][0] == "ProcessValue/Temperature"


@pytest.mark.asyncio
async def test_adopting_a_topic_that_is_not_under_its_asset_path_is_rejected(fake):
    with pytest.raises(ValueError, match="not under"):
        await asset_mutations.Mutation().adopt_unmodelled_topics(
            topics=[
                AdoptTopicInput(
                    topic="Co/Elsewhere/Temperature", asset_path="Co/PlantA/Mixer", level="MACHINE"
                )
            ]
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 07_uns_graphql/test/mutations/test_asset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_graphql.mutations.asset'`

- [ ] **Step 3: Write the mutations**

Create `07_uns_graphql/src/uns_graphql/mutations/asset.py`:

```python
"""
The console's Asset Model writes.

Postgres is the authored source of truth for the plant hierarchy and this is how it
is authored (ADR-0003, ADR-0009). YAML bootstraps an empty database and stops there;
after that the console is the only writer, which is what makes it safe for an
engineer to rename a line without a deployment reverting it.

Every mutation here is one repository call. The repository owns the transaction, the
Topic Binding rebind and the `NOTIFY`, so a resolver cannot forget them.
"""

import logging

import strawberry
from uns_model.engine import Database
from uns_model.naming import expand_pattern
from uns_model.repositories import AssetModelRepository

from uns_graphql.input.asset import AdoptTopicInput, AssetInput, MetricDefinitionInput
from uns_graphql.type.asset import (
    AssetDependentsType,
    AssetNode,
    DeleteAssetResult,
    MetricDefinitionType,
    RenameResultType,
)

LOGGER = logging.getLogger(__name__)


def _repository() -> AssetModelRepository:
    return AssetModelRepository(Database.shared("graphql"))


@strawberry.type(description="Author the Asset Model")
class Mutation:
    """All write access to the Asset tree and its Metric Definitions."""

    @strawberry.mutation(
        description="Create or replace one Asset, addressed by path. A field changed on an Asset "
        "an Asset Template made becomes an Instance Override and will not be overwritten again."
    )
    async def save_asset(self, asset: AssetInput) -> AssetNode:
        saved = await _repository().save_asset(asset.to_spec())
        LOGGER.info("Asset %s saved", saved.path)
        return AssetNode.from_asset(saved)

    @strawberry.mutation(
        description="Rename an Asset, rewriting every descendant's path. Returns any Alert Rule "
        "still naming the old path — their topic is free text, so nothing rewrote them."
    )
    async def rename_asset(self, path: str, segment: str) -> RenameResultType:
        result = await _repository().rename_asset(path, segment=segment)
        LOGGER.info("Asset %s renamed to %s, %s row(s) rewritten", path, result.path, result.assets_updated)
        return RenameResultType.from_result(result)

    @strawberry.mutation(description="Re-parent an Asset, taking its subtree with it.")
    async def move_asset(self, path: str, new_parent_path: str) -> RenameResultType:
        result = await _repository().move_asset(path, new_parent_path=new_parent_path)
        LOGGER.info("Asset %s moved to %s", path, result.path)
        return RenameResultType.from_result(result)

    @strawberry.mutation(
        description="Retire or restore an Asset and its subtree. Prefer this to deleting: the row "
        "stays, so its history and its OEE configuration survive."
    )
    async def set_asset_active(self, path: str, is_active: bool) -> int:
        changed = await _repository().set_active(path, is_active=is_active)
        LOGGER.info("Asset %s set active=%s, %s row(s) changed", path, is_active, changed)
        return changed

    @strawberry.mutation(
        description="Delete an Asset. Refused — not an error — when it would also remove "
        "descendants or OEE configuration, unless `force` is set."
    )
    async def delete_asset(self, path: str, force: bool = False) -> DeleteAssetResult:
        repository = _repository()
        dependents = await repository.dependents_of(path)
        if dependents.total and not force:
            LOGGER.info("Refused to delete Asset %s: %s", path, dependents.describe())
            return DeleteAssetResult(
                removed=False,
                refused=True,
                dependents=AssetDependentsType.from_dependents(dependents),
            )
        removed = await repository.delete_asset(path, force=True)
        if removed:
            LOGGER.warning("Asset %s deleted with %s", path, dependents.describe())
        return DeleteAssetResult(
            removed=removed,
            refused=False,
            dependents=AssetDependentsType.from_dependents(dependents),
        )

    @strawberry.mutation(
        description="Copy an Asset subtree N times under a new parent, naming the copies from a "
        "pattern like `Cell{n:02d}`. A copy is independent — use instantiateTemplate to stay linked."
    )
    async def duplicate_asset(
        self,
        source_path: str,
        target_parent_path: str,
        naming_pattern: str,
        copies: int = 1,
        start: int = 1,
    ) -> list[AssetNode]:
        segments = expand_pattern(naming_pattern, copies, start=start)
        created = await _repository().duplicate_subtree(
            source_path, target_parent_path=target_parent_path, segments=segments
        )
        LOGGER.info("Duplicated %s into %s copy/copies", source_path, len(created))
        return [AssetNode.from_asset(asset) for asset in created]

    @strawberry.mutation(
        description="Create or replace one Metric Definition. A null assetPath addresses the "
        "default that applies to every Asset. Marks the row as an Instance Override."
    )
    async def save_metric_definition(self, metric: MetricDefinitionInput) -> MetricDefinitionType:
        saved = await _repository().define_metric(
            metric.metric_key,
            asset_path=metric.asset_path,
            display_name=metric.display_name,
            unit_of_measure=metric.unit_of_measure,
            decimals=metric.decimals,
            min_value=metric.min_value,
            max_value=metric.max_value,
            deadband=metric.deadband,
            description=metric.description,
            is_overridden=metric.asset_path is not None,
        )
        LOGGER.info("Metric Definition %s saved for %s", metric.metric_key, metric.asset_path)
        return MetricDefinitionType.from_metric_definition(saved)

    @strawberry.mutation(description="Delete a Metric Definition. False when there was none.")
    async def delete_metric_definition(self, metric_key: str, asset_path: str | None = None) -> bool:
        return await _repository().delete_metric(metric_key, asset_path=asset_path)

    @strawberry.mutation(
        description="Turn Unmodelled Topics into Assets. Each entry names the prefix of the topic "
        "that is the Asset; whatever is below it becomes the Metric Key."
    )
    async def adopt_unmodelled_topics(self, topics: list[AdoptTopicInput]) -> list[AssetNode]:
        repository = _repository()
        adopted: list[AssetNode] = []
        for entry in topics:
            if entry.topic != entry.asset_path and not entry.topic.startswith(f"{entry.asset_path}/"):
                raise ValueError(f"Topic {entry.topic!r} is not under Asset path {entry.asset_path!r}")
            asset = await repository.save_asset(
                AssetInput(
                    path=entry.asset_path, level=entry.level, display_name=entry.display_name
                ).to_spec()
            )
            metric_key = entry.metric_key or entry.topic[len(entry.asset_path) :].lstrip("/")
            if metric_key:
                await repository.define_metric(
                    metric_key,
                    asset_path=entry.asset_path,
                    unit_of_measure=entry.unit_of_measure,
                    is_overridden=True,
                )
            adopted.append(AssetNode.from_asset(asset))
        LOGGER.info("Adopted %s Unmodelled Topic(s)", len(topics))
        return adopted

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the queries, which dispose it."""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 07_uns_graphql/test/mutations/test_asset.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/mutations/asset.py 07_uns_graphql/test/mutations/test_asset.py
git commit -m "feat(graphql): expose Asset Model writes, duplication and topic adoption as mutations"
```

---

### Task 17: Asset Template mutations and queries

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/mutations/asset_template.py`
- Modify: `07_uns_graphql/src/uns_graphql/queries/asset.py`
- Test: `07_uns_graphql/test/mutations/test_asset_template.py` (create)

**Interfaces:**
- Consumes: `AssetTemplateInput` (Task 15); `AssetTemplateRepository` (Tasks 9–13); `AssetTemplateType`, `TemplateProjectionType`, `InstanceDriftType` (Task 15).
- Produces:
  - `class Mutation` with `save_asset_template`, `delete_asset_template`, `instantiate_template`, `propagate_asset_template`, `revert_to_template`, and `on_shutdown`.
  - `queries.asset.Query` gains `get_asset_templates`, `get_asset_template`, `get_template_drift`, `get_metric_definitions`, and `under` on `get_unmodelled_topics`.

- [ ] **Step 1: Write the failing test**

Create `07_uns_graphql/test/mutations/test_asset_template.py`:

```python
"""
Unit tests for the Asset Template mutations. The repository is faked: what is under
test is that the resolver forwards optimistic-locking and naming arguments intact,
because getting either wrong is silent rather than loud.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from uns_graphql.input.asset import AssetTemplateInput, TemplateNodeInput
from uns_graphql.mutations import asset_template as template_mutations

LINE_INPUT = AssetTemplateInput(
    name="Polyol Line",
    root_level="LINE",
    nodes=[
        TemplateNodeInput(relative_path="", segment="Line", level="LINE"),
        TemplateNodeInput(relative_path="Cell1", segment="Cell1", level="WORK_CELL"),
    ],
)


class _FakeTemplates:
    def __init__(self) -> None:
        self.saved: list = []
        self.instantiated: list = []

    async def save_template(self, spec, *, expected_updated_at=None):
        self.saved.append((spec, expected_updated_at))
        return SimpleNamespace(
            assets_created=2,
            assets_updated=0,
            assets_deactivated=0,
            metrics_written=0,
            metrics_deleted=0,
            overrides_skipped=(("Co/PlantA/Line1", "display_name"),),
        )

    async def instantiate_many(self, template_id, *, parent_path, count, naming_pattern, start=1):
        self.instantiated.append((template_id, parent_path, count, naming_pattern, start))
        return []


@pytest.fixture
def fake(monkeypatch):
    templates = _FakeTemplates()
    monkeypatch.setattr(template_mutations, "_repository", lambda: templates)
    return templates


@pytest.mark.asyncio
async def test_saving_a_template_reports_what_it_skipped(fake):
    projection = await template_mutations.Mutation().save_asset_template(template=LINE_INPUT)

    assert projection.assets_created == 2
    assert projection.overrides_skipped[0].asset_path == "Co/PlantA/Line1"
    assert projection.overrides_skipped[0].field_name == "display_name"


@pytest.mark.asyncio
async def test_the_expected_timestamp_reaches_the_repository(fake):
    loaded_at = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

    await template_mutations.Mutation().save_asset_template(
        template=LINE_INPUT, expected_updated_at=loaded_at
    )

    # Dropping this silently would turn a concurrent-edit guard into no guard at all.
    assert fake.saved[0][1] == loaded_at


@pytest.mark.asyncio
async def test_instantiating_forwards_the_naming_pattern_and_start(fake):
    await template_mutations.Mutation().instantiate_template(
        template_id=7, parent_path="Co/PlantA/Area1", copies=3, naming_pattern="Line{n:02d}", start=10
    )

    assert fake.instantiated == [(7, "Co/PlantA/Area1", 3, "Line{n:02d}", 10)]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 07_uns_graphql/test/mutations/test_asset_template.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_graphql.mutations.asset_template'`

- [ ] **Step 3: Write the mutations**

Create `07_uns_graphql/src/uns_graphql/mutations/asset_template.py`:

```python
"""
Asset Template authoring: define a shape once, stamp it out, keep the copies in step.

A save propagates immediately (ADR-0009), so every mutation here that touches a
template returns a `TemplateProjectionType` saying what it did — including which
fields it refused to overwrite because an engineer owns them. Reporting that is not
optional: live propagation is only safe if the console can show what it skipped.
"""

import logging
from datetime import datetime

import strawberry
from uns_model.engine import Database
from uns_model.template_repository import AssetTemplateRepository

from uns_graphql.input.asset import AssetTemplateInput
from uns_graphql.type.asset import AssetNode, TemplateProjectionType

LOGGER = logging.getLogger(__name__)


def _repository() -> AssetTemplateRepository:
    return AssetTemplateRepository(Database.shared("graphql"))


@strawberry.type(description="Author Asset Templates and their instances")
class Mutation:
    """All write access to `model.asset_template` and the Assets it governs."""

    @strawberry.mutation(
        description="Create or replace an Asset Template and immediately project it onto every "
        "instance. Pass `expectedUpdatedAt` as loaded to have a concurrent edit refused."
    )
    async def save_asset_template(
        self, template: AssetTemplateInput, expected_updated_at: datetime | None = None
    ) -> TemplateProjectionType:
        projection = await _repository().save_template(
            template.to_spec(), expected_updated_at=expected_updated_at
        )
        LOGGER.info(
            "Asset Template %s saved: %s created, %s updated, %s deactivated, %s override(s) skipped",
            template.name,
            projection.assets_created,
            projection.assets_updated,
            projection.assets_deactivated,
            len(projection.overrides_skipped),
        )
        return TemplateProjectionType.from_projection(projection)

    @strawberry.mutation(
        description="Delete an Asset Template. Its instances stay — they simply stop being linked."
    )
    async def delete_asset_template(self, template_id: int) -> bool:
        deleted = await _repository().delete_template(template_id)
        if deleted:
            LOGGER.info("Asset Template %s deleted; its instances were released, not removed", template_id)
        return deleted

    @strawberry.mutation(
        description="Place `copies` instances of a template under `parentPath`, named from "
        "`namingPattern` — e.g. `Line{n:02d}` with start 10 gives Line10, Line11, …"
    )
    async def instantiate_template(
        self,
        template_id: int,
        parent_path: str,
        naming_pattern: str,
        copies: int = 1,
        start: int = 1,
    ) -> list[AssetNode]:
        created = await _repository().instantiate_many(
            template_id,
            parent_path=parent_path,
            count=copies,
            naming_pattern=naming_pattern,
            start=start,
        )
        LOGGER.info("Instantiated Asset Template %s %s time(s) under %s", template_id, copies, parent_path)
        return [AssetNode.from_asset(asset) for asset in created]

    @strawberry.mutation(
        description="Re-apply a template to its instances without editing it. Useful after an "
        "instance was reverted, or to see what is currently being skipped."
    )
    async def propagate_asset_template(self, template_id: int) -> TemplateProjectionType:
        projection = await _repository().project_to_instances(template_id)
        return TemplateProjectionType.from_projection(projection)

    @strawberry.mutation(
        description="Drop one instance's Instance Overrides and re-apply its template. This "
        "discards local edits on that instance — which is the point."
    )
    async def revert_to_template(self, asset_path: str) -> TemplateProjectionType:
        projection = await _repository().revert_to_template(asset_path)
        LOGGER.warning("Reverted %s to its Asset Template, discarding local edits", asset_path)
        return TemplateProjectionType.from_projection(projection)

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the queries, which dispose it."""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest 07_uns_graphql/test/mutations/test_asset_template.py -v`
Expected: PASS

- [ ] **Step 5: Add the queries**

In `07_uns_graphql/src/uns_graphql/queries/asset.py`, add to `Query`, following whatever repository helper that module already uses:

```python
    @strawberry.field(description="Every Asset Template, by name. Nodes are not loaded — ask for one.")
    async def get_asset_templates(self) -> list[AssetTemplateType]:
        templates = await _template_repository().list_templates()
        return [AssetTemplateType.from_template(template, include_nodes=False) for template in templates]

    @strawberry.field(description="One Asset Template with its nodes and their Metric Definitions")
    async def get_asset_template(self, template_id: int) -> AssetTemplateType | None:
        template = await _template_repository().get_template(template_id)
        return AssetTemplateType.from_template(template) if template else None

    @strawberry.field(
        description="How far each instance of a template has diverged from it. Read-only."
    )
    async def get_template_drift(self, template_id: int) -> list[InstanceDriftType]:
        return [InstanceDriftType.from_drift(drift) for drift in await _template_repository().drift(template_id)]

    @strawberry.field(
        description="The authored Metric Definitions for one Asset — the Tag list for a machine."
    )
    async def get_metric_definitions(self, asset_path: str) -> list[MetricDefinitionType]:
        metrics = await _repository().metrics_for_path(asset_path)
        return [MetricDefinitionType.from_metric_definition(metric) for metric in metrics]
```

and add `under` to the existing `get_unmodelled_topics` resolver, forwarding it:

```python
    @strawberry.field(
        description="Topics that arrived but match no Asset. `under` scopes the answer to one "
        "subtree, which a central instance serving several plants needs."
    )
    async def get_unmodelled_topics(
        self, limit: int = DEFAULT_UNMODELLED_LIMIT, under: str | None = None
    ) -> list[str]:
        return await _repository().unmodelled_topics(limit=limit, under=under)
```

Add a module-level helper beside the existing one:

```python
def _template_repository() -> AssetTemplateRepository:
    return AssetTemplateRepository(Database.shared("graphql"))
```

and the imports for `AssetTemplateRepository`, `AssetTemplateType`, `InstanceDriftType`. If `get_unmodelled_topics` or `MetricDefinitionType` already exist in this module under different names, keep the existing names and only add the `under` parameter.

- [ ] **Step 6: Check the schema builds and the query tests pass**

Run: `uv run pytest 07_uns_graphql/test -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/mutations/asset_template.py 07_uns_graphql/src/uns_graphql/queries/asset.py 07_uns_graphql/test/mutations/test_asset_template.py
git commit -m "feat(graphql): expose Asset Template authoring, instantiation and drift"
```

---

### Task 18: Wire it in, regenerate the schema, and correct the docs that say this is impossible

Two docstrings currently promise the Asset Model is not writable here. Leaving them is worse than not writing this at all — the next reader would trust them.

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/uns_graphql_app.py:43,66-84`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/alert_rule.py:18-29`
- Modify: `07_uns_graphql/schema/uns_schema.graphql` (regenerated)
- Modify: `07_uns_graphql/README.md`
- Create: `docs/adr/0009-asset-templates-with-live-propagation.md`
- Modify: `CONTEXT.md`
- Test: `07_uns_graphql/test/test_uns_graphql_app.py`

**Interfaces:**
- Consumes: `Mutation` from Tasks 16 and 17.
- Produces: `class Mutation(AlertRuleMutation, OeeMutation, AssetMutation, AssetTemplateMutation)`.

- [ ] **Step 1: Write the failing test**

Append to `07_uns_graphql/test/test_uns_graphql_app.py`:

```python
def test_the_schema_exposes_the_asset_model_writes():
    sdl = str(UNSGraphql.schema)

    for mutation in ("saveAsset", "renameAsset", "moveAsset", "deleteAsset", "duplicateAsset"):
        assert mutation in sdl, mutation


def test_the_schema_exposes_asset_template_authoring():
    sdl = str(UNSGraphql.schema)

    for mutation in ("saveAssetTemplate", "instantiateTemplate", "revertToTemplate"):
        assert mutation in sdl, mutation


def test_the_schema_exposes_the_tag_and_drift_queries():
    sdl = str(UNSGraphql.schema)

    for field in ("getAssetTemplates", "getTemplateDrift", "getMetricDefinitions"):
        assert field in sdl, field
```

Match the existing import of `UNSGraphql` in that file rather than adding a second one.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest 07_uns_graphql/test/test_uns_graphql_app.py -v -k "asset_model_writes or template_authoring or tag_and_drift"`
Expected: FAIL — `assert 'saveAsset' in sdl`

- [ ] **Step 3: Wire the mutations in**

In `07_uns_graphql/src/uns_graphql/uns_graphql_app.py`, add the imports beside the existing ones:

```python
from uns_graphql.mutations.asset import Mutation as AssetMutation
from uns_graphql.mutations.asset_template import Mutation as AssetTemplateMutation
```

Replace the `Mutation` class declaration and its docstring:

```python
@strawberry.type(description="Write configuration to the UNS platform")
class Mutation(AlertRuleMutation, OeeMutation, AssetMutation, AssetTemplateMutation):
    """
    The only mutations this service exposes.

    Still deliberately narrow: process data is written by publishing to the broker,
    never through here. What is writable is *configuration a human authors* — the
    console's Alert Rules, one correction to plant data no machine can make, and the
    Asset Model itself, which Postgres is the source of truth for (ADR-0003,
    ADR-0009). The console is a static bundle with no backend of its own (ADR-0005),
    so this is the only place those writes can land.
    """

    @classmethod
    async def on_shutdown(cls):
        """
        Clean up connections, db pools etc.
        """
        await AlertRuleMutation.on_shutdown()
        await OeeMutation.on_shutdown()
        await AssetMutation.on_shutdown()
        await AssetTemplateMutation.on_shutdown()
```

- [ ] **Step 4: Correct `mutations/alert_rule.py`'s module docstring**

Replace its last paragraph (the one beginning "The Asset Model is deliberately *not* writable here either"):

```
The Asset Model is writable too, but from its own module — see `mutations/asset.py`
and `mutations/asset_template.py`. It is authored in Postgres rather than in
`conf/settings.yaml`; YAML only bootstraps an empty database (ADR-0009).
```

and change the opening line from "The only writes this service accepts: the console's Alert Rules." to:

```
The console's Alert Rules. The Asset Model has its own modules; see below.
```

- [ ] **Step 5: Run the test and regenerate the schema**

Run: `uv run pytest 07_uns_graphql/test -v`
Expected: PASS

Run from `07_uns_graphql/`:
```sh
uv run strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema --output ./schema/uns_schema.graphql
```
Expected: the file gains the new mutations, inputs and types. Check `git diff --stat 07_uns_graphql/schema/uns_schema.graphql` shows additions only — a removal means a type was renamed by accident.

- [ ] **Step 6: Write the ADR**

Create `docs/adr/0009-asset-templates-with-live-propagation.md`:

```markdown
---
status: accepted
---

# The Asset Model is authored in the console, and Asset Templates propagate live

`conf/settings.yaml` plus a reconciling seed made the Asset Model reviewable in
version control, and unusable by the people who know the plant. Every correction
needed a commit and a container restart, and the restart reverted anything typed
into the console, because `ensure_branch`'s upsert wrote YAML's `display_name` over
whatever was there. Two writers with equal authority is not a workflow.

Postgres is now the authored source of truth, the console is its only writer, and
`uns_model_seed` **bootstraps** an empty database rather than reconciling a
populated one (`--reconcile` restores the old behaviour for the one case that
wants it).

Repetition is handled by **Asset Templates** — ISA-95's Equipment Class, made
concrete. A template describes a subtree relative to wherever it is placed, is
instantiated N times from a naming pattern, and its instances stay linked to it.
Editing a template projects onto every instance in the same call, and a field an
engineer edited locally is an **Instance Override** that propagation never
overwrites. Every projection reports what it skipped.

## Considered Options

Keeping YAML authoritative and giving the console a pull request was rejected: it
puts a git round-trip between an engineer and a Unit of Measure correction, which
is the change they make most often.

Copy-on-instantiate with no link — a plain subtree clone — was rejected as the
primary mechanism. It is simpler and it is still available as `duplicateAsset`,
but forty independent copies means a corrected Unit of Measure has to be applied
forty times, which is the problem the request started from.

Explicit sync with a diff preview was rejected in favour of live propagation. It is
the safer design and it was the recommendation; the trade accepted instead is that
a template edit is immediate and *auditable* — the projection names every override
it skipped — because an explicit sync that nobody presses leaves instances silently
stale, which is the failure this replaces.

Deleting the Assets a removed Template Node made was rejected outright.
`oee.oee_unit`, `oee.shift_pattern`, `oee.shift_exception` and
`oee.ideal_cycle_time` all hold `ON DELETE CASCADE` FKs to `model.asset`, so a
template edit would silently destroy shift calendars. Removed nodes are
**deactivated**, and the template FKs on `asset` are `ON DELETE SET NULL` so
dropping a template releases its instances instead of taking them with it.

## Consequences

Because `path` is denormalised (ADR-0003), renaming or moving an Asset is a subtree
rewrite: the row itself first, so the per-row CHECK tying `path` to `segment` holds,
then a prefix rewrite of its descendants. Both run with the rebind in **one**
transaction — `NOTIFY asset_model_changed` is queued on that transaction, so a
rolled-back write never announces itself.

`console.alert_rules.topic` is free text and may be an MQTT pattern, so a rename
cannot cascade to it. `renameAsset` returns the matching rules and the console shows
them as a warning; this is a known sharp edge, not an oversight.

An Instance Override is defined as *differing from the Template Node*, not as a
flag that was once set, so typing the template's own value back in clears it.
`revertToTemplate` clears an instance's overrides deliberately and discards local
edits, which is the only way back out.

The Asset Model is now editable by anyone who can reach the console, and there is no
per-plant authorisation yet: `asset_model_edit` is one feature key across every
plant. Per-plant RBAC is a follow-on, and until it lands this is a trusted-network
assumption.
```

- [ ] **Step 7: Add the vocabulary to `CONTEXT.md`**

Add these to `CONTEXT.md`'s glossary, in the style of the entries already there:

- **Asset Template** — a reusable Asset shape, ISA-95's Equipment Class. Describes a subtree relative to wherever it is placed, so it holds no path of its own. Instantiated N times; the instances stay linked.
- **Template Node** — one Asset within a template, positioned by `relative_path` (`''` for the root). Not an Asset: it becomes one when the template is instantiated.
- **Instance Override** — a field on an instance that an engineer edited locally. Template propagation never overwrites one. Defined as differing from the Template Node, so restoring the template's value clears it.
- **Plant Scope** — the Site subtree a console session is looking at. One central instance serves many plants; almost every screen is scoped to one.
- **Bootstrap** (of the seed) — filling an empty database from `conf/settings.yaml`. Distinct from **reconcile**, which overwrites authored text and now has to be asked for.

Also add a line to `07_uns_graphql/README.md` wherever it lists what is writable, replacing any claim that the Asset Model is read-only:

```markdown
Writable: the console's Alert Rules, one OEE stop-reason correction, and the Asset
Model — Assets, Metric Definitions and Asset Templates (ADR-0009). Everything else
is read-only; process data is written by publishing to the broker.
```

- [ ] **Step 8: Run everything**

Run: `uv run pytest 07_uns_graphql/test 09_uns_model/test -v`
Expected: PASS

Run: `uv run ruff check 07_uns_graphql 09_uns_model` and `uv run ruff format --check 07_uns_graphql 09_uns_model`
Expected: clean. Fix anything reported rather than adding a `noqa`, except the `# noqa: A003` markers already needed for GraphQL fields named `id`.

- [ ] **Step 9: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/uns_graphql_app.py 07_uns_graphql/src/uns_graphql/mutations/alert_rule.py 07_uns_graphql/schema/uns_schema.graphql 07_uns_graphql/README.md 07_uns_graphql/test/test_uns_graphql_app.py docs/adr/0009-asset-templates-with-live-propagation.md CONTEXT.md
git commit -m "feat(graphql): wire the Asset Model writes into the schema, and record ADR-0009"
```

---

### Task 19: Assert the four guarantees against real Postgres

Everything so far is tested, but four of this design's claims cannot be proved by a fake, because a fake is what would have to be wrong for them to fail:

1. Migration `0004` reverses cleanly.
2. `ON DELETE SET NULL` really releases instances instead of taking their OEE configuration with them.
3. A projection really moves `model.topic_binding`.
4. A projection that fails partway really changes nothing — the single-transaction guarantee of spec 7.1.1.

**Files:**
- Test: `09_uns_model/test/test_migrations_asyncpg.py`
- Test: `09_uns_model/test/test_integration.py`

**Interfaces:**
- Consumes: `migrate` from `uns_model.cli`; `AssetTemplateRepository.save_template` / `instantiate` / `delete_template` / `project_to_instances`; `OeeMasterDataRepository.save_oee_unit` / `save_shift_pattern`; the `templates` and `repository` fixtures and `LINE_TEMPLATE` from Tasks 3 and 9.
- Produces: no production code. This task adds tests only, and passes if they pass.

- [ ] **Step 1: The migration round-trip**

Append to `09_uns_model/test/test_migrations_asyncpg.py`:

```python
@pytest.mark.integrationtest
def test_migration_0004_downgrades_and_upgrades_against_postgres():
    """
    A migration nobody has reversed is a migration that cannot be reversed. Runs
    serially with the rest of the integration suite: it drops and recreates the
    Asset Template tables, so nothing may hold a session across it.
    """
    from uns_model.cli import migrate

    assert migrate(["head"]) == 0
    assert migrate(["0003_oee_model", "--downgrade"]) == 0
    assert migrate(["head"]) == 0
```

- [ ] **Step 2: Run it**

Run: `uv run pytest 09_uns_model/test/test_migrations_asyncpg.py -v -m integrationtest`
Expected: PASS. A failure here is a real bug in Task 2's `downgrade()` — most likely a constraint dropped in the wrong order — and it is fixed in the migration, never by weakening this test.

- [ ] **Step 3: The SET NULL guarantee, with an OEE Unit attached**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_deleting_a_template_releases_its_instances_and_keeps_their_oee_config(
    templates: AssetTemplateRepository, repository: AssetModelRepository, database: Database
):
    """
    `oee.oee_unit.asset_id` cascades. If the template FK cascaded too, deleting a
    template would silently destroy shift calendars — so it is ON DELETE SET NULL,
    and this asserts it against the real constraint rather than the ORM's opinion.
    """
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(
        stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="LineOee"
    )
    mixer_path = f"{root.path}/Cell1/Mixer"
    oee = OeeMasterDataRepository(database)
    await oee.save_shift_pattern(
        ShiftPatternSpec(
            name="PyTest Pattern",
            timezone="Europe/Berlin",
            slots=(ShiftSlotSpec(day_of_week=0, start_time=time(6, 0), duration_minutes=480),),
        ),
    )
    await oee.save_oee_unit(
        OeeUnitSpec(
            asset_path=mixer_path,
            shift_pattern_name="PyTest Pattern",
            state_metric_key=f"{TEST_METRIC_PREFIX}State/value",
            good_count_metric_key=f"{TEST_METRIC_PREFIX}GoodCount/value",
        )
    )

    assert await templates.delete_template(stored.id) is True

    released = await repository.get_asset(root.path)
    assert released is not None, "deleting a template must not delete its instances"
    assert released.template_id is None
    assert (await repository.get_asset(mixer_path)).template_node_id is None
    async with database.begin() as connection:
        units = (
            await connection.execute(
                text("SELECT count(*) FROM oee.oee_unit WHERE asset_id = (SELECT id FROM model.asset WHERE path = :path)"),
                {"path": mixer_path},
            )
        ).scalar_one()
    assert units == 1, "the shift calendar survived, which is the whole point of SET NULL"
```

Add to that file's imports:

```python
from datetime import time

from sqlalchemy import text
from uns_model.oee_master_data import (
    OeeMasterDataRepository,
    OeeUnitSpec,
    ShiftPatternSpec,
    ShiftSlotSpec,
)
```

and extend the `templates` fixture's cleanup to also remove `oee.oee_unit` rows and the `PyTest Pattern` shift pattern, so a failure here does not leave a pattern behind that the next run collides with:

```python
    async with database.begin() as connection:
        await connection.execute(text("DELETE FROM oee.shift_pattern WHERE name LIKE 'PyTest %'"))
```

- [ ] **Step 4: Projection moves the Topic Binding, and a failed projection moves nothing**

Append to `09_uns_model/test/test_integration.py`:

```python
@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_projection_rebinds_topics_so_enriched_reads_follow_the_new_asset(
    templates: AssetTemplateRepository, repository: AssetModelRepository, database: Database
):
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    root = await templates.instantiate(
        stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="LineBind"
    )
    topic = f"{root.path}/Cell1/Mixer/{TEST_METRIC_PREFIX}Temperature/value"
    binder = TopicBinder(repository)
    await binder.observe(topic)

    async with database.begin() as connection:
        bound = (
            await connection.execute(
                text(
                    "SELECT a.path FROM model.topic_binding b "
                    "JOIN model.asset a ON a.id = b.asset_id WHERE b.topic = :topic"
                ),
                {"topic": topic},
            )
        ).scalar_one_or_none()

    assert bound == f"{root.path}/Cell1/Mixer", (
        "an unbound topic reads as unenriched, which is what rebinding inside the "
        "projection's transaction is for"
    )


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_a_projection_that_fails_partway_changes_nothing(
    templates: AssetTemplateRepository, repository: AssetModelRepository, monkeypatch
):
    """
    ADR-0003: a stale binding is worse than a rejected edit. The rebind runs in the
    caller's transaction, so making it fail must roll the structural writes back too.
    A fake cannot prove this; only a real transaction can.
    """
    await repository.ensure_branch(MIXER_BRANCH)
    await templates.save_template(LINE_TEMPLATE)
    stored = next(t for t in await templates.list_templates() if t.name == LINE_TEMPLATE.name)
    await templates.instantiate(stored.id, parent_path=f"{TEST_ROOT}/Plant1/Area1", segment="LineRoll")
    before = {asset.path for asset in await repository.list_assets(under=f"{TEST_ROOT}/Plant1/Area1")}

    extended = replace(
        LINE_TEMPLATE,
        nodes=(
            *LINE_TEMPLATE.nodes,
            TemplateNodeSpec(relative_path="Cell1/Packer", segment="Packer", level="MACHINE"),
        ),
    )
    await templates.save_template(extended)  # the node now exists on the template
    after_save = {asset.path for asset in await repository.list_assets(under=f"{TEST_ROOT}/Plant1/Area1")}
    assert f"{TEST_ROOT}/Plant1/Area1/LineRoll/Cell1/Packer" in after_save

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("rebind failed")

    monkeypatch.setattr(type(templates._assets), "rebind_all", _explode)
    with pytest.raises(RuntimeError, match="rebind failed"):
        await templates.project_to_instances(stored.id)

    monkeypatch.undo()
    assert {
        asset.path for asset in await repository.list_assets(under=f"{TEST_ROOT}/Plant1/Area1")
    } == after_save, "a failed projection must leave the tree exactly as it was"
    assert before <= after_save
```

`replace(LINE_TEMPLATE, ...)` works because `save_template` upserts the header by name, so re-saving the extended spec edits the same template rather than creating a second one. Add `from uns_model.asset_templates import TemplateNodeSpec` and `from uns_model.topic_binder import TopicBinder` to the imports if Tasks 8 and earlier have not already put them there.

`templates._assets` is a private attribute, and reaching into it is deliberate: the guarantee under test is that the projection uses *that* repository's connection, so injecting a different one through the constructor would test a different object than the one production uses.

- [ ] **Step 5: Run the whole integration suite**

Run: `uv run pytest 09_uns_model/test -v -m integrationtest`
Expected: PASS

Run: `uv run pytest 09_uns_model/test 07_uns_graphql/test -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add 09_uns_model/test/test_migrations_asyncpg.py 09_uns_model/test/test_integration.py
git commit -m "test(model): assert the migration, cascade and single-transaction guarantees against Postgres"
```

---

## Done when

- `uv run pytest 07_uns_graphql/test 09_uns_model/test` passes, integration tests included.
- `uv run uns_model_migrate` takes a fresh database to `0004_asset_templates`, and `--downgrade 0003_oee_model` reverses it.
- In GraphiQL: `saveAssetTemplate` → `instantiateTemplate` with `copies: 3` creates three linked subtrees; editing the template's display name and re-saving updates all three; overriding one with `saveAsset` and re-saving the template leaves that one alone and reports it in `overridesSkipped`.
- `docker compose up asset_model_setup` on a database with console edits leaves those edits in place.
