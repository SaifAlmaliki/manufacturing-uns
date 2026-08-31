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

Operator commands for the Asset Model: `uns_model_migrate`, `uns_model_seed` and
`uns_model_setup`, which is both in the order a deployment needs them.

All three are thin: the migration lives in migrations/, the plan lives in seed.py,
and this module only parses arguments and reports what happened.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from uns_config import get_settings

from uns_model.engine import Database
from uns_model.model_config import ModelConfig
from uns_model.repositories import AssetModelRepository
from uns_model.seed import SeedPlan, apply_plan, plan_from_simulator_config

LOGGER = logging.getLogger(__name__)

_ALEMBIC_INI = "alembic.ini"


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-5.5s [%(name)s] %(message)s",
    )


def _project_dir() -> Path:
    """
    The directory holding alembic.ini and migrations/.

    Walked up from this file rather than assumed to be the working directory, so
    `uns_model_migrate` works from anywhere. Migrations are not packaged inside the
    wheel, so this requires the editable install the uv workspace already uses.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / _ALEMBIC_INI).is_file() and (parent / "migrations").is_dir():
            return parent
    raise FileNotFoundError(
        f"Could not find {_ALEMBIC_INI} above {__file__}. "
        "Run `alembic upgrade head` from the 09_uns_model source directory instead."
    )


def migrate(argv: list[str] | None = None) -> int:
    """Bring the `model` schema to a revision. Defaults to the latest."""
    parser = argparse.ArgumentParser(
        prog="uns_model_migrate",
        description="Create or update the Asset Model schema in Postgres.",
    )
    parser.add_argument("revision", nargs="?", default="head", help="Target revision (default: head)")
    parser.add_argument("--downgrade", action="store_true", help="Move down to REVISION instead of up")
    parser.add_argument("--sql", action="store_true", help="Print the SQL instead of running it")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    # Imported here so that `uns_model` itself does not depend on Alembic at runtime.
    from alembic import command
    from alembic.config import Config

    config = ModelConfig.from_settings()
    if not config.is_valid():
        LOGGER.error("Asset Model database is not configured. Set historian.* in conf/settings.yaml.")
        return 2

    project_dir = _project_dir()
    alembic_config = Config(str(project_dir / _ALEMBIC_INI))
    alembic_config.set_main_option("script_location", str(project_dir / "migrations"))

    LOGGER.info("Migrating %s on %s:%s/%s", args.revision, config.hostname, config.port, config.database)
    if args.downgrade:
        command.downgrade(alembic_config, args.revision, sql=args.sql)
    else:
        command.upgrade(alembic_config, args.revision, sql=args.sql)
    return 0


def seed(argv: list[str] | None = None) -> int:
    """Import the configured plant description into the Asset Model."""
    parser = argparse.ArgumentParser(
        prog="uns_model_seed",
        description="Import conf/settings.yaml `simulator.*` into the Asset Model.",
    )
    parser.add_argument(
        "--from-simulator-config",
        action="store_true",
        help="Source the hierarchy and sensors from simulator.* (currently the only source)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    settings = get_settings("simulator")
    plan = plan_from_simulator_config(
        {
            "hierarchy": settings.get("hierarchy"),
            "plc": settings.get("plc"),
            "equipment": settings.get("equipment"),
        }
    )

    if args.dry_run:
        sys.stdout.write(plan.describe() + "\n")
        LOGGER.info(
            "Dry run: %s Asset(s) and %s Metric Definition(s) would be written",
            len(plan.asset_paths),
            len(plan.metrics),
        )
        return 0

    return asyncio.run(_seed(plan))


async def _seed(plan: SeedPlan) -> int:
    database = Database.from_config(ModelConfig.from_settings())
    try:
        repository = AssetModelRepository(database)
        written = await apply_plan(repository, plan)
        counts = await repository.counts()
        LOGGER.info(
            "Seeded %s Asset(s) and %s Metric Definition(s); rebound %s topic(s)",
            written["assets"],
            written["metric_definitions"],
            written["rebound_topics"],
        )
        LOGGER.info(
            "Asset Model now holds %s Asset(s), %s Metric Definition(s), %s bound and %s unmodelled topic(s)",
            counts["assets"],
            counts["metric_definitions"],
            counts["bound_topics"],
            counts["unmodelled_topics"],
        )
        # Worth shouting about: data is arriving that the Asset Model cannot explain.
        for topic in await repository.unmodelled_topics(limit=10):
            LOGGER.warning("Unmodelled Topic: %s", topic)
    finally:
        await database.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    """
    Migrate, then seed. The entrypoint of the Asset Model container.

    One command rather than two, because a deployment always wants both and seeding
    a schema that was never migrated fails in a way nobody can read. Both steps are
    idempotent, so re-running it is how the model is updated.
    """
    parser = argparse.ArgumentParser(
        prog="uns_model_setup",
        description="Bring the Asset Model schema and content up to date.",
    )
    parser.add_argument("--skip-seed", action="store_true", help="Migrate only, leaving the Asset Model untouched")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    forwarded = ["-v"] if args.verbose else []
    if status := migrate(forwarded):
        return status
    if args.skip_seed:
        LOGGER.info("Skipping the seed as asked; the Asset Model schema is up to date")
        return 0
    return seed(["--from-simulator-config", *forwarded])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
