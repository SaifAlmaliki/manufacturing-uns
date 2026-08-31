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

Resolving observed topics to Assets, once each.

The ingest path calls `observe()` for every message, so the interface has to be
cheap to call and impossible to get wrong: after the first time a topic is seen,
`observe()` does nothing at all, and a database problem is logged rather than
raised, because a missing Topic Binding must never cost a stored measurement.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Protocol

LOGGER = logging.getLogger(__name__)

DEFAULT_CAPACITY = 50_000


class _Binder(Protocol):
    """The only part of AssetModelRepository this needs."""

    async def bind_topic(self, topic: str) -> object: ...


class TopicBinder:
    """
    Binds each distinct topic to its Asset the first time it is published.

    Cost is bounded by the number of distinct topics, not the message rate: a plant
    publishing 10,000 messages a second on 2,000 topics does 2,000 binds. The
    remembered set is an LRU so that a broker with unbounded topic churn cannot
    grow it without limit.
    """

    def __init__(self, repository: _Binder, *, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._repository = repository
        self._capacity = capacity
        self._bound: OrderedDict[str, None] = OrderedDict()
        # Two messages on a new topic can arrive concurrently; one bind is enough
        # and the second would deadlock nothing but would waste a round trip.
        self._in_flight: dict[str, asyncio.Future] = {}

    async def observe(self, topic: str) -> None:
        """
        Ensure this topic has a Topic Binding. A no-op for a topic already seen.

        Never raises: the caller is an ingest loop, and Enrichment is not worth a
        lost message. A failed bind is not remembered, so it is retried on the next
        message for that topic.
        """
        if topic in self._bound:
            self._bound.move_to_end(topic)
            return

        if existing := self._in_flight.get(topic):
            await asyncio.shield(existing)
            return

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._in_flight[topic] = future
        try:
            await self._repository.bind_topic(topic)
            self._remember(topic)
        except Exception as ex:  # noqa: BLE001 - ingest must survive anything here
            LOGGER.warning("Could not bind topic %s to an Asset, will retry: %s", topic, ex)
        finally:
            del self._in_flight[topic]
            if not future.done():
                future.set_result(None)

    def forget(self, topic: str | None = None) -> None:
        """
        Drop what is remembered, so the next message rebinds.

        Call with no argument after the Asset Model changed if this process is the
        one that changed it; `AssetModelRepository.rebind_all` handles other
        processes' bindings but cannot reach this in-memory set.
        """
        if topic is None:
            self._bound.clear()
        else:
            self._bound.pop(topic, None)

    @property
    def bound_count(self) -> int:
        """How many distinct topics this process has bound."""
        return len(self._bound)

    def _remember(self, topic: str) -> None:
        self._bound[topic] = None
        self._bound.move_to_end(topic)
        while len(self._bound) > self._capacity:
            self._bound.popitem(last=False)


__all__ = ["TopicBinder"]
