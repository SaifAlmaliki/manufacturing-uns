"""`uns_oee_recompute` - queue a range for recomputation (spec sections 9.1 and 10).

Two jobs the automatic backfill cannot do: a range older than `backfill_days`, and a
deliberate recomputation after master data changed. A corrected ideal cycle time moves
Performance for every shift that ran that product, and no fingerprint of historian rows will
ever notice, because not one sample changed.

Writes a row to `oee.recompute_request` and stops there. The engine is the only writer of
results, so this process never computes one: `--now` enqueues the same row and then runs one
ordinary pass, which claims it through `claim_requests` like any other request.

    uns_oee_recompute --asset-path Enterprise/Site/Area/Line1 --from 2026-08-01 --to 2026-09-01
    uns_oee_recompute --all-units --from 2026-08-01 --to 2026-09-01 --now --reason "cycle times"
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert

from uns_model.engine import Database
from uns_model.oee_tables import RecomputeRequest
from uns_oee.main import build_scheduler, configure_asyncio_for_mqtt, utc_now
from uns_oee.master_data import MasterDataLoader
from uns_oee.oee_config import OEE_ENV, OeeConfig
from uns_oee.publisher import ResultPublisher

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def as_utc(text: str) -> datetime:
    """An ISO-8601 timestamp as an aware UTC datetime.

    A naive value is read as UTC rather than refused. The range is a filter over shift
    boundaries, not a boundary itself - the shift calendar resolves those from each pattern's
    own timezone - so `2026-08-01` cannot move a shift into the wrong day.
    """
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(f"{text!r} is not an ISO-8601 timestamp") from ex
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    """The command line. One target, one range, two optional flags."""
    parser = argparse.ArgumentParser(
        prog="uns_oee_recompute",
        description="Queue a shift range for recomputation by the OEE engine.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--asset-path", help="ISA-95 path of the OEE unit, e.g. Enterprise/Site/Area/Line1")
    target.add_argument(
        "--all-units",
        action="store_true",
        help="Every active unit. Written as a single request with no unit, which is how the table spells it.",
    )
    parser.add_argument("--from", dest="range_start", required=True, type=as_utc, help="Start of the range")
    parser.add_argument("--to", dest="range_end", required=True, type=as_utc, help="End of the range, exclusive")
    parser.add_argument("--reason", default="", help="Why. Stored on the request and read by the next engineer.")
    parser.add_argument("--requested-by", default=None, help="Defaults to the invoking OS user.")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run one engine pass in this process after enqueuing, instead of waiting for the engine's next scan.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parsed arguments, with the range validated. Exits 2 on a usage error."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.range_end <= args.range_start:
        # The table's CHECK would refuse this too, as an IntegrityError traceback. A usage
        # message is the better answer to a transposed pair of dates.
        parser.error("--to must be after --from")
    if args.requested_by is None:
        args.requested_by = _invoking_user()
    return args


def _invoking_user() -> str:
    """Who to record. `getuser` raises in a container with no passwd entry."""
    try:
        return getpass.getuser()
    except Exception:
        return "cli"


async def resolve_unit_id(master: Any, asset_path: str) -> int:
    """The `oee_unit.id` for an asset path. Exits 1 with the valid paths if there is none."""
    units = await master.active_units()
    for unit in units:
        if unit.asset_path == asset_path:
            return unit.unit_id
    known = ", ".join(sorted(unit.asset_path for unit in units)) or "none configured"
    raise SystemExit(f"No active OEE unit at {asset_path!r}. Active units: {known}")


async def enqueue(
    database: Any,
    unit_id: int | None,
    start: datetime,
    end: datetime,
    *,
    reason: str,
    requested_by: str,
) -> int:
    """Insert one pending request and return its id.

    `claimed_at`, `completed_at` and `error` are left unset: a pending row is the entire
    message, and `requested_at` comes from the server's `now()` so the queue is ordered by one
    clock rather than by whichever machine ran the CLI.
    """
    statement = (
        insert(RecomputeRequest)
        .values(
            oee_unit_id=unit_id,
            range_start=start,
            range_end=end,
            reason=reason,
            requested_by=requested_by,
        )
        .returning(RecomputeRequest.id)
    )
    async with database.begin() as connection:
        return (await connection.execute(statement)).scalar_one()


async def run(
    argv: Sequence[str] | None = None,
    *,
    database: Any | None = None,
    master: Any | None = None,
    pass_runner: Callable[[], Any] | None = None,
) -> int:
    """Enqueue the request, and run one pass if asked. Returns the process exit code.

    `database`, `master` and `pass_runner` are injected so the argument and SQL behaviour can
    be tested without a database; production leaves all three unset.
    """
    args = parse_args(argv)
    config = OeeConfig.from_settings()
    owned = database is None
    database = database if database is not None else Database.shared(OEE_ENV)
    master = master if master is not None else MasterDataLoader(database)

    try:
        unit_id = None if args.all_units else await resolve_unit_id(master, args.asset_path)
        request_id = await enqueue(
            database,
            unit_id,
            args.range_start,
            args.range_end,
            reason=args.reason,
            requested_by=args.requested_by,
        )
        LOGGER.info(
            "Queued recompute request %d for %s from %s to %s",
            request_id,
            args.asset_path if unit_id is not None else "every active unit",
            args.range_start.isoformat(),
            args.range_end.isoformat(),
        )
        if args.now:
            await _run_one_pass(config, database, pass_runner)
        else:
            LOGGER.info("The engine will claim it within %.0fs", config.scan_interval_seconds)
        return 0
    finally:
        if owned:
            await Database.close_shared()


async def _run_one_pass(config: OeeConfig, database: Any, pass_runner: Callable[[], Any] | None) -> None:
    """One ordinary engine pass in this process.

    Ordinary means ordinary: it also re-checks every shift still inside `late_window_hours`
    and, against an empty results table, runs the bounded backfill. Said out loud rather than
    suppressed - an unchanged shift costs two indexed queries, and the rest needed computing.
    """
    LOGGER.info("Running one pass here. It will also re-check recent shifts and, on an empty table, backfill.")
    if pass_runner is not None:
        await pass_runner()
        return
    publisher = ResultPublisher(config)
    try:
        summary = await build_scheduler(config, database, publisher).run_pass(utc_now())
        LOGGER.info(
            "Pass computed %d shift(s) with %d failure(s)", len(summary.outcomes), summary.failures
        )
    finally:
        await publisher.aclose()


def main() -> None:
    """Console entry point `uns_oee_recompute`."""
    configure_asyncio_for_mqtt()
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
