# Plant Hierarchy Add UX + Authored Machines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin create **Machines** on `#/hierarchy` via a catalog-driven **+ New** menu, persist them in `plant.yaml`, and seed them as `MACHINE` Assets so Connectivity, Condition Monitoring, historian, alerts, and OEE all read the same plant tree.

**Architecture:** `#/hierarchy` is the only structure editor. A cell becomes `{ name, machines[] }` through the model, GraphQL, and YAML. Seed creates a MACHINE branch per authored name (empty cells keep the PLC stamp). The frontend catalog lists Machine as the leaf; `insertDescendant` fills skipped parents so Save still sends a complete nest.

**Tech Stack:** Python 3.12, SQLAlchemy/Strawberry GraphQL, React 19, TypeScript 5.8, Vite 6, Tailwind 4, Lucide, Vitest 3 + Testing Library, pytest. No new dropdown package. No new container.

**Spec:** `docs/superpowers/specs/2026-09-05-plant-hierarchy-add-ux-design.md`

## Global Constraints

- **`#/hierarchy` is the platform hierarchy.** Do not add a second tree writer on Connectivity or Condition Monitoring.
- **Writes stay on** `getHierarchy` / `saveHierarchy`. No private frontend API (ADR-0005).
- **No new container or image.** Hierarchy Management is not a separate service.
- **Skip is editor-only.** A Machine under a Line still creates a default Cell. A Line under a Site still creates a default Area (`kind: production`).
- **Catalog levels:** Enterprise, Site, Area, Line, Cell, Machine. Do not add Division, Product Line, Production Unit, or Work Cell as a separate label (Cell is the Work Cell).
- **Machine is the leaf.** + New is disabled with `Machine is a leaf — nothing can be added under it.`
- **YAML read accepts string cells.** YAML write always emits `{ name, machines }`.
- **Seed:** authored `machines` on a cell replace the PLC stamp on that cell; empty/omitted machines keep today’s PLC + SCADA/HMI stamp.
- **Edits stay local until Save.** Adding a Machine does not subscribe OPC, publish MQTT, or open Condition Monitoring.
- **Icons:** Enterprise `Globe`, Site `Factory`, Area `MapPinned`, Line `GitBranch`, Cell `Cpu`, Machine `Cog`.
- **Page title and sidebar stay** Plant hierarchy. Route stays `#/hierarchy`. `settings_edit` gate is unchanged.
- **Do not copy level labels** into `HierarchyView` — read `levelDef` / `EDITOR_LEVELS`.
- **English only.** Every new behaviour gets a test. Frontend tests from `11_frontend`. Python tests from the package that owns the file.
- **No new npm dependency** for the menu. Use a button + `role="menu"` / `role="menuitem"`.

---

## File Structure

```
09_uns_model/src/uns_model/hierarchy.py          MODIFY  HierarchyCell; coerce; prefixes
09_uns_model/src/uns_model/seed.py               MODIFY  authored machines win on a cell
09_uns_model/test/test_hierarchy.py              MODIFY
09_uns_model/test/test_hierarchy_io.py           MODIFY
09_uns_model/test/test_seed.py                   MODIFY
07_uns_graphql/src/uns_graphql/type/hierarchy.py MODIFY  HierarchyCellType
07_uns_graphql/src/uns_graphql/input/hierarchy.py MODIFY HierarchyCellInput
07_uns_graphql/test/mutations/test_hierarchy.py  MODIFY
11_frontend/src/services/graphql/types.ts        MODIFY
11_frontend/src/services/graphql/queries.ts      MODIFY
11_frontend/src/components/hierarchy/
  hierarchyLevels.ts                             CREATE
  hierarchyLevels.test.ts                        CREATE
  hierarchyTree.ts                               CREATE
  hierarchyTree.test.ts                          CREATE
  AssetLevelIcon.tsx                             CREATE
  NewAssetMenu.tsx                               CREATE
  NewAssetMenu.test.tsx                          CREATE
  HierarchyView.tsx                              MODIFY
  HierarchyView.test.tsx                         MODIFY
```

Do not touch `App.tsx`, `Sidebar.tsx`, Connectivity, Condition Monitoring, or Compose.

---

### Task 1: HierarchyCell in the model

**Files:**
- Modify: `09_uns_model/src/uns_model/hierarchy.py`
- Modify: `09_uns_model/test/test_hierarchy.py`
- Modify: `09_uns_model/test/test_hierarchy_io.py`
- Modify: `09_uns_model/test/test_seed.py` — only the `HierarchyLine(..., ("V101",))` constructors that this compile break forces; seed behaviour is Task 2

**Interfaces:**
- Consumes: `validate_segment`, `join_segments`
- Produces:
  - `HierarchyCell(name: str, machines: tuple[str, ...] = ())`
  - `HierarchyLine.name` + `HierarchyLine.cells: tuple[HierarchyCell, ...]`
  - `tree_from_mapping` accepts `cells: [V101]` or `cells: [{ name, machines }]`
  - `tree_to_mapping` always writes `{ name, machines }`
  - `all_prefixes` includes `…/Cell/Machine`

- [ ] **Step 1: Write the failing tests**

Add to `09_uns_model/test/test_hierarchy.py`:

