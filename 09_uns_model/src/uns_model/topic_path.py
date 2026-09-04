"""
Pure topic-path arithmetic: no database, no I/O.

An Asset's path is a *prefix* of the topics its Metrics are published on. The
simulator publishes

    ManufacturingCo/PlantA/Production/Line1/Cell1/MixerTank/ProcessValue/Temperature

where the Asset is the machine `.../MixerTank` and `ProcessValue/Temperature` is
part of the Metric Key, not part of the Asset Model. Splitting a topic into those
two halves is the whole job of this module, and it is kept separate from Postgres
so it can be tested exhaustively without one.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

SEPARATOR = "/"


@dataclass(frozen=True, slots=True)
class TopicMatch:
    """The result of resolving one topic against known Asset paths."""

    asset_path: str
    """Path of the deepest Asset that is a prefix of the topic."""

    metric_path: str
    """Topic segments below the Asset, joined by `/`. Empty when the topic is the Asset itself."""


def split_topic(topic: str) -> tuple[str, ...]:
    """
    Split a topic into segments, preserving empty ones.

    MQTT permits empty levels (`a//c`), so they are kept rather than discarded.
    """
    if not topic:
        return ()
    return tuple(topic.split(SEPARATOR))


def join_segments(*segments: str) -> str:
    """Join non-empty segments with the topic separator."""
    return SEPARATOR.join(segment for segment in segments if segment)


def validate_segment(name: str) -> str:
    """
    Return `name` if it is a legal single topic segment.

    Rejects empty names and names containing the separator, since either
    would corrupt segment boundaries when joined into a topic.
    """
    if not name:
        raise ValueError(f"segment must be non-empty: {name!r}")
    if SEPARATOR in name:
        raise ValueError(f"segment must not contain {SEPARATOR!r}: {name!r}")
    return name


def ancestor_paths(topic: str) -> list[str]:
    """Every prefix of the topic including the topic itself, deepest first."""
    segments = split_topic(topic)
    return [SEPARATOR.join(segments[:depth]) for depth in range(len(segments), 0, -1)]


def parent_path(topic: str) -> str | None:
    """The topic one level up, or None for a top-level topic."""
    segments = split_topic(topic)
    if len(segments) < 2:
        return None
    return SEPARATOR.join(segments[:-1])


def match_asset_path(topic: str, asset_paths: Collection[str]) -> TopicMatch | None:
    """
    Bind a topic to the deepest Asset whose path is a prefix of it.

    Matching is on whole segments, so `Plant/Line1` does not match
    `Plant/Line10/...`, and case-sensitive, because MQTT topics are. Returns None
    for an Unmodelled Topic.
    """
    candidates = asset_paths if isinstance(asset_paths, (set, frozenset, dict)) else set(asset_paths)
    for candidate in ancestor_paths(topic):
        if candidate in candidates:
            remainder = topic[len(candidate) :].lstrip(SEPARATOR)
            return TopicMatch(asset_path=candidate, metric_path=remainder)
    return None


def metric_key(metric_path: str, metric_name: str) -> str:
    """
    Build a Metric Key from the topic remainder and the payload's dotted path.

    `("ProcessValue/Temperature", "value")` -> `"ProcessValue/Temperature/value"`.
    """
    parts = [part for part in (metric_path, metric_name) if part]
    return SEPARATOR.join(parts)
