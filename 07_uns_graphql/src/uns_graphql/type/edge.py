"""GraphQL types for cloud edge device management."""

from __future__ import annotations

import datetime

import strawberry
from strawberry.scalars import JSON

from uns_model.edge_repository import EdgeDevice, EdgeStatusSnapshot


@strawberry.type(description="One enrolled edge site and its reconciliation lifecycle.")
class EdgeDeviceType:
    edge_id: str
    display_name: str
    site_id: str | None = None
    status: str
    desired_revision: int
    applied_revision: int
    applied_phase: str
    last_seen: datetime.datetime | None = None
    capabilities: JSON | None = None

    @classmethod
    def from_device(
        cls,
        device: EdgeDevice,
        *,
        status: EdgeStatusSnapshot | None = None,
    ) -> EdgeDeviceType:
        snapshot = status
        return cls(
            edge_id=device.edge_id,
            display_name=device.display_name,
            site_id=device.site_id,
            status=device.status,
            desired_revision=snapshot.desired_revision if snapshot else device.desired_head_revision,
            applied_revision=snapshot.applied_revision if snapshot else device.latest_applied_revision,
            applied_phase=snapshot.applied_phase if snapshot else device.latest_applied_phase,
            last_seen=snapshot.last_seen if snapshot else None,
            capabilities=snapshot.capabilities if snapshot else None,
        )
