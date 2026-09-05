# Plant hierarchy add UX (typed + New menu)

Date: 2026-09-05
Modules: `11_frontend` (`components/hierarchy` only). No GraphQL, YAML, or container changes.
Status: Approved
Extends: [2026-09-04 admin plant hierarchy](./2026-09-04-admin-hierarchy-yaml-design.md)

The Plant hierarchy page at `#/hierarchy` stays the editor for the Asset Model. This spec
changes how an admin **adds** a node and how the tree **shows** each Asset Level. It does
not change what Save writes.

## 1. Problem

`+ Add child` creates the next ISA-95 level and does not say which. The tree marks rows
with the first letter of Site / Area / Line / Cell (`A`, `L`, `c`). An admin cannot tell
whether they are adding a Line, a Cell, or something the model does not store (Division,
Machine).

Save already writes the shared Asset Model through GraphQL. Connectivity and Condition
Monitoring do not own the tree. The confusion is the add control and the row chrome, not
the persistence path.

## 2. Goals

- An admin with `settings_edit` can open **+ New** in the **tree header** and on the
  **selected node**, and see every remaining editor level below that node, each with an
  icon, label, and one-line description.
- Picking a non-adjacent level (Line under Site) creates the missing parents in the same
  action, so `saveHierarchy` still receives a complete nested tree.
- Each tree row shows that level’s Lucide icon and the type name next to the node name
  (for example `Line · Train1`).
- One catalog drives both menus and the tree, so a later level (Machine, Division) is a
  catalog row plus Save support — not a second menu implementation.
- Edits stay local until **Save**. After Save, the new structure is in the Asset Model
  for the whole platform. Nothing publishes, subscribes, or draws a card until a later
  commissioning step.

## 3. Non-goals

- No new container or image. Hierarchy Management is not a separate service.
- No private frontend API. Writes stay on `getHierarchy` / `saveHierarchy` (ADR-0005).
- No change to `plant.yaml` shape or GraphQL `HierarchyTreeInput`.
- No true skipped levels on disk (a Line with no Area Asset). That needs a flat Asset
  list and is a later spec.
- No Machine, Work Cell, Production Unit, or Division in this catalog. Cell remains the
  editor leaf (instance tag).
- The tree is not shared chrome on Condition Monitoring or Connectivity in this slice.
- No import/export, tree search, or empty-state illustration.
- No MQTT, OPC, Condition Monitoring, or Grafana wiring when a node is added.

## 4. Architecture

```
Browser (#/hierarchy)
    → uns_frontend (HierarchyView + catalog + NewAssetMenu + AssetLevelIcon)
    → graphql_server  getHierarchy / saveHierarchy
        → plant.yaml + Postgres Asset Model
```

`asset_model_setup` still seeds at stack start. After Save, GraphQL reseeds in-process
as today. Other console pages and services **read** Assets; they do not write this tree.

`saveHierarchy` still requires every Line to sit under an Area under a Site. The menu
may offer a skipped **editor** level; the insert path fills the chain with default-named
parents so the in-memory tree stays a complete nest.

## 5. Level catalog

One module beside the hierarchy view, for example
`11_frontend/src/components/hierarchy/hierarchyLevels.ts`. Ordered list of editor levels.
Both menus and the tree read it. Do not copy labels into `HierarchyView`.

| `id` | Label | Lucide icon | Default name | Remaining children |
|---|---|---|---|---|
| `enterprise` | Enterprise | `Globe` | (rename only) | Site, Area, Line, Cell |
| `site` | Site | `Factory` | `Site` | Area, Line, Cell |
| `area` | Area | `MapPinned` | `Area` | Line, Cell |
| `line` | Line | `GitBranch` | `Line` | Cell |
| `cell` | Cell | `Cpu` | `Cell` | (none) |

Default names keep today’s unique-suffix rule: `Line`, then `Line2`, `Line3`, …

**Description** is written for the **parent the admin clicked**, not a generic blurb.

