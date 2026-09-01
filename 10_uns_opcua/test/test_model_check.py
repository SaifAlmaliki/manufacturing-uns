"""Unit tests for the Asset Model validation rules."""

import pytest
from uns_opcua.model_check import check_bindings
from uns_opcua.opcua_config import ServerConfig, TagConfig
from uns_opcua.tag_map import build_bindings

ASSET = "CovestroAG/Dormagen/Production/Line1/Cell1/MixerTank"
METRIC_KEY = "ProcessValue/Temperature/value"


def _bindings(*tags: TagConfig):
    return build_bindings(
        ServerConfig(name="plc01", url="opc.tcp://host:4840/", publishing_interval_ms=200, tags=tags)
    )


def _tag(node_id="ns=2;i=5", metric_path="ProcessValue/Temperature", unit=None, asset=ASSET):
    return TagConfig(node_id=node_id, asset=asset, metric_path=metric_path, unit=unit)


def test_a_fully_modelled_tag_reports_nothing():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="°C")),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): "°C"},
    )
    assert issues == []


def test_an_unknown_asset_is_reported():
    issues = check_bindings(
        bindings=_bindings(_tag()),
        known_asset_paths=set(),
        metric_units={},
    )
    kinds = [issue.kind for issue in issues]
    assert "unknown_asset" in kinds
    assert any(ASSET in issue.detail for issue in issues)


def test_a_missing_metric_definition_is_reported():
    issues = check_bindings(
        bindings=_bindings(_tag()),
        known_asset_paths={ASSET},
        metric_units={},
    )
    assert [issue.kind for issue in issues] == ["missing_metric_definition"]
    assert METRIC_KEY in issues[0].detail


def test_a_global_metric_definition_satisfies_the_lookup():
    """A row with asset_id IS NULL gives one unit to every Asset."""
    issues = check_bindings(
        bindings=_bindings(_tag(unit="°C")),
        known_asset_paths={ASSET},
        metric_units={(None, METRIC_KEY): "°C"},
    )
    assert issues == []


def test_an_asset_specific_definition_wins_over_the_global_one():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="K")),
        known_asset_paths={ASSET},
        metric_units={(None, METRIC_KEY): "°C", (ASSET, METRIC_KEY): "K"},
    )
    assert issues == []


def test_a_disagreeing_unit_is_reported():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="K")),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): "°C"},
    )
    assert [issue.kind for issue in issues] == ["unit_mismatch"]
    assert "K" in issues[0].detail
    assert "°C" in issues[0].detail


def test_no_configured_unit_is_not_a_mismatch():
    issues = check_bindings(
        bindings=_bindings(_tag(unit=None)),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): "°C"},
    )
    assert issues == []


def test_a_definition_with_no_unit_of_measure_is_not_a_mismatch():
    issues = check_bindings(
        bindings=_bindings(_tag(unit="°C")),
        known_asset_paths={ASSET},
        metric_units={(ASSET, METRIC_KEY): None},
    )
    assert issues == []


def test_configuration_conflicts_are_reported_too():
    issues = check_bindings(
        bindings=_bindings(
            _tag(node_id="ns=2;i=5", metric_path="ProcessValue/Temperature"),
            _tag(node_id="ns=2;i=5", metric_path="ProcessValue/Pressure"),
        ),
        known_asset_paths={ASSET},
        metric_units={
            (ASSET, METRIC_KEY): None,
            (ASSET, "ProcessValue/Pressure/value"): None,
        },
    )
    assert [issue.kind for issue in issues] == ["config_conflict"]
    assert "duplicate node_id" in issues[0].detail


def test_every_issue_for_one_tag_is_reported_at_once():
    """One pass should tell the whole story, not just the first problem."""
    issues = check_bindings(
        bindings=_bindings(_tag(unit="K")),
        known_asset_paths=set(),
        metric_units={},
    )
    assert {issue.kind for issue in issues} == {"unknown_asset", "missing_metric_definition"}
