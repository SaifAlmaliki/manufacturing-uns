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
