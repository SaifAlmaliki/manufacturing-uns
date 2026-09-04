# Admin plant hierarchy (YAML write, reseed, prefix migrate)

Date: 2026-09-04
Modules: `11_frontend`, `07_uns_graphql`, `09_uns_model`, `conf/simulator/plant.yaml`, `conf/settings.yaml`
Status: Approved

Supersedes the “hierarchy is YAML-only, not a form” sentence in
[ADR-0005](../../adr/0005-graphql-mutations-for-console-configuration.md). YAML remains the
reviewable source of truth; the console may write it through GraphQL. Alert-rule mutations
stay unchanged.

## 1. Problem

The platform is meant to run for different companies. Company and plant names are copied
today across `plant.yaml`, `settings.yaml` branding, mapper topic filters, seed input, and
UI placeholders. There is no admin UI to add, remove, or rename ISA-95 nodes. An operator
cannot set up their plant without editing files and restarting `asset_model_setup`.

The WTP simulator is a **demo publisher**. It must not become a process-engineering editor.

## 2. Goals

- An admin with `settings_edit` can add, remove, and rename enterprise, site, area, line,
  and cell (instance tag) in a **Plant hierarchy** console page.
- The live source of those names is `conf/simulator/plant.yaml`. One GraphQL save writes
  that file, then reseeds the Asset Model from it.
- The same save derives branding (`platform.organization_name`, `display_name`) and mapper
  topic filters (`<enterprise>/#`) from the enterprise name. No service keeps a second
  hard-coded company string.
- Adding a node updates YAML and the Asset Model only. The tree shows it as commissioned.
  Nothing publishes there until a real device or a later simulator change does.
- Renaming any hierarchy node rewrites that prefix in the graph database and the historian.
  Nested children move with the parent.
- Delete removes the node from YAML and the Asset Model. Stored graph/historian rows stay.
- Python and TypeScript share the **same path rules** (ISA-95 join/split, enterprise
  segment) via thin helpers that read the YAML/API — not duplicated literals.

## 3. Non-goals

- No new WTP hydraulics or generic simulator publishers when equipment is added.
- The WTP simulator does **not** retarget its publish map on rename. Shipped topics stay
  (`AcmeWater/Site1/…` until someone later changes simulator config).
- No delete-and-purge of historian series or graph nodes.
- No historian downsample rebuild — only the topic/path column (or equivalent key).
- No Grafana dashboard JSON rewrite in this slice.
- No Docker restart from the browser. Mappers pick up new topic filters on their next
  settings reload / process bounce.
- No private frontend API. Writes go through GraphQL (ADR-0005).
- No SparkplugB topic rewrite.
- OEE unit YAML and explore-view copy are out of scope unless they still hard-code the
  enterprise after branding is derived (then they must read the shared helper / API).

## 4. Architecture

```
Admin UI  --saveHierarchy-->  GraphQL
                                |  1. write plant.yaml (whole tree)
                                |  2. derive settings.yaml branding + mapper filters
                                |  3. reseed Asset Model (existing apply_plan)
                                |  4. if rename: enqueue prefix migrate
                                v
                         Neo4j topics + historian topic keys
```

| Piece | Role |
|---|---|
| `conf/simulator/plant.yaml` | Authoritative ISA-95 tree (enterprise, sites, areas, lines, `cells`). A UI “equipment” add is a new **cell** (instance tag, e.g. `V102`) under a line — the same place WTP tags live today. Poster names (`WTP_Valve`, …) are not authored in this slice. |
| `conf/settings.yaml` | Branding and mapper `mqtt.topics` **derived** from enterprise on save. Fallback `simulator.hierarchy` must not disagree with `plant.yaml` after a successful save (write both or make seed ignore the fallback when `plant.yaml` exists). |
| `uns_model.seed` | Reads `plant.yaml` first (today it still reads `settings.simulator.hierarchy`). Same `apply_plan` as `uns_model_seed`. |
| GraphQL `saveHierarchy` | Whole-tree replace, gated like other admin mutations (`settings_edit` / admin). Returns the stored tree plus migrate job status. |
| Prefix migrate job | One at a time. Rewrites graph and historian keys from `oldPrefix` to `newPrefix`. |
| Path helpers | `09_uns_model` (or `00_uns_config`) owns join/split/validate; `11_frontend` has a matching helper used by the hierarchy page and any leftover `CovestroAG` / `AcmeWater` defaults that are still in-scope. |

