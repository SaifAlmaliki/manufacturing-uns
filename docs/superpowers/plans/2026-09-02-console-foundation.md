# Console Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every capability the platform already has callable and tested from the console's data layer, make connection state truthful, and add the one missing read query — without changing a single screen.

**Architecture:** Three layers, bottom-up. In `09_uns_model` and `07_uns_graphql`, add a read for the authored downtime reason codes and pin the schema dump so it can never go stale again. In `11_frontend`, install Vitest, narrow `SystemHealthInfo` to what a browser can actually observe, and add the eleven missing client methods with tests. Screens come in the surfaces plan and consume this layer unchanged.

**Tech Stack:** Python 3.12+, Strawberry GraphQL, SQLAlchemy 2 async, pytest + pytest-asyncio. React 19, TypeScript 5.8, Vite 6, Vitest 3, Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-02-operations-console-design.md`

## Global Constraints

- Do not invent GraphQL fields. Every field used must exist in the built schema.
- The browser talks only to `/graphql` (POST + WS) and `/simulator`. Never to MQTT, Neo4j, TimescaleDB, Kafka, or Sparkplug protobuf.
- Do not decode Sparkplug B in the browser.
- Tree queries use `+`, never `#`. `spBv1.0/` never enters the ISA-95 tree.
- Never coalesce a null OEE ratio to zero. Null renders as `—`.
- `CONTEXT.md` vocabulary: Unified Namespace, UNS Node, Historic Event, Mapper, Metric, Asset, Asset Model, Enrichment, Unmodelled Topic, Process Visualization, Platform Observability, Alert Rule (never "alarm" for the rule).
- English only. No i18n.
- No live broker and no live GraphQL in frontend tests.
- Minimum font size 11px. Body 13px, dense tables 12px.
- Python: line length and lint rules per each module's `pyproject.toml`; run `ruff` before commit.
- Every new Python file carries the repository's MIT copyright header, copied verbatim from a sibling file in the same directory.

---

## File Structure

**`09_uns_model`**
- Modify `src/uns_model/oee_results.py` — add `downtime_reasons()` to `OeeResultRepository`. It already imports `DowntimeReason` (`:46`), joins to it (`:232`) and validates against it (`:284`), so it is the class already responsible for that table.
- Modify `test/test_oee_results.py` — one new test group.

**`07_uns_graphql`**
- Modify `src/uns_graphql/type/oee.py` — add `DowntimeReasonType`, published as `DowntimeReason`.
- Modify `src/uns_graphql/queries/oee.py` — add the `downtime_reasons` resolver.
- Modify `schema/uns_schema.graphql` — regenerated.
- Create `test/test_schema_dump.py` — fails when the dump drifts from the built schema.
- Modify `test/queries/test_oee.py` — tests for the new query.
- Modify `test/type/test_oee.py` — enum/shape drift guard for the new type.

**`11_frontend`**
- Modify `package.json` — test tooling and a `test` script.
- Create `vitest.config.ts` — jsdom, and the same `define` as `vite.config.ts` so `platformConfig` resolves.
- Create `src/test/setup.ts` — `@testing-library/jest-dom`, and a guard that fails any test touching real `fetch` or `WebSocket`.
- Modify `src/types/uns.ts` — narrow `SystemHealthInfo`.
- Create `src/lib/health/connection-state.ts` — the four-state derivation and its wording.
- Create `src/lib/oee/format.ts` — null-safe ratio and status wording. The single most important unit in this plan.
- Modify `src/services/graphql/queries.ts` — eleven documents.
- Modify `src/services/graphql/types.ts` — the matching response shapes.
- Modify `src/services/graphql/client.ts` — eleven methods; honest `getHealth()`.
- Create `src/lib/oee/map-oee.ts` — GraphQL shapes to console types.
- Create `src/types/oee.ts` — console-side OEE types.

**Root**
- Modify `docker-compose.yml` — drop the duplicate host port 9092; add Grafana sub-path env.
- Modify `11_frontend/nginx.conf` and `11_frontend/vite.config.ts` — the `/grafana` proxy.

---

## Task 1: Frontend test tooling

`11_frontend/package.json` has no `test` script, no Vitest and no Testing Library, and there is not one `*.test.tsx` file in the module. Everything downstream needs this first.

**Files:**
- Modify: `11_frontend/package.json`
- Create: `11_frontend/vitest.config.ts`
- Create: `11_frontend/src/test/setup.ts`
- Test: `11_frontend/src/lib/platform/config.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `npm test` and `npm run test:run`. A jsdom environment where `__UNS_PLATFORM_CONFIG__` is defined. A setup file that fails any test which reaches for the network.

- [ ] **Step 1: Install the tooling**

```bash
cd 11_frontend
npm install -D vitest@^3 jsdom@^26 @testing-library/react@^16 @testing-library/dom@^10 @testing-library/user-event@^14 @testing-library/jest-dom@^6
```

- [ ] **Step 2: Add the scripts**

In `11_frontend/package.json`, add to `"scripts"`:

```json
    "test": "vitest",
    "test:run": "vitest run"
```

- [ ] **Step 3: Write the Vitest config**

Create `11_frontend/vitest.config.ts`. The `define` block must match `vite.config.ts:12`–`:14`, or `src/lib/platform/config.ts:18` throws on `__UNS_PLATFORM_CONFIG__` being undefined in every test that imports it.

```ts
import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig } from 'vitest/config'
import { loadPlatformSettings } from './platform/settings.ts'

const platform = loadPlatformSettings()

