"""Administration mutations for cloud edge enrollment and access."""

from __future__ import annotations

import logging

import strawberry
from uns_model.edge_repository import EdgeRepository, EdgeRepositoryError
from uns_model.engine import Database

from uns_graphql.auth.require import require
from uns_graphql.edge_api.issuer import EdgeCertificateIssuer, generate_authority
from uns_graphql.edge_api.service import EdgeManagementService
from uns_graphql.type.edge import EdgeDeviceType
from uns_model.edge_secrets import EdgeKeyRing, EdgeSecretStore

LOGGER = logging.getLogger(__name__)


def _edge_repository() -> EdgeRepository:
    return EdgeRepository(Database.shared("graphql"))


def _edge_service() -> EdgeManagementService:
    database = Database.shared("graphql")
    repository = EdgeRepository(database)
    issuer = EdgeCertificateIssuer(generate_authority())
    try:
        secret_store: EdgeSecretStore | None = EdgeSecretStore(EdgeKeyRing.from_settings())
    except Exception:
        secret_store = None
    return EdgeManagementService(database, repository, issuer, secret_store)


@strawberry.type(description="Administer cloud edge enrollment and engineer grants.")
class Mutation:
    @strawberry.mutation(description="Register a new edge device record for one site.")
    async def register_edge_device(
        self,
        info: strawberry.Info,
        edge_id: str,
        display_name: str = "",
        site_id: str | None = None,
    ) -> EdgeDeviceType:
        require(info, "registerEdgeDevice")
        device = await _edge_repository().register_device(
            edge_id,
            site_id=site_id,
            display_name=display_name or edge_id,
        )
        LOGGER.info("Registered edge device %s", edge_id)
        return EdgeDeviceType.from_device(device)

    @strawberry.mutation(description="Mint a short-lived enrollment token for IT on the DMZ VM.")
    async def create_edge_enrollment_token(self, info: strawberry.Info, edge_id: str) -> str:
        require(info, "createEdgeEnrollmentToken")
        return await _edge_service().create_enrollment_token(edge_id)

    @strawberry.mutation(description="Revoke an edge device and invalidate active leases.")
    async def revoke_edge_device(self, info: strawberry.Info, edge_id: str) -> bool:
        require(info, "revokeEdgeDevice")
        await _edge_repository().revoke_device(edge_id)
        LOGGER.info("Revoked edge device %s", edge_id)
        return True

    @strawberry.mutation(
        description="Assign a legacy connectivity server to one edge for cloud collection."
    )
    async def assign_connectivity_server_to_edge(
        self,
        info: strawberry.Info,
        connection_id: str,
        edge_id: str,
    ) -> str:
        require(info, "assignConnectivityServerToEdge")
        try:
            server = await _edge_repository().assign_legacy(connection_id, edge_id)
        except EdgeRepositoryError as exc:
            raise ValueError(str(exc)) from exc
        LOGGER.info("Assigned connectivity server %s to edge %s", connection_id, edge_id)
        return server.id

    @strawberry.mutation(description="Grant an engineer write access to one edge.")
    async def grant_edge_access(
        self, info: strawberry.Info, edge_id: str, user_id: str
    ) -> bool:
        require(info, "grantEdgeAccess")
        await _edge_repository().grant_user(edge_id, user_id)
        return True

    @strawberry.mutation(description="Remove an engineer's write access to one edge.")
    async def revoke_edge_access(
        self, info: strawberry.Info, edge_id: str, user_id: str
    ) -> bool:
        require(info, "revokeEdgeAccess")
        return await _edge_repository().revoke_user(edge_id, user_id)
