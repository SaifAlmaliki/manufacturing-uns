# ISA-95 asset authoring: Asset Templates, tags, and the console screens

Date: 2026-09-03
Modules: `09_uns_model`, `07_uns_graphql`, `11_frontend`, `CONTEXT.md`, `docs/adr`
Status: Approved, not yet implemented

## 1. Problem

The Asset Model is the source of truth for plant structure and naming (ADR-0003), and it
cannot be edited by a human being. It is authored by writing YAML into
`conf/settings.yaml` and running a container:

```sh
uv run uns_model_seed --from-simulator-config
docker compose up asset_model_setup
```

That is acceptable for one simulated plant. It does not survive the goal, which is a
platform serving many plants, each with its own assets, its own tags, its own dashboards
and its own OEE. Three things break at once:

1. **There is no write API.** `07_uns_graphql` exposes `getAssets`, `getAssetChildren`,
   `getAsset`, `getTopicContext`, `getUnmodelledTopics` and `getAssetModelSummary`. Its
   `Mutation` type is `class Mutation(AlertRuleMutation, OeeMutation)`
   (`07_uns_graphql/src/uns_graphql/uns_graphql_app.py:68`). Nothing can write an Asset.

2. **Repetition has no leverage.** A plant with forty identical mixers is forty YAML
   blocks, and adding one tag to all forty is forty edits. The seed's own helper
   `_machines()` (`09_uns_model/src/uns_model/seed.py:149`) exists precisely because the
   simulator config already needed a way to say "these devices are all the same shape" —
   in a config file, with no equivalent available to an engineer.

3. **Tags are invisible.** `model.metric_definition` holds the Unit of Measure, display
   name, precision and engineering range for every Metric Key
   (`09_uns_model/src/uns_model/tables.py:170`). Nothing in the console lists them, and
   nothing lets an engineer see that a published topic has no definition at all — even
   though `getUnmodelledTopics` already computes exactly that gap.

This spec adds the authoring layer: an Asset Template concept with live propagation, the
write API beneath it, and the console screens on top.

## 2. Findings that shape the design

Established by reading the code, not assumed.

1. **The tree already supports many plants.** `model.asset` is self-referencing with
   `path` as a unique natural key and `level` carried per row, explicitly so a branch may
   skip levels (`tables.py:57`, `tables.py:86`). Many `SITE` subtrees under one
   `ENTERPRISE` need no schema change. There is no tenant dimension and this spec does not
   add one — see section 4.

2. **The write primitives half-exist.** `AssetModelRepository` has `ensure_branch`,
   `define_metric`, `delete_asset`, `bind_topic` and `rebind_all`
   (`repositories.py:117`). What is missing is not persistence but the shape a UI needs.

3. **`ensure_branch` is the wrong primitive for a screen.** It writes a whole root-down
   branch, upserting each level by path (`repositories.py:128`). A console that wants "add
   one Work Cell under this Line" would have to resend the entire ancestry, and a console
   that wants to *rename* would silently create a second branch and orphan the first.

4. **`asset.path` is denormalized, and nothing maintains it on rename.** The column is
   documented as kept alongside `parent_id` "because resolving a topic means matching a
   prefix, not walking a tree" (`tables.py:87`). A `CHECK` enforces
   `path = segment OR right(path, length(segment)+1) = '/' || segment`
   (`tables.py:103`) — which constrains the row's own suffix and says nothing about its
   descendants. Renaming a Line therefore needs a recursive rewrite that does not exist.

5. **Forgetting to rebind is the documented way to break the design.** ADR-0003:
   "any write to `model.asset` must trigger a rebind... forgetting it is the obvious way
   to break this design." `ensure_branch` and `delete_asset` already default to
   `rebind=True`; every new write must too.

6. **Cache invalidation across services is already built.** `announce_asset_model_changed`
   emits `NOTIFY asset_model_changed`; `AssetModelChangeListener` is wired into the
   GraphQL server's `on_startup` (`queries/asset.py`) and into the historian's binder. A
   console edit therefore reaches every reader with no redeploy and no new plumbing.

7. **Deleting an Asset silently destroys OEE configuration.** `oee_unit.asset_id`,
   `shift_pattern.asset_id`, `shift_exception.asset_id` and `ideal_cycle_time.asset_id` all
   FK to `model.asset` with `ON DELETE CASCADE` (`oee_tables.py:236`, `:132`, `:200`,
   `:288`). Deleting a Line takes its OEE unit, its shift pattern and its cycle times with
   it. Nothing warns anyone today, because nothing can delete an Asset today.

