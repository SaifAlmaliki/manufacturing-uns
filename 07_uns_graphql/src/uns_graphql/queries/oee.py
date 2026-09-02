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

GraphQL queries for computed OEE (spec section 10).

Read from `oee.shift_result` and `oee.downtime_event`, never from `uns_metrics`. The
engine has already resolved the shift calendar, the interval union, the counter resets
and the product mix; a dashboard that recomputed any of that from raw samples would be
a second implementation of the arithmetic, free to disagree with the first.

The publishing side is `12_uns_oee`, which puts the same numbers on
`<line>/KPI/ShiftOee`. This is the query path for a range of shifts, which MQTT cannot
answer.
"""

import logging
from datetime import datetime
from typing import Annotated

import strawberry
from uns_model.engine import Database
from uns_model.oee_results import OeeResultRepository

from uns_graphql.type.oee import DowntimeEventType, DowntimeParetoBucket, OeeShiftResult

LOGGER = logging.getLogger(__name__)

# `from` is a Python keyword, so the resolver parameters are named for what they are and
# the published argument names are set explicitly. Spec section 10 fixes them as
# `from`/`to`; test/queries/test_oee.py pins them by introspection.
FromArgument = Annotated[datetime, strawberry.argument(name="from")]
ToArgument = Annotated[datetime, strawberry.argument(name="to")]


def _repository() -> OeeResultRepository:
    return OeeResultRepository(Database.shared("graphql"))


@strawberry.type(description="Query computed OEE results and their downtime breakdown")
class Query:
    """All read access to schema `oee`."""

    @strawberry.field(
        description="Shift results for one Asset whose shift began in [from, to), oldest first. "
        "Ratios are null when undefined - a shift with no Loading Time has no Availability."
    )
    async def oee_shift_results(
        self, asset_path: str, range_start: FromArgument, range_end: ToArgument
    ) -> list[OeeShiftResult]:
        rows = await _repository().shift_results(asset_path, range_start, range_end)
        return [OeeShiftResult.from_row(row) for row in rows]

    @strawberry.field(
        description="Stops for one Asset that began in [from, to), oldest first, each with its "
        "reason code resolved. Bounded the same way downtimePareto is, so the two agree."
    )
    async def downtime_events(
        self, asset_path: str, range_start: FromArgument, range_end: ToArgument
    ) -> list[DowntimeEventType]:
        rows = await _repository().downtime_events(asset_path, range_start, range_end)
        return [DowntimeEventType.from_row(row) for row in rows]

    @strawberry.field(
        description="Lost time per reason code over [from, to), largest first. Always sums to the "
        "window's total downtime: an unmapped state is UNCLASSIFIED, never null."
    )
    async def downtime_pareto(
        self, asset_path: str, range_start: FromArgument, range_end: ToArgument
    ) -> list[DowntimeParetoBucket]:
        buckets = await _repository().downtime_pareto(asset_path, range_start, range_end)
        return [DowntimeParetoBucket.from_bucket(bucket) for bucket in buckets]

    @classmethod
    async def on_shutdown(cls):
        """
        Nothing to do: the engine is shared with the Asset Model queries, which dispose
        it. Kept so every Query mixin has the same shape.
        """
