"""Access Groups: path coverage and the demo-subject constants.

Coverage is a prefix test with a slash boundary. Do not use LIKE: an underscore
in a segment would become a wildcard (same reason model.asset avoids LIKE).
"""

from __future__ import annotations

from uns_model.topic_path import SEPARATOR

DEMO_SUBJECTS: dict[str, str] = {
    "admin.user": "00000000-0000-4000-a000-000000000001",
    "engineer.user": "00000000-0000-4000-a000-000000000002",
    "operator.user": "00000000-0000-4000-a000-000000000003",
    "auditor.user": "00000000-0000-4000-a000-000000000004",
    "viewer.user": "00000000-0000-4000-a000-000000000005",
}

OPERATOR_AREA_SEGMENT = "Filtration"
VIEWER_AREA_SEGMENT = "Distribution"


def covers(asset_path: str, root_path: str) -> bool:
    if asset_path == root_path:
        return True
    prefix = root_path + SEPARATOR
    return asset_path.startswith(prefix)
