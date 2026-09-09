"""Flatten Historic Event payloads into narrow Metric rows for uns_metrics."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

MetricRow = tuple[str, float | None, str | None]


class MetricExpansionLimitError(ValueError):
    """Scalar expansion exceeded the configured row budget."""


def flatten_payload_to_metrics(payload: Any, prefix: str = "") -> list[MetricRow]:
    """
    Extract every scalar leaf from a payload as a Metric keyed by dotted path.

    Nested dicts recurse; list items use numeric indices in the path.
    """
    return list(iter_payload_metrics(payload, prefix=prefix))


def iter_payload_metrics(payload: Any, prefix: str = "", *, limit: int | None = None) -> Iterator[MetricRow]:
    """Yield scalar metrics without materializing the full expansion first."""
    emitted = 0
    for metric in _iter_metrics(payload, prefix):
        if limit is not None and emitted >= limit:
            raise MetricExpansionLimitError(f"metric expansion exceeds limit of {limit}")
        emitted += 1
        yield metric


def _iter_metrics(payload: Any, prefix: str) -> Iterator[MetricRow]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _iter_value(value, path)
        return

    if isinstance(payload, list):
        for index, value in enumerate(payload):
            path = f"{prefix}.{index}" if prefix else str(index)
            yield from _iter_value(value, path)
        return

    scalar = _scalar_to_metric(prefix or "value", payload)
    if scalar is not None:
        yield scalar


def _iter_value(value: Any, path: str) -> Iterator[MetricRow]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _iter_value(nested, f"{path}.{key}")
        return

    if isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _iter_value(nested, f"{path}.{index}")
        return

    scalar = _scalar_to_metric(path, value)
    if scalar is not None:
        yield scalar


def _flatten_value(value: Any, path: str) -> list[MetricRow]:
    return list(_iter_value(value, path))


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
