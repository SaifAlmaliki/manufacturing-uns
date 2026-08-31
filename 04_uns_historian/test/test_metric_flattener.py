"""Tests for metric flattening into uns_metrics rows."""

from uns_historian.metric_flattener import flatten_payload_to_metrics


def _as_dict(payload):
    return {name: (value_double, value_text) for name, value_double, value_text in flatten_payload_to_metrics(payload)}


def test_flatten_top_level_scalars():
    metrics = _as_dict({"Temperature": 75.2, "status": "running", "enabled": True})
    assert metrics["Temperature"] == (75.2, None)
    assert metrics["status"] == (None, "running")
    assert metrics["enabled"] == (None, "true")


def test_flatten_nested_dict():
    metrics = _as_dict({"sensors": {"Temperature": 80.0, "Pressure": 150}})
    assert metrics["sensors.Temperature"] == (80.0, None)
    assert metrics["sensors.Pressure"] == (150.0, None)


def test_flatten_list_indices():
    metrics = _as_dict({"readings": [10, 20, 30]})
    assert metrics["readings.0"] == (10.0, None)
    assert metrics["readings.1"] == (20.0, None)
    assert metrics["readings.2"] == (30.0, None)


def test_flatten_skips_nulls():
    metrics = _as_dict({"value": None, "count": 5})
    assert "value" not in metrics
    assert metrics["count"] == (5.0, None)


def test_flatten_deeply_nested():
    metrics = _as_dict({"a": {"b": {"c": "leaf"}}})
    assert metrics["a.b.c"] == (None, "leaf")
