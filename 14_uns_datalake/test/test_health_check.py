"""Health check tests."""

from uns_datalake import health_check as datalake_health


def test_heartbeat_freshness():
    datalake_health.touch_heartbeat(100.0)
    assert datalake_health.heartbeat_is_fresh(120.0)
    assert not datalake_health.heartbeat_is_fresh(200.0)


def test_consumer_ready_flag():
    datalake_health.set_consumer_ready(True)
    assert datalake_health.is_consumer_ready()
    datalake_health.set_consumer_ready(False)
    assert not datalake_health.is_consumer_ready()
