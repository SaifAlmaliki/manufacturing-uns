"""GraphQL types for the console's Connectivity catalog and OPC UA probes.

The enums are spelled out rather than generated from `uns_model.tables`, mirroring
`type/alert_rule.py`: a GraphQL schema is a published contract, and a generated
enum changes shape without review. The OPC UA row types mirror
`uns_opcua.browse.BrowseNode` / `DataValueRow` so the bridge and the console
agree on shape without sharing a class.
"""

from __future__ import annotations

import datetime
from enum import Enum

import strawberry
from strawberry.scalars import JSON
from uns_model.tables import ConnectivityServer, ConnectivityTag

# The single protocol the catalog allows today. Spelled out as an enum so adding
# a second protocol is a schema change a reviewer sees, not a string a typo can
# slip past a CHECK constraint unnoticed.
_OPC_UA_PROTOCOL = "opc_ua"


@strawberry.enum(description="A connectivity protocol the console can author a server for.")
class ConnectivityProtocol(Enum):
    OPC_UA = _OPC_UA_PROTOCOL


@strawberry.type(description="An OPC UA node the console browsed or discovered.")
class OpcUaBrowseNodeType:
    node_id: str
    browse_name: str
    display_name: str
    browse_path: str
    node_class: str
    has_children: bool

    @classmethod
    def from_browse(cls, row) -> "OpcUaBrowseNodeType":
        return cls(
            node_id=row.node_id,
            browse_name=row.browse_name,
            display_name=row.display_name,
            browse_path=row.browse_path,
            node_class=row.node_class,
            has_children=row.has_children,
        )


@strawberry.type(description="One OPC UA node's current value as read from the server.")
class OpcUaDataValueType:
    node_id: str
    display_name: str
    browse_path: str
    value: JSON = strawberry.field(description="The current value as a JSON scalar")
    data_type: str | None = None
    source_timestamp: datetime.datetime | None = None
    server_timestamp: datetime.datetime | None = None
    status: str

    @classmethod
    def from_row(cls, row) -> "OpcUaDataValueType":
        return cls(
            node_id=row.node_id,
            display_name=row.display_name,
            browse_path=row.browse_path,
            value=row.value,
            data_type=row.data_type,
            source_timestamp=row.source_timestamp,
            server_timestamp=row.server_timestamp,
            status=row.status,
        )


@strawberry.type(description="The outcome of a connection probe against one OPC UA endpoint.")
class ConnectivityTestResultType:
    ok: bool
    error: str | None = None
    elapsed_ms: float


@strawberry.type(description="One OPC UA node the console subscribes to.")
class ConnectivityTagType:
    server_id: str
    node_id: str
    browse_path: str
    display_name: str
    mqtt_topic: str
    subscribed: bool
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    @classmethod
    def from_tag(cls, tag: ConnectivityTag) -> "ConnectivityTagType":
        return cls(
            server_id=tag.server_id,
            node_id=tag.node_id,
            browse_path=tag.browse_path,
            display_name=tag.display_name,
            mqtt_topic=tag.mqtt_topic,
            subscribed=tag.subscribed,
            created_at=tag.created_at,
            updated_at=tag.updated_at,
        )


@strawberry.type(description="An OPC UA server the console dials, with its subscribed tags.")
class ConnectivityServerType:
    id: str
    name: str
    protocol: ConnectivityProtocol
    endpoint: str
    last_status: str
    last_error: str
    last_tested_at: datetime.datetime | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    tags: list[ConnectivityTagType] = strawberry.field(default_factory=list)

    @classmethod
    def from_server(cls, server: ConnectivityServer) -> "ConnectivityServerType":
        return cls(
            id=server.id,
            name=server.name,
            protocol=ConnectivityProtocol(server.protocol),
            endpoint=server.endpoint,
            last_status=server.last_status,
            last_error=server.last_error,
            last_tested_at=server.last_tested_at,
            created_at=server.created_at,
            updated_at=server.updated_at,
            tags=[ConnectivityTagType.from_tag(tag) for tag in server.tags],
        )
