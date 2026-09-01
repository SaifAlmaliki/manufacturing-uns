import pytest

from uns_simulator.models import expand_hierarchy_paths
from uns_simulator.profiles import (
    FAMILIES,
    TIER_DEFAULTS,
    build_plant_context,
    filter_paths,
    load_profile,
    validate_line_overrides,
)

HIERARCHY = {
    "enterprise": "CovestroAG",
    "sites": [
        {
            "name": "Dormagen",
            "areas": [
                {
                    "name": "Production",
                    "kind": "production",
                    "lines": [{"name": "Line1", "nameplate_tph": 12.0, "cells": ["Cell1", "Cell2"]}],
                },
                {"name": "Utilities", "kind": "utilities", "lines": [{"name": "Powerhouse", "cells": ["Cell1"]}]},
            ],
        },
        {
            "name": "Krefeld",
            "areas": [
                {
                    "name": "Production",
                    "kind": "production",
                    "lines": [{"name": "Line1", "nameplate_tph": 5.0, "cells": ["Cell1"]}],
                }
            ],
        },
    ],
}

RAW = {
    "hierarchy": HIERARCHY,
    "plant": {
        "sites": {"Dormagen": {"ambient_mean_c": 12.0, "ambient_swing_c": 9.0, "tariff_peak_hours": [8, 20]}},
        "lines": {"Dormagen/Production/Line1": {"execute_s": 1800.0, "starting_s": 45.0, "hold_probability_per_hour": 3.0}},
    },
    "energy": {
        "devices": [
            {
                "id": "MAIN",
                "equipment": "MainIncomer",
                "target": {"kind": "utilities"},
                "tier": "energy",
                "serves": ["Dormagen/Production/Line1"],
                "signals": {
                    "ActivePower": {"shape": "ou_walk", "unit": "kW", "mean": 400.0, "sigma": 20.0, "tau": 120.0},
                    "EnergyTotal": {"shape": "counter", "unit": "kWh", "tier": "meter", "rate": "ActivePower / 3600.0"},
                },
            }
        ]
    },
    "water": {
        "devices": [
            {
                "id": "FEED",
                "equipment": "FeedwaterMeter",
                "tier": "meter",
                "signals": {"Flow": {"shape": "ou_walk", "unit": "m3/h", "mean": 20.0, "sigma": 2.0}},
            }
        ]
    },
    "profiles": {
        "full": {"tier_scale": 1.0, "sites": ["Dormagen", "Krefeld"], "families": list(FAMILIES)},
        "small": {"tier_scale": 6.0, "sites": ["Dormagen"], "families": ["energy"], "max_cells_per_line": 1},
    },
    "simulation": {"seed": 1234, "tiers": {"process": 4.0}},
}

ALL_PATHS = expand_hierarchy_paths(HIERARCHY)


def test_tier_defaults_cover_every_documented_tier():
    assert set(TIER_DEFAULTS) == {"fast", "process", "energy", "status", "meter", "lab", "event"}
    assert TIER_DEFAULTS["fast"] == 1.0
    assert TIER_DEFAULTS["meter"] == 900.0
    assert TIER_DEFAULTS["event"] == 0.0


def test_families_are_exactly_the_six_the_spec_names_in_its_order():
    assert FAMILIES == ("energy", "water", "utilities", "asset_health", "production", "safety")


def test_filter_paths_without_filters_keeps_everything():
    assert filter_paths(ALL_PATHS) == list(ALL_PATHS)


def test_filter_paths_keeps_only_the_named_sites():
    kept = filter_paths(ALL_PATHS, sites=["Dormagen"])
    assert {path.site for path in kept} == {"Dormagen"}


def test_filter_paths_caps_cells_per_line_in_declaration_order():
    kept = filter_paths(ALL_PATHS, max_cells_per_line=1)
    production = [path for path in kept if path.area == "Production" and path.site == "Dormagen"]
    assert [path.cell for path in production] == ["Cell1"]


def test_filter_paths_naming_a_site_that_does_not_exist_is_rejected():
    with pytest.raises(ValueError, match="Nowhere"):
        filter_paths(ALL_PATHS, sites=["Dormagen", "Nowhere"])


def test_build_plant_context_creates_a_line_state_per_production_line_only():
    """Spec 6.1: PackML belongs to production lines. A compressor house has no batch."""
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    assert set(context.sites) == {"Dormagen", "Krefeld"}
    assert set(context.sites["Dormagen"].lines) == {"Production/Line1"}
    assert set(context.sites["Krefeld"].lines) == {"Production/Line1"}


def test_line_timing_overrides_are_applied():
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    timing = context.sites["Dormagen"].lines["Production/Line1"].timing
    assert timing.execute_s == 1800.0
    assert timing.starting_s == 45.0
    assert timing.hold_probability_per_hour == 3.0