8. **Alert Rules point at Assets by text, not by key.** `alert_rules.topic` is `Text` and
   documented as "May be an MQTT pattern; not resolved to an Asset here"
   (`tables.py:335`). Renaming or moving an Asset cannot cascade to its rules; they simply
   stop matching. This is a pre-existing hazard that authoring makes reachable.

9. **`_BEST_ASSET_SQL` filters on `is_active`** (`repositories.py:56`). Deactivating an
   Asset stops it binding topics while leaving its row, its OEE unit and its history
   intact. That makes `is_active = false` the safe counterpart to a delete, and this design
   leans on it heavily.

10. **OEE master data is already relational and already per-Asset.** `oee_unit`,
    `shift_pattern`, `product`, `downtime_reason`, `ideal_cycle_time` and
    `state_reason_map` are tables with a repository full of `save_*` and `reconcile_*`
    methods (`oee_master_data.py:277`). Per-plant OEE screens are therefore a UI-and-
    mutations job over an existing model, which is why they are a follow-on spec and not
    a rewrite.

11. **The seed reconciles, so it will fight a console.** `deactivate_units_absent_from`,
    `delete_cycle_times_absent_from`, `delete_state_rules_absent_from`
    (`oee_master_data.py:212`–`:266`) remove what the YAML no longer mentions. Two
    authors over one table, one of which prunes, is not a tie that resolves itself.

12. **The frontend has no test runner.** `11_frontend/package.json` defines `dev`,
    `build`, `preview` and `lint: tsc --noEmit`. There is no `test` script and no runner
    in `devDependencies`.

13. **A structural write is three transactions today, not one.** `ensure_branch` writes
    through `Database.session()`, which commits on exit (`engine.py:100`). It then calls
    `rebind_all()`, which opens its own `Database.begin()` connection
    (`repositories.py:274`), which then calls `announce_asset_model_changed()`, which opens
    a third (`notifications.py:24`). A rebind that fails therefore leaves committed
    structure with stale bindings — precisely the state ADR-0003 warns about. This is
    tolerable for a batch seed and not tolerable for forty instances updated by one click,
    so section 7.1.1 closes it.

## 3. Four rules the whole design serves

1. **Postgres is the source of truth; YAML is a bootstrap.** The console writes the
   database and the database wins. `uns_model_seed` becomes a first-run convenience and
   stops pruning.
2. **Structure is edited server-side, in one transaction.** A template save that touches
   forty instances either lands completely or not at all. The browser never orchestrates a
   multi-row structural edit.
3. **Propagation never destroys.** A template edit may create, update and *deactivate*.
   It may not delete an Asset, because deleting one cascades away OEE configuration
   (finding 7).
4. **Every write rebinds, in the same transaction as the write.** `rebind_all()` and
   `NOTIFY asset_model_changed` fire once per mutation, enlisted in the mutation's own
   transaction (findings 5 and 13). Postgres delivers a `NOTIFY` only when its transaction
   commits, so a listener can never drop its cache over a change that rolled back.

## 4. Scope

**In scope**

- Asset Template tables, repository and live propagation.
- Single-Asset write primitives: save, rename, move, activate/deactivate, delete, and
  subtree duplication with a naming pattern.
- Metric Definition (tag) CRUD, and adopting Unmodelled Topics into the model.
- GraphQL mutations and queries for all of the above.
- Console screens: Asset Model Explorer, Template Library, tag tables, adopt drawer.
- Demoting `uns_model_seed` to bootstrap-only.
- New `CONTEXT.md` entries and one ADR.

**Out of scope, deliberately, each its own follow-on spec**

- **Per-plant OEE configuration screens.** The tables exist (finding 10); the console has
  no OEE route, view or `FeatureKey` at all. Separate spec.
- **Per-plant RBAC.** `FeatureKey` is feature-scoped, not site-scoped
  (`11_frontend/src/types/rbac.ts`). This spec adds a *UI* plant scope; it does not
  enforce that an engineer may only see their own plant.
- **Edge snapshot export and OPC UA tag-mapping generation.** The per-plant edge stack
  does not exist yet — `docker-compose.yml` is one stack — so there is nothing to deliver
  a snapshot to and nothing to test against. Section 12 records what this design must not
  foreclose.
- **Per-plant dashboards.** Grafana reads `uns_metrics_enriched` (ADR-0001), which this
  spec improves by making the model editable. Dashboard provisioning is separate.

