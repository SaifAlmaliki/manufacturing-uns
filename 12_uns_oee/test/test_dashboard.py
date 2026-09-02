"""What the OEE dashboard is not allowed to do.

Grafana fails quietly. A panel naming a datasource uid that provisioning never declared
renders "Datasource not found" in one panel and nothing anywhere else; a panel missing
`$__timeFilter` works perfectly until the table has a year in it. Both are found by a
person looking at a screen, which is the worst place to find them.
"""

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAFANA = REPO_ROOT / "08_uns_observability" / "grafana"
DASHBOARD_DIR = GRAFANA / "dashboards"
OEE_DASHBOARD = DASHBOARD_DIR / "oee.json"
DATASOURCES = GRAFANA / "provisioning" / "datasources" / "datasources.yaml.template"


def _panels(dashboard: dict) -> list[dict]:
    """Flattened, because a collapsed row nests its panels inside itself."""
    panels = []
    for panel in dashboard.get("panels", []):
        panels.append(panel)
        panels.extend(panel.get("panels", []))
    return panels


def _queries(panel: dict) -> list[str]:
    return [target["rawSql"] for target in panel.get("targets", []) if "rawSql" in target]


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(OEE_DASHBOARD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def declared_uids() -> set[str]:
    template = yaml.safe_load(DATASOURCES.read_text(encoding="utf-8"))
    return {source["uid"] for source in template["datasources"] if "uid" in source}


@pytest.mark.parametrize("path", sorted(DASHBOARD_DIR.glob("*.json")), ids=lambda path: path.name)
def test_every_dashboard_names_a_declared_datasource(path: Path, declared_uids: set[str]):
    """
    Applies to all three dashboards, not only the new one: two of them referenced uids
    that provisioning never declared, which is why the datasource template changed here.
    """
    body = json.loads(path.read_text(encoding="utf-8"))
    named = {
        panel["datasource"]["uid"]
        for panel in _panels(body)
        if isinstance(panel.get("datasource"), dict) and "uid" in panel["datasource"]
    }
    assert named <= declared_uids, f"{path.name} names undeclared datasource uid(s): {named - declared_uids}"


def test_no_panel_recomputes_oee_from_raw_samples(dashboard: dict):
    """
    The engine's numbers or nothing. A panel doing its own arithmetic over `uns_metrics`
    would be a second implementation of the formulas, free to disagree with the value
    already published to `<line>/KPI/ShiftOee`.
    """
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "uns_metrics" not in query, f"panel {panel.get('title')!r} reads uns_metrics"


def test_every_query_is_bounded_by_the_dashboard_time_range(dashboard: dict):
    """Without $__timeFilter a panel scans every shift ever computed."""
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "$__timeFilter" in query, f"panel {panel.get('title')!r} has an unbounded query"


def test_the_trend_is_plotted_against_shift_start(dashboard: dict):
    """
    Not `computed_at`: a restated August shift has to move where the shift was, not where
    the recomputation happened.
    """
    trend = next(panel for panel in _panels(dashboard) if panel["type"] == "timeseries")
    query = _queries(trend)[0]
    assert "$__timeFilter(shift_start)" in query
    assert "computed_at" not in query


def test_every_query_is_filtered_to_the_selected_asset(dashboard: dict):
    """A dashboard showing two lines' OEE on one axis is a dashboard showing neither."""
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "$asset" in query, f"panel {panel.get('title')!r} ignores the asset variable"


def test_the_asset_variable_lists_only_assets_oee_is_computed_for(dashboard: dict):
    variable = next(item for item in dashboard["templating"]["list"] if item["name"] == "asset")
    assert variable["type"] == "query"
    assert "model.oee_unit" in variable["query"]
    assert "is_active" in variable["query"]


def test_the_waterfall_walks_loading_time_down_to_valuable_time(dashboard: dict):
    """
    Spec section 15 asks for a waterfall from Loading Time through the three losses. Its
    four stages have to descend in that order, because a waterfall whose bars are not
    successive remainders is just four unrelated bars.
    """
    waterfall = next(panel for panel in _panels(dashboard) if panel["title"] == "Loss waterfall")
    query = _queries(waterfall)[0]
    positions = [
        query.index(stage) for stage in ("'Loading time'", "'Run time'", "'Net run time'", "'Valuable time'")
    ]
    assert positions == sorted(positions)
    # Each stage is the previous one less its loss, taken from the stored columns - not
    # recomputed, and not a fifth factor invented in SQL.
    assert "run_time_s * coalesce(performance, 0) * coalesce(quality, 0)" in query


def test_panel_ids_are_unique(dashboard: dict):
    """Duplicated ids make Grafana silently drop a panel on import."""
    ids = [panel["id"] for panel in _panels(dashboard)]
    assert len(ids) == len(set(ids))


def test_the_dashboard_is_identified_and_tagged(dashboard: dict):
    assert dashboard["uid"] == "uns-oee"
    assert dashboard["title"] == "OEE"
    assert "oee" in dashboard["tags"]
