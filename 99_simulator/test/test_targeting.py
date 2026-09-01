import pytest

from uns_simulator import devices
from uns_simulator.models import ISA95Hierarchy, ParameterType, expand_hierarchy_paths
from uns_simulator.profiles import DeviceSpec, expand_template, matches_target
from uns_simulator.simulator import UnifiedNamespaceSimulator


class DummyClient:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.published = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

PRODUCTION = ISA95Hierarchy("CovestroAG", "Dormagen", "Production", "Line1", "Cell1", nameplate_tph=12.0)
PRODUCTION_2 = ISA95Hierarchy("CovestroAG", "Dormagen", "Production", "Line2", "Cell1", nameplate_tph=8.0)
UTILITY = ISA95Hierarchy("CovestroAG", "Dormagen", "Utilities", "Powerhouse", "Cell1", kind="utilities")
KREFELD = ISA95Hierarchy("CovestroAG", "Krefeld", "Production", "Line1", "Cell1", kind="production")
ALL_PATHS = [PRODUCTION, PRODUCTION_2, UTILITY, KREFELD]


def test_no_target_means_production_areas_only():
    assert matches_target(PRODUCTION, None) is True
    assert matches_target(UTILITY, None) is False


def test_kind_selector():
    assert matches_target(UTILITY, {"kind": "utilities"}) is True
    assert matches_target(PRODUCTION, {"kind": "utilities"}) is False


def test_every_present_key_must_match():
    assert matches_target(PRODUCTION, {"site": "Dormagen", "line": "Line1"}) is True
    assert matches_target(PRODUCTION, {"site": "Dormagen", "line": "Line2"}) is False


def test_absent_keys_are_wildcards():
    assert matches_target(PRODUCTION, {"site": "Dormagen"}) is True
    assert matches_target(PRODUCTION_2, {"site": "Dormagen"}) is True


def test_a_list_selector_matches_any_member():
    assert matches_target(PRODUCTION, {"line": ["Line1", "Line3"]}) is True
    assert matches_target(PRODUCTION_2, {"line": ["Line1", "Line3"]}) is False


def test_an_empty_target_matches_everything_including_utilities():
    assert matches_target(UTILITY, {}) is True
    assert matches_target(PRODUCTION, {}) is True


def test_unknown_selector_key_is_rejected_by_name():
    with pytest.raises(ValueError, match="celll"):
        matches_target(PRODUCTION, {"celll": "Cell1"})


