"""Connectivity catalog writes.

Role each field needs is in `auth/require.py`, not in these resolvers. Repository
`ValueError` is raised as-is so Strawberry surfaces the message, same contract as
`mutations/access_group.py`.

`subscribeOpcUaVariables` is the discovery path: it discovers every Variable on the
server's endpoint and folds the result into the catalog via
`ConnectivityRepository.replace_subscribed_tags`, which keeps an engineer's edited
`mqtt_topic` and never unsubscribes by omission.
"""

from __future__ import annotations

import logging

import strawberry
from uns_model.connectivity import (
    ConnectivityRepository,
    ConnectivityServerSpec,
    ConnectivityTagSpec,
)
from uns_model.engine import Database
from uns_opcua import browse as opcua_browse
from uns_opcua.session import open_client

from uns_graphql.auth.require import require
from uns_graphql.input.connectivity import ConnectivityServerInput
from uns_graphql.type.connectivity import ConnectivityServerType, ConnectivityTagType

LOGGER = logging.getLogger(__name__)


def _repository() -> ConnectivityRepository:
    return ConnectivityRepository(Database.shared("graphql"))


async def _server_endpoint(server_id: str) -> str | None:
    """The endpoint of a saved server, or None when no such server is stored."""
    for server in await _repository().list_servers():
        if server.id == server_id:
            return server.endpoint
    return None


@strawberry.type(description="Author the console's Connectivity catalog")
class Mutation:
    @strawberry.mutation(
        description="Create or replace one Connectivity server and return it as stored. "
        "Fails with a readable message when a value is outside the allowed vocabulary."
    )
    async def save_connectivity_server(
        self, info: strawberry.Info, server: ConnectivityServerInput
    ) -> ConnectivityServerType:
        require(info, "saveConnectivityServer")
        saved = await _repository().save_server(
            ConnectivityServerSpec(
                id=server.id,
                name=server.name,
                protocol=server.protocol.value,
                endpoint=server.endpoint,
                auth_mode=server.auth_mode.value,
                security_policy=server.security_policy.value,
                security_mode=server.security_mode.value,
                username=server.username,
                password=server.password,
                certificate=server.certificate,
                private_key=server.private_key,
                server_certificate=server.server_certificate,
            )
        )
        LOGGER.info("Connectivity server %s saved as %s", saved.id, saved.name)
        return ConnectivityServerType.from_server(saved)

    @strawberry.mutation(
        description="Delete a Connectivity server and its tags (cascade). False when there was no such server."
    )
    async def delete_connectivity_server(self, info: strawberry.Info, id: str) -> bool:  # noqa: A002
        require(info, "deleteConnectivityServer")
        deleted = await _repository().delete_server(id)
        if deleted:
            LOGGER.info("Connectivity server %s deleted", id)
        return deleted

    @strawberry.mutation(
        description="Discover Variables under nodeId (or the whole Objects tree) and fold "
        "them into the catalog. An engineer's edited mqttTopic survives; nodes missing "
        "from this discovery stay subscribed until unsubscribeConnectivityTag removes them."
    )
    async def subscribe_opc_ua_variables(
        self,
        info: strawberry.Info,
        server_id: str,
        node_id: str | None = strawberry.UNSET,
    ) -> list[ConnectivityTagType]:
        require(info, "subscribeOpcUaVariables")
        endpoint = await _server_endpoint(server_id)
        if endpoint is None:
            raise ValueError(f"No Connectivity server with id {server_id!r}")
        start = node_id if node_id is not strawberry.UNSET else None
        async with await open_client(endpoint) as client:
            discovered = await opcua_browse.discover_variables(client, start)
        tags = [
            ConnectivityTagSpec(
                node_id=row.node_id,
                browse_path=row.browse_path,
                display_name=row.display_name,
                mqtt_topic=row.browse_path,
            )
            for row in discovered
        ]
        stored = await _repository().replace_subscribed_tags(server_id, tags)
        LOGGER.info("Subscribed %s tag(s) on %s", len(stored), server_id)
        return [ConnectivityTagType.from_tag(tag) for tag in stored]

    @strawberry.mutation(
        description="Set the MQTT topic an engineer wants this node republished under."
    )
    async def update_connectivity_tag_topic(
        self, info: strawberry.Info, server_id: str, node_id: str, mqtt_topic: str
    ) -> ConnectivityTagType:
        require(info, "updateConnectivityTagTopic")
        tag = await _repository().update_tag_topic(server_id, node_id, mqtt_topic)
        if tag is None:
            raise ValueError(
                f"No Connectivity tag for server {server_id!r} node {node_id!r}"
            )
        return ConnectivityTagType.from_tag(tag)

    @strawberry.mutation(
        description="Stop subscribing to a node. A deliberate act, never done by omission. "
        "False when there was no such tag."
    )
    async def unsubscribe_connectivity_tag(
        self, info: strawberry.Info, server_id: str, node_id: str
    ) -> bool:
        require(info, "unsubscribeConnectivityTag")
        tag = await _repository().unsubscribe_tag(server_id, node_id)
        if tag is None:
            return False
        LOGGER.info("Unsubscribed %s on %s", node_id, server_id)
        return True

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the Asset Model queries, which dispose it."""
