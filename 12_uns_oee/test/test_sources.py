"""Tests for the historian read path.

The SQL is exercised for real in the end-to-end integration test. What is worth pinning
without a database is everything around it: that a metric binding resolves to the right
(topic, metric_name) pair, that the prior-sample query is bounded so it cannot walk a whole
hypertable backwards, that a text metric and a numeric metric read different columns, and
that the fingerprint is a stable string - a fingerprint that formats differently between two
runs would make every shift look like it had late data.
"""

from datetime import datetime, timedelta, timezone

import pytest

from uns_oee.sources import (
    DEFAULT_PRIOR_LOOKBACK_HOURS,
    Fingerprint,
    MetricRef,
    MetricSource,
    earliest_sql,
    fingerprint_sql,
    pair_params,
    prior_sql,
    split_metric_key,
    window_sql,
)

ASSET = "CovestroAG/Dormagen/Production/Line1"
STATE_KEY = "Cell1/MES-01/Status/PackMlState/value"
T0 = datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, results):
        self._results = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        return self._results.pop(0) if self._results else FakeResult([])


class FakeDatabase:
    """Stands in for `uns_model.engine.Database`; only `begin()` is used by MetricSource."""

    def __init__(self, *results):
        self.connection = FakeConnection(results)

    def begin(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


def test_a_binding_splits_into_topic_and_metric_name():
    assert split_metric_key(ASSET, STATE_KEY) == MetricRef(
        topic=f"{ASSET}/Cell1/MES-01/Status/PackMlState", metric_name="value"
    )


def test_a_nested_payload_leaf_is_addressable():
    assert split_metric_key(ASSET, "Cell1/MES-01/Status/Detail/value.inner").metric_name == "value.inner"


def test_surrounding_slashes_do_not_produce_an_empty_segment():
    assert split_metric_key(f"{ASSET}/", f"/{STATE_KEY}") == split_metric_key(ASSET, STATE_KEY)


def test_a_binding_with_no_slash_is_rejected():
    with pytest.raises(ValueError, match="value"):
        split_metric_key(ASSET, "value")


def test_a_fingerprint_formats_the_same_way_twice():
    fingerprint = Fingerprint(row_count=1440, max_time=T0)
    assert fingerprint.as_text() == "1440:2026-09-07T06:00:00+00:00:-"
    assert fingerprint.as_text() == Fingerprint(row_count=1440, max_time=T0).as_text()
    assert fingerprint.is_empty is False


def test_an_empty_fingerprint_is_recognisable_and_still_formats():
    empty = Fingerprint()
    assert empty.is_empty is True
    assert empty.as_text() == "0:-:-"


def test_an_operator_reassignment_moves_the_fingerprint_without_moving_a_sample():
    fingerprint = Fingerprint(row_count=1440, max_time=T0)
    reassigned = fingerprint.with_manual("9f2c1a")
    assert reassigned.as_text() != fingerprint.as_text()
    # Same historian rows: the recompute is driven by the operator, not by late data.
    assert (reassigned.row_count, reassigned.max_time) == (1440, T0)
    assert reassigned.is_empty is False


def test_the_historian_half_of_a_stored_fingerprint_is_recoverable():
    fingerprint = Fingerprint(row_count=1440, max_time=T0)
    # A reassignment leaves the historian half identical; late data changes it.
    assert Fingerprint.source_part(fingerprint.with_manual("9f2c1a").as_text()) == (
        Fingerprint.source_part(fingerprint.as_text())
    )
    later = Fingerprint(row_count=1441, max_time=T0)
    assert Fingerprint.source_part(later.as_text()) != Fingerprint.source_part(fingerprint.as_text())
    assert Fingerprint.source_part(Fingerprint().as_text()) == "0:-"


def test_a_table_name_that_is_not_an_identifier_is_refused():
    with pytest.raises(ValueError, match="metrics table"):
        MetricSource(FakeDatabase(), metrics_table="uns_metrics; DROP TABLE model.asset")


def test_the_window_query_reads_the_column_the_caller_asked_for():
    numeric = window_sql("uns_metrics", "value_double")
    text = window_sql("uns_metrics", "value_text")
    assert "value_double IS NOT NULL" in numeric
    assert "value_text IS NOT NULL" in text
    for statement in (numeric, text):
        assert "topic = :topic" in statement
        assert "metric_name = :metric_name" in statement
        assert "ORDER BY time" in statement


def test_the_prior_query_is_bounded_at_both_ends_and_takes_one_row():
    statement = prior_sql("uns_metrics", "value_double")
    assert "time < :start" in statement
    assert "time >= :lookback_from" in statement
    assert "ORDER BY time DESC" in statement
    assert "LIMIT 1" in statement


def test_the_pair_predicate_binds_one_placeholder_per_pair():
    refs = [MetricRef("a", "value"), MetricRef("b", "value")]
    statement = fingerprint_sql("uns_metrics", len(refs))
    assert "(topic, metric_name) IN ((:topic_0, :metric_0), (:topic_1, :metric_1))" in statement
    assert "count(*)" in statement
    assert "max(time)" in statement
    assert pair_params(refs) == {
        "topic_0": "a",
        "metric_0": "value",
        "topic_1": "b",
        "metric_1": "value",
    }


def test_a_fingerprint_over_no_bindings_is_empty_without_a_query():
    statement = fingerprint_sql("uns_metrics", 0)
    assert statement == ""


def test_the_earliest_query_is_a_min_over_the_same_pairs():
    statement = earliest_sql("uns_metrics", 1)
    assert "min(time)" in statement
    assert "(:topic_0, :metric_0)" in statement


@pytest.mark.asyncio
async def test_numeric_samples_prepend_the_prior_reading():
    database = FakeDatabase(
        FakeResult([(T0 - timedelta(minutes=2), 140.0)]),
        FakeResult([(T0 + timedelta(minutes=5), 150.0), (T0 + timedelta(minutes=10), 160.0)]),
    )
    source = MetricSource(database)
    samples = await source.numeric_samples(
        MetricRef("topic", "value"), T0, T0 + timedelta(hours=8)
    )
    assert [sample.value for sample in samples] == [140.0, 150.0, 160.0]
    assert samples == sorted(samples)


@pytest.mark.asyncio
async def test_include_prior_false_issues_one_query_only():
    database = FakeDatabase(FakeResult([(T0, 150.0)]))
    source = MetricSource(database)
    await source.numeric_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=8), include_prior=False)
    assert len(database.connection.calls) == 1


