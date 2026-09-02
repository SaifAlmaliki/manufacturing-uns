"""Tests for the OEE module's configuration reader."""

from uns_oee.oee_config import OeeConfig


def test_defaults_match_the_documented_platform_ports():
    config = OeeConfig(mqtt_host="localhost")
    assert config.metrics_port == 9095
    assert config.settle_minutes == 15
    assert config.late_window_hours == 48
    assert config.backfill_days == 30
    assert config.mqtt_client_id == "uns_oee_client"
    assert config.metrics_table == "uns_metrics"


def test_is_valid_requires_an_mqtt_host():
    assert OeeConfig(mqtt_host="localhost").is_valid()
    assert not OeeConfig(mqtt_host=None).is_valid()


def test_from_settings_reads_the_oee_environment():
    config = OeeConfig.from_settings("oee")
    assert config.metrics_port == 9095
    assert config.mqtt_client_id == "uns_oee_client"
    assert config.scan_interval_seconds == 300


def test_from_settings_reuses_the_platforms_shared_broker_settings():
    config = OeeConfig.from_settings("oee")
    assert config.mqtt_host == "localhost"
    assert config.mqtt_port == 1883
    assert config.mqtt_keep_alive == 60
    assert config.mqtt_version == 5
    assert config.mqtt_transport == "tcp"
