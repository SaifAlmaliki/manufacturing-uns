"""Tests for uns_oee.recompute_cli.

Argument handling is pure and gets tested directly. The one database call, `enqueue`, is
tested against a fake connection that records the compiled statement - what matters is that
the row lands pending, with the range the operator asked for.
"""

from datetime import datetime, timedelta, timezone

import pytest

from uns_oee.recompute_cli import as_utc, enqueue, parse_args, resolve_unit_id, run

FROM = "2026-08-01T00:00:00+00:00"
TO = "2026-09-01T00:00:00+00:00"
LINE = "CovestroAG/Dormagen/Production/Line1"


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeConnection:
    def __init__(self, results):
        self._results = list(results)
        self.statements: list = []

    async def execute(self, statement, parameters=None):
        self.statements.append(statement)
        return self._results.pop(0)


class FakeDatabase:
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


class FakeUnit:
    def __init__(self, unit_id: int, asset_path: str) -> None:
        self.unit_id = unit_id
        self.asset_path = asset_path


class FakeMaster:
    def __init__(self, units) -> None:
        self._units = units

    async def active_units(self):
        return self._units


# --- timestamps ----------------------------------------------------------------------


def test_a_naive_timestamp_is_read_as_utc():
    # A bare date is what an operator types. It is a range filter, not a shift boundary -
    # the shift calendar resolves local boundaries from the pattern's own timezone - so
    # reading it as UTC cannot shift a shift into the wrong day.
    assert as_utc("2026-08-01") == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_an_offset_is_honoured_rather_than_overwritten():
    parsed = as_utc("2026-08-01T02:00:00+02:00")
    assert parsed == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert parsed.tzinfo is not None


def test_an_unparsable_timestamp_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--asset-path", LINE, "--from", "last tuesday", "--to", TO])
    assert exit_info.value.code == 2


# --- arguments -----------------------------------------------------------------------


def test_a_unit_and_a_range_are_enough():
    args = parse_args(["--asset-path", LINE, "--from", FROM, "--to", TO])
    assert args.asset_path == LINE
    assert args.all_units is False
    assert args.now is False
    assert args.range_start == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_a_target_is_required():
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--from", FROM, "--to", TO])
    assert exit_info.value.code == 2


def test_a_unit_and_all_units_cannot_both_be_asked_for():
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--asset-path", LINE, "--all-units", "--from", FROM, "--to", TO])
    assert exit_info.value.code == 2


def test_a_backwards_range_is_refused_before_anything_is_written():
    # The table's CHECK would refuse it too, but as an IntegrityError traceback rather than
    # a usage message.
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--all-units", "--from", TO, "--to", FROM])
    assert exit_info.value.code == 2


# --- the unit -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_asset_path_resolves_to_its_unit_id():
    master = FakeMaster([FakeUnit(1, LINE), FakeUnit(2, "Other/Line2")])
    assert await resolve_unit_id(master, LINE) == 1


@pytest.mark.asyncio
async def test_an_unknown_asset_path_names_the_paths_that_do_exist():
    master = FakeMaster([FakeUnit(1, LINE)])
    with pytest.raises(SystemExit) as exit_info:
        await resolve_unit_id(master, "Typo/Line9")
    # The message, not just the exit code: an operator with a typo needs the list.
    assert LINE in str(exit_info.value)


# --- the row --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_writes_one_pending_request_and_returns_its_id():
    database = FakeDatabase(FakeResult(42))
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    request_id = await enqueue(
        database, 1, start, start + timedelta(days=31), reason="cycle time fixed", requested_by="ops"
    )
    assert request_id == 42
    sql = str(database.connection.statements[0]).lower()
    assert "insert into oee.recompute_request" in sql
    # claimed_at and completed_at are left NULL: pending is the whole point of the row.
    assert "claimed_at" not in sql
    assert "returning" in sql


@pytest.mark.asyncio
async def test_all_units_enqueues_one_row_with_no_unit():
    database = FakeDatabase(FakeResult(7))
    exit_code = await run(["--all-units", "--from", FROM, "--to", TO], database=database, master=FakeMaster([]))
    assert exit_code == 0
    parameters = database.connection.statements[0].compile().params
    assert parameters["oee_unit_id"] is None


@pytest.mark.asyncio
async def test_a_queued_request_does_not_run_a_pass():
    database = FakeDatabase(FakeResult(7))
    ran = []
    await run(
        ["--asset-path", LINE, "--from", FROM, "--to", TO],
        database=database,
        master=FakeMaster([FakeUnit(1, LINE)]),
        pass_runner=lambda: ran.append(True),
    )
    # Without --now the CLI's job is done when the row is committed; the engine's next pass
    # picks it up. Running a pass here would make the CLI a second writer of results.
    assert ran == []


@pytest.mark.asyncio
async def test_now_runs_one_pass_after_enqueuing():
    database = FakeDatabase(FakeResult(7))
    ran = []

    async def pass_runner():
        ran.append(True)

    exit_code = await run(
        ["--asset-path", LINE, "--from", FROM, "--to", TO, "--now"],
        database=database,
        master=FakeMaster([FakeUnit(1, LINE)]),
        pass_runner=pass_runner,
    )
    assert exit_code == 0
    assert ran == [True]
