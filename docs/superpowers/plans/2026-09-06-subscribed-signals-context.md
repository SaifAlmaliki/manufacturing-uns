# Subscribed Signals Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let engineers attach Unit of Measure, Asset, types, and labels to subscribed OPC UA tags on `#/connectivity` Signals, and show unit plus Asset name on Condition Monitoring cards.

**Architecture:** Persist context on `console.connectivity_tags` plus two small catalogs (`units_of_measure`, `signal_labels`). GraphQL exposes list/save for catalogs and `updateConnectivityTag` for a row. Condition Monitoring keeps using `getConnectivityServers` and reads the new fields. When Asset and Unit of Measure are both set, upsert a Metric Definition so Enrichment stays aligned. Do not rewrite `mqtt_topic` on Asset assign.

**Tech Stack:** Alembic + SQLAlchemy (schema `console` / `model`), Strawberry GraphQL, React 19 + Vitest, existing console `FilterToolbar` / `SegmentTabs` / `PageShell`.

**Spec:** `docs/superpowers/specs/2026-09-06-subscribed-signals-context-design.md`

## Global Constraints

- **Say Unit of Measure, not unit.** `conf/oee/units.yaml` is OEE Lines, not `°C`.
- **Signal** in the UI = a subscribed `ConnectivityTag`. Not a new store. Not a Metric.
- **No `+ New Signal`.** Subscribe stays in Browse data.
- **Do not rewrite `mqtt_topic` when assigning an Asset.**
- **Discovery must not clobber** `unit_of_measure`, `asset_id`, `semantic_class`, `data_type`, `labels`, or an engineer-edited `display_name`.
- **All new fields optional.** Filter “missing unit”; do not hide unit-less tags from Condition Monitoring.
- **Writes:** engineer + admin (`connectivity`). CM only displays context (`uns_tree`).
- **Other…** persists to Postgres; duplicate symbol/name returns the existing row.
- **ON DELETE SET NULL** on `asset_id`. Unit and labels stay.
- **English only.** Compact console: `PageContent fullWidth`, no extra title banner.
- **TDD.** Watch the test fail before implementing. Commit after each task.
- **Regenerate** `07_uns_graphql/schema/uns_schema.graphql` in the GraphQL task.

---

## File Structure

```
09_uns_model/
  migrations/versions/0007_signal_context.py          CREATE
  src/uns_model/tables.py                             MODIFY  catalogs + tag columns + vocabs
  src/uns_model/connectivity.py                       MODIFY  merge, update_tag, catalogs, metric_key
  test/test_connectivity.py                           MODIFY  merge + metric_key + catalogs (unit)
  test/test_integration.py                            MODIFY  persist / discovery (if DB available)

07_uns_graphql/
  src/uns_graphql/type/connectivity.py                MODIFY  enums + tag fields
  src/uns_graphql/input/connectivity.py               MODIFY  ConnectivityTagUpdateInput
  src/uns_graphql/queries/connectivity.py             MODIFY  units, labels, getSubscribedSignals
  src/uns_graphql/mutations/connectivity.py           MODIFY  save unit/label, updateConnectivityTag
  src/uns_graphql/auth/require.py                     MODIFY  MUTATION_ROLES
  schema/uns_schema.graphql                           REGENERATE
  test/mutations/test_connectivity.py                 MODIFY
  test/type/test_connectivity.py                      MODIFY  enum drift

11_frontend/src/
  services/graphql/types.ts                           MODIFY
  services/graphql/queries.ts                         MODIFY
  services/graphql/client.ts                          MODIFY
  lib/connectivity/signal-filters.ts                  CREATE
  lib/connectivity/signal-filters.test.ts             CREATE
  components/connectivity/ConnectivityView.tsx        MODIFY  Servers | Signals tabs
  components/connectivity/ConnectivityView.test.tsx   MODIFY
  components/connectivity/SignalsTab.tsx              CREATE
  components/connectivity/SignalsTab.test.tsx         CREATE
  components/connectivity/SignalContextPanel.tsx      CREATE
  lib/condition-monitoring/match-tags.ts              MODIFY  Asset path scope
  lib/condition-monitoring/match-tags.test.ts         MODIFY
  components/condition-monitoring/SignalCard.tsx      MODIFY
  components/condition-monitoring/SignalCard.test.tsx MODIFY
```