@pytest.mark.asyncio
async def test_the_prior_query_passes_the_bounded_lookback():
    database = FakeDatabase(FakeResult([]), FakeResult([]))
    source = MetricSource(database, prior_lookback_hours=6)
    await source.numeric_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=8))
    _statement, parameters = database.connection.calls[0]
    assert parameters["lookback_from"] == T0 - timedelta(hours=6)


@pytest.mark.asyncio
async def test_the_prior_lookback_defaults_to_seventy_two_hours():
    database = FakeDatabase(FakeResult([]), FakeResult([]))
    source = MetricSource(database)
    await source.numeric_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=8))
    _statement, parameters = database.connection.calls[0]
    assert DEFAULT_PRIOR_LOOKBACK_HOURS == 72
    assert parameters["lookback_from"] == T0 - timedelta(hours=72)


@pytest.mark.asyncio
async def test_text_samples_become_state_samples():
    database = FakeDatabase(
        FakeResult([(T0 - timedelta(minutes=1), "HELD")]),
        FakeResult([(T0 + timedelta(hours=1), "EXECUTE")]),
    )
    source = MetricSource(database)
    samples = await source.text_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=8))
    assert [sample.state for sample in samples] == ["HELD", "EXECUTE"]


@pytest.mark.asyncio
async def test_a_null_value_row_is_skipped_rather_than_becoming_a_zero():
    # The CHECK constraint makes one of the two value columns null on every row, so a caller
    # that queried the wrong column would otherwise read a column of zeros.
    database = FakeDatabase(FakeResult([]), FakeResult([(T0, None), (T0 + timedelta(minutes=1), 12.0)]))
    source = MetricSource(database)
    samples = await source.numeric_samples(MetricRef("topic", "value"), T0, T0 + timedelta(hours=1))
    assert [sample.value for sample in samples] == [12.0]


@pytest.mark.asyncio
async def test_a_fingerprint_with_no_bindings_never_touches_the_database():
    database = FakeDatabase()
    source = MetricSource(database)
    assert await source.fingerprint([], T0, T0 + timedelta(hours=8)) == Fingerprint()
    assert database.connection.calls == []


@pytest.mark.asyncio
async def test_a_fingerprint_reads_the_count_and_the_latest_time():
    database = FakeDatabase(FakeResult([(1440, T0)]))
    source = MetricSource(database)
    fingerprint = await source.fingerprint([MetricRef("topic", "value")], T0, T0 + timedelta(hours=8))
    assert fingerprint == Fingerprint(row_count=1440, max_time=T0)


@pytest.mark.asyncio
async def test_earliest_sample_at_is_none_when_the_unit_has_never_published():
    database = FakeDatabase(FakeResult([(None,)]))
    source = MetricSource(database)
    assert await source.earliest_sample_at([MetricRef("topic", "value")]) is None
