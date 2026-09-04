# Admin Plant Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin edit the ISA-95 plant tree in the console; persist it as `plant.yaml`, reseed the Asset Model, derive branding and mapper filters from the enterprise name, and rewrite graph/historian prefixes on rename.

**Architecture:** GraphQL `saveHierarchy` writes `conf/simulator/plant.yaml` (whole tree) plus derived `settings.yaml` keys, reseeds via existing `apply_plan` with prune, then runs a one-at-a-time prefix migrate. The WTP simulator is not retargeted. Adds create Asset Model cells only.

**Tech Stack:** Python ≥3.14, `uns_model`, Strawberry GraphQL, React + existing `console-ui`, pytest, `npx tsc --noEmit`.

**Spec:** `docs/superpowers/specs/2026-09-04-admin-hierarchy-yaml-design.md`

## Global Constraints

- YAML is the reviewable source of truth. The browser never writes disk; GraphQL does.
- Add cell = Asset Model only. No new simulator publishers or WTP hydraulics.
- Rename any node: rewrite that prefix in graph and historian. Delete: YAML + model only; keep stored series.
- Simulator publish map does not change on rename.
- Enterprise save sets `organization_name` to the enterprise, `display_name` to `"<enterprise> UNS"`, mapper filters to include `<enterprise>/#` (keep `test/uns/#` and Sparkplug entries).
- No new hard-coded `AcmeWater` or `CovestroAG` in files this plan touches.
- `saveHierarchy` is **admin** only. Frontend route uses `settings_edit` + `adminOnly`.
- Whole-tree save. Renames are an explicit `renames: [{oldPrefix, newPrefix}]` list (a name change is not inferred from delete+add).
- One migrate job at a time; a second renaming Save is rejected.
- Failed migrate does not roll back YAML. Admin calls `retryHierarchyMigrate`.
- Test from the module dir: `uv run pytest test/<file>.py::test_name -v`. Frontend: `npx tsc --noEmit` in `11_frontend`.
- Do not rewrite OEE units, SparkplugB payloads, or Grafana dashboard JSON.

---

## File Structure

**Create**

- `09_uns_model/src/uns_model/hierarchy.py` — `HierarchyTree` types, validate, prefixes, load/save `plant.yaml`, derive settings, rename list check
- `09_uns_model/test/test_hierarchy.py` — pure tests (no DB)
- `09_uns_model/src/uns_model/hierarchy_io.py` — read/write YAML + settings branding/mappers
- `07_uns_graphql/src/uns_graphql/mutations/hierarchy.py` — `saveHierarchy`, `retryHierarchyMigrate`, job file
- `07_uns_graphql/src/uns_graphql/type/hierarchy.py` — GraphQL types
- `07_uns_graphql/src/uns_graphql/input/hierarchy.py` — inputs
- `07_uns_graphql/test/mutations/test_hierarchy.py`
- `11_frontend/src/components/hierarchy/HierarchyView.tsx`
- `11_frontend/src/components/hierarchy/HierarchyView.test.tsx` (if the users page has a sibling test pattern; otherwise tsc is the UI gate)

**Modify**

- `09_uns_model/src/uns_model/topic_path.py` — `join_segments`, `validate_segment` (reuse `SEPARATOR`)
- `09_uns_model/src/uns_model/seed.py` + `cli.py` — load hierarchy from `plant.yaml` first; `apply_plan` prunes assets not in the plan
- `09_uns_model/src/uns_model/repositories.py` — `delete_asset` deletes the path **and descendants**
- `07_uns_graphql/src/uns_graphql/backend/historian.py` — `rewrite_topic_prefix`
- `07_uns_graphql/src/uns_graphql/backend/graphdb.py` (or `queries/graph.py` helpers) — rename ISA-95 node
- `07_uns_graphql/src/uns_graphql/uns_graphql_app.py` — register mutation
- `07_uns_graphql/src/uns_graphql/auth/require.py` + auth tests
- `07_uns_graphql/schema/uns_schema.graphql` if the repo keeps a checked-in schema
- `11_frontend/src/lib/uns/topics.ts` — `joinSegments` / `splitTopic` / reject `/` in a segment
- `11_frontend/src/services/graphql/queries.ts` + `client.ts`
- `11_frontend/src/App.tsx`, `Sidebar.tsx`, `Header.tsx`
- `docs/adr/0005-graphql-mutations-for-console-configuration.md` — one-paragraph addendum

---

### Task 1: Path helpers and HierarchyTree

