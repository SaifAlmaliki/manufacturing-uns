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

The one write this service makes to plant data: which reason a stop is attributed to.

An OEE number is computed, never edited. What a human legitimately knows better than
the engine is *why* a machine stopped - the engine only ever saw a state code. So this
mutation corrects the attribution and queues a recomputation, and the engine remains
the only writer of `oee.shift_result` (ADR-0005 for why the write lives in GraphQL at
all: the console is a static bundle with no backend of its own).

The correction is signed by the signed-in user. `assignedBy` is taken from the token's
`preferred_username`, not from an argument: a caller who could name themselves could name
anybody, and this is the only write this platform makes to plant data.

Reassignment can change the OEE, because a reason's `is_planned` flag moves the
interval between Unplanned Down and excluded time. That is correct behaviour, and it is
why this enqueues rather than merely editing a label.
"""

import logging

import strawberry
from uns_model.engine import Database
from uns_model.oee_results import OeeResultRepository

from uns_graphql.auth.require import require
from uns_graphql.type.oee import DowntimeEventType

LOGGER = logging.getLogger(__name__)


def _repository() -> OeeResultRepository:
    return OeeResultRepository(Database.shared("graphql"))


@strawberry.type(description="Correct which reason a stop is attributed to")
class Mutation:
    """All write access to schema `oee`. One field, deliberately."""

    @strawberry.mutation(
        description="Attribute a stop to a reason code by hand and queue that shift for "
        "recomputation. The stored reason becomes MANUAL, which the engine never overwrites. "
        "The correction is signed by the signed-in user, who cannot choose the name recorded. "
        "Errors when there is no such event or the reason code is not authored."
    )
    async def assign_downtime_reason(
        self,
        info: strawberry.Info,
        event_id: strawberry.ID,
        reason_code: str,
        note: str | None = None,
    ) -> DowntimeEventType:
        identity = require(info, "assignDowntimeReason")

        try:
            numeric_id = int(event_id)
        except (TypeError, ValueError) as ex:
            # Rejected before the database, so a typo does not arrive as a driver error.
            raise ValueError(f"{event_id!r} is not a downtime event id") from ex

        assigned = await _repository().assign_reason(
            numeric_id, reason_code, note=note, assigned_by=identity.username
        )
        if assigned is None:
            # Non-null return type, and the right answer: an operator whose click did
            # nothing has to be told, not handed an empty object.
            raise ValueError(f"There is no downtime event {event_id}")

        LOGGER.info(
            "Downtime event %s attributed to %s by %s", event_id, reason_code, identity.username
        )
        return DowntimeEventType.from_row(assigned)

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the queries, which dispose it."""