---

### Task 1: Migration and ORM for catalogs + tag context

**Files:**
- Create: `09_uns_model/migrations/versions/0007_signal_context.py`
- Modify: `09_uns_model/src/uns_model/tables.py` (after `CONNECTIVITY_SECURITY_MODES`, and `ConnectivityTag`)
- Test: `09_uns_model/test/test_connectivity.py` (add vocab tests at top)

**Interfaces:**
- Consumes: `CONSOLE_SCHEMA`, `MODEL_SCHEMA` from `uns_model.model_config`
- Produces:
  - `SEEDED_UNITS_OF_MEASURE: tuple[str, ...] = ("°C", "K", "bar", "Pa", "kPa", "%", "kWh", "kW", "L/min", "m³", "Hz", "rpm", "A", "V")`
  - `SIGNAL_SEMANTIC_CLASSES: tuple[str, ...] = ("MeasuredValue", "EnergyConsumption", "CounterOK", "CounterNOK", "State")`
  - `SIGNAL_DATA_TYPES: tuple[str, ...] = ("Double", "Boolean", "Integer", "String")`
  - `class UnitOfMeasure` — `__tablename__ = "units_of_measure"`, schema `console`, PK `symbol: str`
  - `class SignalLabel` — `__tablename__ = "signal_labels"`, schema `console`, PK `name: str`
  - `ConnectivityTag.asset_id: int | None` FK `model.asset.id` ON DELETE SET NULL
  - `ConnectivityTag.unit_of_measure: str | None`
  - `ConnectivityTag.semantic_class: str | None`
  - `ConnectivityTag.data_type: str | None`
  - `ConnectivityTag.labels: list[str]` default `[]`

- [ ] **Step 1: Write the failing test**

Add to `09_uns_model/test/test_connectivity.py`:

```python
from uns_model.tables import (
    SEEDED_UNITS_OF_MEASURE,
    SIGNAL_DATA_TYPES,
    SIGNAL_SEMANTIC_CLASSES,
)

def test_seeded_units_include_celsius_and_kwh():
    assert "°C" in SEEDED_UNITS_OF_MEASURE
    assert "kWh" in SEEDED_UNITS_OF_MEASURE
    assert len(SEEDED_UNITS_OF_MEASURE) == len(set(SEEDED_UNITS_OF_MEASURE))

def test_semantic_classes_and_data_types_are_the_spec_vocabularies():
    assert SIGNAL_SEMANTIC_CLASSES == (
        "MeasuredValue",
        "EnergyConsumption",
        "CounterOK",
        "CounterNOK",
        "State",
    )
    assert SIGNAL_DATA_TYPES == ("Double", "Boolean", "Integer", "String")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest 09_uns_model/test/test_connectivity.py::test_seeded_units_include_celsius_and_kwh -q` from repo root, or from `09_uns_model`: `uv run pytest test/test_connectivity.py::test_seeded_units_include_celsius_and_kwh -q`

Expected: FAIL `ImportError` / attribute missing

- [ ] **Step 3: Write migration + ORM**

`0007_signal_context.py` — `revision = "0007_signal_context"`, `down_revision = "0006_connectivity_security"`.

