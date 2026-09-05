# Plant hierarchy add UX (typed + New menu, authored machines)

Date: 2026-09-05
Modules: `11_frontend` (`components/hierarchy`), `07_uns_graphql` (hierarchy types/inputs),
`09_uns_model` (`hierarchy.py`, `seed.py`, `hierarchy_io` consumers), `conf/simulator/plant.yaml`
Status: Approved
Extends: [2026-09-04 admin plant hierarchy](./2026-09-04-admin-hierarchy-yaml-design.md)

The Plant hierarchy page at `#/hierarchy` is the **only editor** for the shared ISA-95
Asset Model, including **Machine**. This spec changes how an admin **adds** a node, how
the tree **shows** each Asset Level, and how a Machine is **persisted and seeded** so
Connectivity, Condition Monitoring, historian enrichment, alerts, and OEE all read the
same facts.

## 1. Problem

`+ Add child` creates the next ISA-95 level and does not say which. The tree marks rows
with the first letter of Site / Area / Line / Cell. An admin cannot add a Machine.

Machines exist in the Asset Model today only because seed **stamps every PLC template
under every Work Cell**. They are not in `plant.yaml`, not on `#/hierarchy`, and not
something an admin can create. Connectivity cannot attach a subscribed tag to Dryer
unless Dryer is already a MACHINE Asset.

Save already writes the shared Asset Model through GraphQL. Connectivity and Condition
Monitoring must not own a second tree. The gap is the add control, the row chrome, and
the missing Machine level on the hierarchy write path.

## 2. Goals

- An admin with `settings_edit` can open **+ New** in the **tree header** and on the
  **selected node**, and see every remaining editor level below that node, each with an
  icon, label, and one-line description. **Machine is in that catalog.**
- Picking a non-adjacent level (Machine under Line, Line under Site) creates the missing
  parents in the same action, so `saveHierarchy` still receives a complete nested tree.
- Each tree row shows that level’s Lucide icon and the type name next to the node name
  (for example `Machine · Dryer`).
- One catalog drives both menus and the tree.
- Edits stay local until **Save**. After Save, the new structure — including Machines —
  is in `plant.yaml` and in the Postgres Asset Model (`level = MACHINE`) for the whole
  platform. Nothing publishes, subscribes, or draws a card until a later commissioning
  step (Connectivity attach, simulator, or a live device).

## 3. Non-goals

- No new container or image. Hierarchy Management is not a separate service.
- No private frontend API. Writes stay on `getHierarchy` / `saveHierarchy` (ADR-0005).
- No true skipped levels on disk (a Line with no Area Asset). Insert default parents.
- No Division, Product Line, Production Unit, or Work Cell as extra editor labels.
  Cell remains the Work Cell / instance tag (`V101`). Machine is the equipment leaf
  (`Dryer`), matching Asset Level `MACHINE`. A PLC is also a Machine — the Asset
  Level already means “a machine or PLC that publishes Metrics”. OPC / Modbus /
  MQTT servers and their signals are **not** hierarchy nodes: the server lives in
  Connectivity; each signal becomes a Metric on a MACHINE Asset at attach time.
- The tree component is not copied onto Condition Monitoring or Connectivity in this
  slice. Those pages **read** Assets after Save; they do not write this tree.
- No import/export, tree search, or empty-state illustration (the PwC “+ New Item /
  nothing selected” chrome is the interaction reference, not a pixel copy).
- No MQTT, OPC, Condition Monitoring, or Grafana wiring when a node is added.
- No create-machine control on `#/connectivity`. That page picks existing MACHINE
  Assets authored here.

## 4. Architecture

```
Browser (#/hierarchy)
    → uns_frontend (HierarchyView + catalog + NewAssetMenu + AssetLevelIcon)
    → graphql_server  getHierarchy / saveHierarchy
        → plant.yaml  (cells are { name, machines[] })
        → Postgres Asset Model  (WORK_CELL + MACHINE branches)
```

