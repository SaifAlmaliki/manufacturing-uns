"""GraphQL queries for the Connectivity catalog and live OPC UA probes.

The catalog reads come from `ConnectivityRepository`; the probes are thin wrappers
over `uns_opcua.browse`'s anonymous-session helpers. The probes do not import
`uns_opcua.opcua_config` — they take an endpoint and open their own anonymous
session, so the GraphQL service can reach a PLC the bridge is not configured for.
"""

from __future__ import annotations

import logging

import strawberry
from uns_model.connectivity import ConnectivityRepository
from uns_model.engine import Database
from uns_opcua import browse as opcua_browse
from uns_opcua.session import open_client

from uns_graphql.auth.require import OPC_PROBE_ROLES, require_role
from uns_graphql.type.connectivity import (
    ConnectivityProtocol,
    ConnectivityServerType,
    ConnectivityTestResultType,
    OpcUaBrowseNodeType,
    OpcUaDataValueType,
)

LOGGER = logging.getLogger(__name__)


def _repository() -> ConnectivityRepository:
    return ConnectivityRepository(Database.shared("graphql"))


@strawberry.type(description="Query the console's Connectivity catalog and probe OPC UA servers")
class Query:
    @strawberry.field(
        description="Every Connectivity server, oldest first. Optionally only one protocol's."
    )
    async def get_connectivity_servers(
        self,
        info: strawberry.Info,
        protocol: ConnectivityProtocol | None = strawberry.UNSET,
    ) -> list[ConnectivityServerType]:
        require_role(info, OPC_PROBE_ROLES)
        servers = await _repository().list_servers(
            protocol=protocol.value if protocol is not strawberry.UNSET else None
        )
        return [ConnectivityServerType.from_server(server) for server in servers]

    @strawberry.field(
        description="Open an anonymous session to the endpoint and read the server node. "
        "When a saved server has this endpoint, the outcome is recorded against it."
    )
    async def test_opc_ua_connection(
        self,
        info: strawberry.Info,
        endpoint: str,
    ) -> ConnectivityTestResultType:
        require_role(info, OPC_PROBE_ROLES)
        ok, error, elapsed_ms = await opcua_browse.test_connection(endpoint)
        # Record the test against a saved server that owns this endpoint, if any.
        # The bridge also calls record_test; this is the console's own probe, so the
        # connection history reflects a human pressing "Test", not only the bridge.
        for server in await _repository().list_servers():
            if server.endpoint == endpoint:
                await _repository().record_test(server.id, ok=ok, error=error)
                break
        return ConnectivityTestResultType(ok=ok, error=error, elapsed_ms=elapsed_ms)

    @strawberry.field(
        description="Browse the direct children of one OPC UA node, or of Objects when nodeId is omitted."
    )
    async def browse_opc_ua(
        self,
        info: strawberry.Info,
        endpoint: str,
        node_id: str | None = strawberry.UNSET,
    ) -> list[OpcUaBrowseNodeType]:
        require_role(info, OPC_PROBE_ROLES)
        async with await open_client(endpoint) as client:
            rows = await opcua_browse.browse_children(
                client, node_id if node_id is not strawberry.UNSET else None
            )
        return [OpcUaBrowseNodeType.from_browse(row) for row in rows]

    @strawberry.field(
        description="Recursively discover every Variable under nodeId, or under Objects."
    )
    async def discover_opc_ua_variables(
        self,
        info: strawberry.Info,
        endpoint: str,
        node_id: str | None = strawberry.UNSET,
    ) -> list[OpcUaBrowseNodeType]:
        require_role(info, OPC_PROBE_ROLES)
        start = node_id if node_id is not strawberry.UNSET else None
        async with await open_client(endpoint) as client:
            rows = await opcua_browse.discover_variables(client, start)
        return [OpcUaBrowseNodeType.from_browse(row) for row in rows]

    @strawberry.field(description="Read the current value of one or more OPC UA nodes by NodeId.")
    async def read_opc_ua_nodes(
        self,
        info: strawberry.Info,
        endpoint: str,
        node_ids: list[str],
    ) -> list[OpcUaDataValueType]:
        require_role(info, OPC_PROBE_ROLES)
        async with await open_client(endpoint) as client:
            rows = await opcua_browse.read_nodes(client, node_ids)
        return [OpcUaDataValueType.from_row(row) for row in rows]

    @classmethod
    async def on_shutdown(cls):
        """The engine is shared with the Asset Model queries, which dispose it."""