`asset_model_setup` remains the boot-time seed. After an admin save, GraphQL reseeds
in-process so the operator does not run Compose.

## 5. Hierarchy UI

- Route: `#/hierarchy` (name **Plant hierarchy**). Sidebar under Platform, `adminOnly`,
  feature `settings_edit`.
- Compact console layout: app header title only; `ConsoleCard` + tree; no second page banner.
- Left: tree enterprise → site → area → line → cell (instance tag).
- Right: selected node name (and optional description). Actions: add child, rename, remove.
- Add child is only the next legal level. A cell is a leaf in this slice.
- Edits stay local until **Save**. Save sends the entire tree.
- Banner: the simulator still publishes the shipped WTP paths; renamed nodes will not match
  live sim topics until the simulator config is changed separately.
- Non-admins keep the UNS tree read-only (Asset Model first, then graph).

## 6. Save and migrate

Order on Save:

1. Validate the tree (unique sibling names, legal ISA-95 characters, non-empty enterprise).
2. Write `plant.yaml` (atomic replace).
3. Update `settings.yaml` `organization_name` to the enterprise, `display_name` to
   `"<enterprise> UNS"`, and mapper filters to include `<enterprise>/#`.
4. Reseed the Asset Model from `plant.yaml`.
5. If any path renamed, start the prefix migrate. If a migrate is already `running`, reject
   this Save (or queue — first implementation **rejects**).

Migrate job fields: `oldPrefix`, `newPrefix`, `status` (`running` / `done` / `failed`),
counts, error. The hierarchy page shows this status.

If step 5 fails after 2–4 succeeded, YAML and the model already have the new names. The
admin retries migrate only. Files are not rolled back.

Enterprise rename updates mapper filters to `["test/uns/#", "<enterprise>/#", …]` (keep
existing non-enterprise entries such as Sparkplug). Site/area/line/cell/equipment rename
does not change mapper filters.

## 7. Shared naming

Forbidden: new hard-coded `AcmeWater` or `CovestroAG` in code paths this feature touches.

Required:

- One function to join ISA-95 segments and one to split a topic prefix.
- Enterprise for branding and mapper filters is `plant.yaml`’s `enterprise` after save.
- Frontend branding that today comes from build-time `platformConfig.organizationName`
  must refresh after save (read from GraphQL/settings, or require a reload that re-reads
  conf). A save that only changes YAML while the sidebar still shows the old name is a bug.

## 8. Testing

- Seed reads `plant.yaml` when it exists; fallback hierarchy is unused in that case.
- `saveHierarchy` writes files, reseeds, and is rejected without `settings_edit` / admin.
- Add equipment: Asset Model has the path; simulator device count unchanged.
- Rename site: graph and historian rows under the old prefix are rewritten; children follow.
- Delete cell: gone from YAML and model; historian rows for that prefix remain.
- Concurrent second rename Save is rejected while a job is running.
- Path helpers reject empty segments and disagreeing join/split.

## 9. Decisions (locked)

| Topic | Choice |
|---|---|
| First-slice scope | Full hierarchy CRUD, not branding-only |
| Add equipment | Asset Model only |
| Persistence | UI writes YAML, then reseed |
| Write channel | GraphQL, whole tree |
| Enterprise rename | Branding + mapper filters + graph/historian migrate |
| Other renames | Graph/historian prefix migrate |
| Delete | Model + YAML only; keep stored series |
| Simulator on rename | Does not retarget |
| ADR-0005 | YAML still truth; forms may write it |

## 10. Out of this spec

WTP process model, MQTT command writes, Sparkplug rewrite, Grafana JSON, OEE units,
automatic mapper process restart.
