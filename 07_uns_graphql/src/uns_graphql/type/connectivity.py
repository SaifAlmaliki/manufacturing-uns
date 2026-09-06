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
from typing import TypeVar

import strawberry
from sqlalchemy import inspect as sa_inspect
from strawberry.scalars import JSON
from uns_model.tables import ConnectivityServer, ConnectivityTag

# The single protocol the catalog allows today. Spelled out as an enum so adding
# a second protocol is a schema change a reviewer sees, not a string a typo can
# slip past a CHECK constraint unnoticed.
_OPC_UA_PROTOCOL = "opc_ua"

_E = TypeVar("_E", bound=Enum)


@strawberry.enum(description="A connectivity protocol the console can author a server for.")
class ConnectivityProtocol(Enum):
    OPC_UA = _OPC_UA_PROTOCOL


@strawberry.enum(description="How the console authenticates to an OPC UA server.")
class ConnectivityAuthMode(Enum):
    ANONYMOUS = "anonymous"
    USERNAME = "username"
    X509 = "x509"


@strawberry.enum(description="OPC UA channel security policy.")
class ConnectivitySecurityPolicy(Enum):
    NONE = "None"
    BASIC256_SHA256 = "Basic256Sha256"
    AES128_SHA256_RSA_OAEP = "Aes128Sha256RsaOaep"
    AES256_SHA256_RSA_PSS = "Aes256Sha256RsaPss"


@strawberry.enum(description="OPC UA channel security mode.")
class ConnectivitySecurityMode(Enum):
    NONE = "None"
    SIGN = "Sign"
    SIGN_AND_ENCRYPT = "SignAndEncrypt"


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


@strawberry.enum(description="What kind of plant signal a subscribed tag represents.")
class SignalSemanticClass(Enum):
    MeasuredValue = "MeasuredValue"
    EnergyConsumption = "EnergyConsumption"
    CounterOK = "CounterOK"
    CounterNOK = "CounterNOK"
    State = "State"


@strawberry.enum(description="The scalar type Condition Monitoring should chart for a tag.")
class SignalDataType(Enum):
    Double = "Double"
    Boolean = "Boolean"
    Integer = "Integer"
    String = "String"


def _optional_enum(enum_cls: type[_E], value: str | None) -> _E | None:
    if value is None or value == "":
        return None
    return enum_cls(value)


def _loaded_asset(tag: object) -> object | None:
    """Return `tag.asset` only when already present — never lazy-load.

    `getattr(tag, "asset")` on a mapped `ConnectivityTag` always finds the
    relationship and will emit a load. On a detached instance whose Asset was
    not eager-loaded that raises `DetachedInstanceError`. Test doubles
    (`SimpleNamespace`) are not mapped, so `inspect` returns None and we
    read `.asset` as a normal attribute.
    """
    state = sa_inspect(tag, raiseerr=False)
    if state is None:
        return getattr(tag, "asset", None)
    if "asset" in state.unloaded:
        return None
    return getattr(tag, "asset", None)


@strawberry.type(description="A Unit of Measure the console can attach to a subscribed tag.")
class UnitOfMeasureType:
    symbol: str
    name: str | None = None


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
    asset_id: int | None = None
    asset_path: str | None = None
    asset_display_name: str | None = None
    unit_of_measure: str | None = None
    semantic_class: SignalSemanticClass | None = None
    data_type: SignalDataType | None = None
    labels: list[str] = strawberry.field(default_factory=list)

    @classmethod
    def from_tag(cls, tag: ConnectivityTag) -> "ConnectivityTagType":
        asset = _loaded_asset(tag)
        return cls(
            server_id=tag.server_id,
            node_id=tag.node_id,
            browse_path=tag.browse_path,
            display_name=tag.display_name,
            mqtt_topic=tag.mqtt_topic,
            subscribed=tag.subscribed,
            created_at=tag.created_at,
            updated_at=tag.updated_at,
            asset_id=getattr(tag, "asset_id", None),
            asset_path=getattr(asset, "path", None) if asset is not None else None,
            asset_display_name=(
                getattr(asset, "name", None)
                or getattr(asset, "display_name", None)
                or getattr(asset, "segment", None)
            )
            if asset is not None
            else None,
            unit_of_measure=getattr(tag, "unit_of_measure", None),
            semantic_class=_optional_enum(SignalSemanticClass, getattr(tag, "semantic_class", None)),
            data_type=_optional_enum(SignalDataType, getattr(tag, "data_type", None)),
            labels=list(getattr(tag, "labels", None) or []),
        )


@strawberry.type(description="A subscribed catalog tag, named by the server it belongs to.")
class SubscribedSignalType(ConnectivityTagType):
    server_name: str

    @classmethod
    def from_tag(cls, tag: ConnectivityTag, *, server_name: str) -> "SubscribedSignalType":
        base = ConnectivityTagType.from_tag(tag)
        return cls(
            server_id=base.server_id,
            node_id=base.node_id,
            browse_path=base.browse_path,
            display_name=base.display_name,
            mqtt_topic=base.mqtt_topic,
            subscribed=base.subscribed,
            created_at=base.created_at,
            updated_at=base.updated_at,
            asset_id=base.asset_id,
            asset_path=base.asset_path,
            asset_display_name=base.asset_display_name,
            unit_of_measure=base.unit_of_measure,
            semantic_class=base.semantic_class,
            data_type=base.data_type,
            labels=base.labels,
            server_name=server_name,
        )


@strawberry.type(description="An OPC UA server the console dials, with its subscribed tags.")
class ConnectivityServerType:
    id: str
    name: str
    protocol: ConnectivityProtocol
    endpoint: str
    auth_mode: ConnectivityAuthMode
    username: str
    has_password: bool
    security_policy: ConnectivitySecurityPolicy
    security_mode: ConnectivitySecurityMode
    certificate: str
    has_private_key: bool
    server_certificate: str
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
            auth_mode=ConnectivityAuthMode(getattr(server, "auth_mode", None) or "anonymous"),
            username=getattr(server, "username", None) or "",
            has_password=bool(getattr(server, "password", None)),
            security_policy=ConnectivitySecurityPolicy(
                getattr(server, "security_policy", None) or "None"
            ),
            security_mode=ConnectivitySecurityMode(getattr(server, "security_mode", None) or "None"),
            certificate=getattr(server, "certificate", None) or "",
            has_private_key=bool(getattr(server, "private_key", None)),
            server_certificate=getattr(server, "server_certificate", None) or "",
            last_status=server.last_status,
            last_error=server.last_error,
            last_tested_at=server.last_tested_at,
            created_at=server.created_at,
            updated_at=server.updated_at,
            tags=[ConnectivityTagType.from_tag(tag) for tag in server.tags],
        )