## 5. Vocabulary

To be added to `CONTEXT.md` under the Asset model heading:

**Asset Template**: A reusable subtree of Assets and their Metric Definitions, authored
once and instantiated many times. ISA-95's Equipment Class. Editing a template changes
every instance that has not overridden the edited field.
_Avoid_: class, type, blueprint, prototype, pattern

**Template Node**: One Asset-shaped level inside an Asset Template. Carries a path
*relative* to the template root, because a template has no place in the plant until it is
instantiated.
_Avoid_: template asset, node

**Instance Override**: A column or Metric Definition on an instantiated Asset that has
been edited locally, and is therefore exempt from propagation. Recorded per column, so
correcting one machine's serial number does not freeze its tag list.
_Avoid_: local change, customisation, dirty field

**Plant Scope**: The Site the console is currently authoring or viewing. A UI filter over
Asset paths, not an access control boundary.
_Avoid_: tenant, current plant, context

Note the collision this avoids: `CONTEXT.md` already defines **Instance** as "one
deployment of the platform". An instantiated Asset is never called an Instance on its own
— it is an *instance of a template*, and the recorded fact is an **Instance Override**.

## 6. Data model — migration `0004_asset_templates.py`

### 6.1 New tables, schema `model`

```
model.asset_template
  id            bigint identity PK
  name          text NOT NULL UNIQUE      -- 'Filling Line', 'Mixer Tank'
  description   text
  root_level    text NOT NULL FK -> asset_level.name
  created_at, updated_at  timestamptz NOT NULL default now()

model.asset_template_node
  id                bigint identity PK
  template_id       bigint NOT NULL FK -> asset_template.id ON DELETE CASCADE
  parent_id         bigint     NULL FK -> asset_template_node.id ON DELETE CASCADE
  segment           text NOT NULL
  level             text NOT NULL FK -> asset_level.name ON UPDATE CASCADE
  relative_path     text NOT NULL     -- '' for the root, 'Cell1/MES-01' below it
  display_name      text
  description       text
  attributes        jsonb NOT NULL default '{}'
  UNIQUE (template_id, relative_path)   -- uq_template_node_relative_path
  UNIQUE (parent_id, segment)           -- uq_template_node_sibling_segment
  CHECK  (segment <> '')
  CHECK  (id <> parent_id)
  INDEX  (template_id), INDEX (parent_id)

model.asset_template_metric
  id                bigint identity PK
  template_node_id  bigint NOT NULL FK -> asset_template_node.id ON DELETE CASCADE
  metric_key        text NOT NULL
  display_name      text
  unit_of_measure   text
  decimals          smallint
  min_value         double precision
  max_value         double precision
  deadband          double precision
  description       text
  UNIQUE (template_node_id, metric_key)
  CHECK  (metric_key <> '')
  CHECK  (min_value IS NULL OR max_value IS NULL OR min_value <= max_value)
```

The constraint set deliberately mirrors `asset` and `metric_definition`: same emptiness
checks, same range check, same sibling-uniqueness rule. A template that cannot be
instantiated without violating a constraint is a template that should have been rejected
when it was saved.

`relative_path` is stored rather than derived for the same reason `asset.path` is
(finding 4): projecting a template means matching nodes to Assets by relative position,
and doing that by walking the tree per instance turns one query into N.

### 6.2 Columns added to existing tables

```
model.asset
  + template_id       bigint NULL FK -> asset_template.id      ON DELETE SET NULL
  + template_node_id  bigint NULL FK -> asset_template_node.id ON DELETE SET NULL
  + overridden_fields text[] NOT NULL default '{}'
  INDEX (template_id), INDEX (template_node_id)

model.metric_definition
  + template_metric_id bigint NULL FK -> asset_template_metric.id ON DELETE SET NULL
  + is_overridden      boolean NOT NULL default false
  INDEX (template_metric_id)
```

`ON DELETE SET NULL` on all three template FKs is the single most important choice in this
migration. Deleting an Asset Template must never delete plant structure; the instances stop
being linked and keep every row, every tag and every OEE unit. `CASCADE` here would make
one careless click in a template library destroy a plant.

`template_id` is set on the instance **root** only; `template_node_id` is set on every
Asset the template created, root included. That distinction is what lets
`project_to_instances` find its roots with one indexed lookup and then match descendants by
node.

`overridden_fields` is `text[]` of column names. A `jsonb` of old values was rejected: the
question asked at projection time is only ever "may I write this column", and an array
answers it with `= ANY`.

