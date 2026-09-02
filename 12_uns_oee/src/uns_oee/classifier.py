"""From a machine state to a downtime reason code.

Two lookups and a floor. A rule declared for this unit wins; failing that the plant-wide
rule for the state; failing that `UNCLASSIFIED`. Never null - a downtime Pareto has to sum
to total downtime, and a null bucket holding a third of the lost time is how downtime
analysis loses its credibility.

The reason carries `is_planned`, which is why this runs before the calculator: a planned
reason moves its interval out of Loading Time entirely, while an unplanned one reduces Run
Time inside it. Same seconds, different factor.

Pure: no database. The resolver is handed the rows it needs, so every precedence case is one
dictionary literal in a test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from uns_model.oee_tables import UNCLASSIFIED_REASON_CODE

from uns_oee.states import Interval, StopInterval

AUTO = "auto"
MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ReasonSpec:
    """One `model.downtime_reason` row, as the calculator needs it."""

    code: str
    display_name: str
    category: str
    is_planned: bool = False


@dataclass(frozen=True, slots=True)
class ManualReason:
    """An operator's attribution, read back from an existing `oee.downtime_event` row."""

    reason_code: str
    note: str | None = None
    assigned_by: str | None = None


@dataclass(frozen=True, slots=True)
class ClassifiedStop:
    """A stop with its reason resolved, ready to be written and to be arithmetic."""

    interval: Interval
    state_value: str
    reason_code: str
    is_planned: bool
    source: str = AUTO
    note: str | None = None
    assigned_by: str | None = None


class ReasonResolver:
    """The precedence chain for one OEE unit.

    Constructed per unit and per run from `model.state_reason_map` and
    `model.downtime_reason`; holding no connection is what lets the pipeline classify a
    hundred backfilled shifts without re-querying.
    """

    def __init__(
        self,
        reasons: Mapping[str, ReasonSpec],
        unit_rules: Mapping[str, str],
        default_rules: Mapping[str, str],
    ) -> None:
        if UNCLASSIFIED_REASON_CODE not in reasons:
            raise ValueError(
                f"reason vocabulary is missing {UNCLASSIFIED_REASON_CODE!r}, which is the floor "
                f"every unmapped state falls back to. Migration 0003 seeds it."
            )
        self._reasons = dict(reasons)
        self._unit_rules = dict(unit_rules)
        self._default_rules = dict(default_rules)

    def resolve(self, state_value: str) -> ReasonSpec:
        """The reason for `state_value`: unit rule, then plant-wide rule, then unclassified."""
        code = self._unit_rules.get(state_value) or self._default_rules.get(state_value)
        if code is None:
            return self._reasons[UNCLASSIFIED_REASON_CODE]
        return self.spec(code)

    def spec(self, code: str) -> ReasonSpec:
        """The reason with this code.

        Raises rather than falling back, because a code with no row means the vocabulary was
        loaded incompletely. Labelling every stop on a line as unclassified would hide that.
        """
        try:
            return self._reasons[code]
        except KeyError as error:
            raise ValueError(f"reason code {code!r} is not in the loaded reason vocabulary") from error


def classify(
    stops: Sequence[StopInterval],
    resolver: ReasonResolver,
    manual: Mapping[object, ManualReason] | None = None,
) -> list[ClassifiedStop]:
    """Attach a reason to every stop, honouring Rule 3.

    `manual` is keyed by the stop's start instant, matching `oee.downtime_event`'s
    `(oee_unit_id, started_at)` key. A stop whose start is in that mapping keeps the
    operator's code permanently: auto-classification proposes, it never overrules.
    """
    assigned = manual or {}
    classified: list[ClassifiedStop] = []
    for stop in stops:
        override = assigned.get(stop.interval.start)
        spec = resolver.spec(override.reason_code) if override else resolver.resolve(stop.state)
        classified.append(
            ClassifiedStop(
                interval=stop.interval,
                state_value=stop.state,
                reason_code=spec.code,
                is_planned=spec.is_planned,
                source=MANUAL if override else AUTO,
                note=override.note if override else None,
                assigned_by=override.assigned_by if override else None,
            )
        )
    return classified


def planned_intervals(classified: Sequence[ClassifiedStop]) -> list[Interval]:
    """The intervals that leave Loading Time."""
    return [item.interval for item in classified if item.is_planned]


def unplanned_intervals(classified: Sequence[ClassifiedStop]) -> list[Interval]:
    """The intervals that reduce Run Time within Loading Time."""
    return [item.interval for item in classified if not item.is_planned]


__all__ = [
    "AUTO",
    "MANUAL",
    "ClassifiedStop",
    "ManualReason",
    "ReasonResolver",
    "ReasonSpec",
    "classify",
    "planned_intervals",
    "unplanned_intervals",
]