```python
from uns_model.hierarchy import (
    HierarchyArea,
    HierarchyCell,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
    PrefixRename,
    all_prefixes,
    tree_from_mapping,
    tree_to_mapping,
    validate_renames,
    validate_tree,
)


def test_string_cells_coerce_to_cells_with_no_machines():
    tree = tree_from_mapping(
        {
            "enterprise": "E",
            "sites": [
                {
                    "name": "S",
                    "areas": [
                        {
                            "name": "A",
                            "kind": "production",
                            "lines": [{"name": "L", "cells": ["V101", {"name": "P101"}]}],
                        }
                    ],
                }
            ],
        }
    )
    cells = tree.sites[0].areas[0].lines[0].cells
    assert cells == (HierarchyCell("V101"), HierarchyCell("P101"))


def test_tree_to_mapping_writes_cell_objects():
    tree = HierarchyTree(
        "E",
        (
            HierarchySite(
                "S",
                (
                    HierarchyArea(
                        "A",
                        "production",
                        (HierarchyLine("L", (HierarchyCell("V101", ("Dryer",)),)),),
                    ),
                ),
            ),
        ),
    )
    assert tree_to_mapping(tree)["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": ["Dryer"]}
    ]


def test_all_prefixes_include_machines():
    tree = HierarchyTree(
        "E",
        (
            HierarchySite(
                "S",
                (
                    HierarchyArea(
                        "A",
                        "production",
                        (HierarchyLine("L", (HierarchyCell("V101", ("Dryer",)),)),),
                    ),
                ),
            ),
        ),
    )
    assert "E/S/A/L/V101/Dryer" in all_prefixes(tree)


def test_duplicate_sibling_machines_are_rejected():
    tree = HierarchyTree(
        "E",
        (
            HierarchySite(
                "S",
                (
                    HierarchyArea(
                        "A",
                        "production",
                        (HierarchyLine("L", (HierarchyCell("V101", ("Dryer", "Dryer")),)),),
                    ),
                ),
            ),
        ),
    )
    try:
        validate_tree(tree)
    except ValueError as exc:
        assert "Dryer" in str(exc)
        return
    raise AssertionError("expected ValueError")
```

Update `test_duplicate_sibling_cells_are_rejected` to use `HierarchyCell("V101")` twice.

In `09_uns_model/test/test_hierarchy_io.py`, change the assertion that today’s write emits `["V101", "V102"]` to expect objects:

```python
assert doc["sites"][0]["areas"][0]["lines"][0]["cells"] == [
    {"name": "V101", "machines": []},
    {"name": "V102", "machines": []},
]
```

Keep the string-shaped `MINIMAL_PLANT_YAML` fixture — load must still accept it.

In `09_uns_model/test/test_seed.py`, replace every `HierarchyLine("L", ("V101",))` (and the two-cell / two-area variants) with `HierarchyCell` tuples so the file imports.

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest 09_uns_model/test/test_hierarchy.py 09_uns_model/test/test_hierarchy_io.py -q
```

Expected: FAIL — `HierarchyCell` is not defined, or `cells` is still `tuple[str, ...]`.

- [ ] **Step 3: Write minimal implementation**

In `09_uns_model/src/uns_model/hierarchy.py`:

1. Change the module docstring first sentence to `Enterprise > Site > Area > Line > Cell > Machine`.

2. Add and replace the line/cell types:

```python
@dataclass(frozen=True, slots=True)
class HierarchyCell:
    name: str
    machines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HierarchyLine:
    name: str
    cells: tuple[HierarchyCell, ...]
```

3. Add coerce helpers and use them from `_coerce_lines`:

```python
def _coerce_cell(raw: object) -> HierarchyCell:
    if isinstance(raw, str):
        return HierarchyCell(name=raw)
    if isinstance(raw, HierarchyCell):
        return raw
    if isinstance(raw, Mapping):
        machines = raw.get("machines", ())
        return HierarchyCell(name=str(raw["name"]), machines=tuple(str(m) for m in machines))
    return HierarchyCell(
        name=str(getattr(raw, "name")),
        machines=tuple(str(m) for m in getattr(raw, "machines", ())),
    )


def _coerce_cells(raw: object) -> tuple[HierarchyCell, ...]:
    if raw is None:
        return ()
    return tuple(_coerce_cell(item) for item in raw)
```

In `_coerce_lines`, replace the `cells = tuple(body.get("cells", ()))` line with `cells = _coerce_cells(...)`.

4. `tree_to_mapping` line objects:

```python
"cells": [
    {"name": cell.name, "machines": list(cell.machines)}
    for cell in line.cells
]
```

5. `validate_tree` — unique cell names stay; add unique machines per cell:

```python
for line in area.lines:
    _require_unique(
        [cell.name for cell in line.cells],
        "cell",
        f"{tree.enterprise}/{site.name}/{area.name}/{line.name}",
    )
    for cell in line.cells:
        _require_unique(
            cell.machines,
            "machine",
            f"{tree.enterprise}/{site.name}/{area.name}/{line.name}/{cell.name}",
        )
```

6. `all_prefixes` — walk `cell.name` and each machine:

```python
for cell in line.cells:
    cell_prefix = _cell_prefix(tree.enterprise, site.name, area.name, line.name, cell.name)
    prefixes.add(cell_prefix)
    for machine in cell.machines:
        prefixes.add(join_segments(cell_prefix, machine))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest 09_uns_model/test/test_hierarchy.py 09_uns_model/test/test_hierarchy_io.py 09_uns_model/test/test_seed.py -q