### 6.3 Backfill

None. Every existing Asset gets `template_id IS NULL`, `template_node_id IS NULL` and
`overridden_fields = '{}'`, which is exactly "authored by hand, owned by nobody" — the
correct description of everything the seed has written so far. Existing Metric Definitions
get `is_overridden = false` and a null `template_metric_id`, meaning "not template-managed",
which projection skips rather than claims.

## 7. Module layout

### 7.1 `09_uns_model` — additions to `AssetModelRepository`

| Method | Why it is not an existing method |
| --- | --- |
| `save_asset(parent_path, spec)` | Single-node upsert with a level-rank check against the parent. `ensure_branch` writes the whole ancestry (finding 3). |
| `rename_asset(path, segment)` | Recursive descendant `path` rewrite, then `rebind_all()`. Closes finding 4. |
| `move_asset(path, new_parent_path)` | Same rewrite, plus a cycle guard and a rank check. |
| `set_active(path, is_active, *, cascade)` | The safe counterpart to delete (finding 9). |
| `duplicate_subtree(source_path, target_parent_path, segment)` | Copies Assets and their Metric Definitions; carries `template_node_id` across so a copy of an instance is still an instance. |
| `delete_metric(metric_key, *, asset_path)` | `define_metric` has no inverse. |
| `dependents_of(path)` | The OEE units, shift patterns, cycle times and Alert Rules that would be affected by deleting or renaming this Asset (findings 7 and 8). |
| `unmodelled_topics(limit, *, under=None)` | Existing method gains a branch filter, so the adopt flow shows one plant's gaps. |

`rename_asset` and `move_asset` share one statement, because they are the same operation —
a new `path` prefix for a subtree:

```sql
UPDATE model.asset
   SET path = :new_prefix || substr(path, length(:old_prefix) + 1),
       updated_at = now()
 WHERE path = :old_prefix OR starts_with(path, :old_prefix || '/')
```

`starts_with`, not `LIKE`, for the reason already documented at `repositories.py:47`:
segments routinely contain underscores and `_` is a `LIKE` wildcard, so `LIKE` would drag
`LineX1` along when renaming `Line_1`.

#### 7.1.1 Making a structural write one transaction

Finding 13: a write, its rebind and its notification are currently three transactions, so a
failed rebind commits structure and leaves bindings stale. Two signatures change to close
that:

```python
async def rebind_all(self, *, connection: AsyncConnection | None = None) -> int
async def announce_asset_model_changed(database, *, connection=None) -> None
```

When `connection` is passed, neither opens its own — they execute on the caller's, and the
caller commits once. When it is omitted both behave exactly as today, so `ensure_branch`,
`delete_asset` and the batch seed are unchanged and no existing test moves.

Every mutation added by this spec runs its writes, its `rebind_all` and its
`announce_asset_model_changed` on one `Database.begin()` connection. This is what makes
rule 2 and rule 4 true rather than aspirational, and it is what section 14 relies on when
it claims a failed projection changes nothing.

`NOTIFY` inside a transaction is queued by Postgres and delivered on commit, so enlisting
the announcement strengthens it: a rolled-back projection cannot make the GraphQL resolver
or the historian's binder drop a cache over a change that never happened.

### 7.2 `09_uns_model/src/uns_model/asset_templates.py` — new

Follows `alert_rules.py` and `oee_master_data.py`: frozen dataclass specs with `validate()`
that reject bad input before Postgres does, so the caller gets
`Asset Level 'LINE' cannot sit under 'MACHINE'` rather than a constraint name.

```python
AssetTemplateSpec(name, description, root_level, nodes: Sequence[TemplateNodeSpec])
TemplateNodeSpec(relative_path, segment, level, display_name, description,
                 attributes, metrics: Sequence[TemplateMetricSpec])
TemplateMetricSpec(metric_key, display_name, unit_of_measure, decimals,
                   min_value, max_value, deadband, description)

class AssetTemplateRepository:
    async def save_template(spec, *, expected_updated_at) -> TemplateProjection
    async def instantiate(template_id, parent_path, segment) -> Asset
    async def instantiate_many(template_id, parent_path, count, pattern) -> list[Asset]
    async def project_to_instances(template_id) -> TemplateProjection
    async def delete_template(template_id) -> bool
    async def drift(template_id) -> list[InstanceDrift]
    async def list_templates() -> list[AssetTemplate]
```

