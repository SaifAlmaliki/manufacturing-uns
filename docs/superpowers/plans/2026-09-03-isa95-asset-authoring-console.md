# ISA-95 Asset Authoring — Console Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the console the screens an engineer uses to author the plant — an Asset Model Explorer with a tag table, duplication from a naming pattern, an Asset Template library, and a drawer that turns Unmodelled Topics into Assets.

**Architecture:** The console is a static bundle with no backend of its own (ADR-0005), so every write is a GraphQL mutation from the plan-1 API and no structural logic lives here. New GraphQL documents go in `services/graphql/queries.ts`, new methods on `UnsGraphQLClient`, shape translation in `lib/model/`, and one new React context (`PlantScopeContext`) holding the Site the session is looking at. Only `lib/model/naming.ts` gets unit tests, because it is the only file with logic the server does not already own.

**Tech Stack:** React 19, TypeScript 5.8, React Router 7 (HashRouter), Tailwind CSS 4, `lucide-react` icons, Vite 6, Vitest (added by Task 1).

**Spec:** `docs/superpowers/specs/2026-09-03-isa95-asset-authoring-design.md`

**Depends on:** `docs/superpowers/plans/2026-09-03-isa95-asset-authoring-model.md`. Every mutation and query this plan calls is created there. Task 2 onwards will fail against a server without it, so run that plan first and regenerate `07_uns_graphql/schema/uns_schema.graphql` — that file is the contract this plan reads.

## Global Constraints

- **Work from `11_frontend/`.** Every `npm` command in this plan runs there. Do not create a venv or a second `node_modules` anywhere else.
- **`npm run lint` is `tsc --noEmit`, and it must stay clean.** There is no ESLint, so this is the only automated guard on components — and it is weaker than it looks: `11_frontend/tsconfig.json` sets neither `strict` nor `noUnusedLocals`. With `strictNullChecks` off, a missing null check compiles, and reading a field off a `null` Asset is a runtime crash `lint` will not report; an unused import passes too. Do not turn `strict` on in this plan — the existing console does not compile under it and fixing that is its own piece of work. So: handle nullability in code (`?.`, `?? null`, an explicit `if (!draft)` branch) rather than relying on the compiler, and treat the types in Task 2 as a contract you are holding yourself to. That is exactly why they are worth getting exactly right.
- **Punctuation follows the directory.** `src/lib/`, `src/services/` and `platform/` are written **without** semicolons and with single quotes. `src/components/`, `src/context/` and `src/types/` are written **with** semicolons. Match the neighbours of the file you are in; do not reformat existing lines.
- **Every file opens with a block comment** saying what it is for and naming any non-obvious decision, in the voice of `src/lib/alarms/map-alert-rules.ts` and `src/context/AlarmContext.tsx`. Not a one-line restatement of the filename.
- **Two spellings that will bite silently:**
  - the schema reads a display name as **`name`** on `AssetNode` (display name if authored, else the segment) and writes it as **`displayName`** on `AssetInput`;
  - `attributes` is read as `attributes { data }` (a `JSONPayload`) and written as a **JSON string** — `JSON.stringify(record)`.
  Both asymmetries are the server's, and `lib/model/map-assets-write.ts` is where the console absorbs them so no component has to remember.
- **Vocabulary, in UI copy as well as in code:** Asset, Asset Level, Asset Template, Template Node, Instance Override, Plant Scope, Metric Definition, **Unit of Measure** (never "unit"), Unmodelled Topic.
- **Never say "unit"** for a Unit of Measure in a label, placeholder or tooltip. `oee_unit` is an OEE Unit and the collision is already confusing enough in the schema.
- **Read-only unless `asset_model_edit`.** Every mutating control is hidden or disabled without it, and the check is `hasPermission('asset_model_edit')` from `useAuth()`. Hiding a button is not security — the server is the guard — but showing an engineer a button that returns an error is worse than not showing it.
- **A projection result is always shown.** Any mutation returning `TemplateProjectionType` renders a `ProjectionResultToast`, including the skipped overrides. Live propagation is only defensible if the console reports it (spec 8.2).
- **A rejected write surfaces where the offending value was chosen** (spec 14). The server's `validate()` puts the offending value in the message, so it is worth showing verbatim. Paths and Asset Levels are only ever chosen in the tree's add/rename/move prompts, the Duplicate and Instantiate modals, and the Template Editor's node fields — those are the places that render it. The Asset detail form shows path and level read-only and therefore never has one of these to show. Name collisions are caught before the round trip by the live preview in the two modals, which is better than a server message because it is visible before pressing anything.
- Icons come from `lucide-react`, which is already a dependency. Do not add an icon library, a form library, a state library, or a GraphQL client library.

## File Structure

New, all under `11_frontend/`:

| File | Responsibility |
| --- | --- |
| `vitest.config.ts` | Test config, separate from `vite.config.ts` so tests do not load platform settings or the dev proxy |
| `src/lib/model/naming.ts` | `{n}` / `{n:0Nd}` expansion and collision preview — the one tested unit |
| `src/lib/model/naming.test.ts` | Its tests |
| `src/lib/model/map-assets-write.ts` | Console shape → `AssetInput` / `MetricDefinitionInput`, including the two asymmetries above |
| `src/lib/model/map-templates.ts` | `GraphqlAssetTemplate` ↔ the editor's working shape |
| `src/context/PlantScopeContext.tsx` | Which Enterprise/Site the session is authoring |
| `src/components/model/AssetModelView.tsx` | Route `/model`: layout, summary header, tree + detail panes |
| `src/components/model/PlantScopeSelector.tsx` | Enterprise/Site picker in the Explorer header |
| `src/components/model/AssetTreeEditor.tsx` | Lazy tree over `getAssetChildren`, with the per-node action menu |
| `src/components/model/AssetDetailForm.tsx` | The authored columns, override badges, revert |
| `src/components/model/AttributeEditor.tsx` | JSONB key/value rows |
| `src/components/model/TagTable.tsx` | Metric Definitions for one Asset, inline CRUD |
| `src/components/model/DuplicateAssetModal.tsx` | Target parent, pattern, copies, live name preview |
| `src/components/model/AdoptTopicsDrawer.tsx` | Unmodelled Topics → proposals → adopt |
| `src/components/model/TemplateLibraryView.tsx` | Route `/model/templates` |
| `src/components/model/TemplateEditor.tsx` | Tree + detail over Template Nodes |
| `src/components/model/TemplateTagTable.tsx` | A Template Node's Metric Definitions |
| `src/components/model/InstantiateTemplateModal.tsx` | Parent, pattern, copies, preview |
| `src/components/model/ProjectionResultToast.tsx` | "40 updated, 1 skipped (overridden)" |

Modified, under `11_frontend/`: `package.json`, `src/services/graphql/types.ts`, `src/services/graphql/queries.ts`, `src/services/graphql/client.ts`, `src/types/rbac.ts`, `src/context/AuthContext.tsx`, `src/App.tsx`, `src/components/layout/Sidebar.tsx`, `README.md`.

Modified at the repo root: `CONTEXT.md` (two glossary entries, Task 11).

---

### Task 1: Vitest, and the one piece of frontend logic worth testing

`namingPattern` expansion happens server-side; this reimplements it **only to preview**, so an engineer sees `Cell01 … Cell05` before pressing a button that writes five subtrees. Because it is a reimplementation, it is the one place in the console where being subtly wrong is invisible until it has written the wrong names — which is exactly what makes it worth a test, and why nothing else here gets one.

**Files:**
- Modify: `11_frontend/package.json`
- Create: `11_frontend/vitest.config.ts`
- Create: `11_frontend/src/lib/model/naming.ts`
- Test: `11_frontend/src/lib/model/naming.test.ts`

**Interfaces:**
- Consumes: nothing. This task is self-contained and needs no server.
- Produces:
  - `expandPattern(pattern: string, count: number, start?: number): string[]`
  - `previewNames(pattern: string, count: number, start: number, taken: Iterable<string>): NamePreview[]`
  - `type NamePreview = { name: string; collides: boolean }`
  - `patternError(pattern: string, count: number): string | null`
  - `hasPlaceholder(pattern: string): boolean` — exported for the tests and for `patternError`; no component needs it, since a component wants the message, not the predicate.

- [ ] **Step 1: Add Vitest**

Run: `npm install --save-dev vitest@^3`

Then add the script to `package.json`, beside `lint`:

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

Create `11_frontend/vitest.config.ts`:

```ts
/**
 * Test config, deliberately separate from vite.config.ts.
 *
 * vite.config.ts calls loadPlatformSettings() at module load and declares the dev
 * proxy; a test run needs neither and should not fail because conf/settings.yaml is
 * absent. `include` is scoped to src/lib because that is the only layer under test —
 * every structural rule lives on the server, so components have nothing to assert
 * that would not be asserting React (see the spec, section 13).
 */

import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/lib/**/*.test.ts'],
  },
})
```

- [ ] **Step 2: Write the failing test**

Create `11_frontend/src/lib/model/naming.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { expandPattern, patternError, previewNames } from './naming'

describe('expandPattern', () => {
  it('counts from one for a bare placeholder', () => {
    expect(expandPattern('Line{n}', 3)).toEqual(['Line1', 'Line2', 'Line3'])
  })

  it('pads to the requested width', () => {
    expect(expandPattern('Cell{n:02d}', 3)).toEqual(['Cell01', 'Cell02', 'Cell03'])
  })

  it('starts where it is told to', () => {
    expect(expandPattern('Line{n:02d}', 2, 10)).toEqual(['Line10', 'Line11'])
  })

  it('does not pad a number wider than the requested width', () => {
    // Cell100 must not become Cell00 — truncating a name silently collides.
    expect(expandPattern('Cell{n:02d}', 1, 100)).toEqual(['Cell100'])
  })

  it('allows a single copy with no placeholder at all', () => {
    expect(expandPattern('Packer', 1)).toEqual(['Packer'])
  })

  it('substitutes every occurrence of the placeholder', () => {
    expect(expandPattern('L{n}_Cell{n}', 2)).toEqual(['L1_Cell1', 'L2_Cell2'])
  })
})

describe('patternError', () => {
  it('rejects more than one copy without a placeholder', () => {
    expect(patternError('Packer', 3)).toMatch(/\{n\}/)
  })

  it('rejects a separator, because a segment is one topic level', () => {
    expect(patternError('Line{n}/Cell1', 1)).toMatch(/\//)
  })

  it('rejects a count below one', () => {
    expect(patternError('Line{n}', 0)).toMatch(/at least one/i)
  })

  it('accepts a valid pattern', () => {
    expect(patternError('Line{n:02d}', 5)).toBeNull()
  })
})

describe('previewNames', () => {
  it('marks the names that are already taken', () => {
    const preview = previewNames('Cell{n}', 3, 1, ['Cell2'])

    expect(preview).toEqual([
      { name: 'Cell1', collides: false },
      { name: 'Cell2', collides: true },
      { name: 'Cell3', collides: false },
    ])
  })

  it('returns an empty preview for an unusable pattern rather than throwing', () => {
    // The preview updates on every keystroke, and 'Line{' is what 'Line{n}' looks
    // like halfway through being typed.
    expect(previewNames('Line{', 3, 1, [])).toEqual([])
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `npm test`
Expected: FAIL — `Failed to resolve import "./naming"`

- [ ] **Step 4: Write the implementation**

Create `11_frontend/src/lib/model/naming.ts`:

```ts
/**
 * Generated Asset names, for previewing a duplication before it is written.
 *
 * The server expands the same pattern in `09_uns_model/src/uns_model/naming.py` and
 * its answer is the one that reaches Postgres. This exists so an engineer sees
 * `Cell01 … Cell05` before pressing a button that creates five subtrees, and it is
 * unit-tested precisely because it is a second implementation of somebody else's
 * rule: a mismatch would be invisible until the wrong names existed.
 *
 * Kept free of React so it can be tested without a DOM.
 */

/** `{n}` or `{n:03d}` — the same two forms the server accepts, and no others. */
const PLACEHOLDER = /\{n(?::0(\d+)d)?\}/g

export type NamePreview = {
  name: string
  collides: boolean
}

/** Whether a pattern contains a placeholder at all. */
export function hasPlaceholder(pattern: string): boolean {
  return new RegExp(PLACEHOLDER.source).test(pattern)
}

/**
 * The reason this pattern cannot be used, or null when it can.
 *
 * Returned as a message rather than thrown: this runs on every keystroke, and a
 * half-typed pattern is not an error worth an exception.
 */
export function patternError(pattern: string, count: number): string | null {
  if (count < 1) {
    return 'Enter at least one copy'
  }
  if (!pattern.trim()) {
    return 'Enter a name'
  }
  if (pattern.includes('/')) {
    return 'A name is one topic segment, so it cannot contain "/"'
  }
  if (count > 1 && !hasPlaceholder(pattern)) {
    return `Add {n} so the ${count} copies get different names, e.g. ${pattern}{n}`
  }
  return null
}

/**
 * The names a pattern produces. Throws only on a pattern `patternError` rejects,
 * so callers that have already checked it can use this directly.
 */
export function expandPattern(pattern: string, count: number, start = 1): string[] {
  const error = patternError(pattern, count)
  if (error) {
    throw new Error(error)
  }
  const names: string[] = []
  for (let index = 0; index < count; index += 1) {
    const n = start + index
    names.push(
      pattern.replace(PLACEHOLDER, (_match, width?: string) =>
        // padStart, not slice: a number wider than the requested width keeps every
        // digit. Truncating Cell100 to Cell00 would collide with Cell00 in silence.
        width ? String(n).padStart(Number(width), '0') : String(n),
      ),
    )
  }
  return names
}

/**
 * The names plus whether each one is already in use, for the modal's live preview.
 * An unusable pattern previews as nothing rather than as an error.
 */
