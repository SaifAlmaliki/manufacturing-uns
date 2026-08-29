from uns_simulator.models import ISA95Hierarchy, ParameterType, expand_hierarchy_paths
from uns_simulator.simulator import UnifiedNamespaceSimulator
from uns_simulator import devices


class DummyClient:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.published = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False


def test_expand_nested_sites_areas_lines_cells():
    raw = {
        "enterprise": "CovestroAG",
        "sites": [
            {
                "name": "Dormagen",
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
                "name": "Krefeld",
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
    topics = [
        p.get_parameter_topic("G1", ParameterType.PROCESS_VALUE, "Temperature")
        for p in paths
    ]

    assert [ (p.enterprise, p.site, p.area, p.line, p.cell) for p in paths ] == [
        ("CovestroAG", "Dormagen", "Production", "Line1", "Cell1"),
        ("CovestroAG", "Dormagen", "Production", "Line1", "Cell2"),
        ("CovestroAG", "Dormagen", "Production", "Line2", "Cell1"),
        ("CovestroAG", "Krefeld", "Production", "Line1", "Cell1"),
    ]
    assert topics[0].startswith("CovestroAG/Dormagen/Production/Line1/Cell1/G1/")
    assert topics[-1].startswith("CovestroAG/Krefeld/Production/Line1/Cell1/G1/")


def test_expand_flat_hierarchy_still_works():
    paths = expand_hierarchy_paths({
        "enterprise": "CovestroAG",
        "site": "Dormagen",
        "area": "Production",
        "line": "Line1",
        "cell": "Cell1",
    })
    assert len(paths) == 1
    assert paths[0].site == "Dormagen"
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
    topics = {
        plc.hierarchy.get_parameter_topic(plc.equipment.name, ParameterType.PROCESS_VALUE, "x")
        for plc in plcs
    }
    assert any("Line1/Cell1/G1/" in t for t in topics)
    assert any("Line1/Cell2/FillingMachine/" in t for t in topics)