**Files:**
- Modify: `09_uns_model/src/uns_model/topic_path.py`
- Create: `09_uns_model/src/uns_model/hierarchy.py`
- Test: `09_uns_model/test/test_hierarchy.py`

**Interfaces:**
- Consumes: `SEPARATOR`, `split_topic` in `topic_path.py`
- Produces:

```python
def join_segments(*segments: str) -> str: ...
def validate_segment(name: str) -> str: ...  # raises ValueError if empty or contains "/"

@dataclass(frozen=True, slots=True)
class HierarchyLine:
    name: str
    cells: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class HierarchyArea:
    name: str
    kind: str
    lines: tuple[HierarchyLine, ...]

@dataclass(frozen=True, slots=True)
class HierarchySite:
    name: str
    areas: tuple[HierarchyArea, ...]

@dataclass(frozen=True, slots=True)
class HierarchyTree:
    enterprise: str
    sites: tuple[HierarchySite, ...]

@dataclass(frozen=True, slots=True)
class PrefixRename:
    old_prefix: str
    new_prefix: str

def tree_from_mapping(raw: Mapping[str, Any]) -> HierarchyTree: ...
def tree_to_sites_mapping(tree: HierarchyTree) -> dict[str, Any]: ...  # enterprise + sites only
def validate_tree(tree: HierarchyTree) -> None: ...
def all_prefixes(tree: HierarchyTree) -> frozenset[str]: ...
def validate_renames(tree: HierarchyTree, previous: HierarchyTree, renames: Sequence[PrefixRename]) -> None: ...
```

`validate_tree`: non-empty enterprise; unique sibling names; every name passes `validate_segment`.

`validate_renames`: each `old_prefix` exists on `previous`; each `new_prefix` exists on `tree`; `old_prefix` is not on `tree` unless equal; no overlapping jobs (a prefix is not the parent of another rename’s old prefix).

- [ ] **Step 1: Failing tests**

```python
from uns_model.hierarchy import (
    HierarchyArea,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
    PrefixRename,
    all_prefixes,
    validate_renames,
    validate_tree,
)
from uns_model.topic_path import join_segments, validate_segment

def test_join_and_split_round_trip():
    assert join_segments("Acme", "Site1", "RawWater") == "Acme/Site1/RawWater"

def test_a_slash_in_a_segment_is_rejected():
    try:
        validate_segment("Site/1")
    except ValueError as exc:
        assert "Site/1" in str(exc)
    else:
        raise AssertionError("expected ValueError")

def test_duplicate_sibling_cells_are_rejected():
    tree = HierarchyTree(
        enterprise="E",
        sites=(HierarchySite("S", (HierarchyArea("A", "production", (HierarchyLine("L", ("V101", "V101")),)),)),),
    )
    try:
        validate_tree(tree)
    except ValueError:
        return
    raise AssertionError("expected ValueError")

def test_rename_must_exist_on_the_previous_tree():
    prev = HierarchyTree("E", (HierarchySite("S1", ()),))
    new = HierarchyTree("E", (HierarchySite("S2", ()),))
    try:
        validate_renames(new, prev, (PrefixRename("E/S9", "E/S2"),))
    except ValueError:
        return
    raise AssertionError("expected ValueError")
```

- [ ] **Step 2:** `cd 09_uns_model && uv run pytest test/test_hierarchy.py -v` — FAIL (import / missing functions).
- [ ] **Step 3:** Implement `join_segments` / `validate_segment` next to `split_topic`. Implement dataclasses and validators in `hierarchy.py`. Default `kind` is `"production"`.
- [ ] **Step 4:** Tests PASS.
- [ ] **Step 5: Commit** `feat(model): validate ISA-95 hierarchy trees and prefix renames`

---

### Task 2: Read/write plant.yaml and derived settings

**Files:**
- Create: `09_uns_model/src/uns_model/hierarchy_io.py`
- Test: `09_uns_model/test/test_hierarchy_io.py`

**Interfaces:**
- Consumes: `HierarchyTree`, `tree_from_mapping`, `tree_to_sites_mapping`
- Produces:

```python
def load_plant_tree(conf_dir: Path) -> HierarchyTree: ...
def save_plant_tree(conf_dir: Path, tree: HierarchyTree) -> None: ...
def apply_enterprise_to_settings(settings_text: str, enterprise: str) -> str: ...
def write_enterprise_settings(conf_dir: Path, enterprise: str) -> None: ...
```