```

Expected: hierarchy and hierarchy_io PASS. Seed tests PASS if constructors were updated and `tree_to_mapping` still feeds `plan_from_simulator_config` (string or object cells both work via `_named`). If a seed test still asserts `cells == ["V101"]` on a mapping, update that assertion to the object shape.

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/hierarchy.py 09_uns_model/test/test_hierarchy.py 09_uns_model/test/test_hierarchy_io.py 09_uns_model/test/test_seed.py
git commit -m "feat(hierarchy): persist machines under each work cell."
```

---

### Task 2: Seed authored machines

**Files:**
- Modify: `09_uns_model/src/uns_model/seed.py`
- Modify: `09_uns_model/test/test_seed.py`

**Interfaces:**
- Consumes: `tree_to_mapping` (cells are objects), `_named`, `_machines`
- Produces: `plan_from_simulator_config` / `plan_from_hierarchy_tree` create `…/Cell/Dryer` when the cell lists `machines: [Dryer]`, and do not stamp PLC equipment on that cell

- [ ] **Step 1: Write the failing test**

Add to `09_uns_model/test/test_seed.py`:

```python
def test_authored_machines_replace_the_plc_stamp_on_that_cell():
    tree = HierarchyTree(
        "E",
        (
            HierarchySite(
                "S",
                (
                    HierarchyArea(
                        "A",
                        "production",
                        (
                            HierarchyLine(
                                "L",
                                (
                                    HierarchyCell("V101", ("Dryer",)),
                                    HierarchyCell("P101"),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    extra = {"plc": [{"equipment": "G1", "sensors": {"Temperature": {"unit": "°C"}}}]}
    plan = plan_from_hierarchy_tree(tree, extra)
    paths = plan.asset_paths
    assert "E/S/A/L/V101/Dryer" in paths
    assert "E/S/A/L/V101/G1" not in paths
    assert "E/S/A/L/P101/G1" in paths
    assert "E/S/A/L/V101/SCADA" in paths
    assert "E/S/A/L/V101/HMI" in paths
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest 09_uns_model/test/test_seed.py::test_authored_machines_replace_the_plc_stamp_on_that_cell -q
```

Expected: FAIL — `E/S/A/L/V101/G1` is still present and/or Dryer is missing.

- [ ] **Step 3: Write minimal implementation**

In `seed.py`, change `_cells` to also yield authored machines, or add a sibling helper. Keep `_cells` for callers that only need the five-tuple. Add:

```python
def _cell_entries(
    hierarchy: Mapping[str, Any],
) -> list[tuple[str, str, str, str, str, tuple[str, ...]]]:
    """One row per Work Cell: path segments plus authored machine names."""
    rows: list[tuple[str, str, str, str, str, tuple[str, ...]]] = []
    for site in hierarchy.get("sites") or []:
        site_name = _named(site)
        for area in _as_mapping(site).get("areas") or []:
            area_name = _named(area)
            for line in _as_mapping(area).get("lines") or []:
                line_name = _named(line)
                for cell in _as_mapping(line).get("cells") or []:
                    authored: tuple[str, ...] = ()
                    if isinstance(cell, Mapping):
                        authored = tuple(str(m) for m in (cell.get("machines") or ()))
                    rows.append(
                        (
                            str(hierarchy["enterprise"]),
                            site_name,
                            area_name,
                            line_name,
                            _named(cell),
                            authored,
                        )
                    )
    if not rows:
        # Preserve the existing flat-shape and empty-sites errors via _cells.
        return [(*segments, ()) for segments in _cells(hierarchy)]
    return rows
```

In `plan_from_simulator_config`, replace `for segments in _cells(...)` with `for *segments, authored in _cell_entries(...)`. Then:

```python
        cell_machines = list(authored) if authored else list(machines)
        if segments[1] not in sites_seen:
            sites_seen.add(segments[1])
            cell_machines.append(SITE_MACHINE)
        if segments[1:4] not in lines_seen:
            lines_seen.add(segments[1:4])
            cell_machines.append(LINE_MACHINE)
```

`_cells` can be implemented as `[row[:5] for row in _cell_entries(...)]` if that avoids duplicating the walk — only if the flat-shape error paths stay identical. If flattening `_cells` risks the legacy `site/area/line/cell` shape, keep `_cells` as it is and call it from `_cell_entries` when `sites` is missing.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest 09_uns_model/test/test_seed.py -q
```

Expected: PASS, including `test_each_machine_is_created_under_every_work_cell` (string cells, PLC stamp unchanged).

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/seed.py 09_uns_model/test/test_seed.py
git commit -m "feat(model): seed authored machines from the plant hierarchy."
```

---

### Task 3: GraphQL cell objects

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/type/hierarchy.py`
- Modify: `07_uns_graphql/src/uns_graphql/input/hierarchy.py`
- Modify: `07_uns_graphql/test/mutations/test_hierarchy.py`

**Interfaces:**
- Consumes: `HierarchyCell`, `HierarchyLine`
- Produces:
  - `HierarchyCellType { name, machines }`
  - `HierarchyLineType.cells: list[HierarchyCellType]`
  - `HierarchyCellInput { name, machines }`
  - `HierarchyLineInput.cells: list[HierarchyCellInput]`
  - `HierarchyTreeInput.to_tree()` builds `HierarchyCell`

- [ ] **Step 1: Write the failing tests**

In `07_uns_graphql/test/mutations/test_hierarchy.py` replace the query fragments and the Python tree dicts.

```python
GET_HIERARCHY = """
    { getHierarchy { enterprise sites { name areas { name kind lines { name cells { name machines } } } } } }
"""

