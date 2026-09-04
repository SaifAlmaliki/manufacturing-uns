# Access Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin-named Access Groups in `model`, bound to Asset Model subtrees, so GraphQL hides plant reads and refuses plant writes outside a caller’s groups.

**Architecture:** Keycloak stays identity + Console Role. Three tables next to `model.asset` hold name, root Assets, and member `sub`s. `covers` is a path-prefix test (no `LIKE`). `scope_for` loads one scope per request. Simulator seed upserts one group per Area Asset and attaches the pinned demo users.

**Tech Stack:** SQLAlchemy + Alembic (`09_uns_model`), Strawberry GraphQL (`07_uns_graphql`), React + `console-ui` (`11_frontend`), pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-04-access-groups-design.md`

## Global Constraints

- Access Groups live in schema `model`, not Keycloak, not schema `console`.
- Group names are free text. No Python enum of `RawWater` except the optional demo membership overlay (`Filtration` / `Distribution` segments only).
- Default deny: `admin` sees the whole plant; anyone else needs ≥1 group or sees nothing.
- Subtree: tick a node, children are covered. Union if a person is in several groups.
- Reads hide (empty/null). Writes refuse (`NotPermittedError`). Unmodelled topics are admin-only.
- MQTT/Kafka: keep the subscribe; drop out-of-scope events.
- Member key is Keycloak `sub`, not username.
- Save group requires ≥1 root. Duplicate / empty name rejected with a sentence.
- `/users` stays admin-only. Console never writes Keycloak.
- Tests: no live Keycloak, no broker. From the module dir: `uv run pytest test/<file>.py::test_name -v`. Frontend: `npx vitest run <file>` and `npx tsc --noEmit` in `11_frontend`.
- MQTT broker, Grafana folders, SecuredWrite / four-eyes stay out of scope.

---

## File Structure

**Create**

- `09_uns_model/src/uns_model/access.py` — `covers`, demo subject constants, `AccessGroupRecord`
- `09_uns_model/src/uns_model/access_repository.py` — CRUD + seed upsert
- `09_uns_model/test/test_access.py` — pure `covers` tests
- `09_uns_model/migrations/versions/0004_access_groups.py`
- `07_uns_graphql/src/uns_graphql/auth/scope.py` — `AccessScope`, `scope_for`, `visible_topic`
- `07_uns_graphql/src/uns_graphql/queries/access_group.py`
- `07_uns_graphql/src/uns_graphql/mutations/access_group.py`
- `07_uns_graphql/src/uns_graphql/type/access_group.py`
- `07_uns_graphql/test/auth/test_scope.py`
- `07_uns_graphql/test/queries/test_access_group.py`
- `07_uns_graphql/test/mutations/test_access_group.py`
- `docs/adr/0010-access-groups-in-the-asset-model.md`

**Modify**

- `09_uns_model/src/uns_model/tables.py` — three ORM classes
- `09_uns_model/src/uns_model/seed.py` — call access seed at end of `apply_plan`
- `09_uns_model/test/test_seed.py` — two-area plan upserts two groups
- `conf/keycloak/realm.json` — pin five user `id`s
- `00_uns_config/test/test_keycloak_realm.py` — assert pinned ids
- `07_uns_graphql/src/uns_graphql/auth/require.py` — group mutations + `require_path`
- `07_uns_graphql/test/auth/test_require.py` — three new EXPECTED rows
- `07_uns_graphql/src/uns_graphql/queries/asset.py`, `historian.py`, `graph.py`, `oee.py`, `alert_rule.py`
- `07_uns_graphql/src/uns_graphql/mutations/alert_rule.py`, `oee.py`, `hierarchy.py`
- `07_uns_graphql/src/uns_graphql/subscriptions/mqtt.py`, `kafka.py`
- `07_uns_graphql/src/uns_graphql/uns_graphql_app.py` — register query/mutation
- `07_uns_graphql/schema/uns_schema.graphql` — regenerate
- `11_frontend/src/services/graphql/queries.ts`, `client.ts`, types as needed
- `11_frontend/src/components/users/UserManagementView.tsx` + `.test.tsx`
- `CONTEXT.md` — Access Group
- `docs/adr/0009-oidc-authentication-for-console-and-graphql.md` — §5 superseded note

---

### Task 1: `covers` predicate

**Files:**
- Create: `09_uns_model/src/uns_model/access.py`
- Test: `09_uns_model/test/test_access.py`

**Interfaces:**
- Consumes: `SEPARATOR` from `uns_model.topic_path`
- Produces:

```python
DEMO_SUBJECTS: dict[str, str]  # username -> pinned Keycloak sub
OPERATOR_AREA_SEGMENT: str  # "Filtration"
VIEWER_AREA_SEGMENT: str  # "Distribution"

def covers(asset_path: str, root_path: str) -> bool: ...
```

- [ ] **Step 1: Write the failing test**

Create `09_uns_model/test/test_access.py`:

```python
from uns_model.access import covers

ROOT = "AcmeWater/Site1/Filtration"


