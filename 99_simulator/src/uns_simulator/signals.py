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
import math
import random
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from uns_simulator.expressions import ATTRIBUTE_ROOT, ExpressionError, compile_expression

WARNING_SIGMA = 2.0
ALARM_SIGMA = 3.0

SIGNAL_SHAPES: dict[str, type[Signal]] = {}

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
RESERVED_NAMESPACE_NAMES = frozenset({ATTRIBUTE_ROOT, "dt"})
_AGGREGATES: Final = {
    "min": min,
    "max": max,
    "mean": lambda values: sum(values) / len(values),
}


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


def signal_namespace(spec: SignalSpec, dt: float, view: Any, siblings: Mapping[str, Any]) -> dict[str, Any]:
    """The one namespace every expression in this module is evaluated against.

    Siblings win over params on a name clash, so a param acts as a default. `derived` and
    `counter.rate` share this function rather than each building their own dict, because two
    namespaces that agree today would not stay agreeing.
    """
    return {**spec.params, **siblings, ATTRIBUTE_ROOT: view, "dt": dt}


class Signal:
    """Base class: owns the RNG, the current value, clamping and the status heuristic."""

    shape_name: ClassVar[str] = ""

    def __init__(self, spec: SignalSpec, topic: str, global_seed: int) -> None:
        self.spec = spec
        self.topic = topic
        self.rng = random.Random(signal_seed(global_seed, topic))  # ruff: ignore[suspicious-non-cryptographic-random-usage]
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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # ruff: ignore[unused-method-argument]
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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # ruff: ignore[unused-method-argument]
        self.value = self._clamp(self._fixed)
        return self.value


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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # ruff: ignore[unused-method-argument]
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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # ruff: ignore[unused-method-argument]
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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float:  # ruff: ignore[unused-method-argument]
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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> float | None:  # ruff: ignore[unused-method-argument]
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

    `source` is how WTP mode, duty pump and filter flags reach a topic — the signal
    reports the plant's state rather than inventing one, which is the whole point of
    having a PlantContext. `choices` covers the genuinely arbitrary discretes (tap
    position, downtime reason, batch id), changing only every `dwell_s` seconds so a
    consumer sees a state that holds rather than per-sample flicker.

    `map` translates whichever of the two produced the value, which is how a numeric
    mode code is the same signal as the string mode with a lookup table attached.
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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> Any:  # ruff: ignore[unused-method-argument]
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

    def next(self, dt: float, view: Any, siblings: Mapping[str, Any]) -> Any:  # ruff: ignore[unused-method-argument]
        self.value = self.rng.choice(self._choices) if self.rng.random() < self._p else None
        return self.value

    def status(self) -> str:
        return "Normal" if self.value is None else "Alarm"


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