SAVE_HIERARCHY = """
    mutation Save($tree: HierarchyTreeInput!, $renames: [PrefixRenameInput!]!) {
        saveHierarchy(tree: $tree, renames: $renames) {
            tree { enterprise sites { name areas { name kind lines { name cells { name machines } } } } }
            job { oldPrefix newPrefix status rewritten error }
        }
    }
"""

def _cells(*names: str) -> list[dict]:
    return [{"name": name, "machines": []} for name in names]


TREE_SITE1 = {
    "enterprise": "OldCo",
    "sites": [
        {
            "name": "Site1",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "cells": _cells("V101", "V102")}],
                }
            ],
        }
    ],
}
```

Apply the same `_cells(...)` shape to `TREE_NORD`, `TREE_TWO_RENAMED`, and every other mutation variable in this file.

Update existing assertions that still compare `cells` to strings:

- `test_get_hierarchy_reads_plant_yaml`: expect
  `[{"name": "V101", "machines": []}, {"name": "V102", "machines": []}]`
  (string YAML still loads).
- `test_save_hierarchy_writes_yaml_and_reseeds_without_migrate`: `added` uses `_cells("V101", "V102", "V103")`; GraphQL result and `_read_plant` both expect objects with empty `machines`.

Add:

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_save_hierarchy_persists_authored_machines(conf_dir: Path):
    tree = {
        "enterprise": "OldCo",
        "sites": [
            {
                "name": "Site1",
                "areas": [
                    {
                        "name": "RawWater",
                        "kind": "production",
                        "lines": [
                            {
                                "name": "Train1",
                                "cells": [{"name": "V101", "machines": ["Dryer"]}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock),
        patch(REWRITE_GRAPH, new_callable=AsyncMock),
        patch(RESEED, new_callable=AsyncMock) as reseed,
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": tree, "renames": []},
            context_value=ADMIN,
        )

    assert result.errors is None
    cells = result.data["saveHierarchy"]["tree"]["sites"][0]["areas"][0]["lines"][0]["cells"]
    assert cells == [{"name": "V101", "machines": ["Dryer"]}]
    assert _read_plant(conf_dir)["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": ["Dryer"]}
    ]
    reseed.assert_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest 07_uns_graphql/test/mutations/test_hierarchy.py -q
```

Expected: FAIL — schema still has `cells: [String!]`, or input rejects objects.

- [ ] **Step 3: Write minimal implementation**

`07_uns_graphql/src/uns_graphql/type/hierarchy.py`:

```python
@strawberry.type(description="A work cell (instance tag) and the machines under it.")
class HierarchyCellType:
    name: str
    machines: list[str]

    @classmethod
    def from_cell(cls, cell: HierarchyCell) -> "HierarchyCellType":
        return cls(name=cell.name, machines=list(cell.machines))


@strawberry.type(description="A line and the cells (instance tags) under it.")
class HierarchyLineType:
    name: str
    cells: list[HierarchyCellType]

    @classmethod
    def from_line(cls, line: HierarchyLine) -> HierarchyLineType:
        return cls(name=line.name, cells=[HierarchyCellType.from_cell(cell) for cell in line.cells])
```

Import `HierarchyCell`.

`07_uns_graphql/src/uns_graphql/input/hierarchy.py`:

```python
@strawberry.input(description="A work cell and the machines under it.")
class HierarchyCellInput:
    name: str
    machines: list[str] | None = None

    def to_cell(self) -> HierarchyCell:
        return HierarchyCell(name=self.name, machines=tuple(self.machines or ()))


@strawberry.input(description="A line and the cells (instance tags) under it.")
class HierarchyLineInput:
    name: str
    cells: list[HierarchyCellInput]
```

In `to_tree()`, replace `cells=tuple(line.cells)` with `cells=tuple(cell.to_cell() for cell in line.cells)`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest 07_uns_graphql/test/mutations/test_hierarchy.py 09_uns_model/test/test_hierarchy.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/type/hierarchy.py 07_uns_graphql/src/uns_graphql/input/hierarchy.py 07_uns_graphql/test/mutations/test_hierarchy.py
git commit -m "feat(graphql): expose hierarchy cells as name plus machines."
```

---

### Task 4: Frontend hierarchy types

**Files:**
- Modify: `11_frontend/src/services/graphql/types.ts`
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/components/hierarchy/HierarchyView.tsx`
- Modify: `11_frontend/src/components/hierarchy/HierarchyView.test.tsx`

**Interfaces:**
- Consumes: GraphQL `HierarchyCellType`
- Produces: `GraphqlHierarchyCell { name: string; machines: string[] }`; view clones, names, validates, adds, and removes cell objects; still Cell-leaf **Add child** until Task 8

- [ ] **Step 1: Write the failing tests**

In `HierarchyView.test.tsx` change `TREE` to:

