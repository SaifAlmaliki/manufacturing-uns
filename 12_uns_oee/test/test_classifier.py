"""Tests for resolving a machine state into a downtime reason code.

Three behaviours matter here and each has a failure mode that is invisible in the numbers.
A unit-specific rule must beat the plant-wide one, or a line with its own vocabulary silently
reports someone else's reasons. An unmapped state must land in UNCLASSIFIED and never in
null, or the Pareto stops summing to total downtime. And a manual assignment must survive
recomputation - Rule 3 - or the operator who corrected a reason watches the engine undo it
the next time late data arrives.
"""

from datetime import datetime, timezone

import pytest

from uns_oee.classifier import (
    ManualReason,
    ReasonResolver,
    ReasonSpec,
    classify,
    planned_intervals,
    unplanned_intervals,
)
from uns_oee.states import Interval, StopInterval


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


REASONS = {
    "UNCLASSIFIED": ReasonSpec("UNCLASSIFIED", "Unclassified", "UNKNOWN", is_planned=False),
    "CHANGEOVER": ReasonSpec("CHANGEOVER", "Changeover", "PLANNED", is_planned=True),
    "PLANNED_BREAK": ReasonSpec("PLANNED_BREAK", "Planned break", "PLANNED", is_planned=True),
    "BREAKDOWN": ReasonSpec("BREAKDOWN", "Breakdown", "UNPLANNED", is_planned=False),
    "MINOR_STOP": ReasonSpec("MINOR_STOP", "Minor stop", "UNPLANNED", is_planned=False),
}


def resolver(unit_rules: dict[str, str] | None = None) -> ReasonResolver:
    return ReasonResolver(
        reasons=REASONS,
        unit_rules=unit_rules or {},
        default_rules={"HELD": "MINOR_STOP", "ABORTED": "BREAKDOWN", "SUSPENDED": "CHANGEOVER"},
    )


def stop(from_hour: int, to_hour: int, state: str) -> StopInterval:
    return StopInterval(state=state, interval=Interval(t(from_hour), t(to_hour)))


def test_a_plant_wide_rule_resolves_a_state():
    assert resolver().resolve("HELD").code == "MINOR_STOP"


def test_a_unit_rule_beats_the_plant_wide_rule():
    assert resolver({"HELD": "PLANNED_BREAK"}).resolve("HELD").code == "PLANNED_BREAK"


def test_an_unmapped_state_is_unclassified_and_never_null():
    resolved = resolver().resolve("STOPPING")
    assert resolved.code == "UNCLASSIFIED"
    assert resolved.is_planned is False


def test_a_rule_naming_a_reason_the_resolver_does_not_know_is_a_loud_error():
    # The FK makes this impossible from the database. It is reachable from a hand-edited
    # conf file, and mislabelling every stop on a line is worse than failing one shift.
    broken = ReasonResolver(reasons=REASONS, unit_rules={}, default_rules={"HELD": "NOPE"})
    with pytest.raises(ValueError, match="NOPE"):
        broken.resolve("HELD")


def test_a_resolver_without_the_unclassified_reason_is_rejected_on_construction():
    with pytest.raises(ValueError, match="UNCLASSIFIED"):
        ReasonResolver(reasons={"BREAKDOWN": REASONS["BREAKDOWN"]}, unit_rules={}, default_rules={})


def test_every_stop_is_classified_as_auto_by_default():
    classified = classify([stop(9, 10, "HELD"), stop(11, 12, "ABORTED")], resolver())
    assert [(item.reason_code, item.source) for item in classified] == [
        ("MINOR_STOP", "auto"),
        ("BREAKDOWN", "auto"),
    ]


def test_a_manual_reason_wins_and_is_marked_manual():
    manual = {t(9): ManualReason(reason_code="PLANNED_BREAK", note="canteen", assigned_by="operator1")}
    classified = classify([stop(9, 10, "HELD")], resolver(), manual)
    assert classified[0].reason_code == "PLANNED_BREAK"
    assert classified[0].source == "manual"
    assert classified[0].is_planned is True
    assert classified[0].note == "canteen"
    assert classified[0].assigned_by == "operator1"


def test_a_manual_reason_for_a_different_stop_does_not_leak():
    manual = {t(20): ManualReason(reason_code="PLANNED_BREAK")}
    classified = classify([stop(9, 10, "HELD")], resolver(), manual)
    assert classified[0].source == "auto"
    assert classified[0].reason_code == "MINOR_STOP"


def test_a_manual_reason_naming_an_unknown_code_is_a_loud_error():
    manual = {t(9): ManualReason(reason_code="GONE")}
    with pytest.raises(ValueError, match="GONE"):
        classify([stop(9, 10, "HELD")], resolver(), manual)


def test_planned_and_unplanned_intervals_partition_the_stops():
    classified = classify(
        [stop(9, 10, "HELD"), stop(11, 12, "SUSPENDED"), stop(13, 14, "ABORTED")], resolver()
    )
    assert planned_intervals(classified) == [Interval(t(11), t(12))]
    assert unplanned_intervals(classified) == [Interval(t(9), t(10)), Interval(t(13), t(14))]


def test_no_stops_classifies_to_nothing():
    assert classify([], resolver()) == []
    assert planned_intervals([]) == []