```python
def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS console.units_of_measure (
          symbol TEXT PRIMARY KEY,
          name TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS console.signal_labels (
          name TEXT PRIMARY KEY,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for symbol in (
        "°C", "K", "bar", "Pa", "kPa", "%", "kWh", "kW", "L/min", "m³", "Hz", "rpm", "A", "V",
    ):
        op.execute(
            "INSERT INTO console.units_of_measure (symbol) VALUES (:s) ON CONFLICT DO NOTHING"
        )  # bind :s via op.execute(text(...), {"s": symbol})
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS asset_id BIGINT")
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_asset_id_fkey"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD CONSTRAINT connectivity_tags_asset_id_fkey "
        "FOREIGN KEY (asset_id) REFERENCES model.asset (id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS unit_of_measure TEXT")
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS semantic_class TEXT")
    op.execute("ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS data_type TEXT")
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD COLUMN IF NOT EXISTS labels TEXT[] NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_semantic_class_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD CONSTRAINT connectivity_tags_semantic_class_check "
        "CHECK (semantic_class IS NULL OR semantic_class IN "
        "('MeasuredValue', 'EnergyConsumption', 'CounterOK', 'CounterNOK', 'State'))"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags DROP CONSTRAINT IF EXISTS "
        "connectivity_tags_data_type_check"
    )
    op.execute(
        "ALTER TABLE console.connectivity_tags ADD CONSTRAINT connectivity_tags_data_type_check "
        "CHECK (data_type IS NULL OR data_type IN ('Double', 'Boolean', 'Integer', 'String'))"
    )
```

Use `sqlalchemy.text` + parameters for the seed inserts. Downgrade drops the new columns, FKs, checks, and the two catalog tables.

In `tables.py` add the three vocabs next to `CONNECTIVITY_SECURITY_MODES`. Add `UnitOfMeasure` and `SignalLabel` mapped classes. On `ConnectivityTag` add the five columns. Import `ARRAY` from `sqlalchemy.dialects.postgresql` for `labels`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest test/test_connectivity.py::test_seeded_units_include_celsius_and_kwh test/test_connectivity.py::test_semantic_classes_and_data_types_are_the_spec_vocabularies -q` from `09_uns_model`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/migrations/versions/0007_signal_context.py 09_uns_model/src/uns_model/tables.py 09_uns_model/test/test_connectivity.py
git commit -m "feat(model): add signal context columns and unit/label catalogs"
```

---

### Task 2: Repository — catalogs, merge protection, update_tag, metric_key

**Files:**
- Modify: `09_uns_model/src/uns_model/connectivity.py`
- Test: `09_uns_model/test/test_connectivity.py`

**Interfaces:**
- Consumes: `UnitOfMeasure`, `SignalLabel`, `ConnectivityTag`, `AssetModelRepository.define_metric`
- Produces:
  - `metric_key_for_tag(*, asset_path: str, mqtt_topic: str, browse_path: str, display_name: str) -> str`
  - `ConnectivityRepository.save_unit_of_measure(symbol: str, name: str | None = None) -> UnitOfMeasure` — trim; empty symbol raises `ValueError`; ON CONFLICT DO NOTHING then select
  - `ConnectivityRepository.list_units_of_measure() -> list[UnitOfMeasure]` — order by symbol
  - `ConnectivityRepository.save_signal_label(name: str) -> SignalLabel`
  - `ConnectivityRepository.list_signal_labels() -> list[SignalLabel]`
  - `ConnectivityRepository.update_tag(server_id: str, node_id: str, **fields) -> ConnectivityTag | None` — allowed keys: `display_name`, `mqtt_topic`, `asset_id`, `unit_of_measure`, `semantic_class`, `data_type`, `labels`. `None` for unit/asset/class/type clears. After save, if both `asset_id` and `unit_of_measure` are set, load Asset.path and call `define_metric(metric_key_for_tag(...), asset_path=path, unit_of_measure=..., display_name=...)`
  - `replace_subscribed_tags` `on_conflict_set` must **omit** `display_name`, `mqtt_topic`, and all context columns (only `browse_path`, `subscribed`, `updated_at` on UPDATE)

- [ ] **Step 1: Write the failing tests**