`#/hierarchy` is the platform hierarchy. After Save, `apply_plan` upserts every
Enterprise → Site → Area → Line → Work Cell → Machine path. Other console pages and
services read Assets (`getAssets`, topic binding, Metric Definitions). They do not
author structure.

`asset_model_setup` still seeds at stack start. After Save, GraphQL reseeds in-process
as today.

`saveHierarchy` still requires every Line to sit under an Area under a Site, and every
Machine to sit under a Cell. The menu may offer a skipped **editor** level; the insert
path fills the chain with default-named parents.

### 4.1 YAML and GraphQL shape

A cell is no longer a bare string once machines are authored.

```yaml
lines:
  - name: Train1
    cells:
      - name: V101
        machines:
          - Dryer
      - name: P101
        machines: []
```

**Read** still accepts today’s string cells (`cells: [V101, P101]`). A string becomes
`HierarchyCell(name="V101", machines=())`.

**Write** always emits the object shape so machines survive a round-trip.

GraphQL:

- `HierarchyCellType { name: String!, machines: [String!]! }`
- `HierarchyLineType.cells: [HierarchyCellType!]!` (was `[String!]!`)
- Matching `HierarchyCellInput` / `HierarchyLineInput`

### 4.2 Seed rules (platform source of truth)

For each Work Cell:

| Cell in YAML | MACHINE Assets created |
|---|---|
| String, or object with `machines: []` / omitted | Existing demo stamp: every `simulator.plc` equipment name, plus SCADA on the first cell of a Site and HMI on the first cell of a Line |
| Object with one or more `machines` | **Those names only**, plus the same SCADA / HMI specials |

Authoring Dryer on V101 and Saving replaces the PLC stamp on that cell with Dryer.
Empty new cells keep the demo stamp so an untouched WTP plant does not lose MixerTank
until an admin commissions that cell.

Removing a machine from the list and Saving prunes that MACHINE Asset (existing
`apply_plan` prune).

Metric Definitions from PLC sensor templates stay plant-wide as today. An authored
machine does not invent sensors; Connectivity later writes Metric Definitions when a
tag is attached.

### 4.3 Prefix migrate

`all_prefixes` includes machine paths (`…/V101/Dryer`). Renaming V101 or Dryer
participates in the existing rename list and historian/graph prefix migrate.

## 5. Level catalog

One module beside the hierarchy view, for example
`11_frontend/src/components/hierarchy/hierarchyLevels.ts`. Ordered list of editor levels.
Both menus and the tree read it. Do not copy labels into `HierarchyView`.

| `id` | Label | Lucide icon | Default name | Remaining children |
|---|---|---|---|---|
| `enterprise` | Enterprise | `Globe` | (rename only) | Site, Area, Line, Cell, Machine |
| `site` | Site | `Factory` | `Site` | Area, Line, Cell, Machine |
| `area` | Area | `MapPinned` | `Area` | Line, Cell, Machine |
| `line` | Line | `GitBranch` | `Line` | Cell, Machine |
| `cell` | Cell | `Cpu` | `Cell` | Machine |
| `machine` | Machine | `Cog` | `Machine` | (none) |

Default names keep today’s unique-suffix rule: `Machine`, then `Machine2`, …

**Description** is written for the **parent the admin clicked**.

- Adjacent, Machine under Cell: `Machine — equipment under this cell. After Save it is a MACHINE Asset the rest of the platform can attach tags to.`
- Skip, Machine under Line: `Machine — equipment (a Cell will be created to hold it).`
- Leaf: the button is disabled with
  `Machine is a leaf — nothing can be added under it.`

Auto-created Area uses `kind: production`, same as today’s `addChild`.

## 6. Components

**`AssetLevelIcon`** — the catalog icon at a fixed size. Used in tree rows, the detail
header, and each + New item.

**`NewAssetMenu`** — one component, two mounts (tree card header and detail pane).

- Button label: **+ New** (reference: Hierarchy Management “+ New Item”; we keep the
  existing **New** accessible name).
- Items: remaining levels for the current selection. If nothing is selected, treat the
  parent as Enterprise.