```ts
const TREE = {
  enterprise: 'AcmeWater',
  sites: [
    {
      name: 'Site1',
      areas: [
        {
          name: 'RawWater',
          kind: 'production',
          lines: [{ name: 'Train1', cells: [{ name: 'V101', machines: [] }] }],
        },
      ],
    },
  ],
};
```

Add:

```ts
  it('adds a Cell object under a Line', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Line Train1' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Line Train1' }));
    fireEvent.click(screen.getByRole('button', { name: /add child|add cell/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell Cell' })).toBeTruthy());
  });
```

If the current button name is `Add child`, keep that matcher until Task 8.

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm run test:run -- src/components/hierarchy/HierarchyView.test.tsx
```

Working directory: `11_frontend`.

Expected: FAIL — `cells` treated as strings, or name render is `[object Object]`.

- [ ] **Step 3: Write minimal implementation**

`types.ts`:

```ts
export type GraphqlHierarchyCell = {
  name: string
  machines: string[]
}

export type GraphqlHierarchyLine = {
  name: string
  cells: GraphqlHierarchyCell[]
}

export type GraphqlHierarchyLineInput = {
  name: string
  cells: GraphqlHierarchyCell[]
}
```

`queries.ts` — both `GET_HIERARCHY_QUERY` and `SAVE_HIERARCHY_MUTATION` replace `cells` with:

```
cells { name machines }
```

`HierarchyView.tsx` — keep local `NodeLevel` / helpers in this task. Change:

- `cloneTree`: `cells: line.cells.map((cell) => ({ name: cell.name, machines: [...cell.machines] }))`
- `nodeName` / `applyName` cell branch: `.name`
- `nodePrefix` cell: `cell.name`
- `siblingNames` cell: `cells.filter(...).map((c) => c.name)`
- `addChild` line branch: `uniqueChildName(cells.map((c) => c.name), base)` then `cells.push({ name, machines: [] })`
- `validateEditableTree`: validate `cell.name`; nested unique `cell.machines`
- `treeCounts`: add `machines` count (`cell.machines.length`); show a Machines `PageStat` next to Cells
- Tree render: `key` and label use `cell.name`; nest machine rows only in Task 8 (not yet)

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm run test:run -- src/components/hierarchy/HierarchyView.test.tsx
```

Expected: PASS. Existing rename / save tests still find `Cell V101`.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/services/graphql/types.ts 11_frontend/src/services/graphql/queries.ts 11_frontend/src/components/hierarchy/HierarchyView.tsx 11_frontend/src/components/hierarchy/HierarchyView.test.tsx
git commit -m "feat(hierarchy): load and save cells as name plus machines."
```

---

### Task 5: Level catalog including Machine

**Files:**
- Create: `11_frontend/src/components/hierarchy/hierarchyLevels.ts`
- Test: `11_frontend/src/components/hierarchy/hierarchyLevels.test.ts`

**Interfaces:**
- Produces:
  - `NodeLevel` = `'enterprise' | 'site' | 'area' | 'line' | 'cell' | 'machine'`
  - `LevelDef` = `{ id: NodeLevel; label: string; defaultName: string | null; icon: LucideIcon }`
  - `EDITOR_LEVELS`, `LEAF_TITLE`, `levelDef`, `remainingChildren`, `addDescription`

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/hierarchy/hierarchyLevels.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  EDITOR_LEVELS,
  LEAF_TITLE,
  addDescription,
  levelDef,
  remainingChildren,
} from './hierarchyLevels';

describe('remainingChildren', () => {
  it('lists every editor level below Area', () => {
    expect(remainingChildren('area')).toEqual(['line', 'cell', 'machine']);
  });

  it('lists Site through Machine under Enterprise', () => {
    expect(remainingChildren('enterprise')).toEqual([
      'site',
      'area',
      'line',
      'cell',
      'machine',
    ]);
  });

  it('lists Machine under Cell', () => {
    expect(remainingChildren('cell')).toEqual(['machine']);
  });

  it('lists nothing under Machine', () => {
    expect(remainingChildren('machine')).toEqual([]);
  });
});

describe('addDescription', () => {
  it('describes an adjacent Area under a Site', () => {
    expect(addDescription('site', 'area')).toBe(
      'Area — a production area within this site.',
    );
  });

  it('describes a skipped Line under a Site', () => {
    expect(addDescription('site', 'line')).toBe(
      'Line — a production line (an Area will be created to hold it).',
    );
  });

  it('describes a Machine under a Cell', () => {
    expect(addDescription('cell', 'machine')).toBe(
      'Machine — equipment under this cell. After Save it is a MACHINE Asset the rest of the platform can attach tags to.',
    );
  });

  it('describes a skipped Machine under a Line', () => {
    expect(addDescription('line', 'machine')).toBe(
      'Machine — equipment (a Cell will be created to hold it).',
    );
  });
});

describe('catalog', () => {
  it('names the six editor levels and the leaf title', () => {
    expect(EDITOR_LEVELS.map((l) => l.id)).toEqual([
      'enterprise',
      'site',
      'area',
      'line',
      'cell',
      'machine',
    ]);
    expect(levelDef('machine').label).toBe('Machine');
    expect(levelDef('machine').defaultName).toBe('Machine');
    expect(LEAF_TITLE).toBe('Machine is a leaf — nothing can be added under it.');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm run test:run -- src/components/hierarchy/hierarchyLevels.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `11_frontend/src/components/hierarchy/hierarchyLevels.ts`:

```ts
import { Cog, Cpu, Factory, GitBranch, Globe, MapPinned, type LucideIcon } from 'lucide-react';