def test_a_line_override_keyed_on_a_line_that_does_not_exist_is_rejected():
    """A silently ignored timing override is how a line ends up running the defaults."""
    raw_plant = {"lines": {"Dormagen/Production/LineNine": {"execute_s": 10.0}}}
    with pytest.raises(ValueError, match="Dormagen/Production/LineNine"):
        validate_line_overrides(ALL_PATHS, raw_plant)


def test_a_line_override_for_a_site_this_profile_filters_out_is_still_legal():
    """`small` keeps Dormagen only, and plant.yaml still describes Krefeld's timing.

    Checking staleness against the profile's narrowed slice would make this a load failure,
    so plant.yaml could only describe the intersection of every profile.
    """
    raw = {
        **RAW,
        "plant": {
            **RAW["plant"],
            "lines": {**RAW["plant"]["lines"], "Krefeld/Production/Line1": {"execute_s": 900.0}},
        },
    }
    profile = load_profile(raw, "small")
    assert set(profile.context.sites) == {"Dormagen"}
    assert "Production/Line1" in profile.context.sites["Dormagen"].lines


def test_an_override_naming_a_utility_line_is_rejected():
    """Spec 6.1 gives utility lines no LineState, so timing for one cannot be honoured."""
    with pytest.raises(ValueError, match="Dormagen/Utilities/Powerhouse"):
        validate_line_overrides(ALL_PATHS, {"lines": {"Dormagen/Utilities/Powerhouse": {"execute_s": 10.0}}})


def test_line_nameplate_comes_from_the_hierarchy():
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    assert context.sites["Dormagen"].lines["Production/Line1"].nameplate_tph == 12.0
    assert context.sites["Krefeld"].lines["Production/Line1"].nameplate_tph == 5.0


def test_site_ambient_overrides_are_applied():
    context = build_plant_context(ALL_PATHS, RAW["plant"], seed=1234)
    site = context.sites["Dormagen"]
    for _ in range(0, 86_400, 600):
        site.tick(600.0)
    assert site.ambient_temp_c < 12.0  # the 9 K swing must take it below the 12 C mean


def test_full_profile_loads_every_enabled_family():
    profile = load_profile(RAW, "full")
    assert profile.name == "full"
    assert profile.seed == 1234
    assert {device.family for device in profile.devices} == {"energy", "water"}
    assert profile.sites == ("Dormagen", "Krefeld")


def test_small_profile_drops_families_not_in_its_list():
    profile = load_profile(RAW, "small")
    assert {device.family for device in profile.devices} == {"energy"}
    assert profile.families == {
        "energy": True,
        "water": False,
        "utilities": False,
        "asset_health": False,
        "production": False,
        "safety": False,
    }


def test_small_profile_drops_sites_not_in_its_list():
    profile = load_profile(RAW, "small")
    assert set(profile.context.sites) == {"Dormagen"}
    assert {device.path.site for device in profile.devices} == {"Dormagen"}


def test_small_profile_caps_cells_per_line():
    """max_cells_per_line: 1 is what keeps the `small` profile's volume down."""
    profile = load_profile(RAW, "small")
    assert all(device.path.cell == "Cell1" for device in profile.devices)


def test_tier_scale_multiplies_every_interval():
    small = load_profile(RAW, "small")
    assert small.tier_scale == 6.0
    assert small.tiers["fast"] == 6.0
    assert small.tiers["meter"] == 900.0 * 6.0
    # `event` means "on change", so scaling it must leave it at zero rather than make it slow.
    assert small.tiers["event"] == 0.0


def test_tier_scale_defaults_to_one():
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"families": list(FAMILIES)}}}
    profile = load_profile(raw, "full")
    assert profile.tier_scale == 1.0
    assert profile.tiers["fast"] == TIER_DEFAULTS["fast"]


def test_tier_overrides_come_from_simulation_tiers():
    profile = load_profile(RAW, "full")
    assert profile.tiers["process"] == 4.0
    assert profile.tiers["meter"] == TIER_DEFAULTS["meter"]


def test_explicit_seed_overrides_the_configured_one():
    assert load_profile(RAW, "full", seed=99).seed == 99


def test_report_counts_devices_signals_families_tiers_and_serves():
    report = load_profile(RAW, "full").report
    assert report.devices == 4
    assert report.signals == 5
    assert report.per_family == {"energy": 1, "water": 3}
    assert report.per_tier["meter"] == 4  # EnergyTotal plus one Flow per FEED device
    assert report.serves_links == 1
    assert report.as_dict()["devices"] == report.devices