export function previewNames(
  pattern: string,
  count: number,
  start: number,
  taken: Iterable<string>,
): NamePreview[] {
  if (patternError(pattern, count)) {
    return []
  }
  const existing = new Set(taken)
  return expandPattern(pattern, count, start).map((name) => ({
    name,
    collides: existing.has(name),
  }))
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm test`
Expected: PASS, 12 tests.

Run: `npm run lint`
Expected: clean. If `tsc` reports that it cannot find `vitest/config` types, add `"types": ["vitest/globals"]` is **not** the fix — the test file imports `describe`/`it`/`expect` explicitly for exactly this reason. Check instead that `vitest` installed into `devDependencies`.

- [ ] **Step 6: Commit**

```bash
git add 11_frontend/package.json 11_frontend/package-lock.json 11_frontend/vitest.config.ts 11_frontend/src/lib/model/naming.ts 11_frontend/src/lib/model/naming.test.ts
git commit -m "test(frontend): add vitest and the Asset naming-pattern preview it covers"
```

---

### Task 2: The GraphQL contract — types, documents, client methods

Everything after this task is a component reading these. Getting a field name wrong here surfaces as `undefined` on a screen, three tasks later, so this task is where the regenerated SDL is read carefully.

**Files:**
- Modify: `11_frontend/src/services/graphql/types.ts`
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/services/graphql/client.ts`
- Create: `11_frontend/src/lib/model/map-assets-write.ts`
- Create: `11_frontend/src/lib/model/map-templates.ts`

**Interfaces:**
- Consumes: the mutations and queries from plan 1 — `saveAsset`, `renameAsset`, `moveAsset`, `setAssetActive`, `deleteAsset`, `duplicateAsset`, `saveMetricDefinition`, `deleteMetricDefinition`, `adoptUnmodelledTopics`, `saveAssetTemplate`, `deleteAssetTemplate`, `instantiateTemplate`, `propagateAssetTemplate`, `revertToTemplate`, `getAssetTemplates`, `getAssetTemplate`, `getTemplateDrift`, `getMetricDefinitions`, `getUnmodelledTopics(limit, under)`, `getAssetModelSummary`, `getAssetChildren`.
- Produces:
  - types `GraphqlAssetTemplate`, `GraphqlTemplateNode`, `GraphqlTemplateMetric`, `GraphqlTemplateProjection`, `GraphqlSkippedOverride`, `GraphqlInstanceDrift`, `GraphqlAssetDependents`, `GraphqlDeleteAssetResult`, `GraphqlRenameResult`; `GraphqlAssetNode` and `GraphqlMetricDefinition` gain fields.
  - `assetToInput(asset: AssetDraft): Record<string, unknown>`, `metricToInput(metric: MetricDraft): Record<string, unknown>`, `type AssetDraft`, `type MetricDraft`
  - `templateToInput(template: TemplateDraft): Record<string, unknown>`, `graphqlTemplateToDraft(template: GraphqlAssetTemplate): TemplateDraft`, `parentRelativePath`, `childrenOf`, `newTemplateNode`, `newTemplateRoot`, `rootNodeOf`, `type TemplateDraft`, `type TemplateNodeDraft`, `type TemplateMetricDraft`
  - on `UnsGraphQLClient`: `getAssetChildren` widened from `private` to `public` (`client.ts:251`) — same query, same `GraphqlAssetNode[]`, so the tree editor needs no second accessor; plus `saveAsset`, `renameAsset`, `moveAsset`, `setAssetActive`, `deleteAsset`, `duplicateAsset`, `getMetricDefinitions`, `saveMetricDefinition`, `deleteMetricDefinition`, `getUnmodelledTopics`, `adoptUnmodelledTopics`, `getAssetTemplates`, `getAssetTemplate`, `saveAssetTemplate`, `deleteAssetTemplate`, `instantiateTemplate`, `propagateAssetTemplate`, `revertToTemplate`, `getTemplateDrift`, `getAssetModelSummary`

- [ ] **Step 1: Read the contract**

Run: `git -C .. diff HEAD -- 07_uns_graphql/schema/uns_schema.graphql | head -200`
Expected: the mutations and types listed above. If this shows nothing, plan 1 has not been run or its SDL was not regenerated — stop and do that first. Every field name below must be checked against this output, not against this plan.

- [ ] **Step 2: Extend the types**

In `11_frontend/src/services/graphql/types.ts`, add three fields to `GraphqlAssetNode`:

```ts
  templateId?: number | null
  templateName?: string | null
  /** Fields edited locally. An Asset Template edit will not overwrite these. */
  overriddenFields?: string[]
```

and two to `GraphqlMetricDefinition`:

```ts
  decimals?: number | null
  deadband?: number | null
  isOverridden?: boolean
```

Then append:

```ts
/** One Metric Definition a Template Node declares, before it belongs to any Asset. */
export type GraphqlTemplateMetric = {
  metricKey: string
  displayName?: string | null
  unitOfMeasure?: string | null
  decimals?: number | null
  minValue?: number | null
  maxValue?: number | null
  deadband?: number | null
  description?: string | null
}

/**
 * One Asset within an Asset Template. `relativePath` is '' for the root, so a
 * template holds no absolute path and can be placed anywhere its Asset Level allows.
 */
export type GraphqlTemplateNode = {
  id?: number | null
  relativePath: string
  segment: string
  level: string
  displayName?: string | null
  description?: string | null
  attributes?: { data: unknown } | null
  metrics: GraphqlTemplateMetric[]
}

export type GraphqlAssetTemplate = {
  id: number
  name: string
  description?: string | null
  rootLevel: string
  instanceCount: number
  updatedAt?: string | null
  /** Empty on the library screen: getAssetTemplates does not load nodes. */
  nodes: GraphqlTemplateNode[]
}

/** A field a projection refused to overwrite because an engineer owns it. */
export type GraphqlSkippedOverride = {
  assetPath: string
  fieldName: string
}

/** What one save or propagation actually did. Always shown; see spec 8.2. */
export type GraphqlTemplateProjection = {
  assetsCreated: number
  assetsUpdated: number
  assetsDeactivated: number
  metricsWritten: number
  metricsDeleted: number
  overridesSkipped: GraphqlSkippedOverride[]
}

/** How far one instance has diverged from the Asset Template that made it. */
export type GraphqlInstanceDrift = {
  assetPath: string
  overriddenFields: string[]
  missingNodes: string[]
  extraNodes: string[]
  overriddenMetrics: string[]
  hasDrifted: boolean
}

/**
 * What deleting an Asset would take with it. `alertRules` is the sharp edge:
 * `alert_rules.topic` is free text, so nothing rewrites or cascades it.
 */
export type GraphqlAssetDependents = {
  descendants: number
  oeeUnits: number
  shiftPatterns: number
  shiftExceptions: number
  idealCycleTimes: number
  alertRules: string[]
  total: number
}

export type GraphqlDeleteAssetResult = {
  removed: boolean
  /** True when the server declined and returned dependents instead of deleting. */
  refused: boolean
  dependents: GraphqlAssetDependents
}

export type GraphqlRenameResult = {
  path: string
  assetsUpdated: number
  /** Alert Rules still naming the old path. A warning, not an error. */
  alertRules: string[]
}

export type GraphqlAssetModelSummary = {
  assets: number
  metricDefinitions: number
  boundTopics: number
  unmodelledTopics: number
}
```

`getAssetModelSummary` already exists server-side (`07_uns_graphql/src/uns_graphql/queries/asset.py:115`) but the console has never read it, so the type above is new here.

- [ ] **Step 3: Add the documents**

In `11_frontend/src/services/graphql/queries.ts`, extend the existing `ASSET_FIELDS` constant with the three new fields (they are additive, so every existing query that uses it keeps working and gains them):

```
  templateId
  templateName
  overriddenFields
```

and `METRIC_DEFINITION_FIELDS` with:

```
  decimals
  deadband
  isOverridden
```

Then append:

```ts
const TEMPLATE_METRIC_FIELDS = `
  metricKey
  displayName
  unitOfMeasure
  decimals
  minValue
  maxValue
  deadband
  description
`

const TEMPLATE_NODE_FIELDS = `
  id
  relativePath
  segment
  level
  displayName
  description
  attributes {
    data
  }
  metrics {
    ${TEMPLATE_METRIC_FIELDS}
  }
`

const PROJECTION_FIELDS = `
  assetsCreated
  assetsUpdated
  assetsDeactivated
  metricsWritten
  metricsDeleted
  overridesSkipped {
    assetPath
    fieldName
  }
`

const DEPENDENTS_FIELDS = `
  descendants
  oeeUnits
  shiftPatterns
  shiftExceptions
  idealCycleTimes
  alertRules
  total
`

export const SAVE_ASSET_MUTATION = `
  mutation SaveAsset($asset: AssetInput!) {
    saveAsset(asset: $asset) {
      ${ASSET_FIELDS}
    }
  }
`

export const RENAME_ASSET_MUTATION = `
  mutation RenameAsset($path: String!, $segment: String!) {
    renameAsset(path: $path, segment: $segment) {
      path
      assetsUpdated
      alertRules
    }
  }
`

export const MOVE_ASSET_MUTATION = `
  mutation MoveAsset($path: String!, $newParentPath: String!) {
    moveAsset(path: $path, newParentPath: $newParentPath) {
      path
      assetsUpdated
      alertRules
    }
  }
`

export const SET_ASSET_ACTIVE_MUTATION = `
  mutation SetAssetActive($path: String!, $isActive: Boolean!) {
    setAssetActive(path: $path, isActive: $isActive)
  }
`

export const DELETE_ASSET_MUTATION = `
  mutation DeleteAsset($path: String!, $force: Boolean!) {
    deleteAsset(path: $path, force: $force) {
      removed
      refused
      dependents {
        ${DEPENDENTS_FIELDS}
      }
    }
  }
`

export const DUPLICATE_ASSET_MUTATION = `
  mutation DuplicateAsset(
    $sourcePath: String!
    $targetParentPath: String!
    $namingPattern: String!
    $copies: Int!
    $start: Int!
  ) {
    duplicateAsset(
      sourcePath: $sourcePath
      targetParentPath: $targetParentPath
      namingPattern: $namingPattern
      copies: $copies
      start: $start
    ) {
      ${ASSET_FIELDS}
    }
  }
`

export const GET_METRIC_DEFINITIONS_QUERY = `
  query GetMetricDefinitions($assetPath: String!) {
    getMetricDefinitions(assetPath: $assetPath) {
      ${METRIC_DEFINITION_FIELDS}
    }
  }
`

export const SAVE_METRIC_DEFINITION_MUTATION = `
  mutation SaveMetricDefinition($metric: MetricDefinitionInput!) {
    saveMetricDefinition(metric: $metric) {
      ${METRIC_DEFINITION_FIELDS}
    }
  }
`

export const DELETE_METRIC_DEFINITION_MUTATION = `
  mutation DeleteMetricDefinition($metricKey: String!, $assetPath: String) {
    deleteMetricDefinition(metricKey: $metricKey, assetPath: $assetPath)
  }
`

export const GET_UNMODELLED_TOPICS_QUERY = `
  query GetUnmodelledTopics($limit: Int!, $under: String) {
    getUnmodelledTopics(limit: $limit, under: $under)
  }
`

export const ADOPT_UNMODELLED_TOPICS_MUTATION = `
  mutation AdoptUnmodelledTopics($topics: [AdoptTopicInput!]!) {
    adoptUnmodelledTopics(topics: $topics) {
      ${ASSET_FIELDS}
    }
  }
`

export const GET_ASSET_TEMPLATES_QUERY = `
  query GetAssetTemplates {
    getAssetTemplates {
      id
      name
      description
      rootLevel
      instanceCount
      updatedAt
    }
  }
`

export const GET_ASSET_TEMPLATE_QUERY = `
  query GetAssetTemplate($templateId: Int!) {
    getAssetTemplate(templateId: $templateId) {
      id
      name
      description
      rootLevel
      instanceCount
      updatedAt
      nodes {
        ${TEMPLATE_NODE_FIELDS}
      }
    }
  }
`

export const SAVE_ASSET_TEMPLATE_MUTATION = `
  mutation SaveAssetTemplate($template: AssetTemplateInput!, $expectedUpdatedAt: DateTime) {
    saveAssetTemplate(template: $template, expectedUpdatedAt: $expectedUpdatedAt) {
      ${PROJECTION_FIELDS}
    }
  }
`

export const DELETE_ASSET_TEMPLATE_MUTATION = `
  mutation DeleteAssetTemplate($templateId: Int!) {
    deleteAssetTemplate(templateId: $templateId)
  }
`

export const INSTANTIATE_TEMPLATE_MUTATION = `
  mutation InstantiateTemplate(
    $templateId: Int!
    $parentPath: String!
    $namingPattern: String!
    $copies: Int!
    $start: Int!
  ) {
    instantiateTemplate(
      templateId: $templateId
      parentPath: $parentPath
      namingPattern: $namingPattern
      copies: $copies
      start: $start
    ) {
      ${ASSET_FIELDS}
    }
  }
`

export const PROPAGATE_ASSET_TEMPLATE_MUTATION = `
  mutation PropagateAssetTemplate($templateId: Int!) {
    propagateAssetTemplate(templateId: $templateId) {
      ${PROJECTION_FIELDS}
    }
  }
`

export const REVERT_TO_TEMPLATE_MUTATION = `
  mutation RevertToTemplate($assetPath: String!) {
    revertToTemplate(assetPath: $assetPath) {
      ${PROJECTION_FIELDS}
    }
  }
`

export const GET_TEMPLATE_DRIFT_QUERY = `
  query GetTemplateDrift($templateId: Int!) {
    getTemplateDrift(templateId: $templateId) {
      assetPath
      overriddenFields
      missingNodes
      extraNodes
      overriddenMetrics
      hasDrifted
    }
  }
`
```

Check the scalar name for `expectedUpdatedAt` against the SDL from Step 1 — Strawberry may spell it `DateTime`. Use whatever the SDL says; a wrong scalar name is rejected before the resolver runs.

- [ ] **Step 4: Write the write-side mapping**

Create `11_frontend/src/lib/model/map-assets-write.ts`:

```ts
/**
 * Console shape to GraphQL input, for the Asset Model's writes.
 *
 * This file exists to absorb two asymmetries in the schema so that no component has
 * to remember them:
 *
 *  - an Asset's display name is read as `name` (display name if one was authored,
 *    otherwise the segment) and written as `displayName`. Reading `name` back into a
 *    form and saving it would turn every segment into an authored display name;
 *  - `attributes` is read as a `JSONPayload` (`attributes { data }`) and written as a
 *    JSON *string*, matching how `thresholdValue` already crosses the same boundary.
 *
 * `undefined` and `null` are also not interchangeable here: a field left out is
 * unchanged, and an explicit null clears it. The drafts below carry `null` on purpose.
 */

import type { GraphqlAssetNode, GraphqlMetricDefinition } from '../../services/graphql/types'

export type AssetDraft = {
  path: string
  level: string
  displayName: string | null
  description: string | null
  manufacturer: string | null
  modelNumber: string | null
  serialNumber: string | null
  criticality: string | null
  commissionedOn: string | null
  attributes: Record<string, string>
  isActive: boolean
}

export type MetricDraft = {
  metricKey: string
  assetPath: string | null
  displayName: string | null
  unitOfMeasure: string | null
  decimals: number | null
  minValue: number | null
  maxValue: number | null
  deadband: number | null
  description: string | null
}

/** A record of plain strings, from whatever JSONB the server sent. */
export function attributesOf(asset: Pick<GraphqlAssetNode, 'attributes'>): Record<string, string> {
  const raw = asset.attributes?.data
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {}
  }
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>).map(([key, value]) => [
      key,
      typeof value === 'string' ? value : JSON.stringify(value),
    ]),
  )
}

/**
 * A form draft from a loaded Asset. `displayName` is null when the server's `name`
 * is just the segment, so opening a form and saving it authors nothing new.
 */
export function draftFromAsset(asset: GraphqlAssetNode): AssetDraft {
  return {
    path: asset.path,
    level: asset.level,
    displayName: asset.name === asset.segment ? null : asset.name,
    description: asset.description ?? null,
    manufacturer: asset.manufacturer ?? null,
    modelNumber: asset.modelNumber ?? null,
    serialNumber: asset.serialNumber ?? null,
    criticality: asset.criticality ?? null,
    commissionedOn: null,
    attributes: attributesOf(asset),
    isActive: asset.isActive,
  }
}

export function assetToInput(draft: AssetDraft): Record<string, unknown> {
  return {
    path: draft.path,
    level: draft.level,
    displayName: draft.displayName,
    description: draft.description,
    manufacturer: draft.manufacturer,
    modelNumber: draft.modelNumber,
    serialNumber: draft.serialNumber,
    criticality: draft.criticality,
    commissionedOn: draft.commissionedOn,
    attributes: JSON.stringify(draft.attributes),
    isActive: draft.isActive,
  }
}

export function draftFromMetric(
  metric: GraphqlMetricDefinition,
  assetPath: string | null,
): MetricDraft {
  return {
    metricKey: metric.metricKey,
    assetPath,
    displayName: metric.displayName ?? null,
    unitOfMeasure: metric.unitOfMeasure ?? null,
    decimals: metric.decimals ?? null,
    minValue: metric.minValue ?? null,
    maxValue: metric.maxValue ?? null,
    deadband: metric.deadband ?? null,
    description: null,
  }
}

export function metricToInput(draft: MetricDraft): Record<string, unknown> {
  return { ...draft }
}
```

- [ ] **Step 5: Write the template mapping**

Create `11_frontend/src/lib/model/map-templates.ts`:

```ts
/**
 * An Asset Template as the editor holds it, and as the server takes it.
 *
 * The editor works on a flat list of nodes keyed by `relativePath` rather than a
 * nested tree, for the same reason `model.asset` stores a path: a flat list with a
 * path per row is easy to reorder, easy to diff, and impossible to leave with a
 * dangling child. The tree is derived for rendering only, in `childrenOf`.
 */

import type {
  GraphqlAssetTemplate,
  GraphqlTemplateMetric,
  GraphqlTemplateNode,
} from '../../services/graphql/types'

export type TemplateMetricDraft = GraphqlTemplateMetric

export type TemplateNodeDraft = {
  relativePath: string
  segment: string
  level: string
  displayName: string | null
  description: string | null
  attributes: Record<string, string>
  metrics: TemplateMetricDraft[]
}

export type TemplateDraft = {
  id: number | null
  name: string
  description: string | null
  rootLevel: string
  /** As loaded. Sent back as `expectedUpdatedAt` so a concurrent edit is refused. */
  loadedUpdatedAt: string | null
  nodes: TemplateNodeDraft[]
}

/** '' for the root, otherwise everything before the last '/'. */
export function parentRelativePath(relativePath: string): string | null {
  if (relativePath === '') {
    return null
  }
  const cut = relativePath.lastIndexOf('/')
  return cut === -1 ? '' : relativePath.slice(0, cut)
}

/** Direct children of one node, in segment order. Rendering only. */
export function childrenOf(
  nodes: TemplateNodeDraft[],
  relativePath: string,
): TemplateNodeDraft[] {
  return nodes
    .filter((node) => parentRelativePath(node.relativePath) === relativePath)
    .sort((left, right) => left.segment.localeCompare(right.segment))
}

function attributesOfNode(node: GraphqlTemplateNode): Record<string, string> {
  const raw = node.attributes?.data
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {}
  }
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>).map(([key, value]) => [
      key,
      typeof value === 'string' ? value : JSON.stringify(value),
    ]),
  )
}

export function graphqlTemplateToDraft(template: GraphqlAssetTemplate): TemplateDraft {
  return {
    id: template.id,
    name: template.name,
    description: template.description ?? null,
    rootLevel: template.rootLevel,
    loadedUpdatedAt: template.updatedAt ?? null,
    nodes: template.nodes.map((node) => ({
      relativePath: node.relativePath,
      segment: node.segment,
      level: node.level,
      displayName: node.displayName ?? null,
      description: node.description ?? null,
      attributes: attributesOfNode(node),
      metrics: node.metrics.map((metric) => ({ ...metric })),
    })),
  }
}

export function templateToInput(draft: TemplateDraft): Record<string, unknown> {
  return {
    id: draft.id,
    name: draft.name,
    description: draft.description,
    rootLevel: draft.rootLevel,
    nodes: draft.nodes.map((node) => ({
      relativePath: node.relativePath,
      segment: node.segment,
      level: node.level,
      displayName: node.displayName,
      description: node.description,
      attributes: JSON.stringify(node.attributes),
      metrics: node.metrics.map((metric) => ({ ...metric })),
    })),
  }
}

/**
 * A new node under `parent`, where `parent` is a relativePath and '' means the root.
 * `relativePath` is derived from the segment, never typed separately — the server
 * rejects a mismatch and there is no reading of the pair where they should differ.
 */
export function newTemplateNode(
  parent: string,
  segment: string,
  level: string,
): TemplateNodeDraft {
  return {
    relativePath: parent === '' ? segment : `${parent}/${segment}`,
    segment,
    level,
    displayName: null,
    description: null,
    attributes: {},
    metrics: [],
  }
}

/**
 * The root node, which `newTemplateNode` cannot express: the root's relativePath is ''
 * while a child of the root has a relativePath equal to its segment, so the two cases
 * are genuinely different rather than one being a special value of the other.
 *
 * Its `segment` is a placeholder. Instantiation names the instance root from the
 * naming pattern, so what is stored here only shows in the template editor — but the
 * server requires exactly one root node whose level equals the template's rootLevel,
 * so a template cannot be created without it.
 */
export function newTemplateRoot(segment: string, level: string): TemplateNodeDraft {
  return {
    relativePath: '',
    segment,
    level,
    displayName: null,
    description: null,
    attributes: {},
    metrics: [],
  }
}

/** The root node of a draft, if it has one. */
export function rootNodeOf(draft: TemplateDraft): TemplateNodeDraft | undefined {
  return draft.nodes.find((node) => node.relativePath === '')
}
```

- [ ] **Step 6: Add the client methods**

First, change `private async getAssetChildren` at `11_frontend/src/services/graphql/client.ts:251` to `public async getAssetChildren`. It already returns exactly what the tree editor needs; it is private only because nothing outside the client had asked yet, and a second method issuing the same query would drift from it.

Then add the imports for the new documents and types, and add these methods to `UnsGraphQLClient` beside the Alert Rule ones. They follow that pattern exactly: `executeQuery`, throw on error for a write, return a safe empty value for a read.

```ts
  // ---- Asset Model authoring (ADR-0009) -----------------------------------------
  //
  // Reads return an empty value on failure so a screen renders; writes throw so the
  // form can show what the server refused.

  public async saveAsset(input: Record<string, unknown>): Promise<GraphqlAssetNode> {
    const res = await this.executeQuery<{ saveAsset: GraphqlAssetNode }>(SAVE_ASSET_MUTATION, {
      asset: input,
    })
    if (res.error || !res.data?.saveAsset) {
      throw new Error(res.error || 'Asset was not saved')
    }
    return res.data.saveAsset
  }

  public async renameAsset(path: string, segment: string): Promise<GraphqlRenameResult> {
    const res = await this.executeQuery<{ renameAsset: GraphqlRenameResult }>(
      RENAME_ASSET_MUTATION,
      { path, segment },
    )
    if (res.error || !res.data?.renameAsset) {
      throw new Error(res.error || 'Asset was not renamed')
    }
    return res.data.renameAsset
  }

  public async moveAsset(path: string, newParentPath: string): Promise<GraphqlRenameResult> {
    const res = await this.executeQuery<{ moveAsset: GraphqlRenameResult }>(MOVE_ASSET_MUTATION, {
      path,
      newParentPath,
    })
    if (res.error || !res.data?.moveAsset) {
      throw new Error(res.error || 'Asset was not moved')
    }
    return res.data.moveAsset
  }

  public async setAssetActive(path: string, isActive: boolean): Promise<number> {
    const res = await this.executeQuery<{ setAssetActive: number }>(SET_ASSET_ACTIVE_MUTATION, {
      path,
      isActive,
    })
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.setAssetActive ?? 0
  }

  public async deleteAsset(path: string, force: boolean): Promise<GraphqlDeleteAssetResult> {
    const res = await this.executeQuery<{ deleteAsset: GraphqlDeleteAssetResult }>(
      DELETE_ASSET_MUTATION,
      { path, force },
    )
    if (res.error || !res.data?.deleteAsset) {
      throw new Error(res.error || 'Asset was not deleted')
    }
    return res.data.deleteAsset
  }

  public async duplicateAsset(
    sourcePath: string,
    targetParentPath: string,
    namingPattern: string,
    copies: number,
    start: number,
  ): Promise<GraphqlAssetNode[]> {
    const res = await this.executeQuery<{ duplicateAsset: GraphqlAssetNode[] }>(
      DUPLICATE_ASSET_MUTATION,
      { sourcePath, targetParentPath, namingPattern, copies, start },
    )
    if (res.error || !res.data?.duplicateAsset) {
      throw new Error(res.error || 'Asset was not duplicated')
    }
    return res.data.duplicateAsset
  }

  public async getMetricDefinitions(assetPath: string): Promise<GraphqlMetricDefinition[]> {
    const res = await this.executeQuery<{ getMetricDefinitions: GraphqlMetricDefinition[] }>(
      GET_METRIC_DEFINITIONS_QUERY,
      { assetPath },
    )
    return res.data?.getMetricDefinitions ?? []
  }

  public async saveMetricDefinition(
    input: Record<string, unknown>,
  ): Promise<GraphqlMetricDefinition> {
    const res = await this.executeQuery<{ saveMetricDefinition: GraphqlMetricDefinition }>(
      SAVE_METRIC_DEFINITION_MUTATION,
      { metric: input },
    )
    if (res.error || !res.data?.saveMetricDefinition) {
      throw new Error(res.error || 'Metric Definition was not saved')
    }
    return res.data.saveMetricDefinition
  }

  public async deleteMetricDefinition(
    metricKey: string,
    assetPath: string | null,
  ): Promise<boolean> {
    const res = await this.executeQuery<{ deleteMetricDefinition: boolean }>(
      DELETE_METRIC_DEFINITION_MUTATION,
      { metricKey, assetPath },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.deleteMetricDefinition === true
  }

  public async getUnmodelledTopics(limit: number, under: string | null): Promise<string[]> {
    const res = await this.executeQuery<{ getUnmodelledTopics: string[] }>(
      GET_UNMODELLED_TOPICS_QUERY,
      { limit, under },
    )
    return res.data?.getUnmodelledTopics ?? []
  }

  public async adoptUnmodelledTopics(
    topics: Record<string, unknown>[],
  ): Promise<GraphqlAssetNode[]> {
    const res = await this.executeQuery<{ adoptUnmodelledTopics: GraphqlAssetNode[] }>(
      ADOPT_UNMODELLED_TOPICS_MUTATION,
      { topics },
    )
    if (res.error || !res.data?.adoptUnmodelledTopics) {
      throw new Error(res.error || 'No topic was adopted')
    }
    return res.data.adoptUnmodelledTopics
  }

  public async getAssetTemplates(): Promise<GraphqlAssetTemplate[]> {
    const res = await this.executeQuery<{ getAssetTemplates: GraphqlAssetTemplate[] }>(
      GET_ASSET_TEMPLATES_QUERY,
    )
    return (res.data?.getAssetTemplates ?? []).map((template) => ({ ...template, nodes: [] }))
  }

  public async getAssetTemplate(templateId: number): Promise<GraphqlAssetTemplate | null> {
    const res = await this.executeQuery<{ getAssetTemplate: GraphqlAssetTemplate | null }>(
      GET_ASSET_TEMPLATE_QUERY,
      { templateId },
    )
    return res.data?.getAssetTemplate ?? null
  }

  public async saveAssetTemplate(
    input: Record<string, unknown>,
    expectedUpdatedAt: string | null,
  ): Promise<GraphqlTemplateProjection> {
    const res = await this.executeQuery<{ saveAssetTemplate: GraphqlTemplateProjection }>(
      SAVE_ASSET_TEMPLATE_MUTATION,
      { template: input, expectedUpdatedAt },
    )
    if (res.error || !res.data?.saveAssetTemplate) {
      throw new Error(res.error || 'Asset Template was not saved')
    }
    return res.data.saveAssetTemplate
  }

  public async deleteAssetTemplate(templateId: number): Promise<boolean> {
    const res = await this.executeQuery<{ deleteAssetTemplate: boolean }>(
      DELETE_ASSET_TEMPLATE_MUTATION,
      { templateId },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.deleteAssetTemplate === true
  }

  public async instantiateTemplate(
    templateId: number,
    parentPath: string,
    namingPattern: string,
    copies: number,
    start: number,
  ): Promise<GraphqlAssetNode[]> {
    const res = await this.executeQuery<{ instantiateTemplate: GraphqlAssetNode[] }>(
      INSTANTIATE_TEMPLATE_MUTATION,
      { templateId, parentPath, namingPattern, copies, start },
    )
    if (res.error || !res.data?.instantiateTemplate) {
      throw new Error(res.error || 'Asset Template was not instantiated')
    }
    return res.data.instantiateTemplate
  }

  public async propagateAssetTemplate(templateId: number): Promise<GraphqlTemplateProjection> {
    const res = await this.executeQuery<{ propagateAssetTemplate: GraphqlTemplateProjection }>(
      PROPAGATE_ASSET_TEMPLATE_MUTATION,
      { templateId },
    )
    if (res.error || !res.data?.propagateAssetTemplate) {
      throw new Error(res.error || 'Asset Template was not propagated')
    }
    return res.data.propagateAssetTemplate
  }

  public async revertToTemplate(assetPath: string): Promise<GraphqlTemplateProjection> {
    const res = await this.executeQuery<{ revertToTemplate: GraphqlTemplateProjection }>(
      REVERT_TO_TEMPLATE_MUTATION,
      { assetPath },
    )
    if (res.error || !res.data?.revertToTemplate) {
      throw new Error(res.error || 'Asset was not reverted')
    }
    return res.data.revertToTemplate
  }

  public async getTemplateDrift(templateId: number): Promise<GraphqlInstanceDrift[]> {
    const res = await this.executeQuery<{ getTemplateDrift: GraphqlInstanceDrift[] }>(
      GET_TEMPLATE_DRIFT_QUERY,
      { templateId },
    )
    return res.data?.getTemplateDrift ?? []
  }
```

The Explorer header needs the summary, which no console code has read yet. Add its document to `queries.ts`:

```ts
export const GET_ASSET_MODEL_SUMMARY_QUERY = `
  query GetAssetModelSummary {
    getAssetModelSummary {
      assets
      metricDefinitions
      boundTopics
      unmodelledTopics
    }
  }
`
```

and its method, returning `null` on failure so a header renders without counts rather than not at all:

```ts
  public async getAssetModelSummary(): Promise<GraphqlAssetModelSummary | null> {
    const res = await this.executeQuery<{ getAssetModelSummary: GraphqlAssetModelSummary }>(
      GET_ASSET_MODEL_SUMMARY_QUERY,
    )
    return res.data?.getAssetModelSummary ?? null
  }
```

- [ ] **Step 7: Check it compiles**

Run: `npm run lint`
Expected: clean. Every error here is a field name that does not match the SDL from Step 1 — fix the console, not the schema.

Run: `npm test`
Expected: PASS, unchanged from Task 1.

- [ ] **Step 8: Commit**

```bash
git add 11_frontend/src/services/graphql/types.ts 11_frontend/src/services/graphql/queries.ts 11_frontend/src/services/graphql/client.ts 11_frontend/src/lib/model/map-assets-write.ts 11_frontend/src/lib/model/map-templates.ts
git commit -m "feat(frontend): add the Asset Model authoring GraphQL contract and its mappings"
```

---

### Task 3: Plant Scope, permissions, route, and the projection toast

The scaffolding every screen needs: which Site the session is authoring, whether this user may write, how to reach the screens, and one shared way to report what a projection did. No Asset editing yet — this task ends with a route that renders a stub and is correctly gated, which is verifiable on its own in the browser.

`PlantScopeContext` earns its place because Plant Scope is read by the tree, the duplicate modal, the adopt drawer *and* the instantiate modal, and the point of the spec is one console serving many plants (spec 3). Keeping it in `AssetModelView` state would mean threading it through four component trees and losing it on every navigation.

**Files:**
- Create: `11_frontend/src/context/PlantScopeContext.tsx`
- Create: `11_frontend/src/components/model/ProjectionResultToast.tsx`
- Create: `11_frontend/src/components/model/AssetModelView.tsx` (stub, replaced in Task 4)
- Modify: `11_frontend/src/types/rbac.ts`
- Modify: `11_frontend/src/context/AuthContext.tsx:140-151`, `:405-409`
- Modify: `11_frontend/src/App.tsx`
- Modify: `11_frontend/src/components/layout/Sidebar.tsx:61-71`

**Interfaces:**
- Consumes: `client.getAssetChildren`, `GraphqlAssetNode`, `GraphqlTemplateProjection` from Task 2.
- Produces:
  - `usePlantScope(): { enterprise: string | null; site: string | null; scopePath: string | null; enterprises: GraphqlAssetNode[]; sites: GraphqlAssetNode[]; setEnterprise(path: string | null): void; setSite(path: string | null): void; isLoading: boolean; reload(): void }`
  - `<PlantScopeProvider>`
  - `<ProjectionResultToast projection={GraphqlTemplateProjection | null} onDismiss={() => void} />`
  - `FeatureKey` values `'asset_model'` and `'asset_model_edit'`
  - route path `/model`, tab id `'model'`, component `AssetModelView`

- [ ] **Step 1: Add the two feature keys**

In `11_frontend/src/types/rbac.ts`, add to the `FeatureKey` union after `'alarms'`:

```ts
  | 'asset_model'
  | 'asset_model_edit'
```

Add to `SYSTEM_FEATURES`, after the `alarms` entry:

```ts
  {
    key: 'asset_model',
    label: 'Asset Model Explorer',
    description: 'Browse the authored ISA-95 plant hierarchy, its Metric Definitions, and its Asset Templates',
    category: 'Core Navigation',
  },
  {
    key: 'asset_model_edit',
    label: 'Asset Model Authoring',
    description: 'Create, rename, move, duplicate and deactivate Assets, edit Metric Definitions, and manage Asset Templates',
    category: 'System & Admin',
  },
```

Then add two lines to **all five** `defaultPermissions` blocks in `ROLE_CONFIGS`. The type is `Record<FeatureKey, boolean>`, so missing one is a compile error — which is the point of doing it here rather than discovering it in Task 4:

| Role | `asset_model` | `asset_model_edit` |
| --- | --- | --- |
| admin | `true` | `true` |
| engineer | `true` | `true` |
| operator | `true` | `false` |
| auditor | `true` | `false` |
| viewer | `false` | `false` |

The engineer authors the plant; the operator and the auditor read it (an auditor needs to see what the model claimed at all); the viewer gets only the live tree.

- [ ] **Step 2: Backfill the keys for users already in localStorage**

`AuthContext` persists `users` to `localStorage` and restores them verbatim (`AuthContext.tsx:140-151`), and `getUserPermission` is `!!user.customPermissions?.[feature]` — so a record saved before Step 1 has no `asset_model` key, an absent key reads as denied, and every engineer with an existing session would see "Access Restricted" until they cleared browser storage. Backfill on load:

```ts
  const [users, setUsers] = useState<UserAccount[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.USERS);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed.map(withNewFeatureDefaults);
      }
    } catch {
      // ignore
    }
    return INITIAL_USERS;
  });
```

and define the helper immediately above `AuthProvider`:

```ts
/**
 * Fills in feature keys added since a user record was persisted.
 *
 * Permissions live in localStorage, so a record written by an older console has no
 * entry for a newly added FeatureKey — and an absent entry reads as denied. Falling
 * back to the role's default means shipping a feature does not silently lock out the
 * role meant to have it. An explicitly revoked `false` survives, because it is present.
 */
const withNewFeatureDefaults = (user: UserAccount): UserAccount => {
  const defaults =
    ROLE_CONFIGS[user.role]?.defaultPermissions ?? ROLE_CONFIGS.viewer.defaultPermissions;
  const merged = { ...user.customPermissions };
  (Object.keys(defaults) as FeatureKey[]).forEach((key) => {
    if (!(key in merged)) merged[key] = defaults[key];
  });
  return { ...user, customPermissions: merged };
};
```

Then add the tab case to `canAccessTab`'s `switch`, beside `'alarms'`:

```ts
        case 'model':
          requiredFeature = 'asset_model';
          featureName = 'Asset Model Explorer';
          break;
```

- [ ] **Step 3: Write the Plant Scope context**

Create `11_frontend/src/context/PlantScopeContext.tsx`:

```tsx
/**
 * Which plant the session is authoring.
 *
 * One console serves many plants (spec section 3), so nearly every authoring action
 * needs an answer to "under which Site?" — the tree roots there, a duplicate defaults
 * its target there, the adopt drawer filters Unmodelled Topics by it. That makes it
 * shared state rather than AssetModelView state: otherwise four component trees thread
 * the same two strings, and the choice resets on every navigation.
 *
 * Scope is a *view*, not a permission. It narrows what is listed; it does not stop
 * anyone editing anything. Per-plant RBAC is a follow-on spec, and pretending
 * otherwise here would be worse than not pretending.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { unsGraphQLClient } from '../services/graphql/client';
import type { GraphqlAssetNode } from '../services/graphql/types';

const STORAGE_KEY = 'uns.console.plantScope';

interface PlantScopeValue {
  enterprise: string | null;
  site: string | null;
  /** The Site if one is chosen, else the Enterprise, else null meaning everything. */
  scopePath: string | null;
  enterprises: GraphqlAssetNode[];
  sites: GraphqlAssetNode[];
  setEnterprise: (path: string | null) => void;
  setSite: (path: string | null) => void;
  isLoading: boolean;
  reload: () => void;
}

const PlantScopeContext = createContext<PlantScopeValue | undefined>(undefined);

export const PlantScopeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [enterprise, setEnterpriseState] = useState<string | null>(null);
  const [site, setSiteState] = useState<string | null>(null);
  const [enterprises, setEnterprises] = useState<GraphqlAssetNode[]>([]);
  const [sites, setSites] = useState<GraphqlAssetNode[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [reloadToken, setReloadToken] = useState<number>(0);

  // Restore before the first fetch, so a page reload lands on the same plant.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as { enterprise?: string; site?: string };
        if (parsed.enterprise) setEnterpriseState(parsed.enterprise);
        if (parsed.site) setSiteState(parsed.site);
      }
    } catch {
      // A malformed preference is not worth failing the screen over.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    unsGraphQLClient
      .getAssetChildren(null)
      .then((roots) => {
        if (!cancelled) setEnterprises(roots);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  useEffect(() => {
    if (!enterprise) {
      setSites([]);
      return undefined;
    }
    let cancelled = false;
    unsGraphQLClient.getAssetChildren(enterprise).then((children) => {
      if (!cancelled) setSites(children);
    });
    return () => {
      cancelled = true;
    };
  }, [enterprise, reloadToken]);

  const persist = useCallback((nextEnterprise: string | null, nextSite: string | null) => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ enterprise: nextEnterprise, site: nextSite })
      );
    } catch {
      // Private-browsing mode; the scope is simply not remembered.
    }
  }, []);

  const setEnterprise = useCallback(
    (path: string | null) => {
      setEnterpriseState(path);
      // The old Site is not under the new Enterprise, so keeping it would render an
      // empty tree under a selector that looks perfectly reasonable.
      setSiteState(null);
      persist(path, null);
    },
    [persist]
  );

  const setSite = useCallback(
    (path: string | null) => {
      setSiteState(path);
      persist(enterprise, path);
    },
    [enterprise, persist]
  );

  const value = useMemo<PlantScopeValue>(
    () => ({
      enterprise,
      site,
      scopePath: site ?? enterprise,
      enterprises,
      sites,
      setEnterprise,
      setSite,
      isLoading,
      reload: () => setReloadToken((token) => token + 1),
    }),
    [enterprise, site, enterprises, sites, setEnterprise, setSite, isLoading]
  );

  return <PlantScopeContext.Provider value={value}>{children}</PlantScopeContext.Provider>;
};

export const usePlantScope = (): PlantScopeValue => {
  const context = useContext(PlantScopeContext);
  if (!context) {
    throw new Error('usePlantScope must be used inside a PlantScopeProvider');
  }
  return context;
};
```

- [ ] **Step 4: Write the projection toast**

Create `11_frontend/src/components/model/ProjectionResultToast.tsx`:

```tsx
/**
 * What a template projection actually did.
 *
 * Live propagation means one edit to an Asset Template rewrites Assets nobody is
 * looking at, and instance overrides win — so part of what was asked for did not
 * happen. Showing the counts, and naming every field that was skipped, is what makes
 * that behaviour defensible rather than surprising (spec section 8.2). Skipped
 * overrides are listed rather than counted: "3 skipped" tells an engineer nothing
 * they can act on.
 */

import { AlertTriangle, CheckCircle2, X } from 'lucide-react';
import React from 'react';

import type { GraphqlTemplateProjection } from '../../services/graphql/types';

interface ProjectionResultToastProps {
  projection: GraphqlTemplateProjection | null;
  onDismiss: () => void;
}

const summarise = (projection: GraphqlTemplateProjection): string => {
  const parts: string[] = [];
  if (projection.assetsCreated) parts.push(`${projection.assetsCreated} Asset(s) created`);
  if (projection.assetsUpdated) parts.push(`${projection.assetsUpdated} updated`);
  if (projection.assetsDeactivated) parts.push(`${projection.assetsDeactivated} deactivated`);
  if (projection.metricsWritten) {
    parts.push(`${projection.metricsWritten} Metric Definition(s) written`);
  }
  if (projection.metricsDeleted) parts.push(`${projection.metricsDeleted} removed`);
  return parts.length > 0 ? parts.join(', ') : 'No Asset needed changing';
};

export const ProjectionResultToast: React.FC<ProjectionResultToastProps> = ({
  projection,
  onDismiss,
}) => {
  if (!projection) return null;

  const skipped = projection.overridesSkipped ?? [];

  return (
    <div
      role="status"
      className="fixed bottom-6 right-6 z-50 w-96 rounded-lg border border-slate-200 bg-white p-4 shadow-lg dark:border-slate-700 dark:bg-slate-900"
    >
      <div className="flex items-start gap-3">
        {skipped.length > 0 ? (
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
        ) : (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
            {summarise(projection)}
          </p>
          {skipped.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-amber-700 dark:text-amber-400">
                {skipped.length} Instance Override kept, so the Asset Template did not overwrite:
              </p>
              <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto text-xs text-slate-600 dark:text-slate-400">
                {skipped.map((entry) => (
                  <li key={`${entry.assetPath}:${entry.fieldName}`} className="truncate font-mono">
                    {entry.assetPath} · {entry.fieldName}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};
```

- [ ] **Step 5: Stub the screen so the route is real**

Create `11_frontend/src/components/model/AssetModelView.tsx`. Task 4 replaces the body; this exists so the route, the guard and the sidebar entry can be verified now rather than four tasks from now.

```tsx
/**
 * The Asset Model Explorer: route /model.
 *
 * Filled in by Task 4. This stub exists so the route, the RBAC gate and the sidebar
 * entry are verifiable on their own.
 */

import React from 'react';

import { usePlantScope } from '../../context/PlantScopeContext';

export const AssetModelView: React.FC = () => {
  const { enterprises, isLoading } = usePlantScope();
  return (
    <div className="p-6 text-sm text-slate-600 dark:text-slate-400">
      Asset Model Explorer — {isLoading ? 'loading' : `${enterprises.length} enterprise(s)`}
    </div>
  );
};
```

- [ ] **Step 6: Route it and gate it**

In `11_frontend/src/App.tsx`, wrap the console layout's children in `PlantScopeProvider` — inside `ProtectedConsoleLayout`, not around the whole app, so an unauthenticated visitor triggers no Asset queries — and add the route beside the existing ones:

```tsx
          <Route path="/model" element={<AssetModelView />} />
```

Match whatever guard wrapper the neighbouring routes use, so the `canAccessTab('model')` case from Step 2 applies. The `/model/templates` route arrives in Task 9 and `/model/templates/:templateId` in Task 10.

In `11_frontend/src/components/layout/Sidebar.tsx`, add to `coreNavItems` directly after the `/tree` entry — the Asset Model is what the live tree is a view of, so it belongs next to it. This is a deliberate departure from spec 7.4, which says `opsNavItems`: that section renders under "Platform Ops" alongside the simulator and the RBAC console, and authoring the plant hierarchy is not platform operations. Only one entry is added either way, so nothing else changes.

```tsx
    {
      to: '/model',
      tabId: 'model',
      label: 'Asset Model & Templates',
      shortLabel: 'Asset Model',
      icon: Boxes,
      description: 'Author the ISA-95 Plant Hierarchy',
      featureKey: 'asset_model',
    },
```

Add `Boxes` to the existing `lucide-react` import.

- [ ] **Step 7: Verify**

Run: `npm run lint`
Expected: clean. If `tsc` reports a `defaultPermissions` object missing a property, Step 1's table reached fewer than five roles.

Run: `npm run dev`, then in the browser — sign in as the engineer and confirm **Asset Model** appears in the sidebar and `/model` renders the enterprise count; sign in as the viewer and confirm `/model` renders Access Restricted naming "Asset Model Explorer".

- [ ] **Step 8: Commit**

```bash
git add 11_frontend/src/types/rbac.ts 11_frontend/src/context/AuthContext.tsx 11_frontend/src/context/PlantScopeContext.tsx 11_frontend/src/components/model 11_frontend/src/App.tsx 11_frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(frontend): add the Asset Model route, Plant Scope and its two feature permissions"
```

---

### Task 4: The Explorer shell — Plant Scope selector and the Asset tree

The screen an engineer lands on: pick Enterprise and Site, see the hierarchy under it, and act on a node. The tree loads children lazily per node (`getAssetChildren` takes one parent path) because a plant with thousands of Assets must not be fetched to draw a root, and because that is the only shape the query offers.

The tree owns structural actions — add child, rename, move, activate/deactivate, delete, and the entry point to duplicate — because they all change the tree and the tree is what must refresh afterwards. Field editing belongs to Task 5's detail form.

**Files:**
- Create: `11_frontend/src/components/model/PlantScopeSelector.tsx`
- Create: `11_frontend/src/components/model/AssetTreeEditor.tsx`
- Modify: `11_frontend/src/components/model/AssetModelView.tsx` (replaces the Task 3 stub)

**Interfaces:**
- Consumes: `usePlantScope`, `ProjectionResultToast` (Task 3); `client.getAssetChildren`, `saveAsset`, `renameAsset`, `moveAsset`, `setAssetActive`, `deleteAsset`, `getAssetModelSummary` and `assetToInput` (Task 2).
- Produces:
  - `<PlantScopeSelector />` — reads and writes the context, no props
  - `<AssetTreeEditor selectedPath={string | null} onSelect={(path: string | null) => void} refreshToken={number} onChanged={() => void} onDuplicate={(path: string) => void} />`
  - `<AssetModelView />` owning `selectedPath`, `refreshToken` and `bumpRefresh()`, which Tasks 5–8 hang their panes off.
  - from `AssetTreeEditor.tsx`: `export const ASSET_LEVELS` (the ISA-95 levels, in order) and `export const defaultChildLevel(parentLevel: string): string`. Tasks 9 and 10 import both — the Asset Template screens need the same level list and the same next-level-down guess, and a second copy would drift.

- [ ] **Step 1: Write the Plant Scope selector**

Create `11_frontend/src/components/model/PlantScopeSelector.tsx`:

```tsx
/**
 * Enterprise and Site pickers for the Asset Model Explorer header.
 *
 * Two plain selects rather than a searchable combobox: the counts here are the number
 * of companies and the number of plants, which is small enough that a select is the
 * better control. The Site list is empty until an Enterprise is chosen, because a Site
 * has no meaning without one.
 */

import { Building2, Factory } from 'lucide-react';
import React from 'react';

import { usePlantScope } from '../../context/PlantScopeContext';

const SELECT_CLASS =
  'rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100';

export const PlantScopeSelector: React.FC = () => {
  const { enterprise, site, enterprises, sites, setEnterprise, setSite, isLoading } = usePlantScope();

  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex items-center gap-2">
        <Building2 className="h-4 w-4 text-slate-400" />
        <span className="sr-only">Enterprise</span>
        <select
          className={SELECT_CLASS}
          value={enterprise ?? ''}
          disabled={isLoading}
          onChange={(event) => setEnterprise(event.target.value || null)}
        >
          <option value="">All enterprises</option>
          {enterprises.map((node) => (
            <option key={node.path} value={node.path}>
              {node.name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2">
        <Factory className="h-4 w-4 text-slate-400" />
        <span className="sr-only">Site</span>
        <select
          className={SELECT_CLASS}
          value={site ?? ''}
          disabled={!enterprise || sites.length === 0}
          onChange={(event) => setSite(event.target.value || null)}
        >
          <option value="">{enterprise ? 'All sites' : 'Choose an enterprise first'}</option>
          {sites.map((node) => (
            <option key={node.path} value={node.path}>
              {node.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
};
```

- [ ] **Step 2: Write the tree editor**

Create `11_frontend/src/components/model/AssetTreeEditor.tsx`. It is long because the per-node action menu is where the structural mutations live; it is one file because those actions and the tree state they invalidate are the same concern.

```tsx
/**
 * The authored hierarchy, with the actions that change its shape.
 *
 * Children load per expanded node: getAssetChildren takes a single parent path, and a
 * plant with thousands of Assets must not be fetched to draw its root. `childrenByPath`
 * is therefore a cache keyed by parent path, cleared wholesale when `refreshToken`
 * changes — a rename moves a whole subtree, so invalidating one entry is not enough and
 * working out exactly which entries moved would be re-deriving what the server knows.
 *
 * Inactive Assets are shown greyed rather than hidden. Deactivation is the safe
 * alternative to deletion (a delete would cascade into OEE configuration), so an
 * engineer has to be able to see and reactivate what they deactivated.
 */

import {
  ChevronDown,
  ChevronRight,
  Copy,
  Eye,
  EyeOff,
  FolderPlus,
  Loader2,
  Pencil,
  Trash2,
} from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';

import { useAuth } from '../../context/AuthContext';
import { usePlantScope } from '../../context/PlantScopeContext';
import { assetToInput } from '../../lib/model/map-assets-write';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlAssetDependents, GraphqlAssetNode } from '../../services/graphql/types';

/** The ISA-95 levels, in order, as the server spells them. */
export const ASSET_LEVELS = [
  'ENTERPRISE',
  'SITE',
  'AREA',
  'PRODUCTION_UNIT',
  'LINE',
  'WORK_CELL',
  'MACHINE',
] as const;

/** The level a new child most likely wants, given its parent's. */
export const defaultChildLevel = (parentLevel: string): string => {
  const index = ASSET_LEVELS.indexOf(parentLevel as (typeof ASSET_LEVELS)[number]);
  if (index === -1 || index === ASSET_LEVELS.length - 1) return 'MACHINE';
  return ASSET_LEVELS[index + 1];
};

interface AssetTreeEditorProps {
  selectedPath: string | null;
  onSelect: (path: string | null) => void;
  /** Bumped by the parent after any write; clears the whole children cache. */
  refreshToken: number;
  onChanged: () => void;
  onDuplicate: (path: string) => void;
}

export const AssetTreeEditor: React.FC<AssetTreeEditorProps> = ({
  selectedPath,
  onSelect,
  refreshToken,
  onChanged,
  onDuplicate,
}) => {
  const { scopePath } = usePlantScope();
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('asset_model_edit');

  const [childrenByPath, setChildrenByPath] = useState<Record<string, GraphqlAssetNode[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{
    path: string;
    dependents: GraphqlAssetDependents;
  } | null>(null);

  const rootKey = scopePath ?? '';

  const loadChildren = useCallback(async (parentPath: string | null) => {
    const key = parentPath ?? '';
    setLoadingPaths((paths) => new Set(paths).add(key));
    try {
      const children = await unsGraphQLClient.getAssetChildren(parentPath);
      setChildrenByPath((previous) => ({ ...previous, [key]: children }));
    } finally {
      setLoadingPaths((paths) => {
        const next = new Set(paths);
        next.delete(key);
        return next;
      });
    }
  }, []);

  // A write anywhere invalidates everything: a rename or a move relocates a whole
  // subtree, so the cheap correct answer is to drop the cache and reload what is open.
  useEffect(() => {
    setChildrenByPath({});
    void loadChildren(scopePath ?? null);
    expanded.forEach((path) => {
      void loadChildren(path);
    });
    // `expanded` is deliberately not a dependency: expanding one node should load that
    // node, not reload every open branch. That is handled in `toggle`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken, scopePath, loadChildren]);

  const toggle = useCallback(
    (path: string) => {
      setExpanded((previous) => {
        const next = new Set(previous);
        if (next.has(path)) {
          next.delete(path);
        } else {
          next.add(path);
          if (!childrenByPath[path]) void loadChildren(path);
        }
        return next;
      });
    },
    [childrenByPath, loadChildren]
  );

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setError(null);
      try {
        await action();
        onChanged();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [onChanged]
  );

  const addChild = (parent: GraphqlAssetNode | null) => {
    const segment = window.prompt('Name of the new Asset (one topic segment, no "/")');
    if (!segment) return;
    const parentPath = parent ? parent.path : scopePath;
    const path = parentPath ? `${parentPath}/${segment}` : segment;
    const level = parent ? defaultChildLevel(parent.level) : 'ENTERPRISE';
    void run(() =>
      unsGraphQLClient.saveAsset(
        assetToInput({
          path,
          level,
          displayName: null,
          description: null,
          manufacturer: null,
          modelNumber: null,
          serialNumber: null,
          criticality: null,
          commissionedOn: null,
          attributes: {},
          isActive: true,
        })
      )
    );
  };

  const rename = (node: GraphqlAssetNode) => {
    const segment = window.prompt(`Rename ${node.segment} to`, node.segment);
    if (!segment || segment === node.segment) return;
    void run(async () => {
      const result = await unsGraphQLClient.renameAsset(node.path, segment);
      if (result.alertRules.length > 0) {
        // alert_rules.topic is free text, so nothing rewrote it. Say so rather than
        // letting an Alert Rule quietly stop matching.
        setError(
          `Renamed ${result.assetsUpdated} Asset(s). ${result.alertRules.length} Alert Rule(s) still name the old path and need editing: ${result.alertRules.join(', ')}`
        );
      }
    });
  };

  const move = (node: GraphqlAssetNode) => {
    const newParentPath = window.prompt(`Move ${node.segment} under which Asset path?`);
    if (!newParentPath) return;
    void run(async () => {
      const result = await unsGraphQLClient.moveAsset(node.path, newParentPath);
      if (result.alertRules.length > 0) {
        setError(
          `Moved ${result.assetsUpdated} Asset(s). ${result.alertRules.length} Alert Rule(s) still name the old path: ${result.alertRules.join(', ')}`
        );
      }
    });
  };

  const requestDelete = (node: GraphqlAssetNode) => {
    void run(async () => {
      const result = await unsGraphQLClient.deleteAsset(node.path, false);
      // A refusal is data, not an error: the server hands back what would be lost so
      // the console can ask, rather than the console guessing before it asks.
      if (result.refused) setPendingDelete({ path: node.path, dependents: result.dependents });
      else if (result.removed && selectedPath === node.path) onSelect(null);
    });
  };

  const confirmDelete = () => {
    if (!pendingDelete) return;
    const { path } = pendingDelete;
    setPendingDelete(null);
    void run(async () => {
      await unsGraphQLClient.deleteAsset(path, true);
      if (selectedPath === path) onSelect(null);
    });
  };

  const renderNode = (node: GraphqlAssetNode, depth: number): React.ReactNode => {
    const isExpanded = expanded.has(node.path);
    const children = childrenByPath[node.path];
    const isSelected = selectedPath === node.path;

    return (
      <li key={node.path}>
        <div
          className={`group flex items-center gap-1 rounded px-1 py-1 ${
            isSelected ? 'bg-blue-50 dark:bg-blue-500/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
          }`}
          style={{ paddingLeft: `${depth * 14 + 4}px` }}
        >
          <button
            type="button"
            aria-label={isExpanded ? 'Collapse' : 'Expand'}
            onClick={() => toggle(node.path)}
            className="shrink-0 rounded p-0.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          >
            {loadingPaths.has(node.path) ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>

          <button
            type="button"
            onClick={() => onSelect(node.path)}
            className={`min-w-0 flex-1 truncate text-left text-sm ${
              node.isActive
                ? 'text-slate-800 dark:text-slate-100'
                : 'text-slate-400 line-through dark:text-slate-500'
            }`}
            title={node.path}
          >
            {node.name}
            <span className="ml-2 text-[10px] uppercase tracking-wide text-slate-400">
              {node.level}
            </span>
            {node.templateName && (
              <span className="ml-2 rounded bg-violet-50 px-1 text-[10px] text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                {node.templateName}
              </span>
            )}
          </button>

          {canEdit && (
            <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
              <button type="button" title="Add child Asset" onClick={() => addChild(node)} className="rounded p-1 text-slate-400 hover:text-blue-600">
                <FolderPlus className="h-3.5 w-3.5" />
              </button>
              <button type="button" title="Rename" onClick={() => rename(node)} className="rounded p-1 text-slate-400 hover:text-blue-600">
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button type="button" title="Move" onClick={() => move(node)} className="rounded p-1 text-slate-400 hover:text-blue-600">
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
              <button type="button" title="Duplicate" onClick={() => onDuplicate(node.path)} className="rounded p-1 text-slate-400 hover:text-blue-600">
                <Copy className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                title={node.isActive ? 'Deactivate (keeps history and OEE config)' : 'Reactivate'}
                onClick={() => void run(() => unsGraphQLClient.setAssetActive(node.path, !node.isActive))}
                className="rounded p-1 text-slate-400 hover:text-amber-600"
              >
                {node.isActive ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              </button>
              <button type="button" title="Delete" onClick={() => requestDelete(node)} className="rounded p-1 text-slate-400 hover:text-rose-600">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </div>

        {isExpanded && children && children.length > 0 && (
          <ul>{children.map((child) => renderNode(child, depth + 1))}</ul>
        )}
        {isExpanded && children && children.length === 0 && (
          <p
            className="py-1 text-xs italic text-slate-400"
            style={{ paddingLeft: `${(depth + 1) * 14 + 24}px` }}
          >
            No child Assets
          </p>
        )}
      </li>
    );
  };

  const roots = childrenByPath[rootKey] ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-700">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {scopePath ?? 'All plants'}
        </span>
        {canEdit && (
          <button
            type="button"
            onClick={() => addChild(null)}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-500/10"
          >
            <FolderPlus className="h-3.5 w-3.5" /> New Asset
          </button>
        )}
      </div>

      {error && (
        <p className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          {error}
        </p>
      )}

      <div className="flex-1 overflow-y-auto py-1">
        {loadingPaths.has(rootKey) && roots.length === 0 ? (
          <p className="px-3 py-2 text-xs text-slate-400">Loading the Asset Model…</p>
        ) : roots.length === 0 ? (
          <p className="px-3 py-2 text-xs text-slate-400">
            No Assets here yet. Create one, instantiate an Asset Template, or adopt an Unmodelled Topic.
          </p>
        ) : (
          <ul>{roots.map((node) => renderNode(node, 0))}</ul>
        )}
      </div>

      {pendingDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Delete {pendingDelete.path}?
            </h3>
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
              This would also remove {pendingDelete.dependents.descendants} descendant Asset(s),{' '}
              {pendingDelete.dependents.oeeUnits} OEE Unit(s),{' '}
              {pendingDelete.dependents.shiftPatterns} shift pattern(s),{' '}
              {pendingDelete.dependents.shiftExceptions} shift exception(s) and{' '}
              {pendingDelete.dependents.idealCycleTimes} ideal cycle time(s). Deactivating instead
              keeps all of it.
            </p>
            {pendingDelete.dependents.alertRules.length > 0 && (
              <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
                {pendingDelete.dependents.alertRules.length} Alert Rule(s) name this path and will
                stop matching:{' '}
                <span className="font-mono">{pendingDelete.dependents.alertRules.join(', ')}</span>
              </p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingDelete(null)}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-700 dark:border-slate-600 dark:text-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700"
              >
                Delete anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 3: Replace the AssetModelView stub with the shell**

Rewrite `11_frontend/src/components/model/AssetModelView.tsx`. Tasks 5–8 add panes into the marked slots; the state they share (`selectedPath`, `refreshToken`) lives here.

```tsx
/**
 * The Asset Model Explorer: route /model.
 *
 * A two-pane shell — the authored hierarchy on the left, the selected Asset's fields
 * and Metric Definitions on the right — over a header carrying the Plant Scope and the
 * summary counts. The tree and the right-hand panes share `refreshToken`: any write
 * anywhere calls `bumpRefresh`, and everything reloads. That is heavier than surgical
 * cache updates and much harder to get wrong, which is the right trade for a screen
 * an engineer uses for minutes at a time rather than a live telemetry view.
 */

import { Boxes, Inbox, LayoutTemplate } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { usePlantScope } from '../../context/PlantScopeContext';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlAssetModelSummary } from '../../services/graphql/types';
import { AssetTreeEditor } from './AssetTreeEditor';
import { PlantScopeSelector } from './PlantScopeSelector';

