"""Late telemetry aggregate refresh worker for Timescale continuous aggregates."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from uns_model.engine import Database

from uns_historian.batch import PIPELINE_SCHEMA

LOGGER = logging.getLogger(__name__)

METRICS_1M_VIEW = "uns_metrics_1m"
METRICS_1H_VIEW = "uns_metrics_1h"

_PENDING_WORK = text(
    f"SELECT utc_day, pending_generation, processed_generation "
    f"FROM {PIPELINE_SCHEMA}.late_refresh_worklist "
    "WHERE processed_generation < pending_generation "
    "ORDER BY utc_day ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
)

_MARK_PROCESSED = text(
    f"UPDATE {PIPELINE_SCHEMA}.late_refresh_worklist "
    "SET processed_generation = :generation, updated_at = now() "
    "WHERE utc_day = :utc_day AND pending_generation >= :generation "
    "AND processed_generation < :generation"
)

_REFRESH_AGGREGATE = text("CALL refresh_continuous_aggregate(:view_name, :start_time, :end_time)")


class AggregateRefreshError(RuntimeError):
    """Continuous aggregate refresh failed."""


@dataclass(frozen=True, slots=True)
class RefreshClaim:
    utc_day: date
    generation: int


def utc_day_bounds(utc_day: date) -> tuple[datetime, datetime]:
    start = datetime(utc_day.year, utc_day.month, utc_day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


class AggregateRefreshWorker:
    """Refresh uns_metrics continuous aggregates for late telemetry days."""

    def __init__(self, database: Database | None = None) -> None:
        self._database = database or Database.shared("historian")

    async def claim_pending(self) -> RefreshClaim | None:
        async with self._database.begin() as connection:
            row = (await connection.execute(_PENDING_WORK)).mappings().first()
            if row is None:
                return None
            return RefreshClaim(utc_day=row["utc_day"], generation=int(row["pending_generation"]))

    async def refresh_claim(self, claim: RefreshClaim) -> None:
        start, end = utc_day_bounds(claim.utc_day)
        async with self._database.begin() as connection:
            for view_name in (METRICS_1M_VIEW, METRICS_1H_VIEW):
                await connection.execute(
                    _REFRESH_AGGREGATE,
                    {"view_name": view_name, "start_time": start, "end_time": end},
                )
            updated = (
                await connection.execute(
                    _MARK_PROCESSED,
                    {"utc_day": claim.utc_day, "generation": claim.generation},
                )
            ).rowcount
            if updated != 1:
                raise AggregateRefreshError(
                    f"late refresh generation {claim.generation} for {claim.utc_day} was superseded"
                )
        LOGGER.info(
            "Refreshed continuous aggregates for %s through generation %s",
            claim.utc_day,
            claim.generation,
        )

    async def run_once(self) -> bool:
        claim = await self.claim_pending()
        if claim is None:
            return False
        await self.refresh_claim(claim)
        return True