```python
from uns_model.connectivity import metric_key_for_tag, merge_discovered, ConnectivityTagSpec

def test_metric_key_uses_topic_suffix_under_asset_path():
    assert (
        metric_key_for_tag(
            asset_path="AcmeWater/Site1/Furnace",
            mqtt_topic="AcmeWater/Site1/Furnace/Heater/Temp",
            browse_path="Heater/Temp",
            display_name="Temp",
        )
        == "Heater/Temp"
    )

def test_metric_key_falls_back_to_browse_path_when_topic_is_not_under_asset():
    assert (
        metric_key_for_tag(
            asset_path="AcmeWater/Site1/Furnace",
            mqtt_topic="Server/OpcPlc/Temperature",
            browse_path="Objects/Temperature",
            display_name="Temperature",
        )
        == "Objects/Temperature"
    )

def test_merge_does_not_need_context_fields_to_keep_identity():
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered = [ConnectivityTagSpec("ns=3;s=A", "Path/A/Renamed", "Tank", "Raw/A", True)]
    merged = merge_discovered(existing, discovered)
    assert merged[0].mqtt_topic == "Plant/A"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest test/test_connectivity.py::test_metric_key_uses_topic_suffix_under_asset_path -q` from `09_uns_model`

Expected: FAIL `ImportError` for `metric_key_for_tag`

- [ ] **Step 3: Implement**

```python
def metric_key_for_tag(
    *, asset_path: str, mqtt_topic: str, browse_path: str, display_name: str
) -> str:
    prefix = asset_path.rstrip("/") + "/"
    if mqtt_topic.startswith(prefix):
        return mqtt_topic[len(prefix):]
    if mqtt_topic == asset_path:
        return display_name or browse_path or mqtt_topic
    return browse_path or display_name or mqtt_topic
```

Implement `save_unit_of_measure` / `save_signal_label` with `insert(...).on_conflict_do_nothing()` then `select`. Trim; reject `""`.

`update_tag`: build a values dict from provided kwargs only; `updated_at=func.now()`. Then if the stored row has both asset and unit, resolve Asset.path in the same session and call `AssetModelRepository(self._database).define_metric(...)`.

Change `on_conflict_set` in `replace_subscribed_tags` to:

```python
on_conflict_set = {
    "browse_path": tag.browse_path,
    "subscribed": tag.subscribed,
    "updated_at": func.now(),
}
```

Do **not** set `display_name` on UPDATE.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest test/test_connectivity.py -q` from `09_uns_model`

Expected: PASS (existing merge tests still pass)

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/connectivity.py 09_uns_model/test/test_connectivity.py
git commit -m "feat(model): persist signal context without clobbering on rediscovery"
```

---

