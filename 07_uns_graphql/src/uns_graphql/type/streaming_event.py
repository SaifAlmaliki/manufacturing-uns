"""Type returned by the canonical live event GraphQL subscription."""

from __future__ import annotations

from datetime import datetime

import strawberry

from uns_graphql.type.basetype import JSONPayload


@strawberry.type
class StreamingMessage:
    """One authorized live UNS event."""

    topic: str
    payload: JSONPayload
    event_id: str | None = None
    event_time: datetime | None = None

    def __init__(
        self,
        topic: str,
        payload: bytes,
        *,
        event_id: str | None = None,
        event_time: datetime | None = None,
    ) -> None:
        self.topic = topic
        self.payload = JSONPayload(data=payload.decode("utf-8"))
        self.event_id = event_id
        self.event_time = event_time

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StreamingMessage):
            return False
        return (
            self.topic == other.topic
            and self.payload.data == other.payload.data
            and self.event_id == other.event_id
            and self.event_time == other.event_time
        )