`save_plant_tree` loads the existing document, replaces `enterprise` and `sites`, sets `profiles.wtp.sites` to the new site names (so a Site1 rename does not leave a dead profile filter), and keeps `plant`, `profiles.wtp.tier_scale`, and `profiles.wtp.families`. Round-trip does not preserve comments. Default area `kind` is `"production"`.

`apply_enterprise_to_settings`: set `platform.organization_name` to `enterprise`, `platform.display_name` to `f"{enterprise} UNS"`. In `graphdb`, `historian`, and `kafka_mapper` `mqtt.topics` lists, replace any `Something/#` that is not `test/uns/#` and not Sparkplug (`spBv1.0...`) with `f"{enterprise}/#"`. Keep `test/uns/#` and Sparkplug entries.

- [ ] **Step 1: Failing tests** using `tmp_path` copies of a minimal `plant.yaml` and a `settings.yaml` snippet with `CovestroAG/#` and `test/uns/#`.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement IO. Atomic write: write `plant.yaml.tmp` then replace.
- [ ] **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat(model): persist hierarchy YAML and derived enterprise settings`

---

### Task 3: Seed from plant.yaml and prune removed assets

**Files:**
- Modify: `09_uns_model/src/uns_model/seed.py`, `cli.py`, `repositories.py`
- Test: `09_uns_model/test/test_seed.py`

**Interfaces:**
- Consumes: `load_plant_tree`, `HierarchyTree`
- Produces:

```python
def plan_from_hierarchy_tree(tree: HierarchyTree, extra: Mapping[str, Any] | None = None) -> SeedPlan: ...
# apply_plan also deletes assets whose path is not in plan.asset_paths
# (except do not delete the empty model root if none exists)

async def delete_asset(self, path: str, *, rebind: bool = True) -> int:
    # DELETE WHERE path == :path OR path LIKE :path || '/%'
```

`plan_from_simulator_config` should, when given `{"hierarchy": tree_to_sites_mapping(tree) | {"enterprise": tree.enterprise}}`, keep working. CLI `seed()` loads `plant.yaml` via `load_plant_tree(resolve_conf_dir())` when that file exists; otherwise `settings.get("hierarchy")`.

- [ ] **Step 1:** Add tests: seed from a tree with two cells; apply; apply a smaller tree; the removed cell path is gone. `delete_asset("E/S/A/L/V101")` also removes `E/S/A/L/V101/SCADA` if present.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement prune at the end of `apply_plan` (list current asset paths, delete those not in the new plan). Extend `delete_asset` to descendants.
- [ ] **Step 4:** PASS. Existing seed tests still pass.
- [ ] **Step 5: Commit** `feat(model): seed Asset Model from plant.yaml and prune removed cells`

---

### Task 4: Historian prefix rewrite

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/backend/historian.py`
- Test: `07_uns_graphql/test/backend/test_historian_rewrite.py` (or next to existing historian tests)

**Interfaces:**
- Produces:

```python
async def rewrite_topic_prefix(old_prefix: str, new_prefix: str) -> int:
    """UPDATE HistorianConfig.table and uns_metrics SET topic = new || rest
    WHERE topic = old OR topic LIKE old || '/%'.
    Returns rows changed on the raw table. Does not refresh CAGGs."""
```

SQL (raw table name from `HistorianConfig.table`):

```sql
UPDATE {table}
SET topic = :new_prefix || substring(topic from (char_length(:old_prefix) + 1))
WHERE topic = :old_prefix OR topic LIKE :old_prefix || '/%'
```

Same for `uns_metrics` if that table exists (try/skip if the test DB has only the raw table).

- [ ] **Step 1:** Test inserts two rows (`E/S1/a`, `E/S2/b`), rewrites `E/S1` → `E/Nord`, asserts topics and that `E/S2/b` is unchanged.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement. Reject `old_prefix == new_prefix`. Use the shared `Database` engine.
- [ ] **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat(historian): rewrite stored topics when a hierarchy prefix is renamed`

---

### Task 5: Graph prefix rewrite

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/backend/graphdb.py` (create this helper module if writes are not there yet; do not stuff Cypher into the mutation file)
- Test: `07_uns_graphql/test/backend/test_graph_rewrite.py`

**Interfaces:**
- Produces:

```python
async def rewrite_graph_prefix(old_prefix: str, new_prefix: str) -> int:
    """Rename the ISA-95 node at the last segment of old_prefix to the last
    segment of new_prefix, under the same parent path. Returns 1 if renamed, 0 if
    the old node was absent. Raises ValueError if a sibling already has the new name."""
```