### Task 3: GraphQL types, queries, mutations, roles, schema dump

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/type/connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/input/connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/queries/connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/auth/require.py`
- Modify: `07_uns_graphql/schema/uns_schema.graphql` (regenerate)
- Test: `07_uns_graphql/test/type/test_connectivity.py`
- Test: `07_uns_graphql/test/mutations/test_connectivity.py`

**Interfaces:**
- Consumes: Task 2 repository methods
- Produces GraphQL:
  - enums `SignalSemanticClass`, `SignalDataType` (values = table vocabularies)
  - `ConnectivityTagType` fields: `assetId: Int`, `assetPath: String`, `assetDisplayName: String`, `unitOfMeasure: String`, `semanticClass: SignalSemanticClass`, `dataType: SignalDataType`, `labels: [String!]!`
  - `UnitOfMeasureType { symbol, name }`
  - `SubscribedSignalType` = tag fields + `serverId`, `serverName`
  - `ConnectivityTagUpdateInput` — all fields optional: `displayName`, `mqttTopic`, `assetId`, `unitOfMeasure`, `semanticClass`, `dataType`, `labels`
  - `unitsOfMeasure: [UnitOfMeasureType!]!`
  - `signalLabels: [String!]!`
  - `getSubscribedSignals: [SubscribedSignalType!]!` — `subscribed == true` across servers
  - `saveUnitOfMeasure(symbol: String!, name: String): UnitOfMeasureType!`
  - `saveSignalLabel(name: String!): String!`
  - `updateConnectivityTag(serverId: String!, nodeId: String!, patch: ConnectivityTagUpdateInput!): ConnectivityTagType!`

`from_tag` must pass through the new columns (`getattr` defaults: `None` / `[]`). For `assetPath` / `assetDisplayName`, if the ORM has `asset` relationship loaded use it; else leave null (repository `update_tag` / list can `selectinload` Asset).

MUTATION_ROLES:

```python
"saveUnitOfMeasure": frozenset({"engineer", "admin"}),
"saveSignalLabel": frozenset({"engineer", "admin"}),
"updateConnectivityTag": frozenset({"engineer", "admin"}),
```

Keep `updateConnectivityTagTopic` working (thin wrapper around `update_tag(..., mqtt_topic=)`).

- [ ] **Step 1: Write the failing tests**

In `test/type/test_connectivity.py` add `SignalSemanticClass` / `SignalDataType` to the existing parametrize against `SIGNAL_SEMANTIC_CLASSES` / `SIGNAL_DATA_TYPES`.

In `test/mutations/test_connectivity.py`:

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_save_unit_of_measure_persists_other_symbol():
    repository = AsyncMock()
    repository.save_unit_of_measure.return_value = SimpleNamespace(symbol="NTU", name="turbidity")
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            'mutation { saveUnitOfMeasure(symbol: "NTU", name: "turbidity") { symbol name } }',
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["saveUnitOfMeasure"] == {"symbol": "NTU", "name": "turbidity"}
    repository.save_unit_of_measure.assert_awaited_once_with("NTU", "turbidity")


@pytest.mark.asyncio(loop_scope="function")
async def test_update_connectivity_tag_passes_unit_and_asset():
    repository = AsyncMock()
    stored = _tag()
    stored.unit_of_measure = "°C"
    stored.asset_id = 42
    stored.labels = ["Cycle"]
    repository.update_tag.return_value = stored
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation ($patch: ConnectivityTagUpdateInput!) {
              updateConnectivityTag(serverId: "s1", nodeId: "ns=2;s=Temperature", patch: $patch) {
                unitOfMeasure labels
              }
            }
            """,
            variable_values={"patch": {"unitOfMeasure": "°C", "assetId": 42, "labels": ["Cycle"]}},
            context_value=ADMIN,
        )
    assert result.errors is None
    assert result.data["updateConnectivityTag"]["unitOfMeasure"] == "°C"
```

Use `types.SimpleNamespace` if the ORM helper has no those attrs — or set them on `_tag()` after adding columns to the constructor in the test helper.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest test/mutations/test_connectivity.py::test_save_unit_of_measure_persists_other_symbol -q` from `07_uns_graphql`

Expected: FAIL — unknown field `saveUnitOfMeasure`

- [ ] **Step 3: Implement types, resolvers, roles**

Wire `from_tag` new fields. Resolvers call the repository. `get_subscribed_signals` loops `list_servers` + `list_subscribed_tags`, skips `not subscribed`.

- [ ] **Step 4: Export schema and run tests**

Run from `07_uns_graphql`:

```
uv run strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema --output ./schema/uns_schema.graphql
uv run pytest test/mutations/test_connectivity.py test/type/test_connectivity.py -q
```

Expected: PASS; dump contains `saveUnitOfMeasure` and `updateConnectivityTag`

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql
git commit -m "feat(graphql): expose signal context catalogs and tag updates"
```

---

### Task 4: Frontend GraphQL client

**Files:**
- Modify: `11_frontend/src/services/graphql/types.ts`
- Modify: `11_frontend/src/services/graphql/queries.ts` (`CONNECTIVITY_TAG_FIELDS` + new documents)
- Modify: `11_frontend/src/services/graphql/client.ts`

