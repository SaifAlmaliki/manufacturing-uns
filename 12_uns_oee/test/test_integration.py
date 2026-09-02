"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Integration tests for the OEE engine against a real Postgres/TimescaleDB.

The unit tests cover the decisions; these cover the SQL, which is where the interesting
mistakes are: the master-data joins, the sample window with its prior sample, the
fingerprint, the idempotent upsert, the revision hand-off, and the queue claim. They need a
migrated database reachable with the `historian.*` settings - `uv run uns_model_setup`, or
the compose stack.

Everything is written under TEST_ROOT and removed again, so the tests are safe to run
against a database that already holds a seeded Asset Model and real OEE master data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from uns_model.engine import Database
from uns_model.model_config import ModelConfig
from uns_model.oee_master_data import (
    DowntimeReasonSpec,
    IdealCycleTimeSpec,
    OeeMasterDataRepository,
    OeeUnitSpec,
    ProductSpec,
    ShiftPatternSpec,
    ShiftSlotSpec,
    StateReasonRuleSpec,
)
from uns_model.oee_results import OeeResultRepository
from uns_model.repositories import AssetModelRepository, AssetSpec

from uns_oee.master_data import MasterDataLoader
from uns_oee.oee_config import OeeConfig
from uns_oee.pipeline import ACTION_COMPUTED, ACTION_REVISED, ACTION_UNCHANGED, ShiftPipeline
from uns_oee.scheduler import claim_requests, complete_requests, retention_days
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import MetricSource, split_metric_key
from uns_oee.store import ResultStore

pytestmark = [
    pytest.mark.integrationtest,
    pytest.mark.asyncio(loop_scope="session"),
    # Serialised: every test in the file writes the same test Asset branch.
    pytest.mark.xdist_group(name="oee_database"),
]

# Nothing outside this Enterprise is touched, which is what makes these tests runnable
# against a database that already holds the real plant hierarchy.
TEST_ROOT = "PyTestOEE"
LINE_PATH = f"{TEST_ROOT}/Plant1/Area1/Line1"
PATTERN_NAME = "PyTest OEE 1-shift"
PRODUCT_CODE = "PYTEST-P1"
UNPLANNED_REASON = "PYTEST_MECH_FAULT"
PLANNED_REASON = "PYTEST_CHANGEOVER"
REASON_CODES = (UNPLANNED_REASON, PLANNED_REASON)

STATE_KEY = "Cell1/MES-01/Status/PackMlState"
GOOD_KEY = "Cell1/MES-01/Production/GoodCount"
REJECT_KEY = "Cell1/MES-01/Production/RejectCount"

SHIFT_START = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
WINDOW = ShiftWindow(start=SHIFT_START, end=SHIFT_END, label="A")
COMPUTED_AT = SHIFT_END + timedelta(minutes=20)

STOP_START = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
STOP_END = datetime(2026, 8, 31, 10, 30, tzinfo=UTC)

# See the task's table: every one of these is exact, not approximate.
EXPECTED_AVAILABILITY = 27000 / 28800
EXPECTED_PERFORMANCE = 25000 / 27000
EXPECTED_QUALITY = 4800 / 5000
EXPECTED_OEE = 5 / 6

BRANCH = [
    AssetSpec(segment=TEST_ROOT, level="ENTERPRISE"),
    AssetSpec(segment="Plant1", level="SITE"),
    AssetSpec(segment="Area1", level="AREA"),
    AssetSpec(segment="Line1", level="LINE"),
]


