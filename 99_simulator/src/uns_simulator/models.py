"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Data models for ISA-95 hierarchy and equipment definitions.
Defines the structure for MQTT topics and industrial equipment.
"""
from enum import Enum
from typing import Any


def _node_name(node: Any) -> str:
    if isinstance(node, str):
        return node
    if node is None:
        raise ValueError("Hierarchy node is missing a name")
    name = node.get("name") if hasattr(node, "get") else None
    if not name:
        raise ValueError(f"Hierarchy node is missing 'name': {node}")
    return str(name)


class ParameterType(Enum):
    """Types of industrial parameters following ISA-95 standards"""
    PROCESS_VALUE = "ProcessValue"    # Measured values from sensors
    SETPOINT = "Setpoint"             # Target values for control
    STATUS = "Status"                 # Equipment status information
    ALARM = "Alarm"                   # Alarm and warning conditions
    EVENT = "EVENT"                   # EVENT STATUS


class ISA95Hierarchy:
    """
    Implements ISA-95 hierarchical model for industrial systems.
    Creates structured MQTT topics like: Enterprise/Site/Area/Line/WorkCell/Equipment/ParameterType/ParameterName
    """

    def __init__(self, enterprise: str, site: str, area: str, line: str, cell: str):
        self.enterprise = enterprise
        self.site = site
        self.area = area
        self.line = line
        self.cell = cell

    def get_parameter_topic(self, equipment: str, param_type: ParameterType, param_name: str) -> str:
        """
        Generate ISA-95 compliant MQTT topic
        Example: ManufacturingCo/PlantA/Production/Line1/Cell1/MixerTank/ProcessValue/Temperature
        """
        return f"{self.enterprise}/{self.site}/{self.area}/{self.line}/{self.cell}/{equipment}/{param_type.value}/{param_name}"


def expand_hierarchy_paths(raw: Any) -> list[ISA95Hierarchy]:
    """
    Expand simulator.hierarchy into one ISA-95 path per cell.

    Nested shape:
      enterprise / sites[] / areas[] / lines[] / cells[]
    Legacy flat shape:
      enterprise, site, area, line, cell
    """
    if raw is None:
        raise ValueError("simulator.hierarchy is required")

    enterprise = raw.get("enterprise")
    if not enterprise:
        raise ValueError("simulator.hierarchy.enterprise is required")

    sites = raw.get("sites")
    if sites:
        paths: list[ISA95Hierarchy] = []
        for site in sites:
            site_name = _node_name(site)
            for area in site.get("areas") or []:
                area_name = _node_name(area)
                for line in area.get("lines") or []:
                    line_name = _node_name(line)
                    cells = line.get("cells") or []
                    if not cells:
                        raise ValueError(
                            f"Line {site_name}/{area_name}/{line_name} has no cells"
                        )
                    for cell in cells:
                        paths.append(
                            ISA95Hierarchy(
                                enterprise=str(enterprise),
                                site=site_name,
                                area=area_name,
                                line=line_name,
                                cell=_node_name(cell),
                            )
                        )
        if not paths:
            raise ValueError("simulator.hierarchy.sites did not produce any cells")
        return paths

    return [
        ISA95Hierarchy(
            enterprise=str(enterprise),
            site=str(raw.get("site")),
            area=str(raw.get("area")),
            line=str(raw.get("line")),
            cell=str(raw.get("cell")),
        )
    ]


class Equipment:
    """Represents industrial equipment with sensors and parameters"""

    def __init__(self, name: str, sensors: dict[str, Any]):
        self.name = name
        self.sensors = sensors  # sensor_name -> {base_value, variation, unit}
        self.operational = True
        self.performance = 1.0