**Interfaces:**
- Consumes: Task 3 schema
- Produces:
  - `GraphqlSignalSemanticClass`, `GraphqlSignalDataType`
  - Extra optional fields on `GraphqlConnectivityTag`: `assetId`, `assetPath`, `assetDisplayName`, `unitOfMeasure`, `semanticClass`, `dataType`, `labels`
  - `GraphqlSubscribedSignal` extends tag + `serverName`
  - `GraphqlConnectivityTagPatch`
  - `unsGraphQLClient.unitsOfMeasure()`, `saveUnitOfMeasure(symbol, name?)`, `signalLabels()`, `saveSignalLabel(name)`, `getSubscribedSignals()`, `updateConnectivityTag(serverId, nodeId, patch)`

- [ ] **Step 1: Write the failing test**

If there is no client unit test file, add `11_frontend/src/services/graphql/client.signals.test.ts` that imports the query strings and asserts they contain `unitOfMeasure` and `updateConnectivityTag`:

```ts
import { describe, expect, it } from 'vitest'
import {
  GET_SUBSCRIBED_SIGNALS_QUERY,
  SAVE_UNIT_OF_MEASURE_MUTATION,
  UPDATE_CONNECTIVITY_TAG_MUTATION,
} from './queries'

describe('signal context documents', () => {
  it('asks for unitOfMeasure on subscribed signals', () => {
    expect(GET_SUBSCRIBED_SIGNALS_QUERY).toMatch(/unitOfMeasure/)
    expect(UPDATE_CONNECTIVITY_TAG_MUTATION).toMatch(/updateConnectivityTag/)
    expect(SAVE_UNIT_OF_MEASURE_MUTATION).toMatch(/saveUnitOfMeasure/)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/services/graphql/client.signals.test.ts` from `11_frontend`

Expected: FAIL cannot find module `./queries` exports

- [ ] **Step 3: Add types, documents, client methods**

Extend `CONNECTIVITY_TAG_FIELDS` with the new scalars. Add documents. Client methods follow `saveConnectivityServer` (throw on `res.error`).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- src/services/graphql/client.signals.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/services/graphql
git commit -m "feat(frontend): GraphQL client for signal context"
```

---

### Task 5: Signal filters (pure)

**Files:**
- Create: `11_frontend/src/lib/connectivity/signal-filters.ts`
- Test: `11_frontend/src/lib/connectivity/signal-filters.test.ts`

**Interfaces:**
- Consumes: `GraphqlSubscribedSignal`
- Produces:
  - `filterSubscribedSignals(rows, { search, serverId, missingUnit, semanticClass, label }): GraphqlSubscribedSignal[]`
  - search matches `displayName`, `mqttTopic`, `nodeId`, `serverName` (case-insensitive)

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import { filterSubscribedSignals } from './signal-filters'
import type { GraphqlSubscribedSignal } from '../../services/graphql/types'

const row = (over: Partial<GraphqlSubscribedSignal> = {}): GraphqlSubscribedSignal => ({
  serverId: 's1',
  serverName: 'opcplc',
  nodeId: 'ns=3;s=T101',
  browsePath: 'T101/Level',
  displayName: 'Level',
  mqttTopic: 'Plant/T101/Level',
  subscribed: true,
  unitOfMeasure: '°C',
  labels: ['Cycle'],
  ...over,
})

describe('filterSubscribedSignals', () => {
  it('keeps only missing-unit rows when that chip is on', () => {
    const rows = [row(), row({ nodeId: 'n2', unitOfMeasure: null })]
    expect(filterSubscribedSignals(rows, { missingUnit: true }).map((r) => r.nodeId)).toEqual(['n2'])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- src/lib/connectivity/signal-filters.test.ts`

Expected: FAIL module not found

- [ ] **Step 3: Implement `filterSubscribedSignals`**