export default defineConfig({
  plugins: [react()],
  // Same define as vite.config.ts: src/lib/platform/config.ts reads this at module scope,
  // so without it every test that transitively imports the client fails on an undefined global.
  define: {
    __UNS_PLATFORM_CONFIG__: platform,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
```

Note: `tailwindcss()` is deliberately omitted. Tests assert behaviour and text, never computed styles, and the Tailwind plugin costs startup time for nothing.

- [ ] **Step 4: Write the setup file**

Create `11_frontend/src/test/setup.ts`. The network guard is the point: the spec forbids a live broker or live GraphQL in frontend tests, and a guard enforces that far more reliably than a review habit.

```ts
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * No test may reach the network. A test that needs GraphQL stubs `fetch` itself; a test
 * that forgets to gets a named failure here rather than a timeout against a real port.
 */
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      throw new Error('Unstubbed fetch in a test. Stub it, or mock the client method.')
    }),
  )
  vi.stubGlobal(
    'WebSocket',
    class {
      constructor() {
        throw new Error('Unstubbed WebSocket in a test. Frontend tests never open one.')
      }
    },
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
```

- [ ] **Step 5: Write the failing smoke test**

Create `11_frontend/src/lib/platform/config.test.ts`. This proves the `define` plumbing works, which is the thing most likely to be wrong.

```ts
import { describe, expect, it } from 'vitest'
import { platformConfig } from './config'

describe('platformConfig', () => {
  it('is injected into the test environment', () => {
    expect(platformConfig.graphqlPath).toBe('/graphql')
  })

  it('reports the real dev port, not Grafana&apos;s 3000', () => {
    expect(platformConfig.frontendDevPort).toBe(5173)
  })
})
```

- [ ] **Step 6: Run it**

Run: `cd 11_frontend && npm run test:run`
Expected: PASS, 2 tests. If `__UNS_PLATFORM_CONFIG__` is undefined, Step 3's `define` block does not match `vite.config.ts`.

- [ ] **Step 7: Verify the network guard bites**

Add temporarily to `config.test.ts`, run, confirm it fails with the guard's message, then delete it:

```ts
  it('temporary: the guard fires', async () => {
    await fetch('/graphql')
  })
```

Expected: FAIL with "Unstubbed fetch in a test". Delete the test.

- [ ] **Step 8: Confirm typecheck still passes**

Run: `cd 11_frontend && npm run lint`
Expected: clean. `npm run lint` is `tsc --noEmit`.

- [ ] **Step 9: Commit**

```bash
git add 11_frontend/package.json 11_frontend/package-lock.json 11_frontend/vitest.config.ts 11_frontend/src/test/setup.ts 11_frontend/src/lib/platform/config.test.ts
git commit -m "test(frontend): add Vitest with a guard against network access

The module had no test script, no Vitest and no test files. The setup file
stubs fetch and WebSocket to throw, so a test that forgets to mock the
transport fails by name instead of timing out against a real port."
```

---

## Task 2: `downtime_reasons()` on the repository

`assignDowntimeReason` validates its `reasonCode` against `model.downtime_reason` (`09_uns_model/src/uns_model/oee_results.py:284`) and nothing lists that table. `downtimePareto` returns only codes already used, so a code authored in `conf/oee/reasons.yaml` but never yet triggered is unreachable from a UI.

**Files:**
- Modify: `09_uns_model/src/uns_model/oee_results.py`
- Test: `09_uns_model/test/test_oee_results.py`

**Interfaces:**
- Consumes: `DowntimeReason` (already imported at `oee_results.py:46`), `Database`.
- Produces: `DowntimeReasonRow` — a frozen dataclass with `code: str`, `display_name: str`, `category: str`, `is_planned: bool`. And `OeeResultRepository.downtime_reasons() -> list[DowntimeReasonRow]`, ordered by `category` then `code`.

- [ ] **Step 1: Write the failing tests**

Append to `09_uns_model/test/test_oee_results.py`. `FakeDatabase`, `FakeResult`, `row` and `sql` are already defined at the top of that file (`:55`–`:101`).

```python
@pytest.mark.asyncio
async def test_downtime_reasons_returns_every_authored_code():
    """
    Including one that no event has ever used. `downtime_pareto` can only return codes
    that appear on an event, which is why a picker cannot be built from it.
    """
    database = FakeDatabase(
        [
            FakeResult(
                [
                    row(code="CHANGEOVER", display_name="Changeover", category="PLANNED", is_planned=True),
                    row(code="BREAKDOWN", display_name="Breakdown", category="FAILURE", is_planned=False),
                ]
            )
        ]
    )

    reasons = await OeeResultRepository(database).downtime_reasons()

    assert [reason.code for reason in reasons] == ["CHANGEOVER", "BREAKDOWN"]
    assert reasons[0].is_planned is True
    assert reasons[1].display_name == "Breakdown"
    assert reasons[1].category == "FAILURE"


@pytest.mark.asyncio
async def test_downtime_reasons_orders_by_category_then_code():
    """A picker groups by category, so the order is the repository's job, not the UI's."""
    database = FakeDatabase([FakeResult([])])

    await OeeResultRepository(database).downtime_reasons()

    statement = sql(database.session_obj.statements[0])
    assert "ORDER BY downtime_reason.category, downtime_reason.code" in statement


@pytest.mark.asyncio
async def test_downtime_reasons_is_one_round_trip():
    database = FakeDatabase([FakeResult([])])

    reasons = await OeeResultRepository(database).downtime_reasons()

    assert reasons == []
    assert len(database.session_obj.statements) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd 09_uns_model && python -m pytest test/test_oee_results.py -k downtime_reasons -v -p no:xdist`
Expected: FAIL with `AttributeError: 'OeeResultRepository' object has no attribute 'downtime_reasons'`

- [ ] **Step 3: Add the row dataclass**

In `09_uns_model/src/uns_model/oee_results.py`, beside the other row dataclasses (`ParetoBucket` at `:69`, `ShiftResultRow` at `:82`, `DowntimeEventRow` at `:91`), matching their decorator style:

```python
@dataclass(frozen=True, slots=True)
class DowntimeReasonRow:
    """One authored downtime reason code.

    A row rather than the ORM object, so a caller cannot lazy-load through it after the
    session has closed - the same reason the other reads in this module return rows.
    """

    code: str
    display_name: str
    category: str
    is_planned: bool
```

Check the decorator on `ParetoBucket` (`:69`) and copy it exactly; if the existing ones use plain `@dataclass`, use plain `@dataclass`.

- [ ] **Step 4: Add the read**

In `OeeResultRepository`, in the `# ------- reads` section, after `downtime_pareto`:

```python
    async def downtime_reasons(self) -> list[DowntimeReasonRow]:
        """Every authored downtime reason code, grouped by category.

        `downtime_pareto` returns only codes that some event already carries, so it
        cannot drive a reassignment picker: a code authored in `conf/oee/reasons.yaml`
        and never yet triggered would be missing from it. This is the whole table.
        """
        statement = select(
            DowntimeReason.code,
            DowntimeReason.display_name,
            DowntimeReason.category,
            DowntimeReason.is_planned,
        ).order_by(DowntimeReason.category, DowntimeReason.code)
        async with self._database.session() as session:
            rows = (await session.execute(statement)).all()
        return [
            DowntimeReasonRow(
                code=code,
                display_name=display_name,
                category=category,
                is_planned=is_planned,
            )
            for code, display_name, category, is_planned in rows
        ]
```

- [ ] **Step 5: Export it**

Add `"DowntimeReasonRow"` to the module's `__all__` if one exists (check the end of `oee_results.py`; `oee_master_data.py:530` has one, so this module may too).

- [ ] **Step 6: Run the tests**

Run: `cd 09_uns_model && python -m pytest test/test_oee_results.py -k downtime_reasons -v -p no:xdist`
Expected: PASS, 3 tests.

- [ ] **Step 7: Run the whole module and lint**

Run: `cd 09_uns_model && python -m pytest test/test_oee_results.py -q && ruff check src test`
Expected: all pass, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add 09_uns_model/src/uns_model/oee_results.py 09_uns_model/test/test_oee_results.py
git commit -m "feat(model): read the authored downtime reason codes

assign_reason validates a code against model.downtime_reason and nothing
could list that table, so a console picker had no source. downtime_pareto
is not one: it returns only codes some event already carries, so a code
authored in conf/oee/reasons.yaml and never triggered was unreachable."
```

---

## Task 3: `getDowntimeReasons` in the schema

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/type/oee.py`
- Modify: `07_uns_graphql/src/uns_graphql/queries/oee.py`
- Test: `07_uns_graphql/test/queries/test_oee.py`
- Test: `07_uns_graphql/test/type/test_oee.py`

**Interfaces:**
- Consumes: `DowntimeReasonRow` and `OeeResultRepository.downtime_reasons()` from Task 2.
- Produces: `getDowntimeReasons: [DowntimeReason!]!` with fields `code`, `displayName`, `category`, `isPlanned`. Python class `DowntimeReasonType`, published as `DowntimeReason`.

- [ ] **Step 1: Write the failing tests**

Append to `07_uns_graphql/test/queries/test_oee.py`. `REPOSITORY` is already defined at `:35`.

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_reasons_lists_the_authored_codes():
    """
    The picker behind assignDowntimeReason. Includes a code no event carries, because
    that is exactly the case downtimePareto cannot answer.
    """
    repository = AsyncMock()
    repository.downtime_reasons.return_value = [
        DowntimeReasonRow("CHANGEOVER", "Changeover", "PLANNED", True),
        DowntimeReasonRow("BREAKDOWN", "Breakdown", "FAILURE", False),
    ]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            "{ getDowntimeReasons { code displayName category isPlanned } }"
        )

    assert result.errors is None
    assert result.data["getDowntimeReasons"] == [
        {"code": "CHANGEOVER", "displayName": "Changeover", "category": "PLANNED", "isPlanned": True},
        {"code": "BREAKDOWN", "displayName": "Breakdown", "category": "FAILURE", "isPlanned": False},
    ]


@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_reasons_takes_no_arguments():
    """The whole table, unfiltered: a picker that hid a code would reintroduce the gap."""
    result = await UNSGraphql.schema.execute(
        """{ __type(name: "Query") { fields { name args { name } } } }"""
    )

    assert result.errors is None
    arguments = {
        field["name"]: [arg["name"] for arg in field["args"]]
        for field in result.data["__type"]["fields"]
    }
    assert arguments["getDowntimeReasons"] == []


@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_reasons_is_empty_before_the_seed_runs():
    repository = AsyncMock()
    repository.downtime_reasons.return_value = []

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute("{ getDowntimeReasons { code } }")

    assert result.errors is None
    assert result.data["getDowntimeReasons"] == []
```

Add to that file's imports at `:30`:

```python
from uns_model.oee_results import DowntimeEventRow, DowntimeReasonRow, ParetoBucket, ShiftResultRow
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd 07_uns_graphql && python -m pytest test/queries/test_oee.py -k downtime_reasons -v -p no:xdist`
Expected: FAIL — `Cannot query field 'getDowntimeReasons' on type 'Query'`.

- [ ] **Step 3: Add the type**

In `07_uns_graphql/src/uns_graphql/type/oee.py`, after `DowntimeParetoBucket`:

```python
@strawberry.type(name="DowntimeReason", description="One authored downtime reason code a stop can be attributed to.")
class DowntimeReasonType:
    """
    The catalogue behind `assignDowntimeReason`, whose `reasonCode` is validated against
    this table. `DowntimeParetoBucket` carries the same four fields for a code that was
    used; this is every code that exists, used or not.

    Published as `DowntimeReason` from a differently-named Python class for the same
    reason `DowntimeEventType` is: the ORM class of that name is imported by this
    module's dependencies.
    """

    code: strawberry.ID
    display_name: str
    category: str = strawberry.field(description="Grouping for a picker, e.g. PLANNED or FAILURE. May be empty.")
    is_planned: bool = strawberry.field(
        description="A planned stop leaves Loading Time, an unplanned one leaves Run Time. "
        "Reassigning across this boundary changes the shift's OEE."
    )

    @classmethod
    def from_row(cls, row: DowntimeReasonRow) -> "DowntimeReasonType":
        return cls(
            code=strawberry.ID(row.code),
            display_name=row.display_name,
            category=row.category,
            is_planned=row.is_planned,
        )
```

Add `DowntimeReasonRow` to the `uns_model.oee_results` import at `:34`.

- [ ] **Step 4: Add the resolver**

In `07_uns_graphql/src/uns_graphql/queries/oee.py`, after `downtime_pareto`:

```python
    @strawberry.field(
        description="Every authored downtime reason code, grouped by category. The valid values "
        "for assignDowntimeReason - downtimePareto only returns codes already in use."
    )
    async def get_downtime_reasons(self) -> list[DowntimeReasonType]:
        rows = await _repository().downtime_reasons()
        return [DowntimeReasonType.from_row(row) for row in rows]
```

Extend the import at `:38`:

```python
from uns_graphql.type.oee import (
    DowntimeEventType,
    DowntimeParetoBucket,
    DowntimeReasonType,
    OeeShiftResult,
)
```

- [ ] **Step 5: Run the tests**

Run: `cd 07_uns_graphql && python -m pytest test/queries/test_oee.py -v -p no:xdist`
Expected: PASS, all tests including the three pre-existing argument-name assertions.

- [ ] **Step 6: Add the type drift guard**

`test/type/test_oee.py` exists to fail when the schema's enums drift from `uns_model.oee_tables`. Append:

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_downtime_reason_publishes_exactly_four_fields():
    """
    Pinned so the type cannot quietly grow. It exists to fill a picker, and every field
    on it is a field the picker shows.
    """
    result = await UNSGraphql.schema.execute(
        """{ __type(name: "DowntimeReason") { fields { name } } }"""
    )

    assert result.errors is None
    assert {field["name"] for field in result.data["__type"]["fields"]} == {
        "code",
        "displayName",
        "category",
        "isPlanned",
    }
```

Match that file's existing imports; add `from uns_graphql.uns_graphql_app import UNSGraphql` and `import pytest` only if they are not already there.

- [ ] **Step 7: Run and lint**

Run: `cd 07_uns_graphql && python -m pytest test/queries/test_oee.py test/type/test_oee.py -q && ruff check src test`
Expected: all pass, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/type/oee.py 07_uns_graphql/src/uns_graphql/queries/oee.py 07_uns_graphql/test/queries/test_oee.py 07_uns_graphql/test/type/test_oee.py
git commit -m "feat(graphql): publish the authored downtime reason codes

assignDowntimeReason could not be driven from a UI: its reasonCode is
validated against model.downtime_reason and no query listed it. Read-only,
so ADR-0005's deliberately narrow mutation surface is unchanged."
```

---

## Task 4: Pin the schema dump

`07_uns_graphql/schema/uns_schema.graphql` contains no OEE surface at all. Building the schema and printing it yields four fields the dump omits — `oeeShiftResults`, `downtimeEvents`, `downtimePareto`, `assignDowntimeReason` — plus this plan's fifth. A dump that can silently drift caused a whole audit to under-report the platform. Regenerating it is not enough; it needs a test.

**Files:**
- Create: `07_uns_graphql/test/test_schema_dump.py`
- Modify: `07_uns_graphql/schema/uns_schema.graphql`

**Interfaces:**
- Consumes: `UNSGraphql.schema`.
- Produces: a test that fails with the regeneration command in its message whenever the dump drifts.

- [ ] **Step 1: Write the failing test**

Create `07_uns_graphql/test/test_schema_dump.py`, with the MIT header copied from `test/test_uns_graphql_app.py`.

```python
"""
The committed SDL must match the built schema.

Without this, the dump drifts: it was missing the entire OEE surface -
oeeShiftResults, downtimeEvents, downtimePareto and assignDowntimeReason - while
being the file a reader would trust as the platform's read surface.
"""