- Adjacent pick, Area under Site: `Area — a production area within this site.`
- Skip pick, Line under Site: `Line — a production line (an Area will be created to hold it).`
- Leaf: the menu is not shown as items; the button is disabled with
  `Cell is a leaf — nothing can be added under it.`

Auto-created Area uses `kind: production`, same as today’s `addChild`.

Adding a level later means a new catalog row and a Save path that can store it. This
slice does not add that row.

## 6. Components

**`AssetLevelIcon`** — the catalog icon at a fixed size. Used in tree rows, the detail
header, and each + New item.

**`NewAssetMenu`** — one component, two mounts (tree card header and detail pane).

- Button label: **+ New**.
- Items: remaining levels for the current selection. If nothing is selected, treat the
  parent as Enterprise.
- Each item: icon, label, description.
- Disabled when the catalog lists no remaining children (Cell in this slice).
- Choosing an item commits the name draft first. If the draft is invalid, do not add;
  leave the field error visible.

**`HierarchyView`** — keeps load, draft name, rename list, Remove, Save, simulator
banner, and migrate retry. Replaces the letter badge and **Add child**. Page title and
sidebar stay **Plant hierarchy**. Route stays `#/hierarchy`. `settings_edit` / admin
gate is unchanged.

Tree row: icon + type label + name, for example `Line · Train1`. Selected row keeps the
current orange highlight. `aria-label` stays `{Level} {name}` (`Line Train1`).

## 7. Add and Save flow

1. Load via `getHierarchy`. Default selection is Enterprise.
2. **+ New** reads the current selection (Enterprise if none).
3. Commit the name draft. Invalid segment or duplicate sibling: no add, existing red
   field text.
4. If the pick is not the next adjacent level, insert missing parents with default
   unique names, then insert the requested node.
5. Select the requested node (not a placeholder parent) and put its name in the field.
6. The tree is local until **Save**. Save sends the whole nested tree and the rename
   list, placeholders included.
7. Remove is unchanged. Enterprise cannot be removed.

Keyboard: Escape closes the menu. Enter on the name field still commits the draft.

## 8. Errors

No new error types.

| Case | Behaviour |
|---|---|
| Illegal segment or duplicate sibling | Stay on the node; field error; no add |
| Cell selected | + New disabled; leaf title |
| Save rejected (auth, migrate running, tree validation) | Existing save error banner |
| Migrate failed | Existing retry control |
| Load failure | Existing load card |

## 9. Testing

Extend `HierarchyView.test.tsx`. Add focused tests for the catalog (remaining levels,
skip insert) and `NewAssetMenu` (disabled leaf, descriptions).

- Under Area, + New offers Line and Cell only, each with a description.
- Under Site, choosing Line creates a default Area and a Line; the Line is selected.
- Under Line, Cell is the only item. After adding a Cell and selecting it, + New is
  disabled.
- Header and pane menus produce the same child.
- A Line row shows the Line icon and the word `Line`, not `L`.
- Save still sends a complete nested `HierarchyTreeInput` (auto-created Area included).
- Without `settings_edit`, the editor does not load (existing restricted state).

## 10. Decisions (locked)

| Topic | Choice |
|---|---|
| Page | Existing `#/hierarchy`, not a new route or service |
| Add control | + New menu, not a relabelled one-click button |
| Menu placement | Tree header and selected-node pane |
| What the menu lists | Every remaining editor level below the selection |
| Skip on disk | Not in this slice; insert default parents so YAML stays nested |
| Persistence | Unchanged `saveHierarchy` / `plant.yaml` |
| Platform reach | Structure only: Asset Model after Save |
| Tree chrome | Icon + type name per row |
| Icons | Globe, Factory, MapPinned, GitBranch, Cpu |
| Catalog | Frontend module; GraphQL Asset Levels not queried |
| Later levels | New catalog row + Save support; menus stay catalog-driven |

## 11. Out of this spec

Shared left-tree chrome on other routes; a Hierarchy Management container; true skipped
Asset Levels in YAML; Machine / Division in the editor; import/export; tree search;
commissioning of MQTT, OPC, Condition Monitoring, or Grafana.