def test_covers_the_root_a_child_and_a_grandchild():
    assert covers(ROOT, ROOT)
    assert covers(f"{ROOT}/Train1", ROOT)
    assert covers(f"{ROOT}/Train1/F101", ROOT)


def test_does_not_cover_a_sibling():
    assert not covers("AcmeWater/Site1/RawWater", ROOT)
    assert not covers("AcmeWater/Site1/RawWater/Train1", ROOT)


def test_does_not_cover_a_prefix_without_a_slash_boundary():
    assert not covers("AcmeWater/Site1/FiltrationEast", ROOT)
    assert not covers(f"{ROOT}East", ROOT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 09_uns_model && uv run pytest test/test_access.py -v`

Expected: FAIL — `ModuleNotFoundError: uns_model.access`

- [ ] **Step 3: Write minimal implementation**

Create `09_uns_model/src/uns_model/access.py`:

```python
"""Access Groups: path coverage and the demo-subject constants.

Coverage is a prefix test with a slash boundary. Do not use LIKE: an underscore
in a segment would become a wildcard (same reason model.asset avoids LIKE).
"""

from __future__ import annotations

from uns_model.topic_path import SEPARATOR

DEMO_SUBJECTS: dict[str, str] = {
    "admin.user": "00000000-0000-4000-a000-000000000001",
    "engineer.user": "00000000-0000-4000-a000-000000000002",
    "operator.user": "00000000-0000-4000-a000-000000000003",
    "auditor.user": "00000000-0000-4000-a000-000000000004",
    "viewer.user": "00000000-0000-4000-a000-000000000005",
}

OPERATOR_AREA_SEGMENT = "Filtration"
VIEWER_AREA_SEGMENT = "Distribution"


def covers(asset_path: str, root_path: str) -> bool:
    if asset_path == root_path:
        return True
    prefix = root_path + SEPARATOR
    return asset_path.startswith(prefix)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 09_uns_model && uv run pytest test/test_access.py -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/access.py 09_uns_model/test/test_access.py
git commit -m "feat(model): Access Group path coverage without LIKE wildcards"
```

---

### Task 2: Tables, migration, repository

**Files:**
- Modify: `09_uns_model/src/uns_model/tables.py` (append after `TopicBinding`)
- Create: `09_uns_model/src/uns_model/access_repository.py`
- Create: `09_uns_model/migrations/versions/0004_access_groups.py`
- Test: `09_uns_model/test/test_access.py` (add repository tests that mock nothing if you have no DB — put DB tests in `test_integration.py` only if `uns_model_setup` is the project convention; unit-test save validation with a fake session **or** extend `test_access.py` with the ValueError cases on a thin `validate_save` helper)

**Interfaces:**
- Consumes: `covers`, `DEMO_SUBJECTS`, `Asset`, `Database`
- Produces:

```python
@dataclass(frozen=True, slots=True)
class AccessGroupRecord:
    id: int
    name: str
    root_asset_ids: tuple[int, ...]
    root_paths: tuple[str, ...]
    root_segments: tuple[str, ...]
    subjects: tuple[str, ...]

class AccessGroupRepository:
    def __init__(self, database: Database) -> None: ...
    async def list_groups(self) -> list[AccessGroupRecord]: ...
    async def get_group(self, group_id: int) -> AccessGroupRecord | None: ...
    async def save_group(self, group_id: int | None, name: str, root_asset_ids: Sequence[int]) -> AccessGroupRecord: ...
    async def delete_group(self, group_id: int) -> bool: ...
    async def set_members(self, group_id: int, subjects: Sequence[str]) -> AccessGroupRecord: ...
    async def root_paths_for_subject(self, subject: str) -> frozenset[str]: ...
    async def upsert_area_groups(self, areas: Sequence[Asset]) -> list[AccessGroupRecord]: ...
    async def apply_demo_membership(self, groups: Sequence[AccessGroupRecord]) -> None: ...
```

`save_group` trims `name`. Raises `ValueError("The group needs a name.")` if empty. Raises `ValueError` naming the existing group on unique clash. Raises `ValueError("An Access Group needs at least one root Asset.")` if `root_asset_ids` is empty. Raises `ValueError` naming a missing asset id.

- [ ] **Step 1: Write the failing validation tests** (no DB)

Add to `test_access.py`:

```python
import pytest
from uns_model.access_repository import validate_group_save

def test_validate_rejects_blank_name():
    with pytest.raises(ValueError, match="needs a name"):
        validate_group_save("   ", [1])

def test_validate_rejects_no_roots():
    with pytest.raises(ValueError, match="at least one root"):
        validate_group_save("Packaging", [])
```

- [ ] **Step 2: Run to verify fail**

Run: `cd 09_uns_model && uv run pytest test/test_access.py -v`

Expected: FAIL — `access_repository` missing

- [ ] **Step 3: ORM + validate + repository + migration**

Append to `tables.py` (after `TopicBinding`, same imports already present):

```python
class AccessGroup(Base):
    __tablename__ = "access_group"
    __table_args__ = (
        UniqueConstraint("name", name="uq_access_group_name"),
        CheckConstraint("name <> ''", name="ck_access_group_name_not_empty"),
        {"schema": MODEL_SCHEMA},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AccessGroupRoot(Base):
    __tablename__ = "access_group_root"
    __table_args__ = (
        UniqueConstraint("group_id", "asset_id", name="uq_access_group_root"),
        {"schema": MODEL_SCHEMA},
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{MODEL_SCHEMA}.access_group.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"), primary_key=True
    )


class AccessGroupMember(Base):
    __tablename__ = "access_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "subject", name="uq_access_group_member"),
        CheckConstraint("subject <> ''", name="ck_access_group_member_subject_not_empty"),
        {"schema": MODEL_SCHEMA},
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{MODEL_SCHEMA}.access_group.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str] = mapped_column(Text, primary_key=True)
```

Create `access_repository.py` with `validate_group_save(name, root_asset_ids) -> str` (returns trimmed name) and `AccessGroupRepository` implementing the interface above. `upsert_area_groups` upserts by `name == area.segment`, root = that Area. `apply_demo_membership` adds engineer + auditor `sub`s to every given group; operator to the group whose `root_segments` contains `OPERATOR_AREA_SEGMENT`; viewer to `VIEWER_AREA_SEGMENT`. Does not add admin. Uses `insert ... on conflict do nothing` so re-seed is idempotent.

Create migration `0004_access_groups.py`: `revision = "0004_access_groups"`, `down_revision = "0003_oee_model"`. Create the three tables with the same constraints. Grant `SELECT, INSERT, UPDATE, DELETE` on them to the same application role `0003` grants (read that file’s `_grant` and copy the pattern).

- [ ] **Step 4: Run unit tests**

Run: `cd 09_uns_model && uv run pytest test/test_access.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/tables.py 09_uns_model/src/uns_model/access_repository.py 09_uns_model/migrations/versions/0004_access_groups.py 09_uns_model/test/test_access.py
git commit -m "feat(model): Access Group tables and repository"
```

---

### Task 3: Seed + pinned realm subjects

**Files:**
- Modify: `09_uns_model/src/uns_model/seed.py` (`apply_plan`)
- Modify: `09_uns_model/test/test_seed.py`
- Modify: `conf/keycloak/realm.json` (each of the five `users` entries)
- Modify: `00_uns_config/test/test_keycloak_realm.py`

**Interfaces:**
- Consumes: `AccessGroupRepository`, `DEMO_SUBJECTS`
- Produces: `apply_plan` still returns the same dict keys; Access Groups are a side effect after assets exist

- [ ] **Step 1: Failing tests**

In `00_uns_config/test/test_keycloak_realm.py` add:

```python
from uns_model.access import DEMO_SUBJECTS

def test_development_users_have_pinned_subjects(realm: dict):
    ids = {user["username"]: user["id"] for user in realm["users"]}
    assert ids == DEMO_SUBJECTS
```

Importing `uns_model` from `00_uns_config` may be wrong (separate package). **Do not import across packages.** Duplicate the five UUID strings in the test (same values as `DEMO_SUBJECTS`) and add a comment that `uns_model.access.DEMO_SUBJECTS` must stay in lockstep.

In `test_seed.py`, add a test that a plan with two Area branches produces two area paths. Then add an async test of `apply_plan` only if the file already has async apply tests; otherwise add `test_access_groups_from_areas_are_named_for_the_segment` against `AccessGroupRepository.upsert_area_groups` using a stub list of `SimpleNamespace(id=1, segment="PressShop", path="Co/Site/PressShop")` — that method must accept objects with `.id`, `.segment`, `.path` so a full DB is not required if you extract the name mapping:

```python
def area_group_name(segment: str) -> str:
    return segment
```

and test:

```python
def test_area_group_name_is_the_segment_not_a_wtp_label():
    from uns_model.access_repository import area_group_name
    assert area_group_name("PressShop") == "PressShop"
    assert area_group_name("RawWater") == "RawWater"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd 00_uns_config && uv run pytest test/test_keycloak_realm.py::test_development_users_have_pinned_subjects -v`

Expected: FAIL — users have no `id`

- [ ] **Step 3: Implement**

Add `"id": "00000000-0000-4000-a000-00000000000N"` to each user in `realm.json` (N = 1..5 matching Task 1).

At the end of `apply_plan`, after `rebind_all`:

```python
    from uns_model.access_repository import AccessGroupRepository

    areas = [asset for asset in await repository.list_assets(levels=["AREA"])]
    access = AccessGroupRepository(repository._database)
    groups = await access.upsert_area_groups(areas)
    await access.apply_demo_membership(groups)
```

Add `area_group_name` in `access_repository.py` as `return segment`.

- [ ] **Step 4: Run tests**

Run:

```
cd 00_uns_config && uv run pytest test/test_keycloak_realm.py::test_development_users_have_pinned_subjects -v
cd 09_uns_model && uv run pytest test/test_access.py test/test_seed.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add conf/keycloak/realm.json 00_uns_config/test/test_keycloak_realm.py 09_uns_model/src/uns_model/seed.py 09_uns_model/src/uns_model/access_repository.py 09_uns_model/test/test_seed.py
git commit -m "feat(model): seed one Access Group per Area and pin demo subjects"
```

---

### Task 4: GraphQL `AccessScope` and mutation table

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/auth/scope.py`
- Create: `07_uns_graphql/test/auth/test_scope.py`
- Modify: `07_uns_graphql/src/uns_graphql/auth/require.py`
- Modify: `07_uns_graphql/test/auth/test_require.py`

**Interfaces:**
- Consumes: `Identity`, `AccessGroupRepository.root_paths_for_subject`, `covers`
- Produces:

```python
@dataclass(frozen=True, slots=True)
class AccessScope:
    unrestricted: bool
    root_paths: frozenset[str]
    def covers_path(self, path: str) -> bool: ...

async def scope_for(identity: Identity | None) -> AccessScope: ...
def visible_topic(scope: AccessScope, bound_asset_path: str | None) -> bool: ...
async def require_path(info: Any, path: str) -> Identity: ...
```

`scope_for(None)` and `scope_for` with no admin role and no membership → `AccessScope(False, frozenset())`. Admin → `AccessScope(True, frozenset())`. `visible_topic`: unrestricted True; `bound_asset_path is None` False; else `covers_path`.

`require_path` uses `identity_in`; raises `NotPermittedError` if unsigned-in or `not scope.covers_path(path)`, message: `This Asset or topic is outside your Access Groups: {path}.`

Add to `MUTATION_ROLES`:

```python
    "saveAccessGroup": frozenset({"admin"}),
    "deleteAccessGroup": frozenset({"admin"}),
    "setAccessGroupMembers": frozenset({"admin"}),
```

Rewrite the module docstring: queries are no longer open; plant reads use `scope_for`.

Copy the three keys into `EXPECTED` in `test_require.py`.

- [ ] **Step 1: Failing tests**

`test_scope.py`:

```python
import pytest
from uns_graphql.auth.scope import AccessScope, visible_topic
from uns_model.access import covers  # only to document the same rule

ADMIN = AccessScope(unrestricted=True, root_paths=frozenset())
EMPTY = AccessScope(unrestricted=False, root_paths=frozenset())
FILT = AccessScope(unrestricted=False, root_paths=frozenset({"AcmeWater/Site1/Filtration"}))
UNION = AccessScope(
    unrestricted=False,
    root_paths=frozenset({"AcmeWater/Site1/Filtration", "AcmeWater/Site1/Storage"}),
)


def test_admin_covers_everything():
    assert ADMIN.covers_path("AcmeWater/Site1/RawWater/Train1")


def test_empty_covers_nothing():
    assert not EMPTY.covers_path("AcmeWater/Site1/Filtration")


def test_union_covers_both_roots():
    assert UNION.covers_path("AcmeWater/Site1/Filtration/Train1")
    assert UNION.covers_path("AcmeWater/Site1/Storage/Train1")
    assert not UNION.covers_path("AcmeWater/Site1/RawWater")


def test_unmodelled_topic_is_admin_only():
    assert visible_topic(ADMIN, None)
    assert not visible_topic(FILT, None)
    assert visible_topic(FILT, "AcmeWater/Site1/Filtration")
```

Add the three mutations to `EXPECTED` in `test_require.py` **before** implementing, so `test_the_table_covers_exactly_the_six_mutations` fails until `MUTATION_ROLES` is updated.

- [ ] **Step 2: Run to verify fail**

Run: `cd 07_uns_graphql && uv run pytest test/auth/test_scope.py test/auth/test_require.py -v`

Expected: FAIL — `scope` missing; EXPECTED / MUTATION_ROLES disagree

- [ ] **Step 3: Implement `scope.py` and update `require.py`**

`scope_for` loads roots via `AccessGroupRepository(Database.shared("graphql")).root_paths_for_subject(identity.subject)` unless `identity.has_any({"admin"})`.

`AccessScope.covers_path` uses `uns_model.access.covers(path, root)` for any root.

Injectable repository for tests:

```python
async def scope_for(identity: Identity | None, *, roots_for=None) -> AccessScope:
```

`roots_for` is `Callable[[str], Awaitable[frozenset[str]]] | None`. Tests pass a lambda; production uses the repository.

- [ ] **Step 4: Run tests**

Run: `cd 07_uns_graphql && uv run pytest test/auth/test_scope.py test/auth/test_require.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/auth/scope.py 07_uns_graphql/src/uns_graphql/auth/require.py 07_uns_graphql/test/auth/test_scope.py 07_uns_graphql/test/auth/test_require.py
git commit -m "feat(graphql): AccessScope and admin-only group mutations"
```

---

### Task 5: Enforce plant reads

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/queries/asset.py`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/hierarchy.py` (`get_hierarchy` lives here)
- Modify: `07_uns_graphql/src/uns_graphql/queries/historian.py`
- Modify: `07_uns_graphql/src/uns_graphql/queries/graph.py`
- Modify: `07_uns_graphql/src/uns_graphql/queries/oee.py`
- Modify: `07_uns_graphql/src/uns_graphql/queries/alert_rule.py`
- Modify: `07_uns_graphql/src/uns_graphql/subscriptions/mqtt.py`
- Modify: `07_uns_graphql/src/uns_graphql/subscriptions/kafka.py`
- Test: `07_uns_graphql/test/queries/test_asset_scope.py` (new)

**Interfaces:**
- Consumes: `scope_for`, `visible_topic`, `identity_in`, `TopicContextResolver.resolve` (already used in `asset.py`)
- Produces: every listed resolver takes `info: strawberry.Info` and filters

Helper in `scope.py` (add in this task):

```python
async def scope_from_info(info: Any) -> AccessScope:
    return await scope_for(identity_in(getattr(info, "context", None)))
```

Filter rules (implement each; do not skip):

| Resolver | Rule |
|---|---|
| `get_assets` | keep asset if `scope.covers_path(asset.path)` |
| `get_asset_children` | same |
| `get_asset` | return None if not covered |
| `get_topic_context` | if context is None: return None unless unrestricted (still None — unmodelled has no context). If context exists and not `covers_path(context.asset_path)`: return None |
| `get_unmodelled_topics` | `[]` unless `scope.unrestricted` |
| `get_asset_model_summary` | recount from filtered `list_assets` (assets + whatever counts you can derive without leaking hidden rows). Simplest legal implementation: if not unrestricted, set `unmodelled_topics=0` and count only visible assets |
| `get_hierarchy` | if not unrestricted, drop sites/areas/lines/cells whose joined path is not covered. Build paths with `join_segments` from `uns_model.topic_path` / `hierarchy` |
| historian `get_historic_events_*` | after fetch, keep event if `visible_topic(scope, bound_path)` where `bound_path` comes from `TopicContextResolver.resolve(event.topic)` → `asset_path` or None |
| `get_uns_nodes` / `get_uns_nodes_by_property` | drop records whose `fullName` / `namespace` fails `visible_topic` |
| `get_spb_nodes_by_metric` | drop if the node’s topic fails `visible_topic` (Sparkplug usually unbound → hidden for non-admin) |
| `oee_shift_results` / `downtime_events` / `downtime_pareto` | if not `covers_path(asset_path)` return `[]` |
| `get_alert_rules` / `get_alert_rule` | hide rules whose `topic` fails `visible_topic` |
| `get_mqtt_messages` | add `info: strawberry.Info`; before `yield`, resolve topic and `continue` if not `visible_topic` |
| Kafka subscription | same drop |

Historical event type: use the attribute that holds the topic string (`.topic` on `HistoricalUNSEvent` — confirm in `type/historical_event.py`).

- [ ] **Step 1: Failing tests**

Create `07_uns_graphql/test/queries/test_asset_scope.py`. Drive `asset.Query.get_assets` / `get_unmodelled_topics` by instantiating the Query class and patching `_repository` + `scope_for`:

```python
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.scope import AccessScope
from uns_graphql.auth.token import Identity
from uns_graphql.queries.asset import Query

FILT = "AcmeWater/Site1/Filtration"
RAW = "AcmeWater/Site1/RawWater"

def _info(scope: AccessScope, roles=frozenset({"operator"})):
    identity = Identity(subject="op", username="omar", roles=roles)
    return SimpleNamespace(context={CONTEXT_KEY: identity, "_scope": scope})


@pytest.mark.asyncio
async def test_get_assets_hides_other_areas():
    assets = [
        SimpleNamespace(path=RAW, segment="RawWater", level="AREA"),
        SimpleNamespace(path=FILT, segment="Filtration", level="AREA"),
        SimpleNamespace(path=f"{FILT}/Train1", segment="Train1", level="LINE"),
    ]
    query = Query()
    with (
        patch("uns_graphql.queries.asset._repository") as repo,
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=AccessScope(False, frozenset({FILT})))),
    ):
        repo.return_value.list_assets = AsyncMock(return_value=assets)
        result = await query.get_assets()
    paths = [node.path for node in result]
    assert FILT in paths
    assert f"{FILT}/Train1" in paths
    assert RAW not in paths
```

`get_assets` must accept `info`. If `AssetNode.from_asset` needs more attributes, add them to each `SimpleNamespace` (`segment`, `level`, `path`, `id=0`, `display_name=None`, `is_active=True`) — read `type/asset.py` and copy every field it reads. Do not skip this test.

Read `AssetNode.from_asset` first and put those fields on the namespace. Assert returned paths are `FILT` and `FILT/Train1` only.

Second test: `get_unmodelled_topics` as operator returns `[]` even if repository returns `["orphan/topic"]`.

Third test: admin `unrestricted=True` returns the orphan list.

If `from_asset` is awkward, extract `filter_assets(scope, assets) -> list` in `scope.py` and test that instead, then call it from `get_assets`. Prefer a testable helper over a brittle GraphQL-node test:

```python
def filter_by_path(scope: AccessScope, items: list[T], path_of) -> list[T]:
    return [item for item in items if scope.covers_path(path_of(item))]
```

Unit-test `filter_by_path` + `visible_topic` (already done) and a thin test that `get_unmodelled_topics` short-circuits.

- [ ] **Step 2: Run to verify fail**

Run: `cd 07_uns_graphql && uv run pytest test/queries/test_asset_scope.py -v`

Expected: FAIL until helpers/resolvers exist

- [ ] **Step 3: Implement filters on every row of the table above**

MQTT: wrap the yield:

```python
                    scope = await scope_from_info(info)
                    resolver = _context_resolver()  # reuse asset.Query's resolver or TopicContextResolver(AssetModelRepository(Database.shared("graphql")))
                    async for msg in client.messages:
                        topic = str(msg.topic)
                        context = await resolver.resolve(topic)
                        bound = None if context is None else context.asset_path
                        if not visible_topic(scope, bound):
                            continue
                        yield MQTTMessage(topic=topic, payload=msg.payload)
```

- [ ] **Step 4: Run tests**

Run: `cd 07_uns_graphql && uv run pytest test/queries/test_asset_scope.py test/auth/test_scope.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/auth/scope.py 07_uns_graphql/src/uns_graphql/queries 07_uns_graphql/src/uns_graphql/mutations/hierarchy.py 07_uns_graphql/src/uns_graphql/subscriptions 07_uns_graphql/test/queries/test_asset_scope.py
git commit -m "feat(graphql): hide plant reads outside the caller Access Groups"
```

---

### Task 6: Enforce plant writes

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/mutations/alert_rule.py`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/oee.py`
- Test: `07_uns_graphql/test/mutations/test_access_writes.py` (new)

**Interfaces:**
- Consumes: `require`, `require_path` / `visible_topic` + `scope_from_info`
- Produces: same mutation names; extra refusal when the target Asset/topic is out of scope

After `require(info, ...)`:

- `save_alert_rule` / each rule in `save_alert_rules`: resolve `rule.topic`; if not `visible_topic(scope, bound)` raise `NotPermittedError` with `This Asset or topic is outside your Access Groups: {rule.topic}.`
- `delete_alert_rule` / `set_alert_rule_enabled` / `record_alert_rule_evaluation`: load the existing rule; if missing, keep today’s return (`False` / `None`); if present, same topic check
- `assign_downtime_reason`: after the repository returns (or load first if you can get `asset_path` without writing). If you only have the row after assign, **load the event first** via existing repository read if one exists; otherwise assign then — **do not write then hide**. Prefer: fetch the event, `require_path(info, row.asset_path)`, then `assign_reason`. If there is no fetch-by-id, add `OeeResultRepository.get_downtime_event(id) -> DowntimeEventRow | None` in this task (small, tested in `09_uns_model/test/test_oee_results.py` only if you already have a DB fixture; otherwise unit-test the GraphQL mutation with a patched repository that returns a row with `asset_path`).

- [ ] **Step 1: Failing tests**

```python
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.require import NotPermittedError
from uns_graphql.auth.scope import AccessScope
from uns_graphql.auth.token import Identity
from uns_graphql.mutations.alert_rule import Mutation

@pytest.mark.asyncio
async def test_save_alert_rule_refuses_a_topic_outside_the_groups():
    info = SimpleNamespace(context={
        CONTEXT_KEY: Identity("op", "omar", frozenset({"operator"})),
    })
    rule = SimpleNamespace(topic="AcmeWater/Site1/RawWater/x", to_spec=lambda: SimpleNamespace(topic="AcmeWater/Site1/RawWater/x"))
    with (
        patch("uns_graphql.auth.scope.scope_for", AsyncMock(return_value=AccessScope(False, frozenset({"AcmeWater/Site1/Filtration"})))),
        patch("uns_graphql.auth.scope.visible_topic", return_value=False),
    ):
        with pytest.raises(NotPermittedError, match="outside your Access Groups"):
            await Mutation().save_alert_rule(info, rule)
```

Adjust `rule` to be a real `AlertRuleInput` if Strawberry input is easier to construct — read `input/alert_rule.py`. The assertion that matters is `NotPermittedError` and the sentence.

Second test: `assign_downtime_reason` with a patched event whose `asset_path` is RawWater, operator scoped to Filtration → `NotPermittedError`. The repository `assign_reason` must **not** have been called.

- [ ] **Step 2: Run to verify fail**

Run: `cd 07_uns_graphql && uv run pytest test/mutations/test_access_writes.py -v`

Expected: FAIL — mutation still saves

- [ ] **Step 3: Implement the checks**

- [ ] **Step 4: Run tests**

Run: `cd 07_uns_graphql && uv run pytest test/mutations/test_access_writes.py test/auth/test_require.py -v`

Expected: PASS. Existing alert-rule / oee mutation tests must still pass: `uv run pytest test/mutations -v` (skip live-DB tests if they are marked).

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/mutations/alert_rule.py 07_uns_graphql/src/uns_graphql/mutations/oee.py 07_uns_graphql/test/mutations/test_access_writes.py
git commit -m "feat(graphql): refuse plant writes outside the caller Access Groups"
```

---

### Task 7: Access Group GraphQL API

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/type/access_group.py`
- Create: `07_uns_graphql/src/uns_graphql/queries/access_group.py`
- Create: `07_uns_graphql/src/uns_graphql/mutations/access_group.py`
- Modify: `07_uns_graphql/src/uns_graphql/uns_graphql_app.py` — `Query(..., access_group.Query)` and `Mutation(..., AccessGroupMutation)`
- Test: `07_uns_graphql/test/queries/test_access_group.py`, `07_uns_graphql/test/mutations/test_access_group.py`
- Modify: `07_uns_graphql/schema/uns_schema.graphql` via `strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema --output ./schema/uns_schema.graphql` from `07_uns_graphql`

**Interfaces:**
- Published names: `getAccessGroups`, `getAccessGroup`, `saveAccessGroup`, `deleteAccessGroup`, `setAccessGroupMembers`
- Types:

```python
@strawberry.type
class AccessGroupRootType:
    asset_id: int
    path: str
    segment: str
    level: str

@strawberry.type
class AccessGroupType:
    id: int
    name: str
    roots: list[AccessGroupRootType]
    subjects: list[str]
```

`saveAccessGroup(id: int | None, name: str, root_asset_ids: list[int])`. Map repository `ValueError` to GraphQL errors (raise as-is; Strawberry surfaces the message).

Queries: `require` is not used (not in MUTATION_ROLES). If the caller is not admin, return `[]` / `None` (hide). Do not 403.

- [ ] **Step 1: Failing schema tests**

```python
import pytest
from uns_graphql.uns_graphql_app import UNSGraphql

@pytest.mark.asyncio
async def test_save_access_group_exists():
    result = await UNSGraphql.schema.execute(
        'mutation { saveAccessGroup(name: "X", rootAssetIds: [1]) { id name } }'
    )
    messages = [e.message for e in (result.errors or [])]
    assert not any("Cannot query field" in m for m in messages)
```

Before implementation the first error message contains `Cannot query field 'saveAccessGroup'`.

- [ ] **Step 2: Run to verify fail**

Run: `cd 07_uns_graphql && uv run pytest test/mutations/test_access_group.py -v`

Expected: FAIL — Cannot query field `saveAccessGroup`

- [ ] **Step 3: Implement types, query, mutation; register on `Query`/`Mutation`**

Mutation class calls `require(info, "saveAccessGroup")` etc., then the repository.

- [ ] **Step 4: Tests for admin vs engineer**

Patch `AccessGroupRepository.save_group` / `list_groups`. Admin context (copy `ADMIN` from `test/mutations/test_hierarchy.py`) succeeds. Engineer context (`Identity(..., roles=frozenset({"engineer"}))`) raises `NotPermittedError`. Empty roots: repository ValueError message `at least one root` reaches the result errors.

- [ ] **Step 5: Export schema and commit**

```bash
cd 07_uns_graphql && uv run strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema --output ./schema/uns_schema.graphql
git add 07_uns_graphql
git commit -m "feat(graphql): Access Group queries and admin mutations"
```

---

### Task 8: Users & Access console

**Files:**
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/services/graphql/client.ts`
- Modify: `11_frontend/src/components/users/UserManagementView.tsx`
- Modify: `11_frontend/src/components/users/UserManagementView.test.tsx`
- Add types next to existing GraphQL types in `11_frontend/src/services/graphql/types.ts` (or inline in client)

**Interfaces:**
- `unsGraphQLClient.getAccessGroups(): Promise<AccessGroupDto[]>`
- `unsGraphQLClient.saveAccessGroup(...)`
- `unsGraphQLClient.deleteAccessGroup(id)`
- `unsGraphQLClient.setAccessGroupMembers(id, subjects)`
- `unsGraphQLClient.getAssets()` — use the existing method if present; if not, add a minimal `{ getAssets { path segment level } }` query for the picker

UI (spec §9):

- Tabs: `directory` | `groups` | `roles`
- Directory: column **Access groups** (chips from joining `member.id` to `group.subjects`). **Open Keycloak** button: `window.open(\`${platformConfig.authBaseUrl}/admin/${platformConfig.authRealm}/console/\`, "_blank", "noopener")`. Per row **Assign groups** opens a panel of checkboxes (one per group). Save walks every group and calls `setAccessGroupMembers` with the updated subject list.
- Groups tab: table name / root path chips / member count. **Create group** (FilterToolbar `trailing`). Edit panel: name, Asset tree from `getAssets` (tick = that path + descendants; do not require ticking children), members from `fetchRealmMembers`, **Save group** / **Cancel**. Delete confirms with member count.
- Role Profiles unchanged.

Update tests:

- Replace “names where users are actually managed” with an assertion on a button named `/Open Keycloak/i`.
- `offers no per-user permission tick boxes` must still pass **until Assign groups is opened**. Scope that test to the directory table, or click Assign and then expect group checkboxes only (not `SYSTEM_FEATURES` labels).
- Add tests: Access groups column chip; Create group / Save group / Assign groups present after groups load.

- [ ] **Step 1: Failing tests**

Add to `UserManagementView.test.tsx` (mock `unsGraphQLClient`):

```typescript
const getAccessGroups = vi.hoisted(() => vi.fn());
const getAssets = vi.hoisted(() => vi.fn());
vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getAccessGroups, getAssets, saveAccessGroup: vi.fn(), deleteAccessGroup: vi.fn(), setAccessGroupMembers: vi.fn() },
}));
```

In `beforeEach`, `getAccessGroups.mockResolvedValue([{ id: 1, name: 'Filtration', roots: [{ path: 'AcmeWater/Site1/Filtration', segment: 'Filtration', level: 'AREA', assetId: 9 }], subjects: ['kc-1'] }])`.

```typescript
it('shows Access Group chips on a directory row', async () => {
  fetchRealmMembers.mockResolvedValue(MEMBERS);
  render(<UserManagementView />);
  await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
  expect(screen.getByText('Filtration')).toBeTruthy();
});

it('offers Open Keycloak as a button', async () => {
  fetchRealmMembers.mockResolvedValue({ kind: 'forbidden' });
  render(<UserManagementView />);
  await waitFor(() => expect(screen.getByRole('button', { name: /Open Keycloak/i })).toBeTruthy());
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd 11_frontend && npx vitest run src/components/users/UserManagementView.test.tsx`

Expected: FAIL — no Filtration chip, no button

- [ ] **Step 3: Implement client methods and the view**

Keep `PageShell` / `PageContent fullWidth` / `SegmentTabs` / `FilterToolbar` / `ConsoleCard`. No extra page title.

Asset picker: sort `getAssets` by `path`; indent with `paddingLeft: segmentDepth * 12`; checkbox on a node selects that path; a child is shown included (disabled or checked) when any ancestor path is selected.

- [ ] **Step 4: Run tests and tsc**

Run:

```
cd 11_frontend && npx vitest run src/components/users/UserManagementView.test.tsx
cd 11_frontend && npx tsc --noEmit
```

Expected: PASS, no tsc errors

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/users 11_frontend/src/services/graphql
git commit -m "feat(console): Access Groups on Users and Access"
```

---

### Task 9: Glossary and ADR

**Files:**
- Modify: `CONTEXT.md` (Access section)
- Create: `docs/adr/0010-access-groups-in-the-asset-model.md`
- Modify: `docs/adr/0009-oidc-authentication-for-console-and-graphql.md` after item 5

**Interfaces:** none

- [ ] **Step 1: Write CONTEXT.md term**

After **Identity**, add:

```markdown
**Access Group**:
A name an admin typed, plus the Asset Model roots that name covers, plus the Keycloak
subjects who belong to it. The UI word is group. Distinct from a Console Role and from
a Keycloak group.
_Avoid_: security group, zone, OS group
```

- [ ] **Step 2: Write ADR-0010**

```markdown
---
status: accepted
---

# Access Groups live in the Asset Model, not in Keycloak

Date: 2026-09-04

## Status

Accepted

## Context

ADR-0009 left every authenticated role able to read the whole plant, because
per-Asset authorization needed a mapping `model.asset` did not have.

## Decision

Access Groups are three tables in schema `model`. A group has a free-text name,
one or more Asset roots (subtree via `path`), and member subjects. GraphQL loads
scope from those tables by `Identity.subject`. `admin` bypasses them. Keycloak
does not store plant paths.

## Consequences

- Different clients name groups from their own Asset Model.
- Reads hide; writes refuse. Unmodelled topics are admin-only.
- MQTT on 1883, Grafana, and attribute-level writes remain open (ADR-0009 §7).
```

- [ ] **Step 3: Note on ADR-0009**

After consequence 5, add:

```markdown
   **Superseded for plant data by ADR-0010.** Console Role still gates mutations;
   Access Groups now also scope which Assets a non-admin may read or write.
```

- [ ] **Step 4: Commit**

```bash
git add CONTEXT.md docs/adr/0010-access-groups-in-the-asset-model.md docs/adr/0009-oidc-authentication-for-console-and-graphql.md
git commit -m "docs(adr): Access Groups in the Asset Model"
```

---

## Self-review (spec coverage)

| Spec section | Task |
|---|---|
| §2–3 goals / non-goals | Global Constraints |
| §4 glossary | Task 9 |
| §5–6 data model + `covers` | Tasks 1–2 |
| §7 enforcement | Tasks 4–6 |
| §8 GraphQL groups | Task 7 |
| §9 Users & Access | Task 8 |
| §10–11 seed + pinned ids | Task 3 |
| §12 errors | Tasks 2, 6, 7 |
| §13 tests | each task |
| §14–15 docs + success | Tasks 5–9 |
| §16 judgement | encoded in interfaces |

No TBD/TODO left. `covers` / `AccessScope.covers_path` / `visible_topic` / `DEMO_SUBJECTS` names are stable across tasks.