from pathlib import Path

from uns_graphql.uns_graphql_app import UNSGraphql

DUMP = Path(__file__).resolve().parents[1] / "schema" / "uns_schema.graphql"

REGENERATE = (
    "strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema "
    "--output ./schema/uns_schema.graphql"
)


def test_the_committed_schema_matches_the_built_schema():
    built = str(UNSGraphql.schema).strip()
    committed = DUMP.read_text(encoding="utf-8").strip()

    assert committed == built, f"schema/uns_schema.graphql is stale. Regenerate it:\n  {REGENERATE}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd 07_uns_graphql && python -m pytest test/test_schema_dump.py -v -p no:xdist`
Expected: FAIL with the regeneration hint. This is the finding from the spec, now mechanised.

- [ ] **Step 3: Regenerate the dump**

Run from `07_uns_graphql`, the command in that module's `README.md:123`:

```bash
cd 07_uns_graphql && strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema --output ./schema/uns_schema.graphql
```

- [ ] **Step 4: Run the test again**

Run: `cd 07_uns_graphql && python -m pytest test/test_schema_dump.py -v -p no:xdist`
Expected: PASS. If it still fails on trailing whitespace only, the `.strip()` on both sides is doing its job and something else differs — read the diff before changing the test.

- [ ] **Step 5: Confirm the new surface is in the dump**

Run: `cd 07_uns_graphql && grep -c "oeeShiftResults\|downtimeEvents\|downtimePareto\|getDowntimeReasons\|assignDowntimeReason" schema/uns_schema.graphql`
Expected: `5` or more.

- [ ] **Step 6: Fix the CI step that was supposed to prevent this**

`.github/workflows/uns_graphql-app.yml:204`–`:224` regenerates the dump and then runs `git commit` with **no `git push`**, while the workflow declares `permissions: contents: read` (`:51`–`:52`). The commit lands in the ephemeral runner and is discarded, so the dump has never been able to update — which is why it went stale despite the path filter at `:16` matching every OEE commit.

The pytest guard from Step 1 is now the durable check, so the CI step should verify rather than pretend to commit. Replace `:208`–`:224`:

```yaml
        run: |
          # The dump is now pinned by test/test_schema_dump.py, which runs in the step above.
          # This remains as a second line of defence with a readable failure.
          #
          # It deliberately does not commit: the previous version ran `git commit` with no
          # `git push` under `permissions: contents: read`, so every regeneration was
          # discarded with the runner and the dump silently went stale.
          uv run strawberry export-schema \
            uns_graphql.uns_graphql_app:UNSGraphql.schema \
            --output $schema_file

          if ! git diff --quiet -- "$schema_file"; then
            echo "::error file=$schema_file::Stale. Regenerate and commit it:"
            echo "  cd 07_uns_graphql && strawberry export-schema uns_graphql.uns_graphql_app:UNSGraphql.schema --output ./schema/uns_schema.graphql"
            git diff -- "$schema_file"
            exit 1
          fi
          echo "Schema unchanged"
```

- [ ] **Step 7: Verify the workflow still parses**

Run: `python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('.github/workflows/uns_graphql-app.yml').read_text())"`
Expected: no output, exit 0.

- [ ] **Step 8: Commit**

```bash
git add 07_uns_graphql/test/test_schema_dump.py 07_uns_graphql/schema/uns_schema.graphql .github/workflows/uns_graphql-app.yml
git commit -m "test(graphql): fail when the committed SDL goes stale

The dump was missing the entire OEE surface while being the file a reader
would trust as the platform's read surface. Regenerated, and now pinned by
a test.

CI was meant to catch this and could not: the workflow ran git commit with
no git push under permissions: contents: read, so every regeneration was
discarded with the runner. It now fails with the regeneration command
instead of committing into the void."
```

---

## Task 5: An honest `SystemHealthInfo`

`client.ts:577`–`:581` derives `mqttBroker`, `neo4jTree`, `timescaleHistorian`, `kafkaBroker` and `sparkplugMapper` from the single boolean `this.isLiveBackend`. This is precisely the defect ADR-0001 was written about: "the React console's System Health panel derives all five component indicators from a single boolean and no module emits any metrics at all." `:584` invents a `SIMULATED_MOCK` mode that no code path produces — `UNSContext` has no mock.

**Files:**
- Modify: `11_frontend/src/types/uns.ts:103`–`:117`
- Modify: `11_frontend/src/services/graphql/client.ts:572`–`:586`
- Modify: `11_frontend/src/components/common/ConnectionChip.tsx:58`, `:86`, `:96`, `:107`
- Modify: `11_frontend/src/components/layout/AppLayout.tsx:108`
- Test: `11_frontend/src/services/graphql/client-health.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `SystemHealthInfo` narrowed to `{ status: ConnectionStatus; graphqlHttp: boolean; graphqlWs: boolean; lastPingMs: number; endpointUrl: string }`. `ConnectionStatus` unchanged: `'LIVE' | 'DEGRADED' | 'DOWN'`.

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/services/graphql/client-health.test.ts`.

```ts
import { describe, expect, it, vi } from 'vitest'
import { UnsGraphQLClient } from './client'
import type { SystemHealthInfo } from '../../types/uns'

/** The constructor opens a WebSocket, which the setup file forbids. Stub a silent one. */
function clientWithoutSocket(): UnsGraphQLClient {
  vi.stubGlobal(
    'WebSocket',
    class {
      onopen: (() => void) | null = null
      onmessage: (() => void) | null = null
      onerror: (() => void) | null = null
      onclose: (() => void) | null = null
      send() {}
      close() {}
    },
  )
  return new UnsGraphQLClient('/graphql')
}

describe('getHealth', () => {
  it('reports only what the browser can observe', () => {
    const health = clientWithoutSocket().getHealth()

    // The browser has no connection to MQTT, Neo4j, TimescaleDB or Kafka, so it cannot
    // have an opinion about them. ADR-0001.
    expect(Object.keys(health).sort()).toEqual([
      'endpointUrl',
      'graphqlHttp',
      'graphqlWs',
      'lastPingMs',
      'status',
    ])
  })

  it('does not claim a store is online', () => {
    const health = clientWithoutSocket().getHealth() as SystemHealthInfo & Record<string, unknown>

    expect(health.mqttBroker).toBeUndefined()
    expect(health.neo4jTree).toBeUndefined()
    expect(health.timescaleHistorian).toBeUndefined()
    expect(health.kafkaBroker).toBeUndefined()
    expect(health.sparkplugMapper).toBeUndefined()
  })

  it('has no simulated mode, because there is no mock engine', () => {
    const health = clientWithoutSocket().getHealth() as Record<string, unknown>

    expect(health.mode).toBeUndefined()
  })

  it('starts DOWN before any request has succeeded', () => {
    expect(clientWithoutSocket().getHealth().status).toBe('DOWN')
  })

  it('reports the endpoint it was constructed with', () => {
    expect(clientWithoutSocket().getHealth().endpointUrl).toBe('/graphql')
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-health.test.ts`
Expected: FAIL — the key list still contains `mqttBroker` and the rest.

- [ ] **Step 3: Narrow the type**

Replace `11_frontend/src/types/uns.ts:105`–`:117`:

```ts
/**
 * What the browser can actually observe about the platform: the GraphQL endpoint and its
 * WebSocket. Nothing else.
 *
 * The five per-store indicators this type used to carry were all derived from one boolean,
 * which is the defect ADR-0001 was written about. Store health is Platform Observability
 * and belongs to Grafana, which is where the modules emit and the browser is not.
 */
export interface SystemHealthInfo {
  status: ConnectionStatus;
  graphqlHttp: boolean;
  graphqlWs: boolean;
  lastPingMs: number;
  endpointUrl: string;
}
```

- [ ] **Step 4: Fix `getHealth`**

Replace `client.ts:572`–`:586`:

```ts
  public getHealth(): SystemHealthInfo {
    return {
      status: this.isLiveBackend
        ? this.wsProtocolReady
          ? 'LIVE'
          : 'DEGRADED'
        : this.wsProtocolReady
          ? 'DEGRADED'
          : 'DOWN',
      graphqlHttp: this.isLiveBackend,
      graphqlWs: this.wsProtocolReady,
      lastPingMs: this.lastPingMs || 0,
      endpointUrl: this.httpUrl,
    }
  }
```

`LIVE` now requires both halves. The old version returned `LIVE` on HTTP alone, so a dead WebSocket — values silently frozen — looked fully healthy.

- [ ] **Step 5: Fix the consumers**

`tsc` will name all of them. The mechanical fixes:

- `AppLayout.tsx:108` — delete the `MODE: {health.mode}` span entirely.
`SystemHealthView.tsx` is **not** in this list, although an earlier audit said it was.
Commit `0812fc6e` rewrote it into a three-dashboard Grafana switcher that reads no
`health` at all. Confirm with `grep -n "health" src/components/system/SystemHealthView.tsx`
before touching it; expect no output.
- `ConnectionChip.tsx:58` — replace `{health.mode === 'LIVE_GRAPHQL' ? \`${health.lastPingMs}ms\` : 'SIM'}` with `{health.graphqlHttp ? \`${health.lastPingMs}ms\` : '—'}`.
- `ConnectionChip.tsx:86` — replace `'Fallback Mock Engine'` with `'Unreachable'`.
- `ConnectionChip.tsx:96` — replace `'Simulated Reactive Feed'` with `'Not subscribed'`.
- `ConnectionChip.tsx:107` — delete the `health.mode` row.

The chip is rewritten properly in the surfaces plan; this task only stops it lying.

