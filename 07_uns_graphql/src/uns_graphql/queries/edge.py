"""GraphQL queries for cloud edge devices."""

from __future__ import annotations

import strawberry
from uns_model.edge_repository import EdgeRepository
from uns_model.engine import Database

from uns_graphql.auth.require import require_role
from uns_graphql.type.edge import EdgeDeviceType

EDGE_READ_ROLES = frozenset({"engineer", "admin"})


def _edge_repository() -> EdgeRepository:
    return EdgeRepository(Database.shared("graphql"))


@strawberry.type(description="Query enrolled edge devices and their lifecycle state.")
class Query:
    @strawberry.field(description="Every registered edge device visible to the caller.")
    async def get_edge_devices(self, info: strawberry.Info) -> list[EdgeDeviceType]:
        require_role(info, EDGE_READ_ROLES)
        repo = _edge_repository()
        devices = await repo.list_devices()
        rows: list[EdgeDeviceType] = []
        for device in devices:
            status = await repo.device_status(device.edge_id)
            rows.append(EdgeDeviceType.from_device(device, status=status))
        return rows

    @strawberry.field(description="One edge device by id.")
    async def get_edge_device(self, info: strawberry.Info, edge_id: str) -> EdgeDeviceType | None:
        require_role(info, EDGE_READ_ROLES)
        repo = _edge_repository()
        device = await repo.get_device(edge_id)
        if device is None:
            return None
        status = await repo.device_status(edge_id)
        return EdgeDeviceType.from_device(device, status=status)
