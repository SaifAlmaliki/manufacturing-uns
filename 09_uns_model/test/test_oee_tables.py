"""Structural tests for the OEE tables.

These assert the contract other modules rely on - schema placement, the
nulls-not-distinct uniqueness that makes 'null means every Asset' work, and the
closed vocabularies - without needing a database.
"""

import pytest
from sqlalchemy import UniqueConstraint

from uns_model.model_config import MODEL_SCHEMA, OEE_SCHEMA
from uns_model.oee_tables import (
    DEFAULT_DOWNTIME_REASONS,
    DEFAULT_PRODUCING_STATES,
    OEE_STATUSES,
    REASON_SOURCES,
    SHIFT_EXCEPTION_KINDS,
    UNCLASSIFIED_REASON_CODE,
    DowntimeEvent,
    IdealCycleTime,
    OeeUnit,
    RecomputeRequest,
    ShiftResult,
    ShiftResultProduct,
    ShiftResultRevision,
    StateReasonMap,
)


def test_master_data_lives_in_model_and_results_live_in_oee():
    assert OeeUnit.__table__.schema == MODEL_SCHEMA
    assert IdealCycleTime.__table__.schema == MODEL_SCHEMA
    for table in (ShiftResult, ShiftResultProduct, ShiftResultRevision, DowntimeEvent, RecomputeRequest):
        assert table.__table__.schema == OEE_SCHEMA


@pytest.mark.parametrize(
    ("model", "columns"),
    [
        (IdealCycleTime, {"asset_id", "product_id"}),
        (StateReasonMap, {"oee_unit_id", "state_value"}),
    ],
)
def test_nullable_scope_keys_are_unique_with_nulls_not_distinct(model, columns):
    """A NULL scope key means 'every Asset', so two NULLs must collide."""
    constraints = [c for c in model.__table__.constraints if isinstance(c, UniqueConstraint)]
    matching = [c for c in constraints if {col.name for col in c.columns} == columns]
    assert matching, f"{model.__name__} has no unique constraint over {columns}"
    assert matching[0].dialect_kwargs["postgresql_nulls_not_distinct"] is True


def test_one_result_row_per_unit_and_shift_start():
    constraints = [c for c in ShiftResult.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert any({col.name for col in c.columns} == {"oee_unit_id", "shift_start"} for c in constraints)


def test_vocabularies_are_closed_and_include_the_documented_values():
    assert SHIFT_EXCEPTION_KINDS == ("PLANNED_DOWN", "NON_PRODUCING", "HOLIDAY")
    assert REASON_SOURCES == ("auto", "manual")
    assert OEE_STATUSES == (
        "OK",
        "NO_LOADING_TIME",
        "NO_PRODUCTION",
        "MISSING_IDEAL_CYCLE_TIME",
        "NO_INPUT_DATA",
    )
    assert DEFAULT_PRODUCING_STATES == ("EXECUTE",)


def test_unclassified_is_a_seeded_unplanned_reason():
    seeded = {code: is_planned for code, _name, _category, is_planned in DEFAULT_DOWNTIME_REASONS}
    assert UNCLASSIFIED_REASON_CODE == "UNCLASSIFIED"
    assert seeded[UNCLASSIFIED_REASON_CODE] is False
