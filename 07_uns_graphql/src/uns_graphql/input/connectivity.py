"""Input object for authoring a Connectivity server.

A whole server at a time, mirroring `input/alert_rule.py`: the console edits a
server in a form and saves it, and there is no safe meaning for "update just the
endpoint of a server whose name and protocol I have not read".
"""

from __future__ import annotations

import strawberry

from uns_graphql.type.connectivity import (
    ConnectivityAuthMode,
    ConnectivityProtocol,
    ConnectivitySecurityMode,
    ConnectivitySecurityPolicy,
    SignalDataType,
    SignalSemanticClass,
)


@strawberry.input(description="A Connectivity server to create or replace. The id is supplied by the console.")
class ConnectivityServerInput:
    id: str
    name: str
    protocol: ConnectivityProtocol
    endpoint: str
    auth_mode: ConnectivityAuthMode = ConnectivityAuthMode.ANONYMOUS
    security_policy: ConnectivitySecurityPolicy = ConnectivitySecurityPolicy.NONE
    security_mode: ConnectivitySecurityMode = ConnectivitySecurityMode.NONE
    username: str = ""
    password: str = ""
    certificate: str = ""
    private_key: str = ""
    server_certificate: str = ""


@strawberry.input(description="Partial update of one Connectivity tag's engineer-authored context.")
class ConnectivityTagUpdateInput:
    display_name: str | None = strawberry.UNSET
    mqtt_topic: str | None = strawberry.UNSET
    asset_id: int | None = strawberry.UNSET
    unit_of_measure: str | None = strawberry.UNSET
    semantic_class: SignalSemanticClass | None = strawberry.UNSET
    data_type: SignalDataType | None = strawberry.UNSET
    labels: list[str] | None = strawberry.UNSET