def test_report_records_a_template_that_matched_nothing():
    raw = {**RAW, "energy": {"devices": [{"id": "GHOST", "equipment": "E", "target": {"site": "Nowhere"}, "signals": {}}]}}
    assert "GHOST" in " ".join(load_profile(raw, "full").report.unmatched_templates)


def test_serves_pointing_at_a_line_that_does_not_exist_is_a_load_error():
    """Spec 6.3 makes this fatal, not a warning: the utility would silently run unloaded."""
    raw = {
        **RAW,
        "utilities": {
            "devices": [
                {
                    "id": "CH",
                    "equipment": "Chiller",
                    "target": {"kind": "utilities"},
                    "serves": ["Dormagen/Production/LineZ"],
                    "signals": {},
                }
            ]
        },
    }
    with pytest.raises(ValueError, match="Dormagen/Production/LineZ"):
        load_profile(raw, "full")


def test_serves_naming_a_line_the_profile_filtered_out_is_a_load_error():
    """`small` keeps Dormagen only, so a serves entry into Krefeld must fail loudly."""
    raw = {
        **RAW,
        "energy": {
            "devices": [
                {
                    "id": "MAIN",
                    "equipment": "MainIncomer",
                    "target": {"kind": "utilities"},
                    "serves": ["Krefeld/Production/Line1"],
                    "signals": {},
                }
            ]
        },
    }
    load_profile(raw, "full")  # fine: Krefeld is in `full`
    with pytest.raises(ValueError, match="Krefeld/Production/Line1"):
        load_profile(raw, "small")


def test_unknown_profile_name_is_rejected_by_name():
    with pytest.raises(ValueError, match="tiny"):
        load_profile(RAW, "tiny")


def test_unknown_family_in_a_profile_is_rejected_by_name():
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"families": ["engery"]}}}
    with pytest.raises(ValueError, match="engery"):
        load_profile(raw, "full")


def test_a_families_mapping_instead_of_a_list_is_rejected():
    """The old shape was a mapping. Accepting both would let one profile contradict itself."""
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"families": {"energy": True}}}}
    with pytest.raises(ValueError, match="families"):
        load_profile(raw, "full")


def test_negative_tier_interval_is_rejected_by_name():
    raw = {**RAW, "simulation": {**RAW["simulation"], "tiers": {"process": -1.0}}}
    with pytest.raises(ValueError, match="process"):
        load_profile(raw, "full")


def test_unknown_tier_name_is_rejected_by_name():
    raw = {**RAW, "simulation": {**RAW["simulation"], "tiers": {"turbo": 1.0}}}
    with pytest.raises(ValueError, match="turbo"):
        load_profile(raw, "full")


def test_a_non_positive_tier_scale_is_rejected():
    raw = {**RAW, "profiles": {**RAW["profiles"], "full": {"tier_scale": 0.0, "families": list(FAMILIES)}}}
    with pytest.raises(ValueError, match="tier_scale"):
        load_profile(raw, "full")


def test_a_legacy_flat_interval_becomes_the_process_tier():
    """Spec 12: settings.yaml today has `simulation.interval: 5.0` and no `tiers` block."""
    raw = {**RAW, "simulation": {"seed": 1, "interval": 20.0}}
    profile = load_profile(raw, "full")
    assert profile.tiers["process"] == 20.0
    assert profile.tiers["fast"] == TIER_DEFAULTS["fast"]


def test_an_explicit_tiers_block_wins_over_the_legacy_interval():
    raw = {**RAW, "simulation": {"seed": 1, "interval": 20.0, "tiers": {"process": 3.0}}}
    assert load_profile(raw, "full").tiers["process"] == 3.0


def test_an_unknown_signal_tier_is_rejected_by_name():
    raw = {
        **RAW,
        "water": {"devices": [{"id": "F", "equipment": "M", "signals": {"Flow": {"unit": "m3/h", "tier": "hyper"}}}]},
    }
    with pytest.raises(ValueError, match="hyper"):
        load_profile(raw, "full")


def test_duplicate_device_ids_are_rejected():
    raw = {
        **RAW,
        "energy": {
            "devices": [{"id": "DUP", "equipment": "A", "signals": {}}, {"id": "DUP", "equipment": "B", "signals": {}}]
        },
    }
    with pytest.raises(ValueError, match="DUP"):
        load_profile(raw, "full")


def test_loading_twice_with_the_same_seed_gives_the_same_device_set():
    first = load_profile(RAW, "full", seed=7)
    second = load_profile(RAW, "full", seed=7)
    assert [d.id for d in first.devices] == [d.id for d in second.devices]
    assert [[s.name for s in d.signals] for d in first.devices] == [[s.name for s in d.signals] for d in second.devices]