export type NodeLevel = 'enterprise' | 'site' | 'area' | 'line' | 'cell' | 'machine';

export type LevelDef = {
  id: NodeLevel;
  label: string;
  defaultName: string | null;
  icon: LucideIcon;
};

export const EDITOR_LEVELS: LevelDef[] = [
  { id: 'enterprise', label: 'Enterprise', defaultName: null, icon: Globe },
  { id: 'site', label: 'Site', defaultName: 'Site', icon: Factory },
  { id: 'area', label: 'Area', defaultName: 'Area', icon: MapPinned },
  { id: 'line', label: 'Line', defaultName: 'Line', icon: GitBranch },
  { id: 'cell', label: 'Cell', defaultName: 'Cell', icon: Cpu },
  { id: 'machine', label: 'Machine', defaultName: 'Machine', icon: Cog },
];

export const LEAF_TITLE = 'Machine is a leaf — nothing can be added under it.';

const ORDER: NodeLevel[] = EDITOR_LEVELS.map((row) => row.id);

export function levelDef(id: NodeLevel): LevelDef {
  const found = EDITOR_LEVELS.find((row) => row.id === id);
  if (!found) {
    throw new Error(`Unknown editor level: ${id}`);
  }
  return found;
}

export function remainingChildren(parent: NodeLevel): NodeLevel[] {
  return ORDER.slice(ORDER.indexOf(parent) + 1);
}

const DESCRIPTIONS: Record<string, string> = {
  'enterprise:site': 'Site — a physical plant or facility under this enterprise.',
  'enterprise:area': 'Area — a production area (a Site will be created to hold it).',
  'enterprise:line': 'Line — a production line (a Site and Area will be created to hold it).',
  'enterprise:cell': 'Cell — an instance tag (a Site, Area, and Line will be created to hold it).',
  'enterprise:machine':
    'Machine — equipment (a Site, Area, Line, and Cell will be created to hold it).',
  'site:area': 'Area — a production area within this site.',
  'site:line': 'Line — a production line (an Area will be created to hold it).',
  'site:cell': 'Cell — an instance tag (an Area and Line will be created to hold it).',
  'site:machine': 'Machine — equipment (an Area, Line, and Cell will be created to hold it).',
  'area:line': 'Line — a production line under this area.',
  'area:cell': 'Cell — an instance tag (a Line will be created to hold it).',
  'area:machine': 'Machine — equipment (a Line and Cell will be created to hold it).',
  'line:cell': 'Cell — an instance tag under this line.',
  'line:machine': 'Machine — equipment (a Cell will be created to hold it).',
  'cell:machine':
    'Machine — equipment under this cell. After Save it is a MACHINE Asset the rest of the platform can attach tags to.',
};