export const AssetModelView: React.FC = () => {
  const { scopePath } = usePlantScope();
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<number>(0);
  const [summary, setSummary] = useState<GraphqlAssetModelSummary | null>(null);

  const bumpRefresh = useCallback(() => setRefreshToken((token) => token + 1), []);

  useEffect(() => {
    let cancelled = false;
    unsGraphQLClient.getAssetModelSummary().then((next) => {
      if (!cancelled) setSummary(next);
    });
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  // The selection is a path, and a rename or move changes paths. Clearing it on a
  // scope change is enough: within a scope, a stale path simply loads nothing.
  useEffect(() => {
    setSelectedPath(null);
  }, [scopePath]);

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-slate-200 px-5 py-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Boxes className="h-5 w-5 text-blue-600" />
            <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Asset Model
            </h1>
            {summary && (
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {summary.assets} Assets · {summary.metricDefinitions} Metric Definitions ·{' '}
                {summary.boundTopics} bound topics · {summary.unmodelledTopics} unmodelled
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <PlantScopeSelector />
            <Link
              to="/model/templates"
              className="flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <LayoutTemplate className="h-3.5 w-3.5" /> Asset Templates
            </Link>
            {/* Task 8 replaces this with the AdoptTopicsDrawer trigger. */}
            <span className="flex items-center gap-1 text-xs text-slate-400">
              <Inbox className="h-3.5 w-3.5" /> Adopt topics
            </span>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-96 shrink-0 border-r border-slate-200 dark:border-slate-700">
          <AssetTreeEditor
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
            refreshToken={refreshToken}
            onChanged={bumpRefresh}
            onDuplicate={() => {
              /* Task 7 opens the DuplicateAssetModal here. */
            }}
          />
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto">
          {selectedPath ? (
            /* Task 5 renders AssetDetailForm and Task 6 renders TagTable here. */
            <p className="p-5 text-sm text-slate-500 dark:text-slate-400">{selectedPath}</p>
          ) : (
            <p className="p-5 text-sm text-slate-400">Select an Asset to edit it.</p>
          )}
        </main>
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Verify**

Run: `npm run lint`
Expected: clean.

Run: `npm run dev` against a stack seeded by `uns_model seed`. In the browser at `/model`: choose an Enterprise and a Site, expand to a Line, create a child Asset, rename it, deactivate it (it greys and strikes through), reactivate it, then delete it and confirm the dependents dialog appears if it has OEE configuration. Confirm signing in as an operator shows the tree with no action buttons at all.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/model
git commit -m "feat(frontend): add the Asset Model Explorer shell, Plant Scope selector and tree editor"
```

---

### Task 5: The Asset detail form, its attributes, and the override badges

The right-hand pane: every authored column of the selected Asset, its JSONB attributes, which fields are Instance Overrides, and the button that gives an Asset back to its Asset Template. This is where live propagation becomes legible — a badge on a field is the console explaining why a template edit will not touch it.

`AttributeEditor` is its own file because JSONB key/value editing has nothing to do with the Asset's columns and would otherwise double the form's length.

**Files:**
- Create: `11_frontend/src/components/model/AttributeEditor.tsx`
- Create: `11_frontend/src/components/model/AssetDetailForm.tsx`
- Modify: `11_frontend/src/components/model/AssetModelView.tsx` (the right-hand slot from Task 4 Step 3)
- Modify: `11_frontend/src/services/graphql/queries.ts`, `11_frontend/src/services/graphql/types.ts`, `11_frontend/src/services/graphql/client.ts` (one new single-Asset read)
- Modify: `11_frontend/src/lib/model/map-assets-write.ts` (`commissionedOn` round trip)

**Interfaces:**
- Consumes: `AssetDraft`, `draftFromAsset`, `assetToInput`, `attributesOf` (Task 2); `client.saveAsset`, `client.revertToTemplate` (Task 2); `ProjectionResultToast` (Task 3); `ASSET_LEVELS` (Task 4).
- Produces:
  - `GET_ASSET_QUERY` and `client.getAsset(path: string): Promise<GraphqlAssetNode | null>`
  - `<AttributeEditor value={Record<string, string>} onChange={(next: Record<string, string>) => void} disabled={boolean} />`
  - `<AssetDetailForm path={string} onSaved={() => void} />` — no `onRenamed`: this form cannot rename, because the path is read-only here and renaming is offered in the tree.

- [ ] **Step 1: Add the single-Asset read and finish the `commissionedOn` round trip**

The tree gives a node from a *list*; the form needs the one Asset by path so that reopening it after a save shows what the server stored, including what a projection overwrote. In `queries.ts`:

```ts
export const GET_ASSET_QUERY = `
  query GetAsset($path: String!) {
    getAsset(path: $path) {
      ${ASSET_FIELDS}
    }
  }
`
```

`getAsset(path)` already exists server-side (`07_uns_graphql/src/uns_graphql/queries/asset.py:89`); this only adds the document and the client method.

In `client.ts`:

```ts
  public async getAsset(path: string): Promise<GraphqlAssetNode | null> {
    const res = await this.executeQuery<{ getAsset: GraphqlAssetNode | null }>(GET_ASSET_QUERY, {
      path,
    })
    return res.data?.getAsset ?? null
  }
```

Plan 1 adds `commissionedOn` to `AssetNode`, so add it to `ASSET_FIELDS` in `queries.ts` and to `GraphqlAssetNode` in `types.ts`:

```ts
  commissionedOn?: string | null
```

and read it in `draftFromAsset` in `map-assets-write.ts`, replacing the hard-coded null:

```ts
    commissionedOn: asset.commissionedOn ?? null,
```

Without this the form sends `commissionedOn: null` on every save and erases a date it never displayed.

- [ ] **Step 2: Write the attribute editor**

Create `11_frontend/src/components/model/AttributeEditor.tsx`:

```tsx
/**
 * The Asset's `attributes` JSONB, as key/value rows.
 *
 * Values are edited as text and stored as strings. `attributes` is the escape hatch for
 * site-specific facts that do not deserve a column, and typed JSON editing would mean
 * asking an engineer to get quoting right in a text box — a worse trade than losing the
 * ability to store a nested object here. Anything genuinely structured deserves a
 * Metric Definition or a column.
 *
 * Rows are held in local state as an array rather than as the record itself, because
 * renaming a key by editing a record in place would drop the row on the first
 * keystroke that produces a duplicate or empty key.
 */

import { Plus, Trash2 } from 'lucide-react';
import React, { useEffect, useState } from 'react';

interface AttributeEditorProps {
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  disabled?: boolean;
}

type Row = { key: string; value: string };

const toRows = (record: Record<string, string>): Row[] =>
  Object.entries(record).map(([key, value]) => ({ key, value }));

const toRecord = (rows: Row[]): Record<string, string> => {
  const record: Record<string, string> = {};
  rows.forEach((row) => {
    const key = row.key.trim();
    // A blank key is a half-typed row, not a deletion; skipping it keeps the row on
    // screen while making sure it is never sent.
    if (key) record[key] = row.value;
  });
  return record;
};

const INPUT_CLASS =
  'w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-900 focus:border-blue-500 focus:outline-none disabled:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:disabled:bg-slate-900';

export const AttributeEditor: React.FC<AttributeEditorProps> = ({ value, onChange, disabled }) => {
  const [rows, setRows] = useState<Row[]>(() => toRows(value));

  // Re-seed when a different Asset is selected. Comparing the serialised record avoids
  // stomping the row being typed in on every parent re-render.
  useEffect(() => {
    setRows((current) =>
      JSON.stringify(toRecord(current)) === JSON.stringify(value) ? current : toRows(value)
    );
  }, [value]);

  const update = (next: Row[]) => {
    setRows(next);
    onChange(toRecord(next));
  };

  return (
    <div className="space-y-1">
      {rows.length === 0 && (
        <p className="text-xs italic text-slate-400">No attributes.</p>
      )}
      {rows.map((row, index) => (
        <div key={index} className="flex items-center gap-2">
          <input
            className={INPUT_CLASS}
            placeholder="Key"
            value={row.key}
            disabled={disabled}
            onChange={(event) =>
              update(rows.map((r, i) => (i === index ? { ...r, key: event.target.value } : r)))
            }
          />
          <input
            className={INPUT_CLASS}
            placeholder="Value"
            value={row.value}
            disabled={disabled}
            onChange={(event) =>
              update(rows.map((r, i) => (i === index ? { ...r, value: event.target.value } : r)))
            }
          />
          <button
            type="button"
            aria-label="Remove attribute"
            disabled={disabled}
            onClick={() => update(rows.filter((_r, i) => i !== index))}
            className="shrink-0 rounded p-1 text-slate-400 hover:text-rose-600 disabled:opacity-40"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      {!disabled && (
        <button
          type="button"
          onClick={() => update([...rows, { key: '', value: '' }])}
          className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <Plus className="h-3.5 w-3.5" /> Add attribute
        </button>
      )}
    </div>
  );
};
```

- [ ] **Step 3: Write the detail form**

Create `11_frontend/src/components/model/AssetDetailForm.tsx`:

```tsx
/**
 * Every authored field of one Asset.
 *
 * The path and the Asset Level are read-only here on purpose: changing a path is a
 * rename or a move, which relocates a whole subtree and is offered in the tree where
 * that consequence is visible. A form that let you retype a path would look like it
 * edited one row.
 *
 * A field carrying an Instance Override is badged, because live propagation means an
 * Asset Template edit reaches every instance *except* those fields — an engineer
 * needs to know which of the two owns each value before wondering why an edit had no
 * effect (spec section 8). `Revert to template` clears the overrides in one call and
 * reports what the resulting projection wrote.
 */

import { Link2, RotateCcw, Save } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';

import { useAuth } from '../../context/AuthContext';
import type { AssetDraft } from '../../lib/model/map-assets-write';
import { assetToInput, draftFromAsset } from '../../lib/model/map-assets-write';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlAssetNode, GraphqlTemplateProjection } from '../../services/graphql/types';
import { AttributeEditor } from './AttributeEditor';
import { ProjectionResultToast } from './ProjectionResultToast';

interface AssetDetailFormProps {
  path: string;
  /** Called after any successful write, so the tree and the summary reload. */
  onSaved: () => void;
}

const FIELD_CLASS =
  'w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none disabled:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:disabled:bg-slate-900';
const LABEL_CLASS = 'flex items-center gap-1.5 text-xs font-medium text-slate-600 dark:text-slate-400';

/** The AssetInput field names, so a badge matches what the server calls the field. */
const OVERRIDE_KEYS = {
  displayName: 'display_name',
  description: 'description',
  manufacturer: 'manufacturer',
  modelNumber: 'model_number',
  serialNumber: 'serial_number',
  criticality: 'criticality',
  commissionedOn: 'commissioned_on',
  attributes: 'attributes',
} as const;

export const AssetDetailForm: React.FC<AssetDetailFormProps> = ({ path, onSaved }) => {
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('asset_model_edit');

  const [asset, setAsset] = useState<GraphqlAssetNode | null>(null);
  const [draft, setDraft] = useState<AssetDraft | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [projection, setProjection] = useState<GraphqlTemplateProjection | null>(null);

  const load = useCallback(() => {
    setError(null);
    unsGraphQLClient.getAsset(path).then((loaded) => {
      setAsset(loaded);
      setDraft(loaded ? draftFromAsset(loaded) : null);
    });
  }, [path]);

  useEffect(load, [load]);

  const overridden = new Set(asset?.overriddenFields ?? []);

  const set = <K extends keyof AssetDraft>(key: K, value: AssetDraft[K]) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));

  const save = async () => {
    if (!draft) return;
    setIsSaving(true);
    setError(null);
    try {
      const saved = await unsGraphQLClient.saveAsset(assetToInput(draft));
      setAsset(saved);
      setDraft(draftFromAsset(saved));
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setIsSaving(false);
    }
  };

  const revert = async () => {
    setError(null);
    try {
      setProjection(await unsGraphQLClient.revertToTemplate(path));
      load();
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  if (!draft || !asset) {
    return <p className="p-5 text-sm text-slate-400">Loading {path}…</p>;
  }

  const badge = (field: keyof typeof OVERRIDE_KEYS) =>
    overridden.has(OVERRIDE_KEYS[field]) ? (
      <span
        className="rounded bg-amber-50 px-1 text-[10px] font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-400"
        title="Instance Override: an Asset Template edit will not overwrite this field"
      >
        overridden
      </span>
    ) : null;

  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-slate-500 dark:text-slate-400">{asset.path}</p>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {asset.name}
            <span className="ml-2 text-xs font-normal uppercase tracking-wide text-slate-400">
              {asset.level}
            </span>
          </p>
          {asset.templateName && (
            <p className="mt-1 flex items-center gap-1 text-xs text-violet-700 dark:text-violet-300">
              <Link2 className="h-3 w-3" /> Instance of {asset.templateName}
              {overridden.size > 0 && ` · ${overridden.size} Instance Override(s)`}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {canEdit && asset.templateId && overridden.size > 0 && (
            <button
              type="button"
              onClick={revert}
              className="flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
              title="Drop the Instance Overrides and take the Asset Template's values"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Revert to template
            </button>
          )}
          {canEdit && (
            <button
              type="button"
              onClick={save}
              disabled={isSaving}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" /> {isSaving ? 'Saving…' : 'Save'}
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          {error}
        </p>
      )}

      {asset.templateId && canEdit && (
        <p className="rounded-md border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-800 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-200">
          Editing a field here makes it an Instance Override, and the Asset Template will
          stop maintaining it.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1">
          <span className={LABEL_CLASS}>Display name {badge('displayName')}</span>
          <input
            className={FIELD_CLASS}
            value={draft.displayName ?? ''}
            disabled={!canEdit}
            placeholder={asset.segment}
            onChange={(event) => set('displayName', event.target.value || null)}
          />
        </label>

        <label className="space-y-1">
          <span className={LABEL_CLASS}>Criticality {badge('criticality')}</span>
          <input
            className={FIELD_CLASS}
            value={draft.criticality ?? ''}
            disabled={!canEdit}
            onChange={(event) => set('criticality', event.target.value || null)}
          />
        </label>

        <label className="space-y-1 sm:col-span-2">
          <span className={LABEL_CLASS}>Description {badge('description')}</span>
          <textarea
            className={FIELD_CLASS}
            rows={2}
            value={draft.description ?? ''}
            disabled={!canEdit}
            onChange={(event) => set('description', event.target.value || null)}
          />
        </label>

        <label className="space-y-1">
          <span className={LABEL_CLASS}>Manufacturer {badge('manufacturer')}</span>
          <input
            className={FIELD_CLASS}
            value={draft.manufacturer ?? ''}
            disabled={!canEdit}
            onChange={(event) => set('manufacturer', event.target.value || null)}
          />
        </label>

        <label className="space-y-1">
          <span className={LABEL_CLASS}>Model number {badge('modelNumber')}</span>
          <input
            className={FIELD_CLASS}
            value={draft.modelNumber ?? ''}
            disabled={!canEdit}
            onChange={(event) => set('modelNumber', event.target.value || null)}
          />
        </label>

        <label className="space-y-1">
          <span className={LABEL_CLASS}>Serial number {badge('serialNumber')}</span>
          <input
            className={FIELD_CLASS}
            value={draft.serialNumber ?? ''}
            disabled={!canEdit}
            onChange={(event) => set('serialNumber', event.target.value || null)}
          />
        </label>

        <label className="space-y-1">
          <span className={LABEL_CLASS}>Commissioned on {badge('commissionedOn')}</span>
          <input
            type="date"
            className={FIELD_CLASS}
            value={draft.commissionedOn ?? ''}
            disabled={!canEdit}
            onChange={(event) => set('commissionedOn', event.target.value || null)}
          />
        </label>
      </div>

      <section className="space-y-2">
        <h3 className={LABEL_CLASS}>Attributes {badge('attributes')}</h3>
        <AttributeEditor
          value={draft.attributes}
          disabled={!canEdit}
          onChange={(next) => set('attributes', next)}
        />
      </section>

      <ProjectionResultToast projection={projection} onDismiss={() => setProjection(null)} />
    </div>
  );
};
```

- [ ] **Step 4: Wire it into the shell**

In `11_frontend/src/components/model/AssetModelView.tsx`, replace the placeholder in the `main` element:

```tsx
          {selectedPath ? (
            <AssetDetailForm path={selectedPath} onSaved={bumpRefresh} />
          ) : (
            <p className="p-5 text-sm text-slate-400">Select an Asset to edit it.</p>
          )}
```

and import `AssetDetailForm`.

- [ ] **Step 5: Verify**

Run: `npm run lint`
Expected: clean.

Run: `npm run dev`. Select an Asset, set a display name and a manufacturer, save, and confirm the tree label updates. Add an attribute, save, reload the page and confirm it persisted. Set a commissioning date, save, reselect the Asset and confirm the date is still there — that is Step 1's round trip. On an Asset created from a template (Task 9 makes one), edit its display name and confirm the `overridden` badge appears after saving, then use **Revert to template** and confirm the toast reports the projection. Sign in as an operator and confirm every field is disabled and neither button renders.

- [ ] **Step 6: Commit**

```bash
git add 11_frontend/src/components/model 11_frontend/src/services/graphql 11_frontend/src/lib/model/map-assets-write.ts
git commit -m "feat(frontend): add the Asset detail form, attribute editor and override badges"
```

---

### Task 6: The tag table

"List the tags for my assets" is the request this screen answers most directly. A Metric Definition is what the Asset Model says about one Metric Key — its display name, its Unit of Measure, its range — and it is what makes an enriched read mean something instead of returning a bare number.

Two things must be visible and are easy to get wrong. First, a Metric Definition can be **plant-wide** (`assetPath` null) or **per-Asset**, and the plant-wide row applies to this Asset too — so the table shows both and marks which is which, and editing a plant-wide row from here would change every Asset that inherits it. Second, a row an Asset Template maintains is marked, because editing it makes it an Instance Override.

**Files:**
- Create: `11_frontend/src/components/model/TagTable.tsx`
- Modify: `11_frontend/src/components/model/AssetModelView.tsx`

**Interfaces:**
- Consumes: `client.getMetricDefinitions`, `client.saveMetricDefinition`, `client.deleteMetricDefinition`, `MetricDraft`, `draftFromMetric`, `metricToInput` (Task 2).
- Produces: `<TagTable assetPath={string} refreshToken={number} onChanged={() => void} />`

- [ ] **Step 1: Write the tag table**

Create `11_frontend/src/components/model/TagTable.tsx`:

```tsx
/**
 * The Metric Definitions that apply to one Asset.
 *
 * `getMetricDefinitions(assetPath)` answers the *editing* question — the rows an
 * engineer would change here — which includes plant-wide rows (`assetPath` null) that
 * this Asset inherits. Those are shown, badged, and read-only in this table: editing one
 * from an Asset's page would change every Asset inheriting it, which is not what the
 * page appears to offer. "Override for this Asset" copies it down to a per-Asset row
 * instead, which is the action an engineer actually wants.
 *
 * Rows maintained by an Asset Template are badged too: saving one turns it into an
 * Instance Override and the Asset Template stops maintaining it (spec section 8).
 *
 * `unitOfMeasure` is the physical unit, e.g. °C. It is never labelled "unit" — an OEE
 * Unit is a different thing entirely and the two are already too easy to confuse.
 */

import { Check, Copy, Loader2, Plus, Trash2, X } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';

import { useAuth } from '../../context/AuthContext';
import type { MetricDraft } from '../../lib/model/map-assets-write';
import { draftFromMetric, metricToInput } from '../../lib/model/map-assets-write';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlMetricDefinition } from '../../services/graphql/types';

interface TagTableProps {
  assetPath: string;
  refreshToken: number;
  onChanged: () => void;
}

const emptyDraft = (assetPath: string): MetricDraft => ({
  metricKey: '',
  assetPath,
  displayName: null,
  unitOfMeasure: null,
  decimals: null,
  minValue: null,
  maxValue: null,
  deadband: null,
  description: null,
});

const CELL_INPUT =
  'w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100';

/** '' back to null, so an emptied box clears the column instead of storing ''. */
const orNull = (raw: string): string | null => (raw.trim() === '' ? null : raw);
const numberOrNull = (raw: string): number | null => (raw.trim() === '' ? null : Number(raw));

export const TagTable: React.FC<TagTableProps> = ({ assetPath, refreshToken, onChanged }) => {
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('asset_model_edit');

  const [rows, setRows] = useState<GraphqlMetricDefinition[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [draft, setDraft] = useState<MetricDraft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setIsLoading(true);
    unsGraphQLClient
      .getMetricDefinitions(assetPath)
      .then(setRows)
      .finally(() => setIsLoading(false));
  }, [assetPath]);

  useEffect(load, [load, refreshToken]);

  const commit = async (next: MetricDraft) => {
    setError(null);
    if (!next.metricKey.trim()) {
      setError('A Metric Key is required, e.g. ProcessValue/Temperature/value');
      return;
    }
    try {
      await unsGraphQLClient.saveMetricDefinition(metricToInput(next));
      setDraft(null);
      load();
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const remove = async (row: GraphqlMetricDefinition) => {
    setError(null);
    try {
      await unsGraphQLClient.deleteMetricDefinition(row.metricKey, assetPath);
      load();
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <section className="space-y-2">
      <header className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-slate-600 dark:text-slate-400">
          Metric Definitions{' '}
          <span className="text-slate-400">({rows.length})</span>
        </h3>
        {canEdit && !draft && (
          <button
            type="button"
            onClick={() => setDraft(emptyDraft(assetPath))}
            className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
          >
            <Plus className="h-3.5 w-3.5" /> Add tag
          </button>
        )}
      </header>

      {error && (
        <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          {error}
        </p>
      )}

      <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-700">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
            <tr>
              <th className="px-2 py-1.5 font-medium">Metric Key</th>
              <th className="px-2 py-1.5 font-medium">Display name</th>
              <th className="px-2 py-1.5 font-medium">Unit of Measure</th>
              <th className="px-2 py-1.5 font-medium">Decimals</th>
              <th className="px-2 py-1.5 font-medium">Min</th>
              <th className="px-2 py-1.5 font-medium">Max</th>
              <th className="px-2 py-1.5 font-medium">Deadband</th>
              <th className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {isLoading && (
              <tr>
                <td colSpan={8} className="px-2 py-3 text-slate-400">
                  <Loader2 className="inline h-3.5 w-3.5 animate-spin" /> Loading…
                </td>
              </tr>
            )}

            {!isLoading &&
              rows.map((row) => {
                const inherited = row.isPlantWide === true;
                return (
                  <tr key={`${inherited ? 'plant' : assetPath}:${row.metricKey}`}>
                    <td className="px-2 py-1.5 font-mono text-slate-800 dark:text-slate-200">
                      {row.metricKey}
                      {inherited && (
                        <span
                          className="ml-2 rounded bg-slate-100 px-1 text-[10px] text-slate-600 dark:bg-slate-700 dark:text-slate-300"
                          title="Plant-wide Metric Definition, inherited by this Asset"
                        >
                          plant-wide
                        </span>
                      )}
                      {row.isOverridden && (
                        <span
                          className="ml-2 rounded bg-amber-50 px-1 text-[10px] text-amber-700 dark:bg-amber-500/10 dark:text-amber-400"
                          title="Instance Override: an Asset Template will not overwrite this row"
                        >
                          overridden
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-slate-600 dark:text-slate-300">{row.displayName ?? '—'}</td>
                    <td className="px-2 py-1.5 text-slate-600 dark:text-slate-300">{row.unitOfMeasure ?? '—'}</td>
                    <td className="px-2 py-1.5 text-slate-600 dark:text-slate-300">{row.decimals ?? '—'}</td>
                    <td className="px-2 py-1.5 text-slate-600 dark:text-slate-300">{row.minValue ?? '—'}</td>
                    <td className="px-2 py-1.5 text-slate-600 dark:text-slate-300">{row.maxValue ?? '—'}</td>
                    <td className="px-2 py-1.5 text-slate-600 dark:text-slate-300">{row.deadband ?? '—'}</td>
                    <td className="px-2 py-1.5 text-right">
                      {canEdit && inherited && (
                        <button
                          type="button"
                          title="Override for this Asset"
                          onClick={() => setDraft(draftFromMetric(row, assetPath))}
                          className="rounded p-1 text-slate-400 hover:text-blue-600"
                        >
                          <Copy className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {canEdit && !inherited && (
                        <>
                          <button
                            type="button"
                            title="Edit"
                            onClick={() => setDraft(draftFromMetric(row, assetPath))}
                            className="rounded px-1 text-blue-600 hover:underline"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            title="Delete"
                            onClick={() => remove(row)}
                            className="rounded p-1 text-slate-400 hover:text-rose-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}

            {!isLoading && rows.length === 0 && !draft && (
              <tr>
                <td colSpan={8} className="px-2 py-3 text-slate-400">
                  No Metric Definitions. Add one, or adopt an Unmodelled Topic to create them from
                  what is already publishing.
                </td>
              </tr>
            )}

            {draft && (
              <tr className="bg-blue-50/50 dark:bg-blue-500/5">
                <td className="px-2 py-1.5">
                  <input
                    className={`${CELL_INPUT} font-mono`}
                    placeholder="ProcessValue/Temperature/value"
                    value={draft.metricKey}
                    onChange={(event) => setDraft({ ...draft, metricKey: event.target.value })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    className={CELL_INPUT}
                    value={draft.displayName ?? ''}
                    onChange={(event) => setDraft({ ...draft, displayName: orNull(event.target.value) })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    className={CELL_INPUT}
                    placeholder="°C"
                    value={draft.unitOfMeasure ?? ''}
                    onChange={(event) => setDraft({ ...draft, unitOfMeasure: orNull(event.target.value) })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    type="number"
                    className={CELL_INPUT}
                    value={draft.decimals ?? ''}
                    onChange={(event) => setDraft({ ...draft, decimals: numberOrNull(event.target.value) })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    type="number"
                    className={CELL_INPUT}
                    value={draft.minValue ?? ''}
                    onChange={(event) => setDraft({ ...draft, minValue: numberOrNull(event.target.value) })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    type="number"
                    className={CELL_INPUT}
                    value={draft.maxValue ?? ''}
                    onChange={(event) => setDraft({ ...draft, maxValue: numberOrNull(event.target.value) })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    type="number"
                    className={CELL_INPUT}
                    value={draft.deadband ?? ''}
                    onChange={(event) => setDraft({ ...draft, deadband: numberOrNull(event.target.value) })}
                  />
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right">
                  <button
                    type="button"
                    aria-label="Save tag"
                    onClick={() => void commit(draft)}
                    className="rounded p-1 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10"
                  >
                    <Check className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    aria-label="Cancel"
                    onClick={() => {
                      setDraft(null);
                      setError(null);
                    }}
                    className="rounded p-1 text-slate-400 hover:text-slate-700"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
```

- [ ] **Step 2: Read the inheritance flag**

Plan 1 adds `is_plant_wide` to `MetricDefinitionType`, derived from the row's null `asset_id`. That is the flag the table needs — the path is not on the row and reading it through the relationship would lazy-load after the session closed. In `types.ts` add to `GraphqlMetricDefinition`:

```ts
  /** True for a plant-wide Metric Definition that this Asset inherits. */
  isPlantWide?: boolean
```

and add `isPlantWide` to `METRIC_DEFINITION_FIELDS` in `queries.ts`.

Without it the console cannot tell an inherited row from an owned one and would offer to edit rows that belong to every Asset.

- [ ] **Step 3: Wire it under the detail form**

In `11_frontend/src/components/model/AssetModelView.tsx`:

```tsx
          {selectedPath ? (
            <>
              <AssetDetailForm path={selectedPath} onSaved={bumpRefresh} />
              <div className="px-5 pb-6">
                <TagTable
                  assetPath={selectedPath}
                  refreshToken={refreshToken}
                  onChanged={bumpRefresh}
                />
              </div>
            </>
          ) : (
            <p className="p-5 text-sm text-slate-400">Select an Asset to edit it.</p>
          )}
```

- [ ] **Step 4: Verify**

Run: `npm run lint`
Expected: clean.

Run: `npm run dev`. Select a Machine, add a tag with a Metric Key, a display name and `°C` as the Unit of Measure, save, and confirm it appears in the table. Edit it, delete it. Confirm a plant-wide Metric Definition (the seed's `conf/settings.yaml` has some) shows as **plant-wide** with only the copy-down action, and that using it creates an editable per-Asset row. Confirm the table is read-only for an operator.

Then confirm the enriched read agrees — query `getEnrichedTopic` (or the existing historian view) for a topic under that Asset in GraphiQL and check the new Unit of Measure comes back. That is the whole point of the table.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/model 11_frontend/src/services/graphql
git commit -m "feat(frontend): add the Metric Definition tag table to the Asset Model Explorer"
```

---

### Task 7: Duplicating an Asset

"Easily duplicate them" was the second half of the original request. One `duplicateAsset` call copies a subtree N times under a chosen parent, naming each copy from a pattern; this modal is the preview that makes pressing the button safe.

The preview is the whole point. Writing forty subtrees is not something to discover was wrong afterwards, so the modal shows every name it will create and marks the ones already taken — the server refuses a batch containing a collision and writes none of it, so a preview that highlights collisions is showing exactly what would happen.

**Files:**
- Create: `11_frontend/src/components/model/DuplicateAssetModal.tsx`
- Modify: `11_frontend/src/components/model/AssetModelView.tsx`

**Interfaces:**
- Consumes: `previewNames`, `patternError` (Task 1); `client.duplicateAsset`, `client.getAssetChildren` (Task 2).
- Produces: `<DuplicateAssetModal sourcePath={string} onClose={() => void} onDuplicated={(created: GraphqlAssetNode[]) => void} />`

- [ ] **Step 1: Write the modal**

Create `11_frontend/src/components/model/DuplicateAssetModal.tsx`:

```tsx
/**
 * Copy one Asset subtree N times under a chosen parent.
 *
 * The live name preview is the point of the screen: `duplicateAsset` writes whole
 * subtrees, and a name typed slightly wrong produces forty Assets that all have to be
 * deleted again. The preview marks names already in use because the server rejects the
 * whole batch if any name collides and writes none of it — so a highlighted row is not
 * a warning about one copy, it is a warning that nothing will be created.
 *
 * The expansion is computed locally by lib/model/naming.ts, which reimplements the
 * server's rule. The server's answer is the one that lands; this only has to agree,
 * which is why that module is the one part of the console with unit tests.
 */

import { Copy, Loader2, X } from 'lucide-react';
import React, { useEffect, useMemo, useState } from 'react';

import { usePlantScope } from '../../context/PlantScopeContext';
import { patternError, previewNames } from '../../lib/model/naming';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlAssetNode } from '../../services/graphql/types';

interface DuplicateAssetModalProps {
  sourcePath: string;
  onClose: () => void;
  onDuplicated: (created: GraphqlAssetNode[]) => void;
}

const parentOf = (path: string): string => {
  const cut = path.lastIndexOf('/');
  return cut === -1 ? '' : path.slice(0, cut);
};

const segmentOf = (path: string): string => {
  const cut = path.lastIndexOf('/');
  return cut === -1 ? path : path.slice(cut + 1);
};

const FIELD_CLASS =
  'w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100';
const LABEL_CLASS = 'block text-xs font-medium text-slate-600 dark:text-slate-400';

export const DuplicateAssetModal: React.FC<DuplicateAssetModalProps> = ({
  sourcePath,
  onClose,
  onDuplicated,
}) => {
  const { scopePath } = usePlantScope();

  // Default to the source's own parent: the common case is another Cell beside this
  // one, not the same Cell somewhere else in the plant.
  const [targetParentPath, setTargetParentPath] = useState<string>(() => parentOf(sourcePath) || (scopePath ?? ''));
  const [namingPattern, setNamingPattern] = useState<string>(() => `${segmentOf(sourcePath)}{n:02d}`);
  const [copies, setCopies] = useState<number>(1);
  const [start, setStart] = useState<number>(1);
  const [siblings, setSiblings] = useState<string[]>([]);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    unsGraphQLClient.getAssetChildren(targetParentPath || null).then((children) => {
      if (!cancelled) setSiblings(children.map((child) => child.segment));
    });
    return () => {
      cancelled = true;
    };
  }, [targetParentPath]);

  const invalid = patternError(namingPattern, copies);
  const preview = useMemo(
    () => previewNames(namingPattern, copies, start, siblings),
    [namingPattern, copies, start, siblings]
  );
  const collisions = preview.filter((entry) => entry.collides);

  const submit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const created = await unsGraphQLClient.duplicateAsset(
        sourcePath,
        targetParentPath,
        namingPattern,
        copies,
        start
      );
      onDuplicated(created);
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              <Copy className="h-4 w-4 text-blue-600" /> Duplicate Asset
            </h2>
            <p className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{sourcePath}</p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Copies the whole subtree, its Metric Definitions and its Asset Template link.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          <label className="space-y-1">
            <span className={LABEL_CLASS}>Create under</span>
            <input
              className={`${FIELD_CLASS} font-mono`}
              value={targetParentPath}
              onChange={(event) => setTargetParentPath(event.target.value)}
              placeholder="Enterprise/Site/Area/Line1"
            />
          </label>

          <div className="grid grid-cols-3 gap-3">
            <label className="col-span-1 space-y-1">
              <span className={LABEL_CLASS}>Copies</span>
              <input
                type="number"
                min={1}
                className={FIELD_CLASS}
                value={copies}
                onChange={(event) => setCopies(Number(event.target.value))}
              />
            </label>
            <label className="col-span-1 space-y-1">
              <span className={LABEL_CLASS}>Start at</span>
              <input
                type="number"
                className={FIELD_CLASS}
                value={start}
                onChange={(event) => setStart(Number(event.target.value))}
              />
            </label>
            <label className="col-span-1 space-y-1">
              <span className={LABEL_CLASS}>Name pattern</span>
              <input
                className={FIELD_CLASS}
                value={namingPattern}
                onChange={(event) => setNamingPattern(event.target.value)}
                placeholder="Cell{n:02d}"
              />
            </label>
          </div>

          <div className="rounded-md border border-slate-200 p-2 dark:border-slate-700">
            <p className={LABEL_CLASS}>
              Will create {preview.length} Asset{preview.length === 1 ? '' : 's'}
            </p>
            {invalid ? (
              <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">{invalid}</p>
            ) : (
              <ul className="mt-1 flex max-h-40 flex-wrap gap-1 overflow-y-auto">
                {preview.map((entry) => (
                  <li
                    key={entry.name}
                    className={`rounded px-1.5 py-0.5 font-mono text-xs ${
                      entry.collides
                        ? 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'
                        : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                    }`}
                    title={entry.collides ? 'An Asset with this name already exists here' : undefined}
                  >
                    {entry.name}
                  </li>
                ))}
              </ul>
            )}
            {collisions.length > 0 && (
              <p className="mt-2 text-xs text-rose-700 dark:text-rose-300">
                {collisions.length} name(s) are already taken here. The server writes the batch as
                one transaction, so nothing at all would be created.
              </p>
            )}
          </div>

          {error && (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              {error}
            </p>
          )}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-700 dark:border-slate-600 dark:text-slate-200"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={isSaving || Boolean(invalid) || collisions.length > 0 || !targetParentPath}
            className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Copy className="h-3.5 w-3.5" />}
            Duplicate
          </button>
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Wire it to the tree's duplicate action**

In `11_frontend/src/components/model/AssetModelView.tsx`, hold the source path and render the modal:

```tsx
  const [duplicateSource, setDuplicateSource] = useState<string | null>(null);
```

replace the `onDuplicate` placeholder from Task 4 with `onDuplicate={setDuplicateSource}`, and render the modal at the end of the outer `div`:

```tsx
      {duplicateSource && (
        <DuplicateAssetModal
          sourcePath={duplicateSource}
          onClose={() => setDuplicateSource(null)}
          onDuplicated={bumpRefresh}
        />
      )}
```

`onDuplicated` takes the created nodes but `bumpRefresh` ignores them — the tree reloads from the server rather than splicing them in, which is the same trade Task 4 made and for the same reason.

- [ ] **Step 3: Verify**

Run: `npm run lint`
Expected: clean.

Run: `npm run dev`. Duplicate a Work Cell with `Cell{n:02d}`, 5 copies, starting at 1. Confirm the preview reads `Cell01 … Cell05`; if `Cell01` already exists it turns red, the count warning appears and **Duplicate** is disabled. Change the start to 10, confirm the collision clears, duplicate, and confirm five new Cells appear in the tree with their Metric Definitions copied — check one in the tag table. If the source was an instance of an Asset Template, confirm the copies show the same template badge (they carry `template_node_id`, per spec section 9).

- [ ] **Step 4: Commit**

```bash
git add 11_frontend/src/components/model
git commit -m "feat(frontend): add Asset duplication with a live naming-pattern preview"
```

---

### Task 8: Adopting Unmodelled Topics

An Unmodelled Topic is a topic that has published data and matches no Asset — the plant telling you your model is incomplete. This drawer turns that list into Assets and Metric Definitions, which is the fastest way to model a plant that is already running and the only screen where the edge drives the model rather than the other way round.

The split between Asset path and Metric Key is the decision this screen exists to make, and only a human can make it: `Ent/Site/Area/Line1/Cell1/G1/ProcessValue/Temperature/value` could be a Machine `G1` with a Metric Key `ProcessValue/Temperature/value`, or a Work Cell `Cell1` with a longer key. The drawer proposes a split, shows what it implies, and lets it be changed per row.

**Files:**
- Create: `11_frontend/src/components/model/AdoptTopicsDrawer.tsx`
- Modify: `11_frontend/src/components/model/AssetModelView.tsx`

**Interfaces:**
- Consumes: `client.getUnmodelledTopics`, `client.adoptUnmodelledTopics` (Task 2); `usePlantScope` (Task 3); `ASSET_LEVELS` (Task 4).
- Produces: `<AdoptTopicsDrawer onClose={() => void} onAdopted={() => void} />`

- [ ] **Step 1: Write the drawer**

Create `11_frontend/src/components/model/AdoptTopicsDrawer.tsx`:

```tsx
/**
 * Turn topics that are publishing but match no Asset into Assets.
 *
 * The only judgement in the screen is where the Asset path ends and the Metric Key
 * begins: `.../Cell1/G1/ProcessValue/Temperature/value` could be the Machine `G1` with
 * the key `ProcessValue/Temperature/value`, or the Work Cell `Cell1` with a longer key.
 * Nothing in the topic says which, so the drawer proposes a split, shows the two halves
 * as separate fields, and lets each row be corrected. The proposal is deliberately
 * simple — the last conventional payload leaf marks the boundary — because a clever
 * guess that is wrong is harder to spot than an obvious one.
 *
 * Rows are opt-in. Adopting everything the query returned would create Assets from
 * topics an engineer has not looked at.
 */

import { Check, Inbox, Loader2, X } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';

import { usePlantScope } from '../../context/PlantScopeContext';
import { unsGraphQLClient } from '../../services/graphql/client';
import { ASSET_LEVELS } from './AssetTreeEditor';

const TOPIC_LIMIT = 200;

/**
 * The payload segments the UNS convention puts below an Asset. A topic's Asset path is
 * everything before the first of these; if none is present the last segment is treated
 * as the Metric Key, which is at least a boundary an engineer can see and move.
 */
const PAYLOAD_ROOTS = ['ProcessValue', 'Status', 'Setpoint', 'Alarm', 'Diagnostic', 'Counter'];

const proposeSplit = (topic: string): { assetPath: string; metricKey: string } => {
  const segments = topic.split('/');
  const boundary = segments.findIndex((segment) => PAYLOAD_ROOTS.includes(segment));
  const cut = boundary > 0 ? boundary : Math.max(1, segments.length - 1);
  return {
    assetPath: segments.slice(0, cut).join('/'),
    metricKey: segments.slice(cut).join('/'),
  };
};

/** A guess at the Asset Level from how deep the proposed Asset path is. */
const proposeLevel = (assetPath: string): string => {
  const depth = assetPath.split('/').length;
  return ASSET_LEVELS[Math.min(depth - 1, ASSET_LEVELS.length - 1)] ?? 'MACHINE';
};

interface Proposal {
  topic: string;
  assetPath: string;
  metricKey: string;
  level: string;
  displayName: string;
  unitOfMeasure: string;
  selected: boolean;
}

interface AdoptTopicsDrawerProps {
  onClose: () => void;
  onAdopted: () => void;
}

const INPUT_CLASS =
  'w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100';

export const AdoptTopicsDrawer: React.FC<AdoptTopicsDrawerProps> = ({ onClose, onAdopted }) => {
  const { scopePath } = usePlantScope();
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setIsLoading(true);
    unsGraphQLClient
      .getUnmodelledTopics(TOPIC_LIMIT, scopePath)
      .then((topics) =>
        setProposals(
          topics.map((topic) => {
            const split = proposeSplit(topic);
            return {
              topic,
              assetPath: split.assetPath,
              metricKey: split.metricKey,
              level: proposeLevel(split.assetPath),
              displayName: '',
              unitOfMeasure: '',
              selected: false,
            };
          })
        )
      )
      .finally(() => setIsLoading(false));
  }, [scopePath]);

  useEffect(load, [load]);

  const update = (index: number, patch: Partial<Proposal>) =>
    setProposals((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  const selected = proposals.filter((row) => row.selected);

  const adopt = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await unsGraphQLClient.adoptUnmodelledTopics(
        selected.map((row) => ({
          topic: row.topic,
          assetPath: row.assetPath,
          level: row.level,
          metricKey: row.metricKey || null,
          displayName: row.displayName || null,
          unitOfMeasure: row.unitOfMeasure || null,
        }))
      );
      onAdopted();
      // Reload rather than close: adopting one Asset usually reveals that the next
      // twenty topics belong to it too, and the list shrinks as they are adopted.
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40">
      <div className="flex h-full w-full max-w-3xl flex-col border-l border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
        <header className="flex items-start justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-700">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              <Inbox className="h-4 w-4 text-blue-600" /> Unmodelled Topics
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              These topics are publishing but match no Asset{scopePath ? ` under ${scopePath}` : ''}.
              Adopting one creates the Asset and its Metric Definition, so enriched reads start
              carrying a name and a Unit of Measure.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {error && (
          <p className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
            {error}
          </p>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-3">
          {isLoading ? (
            <p className="text-xs text-slate-400">
              <Loader2 className="inline h-3.5 w-3.5 animate-spin" /> Looking for unmodelled topics…
            </p>
          ) : proposals.length === 0 ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Nothing unmodelled here. Every topic that has published matches an Asset.
            </p>
          ) : (
            <ul className="space-y-2">
              {proposals.map((row, index) => (
                <li
                  key={row.topic}
                  className="rounded-md border border-slate-200 p-2 dark:border-slate-700"
                >
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={row.selected}
                      onChange={(event) => update(index, { selected: event.target.checked })}
                    />
                    <span className="min-w-0 flex-1 break-all font-mono text-xs text-slate-700 dark:text-slate-300">
                      {row.topic}
                    </span>
                  </label>

                  {row.selected && (
                    <div className="mt-2 grid gap-2 pl-6 sm:grid-cols-2">
                      <label className="space-y-1">
                        <span className="text-[11px] text-slate-500">Asset path</span>
                        <input
                          className={`${INPUT_CLASS} font-mono`}
                          value={row.assetPath}
                          onChange={(event) =>
                            update(index, {
                              assetPath: event.target.value,
                              level: proposeLevel(event.target.value),
                              // Keep the two halves adding up to the topic, so the
                              // server's own check cannot be surprised.
                              metricKey: row.topic.startsWith(`${event.target.value}/`)
                                ? row.topic.slice(event.target.value.length + 1)
                                : row.metricKey,
                            })
                          }
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-[11px] text-slate-500">Metric Key</span>
                        <input
                          className={`${INPUT_CLASS} font-mono`}
                          value={row.metricKey}
                          onChange={(event) => update(index, { metricKey: event.target.value })}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-[11px] text-slate-500">Asset Level</span>
                        <select
                          className={INPUT_CLASS}
                          value={row.level}
                          onChange={(event) => update(index, { level: event.target.value })}
                        >
                          {ASSET_LEVELS.map((level) => (
                            <option key={level} value={level}>
                              {level}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="space-y-1">
                        <span className="text-[11px] text-slate-500">Unit of Measure</span>
                        <input
                          className={INPUT_CLASS}
                          placeholder="°C"
                          value={row.unitOfMeasure}
                          onChange={(event) => update(index, { unitOfMeasure: event.target.value })}
                        />
                      </label>
                      <label className="space-y-1 sm:col-span-2">
                        <span className="text-[11px] text-slate-500">Asset display name</span>
                        <input
                          className={INPUT_CLASS}
                          value={row.displayName}
                          onChange={(event) => update(index, { displayName: event.target.value })}
                        />
                      </label>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="flex items-center justify-between border-t border-slate-200 px-5 py-3 dark:border-slate-700">
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {selected.length} of {proposals.length} selected
            {proposals.length === TOPIC_LIMIT && ` (showing the first ${TOPIC_LIMIT})`}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-700 dark:border-slate-600 dark:text-slate-200"
            >
              Close
            </button>
            <button
              type="button"
              onClick={adopt}
              disabled={isSaving || selected.length === 0}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              Adopt {selected.length || ''}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Wire it into the header**

In `11_frontend/src/components/model/AssetModelView.tsx`, replace the placeholder span from Task 4 Step 3 with a real trigger, showing the unmodelled count as a badge because that is the number an engineer is trying to drive to zero:

```tsx
            {canEdit && (
              <button
                type="button"
                onClick={() => setIsAdoptOpen(true)}
                className="flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                <Inbox className="h-3.5 w-3.5" /> Adopt topics
                {summary && summary.unmodelledTopics > 0 && (
                  <span className="rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-800 dark:bg-amber-500/20 dark:text-amber-300">
                    {summary.unmodelledTopics}
                  </span>
                )}
              </button>
            )}
```

Add `const [isAdoptOpen, setIsAdoptOpen] = useState<boolean>(false);`, `const { hasPermission } = useAuth();` with `const canEdit = hasPermission('asset_model_edit');`, and render the drawer beside the duplicate modal:

```tsx
      {isAdoptOpen && (
        <AdoptTopicsDrawer onClose={() => setIsAdoptOpen(false)} onAdopted={bumpRefresh} />
      )}
```

- [ ] **Step 3: Verify**

Run: `npm run lint`
Expected: clean.

Run: `npm run dev` with the simulator publishing. Open **Adopt topics** and confirm the badge count matches the header's unmodelled figure. Select a topic, check the proposed split, correct the Asset path by one segment and confirm the Metric Key follows so the two halves still add up to the topic. Set a Unit of Measure, adopt, and confirm: the drawer's list shrinks, the new Asset is in the tree, the Metric Definition is in its tag table, and the header's unmodelled count has dropped.

Then confirm the loop closes — read the same topic back through the enriched query in GraphiQL and check the Unit of Measure you just typed comes back. Adopting is only worth anything if it changes what a read returns.

- [ ] **Step 4: Commit**

```bash
git add 11_frontend/src/components/model
git commit -m "feat(frontend): add the Unmodelled Topics adoption drawer"
```

---

### Task 9: The Asset Template library and instantiation

An Asset Template is ISA-95's Equipment Class: define a Filling Line once, stamp it out forty times, and it stays linked so a later change reaches every instance. This task is the library — list, create, delete, instantiate, propagate, and see which instances have drifted. Editing a template's nodes is Task 10; a template created here has a root node and no children, which is already instantiable.

Deleting an Asset Template does **not** delete its instances. The FKs are `ON DELETE SET NULL`, so the Assets and their OEE configuration survive and simply stop being maintained — the alternative would cascade a template deletion into shift patterns and ideal cycle times. The confirmation says so, because "delete" reads like it removes what it made.

**Files:**
- Create: `11_frontend/src/components/model/TemplateLibraryView.tsx`
- Create: `11_frontend/src/components/model/InstantiateTemplateModal.tsx`
- Modify: `11_frontend/src/App.tsx`
- Modify: `11_frontend/src/components/layout/Sidebar.tsx` (nothing — the library is reached from the Explorer header; noted so nobody adds a second sidebar row)

**Interfaces:**
- Consumes: `client.getAssetTemplates`, `saveAssetTemplate`, `deleteAssetTemplate`, `instantiateTemplate`, `propagateAssetTemplate`, `getTemplateDrift` (Task 2); `templateToInput`, `newTemplateRoot`, `TemplateDraft` (Task 2); `previewNames`, `patternError` (Task 1); `ProjectionResultToast` (Task 3); `ASSET_LEVELS` (Task 4).
- Produces:
  - `<TemplateLibraryView />` at route `/model/templates`
  - `<InstantiateTemplateModal template={GraphqlAssetTemplate} onClose={() => void} onInstantiated={() => void} />`

- [ ] **Step 1: Write the instantiate modal**

Create `11_frontend/src/components/model/InstantiateTemplateModal.tsx`. It is close to `DuplicateAssetModal` by design — same pattern, same preview, same collision rule — but it is a separate file because the thing being stamped out is a template rather than an existing Asset, and merging them would mean a component with two modes and two sets of copy.

```tsx
/**
 * Create N Assets from one Asset Template.
 *
 * Same live preview as DuplicateAssetModal, for the same reason: this writes whole
 * subtrees. Separate from it because the source is a template rather than an Asset —
 * the parent must accept the template's rootLevel, the instances stay linked to the
 * template afterwards, and the copy differs throughout. One component with a mode flag
 * would be shorter and worse.
 */

import { LayoutTemplate, Loader2, X } from 'lucide-react';
import React, { useEffect, useMemo, useState } from 'react';

import { usePlantScope } from '../../context/PlantScopeContext';
import { patternError, previewNames } from '../../lib/model/naming';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlAssetTemplate } from '../../services/graphql/types';

interface InstantiateTemplateModalProps {
  template: GraphqlAssetTemplate;
  onClose: () => void;
  onInstantiated: () => void;
}

const FIELD_CLASS =
  'w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100';
const LABEL_CLASS = 'block text-xs font-medium text-slate-600 dark:text-slate-400';

export const InstantiateTemplateModal: React.FC<InstantiateTemplateModalProps> = ({
  template,
  onClose,
  onInstantiated,
}) => {
  const { scopePath } = usePlantScope();
  const [parentPath, setParentPath] = useState<string>(scopePath ?? '');
  const [namingPattern, setNamingPattern] = useState<string>(`${template.name}{n:02d}`);
  const [copies, setCopies] = useState<number>(1);
  const [start, setStart] = useState<number>(1);
  const [siblings, setSiblings] = useState<string[]>([]);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    unsGraphQLClient.getAssetChildren(parentPath || null).then((children) => {
      if (!cancelled) setSiblings(children.map((child) => child.segment));
    });
    return () => {
      cancelled = true;
    };
  }, [parentPath]);

  const invalid = patternError(namingPattern, copies);
  const preview = useMemo(
    () => previewNames(namingPattern, copies, start, siblings),
    [namingPattern, copies, start, siblings]
  );
  const collisions = preview.filter((entry) => entry.collides);

  const submit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await unsGraphQLClient.instantiateTemplate(
        template.id,
        parentPath,
        namingPattern,
        copies,
        start
      );
      onInstantiated();
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              <LayoutTemplate className="h-4 w-4 text-violet-600" /> Instantiate {template.name}
            </h2>
            {/*
              Deliberately no node count: getAssetTemplates does not load `nodes`, so any
              count rendered from this prop would read 1 for every template regardless of
              its real size. A wrong number is worse than none on a screen about to write
              whole subtrees.
            */}
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Creates one copy of this Asset Template's subtree per name below, rooted at
              Asset Level {template.rootLevel}. Each instance stays linked, so a later
              change to the Asset Template reaches it.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          <label className="space-y-1">
            <span className={LABEL_CLASS}>Create under</span>
            <input
              className={`${FIELD_CLASS} font-mono`}
              value={parentPath}
              onChange={(event) => setParentPath(event.target.value)}
              placeholder="Enterprise/Site/Area"
            />
          </label>

          <div className="grid grid-cols-3 gap-3">
            <label className="space-y-1">
              <span className={LABEL_CLASS}>Copies</span>
              <input
                type="number"
                min={1}
                className={FIELD_CLASS}
                value={copies}
                onChange={(event) => setCopies(Number(event.target.value))}
              />
            </label>
            <label className="space-y-1">
              <span className={LABEL_CLASS}>Start at</span>
              <input
                type="number"
                className={FIELD_CLASS}
                value={start}
                onChange={(event) => setStart(Number(event.target.value))}
              />
            </label>
            <label className="space-y-1">
              <span className={LABEL_CLASS}>Name pattern</span>
              <input
                className={FIELD_CLASS}
                value={namingPattern}
                onChange={(event) => setNamingPattern(event.target.value)}
              />
            </label>
          </div>

          <div className="rounded-md border border-slate-200 p-2 dark:border-slate-700">
            <p className={LABEL_CLASS}>
              Will create {preview.length} instance{preview.length === 1 ? '' : 's'}
            </p>
            {invalid ? (
              <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">{invalid}</p>
            ) : (
              <ul className="mt-1 flex max-h-40 flex-wrap gap-1 overflow-y-auto">
                {preview.map((entry) => (
                  <li
                    key={entry.name}
                    className={`rounded px-1.5 py-0.5 font-mono text-xs ${
                      entry.collides
                        ? 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'
                        : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                    }`}
                  >
                    {entry.name}
                  </li>
                ))}
              </ul>
            )}
            {collisions.length > 0 && (
              <p className="mt-2 text-xs text-rose-700 dark:text-rose-300">
                {collisions.length} name(s) already exist here, and the batch is one transaction —
                nothing would be created.
              </p>
            )}
          </div>

          {error && (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              {error}
            </p>
          )}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-700 dark:border-slate-600 dark:text-slate-200"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={isSaving || Boolean(invalid) || collisions.length > 0 || !parentPath}
            className="flex items-center gap-1 rounded-md bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            {isSaving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <LayoutTemplate className="h-3.5 w-3.5" />
            )}
            Instantiate
          </button>
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Write the library view**

Create `11_frontend/src/components/model/TemplateLibraryView.tsx`:

```tsx
/**
 * The Asset Template library: route /model/templates.
 *
 * A list rather than a tree — templates have no hierarchy among themselves, only within
 * themselves. Each row carries its instance count, because that number is what makes
 * "Propagate" consequential: pressing it on a template with forty instances rewrites
 * forty subtrees, and the count is the only warning that means anything.
 *
 * `Drift` is loaded on demand per template rather than for the list, because it walks
 * every instance. An engineer asks about drift for one template at a time.
 */

import { AlertTriangle, LayoutTemplate, Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { useAuth } from '../../context/AuthContext';
import { newTemplateRoot, templateToInput } from '../../lib/model/map-templates';
import { unsGraphQLClient } from '../../services/graphql/client';
import type {
  GraphqlAssetTemplate,
  GraphqlInstanceDrift,
  GraphqlTemplateProjection,
} from '../../services/graphql/types';
import { ASSET_LEVELS } from './AssetTreeEditor';
import { InstantiateTemplateModal } from './InstantiateTemplateModal';
import { ProjectionResultToast } from './ProjectionResultToast';

export const TemplateLibraryView: React.FC = () => {
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('asset_model_edit');

  const [templates, setTemplates] = useState<GraphqlAssetTemplate[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [projection, setProjection] = useState<GraphqlTemplateProjection | null>(null);
  const [instantiating, setInstantiating] = useState<GraphqlAssetTemplate | null>(null);
  const [driftById, setDriftById] = useState<Record<number, GraphqlInstanceDrift[]>>({});
  const [pendingDelete, setPendingDelete] = useState<GraphqlAssetTemplate | null>(null);

  const load = useCallback(() => {
    setIsLoading(true);
    unsGraphQLClient
      .getAssetTemplates()
      .then(setTemplates)
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(load, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const create = () => {
    const name = window.prompt('Name of the new Asset Template, e.g. Filling Line');
    if (!name) return;
    const rootLevel = window.prompt(`Asset Level of its root (${ASSET_LEVELS.join(', ')})`, 'LINE');
    if (!rootLevel) return;
    void run(() =>
      unsGraphQLClient.saveAssetTemplate(
        templateToInput({
          id: null,
          name,
          description: null,
          rootLevel,
          loadedUpdatedAt: null,
          // The server requires exactly one root node whose level matches rootLevel,
          // so a template cannot be created empty. Its segment is a placeholder that
          // instantiation replaces from the naming pattern.
          nodes: [newTemplateRoot(name.replace(/\s+/g, ''), rootLevel)],
        }),
        null
      )
    );
  };

  const propagate = (template: GraphqlAssetTemplate) => {
    void run(async () => {
      setProjection(await unsGraphQLClient.propagateAssetTemplate(template.id));
    });
  };

  const loadDrift = (template: GraphqlAssetTemplate) => {
    void unsGraphQLClient.getTemplateDrift(template.id).then((report) => {
      setDriftById((current) => ({ ...current, [template.id]: report }));
    });
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <LayoutTemplate className="h-5 w-5 text-violet-600" />
          <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100">
            Asset Templates
          </h1>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Define equipment once, instantiate it per plant
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/model"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Back to Asset Model
          </Link>
          {canEdit && (
            <button
              type="button"
              onClick={create}
              className="flex items-center gap-1 rounded-md bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700"
            >
              <Plus className="h-3.5 w-3.5" /> New template
            </button>
          )}
        </div>
      </header>

      {error && (
        <p className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          {error}
        </p>
      )}

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {isLoading ? (
          <p className="text-xs text-slate-400">
            <Loader2 className="inline h-3.5 w-3.5 animate-spin" /> Loading Asset Templates…
          </p>
        ) : templates.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No Asset Templates yet. Create one to define a Line or a Machine once and instantiate it
            per plant.
          </p>
        ) : (
          <ul className="space-y-2">
            {templates.map((template) => {
              const drift = driftById[template.id];
              const drifted = drift?.filter((entry) => entry.hasDrifted) ?? [];
              return (
                <li
                  key={template.id}
                  className="rounded-md border border-slate-200 p-3 dark:border-slate-700"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {template.name}
                        <span className="ml-2 text-[10px] uppercase tracking-wide text-slate-400">
                          {template.rootLevel}
                        </span>
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {template.description || 'No description'} · {template.instanceCount}{' '}
                        instance(s)
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Link
                        to={`/model/templates/${template.id}`}
                        className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                      >
                        Edit
                      </Link>
                      <button
                        type="button"
                        onClick={() => loadDrift(template)}
                        className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                      >
                        Check drift
                      </button>
                      {canEdit && (
                        <>
                          <button
                            type="button"
                            onClick={() => setInstantiating(template)}
                            className="rounded-md bg-violet-600 px-2 py-1 text-xs font-medium text-white hover:bg-violet-700"
                          >
                            Instantiate
                          </button>
                          <button
                            type="button"
                            onClick={() => propagate(template)}
                            title={`Rewrite all ${template.instanceCount} instance(s) from this Asset Template`}
                            className="flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                          >
                            <RefreshCw className="h-3.5 w-3.5" /> Propagate
                          </button>
                          <button
                            type="button"
                            aria-label={`Delete ${template.name}`}
                            onClick={() => setPendingDelete(template)}
                            className="rounded p-1 text-slate-400 hover:text-rose-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                  {drift && (
                    <div className="mt-2 border-t border-slate-100 pt-2 dark:border-slate-800">
                      {drifted.length === 0 ? (
                        <p className="text-xs text-emerald-700 dark:text-emerald-400">
                          Every instance matches this Asset Template.
                        </p>
                      ) : (
                        <>
                          <p className="flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-400">
                            <AlertTriangle className="h-3.5 w-3.5" /> {drifted.length} instance(s)
                            have diverged
                          </p>
                          <ul className="mt-1 space-y-0.5 text-xs text-slate-600 dark:text-slate-400">
                            {drifted.map((entry) => (
                              <li key={entry.assetPath}>
                                <span className="font-mono">{entry.assetPath}</span>
                                {entry.overriddenFields.length > 0 &&
                                  ` · overridden: ${entry.overriddenFields.join(', ')}`}
                                {entry.missingNodes.length > 0 &&
                                  ` · missing: ${entry.missingNodes.join(', ')}`}
                                {entry.extraNodes.length > 0 &&
                                  ` · extra: ${entry.extraNodes.join(', ')}`}
                                {entry.overriddenMetrics.length > 0 &&
                                  ` · overridden Metric Definitions: ${entry.overriddenMetrics.join(', ')}`}
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {instantiating && (
        <InstantiateTemplateModal
          template={instantiating}
          onClose={() => setInstantiating(null)}
          onInstantiated={load}
        />
      )}

      {pendingDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Delete the {pendingDelete.name} Asset Template?
            </h3>
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
              Its {pendingDelete.instanceCount} instance(s) are <strong>kept</strong>, along with
              their Metric Definitions and OEE configuration. They simply stop being maintained by
              a template, and each becomes an ordinary hand-built Asset.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingDelete(null)}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-700 dark:border-slate-600 dark:text-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  const { id } = pendingDelete;
                  setPendingDelete(null);
                  void run(() => unsGraphQLClient.deleteAssetTemplate(id));
                }}
                className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700"
              >
                Delete template
              </button>
            </div>
          </div>
        </div>
      )}

      <ProjectionResultToast projection={projection} onDismiss={() => setProjection(null)} />
    </div>
  );
};
```

- [ ] **Step 3: Route it**

In `11_frontend/src/App.tsx`, beside the `/model` route:

```tsx
          <Route path="/model/templates" element={<TemplateLibraryView />} />
```

Both routes are gated by the same `asset_model` feature and tab id `'model'`, so no new `canAccessTab` case is needed. The `/model/templates/:templateId` route the Edit link points at is added in Task 10; until then that link 404s inside the console, which is the expected state at the end of this task.

- [ ] **Step 4: Verify**

Run: `npm run lint`
Expected: clean.

Run: `npm run dev`. From the Explorer header open **Asset Templates**. Create one named `FillingLine` at Asset Level `LINE`. Instantiate it 3 times under an Area with `FillingLine{n:02d}`; confirm the preview, then confirm three new Assets appear in the Explorer tree with the template badge from Task 4. Press **Check drift** and confirm it reports no divergence. Now override a field on one instance (Task 5's form), check drift again and confirm that instance is listed with the field named. Press **Propagate** and confirm the toast reports the skipped override by path and field name. Delete the template and confirm the three instances remain in the tree, now without a badge.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/model 11_frontend/src/App.tsx
git commit -m "feat(frontend): add the Asset Template library, instantiation and drift report"
```

---

### Task 10: The Asset Template editor

The screen where a Filling Line is actually designed: its Template Nodes, their fields and attributes, and their Metric Definitions. Everything is held in one local `TemplateDraft` and saved in a single mutation, because a template's nodes are only valid as a set — a node whose parent was removed is a dangling child, and saving node-by-node would let the server see that intermediate state.

Two things separate this from the Asset detail form:

**The whole template saves at once, guarded by `expectedUpdatedAt`.** The draft carries `loadedUpdatedAt` from the moment it loaded; sending it back lets the server refuse a save that would silently overwrite a colleague's edit. Without the guard, last-write-wins across an entire template — and a template with forty instances propagates the loss.

**Every save shows its projection.** Saving a template is not a local act: it rewrites its instances. The `ProjectionResultToast` is not a nicety here, it is the only place the consequence is visible.

**Files:**
- Create: `11_frontend/src/components/model/TemplateEditor.tsx`
- Create: `11_frontend/src/components/model/TemplateTagTable.tsx`
- Modify: `11_frontend/src/App.tsx`

**Interfaces:**
- Consumes: `client.getAssetTemplate`, `saveAssetTemplate` (Task 2); `graphqlTemplateToDraft`, `templateToInput`, `childrenOf`, `newTemplateNode`, `rootNodeOf`, `TemplateDraft`, `TemplateNodeDraft`, `TemplateMetricDraft` (Task 2); `AttributeEditor` (Task 5); `ASSET_LEVELS`, `defaultChildLevel` (Task 4); `ProjectionResultToast` (Task 3).
- Produces:
  - `<TemplateEditor />` at route `/model/templates/:templateId`
  - `<TemplateTagTable metrics={TemplateMetricDraft[]} canEdit={boolean} onChange={(next: TemplateMetricDraft[]) => void} />`

No GraphQL work: Task 2 already added `GET_ASSET_TEMPLATE_QUERY` (which loads `nodes` via the `TEMPLATE_NODE_FIELDS` field list, unlike `GET_ASSET_TEMPLATES_QUERY`) and `client.getAssetTemplate(templateId): Promise<GraphqlAssetTemplate | null>`. It returns `null` rather than throwing so a bad `:templateId` in the URL is a "not found" screen instead of an error screen, which is what the `!draft` branch below renders.

- [ ] **Step 1: Write the template tag table**

Create `11_frontend/src/components/model/TemplateTagTable.tsx`. It is the template-side sibling of Task 6's `TagTable`, and much simpler: a Template Node's Metric Definitions are a plain list held in the draft, with no inheritance and no per-row save. Editing is purely local until the template is saved.

```tsx
/**
 * The Metric Definitions of one Template Node.
 *
 * Fully local: rows live in the parent's TemplateDraft and reach the server only when the
 * whole template is saved. That is why there is no per-row save button and no isPlantWide
 * column — a template has no plant, and its Metric Definitions are copied onto every
 * instance at projection time.
 *
 * Deliberately not shared with TagTable: that one reconciles inherited plant-wide rows
 * against per-Asset rows and saves each row on its own. The two look alike and behave
 * differently, and a shared component would have to be told which it was.
 */

import { Plus, Trash2 } from 'lucide-react';
import React, { useState } from 'react';

import type { TemplateMetricDraft } from '../../lib/model/map-templates';

interface TemplateTagTableProps {
  metrics: TemplateMetricDraft[];
  canEdit: boolean;
  onChange: (next: TemplateMetricDraft[]) => void;
}

const CELL_CLASS =
  'w-full rounded border border-transparent bg-transparent px-1.5 py-1 text-xs text-slate-900 hover:border-slate-300 focus:border-blue-500 focus:bg-white focus:outline-none dark:text-slate-100 dark:hover:border-slate-600 dark:focus:bg-slate-800';

const orNull = (value: string): string | null => (value.trim() === '' ? null : value.trim());
const numberOrNull = (value: string): number | null =>
  value.trim() === '' || Number.isNaN(Number(value)) ? null : Number(value);

const emptyMetric = (): TemplateMetricDraft => ({
  metricKey: '',
  displayName: null,
  unitOfMeasure: null,
  decimals: null,
  minValue: null,
  maxValue: null,
  deadband: null,
  description: null,
});

export const TemplateTagTable: React.FC<TemplateTagTableProps> = ({
  metrics,
  canEdit,
  onChange,
}) => {
  const [draft, setDraft] = useState<TemplateMetricDraft>(emptyMetric);

  const update = (index: number, patch: Partial<TemplateMetricDraft>) => {
    onChange(metrics.map((metric, position) => (position === index ? { ...metric, ...patch } : metric)));
  };

  const add = () => {
    if (!draft.metricKey.trim()) return;
    onChange([...metrics, { ...draft, metricKey: draft.metricKey.trim() }]);
    setDraft(emptyMetric());
  };

  return (
    <div className="rounded-md border border-slate-200 dark:border-slate-700">
      <table className="w-full text-left">
        <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
          <tr>
            <th className="px-2 py-1.5">Metric Key</th>
            <th className="px-2 py-1.5">Display name</th>
            <th className="px-2 py-1.5">Unit of Measure</th>
            <th className="px-2 py-1.5">Decimals</th>
            <th className="px-2 py-1.5">Min</th>
            <th className="px-2 py-1.5">Max</th>
            <th className="px-2 py-1.5">Deadband</th>
            <th className="w-8 px-2 py-1.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {metrics.length === 0 && (
            <tr>
              <td colSpan={8} className="px-2 py-3 text-xs text-slate-500 dark:text-slate-400">
                No Metric Definitions on this Template Node yet.
              </td>
            </tr>
          )}
          {metrics.map((metric, index) => (
            <tr key={`${metric.metricKey}-${index}`}>
              <td className="px-1 py-0.5">
                <input
                  className={`${CELL_CLASS} font-mono`}
                  disabled={!canEdit}
                  value={metric.metricKey}
                  onChange={(event) => update(index, { metricKey: event.target.value })}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  disabled={!canEdit}
                  value={metric.displayName ?? ''}
                  onChange={(event) => update(index, { displayName: orNull(event.target.value) })}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  disabled={!canEdit}
                  placeholder="°C"
                  value={metric.unitOfMeasure ?? ''}
                  onChange={(event) => update(index, { unitOfMeasure: orNull(event.target.value) })}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  disabled={!canEdit}
                  value={metric.decimals ?? ''}
                  onChange={(event) => update(index, { decimals: numberOrNull(event.target.value) })}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  disabled={!canEdit}
                  value={metric.minValue ?? ''}
                  onChange={(event) => update(index, { minValue: numberOrNull(event.target.value) })}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  disabled={!canEdit}
                  value={metric.maxValue ?? ''}
                  onChange={(event) => update(index, { maxValue: numberOrNull(event.target.value) })}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  disabled={!canEdit}
                  value={metric.deadband ?? ''}
                  onChange={(event) => update(index, { deadband: numberOrNull(event.target.value) })}
                />
              </td>
              <td className="px-1 py-0.5 text-right">
                {canEdit && (
                  <button
                    type="button"
                    aria-label={`Remove ${metric.metricKey}`}
                    onClick={() => onChange(metrics.filter((_, position) => position !== index))}
                    className="rounded p-1 text-slate-400 hover:text-rose-600"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </td>
            </tr>
          ))}

          {canEdit && (
            <tr className="bg-slate-50/60 dark:bg-slate-800/40">
              <td className="px-1 py-0.5">
                <input
                  className={`${CELL_CLASS} font-mono`}
                  placeholder="ProcessValue/Temperature"
                  value={draft.metricKey}
                  onChange={(event) => setDraft({ ...draft, metricKey: event.target.value })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') add();
                  }}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  placeholder="Temperature"
                  value={draft.displayName ?? ''}
                  onChange={(event) => setDraft({ ...draft, displayName: orNull(event.target.value) })}
                />
              </td>
              <td className="px-1 py-0.5">
                <input
                  className={CELL_CLASS}
                  placeholder="°C"
                  value={draft.unitOfMeasure ?? ''}
                  onChange={(event) =>
                    setDraft({ ...draft, unitOfMeasure: orNull(event.target.value) })
                  }
                />
              </td>
              <td colSpan={4} className="px-2 py-0.5 text-[10px] text-slate-400">
                Limits and deadband can be filled in once the row exists
              </td>
              <td className="px-1 py-0.5 text-right">
                <button
                  type="button"
                  aria-label="Add Metric Definition"
                  onClick={add}
                  disabled={!draft.metricKey.trim()}
                  className="rounded p-1 text-slate-400 hover:text-blue-600 disabled:opacity-40"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};
```

- [ ] **Step 2: Write the template editor**

Create `11_frontend/src/components/model/TemplateEditor.tsx`:

```tsx
/**
 * Design one Asset Template: route /model/templates/:templateId.
 *
 * The entire template is one local draft, saved in one mutation. Node-by-node saving would
 * make the server witness invalid intermediate states — a child whose parent was just
 * removed — and each save would re-project onto every instance, so a five-node edit would
 * rewrite forty instances five times.
 *
 * Renaming a node's segment rewrites its own relativePath and every descendant's, because
 * relativePath is derived from the chain of segments. Doing this in the draft rather than
 * on the server is deliberate: the engineer sees the whole reshaped tree before any of it
 * reaches an instance.
 */

import { AlertTriangle, ChevronDown, ChevronRight, Loader2, Plus, Save, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { useAuth } from '../../context/AuthContext';
import {
  childrenOf,
  graphqlTemplateToDraft,
  newTemplateNode,
  rootNodeOf,
  templateToInput,
} from '../../lib/model/map-templates';
import type { TemplateDraft, TemplateNodeDraft } from '../../lib/model/map-templates';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlTemplateProjection } from '../../services/graphql/types';
import { AttributeEditor } from './AttributeEditor';
import { ASSET_LEVELS, defaultChildLevel } from './AssetTreeEditor';
import { ProjectionResultToast } from './ProjectionResultToast';
import { TemplateTagTable } from './TemplateTagTable';

const FIELD_CLASS =
  'w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:disabled:bg-slate-800/50';
const LABEL_CLASS = 'block text-xs font-medium text-slate-600 dark:text-slate-400';

/** `path` and everything beneath it. Used by rename and delete, which both move subtrees. */
const subtreeOf = (nodes: TemplateNodeDraft[], path: string): TemplateNodeDraft[] =>
  nodes.filter((node) => node.relativePath === path || node.relativePath.startsWith(`${path}/`));

export const TemplateEditor: React.FC = () => {
  const { templateId } = useParams<{ templateId: string }>();
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('asset_model_edit');

  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [instanceCount, setInstanceCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isDirty, setIsDirty] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [projection, setProjection] = useState<GraphqlTemplateProjection | null>(null);
  const [selectedPath, setSelectedPath] = useState<string>('');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    const numericId = Number(templateId);
    if (!Number.isInteger(numericId)) {
      setError('That is not an Asset Template id.');
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    unsGraphQLClient
      .getAssetTemplate(numericId)
      .then((template) => {
        if (!template) {
          setError('No such Asset Template.');
          return;
        }
        setDraft(graphqlTemplateToDraft(template));
        setInstanceCount(template.instanceCount);
        setSelectedPath('');
        setIsDirty(false);
      })
      .finally(() => setIsLoading(false));
  }, [templateId]);

  useEffect(load, [load]);

  const edit = (mutate: (current: TemplateDraft) => TemplateDraft) => {
    setDraft((current) => (current ? mutate(current) : current));
    setIsDirty(true);
  };

  const selected = useMemo(
    () => draft?.nodes.find((node) => node.relativePath === selectedPath),
    [draft, selectedPath]
  );

  const patchSelected = (patch: Partial<TemplateNodeDraft>) => {
    edit((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.relativePath === selectedPath ? { ...node, ...patch } : node
      ),
    }));
  };

  /**
   * Renaming a segment rewrites the node's relativePath and every descendant's, since a
   * relativePath is the chain of segments above it. Rewriting only the node itself would
   * orphan its children with no visible sign until the save was refused.
   */
  const renameSegment = (path: string, segment: string) => {
    const trimmed = segment.trim();
    if (!trimmed || trimmed.includes('/')) return;
    edit((current) => {
      const node = current.nodes.find((candidate) => candidate.relativePath === path);
      if (!node) return current;
      const cut = path.lastIndexOf('/');
      const nextPath = cut === -1 ? trimmed : `${path.slice(0, cut)}/${trimmed}`;
      const moving = new Set(subtreeOf(current.nodes, path).map((entry) => entry.relativePath));
      return {
        ...current,
        nodes: current.nodes.map((entry) => {
          if (!moving.has(entry.relativePath)) return entry;
          const rewritten = `${nextPath}${entry.relativePath.slice(path.length)}`;
          return {
            ...entry,
            relativePath: rewritten,
            segment: entry.relativePath === path ? trimmed : entry.segment,
          };
        }),
      };
    });
    setSelectedPath((current) => {
      if (current !== path && !current.startsWith(`${path}/`)) return current;
      const cut = path.lastIndexOf('/');
      const nextPath = cut === -1 ? trimmed : `${path.slice(0, cut)}/${trimmed}`;
      return `${nextPath}${current.slice(path.length)}`;
    });
  };

  const addChild = (parentPath: string) => {
    if (!draft) return;
    const segment = window.prompt('Segment of the new Template Node, e.g. Filler');
    if (!segment?.trim()) return;
    const parent = draft.nodes.find((node) => node.relativePath === parentPath);
    const child = newTemplateNode(
      parentPath,
      segment.trim(),
      defaultChildLevel(parent?.level ?? draft.rootLevel)
    );
    if (draft.nodes.some((node) => node.relativePath === child.relativePath)) {
      setError(`This Asset Template already has a node at ${child.relativePath}.`);
      return;
    }
    setError(null);
    edit((current) => ({ ...current, nodes: [...current.nodes, child] }));
    setSelectedPath(child.relativePath);
  };

  const removeNode = (path: string) => {
    if (!draft || path === '') return;
    const doomed = subtreeOf(draft.nodes, path);
    const confirmed = window.confirm(
      `Remove ${path} and ${doomed.length - 1} descendant(s) from this Asset Template? ` +
        `On the next save, the matching Assets on all ${instanceCount} instance(s) are deactivated.`
    );
    if (!confirmed) return;
    const doomedPaths = new Set(doomed.map((node) => node.relativePath));
    edit((current) => ({
      ...current,
      nodes: current.nodes.filter((node) => !doomedPaths.has(node.relativePath)),
    }));
    if (doomedPaths.has(selectedPath)) setSelectedPath('');
  };

  const save = async () => {
    if (!draft) return;
    if (!rootNodeOf(draft)) {
      setError('An Asset Template needs exactly one root node. Reload to recover it.');
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      const result = await unsGraphQLClient.saveAssetTemplate(
        templateToInput(draft),
        draft.loadedUpdatedAt
      );
      setProjection(result);
      // Reload rather than trust the local draft: the save assigned ids to new nodes and
      // produced a fresh updatedAt, and keeping the stale one would make the next save
      // look like a concurrent edit.
      load();
    } catch (caught) {
      // The save and its projection are one transaction (spec 7.1.1), so a failure part-way
      // through forty instances leaves nothing behind. Saying so is the point: otherwise an
      // engineer reasonably assumes some instances took the change and starts checking.
      const message = caught instanceof Error ? caught.message : String(caught);
      setError(`${message} — nothing was written. The Asset Template and every instance are unchanged.`);
    } finally {
      setIsSaving(false);
    }
  };

  const renderNode = (node: TemplateNodeDraft, depth: number): React.ReactNode => {
    const children = draft ? childrenOf(draft.nodes, node.relativePath) : [];
    const isCollapsed = collapsed.has(node.relativePath);
    const isSelected = node.relativePath === selectedPath;
    return (
      <li key={node.relativePath}>
        <div
          className={`group flex items-center gap-1 rounded px-1 py-1 ${
            isSelected ? 'bg-violet-50 dark:bg-violet-500/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
          }`}
          style={{ paddingLeft: `${depth * 14 + 4}px` }}
        >
          {children.length > 0 ? (
            <button
              type="button"
              aria-label={isCollapsed ? `Expand ${node.segment}` : `Collapse ${node.segment}`}
              onClick={() =>
                setCollapsed((current) => {
                  const next = new Set(current);
                  if (next.has(node.relativePath)) next.delete(node.relativePath);
                  else next.add(node.relativePath);
                  return next;
                })
              }
              className="text-slate-400 hover:text-slate-700"
            >
              {isCollapsed ? (
                <ChevronRight className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
            </button>
          ) : (
            <span className="w-3.5" />
          )}

          <button
            type="button"
            onClick={() => setSelectedPath(node.relativePath)}
            className="min-w-0 flex-1 truncate text-left text-xs text-slate-800 dark:text-slate-200"
          >
            <span className="font-mono">{node.segment}</span>
            <span className="ml-1.5 text-[9px] uppercase tracking-wide text-slate-400">
              {node.level}
            </span>
            {node.relativePath === '' && (
              <span className="ml-1.5 text-[9px] uppercase tracking-wide text-violet-500">root</span>
            )}
            {node.metrics.length > 0 && (
              <span className="ml-1.5 text-[9px] text-slate-400">{node.metrics.length} tag(s)</span>
            )}
          </button>

          {canEdit && (
            <span className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
              <button
                type="button"
                aria-label={`Add a child under ${node.segment}`}
                onClick={() => addChild(node.relativePath)}
                className="rounded p-0.5 text-slate-400 hover:text-blue-600"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
              {node.relativePath !== '' && (
                <button
                  type="button"
                  aria-label={`Remove ${node.segment}`}
                  onClick={() => removeNode(node.relativePath)}
                  className="rounded p-0.5 text-slate-400 hover:text-rose-600"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </span>
          )}
        </div>

        {!isCollapsed && children.length > 0 && (
          <ul>{children.map((child) => renderNode(child, depth + 1))}</ul>
        )}
      </li>
    );
  };

  if (isLoading) {
    return (
      <p className="px-5 py-4 text-xs text-slate-400">
        <Loader2 className="inline h-3.5 w-3.5 animate-spin" /> Loading Asset Template…
      </p>
    );
  }

  if (!draft) {
    return (
      <div className="px-5 py-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">{error ?? 'No such Asset Template.'}</p>
        <Link to="/model/templates" className="mt-2 inline-block text-xs text-blue-600 hover:underline">
          Back to Asset Templates
        </Link>
      </div>
    );
  }

  const root = rootNodeOf(draft);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3 dark:border-slate-700">
        <div className="min-w-0">
          <input
            className="w-64 rounded-md border border-transparent px-1 py-0.5 text-base font-semibold text-slate-900 hover:border-slate-300 focus:border-blue-500 focus:outline-none dark:text-slate-100 dark:hover:border-slate-600"
            disabled={!canEdit}
            value={draft.name}
            onChange={(event) => edit((current) => ({ ...current, name: event.target.value }))}
          />
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            Root Asset Level {draft.rootLevel} · {draft.nodes.length} Template Node(s) ·{' '}
            {instanceCount} instance(s)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/model/templates"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Back to Asset Templates
          </Link>
          {canEdit && (
            <button
              type="button"
              onClick={save}
              disabled={isSaving || !isDirty}
              className="flex items-center gap-1 rounded-md bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {isSaving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              Save and propagate
            </button>
          )}
        </div>
      </header>

      {instanceCount > 0 && isDirty && (
        <p className="flex items-center gap-1.5 border-b border-amber-200 bg-amber-50 px-5 py-2 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          <AlertTriangle className="h-3.5 w-3.5" />
          Saving rewrites {instanceCount} instance(s). Fields an engineer has overridden on an
          instance are left alone and listed afterwards.
        </p>
      )}

      {error && (
        <p className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          {error}
        </p>
      )}

      <div className="flex min-h-0 flex-1">
        <nav className="w-72 shrink-0 overflow-y-auto border-r border-slate-200 px-2 py-2 dark:border-slate-700">
          {root ? (
            <ul>{renderNode(root, 0)}</ul>
          ) : (
            <p className="px-2 text-xs text-rose-600">
              This Asset Template has no root node. Reload the page.
            </p>
          )}
        </nav>

        <section className="min-w-0 flex-1 overflow-y-auto px-5 py-4">
          {!selected ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Select a Template Node to edit its fields and Metric Definitions.
            </p>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-1">
                  <span className={LABEL_CLASS}>Segment</span>
                  <input
                    className={`${FIELD_CLASS} font-mono`}
                    disabled={!canEdit}
                    defaultValue={selected.segment}
                    key={selected.relativePath}
                    onBlur={(event) => renameSegment(selected.relativePath, event.target.value)}
                  />
                  <span className="block text-[10px] text-slate-400">
                    Renaming rewrites this node's path and its descendants' on save
                  </span>
                </label>
                <label className="space-y-1">
                  <span className={LABEL_CLASS}>Asset Level</span>
                  <select
                    className={FIELD_CLASS}
                    disabled={!canEdit || selected.relativePath === ''}
                    value={selected.level}
                    onChange={(event) => patchSelected({ level: event.target.value })}
                  >
                    {ASSET_LEVELS.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </select>
                  {selected.relativePath === '' && (
                    <span className="block text-[10px] text-slate-400">
                      The root's Asset Level is the Asset Template's own {draft.rootLevel}
                    </span>
                  )}
                </label>
                <label className="space-y-1">
                  <span className={LABEL_CLASS}>Display name</span>
                  <input
                    className={FIELD_CLASS}
                    disabled={!canEdit}
                    value={selected.displayName ?? ''}
                    onChange={(event) =>
                      patchSelected({
                        displayName: event.target.value.trim() === '' ? null : event.target.value,
                      })
                    }
                  />
                </label>
                <label className="space-y-1">
                  <span className={LABEL_CLASS}>Description</span>
                  <input
                    className={FIELD_CLASS}
                    disabled={!canEdit}
                    value={selected.description ?? ''}
                    onChange={(event) =>
                      patchSelected({
                        description: event.target.value.trim() === '' ? null : event.target.value,
                      })
                    }
                  />
                </label>
              </div>

              <div>
                <p className={LABEL_CLASS}>Attributes</p>
                <AttributeEditor
                  value={selected.attributes}
                  disabled={!canEdit}
                  onChange={(attributes) => patchSelected({ attributes })}
                />
              </div>

              <div>
                <p className={LABEL_CLASS}>
                  Metric Definitions · copied onto every instance of this node
                </p>
                <TemplateTagTable
                  metrics={selected.metrics}
                  canEdit={canEdit}
                  onChange={(metrics) => patchSelected({ metrics })}
                />
              </div>
            </div>
          )}
        </section>
      </div>

      <ProjectionResultToast projection={projection} onDismiss={() => setProjection(null)} />
    </div>
  );
};
```

The Segment input uses `defaultValue` with `key={selected.relativePath}` and commits `onBlur`, not `onChange`. Renaming on every keystroke would rewrite the whole subtree per character, and since the rename also rewrites `selectedPath` the field would remount mid-word. The `key` is what reloads it when a different node is selected.

- [ ] **Step 3: Route it**

In `11_frontend/src/App.tsx`, after the `/model/templates` route from Task 9:

```tsx
          <Route path="/model/templates/:templateId" element={<TemplateEditor />} />
```

Order matters in react-router 7 only for identical specificity, and these three paths are distinct, so `/model`, `/model/templates` and `/model/templates/:templateId` can be declared in any order. They are listed adjacently so nobody has to search for the set.

- [ ] **Step 4: Verify**

Run: `npm run lint`
Expected: clean.

Run: `npm run dev`. Open an Asset Template from the library. Add a child Template Node, give it two Metric Definitions with Units of Measure, and save. Confirm the toast reports Assets updated and Metric Definitions written across the instances, then confirm in the Explorer that every instance grew the new Asset with both tags.

Now rename the child's segment and confirm the tree in the left pane reshapes immediately, including any grandchildren, before you save. Save, and confirm the instances' Assets are renamed and the toast warns about `console.alert_rules` topics if any exist.

Open the same template in two browser tabs. Save in the first, then save in the second, and confirm the second is refused with a concurrent-edit message rather than silently overwriting — this is the `expectedUpdatedAt` guard, and it is the one behaviour here that cannot be checked any other way.

Finally, sign in as an operator and confirm every field, the Save button and the per-node actions are absent or disabled.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/model 11_frontend/src/App.tsx
git commit -m "feat(frontend): add the Asset Template editor with concurrent-edit guard"
```

---

### Task 11: Document the screens and run everything

The console gained an authoring surface and a test script. Both need to be findable by someone who did not build them. The glossary needs almost nothing: `CONTEXT.md` already defines **Asset Level**, **Metric Definition**, **Unit of Measure** and **Unmodelled Topic** (lines 52, 64, 70 and 87), and Plan 1 Task 18 adds **Asset Template**, **Template Node**, **Instance Override**, **Plant Scope** and the **Bootstrap** / reconcile distinction. Only the frontend-specific terms are left.

**Files:**
- Modify: `11_frontend/README.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Consumes: everything from Tasks 1–10.
- Produces: no code.

- [ ] **Step 1: Document the screens in the frontend README**

In `11_frontend/README.md`, add to the `## Layout` list, after the **Sparkplug B** line:

```markdown
- **Asset Model** (`#/model`): author the ISA-95 hierarchy — Assets, their Metric
  Definitions, Asset Templates, and adoption of Unmodelled Topics.
```

Then add this section after `## Layout` and before `## Simulator Console`:

```markdown
## Asset Model authoring (`#/model`)

Where the plant hierarchy is authored. Two screens: the **Explorer** (`#/model`) edits
Assets and their Metric Definitions; the **Asset Template library** (`#/model/templates`)
defines reusable equipment and stamps it out. See
`docs/adr/0009-asset-templates-with-live-propagation.md`.

**The database is authoritative.** `conf/settings.yaml` bootstraps an empty database and
nothing more — the seed no longer reconciles, so it will not overwrite what is authored
here. Editing YAML after bootstrap changes nothing.

**Plant Scope.** One console serves many plants. The Enterprise/Site selector in the
Explorer header sets the subtree every screen reads, and persists per browser. It is a
view, not a permission: it narrows what is shown, not what may be written. Per-plant RBAC
is a separate piece of work.

**Permissions.** `asset_model` to see the screens, `asset_model_edit` to change anything.
Operators and auditors get the first and not the second. Enforcement is in the browser
only, as everywhere else in this console.

**Propagation is visible.** Saving an Asset Template rewrites its instances, so every
mutation that projects reports what it did — Assets created, updated, deactivated, Metric
Definitions written — and names each field it refused to overwrite because someone had
overridden it on an instance. Overridden fields are badged in the Asset form and in the
tag table.

**What renames cannot reach.** `console.alert_rules.topic` is free text, so renaming or
moving an Asset cannot update the Alert Rules pointing at it. Those operations return the
affected rules and the UI shows them as a warning to fix by hand.

**Tests.** `npm test` runs Vitest over `src/lib/**/*.test.ts` only. That covers
`src/lib/model/naming.ts`, the naming-pattern expander — the one piece of authoring logic
that is reimplemented in the browser rather than called on the server, which is exactly why
it is the piece with tests. Everything else structural is a GraphQL mutation and is tested
in `07_uns_graphql/test`.
```

- [ ] **Step 2: Add the two frontend terms to `CONTEXT.md`**

Append to the same glossary Plan 1 Task 18 Step 7 extends, in the style of the entries already there:

```markdown
**Asset Model authoring**:
The console screens at `#/model` that write the Asset Model through GraphQL mutations.
The console has no backend of its own (ADR-0005), so no structural rule lives in the
browser — path validity, Asset Level ordering and template projection are all decided
by the API.

**Naming pattern**:
A template for generating sibling Asset names when duplicating or instantiating, e.g.
`Cell{n:02d}`. `{n}` is the counter and `{n:0Nd}` zero-pads it to at least N digits. It
never truncates: at a start of 100, `Cell{n:02d}` yields `Cell100`, because narrowing it
to `Cell00` would silently collide with an existing Asset.
```

- [ ] **Step 3: Run everything**

Run: `cd 11_frontend && npm run lint`
Expected: clean. This is `tsc --noEmit`; there is no ESLint in this project.

Run: `npm test`
Expected: PASS, 12 tests in `src/lib/model/naming.test.ts`.

Run: `npm run build`
Expected: a clean Vite production build. Run it even though `lint` passed — `build` is the only step that resolves every import for real, so a component that nothing renders yet still gets checked.

- [ ] **Step 4: Walk the whole feature once**

With GraphQL running and Plan 1 deployed, sign in as an engineer and do this in order. Each step is a screen this plan added, and doing them in sequence is the only check that they hand off to each other correctly:

1. Pick an Enterprise and Site in the Plant Scope selector. Reload the page and confirm the choice survived.
2. Add an Area, then a Line beneath it. Confirm the Asset Level defaulted one step down each time.
3. Give the Line two Metric Definitions with Units of Measure. Confirm a plant-wide Metric Definition also appears, marked inherited and read-only.
4. Override one inherited row for this Asset and confirm it becomes editable and badged.
5. Duplicate the Line 4 times with `Line{n:02d}`. Confirm the preview, then confirm four Lines with their tags.
6. Create an Asset Template from the library, add a child node and two Metric Definitions, and instantiate it 3 times under the Area.
7. Override a field on one instance. Save the template again and confirm the toast names that field and that instance, and that the other two instances took the change.
8. Open the Unmodelled Topics drawer and adopt one topic. Confirm the split it proposed, then confirm the new Asset and Metric Definition appear in the tree and the drawer's count dropped.
9. Rename an Asset that an Alert Rule points at. Confirm the warning names the rule.
10. Sign in as an operator and confirm the whole surface is read-only.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/README.md CONTEXT.md
git commit -m "docs(frontend): document the Asset Model authoring screens"
```