- [ ] **Step 6: Run the test and the typecheck**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-health.test.ts && npm run lint`
Expected: PASS, 5 tests. `tsc --noEmit` clean.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src/types/uns.ts 11_frontend/src/services/graphql/client.ts 11_frontend/src/components/common/ConnectionChip.tsx 11_frontend/src/components/layout/AppLayout.tsx 11_frontend/src/services/graphql/client-health.test.ts
git commit -m "fix(frontend): stop deriving five store indicators from one boolean

client.ts painted mqttBroker, neo4jTree, timescaleHistorian, kafkaBroker and
sparkplugMapper from isLiveBackend alone - the exact defect ADR-0001 was
written about. The browser has no connection to any of them.

Also removes the SIMULATED_MOCK mode, which no code path produces, and makes
LIVE require both halves: HTTP up with a dead WebSocket means values have
silently stopped updating, which is not healthy."
```

---

## Task 6: Connection state wording

An operator whose WebSocket dropped is looking at values that stopped updating while every query still works. One green dot cannot tell them that.

**Files:**
- Create: `11_frontend/src/lib/health/connection-state.ts`
- Test: `11_frontend/src/lib/health/connection-state.test.ts`

**Interfaces:**
- Consumes: `SystemHealthInfo` from Task 5.
- Produces: `connectionState(health: SystemHealthInfo): ConnectionState` where `ConnectionState = { status: ConnectionStatus; label: string; detail: string }`.

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/lib/health/connection-state.test.ts`.

```ts
import { describe, expect, it } from 'vitest'
import { connectionState } from './connection-state'
import type { SystemHealthInfo } from '../../types/uns'

function health(overrides: Partial<SystemHealthInfo> = {}): SystemHealthInfo {
  return {
    status: 'LIVE',
    graphqlHttp: true,
    graphqlWs: true,
    lastPingMs: 12,
    endpointUrl: '/graphql',
    ...overrides,
  }
}

