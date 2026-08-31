"""Flatten Historic Event payloads into narrow Metric rows for uns_metrics."""

from __future__ import annotations

from typing import Any

MetricRow = tuple[str, float | None, str | None]


def flatten_payload_to_metrics(payload: Any, prefix: str = "") -> list[MetricRow]:
    """
    Extract every scalar leaf from a payload as a Metric keyed by dotted path.

    Nested dicts recurse; list items use numeric indices in the path.
    """
    if isinstance(payload, dict):
        metrics: list[MetricRow] = []
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            metrics.extend(_flatten_value(value, path))
        return metrics

    if isinstance(payload, list):
        metrics = []
        for index, value in enumerate(payload):
            path = f"{prefix}.{index}" if prefix else str(index)
            metrics.extend(_flatten_value(value, path))
        return metrics

    scalar = _scalar_to_metric(prefix or "value", payload)
    return [scalar] if scalar else []


def _flatten_value(value: Any, path: str) -> list[MetricRow]:
    if isinstance(value, dict):
        metrics: list[MetricRow] = []
        for key, nested in value.items():
            metrics.extend(_flatten_value(nested, f"{path}.{key}"))
        return metrics

    if isinstance(value, list):
        metrics = []
        for index, nested in enumerate(value):
            metrics.extend(_flatten_value(nested, f"{path}.{index}"))
        return metrics

    scalar = _scalar_to_metric(path, value)
    return [scalar] if scalar else []


def _scalar_to_metric(path: str, value: Any) -> MetricRow | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return (path, None, str(value).lower())
    if isinstance(value, (int, float)):
        return (path, float(value), None)
    if isinstance(value, str):
        return (path, None, value)
    return None