export function addDescription(parent: NodeLevel, target: NodeLevel): string {
  return DESCRIPTIONS[`${parent}:${target}`] ?? '';
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run test:run -- src/components/hierarchy/hierarchyLevels.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/hierarchy/hierarchyLevels.ts 11_frontend/src/components/hierarchy/hierarchyLevels.test.ts
git commit -m "feat(hierarchy): add Machine to the editor level catalog."
```

---

### Task 6: insertDescendant including Machine

**Files:**
- Create: `11_frontend/src/components/hierarchy/hierarchyTree.ts`
- Test: `11_frontend/src/components/hierarchy/hierarchyTree.test.ts`
- Modify: `11_frontend/src/components/hierarchy/HierarchyView.tsx` — delete local `NodeLevel`, `NodeRef`, `CHILD_LEVEL`, `CHILD_BASE_NAME`, `LEVEL_LABEL`, `cloneTree`, `uniqueChildName`, `addChild`; import from the new modules. **Add child** still calls `addChild`.

**Interfaces:**
- Produces: `NodeRef` with `machine`; `cloneTree`; `addChild` (Cell → Machine); `insertDescendant`

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/components/hierarchy/hierarchyTree.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { GraphqlHierarchyTree } from '../../services/graphql/types';
import { insertDescendant } from './hierarchyTree';

const TREE: GraphqlHierarchyTree = {
  enterprise: 'AcmeWater',
  sites: [
    {
      name: 'Site1',
      areas: [
        {
          name: 'RawWater',
          kind: 'production',
          lines: [{ name: 'Train1', cells: [{ name: 'V101', machines: [] }] }],
        },
      ],
    },
  ],
};

describe('insertDescendant', () => {
  it('creates a default Area and Line under a Site and returns the Line', () => {
    const result = insertDescendant(TREE, { level: 'site', site: 0 }, 'line');
    expect(result).not.toBeNull();
    expect(result?.child).toEqual({ level: 'line', site: 0, area: 1, line: 0 });
    expect(result?.tree.sites[0].areas[1]).toEqual({
      name: 'Area',
      kind: 'production',
      lines: [{ name: 'Line', cells: [] }],
    });
  });

  it('creates a default Cell and Machine under a Line and returns the Machine', () => {
    const result = insertDescendant(
      TREE,
      { level: 'line', site: 0, area: 0, line: 0 },
      'machine',
    );
    expect(result?.child).toEqual({
      level: 'machine',
      site: 0,
      area: 0,
      line: 0,
      cell: 1,
      machine: 0,
    });
    expect(result?.tree.sites[0].areas[0].lines[0].cells[1]).toEqual({
      name: 'Cell',
      machines: ['Machine'],
    });
    expect(result?.tree.sites[0].areas[0].lines[0].cells[0].name).toBe('V101');
  });

  it('adds only a Machine under a Cell', () => {
    const result = insertDescendant(
      TREE,
      { level: 'cell', site: 0, area: 0, line: 0, cell: 0 },
      'machine',
    );
    expect(result?.tree.sites[0].areas[0].lines[0].cells[0].machines).toEqual(['Machine']);
    expect(result?.child).toEqual({
      level: 'machine',
      site: 0,
      area: 0,
      line: 0,
      cell: 0,
      machine: 0,
    });
  });

  it('returns null when the parent is a Machine', () => {
    expect(
      insertDescendant(
        TREE,
        { level: 'machine', site: 0, area: 0, line: 0, cell: 0, machine: 0 },
        'cell',
      ),
    ).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm run test:run -- src/components/hierarchy/hierarchyTree.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `hierarchyTree.ts` with `NodeRef` including machine, `cloneTree` from Task 4, `uniqueChildName`, `addChild`, and `insertDescendant`.

`addChild` cell branch:

```ts
    case 'cell': {
      const machines =
        next.sites[ref.site].areas[ref.area].lines[ref.line].cells[ref.cell].machines;
      const name = uniqueChildName(machines, levelDef('machine').defaultName ?? 'Machine');
      machines.push(name);
      return {
        tree: next,
        child: {
          level: 'machine',
          site: ref.site,
          area: ref.area,
          line: ref.line,
          cell: ref.cell,
          machine: machines.length - 1,
        },
      };
    }
    case 'machine':
      return null;
```

`insertDescendant` is the same loop as the previous plan: walk `addChild` until `currentRef.level === target`.

Then edit `HierarchyView.tsx`: import `NodeLevel`, `levelDef`, `remainingChildren` from `./hierarchyLevels`; import `NodeRef`, `cloneTree`, `addChild` from `./hierarchyTree`; delete the local copies. Replace `LEVEL_LABEL[x]` with `levelDef(x).label`. Extend `nodeName`, `nodePrefix`, `applyName`, `siblingNames`, `parentRef`, `removeNode`, `sameRef`, and `validateEditableTree` for `level === 'machine'`. Do **not** switch the button to + New yet.

```ts
const childLevel = selected ? remainingChildren(selected.level)[0] ?? null : null;
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm run test:run -- src/components/hierarchy/hierarchyTree.test.ts src/components/hierarchy/HierarchyView.test.tsx
```

Expected: PASS. Existing Add child from Enterprise still creates `Site Site`.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/hierarchy/hierarchyTree.ts 11_frontend/src/components/hierarchy/hierarchyTree.test.ts 11_frontend/src/components/hierarchy/HierarchyView.tsx
git commit -m "feat(hierarchy): insert skipped levels including Machine."
```

---

### Task 7: NewAssetMenu and AssetLevelIcon

**Files:**
- Create: `11_frontend/src/components/hierarchy/AssetLevelIcon.tsx`
- Create: `11_frontend/src/components/hierarchy/NewAssetMenu.tsx`
- Test: `11_frontend/src/components/hierarchy/NewAssetMenu.test.tsx`

**Interfaces:**
- Produces: `AssetLevelIcon({ level })`, `NewAssetMenu({ parentLevel, onPick })`

- [ ] **Step 1: Write the failing test**

```ts
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NewAssetMenu } from './NewAssetMenu';

describe('NewAssetMenu', () => {
  it('lists Line, Cell, and Machine under an Area', () => {
    const onPick = vi.fn();
    render(<NewAssetMenu parentLevel="area" onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    expect(screen.getByRole('menuitem', { name: /^Line/ })).toHaveTextContent(
      'Line — a production line under this area.',
    );
    expect(screen.getByRole('menuitem', { name: /^Machine/ })).toBeTruthy();
    expect(screen.queryByRole('menuitem', { name: /^Site/ })).toBeNull();
  });

  it('calls onPick with machine when Machine is chosen', () => {
    const onPick = vi.fn();
    render(<NewAssetMenu parentLevel="cell" onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    expect(onPick).toHaveBeenCalledWith('machine');
  });

  it('disables New under a Machine', () => {
    render(<NewAssetMenu parentLevel="machine" onPick={vi.fn()} />);
    const button = screen.getByRole('button', { name: 'New' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      'title',
      'Machine is a leaf — nothing can be added under it.',
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm run test:run -- src/components/hierarchy/NewAssetMenu.test.tsx
```

Expected: FAIL — `NewAssetMenu` is not found.

- [ ] **Step 3: Write minimal implementation**

`AssetLevelIcon.tsx` and `NewAssetMenu.tsx` match the previous plan’s components (button + `role="menu"`). They already read `remainingChildren` / `LEAF_TITLE` / `addDescription`, so Machine appears with no extra branching.

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run test:run -- src/components/hierarchy/NewAssetMenu.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/hierarchy/AssetLevelIcon.tsx 11_frontend/src/components/hierarchy/NewAssetMenu.tsx 11_frontend/src/components/hierarchy/NewAssetMenu.test.tsx
git commit -m "feat(hierarchy): add + New menu of remaining editor levels."
```

---

### Task 8: Wire HierarchyView (icons, + New, Machine rows)

**Files:**
- Modify: `11_frontend/src/components/hierarchy/HierarchyView.tsx`
- Modify: `11_frontend/src/components/hierarchy/HierarchyView.test.tsx`

**Interfaces:**
- Consumes: `NewAssetMenu`, `AssetLevelIcon`, `insertDescendant`, `levelDef`
- Produces: spec §§6–9, including Machine rows under each Cell

- [ ] **Step 1: Write the failing tests**

Delete `'adds only the next legal child level'` and the Task 4 Add-child test if it targets the old button. Add:

```ts
  it('offers Line, Cell, and Machine under an Area from both New menus', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Area RawWater' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Area RawWater' }));
    const news = screen.getAllByRole('button', { name: 'New' });
    expect(news).toHaveLength(2);
    fireEvent.click(news[0]);
    expect(screen.getByRole('menuitem', { name: /^Machine/ })).toBeTruthy();
    expect(screen.getByRole('menuitem', { name: /^Line/ })).toBeTruthy();
  });

  it('creates a Cell and Machine under a Line and selects the Machine', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Line Train1' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Line Train1' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Machine Machine' })).toBeTruthy());
    expect(screen.getByRole('button', { name: 'Cell Cell' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Machine Machine' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(screen.getByLabelText('Name')).toHaveValue('Machine');
  });

  it('disables New after adding a Machine under a Cell', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Machine Machine' })).toBeTruthy());
    for (const button of screen.getAllByRole('button', { name: 'New' })) {
      expect(button).toBeDisabled();
    }
  });

  it('saves an authored machine on the cell', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(saveHierarchy).toHaveBeenCalledTimes(1));
    expect(saveHierarchy).toHaveBeenCalledWith(
      expect.objectContaining({
        sites: [
          expect.objectContaining({
            areas: [
              expect.objectContaining({
                lines: [
                  expect.objectContaining({
                    cells: [
                      expect.objectContaining({
                        name: 'V101',
                        machines: ['Machine'],
                      }),
                    ],
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
      [],
    );
  });

  it('shows the Machine type word on a Machine row, not M', async () => {
    getHierarchy.mockResolvedValue({
      ...TREE,
      sites: [
        {
          name: 'Site1',
          areas: [
            {
              name: 'RawWater',
              kind: 'production',
              lines: [{ name: 'Train1', cells: [{ name: 'V101', machines: ['Dryer'] }] }],
            },
          ],
        },
      ],
    });
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Machine Dryer' })).toBeTruthy());
    const row = screen.getByRole('button', { name: 'Machine Dryer' });
    expect(row).toHaveTextContent('Machine');
    expect(row).toHaveTextContent('Dryer');
    expect(row.textContent).not.toMatch(/^\s*M\s/);
  });
```

Keep access, load, rename, branding, and migrate tests. `aria-label`s stay `Enterprise AcmeWater`, `Site Site1`, `Cell V101`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm run test:run -- src/components/hierarchy/HierarchyView.test.tsx
```

Expected: FAIL — no `New` buttons, or Machine rows not rendered.

- [ ] **Step 3: Wire the view**

1. `handleAdd` calls `insertDescendant` (same body as the previous plan).
2. Tree rows: `AssetLevelIcon` + type label + name. `aria-label={`${levelDef(nodeRef.level).label} ${name}`}`.
3. Under each Cell, map `cell.machines` to `TreeNodeButton` with `level: 'machine'`.
4. Replace both **Add child** controls with `NewAssetMenu`.
5. `PageStat` Machines uses the count from `treeCounts`.
6. Do not change Save, migrate, load, or the `settings_edit` gate.

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm run test:run -- src/components/hierarchy
```

Expected: PASS — catalog, tree, menu, and HierarchyView.

Also:

```bash
pytest 09_uns_model/test/test_hierarchy.py 09_uns_model/test/test_seed.py 07_uns_graphql/test/mutations/test_hierarchy.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/hierarchy/HierarchyView.tsx 11_frontend/src/components/hierarchy/HierarchyView.test.tsx
git commit -m "feat(hierarchy): create machines from + New and show them on the plant tree."
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|---|---|
| String cells still load | 1 |
| YAML / GraphQL `{ name, machines }` | 1, 3, 4 |
| Authored machines seed MACHINE Assets | 2 |
| Empty cell keeps PLC stamp | 2 |
| Prefixes include machines | 1 |
| + New in tree header and detail pane | 7, 8 |
| Remaining levels + Machine descriptions | 5, 7 |
| Skip insert with default parents | 6, 8 |
| Machine leaf disabled + `LEAF_TITLE` | 5, 7, 8 |
| Icon + type name; Cog for Machine | 5, 7, 8 |
| Save payload includes machines | 8 |
| `settings_edit` unchanged | 8 (existing test) |
| No Connectivity / CM tree chrome | Global constraints |
| Platform reach = Asset Model after Save | 2, 3 |

No TBD/TODO. `HierarchyCell` / `NodeLevel` / `insertDescendant` / `NewAssetMenu` names are the same in every task.
