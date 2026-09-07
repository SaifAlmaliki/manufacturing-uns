"""A bare TCP connect check for S7 / EtherNet-IP servers.

Unlike OPC UA, S7 and EtherNet/IP have no shared application-layer handshake this
service can dial without a protocol-specific client library (which lives in HiveMQ
Edge, not here). A TCP connect is the cheapest signal the console can show an
engineer: "something is listening on that host:port" — not a promise the protocol
adapter itself will connect.
"""

from __future__ import annotations

import socket


def probe_tcp(host: str, port: int, timeout_s: float = 3.0) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True, None
    except OSError as exc:
        return False, str(exc)