class _RecordingPublisher:
    """Stands in for `ResultPublisher`. Real MQTT is Task 23's business."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ShiftWindow, object, int]] = []
        self.published = 0
        self.failed = 0
        self.connected = True

    async def publish(self, asset_path, window, metrics, revision) -> bool:
        self.calls.append((asset_path, window, metrics, revision))
        self.published += 1
        return True

    async def aclose(self) -> None:
        return None


# ---- fixtures


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def database():
    """One engine for the whole session: asyncpg connections belong to a loop."""
    config = ModelConfig.from_settings()
    assert config.is_valid(), "historian.* settings are needed for the OEE integration tests"
    database = Database.from_config(config)
    yield database
    await database.dispose()


async def _clean(database: Database) -> None:
    """Remove everything these tests could have written, in FK-safe order."""
    async with database.begin() as connection:
        unit_ids = "SELECT u.id FROM model.oee_unit u JOIN model.asset a ON a.id = u.asset_id WHERE starts_with(a.path, :root)"
        await connection.execute(text(f"DELETE FROM oee.recompute_request WHERE oee_unit_id IN ({unit_ids})"), {"root": TEST_ROOT})
        await connection.execute(text(f"DELETE FROM oee.downtime_event WHERE oee_unit_id IN ({unit_ids})"), {"root": TEST_ROOT})
        # shift_result_product and shift_result_revision cascade from shift_result.
        await connection.execute(text(f"DELETE FROM oee.shift_result WHERE oee_unit_id IN ({unit_ids})"), {"root": TEST_ROOT})
        await connection.execute(text("DELETE FROM uns_metrics WHERE starts_with(topic, :root)"), {"root": TEST_ROOT})
        await connection.execute(text("DELETE FROM model.shift_exception WHERE asset_id IN (SELECT id FROM model.asset WHERE starts_with(path, :root))"), {"root": TEST_ROOT})
        # Cascades to model.oee_unit and model.ideal_cycle_time.
        await connection.execute(text("DELETE FROM model.asset WHERE path = :root"), {"root": TEST_ROOT})
        await connection.execute(text("DELETE FROM model.shift_pattern WHERE name = :name"), {"name": PATTERN_NAME})
        await connection.execute(
            text("DELETE FROM model.state_reason_map WHERE reason_code = ANY(:codes)"), {"codes": list(REASON_CODES)}
        )
        await connection.execute(text("DELETE FROM model.downtime_reason WHERE code = ANY(:codes)"), {"codes": list(REASON_CODES)})
        await connection.execute(text("DELETE FROM model.product WHERE code = :code"), {"code": PRODUCT_CODE})


async def _seed_master_data(database: Database) -> None:
    """The authored side, written through the real repository so its SQL is exercised too."""
    await AssetModelRepository(database).ensure_branch(BRANCH)
    repository = OeeMasterDataRepository(database)
    await repository.save_product(ProductSpec(code=PRODUCT_CODE, name="PyTest product"))
    await repository.save_shift_pattern(
        ShiftPatternSpec(
            name=PATTERN_NAME,
            # UTC on purpose: DST is Task 4's exhaustive unit tests, and a UTC pattern
            # keeps every expected number in this file readable.
            timezone="UTC",
            asset_path=LINE_PATH,
            # All seven days, so the test does not depend on what weekday 2026-08-31 is.
            slots=tuple(
                ShiftSlotSpec(day_of_week=day, start_time=time(6, 0), duration_minutes=480, label="A")
                for day in range(7)
            ),
        )
    )
    await repository.save_downtime_reason(
        DowntimeReasonSpec(code=UNPLANNED_REASON, display_name="PyTest mechanical fault", category="FAILURE", is_planned=False)
    )
    await repository.save_downtime_reason(
        DowntimeReasonSpec(code=PLANNED_REASON, display_name="PyTest changeover", category="PLANNED", is_planned=True)
    )
    await repository.save_oee_unit(
        OeeUnitSpec(
            asset_path=LINE_PATH,
            shift_pattern_name=PATTERN_NAME,
            state_metric_key=STATE_KEY,
            good_count_metric_key=GOOD_KEY,
            reject_count_metric_key=REJECT_KEY,
            producing_states=("EXECUTE",),
        )
    )
    await repository.save_state_reason_rule(
        StateReasonRuleSpec(state_value="ABORTED", reason_code=UNPLANNED_REASON, asset_path=LINE_PATH)
    )
    await repository.save_ideal_cycle_time(IdealCycleTimeSpec(asset_path=LINE_PATH, seconds_per_unit=5.0))


async def _insert_samples(database: Database, rows: list[tuple[datetime, str, str, float | None, str | None]]) -> None:
    async with database.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO uns_metrics (time, topic, metric_name, value_double, value_text) "
                "VALUES (:time, :topic, :metric_name, :value_double, :value_text)"
            ),
            [
                {"time": at, "topic": topic, "metric_name": name, "value_double": number, "value_text": word}
                for at, topic, name, number, word in rows
            ],
        )


def _state(at: datetime, value: str):
    ref = split_metric_key(LINE_PATH, STATE_KEY)
    return (at, ref.topic, ref.metric_name, None, value)


def _counter(at: datetime, key: str, value: float):
    ref = split_metric_key(LINE_PATH, key)
    return (at, ref.topic, ref.metric_name, value, None)


async def _seed_shift_samples(database: Database) -> None:
    """One producing shift with a single 30-minute ABORTED stop in the middle."""
    await _insert_samples(
        database,
        [
            _state(SHIFT_START, "EXECUTE"),
            _state(STOP_START, "ABORTED"),
            _state(STOP_END, "EXECUTE"),
            # Counters are read as deltas, so the first sample is the baseline.
            _counter(SHIFT_START, GOOD_KEY, 1000.0),
            _counter(SHIFT_END - timedelta(minutes=1), GOOD_KEY, 5800.0),
            _counter(SHIFT_START, REJECT_KEY, 0.0),
            _counter(SHIFT_END - timedelta(minutes=1), REJECT_KEY, 200.0),
        ],
    )


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(database: Database):
    """Master data and one shift's samples, with nothing left behind either side."""
    async with database.begin() as connection:
        present = (await connection.execute(text("SELECT to_regclass('public.uns_metrics')"))).scalar()
    if present is None:
        pytest.skip("uns_metrics is missing: apply 04_uns_historian/sql_scripts first")
    await _clean(database)
    await _seed_master_data(database)
    await _seed_shift_samples(database)
    yield database
    await _clean(database)