`TemplateProjection` is a frozen dataclass of counts and skips:
`assets_created`, `assets_updated`, `assets_deactivated`, `metrics_written`,
`metrics_deleted`, `overrides_skipped: list[tuple[str, str]]` — (asset path, field).

`validate()` enforces what the constraints cannot: that `relative_path` is consistent with
`segment` and the parent's `relative_path`, that levels get monotonically finer down each
branch (reusing `level_ranks()`, exactly as `ensure_branch` does at
`repositories.py:139`), and that the root node's level equals `root_level`.

### 7.3 `07_uns_graphql`

New `input/asset.py`, `mutations/asset.py`, `mutations/asset_template.py`; extensions to
`queries/asset.py` and `type/asset.py`.

```graphql
# Assets
saveAsset(asset: AssetInput!): AssetNode!
renameAsset(path: String!, segment: String!): AssetNode!
moveAsset(path: String!, newParentPath: String!): AssetNode!
setAssetActive(path: String!, isActive: Boolean!, cascade: Boolean! = true): AssetNode!
deleteAsset(path: String!, force: Boolean! = false): DeleteAssetResult!
duplicateAsset(sourcePath: String!, targetParentPath: String!, segment: String,
               copies: Int! = 1, namingPattern: String): [AssetNode!]!

# Tags
saveMetricDefinition(definition: MetricDefinitionInput!): MetricDefinitionType!
deleteMetricDefinition(metricKey: String!, assetPath: String): Boolean!
adoptUnmodelledTopics(topics: [AdoptTopicInput!]!): [MetricDefinitionType!]!

# input AdoptTopicInput {
#   topic: String!                  # the Unmodelled Topic being adopted
#   assetPath: String!              # existing or to-be-created Asset it belongs to
#   metricKey: String!              # topic remainder + payload leaf, e.g. 'ProcessValue/Temperature/value'
#   createMissingAssets: [AssetInput!]  # levels to create first; empty when assetPath exists
#   unitOfMeasure: String
#   displayName: String
# }

# Templates
saveAssetTemplate(template: AssetTemplateInput!,
                  expectedUpdatedAt: DateTime): TemplateProjectionType!
deleteAssetTemplate(id: ID!): Boolean!
instantiateTemplate(templateId: ID!, parentPath: String!, segment: String,
                    copies: Int! = 1, namingPattern: String): [AssetNode!]!
revertToTemplate(path: String!, fields: [String!]): AssetNode!

# Queries
getAssetTemplates: [AssetTemplateType!]!
getAssetTemplate(id: ID!): AssetTemplateType
getMetricDefinitions(assetPath: String, includeGlobal: Boolean! = true): [MetricDefinitionType!]!
getTemplateDrift(templateId: ID!): [InstanceDriftType!]!
getUnmodelledTopics(limit: Int64! = 100, under: String): [String!]!   # `under` is new
```

`AssetNode` gains `templateName`, `templateId`, `overriddenFields` and `hasTemplate`, so
the detail form can badge a field without a second round trip.

Wiring, one line at `uns_graphql_app.py:68`:

```python
class Mutation(AlertRuleMutation, OeeMutation, AssetMutation, AssetTemplateMutation):
```

plus the matching `on_shutdown` calls at `:84`.

`deleteAsset` returns `DeleteAssetResult { removed: Int!, refused: Boolean!, dependents: [DependentType!]! }`
rather than an `Int`, because a refusal has to explain itself. This is the guard for
finding 7.

### 7.4 `11_frontend`

```
src/components/model/
  AssetModelView.tsx          route /model
  PlantScopeSelector.tsx      Enterprise / Site scope
  AssetTreeEditor.tsx         lazy tree over getAssetChildren
  AssetDetailForm.tsx         authored columns, override badges, revert action
  AttributeEditor.tsx         JSONB key/value rows
  TagTable.tsx                Metric Definitions, inline CRUD
  DuplicateAssetModal.tsx     target parent, name, copies, pattern, live preview
  AdoptTopicsDrawer.tsx       getUnmodelledTopics(under:) -> adopt
  TemplateLibraryView.tsx     route /model/templates
  TemplateEditor.tsx          same tree+detail shape over Template Nodes
  TemplateTagTable.tsx
  InstantiateTemplateModal.tsx
  ProjectionResultToast.tsx   "40 updated, 1 skipped (overridden)"
src/context/PlantScopeContext.tsx
src/lib/model/naming.ts       pattern expansion + collision preview
src/lib/model/map-templates.ts
```

