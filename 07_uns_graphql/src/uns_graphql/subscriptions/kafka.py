"""GraphQL subscription for authorized canonical live events."""

from __future__ import annotations

import asyncio
import logging
import typing

import strawberry

from uns_graphql.auth.scope import scope_from_info
from uns_graphql.backend.event_stream import get_dispatcher
from uns_graphql.graphql_config import EventStreamConfig
from uns_graphql.input.kafka import KAFKATopicInput
from uns_graphql.queries.asset import _context_resolver
from uns_graphql.type.streaming_event import StreamingMessage

LOGGER = logging.getLogger(__name__)


@strawberry.type(description="Subscribe to authorized live UNS events from the canonical stream.")
class KAFKASubscription:
    """Subscription class providing methods for subscribing to live canonical events."""

    @strawberry.subscription(
        description=(
            "Subscribe to live events for exact original MQTT topics. "
            "Infrastructure Kafka topic names and wildcards are not supported."
        )
    )
    async def get_kafka_messages(
        self, info: strawberry.Info, topics: list[KAFKATopicInput]
    ) -> typing.AsyncGenerator[StreamingMessage]:
        if len(topics) > EventStreamConfig.max_topics_per_subscription:
            raise ValueError(
                f"At most {EventStreamConfig.max_topics_per_subscription} exact MQTT topics are allowed"
            )

        scope = await scope_from_info(info)
        resolver = None if scope.unrestricted else _context_resolver()
        topic_names = [topic_input.topic for topic_input in topics]
        dispatcher = get_dispatcher()
        try:
            async for message in dispatcher.subscribe(topic_names, scope, resolver):
                yield message
        except asyncio.CancelledError:
            LOGGER.info("Live event subscription cancelled.")
            raise

    @classmethod
    async def on_shutdown(cls) -> None:
        """Dispatcher lifecycle is owned by the FastAPI app lifespan."""