def test_expand_template_creates_one_device_per_matching_path():
    devices = expand_template(
        {
            "id": "PWR",
            "equipment": "MainIncomer",
            "target": {"kind": "utilities"},
            "tier": "energy",
            "signals": {"ActivePower": {"shape": "ou_walk", "unit": "kW", "mean": 400.0, "sigma": 20.0, "tau": 120.0}},
        },
        ALL_PATHS,
        family="energy",
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.path is UTILITY
    assert device.family == "energy"
    assert device.tier == "energy"
    assert device.topic_prefix == "CovestroAG/Dormagen/Utilities/Powerhouse/Cell1/MainIncomer"


def test_device_ids_are_unique_and_carry_their_location():
    devices = expand_template(
        {"id": "FLOW", "equipment": "Flowmeter", "signals": {}},
        ALL_PATHS,
        family="water",
    )
    ids = [device.id for device in devices]
    assert len(ids) == len(set(ids))
    assert all("Dormagen" in i or "Krefeld" in i for i in ids)


def test_signal_tier_defaults_to_the_device_tier():
    devices = expand_template(
        {"id": "X", "equipment": "E", "tier": "meter", "signals": {"Total": {"shape": "counter", "unit": "m3"}}},
        [PRODUCTION],
        family="water",
    )
    assert devices[0].signals[0].tier == "meter"


def test_a_signal_may_override_the_device_tier():
    devices = expand_template(
        {
            "id": "X",
            "equipment": "E",
            "tier": "meter",
            "signals": {
                "Total": {"shape": "counter", "unit": "m3"},
                "Flow": {"shape": "ou_walk", "unit": "m3/h", "tier": "fast"},
            },
        },
        [PRODUCTION],
        family="water",
    )
    by_name = {spec.name: spec for spec in devices[0].signals}
    assert by_name["Total"].tier == "meter"
    assert by_name["Flow"].tier == "fast"


def test_signals_come_back_in_dependency_order():
    """Written the way spec 7.3 writes it: `rate` flat, naming a sibling signal."""
    devices = expand_template(
        {
            "id": "X",
            "equipment": "E",
            "signals": {
                "EnergyTotal": {"shape": "counter", "unit": "kWh", "rate": "ActivePower / 3600.0"},
                "ActivePower": {"shape": "ou_walk", "unit": "kW", "mean": 10.0},
            },
        },
        [PRODUCTION],
        family="energy",
    )
    assert [spec.name for spec in devices[0].signals] == ["ActivePower", "EnergyTotal"]


def test_serves_is_carried_onto_the_device():
    """Spec 6.3's `serves` entries are fully qualified Site/Area/Line paths."""
    devices = expand_template(
        {
            "id": "CH",
            "equipment": "Chiller",
            "target": {"kind": "utilities"},
            "serves": ["Dormagen/Production/Line1", "Dormagen/Production/Line2"],
            "signals": {},
        },
        ALL_PATHS,
        family="utilities",
    )
    assert devices[0].serves == ("Dormagen/Production/Line1", "Dormagen/Production/Line2")


def test_a_template_matching_nothing_returns_an_empty_list():
    assert expand_template({"id": "X", "equipment": "E", "target": {"site": "Nowhere"}, "signals": {}}, ALL_PATHS, "energy") == []


def test_a_template_without_an_id_or_equipment_is_rejected():
    with pytest.raises(ValueError, match="equipment"):
        expand_template({"id": "X", "signals": {}}, ALL_PATHS, "energy")
    with pytest.raises(ValueError, match="id"):
        expand_template({"equipment": "E", "signals": {}}, ALL_PATHS, "energy")


def test_a_cycle_inside_a_template_is_rejected_with_the_device_named():
    with pytest.raises(ValueError, match="BAD"):
        expand_template(
            {
                "id": "BAD",
                "equipment": "E",
                "signals": {
                    "a": {"shape": "derived", "unit": "1", "expr": "b"},
                    "b": {"shape": "derived", "unit": "1", "expr": "a"},
                },
            },
            [PRODUCTION],
            family="energy",
        )


def test_a_signal_without_a_unit_is_rejected_naming_the_signal():
    """Spec 11 and 14: `unit` is required, and this is the only place to catch its absence."""
    with pytest.raises(ValueError, match="Pressure"):
        expand_template(
            {"id": "X", "equipment": "E", "signals": {"Pressure": {"base_value": 4.0}}},
            [PRODUCTION],
            family="energy",
        )


def test_an_empty_unit_is_rejected_too():
    """`unit: ""` is the same omission with extra steps; dimensionless ratios use "1"."""
    with pytest.raises(ValueError, match="Ratio"):
        expand_template(
            {"id": "X", "equipment": "E", "signals": {"Ratio": {"shape": "constant", "unit": "", "value": 1.0}}},
            [PRODUCTION],
            family="energy",
        )
    expand_template(
        {"id": "X", "equipment": "E", "signals": {"Ratio": {"shape": "constant", "unit": "1", "value": 1.0}}},
        [PRODUCTION],
        family="energy",
    )


# The `simulator.plc` and `simulator.equipment.mixer_tank` blocks as conf/settings.yaml held
# them before Task 19 removed them, and the hierarchy they expanded against. Frozen history:
# nothing should ever edit these to make a test pass. `create_plc` is legacy and its output
# is what spec 12 promises stays identical for a deployment that still configures it.
LEGACY_HIERARCHY = {
    "enterprise": "CovestroAG",
    "sites": [
        {
            "name": "Dormagen",
            "areas": [
                {
                    "name": "Production",
                    "lines": [
                        {"name": "Line1", "cells": ["Cell1", "Cell2"]},
                        {"name": "Line2", "cells": ["Cell1"]},
                    ],
                }
            ],
        },
        {"name": "Krefeld", "areas": [{"name": "Production", "lines": [{"name": "Line1", "cells": ["Cell1"]}]}]},
    ],
}

LEGACY_PLC = [
    {
        "id": "001",
        "equipment": "G1",
        "sensors": {
            "Temperature": {"base_value": 75.0, "variation": 2.0, "unit": "°C"},
            "Pressure": {"base_value": 150.0, "variation": 5.0, "unit": "psi"},
        },
    },
    {"id": "002", "equipment": "FillingMachine", "sensors": {"FlowRate": {"base_value": 450.0, "variation": 20.0, "unit": "L/min"}}},
]

LEGACY_MIXER_TANK = {
    "name": "MixerTank",
    "sensors": {
        "Temperature": {"base_value": 75.0, "variation": 2.0, "unit": "°C"},
        "Pressure": {"base_value": 150.0, "variation": 5.0, "unit": "psi"},
    },
}

TODAYS_LEGACY_TOPIC_PREFIXES = {
    "CovestroAG/Dormagen/Production/Line1/Cell1/G1",
    "CovestroAG/Dormagen/Production/Line1/Cell2/G1",
    "CovestroAG/Dormagen/Production/Line2/Cell1/G1",
    "CovestroAG/Krefeld/Production/Line1/Cell1/G1",
    "CovestroAG/Dormagen/Production/Line1/Cell1/FillingMachine",
    "CovestroAG/Dormagen/Production/Line1/Cell2/FillingMachine",
    "CovestroAG/Dormagen/Production/Line2/Cell1/FillingMachine",
    "CovestroAG/Krefeld/Production/Line1/Cell1/FillingMachine",
}


def _legacy_simulator(plc_templates, equipment_fallback, plc_count=2):
    """A UnifiedNamespaceSimulator with only the attributes create_plc reads.

    `__new__` rather than `__init__` for the same reason test_hierarchy.py does it: `__init__`
    loads profiles, builds a PlantContext and constructs MQTT devices, none of which the
    legacy path touches.
    """
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sim.mqtt_config = {}
    sim.hierarchies = expand_hierarchy_paths(LEGACY_HIERARCHY)
    sim.plc_templates = plc_templates
    sim.equipment_fallback = equipment_fallback
    sim.simulation_config = {"plc_count": plc_count}
    return sim


def test_the_legacy_plc_config_still_produces_todays_eight_devices(monkeypatch):
    """Spec 11's regression guard: two templates times four production cells, same topics."""
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    plcs = _legacy_simulator(LEGACY_PLC, None).create_plc()

    assert len(plcs) == 8  # noqa: PLR2004
    prefixes = {
        plc.hierarchy.get_parameter_topic(plc.equipment.name, ParameterType.PROCESS_VALUE, "x").rsplit("/", 2)[0]
        for plc in plcs
    }
    assert prefixes == TODAYS_LEGACY_TOPIC_PREFIXES
    assert len({plc.plc_id for plc in plcs}) == 8, "device ids stay unique per cell"  # noqa: PLR2004


def test_the_mixer_tank_fallback_is_still_honoured_when_no_templates_resolve(monkeypatch):
    """Spec 12's second row. Also the branch that makes removing only `plc:` a mistake.

    Empty templates plus a fallback is `plc_count` MixerTanks per cell - eight here - which is
    why Task 19 removes `plc_count` and `equipment.mixer_tank` alongside `plc:` rather than
    leaving the shipped file one deletion away from publishing them.
    """
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    plcs = _legacy_simulator([], LEGACY_MIXER_TANK).create_plc()

    assert len(plcs) == 8  # noqa: PLR2004
    assert {plc.equipment.name for plc in plcs} == {"MixerTank"}


def test_no_legacy_devices_are_created_without_templates_or_a_fallback(monkeypatch):
    """What the shipped configuration now resolves to: nothing from the legacy path."""
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    assert _legacy_simulator([], None).create_plc() == []
