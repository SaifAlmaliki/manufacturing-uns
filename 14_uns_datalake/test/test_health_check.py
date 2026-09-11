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


def test_liveness_ignores_readiness_failures():
    datalake_health.touch_heartbeat(100.0)
    datalake_health.set_consumer_ready(False)
    datalake_health.set_replay_failure("data_gap")
    datalake_health.set_integrity_failure(True)
    assert datalake_health.is_live(120.0)
    assert not datalake_health.is_ready(120.0)


def test_readiness_requires_consumer_assignment_and_no_failures():
    datalake_health.touch_heartbeat(100.0)
    datalake_health.set_consumer_ready(True)
    datalake_health.set_replay_failure(None)
    datalake_health.set_integrity_failure(False)
    assert datalake_health.is_ready(120.0)

    datalake_health.set_replay_failure("offset_out_of_range")
    assert not datalake_health.is_ready(120.0)

    datalake_health.set_replay_failure(None)
    datalake_health.set_integrity_failure(True)
    assert not datalake_health.is_ready(120.0)