Treat `undefined` and `''` and `null` as missing unit.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/connectivity/signal-filters.ts 11_frontend/src/lib/connectivity/signal-filters.test.ts
git commit -m "feat(frontend): filter subscribed signals by unit and search"
```

---

### Task 6: Signals tab + side panel + ConnectivityView tabs

**Files:**
- Create: `11_frontend/src/components/connectivity/SignalsTab.tsx`
- Create: `11_frontend/src/components/connectivity/SignalsTab.test.tsx`
- Create: `11_frontend/src/components/connectivity/SignalContextPanel.tsx`
- Modify: `11_frontend/src/components/connectivity/ConnectivityView.tsx`
- Modify: `11_frontend/src/components/connectivity/ConnectivityView.test.tsx`

**Interfaces:**
- Consumes: Task 4 client, Task 5 filters, `getAssets` for the Asset picker (already on `unsGraphQLClient`)
- Produces: `SignalsTab` page body; `ConnectivityView` `FilterToolbar` `tabs: Servers | Signals`

**UI (frontend-design / compact console):**
- `FilterToolbar` tabs `servers` | `signals` (use existing `tabs` prop).
- Signals: table with checkbox, display name, server, Asset, Unit of Measure `<select>`, class, data type, labels.
- Unit `<select>` options = catalog + empty + `Other…`. Other… prompt (`window.prompt` is acceptable in tests if you stub it; prefer a small inline field) → `saveUnitOfMeasure` → refresh options → `updateConnectivityTag`.
- Click display name opens `SignalContextPanel` (dialog): name, topic, Save (`updateConnectivityTag`), Unsubscribe (confirm → existing `unsubscribeConnectivityTag`).
- Bulk bar when `selected.size > 0`: apply unit / Asset / class / data type / label. Loop `updateConnectivityTag` per id. Do not send `mqttTopic`.
- Empty copy: `Subscribe variables from Browse data on a server — then attach units here.`
- Load error: same rose banner as Servers.

- [ ] **Step 1: Write the failing tests**

In `SignalsTab.test.tsx` mock `unsGraphQLClient` (`getSubscribedSignals`, `unitsOfMeasure`, `signalLabels`, `getAssets`, `updateConnectivityTag`, `saveUnitOfMeasure`, `unsubscribeConnectivityTag`).

```ts
it('lists a subscribed signal and saves a unit from the dropdown', async () => {
  // getSubscribedSignals → one row unitOfMeasure null
  // change Unit of Measure select to °C
  await waitFor(() =>
    expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', { unitOfMeasure: '°C' }),
  )
})

