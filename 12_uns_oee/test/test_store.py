"""Tests for uns_oee.store - the column mappings and the conflict clause.

Compiled against the PostgreSQL dialect rather than executed, because what can be wrong
here is which columns a recomputation touches, and that is visible in the statement. The
round trip - two saves of the same shift leaving one row, a manual reason surviving the
second - is Task 17's integration test, which needs a real database to be worth anything.
"""

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from uns_model.oee_tables import ShiftResult
from uns_oee.classifier import AUTO, MANUAL, ClassifiedStop
from uns_oee.oee_calc import ProductMetrics, ShiftMetrics
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import Fingerprint
from uns_oee.states import Interval
from uns_oee.store import (
    GEOMETRY_COLUMNS,
    REASON_COLUMNS,
    downtime_auto_delete,
    downtime_upsert,
    event_values,
    product_values,
    result_values,
    revision_values,
)

UNIT = 7
FINGERPRINT = Fingerprint(row_count=2880, max_time=datetime(2026, 9, 7, 12, tzinfo=timezone.utc))
COMPUTED_AT = datetime(2026, 9, 7, 12, 5, tzinfo=timezone.utc)


def t(hour: int) -> datetime:
    return datetime(2026, 9, 7, hour, tzinfo=timezone.utc)


WINDOW = ShiftWindow(start=t(4), end=t(12), label="A")


def metrics() -> ShiftMetrics:
    return ShiftMetrics(
        loading_time_s=27000.0,
        run_time_s=24300.0,
        planned_down_s=1800.0,
        unplanned_down_s=2700.0,
        good_count=11760.0,
        reject_count=240.0,
        total_count=12000.0,
        availability=0.9,
        performance=0.95,
        performance_raw=0.95,
        quality=0.98,
        oee=0.8379,
        status="OK",
        products=(
            ProductMetrics(
                product_code="R-100-STD",
                run_time_s=24300.0,
                good_count=11760.0,
                reject_count=240.0,
                total_count=12000.0,
                ideal_cycle_time_s=2.0,
            ),
        ),
    )


def stop(
    from_hour: int,
    to_hour: int,
    *,
    reason: str = "MECH_FAILURE",
    source: str = AUTO,
    note: str = "",
    assigned_by: str | None = None,
) -> ClassifiedStop:
    return ClassifiedStop(
        interval=Interval(t(from_hour), t(to_hour)),
        state_value="ABORTED",
        reason_code=reason,
        is_planned=False,
        source=source,
        note=note,
        assigned_by=assigned_by,
    )


def compile_pg(statement) -> tuple[str, dict[str, object]]:
    """The statement as lower-cased SQL plus its bind parameters.

    Without `literal_binds`, so nothing depends on how a given SQLAlchemy version renders a
    timezone-aware datetime as a literal. Values are asserted through `params`.
    """
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled).lower(), dict(compiled.params)


def test_result_values_carry_the_window_and_its_label():
    values = result_values(UNIT, WINDOW, metrics(), FINGERPRINT, COMPUTED_AT)
    assert values["oee_unit_id"] == UNIT
    assert values["shift_start"] == t(4)
    assert values["shift_end"] == t(12)
    assert values["shift_label"] == "A"


def test_result_values_carry_every_factor_and_its_fingerprint():
    values = result_values(UNIT, WINDOW, metrics(), FINGERPRINT, COMPUTED_AT)
    assert values["availability"] == 0.9
    assert values["performance"] == 0.95
    assert values["performance_raw"] == 0.95
    assert values["quality"] == 0.98
    assert values["oee"] == 0.8379
    assert values["status"] == "OK"
    assert values["input_fingerprint"] == FINGERPRINT.as_text()
    assert values["computed_at"] == COMPUTED_AT


def test_an_undefined_factor_is_stored_as_null_not_zero():
    blank = replace(metrics(), availability=None, performance=None, quality=None, oee=None)
    values = result_values(UNIT, WINDOW, blank, FINGERPRINT, COMPUTED_AT)
    assert values["availability"] is None
    assert values["oee"] is None


def test_a_saved_result_is_always_unpublished():
    assert result_values(UNIT, WINDOW, metrics(), FINGERPRINT, COMPUTED_AT)["published_at"] is None


def test_revision_values_copy_the_stored_row_verbatim():
    stored = ShiftResult(
        id=99,
        oee_unit_id=UNIT,
        shift_start=t(4),
        revision=2,
        loading_time_s=27000.0,
        run_time_s=24300.0,
        good_count=11760.0,
        reject_count=240.0,
        total_count=12000.0,
        availability=0.9,
        performance=0.95,
        quality=0.98,
        oee=0.8379,
        status="OK",
        input_fingerprint="2880:2026-09-07T12:00:00+00:00",
        computed_at=COMPUTED_AT,
    )
    values = revision_values(stored)
    assert values["revision"] == 2
    assert values["oee"] == 0.8379
    assert values["input_fingerprint"] == "2880:2026-09-07T12:00:00+00:00"
    assert values["computed_at"] == COMPUTED_AT
    assert "superseded_at" not in values