- Each item: icon, label, description.
- Disabled when the catalog lists no remaining children (Machine).
- Choosing an item commits the name draft first. If the draft is invalid, do not add;
  leave the field error visible.

**`HierarchyView`** — keeps load, draft name, rename list, Remove, Save, simulator
banner, and migrate retry. Replaces the letter badge and **Add child**. Page title and
sidebar stay **Plant hierarchy**. Route stays `#/hierarchy`. `settings_edit` / admin
gate is unchanged.

Tree row: icon + type label + name, for example `Machine · Dryer`. Selected row keeps
the current orange highlight. `aria-label` stays `{Level} {name}` (`Machine Dryer`).

Machines nest under their Cell in the left tree (reference: functional location leaf).

## 7. Add and Save flow

1. Load via `getHierarchy`. Default selection is Enterprise.
2. **+ New** reads the current selection (Enterprise if none).
3. Commit the name draft. Invalid segment or duplicate sibling: no add, existing red
   field text.
4. If the pick is not the next adjacent level, insert missing parents with default
   unique names, then insert the requested node.
5. Select the requested node (not a placeholder parent) and put its name in the field.
6. The tree is local until **Save**. Save sends the whole nested tree and the rename
   list, placeholders included. Cells are `{ name, machines }`.
7. Remove is unchanged for Enterprise (forbidden). Removing a Cell removes its
   machines. Removing a Machine removes only that machine.
8. After Save, `getAssets` lists the new MACHINE. Connectivity and Condition
   Monitoring see it on their next Asset read. No extra notify beyond today’s
   `asset_model_changed`.

Keyboard: Escape closes the menu. Enter on the name field still commits the draft.

## 8. Errors

No new error types.

| Case | Behaviour |
|---|---|
| Illegal segment or duplicate sibling | Stay on the node; field error; no add |
| Duplicate machine under the same cell | Same as duplicate cell: field error / save validation |
| Machine selected | + New disabled; leaf title |
| Save rejected (auth, migrate running, tree validation) | Existing save error banner |
| Migrate failed | Existing retry control |
| Load failure | Existing load card |

## 9. Testing

Model: string cells coerce; object cells round-trip; `all_prefixes` includes machines;
duplicate machine names under one cell are rejected.

Seed: empty machines still stamps PLC + SCADA/HMI; authored `["Dryer"]` creates
`…/V101/Dryer` and does not create the PLC equipment on that cell.

GraphQL: `getHierarchy` returns `cells { name machines }`; `saveHierarchy` accepts
cell objects and writes object-shaped YAML.

Frontend: catalog remaining children; skip insert Machine under Line; + New disabled
on Machine; Save payload includes `{ name: 'V101', machines: ['Dryer'] }`; row shows
the word `Machine`, not `M`.

## 10. Decisions (locked)

| Topic | Choice |
|---|---|
| Page | Existing `#/hierarchy`, not a new route or service |
| Add control | + New menu, not a relabelled one-click button |
| Menu placement | Tree header and selected-node pane |
| What the menu lists | Every remaining editor level below the selection, including Machine |
| Editor leaf | Machine. Cell is a Work Cell and can have machines. A PLC is a Machine. Signals are Metrics, not a level below Machine |
| Skip on disk | Not in this slice; insert default parents so YAML stays nested |
| Persistence | `saveHierarchy` / `plant.yaml` cells become `{ name, machines[] }` |
| Seed | Authored machines win on that cell; empty cells keep PLC stamp |
| Platform reach | After Save, MACHINE Assets are the picker source for Connectivity |
| Tree chrome | Icon + type name per row |
| Icons | Globe, Factory, MapPinned, GitBranch, Cpu, Cog |
| Catalog | Frontend module; GraphQL Asset Levels not queried |
| Shared tree on other routes | Later spec; those routes read Assets |

## 11. Out of this spec

Shared left-tree chrome on Condition Monitoring or Connectivity; a Hierarchy
Management container; true skipped Asset Levels in YAML; Division / Product Line;
import/export; tree search; Metric Definition authoring; Connectivity attach dialog;
commissioning of MQTT, OPC, or Grafana.
