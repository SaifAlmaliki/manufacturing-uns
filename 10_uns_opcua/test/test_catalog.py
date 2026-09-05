"""`servers_from_catalog`: the pure fold from Connectivity catalog specs to ServerConfig."""

from uns_model.connectivity import ConnectivityServerSpec, ConnectivityTagSpec
from uns_opcua.catalog import servers_from_catalog


def test_catalog_row_becomes_server_config_with_mqtt_topic():
    servers = [ConnectivityServerSpec("s1", "opcplc", "opc_ua", "opc.tcp://desktop-h4hdql2:50000/")]
    tags = {"s1": [ConnectivityTagSpec("ns=3;s=WTP_T101_Level", "RawWater/T101/Level", "Level", "RawWater/T101/Level", True)]}
    configs = servers_from_catalog(servers, tags)
    assert configs[0].url == "opc.tcp://desktop-h4hdql2:50000/"
    assert configs[0].tags[0].mqtt_topic == "RawWater/T101/Level"


def test_unsubscribed_tags_are_filtered_out():
    servers = [ConnectivityServerSpec("s1", "opcplc", "opc_ua", "opc.tcp://host:4840/")]
    tags = {
        "s1": [
            ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True),
            ConnectivityTagSpec("ns=3;s=B", "Path/B", "B", "Plant/B", False),
        ]
    }
    configs = servers_from_catalog(servers, tags)
    assert len(configs) == 1
    assert [tag.node_id for tag in configs[0].tags] == ["ns=3;s=A"]


def test_server_with_zero_subscribed_tags_is_skipped():
    servers = [
        ConnectivityServerSpec("s1", "opcplc", "opc_ua", "opc.tcp://host:4840/"),
        ConnectivityServerSpec("s2", "plc2", "opc_ua", "opc.tcp://host:4841/"),
    ]
    tags = {
        "s1": [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)],
        "s2": [ConnectivityTagSpec("ns=3;s=B", "Path/B", "B", "Plant/B", False)],
    }
    configs = servers_from_catalog(servers, tags)
    assert [server.name for server in configs] == ["opcplc"]


def test_server_missing_from_tags_map_is_skipped():
    """A catalog server with no entry in tags_by_server_id is not a collector to run."""
    servers = [ConnectivityServerSpec("s1", "opcplc", "opc_ua", "opc.tcp://host:4840/")]
    configs = servers_from_catalog(servers, {})
    assert configs == ()


def test_tag_uses_mqtt_topic_as_asset_and_metric_path_is_empty():
    servers = [ConnectivityServerSpec("s1", "opcplc", "opc_ua", "opc.tcp://host:4840/")]
    tags = {"s1": [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/Area/Line/Level", True)]}
    configs = servers_from_catalog(servers, tags)
    tag = configs[0].tags[0]
    assert tag.asset == "Plant/Area/Line/Level"
    assert tag.metric_path == ""
    assert tag.mqtt_topic == "Plant/Area/Line/Level"
    assert tag.node_id == "ns=3;s=A"