Graph nodes are one segment each (`node_name`), chained by parent. Implementation: walk `old_prefix.split("/")`, find the node at the last segment, `SET n.node_name = new_segment`. Parent path of `old_prefix` must equal parent path of `new_prefix` (same-level rename only). A full enterprise rename changes the root node name.

If the existing graph driver API makes a focused integration test too expensive, a unit test that runs the Cypher against a mocked session **and** an integration mark is acceptable; the mutation test in Task 6 must still call this function with a fake.

- [ ] **Step 1:** Test: given a fake/session with `E/S1/...`, rewrite `E/S1` → `E/Nord`; sibling `E/S2` unchanged; collision `E/Nord` already present raises.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat(graphdb): rename an ISA-95 node when a hierarchy prefix changes`

---

### Task 6: GraphQL saveHierarchy and migrate job

**Files:**
- Create: `07_uns_graphql/src/uns_graphql/mutations/hierarchy.py`, `type/hierarchy.py`, `input/hierarchy.py`
- Modify: `uns_graphql_app.py` (`class Mutation`), `auth/require.py`
- Modify: `test/auth/test_require.py` (`EXPECTED` + `test_the_table_covers_exactly_the_six_mutations` → count all keys), `test/auth/test_graphql_gate.py` (`OPERATIONS`)
- Test: `07_uns_graphql/test/mutations/test_hierarchy.py`

**Interfaces:**
- Consumes: Tasks 1–5
- Produces GraphQL:

```graphql
input PrefixRenameInput { oldPrefix: String! newPrefix: String! }
input HierarchyLineInput { name: String! cells: [String!]! }
input HierarchyAreaInput { name: String! kind: String lines: [HierarchyLineInput!]! }
input HierarchySiteInput { name: String! areas: [HierarchyAreaInput!]! }
input HierarchyTreeInput { enterprise: String! sites: [HierarchySiteInput!]! }

type HierarchyMigrateJob {
  oldPrefix: String
  newPrefix: String
  status: String!   # idle | running | done | failed
  rewritten: Int
  error: String
}

type HierarchySaveResult {
  tree: HierarchyTreeType!
  job: HierarchyMigrateJob!
}

