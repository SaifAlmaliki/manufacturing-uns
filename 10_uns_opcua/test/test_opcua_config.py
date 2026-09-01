"""Unit tests for the OPC UA connector's configuration parsing."""

import pytest
from uns_opcua.opcua_config import (
    Deadband,
    parse_deadband,
    parse_security,
    parse_server,
    parse_spool,
    parse_tag,
)


def test_parse_tag_strips_slashes_and_defaults_metric_path():
    tag = parse_tag({"node_id": "ns=2;s=Mixer.Temp_PV", "asset": "/Ent/Site/Line1/Mixer/"})
    assert tag.node_id == "ns=2;s=Mixer.Temp_PV"
    assert tag.asset == "Ent/Site/Line1/Mixer"
    assert tag.metric_path == ""
    assert tag.unit is None
    assert tag.deadband is None


def test_parse_tag_requires_node_id_and_asset():
    with pytest.raises(ValueError, match="node_id"):
        parse_tag({"asset": "Ent/Site"})
    with pytest.raises(ValueError, match="asset"):
        parse_tag({"node_id": "ns=2;i=5"})


def test_parse_tag_rejects_slash_only_asset():
    with pytest.raises(ValueError, match="asset"):
        parse_tag({"node_id": "ns=2;i=5", "asset": "/"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ({}, None),
        ({"type": "none"}, None),
        ({"type": "absolute", "value": 0.2}, Deadband(type="absolute", value=0.2)),
        ({"type": "Percent", "value": 1}, Deadband(type="percent", value=1.0)),
    ],
)
def test_parse_deadband(raw, expected):
    assert parse_deadband(raw) == expected


def test_parse_deadband_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unsupported deadband type"):
        parse_deadband({"type": "sigma", "value": 3})


def test_parse_deadband_requires_value():
    with pytest.raises(ValueError, match="value"):
        parse_deadband({"type": "absolute"})


def test_security_string_matches_asyncua_format():
    security = parse_security(
        {
            "policy": "Basic256Sha256",
            "mode": "SignAndEncrypt",
            "certificate": "/certs/client.der",
            "private_key": "/certs/client.key",
            "server_certificate": "/certs/server.der",
        }
    )
    assert security.to_security_string() == (
        "Basic256Sha256,SignAndEncrypt,/certs/client.der,/certs/client.key,/certs/server.der"
    )


def test_security_string_omits_absent_server_certificate():
    security = parse_security(
        {
            "policy": "Basic256Sha256",
            "mode": "Sign",
            "certificate": "/certs/client.der",
            "private_key": "/certs/client.key",
        }
    )
    assert security.to_security_string() == "Basic256Sha256,Sign,/certs/client.der,/certs/client.key"


def test_parse_security_reports_every_missing_field():
    with pytest.raises(ValueError, match="certificate, private_key"):
        parse_security({"policy": "Basic256Sha256", "mode": "Sign"})


def test_parse_server_defaults_publishing_interval():
    server = parse_server(
        {
            "name": "plc01",
            "url": "opc.tcp://10.4.2.11:4840/",
            "tags": [{"node_id": "ns=2;i=5", "asset": "Ent/Site", "metric_path": "ProcessValue/Temperature"}],
        }
    )
    assert server.publishing_interval_ms == 200
    assert server.security is None
    assert len(server.tags) == 1


def test_parse_server_rejects_a_server_with_no_tags():
    with pytest.raises(ValueError, match="no tags"):
        parse_server({"name": "plc01", "url": "opc.tcp://host:4840/", "tags": []})


def test_parse_spool_defaults_and_normalises_synchronous():
    spool = parse_spool({"synchronous": "full"})
    assert spool.synchronous == "FULL"
    assert spool.path == "/var/lib/uns_opcua/spool.db"
    assert spool.max_rows == 5_000_000
    assert spool.max_bytes == 2_000_000_000
    assert spool.max_age_hours == 168


def test_parse_spool_rejects_unknown_synchronous_mode():
    with pytest.raises(ValueError, match="synchronous"):
        parse_spool({"synchronous": "SOMETIMES"})
