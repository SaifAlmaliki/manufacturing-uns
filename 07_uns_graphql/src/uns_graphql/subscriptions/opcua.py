"""OPC UA data-change subscription for the console.

A live probe, not a collector: the console opens a WebSocket, watches a handful of
nodes for as long as the page is open, and closes. There is no spool, no deadband,
no republishing — `subscribe_data_change` is enough. The bridge's collector does
the heavy version with deadbands and store-and-forward; this is the read-only
console view of the same PLC.
"""

from __future__ import annotations

import asyncio
import logging
import typing

import strawberry
from uns_opcua import browse as opcua_browse
from uns_opcua.session import open_client

from uns_graphql.auth.require import OPC_PROBE_ROLES, require_role
from uns_graphql.type.connectivity import OpcUaDataValueType
from uns_opcua.payload import quality_from_code

LOGGER = logging.getLogger(__name__)


class _DataChangeHandler:
    """asyncua handler that pushes each change onto an asyncio queue.

    Called from the client's task, so it must not block: it maps a single
    DataValue to an `OpcUaDataValueType` and enqueues, mirroring the collector's
    `SubscriptionHandler` discipline (same `(node, val, data)` signature and
    `data.monitored_item.Value` unwrap).
    """

    def __init__(self, queue: asyncio.Queue[OpcUaDataValueType]) -> None:
        self._queue = queue

    def datachange_notification(self, node, val, data) -> None:  # noqa: ANN001 - asyncua protocol
        try:
            data_value = data.monitored_item.Value
            row = opcua_browse.DataValueRow(
                node_id=node.nodeid.to_string(),
                display_name="",  # display_name is resolved by the drawer from the browse tree
                browse_path="",
                value=val,
                data_type=None,
                source_timestamp=data_value.SourceTimestamp,
                server_timestamp=data_value.ServerTimestamp,
                status=quality_from_code(int(data_value.StatusCode.value)),
            )
            self._queue.put_nowait(OpcUaDataValueType.from_row(row))
        except Exception:  # noqa: BLE001 - a callback must not kill the client task
            LOGGER.exception("Failed to enqueue an OPC UA data change")


@strawberry.type(description="Subscribe to live OPC UA data changes")
class Subscription:
    @strawberry.subscription(
        description="Yield the current value of one or more OPC UA nodes each time the server reports a change."
    )
    async def opc_ua_data_changes(
        self,
        info: strawberry.Info,
        endpoint: str,
        node_ids: list[str],
    ) -> typing.AsyncGenerator[OpcUaDataValueType]:
        require_role(info, OPC_PROBE_ROLES)
        queue: asyncio.Queue[OpcUaDataValueType] = asyncio.Queue()
        handler = _DataChangeHandler(queue)
        async with await open_client(endpoint) as client:
            subscription = await client.create_subscription(200.0, handler)
            nodes = [client.get_node(node_id) for node_id in node_ids]
            await subscription.subscribe_data_change(nodes)
            try:
                while True:
                    yield await queue.get()
            finally:
                await subscription.delete()

    @classmethod
    async def on_shutdown(cls):
        """Subscriptions own no process-wide resources; each WebSocket closes itself."""