saveHierarchy(tree: HierarchyTreeInput!, renames: [PrefixRenameInput!]!): HierarchySaveResult!
retryHierarchyMigrate: HierarchyMigrateJob!
getHierarchy: HierarchyTreeType!
```

Job file: `conf/simulator/hierarchy_job.yaml` (`status`, prefixes, counts, error). If `status == running`, `saveHierarchy` with non-empty `renames` raises a GraphQL error naming the field `renames`.

Save order: validate tree + renames against previous loaded tree → write plant.yaml → write settings → reseed+prune → if renames, set job running, call historian then graph rewrite for each rename, set done/failed.

`require`: both mutations `frozenset({"admin"})`.

- [ ] **Step 1:** Extend `EXPECTED` / `OPERATIONS` first so auth tests FAIL (unknown mutation / count). Then add hierarchy mutation tests with tmp `conf_dir` and fakes for rewrite functions.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement. Register on `Mutation`. Viewer role must get `NotPermittedError`.
- [ ] **Step 4:** PASS including `test_require.py` and `test_graphql_gate.py`.
- [ ] **Step 5: Commit** `feat(graphql): save plant hierarchy to YAML and migrate prefixes`

---

### Task 7: Console GraphQL client and path helpers

**Files:**
- Modify: `11_frontend/src/lib/uns/topics.ts`
- Modify: `11_frontend/src/services/graphql/queries.ts`, `client.ts`
- Test: `11_frontend/src/lib/uns/topics.test.ts` (`vitest run src/lib/uns/topics.test.ts`) plus `npx tsc --noEmit`

**Interfaces:**
- Produces:

```typescript
export function joinSegments(...segments: string[]): string
export function splitTopic(topic: string): string[]
export function validateSegment(name: string): string
```

Client methods: `getHierarchy()`, `saveHierarchy(tree, renames)`, `retryHierarchyMigrate()`.

- [ ] **Step 1:** Add `topics.test.ts` asserting `joinSegments("E", "S") === "E/S"` and `validateSegment("A/B")` throws. FAIL because helpers are missing.
- [ ] **Step 2:** Implement helpers; replace the `CovestroAG` example in `topicDepth`’s comment with `Enterprise/Site/Area/Line/Cell/Eq`. Wire GraphQL documents and client methods.
- [ ] **Step 3:** `npx vitest run src/lib/uns/topics.test.ts` PASS; `npx tsc --noEmit` PASS.
- [ ] **Step 4: Commit** `feat(console): hierarchy GraphQL client and shared topic segment helpers`

---

### Task 8: Plant hierarchy page

**Files:**
- Create: `11_frontend/src/components/hierarchy/HierarchyView.tsx`
- Modify: `App.tsx` (`/hierarchy`), `Sidebar.tsx` (Platform menu, `Network` or `Layers` icon, `featureKey: 'settings_edit'`, `adminOnly: true`), `Header.tsx` (`getPageHeading`: `{ title: 'Plant hierarchy' }` — title only, no subtitle)
- Follow `.agents/skills/console-compact-layout/SKILL.md`

**UI contract (spec §5):**
- Left tree: enterprise → site → area → line → cell.
- Right: name field; Add child (next level only); Remove; Save.
- Local state until Save. Track `renames: {oldPrefix, newPrefix}[]` when the user commits a name change on a selected node (record the prefix before and after).
- Banner: simulator still publishes shipped WTP paths.
- Show `job.status` after save. If `failed`, a Retry button calls `retryHierarchyMigrate`.
- `AccessRestricted` when `!canAccess('settings_edit')` (same pattern as Users).

- [ ] **Step 1:** Add route + heading so `tsc` fails if the view is missing, then implement the view.
- [ ] **Step 2:** `npx tsc --noEmit` PASS.
- [ ] **Step 3: Commit** `feat(console): admin plant hierarchy editor`

---

### Task 9: Branding refresh after save

**Files:**
- Modify: wherever `platformConfig.organizationName` / `settings.organization` is set (`UNSContext` / branding). After a successful `saveHierarchy`, the sidebar org name must match `tree.enterprise` without rebuilding Vite.

If `settings.organization` is already fetched from GraphQL/health, add `enterprise` to that payload or reuse `getHierarchy`. If it is compile-time only, have `HierarchyView` on success call a context setter, and initialize that setter from `getHierarchy` on console load.

- [ ] **Step 1:** Test or manual assertion: save enterprise `Contoso` → sidebar shows `Contoso`.
- [ ] **Step 2:** Implement the smallest existing-context update.
- [ ] **Step 3: Commit** `feat(console): refresh organization name from the saved hierarchy`

---

### Task 10: ADR addendum and leftover placeholders

**Files:**
- Modify: `docs/adr/0005-graphql-mutations-for-console-configuration.md` — add an **Addendum** dated 2026-09-04: hierarchy is still YAML, but `saveHierarchy` may write it; the mutation surface is no longer alert-rules-only.
- Modify: `11_frontend/src/components/explore/ExploreView.tsx` Grafana default and validation example: use the live enterprise from context/hierarchy, not `CovestroAG`.
- Modify: `11_frontend/src/components/home/LiveMqttFeed.tsx` placeholder to `# or <enterprise>/#`.
- Do **not** change OEE YAML or Sparkplug decoder logic except the `startsWith('CovestroAG')` check in `SparkplugView.tsx` if it would hide non-Covestro names — replace with “name contains `/` and depth ≥ 3”.

- [ ] **Step 1:** Grep `11_frontend` for `CovestroAG` / `AcmeWater` in files this task listed; update those.
- [ ] **Step 2:** `npx tsc --noEmit` PASS.
- [ ] **Step 3: Commit** `docs(adr): allow GraphQL to write plant.yaml hierarchy`

---

## Spec coverage (self-review)

| Spec section | Task |
|---|---|
| YAML source of truth, GraphQL write | 2, 6 |
| plant.yaml + derived branding/mappers | 2, 6 |
| Seed from plant.yaml, prune delete | 3 |
| Add = model only | 3, 8 (no simulator files) |
| Rename migrate graph + historian | 4, 5, 6 |
| Delete keeps historian | 3, 6 (no rewrite on delete) |
| Simulator not retargeted | no task writes `wtp.yaml` devices / `WTPProcess` |
| Shared path helpers | 1, 7 |
| Admin UI | 8 |
| Branding refresh | 9 |
| Job reject / retry / no YAML rollback | 6 |
| ADR-0005 | 10 |
| No new AcmeWater/CovestroAG in touched UI | 7, 10 |

No command subscribe. No WTP physics. Eight-level topics unchanged.
