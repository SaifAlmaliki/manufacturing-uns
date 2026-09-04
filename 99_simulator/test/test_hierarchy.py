import pytest

from uns_simulator import devices
from uns_simulator.models import AREA_KINDS, ISA95Hierarchy, ParameterType, expand_hierarchy_paths
from uns_simulator.simulator import UnifiedNamespaceSimulator


class DummyClient:
    def __init__(self, *args, **kwargs):
        self.published = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_expand_nested_sites_areas_lines_cells():
    raw = {
        "enterprise": "Enterprise",
        "sites": [
            {
                "name": "North",
                "areas": [
                    {
                        "name": "Production",
                        "lines": [
                            {"name": "Line1", "cells": ["Cell1", {"name": "Cell2"}]},
                            {"name": "Line2", "cells": ["Cell1"]},
                        ],
                    }
                ],
            },
            {
                "name": "South",
                "areas": [
                    {
                        "name": "Production",
                        "lines": [{"name": "Line1", "cells": ["Cell1"]}],
                    }
                ],
            },
        ],
    }

    paths = expand_hierarchy_paths(raw)
    topics = [p.get_parameter_topic("Pump", ParameterType.PROCESS_VALUE, "Temperature") for p in paths]

    assert [(p.enterprise, p.site, p.area, p.line, p.cell) for p in paths] == [
        ("Enterprise", "North", "Production", "Line1", "Cell1"),
        ("Enterprise", "North", "Production", "Line1", "Cell2"),
        ("Enterprise", "North", "Production", "Line2", "Cell1"),
        ("Enterprise", "South", "Production", "Line1", "Cell1"),
    ]
    assert topics[0].startswith("Enterprise/North/Production/Line1/Cell1/Pump/")
    assert topics[-1].startswith("Enterprise/South/Production/Line1/Cell1/Pump/")


def test_expand_flat_hierarchy_still_works():
    paths = expand_hierarchy_paths(
        {
            "enterprise": "Enterprise",
            "site": "North",
            "area": "Production",
            "line": "Line1",
            "cell": "Cell1",
        }
    )
    assert len(paths) == 1
    assert paths[0].site == "North"
    assert paths[0].cell == "Cell1"


def test_create_plc_spawns_one_device_per_cell_and_template(monkeypatch):
    monkeypatch.setattr(devices.aiomqtt, "Client", DummyClient)
    sim = UnifiedNamespaceSimulator.__new__(UnifiedNamespaceSimulator)
    sim.mqtt_config = {}
    sim.hierarchies = [
        ISA95Hierarchy("E", "Dormagen", "Production", "Line1", "Cell1"),
        ISA95Hierarchy("E", "Dormagen", "Production", "Line1", "Cell2"),
    ]
    sim.plc_templates = [
        {"id": "001", "equipment": "G1", "sensors": {"Temperature": {"base_value": 1, "variation": 0, "unit": "C"}}},
        {"id": "002", "equipment": "FillingMachine", "sensors": {}},
    ]
    sim.equipment_fallback = None

    plcs = sim.create_plc()
    assert len(plcs) == 4
    topics = {plc.hierarchy.get_parameter_topic(plc.equipment.name, ParameterType.PROCESS_VALUE, "x") for plc in plcs}
    assert any("Line1/Cell1/G1/" in t for t in topics)
    assert any("Line1/Cell2/FillingMachine/" in t for t in topics)


def test_area_kind_and_nameplate_flow_through_expansion():
    paths = expand_hierarchy_paths(
        {
            "enterprise": "Enterprise",
            "sites": [
                {
                    "name": "North",
                    "areas": [
                        {
                            "name": "Production",
                            "kind": "production",
                            "lines": [{"name": "Line1", "nameplate_tph": 12.5, "cells": ["Cell1"]}],
                        },
                        {
                            "name": "Utilities",
                            "kind": "utilities",
                            "lines": [{"name": "LineU", "cells": ["Cell1"]}],
                        },
                    ],
                }
            ],
        }
    )
    by_area = {path.area: path for path in paths}
    assert by_area["Production"].kind == "production"
    assert by_area["Production"].nameplate_tph == 12.5
    assert by_area["Utilities"].kind == "utilities"
    assert by_area["Utilities"].nameplate_tph == 0.0


def test_kind_defaults_to_production_when_absent():
    paths = expand_hierarchy_paths(
        {
            "enterprise": "E",
            "sites": [{"name": "S", "areas": [{"name": "A", "lines": [{"name": "L", "cells": ["C"]}]}]}],
        }
    )
    assert paths[0].kind == "production"
    assert paths[0].nameplate_tph == 0.0


def test_an_unknown_area_kind_is_rejected_by_name():
    """A typo must not silently become a production area that legacy templates target."""
    with pytest.raises(ValueError, match="utilites"):
        expand_hierarchy_paths(
            {
                "enterprise": "E",
                "sites": [
                    {
                        "name": "S",
                        "areas": [{"name": "A", "kind": "utilites", "lines": [{"name": "L", "cells": ["C"]}]}],
                    }
                ],
            }
        )


def test_area_kinds_are_exactly_the_two_the_spec_names():
    assert AREA_KINDS == frozenset({"production", "utilities"})


def test_positional_construction_is_unchanged():
    """Existing call sites pass five positional args; they must keep working."""
    path = ISA95Hierarchy("E", "S", "A", "L", "C")
    assert path.kind == "production"
    assert path.nameplate_tph == 0.0
