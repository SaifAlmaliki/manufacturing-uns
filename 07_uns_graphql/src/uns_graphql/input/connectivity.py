"""Input object for authoring a Connectivity server.

A whole server at a time, mirroring `input/alert_rule.py`: the console edits a
server in a form and saves it, and there is no safe meaning for "update just the
endpoint of a server whose name and protocol I have not read".
"""

from __future__ import annotations

import strawberry

from uns_graphql.type.connectivity import ConnectivityProtocol


@strawberry.input(description="A Connectivity server to create or replace. The id is supplied by the console.")
class ConnectivityServerInput:
    id: str
    name: str
    protocol: ConnectivityProtocol
    endpoint: str