`PlantScopeContext` is its own context rather than more state in `UNSContext`, because the
follow-on OEE and dashboard specs both need it and neither needs the UNS tree's node cache.

Two new `FeatureKey`s in `types/rbac.ts` — `asset_model` (view) and `asset_model_edit`
(write, `adminOnly`-adjacent: admin and engineer) — with matching `SYSTEM_FEATURES` entries
under `Core Navigation` and `System & Admin`. Sidebar entry in `opsNavItems`, routes in
`App.tsx` under `ProtectedConsoleLayout`.

The Explorer header shows `getAssetModelSummary` — assets, metric definitions, bound
topics, **unmodelled topics** — which turns "is my model complete?" from a SQL query into a
number on a screen.

## 8. Propagation

`project_to_instances(template_id)` runs inside the same transaction as `save_template`.
For each Asset with `template_id = :id`, it maps Template Nodes to Assets by
`template_node_id` and reconciles:

| Template change | Effect on every instance |
| --- | --- |
| Node added | Create the Asset under the mapped parent. If an unlinked sibling with that segment already exists, **adopt** it — set `template_node_id` — rather than fail. `uq_asset_sibling_segment` would reject the duplicate anyway, and adoption is what the engineer meant. |
| `display_name`, `description`, `attributes`, `level` changed | Update, unless the column name is in `asset.overridden_fields`. |
| `segment` changed | `rename_asset` per instance, descendant `path` rewrite included. |
| Node removed | `set_active(false)` on the mapped Asset and its descendants. Never a delete (rule 3, finding 7). |
| Metric added or changed | Upsert the Metric Definition, unless `is_overridden`. |
| Metric removed | Delete the Metric Definition. Nothing FKs to it, and `oee_unit.state_metric_key` is text, so the worst case is a lost Unit of Measure — not lost data. |

Then **once**, after all instances and on the same connection (7.1.1): `rebind_all()` and
`announce_asset_model_changed()`. Once, not per instance: the rebind is a single statement
over `topic_binding` (`repositories.py:_REBIND_ALL_SQL`), and calling it forty times would
be forty full passes over the table to reach the same answer.

### 8.1 Overrides

Editing an instance Asset through `saveAsset` adds each changed column name to
`overridden_fields`. Editing a template-managed Metric Definition sets `is_overridden`.
`revertToTemplate(path, fields)` removes entries and re-projects just those columns.

Overrides are per column, never per Asset. Setting one mixer's `serial_number` must not
stop that mixer receiving a new tag — which is the failure mode of every "dirty flag"
implementation of this feature.

### 8.2 Why live propagation, and what makes it reviewable

Live propagation was chosen over an explicit sync-with-diff: "define once, applies
everywhere" is the reason to have templates at all, and an approval step per instance
recreates the forty-edits problem it exists to solve.

The cost is that the review happens after the write, so the write has to report itself.
`saveAssetTemplate` returns a `TemplateProjection`, and the console shows it as
"Saved — 40 instances updated, 1 tag skipped on `…/Mixer17` (overridden)". A propagation
that cannot be summarised is a propagation nobody will trust.

## 9. Duplication

Two operations, both server-side, both one transaction.

`duplicateAsset` copies any subtree to any parent. `instantiateTemplate` stamps a
template. Both accept `copies` and `namingPattern`.

`namingPattern` supports `{n}` and `{n:0Nd}` — `Line{n}` gives Line1…Line5, `Cell{n:02d}`
gives Cell01…Cell05. Expansion happens server-side; `src/lib/model/naming.ts` reimplements
it only to preview, and that preview is the one piece of frontend logic under test
(section 13).

**All names are validated before any row is written.** Five copies where the third name is
taken creates nothing. A partial batch would leave the engineer to work out which two of
five landed, and `uq_asset_sibling_segment` would surface it as a constraint error rather
than as a name they can fix.

`duplicate_subtree` carries `template_node_id` from source to copy, so duplicating an
instantiated Line yields another instance of the same template rather than a detached
orphan. It does **not** carry `overridden_fields`: a fresh copy has overridden nothing.

## 10. Adopting Unmodelled Topics

`getUnmodelledTopics(under:)` already answers "what is publishing that the model does not
describe" (`repositories.py:289`). The drawer turns each topic into a proposal:

```
CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank/ProcessValue/Temperature
  -> Asset:      CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank   (nearest existing)
     Metric Key: ProcessValue/Temperature/value
```

