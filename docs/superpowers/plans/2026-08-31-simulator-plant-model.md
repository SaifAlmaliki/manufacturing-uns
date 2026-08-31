# Simulator Plant Model and Correlated Signal Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `99_simulator` from ~6 hand-listed PLC sensors into a correlated production-facility simulator publishing ~400 signals across energy, water/utilities, asset health, production/OEE and safety/environment families.

**Architecture:** A single `PlantClock` ticks once per second and advances a shared `PlantContext` (per-site ambient/shift/tariff, per-line PackML state and production rate). Every signal is evaluated on that 1 s tick against the context; cadence tiers control only *when a device publishes*, never when values advance. Signal behaviour is data — ten declarative shapes (`noise`, `constant`, `ou_walk`, `counter`, `sawtooth`, `diurnal`, `derived`, `window_agg`, `stepped`, `bernoulli_event`) declared in `conf/simulator/*.yaml`, with cross-signal coupling expressed as whitelisted-AST expressions rather than Python.

**Tech Stack:** Python ≥3.14, `aiomqtt` (persistent connections), `dynaconf` via `uns_config`, `hashlib.blake2b` for per-signal deterministic seeding, stdlib `ast` for expression evaluation, pytest + pytest-asyncio + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-08-31-simulator-production-facility-design.md`

**Companion spec (sub-project B, NOT in this plan):** `docs/superpowers/specs/2026-08-31-simulator-console-and-control-api-design.md`

## Global Constraints

- `requires-python = ">=3.14, <4"` (`99_simulator/pyproject.toml`). Exactly **one** new runtime dependency is permitted — `pyyaml`, added by Task 16 so `read_simulator_conf` can parse `conf/simulator/*.yaml` without going through Dynaconf. Everything else is stdlib plus the existing `aiomqtt`, `dynaconf`, `logger`, `uns_config`. No task may add a second.
- Ruff config is inherited: `line-length = 127`, `preview = true`, `select = ["A","ARG","B","C","E","F","UP","W","I","N","S","T","RUF","LOG","PERF"]`, `max-complexity = 15`, `S101` ignored in tests. Run `uv run ruff check .` and `uv run ruff format .` in `99_simulator` before every commit.
- **`eval()` and `exec()` are forbidden.** Expressions are evaluated by the whitelisted AST walker from Task 1. Ruff would not catch a hand-rolled `eval`; a test does (Task 1, Step 9).
- Never call the `random` module at module level or on the global instance — every stochastic signal owns a `random.Random` seeded per-signal (Task 2). Module-level `random.*` also trips `S311`; `self.rng.uniform(...)` on a `Random` instance does not.
- Topics stay ISA-95 8-level: `Enterprise/Site/Area/Line/Cell/Equipment/ParameterType/ParameterName`. No plan task may publish a shorter or longer path.
- Plant data publishes under the existing `CovestroAG/#` root only. `uns/platform/#` self-telemetry belongs to sub-project B — do not add it here.
- Existing tests must stay green. `99_simulator/test/test_hierarchy.py::test_create_plc_spawns_one_device_per_cell_and_template` asserts `len(plcs) == 4`; `test_devices.py` calls `publish_parameter` on a `plc.client` it assigned itself.
- Test command in `99_simulator`: `uv run pytest test/... -v`. `addopts` already applies `-n auto --timeout=300 --durations=10`.

### Canonical signal vocabulary — copied verbatim from spec §5.2 and §6.3

Every task below uses these exact key names. The YAML in Tasks 16–18 is transcribed from
spec §8, which uses them, so a paraphrase anywhere breaks the config silently.

| Shape | Params (exact keys) |
|---|---|
| `noise` | `base_value`, `variation` |
| `constant` | `value` |
| `ou_walk` | `mean`, `sigma`, `tau` (seconds) |
| `counter` | `rate` (number, sibling name, or expression), `initial`, `rollover` |
| `sawtooth` | `low`, `high`, `fill_rate`, `drain_rate`, `start` |
| `diurnal` | `mean`, `amplitude`, `period_s` (86400), `phase_s`, `noise` |
| `derived` | `expr`, `params` |
| `window_agg` | `source`, `agg` (`max`/`min`/`mean`), `window_s` |
| `stepped` | `source` **or** `choices`, `map`, `dwell_s` |
| `bernoulli_event` | `p`, `choices` |

Common fields on every signal (spec §5.1): `shape` (default `noise`), `unit` (**required**),
`precision` (default 2), `range` `[min, max]`, `limits` `{lolo, lo, hi, hihi}`, `tier`
(default: the device's tier).

`unit` is the **Unit of Measure** in `CONTEXT.md`'s sense — always written in full, never
abbreviated to "unit" in prose, because bare "unit" collides with the Production Unit Asset
Level. Spec §11 and §14 make its absence a load-time error; a dimensionless ratio therefore
declares `unit: "1"` rather than omitting the key, so an omission is never ambiguous.

`ctx` fields a `derived` expression may read — per site: `ambient_temp_c`, `ambient_rh_pct`,
`wet_bulb_temp_c`, `wind_speed_ms`, `barometric_mbar`, `shift`, `tariff`,
`grid_co2_g_per_kwh`. Per line: `state`, `production_rate`, `throughput_tph`, `heat_load`,
`air_demand`, `time_in_state_s`, `running`. Per `serves` aggregate: `served_production`
(mean), `served_throughput_tph` (sum), `served_heat_load` (sum), `served_air_demand` (sum).

`serves` entries are fully-qualified `Site/Area/Line` paths (spec §7.3:
`serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]`). **A `serves` entry naming
a path that does not exist is a load-time error** (spec §6.3), not a warning.

`status` derivation (spec §5.1), in this order: a `hihi`/`lolo` breach → `"Alarm"`; a
`hi`/`lo` breach → `"Warning"`; otherwise, **only** for `shape: noise` with no `limits`, the
pre-existing heuristic (`deviation > variation*3` → Alarm, `> variation*2` → Warning);
otherwise `"Normal"`.

### Two spec defects this plan deliberately corrects

Transcribing the spec literally would produce failing tests. Both corrections are load-bearing:

1. **Spec §5.3 says seed with `hash((global_seed, topic))`. This plan uses `blake2b` instead.** Python randomizes `str` hashing per process unless `PYTHONHASHSEED` is set, so `hash()` gives a different seed every run — yet §11 specifies a test asserting "identical seed ⇒ identical sequence". `hashlib.blake2b(topic.encode(), digest_size=8)` is stable across processes and platforms.
2. **Spec §12's "values bit-for-bit identical to today" is unachievable and is restated.** Replacing the global `random` module with per-signal seeded RNGs necessarily changes the byte sequence. What is actually preserved, and what Task 2 tests, is: the `noise` shape stays the default so existing YAML keeps working; values stay inside `base_value ± variation`; rounding stays at 2 decimals; and the `Normal`/`Warning`/`Alarm` heuristic keeps its `2×`/`3×` deviation thresholds.

---

## File Structure

**New — `99_simulator/src/uns_simulator/`**

| File | Responsibility |
|---|---|
| `expressions.py` | Compile and evaluate a restricted arithmetic expression against a namespace. Whitelisted AST nodes only. Knows nothing about signals or MQTT. |
| `signals.py` | `SignalSpec` (declaration) and the ten `Signal` shape classes (behaviour). Each shape's only job is `next(dt, view, siblings) -> value`. Owns deterministic seeding and the topological ordering of `derived` signals. |
| `plant.py` | The simulated world: `LineState` (PackML), `SiteState` (ambient/shift/tariff), `PlantContext` (all sites + `serves` aggregation), `DeviceView` (a device's read-only window onto the context), `PlantClock` (the 1 s tick). |
| `profiles.py` | Read `conf/simulator/*.yaml`, validate it, expand device templates against the hierarchy using `matches_target`, and hand back `DeviceSpec` objects. All failure messages point at the offending YAML key. |

**Modified — `99_simulator/src/uns_simulator/`**

| File | Change |
|---|---|
| `models.py` | Area gains `kind` (`production` or `utilities` — `AREA_KINDS` in Task 10, the only two the hierarchy uses) and `nameplate_tph`; `expand_hierarchy_paths` carries them through. |
| `devices.py` | Persistent MQTT connection with reconnect backoff; collision-free `client_id`; new `SignalDevice` that publishes a `SignalSpec` set; `SCADA` reports the real device count. |
| `simulator.py` | Builds the `PlantContext` and `PlantClock`, expands profiles instead of the cartesian PLC loop, and schedules one publish task per cadence tier. |

**New — `conf/simulator/`**

`plant.yaml` — the hierarchy, per-site ambient and tariff, per-line PackML timing, **and the `small`/`full` profile selections** — plus one file per family: `energy.yaml`, `water.yaml`, `utilities.yaml`, `asset_health.yaml`, `production.yaml`, `safety.yaml`. Seven files, not eight: spec §7.2 writes `profiles:` as a top-level block of `plant.yaml`, and a profile names sites and cell caps that only mean something against the hierarchy directly above it.

**New tests — `99_simulator/test/`**

`test_expressions.py`, `test_signals.py`, `test_plant.py`, `test_profiles.py`, `test_targeting.py`, `test_conf_files.py`, `test_volume.py`; `test_devices.py` and `test_hierarchy.py` extended.

**Docs:** `99_simulator/README.md`, `docs/adr/0006-simulator-plant-model-and-signal-generation.md` — **0006, not the `0005` spec §13 names**: `docs/adr/0005-graphql-mutations-for-console-configuration.md` already exists, accepted and committed. Task 19 explains.

---

## Task 1: Whitelisted expression evaluator

The `derived` shape needs "this value is a function of sibling values and plant state" without letting YAML execute code. This task is first because Tasks 6, 11 and 16–18 all depend on it, and because getting the security boundary wrong here is unrecoverable later.

**Files:**
- Create: `99_simulator/src/uns_simulator/expressions.py`
- Test: `99_simulator/test/test_expressions.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ExpressionError(ValueError)` — raised at compile time and at evaluation time.
  - `compile_expression(source: str) -> CompiledExpression`
  - `class CompiledExpression` with `.source: str`, `.names: frozenset[str]` (every free variable, so callers can validate references before running), and `.evaluate(namespace: Mapping[str, Any]) -> float`.

- [ ] **Step 1: Write the failing test for arithmetic and namespace lookup**

```python
# 99_simulator/test/test_expressions.py
import math

import pytest

from uns_simulator.expressions import ExpressionError, compile_expression


def test_arithmetic_and_precedence():
    assert compile_expression("2 + 3 * 4").evaluate({}) == 14  # noqa: PLR2004


def test_reads_names_from_namespace():
    expr = compile_expression("flow * density")
    assert expr.evaluate({"flow": 10.0, "density": 1.2}) == pytest.approx(12.0)


def test_reports_free_variables():
    assert compile_expression("a + b * ctx.ambient_temp_c").names == frozenset({"a", "b", "ctx"})
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest test/test_expressions.py -v` (from `99_simulator`)
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_simulator.expressions'`

- [ ] **Step 3: Implement the evaluator**

```python
# 99_simulator/src/uns_simulator/expressions.py
"""Evaluate small arithmetic expressions from YAML without executing arbitrary code.

`eval()` on configuration is a remote-code-execution hole even when the configuration is
trusted today, so this module walks a whitelisted AST instead. Anything not explicitly
allowed raises ExpressionError at compile time, before any value is produced.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Mapping
from typing import Any, Final


class ExpressionError(ValueError):
    """An expression could not be compiled or could not be evaluated."""


_BIN_OPS: Final = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: Final = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_COMPARE_OPS: Final = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
# Exactly the seven calls spec 5.4 permits - no more.
_FUNCTIONS: Final = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "clamp": lambda value, low, high: max(low, min(high, value)),
    "sqrt": math.sqrt,
    "exp": math.exp,
}
ATTRIBUTE_ROOT: Final = "ctx"
_ALLOWED_NODES: Final = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Attribute,
    ast.And,
    ast.Or,
    *_BIN_OPS,
    *_UNARY_OPS,
    *_COMPARE_OPS,
)


class CompiledExpression:
    """A validated expression, reusable across ticks."""

    __slots__ = ("_tree", "names", "source")

    def __init__(self, source: str, tree: ast.Expression, names: frozenset[str]) -> None:
        self.source = source
        self._tree = tree
        self.names = names

    def evaluate(self, namespace: Mapping[str, Any]) -> Any:
        try:
            return _eval_node(self._tree.body, namespace)
        except ExpressionError:
            raise
        except Exception as exc:
            raise ExpressionError(f"evaluating {self.source!r} failed: {exc}") from exc

    def __repr__(self) -> str:
        return f"CompiledExpression({self.source!r})"


def compile_expression(source: str) -> CompiledExpression:
    """Parse and validate `source`, rejecting anything outside the whitelist."""
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"{source!r} is not a valid expression: {exc.msg}") from exc

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"{type(node).__name__} is not allowed in {source!r}")
        if isinstance(node, ast.Attribute):
            # Spec 5.4: attribute access is permitted on the `ctx` root only. Allowing it
            # anywhere would reopen the `().__class__.__bases__` route to arbitrary objects.
            if not (isinstance(node.value, ast.Name) and node.value.id == ATTRIBUTE_ROOT):
                raise ExpressionError(f"attribute access is only allowed on {ATTRIBUTE_ROOT!r} in {source!r}")
            if node.attr.startswith("_"):
                raise ExpressionError(f"private attribute {node.attr!r} is not allowed in {source!r}")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise ExpressionError(f"only direct calls to whitelisted functions are allowed in {source!r}")
        if isinstance(node, ast.Name) and node.id not in _FUNCTIONS:
            names.add(node.id)
    return CompiledExpression(source, tree, frozenset(names))


def _eval_node(node: ast.AST, ns: Mapping[str, Any]) -> Any:  # noqa: PLR0911
    match node:
        case ast.Constant(value=value):
            return value
        case ast.Name(id=name):
            if name in ns:
                return ns[name]
            if name in _FUNCTIONS:
                return _FUNCTIONS[name]
            raise ExpressionError(f"unknown name {name!r}")
        case ast.Attribute(value=value, attr=attr):
            target = _eval_node(value, ns)
            try:
                return getattr(target, attr)
            except AttributeError as exc:
                raise ExpressionError(f"{type(target).__name__} has no attribute {attr!r}") from exc
        case ast.BinOp(left=left, op=op, right=right):
            return _BIN_OPS[type(op)](_eval_node(left, ns), _eval_node(right, ns))
        case ast.UnaryOp(op=op, operand=operand):
            return _UNARY_OPS[type(op)](_eval_node(operand, ns))
        case ast.BoolOp(op=op, values=values):
            evaluated = [_eval_node(value, ns) for value in values]
            return all(evaluated) if isinstance(op, ast.And) else any(evaluated)
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            current = _eval_node(left, ns)
            for op, comparator in zip(ops, comparators, strict=True):
                right = _eval_node(comparator, ns)
                if not _COMPARE_OPS[type(op)](current, right):
                    return False
                current = right
            return True
        case ast.IfExp(test=test, body=body, orelse=orelse):
            return _eval_node(body if _eval_node(test, ns) else orelse, ns)
        case ast.Call(func=ast.Name(id=name), args=args, keywords=keywords):
            if keywords:
                raise ExpressionError(f"keyword arguments are not allowed in a call to {name!r}")
            if name not in _FUNCTIONS:
                raise ExpressionError(f"{name!r} is not a whitelisted function")
            return _FUNCTIONS[name](*[_eval_node(arg, ns) for arg in args])
        case _:
            raise ExpressionError(f"{type(node).__name__} is not supported")
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest test/test_expressions.py -v`
Expected: 3 passed.

- [ ] **Step 5: Add the rejection tests — this is the security boundary**

```python
# append to 99_simulator/test/test_expressions.py
@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('echo hi')",
        "().__class__.__bases__",
        "flow._secret",
        "[i for i in range(10)]",
        "lambda: 1",
        "open('/etc/passwd')",
        "(1).__class__",
        "f'{flow}'",
    ],
)
def test_rejects_dangerous_source(source):
    with pytest.raises(ExpressionError):
        compile_expression(source)


def test_rejects_unknown_function():
    with pytest.raises(ExpressionError, match="whitelisted function"):
        compile_expression("eval('1')").evaluate({})


def test_rejects_unknown_name_at_evaluation():
    with pytest.raises(ExpressionError, match="unknown name"):
        compile_expression("missing + 1").evaluate({})


def test_whitelisted_helpers_work():
    assert compile_expression("clamp(120, 0, 100)").evaluate({}) == 100  # noqa: PLR2004
    assert compile_expression("sqrt(x)").evaluate({"x": 9.0}) == pytest.approx(3.0)
    assert compile_expression("a if a > b else b").evaluate({"a": 1, "b": 5}) == 5  # noqa: PLR2004


def test_attribute_access_on_context_object_works():
    class View:
        ambient_temp_c = 21.5

    assert compile_expression("ctx.ambient_temp_c * 2").evaluate({"ctx": View()}) == pytest.approx(43.0)
```

- [ ] **Step 6: Run them and confirm they pass**

Run: `uv run pytest test/test_expressions.py -v`
Expected: all passed. `f'{flow}'` is rejected because `ast.JoinedStr` is not whitelisted; `[i for i in ...]` because `ast.ListComp` is not; `lambda` because `ast.Lambda` is not.

- [ ] **Step 7: Add the no-`eval` guard test**

This test exists because a future edit "simplifying" this module back to `eval()` would pass every other test in the suite.

```python
# append to 99_simulator/test/test_expressions.py
def test_module_source_contains_no_eval_or_exec():
    from pathlib import Path

    import uns_simulator.expressions as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "eval" not in called
    assert "exec" not in called
```

Add `import ast` to the test file's imports.

- [ ] **Step 8: Run the full test file, then lint**

Run: `uv run pytest test/test_expressions.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all tests pass, ruff clean.

- [ ] **Step 9: Commit**

```bash
git add 99_simulator/src/uns_simulator/expressions.py 99_simulator/test/test_expressions.py
git commit -m "feat(simulator): add whitelisted AST expression evaluator for derived signals"
```

---

## Task 2: Signal core — `SignalSpec`, deterministic seeding, `noise` and `constant`

Establishes the shape contract every later shape implements, and locks in backward compatibility with today's `base_value ± variation` YAML.

**Files:**
- Create: `99_simulator/src/uns_simulator/signals.py`
- Test: `99_simulator/test/test_signals.py`

**Interfaces:**
- Consumes: nothing from Task 1 yet (Task 6 wires `derived` in).
- Produces — every later task uses these exact names:
  - `SIGNAL_SHAPES: dict[str, type[Signal]]` — the registry a shape class registers itself into.
  - `@dataclass(frozen=True) class SignalSpec` with fields `name: str`, `shape: str = "noise"`, `unit: str = ""`, `precision: int = 2`, `base_value: float = 0.0`, `variation: float = 0.0`, `value_range: tuple[float, float] | None = None`, `limits: dict[str, float] = field(default_factory=dict)`, `tier: str = "process"`, `param_type: str = "ProcessValue"`, `export_metric: bool = False`, `params: dict[str, Any] = field(default_factory=dict)`. `param_type` is one of the five `ParameterType` *values* — `ProcessValue`, `Setpoint`, `Status`, `Alarm`, `EVENT` — carried as a string here so `signals.py` need not import `models.py`; Task 14 resolves it to the enum.
  - `signal_seed(global_seed: int, topic: str) -> int` — process-stable.
  - `class Signal` with `__init__(self, spec: SignalSpec, topic: str, global_seed: int)`, attributes `.spec`, `.topic`, `.rng: random.Random`, `.value: float | str | None`, and:
    - `next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float | str | None` — advances and returns the new value; also assigns `self.value`.
    - `status(self) -> str` — `"Normal"` / `"Warning"` / `"Alarm"`.
    - `_clamp(self, value: float) -> float` — applies `value_range` and `precision`.
  - `build_signal(spec: SignalSpec, topic: str, global_seed: int) -> Signal` — registry lookup, raises `ValueError` naming the unknown shape.
  - `spec_from_config(name: str, raw: Mapping[str, Any]) -> SignalSpec` — reads both the legacy `{base_value, variation, unit}` form and the new form. **Shape params are top-level YAML keys** (`value`, `mean`, `rate`, `expr`, `low`, `high`, …) exactly as spec §7.3 writes them, so every top-level key that is *not* one of the ten common fields is collected into `spec.params`. The one special case: a top-level `params:` block (the expression-constant dict from spec §7.3) is **merged into** `spec.params` rather than nested under it, which makes spec §5.4's "permitted names: sibling signal names, keys of `params`" a single flat lookup.

- [ ] **Step 1: Write the failing tests for the spec, seeding and the two simplest shapes**

```python
# 99_simulator/test/test_signals.py
import pytest

from uns_simulator.signals import (
    SIGNAL_SHAPES,
    SignalSpec,
    build_signal,
    signal_seed,
    spec_from_config,
)


def test_legacy_sensor_config_still_parses_as_noise():
    spec = spec_from_config("Temperature", {"base_value": 75.0, "variation": 2.0, "unit": "°C"})
    assert spec.shape == "noise"
    assert spec.base_value == pytest.approx(75.0)
    assert spec.variation == pytest.approx(2.0)
    assert spec.unit == "°C"
    assert spec.tier == "process"
    assert spec.precision == 2  # noqa: PLR2004


def test_seed_is_stable_for_the_same_topic():
    assert signal_seed(1234, "A/B/C") == signal_seed(1234, "A/B/C")


def test_seed_differs_by_topic_and_by_global_seed():
    assert signal_seed(1234, "A/B/C") != signal_seed(1234, "A/B/D")
    assert signal_seed(1234, "A/B/C") != signal_seed(5678, "A/B/C")


def test_seed_is_stable_across_processes():
    """A literal, not a recomputation: `hash()` would make this value vary per process."""
    assert signal_seed(0, "CovestroAG/Dormagen/Production/Line1/Cell1/G1/ProcessValue/Temperature") == 6842570927962973474


def test_noise_stays_within_variation_band():
    signal = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7)
    for _ in range(500):
        value = signal.next(1.0, None, {})
        assert 73.0 <= value <= 77.0


def test_noise_is_reproducible_for_the_same_seed():
    first = [build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7).next(1.0, None, {})]
    second = [build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7).next(1.0, None, {})]
    assert first == second


def test_two_signals_on_different_topics_diverge():
    a = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "a/T", 7)
    b = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "b/T", 7)
    assert [a.next(1.0, None, {}) for _ in range(20)] != [b.next(1.0, None, {}) for _ in range(20)]


def test_shape_params_are_read_from_top_level_yaml_keys():
    """Spec 7.3 writes shape params flat: `expr:`, `rate:`, `initial:` are top-level."""
    spec = spec_from_config(
        "EnergyTotal",
        {"shape": "counter", "unit": "kWh", "rate": "ActivePower / 3600.0", "initial": 84000.0, "tier": "meter"},
    )
    assert spec.shape == "counter"
    assert spec.tier == "meter"
    assert spec.params == {"rate": "ActivePower / 3600.0", "initial": 84000.0}


def test_expression_constant_block_is_merged_into_params():
    """Spec 5.4 permits "keys of `params`" as expression names, so keep one flat namespace."""
    spec = spec_from_config(
        "ActivePower",
        {
            "shape": "derived",
            "unit": "kW",
            "expr": "base_load + ctx.served_production * connected_kw",
            "params": {"base_load": 220.0, "connected_kw": 1450.0},
        },
    )
    assert spec.params["expr"] == "base_load + ctx.served_production * connected_kw"
    assert spec.params["base_load"] == pytest.approx(220.0)
    assert spec.params["connected_kw"] == pytest.approx(1450.0)
    assert "params" not in spec.params


def test_constant_never_moves():
    signal = build_signal(SignalSpec(name="Sp", shape="constant", params={"value": 180.0}), "t/Sp", 7)
    assert [signal.next(1.0, None, {}) for _ in range(5)] == [180.0] * 5


def test_limits_take_precedence_over_the_noise_heuristic():
    """Spec 5.1: hihi/lolo -> Alarm, hi/lo -> Warning, and only then the legacy heuristic."""
    spec = SignalSpec(name="Lel", unit="%", variation=1.0, limits={"hi": 10.0, "hihi": 20.0})
    signal = build_signal(spec, "t/Lel", 7)
    signal.value = 5.0
    assert signal.status() == "Normal"
    signal.value = 12.0
    assert signal.status() == "Warning"
    signal.value = 25.0
    assert signal.status() == "Alarm"


def test_lo_and_lolo_limits_fire_downwards():
    spec = SignalSpec(name="O2", unit="%", limits={"lo": 19.5, "lolo": 18.0})
    signal = build_signal(spec, "t/O2", 7)
    signal.value = 20.9
    assert signal.status() == "Normal"
    signal.value = 19.0
    assert signal.status() == "Warning"
    signal.value = 17.5
    assert signal.status() == "Alarm"


def test_status_heuristic_matches_the_pre_existing_thresholds():
    signal = build_signal(SignalSpec(name="T", base_value=75.0, variation=2.0), "t/T", 7)
    signal.value = 75.0
    assert signal.status() == "Normal"
    signal.value = 75.0 + 2.0 * 2.5
    assert signal.status() == "Warning"
    signal.value = 75.0 + 2.0 * 3.5
    assert signal.status() == "Alarm"


def test_value_range_clamps():
    signal = build_signal(
        SignalSpec(name="T", base_value=75.0, variation=50.0, value_range=(70.0, 80.0)), "t/T", 7
    )
    for _ in range(200):
        assert 70.0 <= signal.next(1.0, None, {}) <= 80.0


def test_unknown_shape_names_itself():
    with pytest.raises(ValueError, match="banana"):
        build_signal(SignalSpec(name="X", shape="banana"), "t/X", 7)


def test_registry_holds_the_two_shapes_implemented_so_far():
    assert {"noise", "constant"} <= set(SIGNAL_SHAPES)
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_signals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_simulator.signals'`.

Note on `test_seed_is_stable_across_processes`: write the test with a placeholder `0`, run it once after Step 3, and paste the real value the implementation produces. It is a regression pin on the seeding algorithm, not a derived expectation — its purpose is to fail if someone swaps `blake2b` back to `hash()`.

- [ ] **Step 3: Implement the core**

```python
# 99_simulator/src/uns_simulator/signals.py
"""Declarative signal shapes.

A SignalSpec says what a signal *is*; a Signal subclass says how it *moves*. Shapes are
evaluated once per PlantClock tick (1 s) regardless of how often the owning device
publishes, so counters integrate correctly and derived signals always see fresh siblings.

Every stochastic signal owns a random.Random seeded from (global_seed, topic) via blake2b.
`hash()` is deliberately not used: Python randomises str hashing per process, which would
make "same seed ⇒ same run" false.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

WARNING_SIGMA = 2.0
ALARM_SIGMA = 3.0

SIGNAL_SHAPES: dict[str, type["Signal"]] = {}

# Spec 5.1's common fields. Every *other* top-level YAML key is a shape param, because
# spec 7.3 writes `expr:`, `rate:` and `initial:` flat rather than nested under `params:`.
_COMMON_FIELDS: Final = frozenset(
    {
        "shape",
        "unit",
        "precision",
        "range",
        "limits",
        "tier",
        "param_type",
        "export_metric",
        "base_value",
        "variation",
    }
)


@dataclass(frozen=True)
class SignalSpec:
    """One signal as declared in conf/simulator/*.yaml."""

    name: str
    shape: str = "noise"
    unit: str = ""
    precision: int = 2
    base_value: float = 0.0
    variation: float = 0.0
    value_range: tuple[float, float] | None = None
    limits: dict[str, float] = field(default_factory=dict)
    tier: str = "process"
    param_type: str = "ProcessValue"
    export_metric: bool = False
    params: dict[str, Any] = field(default_factory=dict)


def signal_seed(global_seed: int, topic: str) -> int:
    """Derive a per-signal seed that is identical in every process and on every platform."""
    digest = hashlib.blake2b(topic.encode("utf-8"), digest_size=8, key=str(global_seed).encode("utf-8"))
    return int.from_bytes(digest.digest(), "big")


class Signal:
    """Base class: owns the RNG, the current value, clamping and the status heuristic."""

    shape_name: ClassVar[str] = ""

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        self.spec = spec
        self.topic = topic
        self.rng = random.Random(signal_seed(global_seed, topic))
        self.value: float | str | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.shape_name:
            SIGNAL_SHAPES[cls.shape_name] = cls

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float | str | None:
        """Advance one tick of `dt` seconds and return the new value."""
        raise NotImplementedError

    def status(self) -> str:
        """Classify the current value, in spec 5.1's order: limits first, heuristic last."""
        if not isinstance(self.value, int | float) or isinstance(self.value, bool):
            return "Normal"
        value = float(self.value)
        limits = self.spec.limits
        if limits:
            hihi, lolo = limits.get("hihi"), limits.get("lolo")
            if (hihi is not None and value >= hihi) or (lolo is not None and value <= lolo):
                return "Alarm"
            high, low = limits.get("hi"), limits.get("lo")
            if (high is not None and value >= high) or (low is not None and value <= low):
                return "Warning"
            return "Normal"
        # No limits declared: preserve the exact 2x/3x heuristic devices.py used, but only
        # for `noise`, which is the only shape it was ever meaningful for.
        if self.spec.shape != "noise" or not self.spec.variation:
            return "Normal"
        deviation = abs(value - self.spec.base_value)
        if deviation > self.spec.variation * ALARM_SIGMA:
            return "Alarm"
        if deviation > self.spec.variation * WARNING_SIGMA:
            return "Warning"
        return "Normal"

    def _clamp(self, value: float) -> float:
        if self.spec.value_range is not None:
            low, high = self.spec.value_range
            value = max(low, min(high, value))
        return round(value, self.spec.precision)


class NoiseSignal(Signal):
    """base_value +/- variation, uniform. The default, and what today's YAML means."""

    shape_name = "noise"

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # noqa: ARG002
        self.value = self._clamp(self.spec.base_value + self.rng.uniform(-self.spec.variation, self.spec.variation))
        return self.value


class ConstantSignal(Signal):
    """A setpoint or nameplate figure. Spec 5.2 names its single param `value`."""

    shape_name = "constant"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        # `base_value` is the fallback so a legacy sensor entry can be pinned by adding
        # `shape: constant` alone, without also renaming its value key.
        self._fixed = float(spec.params.get("value", spec.base_value))

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # noqa: ARG002
        self.value = self._clamp(self._fixed)
        return self.value


def build_signal(spec: SignalSpec, topic: str, global_seed: int) -> Signal:
    """Instantiate the shape class `spec.shape` names."""
    try:
        shape_cls = SIGNAL_SHAPES[spec.shape]
    except KeyError:
        known = ", ".join(sorted(SIGNAL_SHAPES))
        raise ValueError(f"signal {spec.name!r}: unknown shape {spec.shape!r} (known shapes: {known})") from None
    return shape_cls(spec, topic, global_seed)


def spec_from_config(name: str, raw: Mapping[str, Any]) -> SignalSpec:
    """Build a SignalSpec from YAML, accepting the legacy base_value/variation form."""
    value_range = raw.get("range")
    params: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _COMMON_FIELDS:
            continue
        if key == "params":
            # Spec 7.3's expression-constant block. Flattened so that spec 5.4's
            # "keys of `params`" and the shape's own params share one namespace.
            params.update(dict(value or {}))
        else:
            params[key] = value
    return SignalSpec(
        name=name,
        shape=str(raw.get("shape", "noise")),
        unit=str(raw.get("unit", "")),
        precision=int(raw.get("precision", 2)),
        base_value=float(raw.get("base_value", 0.0)),
        variation=float(raw.get("variation", 0.0)),
        value_range=(float(value_range[0]), float(value_range[1])) if value_range else None,
        limits={str(k): float(v) for k, v in (raw.get("limits") or {}).items()},
        tier=str(raw.get("tier", "process")),
        param_type=str(raw.get("param_type", "ProcessValue")),
        export_metric=bool(raw.get("export_metric", False)),
        params=params,
    )
```

- [ ] **Step 4: Run the tests, then pin the cross-process seed**

Run: `uv run pytest test/test_signals.py -v`
Expected: everything passes except `test_seed_is_stable_across_processes`, which reports the actual value. Paste that value into the test and re-run. Then run it twice more in separate processes — it must give the same number every time.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/signals.py 99_simulator/test/test_signals.py
git commit -m "feat(simulator): add SignalSpec, deterministic per-signal seeding, noise and constant shapes"
```

---

## Task 3: Continuous shapes — `ou_walk`, `diurnal`, `sawtooth`

These three make a value look like a real instrument reading rather than independent draws. `ou_walk` is the workhorse: a mean-reverting random walk, so successive samples are correlated and the trace wanders instead of jittering.

**Files:**
- Modify: `99_simulator/src/uns_simulator/signals.py`
- Test: `99_simulator/test/test_signals.py`

**Interfaces:**
- Consumes: `Signal`, `SignalSpec`, `build_signal` from Task 2.
- Produces — param names are spec §5.2's, verbatim:
  - `"ou_walk"` — params `mean` (falls back to `base_value`), `sigma` (falls back to `variation`), `tau` seconds (default `60.0`). Attribute `._state: float`.
  - `"diurnal"` — params `mean` (falls back to `base_value`), `amplitude`, `period_s` (default `86400.0`), `phase_s` (default `0.0`), `noise` (default `0.0`). Attribute `.elapsed_s: float`.
  - `"sawtooth"` — params `low`, `high`, `fill_rate` and `drain_rate` in units per second, `start` (default `low`). Attributes `._state: float`, `._filling: bool`. **Not** a period-driven ramp: fill and drain rates are independent, because a cooling-tower basin refills far slower than it blows down.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_signals.py
import math

import statistics


def _run(signal, ticks, dt=1.0):
    return [signal.next(dt, None, {}) for _ in range(ticks)]


def test_ou_walk_is_autocorrelated_unlike_noise():
    """The point of ou_walk: consecutive samples are close, so the trace wanders."""
    walk = build_signal(
        SignalSpec(name="P", shape="ou_walk", params={"mean": 150.0, "tau": 60.0, "sigma": 5.0}),
        "t/P",
        7,
    )
    noise = build_signal(SignalSpec(name="P", base_value=150.0, variation=5.0), "t/P", 7)
    walk_steps = statistics.mean(abs(b - a) for a, b in zip(w := _run(walk, 300), w[1:], strict=False))
    noise_steps = statistics.mean(abs(b - a) for a, b in zip(n := _run(noise, 300), n[1:], strict=False))
    assert walk_steps < noise_steps / 2


def test_ou_walk_reverts_to_its_mean():
    signal = build_signal(
        SignalSpec(name="P", shape="ou_walk", params={"mean": 150.0, "tau": 10.0, "sigma": 3.0}),
        "t/P",
        7,
    )
    signal.value = 300.0
    signal._state = 300.0
    for _ in range(200):
        signal.next(1.0, None, {})
    assert abs(signal.value - 150.0) < 20.0  # noqa: PLR2004


def test_ou_walk_falls_back_to_base_value_and_variation():
    """A legacy entry gains a trend line by adding `shape: ou_walk` and nothing else."""
    signal = build_signal(
        SignalSpec(name="P", shape="ou_walk", base_value=150.0, variation=5.0), "t/P", 7
    )
    assert signal._mean == pytest.approx(150.0)
    assert signal._sigma == pytest.approx(5.0)


def test_ou_walk_respects_value_range():
    signal = build_signal(
        SignalSpec(
            name="P",
            shape="ou_walk",
            value_range=(140.0, 160.0),
            params={"mean": 150.0, "tau": 5.0, "sigma": 50.0},
        ),
        "t/P",
        7,
    )
    for value in _run(signal, 500):
        assert 140.0 <= value <= 160.0


def test_diurnal_peaks_and_troughs_once_per_period():
    signal = build_signal(
        SignalSpec(
            name="Amb",
            shape="diurnal",
            precision=3,
            params={"mean": 20.0, "amplitude": 6.0, "period_s": 100.0, "phase_s": 25.0},
        ),
        "t/Amb",
        7,
    )
    values = _run(signal, 100)
    assert max(values) == pytest.approx(26.0, abs=0.05)
    assert min(values) == pytest.approx(14.0, abs=0.05)


def test_diurnal_is_smooth():
    signal = build_signal(
        SignalSpec(name="Amb", shape="diurnal", precision=3, params={"mean": 20.0, "amplitude": 6.0, "period_s": 600.0}),
        "t/Amb",
        7,
    )
    values = _run(signal, 200)
    assert all(abs(b - a) < 0.5 for a, b in zip(values, values[1:], strict=False))  # noqa: PLR2004


def test_sawtooth_fills_slowly_and_drains_quickly():
    """Spec 5.2: independent fill_rate and drain_rate, both in units per second."""
    signal = build_signal(
        SignalSpec(
            name="Basin",
            shape="sawtooth",
            precision=3,
            params={"low": 0.0, "high": 100.0, "fill_rate": 10.0, "drain_rate": 50.0},
        ),
        "t/Basin",
        7,
    )
    values = _run(signal, 13)
    assert values[0] == pytest.approx(10.0)
    assert values[9] == pytest.approx(100.0)
    assert values[10] == pytest.approx(50.0)
    assert values[11] == pytest.approx(0.0)
    assert values[12] == pytest.approx(10.0)


def test_sawtooth_starts_where_start_says():
    signal = build_signal(
        SignalSpec(
            name="Basin",
            shape="sawtooth",
            precision=3,
            params={"low": 20.0, "high": 80.0, "fill_rate": 1.0, "drain_rate": 1.0, "start": 79.0},
        ),
        "t/Basin",
        7,
    )
    assert signal.next(1.0, None, {}) == pytest.approx(80.0)
    assert signal.next(1.0, None, {}) == pytest.approx(79.0)


def test_sawtooth_drain_rate_defaults_to_fill_rate():
    signal = build_signal(
        SignalSpec(name="Basin", shape="sawtooth", params={"low": 0.0, "high": 5.0, "fill_rate": 5.0}),
        "t/Basin",
        7,
    )
    assert signal._drain_rate == pytest.approx(5.0)
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_signals.py -k "ou_walk or diurnal or sawtooth" -v`
Expected: FAIL — `ValueError: unknown shape 'ou_walk'`.

- [ ] **Step 3: Implement the three shapes**

```python
# append to 99_simulator/src/uns_simulator/signals.py
class OUWalkSignal(Signal):
    """Ornstein-Uhlenbeck mean-reverting walk.

    x += (mean - x) * dt/tau + sigma * sqrt(dt/tau) * N(0, 1)

    `tau` is the reversion time constant in seconds: small tau snaps back to `mean`,
    large tau lets the value drift for minutes the way a real process variable does.
    `mean` and `sigma` fall back to `base_value` and `variation` so a legacy sensor entry
    becomes a trend line by adding `shape: ou_walk` alone.
    """

    shape_name = "ou_walk"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        self._mean = float(spec.params.get("mean", spec.base_value))
        self._tau = max(float(spec.params.get("tau", 60.0)), 1e-6)
        self._sigma = float(spec.params.get("sigma", spec.variation or 1.0))
        self._state = self._mean

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # noqa: ARG002
        ratio = dt / self._tau
        self._state += (self._mean - self._state) * ratio + self._sigma * math.sqrt(ratio) * self.rng.gauss(0.0, 1.0)
        if self.spec.value_range is not None:
            low, high = self.spec.value_range
            self._state = max(low, min(high, self._state))
        self.value = self._clamp(self._state)
        return self.value


class DiurnalSignal(Signal):
    """A sine over `period_s` (default one day) plus optional noise. Ambient conditions."""

    shape_name = "diurnal"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        self.elapsed_s = 0.0
        self._mean = float(spec.params.get("mean", spec.base_value))
        self._amplitude = float(spec.params.get("amplitude", spec.variation))
        self._period_s = max(float(spec.params.get("period_s", 86400.0)), 1e-6)
        self._phase_s = float(spec.params.get("phase_s", 0.0))
        self._noise = float(spec.params.get("noise", 0.0))

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # noqa: ARG002
        angle = 2.0 * math.pi * ((self.elapsed_s + self._phase_s) % self._period_s) / self._period_s
        value = self._mean + self._amplitude * math.sin(angle)
        if self._noise:
            value += self.rng.gauss(0.0, self._noise)
        self.elapsed_s += dt
        self.value = self._clamp(value)
        return self.value


class SawtoothSignal(Signal):
    """Fills at `fill_rate` to `high`, drains at `drain_rate` to `low`, repeat.

    Rates are units per second, and they are independent because that is what real level
    signals do: a cooling-tower basin or a boiler drum refills far more slowly than it
    blows down, and a period-driven triangle wave cannot express that asymmetry.
    """

    shape_name = "sawtooth"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        self._low = float(spec.params.get("low", 0.0))
        self._high = float(spec.params.get("high", self._low + 100.0))
        self._fill_rate = abs(float(spec.params.get("fill_rate", 1.0)))
        self._drain_rate = abs(float(spec.params.get("drain_rate", self._fill_rate)))
        self._state = float(spec.params.get("start", self._low))
        self._filling = True

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # noqa: ARG002
        if self._filling:
            self._state += self._fill_rate * dt
            if self._state >= self._high:
                self._state = self._high
                self._filling = False
        else:
            self._state -= self._drain_rate * dt
            if self._state <= self._low:
                self._state = self._low
                self._filling = True
        self.value = self._clamp(self._state)
        return self.value
```

Add `import math` to the top of `signals.py` alongside `hashlib` and `random`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_signals.py -v`
Expected: all pass. If `test_ou_walk_is_autocorrelated_unlike_noise` fails, `tau_s` is too small relative to `dt` — the ratio `dt/tau` must be well under 1 for the walk to be smooth.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/signals.py 99_simulator/test/test_signals.py
git commit -m "feat(simulator): add ou_walk, diurnal and sawtooth signal shapes"
```

---

## Task 4: Accumulating shapes — `counter` and `window_agg`

A kWh register, a water m³ total and a piece count are all *monotonic accumulations* — inexpressible as `base ± variation`, and the single biggest reason today's simulator cannot produce plausible energy or water data. `window_agg` supplies the rolling min/max/mean an operator expects next to a raw value.

**Files:**
- Modify: `99_simulator/src/uns_simulator/signals.py`
- Test: `99_simulator/test/test_signals.py`

**Interfaces:**
- Consumes: Task 2 core.
- Produces — param names are spec §5.2's, verbatim:
  - `"counter"` — params `rate` (a number **or** the name of a sibling signal; spec §5.2 also allows an expression, which Task 6 adds), `initial` (default `0.0`), `rollover` (optional). Attributes `.total: float` and the seam `_rate_value(view, siblings) -> float` that **Task 6 replaces** with expression evaluation. `status()` is overridden to `"Normal"`.
  - `"window_agg"` — params `source` (sibling name), `agg` one of `min`/`max`/`mean` (default `mean`), `window_s` (default `900.0`). An unknown `agg` raises `ValueError` at construction, so a typo is a load-time failure rather than a silent fallback to the mean.
- There is deliberately **no** `scale` and no `only_when_running`. Both are expressible as a `rate` expression — `ActivePower / 3600.0` for kW→kWh, `ctx.production_rate * 2.0` for a piece count that stops when the line does — and a second mechanism for the same thing would let one contradict the other.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_signals.py
class FakeView:
    """Minimal stand-in for plant.DeviceView until Task 8 exists."""

    def __init__(self, *, running=True, production_rate=1.0, ambient_temp_c=20.0):
        self.running = running
        self.production_rate = production_rate
        self.ambient_temp_c = ambient_temp_c


def test_counter_integrates_a_sibling_named_by_rate():
    """`rate` naming a sibling integrates that sibling: 2 ea/s for 10 s is 20 ea."""
    signal = build_signal(
        SignalSpec(name="GoodCount", shape="counter", unit="ea", precision=0, params={"rate": "PieceRate"}),
        "t/Good",
        7,
    )
    view = FakeView()
    for _ in range(10):
        signal.next(1.0, view, {"PieceRate": 2.0})
    assert signal.value == pytest.approx(20.0)


def test_counter_integrates_a_fixed_numeric_rate():
    signal = build_signal(
        SignalSpec(name="RunHours", shape="counter", unit="h", precision=4, params={"rate": 1.0 / 3600.0}),
        "t/RH",
        7,
    )
    for _ in range(3600):
        signal.next(1.0, FakeView(), {})
    assert signal.value == pytest.approx(1.0, abs=1e-4)


def test_counter_never_decreases():
    signal = build_signal(
        SignalSpec(name="Vol", shape="counter", precision=4, params={"rate": "Flow"}),
        "t/V",
        7,
    )
    view = FakeView()
    values = [signal.next(1.0, view, {"Flow": 12.0}) for _ in range(50)]
    assert all(b >= a for a, b in zip(values, values[1:], strict=False))


def test_counter_holds_its_reading_when_the_rate_is_zero():
    """A stopped line is a zero rate, not a special case inside the counter."""
    signal = build_signal(
        SignalSpec(name="Pieces", shape="counter", precision=0, params={"rate": "PieceRate"}),
        "t/Pieces",
        7,
    )
    view = FakeView()
    for _ in range(10):
        signal.next(1.0, view, {"PieceRate": 2.0})
    frozen = signal.value
    for _ in range(10):
        signal.next(1.0, view, {"PieceRate": 0.0})
    assert signal.value == frozen


def test_counter_holds_its_reading_when_the_named_rate_sibling_is_absent():
    signal = build_signal(
        SignalSpec(name="Pieces", shape="counter", precision=0, params={"rate": "Missing", "initial": 5.0}),
        "t/Pieces",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(5.0)


def test_counter_starts_from_initial():
    signal = build_signal(
        SignalSpec(name="RunHours", shape="counter", precision=2, params={"rate": 1.0, "initial": 12345.0}),
        "t/RH",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(12346.0)


def test_counter_wraps_at_rollover():
    """A real 6-digit register wraps; a consumer computing deltas must cope with it."""
    signal = build_signal(
        SignalSpec(name="Energy", shape="counter", precision=1, params={"rate": 10.0, "initial": 95.0, "rollover": 100.0}),
        "t/E",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(5.0)
    assert signal.next(1.0, FakeView(), {}) == pytest.approx(15.0)


def test_window_agg_reports_the_max_over_its_window():
    signal = build_signal(
        SignalSpec(name="PeakDemand", shape="window_agg", params={"source": "ActivePower", "window_s": 5.0, "agg": "max"}),
        "t/Peak",
        7,
    )
    view = FakeView()
    for power in (100.0, 300.0, 200.0, 150.0, 120.0):
        signal.next(1.0, view, {"ActivePower": power})
    assert signal.value == pytest.approx(300.0)
    for power in (100.0, 100.0, 100.0, 100.0, 100.0):
        signal.next(1.0, view, {"ActivePower": power})
    assert signal.value == pytest.approx(100.0), "the 300 kW sample must age out of the window"


def test_window_agg_mean():
    signal = build_signal(
        SignalSpec(name="AvgT", shape="window_agg", params={"source": "T", "window_s": 4.0, "agg": "mean"}),
        "t/AvgT",
        7,
    )
    for value in (10.0, 20.0, 30.0, 40.0):
        signal.next(1.0, FakeView(), {"T": value})
    assert signal.value == pytest.approx(25.0)


def test_window_agg_missing_source_is_none_not_a_crash():
    signal = build_signal(
        SignalSpec(name="AvgT", shape="window_agg", params={"source": "absent", "agg": "mean"}),
        "t/AvgT",
        7,
    )
    assert signal.next(1.0, FakeView(), {}) is None


def test_window_agg_rejects_an_unknown_aggregate_at_construction():
    with pytest.raises(ValueError, match="medain"):
        build_signal(
            SignalSpec(name="AvgT", shape="window_agg", params={"source": "T", "agg": "medain"}),
            "t/AvgT",
            7,
        )
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_signals.py -k "counter or window_agg" -v`
Expected: FAIL — `ValueError: unknown shape 'counter'`.

- [ ] **Step 3: Implement both shapes**

```python
# append to 99_simulator/src/uns_simulator/signals.py
_AGGREGATES: Final = {
    "min": min,
    "max": max,
    "mean": lambda values: sum(values) / len(values),
}


class CounterSignal(Signal):
    """A monotonic register: kWh, m3, Nm3, run hours, piece counts.

    `value += rate * dt`, where `rate` is a number or the name of a sibling signal. Unit
    conversion belongs in the rate itself (`ActivePower / 3600.0` for kW -> kWh), which is
    why there is no `scale` param; Task 6 makes that expression form work.

    Never decreases, which is what makes it a meter reading rather than a measurement, and
    wraps at `rollover` when one is declared, because real registers have finite digits.
    """

    shape_name = "counter"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        self.total = float(spec.params.get("initial", 0.0))
        self._rate = spec.params.get("rate", 0.0)
        rollover = spec.params.get("rollover")
        self._rollover = float(rollover) if rollover else None

    def _rate_value(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # noqa: ARG002
        """Resolve `rate` this tick. Task 6 replaces this body with expression evaluation.

        `dt` is in the signature from the outset so Task 6 can hand it to the expression
        namespace without changing the seam every caller already uses.
        """
        rate = self._rate
        if isinstance(rate, str):
            rate = siblings.get(rate)
        if isinstance(rate, bool) or not isinstance(rate, int | float):
            return 0.0
        return float(rate)

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:
        self.total += max(self._rate_value(dt, view, siblings), 0.0) * dt
        if self._rollover is not None and self.total >= self._rollover:
            self.total %= self._rollover
        self.value = round(self.total, self.spec.precision)
        return self.value

    def status(self) -> str:
        """A register has no band to be outside of."""
        return "Normal"


class WindowAggSignal(Signal):
    """A rolling min/max/mean of a sibling over `window_s` seconds."""

    shape_name = "window_agg"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        self.elapsed_s = 0.0
        self._source = str(spec.params.get("source", ""))
        self._window_s = max(float(spec.params.get("window_s", 900.0)), 1e-6)
        agg = str(spec.params.get("agg", "mean"))
        if agg not in _AGGREGATES:
            known = ", ".join(sorted(_AGGREGATES))
            raise ValueError(f"signal {spec.name!r}: unknown agg {agg!r} (known: {known})")
        self._agg = _AGGREGATES[agg]
        self._samples: deque[tuple[float, float]] = deque()

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float | None:  # noqa: ARG002
        self.elapsed_s += dt
        sample = siblings.get(self._source)
        if isinstance(sample, int | float) and not isinstance(sample, bool):
            self._samples.append((self.elapsed_s, float(sample)))
        cutoff = self.elapsed_s - self._window_s
        while self._samples and self._samples[0][0] <= cutoff:
            self._samples.popleft()
        if not self._samples:
            self.value = None
            return None
        self.value = self._clamp(self._agg([value for _, value in self._samples]))
        return self.value
```

Add `from collections import deque` to the imports in `signals.py`.

Note on `max(self._rate_value(...), 0.0)`: a negative rate is clamped to zero rather than allowed to run the register backwards. Spec §5.2 says "monotonic non-decreasing", and a `rate` expression that briefly goes negative (a derived flow during a valve reversal, say) must not decrement a totaliser — that would make every downstream delta calculation wrong.

Note on the window boundary: the cutoff is `<=`, so a 5 s window keeps exactly 5 one-second samples. `test_window_agg_reports_the_max_over_its_window` depends on that — with `<` it would keep 6 and the 300 kW sample would linger a tick.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_signals.py -v`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/signals.py 99_simulator/test/test_signals.py
git commit -m "feat(simulator): add monotonic counter and rolling window_agg signal shapes"
```

---

## Task 5: Discrete shapes — `stepped` and `bernoulli_event`

Not everything is a float. A valve position, a PackML mode, a selector switch takes one of a few states; a filter alarm or a door-open event fires occasionally. Without these, every "status" signal in the spec would have to be faked as a rounded number.

**Files:**
- Modify: `99_simulator/src/uns_simulator/signals.py`
- Test: `99_simulator/test/test_signals.py`

**Interfaces:**
- Consumes: Task 2 core.
- Produces — param names are spec §5.2's, verbatim:
  - `resolve_ctx_path(view: Any, path: str) -> Any` — walks a dotted path such as `line.state` against the `DeviceView`, tolerating a leading `ctx.`, returning `None` if any hop is missing.
  - shape `"stepped"` — params `source` (a dotted `ctx` path) **or** `choices` (a list), plus `map` (an optional value→value translation applied to either). Declaring neither `source` nor `choices` raises `ValueError` naming the signal.
  - shape `"bernoulli_event"` — params `p` (probability **per tick**) and `choices`. Returns one of `choices` on the tick it fires and `None` otherwise; Task 14 treats `None` as "publish nothing", which is what spec §5.2 asks for.
- Two param names this plan chooses, because spec §5.2 describes the behaviour ("`choices` picks from a list on a dwell timer") without naming the knobs: `dwell_s` (default `300.0`) and an optional `weights` list alongside `choices`. Recorded here so the YAML in Tasks 16–18 and any future reader agree on them.
- `stepped` overrides `status()` to `"Normal"`; `bernoulli_event` reports `"Alarm"` on the tick it fires and `"Normal"` otherwise, since a fired event is by construction the abnormal case.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_signals.py
def test_stepped_holds_its_value_for_the_dwell_time():
    signal = build_signal(
        SignalSpec(name="Mode", shape="stepped", params={"choices": ["Auto", "Manual", "Local"], "dwell_s": 10.0}),
        "t/Mode",
        7,
    )
    values = [signal.next(1.0, None, {}) for _ in range(10)]
    assert len(set(values)) == 1, "must not change within one dwell period"


def test_stepped_only_ever_emits_declared_choices():
    signal = build_signal(
        SignalSpec(name="Mode", shape="stepped", params={"choices": ["Auto", "Manual"], "dwell_s": 1.0}),
        "t/Mode",
        7,
    )
    assert {signal.next(1.0, None, {}) for _ in range(200)} <= {"Auto", "Manual"}


def test_stepped_respects_weights():
    signal = build_signal(
        SignalSpec(
            name="Mode",
            shape="stepped",
            params={"choices": ["Auto", "Manual"], "weights": [99.0, 1.0], "dwell_s": 1.0},
        ),
        "t/Mode",
        7,
    )
    values = [signal.next(1.0, None, {}) for _ in range(1000)]
    assert values.count("Auto") > values.count("Manual") * 10


def test_stepped_reads_a_ctx_source_path():
    """Spec 8.5: PackMlState is `stepped` from the line state — it mirrors, not invents.

    The nested `line.state` here is a deliberately arbitrary path, proving `resolve_ctx_path`
    walks whatever depth it is given. The real `DeviceView` (Task 8) is flat, so the path a
    configuration file writes is `ctx.state`; Task 18 restates that where it matters.
    """
    signal = build_signal(
        SignalSpec(name="PackMlState", shape="stepped", params={"source": "line.state"}),
        "t/State",
        7,
    )
    view = FakeView(line=FakeLine(state="EXECUTE"))
    assert signal.next(1.0, view, {}) == "EXECUTE"
    view.line.state = "HELD"
    assert signal.next(1.0, view, {}) == "HELD", "a sourced stepped signal follows immediately"


def test_stepped_translates_through_map():
    signal = build_signal(
        SignalSpec(
            name="PackMlStateCode",
            shape="stepped",
            params={"source": "ctx.line.state", "map": {"IDLE": 1, "EXECUTE": 6}},
        ),
        "t/Code",
        7,
    )
    assert signal.next(1.0, FakeView(line=FakeLine(state="EXECUTE")), {}) == 6  # noqa: PLR2004
    assert signal.next(1.0, FakeView(line=FakeLine(state="IDLE")), {}) == 1


def test_stepped_passes_an_unmapped_value_through_unchanged():
    signal = build_signal(
        SignalSpec(name="Code", shape="stepped", params={"source": "line.state", "map": {"IDLE": 1}}),
        "t/Code",
        7,
    )
    assert signal.next(1.0, FakeView(line=FakeLine(state="ABORTED")), {}) == "ABORTED"


def test_stepped_without_source_or_choices_names_the_signal():
    with pytest.raises(ValueError, match="TapPosition"):
        build_signal(SignalSpec(name="TapPosition", shape="stepped"), "t/Tap", 7)


def test_resolve_ctx_path_tolerates_a_missing_hop():
    from uns_simulator.signals import resolve_ctx_path

    assert resolve_ctx_path(FakeView(line=FakeLine(state="IDLE")), "line.state") == "IDLE"
    assert resolve_ctx_path(FakeView(line=None), "line.state") is None
    assert resolve_ctx_path(None, "line.state") is None
    assert resolve_ctx_path(FakeView(), "no_such_field") is None


def test_bernoulli_event_fires_at_roughly_the_declared_rate():
    """`p` is per tick, and the PlantClock ticks every second: 1/3600 is once an hour."""
    signal = build_signal(
        SignalSpec(name="DetectorFault", shape="bernoulli_event", params={"p": 1.0 / 3600.0, "choices": ["Fault"]}),
        "t/DF",
        7,
    )
    fires = sum(1 for _ in range(360_000) if signal.next(1.0, None, {}) == "Fault")
    assert 70 <= fires <= 130, f"expected ~100 fires in 100 simulated hours, got {fires}"  # noqa: PLR2004


def test_bernoulli_event_publishes_nothing_on_a_quiet_tick():
    signal = build_signal(
        SignalSpec(name="Door", shape="bernoulli_event", params={"p": 0.0001, "choices": ["Opened", "Closed"]}),
        "t/Door",
        7,
    )
    values = [signal.next(1.0, None, {}) for _ in range(1000)]
    assert values.count(None) > 990  # noqa: PLR2004
    assert set(values) <= {None, "Opened", "Closed"}


def test_bernoulli_event_status_marks_the_tick_it_fires():
    signal = build_signal(
        SignalSpec(name="Trip", shape="bernoulli_event", params={"p": 1.0, "choices": ["Tripped"]}),
        "t/Trip",
        7,
    )
    assert signal.next(1.0, None, {}) == "Tripped"
    assert signal.status() == "Alarm"


def test_stepped_reports_normal_status():
    signal = build_signal(SignalSpec(name="Mode", shape="stepped", params={"choices": ["Auto"]}), "t/Mode", 7)
    signal.next(1.0, None, {})
    assert signal.status() == "Normal"
```

`FakeView` gains the two attributes these tests need — extend the class written in Task 4 rather than adding a second fake:

```python
# in 99_simulator/test/test_signals.py, replacing the Task 4 FakeView
class FakeLine:
    def __init__(self, *, state="EXECUTE", production_rate=1.0, throughput_tph=10.0):
        self.state = state
        self.production_rate = production_rate
        self.throughput_tph = throughput_tph


class FakeView:
    """Minimal stand-in for plant.DeviceView until Task 8 exists."""

    def __init__(self, *, running=True, production_rate=1.0, ambient_temp_c=20.0, line=None):
        self.running = running
        self.production_rate = production_rate
        self.ambient_temp_c = ambient_temp_c
        self.line = line
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_signals.py -k "stepped or bernoulli" -v`
Expected: FAIL — `ValueError: unknown shape 'stepped'`.

- [ ] **Step 3: Implement both shapes**

```python
# append to 99_simulator/src/uns_simulator/signals.py
def resolve_ctx_path(view: Any, path: str) -> Any:
    """Walk a dotted path such as `line.state` against the DeviceView.

    A leading `ctx.` is accepted so YAML can be written either way, and a missing hop
    returns None rather than raising: a utility device legitimately has no line.
    """
    current = view
    for part in path.removeprefix(f"{ATTRIBUTE_ROOT}.").split("."):
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


class SteppedSignal(Signal):
    """A discrete value: either mirrored from a `ctx` path, or picked from `choices`.

    `source` is how PackML state, tariff period and shift reach a topic — the signal
    reports the plant's state rather than inventing one, which is the whole point of
    having a PlantContext. `choices` covers the genuinely arbitrary discretes (tap
    position, downtime reason, batch id), changing only every `dwell_s` seconds so a
    consumer sees a state that holds rather than per-sample flicker.

    `map` translates whichever of the two produced the value, which is how
    PackMlStateCode is the same signal as PackMlState with a lookup table attached.
    """

    shape_name = "stepped"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        self._source = spec.params.get("source")
        self._choices = list(spec.params.get("choices") or [])
        if not self._source and not self._choices:
            raise ValueError(f"signal {spec.name!r}: shape 'stepped' needs either `source` or `choices`")
        self._map = dict(spec.params.get("map") or {})
        weights = spec.params.get("weights")
        self._weights = [float(w) for w in weights] if weights else None
        self._dwell_s = max(float(spec.params.get("dwell_s", 300.0)), 1e-6)
        # Start "expired" so the first tick picks a value instead of publishing None.
        self._held_s = self._dwell_s

    def _translate(self, value: Any) -> Any:
        return self._map.get(value, value) if self._map else value

    def _pick(self) -> Any:
        if self._weights:
            return self.rng.choices(self._choices, weights=self._weights, k=1)[0]
        return self.rng.choice(self._choices)

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> Any:  # noqa: ARG002
        if self._source:
            self.value = self._translate(resolve_ctx_path(view, str(self._source)))
            return self.value
        self._held_s += dt
        if self._held_s >= self._dwell_s:
            self._held_s = 0.0
            self.value = self._translate(self._pick())
        return self.value

    def status(self) -> str:
        return "Normal"


class BernoulliEventSignal(Signal):
    """With probability `p` per tick, emit one of `choices`; otherwise emit nothing.

    `p` is per tick, not per hour, and the PlantClock ticks every second — so 1/3600 is
    "about once an hour". Returning None is meaningful: Task 14 skips publishing on a
    quiet tick, which is what makes this an event topic rather than a value topic that
    happens to say "no".
    """

    shape_name = "bernoulli_event"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        self._p = float(spec.params.get("p", 0.0))
        self._choices = list(spec.params.get("choices") or [True])

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> Any:  # noqa: ARG002
        self.value = self.rng.choice(self._choices) if self.rng.random() < self._p else None
        return self.value

    def status(self) -> str:
        return "Normal" if self.value is None else "Alarm"
```

`"ctx"` must have exactly one spelling in the codebase, or the expression validator and the path resolver can drift apart. Task 1 already exports it as `ATTRIBUTE_ROOT`; import it here:

```python
from uns_simulator.expressions import ATTRIBUTE_ROOT
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_signals.py -v`
Expected: all pass. `test_bernoulli_event_fires_at_roughly_the_declared_rate` runs 360k ticks — that is ~1 s of CPU, well inside the 300 s timeout.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/signals.py 99_simulator/test/test_signals.py
git commit -m "feat(simulator): add stepped and bernoulli_event discrete signal shapes"
```

---

## Task 6: `derived` shape, dependency ordering and cycle rejection

This is what makes the data *correlated* rather than merely plausible: chiller kW follows the heat load that follows the line's production rate. Ordering matters — a derived signal evaluated before its inputs would read last tick's values, which is the kind of bug that looks like a physics problem for a week. Cycles are rejected at load time, not discovered at runtime.

**Files:**
- Modify: `99_simulator/src/uns_simulator/signals.py`
- Test: `99_simulator/test/test_signals.py`

**Interfaces:**
- Consumes: `compile_expression`, `ExpressionError` from Task 1; the Task 2 core.
- Produces:
  - shape `"derived"`, whose `expr` is a **top-level** YAML key (spec §7.3) that Task 2's `spec_from_config` deposits in `spec.params["expr"]`. Absent, `ValueError` naming the signal.
  - `signal_namespace(spec: SignalSpec, dt: float, view: Any, siblings: Mapping[str, Any]) -> dict[str, Any]` — the one evaluation namespace, `{**spec.params, **siblings, "ctx": view, "dt": dt}`. Siblings win over params on a name clash, so a param acts as a default. Shared by `derived` and `counter.rate` so the two can never diverge on what a name means.
  - **`CounterSignal._rate_value` is replaced** so `rate` accepts spec §5.2's third form, an expression: `rate: ActivePower / 3600.0` is how kWh is declared. A bare sibling name is just the one-name case of the same mechanism, so the number/name/expression trio collapses to "a number, or an expression".
  - `signal_dependencies(spec: SignalSpec) -> frozenset[str]` — sibling names this spec reads: expression names for `derived` and for a string `counter.rate`, `source` for `window_agg`. A `stepped` `source` is **not** a dependency — it is a `ctx` path, not a sibling.
  - `order_signals(specs: Sequence[SignalSpec]) -> list[SignalSpec]` — dependency order; raises `ValueError` naming every signal in the cycle.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_signals.py
from uns_simulator.signals import order_signals, signal_dependencies


def test_derived_reads_siblings():
    signal = build_signal(
        SignalSpec(name="ApparentPower", shape="derived", precision=1, params={"expr": "ActivePower / PowerFactor"}),
        "t/S",
        7,
    )
    assert signal.next(1.0, None, {"ActivePower": 450.0, "PowerFactor": 0.9}) == pytest.approx(500.0)


def test_derived_reads_plant_context_through_ctx():
    signal = build_signal(
        SignalSpec(name="ChillerLoad", shape="derived", precision=2, params={"expr": "ctx.ambient_temp_c * 3.0"}),
        "t/CL",
        7,
    )
    assert signal.next(1.0, FakeView(ambient_temp_c=30.0), {}) == pytest.approx(90.0)


def test_derived_params_supply_constants():
    signal = build_signal(
        SignalSpec(name="Power", shape="derived", precision=2, params={"expr": "flow * head * k", "k": 0.0027}),
        "t/P",
        7,
    )
    assert signal.next(1.0, None, {"flow": 100.0, "head": 40.0}) == pytest.approx(10.8)


def test_derived_siblings_override_params():
    signal = build_signal(
        SignalSpec(name="X", shape="derived", precision=2, params={"expr": "a", "a": 1.0}),
        "t/X",
        7,
    )
    assert signal.next(1.0, None, {"a": 9.0}) == pytest.approx(9.0)


def test_derived_without_expr_names_the_signal():
    with pytest.raises(ValueError, match="ChillerLoad"):
        build_signal(SignalSpec(name="ChillerLoad", shape="derived"), "t/CL", 7)


def test_derived_missing_sibling_yields_none_not_a_crash():
    signal = build_signal(SignalSpec(name="X", shape="derived", params={"expr": "absent * 2"}), "t/X", 7)
    assert signal.next(1.0, None, {}) is None


def test_counter_rate_accepts_an_expression():
    """Spec 7.3's EnergyTotal, verbatim: 450 kW integrated for an hour is 450 kWh."""
    signal = build_signal(
        SignalSpec(
            name="EnergyTotal",
            shape="counter",
            unit="kWh",
            precision=3,
            params={"rate": "ActivePower / 3600.0", "initial": 84000.0},
        ),
        "t/E",
        7,
    )
    for _ in range(3600):
        signal.next(1.0, FakeView(), {"ActivePower": 450.0})
    assert signal.value == pytest.approx(84450.0, abs=0.01)


def test_counter_rate_expression_can_read_ctx_and_params():
    signal = build_signal(
        SignalSpec(
            name="GoodCount",
            shape="counter",
            precision=0,
            params={"rate": "ctx.line.production_rate * per_second", "per_second": 3.0},
        ),
        "t/Good",
        7,
    )
    view = FakeView(line=FakeLine(production_rate=0.5))
    for _ in range(10):
        signal.next(1.0, view, {})
    assert signal.value == pytest.approx(15.0)
    view.line.production_rate = 0.0
    for _ in range(10):
        signal.next(1.0, view, {})
    assert signal.value == pytest.approx(15.0), "a held line must not advance the register"


def test_dependencies_are_found_for_every_shape_that_reads_siblings():
    assert signal_dependencies(SignalSpec(name="a", shape="derived", params={"expr": "b + c"})) == frozenset({"b", "c"})
    assert signal_dependencies(SignalSpec(name="a", shape="counter", params={"rate": "Power"})) == frozenset({"Power"})
    assert signal_dependencies(
        SignalSpec(name="a", shape="counter", params={"rate": "Power / 3600.0"})
    ) == frozenset({"Power"})
    assert signal_dependencies(SignalSpec(name="a", shape="counter", params={"rate": 2.0})) == frozenset()
    assert signal_dependencies(
        SignalSpec(name="a", shape="window_agg", params={"source": "T"})
    ) == frozenset({"T"})
    assert signal_dependencies(SignalSpec(name="a")) == frozenset()


def test_a_stepped_ctx_source_is_not_a_sibling_dependency():
    """`line.state` is a ctx path, so ordering must not look for a sibling called `line`."""
    assert signal_dependencies(SignalSpec(name="a", shape="stepped", params={"source": "line.state"})) == frozenset()


def test_ctx_and_dt_are_not_dependencies():
    deps = signal_dependencies(SignalSpec(name="a", shape="derived", params={"expr": "ctx.shift + dt + b"}))
    assert deps == frozenset({"b"})


def test_order_signals_puts_inputs_first():
    specs = [
        SignalSpec(name="Energy", shape="counter", params={"rate": "ApparentPower / 3600.0"}),
        SignalSpec(name="ApparentPower", shape="derived", params={"expr": "ActivePower / pf", "pf": 0.9}),
        SignalSpec(name="ActivePower", shape="ou_walk", params={"mean": 400.0}),
    ]
    assert [spec.name for spec in order_signals(specs)] == ["ActivePower", "ApparentPower", "Energy"]


def test_order_signals_is_stable_for_independent_signals():
    specs = [SignalSpec(name=name) for name in ("c", "a", "b")]
    assert [spec.name for spec in order_signals(specs)] == ["c", "a", "b"]


def test_order_signals_rejects_a_cycle_and_names_it():
    specs = [
        SignalSpec(name="a", shape="derived", params={"expr": "b + 1"}),
        SignalSpec(name="b", shape="derived", params={"expr": "a + 1"}),
    ]
    with pytest.raises(ValueError, match="cycle") as exc:
        order_signals(specs)
    assert "a" in str(exc.value) and "b" in str(exc.value)


def test_order_signals_rejects_self_reference():
    with pytest.raises(ValueError, match="cycle"):
        order_signals([SignalSpec(name="a", shape="derived", params={"expr": "a + 1"})])


def test_order_signals_ignores_references_to_signals_on_other_devices():
    """An unresolved name is not a dependency here; it fails at evaluation with None."""
    specs = [SignalSpec(name="a", shape="derived", params={"expr": "elsewhere * 2"})]
    assert [spec.name for spec in order_signals(specs)] == ["a"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_signals.py -k "derived or dependencies or order_signals or ctx_and_dt" -v`
Expected: FAIL — `ImportError: cannot import name 'order_signals'`.

- [ ] **Step 3: Implement `DerivedSignal`, `signal_dependencies` and `order_signals`**

```python
# append to 99_simulator/src/uns_simulator/signals.py
RESERVED_NAMESPACE_NAMES = frozenset({ATTRIBUTE_ROOT, "dt"})


def signal_namespace(spec: SignalSpec, dt: float, view: Any, siblings: Mapping[str, Any]) -> dict[str, Any]:
    """The one namespace every expression in this module is evaluated against.

    Siblings win over params on a name clash, so a param acts as a default. `derived` and
    `counter.rate` share this function rather than each building their own dict, because two
    namespaces that agree today would not stay agreeing.
    """
    return {**spec.params, **siblings, ATTRIBUTE_ROOT: view, "dt": dt}


class DerivedSignal(Signal):
    """A value computed from sibling signals and plant state.

    Evaluation failure (a missing sibling, a divide by zero) yields None rather than killing
    the device task; None is published as a null and shows in the UI as "no value", which is
    honest about what happened.
    """

    shape_name = "derived"

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        super().__init__(spec, topic, global_seed)
        source = spec.params.get("expr")
        if not source:
            raise ValueError(f"signal {spec.name!r}: shape 'derived' requires an `expr`")
        self._expression = compile_expression(str(source))

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float | None:
        try:
            result = self._expression.evaluate(signal_namespace(self.spec, dt, view, siblings))
        except ExpressionError:
            self.value = None
            return None
        self.value = self._clamp(float(result)) if isinstance(result, int | float) else result
        return self.value
```

Then replace `CounterSignal.__init__` and `CounterSignal._rate_value` from Task 4 so `rate` accepts spec §5.2's expression form:

```python
# in CounterSignal.__init__, after self._rate = spec.params.get("rate", 0.0)
        # A string rate is an expression. `ActivePower` and `ActivePower / 3600.0` go through
        # the same compiler, so the "number, sibling name, or expression" trio of spec 5.2 is
        # really just "a number, or an expression".
        self._rate_expression = compile_expression(str(self._rate)) if isinstance(self._rate, str) else None

    def _rate_value(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:
        if self._rate_expression is None:
            rate = self._rate
        else:
            try:
                rate = self._rate_expression.evaluate(signal_namespace(self.spec, dt, view, siblings))
            except ExpressionError:
                return 0.0
        if isinstance(rate, bool) or not isinstance(rate, int | float):
            return 0.0
        return float(rate)
```

`CounterSignal` is defined before `signal_namespace` in the file, which is fine — the name is resolved at call time, not at class-definition time. If you would rather not rely on that, move `signal_namespace` and `RESERVED_NAMESPACE_NAMES` up next to `_COMMON_FIELDS` when you make this edit.

```python
def signal_dependencies(spec: SignalSpec) -> frozenset[str]:
    """Sibling signal names `spec` reads. Used to order evaluation and to detect cycles."""

    def expression_names(source: object) -> frozenset[str]:
        names = compile_expression(str(source)).names
        return frozenset(names - RESERVED_NAMESPACE_NAMES - set(spec.params))

    match spec.shape:
        case "derived":
            source = spec.params.get("expr")
            return expression_names(source) if source else frozenset()
        case "counter":
            rate = spec.params.get("rate")
            # A numeric rate has no inputs; a string one is an expression over siblings.
            return expression_names(rate) if isinstance(rate, str) else frozenset()
        case "window_agg":
            name = spec.params.get("source")
            return frozenset({str(name)}) if name else frozenset()
        case _:
            # `stepped`'s `source` is deliberately absent here: it is a ctx path, not a
            # sibling, so treating it as a dependency would look for a signal called `line`.
            return frozenset()


def order_signals(specs: Sequence[SignalSpec]) -> list[SignalSpec]:
    """Topologically sort `specs` so every signal is evaluated after its inputs.

    Names that no sibling provides are left alone — they may belong to another device, and
    the derived signal will resolve to None. A cycle is a configuration error and raises,
    because there is no evaluation order that could satisfy it.
    """
    by_name = {spec.name: spec for spec in specs}
    pending = {spec.name: set(signal_dependencies(spec) & by_name.keys()) for spec in specs}
    ordered: list[SignalSpec] = []
    while pending:
        ready = [name for spec in specs if (name := spec.name) in pending and not pending[name]]
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise ValueError(f"signal dependency cycle among: {cycle}")
        for name in ready:
            ordered.append(by_name[name])
            del pending[name]
        for remaining in pending.values():
            remaining.difference_update(ready)
    return ordered
```

Add `from collections.abc import Mapping, Sequence` and `from uns_simulator.expressions import ExpressionError, compile_expression` to the imports in `signals.py`.

Why `ready` iterates `specs` rather than `pending`: it preserves declaration order among independent signals, which is what `test_order_signals_is_stable_for_independent_signals` pins. Stable ordering matters because it keeps YAML reading order and evaluation order the same, so a diagnostics dump is readable.

- [ ] **Step 4: Run the whole signals suite**

Run: `uv run pytest test/test_signals.py -v`
Expected: all pass — the shape registry now holds all ten shapes bar none.

- [ ] **Step 5: Add the registry-completeness assertion**

```python
# replace test_registry_holds_the_two_shapes_implemented_so_far in test_signals.py
def test_registry_holds_all_ten_declared_shapes():
    assert set(SIGNAL_SHAPES) == {
        "noise",
        "constant",
        "ou_walk",
        "counter",
        "sawtooth",
        "diurnal",
        "derived",
        "window_agg",
        "stepped",
        "bernoulli_event",
    }
```

- [ ] **Step 6: Run, lint and commit**

```bash
cd 99_simulator && uv run pytest test/test_signals.py -v && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/signals.py 99_simulator/test/test_signals.py
git commit -m "feat(simulator): add derived signals with topological ordering and cycle rejection"
```

---

## Task 7: PackML line state machine

A line that is always "running" produces data no operator recognises. `LineState` gives every line an ISA-88 PackML state with realistic dwell times and a `production_rate` that ramps rather than jumping, which is what every downstream derived signal keys off.

**Files:**
- Create: `99_simulator/src/uns_simulator/plant.py`
- Test: `99_simulator/test/test_plant.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PACKML_STATES: frozenset[str]` — the 17 ISA-88 state names.
  - `EXECUTE_RATE_FLOOR: float = 0.85` — spec §6.1's lower bound for `production_rate` in `EXECUTE`.
  - `@dataclass class LineTiming` with `execute_s: float = 3600.0`, `starting_s: float = 60.0`, `completing_s: float = 30.0`, `resetting_s: float = 20.0`, `holding_s: float = 15.0`, `held_s: float = 300.0`, `unholding_s: float = 30.0`, `hold_probability_per_hour: float = 2.0`, `execute_walk_s: float = 300.0`, `heat_tau_s: float = 600.0`, `air_noise: float = 0.04`.
  - `class LineState` — `__init__(self, name: str, timing: LineTiming, nameplate_tph: float, rng: random.Random)`; attributes `.name`, `.state: str`, `.previous: str | None`, `.time_in_state_s: float`, `.production_rate: float` (0.0–1.0), `.heat_load: float`, `.air_demand: float`, `.transition_count: int`; properties `.throughput_tph: float` and `.running: bool` (true only in `EXECUTE`); method `tick(self, dt: float) -> str | None` (returns the new state name on a transition, else `None`).
  - The four spec §6.1 derived fields, and the reason each is on the line rather than in a signal:
    - `production_rate` — ramps 0→`EXECUTE_RATE_FLOOR` across `STARTING` (and across `UNHOLDING`/`UNSUSPENDING` when returning from a hold), wanders in 0.85–1.0 through `EXECUTE`, ramps down across `COMPLETING`/`HOLDING`/`SUSPENDING`/`STOPPING`/`ABORTING`, and is exactly 0.0 in `IDLE`/`HELD`/`SUSPENDED`/`COMPLETE`/`ABORTED`/`STOPPED`. Each ramp runs over the dwell of the state it happens in, so there is no separate ramp knob to contradict the dwell.
    - `throughput_tph` — `production_rate * nameplate_tph`.
    - `heat_load` — a **first-order lag** behind `production_rate` with time constant `heat_tau_s`: `heat_load += (production_rate - heat_load) * dt / heat_tau_s`. This is the field that makes a cooling tower ΔT narrow over the *following minutes* when a line holds, rather than the same second. Without the lag, the whole utility side would step in lockstep with production and look synthetic at a glance.
    - `air_demand` — `production_rate` plus a fast gaussian component of scale `air_noise`, clamped to 0–1, modelling intermittent actuator draw. Fast where `heat_load` is slow, which is the physical difference between an air header and a water basin.

- [ ] **Step 1: Write the failing tests**

```python
# 99_simulator/test/test_plant.py
import random
import statistics

import pytest

from uns_simulator.plant import EXECUTE_RATE_FLOOR, PACKML_STATES, LineState, LineTiming


def _line(**timing_kwargs):
    return LineState("Line1", LineTiming(**timing_kwargs), nameplate_tph=12.0, rng=random.Random(7))


def test_a_line_starts_idle():
    line = _line()
    assert line.state == "IDLE"
    assert line.production_rate == 0.0
    assert line.running is False


def test_idle_leads_to_execute_through_starting():
    line = _line(starting_s=5.0)
    seen = [line.state]
    for _ in range(20):
        if (new := line.tick(1.0)) is not None:
            seen.append(new)
    assert seen[:3] == ["IDLE", "STARTING", "EXECUTE"]


def test_only_execute_counts_as_running():
    line = _line(starting_s=1.0)
    line.tick(1.0)
    assert line.state == "STARTING"
    assert line.running is False
    line.tick(1.0)
    assert line.state == "EXECUTE"
    assert line.running is True


def test_production_rate_ramps_across_starting_rather_than_stepping():
    """Spec 6.1: STARTING ramps 0 -> 0.85, and it does it over the STARTING dwell."""
    line = _line(starting_s=60.0)
    line.tick(1.0)  # IDLE dwell is starting_s too, so this does not leave IDLE yet
    while line.state == "IDLE":
        line.tick(1.0)
    assert line.state == "STARTING"
    rates = []
    while line.state == "STARTING":
        line.tick(1.0)
        rates.append(line.production_rate)
    assert rates[0] < rates[-1]
    assert rates[-1] == pytest.approx(EXECUTE_RATE_FLOOR, abs=0.02)
    assert all(b - a < 0.05 for a, b in zip(rates, rates[1:], strict=False))  # noqa: PLR2004


def test_execute_holds_the_rate_inside_the_spec_band():
    """Spec 6.1: EXECUTE is 0.85-1.0 — a real line does not sit pinned at nameplate."""
    line = _line(starting_s=2.0, execute_s=10_000.0, hold_probability_per_hour=0.0, execute_walk_s=30.0)
    while line.state != "EXECUTE":
        line.tick(1.0)
    rates = []
    for _ in range(2000):
        line.tick(1.0)
        rates.append(line.production_rate)
    assert all(EXECUTE_RATE_FLOOR <= rate <= 1.0 for rate in rates)
    assert min(rates) < max(rates), "the rate must wander, not sit at one value"
    assert line.throughput_tph == pytest.approx(12.0 * line.production_rate, abs=0.01)


def test_production_rate_is_zero_in_the_fully_stopped_states():
    line = _line()
    for state in ("IDLE", "HELD", "SUSPENDED", "COMPLETE", "ABORTED", "STOPPED"):
        line.state = state
        line.production_rate = 0.9
        line.tick(1.0)
        assert line.production_rate == pytest.approx(0.0), state


def test_completing_ramps_the_rate_down():
    line = _line(starting_s=1.0, execute_s=20.0, completing_s=10.0, hold_probability_per_hour=0.0)
    while line.state != "COMPLETING":
        line.tick(1.0)
    first = line.production_rate
    for _ in range(4):
        line.tick(1.0)
    assert line.production_rate < first


def test_heat_load_lags_production_rate():
    """Spec 6.1: a first-order lag, so cooling responds slowly. This is the whole point."""
    line = _line(starting_s=2.0, execute_s=100_000.0, hold_probability_per_hour=0.0, heat_tau_s=600.0)
    while line.state != "EXECUTE":
        line.tick(1.0)
    for _ in range(60):
        line.tick(1.0)
    assert line.heat_load < line.production_rate / 2, "one minute in, heat has barely built"
    for _ in range(3000):
        line.tick(1.0)
    assert line.heat_load == pytest.approx(line.production_rate, abs=0.05), "and eventually it catches up"


def test_heat_load_decays_slowly_after_a_stop():
    line = _line(heat_tau_s=600.0)
    line.state = "EXECUTE"
    line.heat_load = 1.0
    line.production_rate = 1.0
    line.state = "HELD"
    line.tick(1.0)
    assert line.production_rate == pytest.approx(0.0), "production stops at once"
    assert line.heat_load > 0.99, "heat does not"


def test_air_demand_tracks_production_with_a_fast_noisy_component():
    line = _line(starting_s=2.0, execute_s=100_000.0, hold_probability_per_hour=0.0, air_noise=0.04)
    while line.state != "EXECUTE":
        line.tick(1.0)
    demands, rates = [], []
    for _ in range(300):
        line.tick(1.0)
        demands.append(line.air_demand)
        rates.append(line.production_rate)
    assert all(0.0 <= demand <= 1.0 for demand in demands)
    assert statistics.mean(demands) == pytest.approx(statistics.mean(rates), abs=0.03)
    jitter = statistics.mean(abs(b - a) for a, b in zip(demands, demands[1:], strict=False))
    assert jitter > 0.01, "air demand is noisy tick to tick, unlike heat load"


def test_a_full_cycle_returns_to_idle():
    line = _line(starting_s=2.0, execute_s=10.0, completing_s=2.0, resetting_s=2.0, hold_probability_per_hour=0.0)
    states = []
    for _ in range(60):
        if (new := line.tick(1.0)) is not None:
            states.append(new)
        if states.count("IDLE") == 1:
            break
    assert states == ["STARTING", "EXECUTE", "COMPLETING", "COMPLETE", "RESETTING", "IDLE"]


def test_a_hold_walks_the_full_hold_branch():
    line = _line(starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=3600.0 * 10, holding_s=2.0, held_s=3.0, unholding_s=2.0)
    states = []
    for _ in range(120):
        if (new := line.tick(1.0)) is not None:
            states.append(new)
        if states.count("EXECUTE") == 2:
            break
    assert states[:5] == ["STARTING", "EXECUTE", "HOLDING", "HELD", "UNHOLDING"]
    assert states[5] == "EXECUTE"


def test_every_state_the_machine_can_reach_is_a_packml_state():
    line = _line(starting_s=1.0, execute_s=5.0, completing_s=1.0, resetting_s=1.0, hold_probability_per_hour=60.0)
    for _ in range(5000):
        line.tick(1.0)
        assert line.state in PACKML_STATES


def test_time_in_state_resets_on_transition():
    line = _line(starting_s=3.0)
    line.tick(1.0)
    line.tick(1.0)
    assert line.state == "IDLE"
    assert line.time_in_state_s == pytest.approx(2.0)
    line.tick(1.0)
    assert line.state == "STARTING"
    assert line.time_in_state_s == pytest.approx(0.0)
    line.tick(1.0)
    assert line.time_in_state_s == pytest.approx(1.0)


def test_previous_state_is_recorded():
    line = _line(starting_s=1.0)
    line.tick(1.0)
    assert line.state == "STARTING"
    assert line.previous == "IDLE"


def test_the_same_seed_gives_the_same_state_history():
    def history():
        line = LineState("L", LineTiming(starting_s=2.0, execute_s=30.0, hold_probability_per_hour=120.0), 12.0, random.Random(42))
        return [(line.tick(1.0), line.state, round(line.production_rate, 6)) for _ in range(500)]

    assert history() == history()
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_plant.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_simulator.plant'`.

- [ ] **Step 3: Implement `LineState`**

```python
# 99_simulator/src/uns_simulator/plant.py
"""The simulated world the signals observe.

One PlantClock ticks every second and advances this state; signals read it and never write
it. Keeping the state here rather than inside devices is what makes values correlate — a
chiller and a compressor on the same site see the same ambient temperature and the same
line production rate, so their traces move together the way real ones do.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# Spec 6.1: EXECUTE runs at 0.85-1.0 of nameplate, and every ramp targets the floor.
EXECUTE_RATE_FLOOR = 0.85

# The states production_rate ramps up through, ramps down through, and is flat zero in.
_RAMP_UP_STATES = frozenset({"STARTING", "UNHOLDING", "UNSUSPENDING"})
_RAMP_DOWN_STATES = frozenset({"COMPLETING", "HOLDING", "SUSPENDING", "STOPPING", "ABORTING", "CLEARING"})

PACKML_STATES = frozenset(
    {
        "IDLE",
        "STARTING",
        "EXECUTE",
        "HOLDING",
        "HELD",
        "UNHOLDING",
        "SUSPENDING",
        "SUSPENDED",
        "UNSUSPENDING",
        "COMPLETING",
        "COMPLETE",
        "RESETTING",
        "ABORTING",
        "ABORTED",
        "CLEARING",
        "STOPPING",
        "STOPPED",
    }
)


@dataclass
class LineTiming:
    """How long a line spends in each state, and how often it holds.

    All durations are seconds of simulated time. Defaults describe an hour-long batch with
    a couple of short holds per hour, which is what the profiles in conf/simulator override.

    There is deliberately no separate `ramp_s`: each ramp runs over the dwell of the state it
    happens in, so a ramp time and a dwell time can never disagree.
    """

    execute_s: float = 3600.0
    starting_s: float = 60.0
    completing_s: float = 30.0
    resetting_s: float = 20.0
    holding_s: float = 15.0
    held_s: float = 300.0
    unholding_s: float = 30.0
    hold_probability_per_hour: float = 2.0
    execute_walk_s: float = 300.0
    heat_tau_s: float = 600.0
    air_noise: float = 0.04


class LineState:
    """One production line's PackML state and the four fields spec 6.1 derives from it.

    Every utility signal in the plant ultimately keys off these four, which is why they live
    here: model the ramp, the thermal lag and the actuator jitter once, and a chiller, a
    cooling tower and an air header all inherit them instead of each faking their own.
    """

    def __init__(self, name: str, timing: LineTiming, nameplate_tph: float, rng: random.Random) -> None:
        self.name = name
        self.timing = timing
        self.nameplate_tph = nameplate_tph
        self.rng = rng
        self.state = "IDLE"
        self.previous: str | None = None
        self.time_in_state_s = 0.0
        self.production_rate = 0.0
        self.heat_load = 0.0
        self.air_demand = 0.0
        self.transition_count = 0

    @property
    def running(self) -> bool:
        return self.state == "EXECUTE"

    @property
    def throughput_tph(self) -> float:
        return round(self.nameplate_tph * self.production_rate, 3)

    def tick(self, dt: float) -> str | None:
        """Advance the machine by `dt` seconds. Returns the new state on a transition."""
        self.time_in_state_s += dt
        self._advance_production_rate(dt)
        self._advance_demands(dt)
        target = self._next_state()
        if target is None:
            return None
        self.previous = self.state
        self.state = target
        self.time_in_state_s = 0.0
        self.transition_count += 1
        return target

    def _dwell_of_current_state(self) -> float:
        timing = self.timing
        dwells = {
            "STARTING": timing.starting_s,
            "UNHOLDING": timing.unholding_s,
            "UNSUSPENDING": timing.unholding_s,
            "COMPLETING": timing.completing_s,
            "HOLDING": timing.holding_s,
            "SUSPENDING": timing.holding_s,
            "STOPPING": timing.completing_s,
            "ABORTING": timing.completing_s,
            "CLEARING": timing.resetting_s,
        }
        return max(dwells.get(self.state, 1.0), 1e-6)

    def _advance_production_rate(self, dt: float) -> None:
        if self.state in _RAMP_UP_STATES:
            # Ramp 0 -> EXECUTE_RATE_FLOOR across this state's own dwell.
            step = EXECUTE_RATE_FLOOR * dt / self._dwell_of_current_state()
            self.production_rate = min(EXECUTE_RATE_FLOOR, self.production_rate + step)
        elif self.state in _RAMP_DOWN_STATES:
            step = EXECUTE_RATE_FLOOR * dt / self._dwell_of_current_state()
            self.production_rate = max(0.0, self.production_rate - step)
        elif self.state == "EXECUTE":
            # Wander inside 0.85-1.0 rather than sitting at nameplate: a mean-reverting step
            # towards the middle of the band, then clamped back into it.
            ratio = dt / max(self.timing.execute_walk_s, 1e-6)
            midpoint = (EXECUTE_RATE_FLOOR + 1.0) / 2.0
            drift = (midpoint - self.production_rate) * ratio
            self.production_rate += drift + (1.0 - EXECUTE_RATE_FLOOR) * math.sqrt(ratio) * self.rng.gauss(0.0, 1.0)
            self.production_rate = min(1.0, max(EXECUTE_RATE_FLOOR, self.production_rate))
        else:
            # IDLE, HELD, SUSPENDED, COMPLETE, ABORTED, STOPPED, RESETTING: nothing is made.
            self.production_rate = 0.0

    def _advance_demands(self, dt: float) -> None:
        """heat_load lags production; air_demand tracks it with jitter. Spec 6.1."""
        self.heat_load += (self.production_rate - self.heat_load) * dt / max(self.timing.heat_tau_s, 1e-6)
        self.heat_load = min(1.0, max(0.0, self.heat_load))
        noisy = self.production_rate + self.rng.gauss(0.0, self.timing.air_noise)
        self.air_demand = min(1.0, max(0.0, noisy))

    def _next_state(self) -> str | None:
        elapsed = self.time_in_state_s
        timing = self.timing
        match self.state:
            case "IDLE":
                return "STARTING" if elapsed >= timing.starting_s else None
            case "STARTING":
                return "EXECUTE" if elapsed >= timing.starting_s else None
            case "EXECUTE":
                if elapsed >= timing.execute_s:
                    return "COMPLETING"
                if self.rng.random() < timing.hold_probability_per_hour * elapsed / 3600.0 / max(elapsed, 1.0):
                    return "HOLDING"
                return None
            case "HOLDING":
                return "HELD" if elapsed >= timing.holding_s else None
            case "HELD":
                return "UNHOLDING" if elapsed >= timing.held_s else None
            case "UNHOLDING":
                return "EXECUTE" if elapsed >= timing.unholding_s else None
            case "SUSPENDING":
                return "SUSPENDED" if elapsed >= timing.holding_s else None
            case "SUSPENDED":
                return "UNSUSPENDING" if elapsed >= timing.held_s else None
            case "UNSUSPENDING":
                return "EXECUTE" if elapsed >= timing.unholding_s else None
            case "COMPLETING":
                return "COMPLETE" if elapsed >= timing.completing_s else None
            case "COMPLETE":
                return "RESETTING"
            case "RESETTING":
                return "IDLE" if elapsed >= timing.resetting_s else None
            case "ABORTING":
                return "ABORTED" if elapsed >= timing.completing_s else None
            case "ABORTED":
                return "CLEARING" if elapsed >= timing.held_s else None
            case "CLEARING":
                return "STOPPED" if elapsed >= timing.resetting_s else None
            case "STOPPING":
                return "STOPPED" if elapsed >= timing.completing_s else None
            case "STOPPED":
                return "RESETTING" if elapsed >= timing.held_s else None
            case _:  # pragma: no cover - PACKML_STATES is exhaustive above
                return None
```

Every one of spec §6.1's legal transitions has a case, including the abort and stop branches. Nothing in `_next_state` currently *enters* `ABORTING`, `STOPPING` or `SUSPENDING` — those are driven from outside, by sub-project B's control API and by the `production.yaml` per-transition probabilities. The cases exist now so that when something does enter them, the line walks out again instead of wedging. A state with no exit is the failure mode that looks like "the simulator stopped publishing".

The `EXECUTE` hold check simplifies to a per-second probability of `hold_probability_per_hour / 3600`; write it that way:

```python
            case "EXECUTE":
                if elapsed >= timing.execute_s:
                    return "COMPLETING"
                return "HOLDING" if self.rng.random() < timing.hold_probability_per_hour / 3600.0 else None
```

Use this second form — the first is wrong (it scales with `elapsed`, which makes the hold rate drift over a batch). It is shown only so the mistake is recognisable if it appears in a diff.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_plant.py -v`
Expected: all pass. Two things the timings quietly depend on, worth knowing before you debug a tick count: `IDLE` uses `starting_s` as its own dwell (one knob controls how long a line waits before a batch), and `_advance_production_rate` runs *before* `_next_state` in `tick`, so on the tick that leaves `STARTING` the rate has already reached `EXECUTE_RATE_FLOOR`.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/plant.py 99_simulator/test/test_plant.py
git commit -m "feat(simulator): add PackML line state machine with ramped production rate"
```

---

## Task 8: `SiteState`, `PlantContext`, `serves` aggregation and `DeviceView`

`SiteState` gives every device on a site a shared ambient condition, shift and tariff. `serves` is the mechanism that lets a utility device (a chiller, a compressor, a water meter) see the aggregate demand of the lines it feeds — without it, a utility's kW could not respond to production and the "correlated" claim would be empty.

**Files:**
- Modify: `99_simulator/src/uns_simulator/plant.py`
- Test: `99_simulator/test/test_plant.py`

**Interfaces:**
- Consumes: `LineState`, `LineTiming` from Task 7.
- Produces:
  - `SHIFTS: tuple[str, ...] = ("A", "B", "C")`; `class SiteState` — `__init__(self, name: str, rng: random.Random, *, ambient_mean_c: float = 14.0, ambient_swing_c: float = 8.0, tariff_peak_hours: tuple[int, int] = (8, 20))`; attributes `.name`, `.lines: dict[str, LineState]` keyed by the site-relative line path `"<Area>/<Line>"`, `.ambient_temp_c`, `.ambient_rh_pct`, `.wet_bulb_temp_c`, `.wind_speed_ms`, `.barometric_mbar`, `.shift: str`, `.tariff: str` (`peak`/`offpeak`), `.grid_co2_g_per_kwh: float`, `.sim_time_s: float`; method `tick(self, dt: float) -> list[tuple[str, str]]` returning `(line_path, new_state)` for each line that transitioned.
  - `class PlantContext` — `__init__(self, global_seed: int)`; `.sites: dict[str, SiteState]`; `.sim_time_s: float`; `add_site(name, **kwargs) -> SiteState`; `add_line(site, area, line, timing, nameplate_tph) -> LineState`; `resolve_line(path) -> LineState` taking a fully-qualified `"<Site>/<Area>/<Line>"` and raising `KeyError` if it does not exist; `resolve_serves(paths) -> tuple[LineState, ...]`; `tick(dt) -> list[tuple[str, str, str]]` returning `(site, line_path, new_state)`; `snapshot() -> dict[str, Any]` (the body sub-project B's `GET /simulator/plant` returns).
  - `class DeviceView` — `__init__(self, context: PlantContext, site: str, line: str | None, serves: Sequence[str] = ())` where `line` is a site-relative `"<Area>/<Line>"` path and each `serves` entry is a fully-qualified `"<Site>/<Area>/<Line>"` path; read-only properties `.site`, `.line`, `.serves`, `.ambient_temp_c`, `.ambient_rh_pct`, `.wet_bulb_temp_c`, `.wind_speed_ms`, `.barometric_mbar`, `.shift`, `.tariff`, `.grid_co2_g_per_kwh`, `.state`, `.previous`, `.production_rate`, `.throughput_tph`, `.heat_load`, `.air_demand`, `.time_in_state_s`, `.running`, `.served_production`, `.served_throughput_tph`, `.served_heat_load`, `.served_air_demand`, `.served_line_count`, `.served_running_count`.

`DeviceView` is deliberately the only thing signals see. It exposes no setters, so no signal can write the world it is measuring — the bug class where one device's evaluation silently changes another's inputs is impossible by construction rather than by discipline.

Two naming decisions this task locks in, both taken from spec §6.3, because getting them wrong is invisible until the YAML in Tasks 16–18 quietly reads a missing attribute:

1. **Lines are addressed by path, not by bare name.** Spec §6.3's `serves` entries are fully qualified — `serves: [Dormagen/Production/Line1]` — so `SiteState.lines` is keyed `"<Area>/<Line>"` and `PlantContext` resolves the leading site itself. Keying by bare line name would work until two areas both contain a line called `Line1`, at which point one utility would silently aggregate the wrong one.
2. **The four aggregates are exactly spec §6.3's four**, with its exact names: `served_production` (mean), `served_throughput_tph` (sum), `served_heat_load` (sum), `served_air_demand` (sum). `served_line_count` and `served_running_count` also exist, but only as diagnostics for sub-project B's device table — no signal expression in Tasks 16–18 uses them.

`resolve_serves` raising `KeyError` is what makes spec §6.3's "a `serves` entry naming a path that does not exist is a **load-time error**" true. It holds only because Task 12 builds the whole hierarchy before it builds any device, so every line a device could name already exists by the time its `DeviceView` is constructed. Keep that order.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_plant.py
from uns_simulator.plant import (
    GRID_CO2_MAX_G_PER_KWH,
    GRID_CO2_MIN_G_PER_KWH,
    MAX_WIND_SPEED_MS,
    SHIFTS,
    DeviceView,
    PlantContext,
    SiteState,
)


def _context():
    """Two Dormagen production lines that reach EXECUTE after one tick and never hold."""
    context = PlantContext(global_seed=7)
    context.add_site("Dormagen")
    timing = LineTiming(starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=0.0)
    context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
    context.add_line("Dormagen", "Production", "Line2", timing, 8.0)
    return context


def test_site_ambient_swings_over_a_day():
    site = SiteState("Dormagen", random.Random(7), ambient_mean_c=14.0, ambient_swing_c=8.0)
    temperatures = []
    for _ in range(0, 86_400, 60):
        site.tick(60.0)
        temperatures.append(site.ambient_temp_c)
    assert max(temperatures) > 20.0  # noqa: PLR2004
    assert min(temperatures) < 8.0  # noqa: PLR2004


def test_wet_bulb_is_never_above_dry_bulb():
    site = SiteState("Dormagen", random.Random(7))
    for _ in range(2000):
        site.tick(60.0)
        assert site.wet_bulb_temp_c <= site.ambient_temp_c + 1e-6


def test_humidity_stays_in_range():
    site = SiteState("Dormagen", random.Random(7))
    for _ in range(2000):
        site.tick(60.0)
        assert 10.0 <= site.ambient_rh_pct <= 100.0  # noqa: PLR2004


def test_shift_rotates_every_eight_hours():
    site = SiteState("Dormagen", random.Random(7))
    shifts = []
    for _ in range(24):
        site.tick(3600.0)
        shifts.append(site.shift)
    assert set(shifts) == set(SHIFTS)
    assert shifts[0] == shifts[1]


def test_tariff_is_peak_during_the_day():
    site = SiteState("Dormagen", random.Random(7), tariff_peak_hours=(8, 20))
    site.tick(10.0 * 3600.0)
    assert site.tariff == "peak"
    site.tick(13.0 * 3600.0)
    assert site.tariff == "offpeak"


def test_wind_speed_stays_in_range():
    site = SiteState("Dormagen", random.Random(7))
    speeds = []
    for _ in range(5000):
        site.tick(60.0)
        assert 0.0 <= site.wind_speed_ms <= MAX_WIND_SPEED_MS
        speeds.append(site.wind_speed_ms)
    # It has to actually move, or the stack's plume-direction signals are constant.
    assert max(speeds) - min(speeds) > 1.0


def test_barometric_pressure_stays_near_standard():
    site = SiteState("Dormagen", random.Random(7))
    readings = []
    for _ in range(5000):
        site.tick(60.0)
        readings.append(site.barometric_mbar)
    assert min(readings) > 950.0  # noqa: PLR2004
    assert max(readings) < 1060.0  # noqa: PLR2004
    assert max(readings) - min(readings) > 1.0


def test_grid_carbon_intensity_is_diurnal_with_a_midday_trough():
    """Spec 6.2 calls grid_co2_g_per_kwh diurnal, not a function of the tariff clock.

    Solar pushes it down over the middle of the day, so a plant that shifts load into
    the afternoon shows a lower CarbonRate even at the same kW.
    """
    site = SiteState("Dormagen", random.Random(7))
    by_hour: dict[int, float] = {}
    for _ in range(24):
        site.tick(3600.0)
        by_hour[int((site.sim_time_s / 3600.0) % 24.0)] = site.grid_co2_g_per_kwh
    assert min(by_hour, key=by_hour.__getitem__) in {12, 13, 14}
    assert max(by_hour.values()) - min(by_hour.values()) > 100.0  # noqa: PLR2004
    assert all(GRID_CO2_MIN_G_PER_KWH <= value <= GRID_CO2_MAX_G_PER_KWH for value in by_hour.values())


def test_context_tick_reports_line_transitions_with_their_site_and_path():
    context = _context()
    transitions = []
    for _ in range(10):
        transitions.extend(context.tick(1.0))
    assert ("Dormagen", "Production/Line1", "STARTING") in transitions
    assert ("Dormagen", "Production/Line2", "STARTING") in transitions


def test_context_snapshot_shape():
    context = _context()
    context.tick(1.0)
    snapshot = context.snapshot()
    site = snapshot["Dormagen"]
    assert set(site) >= {
        "ambient_temp_c",
        "ambient_rh_pct",
        "wet_bulb_temp_c",
        "wind_speed_ms",
        "barometric_mbar",
        "shift",
        "tariff",
        "grid_co2_g_per_kwh",
        "lines",
    }
    line = site["lines"]["Production/Line1"]
    assert set(line) >= {"state", "previous", "production_rate", "throughput_tph", "heat_load", "air_demand", "time_in_state_s"}


def test_device_view_reads_its_own_line():
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    view = DeviceView(context, "Dormagen", "Production/Line1")
    assert view.state == "EXECUTE"
    assert view.running is True
    assert view.production_rate == pytest.approx(0.9, abs=0.1)
    assert view.throughput_tph == pytest.approx(view.production_rate * 12.0, abs=0.05)


def test_device_view_without_a_line_still_reads_the_site():
    context = _context()
    context.tick(60.0)
    view = DeviceView(context, "Dormagen", None)
    assert view.line is None
    assert view.state == "N/A"
    assert view.production_rate == 0.0
    assert view.heat_load == 0.0
    assert view.air_demand == 0.0
    assert view.running is False
    assert isinstance(view.ambient_temp_c, float)


def test_serves_aggregates_the_lines_a_utility_feeds():
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    lines = context.sites["Dormagen"].lines
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/Line2"])
    assert view.served_line_count == 2  # noqa: PLR2004
    assert view.served_running_count == 2  # noqa: PLR2004
    assert view.served_production == pytest.approx(0.9, abs=0.1)
    expected_tph = lines["Production/Line1"].throughput_tph + lines["Production/Line2"].throughput_tph
    assert view.served_throughput_tph == pytest.approx(expected_tph, abs=0.01)
    # Each line runs its own seeded walk, so the sum is not the mean times the total nameplate.
    assert 17.0 < view.served_throughput_tph <= 20.0  # noqa: PLR2004


def test_served_heat_load_and_air_demand_are_sums():
    """Spec 6.3: production is a mean, the two demand aggregates are sums."""
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    lines = context.sites["Dormagen"].lines
    lines["Production/Line1"].heat_load = 0.4
    lines["Production/Line2"].heat_load = 0.3
    lines["Production/Line1"].air_demand = 0.6
    lines["Production/Line2"].air_demand = 0.2
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/Line2"])
    assert view.served_heat_load == pytest.approx(0.7)
    assert view.served_air_demand == pytest.approx(0.8)


def test_served_production_is_a_mean_not_a_sum():
    """A utility sized for two lines is at half load when one runs, not at 100%."""
    context = _context()
    for _ in range(20):
        context.tick(1.0)
    lines = context.sites["Dormagen"].lines
    lines["Production/Line1"].production_rate = 1.0
    lines["Production/Line2"].production_rate = 0.0
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/Line2"])
    assert view.served_production == pytest.approx(0.5)


def test_serving_a_path_that_does_not_exist_is_a_load_time_error():
    """Spec 6.3. A typo in `serves` must fail the profile load, not silently halve a chiller's load."""
    context = _context()
    with pytest.raises(KeyError, match="Dormagen/Production/LineNine"):
        DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Dormagen/Production/LineNine"])


def test_serving_a_line_at_another_site_is_allowed():
    """A central utility can feed lines at more than one site, so `serves` is site-qualified."""
    context = _context()
    context.add_site("Krefeld")
    context.add_line("Krefeld", "Production", "Line1", LineTiming(starting_s=1.0, hold_probability_per_hour=0.0), 5.0)
    for _ in range(20):
        context.tick(1.0)
    view = DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1", "Krefeld/Production/Line1"])
    assert view.served_line_count == 2  # noqa: PLR2004
    assert view.served_throughput_tph > 0.0


def test_serves_nothing_yields_zeroes():
    view = DeviceView(_context(), "Dormagen", None)
    assert view.serves == ()
    assert view.served_line_count == 0
    assert view.served_production == 0.0
    assert view.served_throughput_tph == 0.0
    assert view.served_heat_load == 0.0
    assert view.served_air_demand == 0.0


def test_device_view_exposes_no_setter_for_plant_state():
    view = DeviceView(_context(), "Dormagen", "Production/Line1")
    with pytest.raises(AttributeError):
        view.production_rate = 0.5


def test_resolve_line_names_the_path_it_could_not_find():
    context = _context()
    with pytest.raises(KeyError, match="Dormagen/Utilities/Nope"):
        context.resolve_line("Dormagen/Utilities/Nope")


def test_resolve_line_rejects_a_path_that_is_not_three_segments():
    context = _context()
    with pytest.raises(KeyError, match="Site/Area/Line"):
        context.resolve_line("Dormagen/Line1")


def test_adding_a_line_to_an_unknown_site_names_the_site():
    with pytest.raises(KeyError, match="Nowhere"):
        PlantContext(global_seed=7).add_line("Nowhere", "Production", "Line1", LineTiming(), 1.0)
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_plant.py -v`
Expected: FAIL — `ImportError: cannot import name 'SiteState'`.

- [ ] **Step 3: Implement site, context and view**

```python
# append to 99_simulator/src/uns_simulator/plant.py
SHIFTS: tuple[str, ...] = ("A", "B", "C")
SHIFT_LENGTH_S = 8 * 3600.0

# Spec 6.2 calls grid carbon intensity diurnal. These are the extremes of that curve, not
# the two values of a tariff switch - solar drives it down over the middle of the day.
GRID_CO2_MAX_G_PER_KWH = 420.0
GRID_CO2_MIN_G_PER_KWH = 290.0
GRID_CO2_TROUGH_HOUR = 13.0

MAX_WIND_SPEED_MS = 25.0
WIND_MEAN_MS = 4.0
WIND_TAU_S = 1800.0
WIND_SIGMA_MS = 2.5

BAROMETRIC_MEAN_MBAR = 1013.0
BAROMETRIC_TAU_S = 6.0 * 3600.0
BAROMETRIC_SIGMA_MBAR = 12.0
BAROMETRIC_MIN_MBAR = 960.0
BAROMETRIC_MAX_MBAR = 1050.0


class SiteState:
    """Conditions every device at one site shares, plus the lines that site runs.

    `lines` is keyed by the site-relative path `"<Area>/<Line>"`, not by the bare line name,
    so two areas may each contain a `Line1` without one shadowing the other.
    """

    def __init__(
        self,
        name: str,
        rng: random.Random,
        *,
        ambient_mean_c: float = 14.0,
        ambient_swing_c: float = 8.0,
        tariff_peak_hours: tuple[int, int] = (8, 20),
    ) -> None:
        self.name = name
        self.rng = rng
        self.lines: dict[str, LineState] = {}
        self.sim_time_s = 0.0
        self._ambient_mean_c = ambient_mean_c
        self._ambient_swing_c = ambient_swing_c
        self._peak_from, self._peak_to = tariff_peak_hours
        self.ambient_temp_c = ambient_mean_c
        self.ambient_rh_pct = 65.0
        self.wet_bulb_temp_c = ambient_mean_c - 3.0
        self.wind_speed_ms = WIND_MEAN_MS
        self.barometric_mbar = BAROMETRIC_MEAN_MBAR
        self.shift = SHIFTS[0]
        self.tariff = "offpeak"
        self.grid_co2_g_per_kwh = GRID_CO2_MIN_G_PER_KWH

    def tick(self, dt: float) -> list[tuple[str, str]]:
        """Advance ambient conditions, shift and tariff, then every line on this site."""
        self.sim_time_s += dt
        hour_of_day = (self.sim_time_s / 3600.0) % 24.0

        # Coldest around 05:00, warmest around 17:00 - a cosine trough at hour 5.
        angle = 2.0 * math.pi * (hour_of_day - 5.0) / 24.0
        drift = self.rng.gauss(0.0, 0.05)
        self.ambient_temp_c = round(self._ambient_mean_c - self._ambient_swing_c * math.cos(angle) + drift, 2)

        # Humidity moves opposite to temperature: warm air at fixed moisture is drier.
        self.ambient_rh_pct = round(min(100.0, max(10.0, 78.0 - 1.6 * (self.ambient_temp_c - self._ambient_mean_c))), 2)
        self.wet_bulb_temp_c = round(_wet_bulb_c(self.ambient_temp_c, self.ambient_rh_pct), 2)

        # Wind and barometric pressure are mean-reverting walks on very different time
        # constants: wind gusts over half an hour, a weather front takes most of a day.
        self.wind_speed_ms = round(
            _mean_reverting(self.wind_speed_ms, WIND_MEAN_MS, WIND_TAU_S, WIND_SIGMA_MS, dt, self.rng, 0.0, MAX_WIND_SPEED_MS),
            2,
        )
        self.barometric_mbar = round(
            _mean_reverting(
                self.barometric_mbar,
                BAROMETRIC_MEAN_MBAR,
                BAROMETRIC_TAU_S,
                BAROMETRIC_SIGMA_MBAR,
                dt,
                self.rng,
                BAROMETRIC_MIN_MBAR,
                BAROMETRIC_MAX_MBAR,
            ),
            1,
        )

        self.shift = SHIFTS[int(self.sim_time_s // SHIFT_LENGTH_S) % len(SHIFTS)]
        self.tariff = "peak" if self._peak_from <= hour_of_day < self._peak_to else "offpeak"
        # Diurnal, with its trough in the early afternoon. Deliberately *not* derived from
        # `tariff`: the cheapest hour and the cleanest hour are not the same hour, and a
        # simulator that ties them together cannot show the difference.
        co2_mean = (GRID_CO2_MAX_G_PER_KWH + GRID_CO2_MIN_G_PER_KWH) / 2.0
        co2_swing = (GRID_CO2_MAX_G_PER_KWH - GRID_CO2_MIN_G_PER_KWH) / 2.0
        co2_angle = 2.0 * math.pi * (hour_of_day - GRID_CO2_TROUGH_HOUR) / 24.0
        self.grid_co2_g_per_kwh = round(co2_mean - co2_swing * math.cos(co2_angle), 1)

        transitions: list[tuple[str, str]] = []
        for line_path, line in self.lines.items():
            if (new_state := line.tick(dt)) is not None:
                transitions.append((line_path, new_state))
        return transitions

    def snapshot(self) -> dict[str, Any]:
        return {
            "ambient_temp_c": self.ambient_temp_c,
            "ambient_rh_pct": self.ambient_rh_pct,
            "wet_bulb_temp_c": self.wet_bulb_temp_c,
            "wind_speed_ms": self.wind_speed_ms,
            "barometric_mbar": self.barometric_mbar,
            "shift": self.shift,
            "tariff": self.tariff,
            "grid_co2_g_per_kwh": self.grid_co2_g_per_kwh,
            "lines": {
                path: {
                    "state": line.state,
                    "previous": line.previous,
                    "production_rate": round(line.production_rate, 4),
                    "throughput_tph": line.throughput_tph,
                    "heat_load": round(line.heat_load, 4),
                    "air_demand": round(line.air_demand, 4),
                    "time_in_state_s": round(line.time_in_state_s, 1),
                    "transition_count": line.transition_count,
                }
                for path, line in self.lines.items()
            },
        }


def _mean_reverting(  # noqa: PLR0913
    value: float,
    mean: float,
    tau_s: float,
    sigma: float,
    dt: float,
    rng: random.Random,
    low: float,
    high: float,
) -> float:
    """One Ornstein-Uhlenbeck step, clamped. Same walk `OUWalkSignal` uses, on site state.

    `ratio` is capped at 1.0 so a coarse `dt` cannot overshoot the mean and oscillate. The
    clock always ticks at 1 s, but tests fast-forward whole hours and must stay well-behaved.
    """
    ratio = min(1.0, dt / max(tau_s, 1e-6))
    value += (mean - value) * ratio + sigma * math.sqrt(ratio) * rng.gauss(0.0, 1.0)
    return min(high, max(low, value))


def _wet_bulb_c(dry_bulb_c: float, rh_pct: float) -> float:
    """Stull's approximation. Good to about +/-1 K over normal plant conditions, and cheap.

    Cooling-tower and chiller signals are driven by wet bulb rather than dry bulb, because
    that is what actually limits them - so it has to be present, but it does not have to be
    a psychrometric library.
    """
    rh = max(rh_pct, 1.0)
    return (
        dry_bulb_c * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(dry_bulb_c + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


class PlantContext:
    """Every site's state, advanced together by one clock."""

    def __init__(self, global_seed: int) -> None:
        self.global_seed = global_seed
        self.sites: dict[str, SiteState] = {}
        self.sim_time_s = 0.0

    def add_site(self, name: str, **kwargs: Any) -> SiteState:
        site = SiteState(name, random.Random(f"{self.global_seed}:{name}"), **kwargs)
        self.sites[name] = site
        return site

    def add_line(self, site: str, area: str, line: str, timing: LineTiming, nameplate_tph: float) -> LineState:
        if site not in self.sites:
            raise KeyError(f"cannot add line {area}/{line!r}: site {site!r} is not in the plant context")
        path = f"{area}/{line}"
        state = LineState(line, timing, nameplate_tph, random.Random(f"{self.global_seed}:{site}/{path}"))
        self.sites[site].lines[path] = state
        return state

    def resolve_line(self, path: str) -> LineState:
        """Look up a fully-qualified `<Site>/<Area>/<Line>`. Raises `KeyError` if absent."""
        segments = path.split("/")
        if len(segments) != 3:  # noqa: PLR2004
            raise KeyError(f"line path {path!r} must have exactly three segments, Site/Area/Line")
        site_name, area, line = segments
        site = self.sites.get(site_name)
        if site is None:
            raise KeyError(f"line path {path!r} names site {site_name!r}, which is not in the plant context")
        state = site.lines.get(f"{area}/{line}")
        if state is None:
            raise KeyError(f"line path {path!r} does not exist at site {site_name!r}")
        return state

    def resolve_serves(self, paths: Sequence[str]) -> tuple[LineState, ...]:
        """Resolve every `serves` path, or fail. Spec 6.3 makes an unknown path fatal."""
        return tuple(self.resolve_line(path) for path in paths)

    def tick(self, dt: float) -> list[tuple[str, str, str]]:
        self.sim_time_s += dt
        transitions: list[tuple[str, str, str]] = []
        for site_name, site in self.sites.items():
            transitions.extend((site_name, line_path, state) for line_path, state in site.tick(dt))
        return transitions

    def snapshot(self) -> dict[str, Any]:
        return {name: site.snapshot() for name, site in self.sites.items()}


class DeviceView:
    """A device's read-only window onto the plant.

    Signals receive this and nothing else, so a signal cannot mutate the world it measures.
    `serves` names the lines a utility device feeds, as fully-qualified `<Site>/<Area>/<Line>`
    paths; the served_* properties aggregate them, which is how a chiller's load follows the
    production it is actually cooling. `line` is a site-relative `<Area>/<Line>` path, or
    `None` for a device that is not attached to a production line at all.
    """

    __slots__ = ("_context", "_line", "_served", "_serves", "_site")

    def __init__(self, context: PlantContext, site: str, line: str | None, serves: Sequence[str] = ()) -> None:
        self._context = context
        self._site = site
        self._line = line
        self._serves = tuple(serves)
        # Resolved once, here, so spec 6.3's "an unknown `serves` path is a load-time error"
        # holds: this constructor runs during the profile load. Holding the LineState objects
        # rather than their names also drops a dict lookup out of every signal evaluation.
        self._served = context.resolve_serves(self._serves)

    @property
    def site(self) -> str:
        return self._site

    @property
    def line(self) -> str | None:
        return self._line

    @property
    def serves(self) -> tuple[str, ...]:
        """The declared paths, for sub-project B's `GET /simulator/config` to echo back."""
        return self._serves

    @property
    def _site_state(self) -> SiteState:
        return self._context.sites[self._site]

    @property
    def _line_state(self) -> LineState | None:
        if self._line is None:
            return None
        return self._site_state.lines.get(self._line)

    @property
    def ambient_temp_c(self) -> float:
        return self._site_state.ambient_temp_c

    @property
    def ambient_rh_pct(self) -> float:
        return self._site_state.ambient_rh_pct

    @property
    def wet_bulb_temp_c(self) -> float:
        return self._site_state.wet_bulb_temp_c

    @property
    def wind_speed_ms(self) -> float:
        return self._site_state.wind_speed_ms

    @property
    def barometric_mbar(self) -> float:
        return self._site_state.barometric_mbar

    @property
    def shift(self) -> str:
        return self._site_state.shift

    @property
    def tariff(self) -> str:
        return self._site_state.tariff

    @property
    def grid_co2_g_per_kwh(self) -> float:
        return self._site_state.grid_co2_g_per_kwh

    @property
    def state(self) -> str:
        line = self._line_state
        return line.state if line is not None else "N/A"

    @property
    def previous(self) -> str | None:
        line = self._line_state
        return line.previous if line is not None else None

    @property
    def production_rate(self) -> float:
        line = self._line_state
        return line.production_rate if line is not None else 0.0

    @property
    def throughput_tph(self) -> float:
        line = self._line_state
        return line.throughput_tph if line is not None else 0.0

    @property
    def heat_load(self) -> float:
        line = self._line_state
        return line.heat_load if line is not None else 0.0

    @property
    def air_demand(self) -> float:
        line = self._line_state
        return line.air_demand if line is not None else 0.0

    @property
    def time_in_state_s(self) -> float:
        line = self._line_state
        return line.time_in_state_s if line is not None else 0.0

    @property
    def running(self) -> bool:
        line = self._line_state
        return line.running if line is not None else False

    @property
    def served_line_count(self) -> int:
        return len(self._served)

    @property
    def served_running_count(self) -> int:
        return sum(1 for line in self._served if line.running)

    @property
    def served_production(self) -> float:
        """Mean, not sum: a utility sized for its served lines is at half load when half run."""
        if not self._served:
            return 0.0
        return round(sum(line.production_rate for line in self._served) / len(self._served), 4)

    @property
    def served_throughput_tph(self) -> float:
        """Sum: tonnes per hour through a shared meter is the total, not the average."""
        return round(sum(line.throughput_tph for line in self._served), 3)

    @property
    def served_heat_load(self) -> float:
        """Sum: a cooling tower rejects every served line's heat, not their average."""
        return round(sum(line.heat_load for line in self._served), 4)

    @property
    def served_air_demand(self) -> float:
        """Sum: a compressor house supplies every served line's draw, not their average."""
        return round(sum(line.air_demand for line in self._served), 4)
```

Add `import math` and `from collections.abc import Sequence` and `from typing import Any` to `plant.py`'s imports. Remove the unused `field` import from Task 7 if ruff flags it.

Why `served_production` is a mean while the other three are sums, since it is the one asymmetry in the block and a reader will assume it is a mistake: `served_production` is a 0–1 *utilisation*, so a compressor feeding two lines with one running is at 50%, and averaging is the only answer that keeps `base_load + ctx.served_production * connected_kw` inside its declared `range`. The other three are physical quantities being drawn from one place at once, and adding them is what makes a second line coming up raise the demand.

`DeviceView.__slots__` is what makes `test_device_view_exposes_no_setter_for_plant_state` pass: assigning to a property with no setter raises `AttributeError`, and `__slots__` stops anyone adding a shadowing instance attribute.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_plant.py -v`
Expected: all pass. If `test_shift_rotates_every_eight_hours` fails on `shifts[0] == shifts[1]`, the shift index is being computed from something other than `sim_time_s // SHIFT_LENGTH_S`.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/plant.py 99_simulator/test/test_plant.py
git commit -m "feat(simulator): add site state, plant context, serves aggregation and read-only device views"
```

---

## Task 9: `PlantClock` — one 1 s tick for the whole plant

The clock is the piece that makes cadence tiers safe. Because every signal advances on the same 1 s tick regardless of publish interval, a 900 s water meter and a 1 s vibration sample observe one coherent world, counters integrate correctly, and derived signals never read a stale sibling. Devices publish *snapshots* of an already-advanced world; they never advance it.

**Files:**
- Modify: `99_simulator/src/uns_simulator/plant.py`
- Test: `99_simulator/test/test_plant.py`

**Interfaces:**
- Consumes: `PlantContext` from Task 8.
- Produces: `class PlantClock` — `__init__(self, context: PlantContext, tick_s: float = 1.0)`; attributes `.context`, `.tick_s`, `.tick_count: int`, `.running: bool`; methods `advance(self, dt: float | None = None) -> list[tuple[str, str, str]]` (synchronous, for tests and for a single deterministic step), `async run(self) -> None` (the task the simulator schedules; sleeps `tick_s` between advances), `stop(self) -> None`, and `on_transition(self, callback: Callable[[str, str, str], None]) -> None` (sub-project B's plant-state telemetry hooks here — registered now so B needs no change to this file).

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_plant.py
import asyncio

from uns_simulator.plant import PlantClock


def test_advance_moves_the_context_by_one_tick():
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    clock.advance()
    assert context.sim_time_s == pytest.approx(1.0)
    assert clock.tick_count == 1


def test_advance_accepts_an_explicit_dt():
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    clock.advance(60.0)
    assert context.sim_time_s == pytest.approx(60.0)


def test_advance_returns_transitions_and_notifies_callbacks():
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    seen: list[tuple[str, str, str]] = []
    clock.on_transition(lambda site, line, state: seen.append((site, line, state)))
    transitions: list[tuple[str, str, str]] = []
    for _ in range(5):
        transitions.extend(clock.advance())
    assert transitions
    assert seen == transitions


def test_a_failing_callback_does_not_stop_the_clock():
    """Self-telemetry publishing must never be able to freeze the simulated world."""
    context = _context()
    clock = PlantClock(context, tick_s=1.0)
    calls: list[str] = []

    def explode(site, line, state):  # noqa: ARG001
        calls.append("boom")
        raise RuntimeError("broker down")

    clock.on_transition(explode)
    for _ in range(5):
        clock.advance()
    assert calls
    assert clock.tick_count == 5  # noqa: PLR2004


@pytest.mark.asyncio
async def test_run_ticks_until_stopped():
    context = _context()
    clock = PlantClock(context, tick_s=0.01)
    task = asyncio.create_task(clock.run())
    await asyncio.sleep(0.1)
    clock.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert clock.tick_count >= 5  # noqa: PLR2004
    assert clock.running is False


@pytest.mark.asyncio
async def test_run_can_be_cancelled():
    clock = PlantClock(_context(), tick_s=0.01)
    task = asyncio.create_task(clock.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_same_seed_gives_the_same_plant_history():
    def history():
        context = PlantContext(global_seed=99)
        context.add_site("Dormagen")
        timing = LineTiming(starting_s=2.0, execute_s=30.0, hold_probability_per_hour=120.0)
        context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
        clock = PlantClock(context, tick_s=1.0)
        line = context.sites["Dormagen"].lines["Production/Line1"]
        return [(line.state, clock.advance() and None) for _ in range(400)]

    assert history() == history()
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_plant.py -k clock -v`
Expected: FAIL — `ImportError: cannot import name 'PlantClock'`.

- [ ] **Step 3: Implement the clock**

```python
# append to 99_simulator/src/uns_simulator/plant.py
class PlantClock:
    """Advances the whole plant on a fixed tick.

    Every signal is evaluated on this tick, whatever its publish cadence. That is what lets
    a 1 s vibration sample and a 900 s water meter reading describe the same world, and what
    lets counters integrate correctly no matter how rarely their device publishes.
    """

    def __init__(self, context: PlantContext, tick_s: float = 1.0) -> None:
        self.context = context
        self.tick_s = tick_s
        self.tick_count = 0
        self.running = False
        self._callbacks: list[Callable[[str, str, str], None]] = []

    def on_transition(self, callback: Callable[[str, str, str], None]) -> None:
        """Register a listener for (site, line, new_state). Exceptions in it are swallowed."""
        self._callbacks.append(callback)

    def advance(self, dt: float | None = None) -> list[tuple[str, str, str]]:
        """Advance one tick synchronously and return the line transitions it produced."""
        transitions = self.context.tick(self.tick_s if dt is None else dt)
        self.tick_count += 1
        for site, line, state in transitions:
            for callback in self._callbacks:
                try:
                    callback(site, line, state)
                except Exception:
                    LOGGER.exception("plant transition callback failed for %s/%s -> %s", site, line, state)
        return transitions

    async def run(self) -> None:
        """Tick until `stop()` is called or the task is cancelled."""
        self.running = True
        try:
            while self.running:
                self.advance()
                await asyncio.sleep(self.tick_s)
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False
```

Add to `plant.py`'s imports:

```python
import asyncio
import logging
from collections.abc import Callable, Sequence

LOGGER = logging.getLogger(__name__)
```

`LOGGER.exception` inside the callback loop is why `test_a_failing_callback_does_not_stop_the_clock` passes. Broad `except Exception` is correct here and only here: the callback is sub-project B's MQTT publish, and a broker outage must not freeze the simulated world. Ruff's `BLE001` is not in the selected rule set, so no suppression comment is needed.

- [ ] **Step 4: Run the whole plant suite**

Run: `uv run pytest test/test_plant.py -v`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/plant.py 99_simulator/test/test_plant.py
git commit -m "feat(simulator): add PlantClock driving all signal evaluation on a fixed 1s tick"
```

---

## Task 10: Area `kind` and line `nameplate_tph` in the hierarchy

Device targeting needs to distinguish a production area from a utility area — a compressor house is not a filling line, and `target: {kind: utility}` is how a profile says so. `nameplate_tph` gives `LineState.throughput_tph` a real number instead of a guess.

**Files:**
- Modify: `99_simulator/src/uns_simulator/models.py`
- Test: `99_simulator/test/test_hierarchy.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AREA_KINDS: frozenset[str] = frozenset({"production", "utilities"})`. `ISA95Hierarchy` gains `kind: str = "production"` and `nameplate_tph: float = 0.0` as trailing keyword-defaulted parameters, so every existing positional call site — including `test_hierarchy.py`'s `ISA95Hierarchy("E", "Dormagen", "Production", "Line1", "Cell1")` — keeps working unchanged. `expand_hierarchy_paths` reads `kind` from the area node (defaulting to `"production"`) and `nameplate_tph` from the line node (defaulting to `0.0`), and raises `ValueError` on a `kind` outside `AREA_KINDS`.

The two spellings are spec §7.2's: **`production` and `utilities`** — plural on the second one. They are validated rather than free text because of spec §7.3's compatibility rule: a template with no `target` matches `kind: production` cells only, so a typo like `kind: utilites` would silently turn a compressor house into a production area and every legacy `simulator.plc` template would start publishing into it.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_hierarchy.py
def test_area_kind_and_nameplate_flow_through_expansion():
    paths = expand_hierarchy_paths(
        {
            "enterprise": "CovestroAG",
            "sites": [
                {
                    "name": "Dormagen",
                    "areas": [
                        {
                            "name": "Production",
                            "kind": "production",
                            "lines": [{"name": "Line1", "nameplate_tph": 12.5, "cells": ["Cell1"]}],
                        },
                        {
                            "name": "Utilities",
                            "kind": "utilities",
                            "lines": [{"name": "Powerhouse", "cells": ["Cell1"]}],
                        },
                    ],
                }
            ],
        }
    )
    by_area = {path.area: path for path in paths}
    assert by_area["Production"].kind == "production"
    assert by_area["Production"].nameplate_tph == 12.5  # noqa: PLR2004
    assert by_area["Utilities"].kind == "utilities"
    assert by_area["Utilities"].nameplate_tph == 0.0


def test_kind_defaults_to_production_when_absent():
    paths = expand_hierarchy_paths(
        {
            "enterprise": "E",
            "sites": [{"name": "S", "areas": [{"name": "A", "lines": [{"name": "L", "cells": ["C"]}]}]}],
        }
    )
    assert paths[0].kind == "production"
    assert paths[0].nameplate_tph == 0.0


def test_an_unknown_area_kind_is_rejected_by_name():
    """A typo must not silently become a production area that legacy templates target."""
    with pytest.raises(ValueError, match="utilites"):
        expand_hierarchy_paths(
            {
                "enterprise": "E",
                "sites": [
                    {
                        "name": "S",
                        "areas": [{"name": "A", "kind": "utilites", "lines": [{"name": "L", "cells": ["C"]}]}],
                    }
                ],
            }
        )


def test_area_kinds_are_exactly_the_two_the_spec_names():
    assert AREA_KINDS == frozenset({"production", "utilities"})


def test_positional_construction_is_unchanged():
    """Existing call sites pass five positional args; they must keep working."""
    path = ISA95Hierarchy("E", "S", "A", "L", "C")
    assert path.kind == "production"
    assert path.nameplate_tph == 0.0
```

`AREA_KINDS` and `pytest` need importing at the top of `test_hierarchy.py` if they are not there already.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_hierarchy.py -v`
Expected: FAIL — `AttributeError: 'ISA95Hierarchy' object has no attribute 'kind'`.

- [ ] **Step 3: Modify `models.py`**

Add the constant near the top of `models.py`:

```python
# Spec 7.2's two area kinds. `utilities` is plural; `production` is the default because
# spec 7.3 makes an untargeted template match production cells only.
AREA_KINDS: frozenset[str] = frozenset({"production", "utilities"})
```

Extend `ISA95Hierarchy.__init__` with the two trailing parameters and store them:

```python
    def __init__(
        self,
        enterprise: str,
        site: str,
        area: str,
        line: str,
        cell: str,
        kind: str = "production",
        nameplate_tph: float = 0.0,
    ) -> None:
        self.enterprise = enterprise
        self.site = site
        self.area = area
        self.line = line
        self.cell = cell
        self.kind = kind
        self.nameplate_tph = nameplate_tph
```

Keep the existing body of `get_parameter_topic` untouched. In `expand_hierarchy_paths`, the nested branch currently reads (`models.py:87-105`):

```python
            for area in site.get("areas") or []:
                area_name = _node_name(area)
                for line in area.get("lines") or []:
                    line_name = _node_name(line)
```

Read the two new values just after each `_node_name` call and pass them into the existing keyword-argument construction:

```python
            for area in site.get("areas") or []:
                area_name = _node_name(area)
                area_kind = str(area.get("kind", "production")) if hasattr(area, "get") else "production"
                if area_kind not in AREA_KINDS:
                    raise ValueError(
                        f"Area {site_name}/{area_name} has kind {area_kind!r}; "
                        f"expected one of {sorted(AREA_KINDS)}"
                    )
                for line in area.get("lines") or []:
                    line_name = _node_name(line)
                    nameplate_tph = float(line.get("nameplate_tph", 0.0)) if hasattr(line, "get") else 0.0
                    cells = line.get("cells") or []
                    if not cells:
                        raise ValueError(
                            f"Line {site_name}/{area_name}/{line_name} has no cells"
                        )
                    for cell in cells:
                        paths.append(
                            ISA95Hierarchy(
                                enterprise=str(enterprise),
                                site=site_name,
                                area=area_name,
                                line=line_name,
                                cell=_node_name(cell),
                                kind=area_kind,
                                nameplate_tph=nameplate_tph,
                            )
                        )
```

`hasattr(x, "get")` rather than `isinstance(x, dict)` matches the existing style in `_node_name` and keeps Dynaconf's mapping types working. The legacy flat branch at `models.py:110-118` is left untouched, so it keeps the defaults.

- [ ] **Step 4: Run the hierarchy tests, then the whole suite**

Run: `uv run pytest test/test_hierarchy.py -v && uv run pytest -v`
Expected: all pass, including the pre-existing `test_create_plc_spawns_one_device_per_cell_and_template` (`len(plcs) == 4`) and `test_expand_flat_hierarchy_still_works`.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/models.py 99_simulator/test/test_hierarchy.py
git commit -m "feat(simulator): carry area kind and line nameplate through hierarchy expansion"
```

---

## Task 11: Device targeting — `matches_target` and template expansion

Today `create_plc` is a cartesian product: every PLC template lands on every cell. That is why the simulator cannot have a compressor in the utility area and a filler on the line — there is no way to say where a device belongs. `target` selectors fix that, and this task is where the ~50-device inventory becomes expressible.

**Files:**
- Create: `99_simulator/src/uns_simulator/profiles.py`
- Test: `99_simulator/test/test_targeting.py`

**Interfaces:**
- Consumes: `ISA95Hierarchy` (Task 10), `SignalSpec`/`spec_from_config`/`order_signals` (Tasks 2 and 6).
- Produces:
  - `matches_target(path: ISA95Hierarchy, target: Mapping[str, Any] | None) -> bool`. Semantics, fixed here: `None` means "production areas only" (`path.kind == "production"`), because that is what today's templates implicitly mean and it keeps existing YAML behaving. Otherwise every key present must match; keys absent are wildcards. Recognised keys are `site`, `area`, `line`, `cell`, `kind`, each taking a string or a list of strings. An unrecognised key raises `ValueError` naming it — a silently-ignored typo in a selector would produce a device inventory nobody can explain.
  - `@dataclass(frozen=True) class DeviceSpec` with `id: str`, `equipment: str`, `family: str`, `tier: str`, `path: ISA95Hierarchy`, `signals: tuple[SignalSpec, ...]`, `serves: tuple[str, ...]`, `enabled: bool = True`; property `topic_prefix: str` returning `Enterprise/Site/Area/Line/Cell/Equipment`.
  - `expand_template(template: Mapping[str, Any], paths: Sequence[ISA95Hierarchy], family: str) -> list[DeviceSpec]`.

- [ ] **Step 1: Write the failing tests**

```python
# 99_simulator/test/test_targeting.py
import pytest

from uns_simulator.models import ISA95Hierarchy
from uns_simulator.profiles import DeviceSpec, expand_template, matches_target

PRODUCTION = ISA95Hierarchy("CovestroAG", "Dormagen", "Production", "Line1", "Cell1", nameplate_tph=12.0)
PRODUCTION_2 = ISA95Hierarchy("CovestroAG", "Dormagen", "Production", "Line2", "Cell1", nameplate_tph=8.0)
UTILITY = ISA95Hierarchy("CovestroAG", "Dormagen", "Utilities", "Powerhouse", "Cell1", kind="utilities")
KREFELD = ISA95Hierarchy("CovestroAG", "Krefeld", "Production", "Line1", "Cell1", kind="production")
ALL_PATHS = [PRODUCTION, PRODUCTION_2, UTILITY, KREFELD]


def test_no_target_means_production_areas_only():
    assert matches_target(PRODUCTION, None) is True
    assert matches_target(UTILITY, None) is False


def test_kind_selector():
    assert matches_target(UTILITY, {"kind": "utilities"}) is True
    assert matches_target(PRODUCTION, {"kind": "utilities"}) is False


def test_every_present_key_must_match():
    assert matches_target(PRODUCTION, {"site": "Dormagen", "line": "Line1"}) is True
    assert matches_target(PRODUCTION, {"site": "Dormagen", "line": "Line2"}) is False


def test_absent_keys_are_wildcards():
    assert matches_target(PRODUCTION, {"site": "Dormagen"}) is True
    assert matches_target(PRODUCTION_2, {"site": "Dormagen"}) is True


def test_a_list_selector_matches_any_member():
    assert matches_target(PRODUCTION, {"line": ["Line1", "Line3"]}) is True
    assert matches_target(PRODUCTION_2, {"line": ["Line1", "Line3"]}) is False


def test_an_empty_target_matches_everything_including_utilities():
    assert matches_target(UTILITY, {}) is True
    assert matches_target(PRODUCTION, {}) is True


def test_unknown_selector_key_is_rejected_by_name():
    with pytest.raises(ValueError, match="celll"):
        matches_target(PRODUCTION, {"celll": "Cell1"})


def test_expand_template_creates_one_device_per_matching_path():
    devices = expand_template(
        {
            "id": "PWR",
            "equipment": "MainIncomer",
            "target": {"kind": "utilities"},
            "tier": "energy",
            "signals": {"ActivePower": {"shape": "ou_walk", "unit": "kW", "mean": 400.0, "sigma": 20.0, "tau": 120.0}},
        },
        ALL_PATHS,
        family="energy",
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.path is UTILITY
    assert device.family == "energy"
    assert device.tier == "energy"
    assert device.topic_prefix == "CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainIncomer"


def test_device_ids_are_unique_and_carry_their_location():
    devices = expand_template(
        {"id": "FLOW", "equipment": "Flowmeter", "signals": {}},
        ALL_PATHS,
        family="water",
    )
    ids = [device.id for device in devices]
    assert len(ids) == len(set(ids))
    assert all("Dormagen" in i or "Krefeld" in i for i in ids)


def test_signal_tier_defaults_to_the_device_tier():
    devices = expand_template(
        {"id": "X", "equipment": "E", "tier": "meter", "signals": {"Total": {"shape": "counter", "unit": "m3"}}},
        [PRODUCTION],
        family="water",
    )
    assert devices[0].signals[0].tier == "meter"


def test_a_signal_may_override_the_device_tier():
    devices = expand_template(
        {
            "id": "X",
            "equipment": "E",
            "tier": "meter",
            "signals": {
                "Total": {"shape": "counter", "unit": "m3"},
                "Flow": {"shape": "ou_walk", "unit": "m3/h", "tier": "fast"},
            },
        },
        [PRODUCTION],
        family="water",
    )
    by_name = {spec.name: spec for spec in devices[0].signals}
    assert by_name["Total"].tier == "meter"
    assert by_name["Flow"].tier == "fast"


def test_signals_come_back_in_dependency_order():
    """Written the way spec 7.3 writes it: `rate` flat, naming a sibling signal."""
    devices = expand_template(
        {
            "id": "X",
            "equipment": "E",
            "signals": {
                "EnergyTotal": {"shape": "counter", "unit": "kWh", "rate": "ActivePower / 3600.0"},
                "ActivePower": {"shape": "ou_walk", "unit": "kW", "mean": 10.0},
            },
        },
        [PRODUCTION],
        family="energy",
    )
    assert [spec.name for spec in devices[0].signals] == ["ActivePower", "EnergyTotal"]


def test_serves_is_carried_onto_the_device():
    """Spec 6.3's `serves` entries are fully qualified Site/Area/Line paths."""
    devices = expand_template(
        {
            "id": "CH",
            "equipment": "Chiller",
            "target": {"kind": "utilities"},
            "serves": ["Dormagen/Production/Line1", "Dormagen/Production/Line2"],
            "signals": {},
        },
        ALL_PATHS,
        family="utilities",
    )
    assert devices[0].serves == ("Dormagen/Production/Line1", "Dormagen/Production/Line2")


def test_a_template_matching_nothing_returns_an_empty_list():
    assert expand_template({"id": "X", "equipment": "E", "target": {"site": "Nowhere"}, "signals": {}}, ALL_PATHS, "energy") == []


def test_a_template_without_an_id_or_equipment_is_rejected():
    with pytest.raises(ValueError, match="equipment"):
        expand_template({"id": "X", "signals": {}}, ALL_PATHS, "energy")
    with pytest.raises(ValueError, match="id"):
        expand_template({"equipment": "E", "signals": {}}, ALL_PATHS, "energy")


def test_a_cycle_inside_a_template_is_rejected_with_the_device_named():
    with pytest.raises(ValueError, match="BAD"):
        expand_template(
            {
                "id": "BAD",
                "equipment": "E",
                "signals": {
                    "a": {"shape": "derived", "unit": "1", "expr": "b"},
                    "b": {"shape": "derived", "unit": "1", "expr": "a"},
                },
            },
            [PRODUCTION],
            family="energy",
        )


def test_a_signal_without_a_unit_is_rejected_naming_the_signal():
    """Spec 11 and 14: `unit` is required, and this is the only place to catch its absence."""
    with pytest.raises(ValueError, match="Pressure"):
        expand_template(
            {"id": "X", "equipment": "E", "signals": {"Pressure": {"base_value": 4.0}}},
            [PRODUCTION],
            family="energy",
        )


def test_an_empty_unit_is_rejected_too():
    """`unit: ""` is the same omission with extra steps; dimensionless ratios use "1"."""
    with pytest.raises(ValueError, match="Ratio"):
        expand_template(
            {"id": "X", "equipment": "E", "signals": {"Ratio": {"shape": "constant", "unit": "", "value": 1.0}}},
            [PRODUCTION],
            family="energy",
        )
    expand_template(
        {"id": "X", "equipment": "E", "signals": {"Ratio": {"shape": "constant", "unit": "1", "value": 1.0}}},
        [PRODUCTION],
        family="energy",
    )
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_targeting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uns_simulator.profiles'`.

- [ ] **Step 3: Implement targeting and expansion**

```python
# 99_simulator/src/uns_simulator/profiles.py
"""Turn conf/simulator/*.yaml into DeviceSpec objects.

A device template says what a device is and, through `target`, where it belongs. Without
`target` the simulator could only do a cartesian product of templates and cells, which is
why it could never have had a compressor house and a filling line at the same time.

Every failure in this module names the offending key. A profile that silently produces the
wrong device inventory is far more expensive to debug than one that refuses to load.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from uns_simulator.models import ISA95Hierarchy
from uns_simulator.signals import SignalSpec, order_signals, spec_from_config

LOGGER = logging.getLogger(__name__)

TARGET_KEYS = frozenset({"site", "area", "line", "cell", "kind"})


@dataclass(frozen=True)
class DeviceSpec:
    """One resolved device: a location, a signal set, and the lines it serves."""

    id: str
    equipment: str
    family: str
    tier: str
    path: ISA95Hierarchy
    signals: tuple[SignalSpec, ...]
    serves: tuple[str, ...] = ()
    enabled: bool = True

    @property
    def topic_prefix(self) -> str:
        return "/".join(
            (self.path.enterprise, self.path.site, self.path.area, self.path.line, self.path.cell, self.equipment)
        )


def matches_target(path: ISA95Hierarchy, target: Mapping[str, Any] | None) -> bool:
    """Does `path` satisfy `target`?

    `None` means production areas only - the implicit meaning of today's templates, kept so
    existing configuration behaves the same. `{}` means everywhere, utilities included.
    Every key present must match; a key absent is a wildcard. Values may be a string or a
    list of strings.
    """
    if target is None:
        return path.kind == "production"
    if unknown := set(target) - TARGET_KEYS:
        allowed = ", ".join(sorted(TARGET_KEYS))
        raise ValueError(f"unknown target selector(s): {', '.join(sorted(unknown))} (allowed: {allowed})")
    for key, wanted in target.items():
        actual = getattr(path, key)
        allowed_values = wanted if isinstance(wanted, list | tuple | set) else [wanted]
        if actual not in allowed_values:
            return False
    return True


def expand_template(template: Mapping[str, Any], paths: Sequence[ISA95Hierarchy], family: str) -> list[DeviceSpec]:
    """Create one DeviceSpec per hierarchy path the template's `target` matches."""
    device_id = template.get("id")
    equipment = template.get("equipment")
    if not device_id:
        raise ValueError(f"device template in family {family!r} is missing 'id'")
    if not equipment:
        raise ValueError(f"device template {device_id!r} in family {family!r} is missing 'equipment'")

    tier = str(template.get("tier", "process"))
    serves = tuple(str(name) for name in template.get("serves") or ())
    raw_signals: Mapping[str, Any] = template.get("signals") or {}

    specs = []
    for name, raw in raw_signals.items():
        raw = raw or {}
        # Spec 11 and 14: `unit` is required on every signal, and this is the only place
        # it can be caught. An absent Unit of Measure is not a cosmetic omission - the
        # frontend and Metric Definitions key off it, and a signal published without one
        # is indistinguishable from a signal whose unit was simply forgotten. Dimensionless
        # ratios declare `unit: "1"` rather than omitting the key, so the omission stays
        # unambiguous.
        if "unit" not in raw or str(raw["unit"]).strip() == "":
            raise ValueError(
                f"device template {device_id!r} signal {name!r}: 'unit' is required "
                f"(use \"1\" for a dimensionless ratio)"
            )
        specs.append(spec_from_config(name, {"tier": tier, **raw}))
    try:
        ordered = tuple(order_signals(specs))
    except ValueError as exc:
        raise ValueError(f"device template {device_id!r}: {exc}") from exc

    devices: list[DeviceSpec] = []
    for path in paths:
        if not matches_target(path, template.get("target")):
            continue
        devices.append(
            DeviceSpec(
                id=f"{device_id}@{path.site}.{path.area}.{path.line}.{path.cell}",
                equipment=str(equipment),
                family=family,
                tier=tier,
                path=path,
                signals=ordered,
                serves=serves,
                enabled=bool(template.get("enabled", True)),
            )
        )
    if not devices:
        LOGGER.warning("device template %s (family %s) matched no hierarchy path", device_id, family)
    return devices
```

Note on `spec_from_config(name, {"tier": tier, **(raw or {})})`: the device tier goes in first so a per-signal `tier` in the YAML overrides it. That ordering is what `test_a_signal_may_override_the_device_tier` pins — reversing it would silently force every signal onto the device tier.

`serves` is carried through as opaque strings here and **not** validated. It cannot be: this function sees hierarchy paths but not the `PlantContext`, and spec §6.3's load-time check needs the context. Task 12 builds the context first and then constructs each device's `DeviceView`, whose `resolve_serves` is where a bad path fails.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_targeting.py -v`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/profiles.py 99_simulator/test/test_targeting.py
git commit -m "feat(simulator): add target selectors and device template expansion"
```

---

## Task 12: Profile loading and validation

The loader is the only place a configuration mistake can be caught before it becomes wrong data. It reads the family files, applies the profile's `sites` / `families` / `max_cells_per_line` / `tier_scale` keys, builds the `PlantContext` from the same narrowed hierarchy the devices use, resolves every `serves` path against it, and produces a diagnostics report — the report is what sub-project B's `GET /simulator/diagnostics` renders, so it is built here rather than bolted on later.

**Files:**
- Modify: `99_simulator/src/uns_simulator/profiles.py`
- Test: `99_simulator/test/test_profiles.py`

**Interfaces:**
- Consumes: Task 11's `DeviceSpec`/`expand_template`; `PlantContext`/`LineTiming` (Tasks 7–9); `expand_hierarchy_paths` (Task 10).
- Produces:
  - `TIER_DEFAULTS: dict[str, float]` = `{"fast": 1.0, "process": 5.0, "energy": 15.0, "status": 30.0, "meter": 900.0, "lab": 1800.0, "event": 0.0}`. `event` is 0.0 meaning "publish only when the value changes".
  - `FAMILIES: tuple[str, ...]` = `("energy", "water", "utilities", "asset_health", "production", "safety")` — spec §7.2's list, in its order.
  - `@dataclass class LoadReport` with `devices: int`, `signals: int`, `per_family: dict[str, int]`, `per_tier: dict[str, int]`, `serves_links: int`, `unmatched_templates: list[str]`, `warnings: list[str]`; method `as_dict() -> dict[str, Any]`.
  - `@dataclass class LoadedProfile` with `name: str`, `seed: int`, `tier_scale: float`, `tiers: dict[str, float]` (already multiplied by `tier_scale`), `families: dict[str, bool]`, `sites: tuple[str, ...]`, `max_cells_per_line: int | None`, `devices: tuple[DeviceSpec, ...]`, `context: PlantContext`, `report: LoadReport`.
  - `load_profile(raw: Mapping[str, Any], profile_name: str = "full", *, seed: int | None = None) -> LoadedProfile` — `raw` is the merged mapping of `conf/simulator/*.yaml` (so tests pass dicts and never touch the filesystem).
  - `filter_paths(paths: Sequence[ISA95Hierarchy], *, sites: Sequence[str] | None = None, max_cells_per_line: int | None = None) -> list[ISA95Hierarchy]`.
  - `build_plant_context(paths: Sequence[ISA95Hierarchy], raw_plant: Mapping[str, Any], seed: int) -> PlantContext`.
  - `validate_line_overrides(paths: Sequence[ISA95Hierarchy], raw_plant: Mapping[str, Any]) -> None` — raises on a `plant.lines` key naming no production line. Takes the **unfiltered** paths; see the design note at the end of this task.

Four things spec §7.2 fixes about a profile's shape, all of which the YAML in Task 16 depends on:

| Key | Type | Meaning |
|---|---|---|
| `tier_scale` | float, default `1.0` | Multiplies **every** tier interval. `small` uses `6.0`, so a 1 s tier publishes every 6 s. |
| `sites` | list of site names | Filters the expanded hierarchy. Absent means every site. |
| `families` | **list** of family names, not a mapping | The families whose YAML file loads. Absent means none. |
| `max_cells_per_line` | int | Keeps at most this many cells per line, in declaration order. Absent means no cap. |

Tier interval overrides live under **`simulation.tiers`**, not under `profiles`. `profiles` holds profiles and nothing else, so `profiles.small` and a stray `profiles.tiers` can never be confused for one another.

`tiers` on `LoadedProfile` is the *resolved and already-scaled* interval per tier. Handing consumers a pre-multiplied number rather than a base plus a scale means the scheduler in Task 15 cannot forget to apply it — the bug where `small` silently publishes at full rate.

- [ ] **Step 1: Write the failing tests**

```python
# 99_simulator/test/test_profiles.py
import pytest

from uns_simulator.models import expand_hierarchy_paths
from uns_simulator.profiles import (
    FAMILIES,
    TIER_DEFAULTS,
    build_plant_context,
    filter_paths,
    load_profile,
    validate_line_overrides,
)

HIERARCHY = {
    "enterprise": "CovestroAG",
    "sites": [
        {
            "name": "Dormagen",
            "areas": [
                {
                    "name": "Production",
                    "kind": "production",
                    "lines": [{"name": "Line1", "nameplate_tph": 12.0, "cells": ["Cell1", "Cell2"]}],
                },
                {"name": "Utilities", "kind": "utilities", "lines": [{"name": "Powerhouse", "cells": ["Cell1"]}]},
            ],
        },
        {
            "name": "Krefeld",
            "areas": [
                {
                    "name": "Production",
                    "kind": "production",
                    "lines": [{"name": "Line1", "nameplate_tph": 5.0, "cells": ["Cell1"]}],
                }
            ],
        },
    ],
}

RAW = {
    "hierarchy": HIERARCHY,
    "plant": {
        "sites": {"Dormagen": {"ambient_mean_c": 12.0, "ambient_swing_c": 9.0, "tariff_peak_hours": [8, 20]}},
        "lines": {"Dormagen/Production/Line1": {"execute_s": 1800.0, "starting_s": 45.0, "hold_probability_per_hour": 3.0}},
    },
    "energy": {
        "devices": [
            {
                "id": "MAIN",
                "equipment": "MainIncomer",
                "target": {"kind": "utilities"},
                "tier": "energy",
                "serves": ["Dormagen/Production/Line1"],
                "signals": {
                    "ActivePower": {"shape": "ou_walk", "unit": "kW", "mean": 400.0, "sigma": 20.0, "tau": 120.0},
                    "EnergyTotal": {"shape": "counter", "unit": "kWh", "tier": "meter", "rate": "ActivePower / 3600.0"},
                },
            }
        ]
    },
    "water": {
        "devices": [
            {
                "id": "FEED",
                "equipment": "FeedwaterMeter",
                "tier": "meter",
                "signals": {"Flow": {"shape": "ou_walk", "unit": "m3/h", "mean": 20.0, "sigma": 2.0}},
            }
        ]
    },
    "profiles": {
        "full": {"tier_scale": 1.0, "sites": ["Dormagen", "Krefeld"], "families": list(FAMILIES)},
        "small": {"tier_scale": 6.0, "sites": ["Dormagen"], "families": ["energy"], "max_cells_per_line": 1},
    },
    "simulation": {"seed": 1234, "tiers": {"process": 4.0}},
}

ALL_PATHS = expand_hierarchy_paths(HIERARCHY)


def test_tier_defaults_cover_every_documented_tier():
    assert set(TIER_DEFAULTS) == {"fast", "process", "energy", "status", "meter", "lab", "event"}
    assert TIER_DEFAULTS["fast"] == 1.0
    assert TIER_DEFAULTS["meter"] == 900.0
    assert TIER_DEFAULTS["event"] == 0.0


def test_families_are_exactly_the_six_the_spec_names_in_its_order():
    assert FAMILIES == ("energy", "water", "utilities", "asset_health", "production", "safety")


def test_filter_paths_without_filters_keeps_everything():
    assert filter_paths(ALL_PATHS) == list(ALL_PATHS)


def test_filter_paths_keeps_only_the_named_sites():
    kept = filter_paths(ALL_PATHS, sites=["Dormagen"])
    assert {path.site for path in kept} == {"Dormagen"}


def test_filter_paths_caps_cells_per_line_in_declaration_order():
    kept = filter_paths(ALL_PATHS, max_cells_per_line=1)
    production = [path for path in kept if path.area == "Production" and path.site == "Dormagen"]
    assert [path.cell for path in production] == ["Cell1"]


def test_filter_paths_naming_a_site_that_does_not_exist_is_rejected():
    with pytest.raises(ValueError, match="Nowhere"):
        filter_paths(ALL_PATHS, sites=["Dormagen", "Nowhere"])


def test_build_plant_context_creates_a_line_state_per_production_line_only():
    """Spec 6.1: PackML belongs to production lines. A compressor house has no batch."""
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    assert set(context.sites) == {"Dormagen", "Krefeld"}
    assert set(context.sites["Dormagen"].lines) == {"Production/Line1"}
    assert set(context.sites["Krefeld"].lines) == {"Production/Line1"}


def test_line_timing_overrides_are_applied():
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    timing = context.sites["Dormagen"].lines["Production/Line1"].timing
    assert timing.execute_s == 1800.0  # noqa: PLR2004
    assert timing.starting_s == 45.0  # noqa: PLR2004
    assert timing.hold_probability_per_hour == 3.0  # noqa: PLR2004


def test_a_line_override_keyed_on_a_line_that_does_not_exist_is_rejected():
    """A silently ignored timing override is how a line ends up running the defaults."""
    raw_plant = {"lines": {"Dormagen/Production/LineNine": {"execute_s": 10.0}}}
    with pytest.raises(ValueError, match="Dormagen/Production/LineNine"):
        validate_line_overrides(ALL_PATHS, raw_plant)


def test_a_line_override_for_a_site_this_profile_filters_out_is_still_legal():
    """`small` keeps Dormagen only, and plant.yaml still describes Krefeld's timing.

    Checking staleness against the profile's narrowed slice would make this a load failure,
    so plant.yaml could only describe the intersection of every profile.
    """
    raw = {
        **RAW,
        "plant": {
            **RAW["plant"],
            "lines": {**RAW["plant"]["lines"], "Krefeld/Production/Line1": {"execute_s": 900.0}},
        },
    }
    profile = load_profile(raw, "small")
    assert set(profile.context.sites) == {"Dormagen"}
    assert "Production/Line1" in profile.context.sites["Dormagen"].lines


def test_an_override_naming_a_utility_line_is_rejected():
    """Spec 6.1 gives utility lines no LineState, so timing for one cannot be honoured."""
    with pytest.raises(ValueError, match="Dormagen/Utilities/Powerhouse"):
        validate_line_overrides(ALL_PATHS, {"lines": {"Dormagen/Utilities/Powerhouse": {"execute_s": 10.0}}})


def test_line_nameplate_comes_from_the_hierarchy():
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    assert context.sites["Dormagen"].lines["Production/Line1"].nameplate_tph == 12.0  # noqa: PLR2004
    assert context.sites["Krefeld"].lines["Production/Line1"].nameplate_tph == 5.0  # noqa: PLR2004


def test_site_ambient_overrides_are_applied():
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    site = context.sites["Dormagen"]
    for _ in range(0, 86_400, 600):
        site.tick(600.0)
    assert site.ambient_temp_c < 12.0  # the 9 K swing must take it below the 12 C mean


def test_full_profile_loads_every_enabled_family():
    profile = load_profile(RAW, "full")
    assert profile.name == "full"
    assert profile.seed == 1234  # noqa: PLR2004
    assert {device.family for device in profile.devices} == {"energy", "water"}
    assert profile.sites == ("Dormagen", "Krefeld")


def test_small_profile_drops_families_not_in_its_list():
    profile = load_profile(RAW, "small")
    assert {device.family for device in profile.devices} == {"energy"}
    assert profile.families == {
        "energy": True,
        "water": False,
        "utilities": False,
        "asset_health": False,
        "production": False,
        "safety": False,
    }


def test_small_profile_drops_sites_not_in_its_list():
    profile = load_profile(RAW, "small")
    assert set(profile.context.sites) == {"Dormagen"}
    assert {device.path.site for device in profile.devices} == {"Dormagen"}


def test_small_profile_caps_cells_per_line():
    """max_cells_per_line: 1 is what keeps the `small` profile's volume down."""
    profile = load_profile(RAW, "small")
    assert all(device.path.cell == "Cell1" for device in profile.devices)


def test_tier_scale_multiplies_every_interval():
    small = load_profile(RAW, "small")
    assert small.tier_scale == 6.0  # noqa: PLR2004
    assert small.tiers["fast"] == 6.0  # noqa: PLR2004
    assert small.tiers["meter"] == 900.0 * 6.0  # noqa: PLR2004
    # `event` means "on change", so scaling it must leave it at zero rather than make it slow.
    assert small.tiers["event"] == 0.0


def test_tier_scale_defaults_to_one():
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"families": list(FAMILIES)}}}
    profile = load_profile(raw, "full")
    assert profile.tier_scale == 1.0
    assert profile.tiers["fast"] == TIER_DEFAULTS["fast"]


def test_tier_overrides_come_from_simulation_tiers():
    profile = load_profile(RAW, "full")
    assert profile.tiers["process"] == 4.0  # noqa: PLR2004
    assert profile.tiers["meter"] == TIER_DEFAULTS["meter"]


def test_explicit_seed_overrides_the_configured_one():
    assert load_profile(RAW, "full", seed=99).seed == 99  # noqa: PLR2004


def test_report_counts_devices_signals_families_tiers_and_serves():
    report = load_profile(RAW, "full").report
    assert report.devices == 4  # noqa: PLR2004
    assert report.signals == 5  # noqa: PLR2004
    assert report.per_family == {"energy": 1, "water": 3}
    assert report.per_tier["meter"] == 4  # EnergyTotal plus one Flow per FEED device  # noqa: PLR2004
    assert report.serves_links == 1
    assert report.as_dict()["devices"] == report.devices


def test_report_records_a_template_that_matched_nothing():
    raw = {**RAW, "energy": {"devices": [{"id": "GHOST", "equipment": "E", "target": {"site": "Nowhere"}, "signals": {}}]}}
    assert "GHOST" in " ".join(load_profile(raw, "full").report.unmatched_templates)


def test_serves_pointing_at_a_line_that_does_not_exist_is_a_load_error():
    """Spec 6.3 makes this fatal, not a warning: the utility would silently run unloaded."""
    raw = {
        **RAW,
        "utilities": {
            "devices": [
                {
                    "id": "CH",
                    "equipment": "Chiller",
                    "target": {"kind": "utilities"},
                    "serves": ["Dormagen/Production/LineZ"],
                    "signals": {},
                }
            ]
        },
    }
    with pytest.raises(ValueError, match="Dormagen/Production/LineZ"):
        load_profile(raw, "full")


def test_serves_naming_a_line_the_profile_filtered_out_is_a_load_error():
    """`small` keeps Dormagen only, so a serves entry into Krefeld must fail loudly."""
    raw = {
        **RAW,
        "energy": {
            "devices": [
                {
                    "id": "MAIN",
                    "equipment": "MainIncomer",
                    "target": {"kind": "utilities"},
                    "serves": ["Krefeld/Production/Line1"],
                    "signals": {},
                }
            ]
        },
    }
    load_profile(raw, "full")  # fine: Krefeld is in `full`
    with pytest.raises(ValueError, match="Krefeld/Production/Line1"):
        load_profile(raw, "small")


def test_unknown_profile_name_is_rejected_by_name():
    with pytest.raises(ValueError, match="tiny"):
        load_profile(RAW, "tiny")


def test_unknown_family_in_a_profile_is_rejected_by_name():
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"families": ["engery"]}}}
    with pytest.raises(ValueError, match="engery"):
        load_profile(raw, "full")


def test_a_families_mapping_instead_of_a_list_is_rejected():
    """The old shape was a mapping. Accepting both would let one profile contradict itself."""
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"families": {"energy": True}}}}
    with pytest.raises(ValueError, match="families"):
        load_profile(raw, "full")


def test_negative_tier_interval_is_rejected_by_name():
    raw = {**RAW, "simulation": {**RAW["simulation"], "tiers": {"process": -1.0}}}
    with pytest.raises(ValueError, match="process"):
        load_profile(raw, "full")


def test_unknown_tier_name_is_rejected_by_name():
    raw = {**RAW, "simulation": {**RAW["simulation"], "tiers": {"turbo": 1.0}}}
    with pytest.raises(ValueError, match="turbo"):
        load_profile(raw, "full")


def test_a_non_positive_tier_scale_is_rejected():
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"tier_scale": 0.0, "families": list(FAMILIES)}}}
    with pytest.raises(ValueError, match="tier_scale"):
        load_profile(raw, "full")


def test_a_legacy_flat_interval_becomes_the_process_tier():
    """Spec 12: settings.yaml today has `simulation.interval: 5.0` and no `tiers` block."""
    raw = {**RAW, "simulation": {"seed": 1, "interval": 20.0}}
    profile = load_profile(raw, "full")
    assert profile.tiers["process"] == 20.0  # noqa: PLR2004
    assert profile.tiers["fast"] == TIER_DEFAULTS["fast"]


def test_an_explicit_tiers_block_wins_over_the_legacy_interval():
    raw = {**RAW, "simulation": {"seed": 1, "interval": 20.0, "tiers": {"process": 3.0}}}
    assert load_profile(raw, "full").tiers["process"] == 3.0  # noqa: PLR2004


def test_an_unknown_signal_tier_is_rejected_by_name():
    raw = {
        **RAW,
        "water": {
            "devices": [
                {"id": "F", "equipment": "M", "signals": {"Flow": {"unit": "m3/h", "tier": "hyper"}}}
            ]
        },
    }
    with pytest.raises(ValueError, match="hyper"):
        load_profile(raw, "full")


def test_duplicate_device_ids_are_rejected():
    raw = {
        **RAW,
        "energy": {"devices": [{"id": "DUP", "equipment": "A", "signals": {}}, {"id": "DUP", "equipment": "B", "signals": {}}]},
    }
    with pytest.raises(ValueError, match="DUP"):
        load_profile(raw, "full")


def test_loading_twice_with_the_same_seed_gives_the_same_device_set():
    first = load_profile(RAW, "full", seed=7)
    second = load_profile(RAW, "full", seed=7)
    assert [d.id for d in first.devices] == [d.id for d in second.devices]
    assert [[s.name for s in d.signals] for d in first.devices] == [[s.name for s in d.signals] for d in second.devices]
```

Where the counts in `test_report_counts_...` come from, so a failure sends you to the loader rather than to the arithmetic. `HIERARCHY` expands to four paths:

| Path | `kind` |
|---|---|
| `Dormagen/Production/Line1/Cell1` | production |
| `Dormagen/Production/Line1/Cell2` | production |
| `Dormagen/Utilities/Powerhouse/Cell1` | utilities |
| `Krefeld/Production/Line1/Cell1` | production |

`MAIN` has `target: {kind: utilities}`, so it lands once. `FEED` has **no** `target`, which spec §7.3 defines as "production cells only", so it lands three times. That is 4 devices, 1 + 3 × 1 = 5 signals, and `{"energy": 1, "water": 3}` per family. `per_tier["meter"]` is 4 because `EnergyTotal` overrides onto `meter` and `FEED`'s device tier is already `meter`.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_profiles.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_profile'`.

- [ ] **Step 3: Implement the loader**

```python
# append to 99_simulator/src/uns_simulator/profiles.py
TIER_DEFAULTS: dict[str, float] = {
    "fast": 1.0,
    "process": 5.0,
    "energy": 15.0,
    "status": 30.0,
    "meter": 900.0,
    "lab": 1800.0,
    "event": 0.0,
}

FAMILIES: tuple[str, ...] = ("energy", "water", "utilities", "asset_health", "production", "safety")


PRODUCTION_KIND = "production"


@dataclass
class LoadReport:
    """What the loader saw. Rendered by sub-project B's GET /simulator/diagnostics."""

    devices: int = 0
    signals: int = 0
    per_family: dict[str, int] = field(default_factory=dict)
    per_tier: dict[str, int] = field(default_factory=dict)
    serves_links: int = 0
    unmatched_templates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "devices": self.devices,
            "signals": self.signals,
            "per_family": dict(self.per_family),
            "per_tier": dict(self.per_tier),
            "serves_links": self.serves_links,
            "unmatched_templates": list(self.unmatched_templates),
            "warnings": list(self.warnings),
        }


@dataclass
class LoadedProfile:
    """Everything the simulator needs to run, resolved and validated."""

    name: str
    seed: int
    tier_scale: float
    tiers: dict[str, float]
    families: dict[str, bool]
    sites: tuple[str, ...]
    max_cells_per_line: int | None
    devices: tuple[DeviceSpec, ...]
    context: PlantContext
    report: LoadReport


def filter_paths(
    paths: Sequence[ISA95Hierarchy],
    *,
    sites: Sequence[str] | None = None,
    max_cells_per_line: int | None = None,
) -> list[ISA95Hierarchy]:
    """Narrow the expanded hierarchy the way spec 7.2's profile keys say to.

    `sites` naming a site that is not in the hierarchy is an error rather than an empty
    result: a profile that quietly resolves to nothing is the hardest kind of typo to see.
    """
    if sites is not None:
        wanted = list(dict.fromkeys(str(name) for name in sites))
        available = {path.site for path in paths}
        if unknown := [name for name in wanted if name not in available]:
            raise ValueError(
                f"profile site(s) {', '.join(unknown)} are not in the hierarchy "
                f"(available: {', '.join(sorted(available))})"
            )
        paths = [path for path in paths if path.site in set(wanted)]

    if max_cells_per_line is None:
        return list(paths)
    if max_cells_per_line < 1:
        raise ValueError(f"max_cells_per_line must be at least 1, got {max_cells_per_line}")

    # Declaration order, not sorted order: the profile author's first cell is the one kept.
    seen: dict[tuple[str, str, str], int] = {}
    kept: list[ISA95Hierarchy] = []
    for path in paths:
        key = (path.site, path.area, path.line)
        count = seen.get(key, 0)
        if count >= max_cells_per_line:
            continue
        seen[key] = count + 1
        kept.append(path)
    return kept


def build_plant_context(paths: Sequence[ISA95Hierarchy], raw_plant: Mapping[str, Any], seed: int) -> PlantContext:
    """Build the PlantContext from the same paths the devices are targeted at.

    Only areas of kind `production` get a `LineState`: spec 6.1 gives PackML to production
    lines, and a compressor house has no batch to be IDLE between. Utility devices read
    their served lines through `serves` instead.
    """
    site_overrides: Mapping[str, Any] = raw_plant.get("sites") or {}
    line_overrides: Mapping[str, Any] = raw_plant.get("lines") or {}

    context = PlantContext(global_seed=seed)
    for path in paths:
        if path.site not in context.sites:
            override = dict(site_overrides.get(path.site) or {})
            peak = override.pop("tariff_peak_hours", None)
            if peak is not None:
                override["tariff_peak_hours"] = (int(peak[0]), int(peak[1]))
            context.add_site(path.site, **override)
        if path.kind != PRODUCTION_KIND:
            continue
        line_path = f"{path.area}/{path.line}"
        if line_path in context.sites[path.site].lines:
            continue
        timing_kwargs = dict(line_overrides.get(f"{path.site}/{line_path}") or {})
        context.add_line(path.site, path.area, path.line, LineTiming(**timing_kwargs), path.nameplate_tph)
    return context


def validate_line_overrides(paths: Sequence[ISA95Hierarchy], raw_plant: Mapping[str, Any]) -> None:
    """Every `plant.lines` key must name a production line somewhere in the hierarchy.

    Checked against the **unfiltered** hierarchy, which is why this is a separate function
    rather than a block inside `build_plant_context`. `small` keeps only Dormagen, and its
    `plant.lines` block still legitimately describes Krefeld's timing; folding the check into
    the context builder would make every override illegal in every profile that filters it
    out, so `plant.yaml` could only ever describe the intersection of all profiles.

    An override that matches nothing anywhere is still fatal: it leaves a line running the
    defaults, which looks exactly like the override having been written badly.
    """
    known = {f"{path.site}/{path.area}/{path.line}" for path in paths if path.kind == PRODUCTION_KIND}
    if stale := sorted(set(raw_plant.get("lines") or {}) - known):
        raise ValueError(
            f"plant.lines override(s) {', '.join(stale)} name no production line in the "
            f"hierarchy; expected Site/Area/Line"
        )


def _resolve_families(profile_name: str, selection: Mapping[str, Any]) -> dict[str, bool]:
    """Spec 7.2's `families` is a list of names, not a mapping of flags."""
    raw_families = selection.get("families")
    if raw_families is None:
        raw_families = []
    if isinstance(raw_families, Mapping) or isinstance(raw_families, str):
        raise ValueError(
            f"profile {profile_name!r}: 'families' must be a list of family names, "
            f"got {type(raw_families).__name__}"
        )
    named = [str(name) for name in raw_families]
    if unknown := sorted(set(named) - set(FAMILIES)):
        raise ValueError(f"unknown family/families in profile {profile_name!r}: {', '.join(unknown)}")
    return {family: family in set(named) for family in FAMILIES}


def _resolve_tiers(raw: Mapping[str, Any], tier_scale: float) -> dict[str, float]:
    """Merge `simulation.tiers` onto the defaults, then apply the profile's `tier_scale`."""
    tiers = dict(TIER_DEFAULTS)
    simulation: Mapping[str, Any] = raw.get("simulation") or {}
    overrides: Mapping[str, Any] = simulation.get("tiers") or {}
    if not overrides and (legacy := simulation.get("interval")) is not None:
        # Spec 12: a flat `simulation.interval` was the only cadence knob before tiers
        # existed, and it published every sensor. With no `simulation.tiers` block it still
        # means "how often process values publish", so an untouched settings.yaml keeps the
        # rate it has today instead of silently jumping to the 5 s default.
        tiers["process"] = float(legacy)
    for name, interval in overrides.items():
        if name not in TIER_DEFAULTS:
            raise ValueError(f"unknown cadence tier {name!r} (known tiers: {', '.join(sorted(TIER_DEFAULTS))})")
        if float(interval) < 0.0:
            raise ValueError(f"cadence tier {name!r} must not be negative, got {interval}")
        tiers[name] = float(interval)
    # `event` is 0.0 meaning "on change". Scaling zero keeps it zero, which is what we want:
    # a slow profile must not turn an event topic into a slow periodic one.
    return {name: interval * tier_scale for name, interval in tiers.items()}


def load_profile(
    raw: Mapping[str, Any], profile_name: str = "full", *, seed: int | None = None
) -> LoadedProfile:
    """Resolve a profile into devices, a plant context and a load report.

    `raw` is the merged conf/simulator mapping. Every validation error names the offending
    key, because the alternative - a profile that loads and produces the wrong plant - costs
    far more to diagnose.
    """
    profiles: Mapping[str, Any] = raw.get("profiles") or {}
    selection = profiles.get(profile_name)
    if selection is None:
        known = ", ".join(sorted(profiles)) or "none"
        raise ValueError(f"unknown profile {profile_name!r} (known profiles: {known})")

    families = _resolve_families(profile_name, selection)

    tier_scale = float(selection.get("tier_scale", 1.0))
    if tier_scale <= 0.0:
        raise ValueError(f"profile {profile_name!r}: tier_scale must be positive, got {tier_scale}")
    tiers = _resolve_tiers(raw, tier_scale)

    resolved_seed = int(seed if seed is not None else (raw.get("simulation") or {}).get("seed", 0))

    raw_sites = selection.get("sites")
    max_cells = selection.get("max_cells_per_line")
    max_cells_per_line = int(max_cells) if max_cells is not None else None
    raw_plant: Mapping[str, Any] = raw.get("plant") or {}
    all_paths = expand_hierarchy_paths(raw.get("hierarchy") or {})
    validate_line_overrides(all_paths, raw_plant)
    paths = filter_paths(
        all_paths,
        sites=[str(name) for name in raw_sites] if raw_sites is not None else None,
        max_cells_per_line=max_cells_per_line,
    )
    context = build_plant_context(paths, raw_plant, resolved_seed)

    report = LoadReport()
    devices: list[DeviceSpec] = []
    seen_template_ids: set[str] = set()
    for family in FAMILIES:
        if not families[family]:
            continue
        for template in (raw.get(family) or {}).get("devices") or []:
            template_id = str(template.get("id", "<missing id>"))
            if template_id in seen_template_ids:
                raise ValueError(f"duplicate device template id {template_id!r} in family {family!r}")
            seen_template_ids.add(template_id)
            expanded = expand_template(template, paths, family)
            if not expanded:
                report.unmatched_templates.append(f"{family}/{template_id}: target matched no hierarchy path")
                continue
            devices.extend(expanded)

    for device in devices:
        report.per_family[device.family] = report.per_family.get(device.family, 0) + 1
        for spec in device.signals:
            if spec.tier not in tiers:
                raise ValueError(
                    f"device {device.id!r} signal {spec.name!r}: unknown tier {spec.tier!r} "
                    f"(known tiers: {', '.join(sorted(tiers))})"
                )
            report.per_tier[spec.tier] = report.per_tier.get(spec.tier, 0) + 1
        report.signals += len(device.signals)
        # Spec 6.3: an unresolvable `serves` path fails the load. Done here rather than in
        # `expand_template` because only this function has the PlantContext to check against.
        try:
            context.resolve_serves(device.serves)
        except KeyError as exc:
            raise ValueError(f"device {device.id!r}: {exc.args[0]}") from exc
        report.serves_links += len(device.serves)
    report.devices = len(devices)

    if not devices:
        report.warnings.append(f"profile {profile_name!r} resolved to zero devices")

    return LoadedProfile(
        name=profile_name,
        seed=resolved_seed,
        tier_scale=tier_scale,
        tiers=tiers,
        families=families,
        sites=tuple(dict.fromkeys(path.site for path in paths)),
        max_cells_per_line=max_cells_per_line,
        devices=tuple(devices),
        context=context,
        report=report,
    )
```

Extend `profiles.py`'s imports:

```python
from dataclasses import dataclass, field

from uns_simulator.models import ISA95Hierarchy, expand_hierarchy_paths
from uns_simulator.plant import LineTiming, PlantContext
```

Three design notes worth keeping in the code review:
- **Filtering happens before the context is built, not after.** `filter_paths` runs first, so `build_plant_context` and `expand_template` see exactly the same narrowed path list. That is what makes `serves` validation meaningful under `small`: a path filtered out of the profile is genuinely absent, and a device still pointing at it fails rather than silently aggregating nothing.
- **An unresolvable `serves` path is fatal.** Spec §6.3 says so, and the reason is asymmetric cost: a chiller whose `serves` no longer resolves runs at its base load forever and looks plausible on a chart. A load failure naming the path costs one restart.
- **A stale `plant.lines` override key is fatal too**, by the same argument — an override nobody applies leaves a line running the defaults, which is indistinguishable from the override having been written badly. But it is checked against the **unfiltered** hierarchy, one step earlier than `serves`, and the difference matters: `serves` lives on a device that the profile chose to load, so the profile's narrowed view is the right one to judge it against, whereas `plant.lines` is plant-wide furniture that every profile shares. Judged against the narrow view, `small` would reject `plant.yaml`'s Krefeld timing and `plant.yaml` could only ever describe the intersection of all profiles.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_profiles.py -v`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/profiles.py 99_simulator/test/test_profiles.py
git commit -m "feat(simulator): add profile loading, validation and a diagnostics load report"
```

---

## Task 13: Persistent MQTT transport

`devices.py:84` opens and closes a broker connection *for every single message*. At today's 6 signals that is invisible; at ~400 signals with a 1 s tier it is thousands of TCP handshakes a minute, and it makes the connection state unobservable — which is why sub-project B's `broker_connected` could not be reported. This task also fixes the client-id collision at `devices.py:34` (`f"graphql-{time.time()}-..."`: wrong prefix, and `time.time()` collides when devices are constructed in the same millisecond).

**Files:**
- Modify: `99_simulator/src/uns_simulator/devices.py:29-96`
- Test: `99_simulator/test/test_devices.py`

**Interfaces:**
- Consumes: `MQTTConfig` (unchanged).
- Produces on `AsyncMQTTDevice`: attributes `.client_id: str`, `.connected: bool`, `.publish_ok: int`, `.publish_fail: int`, `.reconnects: int`, `.last_error: str | None`, `.last_publish_ts: float | None`; methods `async connect(self) -> bool`, `async disconnect(self) -> None`, and `health(self) -> dict[str, Any]` (the body sub-project B publishes as device health). `publish_parameter`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests**

The existing `DummyClient` in `test_devices.py` records `(topic, parsed)` on publish and supports `__aenter__`/`__aexit__`. Extend it in place so it can also count context entries and be told to fail:

```python
# in 99_simulator/test/test_devices.py, extend the existing DummyClient
class DummyClient:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.published: list[tuple[str, dict]] = []
        self.enter_count = 0
        self.fail_on_enter = 0
        self.fail_on_publish = False

    async def __aenter__(self):
        self.enter_count += 1
        if self.fail_on_enter > 0:
            self.fail_on_enter -= 1
            raise OSError("broker refused the connection")
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    async def publish(self, topic, payload, **kwargs):  # noqa: ARG002
        if self.fail_on_publish:
            raise OSError("broker went away")
        self.published.append((topic, json.loads(payload)))
```

Keep whatever attributes the existing four tests already rely on. Then add:

```python
# append to 99_simulator/test/test_devices.py
@pytest.mark.asyncio
async def test_client_id_is_unique_per_device_and_names_the_simulator():
    first = AsyncMQTTDevice("dev-a", FakeHierarchy(), {})
    second = AsyncMQTTDevice("dev-a", FakeHierarchy(), {})
    assert first.client_id.startswith("uns_simulator-")
    assert "dev-a" in first.client_id
    assert first.client_id != second.client_id


@pytest.mark.asyncio
async def test_the_connection_is_opened_once_for_many_publishes():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    for index in range(20):
        assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, f"S{index}", {"value": index})
    assert device.client.enter_count == 1, "one connection, not one per message"
    assert len(device.client.published) == 20  # noqa: PLR2004
    assert device.connected is True
    assert device.publish_ok == 20  # noqa: PLR2004
    assert device.publish_fail == 0


@pytest.mark.asyncio
async def test_connect_retries_with_backoff_and_counts_reconnects(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(devices.asyncio, "sleep", fake_sleep)
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    device.client.fail_on_enter = 3
    assert await device.connect() is True
    assert device.connected is True
    assert sleeps == [1.0, 2.0, 4.0], "backoff must double"
    assert device.reconnects == 3  # noqa: PLR2004


@pytest.mark.asyncio
async def test_backoff_is_capped_at_the_configured_retry_interval(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(devices.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(devices.MQTTConfig, "retry_interval", 5, raising=False)
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    device.client.fail_on_enter = 6
    await device.connect()
    assert max(sleeps) == 5.0  # noqa: PLR2004
    assert sleeps[-1] == 5.0  # noqa: PLR2004


@pytest.mark.asyncio
async def test_a_publish_failure_marks_the_device_disconnected_and_is_counted():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    device.client.fail_on_publish = True
    assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1}) is False
    assert device.connected is False
    assert device.publish_fail == 1
    assert "broker went away" in device.last_error


@pytest.mark.asyncio
async def test_a_publish_failure_is_followed_by_a_reconnect_on_the_next_attempt():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    device.client.fail_on_publish = True
    await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1})
    device.client.fail_on_publish = False
    assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 2}) is True
    assert device.client.enter_count == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_disconnect_is_idempotent():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    await device.disconnect()
    await device.disconnect()
    assert device.connected is False


@pytest.mark.asyncio
async def test_health_reports_the_publish_counters():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1})
    health = device.health()
    assert health["connected"] is True
    assert health["publish_ok"] == 1
    assert health["publish_fail"] == 0
    assert health["last_error"] is None
    assert isinstance(health["last_publish_ts"], float)
```

Add `import json` and `from uns_simulator.devices import AsyncMQTTDevice` to the test file's imports if not already present.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_devices.py -v`
Expected: the four pre-existing tests still pass; the new ones fail on `AttributeError: 'AsyncMQTTDevice' object has no attribute 'client_id'`.

- [ ] **Step 3: Replace `AsyncMQTTDevice.__init__` (`devices.py:29-50`)**

```python
    def __init__(self, device_id: str, hierarchy: ISA95Hierarchy, mqtt_config: dict[str, Any]):
        self.device_id = device_id
        self.hierarchy = hierarchy
        self.mqtt_config = mqtt_config

        # uuid4, not time.time(): devices are constructed in a tight loop and a timestamp
        # collides. A duplicate client id makes the broker evict the earlier connection.
        self.client_id = f"uns_simulator-{device_id}-{uuid.uuid4().hex[:8]}"

        self.connected = False
        self.publish_ok = 0
        self.publish_fail = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self.last_publish_ts: float | None = None
        self._stack: contextlib.AsyncExitStack | None = None
        self._running = False

        self.client = aiomqtt.Client(
            identifier=self.client_id,
            clean_session=MQTTConfig.clean_session,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            hostname=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            keepalive=MQTTConfig.keep_alive,
            tls_params=MQTTConfig.tls_params,
            tls_insecure=MQTTConfig.tls_insecure,
        )

        LOGGER.info("Initialized device: %s (client id %s)", device_id, self.client_id)
```

Replace `import random` / `import time` usage at the top with `import contextlib` and `import uuid` added to the import block. Leave `random` imported — `PLC`, `SCADA` and `HMI` still use it. Drop `import time` if nothing else uses it; ruff `F401` will say.

- [ ] **Step 4: Add `connect`, `disconnect` and `health`, and rewrite the publish body**

```python
    async def connect(self) -> bool:
        """Open one long-lived broker connection, retrying with exponential backoff.

        Backoff doubles from 1 s and is capped at MQTTConfig.retry_interval, so a broker
        that is down at startup does not turn into a hot loop and does not give up either.
        """
        if self.connected:
            return True
        cap = float(getattr(MQTTConfig, "retry_interval", 10) or 10)
        delay = 1.0
        while True:
            self._stack = contextlib.AsyncExitStack()
            try:
                await self._stack.enter_async_context(self.client)
            except Exception as exc:
                self.reconnects += 1
                self.last_error = str(exc)
                await self._stack.aclose()
                self._stack = None
                LOGGER.warning(
                    "Device %s could not connect (%s); retrying in %.1fs", self.device_id, exc, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, cap)
                continue
            self.connected = True
            LOGGER.info("Device %s connected to the broker", self.device_id)
            return True

    async def disconnect(self) -> None:
        """Close the connection. Safe to call when already disconnected."""
        self.connected = False
        if self._stack is None:
            return
        stack, self._stack = self._stack, None
        try:
            await stack.aclose()
        except Exception as exc:
            LOGGER.debug("Device %s disconnect raised %s", self.device_id, exc)

    def health(self) -> dict[str, Any]:
        """Connection and publish counters. Published as device health by sub-project B."""
        return {
            "device_id": self.device_id,
            "client_id": self.client_id,
            "connected": self.connected,
            "publish_ok": self.publish_ok,
            "publish_fail": self.publish_fail,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "last_publish_ts": self.last_publish_ts,
        }
```

Then in `publish_parameter`, replace the `async with self.client:` block (`devices.py:83-88`) with:

```python
            if not self.connected:
                await self.connect()

            await self.client.publish(topic, json.dumps(enriched_data))
            self.publish_ok += 1
            self.last_publish_ts = datetime.now().timestamp()
            LOGGER.debug(
                "Device %s published to %s: %s", self.device_id, topic, enriched_data.get("value", "N/A")
            )
            return True
```

and in the trailing `except Exception as e:` handler, mark the device as needing a reconnect before returning `False`:

```python
        except Exception as e:
            self.publish_fail += 1
            self.last_error = str(e)
            self.connected = False
            await self.disconnect()
            LOGGER.error("Publish error in device %s: %s", self.device_id, e)
            return False
```

Do not add counters to the `json.JSONDecodeError` branch — a malformed payload is a programming error in the caller, not a transport failure, and conflating the two would make `publish_fail` useless as a broker-health signal. Keep that branch returning `False` as it does today.

`test_the_connection_is_opened_once_for_many_publishes` passes because `connect()` is a no-op once `self.connected` is true; `test_a_publish_failure_is_followed_by_a_reconnect_on_the_next_attempt` passes because the failure path clears it. The pre-existing `test_publish_parameter_enriches_and_publishes`, which assigns `plc.client = DummyClient()` and calls `publish_parameter` directly, still passes: `connect()` enters the dummy's context successfully.

- [ ] **Step 5: Add `stop()` calling `disconnect()`**

`AsyncMQTTDevice.stop` (`devices.py:131-134`) currently only flips `_running`. Make it release the connection too:

```python
    async def stop(self) -> None:
        """Stop device operation and release the broker connection."""
        self._running = False
        await self.disconnect()
        LOGGER.info("Device %s stopped", self.device_id)
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -v`
Expected: all pass, including the four pre-existing `test_devices.py` tests and `test_hierarchy.py`'s `len(plcs) == 4`.

- [ ] **Step 7: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/devices.py 99_simulator/test/test_devices.py
git commit -m "fix(simulator): reuse one MQTT connection per device with backoff and unique client ids"
```

---

## Task 14: `SignalDevice` — publish a `SignalSpec` set on cadence tiers

The device that replaces the hardcoded `PLC`. It separates the two things `PLC.generate_sensor_data` welds together: computing a value, and publishing it. Values advance on the plant tick; publishing happens per tier. `PLC`, `SCADA` and `HMI` stay in place untouched so nothing existing breaks.

**Files:**
- Modify: `99_simulator/src/uns_simulator/devices.py`
- Test: `99_simulator/test/test_devices.py`

**Interfaces:**
- Consumes: `AsyncMQTTDevice` (Task 13), `DeviceSpec` (Task 11), `DeviceView` (Task 8), `build_signal`/`Signal` (Tasks 2–6), `ParameterType` (`models.py`).
- Produces `class SignalDevice(AsyncMQTTDevice)`:
  - `__init__(self, spec: DeviceSpec, mqtt_config: dict[str, Any], view: DeviceView, global_seed: int)`; attributes `.spec`, `.view`, `.signals: list[Signal]`, `.values: dict[str, Any]`, `.enabled: bool`, `.tiers: frozenset[str]`.
  - `evaluate(self, dt: float) -> dict[str, Any]` — advances every signal in dependency order and returns the new `values`. Synchronous; called from the clock tick, never from a publish task.
  - `async publish_tier(self, tier: str) -> int` — publishes every signal whose `tier` matches, returning how many succeeded.
  - `async run_tier(self, tier: str, interval: float) -> None` — the loop the simulator schedules per tier.
  - `snapshot(self) -> list[dict[str, Any]]` — per-signal `{name, shape, unit, precision, range, limits, params, value, status, tier}`; the body of sub-project B's `GET /simulator/devices/{id}/signals`.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_devices.py
import random

from uns_simulator.devices import SignalDevice
from uns_simulator.models import ISA95Hierarchy
from uns_simulator.plant import DeviceView, LineTiming, PlantContext
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import SignalSpec

PATH = ISA95Hierarchy("CovestroAG", "Dormagen", "Utilities", "Powerhouse", "Cell1", kind="utilities")


def _view():
    """A utility device's view: no PackML line of its own, one served production line.

    `line=None` is deliberate and is what a real utility device gets — spec 6.1 gives
    `LineState` to production lines only, so a powerhouse reads production through `serves`.
    """
    context = PlantContext(global_seed=7)
    context.add_site("Dormagen")
    timing = LineTiming(starting_s=1.0, execute_s=100_000.0, hold_probability_per_hour=0.0)
    context.add_line("Dormagen", "Production", "Line1", timing, 12.0)
    for _ in range(10):
        context.tick(1.0)
    return DeviceView(context, "Dormagen", None, serves=["Dormagen/Production/Line1"])


def _device(*signals, tier="energy"):
    spec = DeviceSpec(
        id="MAIN@Dormagen.Utilities.Powerhouse.Cell1",
        equipment="MainIncomer",
        family="energy",
        tier=tier,
        path=PATH,
        signals=tuple(signals),
    )
    return SignalDevice(spec, {}, _view(), global_seed=7)


def test_evaluate_advances_every_signal_and_returns_the_values():
    device = _device(
        SignalSpec(name="ActivePower", shape="ou_walk", unit="kW", params={"mean": 400.0, "sigma": 10.0, "tau": 120.0}),
        SignalSpec(name="EnergyTotal", shape="counter", unit="kWh", params={"rate": "ActivePower / 3600.0"}),
    )
    values = device.evaluate(1.0)
    assert set(values) == {"ActivePower", "EnergyTotal"}
    assert values["EnergyTotal"] > 0.0


def test_a_derived_signal_sees_this_tick_not_the_last_one():
    device = _device(
        SignalSpec(name="ActivePower", shape="constant", base_value=400.0),
        SignalSpec(name="ApparentPower", shape="derived", precision=1, params={"expr": "ActivePower / 0.9"}),
    )
    assert device.evaluate(1.0)["ApparentPower"] == pytest.approx(444.4)


def test_a_derived_signal_reads_the_plant_through_ctx():
    """Spec 6.3's name is `served_production`; the served line sits in EXECUTE at 0.85-1.0."""
    device = _device(SignalSpec(name="ChillerLoad", shape="derived", precision=2, params={"expr": "ctx.served_production * 200"}))
    assert device.evaluate(1.0)["ChillerLoad"] == pytest.approx(185.0, abs=20.0)


def test_publish_tier_only_publishes_that_tier():
    device = _device(
        SignalSpec(name="ActivePower", shape="ou_walk", tier="energy", params={"mean": 400.0}),
        SignalSpec(name="EnergyTotal", shape="counter", tier="meter", params={"rate": 1.0}),
    )
    device.evaluate(1.0)
    published = asyncio.run(device.publish_tier("energy"))
    assert published == 1
    topics = [topic for topic, _ in device.client.published]
    assert topics == ["CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainIncomer/ProcessValue/ActivePower"]


def test_the_payload_carries_value_unit_status_and_quality():
    device = _device(SignalSpec(name="ActivePower", shape="constant", unit="kW", base_value=400.0, tier="energy"))
    device.evaluate(1.0)
    asyncio.run(device.publish_tier("energy"))
    _, payload = device.client.published[0]
    assert payload["value"] == pytest.approx(400.0)
    assert payload["unit"] == "kW"
    assert payload["status"] == "Normal"
    assert payload["quality"] == "Good"
    assert payload["source"] == device.device_id
    assert payload["equipment"] == "MainIncomer"
    assert "timestamp" in payload


def test_param_type_selects_the_topic_segment():
    device = _device(
        SignalSpec(name="Mode", shape="stepped", tier="status", param_type="Status", params={"choices": ["Auto"]}),
    )
    device.evaluate(1.0)
    asyncio.run(device.publish_tier("status"))
    assert device.client.published[0][0].endswith("/Status/Mode")


def test_an_unknown_param_type_is_rejected_at_construction_by_name():
    with pytest.raises(ValueError, match="Banana"):
        _device(SignalSpec(name="X", param_type="Banana"))


def test_a_none_valued_signal_is_not_published():
    device = _device(SignalSpec(name="Avg", shape="window_agg", tier="energy", params={"source": "absent"}))
    device.evaluate(1.0)
    assert asyncio.run(device.publish_tier("energy")) == 0
    assert device.client.published == []


def test_an_event_tier_signal_publishes_only_when_its_value_changes():
    device = _device(
        SignalSpec(name="Door", shape="stepped", tier="event", param_type="EVENT", params={"choices": ["Closed"], "dwell_s": 1e9}),
    )
    for _ in range(5):
        device.evaluate(1.0)
        asyncio.run(device.publish_tier("event"))
    assert len(device.client.published) == 1, "an unchanged event value must not republish"


def test_tiers_lists_only_the_tiers_this_device_actually_uses():
    device = _device(
        SignalSpec(name="A", tier="fast"),
        SignalSpec(name="B", tier="meter"),
        SignalSpec(name="C", tier="fast"),
    )
    assert device.tiers == frozenset({"fast", "meter"})


def test_a_disabled_device_publishes_nothing():
    device = _device(SignalSpec(name="A", tier="fast", base_value=1.0))
    device.enabled = False
    device.evaluate(1.0)
    assert asyncio.run(device.publish_tier("fast")) == 0


def test_snapshot_describes_every_signal():
    device = _device(SignalSpec(name="ActivePower", shape="ou_walk", unit="kW", params={"mean": 400.0}, limits={"hi": 600.0}))
    device.evaluate(1.0)
    entry = device.snapshot()[0]
    assert entry["name"] == "ActivePower"
    assert entry["shape"] == "ou_walk"
    assert entry["unit"] == "kW"
    assert entry["limits"] == {"hi": 600.0}
    assert entry["status"] in {"Normal", "Warning", "Alarm"}
    assert isinstance(entry["value"], float)


@pytest.mark.asyncio
async def test_run_tier_publishes_then_sleeps_and_stops():
    device = _device(SignalSpec(name="A", tier="fast", shape="constant", base_value=1.0))
    device.evaluate(1.0)
    task = asyncio.create_task(device.run_tier("fast", 0.01))
    await asyncio.sleep(0.05)
    await device.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert len(device.client.published) >= 2  # noqa: PLR2004
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_devices.py -k "signal or tier or snapshot or param_type or derived" -v`
Expected: FAIL — `ImportError: cannot import name 'SignalDevice'`.

- [ ] **Step 3: Implement `SignalDevice`**

Append to `devices.py`:

```python
class SignalDevice(AsyncMQTTDevice):
    """A device whose behaviour is entirely declared by its DeviceSpec.

    Two responsibilities, deliberately kept apart:
      evaluate(dt)      - advance the signals. Called once per plant tick.
      publish_tier(t)   - send the current values for one cadence tier.

    Splitting them is what makes a 900 s meter reading and a 1 s vibration sample describe
    the same instant of the same world. The old PLC computed a value at publish time, so a
    slow publisher necessarily saw a coarser simulation.
    """

    def __init__(
        self,
        spec: DeviceSpec,
        mqtt_config: dict[str, Any],
        view: DeviceView,
        global_seed: int,
    ) -> None:
        super().__init__(spec.id, spec.path, mqtt_config)
        self.spec = spec
        self.view = view
        self.enabled = spec.enabled
        self.values: dict[str, Any] = {}
        self._last_published: dict[str, Any] = {}

        self._param_types: dict[str, ParameterType] = {}
        for signal_spec in spec.signals:
            try:
                self._param_types[signal_spec.name] = ParameterType(signal_spec.param_type)
            except ValueError:
                allowed = ", ".join(member.value for member in ParameterType)
                raise ValueError(
                    f"device {spec.id!r} signal {signal_spec.name!r}: unknown param_type "
                    f"{signal_spec.param_type!r} (allowed: {allowed})"
                ) from None

        # spec.signals is already in dependency order (profiles.expand_template sorted it),
        # so evaluating in sequence guarantees a derived signal sees this tick's siblings.
        self.signals = [
            build_signal(signal_spec, f"{spec.topic_prefix}/{signal_spec.name}", global_seed)
            for signal_spec in spec.signals
        ]
        self.tiers = frozenset(signal_spec.tier for signal_spec in spec.signals)

    def evaluate(self, dt: float) -> dict[str, Any]:
        """Advance every signal by `dt` seconds. Synchronous, and never publishes."""
        for signal in self.signals:
            self.values[signal.spec.name] = signal.next(dt, self.view, self.values)
        return self.values

    async def publish_tier(self, tier: str) -> int:
        """Publish the current value of every signal in `tier`. Returns the success count."""
        if not self.enabled:
            return 0
        published = 0
        for signal in self.signals:
            if signal.spec.tier != tier:
                continue
            value = self.values.get(signal.spec.name)
            if value is None:
                continue
            # The 'event' tier means "on change" - a door that stays shut says so once.
            if tier == "event" and self._last_published.get(signal.spec.name, object()) == value:
                continue
            payload = {
                "value": value,
                "unit": signal.spec.unit,
                "status": signal.status(),
                "quality": "Good",
            }
            if signal.spec.limits:
                payload["limits"] = signal.spec.limits
            if await self.publish_parameter(
                self.spec.equipment, self._param_types[signal.spec.name], signal.spec.name, payload
            ):
                self._last_published[signal.spec.name] = value
                published += 1
        return published

    async def run_tier(self, tier: str, interval: float) -> None:
        """Publish `tier` every `interval` seconds until stopped or cancelled."""
        self._running = True
        LOGGER.info("Device %s publishing tier %s every %.1fs", self.device_id, tier, interval)
        try:
            while self._running:
                await self.publish_tier(tier)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            LOGGER.info("Device %s tier %s cancelled", self.device_id, tier)
            raise

    def snapshot(self) -> list[dict[str, Any]]:
        """Describe every signal. Rendered by sub-project B's SignalInspector."""
        return [
            {
                "name": signal.spec.name,
                "shape": signal.spec.shape,
                "unit": signal.spec.unit,
                "precision": signal.spec.precision,
                "range": list(signal.spec.value_range) if signal.spec.value_range else None,
                "limits": dict(signal.spec.limits),
                "params": dict(signal.spec.params),
                "tier": signal.spec.tier,
                "param_type": signal.spec.param_type,
                "value": self.values.get(signal.spec.name),
                "status": signal.status(),
            }
            for signal in self.signals
        ]
```

Add to `devices.py`'s imports:

```python
from uns_simulator.plant import DeviceView
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import build_signal
```

Two things to get right, both load-bearing:
- `super().__init__(spec.id, spec.path, mqtt_config)` passes the `DeviceSpec.path` as the hierarchy, so `publish_parameter`'s existing `self.hierarchy.get_parameter_topic(...)` produces the full 8-level topic with no change to that method.
- `run_tier` re-raises `CancelledError` rather than swallowing it (which is what `PLC.start` does at `devices.py:331`). Swallowing it makes `asyncio.gather` on shutdown hang, and it is not worth reproducing.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/test_devices.py -v`
Expected: all pass, old and new.

- [ ] **Step 5: Fix `SCADA.connected_devices` while in this file**

`devices.py:371` reports `random.randint(5, 10)` as the connected device count — a number that contradicts the ~50 devices this plan creates and that would make the SCADA payload actively misleading. `SCADA.__init__` already has a `self.connected_devices = 0` attribute nobody writes. Make the simulator's real count settable and report it:

```python
        status_data = {
            'system_name': self.system_name,
            'system_status': 'Operational',
            'connected_devices': self.connected_devices,
            'data_points_per_second': random.randint(500, 1500),  # noqa: S311
```

Task 15 sets `scada.connected_devices` from the device inventory. Add a test:

```python
# append to 99_simulator/test/test_devices.py
@pytest.mark.asyncio
async def test_scada_reports_the_real_connected_device_count():
    scada = devices.SCADA(FakeHierarchy(), {})
    scada.connected_devices = 47
    status = await scada.generate_system_status()
    assert status["connected_devices"] == 47  # noqa: PLR2004
```

- [ ] **Step 6: Run the whole suite, lint and commit**

```bash
cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/devices.py 99_simulator/test/test_devices.py
git commit -m "feat(simulator): add SignalDevice publishing declarative signals on cadence tiers"
```

---

## Task 15: Wire the simulator — profile loading, the clock, and one task per tier

The last code task. `run_simulation` currently schedules `device.start(interval)` for every device on one interval (`simulator.py:147-150`). It now runs the `PlantClock` as its own task, evaluates every `SignalDevice` on each tick, and schedules one publish task per `(device, tier)` pair. `PLC`/`SCADA`/`HMI` keep working exactly as they do, so the legacy `plc:` config in `conf/settings.yaml` remains valid.

**Files:**
- Modify: `99_simulator/src/uns_simulator/simulator.py`
- Test: `99_simulator/test/test_simulator.py`

**Interfaces:**
- Consumes: `load_profile`/`LoadedProfile`/`TIER_DEFAULTS` (Task 12), `PlantClock`/`DeviceView` (Tasks 8–9), `SignalDevice` (Task 14).
- Produces on `UnifiedNamespaceSimulator`:
  - `.profile: LoadedProfile | None`, `.clock: PlantClock | None`, `.signal_devices: list[SignalDevice]`.
  - `load_simulator_config(settings_obj: Any) -> dict[str, Any]` — module-level; assembles the mapping `load_profile` expects from the Dynaconf settings object, so tests can call `load_profile` with a plain dict and production goes through this one adapter.
  - `create_signal_devices(self) -> list[SignalDevice]` — builds one `SignalDevice` per `DeviceSpec`, each with its own `DeviceView`.
  - `tick(self, dt: float) -> None` — evaluates every enabled `SignalDevice`. Driven by `_run_clock`.
  - `async _run_clock(self) -> None` — the clock task: advance, evaluate, sleep, in that order.
  - `announce_device_count(self) -> None` — replaces `SCADA`'s random device count with the real one.
  - `status(self) -> dict[str, Any]` — `{profile, seed, device_count, signal_count, tiers, families, per_tier, broker_connected, published_total, failed_total, tick_count}`. Sub-project B's `GET /simulator/status` extends this rather than inventing it.

- [ ] **Step 1: Write the failing tests**

```python
# append to 99_simulator/test/test_simulator.py
from uns_simulator import devices as devices_module
from uns_simulator.models import expand_hierarchy_paths
from uns_simulator.plant import PlantClock
from uns_simulator.profiles import TIER_DEFAULTS, load_profile
from uns_simulator.simulator import UnifiedNamespaceSimulator

HIERARCHY = {
    "enterprise": "CovestroAG",
    "sites": [
        {
            "name": "Dormagen",
            "areas": [
                {
                    "name": "Production",
                    "kind": "production",
                    "lines": [{"name": "Line1", "nameplate_tph": 12.0, "cells": ["Cell1"]}],
                },
                {
                    "name": "Utilities",
                    "kind": "utilities",
                    "lines": [{"name": "Powerhouse", "cells": ["Cell1"]}],
                },
            ],
        }
    ],
}

RAW = {
    "hierarchy": HIERARCHY,
    # `starting_s` of 1 s and no holds, so 30 ticks are enough to reach EXECUTE and stay there.
    "plant": {"lines": {"Dormagen/Production/Line1": {"starting_s": 1.0, "hold_probability_per_hour": 0.0}}},
    "energy": {
        "devices": [
            {
                "id": "MAIN",
                "equipment": "MainIncomer",
                "target": {"kind": "utilities"},
                "tier": "energy",
                "serves": ["Dormagen/Production/Line1"],
                "signals": {
                    "ActivePower": {
                        "shape": "derived",
                        "unit": "kW",
                        "precision": 1,
                        "expr": "80 + ctx.served_production * 320",
                    },
                    "EnergyTotal": {
                        "shape": "counter",
                        "unit": "kWh",
                        "tier": "meter",
                        "precision": 4,
                        "rate": "ActivePower / 3600.0",
                    },
                },
            }
        ]
    },
    "profiles": {"full": {"families": ["energy"]}},
    "simulation": {"seed": 1234, "interval": 5.0, "duration": 0},
}


@pytest.fixture(autouse=True)
def _dummy_broker(monkeypatch):
    """Same pattern as test_devices.py: never touch a real broker."""
    from test.test_devices import DummyClient  # noqa: PLC0415

    monkeypatch.setattr(devices_module.aiomqtt, "Client", DummyClient)


def _sim():
    """A simulator with the profile loaded but `__init__` bypassed.

    `__init__` reads the global Dynaconf `settings`; these tests need a fixture dict instead,
    so they assemble the same attributes by hand. Everything `run_simulation` touches is set.
    """
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sim.mqtt_config = {}
    sim.simulation_config = RAW["simulation"]
    sim.hierarchies = expand_hierarchy_paths(HIERARCHY)
    sim.hierarchy = sim.hierarchies[0]
    sim.plc_templates = []
    sim.equipment_fallback = None
    sim.devices = []
    sim.tasks = []
    sim.profile = load_profile(RAW, "full")
    sim.clock = PlantClock(sim.profile.context, tick_s=1.0)
    sim.signal_devices = sim.create_signal_devices()
    return sim


def test_create_signal_devices_builds_one_device_per_spec():
    sim = _sim()
    assert len(sim.signal_devices) == 1
    device = sim.signal_devices[0]
    assert device.spec.equipment == "MainIncomer"
    assert device.tiers == {"energy", "meter"}


def test_a_utility_device_has_no_line_of_its_own_but_serves_one():
    """MAIN sits in the Utilities area, which spec 6.1 gives no `LineState`."""
    sim = _sim()
    view = sim.signal_devices[0].view
    assert view.site == "Dormagen"
    assert view.line is None
    assert view.served_line_count == 1


def test_tick_evaluates_every_device():
    sim = _sim()
    sim.tick(1.0)
    values = sim.signal_devices[0].values
    assert values["ActivePower"] >= 80.0  # noqa: PLR2004
    assert values["EnergyTotal"] > 0.0


def test_utility_power_follows_the_production_it_serves():
    """The whole point of the plant context: an idle line means an idle chiller."""
    sim = _sim()
    sim.tick(1.0)
    idle_power = sim.signal_devices[0].values["ActivePower"]
    for _ in range(30):
        sim.clock.advance()
        sim.tick(1.0)
    running_power = sim.signal_devices[0].values["ActivePower"]
    # Keyed `<Area>/<Line>` within the site, so `Line1` in two areas cannot collide.
    assert sim.profile.context.sites["Dormagen"].lines["Production/Line1"].state == "EXECUTE"
    # 80 kW idle against 80 + ~0.9 * 320 running: comfortably more than double.
    assert running_power > idle_power * 2


def test_energy_accumulates_monotonically_across_ticks():
    sim = _sim()
    readings = []
    for _ in range(20):
        sim.clock.advance()
        sim.tick(1.0)
        readings.append(sim.signal_devices[0].values["EnergyTotal"])
    assert all(b >= a for a, b in zip(readings, readings[1:], strict=False))
    assert readings[-1] > readings[0]


def test_status_reports_the_loaded_profile():
    sim = _sim()
    status = sim.status()
    assert status["profile"] == "full"
    assert status["seed"] == 1234  # noqa: PLR2004
    assert status["device_count"] == 1
    assert status["signal_count"] == 2  # noqa: PLR2004
    # `full` leaves `tier_scale` at its 1.0 default, so the pre-scaled tiers are the defaults.
    assert status["tiers"]["meter"] == TIER_DEFAULTS["meter"]
    assert status["families"] == {
        "energy": True,
        "water": False,
        "utilities": False,
        "asset_health": False,
        "production": False,
        "safety": False,
    }
    assert status["per_tier"] == {"energy": 1, "meter": 1}
    assert status["published_total"] == 0
    assert status["failed_total"] == 0


@pytest.mark.asyncio
async def test_run_simulation_schedules_the_clock_and_one_task_per_device_tier(monkeypatch):
    sim = _sim()
    monkeypatch.setattr(sim, "create_plc", lambda: [])
    monkeypatch.setattr(sim, "create_scada", lambda: [])
    monkeypatch.setattr(sim, "create_hmi", lambda: [])
    sim.profile.tiers["energy"] = 0.01
    sim.profile.tiers["meter"] = 0.01

    task = asyncio.create_task(sim.run_simulation(0))
    await asyncio.sleep(0.1)
    await sim._stop_simulation()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Both tiers were scheduled, so both signals published even though they run on separate
    # tasks at separate intervals. The last two segments of the eight-level topic are
    # ParameterType/ParameterName.
    published = sim.signal_devices[0].client.published
    topics = {"/".join(topic.split("/")[-2:]) for topic, _ in published}
    assert "ProcessValue/ActivePower" in topics
    assert "ProcessValue/EnergyTotal" in topics


@pytest.mark.asyncio
async def test_a_zero_interval_tier_is_not_scheduled_as_a_busy_loop(monkeypatch):
    """The 'event' tier has interval 0 and publishes on change from the tick, not a loop."""
    sim = _sim()
    monkeypatch.setattr(sim, "create_plc", lambda: [])
    monkeypatch.setattr(sim, "create_scada", lambda: [])
    monkeypatch.setattr(sim, "create_hmi", lambda: [])
    sim.profile.tiers["energy"] = 0.0
    sim.profile.tiers["meter"] = 0.0
    task = asyncio.create_task(sim.run_simulation(0))
    await asyncio.sleep(0.05)
    await sim._stop_simulation()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sim.signal_devices[0].client.published == []


def test_scada_is_told_the_real_device_count():
    sim = _sim()
    sim.devices = [*sim.signal_devices, *sim.create_scada()]
    sim.announce_device_count()
    scada = [d for d in sim.devices if isinstance(d, devices_module.SCADA)]
    assert scada
    assert scada[0].connected_devices == len(sim.signal_devices)
```

The five pre-existing tests in `test_simulator.py` (`resolve_simulation_duration` × 5 and `_run_until` × 2) must stay untouched and green.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_simulator.py -v`
Expected: the seven pre-existing tests pass; the new ones fail on `AttributeError: 'UnifiedNamespaceSimulator' object has no attribute 'create_signal_devices'`.

- [ ] **Step 3: Add the settings adapter and extend `__init__`**

```python
# add to simulator.py, module level
def load_simulator_config(settings_obj: Any) -> dict[str, Any]:
    """Assemble the mapping load_profile expects out of the Dynaconf settings object.

    One adapter, so tests hand load_profile a plain dict and never depend on Dynaconf, and
    production has exactly one place where the two representations meet.
    """
    raw: dict[str, Any] = {
        "hierarchy": settings_obj.get("hierarchy") or {},
        "plant": settings_obj.get("plant") or {},
        "profiles": settings_obj.get("profiles") or {},
        "simulation": settings_obj.get("simulation") or {},
    }
    for family in FAMILIES:
        raw[family] = settings_obj.get(family) or {}
    return raw
```

Extend `UnifiedNamespaceSimulator.__init__` (`simulator.py:35-43`), keeping every existing line:

```python
    def __init__(self, profile_name: str | None = None, seed: int | None = None):
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(settings.hierarchy)
        self.hierarchy = self.hierarchies[0]
        self.plc_templates = list(settings.get("plc") or [])
        self.equipment_fallback = settings.get("equipment.mixer_tank")
        self.devices: list = []
        self.tasks: list[asyncio.Task] = []

        requested = profile_name or self.simulation_config.get("profile", "full")
        self.profile: LoadedProfile = load_profile(load_simulator_config(settings), requested, seed=seed)
        self.clock = PlantClock(self.profile.context, tick_s=float(self.simulation_config.get("tick_s", 1.0)))
        self.signal_devices: list[SignalDevice] = self.create_signal_devices()
        LOGGER.info(
            "Loaded profile %s: %d devices, %d signals across %s",
            self.profile.name,
            self.profile.report.devices,
            self.profile.report.signals,
            ", ".join(sorted(self.profile.report.per_family)) or "no families",
        )
        for warning in self.profile.report.warnings + self.profile.report.unmatched_templates:
            LOGGER.warning("profile %s: %s", self.profile.name, warning)
```

- [ ] **Step 4: Add `create_signal_devices`, `tick`, `status` and `announce_device_count`**

```python
    def create_signal_devices(self) -> list[SignalDevice]:
        """One SignalDevice per resolved DeviceSpec, each with its own read-only view."""
        built: list[SignalDevice] = []
        for spec in self.profile.devices:
            # Only production areas have a LineState (spec 6.1: a compressor house has no
            # batch to be IDLE between), so a utility device's view carries `line=None` and
            # reads production through `serves` instead. The line key is `<Area>/<Line>`,
            # matching how `build_plant_context` registered it.
            line = f"{spec.path.area}/{spec.path.line}" if spec.path.kind == PRODUCTION_KIND else None
            view = DeviceView(self.profile.context, spec.path.site, line, spec.serves)
            built.append(SignalDevice(spec, self.mqtt_config, view, self.profile.seed))
        return built

    def tick(self, dt: float) -> None:
        """Advance every enabled device's signals. Called once per plant tick."""
        for device in self.signal_devices:
            if device.enabled:
                device.evaluate(dt)

    def announce_device_count(self) -> None:
        """Tell every SCADA how many devices actually exist, instead of a random guess."""
        count = len(self.signal_devices)
        for device in self.devices:
            if isinstance(device, SCADA):
                device.connected_devices = count

    def status(self) -> dict[str, Any]:
        """Runtime status. Sub-project B's GET /simulator/status extends this body."""
        per_tier: dict[str, int] = {}
        for device in self.signal_devices:
            for spec in device.spec.signals:
                per_tier[spec.tier] = per_tier.get(spec.tier, 0) + 1
        return {
            "profile": self.profile.name,
            "seed": self.profile.seed,
            "device_count": len(self.signal_devices),
            "signal_count": sum(len(d.spec.signals) for d in self.signal_devices),
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "per_tier": per_tier,
            "broker_connected": any(d.connected for d in self.signal_devices),
            "published_total": sum(d.publish_ok for d in self.signal_devices),
            "failed_total": sum(d.publish_fail for d in self.signal_devices),
            "tick_count": self.clock.tick_count,
        }
```

- [ ] **Step 5: Rewrite the scheduling block in `run_simulation` (`simulator.py:143-150`)**

Replace those eight lines with:

```python
        self.devices = [
            *self.signal_devices,
            *self.create_plc(),
            *self.create_scada(),
            *self.create_hmi(),
        ]
        self.announce_device_count()

        # The clock is a task of its own: it advances the world, and self.tick evaluates
        # every signal on that same advance. Publishing is scheduled separately, per tier.
        self.clock.on_transition(
            lambda site, line, state: LOGGER.info("Plant %s/%s -> %s", site, line, state)
        )
        self.tasks.append(asyncio.create_task(self._run_clock()))

        for device in self.signal_devices:
            for tier in sorted(device.tiers):
                # Already multiplied by the profile's `tier_scale` by `load_profile`, so a
                # slow profile cannot be defeated by forgetting to scale here.
                interval = self.profile.tiers.get(tier, 0.0)
                if interval <= 0.0:
                    # tier 'event' (and any tier explicitly set to 0) publishes on change
                    # from the tick itself; scheduling it would be a busy loop.
                    continue
                self.tasks.append(asyncio.create_task(device.run_tier(tier, interval)))

        # `.get`, not `.interval`: the legacy devices keep the single flat interval, and tests
        # hand this class a plain dict rather than the Dynaconf settings object.
        interval = float(self.simulation_config.get("interval", 5.0))
        for device in self.devices:
            if isinstance(device, SignalDevice):
                continue
            self.tasks.append(asyncio.create_task(device.start(interval)))
```

and add the clock runner:

```python
    async def _run_clock(self) -> None:
        """Advance the plant and evaluate every signal on the same tick."""
        tick_s = self.clock.tick_s
        self.clock.running = True
        try:
            while self.clock.running:
                self.clock.advance()
                self.tick(tick_s)
                await asyncio.sleep(tick_s)
        except asyncio.CancelledError:
            LOGGER.info("Plant clock cancelled")
            raise
        finally:
            self.clock.running = False
```

`_run_clock` rather than `PlantClock.run` because the evaluation has to happen between the advance and the sleep, in that order, on the same tick — that ordering is exactly what `test_energy_accumulates_monotonically_across_ticks` and `test_utility_power_follows_the_production_it_serves` verify. `PlantClock.run` stays as the standalone loop its own tests cover and as the entry point sub-project B can drive while paused.

It loops on `self.clock.running` rather than `while True` for the same reason the legacy devices loop on their own flag: `_stop_simulation` gathers `self.tasks` **without cancelling them**, so a task that never returns would hang the shutdown. Which is the next step.

- [ ] **Step 6: Stop the clock in `_stop_simulation` (`simulator.py:159-165`)**

`_stop_simulation` currently stops the devices and then gathers. Add the clock, before the gather:

```python
    async def _stop_simulation(self):
        """Cleanly stop all devices"""
        self.clock.stop()
        for device in self.devices:
            await device.stop()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
```

One line, and it is the line that makes `await sim._stop_simulation()` in the two `run_simulation` tests return instead of hanging until the pytest timeout. `SignalDevice.stop()` (Task 14) already ends its `run_tier` loops the same way.

Add to `simulator.py`'s imports:

```python
from uns_simulator.devices import HMI, PLC, SCADA, SignalDevice
from uns_simulator.plant import DeviceView, PlantClock
from uns_simulator.profiles import FAMILIES, PRODUCTION_KIND, LoadedProfile, load_profile
```

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -v`
Expected: everything passes. `test_a_zero_interval_tier_is_not_scheduled_as_a_busy_loop` is the guard that a tier interval of 0 never becomes `asyncio.sleep(0)` in a `while True`.

- [ ] **Step 8: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/simulator.py 99_simulator/test/test_simulator.py
git commit -m "feat(simulator): run the plant clock and schedule publishing per cadence tier"
```

---

## Task 16: `conf/simulator/` on disk — the file reader, `plant.yaml`, `energy.yaml`, `water.yaml`

Every task so far has been driven by dict fixtures. This one puts the real plant on disk and connects the loader to it. Spec §7.1 is explicit that `profiles.py` reads these files itself rather than through `uns_config.get_settings()`, which hardcodes `settings_files=["settings.yaml", ".secrets.yaml"]` for all nine modules — widening that list for one module's benefit would change config loading platform-wide.

The two families in this task are the ones spec §8 leads with, and between them they prove the whole correlation claim end to end: a main incomer whose kW follows `ctx.served_production`, and a cooling tower whose ΔT follows `ctx.served_heat_load` with the first-order lag Task 7 built.

**Files:**
- Create: `conf/simulator/plant.yaml`, `conf/simulator/energy.yaml`, `conf/simulator/water.yaml`
- Modify: `99_simulator/src/uns_simulator/profiles.py`, `99_simulator/src/uns_simulator/simulator.py`, `99_simulator/pyproject.toml`
- Test: `99_simulator/test/test_conf_files.py`

**Interfaces:**
- Consumes: `FAMILIES` / `load_profile` (Task 12), `load_simulator_config` (Task 15), `uns_config.resolve_conf_dir`.
- Produces, in `profiles.py`:
  - `SIMULATOR_CONF_SUBDIR: Final[str] = "simulator"` — the directory under `conf/`.
  - `read_simulator_conf(conf_dir: Path | None = None) -> dict[str, Any]` — reads `<conf_dir>/simulator/plant.yaml` plus one file per family into exactly the mapping `load_profile` consumes. `conf_dir` defaults to `resolve_conf_dir()`. The parameter exists so tests read a `tmp_path` and so sub-project B's `PUT /simulator/profile` can reload from an explicit directory.
  - `load_simulator_config(settings_obj: Any, conf_dir: Path | None = None) -> dict[str, Any]` — Task 15's adapter, now overlaying the files on top of the Dynaconf values.

Three rules fix `read_simulator_conf`'s behaviour, and each one is a test below:

| Situation | Behaviour | Why |
|---|---|---|
| `conf/simulator/` or a family file is absent | Skipped silently | Spec §14's mitigation is "land and validate one family at a time", and spec §12 promises a deployment with no `conf/simulator/` still runs off `simulator.hierarchy` in `settings.yaml`. Both need absence to be ordinary. |
| A file exists but its top level is not a mapping | `ValueError` naming the file | A YAML file that parses to a list or a string is a typo, not a configuration choice, and the alternative is an empty family nobody can explain. |
| `plant.yaml` is present | Its `plant` and `profiles` keys are lifted out; **everything else** becomes `hierarchy` | `plant.yaml` writes `enterprise:` and `sites:` at the top level (spec §7.2) while `load_profile` wants them under `hierarchy`. Lifting by exclusion rather than by an allow-list means a future hierarchy key needs no change here. |

### Why a new dependency

`read_simulator_conf` needs a plain YAML parser. Dynaconf has loaders, but only for its own settings files, and `ruamel-yaml` is in `uv.lock` solely as a transitive dependency of the `safety` dev tool — depending on it from runtime code would be depending on an accident. Add `pyyaml` explicitly.

- [ ] **Step 1: Add the dependency**

In `99_simulator/pyproject.toml`, in the `[project]` `dependencies` list, after `"dynaconf~=3.2",`:

```toml
    "pyyaml~=6.0",
```

Then:

```bash
cd 99_simulator && uv lock && uv sync --all-groups
```

- [ ] **Step 2: Write the failing test file**

```python
# 99_simulator/test/test_conf_files.py
"""The real conf/simulator/*.yaml files, loaded from disk.

Every other suite hands `load_profile` a dict, which is what keeps them fast and
hermetic - and also what makes them blind to the files that actually ship. This is the
only place that would notice a family file nobody wrote, a device that lost half its
signals in transcription, or a `serves` path naming a line the hierarchy renamed.

The two tables are the point of the file. Asserting a single total device count would
pass just as happily on a wrong total that I miscomputed; a count per template cannot,
because a missing device names itself.
"""

from pathlib import Path

import pytest

from uns_simulator.profiles import load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"

# Signals declared by each device template, per spec 8.1-8.2. Tasks 17 and 18 extend
# these tables as they add family files; a family named in a profile whose file does not
# exist yet contributes nothing and is not an error, which is spec 14's
# land-one-family-at-a-time mitigation working as intended.
EXPECTED_SIGNAL_COUNT = {
    "energy": {"EM-01": 17, "EM-02": 17, "TR-01": 6, "MCC-01": 6, "MCC-02": 6},
    "water": {"FM-01": 5, "DEMIN-01": 6, "CT-01": 11, "CT-02": 11, "EFF-01": 9},
}

# Hierarchy paths each template expands to under the `full` profile. Anything other than
# 1 is a template deliberately left site-agnostic: FM-01 has no `serves`, so one entry
# can serve both sites' raw water intakes.
EXPECTED_DEVICE_COUNT = {
    "energy": {"EM-01": 1, "EM-02": 1, "TR-01": 1, "MCC-01": 1, "MCC-02": 1},
    "water": {"FM-01": 2, "DEMIN-01": 1, "CT-01": 1, "CT-02": 1, "EFF-01": 1},
}

FAMILY_TEMPLATES = [
    (family, template_id, count)
    for family, table in EXPECTED_SIGNAL_COUNT.items()
    for template_id, count in table.items()
]


@pytest.fixture(scope="module")
def raw():
    return read_simulator_conf(CONF_DIR)


def test_plant_yaml_supplies_the_hierarchy_at_the_top_level(raw):
    """Spec 7.2 writes `enterprise:` and `sites:` at the top of plant.yaml."""
    assert raw["hierarchy"]["enterprise"] == "CovestroAG"
    assert [site["name"] for site in raw["hierarchy"]["sites"]] == ["Dormagen", "Krefeld"]
    assert "profiles" not in raw["hierarchy"]
    assert "plant" not in raw["hierarchy"]


def test_both_shipped_profiles_are_declared(raw):
    assert set(raw["profiles"]) == {"small", "full"}
    assert raw["profiles"]["small"]["tier_scale"] == 6.0  # noqa: PLR2004
    assert raw["profiles"]["small"]["sites"] == ["Dormagen"]
    assert raw["profiles"]["small"]["max_cells_per_line"] == 1
    assert raw["profiles"]["full"]["sites"] == ["Dormagen", "Krefeld"]


def test_a_serves_list_never_names_another_sites_lines(raw):
    """A copied template with a Dormagen `serves` list is the mistake this catches.

    `load_profile` rejects a `serves` path that resolves to nothing, but Dormagen's lines
    do resolve - so a Krefeld meter carrying them would correlate against the wrong site's
    production and load perfectly cleanly. Only the site prefix betrays it.
    """
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            site = (template.get("target") or {}).get("site")
            if site is None:
                continue  # covered by the next test instead
            for served in template.get("serves") or []:
                assert served.startswith(f"{site}/"), f"{template['id']} serves {served} but sits on {site}"


def test_a_template_carrying_serves_never_replicates(raw):
    """The other half of the guard above, for templates that omit `target.site`.

    `TR-01` and `MCC-01` leave `site` out because `Transformer_T1` and `MCC_Production` are
    Dormagen-only cell names. If a Krefeld cell were ever given one of those names they
    would replicate silently, and the copy would carry Dormagen's `serves` list. A device
    count of 1 is what rules that out, so it is asserted rather than left to the table.
    """
    for family, table in EXPECTED_DEVICE_COUNT.items():
        for template in raw[family]["devices"]:
            if template.get("serves"):
                assert table[str(template["id"])] == 1, f"{template['id']} carries `serves` and replicates"


@pytest.mark.parametrize(("family", "template_id", "expected"), FAMILY_TEMPLATES)
def test_each_template_declares_the_expected_signal_count(raw, family, template_id, expected):
    by_id = {str(template["id"]): template for template in raw[family]["devices"]}
    assert len(by_id[template_id]["signals"]) == expected


def test_the_family_files_declare_exactly_the_expected_templates(raw):
    for family, table in EXPECTED_SIGNAL_COUNT.items():
        declared = [str(template["id"]) for template in raw[family]["devices"]]
        assert sorted(declared) == sorted(table), f"{family}.yaml template ids drifted from the table"
        assert len(declared) == len(set(declared)), f"{family}.yaml declares a duplicate id"


def test_every_signal_in_every_family_file_declares_a_unit(raw):
    """`expand_template` enforces this too; this test names the file and the signal."""
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            for name, signal in template["signals"].items():
                unit = (signal or {}).get("unit")
                assert unit is not None and str(unit).strip(), f"{family}.yaml {template['id']}/{name} has no unit"


def test_the_full_profile_loads_from_disk_with_the_expected_device_count(raw):
    profile = load_profile(raw, "full")
    expected = sum(count for table in EXPECTED_DEVICE_COUNT.values() for count in table.values())
    assert profile.report.devices == expected
    assert profile.report.warnings == []
    assert profile.report.unmatched_templates == []


def test_the_full_profile_signal_count_is_the_table_multiplied_out(raw):
    profile = load_profile(raw, "full")
    expected = sum(
        EXPECTED_SIGNAL_COUNT[family][template_id] * EXPECTED_DEVICE_COUNT[family][template_id]
        for family, table in EXPECTED_SIGNAL_COUNT.items()
        for template_id in table
    )
    assert profile.report.signals == expected


def test_the_small_profile_drops_krefeld_and_the_second_cell(raw):
    small = load_profile(raw, "small")
    full = load_profile(raw, "full")
    assert small.report.devices < full.report.devices
    assert {device.path.site for device in small.devices} == {"Dormagen"}
    assert small.tiers["process"] == pytest.approx(30.0), "5 s process tier times a tier_scale of 6"


def test_loading_the_same_directory_twice_gives_identical_reports(raw):
    """Spec 5.3: the seed is the only source of variation, and the files do not carry one."""
    assert load_profile(raw, "full").report.as_dict() == load_profile(read_simulator_conf(CONF_DIR), "full").report.as_dict()


def test_an_absent_conf_directory_is_not_an_error(tmp_path):
    """Spec 12: a deployment with no conf/simulator still runs off settings.yaml."""
    assert read_simulator_conf(tmp_path) == {}


def test_an_absent_family_file_is_skipped(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "plant.yaml").write_text("enterprise: E\nsites: []\n", encoding="utf-8")
    raw = read_simulator_conf(tmp_path)
    assert raw["hierarchy"] == {"enterprise": "E", "sites": []}
    assert "energy" not in raw


def test_a_family_file_that_is_not_a_mapping_is_rejected_by_name(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "energy.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="energy.yaml"):
        read_simulator_conf(tmp_path)
```

- [ ] **Step 3: Run the test file to verify it fails**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -x`
Expected: collection error — `ImportError: cannot import name 'read_simulator_conf' from 'uns_simulator.profiles'`.

- [ ] **Step 4: Implement the reader**

Add to the top of `profiles.py`:

```python
from pathlib import Path

import yaml
from uns_config import resolve_conf_dir
```

and at the end of the file:

```python
SIMULATOR_CONF_SUBDIR: Final = "simulator"

# Everything in plant.yaml that is *not* one of these is hierarchy. Lifting by exclusion
# rather than by an allow-list means a future hierarchy key needs no change here.
_PLANT_NON_HIERARCHY_KEYS: Final = frozenset({"plant", "profiles"})


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    """Parse one file, or None if it is absent. A non-mapping top level is fatal."""
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{path.name}: expected a YAML mapping at the top level, got {type(loaded).__name__}")
    return dict(loaded)


def read_simulator_conf(conf_dir: Path | None = None) -> dict[str, Any]:
    """Read conf/simulator/*.yaml into the mapping `load_profile` consumes.

    Not routed through `uns_config.get_settings()`: that function hardcodes
    `settings_files=["settings.yaml", ".secrets.yaml"]` for all nine modules, so widening
    it for the simulator's benefit would change config loading platform-wide (spec 7.1).

    Absent files are skipped rather than defaulted. That is what lets spec 14's
    land-one-family-at-a-time work, and what keeps spec 12's promise that a deployment
    with no conf/simulator/ still runs off `simulator.hierarchy` in settings.yaml.
    """
    directory = (conf_dir if conf_dir is not None else resolve_conf_dir()) / SIMULATOR_CONF_SUBDIR
    raw: dict[str, Any] = {}

    if (plant_doc := _read_yaml_mapping(directory / "plant.yaml")) is not None:
        raw["hierarchy"] = {key: value for key, value in plant_doc.items() if key not in _PLANT_NON_HIERARCHY_KEYS}
        raw["plant"] = plant_doc.get("plant") or {}
        raw["profiles"] = plant_doc.get("profiles") or {}

    for family in FAMILIES:
        if (family_doc := _read_yaml_mapping(directory / f"{family}.yaml")) is not None:
            raw[family] = family_doc

    LOGGER.info("Read simulator configuration from %s: %s", directory, ", ".join(sorted(raw)) or "nothing")
    return raw
```

`Mapping` is already imported in `profiles.py` from Task 11; `Final` and `Any` from Task 12. `resolve_conf_dir` is exported from `uns_config` (`00_uns_config/src/uns_config/loader.py:34`) and is how every other module finds `conf/`, so the simulator does not invent its own search.

- [ ] **Step 5: Overlay the files on the Dynaconf settings**

Replace Task 15's `load_simulator_config` in `simulator.py`:

```python
def load_simulator_config(settings_obj: Any, conf_dir: Path | None = None) -> dict[str, Any]:
    """Assemble the mapping load_profile expects, files layered over Dynaconf.

    One adapter, so tests hand load_profile a plain dict and never depend on Dynaconf, and
    production has exactly one place where the two representations meet.

    `conf/simulator/*.yaml` wins over `settings.yaml` key by key, and only where the file
    supplies something. Whole-mapping replacement would be wrong in one direction and a
    deep merge wrong in the other: `simulation` only ever lives in settings.yaml, and a
    `hierarchy` half from each file would be a plant nobody authored. Per-key overlay is
    what keeps spec 12's promise that an untouched deployment with no conf/simulator/
    behaves exactly as it does today.
    """
    raw: dict[str, Any] = {
        "hierarchy": settings_obj.get("hierarchy") or {},
        "plant": settings_obj.get("plant") or {},
        "profiles": settings_obj.get("profiles") or {},
        "simulation": settings_obj.get("simulation") or {},
    }
    for family in FAMILIES:
        raw[family] = settings_obj.get(family) or {}
    for key, value in read_simulator_conf(conf_dir).items():
        if value:
            raw[key] = value
    return raw
```

Add `from pathlib import Path` and `read_simulator_conf` to `simulator.py`'s imports:

```python
from uns_simulator.profiles import FAMILIES, PRODUCTION_KIND, LoadedProfile, load_profile, read_simulator_conf
```

Then amend the two lines of `__init__` that Task 15 left reading Dynaconf directly, so the legacy devices and the signal devices cannot disagree about what the plant is:

```python
        raw_config = load_simulator_config(settings)
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(raw_config["hierarchy"])
        self.hierarchy = self.hierarchies[0]
```

and pass the same mapping to `load_profile` instead of rebuilding it:

```python
        self.profile: LoadedProfile = load_profile(raw_config, requested, seed=seed)
```

Without this, `SCADA` and `HMI` would publish under `settings.yaml`'s hierarchy while every `SignalDevice` published under `plant.yaml`'s — two plants in one topic tree, and nothing would fail to make it visible.

- [ ] **Step 6: Write `conf/simulator/plant.yaml`**

Spec §7.2 leaves Krefeld as a comment ("reduced mirror: Production/Line1/Cell1 plus PowerDistribution, WaterTreatment, CompressedAir, GasDetection, WeatherStation"). Write it out. A commented-out site cannot be targeted, cannot appear in a `serves` path, and cannot be counted by a test — and `full`'s `sites: [Dormagen, Krefeld]` would resolve to one site while claiming two.

```yaml
# conf/simulator/plant.yaml
#
# The whole plant: every site, area, line and cell, plus the profiles that narrow it.
# Read by uns_simulator.profiles.read_simulator_conf, NOT by Dynaconf (spec 7.1), so there
# are no environment sections here and no secrets.
#
# `kind` on an area is what keeps production templates out of utility areas: a device
# template with no `target` matches cells in `kind: production` areas only.

enterprise: CovestroAG

sites:
  - name: Dormagen
    areas:
      - name: Production
        kind: production
        lines:
          - name: Line1
            nameplate_tph: 12.0
            cells: [Cell1, Cell2]
          - name: Line2
            nameplate_tph: 8.0
            cells: [Cell1]
      - name: Utilities
        kind: utilities
        lines:
          - name: PowerDistribution
            cells: [MainIncomer, Transformer_T1, MCC_Production, MCC_Utilities]
          - name: WaterTreatment
            cells: [RawWaterIntake, DeminPlant, CoolingTower1, EffluentOutfall]
          - name: CompressedAir
            cells: [Compressor_C1, Compressor_C2, AirDryer, AirHeader]
          - name: SteamPlant
            cells: [Boiler_B1, SteamHeader, CondensateReturn]
          - name: Nitrogen
            cells: [N2Generator, N2Header]
          - name: HVAC
            cells: [AHU_01, ChillerPlant]
      - name: Safety
        kind: utilities
        lines:
          - name: GasDetection
            cells: [GD_Zone1, GD_Zone2]
          - name: Emissions
            cells: [Stack_S1]
          - name: WeatherStation
            cells: [WS_01]
      - name: Quality
        kind: utilities
        lines:
          - name: Lab
            cells: [LIMS_01]

  # Spec 7.2's reduced mirror, written out rather than left as a comment: a `serves` path
  # and a device count have to resolve against something real.
  - name: Krefeld
    areas:
      - name: Production
        kind: production
        lines:
          - name: Line1
            nameplate_tph: 5.0
            cells: [Cell1]
      - name: Utilities
        kind: utilities
        lines:
          - name: PowerDistribution
            cells: [MainIncomer]
          - name: WaterTreatment
            cells: [RawWaterIntake, CoolingTower1]
          - name: CompressedAir
            cells: [Compressor_C1, AirHeader]
      - name: Safety
        kind: utilities
        lines:
          - name: GasDetection
            cells: [GD_Zone1]
          - name: WeatherStation
            cells: [WS_01]

# Per-site ambient and tariff, per-line PackML timing. Keys map onto SiteState's keyword
# arguments and LineTiming's fields; anything absent keeps its default. A `lines` key that
# names no production line anywhere in the hierarchy fails the load, so this block cannot
# quietly describe a line that was renamed.
plant:
  sites:
    Dormagen:
      ambient_mean_c: 11.0
      ambient_swing_c: 9.0
      tariff_peak_hours: [7, 21]
    Krefeld:
      ambient_mean_c: 11.5
      ambient_swing_c: 8.0
      tariff_peak_hours: [7, 21]
  lines:
    # Line1 runs long batches; Line2 is the short-batch line, so it cycles through
    # STARTING and COMPLETING far more often and is the one that exercises the ramps.
    Dormagen/Production/Line1:
      execute_s: 3600.0
      hold_probability_per_hour: 2.0
    Dormagen/Production/Line2:
      execute_s: 1200.0
      completing_s: 45.0
      resetting_s: 30.0
      hold_probability_per_hour: 3.0
    Krefeld/Production/Line1:
      execute_s: 5400.0
      hold_probability_per_hour: 1.0

profiles:
  # `small` is the shipped default. Spec 9: `full` is roughly 100 msg/s, and the graphdb
  # mapper MERGEs per topic level on every message, so `full` is opt-in via
  # `simulation.profile` rather than the default.
  small:
    tier_scale: 6.0
    sites: [Dormagen]
    families: [energy, water, production]
    max_cells_per_line: 1
  full:
    tier_scale: 1.0
    sites: [Dormagen, Krefeld]
    families: [energy, water, utilities, asset_health, production, safety]
```

Both `families` lists are spec §7.2's final lists, naming families whose files Tasks 17 and 18 have yet to write. That is deliberate and it is not a placeholder: `load_profile` iterates `FAMILIES` and skips a family with no `devices` (Task 12, Step 4), so an unwritten family contributes zero devices and no error. Writing the final lists once means `plant.yaml` is authored exactly once, and the test tables — not the profile — are what each later task extends.

- [ ] **Step 7: Write `conf/simulator/energy.yaml`**

Three things worth understanding before transcribing, because they are the difference between a plant model and 52 independent random walks:

1. **`ActivePower` is the only primary signal on a meter.** `ReactivePower`, `ApparentPower`, `PowerFactor` and the three phase currents are `derived` from it, so a production hold moves all seven together and the power triangle stays internally consistent. Deriving `PowerFactor` from two signals that were each walking independently would produce a power factor that violates its own definition.
2. **A device declares `serves` only if it genuinely feeds those lines.** `MCC_Utilities` feeds the utility side, has no production line under it, and so gets an `ou_walk` and no `serves`. Handing it a `serves` it does not have would make it track production it does not feed — worse than not correlating at all, because it looks correct.
3. **A template naming no `site` replicates to every matching cell.** `Transformer_T1` is a Dormagen-only cell name, so `TR-01`'s `target` omits `site` and still resolves to exactly one device. `EM-01` and `EM-02` *do* name their site, because a `serves` list is site-specific and cannot be shared — which is also why the two meters are written out in full rather than sharing a YAML anchor. An anchor would give Krefeld Dormagen's 1450 kW connected load, and since `range` and `limits` drive `status`, a wrong rating shows up as a permanently alarming meter.

```yaml
# conf/simulator/energy.yaml
# Spec 8.1. Electrical metering: incomer, transformer, two motor control centres.
# ActivePower is the only primary signal on a meter; the rest of the power triangle is
# derived from it, so the seven values stay mutually consistent on every tick.

devices:
  - id: EM-01
    equipment: EM-01
    target: {site: Dormagen, area: Utilities, line: PowerDistribution, cell: MainIncomer}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: energy
    signals:
      ActivePower:
        shape: derived
        unit: kW
        expr: base_load + ctx.served_production * connected_kw
        params: {base_load: 220.0, connected_kw: 1450.0}
        precision: 1
        range: [0, 2000]
        limits: {hi: 1800, hihi: 1950}
        export_metric: true
      ReactivePower:
        shape: derived
        unit: kVAr
        expr: ActivePower * tan_phi
        params: {tan_phi: 0.44}
        precision: 1
        range: [0, 1200]
      ApparentPower:
        shape: derived
        unit: kVA
        expr: sqrt(ActivePower * ActivePower + ReactivePower * ReactivePower)
        precision: 1
        range: [0, 2400]
      PowerFactor:
        # max(..., 1.0) rather than a raw divide: at a dead plant both powers are zero and
        # this is a division by zero, not a small number.
        shape: derived
        unit: "1"
        expr: ActivePower / max(ApparentPower, 1.0)
        precision: 3
        range: [0, 1]
        limits: {lo: 0.9, lolo: 0.85}
      VoltageL1:
        shape: ou_walk
        unit: V
        mean: 400.0
        sigma: 1.2
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL2:
        shape: ou_walk
        unit: V
        mean: 399.4
        sigma: 1.2
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL3:
        shape: ou_walk
        unit: V
        mean: 400.6
        sigma: 1.2
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      CurrentL1:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL1, 1.0))
        precision: 1
        range: [0, 3500]
      CurrentL2:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL2, 1.0))
        precision: 1
        range: [0, 3500]
      CurrentL3:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL3, 1.0))
        precision: 1
        range: [0, 3500]
      Frequency:
        shape: ou_walk
        unit: Hz
        mean: 50.0
        sigma: 0.015
        tau: 30.0
        precision: 3
        range: [49.0, 51.0]
        limits: {lo: 49.8, hi: 50.2}
      VoltageThd:
        shape: ou_walk
        unit: "%"
        mean: 2.4
        sigma: 0.35
        tau: 180.0
        precision: 2
        range: [0, 12]
        limits: {hi: 5.0, hihi: 8.0}
      EnergyTotal:
        # kW divided by 3600 is kWh per second, and `rate` is per second. Getting this
        # wrong by 3600 is the easiest mistake in the file and the hardest to spot: the
        # register still rises monotonically, just absurdly fast.
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 84000.0
        tier: meter
        precision: 1
        export_metric: true
      ReactiveEnergyTotal:
        shape: counter
        unit: kVArh
        rate: ReactivePower / 3600.0
        initial: 31000.0
        tier: meter
        precision: 1
      PeakDemand:
        shape: window_agg
        unit: kW
        source: ActivePower
        agg: max
        window_s: 900.0
        tier: meter
        precision: 1
      EnergyIntensity:
        # kWh per tonne. The 0.1 floor is not cosmetic: an idle line makes the true
        # intensity infinite, and a topic reporting 1/0 is worse than one reporting the
        # intensity a very slow line would have.
        shape: derived
        unit: kWh/t
        expr: ActivePower / max(ctx.served_throughput_tph, 0.1)
        tier: meter
        precision: 2
        range: [0, 2000]
      CarbonRate:
        shape: derived
        unit: kgCO2/h
        expr: ActivePower * ctx.grid_co2_g_per_kwh / 1000.0
        precision: 2
        range: [0, 900]

  - id: EM-02
    equipment: EM-02
    target: {site: Krefeld, area: Utilities, line: PowerDistribution, cell: MainIncomer}
    serves: [Krefeld/Production/Line1]
    tier: energy
    signals:
      ActivePower:
        shape: derived
        unit: kW
        expr: base_load + ctx.served_production * connected_kw
        params: {base_load: 90.0, connected_kw: 520.0}
        precision: 1
        range: [0, 800]
        limits: {hi: 700, hihi: 760}
        export_metric: true
      ReactivePower:
        shape: derived
        unit: kVAr
        expr: ActivePower * tan_phi
        params: {tan_phi: 0.48}
        precision: 1
        range: [0, 500]
      ApparentPower:
        shape: derived
        unit: kVA
        expr: sqrt(ActivePower * ActivePower + ReactivePower * ReactivePower)
        precision: 1
        range: [0, 1000]
      PowerFactor:
        shape: derived
        unit: "1"
        expr: ActivePower / max(ApparentPower, 1.0)
        precision: 3
        range: [0, 1]
        limits: {lo: 0.9, lolo: 0.85}
      VoltageL1:
        shape: ou_walk
        unit: V
        mean: 400.0
        sigma: 1.4
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL2:
        shape: ou_walk
        unit: V
        mean: 400.8
        sigma: 1.4
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      VoltageL3:
        shape: ou_walk
        unit: V
        mean: 399.2
        sigma: 1.4
        tau: 45.0
        precision: 1
        range: [370, 430]
        limits: {lo: 380, hi: 420}
      CurrentL1:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL1, 1.0))
        precision: 1
        range: [0, 1500]
      CurrentL2:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL2, 1.0))
        precision: 1
        range: [0, 1500]
      CurrentL3:
        shape: derived
        unit: A
        expr: ApparentPower * 1000.0 / (sqrt(3.0) * max(VoltageL3, 1.0))
        precision: 1
        range: [0, 1500]
      Frequency:
        shape: ou_walk
        unit: Hz
        mean: 50.0
        sigma: 0.015
        tau: 30.0
        precision: 3
        range: [49.0, 51.0]
        limits: {lo: 49.8, hi: 50.2}
      VoltageThd:
        shape: ou_walk
        unit: "%"
        mean: 2.8
        sigma: 0.4
        tau: 180.0
        precision: 2
        range: [0, 12]
        limits: {hi: 5.0, hihi: 8.0}
      EnergyTotal:
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 29500.0
        tier: meter
        precision: 1
        export_metric: true
      ReactiveEnergyTotal:
        shape: counter
        unit: kVArh
        rate: ReactivePower / 3600.0
        initial: 11200.0
        tier: meter
        precision: 1
      PeakDemand:
        shape: window_agg
        unit: kW
        source: ActivePower
        agg: max
        window_s: 900.0
        tier: meter
        precision: 1
      EnergyIntensity:
        shape: derived
        unit: kWh/t
        expr: ActivePower / max(ctx.served_throughput_tph, 0.1)
        tier: meter
        precision: 2
        range: [0, 2000]
      CarbonRate:
        shape: derived
        unit: kgCO2/h
        expr: ActivePower * ctx.grid_co2_g_per_kwh / 1000.0
        precision: 2
        range: [0, 400]

  - id: TR-01
    equipment: TR-01
    # No `site`: Transformer_T1 is a Dormagen-only cell name, so the cell is the selector.
    target: {area: Utilities, line: PowerDistribution, cell: Transformer_T1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: energy
    signals:
      LoadPercent:
        shape: derived
        unit: "%"
        expr: idle_pct + ctx.served_production * span_pct
        params: {idle_pct: 14.0, span_pct: 62.0}
        precision: 1
        range: [0, 120]
        limits: {hi: 95, hihi: 110}
      OilTemperature:
        # Spec 8.1: rises with load and with ambient. Ambient sets the floor the oil can
        # never cool below; load sets how far above that floor it sits.
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 48.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 85, hihi: 95}
      WindingTemperature:
        shape: derived
        unit: "°C"
        expr: OilTemperature + hotspot_k * LoadPercent / 100.0
        params: {hotspot_k: 22.0}
        precision: 1
        range: [-20, 150]
        limits: {hi: 105, hihi: 120}
      TapPosition:
        # `weights` rather than a repeated 0 in `choices`: both bias the draw towards the
        # nominal tap, but only one of them says so.
        shape: stepped
        unit: "1"
        choices: [-2, -1, 0, 1, 2]
        weights: [1, 2, 6, 2, 1]
        dwell_s: 3600.0
        tier: status
        param_type: Status
        precision: 0
      CoolingFanStatus:
        # Spec 8.1 says stepped, and stepped's `source` reads `ctx`, not siblings - so this
        # cannot be driven from OilTemperature and is an honest dwell-timer discrete rather
        # than a fake correlation. The temperature signals above carry the load story.
        shape: stepped
        unit: "1"
        choices: ["Off", "Stage1", "Stage2"]
        weights: [4, 3, 1]
        dwell_s: 900.0
        tier: status
        param_type: Status
      EnergyThroughput:
        shape: counter
        unit: kWh
        rate: LoadPercent * rated_kva / 100.0 / 3600.0
        params: {rated_kva: 2500.0}
        initial: 156000.0
        tier: meter
        precision: 1

  - id: MCC-01
    equipment: MCC-01
    target: {area: Utilities, line: PowerDistribution, cell: MCC_Production}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: energy
    signals:
      ActivePower:
        shape: derived
        unit: kW
        expr: base_load + ctx.served_production * connected_kw
        params: {base_load: 35.0, connected_kw: 610.0}
        precision: 1
        range: [0, 800]
        limits: {hi: 700, hihi: 760}
      Current:
        shape: derived
        unit: A
        expr: ActivePower * 1000.0 / (sqrt(3.0) * nominal_v * pf)
        params: {nominal_v: 400.0, pf: 0.91}
        precision: 1
        range: [0, 1400]
      EnergyTotal:
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 42000.0
        tier: meter
        precision: 1
      FeederTripCount:
        # `rate` is per second, so this is about one trip a fortnight. A counter rather
        # than an event because what a maintenance engineer asks for is the running total.
        shape: counter
        unit: "1"
        rate: 0.0000008
        initial: 3.0
        tier: meter
        precision: 0
      InsulationResistance:
        shape: ou_walk
        unit: "MΩ"
        mean: 180.0
        sigma: 12.0
        tau: 3600.0
        precision: 1
        range: [0, 500]
        limits: {lo: 50, lolo: 20}
      BusbarTemperature:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * ctx.served_production
        params: {rise_k: 26.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 70, hihi: 85}

  - id: MCC-02
    equipment: MCC-02
    # No `serves`: this centre feeds the utility side, so there is no production for its
    # load to follow and an ou_walk is the honest shape.
    target: {area: Utilities, line: PowerDistribution, cell: MCC_Utilities}
    tier: energy
    signals:
      ActivePower:
        shape: ou_walk
        unit: kW
        mean: 310.0
        sigma: 18.0
        tau: 240.0
        precision: 1
        range: [0, 600]
        limits: {hi: 520, hihi: 560}
      Current:
        shape: derived
        unit: A
        expr: ActivePower * 1000.0 / (sqrt(3.0) * nominal_v * pf)
        params: {nominal_v: 400.0, pf: 0.89}
        precision: 1
        range: [0, 1100]
      EnergyTotal:
        shape: counter
        unit: kWh
        rate: ActivePower / 3600.0
        initial: 61000.0
        tier: meter
        precision: 1
      FeederTripCount:
        shape: counter
        unit: "1"
        rate: 0.0000005
        initial: 1.0
        tier: meter
        precision: 0
      InsulationResistance:
        shape: ou_walk
        unit: "MΩ"
        mean: 165.0
        sigma: 14.0
        tau: 3600.0
        precision: 1
        range: [0, 500]
        limits: {lo: 50, lolo: 20}
      BusbarTemperature:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * ActivePower / rated_kw
        params: {rise_k: 24.0, rated_kw: 600.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 70, hihi: 85}
```

- [ ] **Step 8: Write `conf/simulator/water.yaml`**

Two decisions to carry over from the energy file, plus one that is specific to water:

- **`CT-01` and `CT-02` are per-site**, because `ReturnTemp` derives from `ctx.served_heat_load` and that needs a site-specific `serves` list. `served_heat_load` is a **sum** over served lines, each in 0–1 (Task 8), so Dormagen's two lines give 0–2 and Krefeld's one gives 0–1. Each tower therefore carries a `served_lines` parameter and divides by it — without that, Krefeld's tower would run at half the ΔT for the same relative load, and the two sites' numbers would not be comparable.
- **`FM-01` is site-agnostic and has no `serves`.** Raw water intake sits behind storage, so it does not track production tick for tick; an `ou_walk` is the honest shape and one template covers both sites' `RawWaterIntake` cells.
- **The cooling tower is where the weather station earns its place.** `SupplyTemp` is the wet-bulb temperature plus an approach that widens under load, so a hot humid afternoon degrades cooling exactly as it does in a real plant. `ApproachTemp` then derives back off `ctx.wet_bulb_temp_c` and varies rather than being a restated constant.

```yaml
# conf/simulator/water.yaml
# Spec 8.2. Raw water, demineralisation, cooling tower, effluent.
# The tower is the correlation showcase: heat load (a lagged follower of production, Task
# 7) sets its delta T, and the site wet-bulb temperature sets the supply temperature it
# can achieve at all.

devices:
  - id: FM-01
    equipment: FM-01
    # No `site` and no `serves`: intake sits behind storage, so it does not follow
    # production tick for tick, and one template covers both sites' intakes.
    target: {area: Utilities, line: WaterTreatment, cell: RawWaterIntake}
    tier: process
    signals:
      FlowRate:
        shape: ou_walk
        unit: "m³/h"
        mean: 145.0
        sigma: 6.0
        tau: 300.0
        precision: 2
        range: [0, 300]
        limits: {hi: 260, hihi: 285}
        export_metric: true
      VolumeTotal:
        shape: counter
        unit: "m³"
        rate: FlowRate / 3600.0
        initial: 1875000.0
        tier: meter
        precision: 2
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 4.2
        sigma: 0.12
        tau: 120.0
        precision: 2
        range: [0, 10]
        limits: {lo: 3.0, lolo: 2.5}
      Temperature:
        # River water follows ambient slowly and from below, which is what the 0.55
        # coefficient and the 4 K offset say.
        shape: derived
        unit: "°C"
        expr: offset_c + slope * ctx.ambient_temp_c
        params: {offset_c: 4.0, slope: 0.55}
        precision: 2
        range: [0, 40]
      Turbidity:
        shape: ou_walk
        unit: NTU
        mean: 3.4
        sigma: 0.8
        tau: 900.0
        precision: 2
        range: [0, 50]
        limits: {hi: 12.0, hihi: 25.0}

  - id: DEMIN-01
    equipment: DEMIN-01
    target: {area: Utilities, line: WaterTreatment, cell: DeminPlant}
    tier: process
    signals:
      ProductFlow:
        shape: ou_walk
        unit: "m³/h"
        mean: 42.0
        sigma: 2.5
        tau: 240.0
        precision: 2
        range: [0, 90]
      Conductivity:
        # Spec 8.2 puts the hi limit at 0.2 µS/cm. Demineralised water is judged on
        # conductivity, so this is the signal an operator actually watches here.
        shape: ou_walk
        unit: "µS/cm"
        mean: 0.09
        sigma: 0.02
        tau: 600.0
        precision: 3
        range: [0, 2]
        limits: {hi: 0.2, hihi: 0.5}
      Silica:
        shape: ou_walk
        unit: ppb
        mean: 8.0
        sigma: 1.6
        tau: 1800.0
        precision: 2
        range: [0, 100]
        limits: {hi: 20.0, hihi: 40.0}
      ResinBedDp:
        shape: ou_walk
        unit: bar
        mean: 0.35
        sigma: 0.04
        tau: 3600.0
        precision: 3
        range: [0, 2]
        limits: {hi: 0.9, hihi: 1.3}
      RegenerationState:
        shape: stepped
        unit: "1"
        choices: ["Service", "Backwash", "Regenerate", "Rinse"]
        weights: [20, 1, 1, 1]
        dwell_s: 1800.0
        tier: status
        param_type: Status
      ProductVolumeTotal:
        shape: counter
        unit: "m³"
        rate: ProductFlow / 3600.0
        initial: 512000.0
        tier: meter
        precision: 2

  - id: CT-01
    equipment: CT-01
    target: {site: Dormagen, area: Utilities, line: WaterTreatment, cell: CoolingTower1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      SupplyTemp:
        # What the tower can deliver: wet bulb plus an approach that widens with load. No
        # tower beats its wet-bulb temperature, so this is the physical floor.
        shape: derived
        unit: "°C"
        expr: ctx.wet_bulb_temp_c + approach_min + approach_span * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {approach_min: 3.2, approach_span: 3.4, served_lines: 2.0}
        precision: 2
        range: [-5, 45]
        limits: {hi: 32.0, hihi: 36.0}
        export_metric: true
      ReturnTemp:
        # Hot water back from the plant. Spec 8.2: derived on ctx.served_heat_load, which
        # is the lagged follower of production - so a hold narrows this over the following
        # minutes rather than in the same second.
        shape: derived
        unit: "°C"
        expr: SupplyTemp + delta_max_k * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {delta_max_k: 9.5, served_lines: 2.0}
        precision: 2
        range: [-5, 60]
        limits: {hi: 42.0, hihi: 46.0}
      DeltaT:
        shape: derived
        unit: K
        expr: ReturnTemp - SupplyTemp
        precision: 2
        range: [0, 20]
        export_metric: true
      CirculationFlow:
        shape: ou_walk
        unit: "m³/h"
        mean: 1150.0
        sigma: 25.0
        tau: 300.0
        precision: 1
        range: [0, 1600]
        limits: {lo: 800, lolo: 600}
      BasinLevel:
        shape: sawtooth
        unit: "%"
        low: 58.0
        high: 84.0
        fill_rate: 0.09
        drain_rate: 0.035
        start: 70.0
        precision: 1
        range: [0, 100]
        limits: {lo: 45, lolo: 30}
      MakeupVolumeTotal:
        # Makeup replaces what evaporates plus what is blown down. Evaporation is the load
        # term, which is why this counter is worth having: it moves with production.
        shape: counter
        unit: "m³"
        rate: (BlowdownFlow + evap_m3h_max * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)) / 3600.0
        params: {evap_m3h_max: 17.5, served_lines: 2.0}
        initial: 268000.0
        tier: meter
        precision: 2
      BlowdownFlow:
        shape: derived
        unit: "m³/h"
        expr: blowdown_fraction * CirculationFlow
        params: {blowdown_fraction: 0.004}
        precision: 3
        range: [0, 20]
      Conductivity:
        shape: ou_walk
        unit: "µS/cm"
        mean: 1450.0
        sigma: 60.0
        tau: 1800.0
        precision: 1
        range: [0, 4000]
        limits: {hi: 2400, hihi: 3000}
      FanSpeed:
        shape: derived
        unit: Hz
        expr: fan_min_hz + fan_span_hz * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {fan_min_hz: 18.0, fan_span_hz: 32.0, served_lines: 2.0}
        precision: 1
        range: [0, 60]
      ApproachTemp:
        # Spec 8.2: derived against ctx.wet_bulb_temp_c. Not a restatement of the constant
        # in SupplyTemp - the approach widens under load, and this is the signal that says
        # so on its own topic.
        shape: derived
        unit: K
        expr: SupplyTemp - ctx.wet_bulb_temp_c
        precision: 2
        range: [0, 15]
        limits: {hi: 8.0, hihi: 11.0}
      BiocideDosingRate:
        shape: stepped
        unit: L/h
        choices: [0.0, 1.8, 3.5]
        weights: [6, 2, 1]
        dwell_s: 3600.0
        tier: status
        precision: 2

  - id: CT-02
    equipment: CT-02
    target: {site: Krefeld, area: Utilities, line: WaterTreatment, cell: CoolingTower1}
    serves: [Krefeld/Production/Line1]
    tier: process
    signals:
      SupplyTemp:
        # served_lines is 1.0 here, not 2.0: served_heat_load is a sum over served lines,
        # so dividing by the wrong count would give Krefeld half the delta T for the same
        # relative load and make the two sites incomparable.
        shape: derived
        unit: "°C"
        expr: ctx.wet_bulb_temp_c + approach_min + approach_span * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {approach_min: 3.6, approach_span: 3.2, served_lines: 1.0}
        precision: 2
        range: [-5, 45]
        limits: {hi: 32.0, hihi: 36.0}
        export_metric: true
      ReturnTemp:
        shape: derived
        unit: "°C"
        expr: SupplyTemp + delta_max_k * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {delta_max_k: 8.5, served_lines: 1.0}
        precision: 2
        range: [-5, 60]
        limits: {hi: 42.0, hihi: 46.0}
      DeltaT:
        shape: derived
        unit: K
        expr: ReturnTemp - SupplyTemp
        precision: 2
        range: [0, 20]
        export_metric: true
      CirculationFlow:
        shape: ou_walk
        unit: "m³/h"
        mean: 480.0
        sigma: 14.0
        tau: 300.0
        precision: 1
        range: [0, 700]
        limits: {lo: 330, lolo: 250}
      BasinLevel:
        shape: sawtooth
        unit: "%"
        low: 60.0
        high: 82.0
        fill_rate: 0.08
        drain_rate: 0.03
        start: 72.0
        precision: 1
        range: [0, 100]
        limits: {lo: 45, lolo: 30}
      MakeupVolumeTotal:
        shape: counter
        unit: "m³"
        rate: (BlowdownFlow + evap_m3h_max * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)) / 3600.0
        params: {evap_m3h_max: 7.2, served_lines: 1.0}
        initial: 96000.0
        tier: meter
        precision: 2
      BlowdownFlow:
        shape: derived
        unit: "m³/h"
        expr: blowdown_fraction * CirculationFlow
        params: {blowdown_fraction: 0.0045}
        precision: 3
        range: [0, 20]
      Conductivity:
        shape: ou_walk
        unit: "µS/cm"
        mean: 1520.0
        sigma: 70.0
        tau: 1800.0
        precision: 1
        range: [0, 4000]
        limits: {hi: 2400, hihi: 3000}
      FanSpeed:
        shape: derived
        unit: Hz
        expr: fan_min_hz + fan_span_hz * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {fan_min_hz: 20.0, fan_span_hz: 30.0, served_lines: 1.0}
        precision: 1
        range: [0, 60]
      ApproachTemp:
        shape: derived
        unit: K
        expr: SupplyTemp - ctx.wet_bulb_temp_c
        precision: 2
        range: [0, 15]
        limits: {hi: 8.0, hihi: 11.0}
      BiocideDosingRate:
        shape: stepped
        unit: L/h
        choices: [0.0, 1.2, 2.4]
        weights: [6, 2, 1]
        dwell_s: 3600.0
        tier: status
        precision: 2

  - id: EFF-01
    equipment: EFF-01
    target: {site: Dormagen, area: Utilities, line: WaterTreatment, cell: EffluentOutfall}
    tier: process
    signals:
      FlowRate:
        shape: ou_walk
        unit: "m³/h"
        mean: 118.0
        sigma: 7.0
        tau: 420.0
        precision: 2
        range: [0, 300]
        limits: {hi: 240, hihi: 270}
      VolumeTotal:
        shape: counter
        unit: "m³"
        rate: FlowRate / 3600.0
        initial: 1420000.0
        tier: meter
        precision: 2
      pH:
        # Spec 8.2: lo 6.5, hi 9.0. Both sides matter - a discharge consent is a band, not
        # a ceiling - which is why this signal has limits in both directions.
        shape: ou_walk
        unit: pH
        mean: 7.6
        sigma: 0.09
        tau: 900.0
        precision: 2
        range: [0, 14]
        limits: {lo: 6.5, hi: 9.0, lolo: 6.0, hihi: 9.5}
      COD:
        shape: ou_walk
        unit: mg/L
        mean: 85.0
        sigma: 9.0
        tau: 1800.0
        precision: 1
        range: [0, 600]
        limits: {hi: 180, hihi: 250}
      TSS:
        shape: ou_walk
        unit: mg/L
        mean: 22.0
        sigma: 4.0
        tau: 1800.0
        precision: 1
        range: [0, 300]
        limits: {hi: 60, hihi: 100}
      Turbidity:
        shape: ou_walk
        unit: NTU
        mean: 6.5
        sigma: 1.4
        tau: 1200.0
        precision: 2
        range: [0, 100]
        limits: {hi: 20.0, hihi: 35.0}
      Temperature:
        # Spec 8.2 puts the hi limit at 35 °C. Effluent leaves warmer than the river it
        # came from, so this tracks ambient with an offset from process heat.
        shape: derived
        unit: "°C"
        expr: offset_c + slope * ctx.ambient_temp_c
        params: {offset_c: 12.0, slope: 0.6}
        precision: 2
        range: [0, 60]
        limits: {hi: 35.0, hihi: 40.0}
      Conductivity:
        shape: ou_walk
        unit: "µS/cm"
        mean: 1180.0
        sigma: 55.0
        tau: 1800.0
        precision: 1
        range: [0, 5000]
        limits: {hi: 2500, hihi: 3200}
      AmmoniumN:
        shape: ou_walk
        unit: mg/L
        mean: 1.4
        sigma: 0.3
        tau: 1800.0
        precision: 3
        range: [0, 20]
        limits: {hi: 5.0, hihi: 8.0}
```

- [ ] **Step 9: Run the new test file**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -v`
Expected: all pass.

If `test_the_full_profile_signal_count_is_the_table_multiplied_out` fails, read the number in the assertion error rather than adjusting the table: a shortfall of exactly one device's worth of signals means a template lost signals in transcription, and a shortfall that is not a multiple of any table entry means a signal was dropped from a device that is otherwise intact.

If a `derived` signal raises `ValueError: unknown name`, the name is a sibling that does not exist or a `params` key that was not declared — both are load-time errors by design (Task 6), and the message names the signal.

- [ ] **Step 10: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes, including the seven pre-existing tests in `test_simulator.py` and the legacy-`plc` regression guard in `test_targeting.py`.

- [ ] **Step 11: Commit**

```bash
git add conf/simulator/plant.yaml conf/simulator/energy.yaml conf/simulator/water.yaml \
        99_simulator/src/uns_simulator/profiles.py 99_simulator/src/uns_simulator/simulator.py \
        99_simulator/pyproject.toml 99_simulator/uv.lock 99_simulator/test/test_conf_files.py
git commit -m "feat(simulator): read conf/simulator YAML and add the energy and water families"
```

---

## Task 17: `utilities.yaml` and `asset_health.yaml`

Compressed air, steam, nitrogen, HVAC and chilled water, then condition monitoring on the rotating equipment. This is the bulk of the device inventory and the bulk of the message rate: `asset_health` publishes on the `fast` tier, which is why it is in `full` and not in `small`.

Nothing in the loader changes. Both files are transcription against interfaces Tasks 11, 12 and 16 already fixed, which is why they are one task and not four.

**Files:**
- Create: `conf/simulator/utilities.yaml`, `conf/simulator/asset_health.yaml`
- Modify: `99_simulator/test/test_conf_files.py` (extend the two tables)

**Interfaces:**
- Consumes: `read_simulator_conf` / `load_profile` (Task 16), and the `ctx` surface from Task 8 — this task is the first to use `ctx.served_air_demand` and the first to read `ctx.production_rate` and `ctx.running` *directly* rather than through `serves`, because an asset-health device sits on a production cell and therefore has a `LineState` of its own.
- Produces: no new code. The deliverable is two configuration files and the extended tables that prove they are complete.

Two placement rules carry over from Task 16 and decide the whole device list:

1. **A template that needs `serves` is per-site.** `CMP-01`/`CMP-02` (Dormagen) and `CMP-03` (Krefeld) are three templates rather than one because `FlowRate` derives from `ctx.served_air_demand`, and `AH-01`/`AH-02` are two for the same reason. `served_air_demand` is a **sum** over served lines, each in 0–1, so every one of them carries a `served_lines` parameter and divides by it.
2. **Everything else is site-agnostic.** `AirDryer`, `Boiler_B1`, `SteamHeader`, `CondensateReturn`, `N2Generator`, `N2Header`, `AHU_01` and `ChillerPlant` are Dormagen-only cell names (Krefeld's `CompressedAir` line has only `Compressor_C1` and `AirHeader`), so those templates omit `site` and still resolve to one device each.

Device tags are unique plant-wide — Krefeld's compressor is `CMP-03`, not a second `CMP-01`. Real plants often reuse tags per site, but template `id`s must be unique (Task 12 raises on a duplicate) and having `id` and `equipment` disagree would make the diagnostics table in sub-project B unreadable.

### The one honest limitation, stated once

Spec §8.4 wants condition monitoring that responds to load, and the shape catalogue has no "noise around a derived value" — `derived` is smooth, `ou_walk`'s `mean` is a float and not an expression. Rather than fake it, the split is physical:

- **Load-following signals are `derived`**: `MotorCurrent`, `MotorWindingTemp`, `BearingTempDe`/`Nde`, `LubeOilTemp`. These genuinely track duty, and they are what demonstrate the correlation.
- **Condition signals are `ou_walk`**: `VibrationRmsVelocity`, `VibrationAccelPeak`, `BearingEnvelope`, `FilterDp`. A bearing degrades on its own clock, not the line's, so a mean-reverting walk against ISO 10816 zones is the truthful model rather than a shortcoming.

- [ ] **Step 1: Extend the test tables**

In `99_simulator/test/test_conf_files.py`, add two entries to each table:

```python
EXPECTED_SIGNAL_COUNT = {
    "energy": {"EM-01": 17, "EM-02": 17, "TR-01": 6, "MCC-01": 6, "MCC-02": 6},
    "water": {"FM-01": 5, "DEMIN-01": 6, "CT-01": 11, "CT-02": 11, "EFF-01": 9},
    "utilities": {
        "CMP-01": 8,
        "CMP-02": 8,
        "CMP-03": 8,
        "DRY-01": 4,
        "AH-01": 4,
        "AH-02": 4,
        "BLR-01": 11,
        "SH-01": 3,
        "CR-01": 4,
        "N2-01": 5,
        "N2H-01": 2,
        "AHU-01": 8,
        "CH-01": 7,
    },
    "asset_health": {"VIB-01": 15, "VIB-02": 12},
}

EXPECTED_DEVICE_COUNT = {
    "energy": {"EM-01": 1, "EM-02": 1, "TR-01": 1, "MCC-01": 1, "MCC-02": 1},
    "water": {"FM-01": 2, "DEMIN-01": 1, "CT-01": 1, "CT-02": 1, "EFF-01": 1},
    "utilities": {
        "CMP-01": 1,
        "CMP-02": 1,
        "CMP-03": 1,
        "DRY-01": 1,
        "AH-01": 1,
        "AH-02": 1,
        "BLR-01": 1,
        "SH-01": 1,
        "CR-01": 1,
        "N2-01": 1,
        "N2H-01": 1,
        "AHU-01": 1,
        "CH-01": 1,
    },
    # VIB-01 lands on every Production cell: Dormagen Line1/Cell1, Line1/Cell2,
    # Line2/Cell1, and Krefeld Line1/Cell1. VIB-02 lands on the three compressor cells.
    "asset_health": {"VIB-01": 4, "VIB-02": 3},
}
```

Then add one test, because `asset_health` is the first family whose templates deliberately replicate and the first that must stay out of `small`:

```python
def test_asset_health_is_excluded_from_the_small_profile(raw):
    """Spec 9: asset_health publishes on the `fast` tier, so `small` must not load it.

    `small` is the shipped default and its whole purpose is to keep the graphdb mapper's
    per-topic-level MERGE load survivable. A fast-tier family creeping into it would undo
    that quietly - the simulator would still work, and Neo4j would simply fall behind.
    """
    small = load_profile(raw, "small")
    assert "asset_health" not in small.report.per_family
    assert small.families["asset_health"] is False
    assert load_profile(raw, "full").report.per_family["asset_health"] == 7  # noqa: PLR2004


def test_every_asset_health_signal_is_on_a_deliberate_tier(raw):
    """A `fast` tier is 1 s per signal per device; nothing lands there by accident.

    Counters and the ISO 4406 oil class are explicitly demoted, so this test is what stops
    a 15-minute register from being republished every second on 7 devices.
    """
    slow = {"RunHours": "meter", "StartCount": "meter", "LubeOilParticleCount": "status"}
    for template in raw["asset_health"]["devices"]:
        assert template["tier"] == "fast"
        for name, signal in template["signals"].items():
            assert signal.get("tier") == slow.get(name), f"{template['id']}/{name} is on the wrong tier"
```

`LoadedProfile.families` is the `dict[str, bool]` Task 12 produces, so `small.families["asset_health"] is False` reads the resolved decision rather than re-deriving it from `plant.yaml`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -x`
Expected: `KeyError: 'utilities'` from the `raw` fixture — `read_simulator_conf` skips files that do not exist, so an unwritten family is simply absent from the mapping.

- [ ] **Step 3: Write `conf/simulator/utilities.yaml`**

```yaml
# conf/simulator/utilities.yaml
# Spec 8.3. Compressed air, steam, nitrogen, HVAC, chilled water.
#
# Air and steam are the two utilities that visibly follow production: ctx.served_air_demand
# is fast and jittery (Task 7 gives it a noise term, modelling intermittent actuator draw)
# while ctx.served_heat_load is slow (a first-order lag), so the compressors chase the line
# and the boiler trails it. That difference is the point of having both.

devices:
  - id: CMP-01
    equipment: CMP-01
    target: {site: Dormagen, area: Utilities, line: CompressedAir, cell: Compressor_C1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      LoadPercent:
        shape: derived
        unit: "%"
        expr: idle_pct + span_pct * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_pct: 22.0, span_pct: 71.0, served_lines: 2.0}
        precision: 1
        range: [0, 110]
        limits: {hi: 97, hihi: 103}
      MotorPower:
        # An unloaded screw compressor still draws roughly a quarter of rated power, which
        # is why this interpolates from `unload_kw` rather than scaling from zero.
        shape: derived
        unit: kW
        expr: unload_kw + (rated_kw - unload_kw) * LoadPercent / 100.0
        params: {unload_kw: 46.0, rated_kw: 185.0}
        precision: 1
        range: [0, 220]
        limits: {hi: 195, hihi: 210}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: rated_nm3h * LoadPercent / 100.0
        params: {rated_nm3h: 1750.0}
        precision: 1
        range: [0, 2000]
      DischargePressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {setpoint_barg: 7.6, droop_bar: 0.55, served_lines: 2.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.5, lolo: 6.0}
      DischargeTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 62.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 95, hihi: 110}
      RunHours:
        # 1.0 / 3600.0 rather than 0.000278: the arithmetic is legal in an expression and
        # the intent survives being read six months later.
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 41200.0
        tier: meter
        precision: 2
      LoadUnloadCycles:
        # Cycling is worst at part load and near zero at full load, which is exactly the
        # wear mechanism an energy engineer is looking for on this topic.
        shape: counter
        unit: "1"
        rate: cycles_per_hour_max * (1.0 - LoadPercent / 100.0) / 3600.0
        params: {cycles_per_hour_max: 14.0}
        initial: 210400.0
        tier: meter
        precision: 0
      SpecificPower:
        shape: derived
        unit: "kW/(m³/min)"
        expr: MotorPower / max(FlowRate / 60.0, 0.1)
        precision: 3
        range: [0, 40]
        limits: {hi: 8.0, hihi: 11.0}

  - id: CMP-02
    equipment: CMP-02
    target: {site: Dormagen, area: Utilities, line: CompressedAir, cell: Compressor_C2}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      LoadPercent:
        # The trim machine: it idles lower and swings harder than the base-load C1, which
        # is how two compressors on one header actually share duty.
        shape: derived
        unit: "%"
        expr: idle_pct + span_pct * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_pct: 8.0, span_pct: 84.0, served_lines: 2.0}
        precision: 1
        range: [0, 110]
        limits: {hi: 97, hihi: 103}
      MotorPower:
        shape: derived
        unit: kW
        expr: unload_kw + (rated_kw - unload_kw) * LoadPercent / 100.0
        params: {unload_kw: 38.0, rated_kw: 160.0}
        precision: 1
        range: [0, 200]
        limits: {hi: 170, hihi: 185}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: rated_nm3h * LoadPercent / 100.0
        params: {rated_nm3h: 1480.0}
        precision: 1
        range: [0, 1700]
      DischargePressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {setpoint_barg: 7.5, droop_bar: 0.6, served_lines: 2.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.5, lolo: 6.0}
      DischargeTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 58.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 95, hihi: 110}
      RunHours:
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 28650.0
        tier: meter
        precision: 2
      LoadUnloadCycles:
        shape: counter
        unit: "1"
        rate: cycles_per_hour_max * (1.0 - LoadPercent / 100.0) / 3600.0
        params: {cycles_per_hour_max: 22.0}
        initial: 318900.0
        tier: meter
        precision: 0
      SpecificPower:
        shape: derived
        unit: "kW/(m³/min)"
        expr: MotorPower / max(FlowRate / 60.0, 0.1)
        precision: 3
        range: [0, 40]
        limits: {hi: 8.0, hihi: 11.0}

  - id: CMP-03
    equipment: CMP-03
    target: {site: Krefeld, area: Utilities, line: CompressedAir, cell: Compressor_C1}
    serves: [Krefeld/Production/Line1]
    tier: process
    signals:
      LoadPercent:
        # served_lines is 1.0: Krefeld has one line, and served_air_demand is a sum.
        shape: derived
        unit: "%"
        expr: idle_pct + span_pct * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_pct: 20.0, span_pct: 73.0, served_lines: 1.0}
        precision: 1
        range: [0, 110]
        limits: {hi: 97, hihi: 103}
      MotorPower:
        shape: derived
        unit: kW
        expr: unload_kw + (rated_kw - unload_kw) * LoadPercent / 100.0
        params: {unload_kw: 18.0, rated_kw: 75.0}
        precision: 1
        range: [0, 100]
        limits: {hi: 82, hihi: 90}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: rated_nm3h * LoadPercent / 100.0
        params: {rated_nm3h: 690.0}
        precision: 1
        range: [0, 800]
      DischargePressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {setpoint_barg: 7.4, droop_bar: 0.5, served_lines: 1.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.5, lolo: 6.0}
      DischargeTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * LoadPercent / 100.0
        params: {rise_k: 60.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 95, hihi: 110}
      RunHours:
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 16400.0
        tier: meter
        precision: 2
      LoadUnloadCycles:
        shape: counter
        unit: "1"
        rate: cycles_per_hour_max * (1.0 - LoadPercent / 100.0) / 3600.0
        params: {cycles_per_hour_max: 18.0}
        initial: 94300.0
        tier: meter
        precision: 0
      SpecificPower:
        shape: derived
        unit: "kW/(m³/min)"
        expr: MotorPower / max(FlowRate / 60.0, 0.1)
        precision: 3
        range: [0, 40]
        limits: {hi: 8.0, hihi: 11.0}

  - id: DRY-01
    equipment: DRY-01
    # No `site`: AirDryer is a Dormagen-only cell name.
    target: {area: Utilities, line: CompressedAir, cell: AirDryer}
    tier: process
    signals:
      DewPoint:
        # Spec 8.3 puts the hi limit at -20 °C. This is the one number that decides whether
        # instrument air is fit to use, so the alarm is on the warm side of the walk.
        shape: ou_walk
        unit: "°C"
        mean: -38.0
        sigma: 2.4
        tau: 900.0
        precision: 2
        range: [-70, 10]
        limits: {hi: -20.0, hihi: -10.0}
        export_metric: true
      InletTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k
        params: {rise_k: 14.0}
        precision: 1
        range: [-20, 80]
        limits: {hi: 45, hihi: 55}
      DifferentialPressure:
        shape: ou_walk
        unit: bar
        mean: 0.16
        sigma: 0.02
        tau: 1800.0
        precision: 3
        range: [0, 1.5]
        limits: {hi: 0.4, hihi: 0.7}
      RegenCycleState:
        shape: stepped
        unit: "1"
        choices: ["TowerA", "TowerB", "Purge"]
        weights: [5, 5, 1]
        dwell_s: 300.0
        tier: status
        param_type: Status

  - id: AH-01
    equipment: AH-01
    target: {site: Dormagen, area: Utilities, line: CompressedAir, cell: AirHeader}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      HeaderPressure:
        shape: derived
        unit: barg
        expr: idle_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_barg: 7.2, droop_bar: 0.9, served_lines: 2.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.0, lolo: 5.5}
        export_metric: true
      FlowRate:
        # `leak_nm3h` is the floor, not an addition on top of nothing: a header always
        # flows, because a plant always leaks.
        shape: derived
        unit: "Nm³/h"
        expr: leak_nm3h + process_nm3h * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {leak_nm3h: 190.0, process_nm3h: 2400.0, served_lines: 2.0}
        precision: 1
        range: [0, 3200]
      VolumeTotal:
        shape: counter
        unit: "Nm³"
        rate: FlowRate / 3600.0
        initial: 74500000.0
        tier: meter
        precision: 1
      LeakageEstimate:
        # Spec 8.3: "visible at idle". min() rather than a subtraction - at idle the whole
        # header flow *is* leakage, and under load the estimate caps at the leak rate
        # instead of going negative.
        shape: derived
        unit: "Nm³/h"
        expr: min(FlowRate, leak_nm3h)
        params: {leak_nm3h: 190.0}
        precision: 1
        range: [0, 500]
        limits: {hi: 250, hihi: 350}

  - id: AH-02
    equipment: AH-02
    target: {site: Krefeld, area: Utilities, line: CompressedAir, cell: AirHeader}
    serves: [Krefeld/Production/Line1]
    tier: process
    signals:
      HeaderPressure:
        shape: derived
        unit: barg
        expr: idle_barg - droop_bar * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {idle_barg: 7.1, droop_bar: 0.8, served_lines: 1.0}
        precision: 3
        range: [0, 12]
        limits: {lo: 6.0, lolo: 5.5}
        export_metric: true
      FlowRate:
        shape: derived
        unit: "Nm³/h"
        expr: leak_nm3h + process_nm3h * clamp(ctx.served_air_demand / served_lines, 0.0, 1.0)
        params: {leak_nm3h: 95.0, process_nm3h: 620.0, served_lines: 1.0}
        precision: 1
        range: [0, 900]
      VolumeTotal:
        shape: counter
        unit: "Nm³"
        rate: FlowRate / 3600.0
        initial: 19800000.0
        tier: meter
        precision: 1
      LeakageEstimate:
        shape: derived
        unit: "Nm³/h"
        expr: min(FlowRate, leak_nm3h)
        params: {leak_nm3h: 95.0}
        precision: 1
        range: [0, 300]
        limits: {hi: 140, hihi: 200}

  - id: BLR-01
    equipment: BLR-01
    target: {area: Utilities, line: SteamPlant, cell: Boiler_B1}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      SteamFlow:
        # On ctx.served_heat_load, the lagged follower - so the boiler trails a line stop
        # by minutes while the compressors react in seconds. Spec 6.1 built that lag
        # precisely so the utility side does not step in lockstep with production.
        shape: derived
        unit: t/h
        expr: min_t_h + span_t_h * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {min_t_h: 3.5, span_t_h: 22.0, served_lines: 2.0}
        precision: 2
        range: [0, 32]
        limits: {hi: 28, hihi: 30}
        export_metric: true
      SteamPressure:
        shape: derived
        unit: barg
        expr: setpoint_barg - droop_bar * SteamFlow / rated_t_h
        params: {setpoint_barg: 13.5, droop_bar: 1.1, rated_t_h: 25.0}
        precision: 3
        range: [0, 20]
        limits: {lo: 11.5, lolo: 10.5, hi: 15.0, hihi: 16.0}
      SteamTemp:
        shape: derived
        unit: "°C"
        expr: base_c + rise_k * SteamFlow / rated_t_h
        params: {base_c: 192.0, rise_k: 14.0}
        precision: 1
        range: [0, 300]
        limits: {hi: 225, hihi: 240}
      DrumLevel:
        shape: sawtooth
        unit: "%"
        low: 44.0
        high: 58.0
        fill_rate: 0.6
        drain_rate: 0.4
        start: 50.0
        precision: 1
        range: [0, 100]
        limits: {lo: 35, lolo: 25, hi: 70, hihi: 80}
      FeedwaterFlow:
        # Slightly above steam flow: what leaves as blowdown never leaves as steam.
        shape: derived
        unit: t/h
        expr: SteamFlow * (1.0 + blowdown_fraction)
        params: {blowdown_fraction: 0.03}
        precision: 2
        range: [0, 35]
      FuelGasFlow:
        shape: derived
        unit: "Nm³/h"
        expr: standby_nm3h + nm3h_per_tonne * SteamFlow
        params: {standby_nm3h: 40.0, nm3h_per_tonne: 74.0}
        precision: 1
        range: [0, 2200]
      FuelGasTotal:
        shape: counter
        unit: "Nm³"
        rate: FuelGasFlow / 3600.0
        initial: 12750000.0
        tier: meter
        precision: 1
        export_metric: true
      FlueGasTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + base_rise_k + load_rise_k * SteamFlow / rated_t_h
        params: {base_rise_k: 95.0, load_rise_k: 78.0, rated_t_h: 25.0}
        precision: 1
        range: [0, 350]
        limits: {hi: 210, hihi: 240}
      FlueGasO2:
        # Excess air falls as the burner turns up, which is why this runs the other way
        # from every other load-following signal in the file.
        shape: derived
        unit: "%"
        expr: o2_idle_pct - o2_span_pct * clamp(SteamFlow / rated_t_h, 0.0, 1.0)
        params: {o2_idle_pct: 7.4, o2_span_pct: 4.2, rated_t_h: 25.0}
        precision: 2
        range: [0, 21]
        limits: {lo: 1.5, lolo: 0.8, hi: 8.5, hihi: 10.0}
      Efficiency:
        # The two real losses: stack temperature above ambient, and excess air. Both are
        # already on their own topics, so this signal is a genuine calculation rather than
        # a number invented alongside them.
        shape: derived
        unit: "%"
        expr: eff_max - stack_k * (FlueGasTemp - ctx.ambient_temp_c) / 100.0 - o2_k * FlueGasO2
        params: {eff_max: 94.5, stack_k: 3.1, o2_k: 0.55}
        precision: 2
        range: [0, 100]
        limits: {lo: 84.0, lolo: 78.0}
        export_metric: true
      BurnerState:
        shape: stepped
        unit: "1"
        choices: ["HighFire", "LowFire", "Modulating", "Standby"]
        weights: [3, 2, 6, 1]
        dwell_s: 600.0
        tier: status
        param_type: Status

  - id: SH-01
    equipment: SH-01
    target: {area: Utilities, line: SteamPlant, cell: SteamHeader}
    tier: process
    signals:
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 12.4
        sigma: 0.18
        tau: 240.0
        precision: 3
        range: [0, 20]
        limits: {lo: 10.5, lolo: 9.5}
      Temperature:
        shape: ou_walk
        unit: "°C"
        mean: 196.0
        sigma: 2.2
        tau: 300.0
        precision: 1
        range: [0, 300]
        limits: {lo: 175, hi: 225}
      FlowTotal:
        # A literal rate: the header totaliser has no flow transmitter of its own on this
        # skid, so 15 t/h is a nameplate figure written as arithmetic to keep the unit
        # conversion visible.
        shape: counter
        unit: t
        rate: 15.0 / 3600.0
        initial: 486000.0
        tier: meter
        precision: 2

  - id: CR-01
    equipment: CR-01
    target: {area: Utilities, line: SteamPlant, cell: CondensateReturn}
    tier: process
    signals:
      ReturnFlow:
        shape: ou_walk
        unit: t/h
        mean: 11.5
        sigma: 1.1
        tau: 600.0
        precision: 2
        range: [0, 25]
        limits: {lo: 6.0, lolo: 4.0}
      ReturnPercent:
        # Against a nameplate steam rate rather than BLR-01's SteamFlow: expressions see
        # sibling signals only, and reaching across devices is exactly the coupling the
        # `serves` mechanism exists to avoid.
        shape: derived
        unit: "%"
        expr: 100.0 * ReturnFlow / max(nominal_steam_t_h, 0.1)
        params: {nominal_steam_t_h: 16.0}
        precision: 1
        range: [0, 120]
        limits: {lo: 55, lolo: 40}
        export_metric: true
      Conductivity:
        # Condensate conductivity is the contamination alarm: a failed heat exchanger puts
        # process fluid straight into the boiler feed.
        shape: ou_walk
        unit: "µS/cm"
        mean: 8.5
        sigma: 1.8
        tau: 1200.0
        precision: 2
        range: [0, 200]
        limits: {hi: 25.0, hihi: 50.0}
      TrapFailureCount:
        shape: counter
        unit: "1"
        rate: 0.0000015
        initial: 27.0
        tier: meter
        precision: 0

  - id: N2-01
    equipment: N2-01
    target: {area: Utilities, line: Nitrogen, cell: N2Generator}
    tier: process
    signals:
      FlowRate:
        shape: ou_walk
        unit: "Nm³/h"
        mean: 320.0
        sigma: 22.0
        tau: 300.0
        precision: 1
        range: [0, 500]
      Purity_O2:
        # Spec 8.3 puts the hi limit at 10 ppm. Residual oxygen is what an inerting duty
        # actually cares about, so purity is expressed as the contaminant, not the product.
        shape: ou_walk
        unit: ppm
        mean: 4.2
        sigma: 0.9
        tau: 900.0
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 25.0}
        export_metric: true
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 8.1
        sigma: 0.15
        tau: 240.0
        precision: 3
        range: [0, 14]
        limits: {lo: 7.0, lolo: 6.5}
      VolumeTotal:
        shape: counter
        unit: "Nm³"
        rate: FlowRate / 3600.0
        initial: 9860000.0
        tier: meter
        precision: 1
      MotorPower:
        shape: derived
        unit: kW
        expr: standby_kw + kw_per_nm3h * FlowRate
        params: {standby_kw: 12.0, kw_per_nm3h: 0.115}
        precision: 1
        range: [0, 90]
        limits: {hi: 72, hihi: 80}

  - id: N2H-01
    equipment: N2H-01
    target: {area: Utilities, line: Nitrogen, cell: N2Header}
    tier: process
    signals:
      Pressure:
        shape: ou_walk
        unit: barg
        mean: 7.6
        sigma: 0.2
        tau: 300.0
        precision: 3
        range: [0, 14]
        limits: {lo: 6.5, lolo: 6.0}
      FlowRate:
        shape: ou_walk
        unit: "Nm³/h"
        mean: 295.0
        sigma: 28.0
        tau: 180.0
        precision: 1
        range: [0, 500]

  - id: AHU-01
    equipment: AHU-01
    target: {area: Utilities, line: HVAC, cell: AHU_01}
    tier: process
    signals:
      SupplyAirTemp:
        # Control holds the setpoint; how well it holds it degrades as ambient runs away
        # from it. The 0.06 coefficient is that droop, not a physical mixing ratio.
        shape: derived
        unit: "°C"
        expr: setpoint_c + droop * (ctx.ambient_temp_c - setpoint_c)
        params: {setpoint_c: 20.0, droop: 0.06}
        precision: 2
        range: [0, 45]
        limits: {lo: 16, hi: 26}
      ReturnAirTemp:
        shape: derived
        unit: "°C"
        expr: SupplyAirTemp + room_gain_k
        params: {room_gain_k: 3.4}
        precision: 2
        range: [0, 45]
        limits: {hi: 28, hihi: 32}
      SupplyAirRh:
        shape: ou_walk
        unit: "%"
        mean: 46.0
        sigma: 3.5
        tau: 900.0
        precision: 1
        range: [0, 100]
        limits: {lo: 30, hi: 65}
      FanSpeed:
        shape: ou_walk
        unit: Hz
        mean: 38.0
        sigma: 2.0
        tau: 600.0
        precision: 1
        range: [0, 60]
      FilterDp:
        # Spec 8.3: "slow-rising, resets on service". A sawtooth is literally that - the
        # fast drain edge is the filter change.
        shape: sawtooth
        unit: Pa
        low: 90.0
        high: 320.0
        fill_rate: 0.0009
        drain_rate: 4.0
        start: 140.0
        precision: 1
        range: [0, 500]
        limits: {hi: 250, hihi: 300}
      DamperPosition:
        # Free cooling: the damper opens when outside air is close to setpoint and closes
        # when using it would cost more than it saves.
        shape: derived
        unit: "%"
        expr: clamp(max_pct - gain * abs(ctx.ambient_temp_c - setpoint_c), min_pct, max_pct)
        params: {max_pct: 85.0, min_pct: 12.0, gain: 4.5, setpoint_c: 20.0}
        precision: 1
        range: [0, 100]
      HeatingValvePosition:
        shape: derived
        unit: "%"
        expr: clamp(gain * (setpoint_c - ctx.ambient_temp_c), 0.0, 100.0)
        params: {gain: 5.5, setpoint_c: 20.0}
        precision: 1
        range: [0, 100]
      CoolingValvePosition:
        # The mirror image of the heating valve, so the pair can never both be open. Two
        # independent walks would sit there heating and cooling the same air.
        shape: derived
        unit: "%"
        expr: clamp(gain * (ctx.ambient_temp_c - setpoint_c), 0.0, 100.0)
        params: {gain: 6.5, setpoint_c: 20.0}
        precision: 1
        range: [0, 100]

  - id: CH-01
    equipment: CH-01
    target: {area: Utilities, line: HVAC, cell: ChillerPlant}
    serves: [Dormagen/Production/Line1, Dormagen/Production/Line2]
    tier: process
    signals:
      ChilledWaterSupply:
        shape: ou_walk
        unit: "°C"
        mean: 6.5
        sigma: 0.25
        tau: 300.0
        precision: 2
        range: [0, 20]
        limits: {hi: 9.0, hihi: 11.0}
      ChilledWaterReturn:
        shape: derived
        unit: "°C"
        expr: ChilledWaterSupply + delta_max_k * clamp(ctx.served_heat_load / served_lines, 0.0, 1.0)
        params: {delta_max_k: 6.2, served_lines: 2.0}
        precision: 2
        range: [0, 30]
        limits: {hi: 16.0, hihi: 19.0}
      CoolingLoad:
        # 1.163 kWh/(m³·K) is water's volumetric heat capacity, so this is flow times delta
        # T and not a fitted constant.
        shape: derived
        unit: kW
        expr: flow_m3h * 1.163 * (ChilledWaterReturn - ChilledWaterSupply)
        params: {flow_m3h: 145.0}
        precision: 1
        range: [0, 1400]
        export_metric: true
      CompressorPower:
        # Efficiency degrades as the condenser gets hotter, which is why ambient appears
        # here: a hot afternoon costs more kW for the same kW of cooling.
        shape: derived
        unit: kW
        expr: standby_kw + CoolingLoad / max(cop_nominal - ambient_penalty * (ctx.ambient_temp_c - 20.0) / 10.0, 1.2)
        params: {standby_kw: 9.0, cop_nominal: 4.6, ambient_penalty: 0.9}
        precision: 1
        range: [0, 400]
        limits: {hi: 320, hihi: 360}
        export_metric: true
      COP:
        shape: derived
        unit: "1"
        expr: CoolingLoad / max(CompressorPower, 1.0)
        precision: 3
        range: [0, 8]
        limits: {lo: 2.5, lolo: 1.8}
      EvaporatorPressure:
        shape: derived
        unit: barg
        expr: base_barg + slope * ChilledWaterSupply
        params: {base_barg: 2.6, slope: 0.085}
        precision: 3
        range: [0, 12]
        limits: {lo: 2.2, lolo: 1.8}
      CondenserPressure:
        shape: derived
        unit: barg
        expr: base_barg + slope * ctx.ambient_temp_c
        params: {base_barg: 8.4, slope: 0.19}
        precision: 3
        range: [0, 25]
        limits: {hi: 15.0, hihi: 17.5}
```

- [ ] **Step 4: Write `conf/simulator/asset_health.yaml`**

`VIB-01` is the first template that reads the line's own state rather than an aggregate. It sits on a production cell, so `build_plant_context` gave it a `LineState` and its `DeviceView` exposes `ctx.production_rate` and `ctx.running` directly — no `serves` list, and none would be correct, because a pump on Line1 is not serving Line1, it *is* Line1.

```yaml
# conf/simulator/asset_health.yaml
# Spec 8.4. Condition monitoring on the `fast` tier - 1 s per signal per device, which is
# how vibration is actually sampled and why this family is in `full` and not in `small`.
#
# The split between shapes here is physical, not a workaround: load-following signals are
# `derived` (they genuinely track duty), and condition signals are `ou_walk` (a bearing
# degrades on its own clock, not the line's). Counters and the oil-cleanliness class carry
# an explicit slower tier, because a 15-minute register republished every second would be
# 7 devices' worth of noise.

devices:
  - id: VIB-01
    equipment: PumpP101
    # Every Production cell at every site. No `serves`: a pump on Line1 is not serving
    # Line1, it is part of it, so it reads ctx.production_rate directly.
    target: {area: Production}
    tier: fast
    signals:
      VibrationRmsVelocity:
        # ISO 10816 zones: 4.5 mm/s is the boundary into "unsatisfactory", 7.1 into
        # "unacceptable". The walk's mean sits in zone A/B so the alarms mean something.
        shape: ou_walk
        unit: mm/s
        mean: 2.1
        sigma: 0.35
        tau: 600.0
        precision: 3
        range: [0, 20]
        limits: {hi: 4.5, hihi: 7.1}
        export_metric: true
      VibrationAccelPeak:
        shape: ou_walk
        unit: g
        mean: 1.4
        sigma: 0.28
        tau: 300.0
        precision: 3
        range: [0, 15]
        limits: {hi: 4.0, hihi: 6.5}
      BearingEnvelope:
        shape: ou_walk
        unit: gE
        mean: 0.9
        sigma: 0.2
        tau: 1200.0
        precision: 3
        range: [0, 10]
        limits: {hi: 2.5, hihi: 4.0}
      MotorCurrent:
        shape: derived
        unit: A
        expr: idle_a + span_a * ctx.production_rate
        params: {idle_a: 11.0, span_a: 27.0}
        precision: 2
        range: [0, 60]
        limits: {hi: 44, hihi: 50}
        export_metric: true
      MotorWindingTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 68.0, rated_a: 38.0}
        precision: 1
        range: [-20, 180]
        limits: {hi: 130, hihi: 145}
      BearingTempDe:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 34.0, rated_a: 38.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 85, hihi: 95}
      BearingTempNde:
        # Runs cooler than the drive end: no radial load from the coupling.
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 28.0, rated_a: 38.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 85, hihi: 95}
      SuctionPressure:
        shape: ou_walk
        unit: barg
        mean: 1.35
        sigma: 0.06
        tau: 120.0
        precision: 3
        range: [-1, 10]
        limits: {lo: 0.6, lolo: 0.3}
      DischargePressure:
        shape: derived
        unit: barg
        expr: SuctionPressure + shutoff_bar * (deadhead_frac + duty_frac * ctx.production_rate)
        params: {shutoff_bar: 5.8, deadhead_frac: 0.55, duty_frac: 0.45}
        precision: 3
        range: [0, 16]
        limits: {hi: 8.5, hihi: 9.5}
      DifferentialPressure:
        shape: derived
        unit: bar
        expr: DischargePressure - SuctionPressure
        precision: 3
        range: [0, 12]
        limits: {lo: 2.0, lolo: 1.2}
      RunHours:
        # ctx.running is a boolean, and Python's True is 1 in arithmetic - so run hours
        # accrue only while the line is in EXECUTE, which is what a run-hour meter means.
        # The only place in this file where a boolean enters an expression; MES-01's
        # Availability in production.yaml is the other one.
        shape: counter
        unit: h
        rate: ctx.running / 3600.0
        initial: 22400.0
        tier: meter
        precision: 2
      StartCount:
        shape: counter
        unit: "1"
        rate: 0.00028
        initial: 4180.0
        tier: meter
        precision: 0
      LubeOilTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 22.0, rated_a: 38.0}
        precision: 1
        range: [-20, 120]
        limits: {hi: 70, hihi: 80}
      LubeOilParticleCount:
        # ISO 4406 cleanliness class, published as the code engineers actually quote.
        shape: stepped
        unit: "1"
        choices: ["16/14/11", "17/15/12", "18/16/13", "19/17/14"]
        weights: [4, 6, 3, 1]
        dwell_s: 3600.0
        tier: status
        param_type: Status
      FilterDp:
        shape: ou_walk
        unit: bar
        mean: 0.42
        sigma: 0.05
        tau: 3600.0
        precision: 3
        range: [0, 3]
        limits: {hi: 1.2, hihi: 1.8}

  - id: VIB-02
    equipment: CompressorDrive
    # Spec 8.4: "plus rotating utility equipment (compressors, pumps)". A generic equipment
    # tag because one template covers three compressor cells and the cell already
    # disambiguates the topic.
    #
    # Twelve signals, not fifteen: suction, discharge and differential pressure belong to
    # the compressor itself and are already published by CMP-01/02/03. Duplicating them
    # here would put two different walks on the same physical measurement.
    target: {area: Utilities, line: CompressedAir, cell: [Compressor_C1, Compressor_C2]}
    tier: fast
    signals:
      VibrationRmsVelocity:
        shape: ou_walk
        unit: mm/s
        mean: 2.6
        sigma: 0.4
        tau: 600.0
        precision: 3
        range: [0, 20]
        limits: {hi: 4.5, hihi: 7.1}
        export_metric: true
      VibrationAccelPeak:
        shape: ou_walk
        unit: g
        mean: 1.8
        sigma: 0.32
        tau: 300.0
        precision: 3
        range: [0, 15]
        limits: {hi: 4.0, hihi: 6.5}
      BearingEnvelope:
        shape: ou_walk
        unit: gE
        mean: 1.2
        sigma: 0.24
        tau: 1200.0
        precision: 3
        range: [0, 10]
        limits: {hi: 2.5, hihi: 4.0}
      MotorCurrent:
        # ctx.served_air_demand would need a `serves` list, and a template that replicates
        # across three cells at two sites cannot carry one (Task 16). ctx.production_rate is
        # unavailable too - a utility cell has no LineState. So this is an ou_walk, and the
        # compressor's own load story lives on CMP-01/02/03's LoadPercent.
        shape: ou_walk
        unit: A
        mean: 196.0
        sigma: 22.0
        tau: 180.0
        precision: 2
        range: [0, 400]
        limits: {hi: 320, hihi: 355}
      MotorWindingTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 74.0, rated_a: 300.0}
        precision: 1
        range: [-20, 180]
        limits: {hi: 130, hihi: 145}
      BearingTempDe:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 42.0, rated_a: 300.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 90, hihi: 100}
      BearingTempNde:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 35.0, rated_a: 300.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 90, hihi: 100}
      RunHours:
        # A literal rate, unlike VIB-01's: a compressor runs whether or not any line is in
        # EXECUTE, and a utility cell has no ctx.running to read anyway.
        shape: counter
        unit: h
        rate: 1.0 / 3600.0
        initial: 39800.0
        tier: meter
        precision: 2
      StartCount:
        shape: counter
        unit: "1"
        rate: 0.00011
        initial: 1620.0
        tier: meter
        precision: 0
      LubeOilTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k * MotorCurrent / rated_a
        params: {rise_k: 46.0, rated_a: 300.0}
        precision: 1
        range: [-20, 140]
        limits: {hi: 88, hihi: 98}
      LubeOilParticleCount:
        shape: stepped
        unit: "1"
        choices: ["16/14/11", "17/15/12", "18/16/13", "19/17/14"]
        weights: [3, 6, 4, 2]
        dwell_s: 3600.0
        tier: status
        param_type: Status
      FilterDp:
        shape: ou_walk
        unit: bar
        mean: 0.55
        sigma: 0.07
        tau: 3600.0
        precision: 3
        range: [0, 3]
        limits: {hi: 1.4, hihi: 2.0}
```

`target.cell` takes a list here — `matches_target` accepts a string or a list of strings for every selector key (Task 11), which is what lets one template cover `Compressor_C1` and `Compressor_C2` without a wildcard that would also catch the dryer and the header.

- [ ] **Step 5: Run the tests**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -v`
Expected: all pass, including the two new tests and the extended parametrised cases.

If `test_a_template_carrying_serves_never_replicates` fails on `VIB-02`, a `serves` list was added to it — that template covers three cells across two sites, so no single `serves` list can be right for all of them, which is exactly why its `MotorCurrent` is an `ou_walk`.

- [ ] **Step 6: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add conf/simulator/utilities.yaml conf/simulator/asset_health.yaml 99_simulator/test/test_conf_files.py
git commit -m "feat(simulator): add the utilities and asset_health device families"
```

---

## Task 18: `production.yaml` and `safety.yaml`

The last two families. `production.yaml` is where the plant model pays off — PackML state, OEE and batch identity all read the same `LineState` the utilities are reacting to — and it is where the legacy `G1`/`FillingMachine` templates move so that nothing that publishes today stops publishing. `safety.yaml` closes the loop: `WS-01` publishes the weather that `CT-01`'s approach temperature and `CH-01`'s power already depend on.

**Files:**
- Create: `conf/simulator/production.yaml`, `conf/simulator/safety.yaml`
- Modify: `99_simulator/test/test_conf_files.py` (extend the two tables, plus three tests)

**Interfaces:**
- Consumes: `read_simulator_conf` / `load_profile` (Task 16); `ctx.state`, `ctx.production_rate`, `ctx.running`, `ctx.time_in_state_s` (Task 8); `PACKML_STATES` (Task 4) as the domain of the `map` on `PackMlStateCode`.
- Produces: no new code.

**Read this before transcribing `ctx.state`.** Task 5's unit test for `SteppedSignal` uses a fake view and writes `source: ctx.line.state`, because `resolve_ctx_path` walks whatever attributes it is given. A real `DeviceView` is **flat**: the path is `ctx.state`, not `ctx.line.state` (Task 8, `DeviceView` properties). Copying the path out of the Task 5 test into a configuration file would raise at load time.

### Three decisions taken here, with reasons

**1. `WS-01` derives the weather from `ctx` instead of generating its own.**

Spec §8.6 marks `AmbientTemp` and `SolarIrradiance` as `diurnal`. `SolarIrradiance` stays `diurnal` — nothing in `PlantContext` models sunlight. `AmbientTemp`, `RelativeHumidity`, `WetBulbTemp`, `WindSpeed` and `BarometricPressure` do **not**, and instead read `ctx`, because `SiteState` already computes all five from that site's `ambient_mean_c` and `ambient_swing_c` in `plant.yaml`. A second sine on the same quantity would be a second, disagreeing weather: the cooling tower would be sizing its approach against one number while the weather station published another, and the spec's own closing sentence — "hot humid afternoons degrade cooling performance" — would be unverifiable, because the two would not be the same afternoon. It would also force one template per site to carry each site's amplitude, where one site-agnostic template now serves both.

**2. The four OEE percentages are instantaneous, not windowed.**

`window_agg` reads **numeric siblings only** — it resolves `source` against the sibling map and skips `bool` explicitly (Task 6). It cannot see `ctx.running`, so an availability computed as "fraction of the last hour spent in EXECUTE" is not expressible with the shapes this plan builds, and inventing a shape for one signal is not worth it. So `Availability`, `Performance`, `Quality` and `Oee` are the textbook ratios evaluated now, and windowing is Grafana's job — which is the division of labour spec B §2 already settled. `Availability` is consequently a 0-or-100 square wave; that is stated in a comment on the signal so nobody reads it as a rolling figure.

**3. `DowntimeReason` is mapped from `ctx.state`, not drawn from a list.**

A reason drawn independently would publish "MaterialShortage" while `PackMlState` said `EXECUTE`. Mapping the same `ctx.state` through a lookup table makes the two incapable of contradicting each other, which is exactly what `SteppedSignal`'s `map` exists for.

- [ ] **Step 1: Extend the test tables and add three tests**

In `99_simulator/test/test_conf_files.py`, add to each table:

```python
    "production": {"MES-01": 15, "QA-01": 6, "LAB-01": 6, "001": 2, "002": 1},
    "safety": {"GD-01": 7, "GD-02": 7, "CEMS-01": 9, "SIS-01": 6, "WS-01": 9},
```

```python
    # MES-01, QA-01 and the two legacy PLC templates land on all four Production cells.
    # LAB-01 is Dormagen's Quality area only.
    "production": {"MES-01": 4, "QA-01": 4, "LAB-01": 1, "001": 4, "002": 4},
    # GD_Zone1 and WS_01 exist at both sites; GD_Zone2 and Stack_S1 are Dormagen-only.
    "safety": {"GD-01": 2, "GD-02": 1, "CEMS-01": 1, "SIS-01": 1, "WS-01": 2},
```

Add `from uns_simulator.plant import PACKML_STATES` to the imports at the top of the file — at function scope ruff's preview `PLC0415` would reject it.

Then three tests. The first is the regression guard spec §12 asks for; the second and third pin the two decisions above:

```python
LEGACY_PLC_SENSORS = {
    ("001", "G1"): {"Temperature": (75.0, 2.0, "°C"), "Pressure": (150.0, 5.0, "psi")},
    ("002", "FillingMachine"): {"FlowRate": (450.0, 20.0, "L/min")},
}


@pytest.mark.parametrize("key", sorted(LEGACY_PLC_SENSORS))
def test_legacy_plc_templates_moved_across_unchanged(raw, key):
    """Spec 8.5 and 12: the pre-existing PLC signals must publish exactly as they did.

    `sensors:` became `signals:` and the file changed, but `equipment` decides the topic and
    base_value/variation/unit decide the payload, so those four are what this asserts. A
    `shape` key appearing on any of them would also be a change - `noise` is the default and
    the old generator had no other behaviour.
    """
    device_id, equipment = key
    sensors = LEGACY_PLC_SENSORS[key]
    template = next(item for item in raw["production"]["devices"] if str(item["id"]) == device_id)
    assert template["equipment"] == equipment
    assert template.get("target") is None, "an absent target means every production cell, which is what create_plc did"
    assert set(template["signals"]) == set(sensors)
    for name, (base_value, variation, unit) in sensors.items():
        signal = template["signals"][name]
        assert signal["base_value"] == base_value
        assert signal["variation"] == variation
        assert signal["unit"] == unit
        assert "shape" not in signal


def test_the_weather_station_reports_the_plant_context(raw):
    """The station must not be a second, disagreeing model of the same weather.

    SiteState already derives all five of these from plant.yaml. SolarIrradiance is exempt:
    PlantContext has no sunlight, so a `diurnal` of its own is the only option.
    """
    signals = next(item for item in raw["safety"]["devices"] if item["id"] == "WS-01")["signals"]
    from_context = {
        "AmbientTemp": "ctx.ambient_temp_c",
        "RelativeHumidity": "ctx.ambient_rh_pct",
        "WetBulbTemp": "ctx.wet_bulb_temp_c",
        "WindSpeed": "ctx.wind_speed_ms",
        "BarometricPressure": "ctx.barometric_mbar",
    }
    for name, path in from_context.items():
        assert signals[name]["shape"] == "derived"
        assert path in signals[name]["expr"], f"{name} must read {path}"
    assert signals["SolarIrradiance"]["shape"] == "diurnal"


def test_packml_state_code_maps_every_state(raw):
    """A state missing from the map publishes its own name where an integer is expected.

    SteppedSignal._translate falls through to the raw value on a miss, so an incomplete map
    fails as a type surprise on a consumer rather than at load time. Only this test catches it.
    """
    signals = next(item for item in raw["production"]["devices"] if item["id"] == "MES-01")["signals"]
    assert set(signals["PackMlStateCode"]["map"]) == set(PACKML_STATES)
    assert set(signals["DowntimeReason"]["map"]) == set(PACKML_STATES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -x`
Expected: `KeyError: 'production'` from the `raw` fixture.

- [ ] **Step 3: Write `conf/simulator/production.yaml`**

```yaml
# conf/simulator/production.yaml
# Spec 8.5. What the line is doing, how well, and what it is making.
#
# Every device here sits on a Production cell, so it reads its own line's state directly -
# ctx.state, ctx.production_rate, ctx.running - and carries no `serves` list. A `serves` list
# would be wrong by definition: a filling machine on Line1 is not serving Line1, it is Line1.
#
# NOTE the ctx path. DeviceView is flat: `ctx.state`, not `ctx.line.state`. The unit test in
# Task 5 uses a fake view with a nested attribute; a configuration file cannot.

devices:
  - id: MES-01
    equipment: MES-01
    target: {area: Production}
    tier: process
    signals:
      PackMlState:
        # Mirrored, not invented. The whole reason PlantContext exists is so that the state
        # on this topic is the same object the compressors and the boiler are reacting to.
        shape: stepped
        unit: "1"
        source: ctx.state
        tier: status
        param_type: Status
      PackMlStateCode:
        # The OMAC PackML numeric codes. Same source, same instant, lookup table attached -
        # so the code and the name can never disagree.
        shape: stepped
        unit: "1"
        source: ctx.state
        map:
          CLEARING: 1
          STOPPED: 2
          STARTING: 3
          IDLE: 4
          SUSPENDED: 5
          EXECUTE: 6
          STOPPING: 7
          ABORTING: 8
          ABORTED: 9
          HOLDING: 10
          HELD: 11
          UNHOLDING: 12
          SUSPENDING: 13
          UNSUSPENDING: 14
          RESETTING: 15
          COMPLETING: 16
          COMPLETE: 17
        tier: status
        param_type: Status
      ProductionRate:
        shape: derived
        unit: ea/h
        expr: nameplate_ea_h * ctx.production_rate
        params: {nameplate_ea_h: 1800.0}
        precision: 1
        range: [0, 2200]
      ThroughputTph:
        # ctx.throughput_tph is already nameplate_tph * production_rate, and nameplate_tph is
        # per-line in plant.yaml - so this one template publishes 12 t/h on Dormagen Line1 and
        # 5 t/h on Krefeld Line1 without knowing either number.
        shape: derived
        unit: t/h
        expr: ctx.throughput_tph
        precision: 3
        range: [0, 20]
        export_metric: true
      GoodCount:
        shape: counter
        unit: ea
        rate: ProductionRate * (1.0 - reject_fraction) / 3600.0
        params: {reject_fraction: 0.014}
        initial: 0.0
        tier: meter
        precision: 0
      RejectCount:
        shape: counter
        unit: ea
        rate: ProductionRate * reject_fraction / 3600.0
        params: {reject_fraction: 0.014}
        initial: 0.0
        tier: meter
        precision: 0
      TotalCount:
        shape: derived
        unit: ea
        expr: GoodCount + RejectCount
        precision: 0
        tier: meter
      CycleTime:
        # Seconds per unit. The 1.0 floor is the idle case: at zero rate the true cycle time
        # is infinite, and `cycle_time_max_s` says what gets published instead.
        shape: derived
        unit: s
        expr: min(3600.0 / max(ProductionRate, 1.0), cycle_time_max_s)
        params: {cycle_time_max_s: 600.0}
        precision: 3
        range: [0, 600]
      Availability:
        # Instantaneous, so this is a 0-or-100 square wave and NOT a rolling percentage.
        # window_agg reads numeric siblings only and skips bools, so it cannot see
        # ctx.running; the rolling view belongs in Grafana. ctx.running is a boolean and
        # Python's True is 1 in arithmetic.
        shape: derived
        unit: "%"
        expr: 100.0 * ctx.running
        precision: 1
        range: [0, 100]
      Performance:
        # Actual rate over ideal rate, which is what ctx.production_rate already is. Zero
        # while the line is down, 85-100 while it executes.
        shape: derived
        unit: "%"
        expr: 100.0 * ctx.production_rate
        precision: 2
        range: [0, 100]
        limits: {lo: 80.0, lolo: 70.0}
      Quality:
        # The 1.0 floor makes this 100 % before the first unit is made rather than 0 %,
        # which would alarm on every restart. Both counters start at zero, so this converges
        # on the true ratio within a minute of running.
        shape: derived
        unit: "%"
        expr: 100.0 * (1.0 - RejectCount / max(TotalCount, 1.0))
        precision: 3
        range: [0, 100]
        limits: {lo: 97.0, lolo: 95.0}
      Oee:
        shape: derived
        unit: "%"
        expr: Availability * Performance * Quality / 10000.0
        precision: 2
        range: [0, 100]
        limits: {lo: 65.0, lolo: 50.0}
        export_metric: true
      DowntimeReason:
        # Mapped from the same ctx.state as PackMlState, so a reason can never contradict the
        # state it is explaining. A reason drawn from a list would eventually publish
        # "MaterialShortage" on a line that was running.
        shape: stepped
        unit: "1"
        source: ctx.state
        map:
          IDLE: NoOrder
          STARTING: Startup
          EXECUTE: None
          HOLDING: ProcessHold
          HELD: MaterialShortage
          UNHOLDING: Recovering
          SUSPENDING: UpstreamBlocked
          SUSPENDED: UpstreamBlocked
          UNSUSPENDING: Recovering
          COMPLETING: OrderFinishing
          COMPLETE: OrderComplete
          RESETTING: Changeover
          ABORTING: Fault
          ABORTED: Fault
          CLEARING: FaultClearing
          STOPPING: OperatorStop
          STOPPED: OperatorStop
        tier: status
        param_type: Status
      BatchId:
        # dwell_s tracks Dormagen Line1's execute_s of 3600 s, so a batch id holds for about
        # as long as a batch. Krefeld's longer batches will see it change mid-batch; a
        # per-line batch identity would need a per-line template and buys nothing.
        shape: stepped
        unit: "1"
        choices: ["B-24101", "B-24102", "B-24103", "B-24104", "B-24105", "B-24106"]
        dwell_s: 3600.0
        tier: status
        param_type: Status
      RecipeId:
        shape: stepped
        unit: "1"
        choices: ["R-100-STD", "R-100-HIGH", "R-220-STD", "R-330-LOW"]
        weights: [6, 2, 3, 1]
        dwell_s: 7200.0
        tier: status
        param_type: Status

  - id: QA-01
    equipment: QA-01
    target: {area: Production}
    tier: process
    signals:
      Viscosity:
        # Inline quality: it degrades as the line runs harder, which is what makes the
        # limits worth watching rather than decorative.
        shape: derived
        unit: "mPa·s"
        expr: base_mpas + span_mpas * ctx.production_rate
        params: {base_mpas: 780.0, span_mpas: 145.0}
        precision: 1
        range: [0, 1500]
        limits: {lo: 750, lolo: 700, hi: 980, hihi: 1050}
        export_metric: true
      Density:
        shape: ou_walk
        unit: "kg/m³"
        mean: 1042.0
        sigma: 3.5
        tau: 600.0
        precision: 2
        range: [900, 1200]
        limits: {lo: 1030, hi: 1055}
      Moisture:
        shape: ou_walk
        unit: "%"
        mean: 0.062
        sigma: 0.012
        tau: 900.0
        precision: 4
        range: [0, 1]
        limits: {hi: 0.1, hihi: 0.15}
      RefractiveIndex:
        shape: ou_walk
        unit: "1"
        mean: 1.4712
        sigma: 0.0008
        tau: 1200.0
        precision: 5
        range: [1.3, 1.6]
        limits: {lo: 1.468, hi: 1.474}
      NirIndex:
        shape: ou_walk
        unit: "1"
        mean: 0.842
        sigma: 0.018
        tau: 300.0
        precision: 4
        range: [0, 2]
        limits: {lo: 0.78, hi: 0.9}
      ColorB:
        # CIE b*: yellowing is the classic thermal-history defect, so this one tracks
        # ambient rather than rate.
        shape: derived
        unit: "1"
        expr: base_b + ambient_k * (ctx.ambient_temp_c - 20.0) / 10.0
        params: {base_b: 2.4, ambient_k: 0.35}
        precision: 3
        range: [-10, 30]
        limits: {hi: 4.0, hihi: 6.0}

  - id: LAB-01
    equipment: LAB-01
    # The Quality area, not a Production cell - so no ctx.state is available here and every
    # signal is either a walk or a discrete. That is honest: a lab result is a sample taken
    # at some earlier time, not a live reading of the line.
    target: {area: Quality, line: Lab, cell: LIMS_01}
    tier: lab
    signals:
      SampleId:
        shape: stepped
        unit: "1"
        choices: ["S-88201", "S-88202", "S-88203", "S-88204", "S-88205"]
        dwell_s: 1800.0
        param_type: Status
      Viscosity:
        shape: ou_walk
        unit: "mPa·s"
        mean: 845.0
        sigma: 42.0
        tau: 7200.0
        precision: 1
        range: [0, 1500]
        limits: {lo: 750, lolo: 700, hi: 980, hihi: 1050}
      HydroxylNumber:
        shape: ou_walk
        unit: mgKOH/g
        mean: 56.2
        sigma: 1.4
        tau: 7200.0
        precision: 2
        range: [0, 120]
        limits: {lo: 52.0, hi: 60.0}
      WaterContent:
        shape: ou_walk
        unit: ppm
        mean: 320.0
        sigma: 65.0
        tau: 7200.0
        precision: 1
        range: [0, 2000]
        limits: {hi: 500, hihi: 800}
      Acidity:
        shape: ou_walk
        unit: mgKOH/g
        mean: 0.042
        sigma: 0.011
        tau: 7200.0
        precision: 4
        range: [0, 1]
        limits: {hi: 0.08, hihi: 0.12}
      ResultStatus:
        # Weighted 9:1 rather than an even draw: a lab that failed half its samples would be
        # a plant in crisis, and the console's alarm view should look like a working plant.
        shape: stepped
        unit: "1"
        choices: ["Pass", "Fail"]
        weights: [9, 1]
        dwell_s: 1800.0
        param_type: Status

  # Spec 8.5 and 12: the two pre-existing PLC templates, moved from conf/settings.yaml's
  # `plc:` key with their ids, equipment names, base values, variations and Units of Measure
  # untouched. `sensors:` became `signals:` because that is the key expand_template reads;
  # nothing that reaches the broker changes. `shape` is omitted, so both fall through to
  # `noise` - the only behaviour the old generator had.
  #
  # No `target`, which means every cell in a `kind: production` area. That is exactly what
  # create_plc's cartesian product did, so the topic set is unchanged too.
  - id: "001"
    equipment: "G1"
    tier: process
    signals:
      Temperature:
        base_value: 75.0
        variation: 2.0
        unit: "°C"
      Pressure:
        base_value: 150.0
        variation: 5.0
        unit: "psi"

  - id: "002"
    equipment: "FillingMachine"
    tier: process
    signals:
      FlowRate:
        base_value: 450.0
        variation: 20.0
        unit: "L/min"
```

`id: "001"` stays quoted. Unquoted, YAML reads it as the integer `1`, `expand_template` builds `1@Dormagen.Production.Line1.Cell1`, and the MQTT client id becomes `uns-sim-1@…` — a change to what appears on the wire, in a task whose whole point is that nothing changes.

- [ ] **Step 4: Write `conf/simulator/safety.yaml`**

```yaml
# conf/simulator/safety.yaml
# Spec 8.6. Gas detection, stack emissions, the safety instrumented system, and the weather.
#
# WS-01 is the family's reason to exist. Its five ambient signals derive from ctx rather than
# running sines of their own, because SiteState already computes them from each site's
# ambient_mean_c and ambient_swing_c in plant.yaml. That is what makes the correlation
# checkable end to end: the wet bulb WS-01 publishes is the same wet bulb CT-01 sizes its
# approach against, so a warm humid stretch really does show up as a hotter tower supply and
# a higher chiller kW - on three different topics, from one number.

devices:
  - id: GD-01
    equipment: GD-01
    # No `site`: GD_Zone1 exists at both, and a gas detector reads the air in front of it -
    # there is nothing site-specific to parameterise.
    target: {area: Safety, line: GasDetection, cell: GD_Zone1}
    tier: process
    signals:
      Lel:
        # Spec 8.6: hi 10, hihi 20. Percent of the lower explosive limit, and the two
        # thresholds are the conventional alarm and trip points.
        shape: ou_walk
        unit: "%"
        mean: 1.8
        sigma: 0.9
        tau: 120.0
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 20.0}
        export_metric: true
      H2S:
        shape: ou_walk
        unit: ppm
        mean: 0.6
        sigma: 0.35
        tau: 180.0
        precision: 2
        range: [0, 200]
        limits: {hi: 5.0, hihi: 10.0}
      CO:
        shape: ou_walk
        unit: ppm
        mean: 3.4
        sigma: 1.6
        tau: 180.0
        precision: 2
        range: [0, 500]
        limits: {hi: 25.0, hihi: 50.0}
      O2:
        # Spec 8.6: lo 19.5. The only signal in the file whose alarm is on the low side -
        # oxygen depletion, not accumulation.
        shape: ou_walk
        unit: "%"
        mean: 20.9
        sigma: 0.08
        tau: 300.0
        precision: 2
        range: [0, 25]
        limits: {lo: 19.5, lolo: 18.0}
        export_metric: true
      VOC:
        shape: ou_walk
        unit: ppm
        mean: 2.1
        sigma: 1.1
        tau: 240.0
        precision: 2
        range: [0, 500]
        limits: {hi: 20.0, hihi: 50.0}
      DetectorFault:
        # p is per one-second tick, so 3e-6 is roughly one fault a fortnight per detector.
        # bernoulli_event publishes nothing on a quiet tick and its tier is 0.0 (on change),
        # so this costs one message per fault rather than one per second.
        shape: bernoulli_event
        unit: "1"
        p: 0.000003
        choices: ["SensorDrift", "BeamBlocked", "CalibrationDue"]
        tier: event
        param_type: Alarm
      ZoneAlarmState:
        shape: stepped
        unit: "1"
        choices: ["Clear", "Warning", "Alarm", "Inhibited"]
        weights: [40, 4, 1, 2]
        dwell_s: 600.0
        tier: status
        param_type: Status

  - id: GD-02
    equipment: GD-02
    # Dormagen only: GD_Zone2 has no Krefeld counterpart. Written out in full rather than
    # sharing a YAML anchor with GD-01, for the same reason as EM-01/EM-02 in Task 16 -
    # `range` and `limits` drive `status`, so a silently inherited threshold is a silently
    # wrong alarm.
    target: {area: Safety, line: GasDetection, cell: GD_Zone2}
    tier: process
    signals:
      Lel:
        shape: ou_walk
        unit: "%"
        mean: 2.6
        sigma: 1.2
        tau: 120.0
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 20.0}
        export_metric: true
      H2S:
        shape: ou_walk
        unit: ppm
        mean: 1.1
        sigma: 0.5
        tau: 180.0
        precision: 2
        range: [0, 200]
        limits: {hi: 5.0, hihi: 10.0}
      CO:
        shape: ou_walk
        unit: ppm
        mean: 4.8
        sigma: 2.1
        tau: 180.0
        precision: 2
        range: [0, 500]
        limits: {hi: 25.0, hihi: 50.0}
      O2:
        shape: ou_walk
        unit: "%"
        mean: 20.8
        sigma: 0.1
        tau: 300.0
        precision: 2
        range: [0, 25]
        limits: {lo: 19.5, lolo: 18.0}
        export_metric: true
      VOC:
        shape: ou_walk
        unit: ppm
        mean: 3.6
        sigma: 1.7
        tau: 240.0
        precision: 2
        range: [0, 500]
        limits: {hi: 20.0, hihi: 50.0}
      DetectorFault:
        shape: bernoulli_event
        unit: "1"
        p: 0.000003
        choices: ["SensorDrift", "BeamBlocked", "CalibrationDue"]
        tier: event
        param_type: Alarm
      ZoneAlarmState:
        shape: stepped
        unit: "1"
        choices: ["Clear", "Warning", "Alarm", "Inhibited"]
        weights: [30, 5, 2, 2]
        dwell_s: 600.0
        tier: status
        param_type: Status

  - id: CEMS-01
    equipment: CEMS-01
    # Stack_S1 is Dormagen-only. No `serves`: the stack is the boiler's, and the boiler's own
    # load already lives on BLR-01. Coupling the two would need a serves list pointing at
    # production lines, which would say something false about what a stack serves.
    target: {area: Safety, line: Emissions, cell: Stack_S1}
    tier: process
    signals:
      NOx:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 118.0
        sigma: 14.0
        tau: 600.0
        precision: 1
        range: [0, 600]
        limits: {hi: 200.0, hihi: 250.0}
        export_metric: true
      SOx:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 22.0
        sigma: 6.0
        tau: 900.0
        precision: 1
        range: [0, 600]
        limits: {hi: 100.0, hihi: 150.0}
      CO:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 34.0
        sigma: 11.0
        tau: 300.0
        precision: 1
        range: [0, 600]
        limits: {hi: 100.0, hihi: 150.0}
      Particulate:
        shape: ou_walk
        unit: "mg/Nm³"
        mean: 4.2
        sigma: 1.3
        tau: 900.0
        precision: 2
        range: [0, 100]
        limits: {hi: 20.0, hihi: 30.0}
      O2:
        shape: ou_walk
        unit: "%"
        mean: 5.4
        sigma: 0.7
        tau: 600.0
        precision: 2
        range: [0, 21]
        limits: {lo: 1.5, hi: 9.0}
      FlueGasFlow:
        shape: ou_walk
        unit: "Nm³/h"
        mean: 24500.0
        sigma: 1800.0
        tau: 600.0
        precision: 1
        range: [0, 40000]
      StackTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c + rise_k
        params: {rise_k: 148.0}
        precision: 1
        range: [0, 350]
        limits: {hi: 210, hihi: 240}
      Opacity:
        shape: derived
        unit: "%"
        expr: base_pct + slope * Particulate
        params: {base_pct: 1.2, slope: 0.42}
        precision: 2
        range: [0, 100]
        limits: {hi: 10.0, hihi: 20.0}
      NoxMassTotal:
        # mg/Nm³ times Nm³/h is mg/h; the 1e-6 converts to kg/s along with the 3600. Getting
        # this factor wrong is invisible in the number and obvious in the trend a month later.
        shape: counter
        unit: kg
        rate: NOx * FlueGasFlow * 0.000000001 / 3.6
        initial: 18400.0
        tier: meter
        precision: 3
        export_metric: true

  - id: SIS-01
    equipment: SIS-01
    target: {area: Safety, line: Emissions, cell: Stack_S1}
    # Spec 8.6 puts this device on the `status` tier: interlocks are step changes, and
    # republishing "Healthy" every five seconds says nothing new.
    tier: status
    signals:
      TripStatus:
        shape: stepped
        unit: "1"
        choices: ["Healthy", "PreTrip", "Tripped", "Bypassed"]
        weights: [60, 4, 1, 2]
        dwell_s: 1800.0
        param_type: Status
      InterlockStatus:
        shape: stepped
        unit: "1"
        choices: ["Enabled", "Overridden"]
        weights: [40, 1]
        dwell_s: 3600.0
        param_type: Status
      EStopStatus:
        shape: stepped
        unit: "1"
        choices: ["Released", "Pressed"]
        weights: [200, 1]
        dwell_s: 1800.0
        param_type: Status
      GuardDoorStatus:
        shape: stepped
        unit: "1"
        choices: ["Closed", "Open"]
        weights: [25, 1]
        dwell_s: 900.0
        param_type: Status
      SafetyDemandCount:
        # A safety demand is a genuinely rare event. 2e-7 per second is roughly one every
        # eight weeks, which is the point: a demand counter that ticks visibly means the
        # protection layer is being used as a control layer.
        shape: counter
        unit: "1"
        rate: 0.0000002
        initial: 6.0
        tier: meter
        precision: 0
      ProofTestDueDays:
        # Counts down, so it is a `derived` off nothing but its own constants - a counter
        # cannot decrease (Task 6 clamps a negative rate to zero, deliberately).
        shape: constant
        unit: d
        value: 214.0
        precision: 0
        range: [0, 730]
        limits: {lo: 30.0, lolo: 7.0}

  - id: WS-01
    equipment: WS-01
    # Both sites, one template: every signal reads ctx, and ctx is already per-site. This is
    # the payoff of deriving instead of generating - a second diurnal per quantity would have
    # needed a second template carrying Krefeld's amplitudes.
    target: {area: Safety, line: WeatherStation, cell: WS_01}
    tier: process
    signals:
      AmbientTemp:
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c
        precision: 2
        range: [-30, 50]
        export_metric: true
      RelativeHumidity:
        shape: derived
        unit: "%"
        expr: ctx.ambient_rh_pct
        precision: 1
        range: [0, 100]
      WetBulbTemp:
        # The number CT-01's approach temperature is written against. Same value, two
        # families, one source.
        shape: derived
        unit: "°C"
        expr: ctx.wet_bulb_temp_c
        precision: 2
        range: [-30, 40]
        export_metric: true
      DewPoint:
        # The Magnus-Tetens rule of thumb, accurate to about half a degree above 50 % RH,
        # which is where this plant's humidity sits. Deriving it from the same two ctx
        # values keeps it consistent with the wet bulb rather than merely near it.
        shape: derived
        unit: "°C"
        expr: ctx.ambient_temp_c - (100.0 - ctx.ambient_rh_pct) / 5.0
        precision: 2
        range: [-40, 40]
      WindSpeed:
        shape: derived
        unit: m/s
        expr: ctx.wind_speed_ms
        precision: 2
        range: [0, 40]
      WindDirection:
        # The one genuinely independent signal here: PlantContext models wind speed because
        # it affects the cooling tower, and has no reason to model direction.
        shape: ou_walk
        unit: "°"
        mean: 232.0
        sigma: 35.0
        tau: 1800.0
        precision: 1
        range: [0, 360]
      SolarIrradiance:
        # `diurnal` because PlantContext has no sunlight. elapsed_s is time since process
        # start, not time of day, so phase_s positions the curve against startup rather than
        # against noon - and `range` clamps the trough to zero, which is what makes a sine a
        # usable irradiance curve at all.
        shape: diurnal
        unit: "W/m²"
        mean: 210.0
        amplitude: 480.0
        period_s: 86400.0
        phase_s: 0.0
        noise: 18.0
        precision: 1
        range: [0, 1000]
      RainfallTotal:
        shape: counter
        unit: mm
        rate: 0.0000023
        initial: 812.4
        tier: meter
        precision: 2
      BarometricPressure:
        shape: derived
        unit: mbar
        expr: ctx.barometric_mbar
        precision: 2
        range: [900, 1080]
        limits: {lo: 970, hi: 1040}
```

`ProofTestDueDays` is `shape: constant`, not `counter`. A counter cannot count down — Task 6 clamps a negative rate to zero on purpose, so that a totaliser never runs backwards — and no shape in the catalogue decreases monotonically. A constant is the truthful option: the days-remaining figure genuinely changes only when somebody reschedules the proof test, which is a configuration change, not a signal.

- [ ] **Step 5: Run the tests**

Run: `cd 99_simulator && uv run pytest test/test_conf_files.py -v`
Expected: all pass.

Triage, if they do not:
- `ValueError: unknown target selector(s)` names the key — the `target` blocks here use `area`, `line` and `cell` only.
- A `serves` load error from `production.yaml` means a `serves` list was added to a device on a production cell. None belongs there; those devices read `ctx.state` directly.
- `test_packml_state_code_maps_every_state` failing with a set difference means a PackML state was dropped from one of the two `map` blocks. There are seventeen, and both maps need all of them.
- A cycle error naming `MES-01` means a `derived` expression was pointed the wrong way — `TotalCount` reads the counters, `Quality` reads `TotalCount`, and `Oee` reads `Quality`, in that order.

- [ ] **Step 6: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add conf/simulator/production.yaml conf/simulator/safety.yaml 99_simulator/test/test_conf_files.py
git commit -m "feat(simulator): add the production and safety device families"
```

With all six families landed, `full` resolves to **55 devices and 427 signal instances** — spec §8's "~50 devices, ~400 signals". The per-template tables in `test_conf_files.py` are what make those two totals derived rather than asserted, so the next person to add a device changes one table entry and the totals follow.

---

## Task 19: Settings, the volume guard, Docker, README and the ADR

Everything that makes the six family files reachable from a real deployment, plus the one test that stops `full` becoming the default by accident.

**Files:**
- Create: `99_simulator/test/test_volume.py`, `docs/adr/0006-simulator-plant-model-and-signal-generation.md`
- Modify: `conf/settings.yaml:141-175`, `99_simulator/src/uns_simulator/profiles.py`, `99_simulator/src/uns_simulator/simulator.py:35-43`, `99_simulator/test/test_targeting.py`, `99_simulator/Dockerfile:52`, `99_simulator/README.md`

**Interfaces:**
- Consumes: `LoadedProfile` (Task 12), `load_simulator_config` (Task 16), all six family files (Tasks 16–18).
- Produces: `LoadedProfile.messages_per_second(self) -> dict[str, float]` — periodic publish rate per cadence tier. Sub-project B's `GET /simulator/status` returns this as its `msg_per_sec` field, so it lives on the profile rather than in the test.

### The ADR number is 0006, not 0005

Spec §13 says `docs/adr/0005-simulator-plant-model-and-signal-generation.md`, and spec B §11 reasons from "`docs/adr/` currently ends at `0004`". Both are wrong: `docs/adr/0005-graphql-mutations-for-console-configuration.md` is committed and accepted (`58618df2`). This plan's ADR therefore takes **0006**. Reusing 0005 would give the directory two documents with one number, which is the one thing a numbered decision log cannot survive.

### The whole legacy `create_plc` block comes out of `conf/settings.yaml`

Spec §12 says the `simulator.plc` list is "still loaded and still instantiated per production cell", and spec §8.5 moves those same two templates into `production.yaml`. Both at once means both: `simulator.py` keeps `self.plc_templates = list(settings.get("plc") or [])` feeding the legacy `create_plc` path, and `production.yaml`'s `001`/`002` feed `SignalDevice`. The result is two devices publishing `.../Cell1/G1/ProcessValue/Temperature` with independently drawn values — a topic served by two publishers, which no consumer can detect and no test currently forbids.

Spec §13 settles it in one line — "PLC templates migrate out to `production.yaml` (the keys stay supported)" — and that is the reading that keeps §12 true as well: **the keys stay supported by the loader, and stop being declared in the shipped file.** A deployment carrying its own `settings.yaml` with `plc:` still works exactly as before — that is what §12's two rows promise, and Step 1's regression guard is what pins it. The repository's own configuration gets those devices from `production.yaml` instead, once.

**Read `create_plc` (`simulator.py:45-82`) before editing the file, because removing `plc:` alone makes things worse rather than better.** The two branches are mutually exclusive: with `plc_templates` non-empty it instantiates the templates and `continue`s; with `plc_templates` empty it falls through to `equipment_fallback` and creates `simulation.plc_count` copies of it *per cell*. So deleting only the `plc:` list flips the shipped configuration into the fallback branch and produces **eight `MixerTank` PLCs** — 2 per production cell, from `plc_count: 2` — publishing `Temperature` and `Pressure` on topics no family file declares. That is a worse outcome than the double-publish it was meant to fix, and it would not fail a single existing test.

So all three keys go: `plc:`, `simulation.plc_count`, and `equipment.mixer_tank`. `plc_count` is read *only* in the fallback branch, and `mixer_tank` is the only thing that branch can build, so the three are one feature and are removed together. `create_plc()` then returns `[]` for the shipped configuration, `SCADA` and `HMI` are untouched, and every plant signal comes from `SignalDevice`.

Spec §12's "`simulator.equipment.mixer_tank` fallback — still honoured when no templates resolve" is a statement about the loader, and it stays true: `self.equipment_fallback = settings.get("equipment.mixer_tank")` is unchanged, and Step 1's guard exercises that branch by supplying the key directly. A promise about supported configuration is kept by the code that reads it plus a test, not by shipping the configuration switched on.

`simulator.hierarchy` is the opposite case and stays: it is the fallback for a deployment with no `conf/simulator/` directory at all (Task 16), so deleting it would make `raw_config["hierarchy"]` a `KeyError` in exactly the situation it exists to cover. A comment says which file wins, because a hierarchy that is silently ignored is worse than one that is absent.

- [ ] **Step 1: Write the failing tests**

Two files. First, `99_simulator/test/test_volume.py`, which is new:

```python
"""Spec 9 and 14: the shipped default must not be a firehose.

`full` is roughly 100 msg/s of eight-level topics, and the graphdb mapper MERGEs once per
topic level on every message - so the volume risk is Neo4j's write path, not Timescale's.
`small` is the shipped default for that reason, and this file is what keeps it small: a
family added to the wrong profile, or a tier_scale dropped from 6.0 to 1.0, shows up here
rather than in a mapper falling quietly behind in production.

The assertions are bands, not numbers. A tight figure would break on every legitimate device
added, which trains people to edit the test; an order-of-magnitude band breaks only when the
shipped default has genuinely changed character.
"""

from pathlib import Path

import pytest
import yaml
from uns_simulator.profiles import TIER_DEFAULTS, load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"

# Spec 9: "small (default) ~5 msg/s". The ceiling is that figure; the floor catches the
# opposite failure, a profile that resolves to almost nothing and passes by being broken.
SMALL_MAX_MSG_PER_SEC = 5.0
SMALL_MIN_MSG_PER_SEC = 0.5

# Spec 9: "full ~100 msg/s". Bands wide enough to absorb a family gaining a few devices.
FULL_MIN_MSG_PER_SEC = 70.0
FULL_MAX_MSG_PER_SEC = 160.0


@pytest.fixture
def raw():
    return read_simulator_conf(CONF_DIR)


@pytest.fixture
def settings_doc():
    return yaml.safe_load((CONF_DIR / "settings.yaml").read_text(encoding="utf-8"))


def test_the_shipped_default_profile_is_small(settings_doc):
    """The default is a deployment decision, so it is asserted against the shipped file."""
    assert settings_doc["simulator"]["simulation"]["profile"] == "small"


def test_the_shipped_config_declares_a_seed(settings_doc):
    """Spec 14 mitigates flaky correlation tests with a fixed default seed.

    Absent, every restart reshuffles every signal and two runs of the same profile cannot be
    compared - which is most of the value of having a profile.
    """
    assert isinstance(settings_doc["simulator"]["simulation"]["seed"], int)


def test_the_legacy_create_plc_config_is_no_longer_declared_in_settings(settings_doc):
    """The three keys of the legacy generator are one feature and leave together.

    `plc:` leaves because production.yaml declares those two templates now, and declared in
    both they publish twice. `equipment.mixer_tank` and `plc_count` leave with it because
    create_plc's two branches are mutually exclusive: with no `plc:` list it falls through to
    the fallback and builds `plc_count` MixerTanks per cell, so removing one key and not the
    other three would replace a double-publish with eight undeclared devices.

    simulator.py still reads all three for deployments that carry their own settings.yaml;
    test_targeting.py exercises both branches. This asserts about the shipped file only.
    """
    simulator = settings_doc["simulator"]
    assert "plc" not in simulator
    assert "mixer_tank" not in simulator.get("equipment", {})
    assert "plc_count" not in simulator["simulation"]


def test_the_settings_hierarchy_is_kept_as_the_no_conf_simulator_fallback(settings_doc):
    """Removing it would make raw_config["hierarchy"] a KeyError when conf/simulator/ is absent."""
    assert settings_doc["simulator"]["hierarchy"]["enterprise"] == "CovestroAG"


def test_small_stays_under_the_default_ceiling(raw):
    rate = sum(load_profile(raw, "small").messages_per_second().values())
    assert SMALL_MIN_MSG_PER_SEC < rate < SMALL_MAX_MSG_PER_SEC, f"small resolved to {rate:.2f} msg/s"


def test_full_is_in_the_band_the_spec_claims(raw):
    rate = sum(load_profile(raw, "full").messages_per_second().values())
    assert FULL_MIN_MSG_PER_SEC < rate < FULL_MAX_MSG_PER_SEC, f"full resolved to {rate:.2f} msg/s"


def test_full_is_at_least_an_order_of_magnitude_busier_than_small(raw):
    """The two profiles must be genuinely different, not two names for the same load.

    This is the assertion that survives the device inventory growing: both bands above move
    together, this ratio does not.
    """
    small = sum(load_profile(raw, "small").messages_per_second().values())
    full = sum(load_profile(raw, "full").messages_per_second().values())
    assert full / small > 20.0


def test_the_fast_tier_is_absent_from_small(raw):
    """A 1 s tier in the default profile would dominate everything else in this file."""
    assert load_profile(raw, "small").messages_per_second()["fast"] == 0.0


def test_every_signal_lands_on_a_known_tier(raw):
    """The only check that a per-signal `tier` is spelled correctly.

    `_resolve_tiers` validates the keys of a `simulation.tiers` override, and nothing
    validates a `tier:` written on a signal. A typo there does not raise - the signal is
    simply never scheduled, and a silently unpublished topic is the hardest kind of bug to
    notice in a simulator whose whole output is topics.
    """
    for profile_name in ("small", "full"):
        for device in load_profile(raw, profile_name).devices:
            for signal in device.signals:
                assert signal.tier in TIER_DEFAULTS, f"{device.id}/{signal.name}: unknown tier {signal.tier!r}"


def test_messages_per_second_reports_every_tier(raw):
    """Sub-project B renders this per tier, so a missing key is a missing row, not a zero."""
    rates = load_profile(raw, "full").messages_per_second()
    assert set(rates) == set(TIER_DEFAULTS)
    assert rates["event"] == 0.0  # `event` publishes on change; it has no periodic rate
```

Second, the regression guard spec §11 asks `test_targeting.py` for: "the existing `simulator.plc` + `equipment.mixer_tank` config still produces exactly today's 8 devices with today's topics". It could not be written before now, because until this task the legacy config was still live and the guard would have been asserting the status quo against itself. Now that the shipped file no longer declares it, the guard is the only thing standing between "the keys stay supported" and a quiet regression.

The legacy literal below is deliberately a second, independent copy of frozen history — Task 18's `LEGACY_PLC_SENSORS` in `test_conf_files.py` pins `production.yaml` to the same past. Two independent witnesses is what a regression guard wants: edit either one and the other still testifies. Sharing a constant between them would let one edit move both.

Append to `99_simulator/test/test_targeting.py`:

```python
# The `simulator.plc` and `simulator.equipment.mixer_tank` blocks as conf/settings.yaml held
# them before Task 19 removed them, and the hierarchy they expanded against. Frozen history:
# nothing should ever edit these to make a test pass. `create_plc` is legacy and its output
# is what spec 12 promises stays identical for a deployment that still configures it.
LEGACY_HIERARCHY = {
    "enterprise": "CovestroAG",
    "sites": [
        {
            "name": "Dormagen",
            "areas": [
                {
                    "name": "Production",
                    "lines": [
                        {"name": "Line1", "cells": ["Cell1", "Cell2"]},
                        {"name": "Line2", "cells": ["Cell1"]},
                    ],
                }
            ],
        },
        {"name": "Krefeld", "areas": [{"name": "Production", "lines": [{"name": "Line1", "cells": ["Cell1"]}]}]},
    ],
}

LEGACY_PLC = [
    {
        "id": "001",
        "equipment": "G1",
        "sensors": {
            "Temperature": {"base_value": 75.0, "variation": 2.0, "unit": "°C"},
            "Pressure": {"base_value": 150.0, "variation": 5.0, "unit": "psi"},
        },
    },
    {"id": "002", "equipment": "FillingMachine", "sensors": {"FlowRate": {"base_value": 450.0, "variation": 20.0, "unit": "L/min"}}},
]

LEGACY_MIXER_TANK = {
    "name": "MixerTank",
    "sensors": {
        "Temperature": {"base_value": 75.0, "variation": 2.0, "unit": "°C"},
        "Pressure": {"base_value": 150.0, "variation": 5.0, "unit": "psi"},
    },
}

TODAYS_LEGACY_TOPIC_PREFIXES = {
    "CovestroAG/Dormagen/Production/Line1/Cell1/G1",
    "CovestroAG/Dormagen/Production/Line1/Cell2/G1",
    "CovestroAG/Dormagen/Production/Line2/Cell1/G1",
    "CovestroAG/Krefeld/Production/Line1/Cell1/G1",
    "CovestroAG/Dormagen/Production/Line1/Cell1/FillingMachine",
    "CovestroAG/Dormagen/Production/Line1/Cell2/FillingMachine",
    "CovestroAG/Dormagen/Production/Line2/Cell1/FillingMachine",
    "CovestroAG/Krefeld/Production/Line1/Cell1/FillingMachine",
}


def _legacy_simulator(plc_templates, equipment_fallback, plc_count=2):
    """A UnifiedNamespaceSimulator with only the attributes create_plc reads.

    `__new__` rather than `__init__` for the same reason test_hierarchy.py does it: `__init__`
    loads profiles, builds a PlantContext and constructs MQTT devices, none of which the
    legacy path touches.
    """
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sim.mqtt_config = {}
    sim.hierarchies = expand_hierarchy_paths(LEGACY_HIERARCHY)
    sim.plc_templates = plc_templates
    sim.equipment_fallback = equipment_fallback
    sim.simulation_config = {"plc_count": plc_count}
    return sim


def test_the_legacy_plc_config_still_produces_todays_eight_devices(monkeypatch):
    """Spec 11's regression guard: two templates times four production cells, same topics."""
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    plcs = _legacy_simulator(LEGACY_PLC, None).create_plc()

    assert len(plcs) == 8  # noqa: PLR2004
    prefixes = {
        plc.hierarchy.get_parameter_topic(plc.equipment.name, ParameterType.PROCESS_VALUE, "x").rsplit("/", 2)[0]
        for plc in plcs
    }
    assert prefixes == TODAYS_LEGACY_TOPIC_PREFIXES
    assert len({plc.plc_id for plc in plcs}) == 8, "device ids stay unique per cell"  # noqa: PLR2004


def test_the_mixer_tank_fallback_is_still_honoured_when_no_templates_resolve(monkeypatch):
    """Spec 12's second row. Also the branch that makes removing only `plc:` a mistake.

    Empty templates plus a fallback is `plc_count` MixerTanks per cell - eight here - which is
    why Task 19 removes `plc_count` and `equipment.mixer_tank` alongside `plc:` rather than
    leaving the shipped file one deletion away from publishing them.
    """
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    plcs = _legacy_simulator([], LEGACY_MIXER_TANK).create_plc()

    assert len(plcs) == 8  # noqa: PLR2004
    assert {plc.equipment.name for plc in plcs} == {"MixerTank"}


def test_no_legacy_devices_are_created_without_templates_or_a_fallback(monkeypatch):
    """What the shipped configuration now resolves to: nothing from the legacy path."""
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    assert _legacy_simulator([], None).create_plc() == []
```

`test_targeting.py` gains four imports for this — put them with the existing ones at the top of the file, since a function-scope import trips ruff's preview `PLC0415`:

```python
from uns_simulator import devices
from uns_simulator.models import ParameterType, expand_hierarchy_paths
from uns_simulator.simulator import UnifiedNamespaceSimulator
```

`DummyClient` is the two-method async context manager already defined in `test_hierarchy.py`; copy it into `test_targeting.py` rather than importing across test modules. It is nine lines, and `test_devices.py` (Task 13) has its own richer copy for the same reason.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd 99_simulator && uv run pytest test/test_volume.py -x`
Expected: `AttributeError: 'LoadedProfile' object has no attribute 'messages_per_second'`.

Run: `cd 99_simulator && uv run pytest test/test_targeting.py -k "legacy or mixer" -v`
Expected: the three new cases fail on the missing imports, then — once those are added — `test_the_legacy_create_plc_config_is_no_longer_declared_in_settings` in `test_volume.py` is the only remaining failure, because the settings edit has not happened yet. The three `create_plc` cases supply their own configuration and should pass as soon as they import, which is the point: they do not depend on what `settings.yaml` says.

- [ ] **Step 3: Add `messages_per_second` to `LoadedProfile`**

In `99_simulator/src/uns_simulator/profiles.py`, add the method to `LoadedProfile`:

```python
    def messages_per_second(self) -> dict[str, float]:
        """Periodic publish rate per cadence tier, for the volume guard and the control API.

        Counts periodic publishing only. A `tier` whose interval is 0.0 - `event`, by
        default - publishes on change and contributes nothing here, which is honest rather
        than convenient: the two `bernoulli_event` detector faults in safety.yaml average
        about one message a fortnight each, and rounding that to zero is the right rounding.

        A signal on an unrecognised tier is skipped rather than crashing a status endpoint;
        `test_volume.py` is what makes such a signal fail loudly at the right time.
        """
        rates = dict.fromkeys(self.tiers, 0.0)
        for device in self.devices:
            if not device.enabled:
                continue
            for signal in device.signals:
                interval = self.tiers.get(signal.tier, 0.0)
                if interval > 0.0:
                    rates[signal.tier] += 1.0 / interval
        return rates
```

`dict.fromkeys(self.tiers, 0.0)` rather than a comprehension over `TIER_DEFAULTS`: `self.tiers` is already the scaled, override-merged mapping with exactly the default tier names as keys, so this reports the tiers this profile actually runs.

- [ ] **Step 4: Amend `conf/settings.yaml`**

Replace the `plc:` block (lines 141–159) and the `simulation:` block (lines 160–163) with a `simulation:` block only:

```yaml
  # The legacy `plc:` list moved to conf/simulator/production.yaml as templates `001` and
  # `002`, unchanged. `simulator.py` still reads this key, so a deployment carrying its own
  # settings.yaml with `plc:` keeps working - but declaring it here as well as in
  # production.yaml would put two publishers on every G1 and FillingMachine topic.
  simulation:
    # Spec 9: `small` is the shipped default because the graphdb mapper MERGEs once per topic
    # level on every message. Switch to `full` for the complete ~55-device plant.
    profile: "small"
    # A fixed seed makes two runs of one profile comparable. Change it to get a different
    # plant with the same shape.
    seed: 20260831
    # Superseded by `tiers` below, which is why it still reads 5.0: spec 12 requires
    # `interval` to be honoured as the `process` tier when no `tiers` block exists, and a
    # deployment that deletes `tiers` should land back on today's behaviour, not on a default.
    interval: 5.0
    duration: 5  # minutes; 0 = run until stopped (Compose sets this to 0)
    # Seconds per cadence tier, before the profile's `tier_scale` multiplies them. `event` is
    # 0.0 meaning "publish on change", and scaling zero keeps it zero - a slow profile must
    # not turn an alarm topic into a slow periodic one.
    tiers:
      fast: 1.0
      process: 5.0
      energy: 15.0
      status: 30.0
      meter: 900.0
      lab: 1800.0
      event: 0.0
```

Then delete the `equipment:` block (lines 164–175 of the original file) as well, so the region from the old `plc:` through the old `equipment.mixer_tank` is replaced by the `simulation:` block above and nothing else. `dynaconf_merge: true` on the last line stays.

The file's `simulator` section afterwards is exactly three keys — `mqtt`, `hierarchy`, `simulation` — and `create_plc()` returns `[]`. If a diff shows `plc_count` or `mixer_tank` surviving, the shipped configuration publishes eight `MixerTank` PLCs; `test_the_legacy_create_plc_config_is_no_longer_declared_in_settings` is what catches that.

Add one comment above the existing `hierarchy:` key, which is otherwise indistinguishable from live configuration:

```yaml
  # Fallback only. conf/simulator/plant.yaml replaces this whole block when it exists, and it
  # does in this repository - so edits here have no effect unless that file is removed. Kept
  # because a deployment with no conf/simulator/ directory still has to have a plant.
  hierarchy:
```

- [ ] **Step 5: Wire `simulation.seed` in `simulator.py`**

Task 15 left `__init__` passing only its own `seed` argument, so `simulation.seed` in `settings.yaml` would be read by nobody. Change the one line:

```python
        requested = profile_name or self.simulation_config.get("profile", "full")
        configured_seed = seed if seed is not None else self.simulation_config.get("seed")
        raw_config = load_simulator_config(settings)
        self.profile: LoadedProfile = load_profile(raw_config, requested, seed=configured_seed)
```

The constructor argument still wins, because that is how sub-project B's `PUT /simulator/profile` will pass a seed chosen in the console, and a file must not override a deliberate runtime choice.

- [ ] **Step 6: Run the tests**

Run: `cd 99_simulator && uv run pytest test/test_volume.py test/test_targeting.py -v`
Expected: all pass.

If `test_small_stays_under_the_default_ceiling` fails high, print the breakdown before changing the threshold:

```bash
cd 99_simulator && uv run python -c "
from pathlib import Path
from uns_simulator.profiles import load_profile, read_simulator_conf
p = load_profile(read_simulator_conf(Path('../conf')), 'small')
print(p.report.per_family)
print({k: round(v, 3) for k, v in p.messages_per_second().items()})
"
```

A non-zero `fast` entry means `asset_health` reached `small`. A `process` figure six times what you expected means `tier_scale` is 1.0 rather than 6.0.

- [ ] **Step 7: Add the Docker copy line**

In `99_simulator/Dockerfile`, after line 52:

```dockerfile
COPY ./conf/settings.yaml /app/conf/settings.yaml
COPY ./conf/simulator /app/conf/simulator
```

Compose and the `docker run` in the file's own header comment both bind-mount the whole of `./conf`, so neither is affected. The line is for the case where nothing is mounted: without it the image starts, finds no `conf/simulator/` directory, silently falls back to `simulator.hierarchy`, and — with the legacy generator now gone from that file too — publishes nothing but `SCADA` and `HMI`. A container that starts, connects, logs no error and simulates no plant. `COPY ./conf/settings.yaml` on the line above exists for exactly that reason, and the new directory is now half of the configuration it was standing in for.

- [ ] **Step 8: Write the README section**

Add to `99_simulator/README.md`, after the "Repository layout" section. Also add the four new modules to that layout list:

```markdown
- src/uns_simulator/
  - signals.py — the ten signal shapes and their status derivation ([src/uns_simulator/signals.py](src/uns_simulator/signals.py))
  - expressions.py — the whitelisted expression evaluator used by `derived` and `counter` ([src/uns_simulator/expressions.py](src/uns_simulator/expressions.py))
  - plant.py — PackML line state, site ambient conditions, the plant clock ([src/uns_simulator/plant.py](src/uns_simulator/plant.py))
  - profiles.py — device targeting, profile resolution, the conf/simulator reader ([src/uns_simulator/profiles.py](src/uns_simulator/profiles.py))
```

Then the section itself:

````markdown
## The plant model

The simulator is not a set of independent random generators. One `PlantClock` ticks every
second and drives a `PlantContext`: per site, ambient temperature, humidity, wet bulb, wind
and barometric pressure, plus the shift and the electricity tariff period; per production
line, a PackML state machine that only ever takes legal transitions, and the production
rate, throughput, heat load and air demand that follow from it.

Devices read that context. A compressor's load follows the air demand of the lines it
`serves`; a boiler's steam flow follows their heat load, but through a first-order lag, so
it trails a line stop by minutes while the compressors react in seconds. The cooling tower
sizes its approach temperature against the wet bulb the weather station publishes — the same
number, not a second model of it — so a warm humid stretch shows up as a hotter tower supply
**and** a higher chiller kW.

That is the point of the whole design: values that move together for a reason, so a consumer
built against this data behaves like one built against a plant.

### Profiles

`conf/simulator/plant.yaml` declares the whole plant; a profile narrows it. Select one with
`simulator.simulation.profile` in `conf/settings.yaml`.

| Profile | Sites | Families | Devices | Rate |
|---|---|---|---|---|
| `small` (default) | Dormagen, first cell per line | energy, water, production | 11 | ~2 msg/s |
| `full` | Dormagen, Krefeld | all six | 55 | ~120 msg/s |

`small` is the default because the graphdb mapper performs `MERGE` work once per topic level
on **every** message, and eight-level topics at `full` rate are a heavy sustained write load
on Neo4j. The historian only appends, so it is not the constraint. `test/test_volume.py`
enforces the default: a family added to the wrong profile fails a test rather than a mapper.

A profile also carries `tier_scale`, which multiplies every cadence interval — `small` uses
6.0, so its 5 s process tier publishes every 30 s.

### Cadence tiers

Every signal belongs to a tier, and the tier decides how often it publishes. Intervals are
configurable under `simulator.simulation.tiers`.

| Tier | Interval | What is on it |
|---|---|---|
| `fast` | 1 s | vibration, motor current |
| `process` | 5 s | temperatures, pressures, flows, levels, analysers |
| `energy` | 15 s | power, power factor, per-phase voltage and current |
| `status` | 30 s | PackML state, equipment status, SIS status |
| `meter` | 900 s | cumulative kWh, m³, Nm³ and tonne registers |
| `lab` | 1800 s | LIMS sample results |
| `event` | on change | alarms, trips, detector faults |

Evaluation and publishing are separate. Every signal is evaluated on every one-second tick
regardless of tier, so a 15-minute meter register has integrated all 900 seconds rather than
sampling 900 seconds apart. The tier controls publishing only.

### Signal shapes

| Shape | Behaviour | Key parameters |
|---|---|---|
| `noise` (default) | Gaussian around `base_value` | `base_value`, `variation` |
| `constant` | A fixed value | `value` |
| `ou_walk` | Mean-reverting random walk; drifts and returns | `mean`, `sigma`, `tau` |
| `diurnal` | Sine over `period_s`, plus optional noise | `mean`, `amplitude`, `period_s`, `phase_s` |
| `sawtooth` | Fills to `high`, drains to `low`, independent rates | `low`, `high`, `fill_rate`, `drain_rate` |
| `counter` | Monotonic register; `rate` is an expression in units per second | `rate`, `initial`, `rollover` |
| `window_agg` | Rolling min/max/mean of a **sibling** over `window_s` | `source`, `window_s`, `agg` |
| `derived` | An expression over siblings and `ctx` | `expr`, `params` |
| `stepped` | A discrete: mirrored from a `ctx` path, or drawn from `choices` | `source`, `choices`, `map`, `weights`, `dwell_s` |
| `bernoulli_event` | With probability `p` per tick, emit one of `choices` | `p`, `choices` |

`derived` and `counter.rate` take arithmetic over sibling signal names, keys of the signal's
own `params`, and `ctx.*`. Permitted calls are `min`, `max`, `abs`, `round`, `clamp`, `sqrt`
and `exp`. It is a whitelisted AST walk, never `eval`: attribute access off anything but
`ctx`, subscripts, lambdas, comprehensions and imports are all rejected when the file loads,
and a reference cycle between `derived` signals is rejected the same way.

`unit` is required on every signal. A dimensionless ratio declares `unit: "1"` rather than
omitting the key, so an omission is always a mistake and never a choice.

### Adding a device

1. Pick the family file in `conf/simulator/` — or add a family name to `FAMILIES` in
   `profiles.py` and create the file.
2. Add an entry under `devices:` with `id`, `equipment`, a `target`, a `tier`, and `signals`.
   An absent `target` means every cell in a `kind: production` area.
3. If it should follow production, give it `serves: [Site/Area/Line, ...]` and read
   `ctx.served_*` in its expressions. `served_throughput_tph`, `served_heat_load` and
   `served_air_demand` are **sums** over the served lines, so divide by a `served_lines`
   parameter if the device should behave the same at a one-line site as at a two-line one.
4. Update `EXPECTED_SIGNAL_COUNT` and `EXPECTED_DEVICE_COUNT` in `test/test_conf_files.py`.
   Those tables are per template, so the suite's totals are derived from them rather than
   asserted, and a device that fails to resolve names itself in the failure.
````

- [ ] **Step 9: Write the ADR**

Create `docs/adr/0006-simulator-plant-model-and-signal-generation.md`, following the shape of `0005`:

```markdown
---
status: accepted
---

# Simulator plant model and signal generation

The simulator published two PLC templates of Gaussian noise per production cell. It now
publishes about 55 devices and 430 signals across six families — energy, water, utilities,
asset health, production and safety — and every value is computed from one shared plant
state rather than drawn independently.

Independent noise is enough to prove a mapper writes what it receives, and that is all the
old simulator was for. It is not enough to develop against. A console showing site kW, a
cooling tower supply temperature and a line's PackML state side by side is showing three
unrelated random walks, so nothing built on top can be checked: an OEE calculation cannot be
wrong, a correlation cannot be missing, an alarm cannot be spurious, because there is no
underlying fact for any of them to disagree with. Every consumer in this platform — the
graphdb mapper's node model, the historian's Metric extraction, the frontend's Process
Visualization, the Alert Rules of ADR 0005 — is developed against this data.

So the simulator gained a model of the plant: a PackML state machine per production line
taking only legal transitions, ambient conditions per site, and a `PlantContext` that every
device reads. A compressor's load follows the air demand of the lines it serves. A cooling
tower's approach temperature is set by the wet bulb the weather station publishes. Values
move together because they are computed from the same state, which is what makes them worth
developing against.

## Considered Options

**More templates of the same kind** was rejected. Reaching 400 signals by adding 400 more
independent generators multiplies the output and adds nothing: the failure is that the values
are unrelated, and more unrelated values is more of the failure.

**Replaying a recorded plant dataset** was rejected. It would be the most realistic option
and the least usable one: a fixed recording cannot be started, stopped, held or reconfigured,
it cannot exercise a state the recording never entered, and the recording itself would be
plant data with all the handling that implies.

**A physics solver** was rejected as the wrong tool. Mass and energy balances would buy
accuracy nobody consuming this data can use, at the cost of a component whose behaviour is
harder to predict than the platform it exists to test. First-order lags and algebraic
relations between named signals are enough for every correlation the platform needs to show.

**One topic per signal** was retained rather than bundling signals into nested payloads.
Bundling would cut the message count several-fold, which is tempting given that the volume
constraint is real. It was rejected because the Metric Key in `CONTEXT.md` is the topic
segments below the Asset plus the dotted path within the payload, so bundling changes the
shape of every Metric Key in the platform — a data-model change, made to relieve a load
problem that a profile already solves.

## Consequences

Volume is now a real constraint, and it lands on Neo4j rather than Timescale: the graphdb
mapper performs `MERGE` work per topic level on every message, while the historian appends.
`full` is roughly 120 msg/s of eight-level topics. So `small` — one site, three families, all
cadences scaled by six, about 2 msg/s — is the shipped default, `full` is opt-in through
`simulator.simulation.profile`, and `test_volume.py` asserts the default stays small.

Configuration moved out of `conf/settings.yaml` into `conf/simulator/*.yaml`, read directly
rather than through Dynaconf, because `uns_config.get_settings()` hardcodes its settings
files for all nine modules and widening it for one would change config loading platform-wide.
The `simulator.plc` and `simulator.equipment.mixer_tank` keys stay supported by the loader but
are no longer declared in the shipped file, because `create_plc`'s two branches are mutually
exclusive and leaving either key in place would have the legacy generator publishing on top of
the new devices — the same topics twice from `plc:`, or eight undeclared `MixerTank`s from the
fallback. The two PLC templates are declared in `conf/simulator/production.yaml` instead, with
their equipment names, base values, variations and Units of Measure unchanged, so the topics
and payloads they produced before are the topics and payloads they produce now.

`derived` signals introduced an expression language, which is a cost. It is bounded by being
a whitelisted AST walk over arithmetic, comparisons, `ctx.*` and seven named functions, with
every rejection raised when the file loads and naming the offending construct. There is no
`eval` anywhere in it.
```

- [ ] **Step 10: Run the whole suite and lint**

Run: `cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: everything passes, including the seven pre-existing `test_simulator.py` cases and `test_targeting.py`'s legacy-`plc` regression guard — that guard builds its own template list rather than reading `conf/settings.yaml`, so removing the shipped `plc:` block does not weaken it.

Then confirm the container still starts with no bind mount, which is the only thing Step 7 changes:

```bash
docker build -t uns/simulator:local --build-arg GIT_HASH=local -f 99_simulator/Dockerfile .
docker run --rm --name uns_sim_smoke uns/simulator:local
```

Expected: the startup log line `Loaded profile small: 11 devices, 76 signals across energy, production, water`. It will then fail to reach a broker, which is correct for a container with no network — the profile line is what this checks.

- [ ] **Step 11: Commit**

```bash
git add conf/settings.yaml 99_simulator/src/uns_simulator/profiles.py 99_simulator/src/uns_simulator/simulator.py \
        99_simulator/test/test_volume.py 99_simulator/test/test_targeting.py \
        99_simulator/Dockerfile 99_simulator/README.md \
        docs/adr/0006-simulator-plant-model-and-signal-generation.md
git commit -m "feat(simulator): ship the small profile by default, guard message volume, document the plant model"
```