it('persists Other unit and then it appears in the dropdown', async () => {
  // choose Other…, type NTU, confirm
  await waitFor(() => expect(saveUnitOfMeasure).toHaveBeenCalledWith('NTU', undefined))
})
```

In `ConnectivityView.test.tsx`:

```ts
it('shows Servers and Signals tabs', async () => {
  render(<ConnectivityView />)
  await waitFor(() => expect(screen.getByRole('button', { name: /signals/i })).toBeTruthy())
  expect(screen.getByRole('button', { name: /servers/i })).toBeTruthy()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test:run -- src/components/connectivity/SignalsTab.test.tsx src/components/connectivity/ConnectivityView.test.tsx`

Expected: FAIL missing Signals tab / missing SignalsTab

- [ ] **Step 3: Implement SignalsTab, panel, wire tabs**

Keep Servers content as today when `activeTab === 'servers'`. Do not move Browse data off Servers.

- [ ] **Step 4: Run tests to verify they pass**

Expected: PASS including existing ConnectivityView tests

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/connectivity
git commit -m "feat(frontend): Signals tab to edit subscribed tag context"
```

---

### Task 7: Condition Monitoring card context + Asset scope

**Files:**
- Modify: `11_frontend/src/lib/condition-monitoring/match-tags.ts`
- Modify: `11_frontend/src/lib/condition-monitoring/match-tags.test.ts`
- Modify: `11_frontend/src/components/condition-monitoring/SignalCard.tsx`
- Modify: `11_frontend/src/components/condition-monitoring/SignalCard.test.tsx`

**Interfaces:**
- Consumes: `GraphqlConnectivityTag.assetPath`, `unitOfMeasure`, `assetDisplayName`, `dataType`
- Produces:
  - `tagMatchesNode` also true when `tag.assetPath` equals `node.topic`, either is a prefix of the other, or Asset last segment equals node leaf
  - `SignalCard` shows `latest.v` + ` ${unitOfMeasure}` when set; subtitle Asset display name; chart `Boolean` → step, `Double|Integer` → line, else today’s inference. Do **not** print semantic class or labels. Keep BOOLEAN/DOUBLE hint only when `dataType` is unset (today’s behaviour)

- [ ] **Step 1: Write the failing tests**

```ts
it('matches by assigned Asset path prefix', () => {
  const assigned = tag({
    assetPath: 'AcmeWater/Site1/Furnace',
    mqttTopic: 'Server/OpcPlc/Temperature',
  })
  expect(tagMatchesNode(assigned, node('AcmeWater/Site1/Furnace'))).toBe(true)
  expect(tagMatchesNode(assigned, node('AcmeWater/Site1'))).toBe(true)
})
```

```ts
it('shows unit of measure and asset name next to the value', () => {
  render(
    <SignalCard
      tag={{ ...TAG, unitOfMeasure: '°C', assetDisplayName: 'Furnace', dataType: 'Double' }}
      samples={[{ t: 1, v: 1234, quality: 'GOOD', boolean: false }]}
      latest={{ t: 1, v: 1234, quality: 'GOOD', boolean: false }}
    />,
  )
  expect(screen.getByText(/1234/)).toBeTruthy()
  expect(screen.getByText('°C')).toBeTruthy()
  expect(screen.getByText('Furnace')).toBeTruthy()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test:run -- src/lib/condition-monitoring/match-tags.test.ts src/components/condition-monitoring/SignalCard.test.tsx`

Expected: FAIL (no °C / Asset match false)

- [ ] **Step 3: Implement matching and card**

```ts
export function tagMatchesNode(tag: GraphqlConnectivityTag, node: UnsNode): boolean {
  const topic = tag.mqttTopic
  if (topic === node.topic || topic.startsWith(`${node.topic}/`)) return true
  const assetPath = tag.assetPath
  if (assetPath) {
    if (
      assetPath === node.topic
      || assetPath.startsWith(`${node.topic}/`)
      || node.topic.startsWith(`${assetPath}/`)
    ) {
      return true
    }
    const assetLeaf = pathSegments(assetPath).at(-1)
    const nodeLeaf = pathSegments(node.topic).at(-1)
    if (assetLeaf && assetLeaf === nodeLeaf) return true
  }
  const leaf = pathSegments(node.topic).at(-1)
  if (!leaf) return false
  const haystack = [...pathSegments(tag.mqttTopic), ...pathSegments(tag.browsePath)]
  return haystack.includes(leaf)
}
```

On the card, prefer `tag.dataType === 'Boolean'` for step charts.

- [ ] **Step 4: Run tests to verify they pass**

Expected: PASS existing CM tests still pass

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/condition-monitoring 11_frontend/src/components/condition-monitoring
git commit -m "feat(frontend): show unit and asset on condition monitoring cards"
```

---

## Self-review (spec coverage)

| Spec section | Task |
| --- | --- |
| 6.1–6.3 catalogs + tag columns | 1 |
| 6.3 discovery must not overwrite context | 2 (`on_conflict_set`) |
| 6.4 Metric Definition upsert | 2 `update_tag` |
| 7 GraphQL | 3 |
| 8 Signals tab UI, Other…, bulk, panel | 6 (filters 5, client 4) |
| 9 CM unit + Asset + data type + scope | 7 |
| 10 errors / viewer AccessRestricted | 6 (existing banner + AccessRestricted) |
| 11 tests | each task |
| 12 out of scope | not tasked |

No TBD. Names are consistent: `updateConnectivityTag`, `metric_key_for_tag`, `unitOfMeasure`, `saveUnitOfMeasure`.