@pytest_asyncio.fixture(loop_scope="session")
async def unit(seeded: Database):
    """The one `UnitMasterData` these tests compute, loaded through the real joins."""
    units = [item for item in await MasterDataLoader(seeded).active_units() if item.asset_path == LINE_PATH]
    assert len(units) == 1, "the test unit was not loaded; is the 0003 migration applied?"
    return units[0]


@pytest_asyncio.fixture(loop_scope="session")
async def pipeline(seeded: Database):
    """A pipeline whose only stub is the broker."""
    publisher = _RecordingPublisher()
    config = OeeConfig(mqtt_host="localhost")
    yield ShiftPipeline(
        MetricSource(seeded, metrics_table=config.metrics_table),
        MasterDataLoader(seeded),
        ResultStore(seeded),
        publisher,
    ), publisher


async def _stored(database: Database, unit_id: int) -> dict:
    async with database.begin() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT revision, status, loading_time_s, run_time_s, planned_down_s, unplanned_down_s, "
                    "good_count, reject_count, total_count, availability, performance, quality, oee, published_at "
                    "FROM oee.shift_result WHERE oee_unit_id = :unit AND shift_start = :start"
                ),
                {"unit": unit_id, "start": SHIFT_START},
            )
        ).mappings().one()
    return dict(row)


# ---- the authored side and the reads


async def test_master_data_loader_resolves_every_binding(unit):
    """
    The joins in `master_data.py`, which no unit test can validate: four tables, two of
    them optional, plus an array column and a mapping keyed by a nullable product code.
    """
    assert unit.asset_path == LINE_PATH
    assert unit.schedule.timezone == "UTC"
    assert len(unit.schedule.slots) == 7
    assert unit.producing_states == ("EXECUTE",)
    assert unit.state_ref == split_metric_key(LINE_PATH, STATE_KEY)
    assert unit.good_ref == split_metric_key(LINE_PATH, GOOD_KEY)
    assert unit.reject_ref == split_metric_key(LINE_PATH, REJECT_KEY)
    assert unit.product_ref is None
    # The Asset-wide row: keyed by None, which is what makes a single-product line work.
    assert unit.ideal_cycle_time_for(None) == pytest.approx(5.0)
    assert unit.resolver.resolve("ABORTED").code == UNPLANNED_REASON


async def test_metric_source_reads_the_window_and_its_prior_sample(seeded: Database, unit):
    """
    `include_prior` is the difference between a shift that starts mid-stop being counted
    as running and being counted as stopped. It needs a real query to prove.
    """
    source = MetricSource(seeded)

    states = await source.text_samples(unit.state_ref, SHIFT_START, SHIFT_END)
    assert [sample.state for sample in states] == ["EXECUTE", "ABORTED", "EXECUTE"]

    # A window starting inside the stop must still learn the machine was ABORTED.
    later = await source.text_samples(unit.state_ref, STOP_START + timedelta(minutes=5), SHIFT_END)
    assert later[0].state == "ABORTED"
    assert later[0].at <= STOP_START

    counts = await source.numeric_samples(unit.good_ref, SHIFT_START, SHIFT_END)
    assert [sample.value for sample in counts] == [1000.0, 5800.0]


