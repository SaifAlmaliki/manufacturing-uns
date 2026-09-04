import pytest

from uns_simulator.models import expand_hierarchy_paths
from uns_simulator.profiles import (
    FAMILIES,
    TIER_DEFAULTS,
    build_plant_context,
    filter_paths,
    load_profile,
)

# Minimal WTP hierarchy: one enterprise, one site, one production area, one train, one cell.
# Spec 7.2's profile keys narrow this; `load_profile` tests that do not touch disk still work.
HIERARCHY = {
    "enterprise": "AcmeWater",
    "sites": [
        {
            "name": "Site1",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "nameplate_tph": 12.0, "cells": ["V101"]}],
                },
            ],
        },
    ],
}

RAW = {
    "hierarchy": HIERARCHY,
    "plant": {},
    "wtp": {"devices": []},
    "profiles": {
        "wtp": {"tier_scale": 1.0, "sites": ["Site1"], "families": ["wtp"]},
    },
    "simulation": {"seed": 1234, "tiers": {"process": 4.0}},
}

ALL_PATHS = expand_hierarchy_paths(HIERARCHY)


def test_tier_defaults_cover_every_documented_tier():
    assert set(TIER_DEFAULTS) == {"fast", "process", "energy", "status", "meter", "lab", "event"}
    assert TIER_DEFAULTS["fast"] == 1.0
    assert TIER_DEFAULTS["meter"] == 900.0
    assert TIER_DEFAULTS["event"] == 0.0


def test_families_is_just_wtp():
    assert FAMILIES == ("wtp",)


def test_filter_paths_without_filters_keeps_everything():
    assert filter_paths(ALL_PATHS) == list(ALL_PATHS)


def test_filter_paths_keeps_only_the_named_sites():
    # Only one site in the minimal hierarchy; naming it keeps everything.
    kept = filter_paths(ALL_PATHS, sites=["Site1"])
    assert {path.site for path in kept} == {"Site1"}


def test_filter_paths_naming_a_site_that_does_not_exist_is_rejected():
    with pytest.raises(ValueError, match="Nowhere"):
        filter_paths(ALL_PATHS, sites=["Site1", "Nowhere"])


def test_build_plant_context_creates_a_site_state():
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    assert set(context.sites) == {"Site1"}
    assert context.enterprise == "AcmeWater"


def test_wtp_profile_loads_with_the_single_family_enabled():
    profile = load_profile(RAW, "wtp")
    assert profile.name == "wtp"
    assert profile.seed == 1234
    assert profile.families == {"wtp": True}
    assert profile.sites == ("Site1",)
    assert profile.devices == ()


def test_wtp_profile_reports_zero_devices_with_a_warning():
    report = load_profile(RAW, "wtp").report
    assert report.devices == 0
    assert report.signals == 0
    assert report.per_family == {}
    assert report.per_tier == {}
    assert report.serves_links == 0
    assert any("zero devices" in w for w in report.warnings)
    assert report.as_dict()["devices"] == report.devices


def test_report_records_a_template_that_matched_nothing():
    raw = {**RAW, "wtp": {"devices": [{"id": "GHOST", "equipment": "E", "target": {"site": "Nowhere"}, "signals": {}}]}}
    assert "GHOST" in " ".join(load_profile(raw, "wtp").report.unmatched_templates)


def test_unknown_profile_name_is_rejected_by_name():
    with pytest.raises(ValueError, match="tiny"):
        load_profile(RAW, "tiny")


def test_unknown_family_in_a_profile_is_rejected_by_name():
    raw = {**RAW, "profiles": {**RAW["profiles"], "wtp": {"families": ["energy"]}}}
    with pytest.raises(ValueError, match="energy"):
        load_profile(raw, "wtp")


def test_a_families_mapping_instead_of_a_list_is_rejected():
    raw = {**RAW, "profiles": {**RAW["profiles"], "wtp": {"families": {"wtp": True}}}}
    with pytest.raises(ValueError, match="families"):
        load_profile(raw, "wtp")


def test_negative_tier_interval_is_rejected_by_name():
    raw = {**RAW, "simulation": {**RAW["simulation"], "tiers": {"process": -1.0}}}
    with pytest.raises(ValueError, match="process"):
        load_profile(raw, "wtp")


def test_unknown_tier_name_is_rejected_by_name():
    raw = {**RAW, "simulation": {**RAW["simulation"], "tiers": {"turbo": 1.0}}}
    with pytest.raises(ValueError, match="turbo"):
        load_profile(raw, "wtp")


def test_a_non_positive_tier_scale_is_rejected():
    raw = {**RAW, "profiles": {**RAW["profiles"], "wtp": {"tier_scale": 0.0, "families": ["wtp"]}}}
    with pytest.raises(ValueError, match="tier_scale"):
        load_profile(raw, "wtp")


def test_tier_scale_defaults_to_one():
    raw = {**RAW, "profiles": {**RAW["profiles"], "wtp": {"families": ["wtp"]}}}
    profile = load_profile(raw, "wtp")
    assert profile.tier_scale == 1.0
    assert profile.tiers["fast"] == TIER_DEFAULTS["fast"]


def test_tier_overrides_come_from_simulation_tiers():
    profile = load_profile(RAW, "wtp")
    assert profile.tiers["process"] == 4.0
    assert profile.tiers["meter"] == TIER_DEFAULTS["meter"]


def test_explicit_seed_overrides_the_configured_one():
    assert load_profile(RAW, "wtp", seed=99).seed == 99


def test_a_legacy_flat_interval_becomes_the_process_tier():
    """Spec 12: settings.yaml today has `simulation.interval: 5.0` and no `tiers` block."""
    raw = {**RAW, "simulation": {"seed": 1, "interval": 20.0}}
    profile = load_profile(raw, "wtp")
    assert profile.tiers["process"] == 20.0
    assert profile.tiers["fast"] == TIER_DEFAULTS["fast"]


def test_an_explicit_tiers_block_wins_over_the_legacy_interval():
    raw = {**RAW, "simulation": {"seed": 1, "interval": 20.0, "tiers": {"process": 3.0}}}
    assert load_profile(raw, "wtp").tiers["process"] == 3.0


def test_an_unknown_signal_tier_is_rejected_by_name():
    raw = {
        **RAW,
        "wtp": {"devices": [{"id": "F", "equipment": "M", "signals": {"Flow": {"unit": "m3/h", "tier": "hyper"}}}]},
    }
    with pytest.raises(ValueError, match="hyper"):
        load_profile(raw, "wtp")


def test_duplicate_device_ids_are_rejected():
    raw = {
        **RAW,
        "wtp": {
            "devices": [{"id": "DUP", "equipment": "A", "signals": {}}, {"id": "DUP", "equipment": "B", "signals": {}}]
        },
    }
    with pytest.raises(ValueError, match="DUP"):
        load_profile(raw, "wtp")


def test_loading_twice_with_the_same_seed_gives_the_same_device_set():
    first = load_profile(RAW, "wtp", seed=7)
    second = load_profile(RAW, "wtp", seed=7)
    assert [d.id for d in first.devices] == [d.id for d in second.devices]
    assert [[s.name for s in d.signals] for d in first.devices] == [
        [s.name for s in d.signals] for d in second.devices
    ]