describe('connectionState', () => {
  it('is Live when both halves are up', () => {
    expect(connectionState(health())).toEqual({
      status: 'LIVE',
      label: 'Live',
      detail: 'Queries and live updates are working.',
    })
  })

  it('names the WebSocket when only it is down', () => {
    const state = connectionState(health({ graphqlWs: false }))

    expect(state.status).toBe('DEGRADED')
    expect(state.label).toBe('Degraded — live updates offline')
    expect(state.detail).toContain('Values are not updating')
  })

  it('names queries when only HTTP is down', () => {
    const state = connectionState(health({ graphqlHttp: false }))

    expect(state.status).toBe('DEGRADED')
    expect(state.label).toBe('Degraded — queries failing')
  })

  it('is Down when neither half is up', () => {
    expect(connectionState(health({ graphqlHttp: false, graphqlWs: false }))).toEqual({
      status: 'DOWN',
      label: 'Down — no connection to GraphQL',
      detail: 'Nothing on this screen is current.',
    })
  })

  it('never says Degraded without naming which half failed', () => {
    const degraded = [health({ graphqlWs: false }), health({ graphqlHttp: false })]

    for (const state of degraded.map(connectionState)) {
      expect(state.label).toMatch(/^Degraded — .+/)
    }
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd 11_frontend && npx vitest run src/lib/health/connection-state.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `11_frontend/src/lib/health/connection-state.ts`.

```ts
import type { ConnectionStatus, SystemHealthInfo } from '../../types/uns'

export type ConnectionState = {
  status: ConnectionStatus
  label: string
  detail: string
}

/**
 * Which half of the connection failed, in words.
 *
 * An operator whose WebSocket dropped is reading values that stopped updating while every
 * query still works. A single indicator cannot say that, so the label always names the
 * half that failed.
 */
export function connectionState(health: SystemHealthInfo): ConnectionState {
  if (health.graphqlHttp && health.graphqlWs) {
    return {
      status: 'LIVE',
      label: 'Live',
      detail: 'Queries and live updates are working.',
    }
  }
  if (health.graphqlHttp) {
    return {
      status: 'DEGRADED',
      label: 'Degraded — live updates offline',
      detail: 'Values are not updating. Queries and history still work; reload to refresh.',
    }
  }
  if (health.graphqlWs) {
    return {
      status: 'DEGRADED',
      label: 'Degraded — queries failing',
      detail: 'Live updates are arriving, but queries and history are failing.',
    }
  }
  return {
    status: 'DOWN',
    label: 'Down — no connection to GraphQL',
    detail: 'Nothing on this screen is current.',
  }
}
```

- [ ] **Step 4: Run the test**

Run: `cd 11_frontend && npx vitest run src/lib/health/connection-state.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/lib/health/connection-state.ts 11_frontend/src/lib/health/connection-state.test.ts
git commit -m "feat(frontend): name which half of the connection failed

A dead WebSocket with working queries means values silently stopped
updating. One green dot cannot say that, so Degraded always names the half."
```

---

## Task 7: Null-safe OEE formatting

The single most important unit in this plan. `07_uns_graphql/src/uns_graphql/type/oee.py` makes every ratio nullable on purpose: "a shift with no Loading Time has no Availability — it did not achieve 0%". One function, tested, so that guarantee is not a convention repeated across four components.

**Files:**
- Create: `11_frontend/src/types/oee.ts`
- Create: `11_frontend/src/lib/oee/format.ts`
- Test: `11_frontend/src/lib/oee/format.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `OeeStatus = 'OK' | 'NO_LOADING_TIME' | 'NO_PRODUCTION' | 'MISSING_IDEAL_CYCLE_TIME' | 'NO_INPUT_DATA'`
  - `ReasonSource = 'AUTO' | 'MANUAL'`
  - `OeeShiftProduct`, `OeeShiftResult`, `DowntimeEvent`, `DowntimeParetoBucket`, `DowntimeReason`
  - `formatRatio(value: number | null | undefined): string`
  - `statusLabel(status: OeeStatus): string`
  - `isRestated(result: Pick<OeeShiftResult, 'revision'>): boolean`
  - `performanceWarning(result: Pick<OeeShiftResult, 'performanceRaw'>): string | null`

- [ ] **Step 1: Write the console types**

Create `11_frontend/src/types/oee.ts`. Field names are the camelCase of the GraphQL type, verified against `07_uns_graphql/src/uns_graphql/type/oee.py`.

```ts
/**
 * Computed OEE, as the schema publishes it.
 *
 * Every ratio is nullable and must stay that way. ADR-0008: undefined is represented as
 * null, never zero - a shift with no Loading Time did not achieve 0%.
 */

export type OeeStatus =
  | 'OK'
  | 'NO_LOADING_TIME'
  | 'NO_PRODUCTION'
  | 'MISSING_IDEAL_CYCLE_TIME'
  | 'NO_INPUT_DATA';

export type ReasonSource = 'AUTO' | 'MANUAL';

export interface OeeShiftProduct {
  productCode: string;
  goodCount: number;
  rejectCount: number;
  totalCount: number;
  idealCycleTimeS: number | null;
}

export interface OeeShiftResult {
  assetPath: string;
  shiftStart: string;
  shiftEnd: string;
  shiftLabel: string;
  loadingTimeS: number;
  runTimeS: number;
  plannedDownS: number;
  unplannedDownS: number;
  goodCount: number;
  rejectCount: number;
  totalCount: number;
  availability: number | null;
  performance: number | null;
  performanceRaw: number | null;
  quality: number | null;
  oee: number | null;
  status: OeeStatus;
  revision: number;
  computedAt: string | null;
  publishedAt: string | null;
  products: OeeShiftProduct[];
}

export interface DowntimeEvent {
  id: string;
  assetPath: string;
  shiftStart: string;
  startedAt: string;
  endedAt: string;
  durationS: number;
  stateValue: string;
  reasonCode: string;
  reasonDisplayName: string;
  reasonCategory: string;
  isPlanned: boolean;
  reasonSource: ReasonSource;
  assignedBy: string | null;
  assignedAt: string | null;
  note: string;
}

export interface DowntimeParetoBucket {
  reasonCode: string;
  displayName: string;
  category: string;
  isPlanned: boolean;
  eventCount: number;
  totalSeconds: number;
  share: number;
}

export interface DowntimeReason {
  code: string;
  displayName: string;
  category: string;
  isPlanned: boolean;
}
```

- [ ] **Step 2: Write the failing test**

Create `11_frontend/src/lib/oee/format.test.ts`.

```ts
import { describe, expect, it } from 'vitest'
import { formatRatio, isRestated, performanceWarning, statusLabel } from './format'

describe('formatRatio', () => {
  it('renders a ratio as a percentage with one decimal', () => {
    expect(formatRatio(0.7344)).toBe('73.4%')
  })

  it('renders null as an em dash, never as zero', () => {
    // ADR-0008: a shift with no Loading Time did not achieve 0%.
    expect(formatRatio(null)).toBe('—')
    expect(formatRatio(undefined)).toBe('—')
  })

  it('renders a real zero as zero', () => {
    // Nothing produced is a fact; no scheduled time is an absence. They differ.
    expect(formatRatio(0)).toBe('0.0%')
  })

  it('renders a clamped 1.0 as 100%', () => {
    expect(formatRatio(1)).toBe('100.0%')
  })
})

describe('statusLabel', () => {
  it('turns every status into a sentence an operator can read', () => {
    expect(statusLabel('OK')).toBe('OK')
    expect(statusLabel('NO_LOADING_TIME')).toBe('No scheduled time')
    expect(statusLabel('NO_PRODUCTION')).toBe('Scheduled, nothing produced')
    expect(statusLabel('MISSING_IDEAL_CYCLE_TIME')).toBe('No rated cycle time authored')
    expect(statusLabel('NO_INPUT_DATA')).toBe('No data historised for this shift')
  })
})

describe('isRestated', () => {
  it('is false on the first computation', () => {
    expect(isRestated({ revision: 1 })).toBe(false)
  })

  it('is true once late data has restated the shift', () => {
    expect(isRestated({ revision: 2 })).toBe(true)
  })
})

describe('performanceWarning', () => {
  it('warns above 1.0, which is the only evidence the cycle time is wrong', () => {
    expect(performanceWarning({ performanceRaw: 1.2 })).toBe(
      'Performance above 100% before clamping: the rated cycle time is too slow, or a stop was missed.',
    )
  })

  it('is silent at or below 1.0', () => {
    expect(performanceWarning({ performanceRaw: 1 })).toBeNull()
    expect(performanceWarning({ performanceRaw: 0.85 })).toBeNull()
  })

  it('is silent when performance is undefined', () => {
    expect(performanceWarning({ performanceRaw: null })).toBeNull()
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd 11_frontend && npx vitest run src/lib/oee/format.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement**

Create `11_frontend/src/lib/oee/format.ts`.

```ts
import type { OeeShiftResult, OeeStatus } from '../../types/oee'

/** What an undefined ratio renders as. Never '0%'. */
export const NO_VALUE = '—'

const STATUS_LABELS: Record<OeeStatus, string> = {
  OK: 'OK',
  NO_LOADING_TIME: 'No scheduled time',
  NO_PRODUCTION: 'Scheduled, nothing produced',
  MISSING_IDEAL_CYCLE_TIME: 'No rated cycle time authored',
  NO_INPUT_DATA: 'No data historised for this shift',
}

/**
 * A ratio as a percentage, or NO_VALUE when it is undefined.
 *
 * The null check is the whole point of this function existing. ADR-0008: "Undefined is
 * represented as null, never zero. A shift with no Loading Time did not achieve 0%."
 * A `?? 0` anywhere in a component would undo that guarantee silently, so the conversion
 * happens here and is tested here.
 */
export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return NO_VALUE
  }
  return `${(value * 100).toFixed(1)}%`
}

/** The status as a sentence. `NO_LOADING_TIME` is a plant holiday, not a catastrophe. */
export function statusLabel(status: OeeStatus): string {
  return STATUS_LABELS[status] ?? status
}

/** Whether late data has restated this shift. ADR-0008 says this needs explaining once. */
export function isRestated(result: Pick<OeeShiftResult, 'revision'>): boolean {
  return result.revision > 1
}

/**
 * Performance above 1.0 before the clamp. The schema calls this "the only evidence" that
 * the ideal cycle time is wrong or a stop was missed, so it must not be hidden.
 */
export function performanceWarning(
  result: Pick<OeeShiftResult, 'performanceRaw'>,
): string | null {
  if (result.performanceRaw === null || result.performanceRaw <= 1) {
    return null
  }
  return 'Performance above 100% before clamping: the rated cycle time is too slow, or a stop was missed.'
}
```

- [ ] **Step 5: Run the test**

Run: `cd 11_frontend && npx vitest run src/lib/oee/format.test.ts && npm run lint`
Expected: PASS, 12 tests. `tsc` clean.

- [ ] **Step 6: Commit**

```bash
git add 11_frontend/src/types/oee.ts 11_frontend/src/lib/oee/format.ts 11_frontend/src/lib/oee/format.test.ts
git commit -m "feat(frontend): render an undefined OEE ratio as a dash, never zero

ADR-0008 makes every ratio nullable on purpose: a shift with no Loading Time
did not achieve 0%. One tested function, so a stray ?? 0 in a component
cannot quietly undo it."
```

---

## Task 8: Asset Model client reads

`getAssets`, `getAsset`, `getUnmodelledTopics` and `getAssetModelSummary` all exist in the schema (`07_uns_graphql/src/uns_graphql/queries/asset.py:70`, `:89`, `:111`, `:115`) and none is reachable. `CONTEXT.md` says counting Unmodelled Topics "is how you tell an incomplete Asset Model from a complete one".

**Files:**
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/services/graphql/types.ts`
- Modify: `11_frontend/src/services/graphql/client.ts`
- Test: `11_frontend/src/services/graphql/client-assets.test.ts`

**Interfaces:**
- Consumes: `ASSET_FIELDS` and `METRIC_DEFINITION_FIELDS`, already defined in `queries.ts`.
- Produces:
  - `getAssets(pathPrefix?: string): Promise<GraphqlAssetNode[]>`
  - `getAsset(path: string): Promise<GraphqlAssetNode | null>`
  - `getUnmodelledTopics(limit?: number): Promise<string[]>`
  - `getAssetModelSummary(): Promise<AssetModelSummary | null>` where `AssetModelSummary = { assets: number; metricDefinitions: number; boundTopics: number; unmodelledTopics: number }`
  - `getAssetChildren` changes from `private` to `public`.

- [ ] **Step 1: Confirm the real field names before writing a query**

Run: `cd 07_uns_graphql && grep -n "class AssetModelSummary" -A 20 src/uns_graphql/type/asset.py` and `grep -n "async def get_assets" -A 12 src/uns_graphql/queries/asset.py`

Write the query documents in Step 3 against what this prints, not against this plan. If a field name here disagrees with the source, the source wins and the plan is wrong — note it in the commit message.

- [ ] **Step 2: Write the failing test**

Create `11_frontend/src/services/graphql/client-assets.test.ts`.

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UnsGraphQLClient } from './client'

function silentSocket() {
  vi.stubGlobal(
    'WebSocket',
    class {
      onopen = null
      onmessage = null
      onerror = null
      onclose = null
      send() {}
      close() {}
    },
  )
}

/** One scripted GraphQL response. */
function respond(data: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ data }),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sentBody(fetchMock: ReturnType<typeof vi.fn>) {
  return JSON.parse(fetchMock.mock.calls[0][1].body as string)
}

describe('Asset Model reads', () => {
  let client: UnsGraphQLClient

  beforeEach(() => {
    silentSocket()
    client = new UnsGraphQLClient('/graphql')
  })

  it('reads the completeness summary', async () => {
    respond({
      getAssetModelSummary: {
        assets: 57,
        metricDefinitions: 430,
        boundTopics: 12,
        unmodelledTopics: 3,
      },
    })

    const summary = await client.getAssetModelSummary()

    expect(summary).toEqual({
      assets: 57,
      metricDefinitions: 430,
      boundTopics: 12,
      unmodelledTopics: 3,
    })
  })

  it('returns null for the summary when the endpoint fails, not zeroes', async () => {
    // Zeroes would read as "the Asset Model is empty", which is a different fact.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    expect(await client.getAssetModelSummary()).toBeNull()
  })

  it('reads Unmodelled Topics and passes the limit through', async () => {
    const fetchMock = respond({ getUnmodelledTopics: ['spBv1.0/CovestroAG/NBIRTH/GW1'] })

    const topics = await client.getUnmodelledTopics(50)

    expect(topics).toEqual(['spBv1.0/CovestroAG/NBIRTH/GW1'])
    expect(sentBody(fetchMock).variables).toEqual({ limit: 50 })
  })

  it('treats an empty Unmodelled Topic list as a complete model, not a failure', async () => {
    respond({ getUnmodelledTopics: [] })

    expect(await client.getUnmodelledTopics()).toEqual([])
  })

  it('reads one Asset by path', async () => {
    const fetchMock = respond({ getAsset: { path: 'CovestroAG/Dormagen', name: 'Dormagen' } })

    const asset = await client.getAsset('CovestroAG/Dormagen')

    expect(asset?.path).toBe('CovestroAG/Dormagen')
    expect(sentBody(fetchMock).variables).toEqual({ path: 'CovestroAG/Dormagen' })
  })

  it('returns null when nothing is modelled at that path', async () => {
    respond({ getAsset: null })

    expect(await client.getAsset('CovestroAG/Nowhere')).toBeNull()
  })

  it('reads the authored Asset list', async () => {
    respond({ getAssets: [{ path: 'CovestroAG', name: 'CovestroAG' }] })

    const assets = await client.getAssets()

    expect(assets).toHaveLength(1)
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-assets.test.ts`
Expected: FAIL — `client.getAssetModelSummary is not a function`.

- [ ] **Step 4: Add the query documents**

Append to `11_frontend/src/services/graphql/queries.ts`. Adjust `getAssets`' argument to whatever Step 1 printed.

```ts
/**
 * The authored Asset Model as a flat list. Distinct from getUnsNodes, which is discovered
 * from traffic: an Asset that has never published still appears here, and that difference
 * is the point of having both.
 */
export const GET_ASSETS_QUERY = `
  query GetAssets($pathPrefix: String) {
    getAssets(pathPrefix: $pathPrefix) {
      ${ASSET_FIELDS}
    }
  }
`

export const GET_ASSET_QUERY = `
  query GetAsset($path: String!) {
    getAsset(path: $path) {
      ${ASSET_FIELDS}
      metricDefinitions {
        ${METRIC_DEFINITION_FIELDS}
      }
    }
  }
`

/** Topics that have published but match no Asset. Empty means the Asset Model is complete. */
export const GET_UNMODELLED_TOPICS_QUERY = `
  query GetUnmodelledTopics($limit: Int) {
    getUnmodelledTopics(limit: $limit)
  }
`

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

If `getAsset` does not expose `metricDefinitions` (check Step 1's output), drop that block and read Metric Definitions through `getTopicContext` instead — do not invent the field.

- [ ] **Step 5: Add the response type**

Append to `11_frontend/src/services/graphql/types.ts`:

```ts
export interface AssetModelSummary {
  assets: number
  metricDefinitions: number
  boundTopics: number
  unmodelledTopics: number
}
```

- [ ] **Step 6: Add the client methods**

In `client.ts`, change `getAssetChildren` at `:251` from `private` to `public` — the Assets screen needs it — and add:

```ts
  /**
   * The authored Asset Model, flat. Not the tree: the tree is `getAssetChildren` a level
   * at a time, because an Asset Model with thousands of Assets should not arrive at once.
   */
  public async getAssets(pathPrefix?: string): Promise<GraphqlAssetNode[]> {
    const res = await this.executeQuery<{ getAssets: GraphqlAssetNode[] }>(GET_ASSETS_QUERY, {
      pathPrefix,
    })
    return res.data?.getAssets ?? []
  }

  public async getAsset(path: string): Promise<GraphqlAssetNode | null> {
    const res = await this.executeQuery<{ getAsset: GraphqlAssetNode | null }>(GET_ASSET_QUERY, {
      path,
    })
    return res.data?.getAsset ?? null
  }

  /**
   * Topics that published but match no Asset. Counting them is how you tell an incomplete
   * Asset Model from a complete one (CONTEXT.md), so an empty list is a result and not an
   * absence of one.
   */
  public async getUnmodelledTopics(limit?: number): Promise<string[]> {
    const res = await this.executeQuery<{ getUnmodelledTopics: string[] }>(
      GET_UNMODELLED_TOPICS_QUERY,
      limit === undefined ? {} : { limit },
    )
    return res.data?.getUnmodelledTopics ?? []
  }

  /**
   * Null when the server cannot be reached, following getAlertRules' precedent: zeroes
   * would read as "the Asset Model is empty", which is a different fact entirely.
   */
  public async getAssetModelSummary(): Promise<AssetModelSummary | null> {
    const res = await this.executeQuery<{ getAssetModelSummary: AssetModelSummary }>(
      GET_ASSET_MODEL_SUMMARY_QUERY,
    )
    if (res.error || !res.data?.getAssetModelSummary) {
      return null
    }
    return res.data.getAssetModelSummary
  }
```

Add the four query constants and `AssetModelSummary` to the imports at the top of `client.ts`.

- [ ] **Step 7: Run the test**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-assets.test.ts && npm run lint`
Expected: PASS, 7 tests.

- [ ] **Step 8: Verify against the running schema**

If a stack is up, confirm the documents are accepted rather than merely well-formed:

```bash
curl -s localhost:8000/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ getAssetModelSummary { assets metricDefinitions boundTopics unmodelledTopics } }"}'
```

Expected: a `data` object with four numbers, no `errors`. If a field name is rejected, fix the document — the server is right.

- [ ] **Step 9: Commit**

```bash
git add 11_frontend/src/services/graphql/queries.ts 11_frontend/src/services/graphql/types.ts 11_frontend/src/services/graphql/client.ts 11_frontend/src/services/graphql/client-assets.test.ts
git commit -m "feat(frontend): read the Asset Model and its Unmodelled Topics

getAssets, getAsset, getUnmodelledTopics and getAssetModelSummary all existed
in the schema and none was reachable. Counting Unmodelled Topics is how you
tell an incomplete Asset Model from a complete one (CONTEXT.md).

The summary returns null rather than zeroes when the server is unreachable:
zeroes would read as an empty Asset Model, which is a different fact."
```

---

## Task 9: Alert Rule detail and summary reads

**Files:**
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/services/graphql/types.ts`
- Modify: `11_frontend/src/services/graphql/client.ts`
- Test: `11_frontend/src/services/graphql/client-alert-rules.test.ts`

**Interfaces:**
- Consumes: `graphqlAlertRuleToAlertRule` from `lib/alarms/map-alert-rules.ts`, and the `ALERT_RULE_FIELDS` fragment already used by `GET_ALERT_RULES_QUERY`.
- Produces:
  - `getAlertRule(id: string): Promise<AlertRule | null>`
  - `getAlertRuleSummary(): Promise<AlertRuleSummary | null>`
  - `getAlertRules(topic?: string, enabledOnly?: boolean)` — the existing method gains the two optional filters the resolver already accepts (`queries/alert_rule.py:45`).

- [ ] **Step 1: Confirm the real argument and field names**

Run: `cd 07_uns_graphql && grep -n "async def get_alert_rules" -A 10 src/uns_graphql/queries/alert_rule.py && grep -n "class AlertRuleSummary" -A 15 src/uns_graphql/type/alert_rule.py`

Write Step 3 against that output.

- [ ] **Step 2: Write the failing test**

Create `11_frontend/src/services/graphql/client-alert-rules.test.ts`. Reuse the `silentSocket`, `respond` and `sentBody` helpers from Task 8 — copy them in rather than importing across test files, so each test file stands alone.

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UnsGraphQLClient } from './client'

function silentSocket() {
  vi.stubGlobal(
    'WebSocket',
    class {
      onopen = null
      onmessage = null
      onerror = null
      onclose = null
      send() {}
      close() {}
    },
  )
}

function respond(data: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data }) })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sentBody(fetchMock: ReturnType<typeof vi.fn>) {
  return JSON.parse(fetchMock.mock.calls[0][1].body as string)
}

describe('Alert Rule reads', () => {
  let client: UnsGraphQLClient

  beforeEach(() => {
    silentSocket()
    client = new UnsGraphQLClient('/graphql')
  })

  it('reads the rule counts', async () => {
    respond({ getAlertRuleSummary: { total: 12, enabled: 9 } })

    expect(await client.getAlertRuleSummary()).toEqual({ total: 12, enabled: 9 })
  })

  it('returns null for the counts when the endpoint fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    expect(await client.getAlertRuleSummary()).toBeNull()
  })

  it('filters rules by topic', async () => {
    const fetchMock = respond({ getAlertRules: [] })

    await client.getAlertRules('CovestroAG/Dormagen/Production/Line1')

    expect(sentBody(fetchMock).variables.topic).toBe('CovestroAG/Dormagen/Production/Line1')
  })

  it('still returns null on failure, so an empty list cannot disarm every rule', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    expect(await client.getAlertRules()).toBeNull()
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-alert-rules.test.ts`
Expected: FAIL — `client.getAlertRuleSummary is not a function`.

- [ ] **Step 4: Add the documents**

Append to `queries.ts`, using the exact field list Step 1 printed for `AlertRuleSummary`:

```ts
export const GET_ALERT_RULE_QUERY = `
  query GetAlertRule($id: String!) {
    getAlertRule(id: $id) {
      ${ALERT_RULE_FIELDS}
    }
  }
`

export const GET_ALERT_RULE_SUMMARY_QUERY = `
  query GetAlertRuleSummary {
    getAlertRuleSummary {
      total
      enabled
    }
  }
`
```

Replace `GET_ALERT_RULES_QUERY` with the filtered form, keeping the same export name:

```ts
export const GET_ALERT_RULES_QUERY = `
  query GetAlertRules($topic: String, $enabledOnly: Boolean) {
    getAlertRules(topic: $topic, enabledOnly: $enabledOnly) {
      ${ALERT_RULE_FIELDS}
    }
  }
`
```

The fragment name and the summary's fields must match Step 1's output. If `ALERT_RULE_FIELDS` is spelled differently in the file, use the existing spelling.

- [ ] **Step 5: Add the types and methods**

In `types.ts`:

```ts
export interface AlertRuleSummary {
  total: number
  enabled: number
}
```

In `client.ts`, replace `getAlertRules` at `:401` with the filtered version and add the two new methods. Keep the existing docstring at `:393`–`:400` — the null-versus-empty distinction it explains still holds.

```ts
  public async getAlertRules(topic?: string, enabledOnly?: boolean): Promise<AlertRule[] | null> {
    const res = await this.executeQuery<{ getAlertRules: GraphqlAlertRule[] }>(
      GET_ALERT_RULES_QUERY,
      { topic, enabledOnly },
    )
    if (res.error || !res.data?.getAlertRules) {
      return null
    }
    return res.data.getAlertRules.map(graphqlAlertRuleToAlertRule)
  }

  public async getAlertRule(id: string): Promise<AlertRule | null> {
    const res = await this.executeQuery<{ getAlertRule: GraphqlAlertRule | null }>(
      GET_ALERT_RULE_QUERY,
      { id },
    )
    if (res.error || !res.data?.getAlertRule) {
      return null
    }
    return graphqlAlertRuleToAlertRule(res.data.getAlertRule)
  }

  /** Null on failure, for the same reason getAlertRules is: zero rules is a different fact. */
  public async getAlertRuleSummary(): Promise<AlertRuleSummary | null> {
    const res = await this.executeQuery<{ getAlertRuleSummary: AlertRuleSummary }>(
      GET_ALERT_RULE_SUMMARY_QUERY,
    )
    if (res.error || !res.data?.getAlertRuleSummary) {
      return null
    }
    return res.data.getAlertRuleSummary
  }
```

- [ ] **Step 6: Run the full frontend suite**

Run: `cd 11_frontend && npm run test:run && npm run lint`
Expected: all pass. The existing `AlarmContext` call site of `getAlertRules()` still compiles because both new parameters are optional.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src/services/graphql/queries.ts 11_frontend/src/services/graphql/types.ts 11_frontend/src/services/graphql/client.ts 11_frontend/src/services/graphql/client-alert-rules.test.ts
git commit -m "feat(frontend): read one Alert Rule and the rule counts

getAlertRule and getAlertRuleSummary existed and were unreachable, and
getAlertRules ignored the topic and enabledOnly filters the resolver already
accepts - which a per-Asset rule list needs."
```

---

## Task 10: OEE client reads and the reason reassignment

The pilot's success criterion (ADR-0008), referenced zero times by the console.

**Files:**
- Modify: `11_frontend/src/services/graphql/queries.ts`
- Modify: `11_frontend/src/services/graphql/client.ts`
- Create: `11_frontend/src/lib/oee/map-oee.ts`
- Test: `11_frontend/src/services/graphql/client-oee.test.ts`

**Interfaces:**
- Consumes: the types from Task 7, `getDowntimeReasons` from Task 3.
- Produces:
  - `getOeeShiftResults(assetPath: string, from: string, to: string): Promise<OeeShiftResult[]>`
  - `getDowntimeEvents(assetPath: string, from: string, to: string): Promise<DowntimeEvent[]>`
  - `getDowntimePareto(assetPath: string, from: string, to: string): Promise<DowntimeParetoBucket[]>`
  - `getDowntimeReasons(): Promise<DowntimeReason[]>`
  - `assignDowntimeReason(eventId: string, reasonCode: string, note?: string, assignedBy?: string): Promise<DowntimeEvent>` — throws with the server's message on failure.

- [ ] **Step 1: Write the failing test**

Create `11_frontend/src/services/graphql/client-oee.test.ts`. Copy `silentSocket`, `respond` and `sentBody` from Task 8.

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UnsGraphQLClient } from './client'

const LINE = 'CovestroAG/Dormagen/Production/Line1'
const FROM = '2026-08-31T06:00:00.000Z'
const TO = '2026-09-01T06:00:00.000Z'

function silentSocket() {
  vi.stubGlobal(
    'WebSocket',
    class {
      onopen = null
      onmessage = null
      onerror = null
      onclose = null
      send() {}
      close() {}
    },
  )
}

function respond(data: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data }) })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sentBody(fetchMock: ReturnType<typeof vi.fn>) {
  return JSON.parse(fetchMock.mock.calls[0][1].body as string)
}

describe('OEE reads', () => {
  let client: UnsGraphQLClient

  beforeEach(() => {
    silentSocket()
    client = new UnsGraphQLClient('/graphql')
  })

  it('sends the range as `from` and `to`, which is what the schema publishes', async () => {
    const fetchMock = respond({ oeeShiftResults: [] })

    await client.getOeeShiftResults(LINE, FROM, TO)

    expect(sentBody(fetchMock).variables).toEqual({ assetPath: LINE, from: FROM, to: TO })
  })

  it('preserves a null ratio all the way through the client', async () => {
    respond({
      oeeShiftResults: [
        {
          assetPath: LINE,
          shiftStart: FROM,
          shiftEnd: TO,
          shiftLabel: 'A',
          loadingTimeS: 0,
          runTimeS: 0,
          plannedDownS: 0,
          unplannedDownS: 0,
          goodCount: 0,
          rejectCount: 0,
          totalCount: 0,
          availability: null,
          performance: null,
          performanceRaw: null,
          quality: null,
          oee: null,
          status: 'NO_LOADING_TIME',
          revision: 1,
          computedAt: null,
          publishedAt: null,
          products: [],
        },
      ],
    })

    const [result] = await client.getOeeShiftResults(LINE, FROM, TO)

    expect(result.availability).toBeNull()
    expect(result.oee).toBeNull()
    expect(result.status).toBe('NO_LOADING_TIME')
  })

  it('returns an empty list for a line with no closed shifts', async () => {
    respond({ oeeShiftResults: [] })

    expect(await client.getOeeShiftResults(LINE, FROM, TO)).toEqual([])
  })

  it('reads the Pareto buckets in the order the server sent them', async () => {
    respond({
      downtimePareto: [
        {
          reasonCode: 'BREAKDOWN',
          displayName: 'Breakdown',
          category: 'FAILURE',
          isPlanned: false,
          eventCount: 5,
          totalSeconds: 5400,
          share: 0.6,
        },
        {
          reasonCode: 'CHANGEOVER',
          displayName: 'Changeover',
          category: 'PLANNED',
          isPlanned: true,
          eventCount: 2,
          totalSeconds: 3600,
          share: 0.4,
        },
      ],
    })

    const buckets = await client.getDowntimePareto(LINE, FROM, TO)

    expect(buckets.map((b) => b.reasonCode)).toEqual(['BREAKDOWN', 'CHANGEOVER'])
    expect(buckets[1].isPlanned).toBe(true)
  })

  it('reads every authored reason code, including unused ones', async () => {
    respond({
      getDowntimeReasons: [
        { code: 'CHANGEOVER', displayName: 'Changeover', category: 'PLANNED', isPlanned: true },
      ],
    })

    expect(await client.getDowntimeReasons()).toEqual([
      { code: 'CHANGEOVER', displayName: 'Changeover', category: 'PLANNED', isPlanned: true },
    ])
  })
})

describe('assignDowntimeReason', () => {
  let client: UnsGraphQLClient

  beforeEach(() => {
    silentSocket()
    client = new UnsGraphQLClient('/graphql')
  })

  it('sends the event, the code and the note', async () => {
    const fetchMock = respond({
      assignDowntimeReason: {
        id: '11',
        assetPath: LINE,
        shiftStart: FROM,
        startedAt: FROM,
        endedAt: TO,
        durationS: 60,
        stateValue: 'ABORTED',
        reasonCode: 'BREAKDOWN',
        reasonDisplayName: 'Breakdown',
        reasonCategory: 'FAILURE',
        isPlanned: false,
        reasonSource: 'MANUAL',
        assignedBy: 'shift.lead',
        assignedAt: TO,
        note: 'seal failed',
      },
    })

    const event = await client.assignDowntimeReason('11', 'BREAKDOWN', 'seal failed', 'shift.lead')

    expect(sentBody(fetchMock).variables).toEqual({
      eventId: '11',
      reasonCode: 'BREAKDOWN',
      note: 'seal failed',
      assignedBy: 'shift.lead',
    })
    expect(event.reasonSource).toBe('MANUAL')
  })

  it('throws the server&apos;s sentence when the code is not authored', async () => {
    // oee_results.py:284 raises a sentence rather than a constraint violation, so it is
    // worth showing verbatim instead of replacing with "an error occurred".
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          errors: [{ message: "'NOPE' is not an authored downtime reason code" }],
        }),
      }),
    )

    await expect(client.assignDowntimeReason('11', 'NOPE')).rejects.toThrow(
      "'NOPE' is not an authored downtime reason code",
    )
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-oee.test.ts`
Expected: FAIL — `client.getOeeShiftResults is not a function`.

- [ ] **Step 3: Add the documents**

Append to `queries.ts`:

```ts
/**
 * Computed OEE for closed shifts. The arguments are `from` and `to` because `from` is a
 * Python keyword and the resolver renames them explicitly (queries/oee.py:45).
 *
 * Every ratio is nullable and is requested as such: ADR-0008 represents undefined as null,
 * never zero.
 */
export const GET_OEE_SHIFT_RESULTS_QUERY = `
  query GetOeeShiftResults($assetPath: String!, $from: DateTime!, $to: DateTime!) {
    oeeShiftResults(assetPath: $assetPath, from: $from, to: $to) {
      assetPath
      shiftStart
      shiftEnd
      shiftLabel
      loadingTimeS
      runTimeS
      plannedDownS
      unplannedDownS
      goodCount
      rejectCount
      totalCount
      availability
      performance
      performanceRaw
      quality
      oee
      status
      revision
      computedAt
      publishedAt
      products {
        productCode
        goodCount
        rejectCount
        totalCount
        idealCycleTimeS
      }
    }
  }
`

const DOWNTIME_EVENT_FIELDS = `
      id
      assetPath
      shiftStart
      startedAt
      endedAt
      durationS
      stateValue
      reasonCode
      reasonDisplayName
      reasonCategory
      isPlanned
      reasonSource
      assignedBy
      assignedAt
      note
`

export const GET_DOWNTIME_EVENTS_QUERY = `
  query GetDowntimeEvents($assetPath: String!, $from: DateTime!, $to: DateTime!) {
    downtimeEvents(assetPath: $assetPath, from: $from, to: $to) {
${DOWNTIME_EVENT_FIELDS}
    }
  }
`

export const GET_DOWNTIME_PARETO_QUERY = `
  query GetDowntimePareto($assetPath: String!, $from: DateTime!, $to: DateTime!) {
    downtimePareto(assetPath: $assetPath, from: $from, to: $to) {
      reasonCode
      displayName
      category
      isPlanned
      eventCount
      totalSeconds
      share
    }
  }
`

/** The valid values for assignDowntimeReason. downtimePareto only returns codes in use. */
export const GET_DOWNTIME_REASONS_QUERY = `
  query GetDowntimeReasons {
    getDowntimeReasons {
      code
      displayName
      category
      isPlanned
    }
  }
`

export const ASSIGN_DOWNTIME_REASON_MUTATION = `
  mutation AssignDowntimeReason(
    $eventId: ID!
    $reasonCode: String!
    $note: String
    $assignedBy: String
  ) {
    assignDowntimeReason(
      eventId: $eventId
      reasonCode: $reasonCode
      note: $note
      assignedBy: $assignedBy
    ) {
${DOWNTIME_EVENT_FIELDS}
    }
  }
`
```

- [ ] **Step 4: Add the client methods**

In `client.ts`:

```ts
  /**
   * Closed-shift OEE for one Asset. Empty is normal, not an error: ADR-0008 computes after
   * a shift closes, so a line mid-shift has nothing yet.
   */
  public async getOeeShiftResults(
    assetPath: string,
    from: string,
    to: string,
  ): Promise<OeeShiftResult[]> {
    const res = await this.executeQuery<{ oeeShiftResults: OeeShiftResult[] }>(
      GET_OEE_SHIFT_RESULTS_QUERY,
      { assetPath, from, to },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.oeeShiftResults ?? []
  }

  public async getDowntimeEvents(
    assetPath: string,
    from: string,
    to: string,
  ): Promise<DowntimeEvent[]> {
    const res = await this.executeQuery<{ downtimeEvents: DowntimeEvent[] }>(
      GET_DOWNTIME_EVENTS_QUERY,
      { assetPath, from, to },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.downtimeEvents ?? []
  }

  public async getDowntimePareto(
    assetPath: string,
    from: string,
    to: string,
  ): Promise<DowntimeParetoBucket[]> {
    const res = await this.executeQuery<{ downtimePareto: DowntimeParetoBucket[] }>(
      GET_DOWNTIME_PARETO_QUERY,
      { assetPath, from, to },
    )
    if (res.error) {
      throw new Error(res.error)
    }
    return res.data?.downtimePareto ?? []
  }

  public async getDowntimeReasons(): Promise<DowntimeReason[]> {
    const res = await this.executeQuery<{ getDowntimeReasons: DowntimeReason[] }>(
      GET_DOWNTIME_REASONS_QUERY,
    )
    return res.data?.getDowntimeReasons ?? []
  }

  /**
   * The one correction to plant data this platform allows. Throws the server's message
   * verbatim: oee_results.py:284 raises a sentence naming the bad code, which is more use
   * to an operator than "an error occurred".
   */
  public async assignDowntimeReason(
    eventId: string,
    reasonCode: string,
    note?: string,
    assignedBy?: string,
  ): Promise<DowntimeEvent> {
    const res = await this.executeQuery<{ assignDowntimeReason: DowntimeEvent }>(
      ASSIGN_DOWNTIME_REASON_MUTATION,
      { eventId, reasonCode, note, assignedBy },
    )
    if (res.error || !res.data?.assignDowntimeReason) {
      throw new Error(res.error || 'The downtime reason was not assigned')
    }
    return res.data.assignDowntimeReason
  }
```

Import the five documents and the four types from `../../types/oee`.

The GraphQL response shape and the console type are identical here, so there is no mapper — `src/lib/oee/map-oee.ts` from the File Structure is not needed. Delete it from the plan rather than creating an empty pass-through.

- [ ] **Step 5: Run the test**

Run: `cd 11_frontend && npx vitest run src/services/graphql/client-oee.test.ts && npm run lint`
Expected: PASS, 7 tests.

- [ ] **Step 6: Verify against a running server**

```bash
curl -s localhost:8000/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ getDowntimeReasons { code displayName category isPlanned } }"}'
```

Expected: the codes from `conf/oee/reasons.yaml` plus migration 0003's seeds. If `data` is `null` with an error, the schema was not rebuilt — Tasks 3 and 4 must be deployed first.

- [ ] **Step 7: Commit**

```bash
git add 11_frontend/src/services/graphql/queries.ts 11_frontend/src/services/graphql/client.ts 11_frontend/src/services/graphql/client-oee.test.ts
git commit -m "feat(frontend): read computed OEE, stops and the reason catalogue

ADR-0008 calls this number the pilot's success criterion and the console
referenced it zero times. Nullable ratios stay nullable through the client,
and assignDowntimeReason surfaces the server's sentence verbatim."
```

---

## Task 11: One host port 9092

`uns_kafka_broker` publishes `9092:9092` (`docker-compose.yml:82`) and so does `graphdb_client`'s metrics endpoint (`:165`). Only one can bind, so on a clean `up` one of them fails.

**Files:**
- Modify: `docker-compose.yml:164`–`:165`

**Interfaces:**
- Consumes: nothing.
- Produces: a compose file whose published ports are unique.

- [ ] **Step 1: Confirm the collision**

Run: `grep -n '"9092:9092"' docker-compose.yml`
Expected: two lines, 82 and 165.

- [ ] **Step 2: Confirm nothing on the host needs it**

Run: `grep -n "graphdb_client" 08_uns_observability/prometheus/prometheus.yml`
Expected: `targets: ["graphdb_client:9092"]` — a service name, resolved inside the compose network. No host publish is needed.

- [ ] **Step 3: Remove the publish**

In `docker-compose.yml`, delete lines 164–165 from the `graphdb_client` service:

```yaml
    ports:
      - "9092:9092"
```

and add a comment above `environment:` matching how `oee_client` (`:277`–`:278`) and `uns_simulator` (`:313`–`:314`) already explain the same decision:

```yaml
    # 9092 stays unpublished: it collides with uns_kafka_broker's host port, and Prometheus
    # scrapes graphdb_client:9092 from inside the network, exactly as it does the historian's
    # 9091 and the OEE engine's 9095.
```

`UNS_graphdb__metrics_port: 9092` stays — the container still listens on it.

- [ ] **Step 4: Verify uniqueness**

Run:

```bash
grep -oE '"[0-9]+:[0-9]+"' docker-compose.yml | cut -d'"' -f2 | cut -d: -f1 | sort | uniq -d
```

Expected: no output.

- [ ] **Step 5: Verify the file still parses**

Run: `docker compose config --quiet`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(compose): stop publishing host port 9092 twice

uns_kafka_broker and graphdb_client's metrics endpoint both claimed it, so
one failed to bind on a clean up. Prometheus scrapes graphdb_client:9092
inside the network, so the host publish was never needed."
```

---

## Task 12: Verify the `/grafana` proxy, and close its one real gap

**This task is mostly verification.** Commit `0812fc6e` ("feat(grafana): integrate
Grafana into the console for enhanced observability") already landed the proxy, the
dev proxy, the sub-path environment and a `GrafanaEmbed` component. Read the four
files before writing anything — the earlier audit predated that commit, and a task
that re-adds what exists produces a duplicate `location` block that nginx refuses to
start with.

What is already correct, and must be left alone:

| Concern | Where | State |
|---|---|---|
| nginx sub-path | `11_frontend/nginx.conf` — `location /grafana/` plus `location = /grafana` returning a 301 | Correct, and ordered before `location /` as ADR-0007 requires |
| dev proxy | `11_frontend/vite.config.ts` — `'/grafana'` with `ws: true` | Correct |
| setting | `11_frontend/platform/settings.ts:19`, `:62` — `grafanaProxyTarget` | Present |
| embedding allowed | `docker-compose.yml:398` — `GF_SECURITY_ALLOW_EMBEDDING: "true"` | Correct |
| sub-path env | `docker-compose.yml:399`–`:400` — `GF_SERVER_SERVE_FROM_SUB_PATH` and `GF_SERVER_ROOT_URL: "http://localhost:8088/grafana/"` | Correct. Do **not** change the root URL to `%(protocol)s://%(domain)s:%(http_port)s/grafana/`: those placeholders expand to Grafana's own host and port, 3000, not the console's 8088 |

The one real gap: `grafanaProxyTarget` falls back to `http://localhost:3000`
(`platform/settings.ts:62`) because `conf/settings.yaml` has no
`urls.grafana_proxy_target`, and `docker-compose.yml:390`–`:392` deliberately leaves
Grafana's 3000 unpublished. So `npm run dev` against a composed stack proxies
`/grafana` at a port nothing is listening on, and every embedded dashboard renders a
blank frame with no error text. Every other URL in this repo is configured in
`conf/settings.yaml`; this one must be too.

**Files:**
- Modify: `conf/settings.yaml` — `default.urls`
- Modify: `11_frontend/platform/settings.ts:62`
- Test: `11_frontend/src/lib/platform/config.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `platformConfig.grafanaProxyTarget`, already exported. This task only changes
  where its value comes from.

- [ ] **Step 1: Prove the four files are already right**

```bash
cd /c/Dev/unifiednamespace
grep -n "grafana" 11_frontend/nginx.conf 11_frontend/vite.config.ts 11_frontend/platform/settings.ts
grep -n "GF_SERVER_ROOT_URL\|GF_SERVER_SERVE_FROM_SUB_PATH\|GF_SECURITY_ALLOW_EMBEDDING" docker-compose.yml
```

Expected: a `location /grafana/` block, a `'/grafana'` proxy entry with `ws: true`, a
`grafanaProxyTarget` field, and the three `GF_` variables. If any one of them is missing,
this task grew — stop and add it in the style of the neighbouring entry before continuing.

- [ ] **Step 2: Write the failing setting test**

Replace the Grafana assertion in `11_frontend/src/lib/platform/config.test.ts` — or append
it if there is none — with one that reads the configured value rather than the fallback:

```ts
  it('takes the Grafana proxy target from settings.yaml, not from a hardcoded port', () => {
    expect(platformSettingsFromConfig({
      urls: { grafana_proxy_target: 'http://uns_grafana:3000' },
    }).grafanaProxyTarget).toBe('http://uns_grafana:3000')
  })

  it('falls back to the published dev port when settings.yaml says nothing', () => {
    expect(platformSettingsFromConfig({}).grafanaProxyTarget).toBe('http://localhost:3000')
  })
```

- [ ] **Step 3: Run it**

Run: `cd 11_frontend && npx vitest run src/lib/platform/config.test.ts`

Expected: both PASS. `platformSettingsFromConfig` already reads
`urls.grafana_proxy_target`, so this test documents behaviour rather than driving it. That
is the point: it fails later if someone hardcodes the port back in.

- [ ] **Step 4: Configure the target**

In `conf/settings.yaml`, in `default.urls` after `simulator_port` (`:40`):

```yaml
    # Grafana is reached through the console's /grafana proxy, never directly. Compose
    # leaves Grafana's 3000 unpublished (docker-compose.yml:390-392), so `npm run dev`
    # needs a target it can actually reach: publish 3000 locally, or point this at a
    # Grafana you run yourself.
    grafana_proxy_target: "http://localhost:3000"
```

The value is the same as the current fallback. What changes is that it is now visible and
overridable next to every other URL, instead of buried in a TypeScript default.

- [ ] **Step 5: Publish Grafana for development only**

In `docker-compose.yml`, `uns_grafana` — keep the existing comment, add the override file
rather than editing the service, so the composed stack keeps 3000 unpublished:

Create `docker-compose.override.yml.example`:

```yaml
# Copy to docker-compose.override.yml for frontend development. `npm run dev` proxies
# /grafana to localhost:3000, which the main compose file deliberately does not publish
# (a published 3000 collided with whatever already bound it on the host).
services:
  uns_grafana:
    ports:
      - "3000:3000"
```

Add `docker-compose.override.yml` to `.gitignore` if it is not already ignored.

- [ ] **Step 6: Verify in compose**

```bash
docker compose up -d uns_frontend uns_grafana
curl -s localhost:8088/grafana/api/health
```

Expected: JSON with `"database": "ok"`. If the response is HTML with a 200, the request
fell through to `index.html` — the exact failure ADR-0007 warns about — and the nginx
block was damaged.

- [ ] **Step 7: Verify the three dashboards resolve by UID**

```bash
for uid in uns-oee uns-process-visualization uns-platform-observability; do
  curl -s -o /dev/null -w "$uid %{http_code}
" "localhost:8088/grafana/api/dashboards/uid/$uid"
done
```

Expected: `200` for all three. These are the UIDs the surfaces plan embeds; a 404 here
means a dashboard JSON in `08_uns_observability/grafana/dashboards/` declares a different
uid, and the surfaces plan must use whatever it actually declares.

- [ ] **Step 8: Verify in dev**

```bash
cd 11_frontend && npm run dev
# in another shell:
curl -s -o /dev/null -w '%{http_code} %{content_type}
' localhost:5173/grafana/api/health
```

Expected: `200 application/json`, given the override from Step 5.

- [ ] **Step 9: Run the frontend suite**

Run: `cd 11_frontend && npm run test:run && npm run lint`

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add conf/settings.yaml 11_frontend/src/lib/platform/config.test.ts   docker-compose.override.yml.example .gitignore
git commit -m "fix: configure the Grafana proxy target instead of hardcoding it

The /grafana proxy, the sub-path environment and the embed component already
existed. What did not: urls.grafana_proxy_target in settings.yaml. Compose
leaves Grafana's 3000 unpublished on purpose, so \`npm run dev\` proxied to a
port nothing was listening on and every embedded dashboard rendered a blank
frame. The example override file publishes it for development."
```

---

## Definition of done

- `cd 11_frontend && npm run test:run` passes; `npm run lint` clean.
- `cd 07_uns_graphql && python -m pytest test -q` passes, including the new dump guard.
- `cd 09_uns_model && python -m pytest test -q` passes.
- `07_uns_graphql/schema/uns_schema.graphql` contains all five OEE fields.
- `docker compose config --quiet` succeeds and no host port is published twice.
- `localhost:8088/grafana/api/health` returns JSON.
- `SystemHealthInfo` has five keys and none of them names a datastore.
- No screen has changed. That is the surfaces plan.

## Notes for the surfaces plan

Carried forward, discovered while writing this plan:

- `src/components/common/ConnectionChip.tsx` says `Fallback Mock Engine` (`:86`), `Simulated Reactive Feed` (`:96`) and `SIM` (`:58`). Task 5 makes them merely wrong rather than lying; the chip is rewritten against `connectionState()` in the surfaces plan. It was not in the spec's section 11 table — add it there.
- `getAssetChildren` became public in Task 8.
- `src/lib/oee/map-oee.ts` was planned and is not needed: the GraphQL shape and the console type are identical, so a mapper would be a pass-through.