async def test_the_fingerprint_and_the_earliest_sample_come_from_sql(seeded: Database, unit):
    source = MetricSource(seeded)

    fingerprint = await source.fingerprint(unit.refs, SHIFT_START, SHIFT_END)

    assert fingerprint.row_count == 7
    assert fingerprint.max_time == SHIFT_END - timedelta(minutes=1)
    assert not fingerprint.is_empty
    # What bounds backfill: shifts ending before this are skipped, not written as zero.
    assert await source.earliest_sample_at(unit.refs) == SHIFT_START


# ---- computing, storing, and not storing


async def test_one_shift_stores_the_result_its_products_and_its_stop(seeded: Database, unit, pipeline):
    engine, publisher = pipeline

    outcome = await engine.run_shift(unit, WINDOW, COMPUTED_AT)

    assert outcome.action == ACTION_COMPUTED
    assert outcome.revision == 1
    assert outcome.published is True
    assert publisher.published == 1

    stored = await _stored(seeded, unit.unit_id)
    assert stored["status"] == "OK"
    assert stored["loading_time_s"] == pytest.approx(28800.0)
    assert stored["run_time_s"] == pytest.approx(27000.0)
    assert stored["planned_down_s"] == pytest.approx(0.0)
    assert stored["unplanned_down_s"] == pytest.approx(1800.0)
    assert stored["good_count"] == pytest.approx(4800.0)
    assert stored["reject_count"] == pytest.approx(200.0)
    assert stored["total_count"] == pytest.approx(5000.0)
    assert stored["availability"] == pytest.approx(EXPECTED_AVAILABILITY)
    assert stored["performance"] == pytest.approx(EXPECTED_PERFORMANCE)
    assert stored["quality"] == pytest.approx(EXPECTED_QUALITY)
    assert stored["oee"] == pytest.approx(EXPECTED_OEE)
    # Set by `mark_published`, which is a second statement: an unset value here means the
    # engine would republish the same revision on the next pass.
    assert stored["published_at"] is not None

    async with seeded.begin() as connection:
        stop = (
            await connection.execute(
                text(
                    "SELECT started_at, ended_at, duration_s, state_value, reason_code, reason_source "
                    "FROM oee.downtime_event WHERE oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).mappings().one()
    assert stop["started_at"] == STOP_START
    assert stop["ended_at"] == STOP_END
    assert stop["duration_s"] == pytest.approx(1800.0)
    assert stop["state_value"] == "ABORTED"
    assert stop["reason_code"] == UNPLANNED_REASON
    assert stop["reason_source"] == "auto"


async def test_an_unchanged_fingerprint_writes_nothing(seeded: Database, unit, pipeline):
    """
    The whole recomputation design rests on this: the CLI, the queue and the scheduler can
    all ask for the same range and only the first one writes.
    """
    engine, publisher = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    first = await _stored(seeded, unit.unit_id)

    again = await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(minutes=10))

    assert again.action == ACTION_UNCHANGED
    assert again.revision == 1
    assert publisher.published == 1, "an unchanged shift must not be republished"
    assert await _stored(seeded, unit.unit_id) == first
    async with seeded.begin() as connection:
        revisions = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM oee.shift_result_revision v "
                    "JOIN oee.shift_result r ON r.oee_unit_id = v.oee_unit_id AND r.shift_start = v.shift_start "
                    "WHERE r.oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).scalar()
    assert revisions == 0


async def test_late_data_bumps_the_revision_and_preserves_the_previous(seeded: Database, unit, pipeline):
    engine, publisher = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)

    # An edge connector reconnecting and flushing a buffered sample inside the window.
    await _insert_samples(seeded, [_counter(SHIFT_END - timedelta(seconds=30), GOOD_KEY, 5900.0)])
    revised = await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(hours=1))

    assert revised.action == ACTION_REVISED
    assert revised.revision == 2
    assert publisher.published == 2, "a restated shift is published again"

    stored = await _stored(seeded, unit.unit_id)
    assert stored["revision"] == 2
    assert stored["good_count"] == pytest.approx(4900.0)

    async with seeded.begin() as connection:
        previous = (
            await connection.execute(
                text(
                    "SELECT v.revision, v.good_count, v.oee FROM oee.shift_result_revision v "
                    "JOIN oee.shift_result r ON r.oee_unit_id = v.oee_unit_id AND r.shift_start = v.shift_start "
                    "WHERE r.oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).mappings().all()
    # The superseded number is kept, which is what makes a restatement explainable.
    assert [row["revision"] for row in previous] == [1]
    assert previous[0]["good_count"] == pytest.approx(4800.0)
    assert previous[0]["oee"] == pytest.approx(EXPECTED_OEE)


async def test_two_pipelines_computing_the_same_shift_produce_one_row(seeded: Database, unit):
    """
    Two engines, or an engine and the CLI. `ResultStore.save` upserts on
    (oee_unit_id, shift_start); without that this is two rows and the dashboard shows the
    shift twice.
    """
    stores = [
        ShiftPipeline(MetricSource(seeded), MasterDataLoader(seeded), ResultStore(seeded), _RecordingPublisher())
        for _ in range(2)
    ]

    outcomes = await asyncio.gather(*(engine.run_shift(unit, WINDOW, COMPUTED_AT) for engine in stores))

    async with seeded.begin() as connection:
        rows = (
            await connection.execute(
                text("SELECT count(*) FROM oee.shift_result WHERE oee_unit_id = :unit"), {"unit": unit.unit_id}
            )
        ).scalar()
    assert rows == 1
    assert {outcome.revision for outcome in outcomes} <= {1, 2}


# ---- corrections


async def _assign_planned_reason(database: Database, unit) -> int:
    """Reassign the shift's one stop to a planned reason, as the mutation would."""
    repository = OeeResultRepository(database)
    events = await repository.downtime_events(LINE_PATH, SHIFT_START, SHIFT_END)
    assert len(events) == 1
    assigned = await repository.assign_reason(
        int(events[0].event.id), PLANNED_REASON, note="pytest", assigned_by="pytest"
    )
    assert assigned is not None
    return int(events[0].event.id)


async def test_a_manual_reason_survives_a_recompute(seeded: Database, unit, pipeline):
    """
    Rule 3. Without it, the next pass would silently overwrite the correction with the
    state-code default and the number would flip back an hour after somebody fixed it.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    event_id = await _assign_planned_reason(seeded, unit)

    await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(hours=1))

    async with seeded.begin() as connection:
        stop = (
            await connection.execute(
                text("SELECT reason_code, reason_source, assigned_by, note FROM oee.downtime_event WHERE id = :id"),
                {"id": event_id},
            )
        ).mappings().one()
    assert stop["reason_code"] == PLANNED_REASON
    assert stop["reason_source"] == "manual"
    assert stop["assigned_by"] == "pytest"
    assert stop["note"] == "pytest"


async def test_reassigning_to_a_planned_reason_raises_availability(seeded: Database, unit, pipeline):
    """
    The reason this is a recomputation and not a relabelling: `is_planned` moves the 1800
    seconds out of Loading Time, so Availability goes from 15/16 to 1.0 and OEE to 8/9.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    await _assign_planned_reason(seeded, unit)

    revised = await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(hours=1))

    assert revised.action == ACTION_REVISED
    stored = await _stored(seeded, unit.unit_id)
    assert stored["loading_time_s"] == pytest.approx(27000.0)
    assert stored["planned_down_s"] == pytest.approx(1800.0)
    assert stored["unplanned_down_s"] == pytest.approx(0.0)
    assert stored["availability"] == pytest.approx(1.0)
    assert stored["oee"] == pytest.approx(8 / 9)


async def test_assigning_a_reason_queues_exactly_that_shift(seeded: Database, unit, pipeline):
    """
    `SINGLE_SHIFT_MARGIN` is one second, and `shift_windows` selects by start. The queued
    range must therefore name this shift and not the one that begins when it ends.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    await _assign_planned_reason(seeded, unit)

    async with seeded.begin() as connection:
        queued = (
            await connection.execute(
                text(
                    "SELECT range_start, range_end, requested_by, completed_at FROM oee.recompute_request "
                    "WHERE oee_unit_id = :unit"
                ),
                {"unit": unit.unit_id},
            )
        ).mappings().all()
    assert len(queued) == 1
    assert queued[0]["range_start"] == SHIFT_START
    assert queued[0]["range_end"] == SHIFT_START + timedelta(seconds=1)
    assert queued[0]["requested_by"] == "pytest"
    assert queued[0]["completed_at"] is None


# ---- what the console reads back


async def test_the_result_repository_reads_what_the_engine_wrote(seeded: Database, unit, pipeline):
    """
    The four selects in `oee_results.py`, whose unit tests only pin statement order. The
    Pareto's shares must sum to 1 and its seconds to the stored downtime, or the events
    table and the Pareto chart on one dashboard disagree.
    """
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    repository = OeeResultRepository(seeded)

    results = await repository.shift_results(LINE_PATH, SHIFT_START, SHIFT_END + timedelta(days=1))
    assert len(results) == 1
    assert results[0].asset_path == LINE_PATH
    assert results[0].result.oee == pytest.approx(EXPECTED_OEE)
    # One product segment, from the Asset-wide ideal cycle time.
    assert [product.ideal_cycle_time_s for product in results[0].products] == [pytest.approx(5.0)]

    events = await repository.downtime_events(LINE_PATH, SHIFT_START, SHIFT_END)
    assert [event.event.reason_code for event in events] == [UNPLANNED_REASON]
    assert events[0].display_name == "PyTest mechanical fault"
    assert events[0].is_planned is False

    pareto = await repository.downtime_pareto(LINE_PATH, SHIFT_START, SHIFT_END)
    assert [bucket.reason_code for bucket in pareto] == [UNPLANNED_REASON]
    assert pareto[0].event_count == 1
    assert pareto[0].total_seconds == pytest.approx(1800.0)
    assert pareto[0].share == pytest.approx(1.0)


async def test_an_asset_with_no_results_reads_back_empty(seeded: Database):
    """One round trip and an empty list, not an error: a line whose first shift is open."""
    repository = OeeResultRepository(seeded)

    assert await repository.shift_results("No/Such/Asset", SHIFT_START, SHIFT_END) == []
    assert await repository.downtime_events("No/Such/Asset", SHIFT_START, SHIFT_END) == []
    assert await repository.downtime_pareto("No/Such/Asset", SHIFT_START, SHIFT_END) == []


async def test_assigning_an_unauthored_reason_is_refused_before_the_foreign_key(seeded: Database, unit, pipeline):
    engine, _ = pipeline
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    repository = OeeResultRepository(seeded)
    events = await repository.downtime_events(LINE_PATH, SHIFT_START, SHIFT_END)

    with pytest.raises(ValueError, match="not an authored downtime reason code"):
        await repository.assign_reason(int(events[0].event.id), "PYTEST_NOT_A_REASON")


# ---- the scheduler's three pieces of SQL


async def test_claim_requests_hands_each_row_to_one_claimer(seeded: Database, unit):
    """
    `FOR UPDATE SKIP LOCKED` in a `RETURNING` update. Two claimers must partition the
    queue, not both take it: a doubly-claimed range is a shift computed twice concurrently.
    """
    async with seeded.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO oee.recompute_request (oee_unit_id, range_start, range_end, reason) "
                "SELECT :unit, CAST(:start AS timestamptz) + (n || ' days')::interval, "
                "CAST(:end AS timestamptz) + (n || ' days')::interval, 'pytest' "
                "FROM generate_series(0, 3) AS n"
            ),
            {"unit": unit.unit_id, "start": SHIFT_START, "end": SHIFT_END},
        )

    first, second = await asyncio.gather(
        claim_requests(seeded, COMPUTED_AT, limit=2), claim_requests(seeded, COMPUTED_AT, limit=2)
    )

    mine = [claim for claim in first + second if claim.unit_id == unit.unit_id]
    assert len(mine) == 4
    assert len({claim.request_id for claim in mine}) == 4, "a request was claimed twice"

    await complete_requests(seeded, [claim.request_id for claim in mine], COMPUTED_AT)
    async with seeded.begin() as connection:
        outstanding = (
            await connection.execute(
                text("SELECT count(*) FROM oee.recompute_request WHERE oee_unit_id = :unit AND completed_at IS NULL"),
                {"unit": unit.unit_id},
            )
        ).scalar()
    assert outstanding == 0
    # Claimed rows must not come back on the next pass.
    assert [claim for claim in await claim_requests(seeded, COMPUTED_AT) if claim.unit_id == unit.unit_id] == []


async def test_retention_days_reads_the_timescale_job_table(seeded: Database):
    """
    Queries `timescaledb_information.jobs`, whose shape changes between Timescale versions.
    `None` is a valid answer - a database with no retention policy - so what is asserted is
    that the query runs and returns something usable rather than raising.
    """
    days = await retention_days(seeded, "uns_metrics")

    assert days is None or days > 0