The nearest existing Asset comes from `ancestors_of(topic)` (`repositories.py:344`). When
there is no ancestor at all, the row offers to create the missing Assets first, at levels
the engineer picks — `specs_for_path` (`repositories.py:402`) already exists for exactly
this shape of problem.

Multi-select, then `adoptUnmodelledTopics` writes the Metric Definitions in one
transaction. This is the fastest honest route from a running plant to a complete model, and
it is how `unmodelled_topics` stops being a number nobody can act on.

## 11. Demoting the seed

`uns_model_seed` stays, with two changes.

1. **It stops pruning.** The `deactivate_*_absent_from` and `delete_*_absent_from` calls
   in `oee_master_data.py:212`–`:266` are no longer invoked by the CLI's default path.
   Reconciliation moves behind an explicit `--reconcile` flag, for a deployment that
   really does want YAML to be authoritative.
2. **It says so.** `--from-simulator-config` prints that Postgres is authoritative and
   that console edits are not represented in `conf/settings.yaml`.

`docker-compose.yml` keeps `asset_model_setup` unchanged: migrate, seed if empty, exit. The
`service_completed_successfully` dependencies of `historian_client`, `graphql_server` and
`uns_grafana` still hold.

`09_uns_model/README.md` loses "Restarting that one service is how the Asset Model is
updated after `conf/settings.yaml` changes" — which stops being true the moment the console
can write.

## 12. What the edge phase must not be foreclosed

Out of scope, but the design is checked against it.

A per-plant edge stack will need the Asset Model for one `SITE` branch as a transferable
artifact. Three properties make that possible later without a migration now:

- `list_assets(under=)` already scopes to a branch, and Metric Definitions are reachable per
  Asset via `metric_definitions_for`. A snapshot is a read, not a new store.
- Asset Templates are referenced by `id` from `asset`, so a snapshot of one Site must carry
  the templates its Assets reference, or flatten them. **The snapshot format decision is
  deferred, and this is the one place the two phases touch.** Recorded here so it is a
  decision and not a surprise.
- The OPC UA connector's `nodes[]` maps `node_id -> asset + metric_path`
  (`10_uns_opcua/README.md`, `conf/settings.yaml`). `metric_path` is a Metric Key without
  its payload leaf, which the tag tables in this spec author directly. Generating that
  config from the model is then a projection, not a new data model.

Nothing in section 6 assumes a single Site, and nothing assumes the console and the model
share a process.

## 13. Testing

Python is TDD per `AGENTS.md`. The repository seam is where the fakes go, following
`test_seed.py` and `test_alert_rules.py`.

`09_uns_model/test/test_asset_templates.py` — pure unit:
- Spec `validate()` rejects an inverted level, a `relative_path` inconsistent with its
  `segment`, a root level that disagrees with `root_level`, and an inverted min/max.
- Projection creates a new node on every instance.
- Projection **skips a column in `overridden_fields`** and reports it in `overrides_skipped`.
- Projection **adopts** an existing unlinked sibling instead of failing.
- A removed node **deactivates and does not delete** — asserted by the row still existing
  with `is_active = false`.
- `delete_template` leaves every instance Asset present with `template_id IS NULL`.

`09_uns_model/test/test_asset_writes.py` — pure unit:
- `rename_asset` rewrites every descendant `path`, and a segment containing `_` does not
  drag a similarly-named sibling with it (finding 4, `starts_with` not `LIKE`).
- `move_asset` refuses to make an Asset its own descendant, and refuses an inverted rank.
- `duplicate_subtree` copies Metric Definitions, carries `template_node_id`, and clears
  `overridden_fields`.
- Naming-pattern expansion for `{n}` and `{n:02d}`; a batch with one taken name writes
  nothing.
- `dependents_of` reports an `oee_unit` and a matching Alert Rule, so the mutation has
  something to refuse with.
- `rebind_all(connection=...)` executes on the passed connection and opens none of its own
  (7.1.1), asserted with a fake that fails if `begin()` is called.

Integration, marked `integrationtest`, extending `test_migrations_asyncpg.py`:
- Migration `0004` upgrades and downgrades cleanly against Timescale.
- Deleting an `asset_template` leaves instance Assets and their `oee_unit` rows intact —
  the `ON DELETE SET NULL` guarantee of section 6.2, asserted against real Postgres
  because it is a constraint claim.
- One end-to-end projection over a real database, asserting `topic_binding` moved as a
  result of `rebind_all()`.
- A projection made to fail after some instances are written leaves **no** structural change
  and **no** `topic_binding` change — the single-transaction guarantee of 7.1.1, asserted
  against real Postgres because it is a transactional claim and a fake cannot prove it.