def test_one_product_row_per_segment():
    rows = product_values(99, metrics())
    assert len(rows) == 1
    assert rows[0] == {
        "shift_result_id": 99,
        "product_code": "R-100-STD",
        "good_count": 11760.0,
        "reject_count": 240.0,
        "total_count": 12000.0,
        "ideal_cycle_time_s": 2.0,
    }


def test_a_segment_with_no_product_code_stores_the_empty_string():
    unbound = replace(metrics().products[0], product_code=None)
    rows = product_values(99, replace(metrics(), products=(unbound,)))
    assert rows[0]["product_code"] == ""


def test_a_segment_with_no_ideal_cycle_time_stores_null():
    gap = replace(metrics().products[0], ideal_cycle_time_s=None)
    rows = product_values(99, replace(metrics(), products=(gap,)))
    assert rows[0]["ideal_cycle_time_s"] is None


def test_no_segments_is_no_product_rows():
    assert product_values(99, replace(metrics(), products=())) == []


def test_one_event_row_per_stop_with_its_duration():
    rows = event_values(UNIT, t(4), (stop(6, 7), stop(9, 10)))
    assert [row["started_at"] for row in rows] == [t(6), t(9)]
    assert [row["duration_s"] for row in rows] == [3600.0, 3600.0]
    assert {row["shift_start"] for row in rows} == {t(4)}


def test_an_event_carries_the_classification():
    row = event_values(UNIT, t(4), (stop(6, 7),))[0]
    assert row["oee_unit_id"] == UNIT
    assert row["state_value"] == "ABORTED"
    assert row["reason_code"] == "MECH_FAILURE"
    assert row["reason_source"] == AUTO
    assert row["assigned_by"] is None
    assert row["assigned_at"] is None
    assert row["note"] == ""


def test_an_auto_classified_stop_with_no_note_persists_empty_string():
    auto = replace(stop(6, 7), note=None)
    row = event_values(UNIT, t(4), (auto,))[0]
    assert row["note"] == ""
    assert row["note"] is not None


def test_a_manual_classification_carries_its_assigner_and_note():
    manual = stop(6, 7, reason="TOOL_CHANGE", source=MANUAL, note="die swap", assigned_by="operator1")
    row = event_values(UNIT, t(4), (manual,))[0]
    assert row["reason_code"] == "TOOL_CHANGE"
    assert row["reason_source"] == MANUAL
    assert row["assigned_by"] == "operator1"
    assert row["note"] == "die swap"


def test_no_stops_is_no_event_rows():
    assert event_values(UNIT, t(4), ()) == []


def test_the_upsert_conflicts_on_unit_and_started_at():
    sql, _ = compile_pg(downtime_upsert(event_values(UNIT, t(4), (stop(6, 7),))))
    assert "on conflict (oee_unit_id, started_at) do update" in sql


def test_the_upsert_always_refreshes_the_stops_geometry():
    sql, _ = compile_pg(downtime_upsert(event_values(UNIT, t(4), (stop(6, 7),))))
    for column in GEOMETRY_COLUMNS:
        assert f"excluded.{column}" in sql
        assert f"downtime_event.{column}" not in sql


def test_the_upsert_never_overwrites_a_manual_reason():
    sql, params = compile_pg(downtime_upsert(event_values(UNIT, t(4), (stop(6, 7),))))
    assert "case when" in sql
    for column in REASON_COLUMNS:
        assert f"downtime_event.{column}" in sql
        assert f"excluded.{column}" in sql
    assert MANUAL in params.values()


def test_stale_auto_stops_are_deleted_for_the_unit_and_shift():
    sql, params = compile_pg(downtime_auto_delete(UNIT, t(4), keep_started_at=(t(6),)))
    assert "delete from" in sql
    assert "downtime_event" in sql
    assert "reason_source" in sql
    assert AUTO in params.values()
    assert UNIT in params.values()
    assert t(4) in params.values()


def test_stale_auto_stops_keep_the_recomputed_started_at_set():
    sql, params = compile_pg(downtime_auto_delete(UNIT, t(4), keep_started_at=(t(6), t(9))))
    bound = [item for value in params.values() for item in (value if isinstance(value, list) else [value])]
    assert "started_at" in sql
    assert "not in" in sql
    assert t(6) in bound
    assert t(9) in bound


def test_an_empty_stop_list_deletes_every_auto_row_for_the_shift():
    sql, _params = compile_pg(downtime_auto_delete(UNIT, t(4), keep_started_at=()))
    assert "delete from" in sql
    assert "downtime_event" in sql
    assert "not in" not in sql


def test_stale_auto_stops_never_target_a_manual_reason():
    sql, params = compile_pg(downtime_auto_delete(UNIT, t(4), keep_started_at=()))
    assert MANUAL not in params.values()
    assert AUTO in params.values()
