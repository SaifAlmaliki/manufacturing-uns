"""Unit tests for topic path matching. No database involved."""

import pytest

from uns_model.topic_path import (
    ancestor_paths,
    match_asset_path,
    metric_key,
    parent_path,
    split_topic,
)

SIMULATOR_TOPIC = "ManufacturingCo/PlantA/Production/Line1/Cell1/MixerTank/ProcessValue/Temperature"


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("a", ("a",)),
        ("a/b/c", ("a", "b", "c")),
        ("a//c", ("a", "", "c")),
        ("", ()),
    ],
)
def test_split_topic(topic: str, expected: tuple[str, ...]):
    assert split_topic(topic) == expected


def test_ancestor_paths_is_longest_first_and_includes_the_topic_itself():
    assert ancestor_paths("a/b/c") == ["a/b/c", "a/b", "a"]


def test_ancestor_paths_of_empty_topic_is_empty():
    assert ancestor_paths("") == []


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("a/b/c", "a/b"),
        ("a", None),
        ("", None),
    ],
)
def test_parent_path(topic: str, expected: str | None):
    assert parent_path(topic) == expected


def test_match_returns_the_longest_asset_path_and_the_remainder_as_metric_path():
    asset_paths = {
        "ManufacturingCo",
        "ManufacturingCo/PlantA",
        "ManufacturingCo/PlantA/Production/Line1/Cell1/MixerTank",
    }

    match = match_asset_path(SIMULATOR_TOPIC, asset_paths)

    assert match is not None
    assert match.asset_path == "ManufacturingCo/PlantA/Production/Line1/Cell1/MixerTank"
    assert match.metric_path == "ProcessValue/Temperature"


def test_match_of_an_asset_path_itself_has_an_empty_metric_path():
    match = match_asset_path("a/b", {"a/b"})

    assert match is not None
    assert match.asset_path == "a/b"
    assert match.metric_path == ""


def test_match_respects_segment_boundaries():
    """Line10 must not be enriched as Line1."""
    assert match_asset_path("Plant/Line10/Temp", {"Plant/Line1"}) is None


def test_match_of_an_unmodelled_topic_is_none():
    assert match_asset_path("Other/Plant/Sensor", {"ManufacturingCo/PlantA"}) is None


def test_a_topic_still_matches_a_remaining_enterprise_after_its_site_is_gone():
    """Deleting a Site does not make the topic Unmodelled while the Enterprise remains."""
    topic = "PyTestUNS/Plant1/Area1/Line1/Cell1/Mixer1/ProcessValue/Temperature"

    match = match_asset_path(topic, {"PyTestUNS"})

    assert match is not None
    assert match.asset_path == "PyTestUNS"
    assert match.metric_path == "Plant1/Area1/Line1/Cell1/Mixer1/ProcessValue/Temperature"


def test_match_is_case_sensitive_because_mqtt_topics_are():
    assert match_asset_path("planta/Line1", {"PlantA"}) is None
    assert match_asset_path("PlantA/Line1", {"PlantA"}) is not None


@pytest.mark.parametrize(
    ("metric_path", "metric_name", "expected"),
    [
        ("ProcessValue/Temperature", "value", "ProcessValue/Temperature/value"),
        ("", "value", "value"),
        ("ProcessValue/Temperature", "sensor.reading", "ProcessValue/Temperature/sensor.reading"),
        ("ProcessValue/Temperature", "", "ProcessValue/Temperature"),
    ],
)
def test_metric_key_joins_topic_remainder_and_payload_path(metric_path: str, metric_name: str, expected: str):
    assert metric_key(metric_path, metric_name) == expected
