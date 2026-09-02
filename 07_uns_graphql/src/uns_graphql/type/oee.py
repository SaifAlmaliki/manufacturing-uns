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

GraphQL types for computed OEE, held in schema `oee`.

The enums are spelled out rather than generated from `uns_model.oee_tables`, because a
GraphQL schema is a published contract and a generated enum changes shape without
anybody reviewing it. `test/type/test_oee.py` fails if the two drift.

Every ratio is nullable. Spec section 8.1: a shift with no Loading Time has no
Availability - it did not achieve 0% - and a schema that could not say so would force
the console to invent a number.
"""

import logging
from datetime import datetime
from enum import Enum

import strawberry
from uns_model.oee_results import DowntimeEventRow, ParetoBucket, ShiftResultRow
from uns_model.oee_tables import ShiftResultProduct

LOGGER = logging.getLogger(__name__)


@strawberry.enum(description="Whether the shift's numbers are usable, and why not when they are not.")
class OeeStatus(Enum):
    OK = "OK"
    NO_LOADING_TIME = "NO_LOADING_TIME"
    NO_PRODUCTION = "NO_PRODUCTION"
    MISSING_IDEAL_CYCLE_TIME = "MISSING_IDEAL_CYCLE_TIME"
    NO_INPUT_DATA = "NO_INPUT_DATA"


@strawberry.enum(description="Whether a stop was classified by the engine or corrected by a person.")
class ReasonSource(Enum):
    AUTO = "auto"
    MANUAL = "manual"


@strawberry.type(description="One product's counts and rated cycle time within a shift.")
class OeeShiftProduct:
    """
    Stored per product because Performance is a sum over products.

    A mixed shift's number cannot be re-derived from the totals once the product mix is
    gone, so the terms are published rather than only the result.
    """

    product_code: str = strawberry.field(description="The value the line published, e.g. a recipe id.")
    good_count: float
    reject_count: float
    total_count: float
    ideal_cycle_time_s: float | None = strawberry.field(
        description="Seconds per unit at the designed rate. Null when none was authored, "
        "which sets MISSING_IDEAL_CYCLE_TIME on the shift."
    )

    @classmethod
    def from_row(cls, product: ShiftResultProduct) -> "OeeShiftProduct":
        return cls(
            product_code=product.product_code,
            good_count=product.good_count,
            reject_count=product.reject_count,
            total_count=product.total_count,
            ideal_cycle_time_s=product.ideal_cycle_time_s,
        )


@strawberry.type(description="Availability x Performance x Quality for one closed shift on one Asset.")
class OeeShiftResult:
    """
    The current result for a shift. Superseded numbers are kept in
    `oee.shift_result_revision` and are deliberately not published: a dashboard reads
    one row per shift, and `revision` is what tells it the number has been restated.
    """

    asset_path: str = strawberry.field(description="The Line the number is reported for.")
    shift_start: datetime
    shift_end: datetime
    shift_label: str

    loading_time_s: float = strawberry.field(description="Scheduled time less planned stops and exceptions.")
    run_time_s: float = strawberry.field(description="Time in a producing state, measured over the interval union.")
    planned_down_s: float
    unplanned_down_s: float

    good_count: float
    reject_count: float
    total_count: float

    availability: float | None = strawberry.field(description="Run Time / Loading Time. Null when undefined.")
    performance: float | None = strawberry.field(description="Clamped at 1.0. Null when undefined.")
    performance_raw: float | None = strawberry.field(
        description="Performance before the clamp. Above 1 means the ideal cycle time is wrong "
        "or a stop was missed, and this is the only evidence of that."
    )
    quality: float | None = strawberry.field(description="Good Count / Total Count. Null when undefined.")
    oee: float | None

    status: OeeStatus
    revision: int = strawberry.field(description="Increments when late data restated the shift.")
    computed_at: datetime | None = None
    published_at: datetime | None = strawberry.field(
        default=None, description="When the result reached MQTT. Null means it has not yet."
    )
    products: list[OeeShiftProduct] = strawberry.field(
        default_factory=list, description="Empty on a line that publishes no recipe."
    )

    @classmethod
    def from_row(cls, row: ShiftResultRow) -> "OeeShiftResult":
        result = row.result
        return cls(
            asset_path=row.asset_path,
            shift_start=result.shift_start,
            shift_end=result.shift_end,
            shift_label=result.shift_label,
            loading_time_s=result.loading_time_s,
            run_time_s=result.run_time_s,
            planned_down_s=result.planned_down_s,
            unplanned_down_s=result.unplanned_down_s,
            good_count=result.good_count,
            reject_count=result.reject_count,
            total_count=result.total_count,
            # Passed straight through, never coalesced: see the module docstring.
            availability=result.availability,
            performance=result.performance,
            performance_raw=result.performance_raw,
            quality=result.quality,
            oee=result.oee,
            status=OeeStatus(result.status),
            revision=result.revision,
            computed_at=result.computed_at,
            published_at=result.published_at,
            products=[OeeShiftProduct.from_row(product) for product in row.products],
        )


@strawberry.type(name="DowntimeEvent", description="One stop, with the reason it is attributed to.")
class DowntimeEventType:
    """
    Published as `DowntimeEvent` (spec section 10) from a Python class that does not
    collide with the ORM class of the same name, which this module's dependencies import.

    `isPlanned` travels with the event because it is what explains a changed OEE: it is
    the flag that moves the interval between Unplanned Down and excluded time.
    """

    id: strawberry.ID
    asset_path: str
    shift_start: datetime = strawberry.field(description="The shift this stop is counted against.")
    started_at: datetime
    ended_at: datetime
    duration_s: float
    state_value: str = strawberry.field(description="The published state that held for the whole stop, e.g. 'ABORTED'.")

    reason_code: str
    reason_display_name: str
    reason_category: str
    is_planned: bool
    reason_source: ReasonSource
    assigned_by: str | None = None
    assigned_at: datetime | None = None
    note: str = ""

    @classmethod
    def from_row(cls, row: DowntimeEventRow) -> "DowntimeEventType":
        event = row.event
        return cls(
            id=strawberry.ID(str(event.id)),
            asset_path=row.asset_path,
            shift_start=event.shift_start,
            started_at=event.started_at,
            ended_at=event.ended_at,
            duration_s=event.duration_s,
            state_value=event.state_value,
            reason_code=event.reason_code,
            reason_display_name=row.display_name,
            reason_category=row.category,
            is_planned=row.is_planned,
            reason_source=ReasonSource(event.reason_source),
            assigned_by=event.assigned_by,
            assigned_at=event.assigned_at,
            note=event.note,
        )


@strawberry.type(description="One reason code's share of the downtime in a window, largest first.")
class DowntimeParetoBucket:
    reason_code: str
    display_name: str
    category: str
    is_planned: bool
    event_count: int
    total_seconds: float
    share: float = strawberry.field(
        description="Fraction of the window's total downtime, 0..1. Zero when nothing was lost."
    )

    @classmethod
    def from_bucket(cls, bucket: ParetoBucket) -> "DowntimeParetoBucket":
        return cls(
            reason_code=bucket.reason_code,
            display_name=bucket.display_name,
            category=bucket.category,
            is_planned=bucket.is_planned,
            event_count=bucket.event_count,
            total_seconds=bucket.total_seconds,
            share=bucket.share,
        )
