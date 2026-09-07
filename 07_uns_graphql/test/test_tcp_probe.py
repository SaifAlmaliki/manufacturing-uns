"""probe_tcp: a bare TCP connect check for S7/EtherNet-IP servers, which have no
application-layer handshake the console can read a server node from the way
OPC UA's test_connection does.
"""

from unittest.mock import patch

from uns_graphql.tcp_probe import probe_tcp


def test_probe_tcp_ok():
    with patch("uns_graphql.tcp_probe.socket.create_connection") as conn:
        conn.return_value.__enter__.return_value = object()
        ok, err = probe_tcp("10.0.0.1", 102)
    assert ok is True
    assert err is None


def test_probe_tcp_refused():
    with patch(
        "uns_graphql.tcp_probe.socket.create_connection",
        side_effect=ConnectionRefusedError("refused"),
    ):
        ok, err = probe_tcp("10.0.0.1", 102)
    assert ok is False
    assert "refused" in (err or "").lower() or err