Frontend: add `vitest` to `devDependencies` and a `test` script (finding 12). One test
file, `src/lib/model/naming.test.ts`, covering pattern expansion and collision preview.
Components stay untested; all structural logic is server-side, which is what makes that
acceptable rather than merely convenient.

## 14. Failure modes

| Failure | Behaviour |
| --- | --- |
| Level inversion, cycle, name collision | Rejected by `validate()` before Postgres, with the offending value in the message. Surfaced inline on the form field. |
| Delete would cascade an OEE unit or orphan Alert Rules | `deleteAsset` refuses, returns `dependents`. `force: true` is the deliberate override. |
| Two engineers save one template | `expectedUpdatedAt` mismatch is refused. Without it, the second save's projection would half-overwrite the first's. |
| Projection fails partway | Whole transaction rolls back, template included. The console reports that nothing changed. |
| Template deleted | Instances keep every row; `template_id` and `template_node_id` go null. |
| Rename leaves Alert Rules behind | Cannot be fixed here — `alert_rules.topic` is free text (finding 8). `renameAsset` returns the matching rules as a warning so the engineer knows to re-point them. |
| Adopt proposes an Asset that does not exist | The row offers to create the branch first; nothing is written until the engineer picks levels. |
| `rebind_all` fails | Same transaction as the write (7.1.1), so the structural change rolls back with it, and the queued `NOTIFY` is never delivered. A stale binding is worse than a rejected edit (ADR-0003). |

## 15. Registration checklist

- `09_uns_model/migrations/versions/0004_asset_templates.py`
- `09_uns_model/src/uns_model/tables.py` — three ORM classes, four columns
- `09_uns_model/src/uns_model/asset_templates.py` — new
- `09_uns_model/src/uns_model/repositories.py` — eight methods, plus the optional
  `connection` parameter on `rebind_all` (7.1.1)
- `09_uns_model/src/uns_model/notifications.py` — optional `connection` parameter on
  `announce_asset_model_changed` (7.1.1)
- `09_uns_model/src/uns_model/__init__.py` — export the new repository and specs
- `09_uns_model/src/uns_model/cli.py` — `--reconcile` flag, authoritative-source notice
- `07_uns_graphql/src/uns_graphql/input/asset.py` — new
- `07_uns_graphql/src/uns_graphql/mutations/asset.py`, `mutations/asset_template.py` — new
- `07_uns_graphql/src/uns_graphql/queries/asset.py`, `type/asset.py` — extended
- `07_uns_graphql/src/uns_graphql/uns_graphql_app.py:68` and `:84` — wiring
- `07_uns_graphql/schema/uns_schema.graphql` — regenerated
- `11_frontend` — the files in 7.4, plus `App.tsx`, `Sidebar.tsx`, `types/rbac.ts`,
  `services/graphql/queries.ts`, `services/graphql/types.ts`
- `11_frontend/package.json` — `vitest`, `test` script
- `CONTEXT.md` — the four terms in section 5
- `09_uns_model/README.md` — the correction in section 11
- `docs/adr/0009-asset-templates-with-live-propagation.md` — new

## 16. Judgement calls open to revision

1. **Live propagation over explicit sync.** Chosen deliberately (section 8.2). If a
   template typo restructures a plant before anyone reviews it, the mitigation is
   `getTemplateDrift` plus a dry-run mutation, not a redesign.
2. **Removals deactivate rather than delete.** This makes a template removal recoverable
   and keeps OEE configuration alive, at the cost of accumulating inactive Assets. A
   "purge inactive" action is deferred until somebody has too many.
3. **`overridden_fields` as `text[]` rather than a side table.** Cheap and local. A side
   table would be needed only to record *who* overrode a field, which nothing asks for
   today — this platform has no authentication (`mutations/oee.py`).
4. **One flat template list, no template inheritance.** A "Mixer Tank" template cannot
   extend a "Vessel" template. Almost certainly wanted eventually; not before the flat
   case is in use.
5. **Plant Scope is a UI filter, not an access boundary.** Honest about what it is. If a
   plant must not see another plant's assets, that is the per-plant RBAC spec and it needs
   a server-side filter, not a dropdown.
6. **Metric removal deletes rather than deactivates**, unlike Asset removal. Justified by
   nothing FK-ing to `metric_definition`, so the loss is a Unit of Measure. If that proves
   wrong, it gets the same `is_active` treatment.
